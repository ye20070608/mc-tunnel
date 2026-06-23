# 技术选型决策记录

> T1.1 产出 | 日期：2026-06-22 | 状态：已确认

## 决策清单

| # | 决策项 | 选项 | 选择 | 理由 |
|---|--------|------|------|------|
| 1 | 主语言 | Go vs **Python** | **Python 3.12** | 团队熟悉度高；已有 venv 和 requirements.txt；Flask + Jinja2 与前端设计系统天然匹配；开发速度快，适合 v1 快速交付 |
| 2 | Web 框架 | Flask / FastAPI | **Flask 3.x** | Jinja2 模板引擎直接渲染 `{{data.xxx}}` 前端模板；生态成熟；适合服务端渲染 + 少量 JS |
| 3 | 前端方案 | Vue.js SPA / **Alpine.js+HTMX** | **Alpine.js+HTMX** | 一期轻量；与 CSS-only 设计系统互补；渐进增强 |
| 4 | 日志库 | **Loguru** / structlog | **Loguru** | 零配置结构化日志；requirements.txt 已包含 |
| 5 | 配置格式 | **YAML** / TOML | **YAML** | 用户可读性最佳；PyYAML 成熟 |
| 6 | 认证方案 | Session Cookie / **JWT** | **JWT** | 无状态，适合单机部署；PyJWT 已在依赖中 |
| 7 | frp 集成 | **子进程** / C 嵌入 | **子进程** | 隔离性好，最稳定 |
| 8 | MC 交互协议 | **RCON** / stdin | **RCON** | 标准协议，mcipc 包已在依赖中 |
| 9 | 打包 | **PyInstaller** | **PyInstaller** | Go 可编译单文件，但 Python + PyInstaller 也能做到；开发速度优先 |
| 10 | Java 版本 | Java 17 vs 21 | **Java 17** | 兼容 MC 1.18+，用户安装率高 |

## 技术栈确认

```
Python 3.12 + Flask 3.x + Loguru + PyYAML + PyJWT + bcrypt
前端: Alpine.js + HTMX + 像素传奇设计系统 (CSS-only routing)
打包: PyInstaller (--onefile)
```

## 架构说明

- **控制核心**: Python 单进程，通过 `subprocess` 管理 PaperMC + frp 子进程
- **Web 服务**: Flask 双端口（8080 介绍页 / 8443 管理后台），使用应用工厂模式
- **TCP 代理**: `asyncio` 实现协议嗅探代理层
- **鉴权**: JWT + BCrypt + CSRF Token
