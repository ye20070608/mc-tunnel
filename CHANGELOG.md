# Changelog

## [v1.1.0] - 2026-07-05

### Fixed (2026-07-05)
- **Reader 线程死锁（根因修复）**：`WhitelistManager._meta_lock` 非重入锁 → `RLock`。`record_last_online()` 获取锁后调用 `_read_meta()` 再次获取同一把锁导致死锁，reader 线程在玩家加入时永久阻塞，控制台冻结 + 看门狗误判 `is_alive()=True` 不重启（whitelist.py + manager.py）
- **Reader 线程 ANSI 转义码污染**：PaperMC stdout 输出 `\x1b[93m` 等颜色码，`\w{2,16}` 贪婪匹配前缀数字导致玩家名捕获为 `93mArchetto`。修复：JVM 源头 `-Dlog4j.skipJansi=true` + reader 行级 ANSI 剥离 + `_on_server_output` 正则收紧 `[a-zA-Z0-9_]` + `_parse_console_lines` ANSI 剥离（adapter.py + manager.py）
- **Reader 线程静默死亡**：`except ValueError` 太窄，回调中未受保护的异常穿透后 daemon 线程死亡 → stdout 管道缓冲区填满 → log4j2 队列堆积 → 游戏主线程阻塞。修复：`except Exception` + 外层 `while True` 兜底重启 + `_check_reader_health()` 看门狗 + JVM `AsyncQueueFullPolicy=Discard`（adapter.py + manager.py）
- **RCON 连接无超时**：`mcipc.rcon.Client` 增加 `timeout=3.0`，防止 RCON 挂起阻塞 API worker 线程（adapter.py）
- **JWT/secret_key 不持久化**：首次启动随机生成后写入 `config.yaml`，重启不丢 key，已有 JWT/CSRF token 不失效（web/server.py + config/loader.py）
- **RCON stop 竞态**：`stop()` 前先调 `request_stop()` 通知 procman，避免 RCON `/stop` 触发的退出被自动重启误判为崩溃（adapter.py + manager.py）
- **cheroot SSL 噪音抑制**：`_CherootLogHandler` 过滤自签名证书握手错误（`SSLEOFError`、`peer dropped TLS`），不再刷屏控制台（web/server.py）
- **Reader 重启竞态**：`restart()` 时 join 旧 reader 线程（3s 超时），避免新进程无 reader 导致管道堵死（manager.py）
- **Fill v3 API 适配**：PaperMC API v2 于 2026-07-01 关闭（410 Gone），迁移至 Fill v3，修复 URL 拼接空 endpoint 尾部斜杠导致 404（downloader.py）

### Added (2026-07-05)
- **BMCLAPI2 v2 缓存端点**：PaperMC JAR 下载优先命中 `bmclapi2.bangbang93.com/paper/api/v2/projects/paper/...`，绕过 Fill v3 镜像未适配的限制。Mojang 原版 JAR 也通过 BMCLAPI2 加速（downloader.py）
- **后台缓存轮询器**：`_cache_poller` 每 3s 通过 RCON + Server List Ping 采集状态/玩家/控制台，API 从缓存零延迟读取，不再阻塞前端请求（adapter.py）

### Changed (2026-07-05)
- **配置向导保存即建目录**：最后一步保存配置后立即 `mkdir` 世界目录，不等 PaperMC 首次启动（adapter.py）
- **BMCLAPI2 镜像清理**：移除无效的 Fill v3 镜像尝试和 fill-data URL 改写（downloader.py）
- **下载容错增强**：PaperMC API 优先跳过 SSL 验证（国内 CDN 证书链问题）→ 失败回退 Mojang 原版 JAR（BMCLAPI2 镜像加速）→ Mojang 预下载回到后台线程不阻塞启动（downloader.py）

---

## [v1.0.0] - 2026-06-30

### Added (2026-06-30)
- **版本管理重构**：多版本共存 (`server/versions/{v}/` 目录隔离)，Web UI 下载/切换版本
- **新建世界自定义种子**：前端弹窗输入种子，留空=随机
- **cheroot WSGI 服务器**：替换 Werkzeug dev server，解决长时间运行后管理后台无响应问题（线程池 + 连接超时 + 原生 SSL）
- **PyInstaller 打包**：`mc-tunnel.spec`，一键构建 `mc-tunnel.exe`（--onefile 模式）
- **README.md 重写**：反映实际项目状态（单端口 Flask 架构）
- **LICENSE**：MIT

