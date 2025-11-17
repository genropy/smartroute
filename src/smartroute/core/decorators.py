"""Decorators and mixins for router registration."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Type

from .router import Router

__all__ = ["route", "routers", "RoutedClass"]

_TARGET_ATTR = "__smartroute_targets__"
_FINALIZED_ATTR = "__smartroute_finalized__"


def route(name: str, *, alias: Optional[str] = None) -> Callable[[Callable], Callable]:
    """
    Generic decorator that marks a method for registration with the given router name.
    """

    def decorator(func: Callable) -> Callable:
        markers = list(getattr(func, _TARGET_ATTR, []))
        markers.append({"name": name, "alias": alias})
        setattr(func, _TARGET_ATTR, markers)
        return func

    return decorator


def routers(*names: str, **named: Router) -> Callable[[Type], Type]:
    """
    Class decorator that instantiates routers and registers marked methods.
    """

    def decorator(cls: Type) -> Type:
        if getattr(cls, _FINALIZED_ATTR, False):
            return cls
        router_map: Dict[str, Router] = dict(named)
        # Include routers already defined as class attributes
        for attr_name, value in vars(cls).items():
            if isinstance(value, Router):
                router_map.setdefault(attr_name, value)
        # Auto instantiate positional routers with default configuration
        for positional in names:
            router_map.setdefault(positional, Router(name=positional))

        # Discover all markers and ensure routers exist
        for attr_name, value in vars(cls).items():
            markers = getattr(value, _TARGET_ATTR, None)
            if not markers:
                continue
            for marker in markers:
                router_name = marker["name"]
                alias = marker.get("alias")
                router = router_map.setdefault(router_name, Router(name=router_name))
                router._register(value, alias)

        # Attach all routers as descriptors
        for attr_name, router in router_map.items():
            setattr(cls, attr_name, router)
        setattr(cls, _FINALIZED_ATTR, True)
        return cls

    return decorator


class RoutedClass:
    """Mixin that automatically finalizes routers defined on subclasses."""

    __slots__ = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        routers()(cls)
