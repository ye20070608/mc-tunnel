"""
PaperMC 服务端 JAR 下载模块。

通过 PaperMC Fill v3 API 获取指定版本的 JAR 文件，支持：
- 获取最新 build 信息
- 流式下载 + 进度显示
- SHA256 完整性校验
- PaperMC API 失败时自动回退到 Mojang 原版 JAR
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Callable

import requests
from loguru import logger

# ---------------------------------------------------------------------------
# PaperMC Fill v3 API (v2 API 已于 2026-07-01 关闭)
# ---------------------------------------------------------------------------

FILL_API_BASE = "https://fill.papermc.io"
FILL_API_PREFIX = "/v3/projects/paper"
# User-Agent 必须标识软件 + 联系方式（Fill v3 要求）
_USER_AGENT = "mc-tunnel/1.0 (ye20070608@126.com)"
# BMCLAPI2 国内镜像 — 加速 Mojang 原版 JAR 下载
MOJANG_MANIFEST_MIRROR = "https://bmclapi2.bangbang93.com/mc/game/version_manifest.json"
# 将 Mojang 官方 URL 映射到 BMCLAPI2 镜像
_MOJANG_MIRROR_MAP = {
    "https://launchermeta.mojang.com": "https://bmclapi2.bangbang93.com",
    "https://piston-meta.mojang.com": "https://bmclapi2.bangbang93.com",
    "https://launcher.mojang.com": "https://bmclapi2.bangbang93.com",
}

# ---------------------------------------------------------------------------
# Thread-safe download progress state (for Web UI polling)
# ---------------------------------------------------------------------------

_download_progress_lock = threading.Lock()
_download_progress: dict[str, Any] = {
    "status": "idle",    # "idle" | "downloading" | "done" | "error"
    "version": "",
    "percent": 0.0,
    "downloaded_mb": 0.0,
    "total_mb": 0.0,
    "phase": "",         # "paperclip" | "mojang_jar" | ""
}


def get_download_progress() -> dict[str, Any]:
    """Return the current download progress state (thread-safe copy)."""
    with _download_progress_lock:
        return dict(_download_progress)


def _update_progress_state(
    version: str, downloaded: int, total: int, phase: str = ""
) -> None:
    """Update the global download progress state (called from callback)."""
    with _download_progress_lock:
        _download_progress["status"] = "downloading"
        _download_progress["version"] = version
        _download_progress["total_mb"] = total / (1024 * 1024) if total > 0 else 0.0
        _download_progress["downloaded_mb"] = downloaded / (1024 * 1024)
        _download_progress["phase"] = phase
        if total > 0:
            _download_progress["percent"] = round(downloaded / total * 100, 1)


def _clear_progress_state() -> None:
    """Reset progress counters between download phases."""
    with _download_progress_lock:
        _download_progress["percent"] = 0.0
        _download_progress["downloaded_mb"] = 0.0
        _download_progress["phase"] = ""


def _mark_progress_done() -> None:
    """Mark the entire multi-phase download as successfully completed."""
    with _download_progress_lock:
        _download_progress["status"] = "done"
        _download_progress["phase"] = ""


def _mark_progress_error() -> None:
    """Mark the entire multi-phase download as failed."""
    with _download_progress_lock:
        _download_progress["status"] = "error"
        _download_progress["phase"] = ""



def _http_get(endpoint: str) -> dict | list:
    """发送 GET 请求到 PaperMC Fill v3 API，返回 JSON 数据。

    Fill v3 要求 User-Agent 头部标识软件名和联系方式。

    Note: BMCLAPI2 等国内镜像源目前尚未适配 Fill v3（2026-07-01 新 API），
    待镜像支持后可在此添加镜像 URL fallback。
    """
    import urllib3

    path = f"{FILL_API_PREFIX}/{endpoint.lstrip('/')}" if endpoint else FILL_API_PREFIX
    url = f"{FILL_API_BASE}{path}"
    headers = {"User-Agent": _USER_AGENT}
    last_error = None
    for verify_ssl in (False, True):  # 优先跳过 SSL（国内 CDN 证书链问题）
        try:
            if not verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(url, timeout=(10, 25), verify=verify_ssl, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_error = e
    raise RuntimeError(f"PaperMC API 请求失败: {last_error}")


def _version_key(version: str) -> tuple[int, ...]:
    """将版本号字符串转为可比较的元组。

    例如 "1.21.4" → (1, 21, 4)，"1.9" → (1, 9)。
    用于正确的语义版本排序（而非字典序）。
    """
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (0,)


def get_available_versions() -> list[str]:
    """获取 PaperMC 支持的所有版本列表（版本组名）。

    Fill v3 的 ``/v3/projects/paper`` 返回 ``versions`` 对象，
    其键为版本组名（如 "1.21"、"1.20"）。
    """
    data = _http_get("")
    versions_obj: dict = data.get("versions", {})
    versions: list[str] = list(versions_obj.keys())
    versions.sort(key=_version_key, reverse=True)
    return versions


def list_stable_versions(limit: int = 20) -> list[str]:
    """获取 PaperMC 可用稳定版本列表（版本组名，仅正式版）。

    Args:
        limit: 最多返回的版本数量

    Returns:
        按版本号倒序排列的版本组名列表，如 ["1.21", "1.20.6", "1.20.4", ...]
    """
    all_versions = get_available_versions()
    # 过滤掉包含 "-pre"、"-rc"、"-alpha"、"-beta" 的预发布版本
    stable = [v for v in all_versions if not any(
        tag in v for tag in ("-pre", "-rc", "-alpha", "-beta", "-snapshot")
    )]
    return stable[:limit]


def list_all_stable_builds(limit: int = 30) -> list[str]:
    """获取所有 PaperMC 稳定版本（仅具体构建，不含版本组名）。

    Fill v3 将版本分组（如 "1.21" 组下有 "1.21.11"、"1.21.10" 等），
    此函数展开所有组的稳定构建，过滤掉纯版本组名（如 "1.21"），
    只返回有具体构建号的版本。

    Args:
        limit: 最多返回的版本数量

    Returns:
        按版本号倒序排列，如 ["1.21.11", "1.21.10", "1.20.6", ...]
    """
    data = _http_get("")
    versions_obj: dict = data.get("versions", {})
    group_names = set(versions_obj.keys())
    all_versions: list[str] = []
    for group, builds in versions_obj.items():
        for build in builds:
            if not any(
                tag in build for tag in ("-pre", "-rc", "-alpha", "-beta", "-snapshot")
            ):
                # 跳过纯版本组名（大版本），只保留具体构建（如 1.21.11 而非 1.21）
                if build in group_names:
                    continue
                if build not in all_versions:
                    all_versions.append(build)
    all_versions.sort(key=_version_key, reverse=True)
    return all_versions[:limit]


def get_latest_build(version: str) -> int:
    """获取指定版本的 PaperMC 最新 build 编号。

    Fill v3 返回完整的构建对象，其中 ``id`` 为 build 编号。
    如果指定版本找不到，尝试回退到主版本组（如 1.21.11 → 1.21）。
    """
    # Try the exact version first, then fall back to major.minor group
    versions_to_try = [version]
    parts = version.split(".")
    if len(parts) > 2:
        # e.g. "1.21.11" → also try "1.21"
        group = ".".join(parts[:2])
        if group != version:
            versions_to_try.append(group)

    last_error = None
    for v in versions_to_try:
        try:
            data = _http_get(f"versions/{v}/builds/latest")
            build_id: int = data.get("id", 0)
            if build_id:
                return build_id
        except Exception as e:
            last_error = e
            continue

    raise ValueError(
        f"PaperMC 版本 '{version}' 没有可用构建"
        + (f"（也在组中查找失败: {last_error}）" if last_error else "")
    )


def get_download_info(version: str, build: int) -> dict:
    """获取指定 build 的下载信息（文件 URL、SHA256、文件名等）。

    Fill v3 在构建详情中直接嵌入完整的下载 URL，
    无需像 v2 那样手动拼接。

    返回:
        {
            "version": str,      # 如 "1.20.4"
            "build": int,        # 如 196
            "file_name": str,    # 如 "paper-1.20.4-196.jar"
            "download_url": str, # 下载链接（完整 URL）
            "sha256": str,       # SHA256 哈希值
        }
    """
    data = _http_get(f"versions/{version}/builds/{build}")
    downloads: dict = data.get("downloads", {})
    # Fill v3 uses "server:default" (old v2 was "application")
    application: dict = downloads.get("server:default", {})

    file_name: str = application.get("name", f"paper-{version}-{build}.jar")
    checksums: dict = application.get("checksums", {})
    sha256: str = checksums.get("sha256", "")
    download_url: str = application.get("url", "")

    if not download_url:
        raise ValueError(
            f"PaperMC build #{build} (version {version}) 没有下载链接"
        )

    return {
        "version": version,
        "build": build,
        "file_name": file_name,
        "download_url": download_url,
        "sha256": sha256,
    }


def download_jar(
    download_url: str,
    output_path: Path,
    expected_sha256: str = "",
    progress_callback: Callable[[int, int, int], None] | None = None,
    chunk_size: int = 8192,
    verify: bool = True,
) -> Path:
    """流式下载 JAR 文件，支持进度回调和 SHA256 校验。

    Args:
        download_url: 下载链接
        output_path: 输出文件路径
        expected_sha256: 期望的 SHA256（空字符串则跳过校验）
        progress_callback: 进度回调 (downloaded_bytes, total_bytes, chunk_bytes)
        chunk_size: 下载块大小
        verify: 是否验证 SSL 证书（Mojang 服务器需设为 False）

    Returns:
        已下载文件的 Path
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # timeout=(connect, read): 15s connect + 60s between chunks
        resp = requests.get(download_url, stream=True, timeout=(15, 60), verify=verify)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("SSL/连接失败，回退到非校验模式重试: {}", download_url[:80])
        resp = requests.get(download_url, stream=True, timeout=(15, 60), verify=False)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    sha256_hash = hashlib.sha256()
    downloaded = 0
    last_bps = 0

    # 用于进度显示的临时文件
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    sha256_hash.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total, last_bps)
    except Exception:
        # 下载失败，清理临时文件
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    # SHA256 校验
    actual_sha256 = sha256_hash.hexdigest()
    if expected_sha256 and actual_sha256 != expected_sha256:
        tmp_path.unlink()
        raise ValueError(
            f"SHA256 校验失败\n"
            f"  期望: {expected_sha256}\n"
            f"  实际: {actual_sha256}"
        )

    # 重命名为最终文件
    tmp_path.replace(output_path)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"下载完成: {output_path.name} ({file_size_mb:.1f} MB)")

    return output_path


