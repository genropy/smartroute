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
``add_entry(target, *, name=None, metadata=None, replace=False, **options)``

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
  explicit ``name`` always overrides.

Marker discovery
----------------
``_iter_marked_methods`` walks the reversed MRO of ``type(owner)`` (child first
wins), scans ``__dict__`` for plain functions carrying ``TARGET_ATTR_NAME``
markers.
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
  string traverses children (``_children`` lookup) and yields the terminal router plus
  method name; no dot returns ``self`` + selector. Missing children raise
  ``KeyError``. Missing handlers fall back to
  ``default_handler`` (if provided) else raise ``NotImplementedError``.

- When ``use_smartasync`` option is truthy, the returned handler is wrapped via
  ``smartasync.smartasync`` before returning.

- ``__getitem__`` aliases ``get``; ``call`` fetches then invokes the handler
  with given args/kwargs. ``entries`` returns a tuple of registered handler
  names (built from ``_handlers`` keys).

Children (instance hierarchies only)
------------------------------------
``attach_instance(child, name=None)`` / ``detach_instance(child)``

- ``attach_instance`` connects routers exposed on a ``RoutedClass`` child that
  is already stored as an attribute on the parent instance. It enforces that
  the child is not bound to another parent (via ``_routed_parent``).
- Alias/mapping rules:
  * parent with a single router: ``name`` optional; if the child has multiple
    routers and no mapping is provided, aliases default to child router names.
  * parent with multiple routers: explicit alias/mapping is required.
  * unmapped child routers are skipped (not attached).
- Attached child routers inherit plugins via ``_on_attached_to_parent``; the
  child's ``_routed_parent`` is set to the parent instance.

``detach_instance`` removes all child routers whose ``instance`` matches the
given child and clears ``_routed_parent`` when pointing to the parent. It is
best-effort (no error if nothing was removed).

Child discovery helpers
-----------------------
``_collect_child_routers(source, override_name=None, seen=None)`` scans only
attributes/slots on ``source`` for ``BaseRouter`` instances, returning
``[(key, router), ...]`` with unique keys (override → attr name → router.name →
``"child"``). A ``seen`` set guards against cycles.

Introspection
-------------
- ``members(scopes=None, channel=None)`` builds a nested dict of routers and
  handlers respecting filters. Each handler entry contains:

    * ``callable`` (entry.func)
    * ``metadata`` (MethodEntry.metadata)
    * ``doc`` (``inspect.getdoc`` or ``__doc__`` fallback)
    * ``signature`` string of ``inspect.signature``
    * ``return_type`` via ``_format_annotation``
    * ``plugins`` (MethodEntry.plugins)
    * ``metadata_keys`` list
    * ``parameters``: name → ``{"type", "default", "required"}`` from signature
      annotations/defaults only.
    * plus any subclass-provided extras via ``_describe_entry_extra``.

  Filtering: ``_prepare_filter_args`` (base: drop ``None``/False values) and
  ``_should_include_entry`` (base: always True) allow subclasses to hide
  entries. Filters are applied both to methods and recursively to children.
  Empty children are pruned only when filters are active.

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
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from smartseeds import SmartOptions
from smartseeds.typeutils import safe_is_instance

from smartroute.plugins._base_plugin import MethodEntry

__all__ = ["BaseRouter", "TARGET_ATTR_NAME", "ROUTER_REGISTRY_ATTR_NAME"]

TARGET_ATTR_NAME = "__smartroute_targets__"
ROUTER_REGISTRY_ATTR_NAME = "__smartroute_router_registry__"


