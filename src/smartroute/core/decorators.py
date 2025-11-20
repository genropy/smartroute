"""Decorators and RoutedClass helpers for runtime routers.

This module bridges plain Python classes with the runtime Router by exposing
`@route` markers and re-exports the :class:`~smartroute.core.routed.RoutedClass`
mixing that tracks routers per instance.

Key ideas
---------
- decorators never mutate routers directly; they only annotate callables
- `RoutedClass` centralises router lookup/configuration so applications do not
  have to manually wire registries
- module-level helpers avoid importing router internals in user code
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Type

from .base_router import TARGET_ATTR
from .routed import RoutedClass
from .router import Router

__all__ = ["route", "routers", "RoutedClass"]


def route(
    router: str, *, name: Optional[str] = None, alias: Optional[str] = None, **kwargs: Any
) -> Callable:
    """Mark a bound method for inclusion in the given router.

    Args:
        router: Router identifier (e.g. ``"api"``).
        name: Optional explicit entry name (overrides function name/prefix stripping).
        alias: Deprecated alias for ``name`` (kept for compatibility).
    """

    def decorator(func: Callable) -> Callable:
        markers = list(getattr(func, TARGET_ATTR, []))
        payload = {"name": router}
        entry_name = alias if name is None else name
        if entry_name is not None:
            payload["entry_name"] = entry_name
        for key, value in kwargs.items():
            payload[key] = value
        markers.append(payload)
        setattr(func, TARGET_ATTR, markers)
        return func

    return decorator


def routers(*_names: str, **_named: Router) -> Callable[[Type], Type]:
    """Legacy placeholder for class-level router declaration."""

    def decorator(cls: Type) -> Type:
        return cls

    return decorator
