"""Integration test for Flask web server and API routes.

Covers 51 checks across all API blueprints:
  - Auth (JWT / CSRF / session / Bearer)
  - MC control (start / stop / restart / status / players / kick / op / deop)
  - Console & command execution
  - Admin (login / CSRF / change-password / operation-log)
  - Whitelist (CRUD / reload / toggle / pending)
  - Logs (query / filter / export)
  - Tunnel (status / update)
  - Server (versions / worlds / info)
  - Plugins (list / upload / delete / toggle)
  - Public status (no auth)
  - Edge cases (invalid JWT / no CSRF / empty input)
"""
import io
import os
import sys
import json
import zipfile
from pathlib import Path

# Ensure the project root is on sys.path (derived relative to this file)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import bcrypt

# Import after path setup to ensure project modules are resolvable
from web.server import create_admin_app  # noqa: E402

# Generate a real bcrypt hash for testing
real_hash = bcrypt.hashpw(b"adminpass", bcrypt.gensalt(rounds=4)).decode("utf-8")

config = {
    "mc": {
        "version": "1.20.4",
        "port": 25565,
        "max_players": 20,
        "java_path": "java",
        "jvm_args": "-Xmx4G",
    },
    "web": {
        "admin_port": 8443,
        "session_timeout": 3600,
        "csrf_enabled": True,
        "jwt_secret": "test-secret-32-chars-min!!-extra-bytes",  # >= 32 bytes
    },
    "admins": [{"username": "admin", "password_hash": real_hash}],
    "tunnel": {"server_addr": "test.example.com", "server_port": 7000, "token": "test"},
    "intro": {"server_name": "Test Server", "slogan": "Test slogan"},
}


class FakeLogger:
    def info(self, msg, *args, **kwargs):
        pass

    def error(self, msg, *args, **kwargs):
        pass

    def warning(self, msg, *args, **kwargs):
        pass

    def debug(self, msg, *args, **kwargs):
        pass


logger = FakeLogger()
errors = []


def check(name, ok, detail=""):
    if ok:
        print(f"  PASS: {name}")
    else:
        msg = f"  FAIL: {name}" + (f" - {detail}" if detail else "")
        print(msg)
        errors.append(msg)


class MockMCAdapter:
    def get_status(self):
        return {
            "onlinePlayers": 5,
            "tps": 19.5,
            "status": "running",
            "memory": {"used": "2G", "max": "4G", "percent": 50},
            "uptime": "2h",
            "cpu": "15%",
        }

    def get_players(self):
        return [{"name": "Steve", "ping": 24, "gamemode": "生存模式", "joined": "2小时前"}]

    def start(self):
        return {"pid": 1234}

    def stop(self):
        return {"success": True}

    def restart(self):
        return {"success": True}

    def kick_player(self, name):
        return {"kicked": True}

    def get_whitelist(self):
        return [{"name": "Steve", "added": "2026-06-15", "by": "admin"}]

    def whitelist_add(self, name):
        return {"added": name}

    def whitelist_remove(self, name):
        return {"removed": name}

    def send_command(self, cmd: str) -> str:
        return "Command executed"

    def get_logs(self, limit=50):
        return [{"time": "14:35:22", "level": "info", "message": "Test log"}]

    def update_mapping(self, mapping):
        return {"updated": True}

    def op_player(self, name):
        return {"opped": True}

    def deop_player(self, name):
        return {"deopped": True}

    def get_console_output(self, limit=100):
        return ["[14:30:22] [Server thread/INFO]: Test console output line"]

    def get_installed_versions(self):
        return ["1.20.4", "1.21"]

    def is_running(self):
        return False

    def get_pending_players(self):
        return [{"name": "NewGuy", "rejected_at": "2026-06-25 14:00"}]

    def get_player_ips(self):
        return {}


class MockTunnelManager:
    def get_status(self):
        return {
            "status": "connected",
            "server": "test.example.com:7000",
            "uptime": "2h",
            "activeTunnels": 3,
            "mappings": [],
        }

    def update_mapping(self, mapping):
        return {"updated": True}

    def reload_and_restart(self):
        return True


class MockConfigManager:
    """Mock config manager for change-password tests."""

    def update_admin_password(self, username, password_hash):
        return True

    def set_web_keys(self, jwt_secret=None, secret_key=None):
        return True


class MockAuditLogger:
    def __init__(self):
        self.logs = []

    def log(self, **kwargs):
        self.logs.append(kwargs)

    def get_logs(self, limit=50):
        return self.logs[-limit:]


