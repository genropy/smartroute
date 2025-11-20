"""Router Runtime and Plugin Registry
=====================================

Scope
-----
- bind handlers to object instances without using descriptors
- manage plugin registration, inheritance, and per-handler wrapping
- provide runtime configuration helpers (`configure`, enable/disable hooks)
- expose introspection primitives (`describe`, `members`) for Publisher/CLI

Invariants
----------
- routers are instance-scoped: every object owns its own router tree
- plugin registration is global but instantiation is per-router
- handler metadata (``MethodEntry``) is the single source of truth for
  describing routes; no hidden registries exist outside this module
"""

from __future__ import annotations

import contextvars
import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type

from smartseeds import SmartOptions

from smartroute.plugins._base_plugin import BasePlugin, MethodEntry

__all__ = ["Router", "TARGET_ATTR", "ROUTER_REGISTRY_ATTR"]

TARGET_ATTR = "__smartroute_targets__"
ROUTER_REGISTRY_ATTR = "__smartroute_router_registry__"

_ACTIVATION_CTX: contextvars.ContextVar[Dict[Any, bool] | None] = contextvars.ContextVar(
    "smartroute_activation", default=None
)
_RUNTIME_CTX: contextvars.ContextVar[Dict[Any, Dict[str, Any]] | None] = contextvars.ContextVar(
    "smartroute_runtime", default=None
)
_PLUGIN_REGISTRY: Dict[str, Type[BasePlugin]] = {}


def _get_activation_map() -> Dict[Any, bool]:
    mapping = _ACTIVATION_CTX.get()
    if mapping is None:
        mapping = {}
        _ACTIVATION_CTX.set(mapping)
    return mapping


def _get_runtime_map() -> Dict[Any, Dict[str, Any]]:
    mapping = _RUNTIME_CTX.get()
    if mapping is None:
        mapping = {}
        _RUNTIME_CTX.set(mapping)
    return mapping


@dataclass
class _PluginSpec:
    factory: Type[BasePlugin]
    kwargs: Dict[str, Any]
    alias: Optional[str] = None

    def instantiate(self) -> BasePlugin:
        plugin = self.factory(**self.kwargs)
        if self.alias:
            plugin.name = self.alias
        return plugin

    def clone(self) -> "_PluginSpec":
        return _PluginSpec(self.factory, dict(self.kwargs), self.alias)


