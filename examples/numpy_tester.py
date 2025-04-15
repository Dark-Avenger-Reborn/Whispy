import sys
import importlib
import urllib.request
import io
import zipfile
import tempfile
import os
import platform
import struct
from collections import namedtuple

# Define a Tag namedtuple to handle tag data
Tag = namedtuple('Tag', ['interpreter', 'abi', 'platform'])

def get_interpreter():
    if platform.python_implementation() == 'CPython':
        return f"cp{sys.version_info.major}{sys.version_info.minor}"
    elif platform.python_implementation() == 'PyPy':
        ver = sys.pypy_version_info
        return f"pp{ver.major}{ver.minor}"
    return 'py3'

def get_abi():
    if platform.python_implementation() == 'CPython':
        return f"cp{sys.version_info.major}{sys.version_info.minor}"
    elif platform.python_implementation() == 'PyPy':
        ver = sys.pypy_version_info
        return f"pypy{ver.major}{ver.minor}_pp73"
    return 'none'

def get_platforms():
    machine = platform.machine().lower()
    system = platform.system()

    platforms = []

    if system == 'Linux':
        if machine == 'x86_64':
            platforms = [
                'manylinux_2_28_x86_64',
                'manylinux_2_17_x86_64',
                'manylinux2014_x86_64',
            ]
        elif machine == 'aarch64':
            platforms = [
                'manylinux_2_28_aarch64',
                'manylinux_2_17_aarch64',
                'manylinux2014_aarch64',
            ]
        elif machine == 'armv7l':
            platforms = [
                'manylinux_2_28_armv7l',
                'manylinux_2_17_armv7l',
                'manylinux2014_armv7l',
            ]
        else:
            platforms = [f'manylinux2014_{machine}']
    elif system == 'Windows':
        platforms = ['win_amd64' if '64' in machine else 'win32']
    elif system == 'Darwin':
        platforms = ['macosx_10_9_x86_64']  # Adjust for more if needed

    platforms.append('any')  # Always include universal tag
    return platforms


def sys_tags():
    interpreter = get_interpreter()
    abi = get_abi()
    platforms = get_platforms()

    tags = []
    # Add interpreter, ABI, and platform combinations
    for plat in platforms:
        tags.append(Tag(interpreter, abi, plat))  # Exact match for current system
        if interpreter.startswith('cp'):
            tags.append(Tag(interpreter, 'abi3', plat))  # For "cpX-abi3" compatibility
        tags.append(Tag('py3', 'none', plat))  # For universal wheels

    # Handle additional specific combinations (to mimic packaging exactly)
    if interpreter.startswith('cp'):
        py_version = interpreter[2:]  # Extract version from "cpXY" string
        for plat in platforms:
            # Ensure we add ABI3 and none versions for fallback compatibility
            tags.append(Tag(interpreter, 'abi3', plat))
            tags.append(Tag(interpreter, 'none', plat))  # Specific interpreter fallback

    return tags


def import_remote_packages(package_name, version=None, server_url="http://localhost:5000"):
    # Gather the tags of the current client
    client_tags = sys_tags()
    
    # Prepare the query with the package name and version
    query = f"?name={package_name}&tags=" + ','.join([f"{tag.interpreter}-{tag.abi}-{tag.platform}" for tag in client_tags])
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
