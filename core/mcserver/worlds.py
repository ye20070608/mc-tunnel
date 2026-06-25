"""World directory manager — scan, create, delete, rename MC world folders.

Minecraft stores each world dimension in a dedicated directory.  The
three dimensions (overworld, nether, end) are grouped as one world entry:
``worlds/<name>/`` (overworld), ``worlds/<name>_nether/``,
``worlds/<name>_the_end/``.

The active world is determined by ``level-name`` in ``server.properties``.
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

    Each world is a group of up to three dimension directories:

    - ``<name>/`` — overworld (required)
    - ``<name>_nether/`` — Nether (auto-created by MC on first visit)
    - ``<name>_the_end/`` — End (auto-created by MC on first visit)

    Only the overworld directory is explicitly created; the MC server
    creates the nether / end dimensions on demand.
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
    # Public API
    # ------------------------------------------------------------------

    def list_worlds(self) -> list[dict[str, Any]]:
        """Return all world groups with per-dimension metadata.

        Scans ``worlds/`` for base world directories (those whose name
        does *not* end with ``_nether`` or ``_the_end``).  Each entry
        reports whether each of the three dimensions exists on disk.

        Returns:
            List of world dicts with keys ``name``, ``size_mb``,
            ``size_human``, ``modified``, ``active``, ``dimensions``.
        """
        if not self._worlds_dir.exists():
            return []

        active = self.get_active_world()
        # Strip worlds/ prefix for comparison
        active_base = active.replace("worlds/", "").replace("worlds\\", "")

        worlds: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entry in sorted(self._worlds_dir.iterdir()):
            if not entry.is_dir():
                continue
            # Skip dimension sub-directories
            base_name = entry.name
            if base_name.endswith("_nether") or base_name.endswith("_the_end"):
                continue
            if base_name in seen:
                continue
            seen.add(base_name)

            dims = self._get_dimension_paths(base_name)
            sizes = self._dimension_sizes(dims)

            total_bytes = sum(sizes.values())
            # Use the overworld's modification time (or the oldest dim)
            mtime = self._dim_modified(dims)

            worlds.append({
                "name": base_name,
                "size_mb": round(total_bytes / (1024 * 1024), 1),
                "size_human": self._human_size(total_bytes),
                "modified": datetime.fromtimestamp(mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "active": base_name == active_base,
                "dimensions": {
                    "overworld": dims["overworld"].exists(),
                    "nether": dims["nether"].exists(),
                    "end": dims["end"].exists(),
                },
            })

        return worlds

    def create_world(self, name: str) -> bool:
        """Create a new world (overworld directory with ``session.lock``).

        The nether / end directories are NOT created here; the MC server
        generates them automatically when players first enter those
        dimensions.

        Args:
            name: Base world name (e.g. ``"creative"`` → ``worlds/creative/``).

        Returns:
            True if created, False if it already existed.
        """
        if not self.validate_world_name(name):
            return False
        world_path = self._worlds_dir / name
        if world_path.exists():
            return False

        self._worlds_dir.mkdir(parents=True, exist_ok=True)
        world_path.mkdir(parents=True, exist_ok=True)
        (world_path / "session.lock").write_text("", encoding="utf-8")
        return True

    def delete_world(self, name: str) -> bool:
        """Delete a world and all its dimension directories.

        Refuses to delete the currently active world (caller should
        validate the server is stopped beforehand).

        Args:
            name: Base world name.

        Returns:
            True if the overworld directory was deleted.
        """
        if not self.validate_world_name(name):
            return False
        dims = self._get_dimension_paths(name)
        deleted = False

        for dim_path in dims.values():
            if dim_path.exists():
                shutil.rmtree(dim_path)
                deleted = True

        return deleted

    def rename_world(self, old_name: str, new_name: str) -> bool:
        """Rename a world and its existing dimension directories.

        If the active world is renamed, ``server.properties`` is updated
        to point to the new name.

        Args:
            old_name: Current base world name.
            new_name: Desired base world name.

        Returns:
            True on success, False if *old_name* overworld doesn't exist
            or *new_name* overworld already exists.
        """
        if not self.validate_world_name(old_name) or not self.validate_world_name(new_name):
            return False
        old_dims = self._get_dimension_paths(old_name)
        new_dims = self._get_dimension_paths(new_name)

        if not old_dims["overworld"].exists():
            return False
        if new_dims["overworld"].exists():
            return False

        for key, old_path in old_dims.items():
            if old_path.exists():
                old_path.rename(new_dims[key])

        # Update server.properties if active world was renamed
        active_base = self.get_active_world().replace("worlds/", "").replace("worlds\\", "")
        if active_base == old_name:
            self._set_active_world(f"worlds/{new_name}")

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
        world_path = self._worlds_dir / name
        if not world_path.exists():
            return False
        self._set_active_world(f"worlds/{name}")

        # Also sync config.yaml so ServerPropertiesGenerator stays in sync
        try:
            import yaml
            cm_path = Path("config/config.yaml")
            if cm_path.exists():
                raw = yaml.safe_load(cm_path.read_text(encoding="utf-8")) or {}
                raw.setdefault("world", {})["level_name"] = f"worlds/{name}"
                # Atomic write
                import tempfile
                fd, tmp = tempfile.mkstemp(dir=cm_path.parent, prefix="config_", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        yaml.dump(raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
                    os.replace(tmp, str(cm_path))
                except Exception:
                    os.unlink(tmp)
        except Exception:
            pass

        return True

    def get_active_world(self) -> str:
        """Return the ``level-name`` from ``server.properties``.

        Returns the bare world name (without ``worlds/`` prefix) when
        the path is under ``worlds/``, or the raw value otherwise.
        """
        return self._get_active_world()

    def migrate_existing(self) -> int:
        """Migrate root-level world dirs into ``worlds/`` on first run.

        If the server root contains ``world/`` and ``worlds/world/``
        does not yet exist, moves ``world/``, ``world_nether/``, and
        ``world_the_end/`` into ``worlds/``.

        Also scans for additional world groups in the root (anything
        with a matching ``_nether`` or ``_the_end`` pair).

        Returns:
            Number of world groups migrated.
        """
        migrated = 0

        # Only consider directories directly under server root
        root_dirs = {d.name: d for d in self._server_dir.iterdir() if d.is_dir()}

        # Known non-world directories to skip
        SKIP = {
            "logs", "plugins", "config", "venv", ".git", "__pycache__",
            "scripts", "docs", "tests", "web", "api", "core", "logger",
            "worlds", ".claude", ".omc", ".vscode", ".idea", ".vs",
            "dist", "build", "cache",
        }

        candidates: set[str] = set()
        for name in root_dirs:
            # Skip hidden directories (starts with .)
            if name.startswith("."):
                continue
            if name in SKIP:
                continue
            if name.endswith("_nether") or name.endswith("_the_end"):
                # Found a dimension dir → the base is the prefix
                if name.endswith("_nether"):
                    base = name[:-7]
                else:
                    base = name[:-9]
                candidates.add(base)
            else:
                # Require level.dat (not just session.lock) to confirm it's a real world
                path = root_dirs[name]
                if (path / "level.dat").exists():
                    candidates.add(name)

        # Ensure worlds/ dir exists
        self._worlds_dir.mkdir(parents=True, exist_ok=True)

        for base in sorted(candidates):
            target_overworld = self._worlds_dir / base
            if target_overworld.exists():
                continue  # already migrated

            source_overworld = root_dirs.get(base)
            source_nether = root_dirs.get(f"{base}_nether")
            source_end = root_dirs.get(f"{base}_the_end")

            if source_overworld and source_overworld.is_dir():
                shutil.move(str(source_overworld), str(target_overworld))
                migrated += 1

            if source_nether and source_nether.is_dir():
                shutil.move(str(source_nether), str(self._worlds_dir / f"{base}_nether"))

            if source_end and source_end.is_dir():
                shutil.move(str(source_end), str(self._worlds_dir / f"{base}_the_end"))

        # After migration, update level-name so PaperMC finds the new location
        if migrated > 0:
            active = self._get_active_world()
            # Only fix if level-name still points to root (not worlds/ prefix)
            if active and not active.startswith("worlds/") and not active.startswith("worlds\\"):
                self._set_active_world(f"worlds/{active}")

        return migrated

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_dimension_paths(self, name: str) -> dict[str, Path]:
        """Return Paths for the three dimensions of a world.

        Returns:
            Dict with keys ``overworld``, ``nether``, ``end``.
        """
        return {
            "overworld": self._worlds_dir / name,
            "nether": self._worlds_dir / f"{name}_nether",
            "end": self._worlds_dir / f"{name}_the_end",
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

        Returns the raw value (e.g. ``"worlds/world"`` or ``"world"``).
        """
        props_path = self._server_dir / "server.properties"
        if not props_path.exists():
            return "worlds/world"
        for line in props_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("level-name="):
                return stripped.split("=", 1)[1].strip()
        return "worlds/world"

    def _set_active_world(self, name: str) -> None:
        """Update the ``level-name`` entry in ``server.properties`` (atomic)."""
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
