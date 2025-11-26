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

### Publish-ready plugin (ecosystem)

The built-in scope/channel plugin was moved out of the core. To attach scopes and channel policies when publishing, install SmartPublisher and plug its PublishPlugin:

```python
from smartpublisher.smartroute_plugins.publish import PublishPlugin
from smartroute import Router

router = Router(self, name="api").plug("publish")  # import registers the plugin
```

This keeps SmartRoute lean while SmartPublisher owns the canonical scope/channel rules. Projects that do not publish externally can skip the plugin entirely.

## Creating Custom Plugins

Extend `BasePlugin` and implement hooks. Every plugin **must** define two class attributes:

- `plugin_code` - unique identifier used for registration (e.g. `"logging"`)
- `plugin_description` - human-readable description

### Basic Plugin Structure

```python
from smartroute import BasePlugin, Router, RoutedClass, route

class CapturePlugin(BasePlugin):
    # Required class attributes
    plugin_code = "capture"
    plugin_description = "Captures handler calls for testing"

    # Optional: custom instance state (use __slots__ for efficiency)
    __slots__ = ("calls",)

    def __init__(self, router, **config):
        self.calls = []
        super().__init__(router, **config)

    def configure(self, enabled: bool = True):
        """Define accepted configuration parameters.

        The method body can be empty - the wrapper handles storage.
        Parameters become the configuration schema validated by Pydantic.
        """
        pass

    def on_decore(self, router, func, entry):
        """Called once when handler is registered."""
        entry.metadata["capture"] = True

    def wrap_handler(self, router, entry, call_next):
        """Called to build middleware chain."""
        def wrapper(*args, **kwargs):
            self.calls.append(entry.name)
            return call_next(*args, **kwargs)
        return wrapper

# Register plugin globally
Router.register_plugin(CapturePlugin)

# Use in service
class PluginService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("capture")

    @route("api")
    def do_work(self):
        return "ok"

svc = PluginService()
result = svc.api.get("do_work")()
assert svc.api.capture.calls == ["do_work"]
```

### Constructor Signature

The constructor **must** accept `router` as first argument and `**config`:

```python
def __init__(self, router, **config):
    # 1. Initialize your own state FIRST
    self.my_state = []

    # 2. Call super().__init__ which:
    #    - Sets self.name = self.plugin_code
    #    - Stores self._router = router
    #    - Initializes the config store
    #    - Calls self.configure(**config)
    super().__init__(router, **config)
```

**Important**: Initialize your state *before* calling `super().__init__()` because the parent constructor calls `configure()` which might need your state.

## Plugin Hooks

SmartRoute plugins can override these methods:

| Hook | When Called | Purpose | Required |
|------|-------------|---------|----------|
| `configure()` | At plugin init and runtime | Define configuration schema | No |
| `on_decore()` | Handler registration | Add metadata, validate signatures | No |
| `wrap_handler()` | Handler invocation | Middleware (logging, auth, etc.) | No |
| `allow_entry()` | `members()` introspection | Filter visible handlers | No |
| `entry_metadata()` | `members()` introspection | Add plugin metadata to output | No |

**All hooks are optional.** Override only what you need. A minimal plugin can have just `plugin_code` and `plugin_description` with no hooks.

### configure(**kwargs)

Define accepted configuration parameters. The method signature becomes the configuration schema, validated by Pydantic.

```python
def configure(
    self,
    enabled: bool = True,
    threshold: int = 10,
    level: str = "info"
):
    """Body can be empty - the wrapper handles storage."""
    pass
```

The wrapper added by `__init_subclass__` automatically:

- Parses `flags` string (e.g. `"enabled,before:off"`) into booleans
- Routes to `_target` (`"_all_"` for router-level, `"handler_name"` for per-handler)
- Validates parameters via Pydantic's `@validate_call`
- Writes config to the router's store

### on_decore(router, func, entry)

Called once when a handler is registered.

**Parameters**:

- `router` - The Router instance
- `func` - The original method
- `entry` - MethodEntry with `name`, `func`, `router`, `plugins`, `metadata`

**Use for**:

