"""
whispy_client — Zero-dependency Python client for the Whispy CDN.

Usage:
    from whispy_client import remote

    requests = remote("requests")
    numpy = remote("numpy==1.26.4")
    bs4 = remote("beautifulsoup4", module="bs4", deps=True)
"""

from __future__ import annotations

import importlib
import io
import json
import platform
import re
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from typing import Optional

__version__ = "1.1.0"
__all__ = ["remote", "configure", "WhispyError"]

# ---------------------------------------------------------------------------
# Default CDN host — users can override via configure() or WHISPY_HOST env var
# ---------------------------------------------------------------------------
import os as _os
_DEFAULT_HOST = _os.environ.get("WHISPY_HOST", "https://cdn.whispycdn.dev")

_config = {
    "host": _DEFAULT_HOST,
    "deps": False,
    "verbose": False,
}

# Tracks live TemporaryDirectory objects so they stay alive for the process
_live_tmpdirs: list[tempfile.TemporaryDirectory] = []


class WhispyError(RuntimeError):
    pass


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
        package: Package name as on PyPI, optionally with version spec
                 e.g. "requests" or "requests==2.31.0" or "requests>=2.28"
        module:  Import name if different from package name.
                 e.g. remote("beautifulsoup4", module="bs4")
        version: Explicit version string, overrides any spec in package name.
        deps:    Fetch dependencies too. Overrides global configure() setting.
        host:    CDN host override for this call only.

    Returns:
        The imported module object.

    Example:
        requests = remote("requests")
        print(requests.get("https://httpbin.org/get").status_code)
    """
    pkg_name, pkg_version = _parse_package_spec(package)
    resolved_version = version or pkg_version
    resolved_module = module or pkg_name
    resolved_host = (host or _config["host"]).rstrip("/")
    resolved_deps = _config["deps"] if deps is None else deps
    verbose = _config["verbose"]

    # Return from sys.modules if already loaded
    if resolved_module in sys.modules:
        return sys.modules[resolved_module]

    if verbose:
        print(f"🌀 Whispy: fetching {pkg_name}" + (f"=={resolved_version}" if resolved_version else ""))

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
            msg = json.loads(body).get("error", body)
        except Exception:
            msg = body
        raise WhispyError(f"Whispy CDN error for '{pkg_name}': {msg}") from e
    except Exception as e:
        raise WhispyError(f"Could not reach Whispy CDN at {resolved_host}: {e}") from e

    # Extract into a TemporaryDirectory that lives for the process lifetime
    tmpdir = tempfile.TemporaryDirectory(prefix="whispy_", ignore_cleanup_errors=True)
    _live_tmpdirs.append(tmpdir)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmpdir.name)

    if tmpdir.name not in sys.path:
        sys.path.insert(0, tmpdir.name)

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
        
        raise WhispyError(
            f"Package '{pkg_name}' was downloaded but module '{resolved_module}' could not be imported.\n"
            f"Try setting module= explicitly. Original error: {e}\n"
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
            if os.path.isdir(item_path) and item not in sys.path:
                # Skip .dist-info directories
                if item.endswith('.dist-info') or item.endswith('.data'):
                    continue
                # Try adding this directory to sys.path
                sys.path.insert(0, item_path)
                try:
                    if verbose:
                        print(f"🌀 Whispy: trying to import {module_name} from {item_path}")
                    result = importlib.import_module(module_name)
                    if verbose:
                        print(f"✅ Whispy: successfully imported {module_name} from {item_path}")
                    return result
                except ModuleNotFoundError:
                    # Remove this path since it didn't work
                    sys.path.pop(0)
                    continue
    except Exception:
        pass
    
    return None


def _parse_package_spec(spec: str) -> tuple[str, Optional[str]]:
    """
    Parse "requests==2.31.0" → ("requests", "2.31.0")
    Parse "requests>=2.28"   → ("requests", None)   (range specs unsupported client-side)
    Parse "requests"         → ("requests", None)
    """
    m = re.match(r'^([A-Za-z0-9_.\-]+)==([A-Za-z0-9._]+)$', spec.strip())
    if m:
        return m.group(1), m.group(2)
    m = re.match(r'^([A-Za-z0-9_.\-]+)', spec.strip())
    if m:
        return m.group(1), None
    raise WhispyError(f"Cannot parse package spec: '{spec}'")


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
