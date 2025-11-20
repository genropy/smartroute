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

    - store global configuration in ``self._global_config`` (default
      ``{\"enabled\": True}``)
    - allow per-handler overrides via ``self._handler_configs`` (dict of dicts)
    - expose ``configure`` proxy so `RoutedClass.configure(...)` can set either
      global or handler-specific settings
    - provide optional hooks ``on_decore(router, func, entry)`` and
      ``wrap_handler(router, entry, call_next)`` used by the Router pipeline

    Constructor signature:

    ``BasePlugin(name=None, *, description=None, flags=None, method_config=None, **config)``

    - ``name`` overrides the plugin name (defaults to class name lowercased)
    - ``description`` stored but never interpreted by the core
    - ``flags`` is a comma-separated string ``\"foo,bar:off\"`` parsed into a
      dict of booleans and merged into the config
    - ``method_config`` is a mapping of handler name → config dict applied
      after the global config
    - any extra ``**config`` entries land in ``self._global_config``

    Required public methods:

    ``get_config(method_name=None)``
        returns the merged configuration dict for the plugin (global + optional
        per-handler overrides)

    ``set_config(flags=None, **config)`` and
    ``set_method_config(method_name, flags=None, **config)``
        mutate the stored global/handler config respectively

    ``configure`` property
        returns a proxy that supports dotted assignment and item access:
        ``plugin.configure.enabled = False`` sets the global flag,
        ``plugin.configure[\"foo\"].threshold = 5`` sets handler-specific values,
        ``plugin.configure.flags = \"enabled:off\"`` is shorthand for toggling
        boolean flags.

    ``on_decore`` (default no-op)
        called once when the Router registers a handler. Plugins use this to
        annotate ``entry.metadata`` or pre-compute structures.

    ``wrap_handler`` (default identity function)
        used by the Router to create middleware layers. Plugin authors receive
        the router, the MethodEntry, and the next callable; they must return a
        callable with the same signature.

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

    __slots__ = (
        "name",
        "description",
        "_global_config",
        "_handler_configs",
        "config",
    )

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
        self._global_config: Dict[str, Any] = {"enabled": True}
        self._handler_configs: Dict[str, Dict[str, Any]] = {}
        if flags:
            self._global_config.update(self._parse_flags(flags))
        self._global_config.update(config)
        if method_config:
            for method_name, settings in method_config.items():
                self._handler_configs[method_name] = dict(settings)
        # Backwards compat alias
        self.config = self._global_config

    @property
    def configure(self) -> "_PluginConfigProxy":
        return _PluginConfigProxy(self)

    def get_config(self, method_name: Optional[str] = None) -> Dict[str, Any]:
        merged = dict(self._global_config)
        if method_name and method_name in self._handler_configs:
            merged.update(self._handler_configs[method_name])
        return merged

    def set_config(self, flags: Optional[str] = None, **config: Any) -> None:
        if flags:
            config.update(self._parse_flags(flags))
        self._global_config.update(config)

    def set_method_config(
        self, method_name: str, *, flags: Optional[str] = None, **config: Any
    ) -> None:
        if flags:
            config.update(self._parse_flags(flags))
        bucket = self._handler_configs.setdefault(method_name, {})
        bucket.update(config)

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
