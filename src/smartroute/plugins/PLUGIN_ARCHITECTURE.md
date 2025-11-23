# SmartRoute plugin architecture (target design)

This note captures the **intended** end-state for plugin configuration and
introspection. Use it as the reference for implementation, tests, and user
documentation.

## Goals
- Single authoritative store for plugin state/config on each router.
- Uniform shape for router-level and entry-level data (no hidden globals in plugins).
- Introspection-friendly: easy to expose via CLI/HTTP/WS for live updates.
- Plugins stay as stateless as possible (no hidden globals).

## Data model (authoritative on `Router`)
Each router owns a `plugin_info` mapping keyed by plugin code (the name used in
`plug(...)`). Value shape:

```python
plugin_info = {
    "logging": {
        "config": { ... },            # router-level defaults for the plugin
        "handlers": {                 # per-entry overrides
            "entry_name": { ... },
            ...
        },
        "locals": {                   # optional live data used by the plugin
            # arbitrary plugin-defined state; separate from config
        },
    },
    ...
}
```

For a specific entry, the effective config is:
```
effective = merge(plugin_info[code]["config"], plugin_info[code]["handlers"].get(entry, {}))
```
If a plugin/entry bucket or key is missing, the merge treats it as empty.

### Entry-side view
`MethodEntry` can mirror the same information for convenience:
```
entry.plugin_info[code] = {
    "config": { ... },   # merged view for this entry (optional cache)
    "locals": { ... },   # optional, plugin-managed live data for this entry
}
```
The authoritative source remains on the router; entry mirrors are a view/cache.

### Locals
Some plugins may keep per-entry live state (e.g., counters, accumulators). Those
belong in `plugin_info[code]["locals"]` (router-level, per-entry) or in
`entry.plugin_info[code]["locals"]` if the plugin needs proximity to the
MethodEntry. Locals are *not* config: they are runtime data the plugin owns.

## API expectations
- `Router.get_config(plugin, entry=None)` (or equivalent) resolves the router,
  then returns:
  - merged config for `entry` when provided,
  - router-level config when `entry` is `None`.
  Missing plugin → `None`; missing entry override → merge of router config only.
- `Router.get_metadata(selector)` should resolve the entry (like `get`) and read
  from `entry.metadata` (orthogonal to plugin_info).
- Plugins read config at call time, not baked into wrappers, so live updates do
  not require rebuilding handlers. If a plugin *does* bake config into a
  closure, it must trigger a rebuild after config changes.

## Introspection for admin/CLI/UI
`members()` should optionally include `plugin_info` for both routers and entries.
This enables a tree-like JSON the UI/CLI can render:
- routers with their plugins and router-level config,
- entries with their plugins, effective config, and locals.

Example snippet:
```json
{
  "name": "api",
  "plugins": ["logging", "publish"],
  "plugin_info": {
    "logging": { "config": {"enabled": true}, "handlers": {}, "locals": {} }
  },
  "methods": {
    "pay_now": {
      "plugins": ["logging", "publish"],
      "plugin_info": {
        "publish": {
          "config": {"channel": "public"},
          "locals": {}
        }
      }
    }
  }
}
```

## Live updates (HTTP/WS/CLI)
1. Resolve router/entry via dotted path (same resolution as `get`).
2. Validate payload against plugin schema (per-plugin responsibility).
3. Write into `plugin_info[...]` (router-level and/or handlers override).
4. If the plugin needs rebuild, trigger it; otherwise changes take effect on
   next call because plugins read config live.

## Migration note
Current implementation still stores config inside `BasePlugin` (`_global_config`
and `_handler_configs`). Moving to this model requires:
- redirecting `configure`/`get_config` to read/write `router.plugin_info`,
- optionally keeping entry mirrors for convenience,
- ensuring inheritance/attach/detach clone/cleanup the `plugin_info` tree.
