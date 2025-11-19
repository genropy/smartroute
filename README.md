# SmartRoute

<p align="center">
  <img src="docs/assets/logo.png" alt="SmartRoute Logo" width="200"/>
</p>

[![PyPI version](https://badge.fury.io/py/smartroute.svg)](https://badge.fury.io/py/smartroute)
[![Tests](https://github.com/genropy/smartroute/actions/workflows/test.yml/badge.svg)](https://github.com/genropy/smartroute/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/genropy/smartroute/branch/main/graph/badge.svg?token=71c0b591-018b-41cb-9fd2-dc627d14a519)](https://codecov.io/gh/genropy/smartroute)
[![Documentation](https://readthedocs.org/projects/smartroute/badge/?version=latest)](https://smartroute.readthedocs.io/en/latest/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**SmartRoute** is an instance-scoped routing engine for Python that enables dynamic method dispatch through a plugin-based architecture. It's the successor to SmartSwitch, designed with instance isolation and composability at its core.

## What is SmartRoute?

SmartRoute allows you to organize and dispatch method calls dynamically based on string identifiers (routes). Each object instance gets its own isolated router with independent plugin stacks, making it ideal for building modular, extensible services where behavior can be customized per-instance without global state.

## Key Features

- **Instance-scoped routers** – Instantiate routers inside `__init__` with `Router(self, ...)` so every object gets its own configuration
- **Hierarchical organization** – Build router trees with `add_child()` and dotted path traversal (`root.api.get("users.list")`)
- **Composable plugins** – Hook into decoration and handler execution with `BasePlugin` (logging, validation, metrics)
- **Plugin inheritance** – Plugins propagate automatically from parent to child routers
- **Flexible registration** – Use `@route` decorator with aliases, prefixes, and custom names
- **Runtime configuration** – Configure plugins at runtime with `routedclass.configure()` using target syntax
- **Per-handler plugin config** – Enable/disable plugins per-handler with glob patterns and selective targeting
- **SmartAsync support** – Optional integration with async execution
- **100% test coverage** – Complete statement coverage with 59 comprehensive tests

## Quick Example

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

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

## Installation

```bash
pip install smartroute
```

For development:

```bash
git clone https://github.com/genropy/smartroute.git
cd smartroute
pip install -e ".[all]"
```

To use the Pydantic plugin:

```bash
pip install smartroute[pydantic]
```

## Core Concepts

- **`Router`** – Runtime router bound directly to an object via `Router(self, name=\"api\")`
- **`@route(\"name\")`** – Decorator that marks bound methods for the router with the matching name
- **`RoutedClass`** – Mixin that tracks routers per instance and exposes the `routedclass` proxy
- **`BasePlugin`** – Base class for creating plugins with `on_decore` and `wrap_handler` hooks
- **`obj.routedclass`** – Proxy esposto da ogni RoutedClass che offre helper come `get_router(...)` e `configure(...)` per gestire router/plugin senza inquinare il namespace dell’istanza.

## Examples

### Basic Routing with Aliases

<!-- test: test_switcher_basic.py::test_prefix_and_alias_resolution -->

```python
from smartroute import RoutedClass, Router, route

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
assert sub.routes.get("list")() == "users:list"
assert sub.routes.get("detail")(10) == "users:detail:10"
```

### Hierarchical Routers

<!-- test: test_switcher_basic.py::test_hierarchical_binding_with_instances -->

```python
class RootAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        users = SubService("users")
        products = SubService("products")

        self.api.add_child(users, name="users")
        self.api.add_child(products, name="products")

root = RootAPI()
assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(5) == "products:detail:5"
```

### Manual Entry Registration

Routers can register handlers dynamically with `add_entry()` for patterns that don't rely on decorators:

```python
class DynamicService(RoutedClass):
    def __init__(self):
        self.dynamic = Router(self, name="dynamic", auto_discover=False)
        self.dynamic.add_entry(self.handle_alpha)
        self.dynamic.add_entry("handle_beta")

    def handle_alpha(self):
        return "alpha"

    def handle_beta(self):
        return "beta"

svc = DynamicService()
assert svc.dynamic.get("handle_alpha")() == "alpha"
assert svc.dynamic.get("handle_beta")() == "beta"
```

### Bulk Child Registration

<!-- test: test_switcher_basic.py::test_add_child_accepts_mapping_for_named_children -->

```python
class RootAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        self.users = SubService("users")
        self.products = SubService("products")

        # Register multiple children via dict
        self.api.add_child({
            "users": self.users,
            "products": self.products
        })

root = RootAPI()
assert root.api.get("users.list")() == "users:list"
```

### Plugins

Built-in plugins (`logging`, `pydantic`) are pre-registered and can be used by name:

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

```python
class PluginService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def do_work(self):
        return "ok"

svc = PluginService()
result = svc.api.get("do_work")()  # Logged automatically
```

### Pydantic Validation

<!-- test: test_pydantic_plugin.py::test_pydantic_plugin_accepts_valid_input -->

```python
class ValidateService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("pydantic")

    @route("api")
    def concat(self, text: str, number: int = 1) -> str:
        return f"{text}:{number}"

svc = ValidateService()
assert svc.api.get("concat")("hello", 3) == "hello:3"
assert svc.api.get("concat")("hi") == "hi:1"  # Default works
```

### Custom Plugins

Create your own plugins by subclassing `BasePlugin`:

```python
from smartroute import RoutedClass, Router, route
from smartroute.core import BasePlugin, MethodEntry  # Not public API

class MetricsPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="metrics")
        self.call_counts = {}

    def on_decore(self, router, func, entry: MethodEntry):
        """Called during route registration"""
        self.call_counts[entry.name] = 0

    def wrap_handler(self, router, entry: MethodEntry, call_next):
        """Wrap handler execution"""
        def wrapper(*args, **kwargs):
            self.call_counts[entry.name] += 1
            return call_next(*args, **kwargs)
        return wrapper

# Register your plugin
Router.register_plugin("metrics", MetricsPlugin)

# Use it like built-in plugins
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("metrics")

    @route("api")
    def work(self):
        return "done"

svc = Service()
svc.api.get("work")()
print(svc.api.metrics.call_counts)  # {"work": 1}
```

See [llm-docs/PATTERNS.md#pattern-12-custom-plugin-development](llm-docs/PATTERNS.md) for more examples.

### Plugin Configuration

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

Configure plugins at runtime with target syntax:

```python
class ConfService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def foo(self):
        return "foo"

    @route("api")
    def bar(self):
        return "bar"

svc = ConfService()

# Global configuration - applies to all handlers
svc.routedclass.configure("api:logging/_all_", level="debug")

# Handler-specific configuration
svc.routedclass.configure("api:logging/foo", enabled=False)

# Glob pattern configuration
svc.routedclass.configure("api:logging/b*", level="info")
```

See [Plugin Configuration Guide](docs/guide/plugin-configuration.md) for complete documentation.

## Documentation

- **[Full Documentation](https://smartroute.readthedocs.io/)** – Complete guides, tutorials, and API reference
- **[Quick Start](docs/quickstart.md)** – Get started in 5 minutes
- **[LLM Reference](llm-docs/README.md)** – Token-optimized reference for AI code generation
- **[API Details](llm-docs/API-DETAILS.md)** – Complete API reference generated from tests
- **[Usage Patterns](llm-docs/PATTERNS.md)** – Common patterns extracted from test suite

## Testing

SmartRoute achieves 100% statement coverage with 59 comprehensive tests:

```bash
PYTHONPATH=src pytest --cov=src/smartroute --cov-report=term-missing
```

All examples in documentation are verified by the test suite and linked with test anchors.

## Repository Structure

```text
smartroute/
├── src/smartroute/
│   ├── core/               # Core router implementation
│   │   ├── router.py       # Router runtime implementation
│   │   ├── decorators.py   # @route and @routers decorators
│   │   └── base.py         # BasePlugin and MethodEntry
│   └── plugins/            # Built-in plugins
│       ├── logging.py      # LoggingPlugin
│       └── pydantic.py     # PydanticPlugin
├── tests/                  # Test suite (>95% coverage)
│   ├── test_switcher_basic.py        # Core functionality
│   ├── test_router_edge_cases.py     # Edge cases
│   ├── test_plugins_new.py           # Plugin system
│   └── test_pydantic_plugin.py       # Pydantic validation
├── docs/                   # Human documentation (Sphinx)
├── llm-docs/              # LLM-optimized documentation
└── examples/              # Example implementations
```

## Project Status

SmartRoute is currently in **alpha** (v0.4.0). The core API is stable with complete documentation.

- **Test Coverage**: 100% (59 tests, 707 statements)
- **Python Support**: 3.10, 3.11, 3.12
- **License**: MIT

## Current Limitations

- **Instance methods only** – Routers assume decorated functions are bound methods (no static/class method or free function support)
- **No SmartAsync plugin** – `get(..., use_smartasync=True)` is optional but there's no dedicated SmartAsync plugin
- **Minimal plugin system** – Intentionally simple; advanced features (e.g., Pydantic declarative config) must be added manually

## Roadmap

- ✅ Complete Sphinx documentation with tutorials and API reference
- Additional plugins (async, storage, audit trail, metrics)
- Benchmarks and performance comparison
- Example applications and use cases

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

SmartRoute is the successor to SmartSwitch, designed with lessons learned from production use.
