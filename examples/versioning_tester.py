"""
Example: Using specific package versions
This demonstrates how to load a specific version of a package
"""
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
    with urllib.request.urlopen(url) as r: data = io.BytesIO(r.read()) if r.getcode() == 200 else (_ for _ in ()).throw(Exception(r.read().decode()))
    td = tempfile.TemporaryDirectory(); zipfile.ZipFile(data).extractall(td.name); sys.path.insert(0, td.name)
    sys._in_memory_packages = getattr(sys, '_in_memory_packages', []) + [td]
    try: return importlib.import_module(module)
    except Exception as e: raise RuntimeError(f"Failed to import {module}: {e}")

if __name__ == "__main__":
    try:
        # Load humanize with a specific version
        print("🔍 Loading humanize version 4.9.0...")
        humanize = import_remote_packages("humanize", ver="4.9.0")
        print("✅ humanize version:", humanize.__version__)
        
        # Show some humanize functionality
        import datetime
        now = datetime.datetime.now()
        past = now - datetime.timedelta(days=3, hours=5, minutes=30)
        
        print("\n📦 humanize functionality:")
        print(f"  • Natural time: {humanize.naturaltime(past)}")
        print(f"  • File size: {humanize.naturalsize(1024*1024*15)}")
        print(f"  • Number: {humanize.intcomma(1234567)}")
        print(f"  • Ordinal: {humanize.ordinal(42)}")
    except Exception as e:
        print(f"❌ Error: {e}")
