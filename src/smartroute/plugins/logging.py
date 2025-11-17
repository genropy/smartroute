"""
Logging plugin adapted for the instance-scoped Router prototype.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from smartroute.core import BasePlugin, MethodEntry, Router


class LoggingPlugin(BasePlugin):
    """Simplified logging plugin for core_new."""

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
