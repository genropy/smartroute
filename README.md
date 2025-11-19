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

**SmartRoute** is a fully runtime routing engine that lets you expose Python methods as "endpoints" (CLI tools, orchestrators, internal services) without global blueprints or shared registries. Each instance creates its own routers, can attach child routers, configure plugins, and provides ready-to-use runtime introspection. It's the successor to SmartSwitch, preserving the core idea of method "switching" but with a simpler design and no compatibility layers.

Use SmartRoute when you need to:

- Compose internal services with many handlers (application APIs, orchestrators, CLI automation)
- Build dashboards/portals that register routers dynamically and need runtime introspection
- Extend handler behavior with plugins (logging, validation, audit trails)

SmartRoute provides a consistent, well-tested foundation for these patterns.

## Key Features

1. **Instance-scoped routers** – Each object instantiates its own routers (`Router(self, ...)`) with isolated state.
2. **Friendly registration** – `@route(...)` accepts explicit names, auto-strips prefixes, and supports custom metadata.
3. **Simple hierarchies** – `add_child("child1, child2")` connects child routers with dotted path access (`parent.api.get("child.method")`).
4. **Plugin pipeline** – `BasePlugin` provides `on_decore`/`wrap_handler` hooks and plugins inherit from parents automatically.
5. **Runtime configuration** – `routedclass.configure()` applies global or per-handler overrides with wildcards and returns reports (`"?"`).
6. **Optional extras** – `logging`, `pydantic` plugins and SmartAsync wrapping are opt-in; the core has minimal dependencies.
7. **Full coverage** – The package is 100% covered by Pytest (65 scenarios) with no hidden compatibility layers.

## Quick Example

<!-- test: test_switcher_basic.py::test_orders_quick_example -->

```python
from smartroute import RoutedClass, Router, route

class OrdersAPI(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(self, name="orders")

    @route("orders")
    def list(self):
        return ["order-1", "order-2"]

    @route("orders")
    def retrieve(self, ident: str):
        return f"{self.label}:{ident}"

    @route("orders")
    def create(self, payload: dict):
        return {"status": "created", **payload}

orders = OrdersAPI("acme")
print(orders.api.get("list")())        # ["order-1", "order-2"]
print(orders.api.get("retrieve")("42"))  # acme:42

overview = orders.api.members()
print(overview["handlers"].keys())      # dict_keys(['list', 'retrieve', 'create'])
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
- **`obj.routedclass`** – Proxy exposed by every RoutedClass that provides helpers like `get_router(...)` and `configure(...)` for managing routers/plugins without polluting the instance namespace.

## Pattern Highlights

- **Explicit naming + prefixes** – `@route("api", name="detail")` and `Router(prefix="handle_")` separate method names from public route names ([`test_prefix_and_name_override`](tests/test_switcher_basic.py)).
- **Attribute-level hierarchies** – `self.api.add_child("sales, finance")` connects child routers by discovering them from instance attributes ([`test_dashboard_hierarchy`](tests/test_switcher_basic.py)).
- **Bulk registration** – Dictionaries or iterables allow connecting routers from external structures ([`test_add_child_accepts_mapping_for_named_children`](tests/test_switcher_basic.py)).
- **Built-in and custom plugins** – `Router(...).plug("logging")`, `Router(...).plug("pydantic")` or custom plugins (`llm-docs/PATTERNS.md#pattern-12-custom-plugin-development`).
- **Runtime configuration** – `routedclass.configure("api:logging/foo", enabled=False)` applies targeted overrides with wildcards or batch updates (see dedicated guide).
- **Dynamic registration** – `router.add_entry(handler)` or `router.add_entry("*")` allow publishing handlers computed at runtime (`tests/test_router_runtime_extras.py`).

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

SmartRoute is currently in **alpha** (v0.4.1). The core API is stable with complete documentation.

- **Test Coverage**: 100% (66 tests, 724 statements)
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
