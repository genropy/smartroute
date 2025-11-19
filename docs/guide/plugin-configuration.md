# Plugin Configuration API

SmartRoute plugins can now be configured at runtime through a single, uniform entry point.
This document introduces the `routedclass.configure()` helper, the target syntax,
and examples for batch updates.

## Target Syntax

A configuration target has the form:

```
<router_name>:<plugin_name>/<selector>
```

Examples:

- `api:logging/_all_` → apply to every handler within the `logging` plugin attached to router `api`.
- `reports:pydantic/orders.detail` → apply only to the `orders.detail` handler.
- `admin:deny/users.*,orders.*` → apply to any handler whose dotted path matches the glob(s).

Selectors support:

- `_all_` (case-insensitive) for global settings.
- Comma-separated list of handler paths (`foo.bar,baz.qux`).
- Simple glob patterns (`admin_*`, `*/detail`). Globs are resolved with `fnmatch`.

## API: `routedclass.configure()`

```python
class AdminAPI(RoutedClass):
    api = Router(name="api").plug("logging")

svc = AdminAPI()

# Enable two logging hooks globally
svc.routedclass.configure("api:logging/_all_", flags="before,after")

# Restrict logging to detail handlers only
svc.routedclass.configure("api:logging/orders.detail,users.detail", enabled=True, level="debug")

# Disable logging for any handler that matches admin_*
svc.routedclass.configure("api:logging/admin_*", enabled=False)
```

Rules:

1. `name:path` identifies the router to inspect (uses `get_router()` internally).
2. `plugin_name` must refer to an attached plugin. Built-ins `logging` and `pydantic` are pre-registered.
3. Keyword arguments (`flags`, `level`, `enabled`, etc.) map to plugin configuration keys.
4. When the selector is `_all_`, SmartRoute updates the global plugin config; otherwise, it applies overrides per handler.

## Batch Updates (JSON-Friendly)

`routedclass.configure` accepts either a single target or a list:

```python
payload = [
    {"target": "api:logging/_all_", "flags": "before,after"},
    {"target": "api:logging/admin_*", "enabled": False},
    {"target": "reports:pydantic/orders.detail", "strict": True},
]

for entry in payload:
    svc.routedclass.configure(entry["target"], **{k: v for k, v in entry.items() if k != "target"})
```

This pattern allows orchestration layers (CLI, HTTP APIs) to forward arbitrary batches in a single request.

## Exposing via Router

You can expose the configuration helper through a dedicated router if needed:

```python
class ConfigAPI(RoutedClass):
    api = Router(name="api").plug("logging")
    admin = Router(name="admin")

    @route("admin")
    def configure_plugin_route(self, target: str, payload: dict):
        self.routedclass.configure(target, **payload)
        return {"status": "ok"}
```

Orchestrators can call `config_api.admin.get("configure_plugin_route")` and pass JSON payloads with the target/payload structure described above.

## Notes

- `flags="enabled,trace,time:off"` follows the legacy SmartSwitch semantics (comma-separated booleans with optional `:off`).
- Plugin authors can inspect final values via `plugin.get_config()` or `plugin.get_config("handler")`.
- If a selector matches no handlers, SmartRoute raises `KeyError` so clients know the request failed.
- Passing `"?"` as the target returns the full router→plugin tree (including current configuration) instead of applying changes.