### Changed (2026-06-30)
- **server_jar 相对路径**：config 存储相对路径，项目搬家不失效
- **get_installed_versions 去重**：同版本多 JAR（Paperclip 补丁产物）只显示一条
- **Mojang 缓存统一到 versions/**：真正文件存 `versions/{v}/`，`cache/` 仅 Paperclip 副本
- **EULA 同步**：`versions/{v}/eula.txt` 自动拷贝到 `server/eula.txt`
- **glob 模式兼容无 build 号**：同时匹配 `paper-{v}-{build}.jar` 和 `paper-{v}.jar`
- **编码规范更新**：提交格式简化为 `type: 描述`，移除 `[TaskID]` 前缀
- **RCON 连接超时**：`_rcon_command()` 增加 3 秒 socket timeout，防止 RCON 挂起阻塞 worker 线程
- **user-guide.md 重写**：修正端口、架构、功能描述

### Fixed (2026-06-30)
- **管理后台长时间运行后无响应**：Werkzeug dev server 线程耗尽 → 替换为 cheroot（线程池 `numthreads=8` + 连接超时 `timeout=30`）
- **RCON 查询无超时**：mcipc Client 增加 `timeout=3.0`，防止 socket 永久阻塞
- **版本切换 404**：`switch_version` glob 不匹配无 build 号 JAR 文件名
- **下载错误版本**：`_find_existing_jar` 回退找到其他版本 JAR 导致跳过下载
- **正则不匹配无 build 号**：`^paper-([\d.]+)-\d+\.jar$` → `^paper-([\d.]+)(?:-\d+)?\.jar$`
- **config.yaml 追踪敏感信息**：从 git 移除，`.gitignore` 生效

### Added (2026-06-25)
- **安全加固 — 18 项修复**：全面安全审计后修复（详见下方 Security 条目）
- **日志导出增强**：导出所有 `logs/` 文件为 ZIP 包（含 `.gz` 轮转文件、审计日志、隧道日志）
- **日志原始展示**：日志 Tab 显示原始控制台文本行（与 cmd 窗口一致），导出全量不截断
- **白名单最后在线**：`whitelist.py:record_last_online()` 记录玩家退出时间，锁保护原子写入

### Security (2026-06-25)
- **#1 世界名路径穿越**：`validate_world_name()` 拒绝 `../`、`/`、`\`（`worlds.py` + `api/server.py`）
- **#2 日志导出 symlink 穿越**：`is_symlink()` 跳过 + `resolve()` 验证在 `logs/` 内（`logs_api.py`）
- **#3 世界迁移跳过列表**：拒绝隐藏目录，要求 `level.dat` 确认是真实世界（`worlds.py`）
- **#4 glob 注入**：版本号正则 `^[\d.]+$` 校验后入 glob（`adapter.py` + `downloader.py`）
- **#5 SSL 全局回退**：删除 `_MOJANG_SSL_OK`，每次请求独立尝试验证（`downloader.py`）
- **#6 白名单 meta TOCTOU**：`record_last_online()` 移入 `WhitelistManager`，全读写锁保护（`whitelist.py` + `adapter.py`）
- **#7/8 配置原子写入**：`tempfile.mkstemp` + `os.replace` 防文件损坏（`loader.py` + `admin.py`）
- **#9/13/15 server.properties 原子写**：三处写入均原子化（`worlds.py` + `api/server.py`）
- **#10 Java 路径跨平台**：`%ProgramFiles%` / `%ProgramW6432%` 替代硬编码（`java.py`）
- **#11 玩家名输入校验**：kick/op/deop 端点添加 `_validate_player_name()`（`api/mc.py`）
- **#12 审计日志导出限制**：限制到 `logs/exports/` 目录（`audit/logger.py`）
- **#14 工作目录依赖**：启动时 `os.chdir(PROJECT_ROOT)`（`main.py`）
- **#16 Path 类型一致**：ConfigManager 统一存储 `Path` 对象（`loader.py`）

### Changed (2026-06-24)
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

