# frp（Fast Reverse Proxy）集成调研报告

> T1.5 产出 | 日期：2026-06-23 | 状态：已完成

## 一、frp 概述

frp（Fast Reverse Proxy）是使用 Go 语言编写的开源内网穿透工具，采用客户端-服务器架构。它通过将内网服务注册到公网服务器上，使得外网能够访问内网中的服务。

### 1.1 核心架构

```
[公网客户端] → [frps（服务器端，公网 VPS）] → [frpc（客户端，本地）] → [本地服务]
```

- **frps（server）**：运行在具有公网 IP 的服务器上，负责监听公网端口并转发流量
- **frpc（client）**：运行在内网机器上，与 frps 建立长连接，将本地端口注册到 frps

### 1.2 通信模型

frpc 主动向 frps 发起 TCP 连接（控制连接），通过控制连接告知 frps 需要代理的端口映射。当外网客户端连接到 frps 上的代理端口时，frps 通过已建立的控制连接或新建的数据连接，将流量转发到 frpc，再由 frpc 转发到本地目标服务。

本项目的 frp 集成代码见 `core/tunnel/config.py`（配置文件生成器）和 `core/tunnel/client.py`（进程管理与状态监控）。

---

## 二、本项目集成方案

经过调研，决定采用 **子进程方式** 集成 frp，而非 CGO 嵌入或纯 Python 重写，原因如下：

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 子进程运行 frpc 二进制 | 隔离性好；frp 上游独立更新；无需关心 Go 依赖 | 用户需自行准备 frpc 二进制 | **采纳** |
| CGO 嵌入 | 单文件分发 | 构建复杂；交叉编译困难 | 放弃 |
| 纯 Python 重写 | 无外部依赖 | 工作量大；不稳定 | 放弃 |

### 2.1 子进程管理架构

`FrpClient` 类的生命周期管理（`core/tunnel/client.py`）：

1. **配置生成**：`FrpConfigGenerator.generate()` 从 `Config` 对象生成标准 `frpc.ini` 字符串
2. **写入文件**：`FrpConfigGenerator.write()` 将配置写入 `frpc.ini`
3. **启动进程**：`subprocess.Popen([frpc, "-c", frpc.ini])` 启动 frpc 二进制
4. **状态监控**：后台线程读取 frpc 的标准输出/错误，解析状态变化
5. **自动重连**：进程意外退出后，延迟 2 秒自动重启（指数退避预留）
6. **优雅停止**：`terminate()` → 等待 5 秒 → `kill()` 强杀

### 2.2 配置生成器设计

`FrpConfigGenerator` 类（`core/tunnel/config.py`）封装了 frpc.ini 的生成：

- **`[common]` 段**：服务器地址、端口、认证 Token、传输协议（KCP 可选）
- **映射段**：每个 `enabled_ports` 中的端口生成一个 `[name]` 段，包含 `type`（TCP/UDP）、`local_port`、`remote_port`
- **动态更新**：`update_mapping()` 方法允许运行时修改 `enabled_ports`，调用 `restart()` 后生效

```python
# 生成示例输出
[common]
server_addr = frp.example.com
server_port = 7000
token = your_token

[mc]
type = tcp
local_port = 25565
remote_port = 25565

[intro]
type = tcp
local_port = 8080
remote_port = 8080

[admin]
type = tcp
local_port = 8443
remote_port = 8443
```

---

## 三、frp 关键配置选项

| 配置项 | 说明 | 本项目用法 |
|--------|------|-----------|
| `server_addr` | frps 服务器地址（IP 或域名） | 从 `config.yaml.tunnel.server_addr` 读取 |
| `server_port` | frps 绑定端口（默认 7000） | 从 `config.yaml.tunnel.server_port` 读取 |
| `token` | 认证令牌 | 从 `config.yaml.tunnel.token` 读取 |
| `protocol` | 传输协议（tcp/kcp） | 用户在配置中选择 |
| `type` | 代理类型（tcp/udp） | 每个映射独立配置 |
| `local_port` | 本地服务端口 | 从映射配置读取 |
| `remote_port` | 公网映射端口 | 从映射配置读取 |

### 3.1 KCP 协议

当用户选择 UDP 或 Both 协议时，frpc 使用 KCP（基于 UDP 的可靠传输协议）而非 TCP 与控制连接通信。KCP 在弱网环境下表现更好，但会略微增加延迟。

本项目通过 `FrpConfigGenerator` 中的逻辑判断：
```python
if tunnel.protocol in ("udp", "both"):
    lines.append("protocol = kcp")
```

### 3.2 端口映射启用

`enabled_ports` 列表控制哪些映射实际生效。用户可在管理后台动态调整此列表，调用 `update_mapping()` 后重启 frpc 使变更生效。

