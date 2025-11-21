# SmartRoute - Complete API Reference

**Generated from test suite - 100% coverage**

## Core Classes

### Router

**Instance-scoped router class for dynamic method dispatch.**

Router is instantiated in `__init__` with the owner instance as first parameter. Each instance gets its own isolated router.

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

```python
class Service(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(
            self,                           # Owner instance (required)
            name="api",                     # Router name (optional)
            prefix="handle_",               # Strip this prefix from method names
            auto_discover=True              # Auto-register @route methods
        )

    @route("api")
    def describe(self):
        return f"service:{self.label}"

# Each instance is isolated
first = Service("alpha")
second = Service("beta")

assert first.api.get("describe")() == "service:alpha"
assert second.api.get("describe")() == "service:beta"
```

**Parameters:**

- `owner` (object): Owner instance (required first parameter)
- `name` (str, optional): Router identifier for `@route("name")` matching
- `prefix` (str, optional): Prefix to strip from decorated method names
- `auto_discover` (bool, optional): Automatically register `@route` methods (default: True)

**Key differences from descriptor pattern:**

- Router is instantiated in `__init__`, not as class attribute
- First parameter is always `self` (the owner instance)
- Each instance has independent routing state and plugins
- No separate "BoundRouter" - there's only Router

**Class Methods:**

#### `Router.plug(plugin: str) -> Router`

Add a plugin to the router by name. Plugins must be pre-registered with `Router.register_plugin()`. Built-in plugins (`"logging"`, `"pydantic"`) are pre-registered. Returns self for chaining.

<!-- test: test_router_edge_cases.py::test_builtin_plugins_registered -->

```python
class Service(RoutedClass):
    def __init__(self):
        # Built-in plugins are pre-registered
        self.api = Router(self, name="api").plug("logging")
        # Chain multiple plugins
        self.admin = Router(self, name="admin")\
            .plug("logging")\
            .plug("pydantic")
```

Custom plugins must be registered first:

```python
# Register once globally
Router.register_plugin("custom", CustomPlugin)

# Then use in any router
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("custom")
```

#### `Router.register_plugin(name: str, plugin_class: Type[BasePlugin]) -> None`

**Class method.** Register a plugin globally by name for use with `.plug()`.

<!-- test: test_router_edge_cases.py::test_register_plugin_validates -->

```python
Router.register_plugin("custom", CustomPlugin)
# Now available: Router(self, name="api").plug("custom")
```

**Validation:**

- `plugin_class` must be a BasePlugin subclass
- Cannot re-register same name with different class
- Name must be non-empty string

#### `Router.available_plugins() -> list[str]`

**Class method.** List all registered plugin names.

<!-- test: test_router_edge_cases.py::test_builtin_plugins_registered -->

```python
plugins = Router.available_plugins()
# Returns: ["logging", "pydantic", ...custom plugins...]
```

---

### Router Instance Methods

Once instantiated, Router provides these methods:

#### `get(name: str, *, default=None, use_smartasync=None) -> Callable`

Retrieve handler by name or dotted path.

<!-- test: test_switcher_basic.py::test_get_with_default_returns_callable -->

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def action(self, value: str):
        return f"result:{value}"

svc = Service()

# Get handler
handler = svc.api.get("action")
result = handler("test")  # "result:test"

# With default fallback
def fallback():
    return "default"

handler = svc.api.get("missing", default=fallback)
result = handler()  # "default"

# With smartasync
handler = svc.api.get("action", use_smartasync=True)
```

**Parameters:**

- `name` (str): Handler name or dotted path for child routers ("child.method")
- `default` (callable, optional): Fallback if handler not found (parameter renamed from `default_handler`)
- `use_smartasync` (bool, optional): Wrap with smartasync

**Returns:** Callable handler

**Raises:**

- `KeyError` if handler not found and no default provided

#### `call(name: str, *args, **kwargs) -> Any`

Get and immediately invoke handler.

<!-- test: test_router_runtime_extras.py::test_router_call_and_members_structure -->

```python
result = svc.api.call("action", "value", flag=True)
# Equivalent to: svc.api.get("action")("value", flag=True)
```

**Convenience method** for one-line handler invocation.

#### `members(scopes: Optional[Union[str, Iterable[str]]] = None, channel: Optional[str] = None) -> Dict[str, Any]`

Get structured information sul router. Pass `scopes` (string CSV o iterabile) per filtrare sugli scope dichiarati dagli handler; passa `channel` per includere solo gli handler i cui scope permettono quel codice canale (quando un plugin come `PublishPlugin` fornisce quei metadati).

<!-- test: test_router_runtime_extras.py::test_router_call_and_members_structure -->

```python
tree = svc.api.members()
first_handler = tree["handlers"]["action"]

