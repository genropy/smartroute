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


# --- Plugin inheritance: clone + config copy ---


def test_inherited_plugin_is_separate_instance():
    """Test that inherited plugin is a new instance, not shared with parent."""

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("logging")
            self.child = ChildSvc()

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()
    parent.api.attach_instance(parent.child, name="child")

    # Plugin instances should be DIFFERENT objects
    parent_plugin = parent.api._plugins_by_name["logging"]
    child_plugin = parent.child.api._plugins_by_name["logging"]

    assert parent_plugin is not child_plugin
    assert parent_plugin._router is parent.api
    assert child_plugin._router is parent.child.api


def test_inherited_plugin_copies_parent_config():
    """Test that child inherits a copy of parent's config at attach time."""

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("logging")
            self.child = ChildSvc()

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()

    # Configure parent BEFORE attach
    parent.api.logging.configure(before=False, after=True)

    # Attach child - should copy config
    parent.api.attach_instance(parent.child, name="child")

    # Child should have same config values
    child_cfg = parent.child.api.logging.configuration()
    assert child_cfg.get("before") is False
    assert child_cfg.get("after") is True


def test_child_config_independent_from_parent():
    """Test that after attach, child's config is independent from parent."""

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("logging")
            self.child = ChildSvc()

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()
    parent.api.logging.configure(before=True, after=False)
    parent.api.attach_instance(parent.child, name="child")

    # Child modifies its own config
    parent.child.api.logging.configure(before=False, after=True)

    # Configs should be different
    parent_cfg = parent.api.logging.configuration()
    child_cfg = parent.child.api.logging.configuration()

    assert parent_cfg.get("before") is True
    assert parent_cfg.get("after") is False
    assert child_cfg.get("before") is False
    assert child_cfg.get("after") is True


# --- on_parent_config_changed notification ---


def test_parent_config_change_notifies_children():
    """Test that changing parent config calls on_parent_config_changed on children."""
    notifications = []

    class TrackingPlugin(BasePlugin):
        plugin_code = "tracking"
        plugin_description = "Tracks parent config changes"

        def configure(self, value: int = 0):
            pass

        def on_parent_config_changed(self, new_config):
            notifications.append({"router": self._router.name, "config": new_config})

    Router.register_plugin(TrackingPlugin)

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="child_api")

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="parent_api").plug("tracking")
            self.child = ChildSvc()

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()
    parent.api.attach_instance(parent.child, name="child")

    # Clear any notifications from __init__
    notifications.clear()

    # Change parent config
    parent.api.tracking.configure(value=42)

    # Child should have been notified
    assert len(notifications) == 1
    assert notifications[0]["router"] == "child_api"
    assert notifications[0]["config"] == {"value": 42}


def test_cascading_notifications():
    """Test that if child applies config, its children are also notified."""
    notifications = []

    class CascadePlugin(BasePlugin):
        plugin_code = "cascade"
        plugin_description = "Cascades config to children"

        def configure(self, level: int = 0):
            pass

        def on_parent_config_changed(self, new_config):
            notifications.append({"router": self._router.name, "config": new_config})
            # Apply the config - this should cascade to our children
            self.configure(**new_config)

    Router.register_plugin(CascadePlugin)

    class GrandchildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="grandchild_api")

        @route("api")
        def grandchild_handler(self):
            return "grandchild"

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="child_api")
            self.grandchild = GrandchildSvc()

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="parent_api").plug("cascade")
            self.child = ChildSvc()

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()
    parent.api.attach_instance(parent.child, name="child")
    parent.child.api.attach_instance(parent.child.grandchild, name="grandchild")

    # Clear notifications
    notifications.clear()

    # Change parent config
    parent.api.cascade.configure(level=99)

    # Both child and grandchild should have been notified
    assert len(notifications) == 2
    routers_notified = [n["router"] for n in notifications]
    assert "child_api" in routers_notified
    assert "grandchild_api" in routers_notified


def test_child_ignores_parent_config_no_cascade():
    """Test that if child ignores parent config, grandchildren are NOT notified."""
    notifications = []

    class IgnorePlugin(BasePlugin):
        plugin_code = "ignore"
        plugin_description = "Ignores parent config changes"

        def configure(self, value: int = 0):
            pass

        def on_parent_config_changed(self, new_config):
            notifications.append({"router": self._router.name, "config": new_config})
            # Do NOT call configure - stop the cascade

    Router.register_plugin(IgnorePlugin)

    class GrandchildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="grandchild_api")

        @route("api")
        def grandchild_handler(self):
            return "grandchild"

    class ChildSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="child_api")
            self.grandchild = GrandchildSvc()

        @route("api")
        def child_handler(self):
            return "child"

    class ParentSvc(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="parent_api").plug("ignore")
            self.child = ChildSvc()

        @route("api")
        def parent_handler(self):
            return "parent"

    parent = ParentSvc()
    parent.api.attach_instance(parent.child, name="child")
    parent.child.api.attach_instance(parent.child.grandchild, name="grandchild")

    # Clear notifications
    notifications.clear()

    # Change parent config
    parent.api.ignore.configure(value=77)

    # Only child should be notified (grandchild NOT because child ignores)
    assert len(notifications) == 1
    assert notifications[0]["router"] == "child_api"