---

## 四、frp 连接状态机

`FrpClient` 通过解析 frpc 的标准输出跟踪连接状态。状态转换如下：

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
            ┌──────────────┐                    ┌──────────┐
            │  disconnected │◄───────────────────│   error  │
            └──────┬───────┘                    └────▲─────┘
                   │                                  │
                   │  start()                          │  会话关闭 / 错误
                   ▼                                  │
            ┌──────────────┐                    ┌──────┴──────┐
            │  connecting  │───────────────────►│  connected  │
            └──────────────┘  "login to server  └─────────────┘
                               success" /
                              "start proxy
                               success"
```

状态通过 `_process_line()` 方法解析：

| frpc 输出关键词 | 状态变更 | 事件触发 |
|-----------------|---------|---------|
| `login to server success` | `connecting` → `connected` | `_connected_event.set()` |
| `start proxy success` | 维持 `connected` | `_connected_event.set()` |
| `session closed` | 任意 → `disconnected` | `_connected_event.clear()` |
| `error` 前缀或包含 ` error ` | 任意 → `error` | — |

状态查询 API（`get_status()`）返回的结构化信息包含：

```json
{
  "status": "connected",
  "server": "frp.example.com:7000",
  "uptime": "3天 7小时 15分钟",
  "activeTunnels": "3",
  "mappings": [
    {"name": "mc", "localPort": 25565, "remotePort": 25565, "protocol": "TCP", "status": "active"}
  ]
}
```

---

## 五、自动重连策略

### 5.1 基本重连

当 frpc 进程意外退出时，`_monitor_process()` 检测到 `proc.wait()` 返回（非正常停止），触发自动重连：

```python
if self.auto_restart:
    self.logger.info("Auto-restarting frpc in 2 s …")
    threading.Thread(target=self._auto_restart_worker, daemon=True).start()
```

重连工作线程在 2 秒延迟后调用 `start()` 重启 frpc。

### 5.2 指数退避（预留）

当前实现使用固定 2 秒延迟。将来可扩展为指数退避策略：

| 重试次数 | 延迟时间 |
|----------|---------|
| 第 1 次 | 2 秒 |
| 第 2 次 | 4 秒 |
| 第 3 次 | 8 秒 |
| 第 4 次 | 16 秒 |
| 第 5+ 次 | 30 秒（上限） |

### 5.3 防抖机制

- 通过 `_stop_event` 标志位防止已请求停止后触发重连
- 使用线程锁（`self._lock`）保证状态变更的原子性
- 后台监控线程设为 daemon 模式，避免阻止进程退出

---

## 六、从 frp 源码学习到的设计要点

### 6.1 配置管理

frp 的配置管理采用 `ini` 格式（v1.x）和 `toml` 格式（v2.x），本项目全线沿用 v1.x 的 `ini` 格式，因为 v2.x 尚未广泛普及，且 v1.x 的 ini 格式更简单，易于程序生成和用户理解。

### 6.2 控制连接保活

frp 客户端通过定期发送心跳包维持控制连接的活性。本项目的 `FrpClient` 不自己实现心跳检测——frpc 二进制内部已处理好。我们只需监控进程是否存活并解析其输出。

### 6.3 代理类型区分

frp 支持多种代理类型：`tcp`、`udp`、`http`、`https`、`stcp`、`xtcp`。本项目仅需前两种：

- **TCP**：MC 协议（Java 版）、Web 服务的 HTTP 流量
- **UDP**：预留用于基岩版 MC 服务端（Bedrock 默认使用 UDP 19132）

`stcp`（安全 TCP）和 `xtcp`（点对点穿透）对本项目需求不匹配，不予采用。

### 6.4 安全考虑

- frp 支持 TLS 加密控制连接，应在生产环境启用
- Token 认证防止未授权客户端连接
- 本项目将 Token 存储在 `config.yaml` 中，禁止在日志中输出 Token 值

### 6.5 进程退出处理

从 frp 源码观察到，frpc 在收到 SIGTERM 信号后会：
1. 关闭所有代理连接
2. 向 frps 发送注销请求
3. 清理资源后退出

本项目利用这一特性，先 `terminate()`（发送 SIGTERM），等待 5 秒，若仍未退出则 `kill()` 强杀。这保证了代理连接被正确关闭，不会在 frps 侧留下孤儿连接。

---

## 七、参考资源

- [frp 官方仓库](https://github.com/fatedier/frp)
- [frp 文档](https://gofrp.org/docs/)
- 本项目 `core/tunnel/config.py` — `FrpConfigGenerator` 配置生成器
- 本项目 `core/tunnel/client.py` — `FrpClient` 进程管理与状态监控
