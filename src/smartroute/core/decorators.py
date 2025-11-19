"""Decorators and mixins for router registration."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any, Callable, Dict, Optional, Type

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

    @property
    def routedclass(self) -> "_RoutedProxy":
        proxy = getattr(self, "__routed_proxy__", None)
        if proxy is None:
            proxy = _RoutedProxy(self)
            setattr(self, "__routed_proxy__", proxy)
        return proxy


class _RoutedProxy:
    def __init__(self, owner: RoutedClass):
        object.__setattr__(self, "_owner", owner)

    def get_router(self, name: str, path: Optional[str] = None):
        owner = self._owner
        base_name, extra_path = self._split_router_spec(name, path)
        router = getattr(owner.__class__, base_name, None)
        if router is None or not isinstance(router, Router):
            raise AttributeError(f"No Router named '{base_name}' on {type(owner).__name__}")
        bound = router.__get__(owner, type(owner))
        if not extra_path:
            return bound
        return self._navigate_router(bound, extra_path)

    # Helpers -------------------------------------------------
    def _split_router_spec(self, name: str, path: Optional[str]) -> tuple[str, Optional[str]]:
        extra_path = path
        base_name = name
        if not path and "." in name:
            base_name, extra_path = name.split(".", 1)
        return base_name, extra_path

    def _navigate_router(self, root, path: str):
        node = root
        for segment in path.split("."):
            segment = segment.strip()
            if not segment:
                continue
            node = node.get_child(segment)
        return node

    def _parse_target(self, target: str) -> tuple[str, str, str]:
        if ":" not in target:
            raise ValueError("Target must include router:plugin")
        router_part, rest = target.split(":", 1)
        router_part = router_part.strip()
        if not router_part:
            raise ValueError("Router name cannot be empty")
        if "/" in rest:
            plugin_part, selector = rest.split("/", 1)
        else:
            plugin_part, selector = rest, "_all_"
        plugin_part = plugin_part.strip()
        selector = selector.strip() or "_all_"
        if not plugin_part:
            raise ValueError("Plugin name cannot be empty")
        return router_part, plugin_part, selector

    def _match_handlers(self, router, selector: str) -> set[str]:
        names = list(router._entries.keys())
        patterns = [token.strip() for token in selector.split(",") if token.strip()]
        matched: set[str] = set()
        for pattern in patterns:
            for handler_name in names:
                if fnmatchcase(handler_name, pattern):
                    matched.add(handler_name)
        return matched

    def _apply_config(self, proxy: Any, options: Dict[str, Any]) -> None:
        for key, value in options.items():
            setattr(proxy, key, value)

    def _describe_all(self) -> Dict[str, Any]:
        owner = self._owner
        result: Dict[str, Any] = {}
        for attr_name, value in vars(type(owner)).items():
            if isinstance(value, Router):
                bound = value.__get__(owner, type(owner))
                result[attr_name] = self._describe_router(bound)
        return result

    def _describe_router(self, router) -> Dict[str, Any]:
        return {
            "name": router.name,
            "plugins": [
                {
                    "name": plugin.name,
                    "description": getattr(plugin, "description", ""),
                    "config": plugin.get_config(),
                    "overrides": {
                        handler: plugin.get_config(handler) for handler in router._entries.keys()
                    },
                }
                for plugin in router.iter_plugins()
            ],
            "handlers": list(router._entries.keys()),
            "children": {
                child_name: self._describe_router(child)
                for child_name, child in router._children.items()
            },
        }

    def configure(self, target: Any, **options: Any):
        if isinstance(target, (list, tuple)):
            if options:
                raise ValueError("Do not mix shared kwargs with list targets")
            return [self.configure(entry) for entry in target]
        if isinstance(target, dict):
            entry = dict(target)
            try:
                entry_target = entry.pop("target")
            except KeyError:
                raise ValueError("Dict targets must include 'target'")
            return self.configure(entry_target, **entry)
        if not isinstance(target, str):
            raise TypeError("Target must be a string, dict, or list")
        target = target.strip()
        if target == "?":
            if options:
                raise ValueError("Options are not allowed with '?'")
            return self._describe_all()
        router_spec, plugin_name, selector = self._parse_target(target)
        bound_router = self.get_router(router_spec)
        plugin = getattr(bound_router, plugin_name, None)
        if plugin is None:
            raise AttributeError(f"No plugin named '{plugin_name}' on router '{router_spec}'")
        if not options:
            raise ValueError("No configuration options provided")
        selector = selector or "_all_"
        if selector.lower() == "_all_":
            self._apply_config(plugin.configure, options)
            return {"target": target, "updated": ["_all_"]}
        matches = self._match_handlers(bound_router, selector)
        if not matches:
            raise KeyError(f"No handlers matching '{selector}' on router '{router_spec}'")
        for handler in matches:
            proxy = plugin.configure[handler]
            self._apply_config(proxy, options)
        return {"target": target, "updated": sorted(matches)}
