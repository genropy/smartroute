"""Tests to cover remaining coverage gaps."""

import pytest

import smartroute.plugins.logging  # noqa: F401
import smartroute.plugins.pydantic  # noqa: F401
from smartroute import RoutedClass, Router, route
from smartroute.plugins._base_plugin import BasePlugin


# --- base_router.py:682 - _describe_entry_extra returns extra ---


def test_members_with_plugin_returns_extra_info():
    """Test that members() includes plugin info when plugins are attached."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def handler(self, text: str) -> str:
            return text

    svc = Svc()
    tree = svc.api.members()
    # Should have plugins info in entry
    entry_info = tree["entries"]["handler"]
    assert "plugins" in entry_info


# --- router.py:130 - _PluginSpec.clone ---


def test_plugin_spec_clone():
    """Test _PluginSpec.clone() method."""
    from smartroute.core.router import _PluginSpec

    class DummyPlugin(BasePlugin):
        plugin_code = "dummy_clone"
        plugin_description = "Dummy for clone test"

    spec = _PluginSpec(DummyPlugin, {"option": "value"})
    cloned = spec.clone()
    assert cloned.factory is spec.factory
    assert cloned.kwargs == spec.kwargs
    assert cloned.kwargs is not spec.kwargs  # Should be a copy


# --- router.py:175 - empty plugin name error ---


def test_register_plugin_empty_name_raises():
    """Test that registering plugin with empty name raises ValueError."""

    class NoCodePlugin(BasePlugin):
        plugin_code = ""
        plugin_description = "No code"

    # Empty plugin_code is treated as missing plugin_code
    with pytest.raises(ValueError, match="missing plugin_code"):
        Router.register_plugin(NoCodePlugin)


# --- router.py:335-341, 353-355 - inherited plugin config lookup ---


def test_inherited_plugin_config_lookup():
    """Test that child router inherits parent plugin config via callable."""

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("logging")
            self.child = ChildSvc()  # Child must be an attribute of parent

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()

    # Set config on parent
    parent.api.logging.configure(before=False, after=True)

    # Attach child to parent
    parent.api.attach_instance(parent.child, name="child")

    # Child should inherit the plugin and config
    assert "logging" in parent.child.api._plugins_by_name

    # The config lookup should work (callable resolution)
    child_logging = parent.child.api._plugins_by_name["logging"]
    cfg = child_logging.configuration("child_handler")
    # Should have inherited config (before=False, after=True from parent)
    assert cfg.get("after") is True
    assert cfg.get("before") is False


# --- _base_plugin.py:119-122 - multi-target configure ---


def test_configure_multi_target():
    """Test configure() with comma-separated targets."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("logging")

        @route("api")
        def handler_a(self):
            return "a"

        @route("api")
        def handler_b(self):
            return "b"

        @route("api")
        def handler_c(self):
            return "c"

    svc = Svc()
    # Configure multiple targets at once
    svc.api.logging.configure(_target="handler_a,handler_b", before=False)

    # Both should have before=False
    cfg_a = svc.api.logging.configuration("handler_a")
    cfg_b = svc.api.logging.configuration("handler_b")
    cfg_c = svc.api.logging.configuration("handler_c")

    assert cfg_a.get("before") is False
    assert cfg_b.get("before") is False
    # handler_c should not be affected (uses base)
    assert cfg_c.get("before") is not False or "before" not in cfg_c


# --- _base_plugin.py:193,195 - _resolve_config callable/None ---


