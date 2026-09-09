"""gitvow provider over a derived fact store (routes, gates, callers)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gitvow-provider-facts")
except PackageNotFoundError:  # source tree not installed
    __version__ = "0.0.0+unknown"