# Helper: create a minimal valid JAR/ZIP for plugin upload testing
def _make_minimal_jar() -> bytes:
    """Return bytes of a minimal valid ZIP containing a plugin.yml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("plugin.yml", 'name: TestPlugin\nversion: "1.0"\nmain: com.example.Test\n')
    return buf.getvalue()


# Ensure server/plugins/ exists for plugin tests and seed with a toggle-test jar
_server_plugins = Path("server/plugins")
_server_plugins.mkdir(parents=True, exist_ok=True)
_toggle_jar = _server_plugins / "toggle_test.jar"
if not _toggle_jar.exists():
    _toggle_jar.write_bytes(_make_minimal_jar())


audit = MockAuditLogger()
admin_app = create_admin_app(
    config, logger, MockMCAdapter(), MockTunnelManager(), audit, MockConfigManager(),
)

print("=== Admin App Auth Flow Tests ===\n")

# Use a session-based client for cookie/session tests
with admin_app.test_client() as c:

    # Step 1: Get CSRF token
    resp = c.get("/api/admin/csrf-token")
    check("GET /api/admin/csrf-token", resp.status_code == 200)
    csrf = json.loads(resp.data)["csrf_token"]
    check("CSRF token format valid", "." in csrf and len(csrf) > 20)

    # Step 2: Login with correct password
    resp = c.post(
        "/api/admin/login",
        json={"username": "admin", "password": "adminpass"},
    )
    check("Login with valid credentials", resp.status_code == 200)
    data = json.loads(resp.data)
    token = data.get("token", "")
    csrf2 = data.get("csrf_token", "")
    check("JWT token returned", len(token) > 20)
    check("CSRF token in login response", len(csrf2) > 20)
    check("Username in response", data.get("username") == "admin")

    # Step 3: Dashboard with session cookie (set by login)
    resp = c.get("/")
    check("Dashboard accessible with session (200)", resp.status_code == 200)

    # Step 4: MC status API with session
    resp = c.get("/api/mc/status")
    check("GET /api/mc/status with auth", resp.status_code == 200)
    data = json.loads(resp.data)
    check("MC status has success=true", data.get("success") is True)
    check("MC status data present", "data" in data)

    # Step 5: Players endpoint (with session)
    resp = c.get("/api/mc/players")
    check("GET /api/mc/players", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Players count returned", data.get("count") == 1)

    # Step 6: Kick player with CSRF
    resp = c.post(
        "/api/mc/kick",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": "Steve"},
    )
    check("POST /api/mc/kick with CSRF", resp.status_code == 200)

    # Step 7: Kick without CSRF -> 403
    resp = c.post(
        "/api/mc/kick",
        headers={"Content-Type": "application/json"},
        json={"name": "Steve"},
    )
    check("POST /api/mc/kick without CSRF -> 403", resp.status_code == 403)

    # Step 8: Operation logs
    resp = c.get("/api/admin/operation-log")
    check("GET /api/admin/operation-log", resp.status_code == 200)

    # Step 9: Whitelist list
    resp = c.get("/api/whitelist/list")
    check("GET /api/whitelist/list", resp.status_code == 200)

    # Step 10: Whitelist add
    resp = c.post(
        "/api/whitelist/add",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": "NewPlayer"},
    )
    check("POST /api/whitelist/add", resp.status_code == 200)

    # Step 11: Whitelist remove
    resp = c.post(
        "/api/whitelist/remove",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": "NewPlayer"},
    )
    check("POST /api/whitelist/remove", resp.status_code == 200)

    # Step 12: Logs recent
    resp = c.get("/api/logs/recent")
    check("GET /api/logs/recent", resp.status_code == 200)

    # Step 13: Logs with level filter
    resp = c.get("/api/logs/recent?level=info&limit=10")
    check("GET /api/logs/recent with filters", resp.status_code == 200)

    # Step 14: Logs export
    resp = c.get("/api/logs/export")
    check("GET /api/logs/export", resp.status_code == 200)
    check("Logs export is application/zip", "application/zip" in resp.content_type)

    # Step 15: Tunnel update with CSRF
    resp = c.post(
        "/api/tunnel/update",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"mapping": {"mc": {"local_port": 25565, "remote_port": 25565, "protocol": "tcp"}}},
    )
    check("POST /api/tunnel/update", resp.status_code == 200)

    # Step 16: MC start
    resp = c.post(
        "/api/mc/start",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
    )
    check("POST /api/mc/start", resp.status_code == 200)

    # Step 17: MC stop
    resp = c.post(
        "/api/mc/stop",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
    )
    check("POST /api/mc/stop", resp.status_code == 200)

    # Step 18: MC restart
    resp = c.post(
        "/api/mc/restart",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
    )
    check("POST /api/mc/restart", resp.status_code == 200)

    # Step 19: Invalid whitelist name -> 400
    resp = c.post(
        "/api/whitelist/add",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": ""},
    )
    check("POST /api/whitelist/add empty name -> 400", resp.status_code == 400)

    # Step 20: Kick with empty name -> 400
    resp = c.post(
        "/api/mc/kick",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": ""},
    )
    check("POST /api/mc/kick empty name -> 400", resp.status_code == 400)

    # Step 21: Public status endpoint (no auth needed)
    resp = c.get("/api/public/status")
    check("Public status (no auth)", resp.status_code == 200)

    # ── OP / DEOP ─────────────────────────────────────────────

    # Step 22: OP player with CSRF
    resp = c.post(
        "/api/mc/op",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": "Steve"},
    )
    check("POST /api/mc/op with CSRF", resp.status_code == 200)

    # Step 23: OP player without CSRF -> 403
    resp = c.post(
        "/api/mc/op",
        headers={"Content-Type": "application/json"},
        json={"name": "Steve"},
    )
    check("POST /api/mc/op without CSRF -> 403", resp.status_code == 403)

    # Step 24: OP player empty name -> 400
    resp = c.post(
        "/api/mc/op",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": ""},
    )
    check("POST /api/mc/op empty name -> 400", resp.status_code == 400)

    # Step 25: DEOP player with CSRF
    resp = c.post(
        "/api/mc/deop",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": "Steve"},
    )
    check("POST /api/mc/deop with CSRF", resp.status_code == 200)

    # Step 26: DEOP player empty name -> 400
    resp = c.post(
        "/api/mc/deop",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"name": ""},
    )
    check("POST /api/mc/deop empty name -> 400", resp.status_code == 400)

    # ── Console & Command ──────────────────────────────────────

    # Step 27: Console output
    resp = c.get("/api/mc/console")
    check("GET /api/mc/console", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Console has success=true", data.get("success") is True)
    check("Console has lines array", isinstance(data.get("lines"), list))

    # Step 28: Console with limit param
    resp = c.get("/api/mc/console?limit=10")
    check("GET /api/mc/console?limit=10", resp.status_code == 200)

    # Step 29: Send command with CSRF
    resp = c.post(
        "/api/mc/command",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"command": "list"},
    )
    check("POST /api/mc/command with CSRF", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Command response has response field", "response" in data)

    # Step 30: Send empty command -> 400
    resp = c.post(
        "/api/mc/command",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"command": ""},
    )
    check("POST /api/mc/command empty -> 400", resp.status_code == 400)

    # ── Change password ────────────────────────────────────────

    # Step 31: Change password success
    resp = c.post(
        "/api/admin/change-password",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"old_password": "adminpass", "new_password": "newpass123"},
    )
    check("POST /api/admin/change-password success", resp.status_code == 200)

    # Step 32: Change password wrong old -> 403
    resp = c.post(
        "/api/admin/change-password",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"old_password": "wrongpass", "new_password": "newpass123"},
    )
    check("POST /api/admin/change-password wrong old -> 403", resp.status_code == 403)

    # Step 33: Change password short new -> 400
    resp = c.post(
        "/api/admin/change-password",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"old_password": "adminpass", "new_password": "123"},
    )
    check("POST /api/admin/change-password short new -> 400", resp.status_code == 400)

    # Step 34: Change password missing fields -> 400
    resp = c.post(
        "/api/admin/change-password",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"old_password": "", "new_password": ""},
    )
    check("POST /api/admin/change-password missing fields -> 400", resp.status_code == 400)

    # ── Server versions & info ─────────────────────────────────

    # Step 35: Version list
    resp = c.get("/api/server/versions")
    check("GET /api/server/versions", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Version list has success=true", data.get("success") is True)
    check("Version list has versions array", isinstance(data.get("versions"), list))
    check("Version list has current_version", "current_version" in data)

    # Step 36: Server info
    resp = c.get("/api/server/info")
    check("GET /api/server/info", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Server info has success=true", data.get("success") is True)
    info_data = data.get("data", {})
    for key in ("local_ip", "port", "version", "online_mode", "active_world", "status"):
        check(f"Server info has key '{key}'", key in info_data)

    # Step 37: World list
    resp = c.get("/api/server/worlds")
    check("GET /api/server/worlds", resp.status_code == 200)
    data = json.loads(resp.data)
    check("World list has success=true", data.get("success") is True)

    # ── Whitelist reload / toggle / pending ────────────────────

    # Step 38: Whitelist reload
    resp = c.post(
        "/api/whitelist/reload",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
    )
    check("POST /api/whitelist/reload", resp.status_code == 200)

    # Step 39: Whitelist toggle
    resp = c.post(
        "/api/whitelist/toggle",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
    )
    check("POST /api/whitelist/toggle", resp.status_code == 200)

    # Step 40: Whitelist pending
    resp = c.get("/api/whitelist/pending")
    check("GET /api/whitelist/pending", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Pending list has success=true", data.get("success") is True)

    # ── Plugin management ──────────────────────────────────────

    # Step 41: Plugin list (empty or seeded)
    resp = c.get("/api/server/plugins")
    check("GET /api/server/plugins", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Plugin list has success=true", data.get("success") is True)
    check("Plugin list has plugins array", isinstance(data.get("plugins"), list))
    check("Plugin list has count", "count" in data)

    # Step 42: Plugin upload — no file -> 400
    resp = c.post(
        "/api/server/plugins/upload",
        headers={"X-CSRF-Token": csrf2},
        content_type="multipart/form-data",
    )
    check("POST /api/server/plugins/upload no file -> 400", resp.status_code == 400)

    # Step 43: Plugin upload — valid file
    resp = c.post(
        "/api/server/plugins/upload",
        data={"file": (io.BytesIO(_make_minimal_jar()), "TestPlugin.jar")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf2},
    )
    check("POST /api/server/plugins/upload valid jar", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Plugin upload success=true", data.get("success") is True)

    # Step 44: Plugin upload — invalid filename -> 400
    resp = c.post(
        "/api/server/plugins/upload",
        data={"file": (io.BytesIO(_make_minimal_jar()), "../evil.jar")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf2},
    )
    check("POST /api/server/plugins/upload path traversal -> 400", resp.status_code == 400)

    # Step 45: Plugin upload — duplicate -> 409
    resp = c.post(
        "/api/server/plugins/upload",
        data={"file": (io.BytesIO(_make_minimal_jar()), "TestPlugin.jar")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf2},
    )
    check("POST /api/server/plugins/upload duplicate -> 409", resp.status_code == 409)

    # Step 46: Plugin delete — missing filename -> 400
    resp = c.post(
        "/api/server/plugins/delete",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={},
    )
    check("POST /api/server/plugins/delete missing filename -> 400", resp.status_code == 400)

    # Step 47: Plugin delete — nonexistent -> 404
    resp = c.post(
        "/api/server/plugins/delete",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"filename": "NonExistent.jar"},
    )
    check("POST /api/server/plugins/delete nonexistent -> 404", resp.status_code == 404)

    # Step 48: Plugin toggle — missing filename -> 400
    resp = c.post(
        "/api/server/plugins/toggle",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={},
    )
    check("POST /api/server/plugins/toggle missing filename -> 400", resp.status_code == 400)

    # Step 49: Plugin toggle — nonexistent -> 404
    resp = c.post(
        "/api/server/plugins/toggle",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"filename": "NonExistent.jar"},
    )
    check("POST /api/server/plugins/toggle nonexistent -> 404", resp.status_code == 404)

    # Step 50: Plugin toggle — existing file (enable → disable)
    resp = c.post(
        "/api/server/plugins/toggle",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"filename": "toggle_test.jar"},
    )
    check("POST /api/server/plugins/toggle existing (enable→disable)", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Toggle result disabled=true", data.get("disabled") is True)

    # Step 51: Plugin toggle — back (disable → enable)
    resp = c.post(
        "/api/server/plugins/toggle",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"filename": "toggle_test.jar.disabled"},
    )
    check("POST /api/server/plugins/toggle (disable→enable)", resp.status_code == 200)

    # Step 52: Plugin delete — delete the uploaded test plugin
    resp = c.post(
        "/api/server/plugins/delete",
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf2},
        json={"filename": "TestPlugin.jar"},
    )
    check("POST /api/server/plugins/delete TestPlugin.jar", resp.status_code == 200)

print("\n--- Bearer Token Tests (no session) ---\n")

# New test client without session cookies, all requests via Bearer header
with admin_app.test_client() as c2:

    # Step 53: Tunnel status with Bearer token
    resp = c2.get(
        "/api/tunnel/status",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    check("Tunnel status via Bearer token", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Tunnel status success", data.get("success") is True)

    # Step 54: Expired/invalid token -> 401
    resp = c2.get(
        "/api/mc/status",
        headers={"Authorization": "Bearer invalid.token.here", "Accept": "application/json"},
    )
    check("Invalid JWT token -> 401", resp.status_code == 401)
    data = json.loads(resp.data)
    check("401 error is 'unauthorized'", data.get("error") == "unauthorized")

    # Step 55: Dashboard redirect with no auth
    resp = c2.get("/", headers={"Accept": "text/html"})
    check("Dashboard redirects (302) without auth", resp.status_code == 302)

    # Step 56: Server versions via Bearer token (read endpoint)
    resp = c2.get(
        "/api/server/versions",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    check("Version list via Bearer token", resp.status_code == 200)

    # Step 57: CSRF protected endpoint via Bearer — missing X-CSRF-Token -> 403
    resp = c2.post(
        "/api/mc/op",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
        json={"name": "Steve"},
    )
    check("OP via Bearer without CSRF -> 403", resp.status_code == 403)

print(f"\n=== Results: {len(errors)} failures ===")
if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("=== All tests passed! ===")