- Adding metadata to handlers
- Validating handler signatures
- Building handler indexes
- Pre-computing handler information (e.g., Pydantic models)

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

Called to build the middleware chain. Return a callable that wraps `call_next`.

**Parameters**:

- `router` - The Router instance
- `entry` - MethodEntry for the handler
- `call_next` - Callable to invoke next plugin or handler

**Returns**: Wrapper function with same signature as `call_next`

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
            print(f"{entry.name} took {duration:.3f}s")

            return result
        except Exception as e:
            print(f"{entry.name} failed: {e}")
            raise

    return wrapper
```

### allow_entry(router, entry, **filters)

Control handler visibility during introspection (`members()`).

**Parameters**:

- `router` - The Router instance
- `entry` - MethodEntry being checked
- `**filters` - Filter criteria passed to `members()` (e.g., `scopes`, `channel`)

**Returns**: `True` to include, `False` to exclude, `None` to defer to other plugins

**Example**:

```python
def allow_entry(self, router, entry, scopes=None, **filters):
    # Only show admin handlers to admin scope
    if entry.metadata.get("admin_only"):
        if scopes and "admin" in scopes:
            return True
        return False
    return None  # defer to other plugins
```

### entry_metadata(router, entry)

Provide plugin-specific metadata for `members()` output.

**Parameters**:

- `router` - The Router instance
- `entry` - MethodEntry being described

**Returns**: Dict stored in `plugins[plugin_name]["metadata"]`

**Example**:

```python
def entry_metadata(self, router, entry):
    cfg = self.configuration(entry.name)
    return {
        "enabled": cfg.get("enabled", True),
        "threshold": cfg.get("threshold", 10),
    }
```

The result appears in `members()` output:

```python
{
    "entries": {
        "handler_name": {
            "plugins": {
                "my_plugin": {
                    "config": {"enabled": True, "threshold": 10},
                    "metadata": {"enabled": True, "threshold": 10}
                }
            }
        }
    }
}
```

## Plugin Registration

Register plugins globally with `Router.register_plugin()`:

```python
class CustomPlugin(BasePlugin):
    plugin_code = "custom"
    plugin_description = "My custom plugin"

    def __init__(self, router, **config):
        super().__init__(router, **config)

# Register once - uses plugin_code as the name
Router.register_plugin(CustomPlugin)

