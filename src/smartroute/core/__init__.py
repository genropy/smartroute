"""Core runtime aggregator (source of truth).

Purpose: expose the runtime building blocks from a single module:
``BaseRouter``, ``Router``, ``route``, ``RoutedClass``. No extra
logic beyond imports/exports.

Guarantees
----------
- Importing this module performs only imports; it does not register plugins or
  instantiate routers.
- Public API mirrors underlying modules 1:1:
  * ``base_router`` → ``BaseRouter`` (plugin-free engine)
  * ``router`` → ``Router`` (plugin-enabled)
  * ``decorators`` → ``route`` helper
  * ``routed`` → ``RoutedClass`` mixin
"""

from .base_router import BaseRouter
from .decorators import route
from .routed import RoutedClass
from .router import Router

__all__ = [
    "BaseRouter",
    "Router",
    "route",
    "RoutedClass",
]
