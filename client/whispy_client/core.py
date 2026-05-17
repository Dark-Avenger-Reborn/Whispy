"""
whispy_client — Zero-dependency Python client for the Whispy CDN.

Usage:
    from whispy_client import remote

    requests = remote("requests")
    numpy = remote("numpy", version="1.26.4")
    bs4 = remote("beautifulsoup4", module="bs4", deps=True)
"""

# ALPHA KNOWN LIMITATIONS:
# - No sandboxing or namespace isolation; imported code runs with full process privileges.
# - No dependency conflict resolution; imports follow normal Python semantics.
# - No auth or multi-tenant access control; trust the configured server.
# - No signed package verification beyond the server-provided archive.

from __future__ import annotations

import atexit
import importlib
import io
import json
import platform
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import warnings
from typing import Optional

__version__ = "1.1.0"
__all__ = ["remote", "configure", "whispy_cleanup", "WhispyError"]

# ---------------------------------------------------------------------------
# Default CDN host — users can override via configure() or WHISPY_HOST env var
# ---------------------------------------------------------------------------
import os as _os
_DEFAULT_HOST = _os.environ.get("WHISPY_HOST", "https://whispycdn.dev")

_config = {
    "host": _DEFAULT_HOST,
    "deps": False,
    "verbose": False,
}

# Tracks live TemporaryDirectory objects so they stay alive until explicit cleanup.
_live_tmpdirs: list[tempfile.TemporaryDirectory] = []


class WhispyError(RuntimeError):
    pass


def whispy_cleanup() -> None:
    """Explicitly clean up all Whispy temporary directories."""
    while _live_tmpdirs:
        tmpdir = _live_tmpdirs.pop()
        _remove_sys_path_entries_under(tmpdir.name)
        tmpdir.cleanup()


atexit.register(whispy_cleanup)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def configure(
    *,
    host: Optional[str] = None,
    deps: Optional[bool] = None,
    verbose: Optional[bool] = None,
) -> None:
    """
    Configure Whispy globally.

    Args:
        host:    CDN base URL, e.g. "http://localhost:5000" for local dev.
        deps:    If True, automatically fetch dependencies alongside packages.
        verbose: If True, print progress messages.
    """
    if host is not None:
        _config["host"] = host.rstrip("/")
    if deps is not None:
        _config["deps"] = deps
    if verbose is not None:
        _config["verbose"] = verbose


