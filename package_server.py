import hashlib
import os
import json
import shutil
import tempfile
import urllib.request
import zipfile
import tarfile
from flask import Flask, request, send_file, jsonify
from io import BytesIO
from pathlib import Path
import urllib.parse

CACHE_DIR = './cache'
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def get_sha256_hash(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def download_url(url, dest):
    print(f"⬇️  Downloading {url}")
    with urllib.request.urlopen(url) as response, open(dest, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def extract_archive(archive_path, extract_to):
    if archive_path.endswith(".whl") or archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
    elif archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
        with tarfile.open(archive_path, 'r:gz') as tar:
            tar.extractall(extract_to)
    elif archive_path.endswith(".tar.bz2"):
        with tarfile.open(archive_path, 'r:bz2') as tar:
            tar.extractall(extract_to)
    elif archive_path.endswith(".tar"):
        with tarfile.open(archive_path, 'r:') as tar:
            tar.extractall(extract_to)
    else:
        raise ValueError(f"Unsupported archive format: {archive_path}")

def download_and_extract_package(package_name, version=None):
    index_url = f"https://pypi.org/pypi/{urllib.parse.quote(package_name)}/json"
    with urllib.request.urlopen(index_url) as response:
        data = json.load(response)

    version = version or data['info']['version']
    release = data['releases'].get(version)
    if not release:
        raise ValueError(f"Version {version} not found for {package_name}")

    links = [f["url"] for f in release]
    best_wheel = find_best_wheel(links)
    temp_dir = tempfile.mkdtemp()

    if best_wheel:
        wheel_path = os.path.join(temp_dir, os.path.basename(best_wheel))
        print(f"📦 Downloading wheel: {best_wheel}")
        download_url(best_wheel, wheel_path)
        extract_archive(wheel_path, temp_dir)
        return temp_dir

    # Fall back to source dist
    sdist = find_sdist(links)
    if sdist:
        sdist_path = os.path.join(temp_dir, os.path.basename(sdist))
        print(f"📦 Downloading source: {sdist}")
        download_url(sdist, sdist_path)
        extract_archive(sdist_path, temp_dir)
        return temp_dir

    raise RuntimeError("No compatible distribution found.")

def get_cached_package(package_name, version):
    cache_file = os.path.join(CACHE_DIR, f"{package_name}-{version}.json")
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            cached_data = json.load(f)

        cached_file_path = cached_data['file_path']
        cached_sha256 = cached_data['sha256']
        current_sha256 = get_sha256_hash(cached_file_path)
        
        if current_sha256 == cached_sha256:
            print("Cache hit, returning cached package.")
            return cached_file_path

    return None

def update_cache(package_name, version, package_file_path):
    # Generate SHA-256 hash for the downloaded file
    sha256 = get_sha256_hash(package_file_path)

    # Store file path and hash in cache
    cache_file = os.path.join(CACHE_DIR, f"{package_name}-{version}.json")
    package_data = {
        'file_path': package_file_path,
        'sha256': sha256
    }

    with open(cache_file, 'w') as f:
        json.dump(package_data, f)

    return package_file_path

app = Flask(__name__)

@app.route("/get_package", methods=["GET"])
def get_package():
    package_name = request.args.get("name")
    version = request.args.get("version")

    if not package_name:
        return jsonify({"error": "Missing 'name' parameter"}), 400

    try:
        # Check if package is in cache
        cached_package = get_cached_package(package_name, version)
        
        if cached_package:
            # If cached and valid, serve it
            with open(cached_package, 'rb') as f:
                return send_file(f, as_attachment=True, download_name=f"{package_name}.zip")

        # If not cached or invalid, download and extract the package
        extracted_dir = download_and_extract_package(package_name, version)

        # Zip the folder to send
        buffer = BytesIO()
        shutil.make_archive("/tmp/pkg", 'zip', extracted_dir)
        with open("/tmp/pkg.zip", "rb") as f:
            buffer.write(f.read())
        buffer.seek(0)

        shutil.rmtree(extracted_dir)
        os.remove("/tmp/pkg.zip")

        # Update cache after downloading and extracting
        update_cache(package_name, version, "/tmp/pkg.zip")

        return send_file(buffer, as_attachment=True, download_name=f"{package_name}.zip")

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
