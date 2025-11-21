# SmartRoute Plugin Layer

This package hosts the built-in plugins (`logging`, `pydantic`) and the shared
contract found in :mod:`smartroute.plugins._base_plugin`. Every plugin—internal
or custom—must inherit from :class:`BasePlugin` and implement its hooks.

Guidelines
---------
- Keep plugin modules lightweight: registration side-effects (`Router.register_plugin`) should happen at import time, but avoid heavy dependencies.
- Place shared helper classes (e.g. `BasePlugin`) in underscore-prefixed modules (`_base_plugin.py`) to signal they are implementation details, even though we export them for advanced use/testing.
- Document each plugin's behavior in its module docstring; documentation elsewhere must match that canonical description.

When developing a new plugin, start by subclassing :class:`BasePlugin` from
`smartroute.plugins._base_plugin` and wire it via `Router.register_plugin`.
Applications should then call `Router(...).plug("your_plugin")`.
