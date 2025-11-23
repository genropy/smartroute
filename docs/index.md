# SmartRoute

```{image} assets/logo.png
:alt: SmartRoute Logo
:width: 200px
:align: center
```

**SmartRoute** is an instance-scoped routing engine for Python that enables dynamic method dispatch through a plugin-based architecture.

## What is SmartRoute?

SmartRoute allows you to organize and dispatch method calls dynamically based on string identifiers (routes). Each object instance gets its own isolated router with independent plugin stacks, making it ideal for building modular, extensible services where behavior can be customized per-instance without global state.

## What Does SmartRoute Do?

SmartRoute provides:

- **Dynamic method dispatch**: Call methods by string name (`router.get("method_name")`)
- **Instance isolation**: Instantiate routers inside `__init__` with `Router(self, ...)` so each object tracks its own configuration
- **Hierarchical routing**: Build nested router trees with dotted path access (`root.api.get("users.list")`)
- **Plugin system**: Extend behavior with composable plugins (logging, validation, etc.)
- **Plugin inheritance**: Child routers automatically inherit parent plugins

## Key Features

- **Instance-scoped routers** - Every object gets an isolated router with its own plugin stack
- **Hierarchical organization** - Build router trees with `attach_instance()` and dotted path traversal
- **Composable plugins** - Hook into decoration and handler execution with `BasePlugin`
- **Plugin inheritance** - Plugins propagate automatically from parent to child routers
- **Flexible registration** - Use `@route` decorator with prefixes, metadata, and explicit names
- **Runtime configuration** - Configure plugins with `routedclass.configure()` using target syntax
- **SmartAsync support** - Optional integration with async execution
- **100% test coverage** - Comprehensive test suite with 78 tests covering 900 statements

## Quick Example

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L131-L138)

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

## Documentation Sections

```{toctree}
:maxdepth: 2
:caption: Getting Started

installation
quickstart
FAQ
```

```{toctree}
:maxdepth: 2
:caption: User Guide

guide/basic-usage
guide/plugins
guide/plugin-configuration
guide/hierarchies
guide/best-practices
```

```{toctree}
:maxdepth: 2
:caption: Reference

api/reference
api/plugins
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

## Next Steps

- **New to SmartRoute?** Start with the [Quick Start](quickstart.md)
- **Have questions?** Check the [FAQ](FAQ.md) for common questions and answers
- **Building plugins?** Read the [Plugin Development Guide](guide/plugins.md)
- **Need examples?** Check the [examples directory](https://github.com/genropy/smartroute/tree/main/examples)

## Project Status

SmartRoute is currently in **beta** (v0.6.0). The core API is stable with complete documentation.

- **Test Coverage**: 100% (78 tests, 900 statements)
- **Python Support**: 3.10, 3.11, 3.12
- **License**: MIT

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](https://github.com/genropy/smartroute/blob/main/CONTRIBUTING.md) for guidelines.

## Indices and Tables

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`
