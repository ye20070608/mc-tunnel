"""Integration test for Flask web server and API routes."""
import sys
import json
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

    def get_logs(self, limit=50):
        return [{"time": "14:35:22", "level": "info", "message": "Test log"}]

    def update_mapping(self, mapping):
        return {"updated": True}


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


class MockAuditLogger:
    def __init__(self):
        self.logs = []

    def log(self, **kwargs):
        self.logs.append(kwargs)

    def get_logs(self, limit=50):
        return self.logs[-limit:]


audit = MockAuditLogger()
admin_app = create_admin_app(config, logger, MockMCAdapter(), MockTunnelManager(), audit)

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
    check("Logs export is text/plain", "text/plain" in resp.content_type)

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

print("\n--- Bearer Token Tests (no session) ---\n")

# New test client without session cookies, all requests via Bearer header
with admin_app.test_client() as c2:

    # Step 22: Tunnel status with Bearer token
    resp = c2.get(
        "/api/tunnel/status",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    check("Tunnel status via Bearer token", resp.status_code == 200)
    data = json.loads(resp.data)
    check("Tunnel status success", data.get("success") is True)

    # Step 23: Expired/invalid token -> 401
    resp = c2.get(
        "/api/mc/status",
        headers={"Authorization": "Bearer invalid.token.here", "Accept": "application/json"},
    )
    check("Invalid JWT token -> 401", resp.status_code == 401)
    data = json.loads(resp.data)
    check("401 error is 'unauthorized'", data.get("error") == "unauthorized")

    # Step 24: Dashboard redirect with no auth
    resp = c2.get("/", headers={"Accept": "text/html"})
    check("Dashboard redirects (302) without auth", resp.status_code == 302)

print(f"\n=== Results: {len(errors)} failures ===")
if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("=== All tests passed! ===")
