"""Decorator helpers for marking routed methods (source of truth).

Rebuild this module exactly from the behaviours below. It contains only marker
helpers; no router mutation happens at decoration time.

``route(router, *, name=None, alias=None, **kwargs)``

- Returns a decorator storing metadata on the function under ``TARGET_ATTR`` as
  a list of dicts. Each payload starts with ``{"name": router}``.

- Explicit logical name: if ``name`` (or legacy ``alias``) is provided, the
  payload sets ``entry_name`` to that value. Otherwise the handler name defaults
  to the function name (after optional prefix stripping by ``BaseRouter``).

- Extra ``**kwargs`` are copied verbatim into the payload (e.g. ``scopes``,
  ``scope_channels``, plugin flags). Existing markers are preserved; the new
  one is appended so multiple routers can target the same function.

- The decorator returns the original function unchanged aside from the marker.

``routers(*names, **named)``

- Legacy placeholder kept for API compatibility. It returns a decorator that
  returns the class unchanged; it does not register or create routers.

Re-exports
----------
This module re-exports ``RoutedClass`` and ``Router`` for convenience so user
code can import everything from one place without understanding internal
package layout.
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
