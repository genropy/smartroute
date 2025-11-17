import pytest

from smartroute import RoutedClass, Router, route, routers
from smartroute.core import BasePlugin, MethodEntry  # Not public API
from smartroute.plugins import pydantic as pyd_mod
from smartroute.plugins.logging import LoggingPlugin
from smartroute.plugins.pydantic import PydanticPlugin


class SimplePlugin(BasePlugin):
    def wrap_handler(self, router, entry, call_next):
        return call_next


# Register test plugin
Router.register_plugin("simple", SimplePlugin)


def test_router_decorator_and_plugin_validation():
    router = Router()
    with pytest.raises(TypeError):
        router(123)

    decorator = router("alias")

    @decorator
    def handle(self):  # pragma: no cover - exercised through decorator
        return "ok"

    Router.register_plugin("simple", SimplePlugin)
    router.plug("simple")
    with pytest.raises(ValueError):
        router.plug("missing")


def test_router_detects_handler_name_collision():
    class DuplicateService(RoutedClass):
        api = Router()

        @route("api", alias="dup")
        def first(self):
            return "one"

        @route("api", alias="dup")
        def second(self):
            return "two"

    svc = DuplicateService()
    with pytest.raises(ValueError):
        _ = svc.api


def test_iter_plugins_and_missing_attribute():
    class Service(RoutedClass):
        api = Router(name="svc").plug("simple")

        @route("api")
        def ping(self):
            return "pong"

    svc = Service()
    plugins = svc.api.iter_plugins()
    assert plugins and isinstance(plugins[0], SimplePlugin)
    with pytest.raises(AttributeError):
        _ = svc.api.missing_plugin  # type: ignore[attr-defined]


def test_router_add_child_error_paths():
    class Node(RoutedClass):
        api = Router()

        @route("api")
        def ping(self):
            return "ok"

    parent = Node()
    with pytest.raises(TypeError):
        parent.api.add_child(object())

    first = Node()
    second = Node()
    parent.api.add_child(first, name="leaf")
    with pytest.raises(ValueError):
        parent.api.add_child(second, name="leaf")

    with pytest.raises(KeyError):
        parent.api.get_child("ghost")

    fresh = Node()
    bound_child = first.api
    attached = fresh.api.add_child(bound_child, name="leaf_bound")
    assert attached is bound_child


def test_routers_decorator_idempotent():
    class Demo:
        routes = Router()

        @route("routes")
        def hello(self):
            return "hi"

    routers()(Demo)
    assert len(Demo.routes._specs) == 1  # type: ignore[attr-defined]
    routers()(Demo)
    assert len(Demo.routes._specs) == 1  # type: ignore[attr-defined]


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
