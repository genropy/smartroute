"""Plugin contract definitions used by the Router runtime.

Source of truth
---------------
If this module were wiped except for this docstring, the implementation must be
reconstructed exactly as described below.

Objects
~~~~~~~
``MethodEntry``
    Frozen dataclass capturing handler metadata at registration time. Fields:

    - ``name`` – logical handler name (after prefix stripping)
    - ``func`` – bound callable invoked by the Router
    - ``router`` – Router instance that owns the handler
    - ``plugins`` – list of plugin names applied to the handler (order matters)
    - ``metadata`` – mutable dict used by plugins to store annotations

``BasePlugin``
    Abstract base class that every plugin *must* subclass. Responsibilities:

    - offer config helpers that delegate to the owning router's ``plugin_info``
      store (no hidden per-plugin globals)
    - provide optional hooks ``on_decore(router, func, entry)`` and
      ``wrap_handler(router, entry, call_next)`` used by the Router pipeline

    Constructor signature:

    ``BasePlugin(name=None, *, description=None, flags=None, method_config=None, **config)``

    - ``name`` overrides the plugin name (defaults to class name lowercased)
    - ``description`` stored but never interpreted by the core
    - ``flags`` is a comma-separated string ``\"foo,bar:off\"`` parsed into a
      dict of booleans and merged into the initial config snapshot
    - ``method_config`` is a mapping of handler name → config dict applied as
      initial per-handler overrides
    - any extra ``**config`` entries land in the initial router-level config

    Required public methods:

    ``get_config(method_name=None)``
        returns merged configuration dict from the router's store
        (router-level + optional per-handler override).

    ``set_config(flags=None, **config)`` and
    ``set_method_config(method_name, flags=None, **config)``
        mutate the router's ``plugin_info`` store (global/handler scopes).

    ``configure`` property
        returns a proxy that supports dotted assignment and item access:
        ``plugin.configure.enabled = False`` sets the router-level flag,
        ``plugin.configure[\"foo\"].threshold = 5`` sets handler-specific values,
        ``plugin.configure.flags = \"enabled:off\"`` toggles booleans.

    ``on_decore`` (default no-op)
        called once when the Router registers a handler. Plugins use this to
        annotate ``entry.metadata`` or pre-compute structures.

    ``wrap_handler`` (default identity function)
        used by the Router to create middleware layers. Plugin authors receive
        the router, the MethodEntry, and the next callable; they must return a
        callable with the same signature.

    ``filter_entry`` (optional)
        when implemented, allows the plugin to decide if a handler should be
        exposed during introspection. It receives the router, the MethodEntry,
        and keyword filters (``scopes``, ``channel``, ...); returning ``False``
        hides the handler from ``members()``.

Design constraints
~~~~~~~~~~~~~~~~~~
* The Router only imports this module (not the concrete plugins) to avoid
  circular dependencies.
* Configuration storage must stay internal to BasePlugin so all plugins behave
  consistently and can be configured via the generic admin/CLI tools.
* Access patterns are thread-safe as long as plugin authors keep their own
  mutable state protected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = ["BasePlugin", "MethodEntry"]


@dataclass
class MethodEntry:
    """Metadata for a registered route handler."""

    name: str
    func: Callable
    router: Any
    plugins: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class BasePlugin:
    """Hook interface + configuration helpers for router plugins."""

    __slots__ = ("name", "description", "_router", "_initial_config", "_initial_method_config")

    def __init__(
        self,
        name: Optional[str] = None,
        *,
        description: Optional[str] = None,
        flags: Optional[str] = None,
        method_config: Optional[Dict[str, Any]] = None,
        **config: Any,
    ):
        self.name = name or self.__class__.__name__.lower()
        self.description = description
        self._router: Any = None
        self._initial_config: Dict[str, Any] = {"enabled": True}
        if flags:
            self._initial_config.update(self._parse_flags(flags))
        self._initial_config.update(config)
        self._initial_method_config: Dict[str, Dict[str, Any]] = {}
        if method_config:
            for method_name, settings in method_config.items():
                self._initial_method_config[method_name] = dict(settings)

    @property
    def configure(self) -> "_PluginConfigProxy":
        return _PluginConfigProxy(self)

    def get_config(self, method_name: Optional[str] = None) -> Dict[str, Any]:
        store = self._get_store()
        plugin_bucket = store.get(self.name)
        if not plugin_bucket:
            return {}
        base_bucket = plugin_bucket.get("--base--", {})
        merged = dict(base_bucket.get("config", {}))
        if method_name:
            entry_bucket = plugin_bucket.get(method_name, {})
            merged.update(entry_bucket.get("config", {}))
        return merged

    def set_config(self, flags: Optional[str] = None, **config: Any) -> None:
        if self._router is None:
            raise RuntimeError("Plugin is not bound to a Router")
        if flags:
            config.update(self._parse_flags(flags))
        store = self._get_store()
        bucket = store.setdefault(self.name, {})
        base_bucket = bucket.setdefault("--base--", {"config": {}, "locals": {}})
        base_bucket["config"].update(config)

    def set_method_config(
        self, method_name: str, *, flags: Optional[str] = None, **config: Any
    ) -> None:
        if self._router is None:
            raise RuntimeError("Plugin is not bound to a Router")
        if flags:
            config.update(self._parse_flags(flags))
        store = self._get_store()
        plugin_bucket = store.setdefault(self.name, {})
        entry_bucket = plugin_bucket.setdefault(method_name, {"config": {}, "locals": {}})
        entry_bucket["config"].update(config)

    def _parse_flags(self, flags: str) -> Dict[str, bool]:
        mapping: Dict[str, bool] = {}
        for chunk in flags.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" in chunk:
                name, value = chunk.split(":", 1)
                mapping[name.strip()] = value.strip().lower() != "off"
            else:
                mapping[chunk] = True
        return mapping

    def on_decore(
        self, router: Any, func: Callable, entry: MethodEntry
    ) -> None:  # pragma: no cover - default no-op
        """Hook run when the route is registered."""

    def wrap_handler(
        self,
        router: Any,
        entry: MethodEntry,
        call_next: Callable,
    ) -> Callable:
        """Wrap handler invocation; default passthrough."""
        return call_next

    # Binding ------------------------------------------------
    def _bind_router(self, router: Any) -> None:
        self._router = router

    def _seed_store(self) -> None:
        if self._router is None:
            return
        store = self._get_store()
        bucket = store.setdefault(self.name, {})
        base_bucket = bucket.setdefault("--base--", {"config": {}, "locals": {}})
        base_bucket["config"].update(self._initial_config)
        for handler, cfg in self._initial_method_config.items():
            entry_bucket = bucket.setdefault(handler, {"config": {}, "locals": {}})
            entry_bucket["config"].update(cfg)

    def _get_store(self) -> Dict[str, Any]:
        if self._router is None:
            raise RuntimeError("Plugin is not bound to a Router")
        return getattr(self._router, "_plugin_info")


class _PluginConfigProxy:
    def __init__(self, plugin: BasePlugin, method: Optional[str] = None):
        self._plugin = plugin
        self._method = method

    def __getitem__(self, method_name: str) -> "_PluginConfigProxy":
        return _PluginConfigProxy(self._plugin, method_name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_plugin", "_method"}:
            object.__setattr__(self, name, value)
            return
        if name == "flags":
            if self._method:
                self._plugin.set_method_config(self._method, flags=value)
            else:
                self._plugin.set_config(flags=value)
            return
        if self._method:
            self._plugin.set_method_config(self._method, **{name: value})
        else:
            self._plugin.set_config(**{name: value})

    def __getattr__(self, name: str) -> Any:
        cfg = self._plugin.get_config(self._method)
        if name in cfg:
            return cfg[name]
        raise AttributeError(name)
