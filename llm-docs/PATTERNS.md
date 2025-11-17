# SmartRoute - Common Usage Patterns

**Extracted from production test suite**

## Pattern 1: Basic Service Router

**Use when:** Building a service with multiple methods that should be callable by name.

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

```python
from smartroute import RoutedClass, Router, route

class Service(RoutedClass):
    api = Router(name="service")

    def __init__(self, label: str):
        self.label = label

    @route("api")
    def describe(self):
        return f"service:{self.label}"

    @route("api")
    def process(self, data: str):
        return f"{self.label}:{data}"

# Usage
svc = Service("myservice")
handler = svc.api.get("describe")
result = handler()  # "service:myservice"
```

**Key Points:**

- Each instance has isolated state
- Router name is optional but recommended for clarity
- Methods are bound to instance automatically

---

## Pattern 2: Prefix Stripping with Aliases

**Use when:** Following naming conventions (e.g., `handle_*`) but want clean route names.

<!-- test: test_switcher_basic.py::test_prefix_and_alias_resolution -->

```python
class SubService(RoutedClass):
    routes = Router(prefix="handle_")

    def __init__(self, prefix: str):
        self.prefix = prefix

    @route("routes")
    def handle_list(self):
        return f"{self.prefix}:list"

    @route("routes", alias="detail")
    def handle_detail(self, ident: int):
        return f"{self.prefix}:detail:{ident}"

# Usage
sub = SubService("users")
sub.routes.entries()  # {"list", "detail"}  ← prefix stripped, alias used
sub.routes.get("list")()  # "users:list"
sub.routes.get("detail")(10)  # "users:detail:10"
```

**Key Points:**

- `prefix` is stripped from method names automatically
- `alias` overrides final registered name
- Useful for maintaining method naming conventions

---

## Pattern 3: Hierarchical Service Composition

**Use when:** Building API with nested resources (e.g., `/users`, `/products`).

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->

```python
class RootAPI(RoutedClass):
    api = Router(name="root")

    def __init__(self):
        users = SubService("users")
        products = SubService("products")

        # Add children individually
        self.api.add_child(users, name="users")
        self.api.add_child(products, name="products")

# Usage
root = RootAPI()
root.api.get("users.list")()  # Dotted path traversal
root.api.get("products.detail")(5)  # "products:detail:5"
```

**Key Points:**

- Use `add_child(obj, name="...")` for hierarchies
- Access with dotted notation: `"parent.child.method"`
- Each child maintains independence

---

## Pattern 4: Bulk Child Registration

**Use when:** Registering multiple children at once.

<!-- test: test_switcher_basic.py::test_add_child_accepts_mapping_for_named_children -->

```python
class RootAPI(RoutedClass):
    api = Router(name="root")

    def __init__(self):
        self.users = SubService("users")
        self.products = SubService("products")

        # Register multiple children via dict
        self.api.add_child({
            "users": self.users,
            "products": self.products
        })

root = RootAPI()
root.api.get("users.list")()
root.api.get("products.detail")(7)
```

**Alternative:** Nested iterables for complex structures.

<!-- test: test_switcher_basic.py::test_add_child_handles_nested_iterables_and_pairs -->

```python
registry = [
    {"users": users_svc},
    [("products", products_svc)],
]
root.api.add_child(registry)
```

---

## Pattern 5: Plugin-Enhanced Service

**Use when:** Need cross-cutting concerns (logging, validation, metrics).

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

```python
from smartroute import BasePlugin, Router

class CapturePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="capture")
        self.calls = []

    def wrap_handler(self, route, entry, call_next):
        def wrapper(*args, **kwargs):
            self.calls.append("wrap")
            return call_next(*args, **kwargs)
        return wrapper

# Register custom plugin
Router.register_plugin("capture", CapturePlugin)

class PluginService(RoutedClass):
    api = Router(name="plugin").plug("capture")

    def __init__(self):
        self.touched = False

    @route("api")
    def do_work(self):
        self.touched = True
        return "ok"

# Usage
svc = PluginService()
svc.api.capture.calls  # []  ← Plugin accessible as attribute
result = svc.api.get("do_work")()
svc.api.capture.calls  # ["wrap"]  ← Plugin recorded call

# Another instance is independent
other = PluginService()
other.api.capture.calls  # []  ← New plugin instance
```

