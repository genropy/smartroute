"""Tests for the Pydantic plugin."""

import pytest
from pydantic import ValidationError

# Import to trigger plugin registration
import smartroute.plugins.pydantic  # noqa: F401
from smartroute import RoutedClass, Router, route


class ValidateService(RoutedClass):
    def __init__(self):
        self.calls = 0
        self.api = Router(self, name="api").plug("pydantic")

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


def test_pydantic_plugin_disabled_at_runtime():
    """Test disabling pydantic validation at runtime via configure()."""
    svc = ValidateService()

    # First verify validation is active
    with pytest.raises(ValidationError):
        svc.api.get("concat")(123, "oops")

    # Disable validation at runtime
    svc.api.pydantic.configure(disabled=True)

    # Now invalid input passes through (no validation)
    result = svc.api.get("concat")(123, "oops")
    assert result == "123:oops"


def test_pydantic_plugin_disabled_per_handler():
    """Test disabling pydantic validation for a specific handler."""

    class MultiService(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def strict(self, text: str, number: int) -> str:
            return f"{text}:{number}"

        @route("api")
        def lenient(self, text: str, number: int) -> str:
            return f"{text}:{number}"

    svc = MultiService()

    # Disable only for "lenient" handler
    svc.api.pydantic.configure(_target="lenient", disabled=True)

    # "strict" still validates
    with pytest.raises(ValidationError):
        svc.api.get("strict")(123, "oops")

    # "lenient" bypasses validation
    result = svc.api.get("lenient")(123, "oops")
    assert result == "123:oops"


def test_pydantic_plugin_config_merge_base_and_handler():
    """Test that per-handler config overrides base config."""

    class MergeService(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def handler_a(self, text: str, number: int) -> str:
            return f"{text}:{number}"

        @route("api")
        def handler_b(self, text: str, number: int) -> str:
            return f"{text}:{number}"

    svc = MergeService()

    # Disable validation globally (base config)
    svc.api.pydantic.configure(disabled=True)

    # Both handlers should bypass validation now
    assert svc.api.get("handler_a")(123, "oops") == "123:oops"
    assert svc.api.get("handler_b")(123, "oops") == "123:oops"

    # Re-enable validation only for handler_a (per-handler overrides base)
    svc.api.pydantic.configure(_target="handler_a", disabled=False)

    # handler_a validates again, handler_b still disabled
    with pytest.raises(ValidationError):
        svc.api.get("handler_a")(123, "oops")

    assert svc.api.get("handler_b")(123, "oops") == "123:oops"
