import pytest

from smartroute import RoutedClass, Router, route
from smartroute.plugins import pydantic as pyd_mod
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry  # Not public API
from smartroute.plugins.logging import LoggingPlugin
from smartroute.plugins.pydantic import PydanticPlugin


class SimplePlugin(BasePlugin):
    def wrap_handler(self, router, entry, call_next):
        return call_next


def test_plugin_config_proxy_updates_global_and_method_config():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

    svc = Host()
    plugin = svc.api._plugins_by_name["simple"]

    plugin.configure.flags = "enabled,,beta"
    assert svc.api.get_config("simple")["enabled"] is True
    plugin.configure.threshold = 5
    assert svc.api.get_config("simple")["threshold"] == 5
    assert plugin.configure.threshold == 5

    method_proxy = plugin.configure["foo"]
    method_proxy.flags = "enabled:off"
    assert svc.api.get_config("simple", "foo")["enabled"] is False
    method_proxy.mode = "strict"
    assert svc.api.get_config("simple", "foo")["mode"] == "strict"


def test_plugin_constructor_flags_and_method_config():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug(
                "simple", flags="beta:on,alpha:off", method_config={"foo": {"enabled": False}}
            )

    svc = Host()
    plugin = svc.api._plugins_by_name["simple"]
    assert svc.api.get_config("simple")["beta"] is True
    assert svc.api.get_config("simple")["alpha"] is False
    assert svc.api.get_config("simple", "foo")["enabled"] is False
    with pytest.raises(AttributeError):
        _ = plugin.configure.nonexistent


def ensure_plugin(name: str, plugin_cls: type) -> None:
    if name not in Router.available_plugins():
        Router.register_plugin(name, plugin_cls)


ensure_plugin("simple", SimplePlugin)


def test_unbound_plugin_config_guards_and_seed_noop():
    plugin = SimplePlugin()
    with pytest.raises(RuntimeError):
        plugin.get_config()
    with pytest.raises(RuntimeError):
        plugin.set_config(flag=True)
    with pytest.raises(RuntimeError):
        plugin.set_method_config("x", enabled=False)
    # _seed_store on an unbound plugin is a no-op
    plugin._seed_store()


def test_plugin_get_config_missing_bucket():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

    svc = Host()
    plugin = svc.api._plugins_by_name["simple"]
    svc.api._plugin_info.pop(plugin.name, None)
    assert plugin.get_config() == {}


def test_plugin_bucket_guards_and_base_autofill():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

    svc = Host()
    # Private helper with create=True should provision base bucket
    bucket = svc.api._get_plugin_bucket("missing", create=True)
    assert bucket["--base--"]["config"] == {}
    # Missing plugin still triggers AttributeError on public setters/getters
    with pytest.raises(AttributeError):
        svc.api.set_plugin_enabled("foo", "ghost", True)
    with pytest.raises(AttributeError):
        svc.api.get_runtime_data("foo", "ghost", "k")
    with pytest.raises(AttributeError):
        svc.api.set_runtime_data("foo", "ghost", "k", 1)
    with pytest.raises(AttributeError):
        svc.api.is_plugin_enabled("foo", "ghost")
    # If base key is removed, accessing will recreate it
    svc.api._plugin_info["simple"].pop("--base--", None)
    assert svc.api.is_plugin_enabled("demo", "simple") is True


def test_route_decorator_plugin_options_apply_to_entry():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

        @route("api", simple_flag=True, simple_mode="x", core_meta="keep")
        def run(self):
            return "ok"

    svc = Host()
    entry = svc.api._entries["run"]
    plugin_cfg = entry.metadata.get("plugin_config", {})
    assert plugin_cfg["simple"]["flag"] is True
    assert plugin_cfg["simple"]["mode"] == "x"
    assert entry.metadata["core_meta"] == "keep"
    # Stored on plugin_info for that entry
    assert svc.api._plugin_info["simple"]["run"]["config"]["flag"] is True
    assert svc.api._plugin_info["simple"]["run"]["config"]["mode"] == "x"


