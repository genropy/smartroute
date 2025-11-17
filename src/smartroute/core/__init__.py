"""Core routing primitives."""

from .base import BasePlugin, MethodEntry
from .decorators import RoutedClass, route, routers
from .router import BoundRouter, Router, RouteSpec

__all__ = [
    "Router",
    "BoundRouter",
    "RouteSpec",
    "route",
    "routers",
    "RoutedClass",
    "BasePlugin",
    "MethodEntry",
]
