# SmartRoute - Frequently Asked Questions

<!-- test: test_switcher_basic.py::test_orders_quick_example -->

## What is SmartRoute?

### What problem does SmartRoute solve?

**Question**: I have many methods in a class and want to call them dynamically by string name. How can I organize them better?

**Answer**: SmartRoute lets you create a "router" that maps string names to Python methods, with per-instance isolation and hierarchy support. Instead of manually managing a dictionary of handlers, you use the `@route()` decorator and SmartRoute handles the rest.

<!-- test: test_switcher_basic.py::test_orders_quick_example -->

**Example**:
```python
from smartroute import RoutedClass, Router, route

class OrdersAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="orders")

    @route("orders")
    def list(self):
        return ["order-1", "order-2"]

    @route("orders")
    def create(self, payload: dict):
        return {"status": "created", **payload}

orders = OrdersAPI()
orders.api.get("list")()  # Calls list()
orders.api.get("create")({"name": "order-3"})  # Calls create()
```

### SmartRoute vs function dictionary?

**Question**: Why not just use a dictionary `{"list": self.list, "create": self.create}`?

**Answer**: SmartRoute offers:

- **Plugin system**: add logging, validation, audit without touching handlers
- **Hierarchies**: organize routers in trees with `add_child()`
- **Metadata**: each handler can have scopes, channels, configurations
- **Introspection**: `router.members()` and `describe()` to explore structure
- **Isolation**: each instance has its own router with independent plugins

For simple apps, a dictionary may suffice. For complex services, SmartRoute provides structure and extensibility.

### Is SmartRoute a web framework?

**Question**: Does SmartRoute replace FastAPI/Flask?

**Answer**: **No**. SmartRoute is an **internal** routing engine for organizing Python methods. It doesn't handle HTTP, WebSocket, or networking. It's used **inside** an application for:
- CLI tools (Publisher)
- Internal orchestrators
- Service composition
- Dynamic dashboards

You can use SmartRoute **alongside** FastAPI to organize your internal handlers before exposing them via HTTP.

## Core Concepts

### What is a Router?

**Question**: What exactly does a `Router` do?

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

**Answer**: A `Router` is an object that:

1. **Registers handlers**: methods decorated with `@route()`
2. **Resolves by name**: `router.get("method_name")` → callable
3. **Applies plugins**: intercepts decoration and execution
4. **Is isolated per instance**: each object has its own router

```python
class Service(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(self, name="api")

    @route("api")
    def info(self):
        return f"service:{self.label}"

s1 = Service("alpha")
s2 = Service("beta")
s1.api.get("info")()  # "service:alpha"
s2.api.get("info")()  # "service:beta"
```

Each instance (`s1`, `s2`) has a **separate and isolated** router.

### How does the @route decorator work?

**Question**: What does `@route("api")` exactly do?

<!-- test: test_switcher_basic.py::test_prefix_and_name_override -->

**Answer**: The `@route("router_name")` decorator marks a method to be registered in a specific router. When you create the instance and call `Router(self, name="api")`, the router finds all methods marked with `@route("api")` and registers them automatically.

**Options**:
```python
@route("api")  # Auto name (method name)
def list_users(self): ...

@route("api", name="users")  # Explicit name
def handle_users(self): ...

# With Router(prefix="handle_")
@route("api")
def handle_create(self): ...  # Registered as "create" (strips prefix)
```

### What is RoutedClass?

**Question**: Do I always need to inherit from `RoutedClass`?

**Answer**: **Recommended but not required**. `RoutedClass` provides:

- `obj.routedclass` proxy to access all routers
- `obj.routedclass.configure()` for global configuration
- Automatic router registry management

**Without RoutedClass** you can still use `Router` directly, but you lose the unified proxy.

## Hierarchies and Child Routers

### How do I organize nested routers?

**Question**: I have an application with modules (sales, finance, admin) that I want to organize hierarchically. How?

<!-- test: test_switcher_basic.py::test_dashboard_hierarchy -->

**Answer**: Use `add_child()` to connect child routers:

```python
class Dashboard(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        self.sales = SalesModule()
        self.finance = FinanceModule()

        # Connect children by attribute name
        self.api.add_child("sales, finance")

dashboard = Dashboard()
# Access with dotted path
dashboard.api.get("sales.report")()
dashboard.api.get("finance.summary")()
```

### How do I access child routers?

**Question**: Once connected, how do I call child handlers?

**Answer**: Use **dotted path**:
```python
# Dotted path
dashboard.api.get("sales.report")()

# Or direct access
dashboard.sales.api.get("report")()

# Introspection
members = dashboard.api.members()
# {
#   "handlers": {...},
#   "children": {
#     "sales": {...},
#     "finance": {...}
#   }
# }
```

### Do plugins inherit to children?

**Question**: If I attach a plugin to the parent router, do children see it?

<!-- test: test_switcher_basic.py::test_parent_plugins_inherit_to_children -->

**Answer**: **Yes, automatically**. Plugins propagate from parent to children:

