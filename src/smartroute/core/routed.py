"""RoutedClass mixin and router proxy (source of truth).

Reconstruct exactly from the following contract. The mixin keeps router state
off user instances via slots and offers a proxy for configuration/lookup.

RoutedClass
-----------
- ``__slots__``: proxy cache and ``ROUTER_REGISTRY_ATTR_NAME`` (dict).
- ``_register_router(router)``: lazily creates a registry dict on the instance
  and stores the router under ``router.name`` if truthy.
- ``_iter_registered_routers``: yields ``(name, router)`` for registry entries
  (empty dict if none).
- ``routedclass`` property: returns cached ``_RoutedProxy`` bound to the owner,
  creating and storing it on first access.

_RoutedProxy
------------
Bound to the owning ``RoutedClass`` instance.

Router lookup:
- ``get_router(name, path=None)`` splits combined specs (``foo.bar``) into
  base router + child path (``_split_router_spec``). Looks in the registry
  first, then falls back to owner attributes (cached if a ``Router``). Raises
  ``AttributeError`` if no router is found. If ``path`` is provided (or found in
  the dotted name), traverses children via ``_children`` lookup for each segment,
  skipping empty segments.

Configuration entrypoint:
- ``configure(target, **options)`` accepts:
  * list/tuple: config each element; shared ``options`` not allowed (raises).
  * dict: must include ``"target"`` key; remaining items are options.
  * string: either ``"?"`` (describe all) or ``"router:plugin/selector"``.
- Errors: non-string/dict/list targets raise ``TypeError``; missing options for
  string targets raise ``ValueError``; bad syntax (missing ``:``) or empty
  router/plugin names raise ``ValueError``; unknown router/plugin raises
  ``AttributeError``; unmatched handlers raise ``KeyError``.
- Selector parsing: ``_parse_target`` splits on the first ``:`` (router/component)
  then optional ``/`` (selector); default selector is ``"_all_"``. Trimmed
  strings must be non-empty; channel/scope semantics are left to plugins.
- Handler matching: ``_match_handlers`` fnmatch-es selectors (comma-separated)
  against router ``_entries`` keys, returning a set.
- Application: for ``"_all_"`` selector, calls ``plugin.configure(_target="--base--", **options)``
  (global config) and returns ``{"target": target, "updated": ["_all_"]}``.
  Otherwise for each matched handler, calls ``plugin.configure(_target=handler, **options)``
  and returns ``{"target": target, "updated": sorted(matches)}``.
- ``"?"`` shortcut returns ``_describe_all()``.

Describe helpers:
- ``_describe_all``: iterates registry routers and returns a dict of name →
  ``_describe_router`` output.
- ``_describe_router``: returns a dict with router name, per-plugin info
  (``name``, ``description``, global config, per-handler overrides), handler
  names list, and child routers described recursively.

Invariants
----------
- Registry is per-instance; attribute lookup fallback is cached for future use.
- Proxies never mutate router internals beyond plugin config proxies.
- Fnmatch is used for selector matching; an empty match set is an error unless
  selector is ``_all_``.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, Dict, Optional

from smartseeds.typeutils import safe_is_instance

from .base_router import ROUTER_REGISTRY_ATTR_NAME

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from .router import Router

__all__ = ["RoutedClass", "is_routed_class"]

_PROXY_ATTR_NAME = "__routed_proxy__"


class RoutedClass:
    """Mixin providing helper proxies for runtime routers."""

    __slots__ = (_PROXY_ATTR_NAME, ROUTER_REGISTRY_ATTR_NAME, "_routed_parent")

    def __setattr__(self, name: str, value: Any) -> None:
        current = self._get_current_routed_attr(name)
        if current is not None:
            self._auto_detach_child(current)

        object.__setattr__(self, name, value)

    def _get_current_routed_attr(self, name: str) -> Any:
        try:
            current = object.__getattribute__(self, name)
        except AttributeError:
            return None
        if not safe_is_instance(current, "smartroute.core.routed.RoutedClass"):
            return None
        if getattr(current, "_routed_parent", None) is not self:
            return None  # pragma: no cover - only detach if bound to this parent
        return current

    def _auto_detach_child(self, current: Any) -> None:
        registry = getattr(self, ROUTER_REGISTRY_ATTR_NAME, {}) or {}
        for router in registry.values():
            try:
                router.detach_instance(current)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - best-effort only
                pass  # best-effort; avoid blocking setattr

    def _register_router(self, router: "Router") -> None:
        registry = getattr(self, ROUTER_REGISTRY_ATTR_NAME, None)
        if registry is None:
            registry = {}
            setattr(self, ROUTER_REGISTRY_ATTR_NAME, registry)
        if not hasattr(self, "_routed_parent"):
            object.__setattr__(self, "_routed_parent", None)
        if router.name:
            registry[router.name] = router

    def _iter_registered_routers(self):
        registry = getattr(self, ROUTER_REGISTRY_ATTR_NAME, None) or {}
        for name, router in registry.items():
            yield name, router

    @property
    def routedclass(self) -> "_RoutedProxy":
        proxy = getattr(self, _PROXY_ATTR_NAME, None)
        if proxy is None:
            proxy = _RoutedProxy(self)
            setattr(self, _PROXY_ATTR_NAME, proxy)
        return proxy


class _RoutedProxy:
    def __init__(self, owner: RoutedClass):
        object.__setattr__(self, "_owner", owner)

    def get_router(self, name: str, path: Optional[str] = None):
        owner = self._owner
        base_name, extra_path = self._split_router_spec(name, path)
        router = self._lookup_router(owner, base_name)
        if router is None:
            raise AttributeError(f"No Router named '{base_name}' on {type(owner).__name__}")
        if not extra_path:
            return router
        return self._navigate_router(router, extra_path)

    def _lookup_router(self, owner: RoutedClass, name: str) -> Optional["Router"]:
        registry = getattr(owner, ROUTER_REGISTRY_ATTR_NAME, None) or {}
        router = registry.get(name)
        if router:
            return router
        candidate = getattr(owner, name, None)
        if safe_is_instance(candidate, "smartroute.core.base_router.BaseRouter"):
            registry[name] = candidate
            return candidate
        return None

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
            node = node._children[segment]
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

    def _apply_config(self, plugin: Any, target: str, options: Dict[str, Any]) -> None:
        plugin.configure(_target=target, **options)

    def _describe_all(self) -> Dict[str, Any]:
        owner = self._owner
        result: Dict[str, Any] = {}
        registry = getattr(owner, ROUTER_REGISTRY_ATTR_NAME, None) or {}
        for attr_name, router in registry.items():
            result[attr_name] = self._describe_router(router)
        return result

    def _describe_router(self, router) -> Dict[str, Any]:
        return {
            "name": router.name,
            "plugins": [
                {
                    "name": plugin.name,
                    "description": getattr(plugin, "description", ""),
                    "config": plugin.configuration(),
                    "overrides": {
                        handler: plugin.configuration(handler) for handler in router._entries.keys()
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
                raise ValueError("Options are not allowed with '?' ")
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
            self._apply_config(plugin, "--base--", options)
            return {"target": target, "updated": ["_all_"]}
        matches = self._match_handlers(bound_router, selector)
        if not matches:
            raise KeyError(f"No handlers matching '{selector}' on router '{router_spec}'")
        for handler in matches:
            self._apply_config(plugin, handler, options)
        return {"target": target, "updated": sorted(matches)}


def is_routed_class(obj: Any) -> bool:
    """Return True when ``obj`` is a RoutedClass instance."""
    return safe_is_instance(obj, "smartroute.core.routed.RoutedClass")
