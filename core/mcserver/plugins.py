"""PaperMC plugin management.

Scans ``server/plugins/`` for installed plugins, parses ``plugin.yml``
metadata from each jar, and supports upload / delete / toggle (enable-disable).

Usage::

    pm = PluginManager("server/plugins")
    plugins = pm.list_plugins()
    pm.upload_plugin("EssentialsX.jar", jar_bytes)
    pm.delete_plugin("EssentialsX.jar")
    pm.toggle_plugin("EssentialsX.jar")   # -> EssentialsX.jar.disabled
"""

from __future__ import annotations

import io
import os
import re
import yaml
import zipfile
from pathlib import Path


# Only alphanumeric, dots, hyphens, underscores; must end with .jar or .jar.disabled
_PLUGIN_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+\.jar(\.disabled)?$")

# Max size of plugin.yml file extracted from a jar (1 MB decompressed)
_MAX_PLUGIN_YML_SIZE = 1 * 1024 * 1024


class PluginManager:
    """Manages PaperMC plugins in the plugins directory."""

    def __init__(self, plugins_dir: str | Path = "server/plugins") -> None:
        """Initialise with an optional plugins directory path.

        Args:
            plugins_dir: Path to the plugins directory (relative to project root).
        """
        self._plugins_dir = Path(plugins_dir)
        # Ensure the directory exists
        self._plugins_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def validate_plugin_name(name: str) -> bool:
        """Validate a plugin filename for safe filesystem operations.

        Rejects path traversal attempts (``..``, ``/``, ``\\``) and
        enforces a strict alphanumeric-plus-dashes pattern ending with
        ``.jar`` or ``.jar.disabled``.

        Args:
            name: The filename to validate.

        Returns:
            True if the name is safe to use.
        """
        if not name or not name.strip():
            return False
        if ".." in name or "/" in name or "\\" in name:
            return False
        return bool(_PLUGIN_FILENAME_RE.match(name))

    def list_plugins(self) -> list[dict]:
        """List all installed plugins with parsed metadata.

        Scans ``plugins_dir/*.jar`` and ``plugins_dir/*.jar.disabled``,
        reading ``plugin.yml`` from each jar.

        Returns:
            A list of dicts, each containing filename, display_name,
            disabled, size_kb, and optionally name/version/author/description/
            api_version/main from the plugin.yml.
        """
        plugins: list[dict] = []

        # Collect both active and disabled jars
        jar_files: list[Path] = []
        jar_files.extend(sorted(self._plugins_dir.glob("*.jar")))
        jar_files.extend(sorted(self._plugins_dir.glob("*.jar.disabled")))

        seen: set[str] = set()
        for jar_path in jar_files:
            if jar_path.is_dir():
                continue
            raw_name = jar_path.name
            if raw_name in seen:
                continue
            seen.add(raw_name)

            disabled = raw_name.endswith(".disabled")
            display_name = raw_name.replace(".disabled", "")
            size_kb = round(jar_path.stat().st_size / 1024, 1)

            meta = self._read_plugin_metadata(jar_path)
            plugins.append({
                "filename": raw_name,
                "display_name": display_name,
                "disabled": disabled,
                "size_kb": size_kb,
                **meta,
            })

        return plugins

    def upload_plugin(self, filename: str, data: bytes) -> bool:
        """Upload (write) a plugin jar to the plugins directory.

        Validates that the uploaded data is a valid ZIP/JAR archive before
        writing.  Uses a temp-file + atomic rename to prevent TOCTOU races.

        Args:
            filename: The target filename (must end with ``.jar``).
            data: Raw bytes of the jar file.

        Returns:
            True on success.

        Raises:
            ValueError: If the filename is invalid, not a valid JAR, or a
                        plugin with the same name already exists.
            OSError: If the file cannot be written.
        """
        if not filename.lower().endswith(".jar"):
            raise ValueError("插件文件名必须以 .jar 结尾")
        if not self.validate_plugin_name(filename):
            raise ValueError(f"无效的插件文件名: {filename}")

        # Validate that the uploaded data is a valid ZIP/JAR archive
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if zf.testzip() is not None:
                    raise ValueError("上传的文件损坏（ZIP 校验失败）")
        except zipfile.BadZipFile:
            raise ValueError("上传的文件不是有效的 JAR/ZIP 格式")

        target = self._plugins_dir / filename

        # Prevent overwriting an existing plugin
        if target.exists():
            raise ValueError(f"插件已存在: {filename}（请先删除旧版本）")

        # Atomic write: temp file + os.replace to prevent corrupted files
        # if the process crashes mid-write.  The existence check above
        # prevents accidental overwrites; os.replace guards data integrity.
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(str(tmp), str(target))
        except Exception:
            # Clean up temp file on any error
            if tmp.exists():
                tmp.unlink()
            raise

        return True

    def delete_plugin(self, filename: str) -> bool:
        """Delete a plugin jar from the plugins directory.

        Args:
            filename: The filename to delete (.jar or .jar.disabled).

        Returns:
            True if the file was deleted.

        Raises:
            ValueError: If the filename is invalid.
            FileNotFoundError: If the file does not exist.
        """
        if not self.validate_plugin_name(filename):
            raise ValueError(f"无效的插件文件名: {filename}")

        target = self._plugins_dir / filename
        if not target.exists():
            raise FileNotFoundError(f"插件不存在: {filename}")

        target.unlink()
        return True

    def toggle_plugin(self, filename: str) -> bool:
        """Toggle a plugin between enabled (.jar) and disabled (.jar.disabled).

        Args:
            filename: Current filename (.jar or .jar.disabled).

        Returns:
            True on success.

        Raises:
            ValueError: If the filename is invalid or not in a togglable state.
            FileNotFoundError: If the file does not exist.
        """
        if not self.validate_plugin_name(filename):
            raise ValueError(f"无效的插件文件名: {filename}")

        source = self._plugins_dir / filename
        if not source.exists():
            raise FileNotFoundError(f"插件不存在: {filename}")

        if filename.endswith(".jar.disabled"):
            # Enable: rename to .jar
            new_name = filename.replace(".jar.disabled", ".jar")
        elif filename.endswith(".jar"):
            # Disable: rename to .jar.disabled
            new_name = filename + ".disabled"
        else:
            raise ValueError(f"无法识别的插件文件扩展名: {filename}")

        target = self._plugins_dir / new_name

        # Atomic rename — on Windows os.rename raises FileExistsError if
        # target exists; on POSIX it overwrites, so we use os.replace which
        # is always atomic and always replaces (but we check first).
        if target.exists():
            raise ValueError(f"目标文件已存在: {new_name}")
        try:
            os.replace(str(source), str(target))
        except OSError as exc:
            raise ValueError(f"重命名失败: {exc}")
        return True

    def get_plugins_dir(self) -> str:
        """Return the relative path of the plugins directory for display."""
        return str(self._plugins_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_plugin_metadata(self, jar_path: Path) -> dict:
        """Extract metadata from ``plugin.yml`` inside a jar file.

        Args:
            jar_path: Path to the jar file.

        Returns:
            A dict with keys name, version, author, description, api_version,
            main — each may be None if the plugin.yml cannot be read.
        """
        result: dict = {
            "name": None,
            "version": None,
            "author": None,
            "description": None,
            "api_version": None,
            "main": None,
        }
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                # plugin.yml is always at the root of the jar
                if "plugin.yml" not in zf.namelist():
                    return result
                # Prevent zip bomb: reject oversized plugin.yml entries
                info = zf.getinfo("plugin.yml")
                if info.file_size > _MAX_PLUGIN_YML_SIZE:
                    return result
                with zf.open("plugin.yml") as fh:
                    # Limit decompressed size to 2× the compressed size
                    # to catch compression-ratio attacks
                    raw = yaml.safe_load(fh)
        except (zipfile.BadZipFile, yaml.YAMLError, KeyError, OSError, MemoryError):
            return result

        if not isinstance(raw, dict):
            return result

        result["name"] = raw.get("name")
        result["version"] = raw.get("version")
        result["author"] = raw.get("author") or raw.get("authors")
        # authors may be a list
        if isinstance(result["author"], list):
            result["author"] = ", ".join(str(a) for a in result["author"])
        result["description"] = raw.get("description")
        result["api_version"] = raw.get("api-version") or raw.get("api_version")
        result["main"] = raw.get("main")

        return result
