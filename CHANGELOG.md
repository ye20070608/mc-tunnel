# Changelog

## [Unreleased]

### Added (2026-06-24)
- **玩家管理增强**：显示所在世界（🌍主世界/🔥地狱/🌑末地）、坐标、在线时长（adapter.py + app.js）
- **OP 管理员设置**：玩家列表每行绿色 OP 按钮，支持设置/撤销服务器管理员（api/mc.py deop 端点）
- **世界管理**：WorldManager — worlds/ 目录统一存储，三维度分组（主世界/地狱/末地），自动迁移旧世界
- **控制台过滤**：`_is_internal_line()` 屏蔽 RCON 连接/断开噪音（procman/manager.py）
- **中文乱码修复**：JVM 加 `-Dsun.stdout.encoding=UTF-8` 等参数强制 UTF-8 输出（adapter.py）

### Changed (2026-06-24)
- **tunnel/client.py 精简**：移除僵尸检测、自动重启、孤儿进程杀除等复杂逻辑，回退为简约启停+状态读取
- **frpc 输出合并**：`stderr=subprocess.STDOUT` 避免同一条消息 stdout+stderr 双份输出
- **前端启停锁**：`_frpcActionLock` 互斥变量防重复点击触发两次 API 请求（app.js）
- **隧道 API 原子化**：移除锁外的 `is_running()` 裸调用，防止多线程竞态（api/tunnel.py）

### Fixed (2026-06-24)
- 隧道状态前端误显示「活跃」：`get_status()` 改为检查 `_connected_event` 而非仅 `is_running()`
- `stop()` 报告成功但进程未死：增加进程死亡确认后才清除状态

### Known Issues
- 樱花官方启动器（`SakuraFrpService.exe`）与我们的 frpc **不能同时运行**——会互相抢占隧道导致「已在线」冲突

## [1.0.0-alpha] - 2026-06-23

### Stage 1 — 技术预研与框架搭建
- 技术选型决策记录（docs/DECISIONS.md）
- 项目骨架搭建，模块划分
- 配置系统：YAML 加载、校验、默认值填充（config/）
- 日志系统：Loguru 结构化日志，文件轮转（logger/）
- frp 集成调研报告（docs/frp-research.md）
- MC 服务端管理调研报告（docs/mc-research.md）
- 开发环境搭建（脚本、依赖管理）

### Stage 2 — 控制核心与 MC 管理
- 通用进程管理器：子进程启停、重启、健康检查、超时强杀（core/procman/manager.py）
- MC 服务端适配器：PaperMC 启动参数构建、EULA 处理、RCON 集成、自动重启（core/mcserver/adapter.py）
- MC 状态采集：通过 RCON + Server List Ping 获取在线人数、TPS、MOTD（core/mcserver/status.py）
- 白名单管理：RCON 命令封装 whitelist add/remove/list（core/mcserver/whitelist.py）
- PaperMC 自动下载：PaperMC API 集成、SHA256 校验（core/mcserver/downloader.py）
- Java 检测与版本校验（core/mcserver/java.py）
- EULA 确认处理（core/mcserver/eula.py）
- 本地 API 雏形：MC 启停/状态/玩家/白名单 API（api/）
- 入口主流程：日志→配置→Java 检测→下载 JAR→EULA 引导（main.py）

### Stage 3 — frp 穿透集成 + TCP 代理层
- frp 配置生成器：根据 config.yaml 动态生成 frpc.ini，支持多端口映射（core/tunnel/config.py）
- frp 进程管理：子进程启停、连接状态监控、自动重连、日志收集（core/tunnel/client.py）
- TCP 代理层：前置协议嗅探，0xFE/VarInt→透传 MC，ASCII→关闭连接（core/proxy/tcp.py）
- UDP 骨架：预留 UDP 数据报处理接口，一期仅记录日志（core/proxy/udp.py）
- 连接数/流量统计：代理层连接计数和流量追踪（core/proxy/stats.py）
- 端口映射管理 API：tunnel update 动态增删端口映射（api/tunnel.py）

### Stage 4 — Web 介绍页
- Flask 双端口 HTTP 服务器：8080 介绍页 + 8443 管理后台（web/server.py）
- 聚合状态 API：/api/public/status 公开只读接口（api/public.py）
- 介绍页模板：HTML 模板展示在线人数、MOTD、服务器规则（web/templates/intro.html）
- 前端静态资源：像素传奇设计系统 CSS、Alpine.js 交互（web/static/）

### Stage 5 — 管理后台
- 用户认证系统：BCrypt 密码验证、JWT 签发、多管理员支持（api/middleware/auth.py）
- 鉴权中间件：页面请求 302 / API 请求 401 分流（api/middleware/auth.py）
- CSRF 防护：Token 生成与校验中间件（api/middleware/csrf.py）
- 登录页面：登录表单、错误提示、频率限制（web/templates/login.html）
- 管理面板：服务控制（启停/重启）、在线玩家列表、踢人（web/templates/admin.html）
- 白名单管理 UI：添加/删除玩家、列表展示（web/templates/admin.html）
- 日志查看：服务器日志、操作日志、筛选与导出（api/logs_api.py）
- 穿透配置管理：端口映射 CRUD、连接状态展示（web/templates/admin.html）
- 操作日志记录：敏感操作写入日志，包含操作人/时间/IP/内容（core/audit/logger.py）
- 配置向导：分步引导首次配置 MC 版本、穿透参数、管理员账号（web/templates/setup.html）
- 前端 JS：Alpine.js + HTMX 交互，10 秒轮询状态刷新（web/static/app.js）
- 管理员 API：密码修改、操作日志查询（api/admin.py）