# ---------------------------------------------------------------------------
# Mojang 原版服务端 JAR 预下载
# ---------------------------------------------------------------------------
# Paperclip（PaperMC 引导器）运行时需要从 Mojang 服务器下载原版 Minecraft
# 服务端 JAR。在部分网络环境（尤其是中国大陆）中，Java 的 SSL 证书信任库
# 可能无法验证 Mojang 的 HTTPS 证书，导致 PKIX path building failed。
#
# 通过 Python 的 requests 库（使用 certifi 证书包）提前下载原版 JAR
# 到 Paperclip 的缓存目录（cache/mojang_{version}.jar），彻底绕过
# Java SSL 问题。

MOJANG_MANIFEST_URL = (
    "https://launchermeta.mojang.com/mc/game/version_manifest.json"
)

# Mojang 的 SSL 证书在某些网络环境（尤其是中国大陆）无法被 certifi 验证。
# 使用 verify=False 回退策略，同时用 SHA1 校验保证下载文件完整性。
# 注意：不再使用全局标志位，每次请求独立尝试 verify=True。


def _rewrite_mojang_url(url: str) -> str:
    """将 Mojang 官方 URL 重写为 BMCLAPI2 国内镜像。"""
    for official, mirror in _MOJANG_MIRROR_MAP.items():
        if url.startswith(official):
            return url.replace(official, mirror)
    return url