# Scope/channel filters require a plugin (e.g. PublishPlugin) to populate metadata
internal_only = svc.api.members(scopes="internal,admin")
cli_only = svc.api.members(channel="CLI")
internal_cli = svc.api.members(scopes="internal", channel="CLI")
```

**Returns:** Dictionary with router metadata + `handlers`/`children` sections (recursive).

#### `describe(scopes: Optional[Union[str, Iterable[str]]] = None, channel: Optional[str] = None) -> Dict[str, Any]`

Get complete descrizione gerarchica (router, plugin, handlers, metadata). Con `scopes` e/o `channel` puoi limitare l’output agli handler che hanno quei tag/canali (stessa logica di `members`) quando un plugin ha arricchito i metadati con questi attributi.

<!-- test: test_switcher_basic.py::test_describe_returns_hierarchy -->

```python
description = svc.api.describe()
# Returns:
# {
#   "name": "api",
#   "plugins": [
#     {"name": "logging", "description": "...", "config": {...}}
#   ],
#   "handlers": ["action", "other"],
#   "children": {
#     "child_name": {...nested description...}
#   }
# }
filtered = svc.api.describe(scopes="internal", channel="CLI")
```

**Returns:** Dictionary with:

- `name` - Router name
- `plugins` - List of plugin info (name, description, config)
- `handlers` - List of handler names
- `children` - Dict of child router descriptions (recursive)

#### `add_child(child, *, name: str = None) -> Router`

Attach child router(s) for hierarchical organization. Plugins propagate automatically to children.

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->
<!-- test: test_switcher_basic.py::test_add_child_accepts_mapping_for_named_children -->

**Single child:**

```python
class RootAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        child = ChildService()
        self.api.add_child(child, name="child")

root = RootAPI()
root.api.get("child.method")()  # Dotted path access
```

**Multiple children (dict):**

```python
self.api.add_child({
    "users": users_service,
    "products": products_service
})

