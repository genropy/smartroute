"""Plugins compatible with the experimental instance-based core."""

from .logging import LoggingPlugin
from .pydantic import PydanticPlugin

__all__ = ["LoggingPlugin", "PydanticPlugin"]
