# MC隧道控制器 (mc-tunnel)

一体化Minecraft服务器穿透控制软件 —— 集MC服务端管理、内网穿透、Web介绍页和管理后台于一体。

## 系统要求

| 组件 | 要求 | 说明 |
|------|------|------|
| **Python** | 3.12 或更高 | 控制核心运行环境 |
| **Java** | JDK 17 或更高 | 运行 PaperMC 服务端（MC 1.18+） |
| **frp 服务器** | 一台有公网 IP 的 VPS | 运行 frps，用于内网穿透 |
| **内存** | 至少 8 GB 空闲 | 分配给 MC 服务端和系统 |
| **操作系统** | Windows 10+ / Ubuntu 20.04+ / macOS | 跨平台支持 |

## 端口说明

| 端口 | 用途 | 说明 |
|------|------|------|
| **25565** | Minecraft 游戏端口 | Java 版 MC 协议连接 |
| **8080** | 服务器介绍页 | 公开状态展示（HTML） |
| **8443** | 管理后台 | 需要登录鉴权的管理界面 |

## 配置快速参考

主要配置存放在 `config/config.yaml`，包含五个顶层键：

| 配置段 | 作用 | 关键字段 |
|--------|------|---------|
| `mc` | MC 服务端配置 | `version`, `port`, `java_path`, `jvm_args`, `auto_restart` |
| `web` | Web 服务配置 | `intro_port`, `admin_port`, `session_timeout`, `csrf_enabled` |
| `admins` | 管理员账号 | `username`, `password_hash`（BCrypt） |
| `tunnel` | 内网穿透配置 | `server_addr`, `server_port`, `token`, `mapping`, `enabled_ports` |

详细配置说明见 [Project.md](Project.md) 第 5 节。

## 技术栈

| 组件 | 技术 |
|------|------|
| 控制核心 | Python 3.12 + Flask |
| MC服务端 | PaperMC (Java 17) |
| 穿透客户端 | frp（子进程） |
| Web前端 | Alpine.js + HTMX |
| 日志 | Loguru |
| 配置 | YAML |
| 打包 | PyInstaller |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制并编辑配置
cp config/defaults.yaml config/config.yaml
nano config/config.yaml

# 启动
python main.py
```

## 项目结构

参见 [Task.md](Task.md) 第五节。

## 文档

- [项目设计方案](Project.md) — 完整设计文档
- [开发任务计划](Task.md) — 任务分解与里程碑
- [技术决策](docs/DECISIONS.md) — 技术选型记录
- [frp调研](docs/frp-research.md) — frp集成分析
- [MC调研](docs/mc-research.md) — MC服务端管理分析
