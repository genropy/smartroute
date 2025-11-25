"""Router with plugin pipeline (source of truth).

If this module disappeared, rebuild it exactly as described. ``Router`` extends
``BaseRouter`` with a global plugin registry, per-router plugin instances,
middleware wrapping, and plugin state stored on the router instance.

Internal state
--------------
- ``_plugin_specs``: list of ``_PluginSpec`` (factory, kwargs copy, alias).
- ``_plugins``: instantiated plugins in the order they were attached.
- ``_plugins_by_name``: name → plugin instance (first wins).
- ``_inherited_from``: set of parent ids already inherited to avoid double
  cloning when the same child is attached multiple times.
- ``_plugin_info``: per-plugin state store on the router.

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
to ``_plugins`` and ``_plugins_by_name`` if not present, applies
``plugin.on_decore`` to all existing entries (also ensuring ``entry.plugins``
lists the plugin), rebuilds handlers, and returns ``self``. ``__getattr__``
exposes attached plugins by name or raises ``AttributeError``.

Runtime flags and data
----------------------
Stored on the router under ``_plugin_info[plugin_code]`` using a reserved
``"--base--"`` bucket for router-level defaults and one bucket per handler
name, each with ``config`` and ``locals``. ``set_plugin_enabled`` /
``is_plugin_enabled`` and ``set_runtime_data`` / ``get_runtime_data`` read/write
these buckets (no contextvars).

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
seeded without overwriting existing names. ``on_decore`` is applied to entries
and handlers rebuilt.

Filtering
---------
``_prepare_filter_args`` extends ``BaseRouter`` by normalizing:

- ``scopes``: optional string or iterable → set of non-empty strings; falsy
  values removed.

- ``channel``: must be uppercase string; stripped; falsy removes filter;
  mismatched case raises ``ValueError``; non-string raises ``TypeError``.

``_should_include_entry`` first calls ``BaseRouter`` then asks each plugin in
``_plugins`` (ordered as attached) via ``allow_entry``. Any explicit ``False``
hides the entry; any other truthy/None keeps it.

Description hooks
-----------------
- ``_describe_entry_extra`` asks plugins to contribute extra fields for
  ``members()`` output. Plugins implement ``entry_metadata(router, entry)``
  which returns a dict stored in ``plugins[plugin_name]["metadata"]``.

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

from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, Type

from smartroute.core.base_router import BaseRouter
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry

__all__ = ["Router"]

_PLUGIN_REGISTRY: Dict[str, Type[BasePlugin]] = {}


@dataclass
class _PluginSpec:
    factory: Type[BasePlugin]
    kwargs: Dict[str, Any]

    def instantiate(self, router: "Router") -> BasePlugin:
        return self.factory(router=router, **self.kwargs)

    def clone(self) -> "_PluginSpec":
        return _PluginSpec(self.factory, dict(self.kwargs))


class Router(BaseRouter):
    """Router with plugin registry/pipeline support."""

    __slots__ = BaseRouter.__slots__ + (
        "_plugin_specs",
        "_plugins",
        "_plugins_by_name",
        "_inherited_from",
        "_plugin_info",
    )

    def __init__(self, *args, **kwargs):
        self._plugin_specs: List[_PluginSpec] = []
        self._plugins: List[BasePlugin] = []
        self._plugins_by_name: Dict[str, BasePlugin] = {}
        self._inherited_from: set[int] = set()
        self._plugin_info: Dict[str, Dict[str, Any]] = {}
        super().__init__(*args, **kwargs)

    # ------------------------------------------------------------------
    # Plugin registration
    # ------------------------------------------------------------------
    @classmethod
    def register_plugin(cls, plugin_class: Type[BasePlugin], name: Optional[str] = None) -> None:
        """Register a plugin class globally.

        Args:
            plugin_class: A BasePlugin subclass with plugin_code defined
            name: Optional override name. If provided, overwrites any existing
                  registration. If not provided, uses plugin_code and raises
                  if already registered.
        """
        if not isinstance(plugin_class, type) or not issubclass(plugin_class, BasePlugin):
            raise TypeError("plugin_class must be a BasePlugin subclass")
        if not getattr(plugin_class, "plugin_code", None):
            raise ValueError(
                f"Plugin {plugin_class.__name__} not following standards: missing plugin_code"
            )
        code = name or plugin_class.plugin_code
        # If name is explicitly provided, allow overwrite (intentional replacement)
        # Otherwise, reject collision
        if name is None:
            existing = _PLUGIN_REGISTRY.get(code)
            if existing is not None and existing is not plugin_class:
                raise ValueError(f"Plugin '{code}' already registered")
        _PLUGIN_REGISTRY[code] = plugin_class

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
        spec_kwargs = dict(config)
        spec = _PluginSpec(plugin_class, spec_kwargs)
        self._plugin_specs.append(spec)
        instance = spec.instantiate(self)
        self._plugins.append(instance)
        self._plugins_by_name[instance.name] = instance
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
        return plugin.configuration(method_name)

    def __getattr__(self, name: str) -> Any:
        plugin = self._plugins_by_name.get(name)
        if plugin is None:
            raise AttributeError(f"No plugin named '{name}' attached to router '{self.name}'")
        return plugin

    def _get_plugin_bucket(
        self, plugin_name: str, create: bool = False
    ) -> Optional[Dict[str, Any]]:
        bucket = self._plugin_info.get(plugin_name)
        if bucket is None and create:
            bucket = {"--base--": {"config": {}, "locals": {}}}
            self._plugin_info[plugin_name] = bucket
        if bucket is not None and "--base--" not in bucket:
            bucket["--base--"] = {"config": {}, "locals": {}}
        return bucket

    # ------------------------------------------------------------------
    # Runtime helpers (state stored on plugin_info)
    # ------------------------------------------------------------------
    def set_plugin_enabled(self, method_name: str, plugin_name: str, enabled: bool = True) -> None:
        bucket = self._get_plugin_bucket(plugin_name, create=False)
        if bucket is None:
            raise AttributeError(
                f"No plugin named '{plugin_name}' attached to router '{self.name}'"
            )
        entry = bucket.setdefault(method_name, {"config": {}, "locals": {}})
        entry.setdefault("locals", {})["enabled"] = bool(enabled)

    def is_plugin_enabled(self, method_name: str, plugin_name: str) -> bool:
        bucket = self._get_plugin_bucket(plugin_name, create=False)
        if bucket is None:
            raise AttributeError(
                f"No plugin named '{plugin_name}' attached to router '{self.name}'"
            )
        entry_locals = bucket.get(method_name, {}).get("locals", {})
        if "enabled" in entry_locals:
            return bool(entry_locals["enabled"])
        base_locals = bucket.get("--base--", {}).get("locals", {})
        return bool(base_locals.get("enabled", True))

    def set_runtime_data(self, method_name: str, plugin_name: str, key: str, value: Any) -> None:
        bucket = self._get_plugin_bucket(plugin_name, create=False)
        if bucket is None:
            raise AttributeError(
                f"No plugin named '{plugin_name}' attached to router '{self.name}'"
            )
        entry = bucket.setdefault(method_name, {"config": {}, "locals": {}})
        entry.setdefault("locals", {})[key] = value

    def get_runtime_data(
        self, method_name: str, plugin_name: str, key: str, default: Any = None
    ) -> Any:
        bucket = self._get_plugin_bucket(plugin_name, create=False)
        if bucket is None:
            raise AttributeError(
                f"No plugin named '{plugin_name}' attached to router '{self.name}'"
            )
        entry_locals = bucket.get(method_name, {}).get("locals", {})
        return entry_locals.get(key, default)

    # ------------------------------------------------------------------
    # Overrides/hooks
    # ------------------------------------------------------------------
    def _wrap_handler(self, entry: MethodEntry, call_next: Callable) -> Callable:  # type: ignore[override]
        wrapped = call_next
        for plugin in reversed(self._plugins):
            plugin_call = plugin.wrap_handler(self, entry, wrapped)
            wrapped = self._create_wrapper(plugin, entry, plugin_call, wrapped)
        return wrapped

    def _create_wrapper(
        self,
        plugin: BasePlugin,
        entry: MethodEntry,
        plugin_call: Callable,
        next_handler: Callable,
    ) -> Callable:
        @wraps(next_handler)
        def wrapper(*args, **kwargs):
            if not self.is_plugin_enabled(entry.name, plugin.name):
                return next_handler(*args, **kwargs)
            return plugin_call(*args, **kwargs)

        return wrapper

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
        # For plugins in parent that child doesn't have:
        # - Add reference to parent's plugin for attribute access
        # - Apply on_decore to child's entries
        inherited_plugins = []
        for parent_plugin in parent._plugins:
            if parent_plugin.name not in self._plugins_by_name:
                # Child doesn't have this plugin - inherit from parent
                self._plugins_by_name[parent_plugin.name] = parent_plugin
                inherited_plugins.append(parent_plugin)
        # Apply on_decore for inherited plugins to child's entries
        for plugin in inherited_plugins:
            for entry in self._entries.values():
                if plugin.name not in entry.plugins:
                    entry.plugins.append(plugin.name)
                plugin.on_decore(self, entry.func, entry)
        if inherited_plugins:
            self._rebuild_handlers()

    def _after_entry_registered(self, entry: MethodEntry) -> None:  # type: ignore[override]
        plugin_options = entry.metadata.get("plugin_config", {})
        if plugin_options:
            for pname, cfg in plugin_options.items():
                bucket = self._plugin_info.setdefault(
                    pname, {"--base--": {"config": {}, "locals": {}}}
                )
                entry_bucket = bucket.setdefault(entry.name, {"config": {}, "locals": {}})
                entry_bucket["config"].update(cfg)
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

    def _allow_entry(self, entry: MethodEntry, **filters: Any) -> bool:
        if not super()._allow_entry(entry, **filters):
            return False  # pragma: no cover - base hook currently always True
        for plugin in self._plugins:
            verdict = plugin.allow_entry(self, entry, **filters)
            if verdict is False:
                return False
        return True

    def _describe_entry_extra(  # type: ignore[override]
        self, entry: MethodEntry, base_description: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Gather plugin config and metadata for a handler."""
        plugins_info: Dict[str, Dict[str, Any]] = {}
        for plugin in self._plugins:
            plugin_data: Dict[str, Any] = {}
            # Get config for this entry
            config = plugin.configuration(entry.name)
            if config:
                plugin_data["config"] = config
            # Get metadata from plugin
            meta = plugin.entry_metadata(self, entry)
            if meta:
                if not isinstance(meta, dict):
                    raise TypeError(  # pragma: no cover - defensive guard
                        f"Plugin {plugin.name} returned non-dict "
                        f"from entry_metadata: {type(meta)}"
                    )
                plugin_data["metadata"] = meta
            # Only include plugin if it has data
            if plugin_data:
                plugins_info[plugin.name] = plugin_data
        if plugins_info:
            return {"plugins": plugins_info}
        return {}

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