class Router:
    """Router bound directly to an object instance."""

    __slots__ = (
        "instance",
        "name",
        "prefix",
        "_entries",
        "_handlers",
        "_children",
        "_plugin_specs",
        "_plugins",
        "_plugins_by_name",
        "_get_defaults",
        "_inherited_from",
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
    ):
        if owner is None:
            raise ValueError("Router requires a parent instance")
        self.instance = owner
        self.name = name
        self.prefix = prefix or ""
        self._entries: Dict[str, MethodEntry] = {}
        self._handlers: Dict[str, Callable] = {}
        self._children: Dict[str, Router] = {}
        self._plugin_specs: List[_PluginSpec] = []
        self._plugins: List[BasePlugin] = []
        self._plugins_by_name: Dict[str, BasePlugin] = {}
        self._inherited_from: set[int] = set()
        defaults: Dict[str, Any] = dict(get_kwargs or {})
        if get_default_handler is not None:
            defaults.setdefault("default_handler", get_default_handler)
        if get_use_smartasync is not None:
            defaults.setdefault("use_smartasync", get_use_smartasync)
        self._get_defaults: Dict[str, Any] = defaults
        self._register_with_owner()
        if auto_discover:
            self.add_entry(auto_selector)

    def _register_with_owner(self) -> None:
        hook = getattr(self.instance, "_register_router", None)
        if callable(hook):
            hook(self)

    # ------------------------------------------------------------------
    # Plugin registration
    # ------------------------------------------------------------------
    @classmethod
    def register_plugin(cls, name: str, plugin_class: Type[BasePlugin]) -> None:
        if not isinstance(plugin_class, type) or not issubclass(plugin_class, BasePlugin):
            raise TypeError("plugin_class must be a BasePlugin subclass")
        if not name:
            raise ValueError("plugin name cannot be empty")
        existing = _PLUGIN_REGISTRY.get(name)
        if existing is not None and existing is not plugin_class:
            raise ValueError(f"Plugin name '{name}' already registered")
        _PLUGIN_REGISTRY[name] = plugin_class

    @classmethod
    def available_plugins(cls) -> Dict[str, Type[BasePlugin]]:
        return dict(_PLUGIN_REGISTRY)

    def plug(self, plugin: str, **config: Any) -> "Router":
        if not isinstance(plugin, str):
            raise TypeError(
                f"Plugin must be referenced by name string, got {type(plugin).__name__}"
            )
        plugin_class = _PLUGIN_REGISTRY.get(plugin)
        if plugin_class is None:
            available = ", ".join(sorted(_PLUGIN_REGISTRY)) or "none"
            raise ValueError(
                f"Unknown plugin '{plugin}'. Register it first. Available plugins: {available}"
            )
        spec = _PluginSpec(plugin_class, dict(config), alias=plugin)
        self._plugin_specs.append(spec)
        instance = spec.instantiate()
        self._plugins.append(instance)
        self._plugins_by_name[instance.name] = instance
        self._apply_plugin_to_entries(instance)
        self._rebuild_handlers()
        return self

    # ------------------------------------------------------------------
    # Entry registration
    # ------------------------------------------------------------------
    def add_entry(
        self,
        target: Any,
        *,
        name: Optional[str] = None,
        alias: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replace: bool = False,
        **options: Any,
    ) -> "Router":
        """Register handlers by name, callable, or wildcard."""
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
            plugins=[p.name for p in self._plugins],
            metadata=dict(metadata or {}),
        )
        self._entries[logical_name] = entry
        for plugin in self._plugins:
            plugin.on_decore(self, entry.func, entry)
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

    # ------------------------------------------------------------------
    # Plugin runtime helpers
    # ------------------------------------------------------------------
    def _activation_key(self, method_name: str, plugin_name: str) -> Tuple[int, str, str]:
        return (id(self.instance), method_name, plugin_name)

    def set_plugin_enabled(self, method_name: str, plugin_name: str, enabled: bool = True) -> None:
        mapping = _get_activation_map()
        mapping[self._activation_key(method_name, plugin_name)] = bool(enabled)

    def is_plugin_enabled(self, method_name: str, plugin_name: str) -> bool:
        mapping = _get_activation_map()
        value = mapping.get(self._activation_key(method_name, plugin_name))
        if value is None:
            return True
        return bool(value)

    def _runtime_key(self, method_name: str, plugin_name: str) -> Tuple[int, str, str]:
        return (id(self.instance), method_name, plugin_name)

    def set_runtime_data(self, method_name: str, plugin_name: str, key: str, value: Any) -> None:
        mapping = _get_runtime_map()
        slot = mapping.setdefault(self._runtime_key(method_name, plugin_name), {})
        slot[key] = value

    def get_runtime_data(
        self, method_name: str, plugin_name: str, key: str, default: Any = None
    ) -> Any:
        mapping = _get_runtime_map()
        slot = mapping.get(self._runtime_key(method_name, plugin_name), {})
        return slot.get(key, default)

    # ------------------------------------------------------------------
    # Handler execution
    # ------------------------------------------------------------------
    def _rebuild_handlers(self) -> None:
        handlers: Dict[str, Callable] = {}
        for logical_name, entry in self._entries.items():
            wrapped = entry.func
            for plugin in reversed(self._plugins):
                wrapped = self._wrap_with_plugin(plugin, entry, wrapped)
            handlers[logical_name] = wrapped
        self._handlers = handlers

    def _wrap_with_plugin(
        self, plugin: BasePlugin, entry: MethodEntry, call_next: Callable
    ) -> Callable:
        wrapped_call = plugin.wrap_handler(self, entry, call_next)

        @wraps(call_next)
        def layer(*args, **kwargs):
            if not self.is_plugin_enabled(entry.name, plugin.name):
                return call_next(*args, **kwargs)
            return wrapped_call(*args, **kwargs)

        return layer

    def _apply_plugin_to_entries(self, plugin: BasePlugin) -> None:
        for entry in self._entries.values():
            if plugin.name not in entry.plugins:
                entry.plugins.append(plugin.name)
            plugin.on_decore(self, entry.func, entry)

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

    def iter_plugins(self) -> List[BasePlugin]:
        return list(self._plugins)

    def __getattr__(self, name: str) -> Any:
        plugin = self._plugins_by_name.get(name)
        if plugin is None:
            raise AttributeError(f"No plugin named '{name}' attached to router '{self.name}'")
        return plugin

    # ------------------------------------------------------------------
    # Children management
    # ------------------------------------------------------------------
    def add_child(self, child: Any, name: Optional[str] = None) -> "Router":
        if isinstance(child, str):
            tokens = [token.strip() for token in child.split(",") if token.strip()]
            if not tokens:
                return self
            if name and len(tokens) > 1:
                raise ValueError("Explicit name cannot be combined with multiple attribute targets")
            attached: Optional[Router] = None
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
        attached: Optional[Router] = None
        for attr_name, router in candidates:
            key = name or attr_name or router.name or "child"
            if key in self._children and self._children[key] is not router:
                raise ValueError(f"Child name collision: {key}")
            self._children[key] = router
            router._inherit_plugins_from(self)
            attached = router
        assert attached is not None
        return attached

    def get_child(self, name: str) -> "Router":
        try:
            return self._children[name]
        except KeyError:
            raise KeyError(f"No child route named {name!r}")

    def _inherit_plugins_from(self, parent: "Router") -> None:
        parent_id = id(parent)
        if parent_id in self._inherited_from:
            return
        self._inherited_from.add(parent_id)
        parent_specs = [spec.clone() for spec in parent._plugin_specs]
        if not parent_specs:
            return
        new_plugins = [spec.instantiate() for spec in parent_specs]
        self._plugin_specs = parent_specs + self._plugin_specs
        self._plugins = new_plugins + self._plugins
        for plugin in new_plugins:
            self._plugins_by_name.setdefault(plugin.name, plugin)
            self._apply_plugin_to_entries(plugin)
        self._rebuild_handlers()

    def _iter_child_routers(
        self, source: Any, seen: Optional[set[int]] = None, override_name: Optional[str] = None
    ) -> Iterator[Tuple[str, "Router"]]:
        if isinstance(source, Router):
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

        router_items: List[Tuple[str, Router]] = []
        for attr_name, value in self._iter_instance_attributes(source):
            if value is None or value is source:
                continue
            if isinstance(value, Router):
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
    def _resolve_path(self, selector: str) -> Tuple["Router", str]:
        if "." not in selector:
            return self, selector
        node: Router = self
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

        def describe_node(node: "Router") -> Dict[str, Any]:
            scope_plugin = getattr(node, "_plugins_by_name", {}).get("scope")

            return {
                "name": node.name,
                "prefix": node.prefix,
                "plugins": [p.name for p in node.iter_plugins()],
                "methods": _describe_methods(node, scope_plugin),
                "children": _describe_children(node),
            }

        def _describe_methods(node: "Router", scope_plugin: Optional[BasePlugin]):
            methods: Dict[str, Any] = {}
            for name, entry in node._entries.items():
                method_info = _build_method_description(entry, scope_plugin)
                if filter_active and not _method_matches_filters(
                    method_info, scope_filter, channel_filter
                ):
                    continue
                methods[name] = method_info
            return methods

        def _describe_children(node: "Router") -> Dict[str, Any]:
            children: Dict[str, Any] = {}
            for key, child in node._children.items():
                payload = describe_node(child)
                if not filter_active or payload["methods"] or payload["children"]:
                    children[key] = payload
            return children

        def _build_method_description(
            entry: MethodEntry, scope_plugin: Optional[BasePlugin]
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

        def _method_matches_filters(
            method_info: Dict[str, Any],
            scope_filter: Optional[set[str]],
            channel_filter: Optional[str],
        ) -> bool:
            scope_meta = method_info.get("scope")
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

        return describe_node(self)

    def members(self, scopes: Optional[Any] = None, channel: Optional[str] = None) -> Dict[str, Any]:
        scope_filter = self._normalize_scope_filter(scopes)
        channel_filter = self._normalize_channel_filter(channel)
        filter_active = bool(scope_filter or channel_filter)

        def capture(node: "Router") -> Dict[str, Any]:
            handlers = {}
            for name, entry in node._entries.items():
                if filter_active and not _entry_matches(entry, scope_filter, channel_filter):
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

        def _entry_matches(
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
                channel_map = scope_meta.get("channels", {})
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

        return capture(self)

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
                raise ValueError(
                    f"channel must be uppercase (got '{normalized}')"
                )
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
