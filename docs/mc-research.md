# Minecraft 服务端管理调研报告

> T1.6 产出 | 日期：2026-06-23 | 状态：已完成

## 一、MC 服务端核心选择

### 1.1 主流服务端对比

| 服务端 | 特点 | 适用场景 | 性能 |
|--------|------|---------|------|
| **PaperMC** | 高优化、支持插件（Bukkit/Spigot）、自动修复安全漏洞 | **推荐**，适合多数服务器 | 最高 |
| **Purpur** | 在 Paper 基础上增加更多可配置选项 | 需要微调服务器行为的场景 | 与 Paper 相当 |
| **Spigot** | 早期标准，Paper 的前身 | 兼容旧插件 | 低于 Paper |
| **Vanilla（原版）** | Mojang 官方服务端，无优化 | 测试、需要纯净体验 | 最差 |
| **CraftBukkit** | 已停止更新，由 Paper 代替 | 不再推荐 | 低 |
| **Forge** | Mod 加载器，Fabric 的前辈 | 大型 Mod 整合包 | 取决于 Mod |
| **Fabric** | 轻量 Mod 加载器，适合新版本 | 轻量 Mod 服 | 良好 |

本项目选择 **PaperMC**，因其：
- 性能最优（通过优化区块生成、实体 AI、红石计算等）
- 兼容 Bukkit 和 Spigot 插件生态
- 提供原生 API（Paper API）用于扩展
- 支持 Profiler 和 TPS 监控功能

### 1.2 Minecraft 版本与 Java 版本对应

| MC 版本 | 最低 Java 版本 | 推荐 Java 版本 |
|---------|---------------|---------------|
| 1.17.x | Java 16 | Java 17 |
| 1.18.x - 1.20.x | Java 17 | Java 17 或 Java 21 |
| 1.21+ | Java 21 | Java 21 |

本项目默认要求 **Java 17**，在 `core/mcserver/java.py` 中通过正则解析 `java --version` 输出进行版本校验。兼容 MC 1.18 至 1.20.x；若用户选择 1.21+，程序会提示升级至 Java 21。

---

## 二、服务端启动流程

完整的服务器启动流程在 `core/mcserver/adapter.py` 的 `MCServerAdapter` 类中实现。

### 2.1 启动步骤

```
1. 校验 eula.txt → 2. 定位 server.jar → 3. 构建 JVM 参数 → 4. 启动子进程 → 5. 等待就绪
```

### 2.2 JVM 参数构建

```python
jvm_parts = config.mc.jvm_args.split()
paper_jar = self._find_jar()  # 搜索 paper-*.jar / minecraft_server*.jar / server.jar
mc_cmd = [config.mc.java_path, *jvm_parts, "-jar", paper_jar, "nogui"]
```

典型参数示例：`-Xmx4G -Xms2G -XX:+UseG1GC -XX:MaxGCPauseMillis=200`

`nogui` 参数禁用 MC 的原生图形窗口，在服务器环境中必须添加。

### 2.3 server.properties 配置

首次启动时 MC 服务端会自动生成 `server.properties`，本项目通过 `server.properties` 中读取 RCON 配置（`enable-rcon`、`rcon.port`、`rcon.password`），见 `_load_rcon_config()` 方法。

### 2.4 EULA 确认

遵循 Mojang 的 Minecraft 最终用户许可协议（EULA）：
- 程序必须确保 `eula.txt` 存在且内容为 `eula=true`
- 本项目的 `core/mcserver/eula.py` 实现了读取/写入/提示逻辑
- 首次启动时通过 Web 配置向导引导用户确认

---

## 三、RCON 协议

### 3.1 协议概述

RCON（Remote Console）是 Minecraft 服务端内置的远程管理协议，允许授权客户端发送命令并接收响应。基于 TCP 协议，使用简单的请求-响应模式。

协议数据包格式：

| 偏移 | 长度 | 类型 | 说明 |
|------|------|------|------|
| 0 | 4 | int32 | 消息长度（后续所有字段的总长度） |
| 4 | 4 | int32 | 请求 ID（用于匹配请求和响应） |
| 8 | 4 | int32 | 消息类型 |
| 12 | 变长 | byte[] | 消息体（UTF-8 编码） |
| 末尾 | 2 | byte[2] | 空终止符（\0\0） |

消息类型：
- `3` — 登录请求（密码）
- `2` — 命令请求
- `0` — 响应

### 3.2 mcipc 库集成

本项目使用 `mcipc` 库（已在 `requirements.txt` 中）进行 RCON 通信：

```python
from mcipc.rcon import Client

with Client("127.0.0.1", 25575) as client:
    client.login("password")
    response = client.run("list")
```

mcipc 提供了：
- 上下文管理器（自动连接/关闭）
- 命令自动补全
- 响应解析

见 `core/mcserver/adapter.py` 中的 `_rcon_command()` 方法。

### 3.3 命令功能

通过 RCON 支持的 MC 命令：

