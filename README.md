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
- 💾 **Automatic server-side caching** (optional force-refresh)
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
import sys
import importlib
import urllib.request
import io
import zipfile
import tempfile
import os

def import_remote_packages(package_name, version=None, server_url="http://localhost:5000"):
    query = f"?name={package_name}"
    if version:
        query += f"&version={version}"
    url = f"{server_url}/get_package{query}"
    print(f"📡 Requesting {url}")
    response = urllib.request.urlopen(url)
    if response.getcode() != 200:
        raise Exception(f"Server error: {response.read().decode()}")
    zip_data = io.BytesIO(response.read())
    temp_dir = tempfile.TemporaryDirectory()
    with zipfile.ZipFile(zip_data) as zip_ref:
        zip_ref.extractall(temp_dir.name)
    sys.path.insert(0, temp_dir.name)
    if not hasattr(sys, "_in_memory_packages"):
        sys._in_memory_packages = []
    sys._in_memory_packages.append(temp_dir)
    try:
        module = importlib.import_module(package_name)
        return module
    except Exception as e:
        raise RuntimeError(f"Failed to import {package_name}: {e}")
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
