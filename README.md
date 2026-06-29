# MC 隧道控制器 (mc-tunnel)

一体化 **Minecraft 服务器穿透管理软件** — 本地运行，集 PaperMC 管理 + frp 内网穿透 + Web 管理后台于一体。

> 目标用户：没有公网 IP、想在自己电脑上开 MC 服务器的服主。

## 功能

- **MC 服务端管理** — 一键启停 PaperMC，在线玩家列表、踢人、OP 管理、白名单、控制台
- **多版本共存** — `server/versions/{version}/` 目录隔离，下载/切换版本互不影响
- **frp 内网穿透** — 支持标准 frp 和樱花 Frp，Web 面板控制启停
- **Web 管理后台** — 单端口 HTTPS（8443），JWT 认证 + CSRF 防护
- **服务器介绍页** — 公开状态展示，在线人数/MOTD 实时更新
- **世界管理** — 创建/删除/切换世界，自定义种子，三维度自动关联
- **插件管理** — 上传/删除/启用禁用 PaperMC 插件
- **操作审计** — 所有敏感操作记录到审计日志
- **Mojang 预下载** — 绕过 Java SSL 证书问题（中国大陆网络环境）

## 系统要求

| 组件 | 要求 |
|------|------|
| Python | 3.12+ |
| Java | JDK 17+（MC 1.18+）|
| frp 服务端 | 一台有公网 IP 的 VPS（可选，标准/樱花 frp）|
| 内存 | ≥ 8 GB |
| 操作系统 | Windows 10+ / Ubuntu 20.04+ / macOS |

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/yourname/mc-tunnel.git
cd mc-tunnel

# 2. 创建虚拟环境并安装依赖
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 3. 准备 frpc（可选，不需要穿透可跳过）
#    下载 frp 客户端，将 frpc.exe / frpc 放入 frp/ 目录

# 4. 首次启动（生成配置文件后退出，编辑配置再重新运行）
venv\Scripts\python main.py
# 编辑 config/config.yaml，填入穿透服务器信息

# 5. 正式启动
venv\Scripts\python main.py
# 指定版本: venv\Scripts\python main.py --version 1.21

# 6. 打开管理后台
# https://127.0.0.1:8443/dashboard
# 默认账号: admin / admin（登录后请修改）
```

## 端口说明

| 端口 | 用途 |
|------|------|
| 8443 | Web 管理后台 + 介绍页 + API（HTTPS，单端口） |
| 25565 | Minecraft 游戏端口（可选，通过 frp 穿透） |

## 配置

`config/config.yaml` 五个配置段：

| 配置段 | 作用 | 关键字段 |
|--------|------|---------|
| `mc` | MC 服务端 | `version`, `port`, `java_path`, `jvm_args`, `auto_restart` |
| `web` | Web 服务 | `admin_port`, `ssl_enabled`, `session_timeout` |
| `admins` | 管理员账号 | `username`, `password_hash`（BCrypt） |
| `tunnel` | 穿透配置 | `server_addr`, `token`/`user`, `mapping` |
| `world` | 世界配置 | `gamemode`, `difficulty`, `seed`, `view_distance` |

详细说明见 [Project.md](Project.md) §5。

## 目录结构

```
MC服务器/
├── main.py                    # 入口
├── config/                    # 配置系统
├── core/
│   ├── mcserver/              # PaperMC 适配器、下载器、世界管理
│   ├── tunnel/                # frp 配置生成、进程管理
│   ├── proxy/                 # TCP 代理层（协议嗅探）
│   ├── procman/               # 通用进程管理器
│   └── audit/                 # 审计日志
├── api/                       # REST API + 认证/CSRF 中间件
├── web/
│   ├── server.py              # Flask 应用工厂
│   ├── templates/             # Jinja2 模板
│   └── static/                # JS/CSS
├── tests/                     # 集成测试
├── docs/                      # 技术文档
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
| 认证 | JWT + BCrypt + CSRF |
| MC 交互 | RCON (mcipc) + Server List Ping (mcstatus) |
| 穿透 | frp 子进程 |
| 测试 | pytest |

## 开发

```bash
# 测试
pytest tests/ --cov                    # 全部测试 + 覆盖率
python tests/test_web_api.py           # 集成测试（83 项）

# 代码质量
ruff format --check .                  # 格式化检查
ruff check .                           # Lint
mypy core/ api/                        # 类型检查
bandit -r core/ api/ -ll              # 安全扫描
```

详细规范见 [coding.md](coding.md)，架构设计见 [Project.md](Project.md)。

## 安全

- 密码 BCrypt 加密（cost ≥ 12）
- JWT 认证 + CSRF 防护
- 所有配置写入原子化（`tempfile.mkstemp` + `os.replace`）
- 输入校验防路径穿越、RCON 注入、glob 注入
- 管理 API 仅监听 `127.0.0.1`
- 完整操作审计日志

## 文档

| 文档 | 内容 |
|------|------|
| [Project.md](Project.md) | 系统设计（架构、安全、API、风险） |
| [coding.md](coding.md) | 编码规范 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技术选型决策 |
| [docs/user-guide.md](docs/user-guide.md) | 用户手册 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

## License

MIT
