# SmartRoute - Complete API Reference

**Generated from test suite - 100% coverage**

## Core Classes

### Router

**Descriptor class for defining routers on classes.**

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

```python
class MyClass(RoutedClass):
    api = Router(
        name="optional_name",           # Router name (optional)
        prefix="handle_",               # Strip this prefix from method names
        get_default_handler=None,       # Callable returning default handler
        get_use_smartasync=False        # Enable smartasync by default
    )
```

**Parameters:**

- `name` (str, optional): Router identifier
- `prefix` (str, optional): Prefix to strip from decorated method names
- `get_default_handler` (callable, optional): Function returning default handler when route not found
- `get_use_smartasync` (bool, optional): Enable smartasync wrapping by default

**Methods:**

#### `Router.plug(plugin: str, **config) -> Router`

Add a plugin to the router by name. Plugins must be pre-registered with `Router.register_plugin()`. Built-in plugins (`"logging"`, `"pydantic"`) are pre-registered. Returns self for chaining.

<!-- test: test_router_edge_cases.py::test_router_decorator_and_plugin_validation -->

```python
# Built-in plugins are pre-registered
api = Router().plug("logging")
api = Router().plug("pydantic")

# Custom plugins must be registered first
Router.register_plugin("custom", CustomPlugin)
api = Router().plug("custom")
```

#### `Router.register_plugin(name: str, plugin_class: Type[BasePlugin]) -> None`

**Class method.** Register a plugin globally by name.

<!-- test: test_router_edge_cases.py::test_register_plugin_validates -->

```python
Router.register_plugin("custom", CustomPlugin)
# Now can use: Router().plug("custom")
```

#### `Router.available_plugins() -> list[str]`

**Class method.** List all registered plugin names.

<!-- test: test_router_edge_cases.py::test_builtin_plugins_registered -->

```python
plugins = Router.available_plugins()  # ["logging", "pydantic"]
```

---

### BoundRouter

**Runtime instance of a router, bound to an object.**

Obtained by accessing router descriptor on instance:

```python
svc = Service()
bound = svc.api  # BoundRouter instance
```

**Methods:**

#### `get(name: str, *, default_handler=None, use_smartasync=None) -> Callable`

Retrieve handler by name.

<!-- test: test_switcher_basic.py::test_get_with_default_returns_callable -->

```python
handler = bound.get("method_name")
result = handler(arg1, arg2)

# With default
handler = bound.get("missing", default_handler=lambda: "default")

# With smartasync
handler = bound.get("method", use_smartasync=True)
```

**Parameters:**

- `name` (str): Handler name or dotted path ("child.method")
- `default_handler` (callable, optional): Fallback if handler not found
- `use_smartasync` (bool, optional): Wrap with smartasync (overrides router default)

**Returns:** Callable handler

**Raises:**
- `NotImplementedError` if handler not found and no default

#### `call(name: str, *args, **kwargs) -> Any`

Get and immediately call handler.

```python
result = bound.call("method", arg1, arg2, key=value)
# Equivalent to: bound.get("method")(arg1, arg2, key=value)
```

#### `entries() -> set[str]`

Get all registered handler names.

<!-- test: test_switcher_basic.py::test_prefix_and_alias_resolution -->

```python
names = bound.entries()  # {"method1", "method2", "alias"}
```

#### `add_child(child, *, name: str = None) -> BoundRouter`

Attach a child router or object with routers.

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->
<!-- test: test_switcher_basic.py::test_add_child_accepts_mapping_for_named_children -->

**Single child:**
```python
bound.add_child(child_obj, name="child_name")
# Access: bound.get("child_name.method")
```

**Mapping:**
```python
bound.add_child({"users": users_svc, "products": prod_svc})
# Access: bound.get("users.method")
```

**Nested iterables:**
```python
bound.add_child([
    {"users": users_svc},
    [("products", prod_svc)]
])
```

**Parameters:**

- `child`: Object with router, BoundRouter, or dict/list of children
- `name` (str, optional): Name for single child

**Returns:** BoundRouter of child

**Raises:**

- `TypeError` if child is not valid type
- `ValueError` if child name already exists
- `KeyError` from `get_child()` if child not found

#### `get_child(name: str) -> BoundRouter`

Get child router by name.

