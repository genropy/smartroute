"""Decorator helpers for marking routed methods (source of truth).

Rebuild this module exactly from the behaviours below. It contains only marker
helpers; no router mutation happens at decoration time.

``route(router, *, name=None, **kwargs)``

- Returns a decorator storing metadata on the function under ``TARGET_ATTR_NAME`` as
  a list of dicts. Each payload starts with ``{"name": router}``.

- Explicit logical name: if ``name`` is provided, the payload sets ``entry_name``
  to that value. Otherwise the handler name defaults to the function name (after
  optional prefix stripping by ``BaseRouter``).

- Extra ``**kwargs`` are copied verbatim into the payload (e.g. ``scopes``,
  ``scope_channels``, plugin flags). Existing markers are preserved; the new
  one is appended so multiple routers can target the same function.

- The decorator returns the original function unchanged aside from the marker.

Re-exports
----------
This module re-exports ``RoutedClass`` and ``Router`` for convenience so user
code can import everything from one place without understanding internal
package layout.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .base_router import TARGET_ATTR_NAME
from .routed import RoutedClass
from .router import Router

__all__ = ["route", "RoutedClass", "Router"]


def route(router: str, *, name: Optional[str] = None, **kwargs: Any) -> Callable:
    """Mark a bound method for inclusion in the given router.

    Args:
        router: Router identifier (e.g. ``"api"``).
        name: Optional explicit entry name (overrides function name/prefix stripping).
    """

    def decorator(func: Callable) -> Callable:
        markers = list(getattr(func, TARGET_ATTR_NAME, []))
        payload = {"name": router}
        if name is not None:
            payload["entry_name"] = name
        for key, value in kwargs.items():
            payload[key] = value
        markers.append(payload)
        setattr(func, TARGET_ATTR_NAME, markers)
        return func

    return decorator
