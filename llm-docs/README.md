# SmartRoute - LLM Quick Reference

**30-Second Quick Start for Code Generation**

## What Is It?

Instance-scoped routing engine for dynamic method dispatch with plugin support.

## Core Pattern

```python
from smartroute.core import RoutedClass, Router, route

class Service(RoutedClass):
    api = Router(name="api")  # Router descriptor

    @route("api")  # Register method
    def method_name(self, arg: str) -> str:
        return f"result:{arg}"

# Usage
svc = Service()
handler = svc.api.get("method_name")  # Get handler
result = handler("value")  # Call it
```

## Key Concepts

| Concept | Purpose | Usage |
|---------|---------|-------|
| `Router` | Descriptor for routing | `api = Router(name="api")` |
| `@route("name")` | Register method | Decorator on instance methods |
| `BoundRouter` | Runtime instance | `svc.api` returns `BoundRouter` |
| `get(name)` | Retrieve handler | `svc.api.get("method")` |
| `add_child(obj)` | Build hierarchy | `parent.api.add_child(child)` |
| `plug(name)` | Add plugin by name | `Router().plug("logging")` |

## Common Patterns

### 1. Basic Router

```python
class Service(RoutedClass):
    api = Router()

    @route("api")
    def action(self): return "ok"
```

### 2. With Alias

```python
@route("api", alias="short_name")
def long_method_name(self): pass
```

### 3. With Prefix

```python
api = Router(prefix="handle_")

@route("api")  # Strips "handle_" prefix
def handle_list(self): pass  # Registered as "list"
```

### 4. Hierarchical

```python
class Root(RoutedClass):
    api = Router()

    def __init__(self):
        self.child = ChildService()
        self.api.add_child(self.child, name="child")

root = Root()
root.api.get("child.method")()  # Dotted path
```

### 5. With Plugins

Built-in plugins (`logging`, `pydantic`) are pre-registered and can be used by name:

```python
api = Router().plug("logging")
# Plugin hooks every handler call
```

### 6. Multiple Children (Dict)

```python
self.api.add_child({"users": users_svc, "products": prod_svc})
```

## Built-in Plugins

Built-in plugins are pre-registered and available by name (no imports needed):

- `"logging"` - Logs handler calls
- `"pydantic"` - Validates args with type hints

```python
api = Router().plug("pydantic")

@route("api")
def validate(self, text: str, count: int) -> str:
    return f"{text}*{count}"
```

## Default Handlers

```python
# Per-call default
handler = api.get("missing", default_handler=lambda: "default")

# Router-level default
api = Router(get_default_handler=lambda: "default")
```

## SmartAsync Support

```python
handler = api.get("method", use_smartasync=True)
```

## Runtime Control

```python
# Disable plugin for handler
api.set_plugin_enabled("method_name", "plugin_name", False)

# Runtime data
api.set_runtime_data("method", "plugin", "key", value)
data = api.get_runtime_data("method", "plugin", "key")
```

## Important Notes

- Each instance has **isolated** BoundRouter
- Plugins are **per-instance**, not global
- Child routers **inherit** parent plugins automatically
- Only **instance methods** supported (no static/class methods)
- Route names must be **unique** within a router

## Full API

See [API-DETAILS.md](API-DETAILS.md) for complete reference.
See [PATTERNS.md](PATTERNS.md) for advanced patterns.
