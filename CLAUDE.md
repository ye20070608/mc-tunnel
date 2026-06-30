# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 文档索引

> CLAUDE.md 是入口，详细内容在各专题文件中。

| 文档 | 用途 | 何时查阅 |
|------|------|---------|
| `Project.md` | 系统设计（架构、安全、API、配置、风险） | 了解系统全貌、做架构决策 |
| `Task.md` | 7阶段任务分解、依赖关系、工时 | 规划开发顺序、评估进度 |
| `coding.md` | 编码规范（Python/前端/安全/Git） | 编写任何代码前 |
| `README.md` | 项目简介、快速开始 | 项目概览 |
| `docs/DECISIONS.md` | 技术选型决策记录（T1.1 产出） | 了解技术栈选择原因 |
| `docs/user-guide.md` | 用户操作手册 | 用户指导 |
| `CHANGELOG.md` | 版本变更记录 | 发布时更新 |

---

## 项目身份

一体化 **MC 服务器穿透控制软件** — 本地运行，集 PaperMC 管理 + frp 内网穿透 + Web 介绍页 + 管理后台于一体。目标用户是缺乏公网 IP 的 MC 服主。

---

## 当前状态：阶段 1-6 完成，阶段 7 待完成（文档完善、打包发布）

**43 个 Python 源文件** 覆盖阶段 1-6 全部功能：

| 阶段 | 状态 | 内容 |
|------|------|------|
| 阶段 1 | ✅ 完成 | 项目骨架、配置系统、日志系统、技术调研文档 |
| 阶段 2 | ✅ 完成 | 进程管理器、MC 适配器、RCON 集成、白名单管理、本地 API |
| 阶段 3 | ✅ 完成 | frp 配置生成器、frp 进程管理、TCP 代理层（协议嗅探）、UDP 预留、连接统计 |
| 阶段 4 | ✅ 完成 | Flask 单端口 HTTP 服务器（8443）、状态 API、介绍页模板 |
| 阶段 5 | ✅ 完成 | JWT 认证、CSRF 防护、管理后台全功能（服务控制/白名单/日志/穿透配置/插件管理/审计） |
| 阶段 6 | ✅ 完成 | 整合测试、18 项安全加固、多版本共存重构、Bug 修复 |
| 阶段 7 | ○ 待完成 | 文档完善、打包发布、CI/CD |

当前焦点：阶段 7 文档与打包。

### 多版本共存（v2.0 核心特性）

PaperMC 服务端按版本隔离存储：`server/versions/{version}/`。`downloader.py` 的 `switch_version()` 切换版本时自动清理旧 Paper 配置（`paper-world-defaults.yml` 等），避免跨版本格式不兼容崩溃。`_find_jar()` 返回绝对路径，防止 Java cwd 与项目根不同导致路径双重嵌套。

### 首次运行行为

- 若 `config/config.yaml` 不存在，自动从 `config/defaults.yaml` 复制模板，打印提示后 **退出**（需用户编辑配置后重新运行）
- 首次运行时若管理员密码为空，自动设置默认密码 `admin/admin`（BCrypt 加密），登录后应修改
- 首次运行时交互式选择 PaperMC 版本（从 API 拉取列表），可用 `--version` 跳过

### 阶段 6 安全加固摘要

18 项安全修复已完成（详见 `CHANGELOG.md` Security 条目），关键模式：