```python
class Parent(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging", level="debug")
        self.child_obj = Child()
        self.api.add_child(self.child_obj.api, name="child")

# Child automatically inherits logging plugin
parent = Parent()
parent.api.get("child.method")()  # Logs with level=debug
```

## Plugin System

### What are plugins?

**Question**: What is a plugin in SmartRoute and what is it for?

**Answer**: A **plugin** extends router behavior without modifying handlers. Plugins intercept:

1. **Decoration** (`on_decore`): when a handler is registered
2. **Execution** (`wrap_handler`): when a handler is called

**Use cases**:

- **Logging**: record all calls
- **Validation**: check input with Pydantic
- **Audit**: track who/when/what
- **Scope**: limit handler visibility by channel

### How do I use built-in plugins?

**Question**: Does SmartRoute have ready-to-use plugins?

<!-- test: test_plugins_new.py::test_logging_plugin_runs_per_instance -->

**Answer**: Yes, 2 built-in plugins:

**1. LoggingPlugin** - Automatic logging
```python
router = Router(self, name="api").plug("logging", level="debug")
router.api.get("method")()  # Auto-logs the call
```

**2. PydanticPlugin** - Input validation
<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

```python
from pydantic import BaseModel

class CreateRequest(BaseModel):
    name: str
    count: int

@route("api")
def create(self, req: CreateRequest):
    return {"status": "created"}

router.plug("pydantic")
router.get("create")({"name": "test", "count": 5})  # OK
router.get("create")({"name": "test"})  # ValidationError
```

Scope/channel policies are provided by the SmartPublisher ecosystem plugin; see *Scope and Channel* below.

### How do I configure plugins at runtime?

**Question**: I want to change plugin configuration after creating the router.

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

**Answer**: Use `routedclass.configure()`:

```python
# Global for all handlers
obj.routedclass.configure("api:logging", level="warning")

# For specific handler
obj.routedclass.configure("api:logging/create", enabled=False)

# With wildcards
obj.routedclass.configure("*:logging/*", level="debug")

# Query configuration
report = obj.routedclass.configure("?")
```

### Can I create custom plugins?

**Question**: How do I write a custom plugin?

**Answer**: Inherit from `BasePlugin` and implement the hooks:

```python
from smartroute.plugins import BasePlugin

class AuditPlugin(BasePlugin):
    def on_decore(self, router, func, entry):
        """Called when handler is registered"""
        entry.metadata["audited"] = True

    def wrap_handler(self, router, entry, call_next):
        """Called when handler is executed"""
        def wrapper(*args, **kwargs):
            print(f"[AUDIT] Calling {entry.name}")
            result = call_next(*args, **kwargs)
            print(f"[AUDIT] Result: {result}")
            return result
        return wrapper

# Register and use
Router.register_plugin("audit", AuditPlugin)
router = Router(self, name="api").plug("audit")
```

## Scope and Channel

### What are scope and channel?

**Question**: I don't understand the difference between "scope" and "channel".

**Answer**:

- **Scope** = **logical tag** identifying visibility level (e.g., `internal`, `public_read`, `admin`)
- **Channel** = **physical channel** where the handler can be exposed (e.g., `CLI`, `HTTP`, `WS`, `MCP`)

For scope/channel rules, use the SmartPublisher ecosystem plugin (`PublishPlugin`).

**Example**:
```python
from smartpublisher.smartroute_plugins.publish import PublishPlugin
from smartroute import Router, route

router = Router(self, name="api").plug("publish")  # import registers the plugin

# Handler with "internal" scope exposed only on CLI
@route("api", metadata={"scopes": "internal"})
def debug_status(self):
    return {"memory": "1GB", "cpu": "45%"}

router.publish.set_config(scope_channels={"internal": ["CLI"]})

# Filter by channel
cli_only = router.members(channel="CLI")  # Includes debug_status
http_only = router.members(channel="HTTP")  # Does NOT include debug_status
```

### When should I use PublishPlugin?

**Question**: In which scenarios is the publication plugin useful?

**Answer**: Use `PublishPlugin` when:

1. **Multi-channel exposure**: same app exposed on CLI, HTTP, WebSocket
2. **Security separation**: internal vs public handlers
3. **API versioning**: `public_v1`, `public_v2` with different channels
4. **MCP integration**: limit handlers visible to AI agents

**Practical example**:
```python
# Publisher with CLI admin and HTTP public
from smartpublisher.smartroute_plugins.publish import PublishPlugin
router = Router(self, name="api").plug("publish")

@route("api", metadata={"scopes": "admin"})
def restart_service(self):  # CLI only
    ...

@route("api", metadata={"scopes": "public"})
def get_status(self):  # CLI + HTTP
    ...

# Configuration
router.publish.set_config(scope_channels={
    "admin": ["CLI"],
    "public": ["CLI", "HTTP"]
})
```

## Advanced Use Cases

### How do I register handlers dynamically?

**Question**: I want to add handlers at runtime, not just with decorators.

<!-- test: test_switcher_basic.py::test_dynamic_router_add_entry_runtime -->

**Answer**: Use `router.add_entry()`:

```python
# Lambda handler
router.add_entry(lambda: "dynamic", name="dynamic_handler")

# External function
def external_func():
    return "external"

router.add_entry(external_func, name="external")

# Register all marked methods (lazy registration)
router.add_entry("*")
```

### How do I handle errors and defaults?

**Question**: What happens if I call a non-existent handler?

<!-- test: test_switcher_basic.py::test_get_with_default_returns_callable -->

**Answer**: You can specify a **default handler**:

```python
# Default handler
def not_found():
    return {"error": "handler not found"}

router = Router(self, name="api", default_handler=not_found)
router.get("missing")()  # Returns {"error": "handler not found"}

# Without default
router2 = Router(self, name="api2")
router2.get("missing")()  # Raises KeyError
```

### How do I use SmartAsync?

**Question**: I want to wrap handlers with SmartAsync for async execution.

<!-- test: test_switcher_basic.py::test_get_with_smartasync -->

**Answer**: Enable `use_smartasync`:

```python
# Global for router
router = Router(self, name="api", use_smartasync=True)

# For single call
handler = router.get("method", use_smartasync=False)  # Override

# Runtime override
result = router.get("method", use_smartasync=True)()
```

**Note**: SmartAsync must be installed separately.

### How do I introspect the structure?

**Question**: I want to see all registered handlers and children.

<!-- test: test_switcher_basic.py::test_describe_returns_hierarchy -->

**Answer**: Use `members()` or `describe()`:

```python
# Structure snapshot
members = router.members()
# {
#   "handlers": {
#     "list": {"func": <function>, "metadata": {...}},
#     "create": {...}
#   },
#   "children": {
#     "sales": {...}
#   }
# }

# Full description
description = router.describe()
# {
#   "name": "api",
#   "prefix": None,
#   "plugins": ["logging", "pydantic"],
#   "methods": {...},
#   "children": {...}
# }

# With filters
internal_only = router.members(scopes="internal")
cli_handlers = router.members(channel="CLI")
```

## Comparisons

### SmartRoute vs decorator dispatch?

**Question**: Why not use `functools.singledispatch`?

**Answer**:

- `singledispatch` → dispatch by **type** of first argument
- SmartRoute → dispatch by **string name** with metadata, plugins, hierarchies

Different use cases: `singledispatch` for typed polymorphism, SmartRoute for dynamic routing.

## Troubleshooting

### "No plugin named 'X' attached to router"

**Problem**: `AttributeError: No plugin named 'logging' attached to router`

**Solution**: The plugin wasn't attached. Use `.plug()`:
```python
router.plug("logging")  # Now router.logging exists
```

### "Handler name collision"

**Problem**: Two methods with the same name registered on the same router.

**Solution**: Use explicit names or prefixes:
```python
@route("api", name="create_user")
def handle_create_user(self): ...

@route("api", name="create_order")
def handle_create_order(self): ...
```

### Plugins don't propagate to children

**Problem**: Children don't see parent plugins.

**Solution**: Make sure to connect children **after** attaching plugins:
```python
# CORRECT
router.plug("logging")
router.add_child(child)  # Child inherits logging

# WRONG
router.add_child(child)
router.plug("logging")  # Child does NOT inherit
```

### ValidationError with Pydantic

**Problem**: `ValidationError` even with correct input.

**Solution**: Verify:

1. PydanticPlugin attached: `router.plug("pydantic")`
2. Type hint correct: `def method(self, req: MyModel)`
3. Input is dict or model instance: `router.get("method")({"field": "value"})`

## Best Practices

### When should I use SmartRoute?

✅ **Use SmartRoute when**:

- You have many handlers to organize dynamically
- You want to extend behavior with plugins
- You need hierarchical routing (parent/child)
- You have multi-channel exposure (CLI/HTTP/WS)

❌ **Don't use SmartRoute when**:
- You only have 2-3 simple methods (overkill)
- You don't need dynamic dispatch
- You prefer explicit/static routing

### Does plugin order matter?

**Question**: Is the order of `.plug()` important?

**Answer**: **Yes**. Plugins are applied **in attachment order**:
```python
router.plug("logging").plug("pydantic")
# Execution: logging → pydantic → handler → pydantic → logging
```

Outer logging sees everything, inner Pydantic validates.

### How do I test code with SmartRoute?

**Question**: How do I write tests for handlers with SmartRoute?

**Answer**: Test directly or via router:
```python
# Direct test
def test_handler_logic():
    obj = MyClass()
    assert obj.my_handler({"input": "test"}) == expected

# Test via router
def test_router_integration():
    obj = MyClass()
    handler = obj.api.get("my_handler")
    assert handler({"input": "test"}) == expected
```

## Useful Links

- **[Quick Start](quickstart.md)** - Get started in 5 minutes
- **[Basic Usage](guide/basic-usage.md)** - Fundamental concepts
- **[Plugin Guide](guide/plugins.md)** - Plugin development
- **[Hierarchies](guide/hierarchies.md)** - Nested routing
- **[API Reference](api/reference.md)** - Complete documentation

## Contributing

Have more questions? [Open an issue](https://github.com/genropy/smartroute/issues) or contribute to this FAQ!
