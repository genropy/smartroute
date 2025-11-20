"""Plugin-free router runtime.

This module isolates the minimal routing engine used by SmartRoute. The
:class:`BaseRouter` binds methods from a host object, exposes hierarchical
lookup (``foo.bar`` selectors), provides handler introspection, and keeps
the runtime free from any plugin logic. Plugins extend the behaviour via the
derived :class:`~smartroute.core.router.Router` class, but the base router must
always work on its own so lightweight apps are unaffected by the plugin
system.
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

    def _wrap_handler(self, entry: MethodEntry, call_next: Callable) -> Callable:
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
            attached: Optional[BaseRouter] = None
            for token in tokens:
                try:
                    target = getattr(self.instance, token)
                except AttributeError as exc:
                    raise AttributeError(
                        f"No attribute '{token}' on {type(self.instance).__name__}"
                    ) from exc
                attached = self.add_child(target, name=name or token)
            assert attached is not None
            return attached
        candidates = list(self._iter_child_routers(child))
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

    def _iter_child_routers(
        self, source: Any, seen: Optional[set[int]] = None, override_name: Optional[str] = None
    ) -> Iterator[Tuple[str, "BaseRouter"]]:
        if isinstance(source, BaseRouter):
            yield override_name or source.name or "router", source
            return
        if seen is None:
            seen = set()
        obj_id = id(source)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if isinstance(source, Mapping):
            for key, value in source.items():
                hint = key if isinstance(key, str) else None
                yield from self._iter_child_routers(value, seen, hint)
            return
        if isinstance(source, Iterable) and not isinstance(source, (str, bytes, bytearray)):
            for value in source:
                name_hint = None
                target = value
                if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
                    name_hint = value[0]
                    target = value[1]
                yield from self._iter_child_routers(target, seen, name_hint)
            return

        router_items: List[Tuple[str, BaseRouter]] = []
        for attr_name, value in self._iter_instance_attributes(source):
            if value is None or value is source:
                continue
            if isinstance(value, BaseRouter):
                router_items.append((attr_name, value))

        if not router_items:
            return

        if override_name and len(router_items) == 1:
            yield (override_name, router_items[0][1])
            return

        yielded: set[str] = set()
        for attr_name, router in router_items:
            key = override_name or attr_name or router.name or "child"
            if key in yielded:
                continue
            yielded.add(key)
            yield (key, router)

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
        scope_filter = self._normalize_scope_filter(scopes)
        channel_filter = self._normalize_channel_filter(channel)
        filter_active = bool(scope_filter or channel_filter)

        def describe_node(node: "BaseRouter") -> Dict[str, Any]:
            scope_plugin = (
                getattr(node, "_plugins_by_name", {}).get("scope")
                if hasattr(node, "_plugins_by_name")
                else None
            )

            return {
                "name": node.name,
                "prefix": node.prefix,
                "plugins": [p.name for p in node.iter_plugins()],
                "methods": {
                    name: _build_method_description(entry, scope_plugin)
                    for name, entry in node._entries.items()
                    if not filter_active
                    or _entry_matches_filters(entry, scope_filter, channel_filter)
                },
                "children": {key: describe_node(child) for key, child in node._children.items()},
            }

        def _build_method_description(
            entry: MethodEntry, scope_plugin: Optional[Any]
        ) -> Dict[str, Any]:
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
                model = pydantic_meta.get("model")
                fields = getattr(model, "model_fields", {}) if model is not None else {}
                for field_name, field in fields.items():
                    field_info = params.setdefault(
                        field_name,
                        {
                            "type": _format_annotation(
                                getattr(field, "annotation", inspect._empty)
                            ),
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

            if scope_plugin and hasattr(scope_plugin, "describe_method"):
                scope_meta = scope_plugin.describe_method(entry.name)
                if scope_meta:
                    method_info["scope"] = scope_meta

            return method_info

        return describe_node(self)

    def members(
        self, scopes: Optional[Any] = None, channel: Optional[str] = None
    ) -> Dict[str, Any]:
        scope_filter = self._normalize_scope_filter(scopes)
        channel_filter = self._normalize_channel_filter(channel)
        filter_active = bool(scope_filter or channel_filter)

        def capture(node: "BaseRouter") -> Dict[str, Any]:
            handlers = {}
            for name, entry in node._entries.items():
                if filter_active and not _entry_matches_filters(
                    entry, scope_filter, channel_filter
                ):
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

    def _on_attached_to_parent(self, parent: "BaseRouter") -> None:
        """Hook for plugin-enabled routers to override when attached."""
        return None

    def _after_entry_registered(self, entry: MethodEntry) -> None:
        """Hook invoked after a handler is registered (subclasses may override)."""
        return None

    def _normalize_scope_filter(self, scopes: Optional[Any]) -> Optional[set[str]]:
        if scopes is None or scopes is False:
            return None
        if isinstance(scopes, str):
            items = scopes.split(",")
        elif isinstance(scopes, Iterable):
            items = scopes
        else:
            raise TypeError("scopes must be a string or iterable of strings")

        cleaned = {str(item).strip() for item in items if str(item).strip()}
        return cleaned or None

    def _normalize_channel_filter(self, channel: Optional[str]) -> Optional[str]:
        if channel is None or channel is False:
            return None
        if isinstance(channel, str):
            normalized = channel.strip()
            if not normalized:
                raise ValueError("channel cannot be empty")
            if normalized != normalized.upper():
                raise ValueError(f"channel must be uppercase (got '{normalized}')")
            return normalized
        raise TypeError("channel must be a string")


def _format_annotation(annotation: Any) -> str:
    if annotation in (inspect._empty, None):
        return "Any"
    if isinstance(annotation, str):
        return annotation
    if getattr(annotation, "__module__", None) == "builtins":
        return getattr(annotation, "__name__", str(annotation))
    return getattr(annotation, "__qualname__", str(annotation))


def _is_pydantic_undefined(value: Any) -> bool:
    cls = getattr(value, "__class__", None)
    return cls is not None and cls.__name__ == "PydanticUndefinedType"


def _entry_matches_filters(
    entry: MethodEntry, scope_filter: Optional[set[str]], channel_filter: Optional[str]
) -> bool:
    scope_meta = entry.metadata.get("scope") if entry.metadata else None
    tags = scope_meta.get("tags") if isinstance(scope_meta, dict) else None

    if scope_filter:
        if not tags or not any(tag in scope_filter for tag in tags):
            return False

    if channel_filter:
        if not scope_meta:
            return False
        channel_map = scope_meta.get("channels", {}) if isinstance(scope_meta, dict) else {}
        if not isinstance(channel_map, dict):
            return False
        relevant_scopes = tags or list(channel_map.keys())
        allowed: set[str] = set()
        for scope_name in relevant_scopes:
            codes = channel_map.get(scope_name, [])
            for code in codes or []:
                normalized = str(code).strip()
                if normalized:
                    allowed.add(normalized)
        if channel_filter not in allowed:
            return False

    if scope_filter or channel_filter:
        return bool(tags)
    return True