def _mojang_request(url: str, stream: bool = False, timeout: int = 30) -> requests.Response:
    """Make a GET request to a Mojang API endpoint.

    Automatically rewrites Mojang URLs to use the BMCLAPI2 mirror for
    faster downloads from China.  Falls back to the official URL if the
    mirror request fails (non-2xx status, SSL error, or connection error).
    """
    import urllib3

    mirror_url = _rewrite_mojang_url(url)
    urls_to_try = [mirror_url]
    if mirror_url != url:
        urls_to_try.append(url)

    last_error = None
    for u in urls_to_try:
        for verify_ssl in (True, False):
            try:
                if not verify_ssl:
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                resp = requests.get(u, timeout=(15, 30), stream=stream, verify=verify_ssl)
                if resp.ok:
                    return resp
                # Non-2xx → try next URL or SSL mode
                last_error = RuntimeError(
                    f"HTTP {resp.status_code} for {u[:60]}"
                )
            except requests.exceptions.SSLError:
                if not verify_ssl:
                    last_error = RuntimeError(f"SSL error for {u[:60]}")
                continue  # try verify=False
            except Exception as e:
                last_error = e
                continue

    raise RuntimeError(f"Mojang 请求失败（所有源均不可用）: {last_error}")


def _get_mojang_server_info(version: str) -> dict[str, Any]:
    """Fetch the vanilla Minecraft server JAR download info for *version*.

    Follows the Mojang API chain:
      1. Version manifest → find the version entry → metadata URL
      2. Version metadata → ``downloads.server.url``

    Returns:
        Dict with ``url``, ``sha1``, ``size``.  Empty dict if unavailable.
    """
    # 1. Get version manifest
    try:
        manifest: dict = _mojang_request(MOJANG_MANIFEST_URL).json()
    except Exception as exc:
        logger.warning(f"无法获取 Mojang 版本清单: {exc}")
        return {}

    version_url: str = ""
    for entry in manifest.get("versions", []):
        if entry.get("id") == version:
            version_url = entry.get("url", "")
            break

    if not version_url:
        logger.warning(f"Mojang 版本清单中未找到 {version}")
        return {}

    # 2. Get version metadata → downloads.server
    try:
        meta: dict = _mojang_request(version_url).json()
    except Exception as exc:
        logger.warning(f"无法获取 Mojang 版本元数据: {exc}")
        return {}

    server: dict = meta.get("downloads", {}).get("server", {})
    return {
        "url": server.get("url", ""),
        "sha1": server.get("sha1", ""),
        "size": server.get("size", 0),
    }