| 命令 | 用途 | 本项目使用 |
|------|------|-----------|
| `list` | 获取在线玩家列表 | `core/mcserver/whitelist.py` |
| `whitelist add <name>` | 添加白名单 | 同上 |
| `whitelist remove <name>` | 移除白名单 | 同上 |
| `whitelist list` | 白名单列表 | 同上 |
| `tps` | 查看 TPS | `core/mcserver/status.py` |
| `stop` | 安全关闭服务器 | `MCServerAdapter.stop()` |
| `say <msg>` | 广播消息 | 关闭前通知玩家 |
| `kick <name>` | 踢出玩家 | 管理后台操作 |
| `ban <name>` | 封禁玩家 | 预留管理接口 |

---

## 四、Server List Ping 协议

### 4.1 协议概述

Server List Ping（SLP）是 Minecraft 用于在多人游戏列表显示服务器信息的协议。基于 TCP 且使用 VarInt 编码。

完整流程：
1. 客户端发送 Handshake 包（协议版本、服务器地址、端口、next_state=1）
2. 客户端发送 Request 包（0x00）
3. 服务端返回 JSON 响应（包含 MOTD、在线人数、版本信息等）
4. 客户端发送 Ping 包（时间戳）
5. 服务端返回相同的时间戳（计算延迟）

### 4.2 mcstatus 库集成

本项目使用 `mcstatus` 库进行 Server List Ping：

```python
from mcstatus import JavaServer

server = JavaServer("127.0.0.1", 25565)
status = server.status()

# status.players.online    — 在线人数
# status.players.max       — 最大人数
# status.motd              — 服务器 MOTD
# status.version.name      — 版本描述
```

见 `core/mcserver/status.py` 中的 `get_basic_status()` 方法。

### 4.3 MOTD 格式化

`mcstatus` 返回的 MOTD 对象可能包含格式化代码（§ 符号），通过 `_format_motd()` 方法转换为纯文本：

```python
if hasattr(motd, "parsed"):
    return str(motd.parsed)
if hasattr(motd, "to_plain"):
    return motd.to_plain()
```

---

## 五、TPS 监控

### 5.1 什么是 TPS

TPS（Ticks Per Second）是衡量 MC 服务器流畅度的核心指标：
- **20.0** — 理论最大值，表示服务器每秒钟处理 20 个游戏刻
- **15-19** — 轻微延迟，可接受
- **10-15** — 明显卡顿，需要优化
- **< 10** — 严重卡顿，影响游戏体验

### 5.2 采集方式

本项目通过 RCON 执行 `/tps` 命令获取 TPS 数据。PaperMC 的输出格式为：

```
Overall TPS: 20.0, Mean: 19.8, Max: 20.0, Min: 19.5
```

解析逻辑在 `_parse_tps()` 方法中：

```python
for line in output.splitlines():
    match = re.search(r"[\d.]+", line)
    if match:
        return float(match.group())
```

### 5.3 局限性

- `/tps` 命令仅存在于 PaperMC 及其衍生服务端，原版 Vanilla 不支持
- 返回的是近期的平均 TPS，而非实时值
- TPS 数据需通过 RCON 获取，依赖 RCON 连接正常

---

## 六、进程生命周期管理

### 6.1 启动

`MCServerAdapter` 将 PaperMC 进程委托给 `ProcessManager`（`core/procman/manager.py`）管理：

```python
self._process = ProcessManager(
    name="paper-mc",
    cmd=mc_cmd,
    logger=logger,
    auto_restart=config.mc.auto_restart,
    restart_max=config.mc.restart_max_retries,
)
```

### 6.2 优雅停止

停止策略体现了"最优雅优先"的设计：

```
1. RCON 广播 "Server is shutting down..." 通知玩家
2. RCON 发送 "stop" 命令（触发 MC 安全关闭流程：保存区块 → 踢出玩家 → 关闭）
3. 等待最多 10 秒
4. 若进程仍在运行，调用 ProcessManager.stop() → terminate() → 5 秒后 kill() 强杀
```

见 `core/mcserver/adapter.py` 的 `stop()` 方法。

### 6.3 自动重启

当 MC 服务端意外崩溃时：
1. `ProcessManager` 检测到进程退出
2. 检查 `auto_restart` 标志和重试次数上限
3. 若允许，自动重新启动
4. 每次重启间有短暂延迟并计入 `restart_max_retries`

---

## 七、测试与调试

### 7.1 单机测试方法

```bash
# 启动服务端（不经过本软件）
java -jar paper-1.20.4.jar nogui

# 测试 RCON 连接
python -c "from mcipc.rcon import Client; c=Client('127.0.0.1', 25575); c.login('password'); print(c.run('list'))"

# 测试 Server List Ping
python -c "from mcstatus import JavaServer; s=JavaServer('127.0.0.1', 25565); print(s.status().players.online)"
```

