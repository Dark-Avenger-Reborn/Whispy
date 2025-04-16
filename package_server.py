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
from collections import namedtuple

Tag = namedtuple('Tag', ['interpreter', 'abi', 'platform'])

class TagWrapper:
    def __init__(self, tag: Tag):
        self.tag = tag

    def __repr__(self):
        return f"{self.tag.interpreter}-{self.tag.abi}-{self.tag.platform}"

    def __eq__(self, other):
        return isinstance(other, TagWrapper) and self.tag == other.tag

    def __hash__(self):
        return hash(self.tag)


class Version:
    def __init__(self, version_str):
        self._version = version_str

    def __repr__(self):
        return f"<Version('{self._version}')>"

    def __eq__(self, other):
        return isinstance(other, Version) and self._version == other._version

    def __hash__(self):
        return hash(self._version)


CACHE_DIR = './cache'
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def get_sha256_hash(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def verify_download(file_path, expected_sha256):
    print(f"🔍 Verifying SHA256: {expected_hash}")
    actual_sha256 = get_sha256_hash(file_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}")

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

def parse_wheel_filename(filename):
    # Remove .whl extension
    if not filename.endswith('.whl'):
        raise ValueError("Not a .whl file")
    name = filename[:-4]

    # Split the filename into parts
    parts = name.split('-')
    if len(parts) < 5:
        raise ValueError("Filename format is not valid")

    # Extract name and version
    distribution = parts[0]
    version = Version(parts[1])
    py_tag = parts[2]
    abi_tag = parts[3]
    platforms = '-'.join(parts[4:])  # Re-join in case platform contains dashes

    # Split platforms by dots
    platform_tags = platforms.split('.')
    # Create TagWrapper instances
    tag_set = frozenset(TagWrapper(Tag(py_tag, abi_tag, platform)) for platform in platform_tags)
    return (distribution, version, (), tag_set)

def parse_wheel_tags(filename, tags_input):
    try:
        parsed = parse_wheel_filename(filename)
        # Check the tuple length
        if len(parsed) == 2:
            # Older packaging versions may return (name_version, tagset)
            _, tagset = parsed
        elif len(parsed) == 4:
            # Newer packaging versions return (distribution, version, build, tagset)
            _, _, _, tagset = parsed
        else:
            print(f"⚠️ Unexpected parse_wheel_filename tuple length for {filename}: {len(parsed)}")
            return set()
        return set(str(tag) for tag in tagset)
    except Exception as e:
        print(f"⚠️ Failed to parse tags for {filename}: {e}")
        return set()

def cast_to_tag(tag_like) -> Tag:
    if isinstance(tag_like, Tag):
        return tag_like
    if isinstance(tag_like, str):
        parts = tag_like.split('-')
        if len(parts) == 3:
            return Tag(*parts)
        else:
            raise ValueError(f"Invalid tag string format: '{tag_like}'")
    raise TypeError(f"Cannot cast type {type(tag_like)} to Tag")

def compatible_with_current(tags, tags_input):
    current = set(f"{cast_to_tag(tag).interpreter}-{cast_to_tag(tag).abi}-{cast_to_tag(tag).platform}" for tag in tags_input.split(","))
    return not tags.isdisjoint(current)

def find_best_wheel(links, tags_input):
    wheels = []
    for link in links:
        if link.endswith('.whl'):
            filename = os.path.basename(link)
            tags = parse_wheel_tags(filename, tags_input)
            wheels.append((link, tags))

    compatible = [(link, tags) for link, tags in wheels if compatible_with_current(tags, tags_input)]
    if compatible:
        return compatible[0][0]
    return None

def find_sdist(links):
    for link in links:
        if link.endswith(('.tar.gz', '.zip', '.tar.bz2', '.tar')):
            return link
    return None

def download_and_extract_package(package_name, tags, version=None):
    index_url = f"https://pypi.org/pypi/{urllib.parse.quote(package_name)}/json"
    with urllib.request.urlopen(index_url) as response:
        data = json.load(response)

    version = version or data['info']['version']
    release = data['releases'].get(version)
    if not release:
        raise ValueError(f"Version {version} not found for {package_name}")

    links = [f["url"] for f in release]
    best_wheel = find_best_wheel(links, tags)
    temp_dir = tempfile.mkdtemp()

    def try_verify(file_path, file_info):
        if file_info and "digests" in file_info and "sha256" in file_info["digests"]:
            expected_hash = file_info["digests"]["sha256"]
            print(f"🔐 Verifying hash: {expected_hash}")
            verify_download(file_path, expected_hash)
        else:
            print("⚠️  No SHA256 digest found for file. Skipping verification.")

    if best_wheel:
        wheel_info = next((f for f in release if f["url"] == best_wheel), None)
        wheel_path = os.path.join(temp_dir, os.path.basename(best_wheel))
        print(f"📦 Downloading wheel: {best_wheel}")
        download_url(best_wheel, wheel_path)
        try_verify(wheel_path, wheel_info)
        extract_archive(wheel_path, temp_dir)
        return temp_dir

    sdist = find_sdist(links)
    if sdist:
        sdist_info = next((f for f in release if f["url"] == sdist), None)
        sdist_path = os.path.join(temp_dir, os.path.basename(sdist))
        print(f"📦 Downloading source: {sdist}")
        download_url(sdist, sdist_path)
        try_verify(sdist_path, sdist_info)
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

def make_cache_key(package_name, version, tags):
    tag_hash = hashlib.sha256(tags.encode()).hexdigest()[:8]
    return f"{package_name}-{version}-{tag_hash}"


def get_cached_package(package_name, version, tags):
    cache_key = make_cache_key(package_name, version, tags)
    cache_meta_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    if os.path.exists(cache_meta_file):
        with open(cache_meta_file, 'r') as f:
            cached_data = json.load(f)

        cached_file_path = cached_data['file_path']
        if os.path.exists(cached_file_path):
            cached_sha256 = cached_data['sha256']
            current_sha256 = get_sha256_hash(cached_file_path)
            if current_sha256 == cached_sha256:
                print("✅ Cache hit.")
                return cached_file_path
            else:
                print("❌ Cache hash mismatch.")

    return None


def update_cache(package_name, version, package_file_path, tags):
    cache_key = make_cache_key(package_name, version, tags)
    sha256 = get_sha256_hash(package_file_path)

    dest_zip = os.path.join(CACHE_DIR, f"{cache_key}.zip")
    shutil.copyfile(package_file_path, dest_zip)

    cache_meta_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    package_data = {
        'file_path': dest_zip,
        'sha256': sha256
    }

    with open(cache_meta_file, 'w') as f:
        json.dump(package_data, f)

    return dest_zip

@app.route("/get_package", methods=["GET"])
def get_package():
    package_name = request.args.get("name")
    version = request.args.get("version")
    tags = request.args.get("tags")

    if not package_name:
        return jsonify({"error": "Missing 'name' parameter"}), 400
    if not tags:
        return jsonify({"error": "Missing 'tags' parameter"}), 400

    try:
        cached_package = get_cached_package(package_name, version, tags)

        if cached_package:
            return send_file(cached_package, as_attachment=True, download_name=f"{package_name}.zip")

        # Download and extract
        extracted_dir = download_and_extract_package(package_name, tags, version)

        # Write to a uniquely named temp file
        tmp_fd, tmp_zip_path = tempfile.mkstemp(suffix='.zip')
        os.close(tmp_fd)
        shutil.make_archive(tmp_zip_path[:-4], 'zip', extracted_dir)

        # Update cache
        final_cached_path = update_cache(package_name, version, tmp_zip_path, tags)

        # Serve from memory
        with open(final_cached_path, "rb") as f:
            zip_bytes = f.read()
        buffer = BytesIO(zip_bytes)

        # Clean up
        shutil.rmtree(extracted_dir)
        os.remove(tmp_zip_path)

        return send_file(buffer, as_attachment=True, download_name=f"{package_name}.zip")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