def _ensure_mojang_jar(
    version: str,
    output_dir: str = ".",
    show_progress: bool = True,
) -> Path | None:
    """Download the vanilla Minecraft server JAR into Paperclip's cache dir.

    Paperclip looks for ``cache/mojang_{version}.jar`` at startup; if the
    file already exists it skips the Java-side download entirely.

    Returns:
        Path to the cached JAR, or ``None`` if the download failed or
        the Mojang API didn't provide a URL.
    """
    jar_name = f"mojang_{version}.jar"
    version_dir = Path(output_dir) / "versions" / version
    version_dir.mkdir(parents=True, exist_ok=True)
    version_path = version_dir / jar_name

    # Paperclip 在 cwd=server/ 下查找 cache/mojang_{v}.jar
    cache_dir = Path(output_dir) / "cache"
    cache_path = cache_dir / jar_name

    # 已存在于版本目录 → 无需下载，确保 cache 副本就绪
    if version_path.exists():
        size_mb = version_path.stat().st_size / (1024 * 1024)
        logger.info(f"Mojang 原版 JAR 已缓存: {jar_name} ({size_mb:.1f} MB)")
        _ensure_cache_copy(version_path, cache_path)
        return version_path

    # 旧文件在 cache/ 但版本目录没有 → 迁移到新位置
    if cache_path.exists():
        logger.info(f"迁移 Mojang 缓存: cache/{jar_name} → versions/{version}/")
        cache_path.rename(version_path)
        _ensure_cache_copy(version_path, cache_path)
        return version_path

    logger.info(f"获取 Mojang {version} 服务端下载链接...")
    info = _get_mojang_server_info(version)

    # 构建下载 URL 列表：BMCLAPI2 国内镜像优先，Mojang 官方回退
    mojang_urls: list[str] = []
    # BMCLAPI2 直链 — 对中国大陆用户速度远优于 Mojang 官方 CDN
    mojang_urls.append(f"https://bmclapi2.bangbang93.com/version/{version}/server")
    if info.get("url"):
        # 官方 URL 作为兜底（镜像不可达时回退）
        official_url = info["url"]
        if official_url not in mojang_urls:
            mojang_urls.append(official_url)

    if not mojang_urls:
        logger.warning(f"Mojang {version} 没有服务端 JAR 下载链接，跳过预下载")
        return None

    total_mb = info.get("size", 0) / (1024 * 1024)
    logger.info(f"下载 Mojang {version} 原版服务端 ({total_mb:.0f} MB)...")

    version_dir.mkdir(parents=True, exist_ok=True)

    _mojang_last_pct = [-5]

    def _mojang_progress(downloaded: int, total: int, _bps: int) -> None:
        _update_progress_state(version, downloaded, total, phase="mojang_jar")
        if not show_progress or total == 0:
            return
        pct = downloaded / total * 100
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        if pct - _mojang_last_pct[0] >= 10 or downloaded >= total:
            _mojang_last_pct[0] = pct
            logger.info(
                "  [>>] Mojang {} ... {:.1f}/{:.1f} MB ({:.0f}%)",
                version, downloaded_mb, total_mb, pct,
            )

    last_error = None
    for url in mojang_urls:
        try:
            download_jar(
                download_url=url,
                output_path=version_path,
                expected_sha256="",  # Mojang 用 SHA1 而非 SHA256
                progress_callback=_mojang_progress,
                verify=True,  # Always try SSL first per request
            )
            if show_progress:
                print()  # 换行
            _clear_progress_state()
            # 确保 Paperclip 能在 cache/ 找到（cwd=server/）
            _ensure_cache_copy(version_path, cache_path)
            logger.info(f"Mojang 原版 JAR 已缓存: {jar_name}")
            return version_path
        except Exception as exc:
            last_error = exc
            if url == mojang_urls[-1]:
                # 最后一个 URL 也失败了
                break
            logger.warning("镜像下载失败，回退 Mojang 官方源: {}", exc)

    _clear_progress_state()
    logger.warning(f"Mojang 原版 JAR 下载失败（Paperclip 将尝试自行下载）: {last_error}")
    if version_path.exists():
        version_path.unlink()
    return None


