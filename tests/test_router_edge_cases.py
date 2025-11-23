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
    plugin = SimplePlugin()
    plugin.configure.flags = "enabled,,beta"
    assert plugin.get_config()["enabled"] is True
    plugin.configure.threshold = 5
    assert plugin.get_config()["threshold"] == 5
    assert plugin.configure.threshold == 5

    method_proxy = plugin.configure["foo"]
    method_proxy.flags = "enabled:off"
    assert plugin.get_config("foo")["enabled"] is False
    method_proxy.mode = "strict"
    assert plugin.get_config("foo")["mode"] == "strict"


def test_plugin_constructor_flags_and_method_config():
    plugin = SimplePlugin(flags="beta:on,alpha:off", method_config={"foo": {"enabled": False}})
    assert plugin.get_config()["beta"] is True
    assert plugin.get_config()["alpha"] is False
    assert plugin.get_config("foo")["enabled"] is False
    with pytest.raises(AttributeError):
        _ = plugin.configure.nonexistent


def ensure_plugin(name: str, plugin_cls: type) -> None:
    if name not in Router.available_plugins():
        Router.register_plugin(name, plugin_cls)


ensure_plugin("simple", SimplePlugin)


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


def test_describe_exposes_metadata():
    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("simple")

        @route("api")
        def run(self):
            """Run child handler."""
            return "ok"

    info = Parent().api.describe()
    assert info["name"] == "api"
    run_info = info["methods"]["run"]
    assert run_info["doc"] == "Run child handler."
    assert run_info["parameters"] == {}
    assert run_info["return_type"] == "Any"


def test_describe_includes_pydantic_validation():
    class Validated(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("pydantic")

        @route("api")
        def greet(self, name: str = "World") -> str:
            """Greet someone."""
            return f"Hello {name}"

    info = Validated().api.describe()
    greet = info["methods"]["greet"]
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
