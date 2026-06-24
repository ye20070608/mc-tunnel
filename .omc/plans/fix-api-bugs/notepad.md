# Fix API Bugs - Implementation Plan

## Bug 1: Missing methods on MCServerAdapter
- **core/mcserver/adapter.py**: Add get_players(), kick_player(), get_whitelist(), whitelist_add(), whitelist_remove(), get_logs()
- **api/whitelist.py**: Refactor to use WhitelistManager directly

## Bug 2: Missing config_manager dependency
- **config/loader.py**: Add ConfigManager class
- **api/router.py**: Add config_manager param to register_routes
- **web/server.py**: Add config_manager param to create_admin_app and run_server

## Bug 3: Type mismatch in tunnel update
- **api/tunnel.py**: Extract keys from mapping dict before passing to update_mapping
