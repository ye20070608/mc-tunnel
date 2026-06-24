# 编码规范

> 项目：MC隧道控制器 (mc-tunnel) | 版本：v1.2 | 日期：2026-06-25
>
> Python + Flask 实现。本规范基于实际代码库制定。

---

## 一、通用规范

### 1.1 命名约定

| 范围 | 规则 | 示例 |
|------|------|------|
| 文件名 | 小写 + 下划线分隔 | `process_manager.py`、`tcp_proxy.py` |
| 目录名 | 小写单数形式 | `core/`、`api/`、`web/` |
| 模块名 | 小写 + 下划线 | `mc_server.py` |
| 配置键 | 小写 + 下划线 | `max_players`、`server_port` |
| API 路由 | `/api/<资源>/<动作>` | `/api/mc/start`、`/api/whitelist/add` |
| 测试文件 | `test_*.py` | `test_adapter.py`、`test_web_api.py` |

### 1.2 注释规范

- **公开接口必须注释**：所有导出的函数、类型、常量需写文档注释（Go: `// FuncName ...`，Python: docstring）
- **复杂逻辑必须注释**：协议解析、状态机、并发控制等需说明设计意图
- **TODO 格式**：`# TODO(T1.3): 支持YAML热重载`（关联任务编号）

### 1.3 错误处理

- 使用显式异常类型，禁止裸 `except:`；自定义异常继承自项目基类
- 错误发生点记录结构化日志，向上传递带上下文

### 1.4 配置管理

- 配置文件格式：YAML（`config.yaml`）
- 配置结构体必须定义 `Validate()` 方法，启动时校验必填字段和值域
- 支持默认值填充：未配置项使用 `config/defaults.yaml` 的默认值
- 端口冲突检测：启动前检查 `mc.port`、`web.admin_port`

---

## 二、Python 编码规范

### 2.1 语言版本与工具链

- Python 3.12+
- 格式化：`ruff format`（替代 black）
- Lint：`ruff check`（替代 flake8/isort）
- 类型检查：`mypy`（渐进式类型注解，核心模块必须覆盖）
- 依赖管理：`pip` + `requirements.txt`

### 2.2 项目结构约定

```
main.py                    # 入口
config/
  __init__.py
  loader.py                # YAML 加载、校验、默认值填充
  defaults.yaml            # 默认配置模板
logger/
  __init__.py              # Loguru 初始化
core/
  procman/
    __init__.py
    manager.py             # 进程管理器
  mcserver/
    adapter.py / status.py / whitelist.py
  tunnel/
    config.py / client.py
  proxy/
    tcp.py / udp.py / stats.py
  audit/
    logger.py
api/
  __init__.py / router.py / mc.py / tunnel.py / admin.py / public.py
  middleware/
    auth.py / csrf.py
web/
  server.py                # Flask 应用工厂（双端口）
  templates/               # Jinja2 模板
  static/                  # 静态资源
```

### 2.3 模块约定

- 使用 Flask 应用工厂模式（`create_app(config)`），避免全局 Flask 实例
- 蓝图（Blueprint）按资源分组：`mc_bp`、`tunnel_bp`、`admin_bp`、`public_bp`
- 中间件注册到 `app.before_request` / `app.after_request`

### 2.4 并发模型

- MC 服务端、frp 子进程使用 `asyncio.subprocess` 或 `subprocess.Popen` + 线程监控
- TCP 代理层使用 `asyncio` 实现，避免阻塞
- Flask 开发服务器仅限开发；生产使用 `waitress`（Windows）或 `gunicorn`（Linux）
- 共享状态使用 `threading.Lock` 保护

### 2.5 日志规范

```python
from loguru import logger

logger.info("mc server started", port=cfg["mc"]["port"], pid=pid)
logger.error("frp connection lost: {}", err)
```

- 使用 Loguru 结构化绑定：`logger.bind(module="proxy").info(...)`
- 生产环境默认 `INFO` 级别
- 禁止 `print()` 输出日志

### 2.6 测试规范

- 使用 `pytest` + `pytest-cov`
- 外部依赖（subprocess、RCON、frp）使用 `unittest.mock` 或 `pytest-mock`
- 覆盖率要求同 Go 方案：核心模块 ≥ 70%

```python
def test_mc_server_start(mock_popen):
    adapter = MCAdapter(valid_config)
    adapter.start()
    mock_popen.assert_called_once()
```

---

