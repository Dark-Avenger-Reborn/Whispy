# 🌀 Whispy — The Python Package CDN

> Stream Python packages at runtime. No `pip install`, no virtual envs, no environment setup.
> **The PyPI equivalent of unpkg.com / jsDelivr.**

```python
from whispy_client import remote

requests = remote("requests")
numpy    = remote("numpy==1.26.4")
bs4      = remote("beautifulsoup4", module="bs4", deps=True)

print(requests.get("https://httpbin.org/get").status_code)  # 200
```

**Packages are streamed from PyPI through the Whispy CDN, SHA-256 verified, extracted to a
temporary directory, and imported at runtime. Nothing is permanently installed. Everything
disappears when your process exits.**

---

## Architecture

```
┌─────────────┐    HTTPS    ┌──────────────────┐    ┌──────────────┐
│ Your Script │ ──────────► │ Cloudflare Edge  │ ──►│ Whispy       │
│ (client)    │             │ (CDN cache)       │    │ Origin Server│
└─────────────┘             └──────────────────┘    └──────┬───────┘
                                                           │
                                                    ┌──────▼───────┐
                                                    │  PyPI API    │
                                                    └──────────────┘
```

- **Client** (`whispy_client`) — Zero-dependency installable. Computes PEP 425 tags, fetches the right wheel, extracts to tmpdir, imports.
- **CDN Edge** (Cloudflare Worker) — Caches versioned package zips with 1-year immutable TTL. Adds security headers, validates inputs.
- **Origin Server** (`server/app.py`) — Resolves packages, fetches from PyPI, verifies SHA-256, zips for serving, maintains disk cache.

---

## Repository Structure

```
whispy/
├── server/                  # Whispy CDN origin server
│   ├── app.py               # Flask application
│   ├── requirements.txt
│   └── Dockerfile
│
├── client/                  # whispy-client Python package
│   ├── whispy_client/
│   │   ├── __init__.py      # Public API: remote(), configure()
│   │   └── core.py          # Zero-dep implementation
│   └── pyproject.toml
│
├── docs/                    # whispy.dev documentation site
│   └── index.html
│
├── deploy/                  # Infrastructure configs
│   ├── docker-compose.yml
│   ├── cloudflare-worker.js # Cloudflare CDN edge layer
│   └── wrangler.toml
│
└── .github/
    └── workflows/
        └── ci.yml           # CI: test → build → publish → deploy
```

---

## Quick Start

### Use the hosted CDN

```bash
pip install whispy-client
```

```python
from whispy_client import remote, configure

# Optional: enable dep resolution and verbose logging
configure(deps=True, verbose=True)

requests = remote("requests")
print(requests.get("https://httpbin.org/get").status_code)
```

### Self-host

```bash
# Clone
git clone https://github.com/Dark-Avenger-Reborn/Whispy
cd Whispy

# Run with Docker Compose
docker compose -f deploy/docker-compose.yml up -d

# Point your client at it
WHISPY_HOST=http://localhost:8000 python my_script.py
```

### Run server locally (dev)

```bash
cd server
pip install -r requirements.txt
python app.py --debug
```

---

## Client API

### `remote(package, *, module=None, version=None, deps=False, host=None)`

| Param | Description |
|-------|-------------|
| `package` | PyPI name, optionally with `==version` e.g. `"requests==2.31.0"` |
| `module` | Import name if different from package name (e.g. `module="bs4"`) |
| `version` | Explicit version, overrides embedded spec |
| `deps` | If `True`, resolve and fetch transitive dependencies |
| `host` | Per-call CDN URL override |

**Common name mismatches:**
```python
bs4      = remote("beautifulsoup4", module="bs4")
PIL      = remote("pillow",         module="PIL")
yaml     = remote("pyyaml",         module="yaml")
dateutil = remote("python-dateutil",module="dateutil")
cv2      = remote("opencv-python",  module="cv2")
```

### `configure(*, host=None, deps=None, verbose=None)`

Set global defaults. Can also use `WHISPY_HOST` env var.

---

## Server API

| Endpoint | Description |
|----------|-------------|
| `GET /get_package?name=X&tags=...&version=Y&deps=1` | Download package zip |
| `GET /metadata/<package>` | Package metadata without download |
| `GET /health` | Health check + cache stats |
| `GET /stats` | Cache statistics |

---

## Security

- **SHA-256 verification** — Every file verified against PyPI digests before serving
- **Blocklist** — Known typosquatted packages are rejected
- **Input validation** — Package names validated against `[A-Za-z0-9_.-]+`
- **Rate limiting** — 60 req/min per IP on `/get_package`
- **HTTPS enforced** — Cloudflare handles TLS termination
- **Immutable URLs** — Versioned package URLs are `Cache-Control: immutable`
- **Server never imports packages** — Only proxies/caches them

---

## Deployment

### CI/CD (GitHub Actions)

The `.github/workflows/ci.yml` pipeline:

1. **Test** — server tests + client across Python 3.8–3.13, Linux/macOS/Windows
2. **Lint** — ruff
3. **Docker** — builds and pushes to GHCR on every `main` push
4. **PyPI** — publishes `whispy-client` on version tags (`v*`)
5. **Cloudflare** — deploys the Worker on `main`

### Required secrets

| Secret | Description |
|--------|-------------|
| `CF_API_TOKEN` | Cloudflare API token with Workers:Edit permission |

### Environment vars (server)

| Var | Default | Description |
|-----|---------|-------------|
| `WHISPY_CACHE_DIR` | `./cache` | Disk cache directory |
| `WHISPY_MAX_CACHE_MB` | `2048` | Max cache size in MB |
| `REDIS_URL` | `memory://` | Redis URL for distributed rate limiting |

---

## Roadmap

- [ ] Conflict-aware dependency resolver (full PubGrub/resolvelib integration)
- [ ] `whispy lock` CLI — generate a lockfile for reproducible scripts
- [ ] Browser / Pyodide support
- [ ] Package usage analytics dashboard
- [ ] Webhook notifications for new package versions

---

## License

MIT — see [LICENSE](LICENSE).

> Packages are sourced from [PyPI](https://pypi.org) and served under their original licenses.
> Whispy does not host or redistribute package source code — it proxies directly from PyPI's CDN.
