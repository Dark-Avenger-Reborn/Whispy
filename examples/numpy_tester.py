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

    # Read entire zip content into memory
    zip_data = io.BytesIO(response.read())

    # Create a temporary directory in memory (OS will handle cleanup on exit)
    temp_dir = tempfile.TemporaryDirectory()
    with zipfile.ZipFile(zip_data) as zip_ref:
        zip_ref.extractall(temp_dir.name)

    # Prepend to sys.path so imports will use it
    sys.path.insert(0, temp_dir.name)

    # Store temp_dir so it doesn't get garbage collected
    if not hasattr(sys, "_in_memory_packages"):
        sys._in_memory_packages = []
    sys._in_memory_packages.append(temp_dir)

    try:
        module = importlib.import_module(package_name)
        return module
    except Exception as e:
        raise RuntimeError(f"Failed to import {package_name}: {e}")

# Example usage
if __name__ == "__main__":
    numpy = import_remote_packages("numpy")
    print("✅ NumPy version:", numpy.__version__)