<!-- test: test_router_edge_cases.py::test_router_add_child_error_paths -->

```python
child = bound.get_child("child_name")
```

#### `iter_plugins() -> list[BasePlugin]`

Get list of active plugins.

<!-- test: test_router_edge_cases.py::test_iter_plugins_and_missing_attribute -->

```python
plugins = bound.iter_plugins()
for plugin in plugins:
    print(plugin.name)
```

#### `set_plugin_enabled(handler_name: str, plugin_name: str, enabled: bool) -> None`

Enable or disable plugin for specific handler.

<!-- test: test_switcher_basic.py::test_plugin_enable_disable_runtime_data -->

```python
bound.set_plugin_enabled("method", "logging", False)
```

#### `set_runtime_data(handler_name: str, plugin_name: str, key: str, value: Any) -> None`

Set runtime data for plugin on handler.

```python
bound.set_runtime_data("method", "plugin", "config", {"opt": 1})
```

#### `get_runtime_data(handler_name: str, plugin_name: str, key: str) -> Any`

Get runtime data for plugin on handler.

```python
value = bound.get_runtime_data("method", "plugin", "config")
```

**Plugin access:**

Plugins attached to router are accessible as attributes:

```python
api = Router().plug("logging")
svc = Service()
svc.api.logger  # Access LoggingPlugin instance
```

---

### RoutedClass

**Mixin that finalizes routers on class.**

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

```python
class Service(RoutedClass):
    api = Router()

    @route("api")
    def method(self):
        return "ok"
```

Automatically processes all `Router` descriptors when class is defined.

---

## Decorators

### @route(router_name: str, *, alias: str = None)

Register instance method with router.

<!-- test: test_switcher_basic.py::test_prefix_and_alias_resolution -->

**Basic:**
```python
@route("api")
def method_name(self):
    pass
# Registered as "method_name"
```

**With alias:**
```python
@route("api", alias="short")
def long_method_name(self):
    pass
# Registered as "short"
```

**With prefix:**
```python
class Service(RoutedClass):
    api = Router(prefix="handle_")

    @route("api")
    def handle_list(self):
        pass
# Registered as "list" (prefix stripped)
```

---

### @routers(*router_names: str)

Class decorator to finalize routers (alternative to `RoutedClass`).

<!-- test: test_router_edge_cases.py::test_routers_decorator_idempotent -->

```python
@routers("api", "admin")
class Service:
    api = Router()
    admin = Router()

    @route("api")
    def public(self): pass

    @route("admin")
    def restricted(self): pass
```

---

## Plugin API

### BasePlugin

**Base class for creating plugins.**

<!-- test: test_router_edge_cases.py::test_base_plugin_default_hooks -->

```python
from smartroute import BasePlugin

class CustomPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="custom")

    def on_decore(self, router, func, entry):
        """Called when handler is registered."""
        entry.metadata["custom"] = True

    def wrap_handler(self, router, entry, call_next):
        """Wrap handler execution."""
        def wrapper(*args, **kwargs):
            print(f"Calling {entry.name}")
            return call_next(*args, **kwargs)
        return wrapper
```

**Methods to Override:**

#### `on_decore(router: BoundRouter, func: Callable, entry: MethodEntry) -> None`

Called during handler registration. Modify `entry.metadata` to store config.

**Parameters:**

- `router`: BoundRouter being decorated
- `func`: Original method being registered
- `entry`: MethodEntry with metadata

#### `wrap_handler(router: BoundRouter, entry: MethodEntry, call_next: Callable) -> Callable`

Wrap handler execution.

**Parameters:**

- `router`: BoundRouter
- `entry`: MethodEntry with metadata
- `call_next`: Next handler in chain (call this!)

**Returns:** Wrapped callable

---

### MethodEntry

**Handler metadata container.**

```python
class MethodEntry:
    name: str                    # Handler name
    func: Callable               # Original method
    router: BoundRouter | None   # Parent router
    plugins: list[BasePlugin]    # Active plugins
    metadata: dict[str, Any]     # Plugin metadata
```

Access in plugins:

```python
def on_decore(self, router, func, entry):
    entry.metadata[self.name] = {"config": True}
```

---

## Built-in Plugins

### LoggingPlugin

Logs handler calls. Pre-registered as `"logging"`.

