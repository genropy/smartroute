"""
Pydantic validation plugin adapted for the instance-scoped Router prototype.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Callable, Optional, get_type_hints

try:
    from pydantic import ValidationError, create_model
except ImportError:  # pragma: no cover - import guard
    raise ImportError(
        "Pydantic plugin requires pydantic. Install with: pip install smartroute[pydantic]"
    )

from smartroute.core import BasePlugin, MethodEntry, Router

if TYPE_CHECKING:
    from smartroute.core import Router


class PydanticPlugin(BasePlugin):
    """Validate handler inputs with Pydantic using type hints."""

    def __init__(self, name: Optional[str] = None, **config: Any):
        super().__init__(name=name or "pydantic", **config)

    def on_decore(self, route: "Router", func: Callable, entry: MethodEntry) -> None:
        try:
            hints = get_type_hints(func)
        except Exception:
            entry.metadata["pydantic"] = {"enabled": False}
            return

        hints.pop("return", None)
        if not hints:
            entry.metadata["pydantic"] = {"enabled": False}
            return

        sig = inspect.signature(func)
        fields = {}
        for param_name, hint in hints.items():
            param = sig.parameters.get(param_name)
            if param is None:
                fields[param_name] = (hint, ...)
            elif param.default is inspect.Parameter.empty:
                fields[param_name] = (hint, ...)
            else:
                fields[param_name] = (hint, param.default)

        validation_model = create_model(f"{func.__name__}_Model", **fields)  # type: ignore

        entry.metadata["pydantic"] = {
            "enabled": True,
            "model": validation_model,
            "hints": hints,
            "signature": sig,
        }

    def wrap_handler(self, route: "Router", entry: MethodEntry, call_next: Callable):
        meta = entry.metadata.get("pydantic", {})
        if not meta.get("enabled"):
            return call_next

        model = meta["model"]
        sig = meta["signature"]
        hints = meta["hints"]

        def wrapper(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            args_to_validate = {k: v for k, v in bound.arguments.items() if k in hints}
            other_args = {k: v for k, v in bound.arguments.items() if k not in hints}
            try:
                validated = model(**args_to_validate)
            except ValidationError as exc:
                raise ValidationError.from_exception_data(
                    title=f"Validation error in {entry.name}",
                    line_errors=exc.errors(),
                ) from exc

            final_args = other_args.copy()
            for key, value in validated:
                final_args[key] = value
            return call_next(**final_args)

        return wrapper


Router.register_plugin("pydantic", PydanticPlugin)
