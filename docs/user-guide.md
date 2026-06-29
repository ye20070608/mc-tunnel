# MC隧道控制器 — 用户手册

> v2.0 | 2026-06-30

---

## 一、准备工作

| 项 | 要求 | 检查方式 |
|----|------|---------|
| Python | 3.12+ | `python --version` |
| Java | JDK 17+ | `java --version` |
| 内存 | ≥ 8 GB | 任务管理器 → 性能 |
| frp 服务器 | 公网 VPS 或樱花 Frp 账号（可选） | — |

---

## 二、安装与启动

### 2.1 安装依赖

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 2.2 首次启动

```bash
venv\Scripts\python main.py
```

- 首次运行自动创建 `config/config.yaml`（从 `config/defaults.yaml` 复制模板），打印提示后**退出**
- 编辑 `config/config.yaml`，至少配置 Java 路径和穿透信息
- 再次运行，交互式选择 PaperMC 版本（可用 `--version 1.21` 跳过）
- 默认管理员 `admin` / `admin`，**登录后请立即修改**

### 2.3 启动后

```
管理后台: https://127.0.0.1:8443/dashboard
介绍页:   https://127.0.0.1:8443/intro
```

> 首次启动自动生成自签名 SSL 证书，浏览器会提示不安全，点击"高级 → 继续访问"即可。

---

## 三、管理后台

登录后看到侧边栏 6 个导航项：

### 📊 总览
- 服务器状态卡片（版本、TPS、内存、在线玩家、运行时间）
- 启停/重启按钮
- frp 隧道连接状态

### 👥 玩家管理
- 在线玩家列表（名称、延迟、世界、坐标、在线时长）
- 踢出玩家
- 设置/撤销 OP

### 📋 白名单
- 添加/移除白名单玩家
- 重载白名单
- 待处理玩家（被白名单拒绝的连接）

### 🖥 服务端管理
- **版本管理** — 查看已安装版本、下载新版本、切换活跃版本
- **世界管理** — 新建/删除/切换世界，新建时可自定义种子
- **插件管理** — 上传/删除/启用禁用 PaperMC 插件
- **server.properties** — 在线模式开关、游戏模式、难度等

### 📜 日志
- 控制台日志实时查看
- 操作审计日志
- 日志导出为 ZIP

### 🌐 穿透配置
- frp 隧道启停
- 端口映射修改

---

## 四、版本管理

系统支持多版本共存，JAR 文件存储在 `server/versions/{版本号}/` 下。

### 下载新版本
1. 管理后台 → 🖥 服务端管理 → 点击 **⬇ 下载新版本**
2. 从 PaperMC 版本列表中选择
3. 等待下载完成（约 50 MB，取决于网络速度）

### 切换版本
1. 在已安装版本列表中点击 **切换到此版本**
2. 需要重启服务器生效

### 版本目录结构
```
server/versions/
  1.20.1/
    paper-1.20.1.jar          # PaperMC JAR
    mojang_1.20.1.jar          # 原版 Mojang JAR（Paperclip 引导用）
    eula.txt
  1.21.11/
    paper-1.21.11-69.jar
    mojang_1.21.11.jar
    eula.txt
```

> 删除某版本目录即彻底清理该版本。

---

## 五、世界管理

### 新建世界
1. 管理后台 → 🖥 服务端管理 → 世界管理 → **+ 新建世界**
2. 输入世界名称（字母数字下划线）
3. 可选填写种子（留空=随机）
4. 创建后切换到新世界，重启服务器生效

### 切换世界
- 在世界列表中点击 **切换** → 自动更新 `server.properties` 的 `level-name`
- 需要重启服务器

### 删除世界
- 点击 **删除** → 确认后不可撤销

---

## 六、内网穿透

支持两种模式，由 `config/config.yaml` 自动切换：

| 模式 | 配置条件 | 认证方式 |
|------|---------|---------|
| 标准 frp | `tunnel.token` 非空、`tunnel.user` 为空 | token |
| 樱花 Frp | `tunnel.user` 非空 | user + auth_pass |

---

### 方式 A：樱花 Frp（推荐，免费节点可用）

无需自建 VPS，注册账号即可使用。

#### A.1 注册与获取信息

1. 打开 https://www.natfrp.com/ ，注册账号并登录
2. 左侧菜单 → **访问密钥** → 新建或复制已有密钥（一串字母数字）
3. 左侧菜单 → **隧道列表** → 获取节点地址，如 `frp-way.com:8088`

#### A.2 创建隧道

1. 点击 **创建隧道**
2. 为 MC 游戏端口和 Web 管理后台分别创建：

| 隧道 | 类型 | 本地端口 | 远程端口 |
|------|------|---------|---------|
| MC 游戏 | TCP | 25565 | 自动分配 |
| Web 管理 | TCP | 8443 | 自动分配 |

3. 记下创建隧道时设置的 **认证密码**（每个隧道一个，用于 `auth_pass`）

#### A.3 配置 config.yaml

```yaml
tunnel:
  server_addr: "frp-way.com"        # 樱花节点地址
  server_port: 8088                  # 樱花节点端口
  user: "你的访问密钥"                # 樱花用户 ID = 访问密钥
  sakura_mode: true
  enabled_ports: ["mc_server", "mc_admin"]
  mapping:
    mc_server:
      local_port: 25565
      remote_port: 0                 # 0 = 自动分配
      auth_pass: "隧道认证密码"
    mc_admin:
      local_port: 8443
      remote_port: 0
      auth_pass: "隧道认证密码"
```

