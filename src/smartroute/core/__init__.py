"""Core routing primitives."""

from .base import BasePlugin, MethodEntry
from .decorators import RoutedClass, route, routers
from .router import Router

__all__ = [
    "Router",
    "route",
    "routers",
    "RoutedClass",
    "BasePlugin",
    "MethodEntry",
]
