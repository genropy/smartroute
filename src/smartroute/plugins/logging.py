"""Logging plugin (source of truth).

Rebuild behaviour exactly as described; no hidden defaults beyond this text.

Responsibilities
----------------
- Wrap each handler call and emit configurable messages:
  * ``before`` (default True): ``"{entry.name} start"``
  * ``after`` (default True): ``"{entry.name} end (<ms> ms)"`` with elapsed time
    in milliseconds and ``{elapsed:.2f}`` formatting.
- Sinks:
  * when ``print`` is true → always ``print(message)``;
  * else when ``log`` is true → ``logger.info(message)`` if the logger reports
    handlers via ``hasHandlers()``, otherwise ``print(message)`` to avoid drops;
  * else → no output.
- ``enabled`` gates the plugin entirely (default True).
- Use a provided ``logging.Logger`` (default ``logging.getLogger("smartroute")``).

Configuration
-------------
- Accepted keys (router-level or per-handler): ``enabled``, ``before``,
  ``after``, ``log``, ``print``. They can be provided as individual kwargs
  (e.g. ``logging_after=False``) or in ``logging_flags`` (e.g.
  ``"enabled:off,before:on,after:on,log:on,print:off"``).
- Runtime: ``router.logging.configure`` mirrors the same options, plus
  per-handler via ``configure["handler"].before = False``.
- ``flags`` string values are parsed like other plugins via ``BasePlugin``.

Behaviour and API
-----------------
- ``LoggingPlugin(name=None, logger=None, **cfg)`` delegates to ``BasePlugin``;
  if ``name`` is falsy it sets ``"logger"`` as the plugin name. ``logger`` is
  stored in ``self._logger``; additional ``**cfg`` seeds initial config.
- ``_emit(message, cfg)`` chooses sink based on ``cfg`` as described above.
- ``wrap_handler(route, entry, call_next)`` applies the configuration on each
  call. Exceptions propagate; the end message is skipped when an exception is
  raised.

Registration
------------
At module import, the plugin registers itself globally as ``"logging"`` via
``Router.register_plugin(LoggingPlugin)``.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from smartroute.core.router import Router
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry


class LoggingPlugin(BasePlugin):
    """Simplified logging plugin for SmartRoute."""

    plugin_code = "logging"
    plugin_description = "Logs handler calls with timing"

    __slots__ = ("_logger",)

    def __init__(self, router, *, logger: Optional[logging.Logger] = None, **cfg):
        self._logger = logger or logging.getLogger("smartroute")
        super().__init__(router, **cfg)

    def configure(
        self,
        enabled: bool = True,
        before: bool = True,
        after: bool = True,
        log: bool = True,
        print: bool = False,  # noqa: A002 - shadowing builtin intentionally
    ):
        """Configure logging plugin options.

        The wrapper added by __init_subclass__ handles writing to store.
        """
        pass  # Storage is handled by the wrapper

    def _emit(self, message: str, *, cfg: Optional[dict] = None):
        # If no config is provided, treat as disabled.
        if cfg is None:
            return
        if cfg.get("print"):
            print(message)
            return
        if cfg.get("log"):
            logger = self._logger
            has_handlers = getattr(logger, "hasHandlers", None) or getattr(
                logger, "has_handlers", None
            )
            can_log = callable(has_handlers) and has_handlers()
            if can_log:
                logger.info(message)
            else:
                print(message)

    def wrap_handler(self, route, entry: MethodEntry, call_next: Callable):
        """Wrap handler with start/end logging and timing."""

        def logged(*args, **kwargs):
            cfg = self._effective_config(entry.name)
            if not cfg["enabled"] or not route.is_plugin_enabled(entry.name, self.name):
                return call_next(*args, **kwargs)
            if cfg["before"]:
                self._emit(f"{entry.name} start", cfg=cfg)
            t0 = time.perf_counter()
            result = call_next(*args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            if cfg["after"]:
                self._emit(f"{entry.name} end ({elapsed:.2f} ms)", cfg=cfg)
            return result

        return logged

    def _effective_config(self, entry_name: str) -> dict:
        defaults = {"enabled": True, "before": True, "after": True, "log": True, "print": False}
        cfg = defaults | self.configuration(entry_name)
        flags = cfg.pop("flags", None)
        if isinstance(flags, str):
            cfg.update(self._parse_flags(flags))

        def to_bool(key: str) -> bool:
            val = cfg.get(key)
            return defaults[key] if val is None else bool(val)

        return {key: to_bool(key) for key in defaults}


Router.register_plugin(LoggingPlugin)