### 7.2 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| RCON 连接被拒绝 | `server.properties` 中 `enable-rcon=false` | 设为 `true` 并重启服务端 |
| `java` 命令找不到 | Java 未加入 PATH 或未安装 | 在 `config.yaml` 中设置绝对路径 |
| MC 服务端启动后闪退 | JVM 参数过大或 Java 版本不兼容 | 检查 `-Xmx` 值是否超过可用内存 |
| EULA 错误 | 未接受 Mojang EULA | 设置 `eula=true` 在 `eula.txt` 中 |

---

## 八、国内下载镜像（2026-07 更新）

### 8.1 可用镜像站

| 镜像 | 地址 | 状态 |
|------|------|------|
| **BMCLAPI2** | `bmclapi2.bangbang93.com` | ✅ 可用，流量压力大（MCBBS 关站后峰值突破 10Gbps） |
| **OpenBMCLAPI** | 分布式节点网络 | ✅ 社区节点分担，[Dashboard](https://bd.bangbang93.com/pages/dashboard) |
| **CERNET 高校镜像** | `mirrors.cernet.edu.cn/list/bmclapi` | ✅ 7所高校反向代理 |
| **MCBBS 镜像** | — | ❌ 已随 MCBBS 永久关闭 |

### 8.2 本项目镜像策略

| 资源类型 | 优先 | 回退 |
|---------|------|------|
| Mojang 原版 JAR | BMCLAPI2 镜像 | Mojang 官方 CDN |
| PaperMC JAR (v2 缓存) | BMCLAPI2 v2 缓存端点 | PaperMC 官方 CloudFlare CDN |
| PaperMC API (Fill v3) | 仅官方（镜像未适配 Fill v3） | — |

BMCLAPI2 由 @bangbang93 个人维护，爱发电支持：https://afdian.com/a/bangbang93。

---

## 九、ANSI/Jansi 与 stdout 管道（2026-07 新增）

### 9.1 问题

PaperMC 使用 Log4j2 + Jansi 进行终端彩色输出。当 stdout 重定向到管道（而非 TTY）时，
Jansi 可能仍输出 ANSI CSI 转义码（如 `\x1b[93m` = 黄色），这些二进制序列会：

1. 污染正则表达式匹配（`\w` 匹配数字 `9`、`3` 等，导致玩家名捕获为 `93mArchetto`）
2. 破坏日志解析器的行首锚点 `^`
3. 在前端显示为乱码

### 9.2 解决

- **源头抑制**：JVM 参数 `-Dlog4j.skipJansi=true`，从日志框架层面禁用颜色输出
- **防御层**：Python reader 线程行级 ANSI 剥离（`_ANSI_RE.sub("", text)`）
- **正则收紧**：`\w{2,16}` → `[a-zA-Z0-9_]{2,16}`（等效 `re.ASCII` 模式）

### 9.3 相关日志系统参数

| JVM 参数 | 作用 |
|---------|------|
| `-Dlog4j.skipJansi=true` | 禁用 Jansi 颜色（源头抑制 ANSI） |
| `-Dlog4j2.AsyncQueueFullPolicy=Discard` | 异步队列满时丢弃而非阻塞调用者（防管道堵塞级联到游戏主线程） |
| `-Dfile.encoding=UTF-8` | 文件 I/O 编码 |
| `-Dsun.stdout.encoding=UTF-8` | 控制台输出编码（JDK < 18） |

---

## 十、后台缓存架构（2026-07 新增）

### 10.1 问题

原始设计中，前端 API（`/api/mc/status`、`/api/mc/players` 等）直接调用 RCON 查询 MC 服务器。
RCON 每次查询需要 TCP 连接→登录→命令→响应（~100-500ms），多个前端轮询请求并发时导致
请求线程堆积，管理后台响应缓慢。

### 10.2 解决

`MCServerAdapter` 内部维护后台缓存线程（`_cache_poller`，daemon），每 3 秒执行一次
`_refresh_cache()`：

1. Server List Ping → 获取 MOTD、在线人数、版本
2. RCON `list` → 获取在线玩家列表
3. RCON `data get entity` → 获取玩家坐标/世界（节流 5s）
4. `get_console_buffer()` → 获取控制台最近 200 行

API 端点从 `_cache_status` / `_cache_players` / `_cache_console` 直接读取，
零延迟返回最后已知值。RCON 或 Ping 失败时保留上一次有效数据，不抛异常。

### 10.3 Reader 健康检查

缓存轮询器每次循环还调用 `_check_reader_health()`：检测 stdout reader 线程是否存活，
如已死亡则自动重启（`_start_reader()`），防止管道缓冲区填满导致级联阻塞。

---

## 十一、参考资源

- [PaperMC 官方文档](https://docs.papermc.io/)
- [Minecraft RCON 协议规范](https://wiki.vg/RCON)
- [Server List Ping 协议规范](https://wiki.vg/Server_List_Ping)
- [mcipc PyPI](https://pypi.org/project/mcipc/)
- [mcstatus PyPI](https://pypi.org/project/mcstatus/)
- 本项目 `core/mcserver/adapter.py` — `MCServerAdapter`
- 本项目 `core/mcserver/status.py` — `MCStatusCollector`
- 本项目 `core/procman/manager.py` — `ProcessManager`
