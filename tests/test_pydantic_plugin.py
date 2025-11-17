"""Tests for the Pydantic plugin with the experimental core."""

import pytest
from pydantic import ValidationError

from smartroute.core import RoutedClass, Router, route
from smartroute.plugins.pydantic import PydanticPlugin


class ValidateService(RoutedClass):
    api = Router(name="validate").plug(PydanticPlugin())

    def __init__(self):
        self.calls = 0

    @route("api")
    def concat(self, text: str, number: int = 1) -> str:
        self.calls += 1
        return f"{text}:{number}"


def test_pydantic_plugin_accepts_valid_input():
    svc = ValidateService()
    assert svc.api.get("concat")("hello", 3) == "hello:3"
    # default value still works
    assert svc.api.get("concat")("hi") == "hi:1"
    assert svc.calls == 2


def test_pydantic_plugin_rejects_invalid_input():
    svc = ValidateService()
    with pytest.raises(ValidationError):
        svc.api.get("concat")(123, "oops")
