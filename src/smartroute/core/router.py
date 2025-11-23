"""Router with plugin pipeline (source of truth).

If this module disappeared, rebuild it exactly as described. ``Router`` extends
``BaseRouter`` with a global plugin registry, per-router plugin instances,
middleware wrapping, and runtime config storage in contextvars.

Internal state
--------------
- ``_plugin_specs``: list of ``_PluginSpec`` (factory, kwargs copy, alias).
- ``_plugins``: instantiated plugins in the order they were attached.
- ``_plugins_by_name``: name → plugin instance (first wins).
- ``_filter_plugins``: plugins exposing ``filter_entry`` callable.
- ``_inherited_from``: set of parent ids already inherited to avoid double
  cloning when the same child is attached multiple times.

Global registry
---------------
``Router.register_plugin(name, plugin_class)`` validates that ``plugin_class``
is a subclass of ``BasePlugin`` and ``name`` is non-empty. Re-registering an
existing name with a different class raises ``ValueError``; otherwise it is
idempotent. ``available_plugins`` returns a shallow copy of the registry.

Attaching plugins
-----------------
``plug(plugin_name, **config)`` looks up the plugin class by name in the global
registry (raises ``ValueError`` with available names if missing). It stores a
``_PluginSpec`` clone, instantiates the plugin (applying alias=name), appends
to ``_plugins`` and ``_plugins_by_name`` if not present, refreshes
``_filter_plugins``, applies ``plugin.on_decore`` to all existing entries (also
ensuring ``entry.plugins`` lists the plugin), rebuilds handlers, and returns
``self``. ``__getattr__`` exposes attached plugins by name or raises
``AttributeError``.

Runtime flags and data
----------------------
Contextvars keep per-instance/plugin/handler state using key
``(id(instance), method_name, plugin_name)``:

- ``set_plugin_enabled``/``is_plugin_enabled`` toggle middleware activation
  (default True when no flag stored).

- ``set_runtime_data``/``get_runtime_data`` store arbitrary dict values per
  plugin/handler.

Wrapping pipeline
-----------------
``_wrap_handler(entry, call_next)`` builds middleware layers from the current
``_plugins`` in reverse order (last attached closest to the handler). For each
plugin, it calls ``plugin.wrap_handler(self, entry, wrapped)`` to produce a
callable, then wraps it with a guard that skips execution when
``is_plugin_enabled`` is False. ``functools.wraps`` preserves metadata of the
next callable. The final callable is stored in ``_handlers`` by ``BaseRouter``.

Entry/plugin application
------------------------
- ``_apply_plugin_to_entries`` ensures ``entry.plugins`` contains the plugin
  name and invokes ``plugin.on_decore`` on each existing entry. Called when a
  plugin is attached and during inheritance.
- ``_after_entry_registered`` (override) is triggered by ``BaseRouter`` whenever
  a new handler is registered; it applies all attached plugins the same way and
  leaves names in ``entry.plugins``.

Inheritance behaviour
---------------------
``_on_attached_to_parent(parent)`` runs when a child router is attached.
Parent specs are cloned once per parent (id tracked in ``_inherited_from``).
Cloned specs are instantiated into new plugins that are *prepended* ahead of
existing child plugins to preserve parent-first order. ``_plugins_by_name`` is
seeded without overwriting existing names. ``on_decore`` is applied to entries,
filter plugins refreshed, and handlers rebuilt.

Filtering
---------
``_prepare_filter_args`` extends ``BaseRouter`` by normalizing:

- ``scopes``: optional string or iterable → set of non-empty strings; falsy
  values removed.

- ``channel``: must be uppercase string; stripped; falsy removes filter;
  mismatched case raises ``ValueError``; non-string raises ``TypeError``.

``_should_include_entry`` first calls ``BaseRouter`` then asks each plugin in
``_filter_plugins`` (ordered as attached). Any explicit ``False`` hides the
entry; any other truthy/None keeps it.

Description hooks
-----------------
- ``_describe_entry_extra`` asks plugins to contribute extra fields for
  ``BaseRouter.describe``. Plugins implement
  ``describe_entry(router, entry, base_description) -> dict``; contributions are
  merged in attachment order; non-dict returns raise ``TypeError``.

Data shapes
-----------
``_PluginSpec`` dataclass stores ``factory``, ``kwargs``, optional ``alias`` and
provides:

- ``instantiate()`` → creates plugin via ``factory(**kwargs)``; applies alias to
  ``plugin.name`` if set.

- ``clone()`` → returns a new spec with a shallow-copied kwargs dict and same
  alias.

Router Invariants
-----------------
- Plugin order is deterministic (first attached = outermost layer; reversed
  wrapping). Filter evaluation follows attachment order.
- Global registry changes do not mutate existing router instances.
- Plugin access via attribute never fails silently.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type

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
    """Router with plugin registry/pipeline support."""

    __slots__ = BaseRouter.__slots__ + (
        "_plugin_specs",
        "_plugins",
        "_plugins_by_name",
        "_filter_plugins",
        "_inherited_from",
    )

    def __init__(self, *args, **kwargs):
        self._plugin_specs: List[_PluginSpec] = []
        self._plugins: List[BasePlugin] = []
        self._plugins_by_name: Dict[str, BasePlugin] = {}
        self._filter_plugins: List[BasePlugin] = []
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
        """Attach a plugin by name (previously registered globally)."""
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
        self._refresh_filter_plugins()
        self._apply_plugin_to_entries(instance)
        self._rebuild_handlers()
        return self

    def iter_plugins(self) -> List[BasePlugin]:  # type: ignore[override]
        """Return attached plugin instances in application order."""
        return list(self._plugins)

    def get_config(self, plugin_name: str, method_name: Optional[str] = None) -> Dict[str, Any]:
        """Return plugin config (global + per-handler overrides) for an attached plugin."""
        plugin = self._plugins_by_name.get(plugin_name)
        if plugin is None:
            raise AttributeError(
                f"No plugin named '{plugin_name}' attached to router '{self.name}'"
            )
        return plugin.get_config(method_name)

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
        self._refresh_filter_plugins()
        for plugin in new_plugins:
            self._plugins_by_name.setdefault(plugin.name, plugin)
            self._apply_plugin_to_entries(plugin)
        self._rebuild_handlers()

    def _after_entry_registered(self, entry: MethodEntry) -> None:  # type: ignore[override]
        for plugin in self._plugins:
            if plugin.name not in entry.plugins:
                entry.plugins.append(plugin.name)
            plugin.on_decore(self, entry.func, entry)

    def _prepare_filter_args(self, **raw_filters: Any) -> Dict[str, Any]:
        filters = super()._prepare_filter_args(**raw_filters)
        scopes_value = raw_filters.get("scopes")
        channel_value = raw_filters.get("channel")
        scope_filter = self._normalize_scope_filter(scopes_value)
        if scope_filter:
            filters["scopes"] = scope_filter
        else:
            filters.pop("scopes", None)
        channel_filter = self._normalize_channel_filter(channel_value)
        if channel_filter:
            filters["channel"] = channel_filter
        else:
            filters.pop("channel", None)
        return filters

    def _should_include_entry(self, entry: MethodEntry, **filters: Any) -> bool:
        if not super()._should_include_entry(entry, **filters):
            return False  # pragma: no cover - base hook currently always True
        if not self._filter_plugins:
            return True
        for plugin in self._filter_plugins:
            verdict = plugin.filter_entry(self, entry, **filters)  # type: ignore[attr-defined]
            if verdict is False:
                return False
        return True

    def _describe_entry_extra(  # type: ignore[override]
        self, entry: MethodEntry, base_description: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Gather extra description data from attached plugins."""
        merged: Dict[str, Any] = {}
        for plugin in self._plugins:
            contrib = None
            describe_entry = getattr(plugin, "describe_entry", None)
            if callable(describe_entry):
                contrib = describe_entry(self, entry, base_description)
            if contrib:
                if not isinstance(contrib, dict):
                    raise TypeError(  # pragma: no cover - defensive guard
                        f"Plugin {plugin.name} returned non-dict "
                        f"from describe hook: {type(contrib)}"
                    )
                merged.update(contrib)
        return merged

    def _refresh_filter_plugins(self) -> None:
        self._filter_plugins = [
            plugin for plugin in self._plugins if callable(getattr(plugin, "filter_entry", None))
        ]

    def _normalize_scope_filter(self, scopes: Optional[Any]) -> Optional[set[str]]:
        if scopes is None or scopes is False:
            return None
        if isinstance(scopes, str):
            items = scopes.split(",")
        elif isinstance(scopes, Iterable):
            items = scopes
        else:
            raise TypeError("scopes must be a string or iterable of strings")
        cleaned = {str(item).strip() for item in items if str(item).strip()}
        return cleaned or None

    def _normalize_channel_filter(self, channel: Optional[str]) -> Optional[str]:
        if channel is None or channel is False:
            return None
        if isinstance(channel, str):
            normalized = channel.strip()
            if not normalized:
                raise ValueError("channel cannot be empty")  # pragma: no cover
            if normalized != normalized.upper():
                raise ValueError(f"channel must be uppercase (got '{normalized}')")
            return normalized
        raise TypeError("channel must be a string")
