# Quick Start

Get started with SmartRoute in 5 minutes.

## Installation

```bash
pip install smartroute
```

## Your First Router

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

Create a simple service with routed methods:

```python
from smartroute.core import RoutedClass, Router, route

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
```

## Using the Router

```python
# Create instance
svc = Service("myservice")

# Get handler by name
handler = svc.api.get("describe")

# Call handler
result = handler()  # "service:myservice"

# Direct call
result = svc.api.get("process")("data")  # "myservice:data"
```

## Instance Isolation

Each instance has its own isolated router:

```python
first = Service("alpha")
second = Service("beta")

assert first.api.get("describe")() == "service:alpha"
assert second.api.get("describe")() == "service:beta"

# Different bound methods
assert first.api.get("describe") != second.api.get("describe")
```

## Adding Aliases

<!-- test: test_switcher_basic.py::test_prefix_and_alias_resolution -->

Use aliases for shorter or more descriptive names:

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

sub = SubService("users")

# Prefix stripped: "handle_list" ’ "list"
assert sub.routes.get("list")() == "users:list"

# Alias used: "handle_detail" ’ "detail"
assert sub.routes.get("detail")(10) == "users:detail:10"
```

## Building Hierarchies

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->

Create nested router structures:

```python
class RootAPI(RoutedClass):
    api = Router(name="root")

    def __init__(self):
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

Extend behavior with plugins:

```python
from smartroute.plugins.logging import LoggingPlugin

class PluginService(RoutedClass):
    api = Router(name="plugin").plug(LoggingPlugin())

    @route("api")
    def do_work(self):
        return "ok"

svc = PluginService()
result = svc.api.get("do_work")()  # Automatically logged
```

## Validating Arguments

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

Use Pydantic for automatic validation:

```bash
pip install smartroute[pydantic]
```

```python
from smartroute.plugins.pydantic import PydanticPlugin

class ValidateService(RoutedClass):
    api = Router(name="validate").plug(PydanticPlugin())

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
