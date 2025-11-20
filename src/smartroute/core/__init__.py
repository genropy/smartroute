"""Core Runtime Aggregator
===========================

The `smartroute.core` package bundles the minimal pieces required to build
instance-scoped routers:

- :mod:`~smartroute.core.base_router` supplies the plugin-free router
- :mod:`~smartroute.core.decorators` contains decorator/proxy helpers
- :mod:`~smartroute.core.routed` defines :class:`RoutedClass`

This module re-exports the public entry points so consumers can simply write
``from smartroute.core import Router, route`` without worrying about the
underlying structure.
"""

from .base_router import BaseRouter
from .decorators import route, routers
from .routed import RoutedClass
from .router import Router

__all__ = [
    "BaseRouter",
    "Router",
    "route",
    "routers",
    "RoutedClass",
]
