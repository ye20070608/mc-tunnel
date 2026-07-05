# MC Tunnel Controller (mc-tunnel)

> An all-in-one **Minecraft server tunneling & management tool** — runs locally, integrates PaperMC management, frp tunneling, and a web admin panel. Built for MC server owners without a public IP.

[🇨🇳 跳转到中文部分 · Jump to Chinese section](#中文)

---

## Features

- **MC Server Control** — one-click start/stop PaperMC, player list, kick, OP, whitelist, console commands
- **Multi-Version Coexistence** — `server/versions/{version}/` isolation, download/switch versions independently
- **frp Tunneling** — 🟢 Sakura Frp (verified) | 🟡 self-hosted frp (not yet fully tested)
- **Web Admin Panel** — single-port HTTPS (8443), JWT auth + CSRF protection
- **Server Intro Page** — public status display, live player count & MOTD
- **World Management** — create/delete/switch worlds, custom seed, auto-dimension grouping
- **Plugin Management** — upload/delete/enable/disable PaperMC plugins
- **Audit Trail** — all sensitive operations logged
- **Security Hardening** — 18 fixes (path traversal, atomic writes, injection filtering, etc.)

## Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.12+ |
| Java | JDK 17+ (MC 1.18+) |
| RAM | ≥ 8 GB |
| OS | Windows 10+ / Ubuntu 20.04+ / macOS |
| Tunnel | 🟢 **Recommended: [Sakura Frp](https://www.natfrp.com/)** (free, no VPS needed) |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/ye20070608/mc-tunnel.git
cd mc-tunnel

# 2. Venv & dependencies
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 3. First run (generates config, then exits)
venv\Scripts\python main.py

# 4. Edit config/config.yaml (see Tunneling section below)

# 5. Launch
venv\Scripts\python main.py
# Specify version: venv\Scripts\python main.py --version 1.21

# 6. Open admin panel
# https://127.0.0.1:8443/dashboard
# Default login: admin / admin (change immediately after first login)
```

## Tunneling

### 🟢 Sakura Frp (Recommended)

Sakura Frp is the **only fully tested and verified** tunneling option. Free, no VPS required.

1. Sign up at [Sakura Frp](https://www.natfrp.com/)
2. Create a tunnel, get your **user ID** and **access key** (token)
3. Download frpc into the `frp/` directory
4. Edit `config/config.yaml`:

```yaml
tunnel:
  user: "your-sakura-user-id"
  auth_pass: "your-access-key"
  frpc_path: "frp/frpc.exe"      # Windows
  # frpc_path: "frp/frpc"        # Linux/macOS
  mapping:
    mc_server:
      local_port: 25565
      remote_port: 25565          # port assigned by Sakura
    mc_admin:
      local_port: 8443
      remote_port: 8443
```

5. After launch, click "Enable Tunnel" in the admin panel

> ⚠️ If `SakuraFrpService.exe` is running, our frpc will conflict (reports "already online"). Kill it first: `taskkill /F /IM SakuraFrpService.exe`, wait 3-5 minutes, then start.

### 🟡 Self-hosted frp (VPS)

```yaml
tunnel:
  server_addr: "your-vps-ip"
  server_port: 7000
  token: "your-token"
  frpc_path: "frp/frpc"
  mapping:
    mc_server:
      local_port: 25565
      remote_port: 25565
```

> 📝 Self-hosted mode **not yet fully tested** — prefer Sakura Frp.

## Ports

| Port | Purpose |
|------|---------|
| 8443 | Web admin + intro page + API (HTTPS, single port) |
| 25565 | Minecraft game port (via tunnel) |
| 25575 | RCON (127.0.0.1 only) |

## Configuration

`config/config.yaml` has five top-level sections:

| Section | Purpose | Key Fields |
|---------|---------|------------|
| `mc` | MC server | `version`, `port`, `java_path`, `jvm_args`, `auto_restart` |
| `web` | Web service | `admin_port`, `ssl_enabled`, `session_timeout` |
| `admins` | Admin accounts | `username`, `password_hash` (BCrypt) |
| `tunnel` | Tunneling | `user`/`token`, `mapping` |
| `world` | World settings | `gamemode`, `difficulty`, `seed`, `view_distance` |

See [Project.md](Project.md) §5 for details.

## Project Structure

```
mc-tunnel/
├── main.py                    # Entry point
├── config/                    # Config system (YAML load/validate/reload)
├── core/
│   ├── mcserver/              # PaperMC adapter, downloader, worlds, plugins
│   ├── tunnel/                # frp config & process manager
│   ├── proxy/                 # TCP proxy (protocol sniffing)
│   ├── procman/               # Generic process manager
│   └── audit/                 # Audit logging
├── api/                       # REST API + JWT/CSRF middleware
├── web/
│   ├── server.py              # Flask app factory + Cheroot WSGI
│   ├── templates/             # Jinja2 templates
│   └── static/                # JS / CSS
├── tests/                     # Integration tests
├── docs/                      # Documentation
└── scripts/                   # Launch scripts
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Web Framework | Flask 3.x (app factory + Blueprint) |
| Frontend | Alpine.js + HTMX |
| Logging | Loguru |
| Config | YAML |
| Auth | JWT + BCrypt (cost ≥ 12) + CSRF |
| MC Protocol | RCON (mcipc) + Server List Ping (mcstatus) |
| Tunneling | frp subprocess |
| WSGI | cheroot 11.x (thread pool + SSL + timeout) |
| Testing | pytest |
| Packaging | PyInstaller (--onefile) |

## Development

```bash
# Tests
pytest tests/ --cov                    # Full suite + coverage
python tests/test_web_api.py           # Integration tests (83 checks)

# Code quality
ruff format --check .                  # Format check
ruff check .                           # Lint
mypy core/ api/                        # Type check
bandit -r core/ api/ -ll              # Security scan
```

See [coding.md](coding.md) for conventions and [Project.md](Project.md) for architecture.

## Security

- BCrypt password hashing (cost ≥ 12)
- JWT authentication + CSRF protection
- Atomic config writes (`tempfile.mkstemp` + `os.replace`)
- Input validation against path traversal, RCON injection, glob injection
- Admin API bound to `127.0.0.1` only
- Full operation audit trail

## Documentation

| Document | Content |
|----------|---------|
| [Project.md](Project.md) | System design (architecture, security, API, risks) |
| [coding.md](coding.md) | Coding conventions |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Technical decision records |
| [docs/user-guide.md](docs/user-guide.md) | User manual (Chinese) |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## License

MIT

## Contact

- Author: ye20070608@126.com
- Issues & PRs welcome

---

<h1 id="中文">MC Tunnel Controller (mc-tunnel) · MC 隧道控制器</h1>

> 一体化 **Minecraft 服务器穿透管理工具** — 本地运行，集 PaperMC 管理 + 内网穿透 + Web 管理后台于一体。专为没有公网 IP 的 MC 服主打造。

[⬆ 回到英文部分 · Back to English](#)

---

## 功能

- **MC 服务器控制** — 一键启停 PaperMC、玩家列表、踢人、OP、白名单、控制台指令
- **多版本共存** — `server/versions/{版本号}/` 隔离存储，独立下载/切换
- **内网穿透** — 🟢 樱花 Frp（已验证）| 🟡 自建 frp（未充分测试）
- **Web 管理后台** — 单端口 HTTPS（8443）、JWT 鉴权 + CSRF 防护
- **公开介绍页** — 展示服务器状态、在线人数、MOTD
- **世界管理** — 创建/删除/切换世界，支持自定义种子，自动维度分组
- **插件管理** — 上传/删除/启用/禁用 PaperMC 插件
- **操作审计** — 所有敏感操作记录到审计日志
- **安全加固** — 18 项修复（路径穿越、原子写入、注入过滤等）

## 环境要求

| 组件 | 要求 |
|------|------|
| Python | 3.12+ |
| Java | JDK 17+（MC 1.18+） |
| 内存 | ≥ 8 GB |
| 系统 | Windows 10+ / Ubuntu 20.04+ / macOS |
| 穿透 | 🟢 **推荐：[樱花 Frp](https://www.natfrp.com/)**（免费，无需自建 VPS） |

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/ye20070608/mc-tunnel.git
cd mc-tunnel

# 2. 虚拟环境 & 安装依赖
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 3. 首次运行（自动生成 config/config.yaml 后退出）
venv\Scripts\python main.py

# 4. 编辑 config/config.yaml（见下方穿透配置）

# 5. 再次启动
venv\Scripts\python main.py
# 指定版本: venv\Scripts\python main.py --version 1.21

# 6. 打开管理后台
# https://127.0.0.1:8443/dashboard
# 默认账号: admin / admin（登录后请立即修改密码）
```

## 穿透配置

### 🟢 樱花 Frp（推荐）

樱花 Frp 是**唯一经过完整测试验证**的穿透方案。免费、无需自建 VPS。

1. 前往 [樱花 Frp](https://www.natfrp.com/) 注册账号
2. 创建隧道，获取**用户 ID**（`user`）和**访问密钥**（`token`）
3. 下载 frpc 放到 `frp/` 目录下
4. 编辑 `config/config.yaml`：

```yaml
tunnel:
  user: "你的樱花用户ID"
  auth_pass: "你的访问密钥"
  frpc_path: "frp/frpc.exe"      # Windows
  # frpc_path: "frp/frpc"        # Linux/macOS
  mapping:
    mc_server:
      local_port: 25565
      remote_port: 25565          # 樱花分配给你的端口
    mc_admin:
      local_port: 8443
      remote_port: 8443
```

5. 启动后在管理后台点击"启用穿透"

> ⚠️ 如果樱花官方启动器（`SakuraFrpService.exe`）正在运行，会和我们的 frpc 冲突（报「已在线」）。**二选一**，不能同时用。切换前先 `taskkill /F /IM SakuraFrpService.exe`，等 3-5 分钟再启动。

### 🟡 自建 frp（VPS）

```yaml
tunnel:
  server_addr: "你的VPS IP"
  server_port: 7000
  token: "你设置的token"
  frpc_path: "frp/frpc"
  mapping:
    mc_server:
      local_port: 25565
      remote_port: 25565
```

> 📝 自建 frp 模式**尚未充分测试**，建议优先使用樱花。

## 端口

| 端口 | 用途 |
|------|------|
| 8443 | Web 管理 + 介绍页 + API（HTTPS 单端口） |
| 25565 | Minecraft 游戏端口（穿透后对外） |
| 25575 | RCON 端口（仅 127.0.0.1） |

## 配置项说明

`config/config.yaml` 包含五个顶层段：

| 段 | 用途 | 关键字段 |
|---|------|---------|
| `mc` | MC 服务器 | `version`、`port`、`java_path`、`jvm_args`、`auto_restart` |
| `web` | Web 服务 | `admin_port`、`ssl_enabled`、`session_timeout` |
| `admins` | 管理员账户 | `username`、`password_hash`（BCrypt 加密） |
| `tunnel` | 内网穿透 | `user`/`token`、`mapping` |
| `world` | 世界设置 | `gamemode`、`difficulty`、`seed`、`view_distance` 等 |

详见 [Project.md](Project.md) §5

## 项目结构

```
mc-tunnel/
├── main.py                    # 入口
├── config/                    # 配置系统（YAML 加载/校验/热更新）
├── core/
│   ├── mcserver/              # PaperMC 适配器、下载器、世界管理、插件管理
│   ├── tunnel/                # frp 配置生成 & 进程管理
│   ├── proxy/                 # TCP 代理（协议嗅探）
│   ├── procman/               # 通用进程管理器
│   └── audit/                 # 审计日志
├── api/                       # REST API + JWT/CSRF 中间件
├── web/
│   ├── server.py              # Flask 应用工厂 + Cheroot WSGI
│   ├── templates/             # Jinja2 模板
│   └── static/                # JS / CSS
├── tests/                     # 集成测试
├── docs/                      # 文档
└── scripts/                   # 启动脚本
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 主语言 | Python 3.12 |
| Web 框架 | Flask 3.x（应用工厂 + Blueprint） |
| 前端 | Alpine.js + HTMX |
| 日志 | Loguru |
| 配置 | YAML |
| 认证 | JWT + BCrypt（cost ≥ 12）+ CSRF |
| MC 协议 | RCON（mcipc）+ Server List Ping（mcstatus） |
| 穿透 | frp 子进程 |
| WSGI | cheroot 11.x（线程池 + SSL + 超时） |
| 测试 | pytest |
| 打包 | PyInstaller（--onefile） |

## 开发

```bash
# 测试
pytest tests/ --cov                    # 全量 + 覆盖率
python tests/test_web_api.py           # 集成测试（83 项检查）

# 代码质量
ruff format --check .                  # 格式检查
ruff check .                           # Lint
mypy core/ api/                        # 类型检查
bandit -r core/ api/ -ll              # 安全扫描
```

编码规范见 [coding.md](coding.md)，架构设计见 [Project.md](Project.md)。

## 安全

- BCrypt 密码哈希（cost ≥ 12）
- JWT 认证 + CSRF 防护
- 原子配置写入（`tempfile.mkstemp` + `os.replace`）
- 路径穿越 + RCON 注入 + glob 注入防护
- 管理 API 仅监听 127.0.0.1
- 完整操作审计日志

## 文档

| 文档 | 内容 |
|------|------|
| [Project.md](Project.md) | 系统设计（架构、安全、API、风险） |
| [coding.md](coding.md) | 编码规范 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技术选型决策记录 |
| [docs/user-guide.md](docs/user-guide.md) | 用户手册（中文） |
| [CHANGELOG.md](CHANGELOG.md) | 版本记录 |

## License

MIT

## 联系方式

- 作者邮箱: ye20070608@126.com
- 欢迎提 Issue 和 Pull Request
