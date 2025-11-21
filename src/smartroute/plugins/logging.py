"""Logging plugin (source of truth).

Rebuild behaviour exactly as described; no hidden defaults beyond this text.

Responsibilities
----------------
- Wrap each handler call and emit two messages: ``"{entry.name} start"`` before
  execution, ``"{entry.name} end (<ms> ms)"`` after. Elapsed time is in
  milliseconds with ``{elapsed:.2f}`` formatting.
- Use a provided ``logging.Logger`` (default ``logging.getLogger("smartswitch")``).
  If the logger reports no handlers via ``hasHandlers()``, fall back to ``print``
  to avoid dropping output.

Behaviour and API
-----------------
- ``LoggingPlugin(name=None, logger=None, **cfg)`` delegates to ``BasePlugin``;
  if ``name`` is falsy it sets ``"logger"`` as the plugin name. ``logger`` is
  stored in ``self._logger``.
- ``_emit(message)`` writes to ``self._logger.info`` when handlers exist, else
  ``print(message)``.
- ``wrap_handler(route, entry, call_next)`` returns ``logged`` callable:
    * records ``start`` via ``time.perf_counter()``
    * emits start message
    * calls ``call_next(*args, **kwargs)``
    * emits end message with elapsed time in ms
    * propagates the return value
  Exceptions from ``call_next`` propagate; the end message is not emitted when
  an exception is raised.

Registration
------------
At module import, the plugin registers itself globally as ``"logging"`` via
``Router.register_plugin("logging", LoggingPlugin)``.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from smartroute.core.router import Router
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry


class LoggingPlugin(BasePlugin):
    """Simplified logging plugin for SmartRoute."""

    def __init__(self, name: Optional[str] = None, logger: Optional[logging.Logger] = None, **cfg):
        super().__init__(name=name or "logger", **cfg)
        self._logger = logger or logging.getLogger("smartswitch")

    def _emit(self, message: str):
        if self._logger.hasHandlers():
            self._logger.info(message)
        else:
            print(message)

    def wrap_handler(self, route, entry: MethodEntry, call_next: Callable):
        def logged(*args, **kwargs):
            self._emit(f"{entry.name} start")
            t0 = time.perf_counter()
            result = call_next(*args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            self._emit(f"{entry.name} end ({elapsed:.2f} ms)")
            return result

        return logged


Router.register_plugin("logging", LoggingPlugin)
