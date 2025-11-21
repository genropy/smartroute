"""Pydantic validation plugin (source of truth).

Rebuild exactly from this contract; no hidden behaviour.

Responsibilities
----------------
- At registration time (``on_decore``), inspect handler type hints and build a
  Pydantic model capturing annotated parameters.
- At call time (``wrap_handler``), validate annotated args/kwargs before
  calling the real handler; non-annotated parameters bypass validation.
- Surface validation failures as Pydantic ``ValidationError`` with contextual
  title ``"Validation error in <entry.name>"``.

Dependencies and guards
-----------------------
- Importing this module requires ``pydantic``; otherwise an ImportError is
  raised with install guidance. Under TYPE_CHECKING it hints ``Router`` import.
- If type hint resolution fails or no usable hints remain after dropping the
  return annotation, ``entry.metadata["pydantic"]`` is set to
  ``{"enabled": False}`` and wrapping becomes a passthrough.

Behaviour and data
------------------
- ``PydanticPlugin(name=None, **config)``: delegates to ``BasePlugin``; default
  name is ``"pydantic"``.
- ``on_decore(route, func, entry)``:
    * resolves type hints via ``get_type_hints(func)``; exceptions mark disabled.
    * removes ``return`` hint if present.
    * builds a fields dict from function signature:
        - annotated parameters missing from signature get required ellipsis.
        - parameters with default use that default; otherwise required.
    * creates a model ``<func.__name__>_Model`` via ``create_model``.
    * stores metadata in ``entry.metadata["pydantic"]``:
      ``{"enabled": True, "model": model, "hints": hints, "signature": sig}``.
- ``wrap_handler(route, entry, call_next)``:
    * if metadata missing or ``enabled`` is false, returns ``call_next``.
    * binds incoming args/kwargs with the captured ``signature`` (``sig.bind``)
      and applies defaults.
    * splits bound arguments into two dicts: annotated (validated) and
      non-annotated (passthrough).
    * runs the model with annotated args; on ``ValidationError`` raises a new
      ``ValidationError.from_exception_data`` with the contextual title.
    * merges validated values back with passthrough args into ``final_args`` and
      calls ``call_next(**final_args)``.
    * return value is propagated unchanged.
- ``describe_entry(router, entry, base_description)``: enriches the entry
  description parameters using stored Pydantic metadata (types/defaults/
  required/validation keys) and returns an empty dict after mutating
  ``base_description["parameters"]`` in place.

Registration
------------
Registers itself globally as ``"pydantic"`` during module import via
``Router.register_plugin("pydantic", PydanticPlugin)``.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, get_type_hints

try:
    from pydantic import ValidationError, create_model
except ImportError:  # pragma: no cover - import guard
    raise ImportError(
        "Pydantic plugin requires pydantic. Install with: pip install smartroute[pydantic]"
    )

from smartroute.core.base_router import _apply_pydantic_metadata
from smartroute.core.router import Router
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry

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

    def describe_entry(  # pragma: no cover - exercised indirectly by router describe
        self, router: "Router", entry: MethodEntry, base_description: Dict[str, Any]
    ) -> Dict[str, Any]:
        meta = entry.metadata.get("pydantic", {})
        if not meta or not meta.get("enabled"):
            return {}
        _apply_pydantic_metadata(meta, base_description.get("parameters", {}))
        return {}


Router.register_plugin("pydantic", PydanticPlugin)