- **路径穿越防护**：世界名 `validate_world_name()` 拒绝 `../`、`/`、`\`；日志导出 `is_symlink()` 跳过 + `resolve()` 验证
- **注入防护**：版本号正则 `^[\d.]+$` 校验后入 glob；玩家名限 1-16 字符字母数字下划线
- **原子写入**：所有配置/server.properties 写入使用 `tempfile.mkstemp` + `os.replace`
- **竞态修复**：frpc 启动前后端双重互斥锁；白名单写入全读写锁保护
- **编码修复**：JVM 加 `-Dsun.stdout.encoding=UTF-8`；frpc stderr 合并到 stdout 单管道

### ⚠️ 樱花穿透冲突警告

樱花官方启动器（`SakuraFrpService.exe`）如果正在运行，会占用隧道导致我们的 frpc 报「已在线」。**二选一**——要么用官方启动器，要么用我们的管理面板，不能同时。切换前先 `taskkill /F /IM SakuraFrpService.exe`，等 3-5 分钟再启动。

---

## 技术栈（已决策）

| 组件 | 技术 |
|------|------|
| 主语言 | Python 3.12 |
| Web 框架 | Flask 3.x（应用工厂模式 + Blueprint） |
| 前端 | Alpine.js + HTMX |
| 日志 | Loguru |
| 配置 | YAML（PyYAML） |
| 认证 | JWT（PyJWT）+ BCrypt ≥ 12 |
| MC 交互 | RCON（mcipc）+ Server List Ping（mcstatus） |
| 穿透 | frp 子进程 |
| 打包 | PyInstaller（--onefile） |
| 测试 | pytest + pytest-cov |

---

## 系统架构

```
[公网] → frp穿透 → TCP代理层(协议嗅探) → 本地服务
  ├─ 端口1: MC协议 (25565)   → 0xFE/VarInt识别 → PaperMC
  └─ 端口2: Web 服务 (8443)  → Flask 单端口（介绍页 + 管理后台 + API）
       ├─ /intro            → 公开介绍页（HTML 模板，无需鉴权）
       ├─ /dashboard        → 管理面板（JWT 鉴权 + CSRF）
       ├─ /login            → 登录页
       ├─ /setup            → 首次配置向导
       └─ /api/*            → REST API（公开/鉴权分流）
```

实际已简化为**单端口架构**（仅 8443），不再使用独立的 8080 介绍页端口。介绍页、管理后台、API 全部走同一个 Flask 应用，通过路由前缀区分。
首次启动自动生成自签名 SSL 证书（`config/certs/`），默认启用 HTTPS。

核心模块（详细设计见 `Project.md` §3）：

| 模块 | 职责 | 详细设计 |
|------|------|---------|
| 控制核心 | 子进程生命周期、配置热重载、日志聚合 | `Project.md` §3.1 |
| TCP 代理层 | 协议嗅探（0xFE/VarInt → MC；ASCII → 拒绝/302），非 MC 流量拦截 | `Project.md` §3.4 |
| 穿透客户端 | frp 子进程，frpc 不自动启动——由用户在管理面板手动控制 | `Project.md` §3.2 |
| Web 服务 | Flask 单端口 HTTPS（8443），介绍页 + 管理后台 + API 统一路由 | `Project.md` §3.3 |
| 鉴权体系 | BCrypt 多用户 + JWT + CSRF + 速率限制 + 操作审计 | `Project.md` §6 |

### 依赖注入模式

Flask 蓝图通过 `current_app` 访问核心服务，而非全局变量：

```
main.py 构造实例  →  web/server.py:create_admin_app()
    →  api/router.py:register_routes(app, mc_adapter, tunnel_manager, audit_logger, config_manager)
        →  存储为 app.mc_adapter / app.tunnel_manager / app.audit_logger / app.config_manager
            →  各蓝图视图通过 current_app.mc_adapter 等访问
```

添加新 API 端点时，遵循此模式：在 `register_routes` 中注入依赖，在蓝图中通过 `current_app.<attr>` 获取。

#### 添加新 API 端点的步骤

1. **创建 Blueprint**：在 `api/` 下新建 `xxx.py`，定义 `xxx_bp = Blueprint("xxx", __name__, url_prefix="/api/xxx")`
2. **编写端点**：导入 `jwt_required`（需要登录）和 `csrf_protect`（状态变更）。通过 `current_app.mc_adapter`（等）访问核心服务。
3. **注册 Blueprint**：在 `api/router.py` 的 `register_routes()` 中添加 `app.register_blueprint(xxx_bp)`
4. **测试覆盖**：在 `tests/test_web_api.py` 中添加对应的 `test_xxx_*` 函数

需要注入新依赖时：在 `main.py` 构造实例 → 传给 `run_server()` → 传给 `create_admin_app()` → 传给 `register_routes()` → 存储为 `app.<attr>`。

### frp 双模式

隧道模块同时支持两种 frp 服务商，由配置自动切换：

| 模式 | 识别条件 | 认证方式 | 配置生成差异 |
|------|---------|---------|------------|
| **标准 frp** | `tunnel.token` 非空，`tunnel.user` 为空 | `token` 认证 | `[common]` 写 `token =` |
| **樱花 Frp** | `tunnel.user` 非空 | `user` + `auth_pass` 双因子 | 强制 `sakura_mode = true`，每个代理写 `auth_pass`，`local_ip = 127.0.0.1` |

切换只需修改 `config.yaml` 中 `tunnel.user` / `tunnel.token` 字段，`FrpConfigGenerator.generate()` 自动检测并生成对应格式。



---

## 开发工作流

### 环境就绪

```bash
# 激活 Python 虚拟环境
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/macOS

# 安装依赖
pip install -r requirements.txt

# 运行（首次运行会创建 config/config.yaml 然后退出，编辑后重新运行）
venv\Scripts\python main.py              # Windows
venv/bin/python main.py                  # Linux/macOS
venv\Scripts\python main.py --version 1.21  # 跳过交互式版本选择

# 测试
pytest tests/ --cov                          # 全部测试 + 覆盖率
python tests/test_web_api.py                 # 集成测试（83 项 check，standalone 脚本 + mock 依赖）
pytest tests/test_web_api.py::test_login_success -v  # 运行单个测试

# 代码质量
ruff format --check .          # 格式化检查
ruff check .                   # Lint
mypy core/ api/                # 类型检查（核心模块）
bandit -r core/ api/ -ll       # 安全漏洞扫描
```

### 编码规范速查

所有代码编写前参考 `coding.md`，要点：

- **Python**：`ruff` 格式化 + lint；`mypy` 类型检查（核心模块必覆盖）；Flask 应用工厂模式 + Blueprint；`asyncio` 实现 TCP 代理
- **前端**：Alpine.js + HTMX；轮询 10 秒间隔；CSRF Token 从 `<meta name="csrf-token">` 读取
- **安全**：BCrypt cost ≥ 12；JWT 密钥 ≥ 256 bit；操作日志记录所有敏感操作；禁止日志泄露密码/Token；输入校验防 RCON 命令注入和目录穿越
- **Git**：`type: 简短中文描述`（`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `security`）；`main` 可发布；`feature/stage-N` 分支开发。末尾追加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- **🔴 每次修改代码后必须 commit**：每完成一个独立的代码改动（不管改了多少文件），立即执行 `git add -A && git commit -m "<type>: <描述>"`。目的是让每次改动都有独立的 git 记录，随时可以用 `git revert` 或 `git diff` 回溯。禁止攒一大批改动再统一 commit。

### 配置

`config/config.yaml` 五个顶层键（对应 `Config` dataclass）：`mc` / `web` / `admins` / `tunnel` / `world`。另外 `intro` 是可选的自定义段（用于介绍页的服务器名称、规则等文本），由 `_make_common_data()` 读取但不在 dataclass 中建模。详见 `Project.md` §5.1 和 `config/loader.py` 数据类定义。关键点：
- 首次运行自动从 `config/defaults.yaml` 复制模板，打印提示后退出
- 首次运行自动设置默认管理员 `admin/admin`（BCrypt），登录后应修改
- 启动前校验端口冲突 + Java 版本兼容性（JDK 17+）
- 内部 API 仅监听 `127.0.0.1`，管理 API 全部经鉴权中间件
- 支持通过 `ConfigManager` 运行时修改配置（如密码变更），所有写入使用 `tempfile.mkstemp` + `os.replace` 原子化
- `web.ssl_enabled` 默认 true，首次启动自动生成自签名证书到 `config/certs/`
- `world` 段驱动 `server.properties` 生成（通过 `core/mcserver/properties.py` 的 `ServerPropertiesGenerator`），含 gamemode/difficulty/pvp/online_mode/view_distance 等 15+ 字段
- `intro` 段（可选，不在 Config dataclass 中）：自定义介绍页内容（`server_name`、`slogan`、`description`、`rules`、`features`），由 `_make_common_data()` 读取并注入 Jinja2 模板的 `{{data.intro.*}}`

### API 约定

路由格式：`/api/<资源>/<动作>`。详见 `Project.md` §5.2。
- 管理 API 必须鉴权：页面请求（`Accept: text/html`）→ 302 重定向；API 请求（`Accept: application/json` 或 `/api/` 前缀）→ 401 JSON
- 公开 API（`/api/public/status`）无需鉴权，只读

### 项目目录结构

> ✓ = 已实现，○ = 待开发

```
MC服务器/
├── main.py                        # ✓ 入口引导（日志→配置→Java→JAR→EULA→就绪）
├── requirements.txt               # ✓ 18 个 Python 依赖
├── config/
│   ├── __init__.py
│   ├── loader.py                  # ✓ YAML 加载/校验/ConfigManager（含密码修改）
│   └── defaults.yaml              # ✓ 默认配置模板
├── logger/
│   └── __init__.py                # ✓ Loguru 初始化（控制台+文件轮转+审计日志分流）
├── core/
│   ├── mcserver/
│   │   ├── __init__.py
│   │   ├── adapter.py             # ✓ PaperMC 适配器（启动/RCON/白名单/日志/玩家管理/OP/坐标）
│   │   ├── status.py              # ✓ MC 状态采集（TPS/MOTD/在线人数/进程指标）
│   │   ├── whitelist.py           # ✓ RCON 白名单管理（WhitelistManager）
│   │   ├── worlds.py              # ✓ 世界管理（worlds/ 目录 + 三维度分组 + 迁移）
│   │   ├── properties.py          # ✓ server.properties 生成器（从 WorldConfig）
│   │   ├── plugins.py             # ✓ 插件管理（上传/删除/启用禁用 + zip 炸弹防护）
│   │   ├── downloader.py          # ✓ PaperMC 下载/版本切换/多版本共存（含 SHA256 校验）
│   │   ├── java.py                # ✓ Java 检测与版本校验（config 指定 → PATH 查找）
│   │   └── eula.py                # ✓ Mojang EULA 确认
│   ├── procman/
│   │   └── manager.py             # ✓ 通用进程管理器（启停/重启/崩溃自动重试/健康检查）
│   ├── tunnel/
│   │   ├── config.py              # ✓ frp 配置生成器（TOML 格式/热更新）
│   │   └── client.py              # ✓ frp 子进程管理（启停/状态/连接事件，精简版无自动重启）
│   ├── proxy/
│   │   ├── tcp.py                 # ✓ TCP 代理层（VarInt 解码/协议嗅探/302 重定向）
│   │   ├── udp.py                 # ○ UDP 预留骨架（二期 Bedrock 支持）
│   │   └── stats.py               # ✓ 连接数和流量统计（线程安全）
│   ├── audit/
│   │   └── logger.py              # ✓ 审计日志（JSON Lines/按操作者过滤/导出）
│   └── ssl.py                     # ✓ 自签名 SSL 证书自动生成（首次启动，RSA 2048 + X.509）
├── api/
│   ├── __init__.py
│   ├── router.py                  # ✓ 蓝图注册 + 依赖注入
│   ├── mc.py                      # ✓ MC 控制 API（启停/状态/玩家/踢人/OP/DEOP）
│   ├── tunnel.py                  # ✓ 穿透配置 API（状态/启停/映射更新）
│   ├── admin.py                   # ✓ 管理 API（登录/CSRF/密码修改/操作日志）
│   ├── public.py                  # ✓ 公开状态 API（无需鉴权）
│   ├── whitelist.py              # ✓ 白名单 API（CRUD/审计记录）
│   ├── logs_api.py               # ✓ 日志 API（查询/过滤/导出）
│   ├── server.py                 # ✓ 服务端管理 API（版本/世界/设置）
│   ├── plugins.py                # ✓ 插件管理 API（上传/删除/启用禁用）
│   └── middleware/
│       ├── auth.py               # ✓ JWT 认证中间件（Bearer/Cookie/302+401 分流）
│       └── csrf.py               # ✓ CSRF 防护中间件（HMAC/2h 过期/双模式校验）
├── web/
│   ├── server.py                  # ✓ Flask 单端口应用工厂（8443，/intro + /dashboard + /api）
│   ├── templates/
│   │   ├── intro.html             # ✓ 介绍页模板（服务器状态展示）
│   │   ├── login.html             # ✓ 登录页（JWT 认证流程）
│   │   ├── admin.html             # ✓ 管理面板（6 卡片+Tab 导航+模态框+Toast，含插件管理）
│   │   └── setup.html             # ✓ 5 步配置向导（MC/穿透/管理员/EULA 确认）
│   └── static/
│       ├── style.css              # ✓ 像素传奇设计系统（CSS 变量/Dark 主题）
│       └── app.js                 # ✓ 前端 JS（API 客户端/轮询器/CSRF/标签切换/服务器操作）
├── tests/
│   └── test_web_api.py            # ✓ 集成测试（83 项 check：认证/CSRF/API/白名单/日志/隧道/插件/边界，standalone 脚本 + mock 依赖）
├── docs/
│   ├── DECISIONS.md               # ✓ 技术选型（10 项决策）
│   ├── user-guide.md              # ✓ 用户手册（10 章/567 行）
│   ├── frp-research.md            # ✓ frp 调研笔记
│   ├── mc-research.md             # ✓ MC 服务端调研笔记
│   └── 前端设计/
│       ├── template.html          # ✓ 像素传奇设计参考原型
│       └── data.json              # ✓ 数据形状定义
└── scripts/
    ├── start.bat                  # ✓ Windows 启动（自动创建 venv + 安装依赖）
    └── start.sh                   # ✓ Linux/macOS 启动（同上）
```

### 运行时目录结构（`server/`）

多版本共存，`server/versions/{version}/` 隔离各版本的 JAR 和配置：

```
server/
├── versions/                      # 多版本隔离目录
│   ├── 1.21/
│   │   ├── paper-1.21-130.jar     # Mojang 原版 JAR（Paperclip 输入）
│   │   ├── paper-1.21-130(1).jar  # Paperclip 补丁产物（实际运行）
│   │   ├── eula.txt               # 每版本独立的 EULA
│   │   └── cache/                 # Mojang 编译缓存（Paperclip 产出）
│   └── 1.20.4/
│       └── ...
├── worlds/                        # 世界存档（按组分组）
│   └── <group_name>/
│       ├── world/                 # 主世界
│       ├── world_nether/          # 地狱
│       └── world_the_end/         # 末地
├── plugins/                       # PaperMC 插件
├── server.properties              # 当前生效的服务器配置
└── eula.txt                       # 当前版本的 EULA 副本
```

`downloader.py` 的 `_find_existing_jar()` 先查 `versions/{v}/`，再 fallback 到旧版平铺结构 `server/paper-*.jar`。`switch_version()` 切换版本时自动调用 `cleanup_paper_configs_on_switch()` 清除 `paper-world-defaults.yml`、`bukkit.yml`、`spigot.yml`、`commands.yml`、`help.yml` 等跨版本不兼容的配置文件。

### 启动脚本注意事项

`start.bat` 使用 `goto` 扁平化流程，核心逻辑：
- 先检测系统 Python（`where python`），不满足才用 `%LOCALAPPDATA%\...\Python\Launcher\py.exe`
- 检测 venv 是否有效（`python.exe` 存在 + 能 `import loguru`），**能用就绝不删除重建**
- `PYTHONUTF8=1` 解决 pip 在 GBK 系统上的解码报错
- 全部 ASCII 编码，避免 cmd.exe 解析 UTF-8 特殊字符报错