class BaseRouter:
    """Plugin-free router bound to an object instance.

    Responsibilities:
    - register bound methods/functions with logical names (optionally via markers)
    - resolve dotted selectors across child routers
    - expose handler tables and introspection data
    - provide hooks for subclasses to wrap handlers or filter introspection
    """

    __slots__ = (
        "instance",
        "name",
        "prefix",
        "_entries",
        "_handlers",
        "_children",
        "_get_defaults",
        "_is_branch",
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
        branch: bool = False,
        auto_discover: bool = True,
        auto_selector: str = "*",
    ) -> None:
        if owner is None:
            raise ValueError("Router requires a parent instance")
        self.instance = owner
        self.name = name
        self.prefix = prefix or ""
        self._is_branch = bool(branch)
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
        if self._is_branch and auto_discover:
            raise ValueError("Branch routers cannot auto-discover handlers")
        if auto_discover:
            self.add_entry(auto_selector)

    def _is_known_plugin(self, prefix: str) -> bool:
        try:
            from smartroute.core.router import Router  # type: ignore
        except Exception:  # pragma: no cover - import safety
            return False
        return prefix in Router.available_plugins()

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
        metadata: Optional[Dict[str, Any]] = None,
        replace: bool = False,
        **options: Any,
    ) -> "BaseRouter":
        """Register handler(s) on this router.

        Args:
            target: Callable, attribute name(s), comma-separated string, or wildcard marker.
            name: Logical name override for this entry.
            metadata: Extra metadata stored on the MethodEntry.
            replace: Allow overwriting an existing logical name.
            options: Extra metadata merged into entry metadata.

        Returns:
            self (to allow chaining).

        Raises:
            ValueError: on handler name collision when replace is False.
            AttributeError: when resolving missing attributes on owner.
            TypeError: on unsupported target type.
        """
        if self._is_branch:
            raise ValueError("Branch routers cannot register handlers")
        entry_name = name
        # Split plugin-scoped options (<plugin>_<key>) from core options
        plugin_options: Dict[str, Dict[str, Any]] = {}
        core_options: Dict[str, Any] = {}
        for key, value in options.items():
            if "_" in key:
                plugin_name, plug_key = key.split("_", 1)
                if plugin_name and plug_key and self._is_known_plugin(plugin_name):
                    plugin_options.setdefault(plugin_name, {})[plug_key] = value
                    continue
            core_options[key] = value

        if isinstance(target, (list, tuple, set)):
            for entry in target:
                self.add_entry(
                    entry,
                    name=entry_name,
                    metadata=dict(metadata or {}),
                    replace=replace,
                    **core_options,
                )
            return self

        if isinstance(target, str):
            target = target.strip()
            if not target:
                return self
            if target in {"*", "_all_", "__all__"}:
                self._register_marked(
                    name=entry_name,
                    metadata=metadata,
                    replace=replace,
                    extra=core_options,
                    plugin_options=plugin_options,
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
                            **core_options,
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
        entry_meta.update(core_options)
        self._register_callable(
            bound,
            name=entry_name,
            metadata=entry_meta,
            replace=replace,
            plugin_options=plugin_options,
        )
        return self

    def _register_callable(
        self,
        bound: Callable,
        *,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replace: bool = False,
        plugin_options: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        logical_name = self._resolve_name(bound.__name__, name_override=name)
        if logical_name in self._entries and not replace:
            raise ValueError(f"Handler name collision: {logical_name}")
        entry = MethodEntry(
            name=logical_name,
            func=bound,
            router=self,
            plugins=[],
            metadata=dict(metadata or {}),
        )
        # Attach plugin-scoped config to metadata for later consumption by plugin-enabled routers.
        if plugin_options:
            entry.metadata["plugin_config"] = plugin_options
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
        plugin_options: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        for func, marker in self._iter_marked_methods():
            entry_override = marker.pop("entry_name", None)
            entry_name = name if name is not None else entry_override
            entry_meta = dict(metadata or {})
            entry_meta.update(marker)
            entry_meta.update(extra)
            # Split plugin-scoped options from marker payload as well
            marker_plugin_opts: Dict[str, Dict[str, Any]] = {}
            core_marker: Dict[str, Any] = {}
            for key, value in entry_meta.items():
                if "_" in key:
                    plugin_name, plug_key = key.split("_", 1)
                    if plugin_name and plug_key and self._is_known_plugin(plugin_name):
                        marker_plugin_opts.setdefault(plugin_name, {})[plug_key] = value
                        continue
                core_marker[key] = value
            entry_meta = core_marker
            merged_plugin_opts: Dict[str, Dict[str, Any]] = {}
            if plugin_options:
                merged_plugin_opts.update(plugin_options)
            for pname, pdata in marker_plugin_opts.items():
                merged_plugin_opts.setdefault(pname, {}).update(pdata)
            bound = func.__get__(self.instance, type(self.instance))
            self._register_callable(
                bound,
                name=entry_name,
                metadata=entry_meta,
                replace=replace,
                plugin_options=merged_plugin_opts or None,
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
                markers = getattr(value, TARGET_ATTR_NAME, None)
                if not markers:
                    continue
                for marker in markers:
                    if marker.get("name") != self.name:
                        continue
                    payload = dict(marker)
                    payload.pop("name", None)
                    yield value, payload

    def _resolve_name(self, func_name: str, *, name_override: Optional[str]) -> str:
        if name_override:
            return name_override
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
        """Resolve and return a handler callable for the given selector.

        Dotted selectors traverse attached children. Falls back to
        ``default_handler`` if provided, otherwise raises NotImplementedError.
        When ``use_smartasync`` is true, the handler is wrapped accordingly.
        """
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
        """Fetch and invoke a handler in one step."""
        handler = self.get(selector)
        return handler(*args, **kwargs)

    def entries(self) -> Tuple[str, ...]:
        """Return a tuple of logical handler names registered on this router."""
        return tuple(self._handlers.keys())

    # ------------------------------------------------------------------
    # Children management (via attach_instance/detach_instance)
    # ------------------------------------------------------------------
    def attach_instance(self, routed_child: Any, *, name: Optional[str] = None) -> "BaseRouter":
        """Attach a RoutedClass instance with optional alias mapping."""
        if not safe_is_instance(routed_child, "smartroute.core.routed.RoutedClass"):
            raise TypeError("attach_instance() requires a RoutedClass instance")
        existing_parent = getattr(routed_child, "_routed_parent", None)
        if existing_parent is not None and existing_parent is not self.instance:
            raise ValueError("attach_instance() rejected: child already bound to another parent")

        # Require the parent to already reference the child via an attribute.
        has_attr_reference = any(
            value is routed_child for _, value in self._iter_instance_attributes(self.instance)
        )
        if not has_attr_reference:
            raise ValueError("attach_instance() requires the child to be stored on the parent")

        candidates = self._collect_child_routers(routed_child)
        if not candidates:
            raise TypeError(
                f"Object {routed_child!r} does not expose Router instances"
            )  # pragma: no cover

        mapping: Dict[str, str] = {}
        tokens = [chunk.strip() for chunk in (name.split(",") if name else []) if chunk.strip()]
        parent_registry = getattr(self.instance, ROUTER_REGISTRY_ATTR_NAME, {}) or {}
        parent_has_multiple = len(parent_registry) > 1

        if len(candidates) == 1:
            # Single child router: alias optional unless parent has multiple routers.
            if parent_has_multiple and not tokens:
                raise ValueError(
                    "attach_instance() requires alias when parent has multiple routers"
                )  # pragma: no cover
            alias = tokens[0] if tokens else name or candidates[0][0] or candidates[0][1].name
            orig_attr, _ = candidates[0]
            mapping[orig_attr] = alias
        else:
            # Multiple child routers.
            if parent_has_multiple and not tokens:
                raise ValueError(
                    "attach_instance() requires mapping when parent has multiple routers"
                )  # pragma: no cover
            if not tokens:
                # Auto-mapping: alias = child router name/attr
                for orig_attr, router in candidates:
                    alias = router.name or orig_attr
                    mapping[orig_attr] = alias
            else:
                candidate_names = {attr for attr, _ in candidates}
                for token in tokens:
                    if ":" not in token:
                        raise ValueError(
                            "attach_instance() with multiple routers requires mapping 'child:alias'"
                        )  # pragma: no cover
                    orig, alias = [part.strip() for part in token.split(":", 1)]
                    if not orig or not alias:
                        raise ValueError(
                            "attach_instance() mapping requires both child and alias"
                        )  # pragma: no cover
                    if orig not in candidate_names:
                        raise ValueError(
                            f"Unknown child router {orig!r} in mapping"
                        )  # pragma: no cover
                    if orig in mapping:
                        raise ValueError(f"Duplicate mapping for {orig!r}")  # pragma: no cover
                    mapping[orig] = alias
                # Unmapped child routers are simply not attached.

        attached: Optional[BaseRouter] = None
        for attr_name, router in candidates:
            alias = mapping.get(attr_name)
            if alias is None:
                continue  # pragma: no cover - unmapped child router is skipped
            if alias in self._children and self._children[alias] is not router:
                raise ValueError(f"Child name collision: {alias}")
            self._children[alias] = router
            router._on_attached_to_parent(self)
            attached = router

        if getattr(routed_child, "_routed_parent", None) is not self.instance:
            object.__setattr__(routed_child, "_routed_parent", self.instance)
        assert attached is not None
        return attached

    def detach_instance(self, routed_child: Any) -> "BaseRouter":
        """Detach all routers belonging to a RoutedClass instance."""
        if not safe_is_instance(routed_child, "smartroute.core.routed.RoutedClass"):
            raise TypeError("detach_instance() requires a RoutedClass instance")
        removed: List[str] = []
        for alias, router in list(self._children.items()):
            if router.instance is routed_child:
                removed.append(alias)
                self._children.pop(alias, None)

        if getattr(routed_child, "_routed_parent", None) is self.instance:
            object.__setattr__(routed_child, "_routed_parent", None)

        # No hard error if nothing was removed; detach is best-effort.
        return routed_child  # type: ignore[return-value]

    def _collect_child_routers(
        self, source: Any, *, override_name: Optional[str] = None, seen: Optional[set[int]] = None
    ) -> List[Tuple[str, "BaseRouter"]]:
        """Return all routers found inside ``source`` (attributes only)."""
        if seen is None:
            seen = set()
        obj_id = id(source)
        if obj_id in seen:
            return []  # pragma: no cover - defensive cycle guard
        seen.add(obj_id)

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
                continue  # pragma: no cover - duplicate key guard
            seen_keys.add(key)
            keyed.append((key, router))
        return keyed

    @staticmethod
    def _iter_instance_attributes(obj: Any) -> Iterator[Tuple[str, Any]]:
        inst_dict = getattr(obj, "__dict__", None)
        if inst_dict:
            for key, value in inst_dict.items():
                if key == ROUTER_REGISTRY_ATTR_NAME:
                    continue
                yield key, value
        slots = getattr(type(obj), "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for slot in slots:
            if slot == ROUTER_REGISTRY_ATTR_NAME:
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
            node = node._children[segment]
        return node, parts[-1]

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def members(
        self, scopes: Optional[Any] = None, channel: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return a live tree of routers/handlers/metadata respecting filters."""
        filter_args = self._prepare_filter_args(scopes=scopes, channel=channel)
        filter_active = bool(filter_args)

        def build_method_description(node: "BaseRouter", entry: MethodEntry) -> Dict[str, Any]:
            func = entry.func
            signature = inspect.signature(func)
            method_info: Dict[str, Any] = {
                "name": entry.name,
                "callable": func,
                "metadata": entry.metadata,
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

        def capture(node: "BaseRouter") -> Dict[str, Any]:
            handlers = {}
            for name, entry in node._entries.items():
                if not node._should_include_entry(entry, **filter_args):
                    continue
                handlers[name] = build_method_description(node, entry)

            children = {}
            for child_name, child in node._children.items():
                child_payload = capture(child)
                if not filter_active or child_payload["handlers"] or child_payload["children"]:
                    children[child_name] = child_payload

            plugin_info: Dict[str, Any] = {}
            info_source = getattr(node, "_plugin_info", {}) or {}
            for pname, pdata in info_source.items():
                plugin_info[pname] = {
                    key: {
                        "config": dict(slot.get("config", {})),
                        "locals": dict(slot.get("locals", {})),
                    }
                    for key, slot in pdata.items()
                }

            return {
                "name": node.name,
                "router": node,
                "instance": node.instance,
                "plugin_info": plugin_info,
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
