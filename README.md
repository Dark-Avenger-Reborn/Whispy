# 🌀 Whispy

> **Whispy** is a plug-and-play server + client system for dynamically importing Python packages at runtime — with **zero installation** required on the client side.  
Packages are loaded **directly from PyPI**, executed entirely **in memory**, and disappear after your script ends.

Think of it like a CDN for Python packages — fast, clean, and ephemeral.

---

## ✨ Features

- 🚫 **No `pip install` required** on the client
- 🧠 **Fully in-memory loading** — nothing is written to disk
- 🔐 **SHA256 verification** ensures PyPI package integrity
- 💾 **Automatic server-side caching** (optional force-refresh)
- 🧩 **Zero external dependencies** on the client
- 💡 **Ultra-simple client API**:
    ```python
    requests = import_remote_packages("requests")
    numpy = import_remote_packages("numpy")
    ```

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
import sys, types, json
from urllib.request import Request, urlopen

_loaded_modules = {}

def import_remote_packages(package):
    if package in _loaded_modules:
        return _loaded_modules[package]

    data = json.dumps({"packages": [{"name": package}]}).encode("utf-8")
    req = Request("http://localhost:5000/get_modules", data=data, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        mods = json.loads(resp.read().decode("utf-8")).get(package, {})

    for name, code in mods.items():
        mod = types.ModuleType(name)
        mod.__name__ = name
        mod.__package__ = name.rsplit('.', 1)[0]
        exec(code, mod.__dict__)
        sys.modules[name] = mod
    
    _loaded_modules[package] = sys.modules.get(package)
    return _loaded_modules[package]
```

> 🧩 **No external dependencies required!**  
> Whispy uses only Python's built-in standard library on the client side.

---

## 🧪 Example Usage

```python
requests = import_remote_packages("requests")
numpy = import_remote_packages("numpy")

print(requests.get("https://httpbin.org/get").status_code)
numpy.test()
```

---

## 🔄 Optional: Cache Invalidation

To bypass the server’s cache and force a fresh download from PyPI:

```bash
POST http://localhost:5000/get_modules?force=true
```

In client code:
```python
req = Request("http://localhost:5000/get_modules?force=true", data=..., headers=...)
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
