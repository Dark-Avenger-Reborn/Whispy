from flask import Flask, request, jsonify
import requests as req
import tarfile, zipfile, io, traceback, re, hashlib, os, json

app = Flask(__name__)
CACHE_DIR = "./cache"
PYPI_API = "https://pypi.org/pypi/{}/json"

os.makedirs(CACHE_DIR, exist_ok=True)

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def cache_path(pkg, version):
    return os.path.join(CACHE_DIR, f"{pkg}-{version}.json")

def load_cache(pkg, version):
    path = cache_path(pkg, version)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_cache(pkg, version, data):
    with open(cache_path(pkg, version), "w", encoding="utf-8") as f:
        json.dump(data, f)

def fetch_from_pypi(pkg, version=None, force=False):
    meta = req.get(PYPI_API.format(pkg)).json()
    version = version or meta["info"]["version"]

    if not force:
        cached = load_cache(pkg, version)
        if cached:
            return cached

    files = meta["releases"].get(version, [])
    file = next((f for f in files if f["filename"].endswith(".whl")), None) \
        or next((f for f in files if f["filename"].endswith(".tar.gz")), None)

    if not file:
        raise Exception(f"No supported file found for {pkg}=={version}")

    data = req.get(file["url"]).content
    if sha256(data) != file["digests"]["sha256"]:
        raise Exception(f"SHA256 mismatch for {pkg}=={version}")

    modules = extract_py_files(data, file["filename"])
    save_cache(pkg, version, modules)
    return modules

def extract_py_files(data, filename):
    mods = {}

    if filename.endswith((".whl", ".zip")):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.endswith(".py") and not name.startswith("tests"):
                    mod = clean_mod_path(name)
                    mods[mod] = z.read(name).decode("utf-8")
    elif filename.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.name.endswith(".py") and m.isfile():
                    mod = clean_mod_path(m.name)
                    mods[mod] = tar.extractfile(m).read().decode("utf-8")
    return mods

def clean_mod_path(path):
    path = re.sub(r"^\./?", "", path)
    path = re.sub(r"[^/]*-(dist|egg).*/", "", path)
    path = path.replace("/", ".").replace("\\", ".")
    return path[:-12] if path.endswith("__init__.py") else path[:-3] if path.endswith(".py") else path

@app.route("/get_modules", methods=["POST"])
def get_modules():
    try:
        data = request.get_json()
        packages = data.get("packages", [])
        force = request.args.get("force") == "true"
        result = {}

        for pkg in packages:
            name, version = pkg.get("name"), pkg.get("version")
            result[name] = fetch_from_pypi(name, version, force=force)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    app.run("0.0.0.0", port=5000)