#### A.4 获取 frpc

1. 樱花管理面板 → 左侧 **软件下载**
2. 下载 Windows 版 frpc（`frpc_windows_amd64.exe`）
3. 放入项目的 `frp/` 目录

#### A.5 启动穿透

管理后台 → 🌐 穿透配置 → 点击 **启动**。

> ⚠️ 如果电脑上安装了樱花官方启动器（`SakuraFrpService.exe`），必须先关闭：`taskkill /F /IM SakuraFrpService.exe`，等 3-5 分钟后再启动我们的 frpc。两者不能同时运行。

#### A.6 玩家连接地址

樱花管理面板 → 隧道列表 → 查看隧道的 **公网地址**，如 `cn-zz.example.com:12345`。玩家在 MC 客户端输入这个地址即可连接。

---

### 方式 B：自建 VPS（标准 frp）

需要一台有公网 IP 的 VPS。

#### B.1 在 VPS 上安装 frps

```bash
# SSH 登录 VPS
cd /opt
wget https://github.com/fatedier/frp/releases/download/v0.58.1/frp_0.58.1_linux_amd64.tar.gz
tar -xzf frp_0.58.1_linux_amd64.tar.gz
mv frp_0.58.1_linux_amd64 frp
cd frp
```

创建 `frps.toml`：
```toml
bindPort = 7000
auth.token = "你自定义的长token字符串"
```

启动并设为开机自启：
```bash
cat > /etc/systemd/system/frps.service << 'EOF'
[Unit]
Description=frp server
After=network.target
[Service]
Type=simple
ExecStart=/opt/frp/frps -c /opt/frp/frps.toml
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl start frps && systemctl enable frps
```

VPS 防火墙放行端口：`7000`（frp 控制）、业务端口（根据需要）。

#### B.2 获取 frpc

从 https://github.com/fatedier/frp/releases 下载对应系统的 frp 包，将 `frpc.exe`（Windows）或 `frpc`（Linux）放入项目的 `frp/` 目录。

#### B.3 配置 config.yaml

```yaml
tunnel:
  server_addr: "你的VPS公网IP"
  server_port: 7000
  token: "你自定义的长token字符串"
  user: ""                          # 留空 = 标准模式
  enabled_ports: ["mc_server", "mc_admin"]
  mapping:
    mc_server:
      local_port: 25565
      remote_port: 25565
    mc_admin:
      local_port: 8443
      remote_port: 8443
```

#### B.4 启动穿透

管理后台 → 🌐 穿透配置 → 点击 **启动**。

---

### 启停与状态

管理后台 🌐 穿透配置页面可查看连接状态、启停隧道。frpc 不随软件自动启动，需手动控制。

---

## 七、插件管理

1. 管理后台 → 🖥 服务端管理 → 插件管理
2. 点击 **📦 上传插件** 选择 `.jar` 文件
3. 上传后自动启用，可点击切换启用/禁用
4. 支持删除插件

> 插件存储在 `server/plugins/`，所有版本共享。

---

## 八、常见问题

### Q: 启动闪退
- 不要双击，先开命令提示符 `cd` 到项目目录再运行
- 检查 Python 版本：`python --version`

### Q: Java not found
- 检查 Java 安装：`java --version`
- 或编辑 `config/config.yaml`，手动指定 `java_path`：
  ```yaml
  mc:
    java_path: "C:\\Program Files\\Eclipse Adoptium\\jdk-17.0.9.9-hotspot\\bin\\java.exe"
  ```

### Q: 端口被占用
```bash
netstat -ano | findstr "8443"
```
修改 `config/config.yaml` 中 `web.admin_port` 的值。

### Q: frp 隧道断开
1. 检查 VPS 上 frps 运行状态
2. 检查防火墙端口放行
3. 确认 `token`/`user` 配置正确
4. 查看 `logs/mc-tunnel.log`

### Q: 玩家连不上
1. 本地测试：MC 客户端连接 `127.0.0.1:25565`
2. 本地能上 → 穿透问题；本地不能上 → MC 服务端未启动
3. 检查白名单设置

### Q: 忘记管理员密码
1. 关闭软件
2. 删除 `config/config.yaml`（下次启动会重新生成）
3. 或用 `admin`/`admin` 登录（若密码哈希为空则自动重置）

### Q: Paperclip 启动报 SSL/PKIX 错误
系统已预下载 Mojang 原版 JAR 到版本目录，正常情况下不会出现此问题。若仍出现，手动运行：
```bash
venv\Scripts\python -c "from core.mcserver.downloader import _ensure_mojang_jar; _ensure_mojang_jar('1.21', 'server')"
```

### Q: 如何彻底卸载
删除整个项目文件夹即可，无注册表残留。

---

## 九、安全建议

1. **改默认密码** — 首次登录后立刻修改
2. **管理后台不对外穿透** — 在 `enabled_ports` 中去掉 `mc_admin`，管理后台仅本地访问
3. **强 Token** — frp 认证信息使用强随机字符串
4. **定期备份** — 复制 `server/worlds/` 和 `config/config.yaml` 到安全位置
5. **检查审计日志** — 定期查看操作日志，确认无异常
