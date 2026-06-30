# MC Tunnel Controller (mc-tunnel)

An all-in-one **Minecraft server tunneling & management tool** — runs locally, integrates PaperMC management, frp tunneling, and a web admin panel.

> Built for MC server owners without a public IP — run a server right from your home PC.

## Features

- **MC Server Control** — one-click start/stop PaperMC, player list, kick, OP, whitelist, console
- **Multi-Version Coexistence** — `server/versions/{version}/` isolation, download/switch versions independently
- **frp Tunneling** — supports standard frp and Sakura Frp, web panel toggle on/off
- **Web Admin Panel** — single-port HTTPS (8443), JWT auth + CSRF protection
- **Server Intro Page** — public status display, live player count & MOTD
- **World Management** — create/delete/switch worlds, custom seed, auto-dimension grouping
- **Plugin Management** — upload/delete/enable/disable PaperMC plugins
- **Audit Trail** — all sensitive operations logged
- **Mojang Pre-download** — bypasses Java SSL certificate issues (for mainland China networks)

## Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.12+ |
| Java | JDK 17+ (MC 1.18+) |
| frp server | A VPS with public IP (optional; standard frp or Sakura Frp) |
| RAM | ≥ 8 GB |
| OS | Windows 10+ / Ubuntu 20.04+ / macOS |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/yourname/mc-tunnel.git
cd mc-tunnel

# 2. Create venv & install dependencies
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 3. Prepare frpc (optional, skip if not using tunneling)
#    Download frp client, place frpc.exe / frpc into the frp/ directory

# 4. First run (generates config file then exits; edit & re-run)
venv\Scripts\python main.py
# Edit config/config.yaml with your settings

# 5. Launch
venv\Scripts\python main.py
# Specify version: venv\Scripts\python main.py --version 1.21

# 6. Open admin panel
# https://127.0.0.1:8443/dashboard
# Default login: admin / admin (change immediately after first login)
```

## Ports

| Port | Purpose |
|------|---------|
| 8443 | Web admin + intro page + API (HTTPS, single port) |
| 25565 | Minecraft game port (via frp tunnel, optional) |

## Configuration

`config/config.yaml` has five top-level sections:

| Section | Purpose | Key Fields |
|---------|---------|------------|
| `mc` | MC server | `version`, `port`, `java_path`, `jvm_args`, `auto_restart` |
| `web` | Web service | `admin_port`, `ssl_enabled`, `session_timeout` |
| `admins` | Admin accounts | `username`, `password_hash` (BCrypt) |
| `tunnel` | Tunneling | `server_addr`, `token`/`user`, `mapping` |
| `world` | World settings | `gamemode`, `difficulty`, `seed`, `view_distance` |

See [Project.md](Project.md) §5 for details.

## Project Structure

```
mc-tunnel/
├── main.py                    # Entry point
├── config/                    # Configuration system
├── core/
│   ├── mcserver/              # PaperMC adapter, downloader, world manager
│   ├── tunnel/                # frp config generator, process manager
│   ├── proxy/                 # TCP proxy (protocol sniffing)
│   ├── procman/               # Generic process manager
│   └── audit/                 # Audit logging
├── api/                       # REST API + auth/CSRF middleware
├── web/
│   ├── server.py              # Flask application factory
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
| Auth | JWT + BCrypt + CSRF |
| MC Protocol | RCON (mcipc) + Server List Ping (mcstatus) |
| Tunneling | frp subprocess |
| WSGI Server | cheroot 11.x (thread pool + SSL + timeout) |
| Testing | pytest |

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
- Issues and pull requests are welcome
