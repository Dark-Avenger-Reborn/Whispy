<div align="center">

# 🌀 Whispy Client

> Import Python packages at runtime with a zero-dependency client.
> Keep your scripts clean, your environments disposable, and your setup friction low.

<p>
	<img alt="stdlib only" src="https://img.shields.io/badge/Runtime-stdlib%20only-22c55e?style=for-the-badge" />
	<img alt="Whispy repo" src="https://img.shields.io/badge/Repo-GitHub-0ea5e9?style=for-the-badge&logo=github&logoColor=white" />
	<img alt="MIT" src="https://img.shields.io/badge/License-MIT-f59e0b?style=for-the-badge" />
</p>

</div>

The client lives in the [Whispy repository](https://github.com/Dark-Avenger-Reborn/Whispy), with the implementation in [client/whispy_client](https://github.com/Dark-Avenger-Reborn/Whispy/tree/testing_new/client/whispy_client) and the server entrypoint in [server/app.py](../server/app.py). It downloads a bundle from a Whispy server, extracts it to a temporary directory, and imports the requested module at runtime.

## When to Use It

- Throwaway scripts that need `requests`, `numpy`, or `beautifulsoup4` without a setup step.
- Short-lived jobs where you want packages to vanish when the process exits.
- Pinned runtime experiments where one exact version matters.
- Self-hosted setups that point at your own server from the [main repo](https://github.com/Dark-Avenger-Reborn/Whispy).

## Quick Examples

```python
from whispy_client import remote, configure

configure(verbose=True)

requests = remote("requests")
numpy = remote("numpy==1.26.4")
bs4 = remote("beautifulsoup4", module="bs4", deps=True)
```

```python
# Common import name mismatches
bs4 = remote("beautifulsoup4", module="bs4")
PIL = remote("pillow", module="PIL")
yaml = remote("pyyaml", module="yaml")
dateutil = remote("python-dateutil", module="dateutil")
cv2 = remote("opencv-python", module="cv2")
```

## Install

```bash
pip install whispy-client
```

For local development from this repo:

```bash
cd client
pip install -e .
```

## API

### `remote(package, *, module=None, version=None, deps=False, host=None)`

`package` can be a bare PyPI distribution name or an exact pin such as `requests==2.31.0`. If the import name differs from the distribution name, pass `module=...`.

`deps=True` asks the server to include install-time dependencies as well. That behavior is best-effort and does not perform full dependency conflict resolution.

| Param | Description |
|-------|-------------|
| `package` | PyPI distribution name, optionally with `==version` |
| `module` | Import name if different from the package name |
| `version` | Explicit version override, if you do not want to embed it in `package` |
| `deps` | Fetch install-time dependencies as well |
| `host` | Per-call Whispy server override |

### `configure(*, host=None, deps=None, verbose=None)`

Sets process-wide defaults. The default host comes from `WHISPY_HOST`, falling back to `https://cdn.whispycdn.dev`.

| Param | Description |
|-------|-------------|
| `host` | Default Whispy server URL |
| `deps` | Default dependency-fetching behavior |
| `verbose` | Print progress messages while fetching and importing |

## Code References

- The client implementation is in [client/whispy_client/core.py](https://github.com/Dark-Avenger-Reborn/Whispy/blob/testing_new/client/whispy_client/core.py).
- The server path that resolves bundles is in [server/app.py](../server/app.py).
- The release workflow is in [the repo workflow file](../.github/workflows/ci.yml).

## License

MIT. Packages are sourced from PyPI and remain under their original licenses.