# Now available in all routers
class Service(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("custom")
```

**Registration rules**:

- Plugin class must extend `BasePlugin`
- Plugin class must define `plugin_code` (used as registration name)
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

Each router instance gets independent plugin state:

```python
class CapturePlugin(BasePlugin):
    plugin_code = "capture"
    plugin_description = "Captures handler calls"

    __slots__ = ("calls",)

    def __init__(self, router, **config):
        self.calls = []  # Per-instance state
        super().__init__(router, **config)

    def wrap_handler(self, router, entry, call_next):
        def wrapper(*args, **kwargs):
            self.calls.append(entry.name)
            return call_next(*args, **kwargs)
        return wrapper

Router.register_plugin(CapturePlugin)

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

## Plugin Configuration

Plugins define their configuration schema via the `configure()` method. The configuration system provides:

- **Router-level defaults**: Apply to all handlers
- **Per-handler overrides**: Target specific handlers
- **Flags shorthand**: Boolean options as comma-separated string
- **Pydantic validation**: Type checking on all parameters

### Defining Configuration

```python
class MyPlugin(BasePlugin):
    plugin_code = "my_plugin"
    plugin_description = "Example plugin with configuration"

    def __init__(self, router, **config):
        super().__init__(router, **config)

    def configure(
        self,
        enabled: bool = True,
        level: str = "info",
        threshold: int = 10
    ):
        """Define accepted parameters. Body can be empty."""
        pass
```

### Reading Configuration

Use `configuration(method_name)` to read merged config (base + per-handler):

```python
def wrap_handler(self, router, entry, call_next):
    def wrapper(*args, **kwargs):
        # Get merged config for this handler
        cfg = self.configuration(entry.name)

        if not cfg.get("enabled", True):
            return call_next(*args, **kwargs)

        level = cfg.get("level", "info")
        # ... use configuration
        return call_next(*args, **kwargs)
    return wrapper
```

### Configuring at Runtime

```python
# At plugin attachment (initial config)
router.plug("my_plugin", enabled=True, level="debug")

# Or via the plugin instance
router.my_plugin.configure(threshold=20)

# Per-handler config
router.my_plugin.configure(_target="critical_handler", level="error")

# Multiple handlers
router.my_plugin.configure(_target="handler1,handler2", enabled=False)

# Using flags shorthand
router.my_plugin.configure(flags="enabled,log:off")
```

### The `_target` Parameter

- `"_all_"` (default): Router-level config, applies to all handlers
- `"handler_name"`: Config for specific handler only
- `"h1,h2,h3"`: Apply same config to multiple handlers

### The `flags` Parameter

Shorthand for boolean options:

```python
# These are equivalent:
router.my_plugin.configure(enabled=True, before=True, after=False)
router.my_plugin.configure(flags="enabled,before,after:off")
```

Format: `"flag1,flag2:off,flag3:on"` - bare names are `True`, `:off` is `False`.

## Complete Example: Authorization Plugin

Real-world plugin with configuration and state:

```python
import inspect
from smartroute import BasePlugin, Router, RoutedClass, route

class AuthPlugin(BasePlugin):
    plugin_code = "auth"
    plugin_description = "Authentication and authorization plugin"

    def __init__(self, router, **config):
        super().__init__(router, **config)

    def configure(
        self,
        enabled: bool = True,
        required: bool = True
    ):
        """Configure auth requirements."""
        pass

    def on_decore(self, router, func, entry):
        """Extract required roles from docstring."""
        doc = inspect.getdoc(func) or ""
        if "@roles:" in doc:
            roles = doc.split("@roles:")[1].split()[0].split(",")
            entry.metadata["required_roles"] = roles

    def wrap_handler(self, router, entry, call_next):
        def wrapper(*args, **kwargs):
            cfg = self.configuration(entry.name)

            if not cfg.get("enabled", True):
                return call_next(*args, **kwargs)

            # Extract user from first arg (assuming request object)
            request = args[0] if args else None
            user = getattr(request, "user", None)

            # Check authentication
            if cfg.get("required", True) and not user:
                raise PermissionError("Authentication required")

            # Check authorization
            required_roles = entry.metadata.get("required_roles", [])
            if required_roles:
                user_roles = getattr(user, "roles", [])
                if not any(role in user_roles for role in required_roles):
                    raise PermissionError(f"Requires roles: {required_roles}")

            return call_next(*args, **kwargs)

        return wrapper

    def entry_metadata(self, router, entry):
        """Expose auth config in members() output."""
        cfg = self.configuration(entry.name)
        return {
            "enabled": cfg.get("enabled", True),
            "required": cfg.get("required", True),
            "roles": entry.metadata.get("required_roles", []),
        }

# Register plugin
Router.register_plugin(AuthPlugin)

# Use in service
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

# Configure: disable auth requirement for public endpoints
api.api.auth.configure(_target="public_endpoint", required=False)
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
# ✅ Good: Sensible defaults in configure() signature
def configure(
    self,
    enabled: bool = True,      # Enabled by default
    level: str = "info",       # Reasonable default
    strict: bool = False       # Permissive by default
):
    pass
```

**Error handling**:

```python
def wrap_handler(self, router, entry, call_next):
    def wrapper(*args, **kwargs):
        try:
            return call_next(*args, **kwargs)
        except Exception as e:
            # Log error but don't suppress unless configured
            cfg = self.configuration(entry.name)
            if cfg.get("suppress_errors", False):
                return None
            raise
    return wrapper
```

## Next Steps

- **[Plugin Configuration](plugin-configuration.md)** - Configure plugins at runtime
- **[Built-in Plugins API](../api/plugins.md)** - LoggingPlugin and PydanticPlugin reference
- **[Hierarchies](hierarchies.md)** - Plugin inheritance in hierarchies
- **[API Reference](../api/reference.md)** - Complete API documentation