**Key Points:**

- Plugins are **per-instance**, not global
- Access plugin via attribute: `bound.plugin_name`
- Useful for testing and monitoring

---

## Pattern 6: Plugin Inheritance

**Use when:** Child services should inherit parent behavior (logging, auth, etc.).

<!-- test: test_switcher_basic.py::test_parent_plugins_inherit_to_children -->

```python
class ParentAPI(RoutedClass):
    api = Router(name="parent").plug("logging")

parent = ParentAPI()
child = SubService("child")
parent.api.add_child(child, name="child")

# Child router now has parent's LoggingPlugin
assert hasattr(child.routes, "logger")
child.routes.get("list")()  # Logged automatically
```

**Key Points:**

- Plugins propagate from parent to child automatically
- No need to re-plug on children
- Simplifies configuration for deep hierarchies

---

## Pattern 7: Default Handler Fallback

**Use when:** Need graceful degradation for missing routes.

<!-- test: test_switcher_basic.py::test_get_with_default_returns_callable -->

```python
def fallback():
    return "fallback"

# Runtime default
handler = svc.api.get("missing", default_handler=fallback)
result = handler()  # "fallback"
```

**Router-level default:**

<!-- test: test_switcher_basic.py::test_get_uses_init_default_handler -->

```python
class DefaultService(RoutedClass):
    api = Router(get_default_handler=lambda: "init-default")

svc = DefaultService()
handler = svc.api.get("missing")  # No error!
handler()  # "init-default"
```

**Override router default at runtime:**

<!-- test: test_switcher_basic.py::test_get_runtime_override_init_default_handler -->

```python
handler = svc.api.get("missing", default_handler=lambda: "runtime")
handler()  # "runtime"  ← Overrides router default
```

---

## Pattern 8: SmartAsync Integration

**Use when:** Handlers need async execution via smartasync library.

<!-- test: test_switcher_basic.py::test_get_with_smartasync -->

```python
# Per-call smartasync
handler = svc.api.get("do_work", use_smartasync=True)
handler()  # Wrapped with smartasync
```

**Router-level smartasync:**

<!-- test: test_switcher_basic.py::test_get_uses_init_smartasync -->

```python
class AsyncService(RoutedClass):
    api = Router(get_use_smartasync=True)

    @route("api")
    def do_work(self):
        return "ok"

svc = AsyncService()
handler = svc.api.get("do_work")  # Auto-wrapped
handler()  # Async execution
```

**Disable router default:**

<!-- test: test_switcher_basic.py::test_get_can_disable_init_smartasync -->

```python
# Router has get_use_smartasync=True
handler = svc.api.get("do_work", use_smartasync=False)
handler()  # NOT wrapped
```

---

## Pattern 9: Runtime Plugin Control

**Use when:** Need to enable/disable plugins dynamically.

<!-- test: test_switcher_basic.py::test_plugin_enable_disable_runtime_data -->

```python
class TogglePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="toggle")

    def wrap_handler(self, route, entry, call_next):
        def wrapper(*args, **kwargs):
            route.set_runtime_data(entry.name, self.name, "last", True)
            return call_next(*args, **kwargs)
        return wrapper

# Register custom plugin
Router.register_plugin("toggle", TogglePlugin)

class ToggleService(RoutedClass):
    api = Router(name="toggle").plug("toggle")

    @route("api")
    def touch(self):
        return "done"

svc = ToggleService()
handler = svc.api.get("touch")

# Plugin active
handler()
assert svc.api.get_runtime_data("touch", "toggle", "last") is True

# Disable plugin
svc.api.set_plugin_enabled("touch", "toggle", False)
svc.api.set_runtime_data("touch", "toggle", "last", None)
handler()
assert svc.api.get_runtime_data("touch", "toggle", "last") is None  # Not set

# Re-enable
svc.api.set_plugin_enabled("touch", "toggle", True)
handler()
assert svc.api.get_runtime_data("touch", "toggle", "last") is True
```

