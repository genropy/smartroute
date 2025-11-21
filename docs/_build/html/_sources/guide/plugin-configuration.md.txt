# Plugin Configuration

Configure plugins at runtime through a unified API with support for global settings, per-handler overrides, and batch updates.

## Overview

SmartRoute provides `routedclass.configure()` for runtime plugin configuration with:

- **Target syntax**: `<router>:<plugin>/<selector>` format
- **Global configuration**: Apply to all handlers with `_all_`
- **Handler-specific overrides**: Target individual handlers
- **Glob patterns**: Match multiple handlers with wildcards
- **Batch updates**: Configure multiple targets in one call
- **Introspection**: Query configuration with `"?"`

## Target Syntax

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L284-L315)

A configuration target has three parts:

```text
<router_name>:<plugin_name>/<selector>
```

**Examples**:

- `api:logging/_all_` - Apply to all handlers in the logging plugin
- `api:logging/foo` - Apply only to the `foo` handler
- `api:logging/b*` - Apply to handlers matching glob pattern `b*`

**Selectors**:

- `_all_` (case-insensitive) - Global plugin settings
- Handler name - Specific handler (e.g., `foo`, `bar`)
- Glob pattern - Multiple handlers (e.g., `admin_*`, `*/detail`)

Glob patterns use `fnmatch` for matching.

## Basic Configuration

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L284-L315)

Configure plugins using keyword arguments:

```python
from smartroute import RoutedClass, Router, route

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
svc.routedclass.configure("api:logging/_all_", threshold=10)
assert svc.api.logging.get_config()["threshold"] == 10

# Handler-specific configuration
svc.routedclass.configure("api:logging/foo", enabled=False)
assert svc.api.logging.get_config("foo")["enabled"] is False

# Glob pattern configuration
svc.routedclass.configure("api:logging/b*", mode="strict")
assert svc.api.logging.get_config("bar")["mode"] == "strict"
```

**Configuration keys** depend on the plugin. Common keys:

- `enabled` - Enable/disable plugin for handler(s)
- `flags` - Plugin-specific flags
- `threshold`, `mode`, `level` - Plugin-specific settings

## Batch Updates

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L309-L315)

Configure multiple targets with a list of dictionaries:

```python
# JSON-friendly batch configuration
payload = [
    {"target": "api:logging/_all_", "flags": "trace"},
    {"target": "api:logging/foo", "limit": 5},
]

result = svc.routedclass.configure(payload)
assert len(result) == 2
assert svc.api.logging.get_config("foo")["limit"] == 5
```

**Each dictionary must have**:

- `target` key - Configuration target string
- Additional keys - Configuration options

**Returns**: List of configuration results (one per target)

**Use cases**:

- External configuration files (JSON, YAML)
- HTTP API endpoints
- CLI configuration commands
- Orchestration layers

## Introspection

<!-- test: test_router_edge_cases.py::test_routed_configure_question_lists_tree -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L318-L343)

Query the router and plugin structure with `"?"`:

```python
class Leaf(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def ping(self):
        return "leaf"

class Root(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")
        self.leaf = Leaf()
        self.api.add_child(self.leaf, name="leaf")

    @route("api")
    def root_ping(self):
        return "root"

svc = Root()

# Get full configuration tree
info = svc.routedclass.configure("?")
assert "api" in info
assert info["api"]["plugins"]
assert "leaf" in info["api"]["children"]
```

**Returns nested dictionary with**:

- Router names
- Attached plugins and their configurations
- Child routers
- Registered handlers

## Exposing Configuration API

<!-- test: test_router_edge_cases.py::test_routed_configure_updates_plugins_global_and_local -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L284-L315)

Create a dedicated configuration endpoint:

```python
class ConfigAPI(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")
        self.admin = Router(self, name="admin")

    @route("admin")
    def configure_plugin(self, target: str, **options):
        """Configure plugins via API endpoint."""
        result = self.routedclass.configure(target, **options)
        return {"status": "ok", "result": result}

config = ConfigAPI()

# Call via router
result = config.admin.get("configure_plugin")("api:logging/_all_", enabled=True)
assert result["status"] == "ok"
```

**Benefits**:

- External configuration without code changes
- Runtime adjustments
- API-driven configuration management
- Dynamic plugin tuning

## Error Handling

**Invalid targets raise exceptions**:

- `ValueError` - Malformed target syntax
- `AttributeError` - Router or plugin not found
- `KeyError` - Selector matches no handlers

**Validation**:

```python
# Router name cannot be empty
try:
    svc.routedclass.configure(":logging/_all_", enabled=True)
except ValueError:
    pass  # Expected

# Plugin must exist
try:
    svc.routedclass.configure("api:nonexistent/_all_", enabled=True)
except AttributeError:
    pass  # Expected

# Selector must match at least one handler
try:
    svc.routedclass.configure("api:logging/nonexistent", enabled=True)
except KeyError:
    pass  # Expected
```

## Best Practices

**Global defaults, specific overrides**:

```python
# Set defaults for all handlers
svc.routedclass.configure("api:logging/_all_", enabled=True, level="info")

# Override for specific handlers
svc.routedclass.configure("api:logging/debug_*", level="debug")
svc.routedclass.configure("api:logging/admin_*", enabled=False)
```

**Configuration from files**:

```python
import json

# Load from JSON configuration
with open("plugin_config.json") as f:
    config = json.load(f)

# Apply batch configuration
svc.routedclass.configure(config["plugins"])
```

**Gradual rollout**:

```python
# Enable new feature for test handlers only
svc.routedclass.configure("api:new_feature/test_*", enabled=True)

# Expand to all after validation
svc.routedclass.configure("api:new_feature/_all_", enabled=True)
```

## Next Steps

- **[Plugin Development](plugins.md)** - Create custom plugins
- **[Built-in Plugins](../api/plugins.md)** - LoggingPlugin and PydanticPlugin reference
- **[API Reference](../api/reference.md)** - Complete API documentation