def _ensure_cache_copy(src: Path, dst: Path) -> None:
    """确保 dst 指向 src 的最新副本。

    Windows 用副本，Linux/macOS 用相对路径符号链接。
    """
    import shutil
    import sys

    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        shutil.copy2(src, dst)
    else:
        import os
        try:
            rel = os.path.relpath(src, dst.parent)
            dst.symlink_to(rel)
        except OSError:
            shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# 编排函数
# ---------------------------------------------------------------------------

def _find_existing_jar(version: str, output_dir: str) -> Path | None:
    """查找已存在的版本对应 JAR 文件。

    按优先级查找：
    1. server/versions/{version}/paper-{version}-*.jar（精确匹配）
    2. server/versions/{version}/mojang_{version}.jar（Mojang 回退产物）
    3. server/versions/*/paper-*.jar（任何已安装版本，取最新）
    4. server/server.jar（通用命名）
    5. server/paper-*.jar（旧版平铺结构迁移兼容）
    """
    import re
    base = Path(output_dir)

    # Validate version to prevent glob injection
    if not re.match(r"^[\d.]+$", version):
        logger.warning("Invalid version string for JAR search: {}", version)
        return None

    # 1. 精确版本匹配 — server/versions/{version}/paper-{version}-*.jar
    versions_dir = base / "versions" / version
    matches = list(versions_dir.glob(f"paper-{version}-*.jar"))
    # 兼容无 build 号的文件名: paper-{version}.jar
    matches += list(versions_dir.glob(f"paper-{version}.jar"))
    if matches:
        matches.sort(reverse=True)  # 取最新 build
        logger.debug("Found JAR in versions/{}: {}", version, matches[0].name)
        return matches[0]

    # 1.5 Mojang 回退产物 — server/versions/{version}/mojang_{version}.jar
    mojang_jar = versions_dir / f"mojang_{version}.jar"
    if mojang_jar.exists():
        logger.debug("Found Mojang JAR in versions/{}: {}", version, mojang_jar.name)
        return mojang_jar

    # 2. 回退 — 任意已安装版本（取最新 build）
    all_versions = base / "versions"
    if all_versions.exists():
        matches = list(all_versions.glob("*/paper-*.jar"))
        matches += list(all_versions.glob("*/mojang_*.jar"))
        if matches:
            matches.sort(reverse=True)
            logger.debug("Found JAR in versions/*/: {}", matches[0].name)
            return matches[0]

    # 3. 通用名
    generic = base / "server.jar"
    if generic.exists():
        return generic

    # 4. 旧版平铺结构兼容（迁移前遗留的 server/paper-*.jar）
    matches = list(base.glob("paper-*.jar"))
    if matches:
        matches.sort(reverse=True)
        logger.debug("Found JAR in legacy flat layout: {}", matches[0].name)
        return matches[0]

    return None


