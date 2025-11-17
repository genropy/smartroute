"""SmartRoute package."""

from .core import RoutedClass, Router, route, routers

# Import plugins to trigger auto-registration
from .plugins import logging, pydantic  # noqa: F401

__all__ = [
    "Router",
    "RoutedClass",
    "route",
    "routers",
]
