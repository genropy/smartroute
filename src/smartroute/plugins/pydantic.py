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
  return annotation, no model is created and wrapping becomes a passthrough.

Behaviour and data
------------------
- ``PydanticPlugin(name=None, **config)``: delegates to ``BasePlugin``; default
  name is ``"pydantic"``.
- ``on_decore(route, func, entry)``:
    * resolves type hints via ``get_type_hints(func)``; exceptions skip model.
    * removes ``return`` hint if present.
    * builds a fields dict from function signature:
        - annotated parameters missing from signature get required ellipsis.
        - parameters with default use that default; otherwise required.
    * creates a model ``<func.__name__>_Model`` via ``create_model``.
    * stores metadata in ``entry.metadata["pydantic"]``:
      ``{"model": model, "hints": hints, "signature": sig}``.
- ``wrap_handler(route, entry, call_next)``:
    * calls ``get_model()`` to check if validation is disabled or no model exists.
    * if ``get_model()`` returns None, returns ``call_next`` (passthrough).
    * binds incoming args/kwargs with the captured ``signature`` (``sig.bind``)
      and applies defaults.
    * splits bound arguments into two dicts: annotated (validated) and
      non-annotated (passthrough).
    * runs the model with annotated args; on ``ValidationError`` raises a new
      ``ValidationError.from_exception_data`` with the contextual title.
    * merges validated values back with passthrough args into ``final_args`` and
      calls ``call_next(**final_args)``.
    * return value is propagated unchanged.
- ``get_model(entry)``: returns the Pydantic model unless config ``disabled``
  is truthy or no model exists.

Registration
------------
Registers itself globally as ``"pydantic"`` during module import via
``Router.register_plugin(PydanticPlugin)``.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple, get_type_hints

try:
    from pydantic import ValidationError, create_model
except ImportError:  # pragma: no cover - import guard
    raise ImportError(
        "Pydantic plugin requires pydantic. Install with: pip install smartroute[pydantic]"
    )

from smartroute.core.router import Router
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry

if TYPE_CHECKING:
    from smartroute.core import Router


class PydanticPlugin(BasePlugin):
    """Validate handler inputs with Pydantic using type hints."""

    plugin_code = "pydantic"
    plugin_description = "Validates handler inputs using Pydantic type hints"

    def __init__(self, router, **config: Any):
        super().__init__(router, **config)

    def configure(self, disabled: bool = False):
        """Configure pydantic plugin options.

        The wrapper added by __init_subclass__ handles writing to store.
        """
        pass  # Storage is handled by the wrapper

    def on_decore(self, route: "Router", func: Callable, entry: MethodEntry) -> None:
        try:
            hints = get_type_hints(func)
        except Exception:
            # No hints resolvable, no model created
            return

        hints.pop("return", None)
        if not hints:
            # No parameter hints, no model needed
            return

        sig = inspect.signature(func)
        fields = {}
        for param_name, hint in hints.items():
            param = sig.parameters.get(param_name)
            if param is None:
                raise ValueError(
                    f"Handler '{func.__name__}' has type hint for '{param_name}' "
                    f"which is not in the function signature"
                )
            elif param.default is inspect.Parameter.empty:
                fields[param_name] = (hint, ...)
            else:
                fields[param_name] = (hint, param.default)

        validation_model = create_model(f"{func.__name__}_Model", **fields)  # type: ignore

        entry.metadata["pydantic"] = {
            "model": validation_model,
            "hints": hints,
            "signature": sig,
        }

    def wrap_handler(self, route: "Router", entry: MethodEntry, call_next: Callable):
        """Validate annotated parameters with the cached Pydantic model before calling."""
        meta = entry.metadata.get("pydantic", {})
        model = meta.get("model")
        if not model:
            # No model created (no type hints), passthrough
            return call_next

        sig = meta["signature"]
        hints = meta["hints"]

        def wrapper(*args, **kwargs):
            # Check disabled config at runtime (not at wrap time)
            cfg = self.configuration(entry.name)
            if cfg.get("disabled"):
                return call_next(*args, **kwargs)

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

    def get_model(self, entry: MethodEntry) -> Optional[Tuple[str, Any]]:
        """Return the Pydantic model for this handler if not disabled."""
        cfg = self.configuration(entry.name)
        if cfg.get("disabled"):
            return None

        meta = entry.metadata.get("pydantic", {})
        model = meta.get("model")
        if not model:
            return None
        return ("pydantic_model", model)

    def entry_metadata(self, router: Any, entry: MethodEntry) -> Dict[str, Any]:
        """Return pydantic metadata for introspection."""
        meta = entry.metadata.get("pydantic", {})
        if not meta:
            return {}
        return {
            "model": meta.get("model"),
            "hints": meta.get("hints"),
        }


Router.register_plugin(PydanticPlugin)
