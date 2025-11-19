# SmartRoute - LLM Quick Reference

**30-Second Quick Start for Code Generation**

## What Is It?

Instance-scoped routing engine for dynamic method dispatch with plugin support. Each instance gets its own isolated router.

## Core Pattern

```python
from smartroute import RoutedClass, Router, route

class Service(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(self, name="api")  # Runtime instantiation

    @route("api")  # Register method
    def method_name(self, arg: str) -> str:
        return f"result:{arg}"

# Usage
svc = Service("example")
handler = svc.api.get("method_name")  # Get handler
result = handler("value")  # Call it
```

## Key Concepts

| Concept | Purpose | Usage |
|---------|---------|-------|
| `Router(self, name="api")` | Instance-scoped router | Create in `__init__` |
| `@route("name")` | Register method | Decorator on instance methods |
| `get(name)` | Retrieve handler | `svc.api.get("method")` |
| `call(name, *args)` | Direct invocation | `svc.api.call("method", arg)` |
| `add_child(obj, name="...")` | Build hierarchy | `parent.api.add_child(child, name="child")` |
| `plug(name)` | Add plugin | `.plug("logging")` |
| `routedclass.configure()` | Configure plugins | Runtime configuration |

## Common Patterns

### 1. Basic Router

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def action(self):
        return "ok"
```

### 2. With Alias

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api", alias="short_name")
    def long_method_name(self):
        pass
```

### 3. With Prefix

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api", prefix="handle_")

    @route("api")  # Strips "handle_" prefix
    def handle_list(self):
        pass  # Registered as "list"
```

### 4. Hierarchical

```python
class Root(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        child = ChildService()
        self.api.add_child(child, name="child")

root = Root()
root.api.get("child.method")()  # Dotted path
```

### 5. With Plugins

Built-in plugins (`logging`, `pydantic`) are pre-registered:

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def action(self):
        return "ok"
```

### 6. Multiple Children (Dict)

```python
class Root(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        users = UsersService()
        products = ProductsService()
        self.api.add_child({"users": users, "products": products})
```

## Built-in Plugins

Pre-registered and available by name:

- `"logging"` - Logs handler calls
- `"pydantic"` - Validates args with type hints (requires `pip install smartroute[pydantic]`)

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("pydantic")

    @route("api")
    def validate(self, text: str, count: int) -> str:
        return f"{text}*{count}"
```

## Plugin Configuration

Configure plugins at runtime with target syntax:

```python
svc = Service()

# Global configuration - applies to all handlers
svc.routedclass.configure("api:logging/_all_", level="debug")

# Handler-specific configuration
svc.routedclass.configure("api:logging/foo", enabled=False)

# Glob pattern configuration
svc.routedclass.configure("api:logging/admin_*", level="error")

# Batch configuration
svc.routedclass.configure([
    {"target": "api:logging/_all_", "level": "info"},
    {"target": "api:pydantic/critical_*", "strict": True}
])
```

## Default Handlers

```python
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def known(self):
        return "ok"

svc = Service()

# Per-call default
def fallback():
    return "default"

handler = svc.api.get("missing", default=fallback)
result = handler()  # Returns "default"
```

## SmartAsync Support

```python
handler = svc.api.get("method", use_smartasync=True)
```

## Introspection

```python
# Get hierarchical description
description = svc.api.describe()
# Returns dict with:
# - name, plugins, handlers, children

# List handler names
members = svc.api.members()
# Returns list of handler names

# Query configuration tree
info = svc.routedclass.configure("?")
# Returns full router/plugin structure
```

## Important Notes

- **Runtime instantiation**: `Router(self, name="api")` in `__init__`
- **Instance isolation**: Each object has independent router state
- **Per-instance plugins**: Plugins are not global
- **Automatic inheritance**: Child routers inherit parent plugins
- **Instance methods only**: No static/class methods
- **Unique names**: Route names must be unique within router

## Full API

- [API-DETAILS.md](API-DETAILS.md) - Complete API reference
- [PATTERNS.md](PATTERNS.md) - Advanced patterns
- [docs/](../docs/) - Human-readable documentation
