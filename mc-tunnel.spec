# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for mc-tunnel (MC 隧道控制器)
# Build: pyinstaller --clean --noconfirm mc-tunnel.spec

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web/templates', 'web/templates'),
        ('web/static', 'web/static'),
        ('config/defaults.yaml', 'config'),
    ],
    hiddenimports=[
        # API blueprints (dynamic imports in router.py)
        'api.router', 'api.mc', 'api.tunnel', 'api.admin', 'api.public',
        'api.whitelist', 'api.logs_api', 'api.server', 'api.plugins',
        # Middleware
        'api.middleware.auth', 'api.middleware.csrf',
        # Core modules (lazy imports in main.py)
        'core.ssl',
        'core.mcserver.adapter', 'core.mcserver.downloader',
        'core.mcserver.status', 'core.mcserver.worlds',
        'core.mcserver.properties', 'core.mcserver.plugins',
        'core.mcserver.java', 'core.mcserver.eula', 'core.mcserver.whitelist',
        'core.tunnel.config', 'core.tunnel.client',
        'core.proxy.tcp', 'core.proxy.stats',
        'core.procman.manager', 'core.audit.logger',
        # Third-party (often missed by auto-detection)
        'cheroot', 'cheroot.ssl.builtin',
        'mcipc', 'mcipc.rcon', 'mcipc.rcon.client',
        'mcstatus',
        'loguru',
        'bcrypt',
        'yaml',
        'jinja2',
        'jinja2.ext',
        'psutil',
        'tqdm',
        'flask_limiter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='mc-tunnel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # Keep console window for log output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
