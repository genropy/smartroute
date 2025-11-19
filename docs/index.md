# SmartRoute

```{image} assets/logo.png
:alt: SmartRoute Logo
:width: 200px
:align: center
```

**SmartRoute** is an instance-scoped routing engine for Python that enables dynamic method dispatch through a plugin-based architecture. It's the successor to SmartSwitch, designed with instance isolation and composability at its core.

## What is SmartRoute?

SmartRoute allows you to organize and dispatch method calls dynamically based on string identifiers (routes). Each object instance gets its own isolated router with independent plugin stacks, making it ideal for building modular, extensible services where behavior can be customized per-instance without global state.

## What Does SmartRoute Do?

SmartRoute provides:

- **Dynamic method dispatch**: Call methods by string name (`router.get("method_name")`)
- **Instance isolation**: Each object has its own `BoundRouter` with independent configuration
- **Hierarchical routing**: Build nested router trees with dotted path access (`root.api.get("users.list")`)
- **Plugin system**: Extend behavior with composable plugins (logging, validation, etc.)
- **Plugin inheritance**: Child routers automatically inherit parent plugins

## Key Features

- **Instance-scoped routers**  Every object gets an isolated `BoundRouter` with its own plugin stack
- **Hierarchical organization**  Build router trees with `add_child()` and dotted path traversal
- **Composable plugins**  Hook into decoration and handler execution with `BasePlugin`
- **Plugin inheritance**  Plugins propagate automatically from parent to child routers
- **Flexible registration**  Use `@route` decorator with aliases, prefixes, and custom names
- **Runtime configuration**  Enable/disable plugins per-handler at runtime
- **SmartAsync support**  Optional integration with async execution
- **High test coverage**  >95% statement coverage with comprehensive edge case tests

## Quick Example

<!-- test: test_switcher_basic.py::test_instance_bound_methods_are_isolated -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L112-L119)

```python
from smartroute.core import RoutedClass, Router, route

class Service(RoutedClass):
    api = Router(name="service")

    def __init__(self, label: str):
        self.label = label

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
- **Migrating from SmartSwitch?** See the migration guide (coming soon)
- **Building plugins?** Read the [Plugin Development Guide](guide/plugins.md)
- **Need examples?** Check the [examples directory](https://github.com/genropy/smartroute/tree/main/examples)

## Project Status

SmartRoute is currently in **alpha** (v0.1.0). The core API is stable, but documentation and additional plugins are still being developed.

- **Test Coverage**: >95%
- **Python Support**: 3.10, 3.11, 3.12
- **License**: MIT

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](https://github.com/genropy/smartroute/blob/main/CONTRIBUTING.md) for guidelines.

## Indices and Tables

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`
