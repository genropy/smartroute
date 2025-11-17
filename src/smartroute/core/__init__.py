"""Core routing primitives."""

from .base import BasePlugin, MethodEntry
from .decorators import RoutedClass, route, routers
from .router import Router, RouteSpec

__all__ = [
    "Router",
    "RouteSpec",
    "route",
    "routers",
    "RoutedClass",
    "BasePlugin",
    "MethodEntry",
]