<!-- test: test_plugins_new.py::test_logging_plugin_runs_per_instance -->

```python
api = Router().plug("logging")
```

**Access logger:**

```python
svc.api.logger._logger  # Python logger instance
```

---

### PydanticPlugin

Validates arguments using type hints. Pre-registered as `"pydantic"`.

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

```python
api = Router().plug("pydantic")

@route("api")
def validate(self, text: str, number: int = 1) -> str:
    return f"{text}:{number}"

# Valid
svc.api.get("validate")("hello", 3)  # "hello:3"

# Invalid - raises ValidationError
svc.api.get("validate")(123, "oops")
```

Requires `pydantic` installed: `pip install smartroute[pydantic]`

---

## Edge Cases & Validation

### Handler Name Collisions

<!-- test: test_router_edge_cases.py::test_router_detects_handler_name_collision -->

Raises `ValueError` if two handlers register same name:

```python
class Service(RoutedClass):
    api = Router()

    @route("api", alias="dup")
    def first(self): pass

    @route("api", alias="dup")  # ERROR!
    def second(self): pass
```

### Invalid add_child Types

<!-- test: test_router_edge_cases.py::test_router_add_child_error_paths -->

```python
# TypeError: Router descriptor not allowed
bound.add_child(Service.api)

# ValueError: Name already exists
bound.add_child(child1, name="x")
bound.add_child(child2, name="x")  # ERROR!

# KeyError: Child not found
bound.get_child("missing")  # ERROR!
```

### Plugin Registration Validation

<!-- test: test_router_edge_cases.py::test_register_plugin_validates -->

```python
# TypeError: Not a BasePlugin subclass
Router.register_plugin("bad", object)

# ValueError: Name already registered with different class
Router.register_plugin("exists", PluginA)
Router.register_plugin("exists", PluginB)  # ERROR!
```

---

## Instance Isolation

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

Each instance has completely isolated state:

```python
first = Service("alpha")
second = Service("beta")

# Different handlers
assert first.api.get("method") != second.api.get("method")

# Independent plugin state
first.api.get("method")()  # Plugin affects only first
second.api.get("method")()  # Independent state
```

---

## Plugin Inheritance

<!-- test: test_switcher_basic.py::test_parent_plugins_inherit_to_children -->

Child routers inherit parent plugins automatically:

```python
class Parent(RoutedClass):
    api = Router().plug("logging")

parent = Parent()
child = ChildService()
parent.api.add_child(child, name="child")

# Child router now has LoggingPlugin
child.routes.logger  # Inherited plugin
```

---

## Nested Child Discovery

<!-- test: test_switcher_basic.py::test_nested_child_discovery -->

Routers scan objects recursively for child routers:

```python
class NestedLeaf(RoutedClass):
    leaf = Router()

class NestedBranch:
    def __init__(self):
        self.child_leaf = NestedLeaf()

class Root(RoutedClass):
    api = Router()

    def __init__(self):
        self.branch = NestedBranch()
        self.api.add_child(self.branch)

root = Root()
root.api.get("leaf.method")()  # Finds through branch.child_leaf
```

---

## Complete Example

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->

```python
from smartroute import RoutedClass, Router, route

class SubService(RoutedClass):
    routes = Router(prefix="handle_").plug("logging")

    def __init__(self, prefix: str):
        self.prefix = prefix

    @route("routes")
    def handle_list(self):
        return f"{self.prefix}:list"

    @route("routes", alias="detail")
    def handle_detail(self, ident: int):
        return f"{self.prefix}:detail:{ident}"

class RootAPI(RoutedClass):
    api = Router()

    def __init__(self):
        self.users = SubService("users")
        self.products = SubService("products")
        self.api.add_child({
            "users": self.users,
            "products": self.products
        })

root = RootAPI()

# Direct access
assert root.users.routes.get("list")() == "users:list"

# Hierarchical access
assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(5) == "products:detail:5"

# Plugin is active (logging occurs)
```

---

## Testing

All examples verified by test suite:

- `tests/test_switcher_basic.py` - Core functionality
- `tests/test_router_edge_cases.py` - Edge cases and validation
- `tests/test_plugins_new.py` - Plugin system
- `tests/test_pydantic_plugin.py` - Pydantic validation

Coverage: >95% statement coverage
