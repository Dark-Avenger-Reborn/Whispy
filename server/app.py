"""
Whispy CDN Server — Production-ready PyPI package streaming server.
The Python equivalent of unpkg.com / jsDelivr.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_file, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("whispy")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CACHE_DIR = Path(os.environ.get("WHISPY_CACHE_DIR", "./cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_CACHE_BYTES = int(os.environ.get("WHISPY_MAX_CACHE_MB", "2048")) * 1024 * 1024
PYPI_BASE = "https://pypi.org/pypi"
PYPI_SIMPLE = "https://pypi.org/simple"

# Packages known to be typosquatted / malicious (extend this list)
BLOCKLIST: set[str] = {
    "colourama", "requesrs", "reqeusts", "urllib4", "urlib3",
    "setup-tools", "setuptoolz", "pips", "django-server",
}

# ---------------------------------------------------------------------------
# Flask app + rate limiter
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute", "2000 per hour"],
    storage_uri=os.environ.get("REDIS_URL", "memory://"),
)

# ---------------------------------------------------------------------------
# Platform tag parsing (no external deps — pure stdlib)
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """PEP 503 normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_wheel_tags(filename: str) -> set[str]:
    """
    Extract the set of compatibility tags from a wheel filename.
    e.g. requests-2.31.0-py3-none-any.whl → {"py3-none-any"}
    Handles compressed tag sets like cp311.cp312-cp311.cp312-manylinux_2_17_x86_64
    """
    if not filename.endswith(".whl"):
        return set()
    stem = filename[:-4]
    parts = stem.split("-")
    if len(parts) < 5:
        return set()

    interps = parts[2].split(".")
    abis = parts[3].split(".")
    plats = parts[4].split(".")

    tags = set()
    for interp in interps:
        for abi in abis:
            for plat in plats:
                tags.add(f"{interp}-{abi}-{plat}")
    return tags


def tags_compatible(wheel_tags: set[str], client_tags: list[str]) -> bool:
    """Check if wheel is compatible with client. Handles abi3 wheels specially."""
    client_set = set(client_tags)
    
    # Direct match
    if wheel_tags & client_set:
        return True
    
    # Check for abi3 (stable ABI) compatibility
    # A cp39-abi3-win_amd64 wheel works with cp310, cp311, cp312, ... cp314, etc
    for wheel_tag in wheel_tags:
        parts = wheel_tag.split("-")
        if len(parts) == 3 and parts[1] == "abi3":
            wheel_interp = parts[0]  # e.g., "cp39"
            wheel_plat = parts[2]     # e.g., "win_amd64"
            
            # Extract interpreter and platform from client tags
            for client_tag in client_tags:
                client_parts = client_tag.split("-")
                if len(client_parts) == 3:
                    client_interp = client_parts[0]
                    client_plat = client_parts[2]
                    
                    # Platform must match
                    if client_plat != wheel_plat:
                        continue
                    
                    # Extract version numbers from interpreters (e.g., "cp39" -> 39, "cp314" -> 314)
                    try:
                        wheel_version = int(wheel_interp[2:]) if wheel_interp.startswith("cp") else 0
                        client_version = int(client_interp[2:]) if client_interp.startswith("cp") else 0
                        
                        # Client version must be >= wheel version for abi3 to work
                        if client_version >= wheel_version:
                            return True
                    except (ValueError, IndexError):
                        pass
    
    return False


def rank_wheel(filename: str, client_tags: list[str]) -> int:
    """
    Lower score = better match. Prefers wheels that match earlier
    in the client's ordered tag list (most-specific first).
    """
    wheel_tags = parse_wheel_tags(filename)
    
    # First check direct matches
    for i, tag in enumerate(client_tags):
        if tag in wheel_tags:
            return i
    
    # Then check abi3 compatibility
    for wheel_tag in wheel_tags:
        parts = wheel_tag.split("-")
        if len(parts) == 3 and parts[1] == "abi3":
            wheel_interp = parts[0]
            wheel_plat = parts[2]
            
            for j, client_tag in enumerate(client_tags):
                client_parts = client_tag.split("-")
                if len(client_parts) == 3:
                    client_interp = client_parts[0]
                    client_plat = client_parts[2]
                    
                    if client_plat != wheel_plat:
                        continue
                    
                    try:
                        wheel_version = int(wheel_interp[2:]) if wheel_interp.startswith("cp") else 0
                        client_version = int(client_interp[2:]) if client_interp.startswith("cp") else 0
                        
                        if client_version >= wheel_version:
                            # Return a score based on how old the wheel is
                            # Prefer newer compatible wheels (lower score = better)
                            return 10000 + (wheel_version * 100) + j
                    except (ValueError, IndexError):
                        pass
    
    return 999999


