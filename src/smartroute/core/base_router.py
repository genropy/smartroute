"""Plugin-free router runtime (source of truth).

If this file vanished, rebuild it verbatim from this description. The module
exposes a single class, :class:`BaseRouter`, which binds methods on an object
instance, resolves dotted selectors, and exposes rich introspection without any
plugin logic. Subclasses add middleware but must preserve these semantics.

Constructor and slots
---------------------
Constructor signature::

    BaseRouter(owner, name=None, prefix=None, *,
               get_default_handler=None, get_use_smartasync=None,
               get_kwargs=None, auto_discover=True, auto_selector="*")

- ``owner`` is required; ``None`` raises ``ValueError``. Routers are bound to
  this instance and never re-bound.
- Slots: ``instance``, ``name``, ``prefix`` (string trimmed from function names),
  ``_entries`` (logical name → MethodEntry), ``_handlers`` (name → callable),
  ``_children`` (name → child router), ``_get_defaults`` (SmartOptions defaults).

- Default options: ``get_default_handler`` and ``get_use_smartasync`` become
  defaults merged via ``SmartOptions`` in ``get()``; extra ``get_kwargs`` are
  copied into ``_get_defaults``.

- On init: registers with owner via optional ``_register_router`` hook, then
  auto-discovers entries when ``auto_discover`` is true by calling
  ``add_entry(auto_selector)`` (``"*"`` by default).

Registration and naming
-----------------------
``add_entry(target, *, name=None, alias=None, metadata=None, replace=False, **options)``

- Accepts a callable or string/iterable of attribute names. Comma-separated
  strings are split and each processed. Empty/whitespace-only strings are
  ignored. ``replace=False`` raises on logical name collision.

- Special markers ``"*"``, ``"_all_"``, ``"__all__"`` trigger marker discovery
  via ``_register_marked`` (see below). A comma inside such marker string is
  split and each chunk processed recursively.

- When ``target`` is a string, it is resolved as an attribute of ``owner``; an
  ``AttributeError`` is surfaced with a helpful message.

- When ``target`` is a function, it is bound to ``owner`` unless already a
  bound method. ``metadata`` + ``options`` are merged into the MethodEntry
  metadata.

- ``_resolve_name`` strips ``prefix`` from ``func.__name__`` when present; an
  explicit ``name``/``alias`` always overrides.

Marker discovery
----------------
``_iter_marked_methods`` walks the reversed MRO of ``type(owner)`` (child first
wins), scans ``__dict__`` for plain functions carrying ``TARGET_ATTR`` markers.
Duplicates (by function identity) are skipped. Only markers whose ``name``
matches this router's ``name`` are used; the name key is removed from the
payload before consumption. ``_register_marked`` binds each function to owner,
merges marker data + metadata + extra options, and registers with collision
behaviour governed by ``replace``.

Handler table and wrapping
--------------------------
- ``_register_callable`` creates a ``MethodEntry`` (name, bound func, router,
  empty plugins list, metadata dict) and stores it in ``_entries``; it invokes
  ``_after_entry_registered`` hook then rebuilds the handler cache.

- ``_rebuild_handlers`` recreates ``_handlers`` by passing each entry through
  ``_wrap_handler`` (default: passthrough). Subclasses may inject middleware.

Lookup and execution
--------------------
- ``get(selector, **options)`` merges ``options`` into ``SmartOptions`` using
  ``_get_defaults``. It resolves ``selector`` via ``_resolve_path``: a dotted
  string traverses children (``get_child``) and yields the terminal router plus
  method name; no dot returns ``self`` + selector. Missing children raise
  ``KeyError`` via ``get_child``. Missing handlers fall back to
  ``default_handler`` (if provided) else raise ``NotImplementedError``.

- When ``use_smartasync`` option is truthy, the returned handler is wrapped via
  ``smartasync.smartasync`` before returning.

- ``__getitem__`` aliases ``get``; ``call`` fetches then invokes the handler
  with given args/kwargs. ``entries`` returns a tuple of registered handler
  names (built from ``_handlers`` keys).

Children
--------
``add_child(child, name=None)``

- If ``child`` is a comma-separated string, each token is resolved as an
  attribute on ``owner``; explicit ``name`` cannot be combined with multiple
  tokens (raises ``ValueError``). Missing attributes raise ``AttributeError``.

- Otherwise, routers are collected from the object (router instance, mapping
  with string keys as name hints, iterable with optional ``(name, router)``
  tuples, or attributes/slots containing routers). At least one router must be
  found or ``TypeError`` is raised. Children are attached under ``name`` or
  inferred attribute/override name; collisions with a different router raise
  ``ValueError``. For each attached child, ``_on_attached_to_parent`` is called.

- ``get_child`` retrieves by name or raises ``KeyError`` with a descriptive
  message.

Child discovery helpers
-----------------------
``_collect_child_routers(source, override_name=None, seen=None)``

- Uses structural matching to collect routers from a single source:

  * ``BaseRouter`` → returns the router with name hint
  * ``Mapping`` → recurses into values using string keys as hints
  * ``Iterable`` (non-string) → recurses elements; ``(name, router)`` tuples
    provide a name hint
  * otherwise inspects attributes/slots for ``BaseRouter`` instances, building
    unique keys (override → attr name → router.name → ``"child"``)

- ``seen`` tracks object ids to avoid cycles.

Introspection
-------------
- ``describe(scopes=None, channel=None)`` builds a nested dict:
  ``{"name", "prefix", "plugins", "methods", "children"}``.
  Methods map logical name → info:

    * ``doc`` (``inspect.getdoc`` or ``__doc__`` fallback)
    * ``signature`` string of ``inspect.signature``; ``return_type`` formatted
      via ``_format_annotation``
    * ``plugins`` (MethodEntry.plugins), ``metadata_keys`` list
    * ``parameters``: name → ``{"type", "default", "required"}`` from signature
      annotations/defaults only.

  Subclasses can inject additional data per entry via
  ``_describe_entry_extra(entry, base_description)``. The base router contributes
  nothing beyond the signature-derived fields.

- Filtering: ``_prepare_filter_args`` (base: drop ``None``/False values) and
  ``_should_include_entry`` (base: always True) allow subclasses to hide
  entries. Filters are applied both to ``methods`` and recursively to children.

- ``members(scopes=None, channel=None)`` returns live objects instead of
  strings: router, instance, handlers dict (callable + metadata), and children
  respecting the same filters; empty children pruned only when filters active.

Hooks for subclasses
--------------------
- ``_wrap_handler``: override to wrap callables (middleware stack).
- ``_after_entry_registered``: invoked after registering a handler.
- ``_on_attached_to_parent``: invoked when attached via ``add_child``.
- ``_describe_entry_extra``: allow subclasses to extend per-entry description.

Default implementations are no-ops/passthrough.

Invariants and guarantees
-------------------------
- Handler names are unique unless ``replace=True``.
- Selector traversal never fabricates routers: only attached children are used.
- Marker discovery is deterministic (reversed MRO, first occurrence wins).
- Introspection never mutates handler metadata; it reads from ``MethodEntry``.
- All normalizations preserve user-provided metadata copies (shallow-copied).
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from smartseeds import SmartOptions

from smartroute.plugins._base_plugin import MethodEntry

__all__ = ["BaseRouter", "TARGET_ATTR", "ROUTER_REGISTRY_ATTR"]

TARGET_ATTR = "__smartroute_targets__"
ROUTER_REGISTRY_ATTR = "__smartroute_router_registry__"


class BaseRouter:
    """Router bound directly to an object instance (no plugin support)."""

    __slots__ = (
        "instance",
        "name",
        "prefix",
        "_entries",
        "_handlers",
        "_children",
        "_get_defaults",
    )

    def __init__(
        self,
        owner: Any,
        name: Optional[str] = None,
        prefix: Optional[str] = None,
        *,
        get_default_handler: Optional[Callable] = None,
        get_use_smartasync: Optional[bool] = None,
        get_kwargs: Optional[Dict[str, Any]] = None,
        auto_discover: bool = True,
        auto_selector: str = "*",
    ) -> None:
        if owner is None:
            raise ValueError("Router requires a parent instance")
        self.instance = owner
        self.name = name
        self.prefix = prefix or ""
        self._entries: Dict[str, MethodEntry] = {}
        self._handlers: Dict[str, Callable] = {}
        self._children: Dict[str, BaseRouter] = {}
        defaults: Dict[str, Any] = dict(get_kwargs or {})
        if get_default_handler is not None:
            defaults.setdefault("default_handler", get_default_handler)
        if get_use_smartasync is not None:
            defaults.setdefault("use_smartasync", get_use_smartasync)
        self._get_defaults: Dict[str, Any] = defaults
        self._register_with_owner()
        if auto_discover:
            self.add_entry(auto_selector)

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def _register_with_owner(self) -> None:
        hook = getattr(self.instance, "_register_router", None)
        if callable(hook):
            hook(self)

    def add_entry(
        self,
        target: Any,
        *,
        name: Optional[str] = None,
        alias: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replace: bool = False,
        **options: Any,
    ) -> "BaseRouter":
        entry_name = name if name is not None else alias
        if isinstance(target, (list, tuple, set)):
            for entry in target:
                self.add_entry(
                    entry,
                    name=entry_name,
                    metadata=dict(metadata or {}),
                    replace=replace,
                    **options,
                )
            return self

        if isinstance(target, str):
            target = target.strip()
            if not target:
                return self
            if target in {"*", "_all_", "__all__"}:
                self._register_marked(
                    name=entry_name, metadata=metadata, replace=replace, extra=options
                )
                return self
            if "," in target:
                for chunk in target.split(","):
                    chunk = chunk.strip()
                    if chunk:
                        self.add_entry(
                            chunk,
                            name=entry_name,
                            metadata=dict(metadata or {}),
                            replace=replace,
                            **options,
                        )
                return self
            bound = getattr(self.instance, target)
        elif callable(target):
            bound = (
                target
                if inspect.ismethod(target)
                else target.__get__(self.instance, type(self.instance))
            )
        else:
            raise TypeError(f"Unsupported add_entry target: {target!r}")

        entry_meta = dict(metadata or {})
        entry_meta.update(options)
        self._register_callable(bound, name=entry_name, metadata=entry_meta, replace=replace)
        return self

    def _register_callable(
        self,
        bound: Callable,
        *,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replace: bool = False,
    ) -> None:
        logical_name = self._resolve_name(bound.__name__, alias=name)
        if logical_name in self._entries and not replace:
            raise ValueError(f"Handler name collision: {logical_name}")
        entry = MethodEntry(
            name=logical_name,
            func=bound,
            router=self,
            plugins=[],
            metadata=dict(metadata or {}),
        )
        self._entries[logical_name] = entry
        self._after_entry_registered(entry)
        self._rebuild_handlers()

    def _register_marked(
        self,
        *,
        name: Optional[str],
        metadata: Optional[Dict[str, Any]],
        replace: bool,
        extra: Dict[str, Any],
    ) -> None:
        for func, marker in self._iter_marked_methods():
            entry_override = marker.pop("entry_name", None) or marker.pop("alias", None)
            entry_name = name if name is not None else entry_override
            entry_meta = dict(metadata or {})
            entry_meta.update(marker)
            entry_meta.update(extra)
            bound = func.__get__(self.instance, type(self.instance))
            self._register_callable(
                bound,
                name=entry_name,
                metadata=entry_meta,
                replace=replace,
            )

    def _iter_marked_methods(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        cls = type(self.instance)
        seen: set[int] = set()
        for base in reversed(cls.__mro__):
            base_dict = vars(base)
            for attr_name, value in base_dict.items():
                if not inspect.isfunction(value):
                    continue
                func_id = id(value)
                if func_id in seen:
                    continue
                seen.add(func_id)
                markers = getattr(value, TARGET_ATTR, None)
                if not markers:
                    continue
                for marker in markers:
                    if marker.get("name") != self.name:
                        continue
                    payload = dict(marker)
                    payload.pop("name", None)
                    yield value, payload

    def _resolve_name(self, func_name: str, *, alias: Optional[str]) -> str:
        if alias:
            return alias
        if self.prefix and func_name.startswith(self.prefix):
            return func_name[len(self.prefix) :]
        return func_name

    def _wrap_handler(
        self, entry: MethodEntry, call_next: Callable
    ) -> Callable:  # pragma: no cover - overridden by plugin routers
        return call_next

    # ------------------------------------------------------------------
    # Handler execution
    # ------------------------------------------------------------------
    def _rebuild_handlers(self) -> None:
        handlers: Dict[str, Callable] = {}
        for logical_name, entry in self._entries.items():
            wrapped = self._wrap_handler(entry, entry.func)
            handlers[logical_name] = wrapped
        self._handlers = handlers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, selector: str, **options: Any) -> Callable:
        opts = SmartOptions(options, defaults=self._get_defaults)
        default = getattr(opts, "default_handler", None)
        use_smartasync = getattr(opts, "use_smartasync", False)

        node, method_name = self._resolve_path(selector)
        handler = node._handlers.get(method_name)
        if handler is None:
            handler = default
        if handler is None:
            raise NotImplementedError(
                f"Handler '{method_name}' not found for selector '{selector}'"
            )

        if use_smartasync:
            from smartasync import smartasync  # type: ignore

            handler = smartasync(handler)

        return handler

    __getitem__ = get

    def call(self, selector: str, *args, **kwargs):
        handler = self.get(selector)
        return handler(*args, **kwargs)

    def entries(self) -> Tuple[str, ...]:
        return tuple(self._handlers.keys())

    # ------------------------------------------------------------------
    # Children management
    # ------------------------------------------------------------------
    def add_child(self, child: Any, name: Optional[str] = None) -> "BaseRouter":
        if isinstance(child, str):
            tokens = [token.strip() for token in child.split(",") if token.strip()]
            if not tokens:
                return self
            if name and len(tokens) > 1:
                raise ValueError("Explicit name cannot be combined with multiple attribute targets")
            result: Optional[BaseRouter] = None
            for token in tokens:
                try:
                    target = getattr(self.instance, token)
                except AttributeError as exc:
                    raise AttributeError(
                        f"No attribute '{token}' on {type(self.instance).__name__}"
                    ) from exc
                result = self.add_child(target, name=name or token)
            assert result is not None
            return result

        candidates = self._collect_child_routers(child)
        if not candidates:
            raise TypeError(f"Object {child!r} does not expose Router instances")

        attached: Optional[BaseRouter] = None
        for attr_name, router in candidates:
            key = name or attr_name or router.name or "child"
            if key in self._children and self._children[key] is not router:
                raise ValueError(f"Child name collision: {key}")
            self._children[key] = router
            router._on_attached_to_parent(self)
            attached = router
        assert attached is not None
        return attached

    def get_child(self, name: str) -> "BaseRouter":
        try:
            return self._children[name]
        except KeyError:
            raise KeyError(f"No child route named {name!r}")

    def _collect_child_routers(
        self, source: Any, *, override_name: Optional[str] = None, seen: Optional[set[int]] = None
    ) -> List[Tuple[str, "BaseRouter"]]:
        """Return all routers found inside ``source``."""
        if seen is None:
            seen = set()
        obj_id = id(source)
        if obj_id in seen:
            return []
        seen.add(obj_id)

        match source:
            case BaseRouter():
                key = override_name or source.name or "router"
                return [(key, source)]
            case Mapping():
                collected: List[Tuple[str, BaseRouter]] = []
                for key, value in source.items():
                    hint = key if isinstance(key, str) else None
                    collected.extend(
                        self._collect_child_routers(value, override_name=hint, seen=seen)
                    )
                return collected
            case Iterable() if not isinstance(source, (str, bytes, bytearray)):
                collected = []
                for value in source:
                    name_hint = None
                    target = value
                    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
                        name_hint = value[0]
                        target = value[1]
                    collected.extend(
                        self._collect_child_routers(target, override_name=name_hint, seen=seen)
                    )
                return collected
            case _:
                router_items: List[Tuple[str, BaseRouter]] = []
                for attr_name, value in self._iter_instance_attributes(source):
                    if value is None or value is source:
                        continue
                    if isinstance(value, BaseRouter):
                        router_items.append((attr_name, value))

                if not router_items:
                    return []

                keyed: List[Tuple[str, BaseRouter]] = []
                seen_keys: set[str] = set()
                for attr_name, router in router_items:
                    key = override_name or attr_name or router.name or "child"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    keyed.append((key, router))
                return keyed

    @staticmethod
    def _iter_instance_attributes(obj: Any) -> Iterator[Tuple[str, Any]]:
        inst_dict = getattr(obj, "__dict__", None)
        if inst_dict:
            for key, value in inst_dict.items():
                if key == ROUTER_REGISTRY_ATTR:
                    continue
                yield key, value
        slots = getattr(type(obj), "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for slot in slots:
            if slot == ROUTER_REGISTRY_ATTR:
                continue
            if hasattr(obj, slot):
                yield slot, getattr(obj, slot)

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------
    def _resolve_path(self, selector: str) -> Tuple["BaseRouter", str]:
        if "." not in selector:
            return self, selector
        node: BaseRouter = self
        parts = selector.split(".")
        for segment in parts[:-1]:
            node = node.get_child(segment)
        return node, parts[-1]

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def describe(
        self, scopes: Optional[Any] = None, channel: Optional[str] = None
    ) -> Dict[str, Any]:
        filter_args = self._prepare_filter_args(scopes=scopes, channel=channel)

        def describe_node(node: "BaseRouter") -> Dict[str, Any]:
            return {
                "name": node.name,
                "prefix": node.prefix,
                "plugins": [p.name for p in node.iter_plugins()],
                "methods": {
                    name: _build_method_description(node, entry)
                    for name, entry in node._entries.items()
                    if node._should_include_entry(entry, **filter_args)
                },
                "children": {key: describe_node(child) for key, child in node._children.items()},
            }

        def _build_method_description(node: "BaseRouter", entry: MethodEntry) -> Dict[str, Any]:
            func = entry.func
            signature = inspect.signature(func)
            method_info: Dict[str, Any] = {
                "name": entry.name,
                "doc": inspect.getdoc(func) or func.__doc__ or "",
                "signature": str(signature),
                "return_type": _format_annotation(signature.return_annotation),
                "plugins": list(entry.plugins),
                "metadata_keys": list(entry.metadata.keys()),
                "parameters": {},
            }
            params = method_info["parameters"]
            for param_name, param in signature.parameters.items():
                params[param_name] = {
                    "type": _format_annotation(param.annotation),
                    "default": None if param.default is inspect._empty else param.default,
                    "required": param.default is inspect._empty,
                }

            pydantic_meta = entry.metadata.get("pydantic")
            if pydantic_meta and pydantic_meta.get("enabled"):
                _apply_pydantic_metadata(pydantic_meta, params)

            extra = node._describe_entry_extra(entry, method_info)
            if extra:
                method_info.update(extra)

            return method_info

        return describe_node(self)

    def members(
        self, scopes: Optional[Any] = None, channel: Optional[str] = None
    ) -> Dict[str, Any]:
        filter_args = self._prepare_filter_args(scopes=scopes, channel=channel)
        filter_active = bool(filter_args)

        def capture(node: "BaseRouter") -> Dict[str, Any]:
            handlers = {}
            for name, entry in node._entries.items():
                if not node._should_include_entry(entry, **filter_args):
                    continue
                handlers[name] = {
                    "callable": entry.func,
                    "metadata": entry.metadata,
                }

            children = {}
            for child_name, child in node._children.items():
                child_payload = capture(child)
                if not filter_active or child_payload["handlers"] or child_payload["children"]:
                    children[child_name] = child_payload

            return {
                "name": node.name,
                "router": node,
                "instance": node.instance,
                "handlers": handlers,
                "children": children,
            }

        return capture(self)

    # ------------------------------------------------------------------
    # Plugin hooks (no-op for BaseRouter)
    # ------------------------------------------------------------------
    def iter_plugins(self) -> List[Any]:  # pragma: no cover - base router has no plugins
        return []

    def _on_attached_to_parent(
        self, parent: "BaseRouter"
    ) -> None:  # pragma: no cover - hook for subclasses
        """Hook for plugin-enabled routers to override when attached."""
        return None

    def _after_entry_registered(
        self, entry: MethodEntry
    ) -> None:  # pragma: no cover - hook for subclasses
        """Hook invoked after a handler is registered (subclasses may override)."""
        return None

    def _describe_entry_extra(
        self, entry: MethodEntry, base_description: Dict[str, Any]
    ) -> Dict[str, Any]:  # pragma: no cover - overridden when plugins present
        """Hook used by subclasses to inject extra description data."""
        return {}

    def _prepare_filter_args(self, **raw_filters: Any) -> Dict[str, Any]:
        """Return normalized filters understood by subclasses (default: passthrough)."""
        return {key: value for key, value in raw_filters.items() if value not in (None, False)}

    def _should_include_entry(self, entry: MethodEntry, **filters: Any) -> bool:
        """Hook used by subclasses to decide if an entry is exposed."""
        return True


def _format_annotation(annotation: Any) -> str:
    if annotation in (inspect._empty, None):
        return "Any"
    if isinstance(annotation, str):
        return annotation
    if getattr(annotation, "__module__", None) == "builtins":
        return getattr(annotation, "__name__", str(annotation))
    return getattr(annotation, "__qualname__", str(annotation))


def _apply_pydantic_metadata(meta: Dict[str, Any], params: Dict[str, Any]) -> None:
    """Enrich parameter descriptions using stored Pydantic metadata."""
    model = meta.get("model")
    fields = getattr(model, "model_fields", {}) if model is not None else {}
    for field_name, field in fields.items():
        field_info = params.setdefault(
            field_name,
            {
                "type": _format_annotation(getattr(field, "annotation", inspect._empty)),
                "default": None,
                "required": True,
            },
        )
        annotation = getattr(field, "annotation", inspect._empty)
        field_info["type"] = _format_annotation(annotation)
        default = getattr(field, "default", None)
        if not _is_pydantic_undefined(default):
            field_info["default"] = default
        required = getattr(field, "is_required", None)
        if callable(required):
            field_info["required"] = bool(required())
        else:
            field_info["required"] = field_info["default"] is None
        validation: Dict[str, Any] = {"source": "pydantic"}
        metadata = getattr(field, "metadata", None)
        if metadata:
            validation["metadata"] = list(metadata)
        json_extra = getattr(field, "json_schema_extra", None)
        if json_extra:
            validation["json_schema_extra"] = json_extra
        description = getattr(field, "description", None)
        if description:
            validation["description"] = description
        examples = getattr(field, "examples", None)
        if examples:
            validation["examples"] = examples
        if validation:
            field_info["validation"] = validation


def _is_pydantic_undefined(value: Any) -> bool:
    cls = getattr(value, "__class__", None)
    return cls is not None and cls.__name__ == "PydanticUndefinedType"