def remote(
    package: str,
    *,
    module: Optional[str] = None,
    version: Optional[str] = None,
    deps: Optional[bool] = None,
    host: Optional[str] = None,
) -> object:
    """
    Import a package from the Whispy CDN at runtime.

    Args:
        package: Package name as on PyPI, e.g. "requests" or "numpy"
        module:  Import name if different from package name.
                 e.g. remote("beautifulsoup4", module="bs4")
        version: Version string, e.g. "2.31.0" or "1.26.4"
        deps:    Fetch dependencies too. Overrides global configure() setting.
        host:    CDN host override for this call only.

    Returns:
        The imported module object.

    Example:
        requests = remote("requests")
        print(requests.get("https://httpbin.org/get").status_code)
    """
    pkg_name = _parse_package_spec(package)
    resolved_version = version
    resolved_module = module or pkg_name
    resolved_host = (host or _config["host"]).rstrip("/")
    resolved_deps = _config["deps"] if deps is None else deps
    verbose = _config["verbose"]

    if resolved_version is None:
        # Alpha reminder: unpinned imports are convenient, but they are not reproducible.
        warnings.warn(
            f"Whispy is fetching the latest available version of '{pkg_name}'. "
            "Pin version='...' for reproducible imports.",
            UserWarning,
            stacklevel=2,
        )

    # Return from sys.modules if already loaded
    if resolved_module in sys.modules:
        return sys.modules[resolved_module]

    if verbose:
        version_label = f"=={resolved_version}" if resolved_version else ""
        dep_label = "on" if resolved_deps else "off"
        print(
            f"🌀 Whispy: fetching {pkg_name}{version_label} "
            f"(module={resolved_module}, deps={dep_label})"
        )

    tags = _compute_tags()
    params = {
        "name": pkg_name,
        "tags": ",".join(tags),
        "deps": "1" if resolved_deps else "0",
    }
    if resolved_version:
        params["version"] = resolved_version

    url = f"{resolved_host}/get_package?" + urllib.parse.urlencode(params)

    try:
        data = _fetch_bytes(url, verbose=verbose)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            payload = json.loads(body)
            msg = payload.get("error") or payload.get("message") or body
        except Exception:
            msg = body or e.reason or "unknown server response"

        if e.code == 404:
            raise WhispyError(
                f"Package '{pkg_name}' was not found on Whispy server {resolved_host}. {msg}"
            ) from e
        if 500 <= e.code < 600:
            raise WhispyError(
                f"Whispy server error while fetching '{pkg_name}' from {resolved_host} "
                f"(HTTP {e.code}): {msg}. Try again later or check server logs."
            ) from e

        raise WhispyError(
            f"Whispy request for '{pkg_name}' failed with HTTP {e.code}: {msg}"
        ) from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        reason_text = str(reason)
        if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in reason_text.lower():
            raise WhispyError(
                f"Whispy request to {resolved_host} timed out while fetching '{pkg_name}'. "
                "Check network connectivity or increase the server timeout."
            ) from e
        raise WhispyError(
            f"Could not connect to Whispy server at {resolved_host} for '{pkg_name}': {reason_text}"
        ) from e
    except Exception as e:
        raise WhispyError(
            f"Unexpected Whispy client failure while fetching '{pkg_name}' from {resolved_host}: {e}"
        ) from e

    # Extract into a TemporaryDirectory that lives for the process lifetime
    tmpdir = tempfile.TemporaryDirectory(prefix="whispy_", ignore_cleanup_errors=True)
    _live_tmpdirs.append(tmpdir)

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmpdir.name)
    except zipfile.BadZipFile as e:
        _cleanup_tmpdir(tmpdir)
        raise WhispyError(
            f"Whispy server returned a malformed archive for '{pkg_name}' from {resolved_host}."
        ) from e

    if tmpdir.name not in sys.path:
        _insert_sys_path_safely(tmpdir.name)

    if verbose:
        print(f"✅ Whispy: imported {resolved_module} from {tmpdir.name}")

    try:
        return importlib.import_module(resolved_module)
    except ModuleNotFoundError as e:
        # Try to find the module in subdirectories (helps with complex wheel structures)
        found_module = _find_and_import_module(resolved_module, tmpdir.name, verbose)
        if found_module is not None:
            return found_module
        
        # If not found, provide detailed diagnostics
        import os
        extracted_items = []
        try:
            for item in os.listdir(tmpdir.name):
                item_path = os.path.join(tmpdir.name, item)
                if os.path.isdir(item_path):
                    extracted_items.append(f"  [DIR]  {item}/")
                else:
                    extracted_items.append(f"  [FILE] {item}")
        except Exception:
            extracted_items.append("  (could not list directory)")
        
        extracted_str = "\n".join(extracted_items[:20])  # Show first 20 items
        if len(extracted_items) > 20:
            extracted_str += f"\n  ... and {len(extracted_items) - 20} more items"
        
        missing_name = getattr(e, "name", None)
        missing_is_dependency = bool(missing_name and missing_name != resolved_module)

        guidance: list[str] = []
        if missing_is_dependency and missing_name:
            if resolved_deps:
                guidance.append(
                    f"Dependency '{missing_name}' is missing even though deps=True was requested."
                )
                guidance.append(
                    "The server bundle may be incomplete for this platform/version combination."
                )
            else:
                guidance.append(
                    f"Missing dependency '{missing_name}' detected. Retry with deps=True "
                    f"or call configure(deps=True) first."
                )
        else:
            guidance.append(
                f"Module '{resolved_module}' was not importable from the downloaded package."
            )
            guidance.append(
                "If the import name differs from the package name, pass module='...'."
            )

        guidance_text = "\n".join(guidance)
        dep_label = "on" if resolved_deps else "off"

        # If the import failed, release just this tempdir so a broken extract does not linger.
        _cleanup_tmpdir(tmpdir)

        raise WhispyError(
            f"Package '{pkg_name}' was downloaded but import failed for module '{resolved_module}'.\n"
            f"Reason: {e}\n"
            f"Settings: deps={dep_label}, host={resolved_host}\n"
            f"{guidance_text}\n"
            f"Extracted contents:\n{extracted_str}"
        ) from e


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_and_import_module(module_name: str, search_dir: str, verbose: bool = False) -> Optional[object]:
    """
    Try to find and import a module by searching in subdirectories.
    This handles cases where the wheel extraction creates unexpected directory structures.
    Returns the imported module if found, or None if not found.
    """
    import os
    
    # Try one level of subdirectories
    try:
        for item in os.listdir(search_dir):
            item_path = os.path.join(search_dir, item)
            if os.path.isdir(item_path) and item_path not in sys.path:
                # Skip .dist-info directories
                if item.endswith('.dist-info') or item.endswith('.data'):
                    continue
                # Insert after stdlib entries, not at position 0, so we do not shadow stdlib modules.
                _insert_sys_path_safely(item_path)
                try:
                    if verbose:
                        print(f"🌀 Whispy: trying to import {module_name} from {item_path}")
                    result = importlib.import_module(module_name)
                    if verbose:
                        print(f"✅ Whispy: successfully imported {module_name} from {item_path}")
                    return result
                except ModuleNotFoundError:
                    # Remove only the path we added so failed probes do not accumulate in sys.path.
                    _remove_sys_path_entry(item_path)
                    continue
    except Exception:
        pass
    
    return None


def _parse_package_spec(spec: str) -> str:
    """
    Extract package name from spec.
    Input: "requests" or "numpy"
    Returns: "requests" or "numpy"
    """
    m = re.match(r'^([A-Za-z0-9_.\-]+)$', spec.strip())
    if m:
        return m.group(1)
    raise WhispyError(f"Invalid package name: '{spec}'. Use the version parameter instead of inline version specs.")


