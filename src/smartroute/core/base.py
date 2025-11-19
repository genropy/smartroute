"""Lightweight plugin and metadata primitives for SmartRoute."""

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