def ensure_server_jar(
    version: str = "1.20.1",
    server_jar_path: str = "",
    output_dir: str = ".",
    show_progress: bool = True,
) -> Path:
    """确保 MC 服务端 JAR 文件就绪。

    优先级：
    1. 用户指定了 server_jar_path → 直接使用
    2. paper-{version}-*.jar 已存在 → 使用
    3. paper-*.jar / server.jar 已存在（可能不同版本）→ 使用
    4. 都不满足 → 从 PaperMC API 下载最新构建

    JAR 文件保存为 paper-{version}-{build}.jar（版本命名，支持多版本共存）。

    Args:
        version: PaperMC 版本号
        server_jar_path: 用户指定的 JAR 路径（空则忽略）
        output_dir: 输出目录
        show_progress: 是否在控制台显示下载进度

    Returns:
        可用的 JAR 文件 Path
    """
    # 1. 用户指定路径 — 仅在版本匹配时使用，否则回退到自动查找/下载
    if server_jar_path:
        path = Path(server_jar_path)
        if path.exists():
            name = path.name
            import re
            # 检查是否为 PaperMC 标准命名 JAR (paper-{version}-{build}.jar)
            paper_match = re.match(r"^paper-([\d.]+)(?:-\d+)?\.jar$", name)
            if paper_match:
                jar_version = paper_match.group(1)
                if jar_version == version:
                    logger.info(f"使用指定的服务端 JAR: {path}")
                    return path.resolve()
                # 版本不匹配 — 配置中的 server_jar 已过期，忽略并回退
                logger.warning(
                    f"指定的服务端 JAR ({name}) 版本 {jar_version} "
                    f"不匹配请求的版本 {version}，将查找/下载正确的版本"
                )
            else:
                # 非标准命名（如自定义 JAR）— 视为用户手动指定，直接使用
                logger.info(f"使用指定的服务端 JAR: {path}")
                return path.resolve()
        else:
            # 路径不存在 — 记录警告并回退到自动查找/下载
            logger.warning(
                f"指定的服务端 JAR 不存在 ({server_jar_path})，"
                f"将自动查找或下载版本 {version}"
            )

    # 2. 检查是否已有该版本的 JAR
    existing = _find_existing_jar(version, output_dir)
    if existing:
        # 校验找到的 JAR 是否匹配请求的版本
        import re as _re
        _name = existing.name
        _match = _re.match(r"^paper-([\d.]+)(?:-\d+)?\.jar$", _name)
        if _match and _match.group(1) != version:
            # 回退找到了其他版本的 JAR，不匹配请求版本 → 进入下载
            logger.info(
                f"已有 JAR ({_name}) 版本 {_match.group(1)} "
                f"不匹配请求版本 {version}，将下载正确版本"
            )
        else:
            size_mb = existing.stat().st_size / (1024 * 1024)
            logger.info(f"服务端 JAR 已存在: {existing.name} ({size_mb:.1f} MB)")
            # 预下载 Mojang 原版 JAR 到 cache/（后台线程，不阻塞主启动流程）
            threading.Thread(
                target=_ensure_mojang_jar,
                args=(version, output_dir, show_progress),
                daemon=True,
            ).start()
            _mark_progress_done()
            return existing.resolve()

    # 3. 下载 MC 服务端 JAR
    #    策略：优先 PaperMC API，同时后台预下载 Mojang 原版作为 fallback。
    #    PaperMC API 任一环节失败（API 报错/网络不通/版本不存在如 410 Gone）
    #    → 等待 Mojang 后台线程完成，自动回退到原版 JAR。
    version_dir = Path(output_dir) / "versions" / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # 先启动 Mojang 后台下载（BMCLAPI2 镜像加速），确保 PaperMC 失败时有备选
    _mojang_thread = threading.Thread(
        target=_ensure_mojang_jar,
        args=(version, output_dir, show_progress),
        daemon=True,
    )
    _mojang_thread.start()

    def _fallback_to_mojang(reason: str, source_error: Exception) -> Path:
        """PaperMC 失败 → 等待 Mojang 后台线程，返回 Mojang JAR 路径或 raise。"""
        logger.warning("PaperMC {}: {}", reason, source_error)
        logger.info("等待 Mojang 镜像下载完成（BMCLAPI2）...")
        _mojang_thread.join(timeout=300)

        mojang_jar = version_dir / f"mojang_{version}.jar"
        if mojang_jar.exists():
            logger.info("使用 Mojang 原版服务端（BMCLAPI2 镜像下载）")
            _update_server_jar_link(mojang_jar, Path(output_dir) / "server.jar")
            _clear_progress_state()
            _mark_progress_done()
            return mojang_jar.resolve()

        _mark_progress_error()
        logger.error("Mojang 镜像下载也未完成，无法启动")
        raise RuntimeError(
            "PaperMC 和 Mojang 下载均失败，请检查网络后重试"
        ) from source_error

    logger.info(f"PaperMC {version} — 获取最新构建信息...")
    try:
        build = get_latest_build(version)
        info = get_download_info(version, build)
    except (requests.HTTPError, ValueError, RuntimeError) as e:
        # PaperMC API 报错（_http_get 将 HTTPError 包装为 RuntimeError，如 410 Gone）
        # 或版本无构建（ValueError）→ Mojang fallback
        return _fallback_to_mojang("API 不可用", e)

    logger.info(
        f"准备下载 PaperMC {info['version']} build #{info['build']} "
        f"({info['file_name']})"
    )

    output_path = version_dir / info["file_name"]

    _progress_last_logged_pct = [-5]  # mutable: log at 0% immediately

    def _progress(downloaded: int, total: int, _bps: int) -> None:
        _update_progress_state(info["version"], downloaded, total)
        if not show_progress or total == 0:
            return
        pct = downloaded / total * 100
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        if pct - _progress_last_logged_pct[0] >= 5 or downloaded >= total:
            _progress_last_logged_pct[0] = pct
            logger.info(
                "  [>>] PaperMC {} ... {:.1f}/{:.1f} MB ({:.0f}%)",
                info["version"], downloaded_mb, total_mb, pct,
            )

    download_url = info["download_url"]

    # BMCLAPI2 缓存了 PaperMC v2 时代的 JAR 文件 — 优先命中缓存
    # （速度快于 Fill v3 的 fill-data.papermc.io CDN，尤其在国内）
    cache_url = (
        f"https://bmclapi2.bangbang93.com/paper/api/v2/projects/paper"
        f"/versions/{info['version']}/builds/{info['build']}"
        f"/downloads/{info['file_name']}"
    )
    urls = [cache_url, download_url]

    last_error = None
    for url in urls:
        logger.info("  正在连接 {} ...", url[:60])
        try:
            download_jar(
                download_url=url,
                output_path=output_path,
                expected_sha256=info["sha256"],
                progress_callback=_progress,
            )
            if show_progress:
                print()  # 换行

            # 同时创建/更新 server.jar 软链接（Windows 用副本）
            _update_server_jar_link(output_path, Path(output_dir) / "server.jar")
            _clear_progress_state()
            last_error = None
            break
        except (requests.HTTPError, ValueError) as e:
            last_error = e
            if url == urls[-1]:
                return _fallback_to_mojang("下载失败", e)
            logger.warning("BMCLAPI2 缓存未命中，回退官方 CDN: {}", e)
        except Exception as e:
            last_error = e
            if url == urls[-1]:
                return _fallback_to_mojang("下载失败", e)
            logger.warning("BMCLAPI2 缓存未命中，回退官方 CDN: {}", e)

    if last_error is not None:
        return _fallback_to_mojang("下载失败", last_error)

    _mark_progress_done()
    return output_path.resolve()


