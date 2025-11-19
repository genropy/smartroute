# Hierarchical Routers

Build complex routing structures with nested routers, dotted path navigation, and automatic plugin inheritance.

## Overview

SmartRoute supports hierarchical router composition where:

- **Parent routers** can have **child routers**
- **Dotted paths** navigate the hierarchy (`root.api.get("users.list")`)
- **Plugins propagate** from parent to children automatically
- **Each level** maintains independent handler registration
- **Multiple registration patterns** support flexible organization

## Basic Hierarchy

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L149-L158)

Create a hierarchy by adding child instances:

```python
from smartroute import RoutedClass, Router, route

class SubService(RoutedClass):
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.routes = Router(self, name="routes", prefix="handle_")

    @route("routes")
    def handle_list(self):
        return f"{self.prefix}:list"

    @route("routes", name="detail")
    def handle_detail(self, ident: int):
        return f"{self.prefix}:detail:{ident}"

class RootAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        self.users = SubService("users")
        self.products = SubService("products")

        # Add children referencing attributes
        self.api.add_child("users")
        self.api.add_child("products")

root = RootAPI()

# Access with dotted paths
assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(5) == "products:detail:5"
```

**Key points**:

- Each child is an independent `RoutedClass` instance
- `add_child(instance, name="...")` registers the child
- Dotted paths navigate: `parent.child.handler`
- Children maintain their own routing state

## Dictionary Registration

<!-- test: test_switcher_basic.py::test_add_child_accepts_mapping_for_named_children -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L174-L182)

Register multiple children with a dictionary:

```python
root = RootAPI()
users = SubService("users")
products = SubService("products")

# Register multiple children at once
root.api.add_child({"users": users, "products": products})

assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(7) == "products:detail:7"
```

**Benefits**:

- Cleaner code for multiple children
- Dictionary keys become child names
- Single method call for bulk registration

## Flexible Registration Patterns

<!-- test: test_switcher_basic.py::test_add_child_handles_nested_iterables_and_pairs -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L185-L197)

Mix different registration patterns:

```python
root = RootAPI()
users = SubService("users")
products = SubService("products")

# Mix dictionaries, lists, and tuples
registry = [
    {"users": users},
    [("products", products)],
]

root.api.add_child(registry)

assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(3) == "products:detail:3"
```

**Supports**:

- Nested lists and dictionaries
- Tuple pairs: `(name, instance)`
- Mixed structures
- Dynamic configuration-driven registration

## Plugin Inheritance

<!-- test: test_switcher_basic.py::test_parent_plugins_inherit_to_children -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L220-L234)

Plugins propagate automatically from parent to children:

```python
class ParentAPI(RoutedClass):
    def __init__(self):
        # Plugin attached to parent
        self.api = Router(self, name="api").plug("logging")

parent = ParentAPI()
child = SubService("child")

# Add child - plugins inherit automatically
parent.api.add_child(child, name="child")

# Child router now has the logging plugin
assert hasattr(child.routes, "logging")

# Plugin applies to child handlers
result = child.routes.get("list")()
assert result == "child:list"
# Logging plugin was active during call
```

**Inheritance rules**:

- Parent plugins apply to all child handlers
- Children can add their own plugins
- Plugin order: parent plugins → child plugins
- Configuration inherits but can be overridden

## Dotted Path Navigation

<!-- test: test_router_edge_cases.py::test_routed_proxy_get_router_handles_dotted_path -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L268-L281)

Navigate hierarchy with dotted paths via `routedclass.get_router()`:

```python
class Child(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

class Parent(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        self.child = Child()
        self.api.add_child(self.child, name="child")

svc = Parent()

# Get child router directly
child_router = svc.routedclass.get_router("api.child")
assert child_router.name == "api"
```

**Navigation features**:

- `get_router("router.child.grandchild")` traverses hierarchy
- Returns the target router instance
- Enables programmatic router access
- Useful for dynamic configuration

## Introspection

<!-- test: test_switcher_basic.py::test_describe_returns_hierarchy -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L370-L379)

Inspect the full hierarchy structure:

```python
class Inspectable(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        child_service = SubService("child")
        self.api.add_child(child_service, name="sub")

    @route("api")
    def action(self):
        pass

insp = Inspectable()

# Get complete hierarchy metadata
info = insp.api.describe()
assert "action" in info["handlers"]
assert "sub" in info["children"]

# Nested structure included
assert "routes" in info["children"]["sub"]
```

**Introspection provides**:

- Complete handler list at each level
- Child router names and structure
- Plugin configuration per level
- Nested hierarchy representation

## Real-World Example

Complete service composition pattern:

```python
class AuthService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def login(self, username: str, password: str):
        return {"token": "..."}

    @route("api")
    def logout(self, token: str):
        return {"status": "ok"}

class UserService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def list_users(self):
        return ["alice", "bob"]

    @route("api")
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "..."}

class Application(RoutedClass):
    def __init__(self):
        # Root router with logging
        self.api = Router(self, name="api").plug("logging")

        # Create services
        auth = AuthService()
        users = UserService()

        # Compose hierarchy
        self.api.add_child({
            "auth": auth,
            "users": users,
        })

app = Application()

# Access through hierarchy
token = app.api.call("auth.login", "alice", "secret123")
users = app.api.call("users.list_users")

# Logging applies to all handlers automatically
```

## Best Practices

**Logical grouping**:

```python
# Group related services
self.api.add_child({
    "auth": AuthService(),
    "users": UserService(),
    "orders": OrderService(),
})
```

**Shared plugins at root**:

```python
# Apply logging and validation to entire hierarchy
self.api = Router(self, name="api")\
    .plug("logging")\
    .plug("pydantic")

# All children inherit both plugins
```

**Deep hierarchies**:

```python
# Organize by domain and subdomain
root.api.add_child({"admin": admin_api})
admin_api.api.add_child({"users": user_admin, "reports": report_admin})

# Access: root.api.get("admin.users.create_user")
```

**Dynamic registration**:

```python
# Load services from configuration
services_config = load_config("services.yaml")
for name, service_class in services_config.items():
    service = service_class()
    root.api.add_child(service, name=name)
```

## Next Steps

- **[Plugin Configuration](plugin-configuration.md)** - Configure plugins across hierarchies
- **[Best Practices](best-practices.md)** - Production-ready patterns
- **[API Reference](../api/reference.md)** - Complete API documentation
