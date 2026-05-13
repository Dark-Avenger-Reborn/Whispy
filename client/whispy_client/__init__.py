"""
whispy_client — Stream Python packages at runtime, no pip install required.

    from whispy_client import remote

    requests = remote("requests")
    numpy    = remote("numpy", version="1.26.4")
    bs4      = remote("beautifulsoup4", module="bs4", deps=True)
"""
from .core import remote, configure, WhispyError, __version__

__all__ = ["remote", "configure", "WhispyError", "__version__"]
