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
    """Minimal hook interface for router plugins."""

    def __init__(self, name: Optional[str] = None, **config: Any):
        self.name = name or self.__class__.__name__.lower()
        self.config: Dict[str, Any] = dict(config)

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