# ---------------------------------------------------------------------------
# PyPI metadata
# ---------------------------------------------------------------------------

def fetch_pypi_metadata(package: str, version: Optional[str] = None) -> dict:
    name = _normalize_name(package)
    if version:
        url = f"{PYPI_BASE}/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
    else:
        url = f"{PYPI_BASE}/{urllib.parse.quote(name)}/json"

    req = urllib.request.Request(url, headers={"User-Agent": "Whispy/1.0 (+https://github.com/Dark-Avenger-Reborn/Whispy)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f"Package '{package}' not found on PyPI")
        raise RuntimeError(f"PyPI error {e.code}: {e.reason}")


def resolve_dependencies(package: str, version: str) -> list[dict]:
    """
    Returns a flat ordered list of {name, version, files} dicts
    covering the package and all its install-time dependencies.
    Simple breadth-first, no conflict resolution (good enough for v1).
    """
    resolved = {}
    queue = [(package, version)]

    while queue:
        name, ver = queue.pop(0)
        norm = _normalize_name(name)
        if norm in resolved:
            continue

        try:
            meta = fetch_pypi_metadata(name, ver or None)
        except Exception as e:
            log.warning("Skipping dep %s==%s: %s", name, ver, e)
            continue

        info = meta["info"]
        actual_ver = info["version"]
        requires = info.get("requires_dist") or []

        resolved[norm] = {
            "name": norm,
            "version": actual_ver,
            "files": meta.get("releases", {}).get(actual_ver, []) or meta.get("urls", []),
            "requires_python": info.get("requires_python"),
        }

        for req in requires:
            # Skip extras and conditional deps for now
            if "extra ==" in req or "; extra" in req:
                continue
            # Strip environment markers
            req_clean = req.split(";")[0].strip()
            # Parse name + version spec
            dep_match = re.match(r'^([A-Za-z0-9_.\-]+)\s*(.*)', req_clean)
            if dep_match:
                dep_name = dep_match.group(1).strip()
                dep_norm = _normalize_name(dep_name)
                if dep_norm not in resolved:
                    queue.append((dep_name, None))

    return list(resolved.values())


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Whispy/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def _best_wheel(files: list[dict], client_tags: list[str]) -> Optional[dict]:
    wheels = [f for f in files if f["filename"].endswith(".whl")]
    compatible = [
        w for w in wheels
        if tags_compatible(parse_wheel_tags(w["filename"]), client_tags)
    ]
    
    # Log details for debugging
    if wheels:
        log.debug("Found %d wheels, %d compatible. Available wheels:", len(wheels), len(compatible))
        for w in wheels[:10]:  # Log first 10 wheels
            tags = parse_wheel_tags(w["filename"])
            is_compat = w in compatible
            log.debug("  %s - tags=%s - compatible=%s", w["filename"], tags, is_compat)
        if len(wheels) > 10:
            log.debug("  ... and %d more wheels", len(wheels) - 10)
    
    if not compatible:
        log.warning("No compatible wheels found. Client tags: %s", client_tags[:10])
        return None
    
    # Sort by rank (most specific match first)
    compatible.sort(key=lambda w: rank_wheel(w["filename"], client_tags))
    best = compatible[0]
    log.info("Selected wheel: %s", best["filename"])
    return best


def _sdist(files: list[dict]) -> Optional[dict]:
    for f in files:
        if f["filename"].endswith((".tar.gz", ".zip")):
            return f
    return None


def download_package_to_dir(pkg_files: list[dict], client_tags: list[str], dest_dir: Path) -> str:
    """Download best-match wheel (or sdist) into dest_dir. Returns chosen filename."""
    best = _best_wheel(pkg_files, client_tags)
    chosen = best or _sdist(pkg_files)
    if not chosen:
        raise RuntimeError("No compatible distribution found")

    dist_type = "wheel" if best else "sdist"
    log.info("Downloading %s (%s)", chosen["filename"], dist_type)
    
    tmp = dest_dir / chosen["filename"]
    _download(chosen["url"], tmp)

    # Verify integrity
    expected = chosen.get("digests", {}).get("sha256")
    if expected:
        actual = _sha256_file(tmp)
        if actual != expected:
            tmp.unlink()
            raise ValueError(f"SHA256 mismatch for {chosen['filename']}: expected {expected}, got {actual}")
    else:
        log.warning("No SHA256 digest available for %s — skipping verification", chosen["filename"])

    # Extract
    if chosen["filename"].endswith(".whl") or chosen["filename"].endswith(".zip"):
        with zipfile.ZipFile(tmp, "r") as z:
            z.extractall(dest_dir)
            # Log extraction for debugging
            extracted_files = z.namelist()
            log.debug("Extracted %d files from %s", len(extracted_files), chosen["filename"])
    else:
        import tarfile
        with tarfile.open(tmp, "r:gz") as t:
            t.extractall(dest_dir)
            log.debug("Extracted tarfile %s", chosen["filename"])

    tmp.unlink()
    return chosen["filename"]


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------

def _cache_key(package: str, version: str, tags_str: str, with_deps: bool) -> str:
    tag_hash = hashlib.sha256(tags_str.encode()).hexdigest()[:12]
    dep_suffix = "-deps" if with_deps else ""
    return f"{_normalize_name(package)}-{version}-{tag_hash}{dep_suffix}"


def cache_get(key: str) -> Optional[Path]:
    meta_path = CACHE_DIR / f"{key}.json"
    zip_path = CACHE_DIR / f"{key}.zip"
    if not meta_path.exists() or not zip_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    if _sha256_file(zip_path) != meta["sha256"]:
        log.warning("Cache integrity fail for %s — evicting", key)
        meta_path.unlink(missing_ok=True)
        zip_path.unlink(missing_ok=True)
        return None
    return zip_path


def cache_put(key: str, zip_path: Path) -> Path:
    dest = CACHE_DIR / f"{key}.zip"
    shutil.copy2(zip_path, dest)
    sha = _sha256_file(dest)
    meta = {"sha256": sha, "created": time.time()}
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(meta))
    _evict_if_needed()
    return dest


def _evict_if_needed():
    """Simple LRU-ish eviction: remove oldest .zip files if over budget."""
    zips = sorted(CACHE_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in zips)
    while total > MAX_CACHE_BYTES and zips:
        victim = zips.pop(0)
        size = victim.stat().st_size
        victim.unlink(missing_ok=True)
        (CACHE_DIR / f"{victim.stem}.json").unlink(missing_ok=True)
        total -= size
        log.info("Evicted cache entry %s (%d MB)", victim.stem, size // 1024 // 1024)


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

def fetch_package_zip(
    package: str,
    version: Optional[str],
    client_tags: list[str],
    with_deps: bool,
) -> tuple[BytesIO, str, list[dict]]:
    """
    Returns (zip_buffer, resolved_version, manifest).
    manifest is a list of {name, version, sha256} dicts.
    """
    if _normalize_name(package) in BLOCKLIST:
        raise ValueError(f"Package '{package}' is blocklisted")

    # Resolve top-level metadata
    meta = fetch_pypi_metadata(package, version)
    resolved_version = meta["info"]["version"]
    tags_str = ",".join(client_tags)
    key = _cache_key(package, resolved_version, tags_str, with_deps)

    cached = cache_get(key)
    if cached:
        log.info("Cache hit: %s", key)
        buf = BytesIO(cached.read_bytes())
        manifest_path = CACHE_DIR / f"{key}.manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
        return buf, resolved_version, manifest

    # Build package set
    if with_deps:
        pkg_list = resolve_dependencies(package, resolved_version)
    else:
        pkg_list = [{
            "name": _normalize_name(package),
            "version": resolved_version,
            "files": meta.get("releases", {}).get(resolved_version, []) or meta.get("urls", []),
        }]

    manifest = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        for pkg in pkg_list:
            pkg_dir = tmp / pkg["name"]
            pkg_dir.mkdir()
            try:
                chosen_filename = download_package_to_dir(pkg["files"], client_tags, pkg_dir)
                sha = None
                for f in pkg["files"]:
                    if f["filename"] == chosen_filename:
                        sha = f.get("digests", {}).get("sha256")
                        break
                
                # Validate that files were actually extracted
                extracted_items = list(pkg_dir.rglob("*"))
                files_count = len([f for f in extracted_items if f.is_file()])
                if files_count == 0:
                    raise RuntimeError(f"No files extracted from {chosen_filename} (extracted {len(extracted_items)} total items)")
                
                manifest.append({
                    "name": pkg["name"],
                    "version": pkg["version"],
                    "filename": chosen_filename,
                    "sha256": sha,
                    "items_extracted": files_count,
                })
                log.info("Successfully extracted %d files from %s for %s", files_count, chosen_filename, pkg["name"])
            except Exception as e:
                log.error("Could not fetch %s: %s", pkg["name"], e, exc_info=True)

        # Check if any packages were successfully extracted
        if not manifest:
            raise RuntimeError(f"No packages were successfully downloaded for {package}. Check server logs for details.")

        # Zip everything up
        zip_tmp = tmp / "bundle.zip"
        with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            file_count = 0
            for item in tmp.rglob("*"):
                if item == zip_tmp or not item.is_file():
                    continue
                # Strip the per-package subdir so all modules land at root
                try:
                    pkg_name = item.relative_to(tmp).parts[0]
                    arcname = item.relative_to(tmp / pkg_name)
                    zf.write(item, arcname)
                    file_count += 1
                except Exception as e:
                    log.warning("Failed to add file %s to zip: %s", item, e)
                    continue
        
        log.info("Zipped %d files for package %s v%s", file_count, package, resolved_version)
        
        if file_count == 0:
            raise RuntimeError(f"No files were added to the package bundle for {package}. Extracted {sum(m['items_extracted'] for m in manifest)} files but zip is empty.")

        cached_path = cache_put(key, zip_tmp)

        # Save manifest
        manifest_path = CACHE_DIR / f"{key}.manifest.json"
        manifest_path.write_text(json.dumps(manifest))

    buf = BytesIO(cached_path.read_bytes())
    return buf, resolved_version, manifest


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.before_request
def verify_secret():
    secret = os.environ.get("WHISPY_SECRET")
    if secret and request.headers.get("X-Whispy-Secret") != secret:
        return jsonify({"error": "Forbidden"}), 403

@app.before_request
def _start_timer():
    g.start = time.monotonic()


@app.after_request
def _log_request(resp):
    duration = (time.monotonic() - g.start) * 1000
    log.info("%s %s %d %.1fms", request.method, request.path, resp.status_code, duration)
    resp.headers["X-Whispy-Version"] = "1.1.0"
    return resp


@app.route("/health")
@limiter.exempt
def health():
    cache_files = list(CACHE_DIR.glob("*.zip"))
    cache_mb = sum(p.stat().st_size for p in cache_files) / 1024 / 1024
    return jsonify({
        "status": "ok",
        "cache_entries": len(cache_files),
        "cache_mb": round(cache_mb, 2),
        "max_cache_mb": MAX_CACHE_BYTES // 1024 // 1024,
    })


@app.route("/get_package")
@limiter.limit("60 per minute")
def get_package():
    """
    GET /get_package?name=requests&version=2.31.0&tags=cp311-cp311-linux_x86_64,...&deps=1

    Returns a zip file containing the package (and optionally its deps)
    ready to be extracted and added to sys.path.
    """
    package = request.args.get("name", "").strip()
    version = request.args.get("version", "").strip() or None
    tags_raw = request.args.get("tags", "").strip()
    with_deps = request.args.get("deps", "0") in ("1", "true", "yes")

    if not package:
        return jsonify({"error": "Missing 'name' parameter"}), 400
    if not tags_raw:
        return jsonify({"error": "Missing 'tags' parameter"}), 400
    if not re.match(r'^[A-Za-z0-9_.\-]+$', package):
        return jsonify({"error": "Invalid package name"}), 400

    client_tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    try:
        buf, resolved_version, manifest = fetch_package_zip(package, version, client_tags, with_deps)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        log.exception("Error fetching %s", package)
        return jsonify({"error": str(e)}), 500

    resp = send_file(
        buf,
        as_attachment=True,
        download_name=f"{_normalize_name(package)}-{resolved_version}.zip",
        mimetype="application/zip",
    )
    resp.headers["X-Whispy-Package"] = package
    resp.headers["X-Whispy-Version-Resolved"] = resolved_version
    resp.headers["X-Whispy-Manifest"] = json.dumps(manifest)
    resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
    return resp


@app.route("/metadata/<package>")
@limiter.limit("120 per minute")
def metadata(package: str):
    """GET /metadata/requests — returns PyPI metadata JSON for a package."""
    if not re.match(r'^[A-Za-z0-9_.\-]+$', package):
        return jsonify({"error": "Invalid package name"}), 400
    version = request.args.get("version") or None
    try:
        meta = fetch_pypi_metadata(package, version)
        info = meta["info"]
        return jsonify({
            "name": info["name"],
            "version": info["version"],
            "summary": info["summary"],
            "requires_python": info["requires_python"],
            "requires_dist": info.get("requires_dist") or [],
            "license": info.get("license"),
            "home_page": info.get("home_page"),
            "project_urls": info.get("project_urls"),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        log.exception("Metadata error for %s", package)
        return jsonify({"error": str(e)}), 500


@app.route("/stats")
@limiter.exempt
def stats():
    """Basic cache statistics."""
    zips = list(CACHE_DIR.glob("*.zip"))
    total_bytes = sum(p.stat().st_size for p in zips)
    return jsonify({
        "cached_packages": len(zips),
        "cache_size_mb": round(total_bytes / 1024 / 1024, 2),
        "cache_limit_mb": MAX_CACHE_BYTES // 1024 // 1024,
    })

@app.route("/")
@limiter.exempt
def index():
    return send_file(Path(__file__).resolve().parent / "../docs/index.html")

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Rate limit exceeded. Please slow down."}), 429


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal(e):
    return jsonify({"error": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Whispy CDN Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    log.info("🌀 Whispy CDN starting on %s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug)