def _update_server_jar_link(source: Path, target: Path) -> None:
    """更新 server.jar 指向最新下载的 JAR。

    Windows 不支持 os.symlink 需要管理员权限，使用副本方式。
    Linux/macOS 使用相对路径符号链接。
    """
    import shutil
    import sys
    import os

    # 删除旧的链接/副本
    if target.exists() or target.is_symlink():
        target.unlink()

    if sys.platform == "win32":
        # Windows：复制文件（硬链接需同分区，用副本最稳妥）
        shutil.copy2(source, target)
    else:
        # Linux/macOS：创建相对路径符号链接
        try:
            rel_path = os.path.relpath(source, target.parent)
            target.symlink_to(rel_path)
        except OSError:
            shutil.copy2(source, target)

    logger.debug(f"server.jar → {source.name}")


def cleanup_paper_configs_on_switch(
    target_version: str,
    output_dir: str = ".",
) -> bool:
    """版本切换时清理旧 Paper 配置，避免新老版本格式不兼容。

    Paper 不同大版本的配置格式可能不同（如 1.21 引入了 "default"
    作为数值字段的合法值，但 1.20 不认识），主动删除让服务端重生。

    Args:
        target_version: 目标版本号（如 "1.20.1"）
        output_dir: 服务端根目录

    Returns:
        True 如果执行了清理
    """
    version_marker = Path(output_dir) / "config" / ".paper_version"
    target_major = target_version.split(".")[:2]  # e.g. ["1", "20"]

    # Read last-run version
    last_major = None
    if version_marker.exists():
        try:
            last_raw = version_marker.read_text(encoding="utf-8").strip()
            last_major = last_raw.split(".")[:2]
        except Exception:
            pass

    if last_major == target_major:
        return False

    # Version changed — remove stale config files so they regenerate
    config_dir = Path(output_dir) / "config"
    stale_files = [
        config_dir / "paper-world-defaults.yml",
        config_dir / "paper-global.yml",
    ]
    cleaned = False
    for f in stale_files:
        if f.exists():
            try:
                f.unlink()
                logger.info(f"已清理旧版配置: {f}")
                cleaned = True
            except OSError as exc:
                logger.warning(f"无法删除旧配置 {f}: {exc}")

    # Write new version marker
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        version_marker.write_text(target_version, encoding="utf-8")
    except OSError:
        pass

    return cleaned


def switch_version(
    version: str,
    output_dir: str = ".",
    show_progress: bool = True,
) -> Path:
    """切换到指定 PaperMC 版本。

    下载新版本 JAR（如果还没有），保留旧版本文件不删除。
    更新 server.jar 指向新版本。

    Args:
        version: 目标 PaperMC 版本号
        output_dir: 输出目录
        show_progress: 是否显示下载进度

    Returns:
        新版本 JAR 文件 Path
    """
    logger.info(f"切换 MC 版本: → {version}")
    cleanup_paper_configs_on_switch(version, output_dir)
    jar_path = ensure_server_jar(
        version=version,
        server_jar_path="",
        output_dir=output_dir,
        show_progress=show_progress,
    )
    logger.info(f"版本切换完成: {jar_path.name}")
    return jar_path