def test_resolve_config_with_callable():
    """Test that _resolve_config handles callable config."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("logging")

        @route("api")
        def handler(self):
            return "ok"

    svc = Svc()
    plugin = svc.api.logging

    # Test callable resolution
    result = plugin._resolve_config(lambda: {"key": "value"})
    assert result == {"key": "value"}

    # Test None resolution
    result = plugin._resolve_config(None)
    assert result == {}

    # Test dict passthrough
    result = plugin._resolve_config({"existing": True})
    assert result == {"existing": True}


# --- _base_plugin.py:240-241 - base configure with flags ---


def test_base_plugin_configure_with_flags():
    """Test BasePlugin.configure() with flags parameter."""

    class FlagsPlugin(BasePlugin):
        plugin_code = "flags_test"
        plugin_description = "Test flags in base configure"

        # No custom configure - uses base implementation

    Router.register_plugin(FlagsPlugin)

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("flags_test")

        @route("api")
        def handler(self):
            return "ok"

    svc = Svc()
    # Call configure with flags - should use base implementation
    svc.api.flags_test.configure(flags="enabled,verbose:off")

    cfg = svc.api.flags_test.configuration("handler")
    assert cfg.get("enabled") is True
    assert cfg.get("verbose") is False


# --- pydantic.py:100 - no parameter hints ---


def test_pydantic_handler_without_param_hints():
    """Test pydantic plugin with handler that has no parameter hints."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def no_hints(self, x, y):  # No type hints on parameters
            return f"{x}:{y}"

    svc = Svc()
    # Should work without validation (passthrough)
    result = svc.api.get("no_hints")("a", "b")
    assert result == "a:b"


def test_pydantic_handler_only_return_hint():
    """Test pydantic plugin with handler that has only return hint."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def only_return(self, x, y) -> str:  # Only return type hint
            return f"{x}:{y}"

    svc = Svc()
    # Should work without validation (no param hints after removing return)
    result = svc.api.get("only_return")("a", "b")
    assert result == "a:b"


# --- pydantic.py:107 - param not in signature raises error ---


def test_pydantic_hint_not_in_signature_raises():
    """Test pydantic raises error when type hint doesn't match signature.

    When a handler has a type hint for a parameter that doesn't exist
    in the function signature, pydantic plugin should raise ValueError.
    """

    # Define function with annotation for non-existent param
    def handler(self, x: str) -> str:
        return x

    # Add annotation for parameter not in signature
    handler.__annotations__["phantom"] = int

    with pytest.raises(ValueError, match="type hint for 'phantom'.*not in the function signature"):

        class Svc(RoutedClass):
            def __init__(self):
                self.api = Router(self, name="api").plug("pydantic")

        # Assign decorated handler - this triggers on_decore
        Svc.handler = route("api")(handler)

        # Creating instance triggers finalization and on_decore
        Svc()


# --- pydantic.py:159-167 - get_model disabled/no model ---


def test_pydantic_get_model_disabled():
    """Test get_model returns None when disabled."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def handler(self, text: str) -> str:
            return text

    svc = Svc()
    entry = svc.api._entries["handler"]

    # Initially should return model
    result = svc.api.pydantic.get_model(entry)
    assert result is not None
    assert result[0] == "pydantic_model"

    # After disabling, should return None
    svc.api.pydantic.configure(disabled=True)
    result = svc.api.pydantic.get_model(entry)
    assert result is None


def test_pydantic_get_model_no_model():
    """Test get_model returns None when no model was created."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def no_hints(self, x, y):  # No type hints
            return f"{x}:{y}"

    svc = Svc()
    entry = svc.api._entries["no_hints"]

    # No model was created
    result = svc.api.pydantic.get_model(entry)
    assert result is None


# --- pydantic.py:171-174 - entry_metadata no meta ---


def test_pydantic_entry_metadata_no_meta():
    """Test entry_metadata returns empty dict when no pydantic metadata."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def no_hints(self, x, y):  # No type hints = no pydantic metadata
            return f"{x}:{y}"

    svc = Svc()
    entry = svc.api._entries["no_hints"]

    result = svc.api.pydantic.entry_metadata(svc.api, entry)
    assert result == {}


def test_pydantic_entry_metadata_with_meta():
    """Test entry_metadata returns model info when pydantic metadata exists."""

    class Svc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def with_hints(self, text: str, num: int) -> str:
            return f"{text}:{num}"

    svc = Svc()
    entry = svc.api._entries["with_hints"]

    result = svc.api.pydantic.entry_metadata(svc.api, entry)
    assert "model" in result
    assert "hints" in result
    assert result["hints"] == {"text": str, "num": int}