def _cleanup_tmpdir(tmpdir: tempfile.TemporaryDirectory) -> None:
    """Remove a single tempdir from sys.path and clean it up immediately."""
    _remove_sys_path_entries_under(tmpdir.name)
    if tmpdir in _live_tmpdirs:
        _live_tmpdirs.remove(tmpdir)
    tmpdir.cleanup()


def _remove_sys_path_entry(path: str) -> None:
    while path in sys.path:
        sys.path.remove(path)


def _remove_sys_path_entries_under(root: str) -> None:
    root_abs = _os.path.abspath(root)
    sys.path[:] = [entry for entry in sys.path if not _path_is_under(entry, root_abs)]


def _path_is_under(candidate: str, root: str) -> bool:
    try:
        candidate_abs = _os.path.abspath(candidate)
        return _os.path.commonpath([candidate_abs, root]) == root
    except Exception:
        return False


def _insert_sys_path_safely(path: str) -> None:
    """
    Add Whispy temp paths after stdlib entries so we avoid shadowing the standard library.
    If no site-packages boundary is found, we append as the safest fallback.
    """
    if path in sys.path:
        return

    site_prefixes = ("site-packages", "dist-packages")
    insert_at = len(sys.path)
    for index, entry in enumerate(sys.path):
        if any(prefix in entry for prefix in site_prefixes):
            insert_at = index
            break
    sys.path.insert(insert_at, path)


def _fetch_bytes(url: str, verbose: bool = False) -> bytes:
    if verbose:
        print(f"  → GET {url}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"whispy-client/{__version__} Python/{sys.version.split()[0]}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _compute_tags() -> list[str]:
    """
    Generate the ordered list of PEP 425 compatibility tags for this interpreter.
    Most-specific first (matching pip's own ordering).
    No external dependencies — pure stdlib.
    """
    impl = platform.python_implementation()
    vi = sys.version_info
    machine = platform.machine().lower()
    system = platform.system()

    if impl == "CPython":
        interp_base = f"cp{vi.major}{vi.minor}"
        abi_base = f"cp{vi.major}{vi.minor}"
        abi_tags = [abi_base, "abi3", "none"]
        interp_tags = [interp_base, f"cp{vi.major}", "py3", f"py{vi.major}{vi.minor}"]
    elif impl == "PyPy":
        interp_base = f"pp{vi.major}{vi.minor}"
        abi_base = f"pypy{vi.major}{vi.minor}"
        abi_tags = [abi_base, "none"]
        interp_tags = [interp_base, "py3"]
    else:
        interp_base = f"cp{vi.major}{vi.minor}"
        abi_tags = ["none"]
        interp_tags = ["py3"]

    platform_tags = _platform_tags(system, machine, vi)

    tags: list[str] = []
    # Specific tags first (interp + abi + platform)
    for interp in interp_tags:
        for abi in abi_tags:
            for plat in platform_tags:
                tags.append(f"{interp}-{abi}-{plat}")

    # Pure-python fallbacks
    for interp in interp_tags:
        if f"{interp}-none-any" not in tags:
            tags.append(f"{interp}-none-any")
    tags.append("py3-none-any")

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _platform_tags(system: str, machine: str, vi) -> list[str]:
    if system == "Linux":
        # Support manylinux + musllinux variants
        tags = []
        manylinux_versions = [
            (2, 35), (2, 34), (2, 33), (2, 32), (2, 31), (2, 30),
            (2, 29), (2, 28), (2, 27), (2, 26), (2, 17), (2, 12), (2, 5),
        ]
        arch_map = {
            "x86_64": "x86_64",
            "aarch64": "aarch64",
            "arm64": "aarch64",
            "armv7l": "armv7l",
            "i686": "i686",
            "ppc64le": "ppc64le",
            "s390x": "s390x",
        }
        arch = arch_map.get(machine, machine)
        for major, minor in manylinux_versions:
            tags.append(f"manylinux_{major}_{minor}_{arch}")
        tags.append(f"manylinux2014_{arch}")
        tags.append(f"linux_{arch}")
        return tags

    elif system == "Darwin":
        # macOS: detect arm64 vs x86_64
        if machine in ("arm64", "aarch64"):
            archs = ["arm64", "universal2"]
        else:
            archs = ["x86_64", "universal2", "intel"]

        mac_ver = platform.mac_ver()[0]
        if mac_ver:
            try:
                parts = mac_ver.split(".")
                maj, mn = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                maj, mn = 14, 0
        else:
            maj, mn = 14, 0

        tags = []
        for arch in archs:
            for minor in range(mn, -1, -1):
                tags.append(f"macosx_{maj}_{minor}_{arch}")
            for older_major in range(maj - 1, 9, -1):
                tags.append(f"macosx_{older_major}_0_{arch}")
        return tags

    elif system == "Windows":
        if "64" in machine or machine == "amd64":
            return ["win_amd64", "win32"]
        elif "arm" in machine:
            return ["win_arm64", "win32"]
        else:
            return ["win32"]

    return ["any"]


# ---------------------------------------------------------------------------
# urllib.parse needed for _fetch_bytes params
# ---------------------------------------------------------------------------
import urllib.parse  # noqa: E402 (already imported via urllib.request chain)
