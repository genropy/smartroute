"""Core Runtime Aggregator
===========================

The `smartroute.core` package bundles the minimal pieces required to build
instance-scoped routers:

- :mod:`~smartroute.core.router` supplies the runtime Router implementation
- :mod:`~smartroute.core.decorators` contains decorator/proxy helpers
- :mod:`~smartroute.core.base` defines plugin primitives

This module re-exports the public entry points so consumers can simply write
``from smartroute.core import Router, route`` without worrying about the
underlying structure.
"""

from .decorators import route, routers
from .routed import RoutedClass
from .router import Router

__all__ = [
    "Router",
    "route",
    "routers",
    "RoutedClass",
]
