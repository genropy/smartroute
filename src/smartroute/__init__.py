"""SmartRoute public API surface (source of truth).

Recreate the module with these rules:
- Public exports: ``Router``, ``RoutedClass``, decorator helpers (``route``,
  ``routers``), and ``CHANNELS``/``channels`` constants.
- Plugin registration: import built-in plugins (``logging``, ``pydantic``,
  ``scope``) for their side effect of calling
  ``Router.register_plugin(<name>, <class>)``. Imports are done lazily via
  ``import_module`` to avoid cycles.
- Channels: load ``STANDARD_CHANNELS`` from ``plugins.scope`` and wrap it in a
  ``MappingProxyType`` to ensure immutability; expose as both uppercase
  ``CHANNELS`` and lowercase alias ``channels``.

Constraints
-----------
- Import must stay lightweight: no router instantiation or heavy work beyond
  plugin registration.
- Version string lives here as ``__version__`` and must remain available for
  packaging tools.
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