**Key Points:**

- Runtime data stored per (handler, plugin, key)
- Useful for feature flags, A/B testing, debugging
- Changes affect only specific handler, not entire router

---

## Pattern 10: Deep Child Discovery

**Use when:** Children are nested in non-routed objects.

<!-- test: test_switcher_basic.py::test_nested_child_discovery -->

```python
class NestedLeaf(RoutedClass):
    leaf_switch = Router(name="leaf")

    @route("leaf_switch")
    def leaf_ping(self):
        return "leaf"

class NestedBranch:
    """Not a RoutedClass - just a container"""
    def __init__(self):
        self.child_leaf = NestedLeaf()

class NestedRoot(RoutedClass):
    api = Router(name="root")

    def __init__(self):
        self.branch = NestedBranch()
        self.api.add_child(self.branch)  # Scans branch recursively

root = NestedRoot()
root.api.get("leaf_switch.leaf_ping")()  # "leaf"  ← Found through branch
```

**Key Points:**

- `add_child()` scans objects recursively for routers
- Non-routed container objects work fine
- Useful for complex domain models

---

## Pattern 11: Pydantic Validation

**Use when:** Need automatic argument validation.

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

```python
class ValidateService(RoutedClass):
    api = Router(name="validate").plug("pydantic")

    @route("api")
    def concat(self, text: str, number: int = 1) -> str:
        return f"{text}:{number}"

svc = ValidateService()

# Valid inputs
svc.api.get("concat")("hello", 3)  # "hello:3"
svc.api.get("concat")("hi")  # "hi:1"  ← Default value works
```

**Invalid inputs raise `ValidationError`:**

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_rejects_invalid_input -->

```python
from pydantic import ValidationError

try:
    svc.api.get("concat")(123, "oops")  # Wrong types!
except ValidationError as e:
    print(e)  # Detailed validation error
```

**Requirements:**

- Install: `pip install smartroute[pydantic]`
- Type hints required on parameters
- Supports defaults, optional, unions

---

## Pattern 12: Custom Plugin Development

**Use when:** Building reusable cross-cutting logic.

```python
from smartroute import RoutedClass, Router, route
from smartroute.core import BasePlugin, MethodEntry  # Not public API

class MetricsPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="metrics")
        self.call_counts = {}

    def on_decore(self, router, func, entry: MethodEntry):
        """Called during registration"""
        entry.metadata["metrics"] = {"enabled": True}
        self.call_counts[entry.name] = 0

    def wrap_handler(self, router, entry: MethodEntry, call_next):
        """Wrap execution"""
        def wrapper(*args, **kwargs):
            if entry.metadata["metrics"]["enabled"]:
                self.call_counts[entry.name] += 1
            return call_next(*args, **kwargs)
        return wrapper

# Register and use
Router.register_plugin("metrics", MetricsPlugin)

class Service(RoutedClass):
    api = Router().plug("metrics")

    @route("api")
    def work(self):
        return "done"

svc = Service()
svc.api.get("work")()
print(svc.api.metrics.call_counts)  # {"work": 1}
```

**Key Methods:**

- `on_decore`: Modify metadata during registration
- `wrap_handler`: Wrap execution (must call `call_next`!)
- Access via attribute: `bound.plugin_name`

---

## Pattern 13: Error Handling

**Without default handler:**

<!-- test: test_switcher_basic.py::test_get_without_default_raises -->

