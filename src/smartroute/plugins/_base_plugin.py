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

    Required class attributes:

    - ``plugin_code`` – unique identifier used for registration (e.g. "logging")
    - ``plugin_description`` – human-readable description of the plugin

    Constructor signature:

    ``BasePlugin(router, **config)``

    - ``router`` is required – the Router instance owning this plugin
    - ``**config`` is passed to ``configure()`` which is validated by Pydantic

    Required methods:

    ``configure(**config)``
        Define accepted configuration parameters via method signature.
        The method is automatically wrapped by ``__init_subclass__`` to:
        - Extract and parse ``flags`` (e.g. "enabled,before:off") into booleans
        - Extract ``_target`` to determine where to write config:
          - ``"--base--"`` (default): router-level config
          - ``"handler_name"``: per-handler config
          - ``"h1,h2,h3"``: multiple handlers (calls recursively)
        - Apply Pydantic's ``validate_call`` for parameter validation
        - Write validated config to the store

    ``configuration(method_name=None)``
        returns merged configuration dict from the router's store
        (router-level + optional per-handler override). This is the read
        counterpart to ``configure()``.

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

from pydantic import validate_call

__all__ = ["BasePlugin", "MethodEntry"]


@dataclass
class MethodEntry:
    """Metadata for a registered route handler."""

    name: str
    func: Callable
    router: Any
    plugins: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


def _wrap_configure(original_configure: Callable) -> Callable:
    """Wrap a plugin's configure() method to handle flags, _target, validation, and storage."""
    validated = validate_call(original_configure)

    def wrapper(self: "BasePlugin", *, _target: str = "--base--", flags: Optional[str] = None, **kwargs: Any) -> None:
        # Parse flags into boolean kwargs
        if flags:
            kwargs.update(self._parse_flags(flags))

        # Handle multiple targets (comma-separated)
        if "," in _target:
            targets = [t.strip() for t in _target.split(",") if t.strip()]
            for t in targets:
                wrapper(self, _target=t, **kwargs)
            return

        # Validate kwargs against original configure signature
        validated(self, **kwargs)

        # Write to store
        self._write_config(_target, kwargs)

    return wrapper


class BasePlugin:
    """Hook interface + configuration helpers for router plugins."""

    __slots__ = ("name", "_router")

    # Subclasses MUST define these class attributes
    plugin_code: str = ""
    plugin_description: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Wrap configure() if the subclass defines its own
        if "configure" in cls.__dict__:
            cls.configure = _wrap_configure(cls.__dict__["configure"])

    def __init__(
        self,
        router: Any,
        **config: Any,
    ):
        self.name = self.plugin_code
        self._router = router
        self._init_store()
        # Call configure with initial config
        self.configure(**config)

    def _init_store(self) -> None:
        """Initialize plugin bucket in router's store."""
        store = self._get_store()
        store.setdefault(self.name, {}).setdefault(
            "--base--", {"config": {"enabled": True}, "locals": {}}
        )

    def configure(self, *, _target: str = "--base--", flags: Optional[str] = None) -> None:
        """Override in subclasses to define accepted configuration parameters.

        Base implementation accepts no additional parameters beyond _target and flags.

        Args:
            _target: Where to write config. "--base--" for router-level,
                     "handler_name" for per-handler, or "h1,h2" for multiple.
            flags: String like "enabled,before:off" parsed into booleans.
        """
        # Base configure just handles flags if provided
        if flags:
            kwargs = self._parse_flags(flags)
            self._write_config(_target, kwargs)

    def _write_config(self, target: str, config: Dict[str, Any]) -> None:
        """Write config to the appropriate bucket in the store."""
        if not config:
            return
        store = self._get_store()
        plugin_bucket = store.setdefault(self.name, {})
        bucket = plugin_bucket.setdefault(target, {"config": {}, "locals": {}})
        bucket["config"].update(config)

    def configuration(self, method_name: Optional[str] = None) -> Dict[str, Any]:
        """Read merged configuration (base + optional per-handler override)."""
        store = self._get_store()
        plugin_bucket = store.get(self.name)
        if not plugin_bucket:
            return {}
        base_bucket = plugin_bucket.get("--base--", {})
        base_config = self._resolve_config(base_bucket.get("config", {}))
        merged = dict(base_config)
        if method_name:
            entry_bucket = plugin_bucket.get(method_name, {})
            entry_config = self._resolve_config(entry_bucket.get("config", {}))
            merged.update(entry_config)
        return merged

    def _resolve_config(self, config: Any) -> Dict[str, Any]:
        """Resolve config value - if callable, call it to get the dict."""
        if callable(config):
            return config()
        if config is None:
            return {}
        return config

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

    def _get_store(self) -> Dict[str, Any]:
        return getattr(self._router, "_plugin_info")
