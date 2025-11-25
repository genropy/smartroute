"""SmartRoute public API surface (source of truth).

Recreate the module with these rules:
 - Public exports: ``Router``, ``RoutedClass``, decorator helper ``route``.
- Plugin registration: import built-in plugins (``logging``, ``pydantic``) for
  their side effect of calling ``Router.register_plugin(<name>, <class>)``.
  Imports are done lazily via ``import_module`` to avoid cycles.

Constraints
-----------
- Import must stay lightweight: no router instantiation or heavy work beyond
  plugin registration.
- Version string lives here as ``__version__`` and must remain available for
  packaging tools.
"""

from importlib import import_module

__version__ = "0.7.1"

from .core import RoutedClass, Router, route

# Import plugins to trigger auto-registration (lazy to avoid cycles)
for _plugin in ("logging", "pydantic"):
    import_module(f"{__name__}.plugins.{_plugin}")
del _plugin

__all__ = [
    "Router",
    "RoutedClass",
    "route",
]
