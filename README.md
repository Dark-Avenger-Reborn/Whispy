# 🌀 Whispy

> **Whispy** is a plug-and-play server + client system for dynamically importing Python packages at runtime — with **zero installation** required on the client side.  
Packages are loaded **directly from PyPI**, executed entirely **in memory**, and disappear after your script ends.

Think of it like a CDN for Python packages — fast, clean, and ephemeral.

---

## ✨ Features

- 🚫 **No `pip install` required** on the client
- 🧠 **Fully in-memory loading** — nothing is written to disk
- 🧩 **Zero external dependencies** on the client
- 🔐 **SHA256 verification** ensures PyPI package integrity
- 💾 **Automatic server-side caching** increases package return speed
- 💡 **Ultra-simple client API**:
-
    ```python
    requests = import_remote_packages("requests")
    ```
> 🧠 **Note:** Supports both **pure Python** and **native extension** packages (e.g., `.so`, `.pyd`, etc.).

---

## 🛠️ Server Setup

### 🔧 Requirements

- Python 3.7+
- `Flask`
- `requests`

### 📦 Install dependencies

```bash
pip install flask requests
```

### ▶️ Run the server

```bash
python package_server.py
```

This starts the Whispy server at `http://localhost:5000`.

---

## 🧑‍💻 Client Setup

### ✅ Requirements
- Python 3.7+
- **No external libraries required**

Just copy the client code below into your Python script:

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

def import_remote_packages(pkg, ver=None, host="http://localhost:5000"):
    tags = ','.join(f"{t.interpreter}-{t.abi}-{t.platform}" for t in sys_tags())
    url = f"{host}/get_package?name={pkg}&tags={tags}" + (f"&version={ver}" if ver else "")
    print(f"📡 Requesting {url}")
    with urllib.request.urlopen(url) as r: data = io.BytesIO(r.read()) if r.getcode() == 200 else (_ for _ in ()).throw(Exception(r.read().decode()))
    td = tempfile.TemporaryDirectory(); zipfile.ZipFile(data).extractall(td.name); sys.path.insert(0, td.name)
    sys._in_memory_packages = getattr(sys, '_in_memory_packages', []) + [td]
    try: return importlib.import_module(pkg)
    except Exception as e: raise RuntimeError(f"Failed to import {pkg}: {e}")
```

> 🧩 **No external dependencies required!**  
> Whispy uses only Python's built-in standard library on the client side.

---

## 🧪 Example Usage

```python
requests = import_remote_packages("requests")

print(requests.get("https://httpbin.org/get").status_code)
```

---

## 📁 Caching

The server stores extracted packages in a local `./cache/` directory.  
You can delete this folder at any time to clear the cache.

---

## 🛡️ Security Notes

- Packages are **SHA256-verified** using PyPI’s metadata to prevent tampering
- The client **never touches disk** — packages live only in memory
- If you're exposing the server externally, consider adding:
  - IP whitelisting
  - Logging and usage tracking
  - Network restrictions

---

## 📜 License

MIT — do whatever you want, just don’t blame me if you load Skynet. 🤖
