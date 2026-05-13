<div align="center">

# 🌀 Whispy

> Stream Python packages at runtime. No `pip install`, no virtualenvs, no project setup.
> The pythonic way to treat packages like network resources.

<p>
	<img alt="PyPI CDN" src="https://img.shields.io/badge/PyPI-CDN-0ea5e9?style=for-the-badge&logo=pypi&logoColor=white" />
	<img alt="Zero runtime deps" src="https://img.shields.io/badge/Zero%20runtime%20deps-stdlib%20only-22c55e?style=for-the-badge" />
	<img alt="MIT License" src="https://img.shields.io/badge/License-MIT-f59e0b?style=for-the-badge" />
</p>


</div>

Whispy streams Python packages at runtime. The client downloads a package bundle from a Whispy server, extracts it to a temporary directory, adds that directory to `sys.path`, and imports the requested module on demand. Nothing is permanently installed.

Browse the source on [GitHub](https://github.com/Dark-Avenger-Reborn/Whispy) if you want to follow the client, the server, or the release workflow in the repo.

## Why Whispy

- Install once, import anything later.
- Keep environments clean by extracting packages to temp directories.
- Resolve the right wheel for the current interpreter and platform.
- Verify PyPI SHA-256 digests before serving a bundle.

## Use Cases

- A notebook or one-off script that needs `requests`, `numpy`, or `bs4` without setting up a virtual environment.
- A throwaway automation job that should not leave packages installed on disk.
- A controlled runtime where you want to fetch only the wheel that matches the current interpreter and platform.
- A self-hosted setup where you want to point [whispy_client](https://github.com/Dark-Avenger-Reborn/Whispy/tree/main/client) at your own server from the [repo source](https://github.com/Dark-Avenger-Reborn/Whispy).

## Quick Start

### Install the client from PyPI

```bash
pip install whispy-client
```

### Or install from source (development)

```bash
cd client
pip install -e .
```

### Use the client

```python
from whispy_client import remote, configure

configure(verbose=True)

requests = remote("requests")
numpy = remote("numpy", version="1.26.4")
bs4 = remote("beautifulsoup4", module="bs4", deps=True)

print(requests.get("https://httpbin.org/get").status_code)
```

Default host: `https://cdn.whispycdn.dev`. Override it per call with `host=...`, or globally with `configure(host=...)` or `WHISPY_HOST`.

If you want the exact implementation, start with the [client package in the repo](https://github.com/Dark-Avenger-Reborn/Whispy/tree/main/client) and the [server entrypoint](https://github.com/Dark-Avenger-Reborn/Whispy/blob/main/server/app.py).

Common examples:

```python
# Import the package (latest version from PyPI)
requests = remote("requests")

# Pin to an exact version
numpy = remote("numpy", version="1.26.4")

# Map a distribution name to a different import name
bs4 = remote("beautifulsoup4", module="bs4")

# Pull dependencies too when you need a fuller runtime bundle
pandas = remote("pandas", deps=True)

# opencv-python imports as cv2 and often needs dependency bundling
cv2 = remote("opencv-python", module="cv2", deps=True)
```

If import fails with a message like `No module named 'numpy'`, the package itself was fetched but a dependency is missing at import time. In that case, retry with `deps=True` or set `configure(deps=True)` globally.

### Run the server locally

```bash
cd server
pip install -r requirements.txt
python app.py --debug
```

For the server implementation details, see [server/app.py](server/app.py) in this repo.

## Client API

### `remote(package, *, module=None, version=None, deps=False, host=None)`

`package` is a PyPI distribution name. Specify versions using the `version` parameter (for example: `remote("requests", version="2.31.0")`). If the import name differs from the distribution name, pass `module=...`.

`deps=True` asks the server to include install-time dependencies as well. That path is best-effort and does not implement full dependency conflict resolution.

| Param | Description |
|-------|-------------|
| `package` | PyPI distribution name |
| `module` | Import name if different from the package name |
| `version` | Explicit version override. Specify versions here instead of embedding them in `package` |
| `deps` | Fetch install-time dependencies as well |
| `host` | Per-call Whispy server override |

### `configure(*, host=None, deps=None, verbose=None)`

Sets process-wide defaults for the client.

| Param | Description |
|-------|-------------|
| `host` | Default Whispy server URL |
| `deps` | Default dependency-fetching behavior |
| `verbose` | Print progress messages while fetching and importing |

## Server API

| Endpoint | Description |
|----------|-------------|
| `GET /get_package?name=X&tags=...&version=Y&deps=1` | Return a zip bundle for the requested package |
| `GET /metadata/<package>?version=...` | Return normalized PyPI metadata |
| `GET /health` | Health check plus cache stats |
| `GET /stats` | Cache statistics |

`/get_package` requires `name` and a comma-separated `tags` list. The server uses those tags to select the best matching wheel when one exists, otherwise it falls back to a source distribution.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPY_HOST` | `https://cdn.whispycdn.dev` | Default client host |
| `WHISPY_CACHE_DIR` | `./cache` | Server cache directory |
| `WHISPY_MAX_CACHE_MB` | `2048` | Maximum cache size in MB |
| `REDIS_URL` | `memory://` | Optional limiter storage backend |
| `WHISPY_SECRET` | unset | Optional shared secret checked via `X-Whispy-Secret` |

## Security and limits

- Package names are validated before requests are processed.
- Known typosquatted packages are blocklisted.
- PyPI file digests are verified before a bundle is served.
- `/get_package` is rate limited to 60 requests per minute per IP.
- `/metadata/<package>` is rate limited to 120 requests per minute per IP.

## CI

The GitHub Actions workflow runs server tests, installs the client across Python 3.8 through 3.12 on Linux, macOS, and Windows, runs `ruff`, and publishes `whispy-client` to PyPI on version tags.

The release and test setup lives in the [repo workflow file](.github/workflows/ci.yml).

## License

MIT. Packages are sourced from PyPI and remain under their original licenses.
