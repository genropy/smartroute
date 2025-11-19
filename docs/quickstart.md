# Quick Start

Get started with SmartRoute in 5 minutes.

## Installation

```bash
pip install smartroute
```

## Your First Router

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L131-L138)

Create a service with instance-scoped routing:

```python
from smartroute import RoutedClass, Router, route

class Service(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(self, name="api")

    @route("api")
    def describe(self):
        return f"service:{self.label}"

# Each instance is isolated
first = Service("alpha")
second = Service("beta")

assert first.api.get("describe")() == "service:alpha"
assert second.api.get("describe")() == "service:beta"
```

**Key concept**: Routers are instantiated in `__init__` with `Router(self, ...)` - each instance gets its own isolated router.

## Adding Aliases

<!-- test: test_switcher_basic.py::test_prefix_and_alias_resolution -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L141-L146)

Use prefixes and aliases for cleaner method names:

```python
class SubService(RoutedClass):
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.routes = Router(self, name="routes", prefix="handle_")

    @route("routes")
    def handle_list(self):
        return f"{self.prefix}:list"

    @route("routes", alias="detail")
    def handle_detail(self, ident: int):
        return f"{self.prefix}:detail:{ident}"

sub = SubService("users")

# Prefix stripped: "handle_list" � "list"
assert sub.routes.get("list")() == "users:list"

# Alias used: "handle_detail" � "detail"
assert sub.routes.get("detail")(10) == "users:detail:10"
```

## Building Hierarchies

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L149-L158)

Create nested router structures:

```python
class RootAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        users = SubService("users")
        products = SubService("products")

        self.api.add_child(users, name="users")
        self.api.add_child(products, name="products")

root = RootAPI()

# Access with dotted paths
assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(5) == "products:detail:5"
```

## Adding Plugins

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L200-L208)

Extend behavior with plugins. Built-in plugins (`logging`, `pydantic`) are pre-registered:

```python
class PluginService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def do_work(self):
        return "ok"

svc = PluginService()
result = svc.api.get("do_work")()  # Automatically logged
```

## Validating Arguments

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_pydantic_plugin.py#L22-L27)

Use Pydantic for automatic validation:

```bash
pip install smartroute[pydantic]
```

```python
class ValidateService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("pydantic")

    @route("api")
    def concat(self, text: str, number: int = 1) -> str:
        return f"{text}:{number}"

svc = ValidateService()

# Valid inputs
assert svc.api.get("concat")("hello", 3) == "hello:3"
assert svc.api.get("concat")("hi") == "hi:1"

# Invalid inputs raise ValidationError
# svc.api.get("concat")(123, "oops")  # ValidationError!
```

## Next Steps

Now that you've learned the basics:

- **[Basic Usage Guide](guide/basic-usage.md)** - Detailed explanation of core concepts
- **[Plugin Guide](guide/plugins.md)** - Learn to create custom plugins
- **[Hierarchies Guide](guide/hierarchies.md)** - Master nested routers
- **[Best Practices](guide/best-practices.md)** - Production-ready patterns
- **[API Reference](api/reference.md)** - Complete API documentation

## Need Help?

- **LLM Reference**: See [llm-docs/](../llm-docs/) for AI-optimized documentation
- **Examples**: Check the [examples/](https://github.com/genropy/smartroute/tree/main/examples) directory
- **Issues**: Report bugs on [GitHub Issues](https://github.com/genropy/smartroute/issues)
