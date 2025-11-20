"""Logging Plugin
=================

Responsibility
--------------
- wrap each handler invocation with a start/end message and timing metrics
- rely on a configured `logging.Logger` (or `print` fallback) without pulling
  additional dependencies

Usage Notes
-----------
- designed for development environments; it emits one line per call
- can be configured per-handler via `svc.routedclass.configure("api:logging/...", ...)`
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
