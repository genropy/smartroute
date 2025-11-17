"""Router descriptors and bound router instances."""

from __future__ import annotations

import contextvars
import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type

from smartseeds import SmartOptions

from .base import BasePlugin, MethodEntry

__all__ = ["RouteSpec", "Router"]

_ACTIVATION_CTX: contextvars.ContextVar[Dict[Any, bool] | None] = contextvars.ContextVar(
    "smartroute_activation", default=None
)
_RUNTIME_CTX: contextvars.ContextVar[Dict[Any, Dict[str, Any]] | None] = contextvars.ContextVar(
    "smartroute_runtime", default=None
)
_BOUND_ATTR = "__smartroute_bound_routers__"
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
class RouteSpec:
    """Metadata collected during decoration time."""

    func: Callable
    alias: Optional[str]


@dataclass
class _PluginSpec:
    factory: Type[BasePlugin]
    kwargs: Dict[str, Any]

    def instantiate(self) -> BasePlugin:
        return self.factory(**self.kwargs)

    def clone(self) -> "_PluginSpec":
        return _PluginSpec(self.factory, dict(self.kwargs))


class Router:
    """
    Descriptor-style router used as decorator on instance methods.

    Example::

        class UsersAPI:
            routes = Router(prefix="handle_")

            @routes
            def handle_list(self): ...
    """

    def __init__(
        self,
        name: Optional[str] = None,
        prefix: Optional[str] = None,
        *,
        get_default_handler: Optional[Callable] = None,
        get_use_smartasync: Optional[bool] = None,
        get_kwargs: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.prefix = prefix or ""
        self._specs: list[RouteSpec] = []
        self._attr_name: Optional[str] = None
        self._plugin_specs: List[_PluginSpec] = []
        defaults: Dict[str, Any] = dict(get_kwargs or {})
        if get_default_handler is not None:
            defaults.setdefault("default_handler", get_default_handler)
        if get_use_smartasync is not None:
            defaults.setdefault("use_smartasync", get_use_smartasync)
        self._get_defaults: Dict[str, Any] = defaults

    # -----------------------------------------------------
    # Descriptor protocol
    # -----------------------------------------------------
    def __set_name__(self, owner: type, name: str) -> None:
        if self.name is None:
            self.name = name
        self._attr_name = name

    def __get__(self, instance: Any, owner: type | None = None):
        if instance is None:
            return self
        registry = self._get_instance_registry(instance)
        bound = registry.get(self)
        if bound is None:
            bound = BoundRouter(self, instance)
            registry[self] = bound
        return bound

    @staticmethod
    def _get_instance_registry(instance: Any) -> Dict["Router", "BoundRouter"]:
        registry = getattr(instance, _BOUND_ATTR, None)
        if registry is None:
            registry = {}
            setattr(instance, _BOUND_ATTR, registry)
        return registry

    # -----------------------------------------------------
    # Decorator interface
    # -----------------------------------------------------
    def __call__(self, arg: Any = None):
        if callable(arg) and not isinstance(arg, str):
            return self._register(arg, alias=None)
        if isinstance(arg, str):
            alias = arg

            def decorator(func: Callable) -> Callable:
                return self._register(func, alias=alias)

            return decorator
        raise TypeError("@Router decorator expects a function or alias string")

    def _register(self, func: Callable, alias: Optional[str]) -> Callable:
        self._specs.append(RouteSpec(func=func, alias=alias))
        return func

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
        """Register a plugin by name. Plugin must be registered first with Router.register_plugin().

        IMPORTANT: Only string plugin names are accepted. Plugins must be pre-registered
        using Router.register_plugin() before they can be used with plug().

        Built-in plugins 'logging' and 'pydantic' are pre-registered and ready to use.

        Args:
            plugin: Plugin name (string). Must be registered via Router.register_plugin().
            **config: Optional configuration passed to plugin constructor.

        Returns:
            Self for chaining.

        Raises:
            ValueError: If plugin name is not registered.
            TypeError: If plugin is not a string.

        Example:
            >>> Router().plug("logging")
            >>> Router().plug("pydantic")
        """
        if not isinstance(plugin, str):
            raise TypeError(
                f"Plugin must be a string (plugin name), got {type(plugin).__name__}. "
                "Register custom plugins with Router.register_plugin() first, "
                "then reference them by name string."
            )

        plugin_class = _PLUGIN_REGISTRY.get(plugin)
        if plugin_class is None:
            available = ", ".join(sorted(_PLUGIN_REGISTRY)) or "none"
            raise ValueError(
                f"Unknown plugin '{plugin}'. Register it with Router.register_plugin(). "
                f"Available plugins: {available}"
            )

        spec = _PluginSpec(plugin_class, dict(config))
        self._plugin_specs.append(spec)
        return self


class BoundRouter:
    """Router bound to a specific object instance."""

    def __init__(self, blueprint: Router, instance: Any):
        self._blueprint = blueprint
        self._instance = instance
        self.name = blueprint.name
        self.prefix = blueprint.prefix
        self._get_defaults: Dict[str, Any] = dict(blueprint._get_defaults)
        self._handlers: Dict[str, Callable] = {}
        self._children: Dict[str, BoundRouter] = {}
        self._plugin_specs = list(blueprint._plugin_specs)
        self._plugins: List[BasePlugin] = [spec.instantiate() for spec in self._plugin_specs]
        self._plugins_by_name: Dict[str, BasePlugin] = {p.name: p for p in self._plugins}
        self._entries: Dict[str, MethodEntry] = {}
        self._inherited_from: set[int] = set()
        self._build_entries()
        for plugin in self._plugins:
            self._apply_plugin(plugin)
        self._rebuild_handlers()

    # -----------------------------------------------------
    # Plugin activation & runtime data helpers
    # -----------------------------------------------------
    def _activation_key(self, method_name: str, plugin_name: str) -> Tuple[int, str, str]:
        return (id(self._instance), method_name, plugin_name)

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
        return (id(self._instance), method_name, plugin_name)

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

    # -----------------------------------------------------
    # Handler registration / rebuild
    # -----------------------------------------------------
    def _build_entries(self) -> None:
        entries: Dict[str, MethodEntry] = {}
        for spec in self._blueprint._specs:
            logical_name = self._resolve_name(spec)
            if logical_name in entries:
                raise ValueError(f"Handler name collision: {logical_name}")
            bound_method = spec.func.__get__(self._instance, type(self._instance))
            entry = MethodEntry(
                name=logical_name,
                func=bound_method,
                router=self,
                plugins=[p.name for p in self._plugins],
            )
            entries[logical_name] = entry
        self._entries = entries

    def _apply_plugin(self, plugin: BasePlugin) -> None:
        for entry in self._entries.values():
            plugin.on_decore(self, entry.func, entry)

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

    def _resolve_name(self, spec: RouteSpec) -> str:
        if spec.alias:
            return spec.alias
        func_name = spec.func.__name__
        if self.prefix and func_name.startswith(self.prefix):
            return func_name[len(self.prefix) :]
        return func_name

    # -----------------------------------------------------
    # Public API
    # -----------------------------------------------------
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
            # Local import to avoid hard dependency if smartasync not installed
            from smartasync import smartasync  # type: ignore

            handler = smartasync(handler)

        return handler

    __getitem__ = get

    def entries(self) -> Tuple[str, ...]:
        """Return tuple of local handler names."""
        return tuple(self._handlers.keys())

    def iter_plugins(self) -> List[BasePlugin]:
        return list(self._plugins)

    def __getattr__(self, name: str) -> Any:
        plugin = self._plugins_by_name.get(name)
        if plugin is None:
            raise AttributeError(f"No plugin named '{name}' attached to router '{self.name}'")
        return plugin

    def _inherit_plugins_from(self, parent: "BoundRouter") -> None:
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
            self._apply_plugin(plugin)
        self._rebuild_handlers()

    # -----------------------------------------------------
    # Children management
    # -----------------------------------------------------
    def add_child(self, child: Any, name: Optional[str] = None) -> BoundRouter:
        candidates = list(self._iter_child_routers(child))
        if not candidates:
            raise TypeError(f"Object {child!r} does not expose Router descriptors")
        attached: BoundRouter | None = None
        for attr_name, bound_router in candidates:
            key = name or attr_name or bound_router.name
            if key in self._children and self._children[key] is not bound_router:
                raise ValueError(f"Child name collision: {key}")
            self._children[key] = bound_router
            bound_router._inherit_plugins_from(self)
            attached = bound_router
        assert attached is not None
        return attached

    def get_child(self, name: str) -> BoundRouter:
        try:
            return self._children[name]
        except KeyError:
            raise KeyError(f"No child route named {name!r}")

    def _iter_child_routers(
        self, source: Any, seen: Optional[set[int]] = None, override_name: Optional[str] = None
    ) -> Iterator[Tuple[str, BoundRouter]]:
        if isinstance(source, BoundRouter):
            yield override_name or source.name or "child", source
            return
        if isinstance(source, Router):
            raise TypeError("Pass an object instance, not the Router descriptor")
        if seen is None:
            seen = set()
        obj_id = id(source)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if isinstance(source, Mapping):
            for key, value in source.items():
                key_hint = key if isinstance(key, str) else None
                yield from self._iter_child_routers(value, seen, key_hint)
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

        names_and_bounds: List[Tuple[str, BoundRouter]] = []
        cls = type(source)
        for attr_name, value in vars(cls).items():
            if isinstance(value, Router):
                bound = value.__get__(source, cls)
                names_and_bounds.append((attr_name, bound))

        inst_dict = getattr(source, "__dict__", None)
        if inst_dict:
            for attr_name, value in inst_dict.items():
                if value is None or value is source:
                    continue
                if attr_name == _BOUND_ATTR:
                    continue
                if isinstance(value, BoundRouter):
                    names_and_bounds.append((attr_name, value))
                    continue
                yield from self._iter_child_routers(value, seen, None)

        if not names_and_bounds:
            return

        if override_name and len(names_and_bounds) == 1:
            yield (override_name, names_and_bounds[0][1])
            return

        yielded: set[str] = set()
        for attr_name, bound in names_and_bounds:
            key = attr_name or bound.name or "child"
            if key in yielded:
                continue
            yielded.add(key)
            yield (key, bound)

    # -----------------------------------------------------
    # Path resolution
    # -----------------------------------------------------
    def _resolve_path(self, selector: str) -> Tuple["BoundRouter", str]:
        if "." not in selector:
            return self, selector
        node: BoundRouter = self
        parts = selector.split(".")
        for segment in parts[:-1]:
            node = node.get_child(segment)
        return node, parts[-1]

    # -----------------------------------------------------
    # Hierarchical callable accessor
    # -----------------------------------------------------
    def call(self, selector: str, *args, **kwargs):
        handler = self.get(selector)
        return handler(*args, **kwargs)

    def describe(self) -> Dict[str, Any]:
        def describe_node(node: "BoundRouter") -> Dict[str, Any]:
            return {
                "name": node.name,
                "prefix": node.prefix,
                "plugins": [p.name for p in node.iter_plugins()],
                "methods": {
                    name: _build_method_description(entry) for name, entry in node._entries.items()
                },
                "children": {key: describe_node(child) for key, child in node._children.items()},
            }

        def _build_method_description(entry: MethodEntry) -> Dict[str, Any]:
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

            return method_info

        return describe_node(self)


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