def test_add_entry_star_with_plugin_options_merges_marker_and_options():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api", auto_discover=False).plug("simple")
            # Apply options via add_entry("*")
            self.api.add_entry("*", simple_opt="via_add_entry")

        @route("api", simple_flag=True)
        def hello(self):
            return "hi"

    svc = Host()
    entry = svc.api._entries["hello"]
    plugin_cfg = entry.metadata.get("plugin_config", {})
    # Options from marker
    assert plugin_cfg["simple"]["flag"] is True
    # Options from add_entry call
    assert svc.api._plugin_info["simple"]["hello"]["config"]["opt"] == "via_add_entry"


def test_add_entry_core_options_preserved():
    class Host(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api", auto_discover=False)

        def hello(self):
            return "hi"

    svc = Host()
    svc.api.add_entry(svc.hello, core_value=123)
    entry = svc.api._entries["hello"]
    assert entry.metadata["core_value"] == 123


def test_router_auto_registers_marked_methods_and_validates_plugins():
    class Demo(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

        @route("api", name="alias")
        def handle(self):
            return "ok"

    svc = Demo()
    assert svc.api.get("alias")() == "ok"
    ensure_plugin("simple", SimplePlugin)
    svc.api.plug("simple")
    with pytest.raises(ValueError):
        svc.api.plug("missing")


def test_router_detects_handler_name_collision():
    class DuplicateService(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

        @route("api", name="dup")
        def first(self):
            return "one"

        @route("api", name="dup")
        def second(self):
            return "two"

    with pytest.raises(ValueError):
        DuplicateService()


def test_iter_plugins_and_missing_attribute():
    class Service(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

        @route("api")
        def ping(self):
            return "pong"

    svc = Service()
    plugins = svc.api.iter_plugins()
    assert plugins and isinstance(plugins[0], SimplePlugin)
    with pytest.raises(AttributeError):
        _ = svc.api.missing_plugin  # type: ignore[attr-defined]


def test_attach_and_detach_instance_single_router_with_alias():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = Child()

    parent = Parent()
    attached = parent.api.attach_instance(parent.child, name="sales")
    assert attached is parent.child.api
    assert parent.child._routed_parent is parent
    assert parent.api._children["sales"] is parent.child.api

    parent.api.detach_instance(parent.child)
    assert "sales" not in parent.api._children
    assert parent.child._routed_parent is None


def test_attach_instance_multiple_routers_requires_mapping():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.admin = Router(self, name="admin")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = Child()

    parent = Parent()
    # Auto-mapping when parent has a single router attaches both routers
    parent.api.attach_instance(parent.child)
    assert set(parent.api._children) == {"api", "admin"}
    assert parent.api._children["api"] is parent.child.api
    assert parent.api._children["admin"] is parent.child.admin


def test_attach_instance_single_child_requires_alias_when_parent_multi():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.admin = Router(self, name="admin")
            self.child = Child()

    parent = Parent()
    with pytest.raises(ValueError):
        parent.api.attach_instance(parent.child)
    parent.api.attach_instance(parent.child, name="child_alias")
    assert "child_alias" in parent.api._children


def test_attach_instance_allows_partial_mapping_and_skips_unmapped():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.admin = Router(self, name="admin")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = Child()

    parent = Parent()
    parent.api.attach_instance(parent.child, name="api:only_api")
    assert "only_api" in parent.api._children
    assert "admin" not in parent.api._children

    parent.api.attach_instance(parent.child, name="api:sales, admin:reports")
    assert parent.api._children["sales"] is parent.child.api
    assert parent.api._children["reports"] is parent.child.admin
    assert parent.child._routed_parent is parent


def test_attach_instance_name_collision():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child1 = Child()
            self.child2 = Child()

    parent = Parent()
    parent.api.attach_instance(parent.child1, name="sales")
    with pytest.raises(ValueError):
        parent.api.attach_instance(parent.child2, name="sales")


def test_attach_instance_requires_child_attribute_on_parent():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    parent = Parent()
    child = Child()
    with pytest.raises(ValueError):
        parent.api.attach_instance(child, name="child")
    # After storing on parent, attach works
    parent.child = child
    parent.api.attach_instance(parent.child, name="child")


def test_detach_instance_missing_alias():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.admin = Router(self, name="admin")

    parent = Child()
    parent.self_ref = parent
    parent.api.attach_instance(parent, name="api:self_api, admin:self_admin")
    # detach without explicit mapping removes both
    parent.api.detach_instance(parent)
    assert parent.api._children == {}


def test_attach_instance_requires_routedclass():
    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    parent = Parent()
    with pytest.raises(TypeError):
        parent.api.attach_instance(object(), name="x")
    with pytest.raises(TypeError):
        parent.api.detach_instance(object())


def test_auto_detach_on_attribute_replacement():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = Child()
            self.api.attach_instance(self.child, name="child")

    parent = Parent()
    assert parent.child._routed_parent is parent
    assert "child" in parent.api._children

    parent.child = None  # triggers auto-detach
    assert "child" not in parent.api._children
    assert parent.child is None


def test_attach_instance_rejects_other_parent_when_already_bound():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")

    class Parent(RoutedClass):
        def __init__(self, label: str):
            self.label = label
            self.api = Router(self, name="api")
            self.child = Child()

    first = Parent("first")
    second = Parent("second")

    # Bind to first parent
    first.api.attach_instance(first.child, name="child")
    assert first.child._routed_parent is first
    assert "child" in first.api._children

    # Attempt to bind same child to another parent should fail
    with pytest.raises(ValueError):
        second.api.attach_instance(first.child, name="child")


def test_attach_instance_requires_mapping_when_parent_has_multiple_routers():
    class Child(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.admin = Router(self, name="admin")

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.admin = Router(self, name="admin")
            self.child = Child()

    parent = Parent()
    with pytest.raises(ValueError):
        parent.api.attach_instance(parent.child)  # parent has multiple routers, mapping required


def test_branch_router_blocks_auto_discover_and_entries():
    class Service(RoutedClass):
        def __init__(self):
            with pytest.raises(ValueError):
                Router(self, name="branch", branch=True)  # auto_discover default True

            self.branch = Router(self, name="branch", branch=True, auto_discover=False)

    svc = Service()
    with pytest.raises(ValueError):
        svc.branch.add_entry("missing")


def test_base_plugin_default_hooks():
    plugin = BasePlugin()
    entry = MethodEntry(name="foo", func=lambda: "ok", router=None, plugins=[])
    plugin.on_decore(None, entry.func, entry)
    assert plugin.wrap_handler(None, entry, lambda: "ok")() == "ok"


def test_logging_plugin_emit_without_handlers(capsys):
    plugin = LoggingPlugin()

    class DummyLogger:
        def has_handlers(self):
            return False

        # Compatibility alias
        hasHandlers = has_handlers  # noqa: N815

    plugin._logger = DummyLogger()  # type: ignore[attr-defined]
    plugin._emit("hello")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_logging_plugin_emit_falls_back_to_print_when_log_enabled(capsys):
    plugin = LoggingPlugin()

    class DummyLogger:
        def has_handlers(self):
            return False

        # Compatibility alias
        hasHandlers = has_handlers  # noqa: N815

        def info(self, message):
            raise AssertionError("Should not be called")

    plugin._logger = DummyLogger()  # type: ignore[attr-defined]
    plugin._emit("hello", cfg={"log": True, "print": False})
    captured = capsys.readouterr()
    assert "hello" in captured.out


def test_pydantic_plugin_handles_hint_errors(monkeypatch):
    plugin = PydanticPlugin()
    entry = MethodEntry(name="foo", func=lambda **kw: "ok", router=None, plugins=[])

    def broken_get_type_hints(func):
        raise RuntimeError("boom")

    monkeypatch.setattr(pyd_mod, "get_type_hints", broken_get_type_hints)

    def handler():
        return "ok"

    plugin.on_decore(None, handler, entry)
    wrapper = plugin.wrap_handler(None, entry, lambda **kw: "ok")
    assert wrapper() == "ok"


def test_pydantic_plugin_disables_when_no_hints(monkeypatch):
    plugin = PydanticPlugin()
    entry = MethodEntry(name="foo", func=lambda: None, router=None, plugins=[])

    def no_hints(func):
        return {}

    monkeypatch.setattr(pyd_mod, "get_type_hints", no_hints)

    def handler(arg):
        return arg

    plugin.on_decore(None, handler, entry)
    assert entry.metadata["pydantic"]["enabled"] is False
    wrapper = plugin.wrap_handler(None, entry, lambda **kw: "ok")
    assert wrapper() == "ok"


def test_pydantic_plugin_handles_missing_signature_params(monkeypatch):
    plugin = PydanticPlugin()
    entry = MethodEntry(name="foo", func=lambda: None, router=None, plugins=[])

    def fake_hints(func):
        return {"ghost": int}

    monkeypatch.setattr(pyd_mod, "get_type_hints", fake_hints)

    def handler():
        return "ok"

    plugin.on_decore(None, handler, entry)
    assert entry.metadata["pydantic"]["enabled"] is True


def test_builtin_plugins_registered():
    available = Router.available_plugins()
    assert "logging" in available
    assert "pydantic" in available


def test_register_plugin_validates():
    with pytest.raises(TypeError):
        Router.register_plugin("bad", object)  # type: ignore[arg-type]

    class CustomPlugin(BasePlugin):
        pass

    Router.register_plugin("custom_edge", CustomPlugin)

    class OtherPlugin(BasePlugin):
        pass

    with pytest.raises(ValueError):
        Router.register_plugin("custom_edge", OtherPlugin)


def test_router_get_config_paths():
    class CfgPlugin(BasePlugin):
        pass

    Router.register_plugin("cfgplug", CfgPlugin)

    class Service(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug(
                "cfgplug", mode="x", method_config={"hello": {"trace": True}}
            )

        @route("api")
        def hello(self):
            return "ok"

    svc = Service()
    assert svc.api.get_config("cfgplug")["mode"] == "x"
    merged = svc.api.get_config("cfgplug", "hello")
    assert merged["mode"] == "x" and merged["trace"] is True
    with pytest.raises(AttributeError):
        svc.api.get_config("missing")


def test_members_expose_metadata():
    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

        @route("api")
        def run(self):
            """Run child handler."""
            return "ok"

    info = Parent().api.members()
    assert info["name"] == "api"
    run_info = info["handlers"]["run"]
    assert run_info["doc"] == "Run child handler."
    assert run_info["parameters"] == {}
    assert run_info["return_type"] == "Any"


def test_members_include_pydantic_validation():
    class Validated(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def greet(self, name: str = "World") -> str:
            """Greet someone."""
            return f"Hello {name}"

    info = Validated().api.members()
    greet = info["handlers"]["greet"]
    assert greet["name"] == "greet"
    assert "Greet someone." in greet["doc"]
    assert greet["return_type"] == "str"
    param = greet["parameters"]["name"]
    assert param["type"] == "str"
    assert param["default"] == "World"
    assert param["required"] is False
    assert isinstance(param.get("validation"), dict)


def test_routed_proxy_get_router_handles_dotted_path():
    class Leaf(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="leaf", auto_discover=False)

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = Leaf()
            self.api._children["child"] = self.child.api  # direct attach for test

    svc = Parent()
    router = svc.routedclass.get_router("api.child")
    assert router.name == "leaf"


def test_routed_configure_updates_plugins_global_and_local():
    ensure_plugin("simple", SimplePlugin)

    class ConfService(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

        @route("api")
        def foo(self):
            return "foo"

        @route("api")
        def bar(self):
            return "bar"

    svc = ConfService()
    svc.routedclass.configure("api:simple/_all_", threshold=10)
    assert svc.api.simple.get_config()["threshold"] == 10

    svc.routedclass.configure("api:simple/foo", enabled=False)
    assert svc.api.simple.get_config("foo")["enabled"] is False

    svc.routedclass.configure("api:simple/b*", mode="strict")
    assert svc.api.simple.get_config("bar")["mode"] == "strict"

    payload = [
        {"target": "api:simple/_all_", "flags": "trace"},
        {"target": "api:simple/foo", "limit": 5},
    ]
    result = svc.routedclass.configure(payload)
    assert len(result) == 2
    assert svc.api.simple.get_config("foo")["limit"] == 5


def test_routed_configure_question_lists_tree():
    ensure_plugin("simple", SimplePlugin)

    class Root(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

        @route("api")
        def root_ping(self):
            return "root"

    svc = Root()
    info = svc.routedclass.configure("?")
    assert "api" in info
    assert info["api"]["plugins"]
    assert info["api"]["children"] == {}
