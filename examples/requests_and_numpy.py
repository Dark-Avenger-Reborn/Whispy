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
        exec(code, mod.__dict__)
        sys.modules[name] = mod

    _loaded_modules[package] = sys.modules.get(package)
    return _loaded_modules[package]


requests = import_remote_packages("requests")
numpy = import_remote_packages("numpy")

print(requests.get("https://httpbin.org/get").status_code)
numpy.test()
