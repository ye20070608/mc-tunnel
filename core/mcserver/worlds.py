"""World directory manager — scan, create, delete, rename MC world folders.

Minecraft stores each world dimension in a dedicated directory.  The
three dimensions (overworld, nether, end) are nested inside a per-world
container directory::

    server/worlds/<name>/
    ├── world/           ← overworld (the ``level-name`` value)
    ├── world_nether/    ← Nether (auto-created by MC on first visit)
    └── world_the_end/   ← End (auto-created by MC on first visit)

The active world is determined by ``level-name`` in ``server.properties``
(e.g. ``worlds/world/world``, ``worlds/hello_world/world``).

Only the overworld directory is explicitly created; the MC server
creates the nether / end dimensions on demand.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

# Whitelist of allowed characters in world names — rejects path traversal
_WORLD_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class WorldManager:
    """Manage Minecraft world directories under a ``worlds/`` base folder.

    Each world is a container directory holding up to three dimension
    subdirectories:

    - ``<name>/world/`` — overworld (required)
    - ``<name>/world_nether/`` — Nether (auto-created by MC on first visit)
    - ``<name>/world_the_end/`` — End (auto-created by MC on first visit)

    ``level-name`` in server.properties points to the overworld, e.g.
    ``worlds/<name>/world``.
    """

    WORLD_MARKERS = ("level.dat", "session.lock")
    DIM_SUFFIXES = ("_nether", "_the_end")

    def __init__(self, server_dir: str | Path = "server") -> None:
        self._server_dir = Path(server_dir).resolve()
        self._worlds_dir = self._server_dir / "worlds"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_world_name(name: str) -> bool:
        """Reject path traversal and invalid world names.

        Valid names contain only alphanumeric characters, underscores,
        and hyphens.  ``..``, ``/``, ``\\``, and empty strings are
        rejected to prevent directory traversal attacks.
        """
        if not name or not name.strip():
            return False
        if ".." in name or "/" in name or "\\" in name:
            return False
        return bool(_WORLD_NAME_RE.match(name))

    # ------------------------------------------------------------------
    # Name helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_level_name(name: str) -> str:
        """Convert a world group name to a ``level-name`` path.

        ``"hello_world"`` → ``"worlds/hello_world/world"``
        """
        return f"worlds/{name}/world"

    @staticmethod
    def _extract_world_name(level_name: str) -> str:
        """Extract the world group name from a ``level-name`` path.

        ``"worlds/hello/world"`` → ``"hello"``
        ``"world"``              → ``"world"``
        ``"worlds\\hello\\world"`` → ``"hello"``
        """
        name = level_name.replace("\\", "/")
        prefix = "worlds/"
        if name.startswith(prefix):
            name = name[len(prefix):]
        suffix = "/world"
        if name.endswith(suffix):
            name = name[:-len(suffix)]
        return name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_worlds(self) -> list[dict[str, Any]]:
        """Return all world groups with per-dimension metadata.

        Scans ``worlds/`` for container directories (those containing a
        ``world/`` overworld subdirectory).  Each entry reports whether
        each of the three dimensions exists on disk.

        Returns:
            List of world dicts with keys ``name``, ``size_mb``,
            ``size_human``, ``modified``, ``active``, ``dimensions``.
        """
        if not self._worlds_dir.exists():
            return []

        active_group = self.get_active_world()

        worlds: list[dict[str, Any]] = []

        for entry in sorted(self._worlds_dir.iterdir()):
            if not entry.is_dir():
                continue
            base_name = entry.name
            # A world group must contain a world/ overworld subdirectory
            overworld = entry / "world"
            if not overworld.is_dir():
                continue

            dims = self._get_dimension_paths(base_name)
            sizes = self._dimension_sizes(dims)

            total_bytes = sum(sizes.values())
            mtime = self._dim_modified(dims)

            worlds.append({
                "name": base_name,
                "size_mb": round(total_bytes / (1024 * 1024), 1),
                "size_human": self._human_size(total_bytes),
                "modified": datetime.fromtimestamp(mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "active": base_name == active_group,
                "dimensions": {
                    "overworld": dims["overworld"].exists(),
                    "nether": dims["nether"].exists(),
                    "end": dims["end"].exists(),
                },
            })

        return worlds

    def create_world(self, name: str, seed: str = "") -> bool:
        """Create a new world (container + overworld with ``session.lock``).

        The nether / end directories are NOT created here; the MC server
        generates them automatically when players first enter those
        dimensions.

        Args:
            name: Base world name (e.g. ``"creative"`` →
                  ``worlds/creative/world/``).
            seed: Optional world seed (empty = random).

        Returns:
            True if created, False if it already existed.
        """
        if not self.validate_world_name(name):
            return False
        overworld = self._worlds_dir / name / "world"
        if overworld.exists():
            return False

        overworld.mkdir(parents=True, exist_ok=True)
        (overworld / "session.lock").write_text("", encoding="utf-8")

        # 保存种子：优先写入 server.properties，若不存在则写入 config.yaml
        if seed:
            self._set_property("level-seed", seed)
            # 如果 server.properties 还不存在，种子会丢失 → 同步写入 config.yaml
            props_path = self._server_dir / "server.properties"
            if not props_path.exists():
                self._save_to_config({"world": {"seed": seed}})
        return True

    def delete_world(self, name: str) -> bool:
        """Delete a world and its entire container directory.

        Refuses to delete the currently active world (caller should
        validate the server is stopped beforehand).

        Args:
            name: Base world name.

        Returns:
            True if the container directory was deleted.
        """
        if not self.validate_world_name(name):
            return False
        container = self._worlds_dir / name
        if not container.exists():
            return False
        shutil.rmtree(container)
        return True

    def rename_world(self, old_name: str, new_name: str) -> bool:
        """Rename a world container directory.

        If the active world is renamed, ``server.properties`` is updated
        to point to the new name.

        Args:
            old_name: Current base world name.
            new_name: Desired base world name.

        Returns:
            True on success, False if *old_name* container doesn't exist
            or *new_name* container already exists.
        """
        if not self.validate_world_name(old_name) or not self.validate_world_name(new_name):
            return False
        old_container = self._worlds_dir / old_name
        new_container = self._worlds_dir / new_name

        if not old_container.is_dir():
            return False
        if new_container.exists():
            return False

        old_container.rename(new_container)

        # Update server.properties if active world was renamed
        active_group = self.get_active_world()
        if active_group == old_name:
            self._set_active_world(self._make_level_name(new_name))

        return True

    def activate_world(self, name: str) -> bool:
        """Set *name* as the active world in ``server.properties`` and ``config.yaml``.

        Args:
            name: Base world name (without ``worlds/`` prefix).

        Returns:
            True if the overworld exists and both files were updated.
        """
        if not self.validate_world_name(name):
            return False
        overworld = self._worlds_dir / name / "world"
        if not overworld.exists():
            return False
        level_name = self._make_level_name(name)
        self._set_active_world(level_name)

        # Always sync to config.yaml — ServerPropertiesGenerator reads from
        # config when regenerating server.properties, so it must stay in sync.
        self._save_to_config({"world": {"level_name": level_name}})

        return True

    def get_active_world(self) -> str:
        """Return the active world group name.

        Parses ``level-name`` from ``server.properties`` and extracts
        the group name.  E.g. ``"worlds/hello/world"`` → ``"hello"``.
        """
        raw = self._get_active_world()
        return self._extract_world_name(raw)

    def migrate_existing(self) -> int:
        """Migrate root-level world dirs into the nested ``worlds/`` structure.

        Handles two scenarios:

        1. **Root-level worlds** — ``server/world/`` (with ``level.dat``)
           is moved to ``server/worlds/world/world/`` (and likewise for
           ``_nether`` / ``_the_end`` companions).

        2. **Old flat worlds/** — If ``server/worlds/<name>/`` already
           contains ``level.dat`` (i.e. it IS the overworld, not a
           container), it is moved to ``server/worlds/<name>/world/``
           (creating the container nesting).

        Returns:
            Number of world groups migrated.
        """
        migrated = 0
        self._worlds_dir.mkdir(parents=True, exist_ok=True)

        # Known non-world directories to skip when scanning root
        SKIP = {
            "logs", "plugins", "config", "venv", ".git", "__pycache__",
            "scripts", "docs", "tests", "web", "api", "core", "logger",
            "worlds", ".claude", ".omc", ".vscode", ".idea", ".vs",
            "dist", "build", "cache", "frp",
        }

        # ── Phase 1: Root-level → nested worlds/<name>/world/ ──
        root_dirs = {d.name: d for d in self._server_dir.iterdir() if d.is_dir()}

        candidates: set[str] = set()
        for name in root_dirs:
            if name.startswith("."):
                continue
            if name in SKIP:
                continue
            if name.endswith("_nether") or name.endswith("_the_end"):
                if name.endswith("_nether"):
                    base = name[:-7]
                else:
                    base = name[:-9]
                candidates.add(base)
            else:
                path = root_dirs[name]
                if (path / "level.dat").exists():
                    candidates.add(name)

        for base in sorted(candidates):
            target_overworld = self._worlds_dir / base / "world"
            if target_overworld.exists():
                continue  # already migrated

            source_overworld = root_dirs.get(base)
            source_nether = root_dirs.get(f"{base}_nether")
            source_end = root_dirs.get(f"{base}_the_end")

            if source_overworld and source_overworld.is_dir():
                # Ensure container exists
                container = self._worlds_dir / base
                container.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source_overworld), str(target_overworld))
                migrated += 1

            if source_nether and source_nether.is_dir():
                shutil.move(str(source_nether), str(self._worlds_dir / base / "world_nether"))

            if source_end and source_end.is_dir():
                shutil.move(str(source_end), str(self._worlds_dir / base / "world_the_end"))

        # ── Phase 2: Old flat worlds/ → nested container structure ──
        # Detect when worlds/<name>/ itself contains level.dat (old flat format)
        for entry in sorted(self._worlds_dir.iterdir()):
            if not entry.is_dir():
                continue
            base_name = entry.name
            # Skip hidden / staging directories and dimension directories
            if base_name.startswith("."):
                continue
            if base_name.endswith("_nether") or base_name.endswith("_the_end"):
                continue
            # Already nested? Skip
            if (entry / "world").is_dir():
                continue
            # Old flat format: the directory itself IS the overworld
            if (entry / "level.dat").exists():
                # Move to nested structure via staging directory
                staging = entry.with_name(f"._migrate_{base_name}")
                try:
                    entry.rename(staging)
                    container = self._worlds_dir / base_name
                    container.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(staging), str(container / "world"))

                    # Also move companion dims if they're in the old flat format
                    for suffix in ("_nether", "_the_end"):
                        flat_dim = self._worlds_dir / f"{base_name}{suffix}"
                        if flat_dim.is_dir():
                            shutil.move(str(flat_dim), str(container / f"world{suffix}"))

                    migrated += 1
                except OSError:
                    # Rollback: move staging back
                    if staging.exists():
                        staging.rename(entry)
                    raise

        # ── Update level-name after migration (always, even if dirs were
        # already migrated — server.properties may be out of sync) ──
        active = self._get_active_world()
        if active:
            extracted = self._extract_world_name(active)
            normalized = active.replace("\\", "/")
            needs_fix = (
                not normalized.startswith("worlds/")
                or not normalized.endswith("/world")
            )
            if needs_fix:
                correct = self._make_level_name(extracted)
                self._set_active_world(correct)

        return migrated

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_dimension_paths(self, name: str) -> dict[str, Path]:
        """Return Paths for the three dimensions of a world.

        Dimensions are nested inside the world container:
        ``worlds/<name>/world/``, ``worlds/<name>/world_nether/``,
        ``worlds/<name>/world_the_end/``.

        Returns:
            Dict with keys ``overworld``, ``nether``, ``end``.
        """
        container = self._worlds_dir / name
        return {
            "overworld": container / "world",
            "nether": container / "world_nether",
            "end": container / "world_the_end",
        }

    def _dimension_sizes(self, dims: dict[str, Path]) -> dict[str, int]:
        """Return the byte size of each dimension that exists."""
        return {
            key: self._dir_size(path) if path.exists() else 0
            for key, path in dims.items()
        }

    @staticmethod
    def _dim_modified(dims: dict[str, Path]) -> float:
        """Return the latest modification time across all existing dims."""
        mtimes = []
        for p in dims.values():
            if p.exists():
                try:
                    mtimes.append(p.stat().st_mtime)
                except OSError:
                    pass
        return max(mtimes) if mtimes else 0.0

    def _get_active_world(self) -> str:
        """Read ``level-name`` from ``server.properties``.

        Returns the raw value (e.g. ``"worlds/world/world"`` or ``"world"``).
        """
        props_path = self._server_dir / "server.properties"
        if not props_path.exists():
            return "worlds/world/world"
        for line in props_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("level-name="):
                return stripped.split("=", 1)[1].strip()
        return "worlds/world/world"

    def _set_active_world(self, name: str) -> None:
        """Update the ``level-name`` entry in ``server.properties`` (atomic).

        Args:
            name: The full level-name value to write
                  (e.g. ``"worlds/hello/world"``).
        """
        props_path = self._server_dir / "server.properties"
        if not props_path.exists():
            return

        lines = props_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("level-name="):
                lines[i] = f"level-name={name}"
                updated = True
                break

        if not updated:
            lines.append(f"level-name={name}")

        # Atomic write via temp file
        tmp_path = Path(str(props_path) + ".tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(str(tmp_path), str(props_path))

    def _set_property(self, key: str, value: str) -> None:
        """Set a single property in ``server.properties`` (atomic write).

        Args:
            key: Property key (e.g. ``"level-seed"``).
            value: Property value.
        """
        props_path = self._server_dir / "server.properties"
        if not props_path.exists():
            return

        lines = props_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break

        if not updated:
            lines.append(f"{key}={value}")

        # Atomic write via temp file
        tmp_path = Path(str(props_path) + ".tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(str(tmp_path), str(props_path))

    @staticmethod
    def _save_to_config(updates: dict) -> None:
        """Atomically merge *updates* into ``config/config.yaml``.

        *updates* is a dict of top-level sections, each mapping to a dict
        of key-value pairs to set/overwrite.  Existing keys not mentioned
        in *updates* are left untouched.

        Example::

            _save_to_config({"world": {"seed": "12345"}})
        """
        import yaml
        import tempfile

        cm_path = Path("config/config.yaml")
        try:
            raw = yaml.safe_load(cm_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return

        for section, kv in updates.items():
            raw.setdefault(section, {}).update(kv)

        try:
            fd, tmp = tempfile.mkstemp(dir=cm_path.parent, prefix="config_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.dump(raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
            os.replace(tmp, str(cm_path))
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _dir_size(path: Path) -> int:
        """Recursively compute the total size of *path* in bytes."""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except OSError:
            pass
        return total

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Convert a byte count to a human-readable string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