## 三、前端编码规范

### 3.1 技术栈

- **Alpine.js**：声明式交互（状态切换、表单提交、轮询）
- **HTMX**：页面局部加载（表格刷新、日志流、管理面板导航）
- **CSS**：无需框架，使用 CSS 变量 + Flexbox/Grid

### 3.2 目录结构

```
web/
  templates/
    intro.html               # 介绍页
    login.html               # 登录页
    admin.html               # 管理面板（Tab 导航含所有功能）
    setup.html               # 5 步配置向导
  static/
    app.js                   # 共享 JS 工具函数
    style.css                # 全局样式
```

### 3.3 HTML 规范

- 使用语义化标签（`<main>`、`<nav>`、`<section>`）
- 表单必须包含 CSRF Token 隐藏字段：`<input type="hidden" name="csrf_token" value="...">`
- 页面请求和 API 请求分离：页面 Accept `text/html`，API Accept `application/json`

### 3.4 JavaScript 规范

- 使用 `fetch()` 进行 API 调用，统一错误处理函数
- 轮询间隔默认 10 秒，避免频繁请求
- CSRF Token 从 `<meta name="csrf-token">` 读取，自动附加到所有 POST/PUT/DELETE 请求

```javascript
// 基础 API 调用封装
async function apiCall(url, method = 'GET', body = null) {
    const opts = { method, headers: { 'Accept': 'application/json' } };
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrf) opts.headers['X-CSRF-Token'] = csrf;
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/login'; return null; }
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
}
```

---

## 四、安全编码规范

### 4.1 密码与认证

- **密码存储**：BCrypt（cost ≥ 12），禁止明文、MD5、SHA1/256 直接哈希
- **密码验证**：使用常量时间比较函数，防时序攻击
- **JWT**：使用 HS256 签名，密钥长度 ≥ 256 bit，从配置文件读取
- **Token 过期**：默认 3600 秒，可配置

### 4.2 输入验证

- 所有外部输入（配置、API 参数、HTTP Header）必须校验
- MC 命令参数（白名单等）：白名单校验，防 RCON 命令注入
- 端口号：范围 1–65535 校验
- 文件路径：防目录穿越（`../` 检查）

### 4.3 敏感操作审计

- 以下操作必须记录操作日志（操作人、时间、来源 IP、操作内容）：
  - MC 启停、白名单修改、踢人
  - 管理密码修改
  - 穿透配置变更
  - 登录失败超过阈值

### 4.4 CSRF 防护

- 所有状态变更请求（POST/PUT/DELETE）需 CSRF Token
- Token 策略：SameSite Cookie，每次登录后重新签发
- API 请求（`Accept: application/json`）通过 Header 校验，页面请求通过表单隐藏字段校验

---

## 五、Git 工作流

### 5.1 分支策略

```
main                     # 可发布状态，仅通过 PR/MR 合并
feature/stage-1          # 阶段 1：框架搭建
feature/stage-2          # 阶段 2：控制核心
feature/stage-N          # 对应 Task.md 中的阶段
```

### 5.2 提交信息格式

```
[T1.3] feat(config): 支持YAML配置热重载
[T2.1] fix(procman): 修复子进程超时未正确杀死的问题
[T5.8] refactor(audit): 操作日志存储从文件改为SQLite
```

- 前缀：`[TaskID]`
- 类型：`feat` / `fix` / `refactor` / `docs` / `test` / `chore`
- 范围：涉及模块名
- 说明：中文或英文，描述清晰

### 5.3 代码审查要求

- 核心模块（`procman`、`proxy`、`auth`、`audit`）修改必须 Review
- 安全相关变更必须 Review
- 合并前 CI（lint + test）必须通过

---

## 六、打包与发布

### Python 路径

```bash
pyinstaller --onefile --name mc-tunnel main.py
```

- 安装包仅包含二进制 + `config/defaults.yaml` + `docs/user-guide.md`
- 首次启动时引导用户生成 `config.yaml`
- 自动下载 MC 服务端前强制 EULA 确认

---

## 七、CI/CD 检查项

`make lint` 或 CI 流水线应包含：

| 检查项 | Python |
|--------|:------:|
| 代码格式化 | `ruff format --check` |
| Lint | `ruff check` |
| 类型检查 | `mypy`（核心模块） |
| 安全隐患 | `bandit` |
| 单元测试 | `pytest --cov` |
| 构建验证 | `python -c "import main"` |