```python
try:
    svc.api.get("unknown")  # No default_handler
except NotImplementedError:
    print("Handler not found!")
```

**With default handler:**

```python
def handle_404():
    return {"error": "Not Found"}

handler = svc.api.get("unknown", default_handler=handle_404)
result = handler()  # {"error": "Not Found"}
```

---

## Pattern 14: Testing Routers

**Instance isolation makes testing easy:**

```python
def test_service_isolation():
    first = Service("alpha")
    second = Service("beta")

    # Independent handlers
    assert first.api.get("describe")() == "service:alpha"
    assert second.api.get("describe")() == "service:beta"

    # Different bound methods
    assert first.api.get("describe") != second.api.get("describe")
```

**Plugin testing:**

```python
def test_plugin_behavior():
    svc = PluginService()

    # Plugin state before
    assert svc.api.capture.calls == []

    # Execute
    svc.api.get("do_work")()

    # Plugin state after
    assert svc.api.capture.calls == ["wrap"]
    assert svc.touched is True
```

---

## Anti-Patterns

### ❌ Don't: Pass Router Descriptor

<!-- test: test_switcher_basic.py::test_add_child_requires_instance -->

```python
# WRONG: Router descriptor not allowed
try:
    root.api.add_child(SubService.routes)
except TypeError:
    pass  # Error!

# CORRECT: Pass instance
users = SubService("users")
root.api.add_child(users)
```

---

### ❌ Don't: Reuse Handler Names

<!-- test: test_router_edge_cases.py::test_router_detects_handler_name_collision -->

```python
class DuplicateService(RoutedClass):
    api = Router()

    @route("api", alias="dup")
    def first(self): pass

    @route("api", alias="dup")  # WRONG: Duplicate name!
    def second(self): pass

# Raises ValueError on access
try:
    svc = DuplicateService()
    _ = svc.api
except ValueError:
    pass  # Name collision detected
```

---

### ❌ Don't: Add Child with Duplicate Name

<!-- test: test_router_edge_cases.py::test_router_add_child_error_paths -->

```python
parent = Node()
child1 = Node()
child2 = Node()

parent.api.add_child(child1, name="leaf")

# WRONG: Name already exists
try:
    parent.api.add_child(child2, name="leaf")
except ValueError:
    pass  # Duplicate child name
```

---

## Summary

| Pattern | Use Case | Test Reference |
|---------|----------|----------------|
| Basic Service Router | Simple service with methods | `test_switcher_basic.py::test_instance_bound_methods_are_isolated` |
| Prefix Stripping | Clean route names with naming conventions | `test_switcher_basic.py::test_prefix_and_alias_resolution` |
| Hierarchical Composition | Nested resources/services | `test_switcher_basic.py::test_hierarchical_binding_with_instances` |
| Bulk Child Registration | Multiple children at once | `test_switcher_basic.py::test_add_child_accepts_mapping_for_named_children` |
| Plugin-Enhanced Service | Cross-cutting concerns | `test_switcher_basic.py::test_plugins_are_per_instance_and_accessible` |
| Plugin Inheritance | Propagate behavior to children | `test_switcher_basic.py::test_parent_plugins_inherit_to_children` |
| Default Handler | Graceful fallback | `test_switcher_basic.py::test_get_with_default_returns_callable` |
| SmartAsync Integration | Async execution | `test_switcher_basic.py::test_get_with_smartasync` |
| Runtime Plugin Control | Dynamic plugin toggling | `test_switcher_basic.py::test_plugin_enable_disable_runtime_data` |
| Deep Child Discovery | Nested non-routed objects | `test_switcher_basic.py::test_nested_child_discovery` |
| Pydantic Validation | Automatic argument validation | `test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input` |
| Custom Plugin | Reusable cross-cutting logic | Custom (based on BasePlugin) |

All patterns are production-tested with >95% coverage.
