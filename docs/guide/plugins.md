# Plugin Development

Create custom plugins to extend SmartRoute with reusable functionality like logging, validation, caching, and authorization.

## Overview

Plugins in SmartRoute:

- **Extend behavior** without modifying handler code
- **Per-instance state** - each router gets independent plugin instances
- **Two hooks**: `on_decore()` for metadata, `wrap_handler()` for execution
- **Configurable** - runtime configuration via `routedclass.configure()`
- **Composable** - multiple plugins work together automatically
- **Inherit automatically** - parent plugins apply to child routers

## Built-in Plugins

SmartRoute includes two production-ready plugins:

**LoggingPlugin** (`logging`):

```python
from smartroute import RoutedClass, Router, route

class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def process(self, data: str):
        return f"processed:{data}"

svc = Service()
result = svc.api.get("process")("test")  # Automatically logged
```

**PydanticPlugin** (`pydantic`):

```python
class ValidatedService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("pydantic")

    @route("api")
    def concat(self, text: str, number: int = 1) -> str:
        return f"{text}:{number}"

svc = ValidatedService()
svc.api.get("concat")("hello", 3)  # ✅ Valid
# svc.api.get("concat")(123, "oops")  # ❌ ValidationError
```

See [Quick Start - Plugins](../quickstart.md#adding-plugins) for more examples.

## Creating Custom Plugins

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L41-L69)

Extend `BasePlugin` and implement hooks:

```python
from smartroute import BasePlugin, Router, RoutedClass, route

class CapturePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="capture")
        self.calls = []

    def on_decore(self, router, func, entry):
        """Called when handler is registered."""
        entry.metadata["capture"] = True

    def wrap_handler(self, router, entry, call_next):
        """Called when handler is invoked."""
        def wrapper(*args, **kwargs):
            self.calls.append("wrap")
            return call_next(*args, **kwargs)
        return wrapper

# Register plugin globally
Router.register_plugin("capture", CapturePlugin)

# Use in service
class PluginService(RoutedClass):
    def __init__(self):
        self.touched = False
        self.api = Router(self, name="api").plug("capture")

    @route("api")
    def do_work(self):
        self.touched = True
        return "ok"

svc = PluginService()
result = svc.api.get("do_work")()
assert result == "ok"
assert svc.touched is True
assert svc.api.capture.calls == ["wrap"]
```

**Key points**:

- `BasePlugin.__init__(name="...")` sets plugin name
- `on_decore()` modifies handler metadata at registration time
- `wrap_handler()` intercepts handler execution
- Each router instance gets independent plugin state

## Plugin Hooks

### on_decore(router, func, entry)

Called once when a handler is registered.

**Parameters**:

- `router` - The Router instance
- `func` - The original method
- `entry` - MethodEntry with `name`, `func`, `metadata`

**Use for**:

- Adding metadata to handlers
- Validating handler signatures
- Building handler indexes
- Pre-computing handler information

**Example**:

```python
def on_decore(self, router, func, entry):
    # Add timestamp to metadata
    entry.metadata["registered_at"] = time.time()

    # Validate signature
    sig = inspect.signature(func)
    if "user_id" not in sig.parameters:
        raise ValueError(f"{entry.name} must have user_id parameter")
```

### wrap_handler(router, entry, call_next)

Called every time a handler is invoked.

**Parameters**:

- `router` - The Router instance
- `entry` - MethodEntry for the handler
- `call_next` - Callable to invoke next plugin or handler

**Returns**: Wrapper function that will be called instead of handler

**Use for**:

- Logging and monitoring
- Authorization checks
- Input/output transformation
- Caching
- Error handling

**Example**:

```python
def wrap_handler(self, router, entry, call_next):
    def wrapper(*args, **kwargs):
        # Before handler
        start = time.time()

        try:
            # Call handler (or next plugin)
            result = call_next(*args, **kwargs)

            # After handler
            duration = time.time() - start
            self.log(f"{entry.name} took {duration:.3f}s")

            return result
        except Exception as e:
            self.log(f"{entry.name} failed: {e}")
            raise

    return wrapper
```

## Plugin Registration

<!-- test: test_router_edge_cases.py::test_register_plugin_validates -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_router_edge_cases.py#L205-L218)

Register plugins globally with `Router.register_plugin()`:

```python
class CustomPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="custom")

# Register once, use everywhere
Router.register_plugin("custom", CustomPlugin)

# Now available in all routers
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("custom")
```

**Registration rules**:

- Name must be non-empty string
- Plugin class must extend `BasePlugin`
- Cannot re-register same name with different class
- Registration is global across all routers

**Check available plugins**:

```python
# List all registered plugins
plugins = Router.available_plugins()
assert "logging" in plugins
assert "pydantic" in plugins
assert "custom" in plugins
```

## Per-Instance State

<!-- test: test_switcher_basic.py::test_plugins_are_per_instance_and_accessible -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L200-L208)

Each router instance gets independent plugin state:

```python
class CapturePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="capture")
        self.calls = []  # Per-instance state

    def wrap_handler(self, router, entry, call_next):
        def wrapper(*args, **kwargs):
            self.calls.append(entry.name)
            return call_next(*args, **kwargs)
        return wrapper

Router.register_plugin("capture", CapturePlugin)

# Each instance is isolated
svc1 = PluginService()
svc2 = PluginService()

svc1.api.get("do_work")()
assert svc1.api.capture.calls == ["do_work"]
assert svc2.api.capture.calls == []  # Independent state
```

**Benefits**:

- No global state pollution
- Thread-safe by default
- Independent configuration per instance
- Easy testing with isolated state

## Runtime Data

<!-- test: test_switcher_basic.py::test_plugin_enable_disable_runtime_data -->

[From test](https://github.com/genropy/smartroute/blob/main/tests/test_switcher_basic.py#L348-L362)

Store temporary data during handler execution:

```python
class TogglePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="toggle")

    def wrap_handler(self, router, entry, call_next):
        def wrapper(*args, **kwargs):
            # Store runtime data
            router.set_runtime_data(entry.name, self.name, "invoked", True)
            return call_next(*args, **kwargs)
        return wrapper

Router.register_plugin("toggle", TogglePlugin)

svc = ToggleService()
svc.api.get("handler")()

# Check runtime data
data = svc.api.get_runtime_data("handler", "toggle")
assert data["invoked"] is True
```

**Use cases**:

- Track invocation counts
- Store request context
- Capture timing information
- Debug plugin behavior

## Plugin Configuration

Plugins support runtime configuration. See [Plugin Configuration](plugin-configuration.md) for complete guide.

**Quick example**:

```python
class ConfigurablePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="configurable")
        # Default configuration
        self.set_config(enabled=True, level="info")

svc = MyService()

# Configure globally
svc.routedclass.configure("api:configurable/_all_", level="debug")

# Configure per handler
svc.routedclass.configure("api:configurable/critical_*", enabled=True, level="error")
```

## Complete Example: Authorization Plugin

Real-world plugin with configuration and state:

```python
class AuthPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="auth")
        self.set_config(
            enabled=True,
            required=True,
            roles=[]
        )

    def on_decore(self, router, func, entry):
        """Extract required roles from docstring or decorator."""
        import inspect
        doc = inspect.getdoc(func) or ""
        if "@roles:" in doc:
            roles = doc.split("@roles:")[1].split()[0].split(",")
            entry.metadata["required_roles"] = roles

    def wrap_handler(self, router, entry, call_next):
        def wrapper(*args, **kwargs):
            config = self.get_config(entry.name)

            if not config.get("enabled", True):
                return call_next(*args, **kwargs)

            # Extract user from first arg (assuming request object)
            request = args[0] if args else None
            user = getattr(request, "user", None)

            # Check authentication
            if config.get("required", True) and not user:
                raise PermissionError("Authentication required")

            # Check authorization
            required_roles = entry.metadata.get("required_roles", [])
            if required_roles:
                user_roles = getattr(user, "roles", [])
                if not any(role in user_roles for role in required_roles):
                    raise PermissionError(f"Requires roles: {required_roles}")

            return call_next(*args, **kwargs)

        return wrapper

# Register and use
Router.register_plugin("auth", AuthPlugin)

class API(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("auth")

    @route("api")
    def public_endpoint(self, request):
        """@roles:guest"""
        return "public data"

    @route("api")
    def admin_endpoint(self, request):
        """@roles:admin"""
        return "admin data"

api = API()

# Configure: disable auth for public endpoints
api.routedclass.configure("api:auth/public_*", required=False)
```

## Best Practices

**Single responsibility**:

```python
# ✅ Good: One plugin, one concern
class LoggingPlugin(BasePlugin): ...
class ValidationPlugin(BasePlugin): ...
class CachingPlugin(BasePlugin): ...

# ❌ Bad: One plugin doing everything
class EverythingPlugin(BasePlugin): ...
```

**Composition over complexity**:

```python
# ✅ Good: Multiple simple plugins
self.api = Router(self, name="api")\
    .plug("logging")\
    .plug("pydantic")\
    .plug("caching")\
    .plug("auth")

# ❌ Bad: One complex plugin
self.api = Router(self, name="api").plug("monolith")
```

**Configuration defaults**:

```python
# ✅ Good: Sensible defaults
def __init__(self):
    super().__init__(name="my_plugin")
    self.set_config(
        enabled=True,  # Enabled by default
        level="info",  # Reasonable default
        strict=False   # Permissive by default
    )
```

**Error handling**:

```python
def wrap_handler(self, router, entry, call_next):
    def wrapper(*args, **kwargs):
        try:
            return call_next(*args, **kwargs)
        except Exception as e:
            # Log error but don't suppress unless configured
            self.log_error(entry.name, e)
            if self.get_config(entry.name).get("suppress_errors", False):
                return None
            raise
    return wrapper
```

## Next Steps

- **[Plugin Configuration](plugin-configuration.md)** - Configure plugins at runtime
- **[Built-in Plugins API](../api/plugins.md)** - LoggingPlugin and PydanticPlugin reference
- **[Hierarchies](hierarchies.md)** - Plugin inheritance in hierarchies
- **[API Reference](../api/reference.md)** - Complete API documentation
