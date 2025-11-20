"""Router runtime with plugin registry.

This module layers plugin capabilities on top of
:class:`smartroute.core.base_router.BaseRouter`. The class exported here
matches the behaviour of the historical ``smartroute.core.router.Router`` and
adds a clear separation between the plain router engine and the middleware
pipeline.

Responsibilities
----------------
- keep the global plugin registry (name → plugin class)
- instantiate plugins per router instance, allowing inheritance across child
  routers
- expose helper APIs for enabling/disabling plugins at runtime and storing
  execution context
- wrap handlers with plugin-provided middleware and feed metadata back into
  ``MethodEntry``

Invariants
----------
- routers remain instance-scoped; plugin configuration never leaks across
  object instances unless explicitly shared via child routers
- plugin registration is global but idempotent; re-registering the same name
  with a different class raises immediately
- ``MethodEntry.plugins`` lists plugins in application order to guarantee the
  wrapping stack is deterministic
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from smartroute.core.base_router import BaseRouter
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry

__all__ = ["Router"]

_ACTIVATION_CTX: contextvars.ContextVar[Dict[Tuple[int, str, str], bool] | None] = (
    contextvars.ContextVar("smartroute_activation", default=None)
)
_RUNTIME_CTX: contextvars.ContextVar[Dict[Tuple[int, str, str], Dict[str, Any]] | None] = (
    contextvars.ContextVar("smartroute_runtime", default=None)
)
_PLUGIN_REGISTRY: Dict[str, Type[BasePlugin]] = {}


def _get_activation_map() -> Dict[Tuple[int, str, str], bool]:
    mapping = _ACTIVATION_CTX.get()
    if mapping is None:
        mapping = {}
        _ACTIVATION_CTX.set(mapping)
    return mapping


def _get_runtime_map() -> Dict[Tuple[int, str, str], Dict[str, Any]]:
    mapping = _RUNTIME_CTX.get()
    if mapping is None:
        mapping = {}
        _RUNTIME_CTX.set(mapping)
    return mapping


@dataclass
class _PluginSpec:
    factory: Type[BasePlugin]
    kwargs: Dict[str, Any]
    alias: Optional[str] = None

    def instantiate(self) -> BasePlugin:
        plugin = self.factory(**self.kwargs)
        if self.alias:
            plugin.name = self.alias
        return plugin

    def clone(self) -> "_PluginSpec":
        return _PluginSpec(self.factory, dict(self.kwargs), self.alias)


class Router(BaseRouter):
    """Default router with plugin support."""

    __slots__ = BaseRouter.__slots__ + (
        "_plugin_specs",
        "_plugins",
        "_plugins_by_name",
        "_inherited_from",
    )

    def __init__(self, *args, **kwargs):
        self._plugin_specs: List[_PluginSpec] = []
        self._plugins: List[BasePlugin] = []
        self._plugins_by_name: Dict[str, BasePlugin] = {}
        self._inherited_from: set[int] = set()
        super().__init__(*args, **kwargs)

    # ------------------------------------------------------------------
    # Plugin registration
    # ------------------------------------------------------------------
    @classmethod
    def register_plugin(cls, name: str, plugin_class: Type[BasePlugin]) -> None:
        if not isinstance(plugin_class, type) or not issubclass(plugin_class, BasePlugin):
            raise TypeError("plugin_class must be a BasePlugin subclass")
        if not name:
            raise ValueError("plugin name cannot be empty")
        existing = _PLUGIN_REGISTRY.get(name)
        if existing is not None and existing is not plugin_class:
            raise ValueError(f"Plugin name '{name}' already registered")
        _PLUGIN_REGISTRY[name] = plugin_class

    @classmethod
    def available_plugins(cls) -> Dict[str, Type[BasePlugin]]:
        return dict(_PLUGIN_REGISTRY)

    def plug(self, plugin: str, **config: Any) -> "Router":
        if not isinstance(plugin, str):
            raise TypeError(
                f"Plugin must be referenced by name string, got {type(plugin).__name__}"
            )
        plugin_class = _PLUGIN_REGISTRY.get(plugin)
        if plugin_class is None:
            available = ", ".join(sorted(_PLUGIN_REGISTRY)) or "none"
            raise ValueError(
                f"Unknown plugin '{plugin}'. Register it first. Available plugins: {available}"
            )
        spec = _PluginSpec(plugin_class, dict(config), alias=plugin)
        self._plugin_specs.append(spec)
        instance = spec.instantiate()
        self._plugins.append(instance)
        self._plugins_by_name[instance.name] = instance
        self._apply_plugin_to_entries(instance)
        self._rebuild_handlers()
        return self

    def iter_plugins(self) -> List[BasePlugin]:  # type: ignore[override]
        return list(self._plugins)

    def __getattr__(self, name: str) -> Any:
        plugin = self._plugins_by_name.get(name)
        if plugin is None:
            raise AttributeError(f"No plugin named '{name}' attached to router '{self.name}'")
        return plugin

    # ------------------------------------------------------------------
    # Runtime helpers
    # ------------------------------------------------------------------
    def _activation_key(self, method_name: str, plugin_name: str) -> Tuple[int, str, str]:
        return (id(self.instance), method_name, plugin_name)

    def set_plugin_enabled(self, method_name: str, plugin_name: str, enabled: bool = True) -> None:
        mapping = _get_activation_map()
        mapping[self._activation_key(method_name, plugin_name)] = bool(enabled)

    def is_plugin_enabled(self, method_name: str, plugin_name: str) -> bool:
        mapping = _get_activation_map()
        value = mapping.get(self._activation_key(method_name, plugin_name))
        if value is None:
            return True
        return bool(value)

    def _runtime_key(self, method_name: str, plugin_name: str) -> Tuple[int, str, str]:
        return (id(self.instance), method_name, plugin_name)

    def set_runtime_data(self, method_name: str, plugin_name: str, key: str, value: Any) -> None:
        mapping = _get_runtime_map()
        slot = mapping.setdefault(self._runtime_key(method_name, plugin_name), {})
        slot[key] = value

    def get_runtime_data(
        self, method_name: str, plugin_name: str, key: str, default: Any = None
    ) -> Any:
        mapping = _get_runtime_map()
        slot = mapping.get(self._runtime_key(method_name, plugin_name), {})
        return slot.get(key, default)

    # ------------------------------------------------------------------
    # Overrides/hooks
    # ------------------------------------------------------------------
    def _wrap_handler(self, entry: MethodEntry, call_next: Callable) -> Callable:  # type: ignore[override]
        wrapped = call_next
        for plugin in reversed(self._plugins):
            plugin_call = plugin.wrap_handler(self, entry, wrapped)

            @wraps(wrapped)
            def layer(
                *args,
                _plugin=plugin,
                _entry=entry,
                _plugin_call=plugin_call,
                _wrapped=wrapped,
                **kwargs,
            ):
                if not self.is_plugin_enabled(_entry.name, _plugin.name):
                    return _wrapped(*args, **kwargs)
                return _plugin_call(*args, **kwargs)

            wrapped = layer
        return wrapped

    def _apply_plugin_to_entries(self, plugin: BasePlugin) -> None:
        for entry in self._entries.values():
            if plugin.name not in entry.plugins:
                entry.plugins.append(plugin.name)
            plugin.on_decore(self, entry.func, entry)

    def _on_attached_to_parent(self, parent: "Router") -> None:  # type: ignore[override]
        parent_id = id(parent)
        if parent_id in self._inherited_from:
            return
        self._inherited_from.add(parent_id)
        parent_specs = [spec.clone() for spec in parent._plugin_specs]
        if not parent_specs:
            return
        new_plugins = [spec.instantiate() for spec in parent_specs]
        self._plugin_specs = parent_specs + self._plugin_specs
        self._plugins = new_plugins + self._plugins
        for plugin in new_plugins:
            self._plugins_by_name.setdefault(plugin.name, plugin)
            self._apply_plugin_to_entries(plugin)
        self._rebuild_handlers()

    def _after_entry_registered(self, entry: MethodEntry) -> None:  # type: ignore[override]
        for plugin in self._plugins:
            if plugin.name not in entry.plugins:
                entry.plugins.append(plugin.name)
            plugin.on_decore(self, entry.func, entry)
