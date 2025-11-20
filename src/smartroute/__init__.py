"""SmartRoute Public API Surface
=================================

Scope
-----
- expose `Router`, `RoutedClass`, and decorator helpers for application code
- eagerly register built-in plugins so `.plug("logging")` works everywhere
- publish the canonical `CHANNELS` mapping (uppercase symbolic names → description)

Rules
-----
- importing this module must *not* perform heavy work; only lightweight
  registrations are allowed
- `CHANNELS` is read-only (`MappingProxyType`) to guarantee consistency across
  CLI, Publisher, and application routers
- downstream documentation and tools must treat the exported channel names as
  the single source of truth
"""

from importlib import import_module
from types import MappingProxyType

__version__ = "0.4.1"

from .core import RoutedClass, Router, route, routers

# Import plugins to trigger auto-registration (lazy to avoid cycles)
for _plugin in ("logging", "pydantic", "scope"):
    import_module(f"{__name__}.plugins.{_plugin}")
del _plugin

from .plugins.scope import STANDARD_CHANNELS as _STANDARD_CHANNELS  # noqa: E402

CHANNELS = MappingProxyType(dict(_STANDARD_CHANNELS))
channels = CHANNELS

__all__ = [
    "Router",
    "RoutedClass",
    "route",
    "routers",
    "CHANNELS",
    "channels",
]
