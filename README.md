
# 🌀 Whispy

> **Whispy** is a lightweight server + client system for dynamically loading Python packages at runtime — without `pip install` on the client.
>
> Packages are streamed from PyPI through a local Whispy server, extracted to temporary storage, and imported dynamically. Nothing is permanently installed, and all files disappear when your process exits.

Think of it as **ephemeral package streaming for Python**.

---

## ✨ Features

- 🚫 No `pip install` required on the client
- ⚡ Runtime package loading using temporary storage (no permanent installs)
- 🧩 Zero external dependencies on the client
- 🔐 SHA256 verification of PyPI packages
- 💾 Automatic server-side caching for faster repeat loads
- 💡 Simple client API:

```python
requests = import_remote_packages("requests")
```

> ⚠️ **Native extensions:**  
> Packages containing compiled binaries (NumPy, SciPy, Torch, etc.) require temporary disk extraction because operating systems cannot load shared libraries directly from memory. Whispy handles this automatically.
>
> Pure-Python packages can be loaded entirely from RAM.

This is an experimental system and **not a replacement for pip or virtual environments**.

---

## 🛠️ Server Setup

### 🔧 Requirements

- Python 3.7+
- Flask
- requests

### 📦 Install dependencies

```bash
pip install flask requests
```

### ▶️ Run the server

```bash
python package_server.py
```

Server starts at:

```
http://localhost:5000
```

---

## 🧑‍💻 Client Setup

### ✅ Requirements

- Python 3.7+
- No external libraries

Copy the client code into your script:

```python
import sys, importlib, urllib.request, io, zipfile, tempfile, platform
from collections import namedtuple

Tag = namedtuple('Tag', 'interpreter abi platform')

def sys_tags():
    impl, mach, sysname = platform.python_implementation(), platform.machine().lower(), platform.system()
    vi = sys.version_info if impl == 'CPython' else getattr(sys, 'pypy_version_info', sys.version_info)
    interp = f"{'cp' if impl == 'CPython' else 'pp'}{vi.major}{vi.minor}"
    abi = f"{'cp' if impl == 'CPython' else 'pypy'}{vi.major}{vi.minor}" + ('' if impl == 'CPython' else '_pp73')
    plats = {
        'Linux': [f"manylinux_2_28_{mach}", f"manylinux_2_17_{mach}", f"manylinux2014_{mach}"] if mach in ['x86_64','aarch64','armv7l'] else [f"manylinux2014_{mach}"],
        'Windows': ['win_amd64'] if '64' in mach else ['win32'],
        'Darwin': ['macosx_10_9_x86_64']
    }.get(sysname, []) + ['any']
    return [Tag(interp, abi, p) for p in plats] + ([Tag(interp, 'abi3', p) for p in plats] if interp.startswith('cp') else []) + [Tag('py3', 'none', p) for p in plats] + ([Tag(interp, 'none', p) for p in plats] if interp.startswith('cp') else [])

def import_remote_packages(pkg, ver=None, host="http://localhost:5000", module=None):
    module = module or pkg
    tags = ','.join(f"{t.interpreter}-{t.abi}-{t.platform}" for t in sys_tags())
    url = f"{host}/get_package?name={pkg}&tags={tags}" + (f"&version={ver}" if ver else "")
    print(f"📡 Requesting {url}")

    with urllib.request.urlopen(url) as r:
        data = io.BytesIO(r.read())

    td = tempfile.TemporaryDirectory()
    zipfile.ZipFile(data).extractall(td.name)
    sys.path.insert(0, td.name)

    sys._whispy_tmp = getattr(sys, "_whispy_tmp", []) + [td]

    return importlib.import_module(module)
```

---

## 🧪 Example

```python
requests = import_remote_packages("requests")

print(requests.get("https://httpbin.org/get").status_code)
```

### Using the `module` parameter

Some packages have different distribution names (for `pip`) and module names (for `import`). Use the optional `module` parameter to handle these cases:

```python
# Distribution name is "python-dateutil", but module name is "dateutil"
dateutil = import_remote_packages("python-dateutil", module="dateutil")

from dateutil import parser
parsed_date = parser.parse("2024-01-25")
```

Other examples with name mismatches:
- `pip install pillow` → `import PIL` → `import_remote_packages("pillow", module="PIL")`
- `pip install pyyaml` → `import yaml` → `import_remote_packages("pyyaml", module="yaml")`
- `pip install beautifulsoup4` → `import bs4` → `import_remote_packages("beautifulsoup4", module="bs4")`

---

## 📁 Caching

The server caches packages in `./cache/`.

You may delete this directory at any time.

---

## 🛡️ Security Notes

- SHA256 hashes are verified using PyPI metadata
- Client does not permanently install packages
- Files exist only in temporary directories
- For external deployments consider:
  - IP whitelisting
  - authentication
  - logging
  - rate limiting

---


## 🧭 Why Whispy Exists

Python’s packaging model assumes:

- dependencies are installed ahead of time
- environments are persistent
- disk access is always available
- users manage virtual environments manually

This works for traditional development, but breaks down for:

- ephemeral compute
- plugin systems
- sandboxed execution
- research scripts
- education
- serverless workflows

Whispy explores a different model:

> **Dependencies as runtime resources, not installations.**

Instead of preparing environments first, Whispy allows code to request packages dynamically at execution time:

```python
numpy = import_remote_packages("numpy")
```

Packages are streamed from PyPI through the Whispy server, temporarily extracted, imported, and discarded when the process exits.

No virtualenvs.  
No permanent installs.  
No environment setup.

---

### What problem does this solve?

Whispy enables:

- **Ephemeral execution** — run scripts without polluting the host system
- **Portable experiments** — share a single Python file with zero setup
- **Dynamic plugins** — load capabilities only when needed
- **Sandboxed code** — prevent permanent dependency installation
- **Education-first workflows** — students run code without wrestling with pip
- **Serverless-friendly patterns** — hydrate dependencies on demand

This mirrors how modern systems work (CDNs, containers, browsers), but applied to Python.

---

### Design philosophy

Whispy is intentionally:

- lightweight
- experimental
- transparent
- minimal

It is **not** intended to replace pip, virtual environments, or proper packaging workflows.

Instead, it serves as:

- a research platform
- a runtime loader proof-of-concept
- a foundation for plugin systems
- a tool for ephemeral Python execution

---

Whispy treats Python packages as **streams of capability**, not permanent state.

That’s the idea.

---

## ⚠️ Disclaimer

Whispy dynamically executes third-party code.

Use only in trusted environments.

This project is experimental.

---

## 📜 License

MIT — do whatever you want, just don’t blame me if you load Skynet.

🤖