# Access: self.api.get("users.list")
```

**Nested iterables:**

```python
registry = [
    {"users": users_service},
    [("products", products_service)]
]
self.api.add_child(registry)
```

**Plugin inheritance:**

<!-- test: test_switcher_basic.py::test_parent_plugins_inherit_to_children -->

```python
class Parent(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

parent = Parent()
child = ChildService()
parent.api.add_child(child, name="child")

# Child router now has logging plugin automatically
assert hasattr(child.routes, "logging")
```

#### `get_child(name: str) -> Router`

Get child router by name.

```python
child_router = parent.api.get_child("users")
# Returns the router from users_service
```

**Raises:** `KeyError` if child not found

#### `iter_plugins() -> Iterator[BasePlugin]`

Iterate over all plugins attached to this router.

```python
for plugin in svc.api.iter_plugins():
    print(plugin.name)
```

---

### Plugin Configuration

#### `set_plugin_enabled(handler_name: str, plugin_name: str, enabled: bool = True) -> None`

Enable/disable plugin for specific handler.

**Note:** Prefer using `routedclass.configure()` for plugin configuration (see RoutedClass section).

```python
# Direct method (old style)
svc.api.set_plugin_enabled("method_name", "logging", False)

# Preferred: routedclass.configure()
svc.routedclass.configure("api:logging/method_name", enabled=False)
```

#### `set_runtime_data(handler_name: str, plugin_name: str, key: str, value: Any) -> None`

Store runtime data for handler/plugin combination.

<!-- test: test_switcher_basic.py::test_plugin_enable_disable_runtime_data -->

```python
svc.api.set_runtime_data("method", "plugin", "count", 42)
```

**Use for:** Temporary data during handler execution, debugging, metrics.

#### `get_runtime_data(handler_name: str, plugin_name: str, key: str, default: Any = None) -> Any`

Retrieve runtime data.

```python
count = svc.api.get_runtime_data("method", "plugin", "count", default=0)
```

---

### RoutedClass

**Mixin providing helper methods for router management.**

Classes using routers should inherit from `RoutedClass` to enable:

- Automatic router registration
- `routedclass` proxy for configuration
- Router discovery and introspection

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")  # Auto-registered

    @route("api")
    def method(self):
        pass
```

**Key feature:** The `routedclass` property provides helper methods without polluting instance namespace.

#### `routedclass.get_router(name: str, path: str = None) -> Router`

Get router by name with optional dotted path traversal.

<!-- test: test_router_edge_cases.py::test_routed_proxy_get_router_handles_dotted_path -->

```python
# Get top-level router
router = svc.routedclass.get_router("api")

# Get child router via dotted path
child_router = svc.routedclass.get_router("api.child")
# Or: svc.routedclass.get_router("api", path="child")
```

#### `routedclass.configure(target: str | dict | list, **options) -> dict`

**Primary method for plugin configuration.** Configure plugins at runtime with target syntax.

**Target syntax:** `<router>:<plugin>/<selector>`

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def foo(self): return "foo"

    @route("api")
    def bar(self): return "bar"

svc = Service()

# Global configuration - applies to ALL handlers
svc.routedclass.configure("api:logging/_all_", level="debug")

# Handler-specific configuration
svc.routedclass.configure("api:logging/foo", enabled=False)

# Glob pattern configuration
svc.routedclass.configure("api:logging/b*", level="info")

# Batch configuration
svc.routedclass.configure([
    {"target": "api:logging/_all_", "level": "info"},
    {"target": "api:logging/admin_*", "enabled": False}
])

# Introspection - query configuration tree
info = svc.routedclass.configure("?")
# Returns full router/plugin structure
```

**Target format:**

- `router_name` - Router to configure
- `plugin_name` - Plugin on that router
- `selector` - Handler selector:
  - `_all_` - All handlers (global config)
  - `handler_name` - Specific handler
  - `pattern*` - Glob pattern (fnmatch)
  - `h1,h2,h3` - Comma-separated list

**Parameters:**

- `target` (str, dict, or list) - Configuration target(s)
- `**options` - Configuration options (plugin-specific)

**Returns:** Dictionary with configuration result

**Special target `"?"`:** Returns complete router/plugin tree for introspection.

---

## Decorators

### @route(router_name: str, *, name: str = None, **kwargs)

Mark instance method for router registration.

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")  # Registered with method name
    def method_name(self):
        return "result"
```

**With explicit name:**

<!-- test: test_switcher_basic.py::test_prefix_and_name_override -->

```python
@route("api", name="short")
def long_method_name(self):
    pass

# Registered as "short" instead of deriving from method name
```

**With prefix stripping:**

```python
class Service(RoutedClass):
    def __init__(self):
        self.routes = Router(self, name="routes", prefix="handle_")

    @route("routes")
    def handle_list(self):  # Registered as "list"
        pass
```

**Parameters:**

- `router_name` (str): Name of router to register with (matches `Router(self, name="...")`)
- `name` (str, optional): Explicit handler name (overrides method name/prefix logic)
- `alias` (str, optional, deprecated): Backwards-compatible synonym for `name`
- `**kwargs`: Additional metadata stored in `MethodEntry.metadata`

### @routers(*router_names: str)

**Legacy decorator.** No longer required with new architecture.

```python
# Old style (no longer needed):
@routers("api", "admin")
class Service(RoutedClass):
    pass

# New style (automatic):
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        self.admin = Router(self, name="admin")
```

With new architecture, routers are registered automatically when instantiated in `__init__`. The `@routers` decorator is kept for backwards compatibility but has no effect.

---

## Plugin API

### BasePlugin

**Base class for creating custom plugins.**

Plugins hook into router lifecycle with two methods:

- `on_decore()` - Called when handler is registered
- `wrap_handler()` - Called when handler is invoked

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

```python
from smartroute.plugins._base import BasePlugin, MethodEntry

class CapturePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="capture")
        self.calls = []  # Per-instance state

    def on_decore(self, router, func, entry: MethodEntry):
        """Called during handler registration."""
        entry.metadata["captured"] = True

    def wrap_handler(self, router, entry: MethodEntry, call_next):
        """Called during handler invocation."""
        def wrapper(*args, **kwargs):
            self.calls.append(entry.name)
            return call_next(*args, **kwargs)
        return wrapper

# Register globally
Router.register_plugin("capture", CapturePlugin)

# Use in service
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("capture")

    @route("api")
    def action(self): return "ok"

svc = Service()
svc.api.get("action")()
assert svc.api.capture.calls == ["action"]
```

#### `on_decore(router: Router, func: Callable, entry: MethodEntry) -> None`

Called once when handler is registered. Modify metadata, validate signatures, build indexes.

**Parameters:**

- `router` - Router instance
- `func` - Original method
- `entry` - MethodEntry with name, func, metadata

#### `wrap_handler(router: Router, entry: MethodEntry, call_next: Callable) -> Callable`

Called every time handler is invoked. Return wrapper function for execution interception.

**Parameters:**

- `router` - Router instance
- `entry` - MethodEntry for handler
- `call_next` - Callable to invoke (next plugin or actual handler)

**Returns:** Wrapper function

**Pattern:**

```python
def wrap_handler(self, router, entry, call_next):
    def wrapper(*args, **kwargs):
        # Before handler
        self.log(f"Calling {entry.name}")

        # Invoke handler (or next plugin)
        result = call_next(*args, **kwargs)

        # After handler
        self.log(f"Result: {result}")

        return result
    return wrapper
```

### MethodEntry

**Container for handler metadata.**

Accessible in `on_decore()` and `wrap_handler()`.

**Attributes:**

- `name` (str) - Handler name (after prefix stripping)
- `func` (Callable) - Original method
- `metadata` (dict) - Custom metadata from `@route(**kwargs)`

**Example:**

```python
def on_decore(self, router, func, entry):
    print(f"Registering: {entry.name}")
    print(f"Metadata: {entry.metadata}")
```

---

## Built-in Plugins

### LoggingPlugin

Pre-registered as `"logging"`. Logs handler calls to configured logger.

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def action(self, value: str):
        return f"result:{value}"

svc = Service()
svc.api.get("action")("test")  # Logged automatically
```

**Configuration:**

```python
svc.routedclass.configure("api:logging/_all_", level="debug")
svc.routedclass.configure("api:logging/critical_*", level="error")
```

### PydanticPlugin

Pre-registered as `"pydantic"`. Validates arguments and return values using type hints.

Requires: `pip install smartroute[pydantic]`

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("pydantic")

    @route("api")
    def concat(self, text: str, number: int = 1) -> str:
        return f"{text}:{number}"

svc = Service()

# Valid inputs
svc.api.get("concat")("hello", 3)  # OK

# Invalid inputs raise ValidationError
try:
    svc.api.get("concat")(123, "invalid")  # ValidationError!
except Exception as e:
    print(f"Validation failed: {e}")
```

**Configuration:**

```python
svc.routedclass.configure("api:pydantic/_all_", strict=True)
```

### PublishPlugin (SmartPublisher)

Provided by `smartpublisher.smartroute_plugins.publish.PublishPlugin`. Importing the module registers the `"publish"` plugin name; attach it with `.plug("publish")`. It carries the scope/channel semantics (uppercase codes such as `CLI`, `SYS_HTTP`, `HTTP`, `WS`, `MCP`) formerly bundled in the core.

```python
from smartpublisher.smartroute_plugins.publish import PublishPlugin

class ScopedService(RoutedClass):
    def __init__(self):
        # import registers the plugin
        self.api = Router(self, name="api").plug("publish")

    @route("api", scopes="internal,admin")
    def admin(self):
        return "ok"

    @route("api", scopes="public_shop")
    def public(self):
        return "ok"

svc = ScopedService()
svc.routedclass.configure("api:publish/_all_", scopes="internal,sales")

# Retrieve handlers exposed via a specific channel
cli_methods = svc.api.publish.get_channel_map("CLI")
assert set(cli_methods) == {"admin", "public"}

public_scope = svc.api.describe()["methods"]["public"]["scope"]
assert public_scope == {"tags": ["public_shop"], "channels": {"public_shop": ["HTTP"]}}
```

**Configuration examples:**

```python
svc.routedclass.configure("api:publish/_all_", scope_channels={"sales": ["CLI"]})
svc.routedclass.configure("api:publish/public", scopes="public_shop,internal")
svc.routedclass.configure("api:publish/admin", channels="CLI")  # alias for {"*": ["CLI"]}
```

---

## Instance Isolation

Each instance has completely independent router state and plugins.

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

```python
class Service(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(self, name="api").plug("capture")

    @route("api")
    def action(self):
        return f"action:{self.label}"

svc1 = Service("first")
svc2 = Service("second")

svc1.api.get("action")()
svc2.api.get("action")()

# Independent plugin state
assert svc1.api.capture.calls == ["action"]
assert svc2.api.capture.calls == ["action"]
# Different handlers
assert svc1.api.get("action")() == "action:first"
assert svc2.api.get("action")() == "action:second"
```

**Benefits:**

- No global state pollution
- Thread-safe by design
- Independent configuration per instance
- Easy testing with isolation

---

## Plugin Inheritance

Child routers automatically inherit parent plugins.

<!-- test: test_switcher_basic.py::test_parent_plugins_inherit_to_children -->

```python
class Parent(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

class Child(RoutedClass):
    def __init__(self):
        self.routes = Router(self, name="routes")

    @route("routes")
    def action(self): return "ok"

parent = Parent()
child = Child()
parent.api.add_child(child, name="child")

# Child router now has logging plugin from parent
assert hasattr(child.routes, "logging")

# Plugin applies to child handlers
child.routes.get("action")()  # Logged
```

**Inheritance rules:**

- Plugins propagate from parent to all descendants
- Plugin order: parent plugins → child plugins
- Configuration can be overridden per child

---

## Edge Cases & Validation

### Router instantiation without owner

```python
# ValueError: Owner instance is required
router = Router(name="api")  # ERROR!

# Correct: Always pass self
router = Router(self, name="api")  # OK
```

### Handler name collisions

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def action(self): pass

    @route("api")
    def action(self): pass  # ERROR: Duplicate name

# ValueError: Handler 'action' already registered
```

### Invalid add_child types

```python
# TypeError: Cannot add Router class
self.api.add_child(Router)  # ERROR!

# ValueError: Name already exists
self.api.add_child(child1, name="child")
self.api.add_child(child2, name="child")  # ERROR!

# KeyError: Child not found
self.api.get_child("missing")  # ERROR!
```

### Plugin registration validation

```python
# TypeError: Not a BasePlugin subclass
Router.register_plugin("bad", object)  # ERROR!

# ValueError: Name already registered with different class
Router.register_plugin("custom", PluginA)
Router.register_plugin("custom", PluginB)  # ERROR!
```

---

## Complete Example

Bringing it all together:

```python
from smartroute import RoutedClass, Router, route

class UsersService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api", prefix="handle_")

    @route("api")
    def handle_list(self):
        return ["alice", "bob"]

    @route("api", name="detail")
    def handle_get(self, user_id: int):
        return {"id": user_id, "name": "..."}

class Application(RoutedClass):
    def __init__(self):
        # Root router with plugins
        self.api = Router(self, name="api")\
            .plug("logging")\
            .plug("pydantic")

        # Add child services
        users = UsersService()
        self.api.add_child(users, name="users")

app = Application()

# Direct access
users_list = app.api.call("users.list")

# Hierarchical access
user = app.api.call("users.detail", 42)

# Plugin is active (logging occurs, validation runs)
# Configuration
app.routedclass.configure("api:logging/users.*", level="debug")
```

---

## Testing

SmartRoute achieves 100% test coverage with 59 comprehensive tests.

All examples in this document are extracted from the test suite and verified by CI.

**Run tests:**

```bash
PYTHONPATH=src pytest --cov=src/smartroute --cov-report=term-missing
```

**Test categories:**

- Core functionality (test_switcher_basic.py)
- Edge cases (test_router_edge_cases.py)
- Plugin system (test_plugins_new.py)
- Pydantic validation (test_pydantic_plugin.py)
- Runtime extras (test_router_runtime_extras.py)
