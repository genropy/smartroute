"""Tests for the experimental instance-based Router (core_new)."""

import sys

import pytest

from smartroute.core import BasePlugin, BoundRouter, RoutedClass, Router, route


class Service(RoutedClass):
    api = Router(name="service")

    def __init__(self, label: str):
        self.label = label

    @route("api")
    def describe(self):
        return f"service:{self.label}"


class SubService(RoutedClass):
    routes = Router(prefix="handle_")

    def __init__(self, prefix: str):
        self.prefix = prefix

    @route("routes")
    def handle_list(self):
        return f"{self.prefix}:list"

    @route("routes", alias="detail")
    def handle_detail(self, ident: int):
        return f"{self.prefix}:detail:{ident}"


class RootAPI(RoutedClass):
    api = Router(name="root")

    def __init__(self):
        self.services: list[Service] = []


class CapturePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="capture")
        self.calls = []

    def on_decore(self, route, func, entry):
        entry.metadata["capture"] = True

    def wrap_handler(self, route, entry, call_next):
        def wrapper(*args, **kwargs):
            self.calls.append("wrap")
            return call_next(*args, **kwargs)

        return wrapper


class PluginService(RoutedClass):
    api = Router(name="plugin").plug(CapturePlugin())

    def __init__(self):
        self.touched = False

    @route("api")
    def do_work(self):
        self.touched = True
        return "ok"


class TogglePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="toggle")

    def wrap_handler(self, route, entry, call_next):
        def wrapper(*args, **kwargs):
            route.set_runtime_data(entry.name, self.name, "last", True)
            return call_next(*args, **kwargs)

        return wrapper


class ToggleService(RoutedClass):
    api = Router(name="toggle").plug(TogglePlugin())

    @route("api")
    def touch(self):
        return "done"


class NestedLeaf(RoutedClass):
    leaf_switch = Router(name="leaf")

    @route("leaf_switch")
    def leaf_ping(self):
        return "leaf"


class NestedBranch:
    def __init__(self):
        self.child_leaf = NestedLeaf()


class NestedRoot(RoutedClass):
    api = Router(name="root")

    def __init__(self):
        self.branch = NestedBranch()
        self.api.add_child(self.branch)


def test_instance_bound_methods_are_isolated():
    first = Service("alpha")
    second = Service("beta")

    assert first.api.get("describe")() == "service:alpha"
    assert second.api.get("describe")() == "service:beta"
    # Ensure handlers are distinct objects (bound to each instance)
    assert first.api.get("describe") != second.api.get("describe")


def test_prefix_and_alias_resolution():
    sub = SubService("users")

    assert set(sub.routes.entries()) == {"list", "detail"}
    assert sub.routes.get("list")() == "users:list"
    assert sub.routes.get("detail")(10) == "users:detail:10"


def test_hierarchical_binding_with_instances():
    root = RootAPI()
    users = SubService("users")
    products = SubService("products")

    root.api.add_child(users, name="users")
    root.api.add_child(products, name="products")

    assert root.api.get("users.list")() == "users:list"
    assert root.api.get("products.detail")(5) == "products:detail:5"


def test_add_child_requires_instance():
    root = RootAPI()
    users = SubService("users")

    # Passing the descriptor should fail
    try:
        root.api.add_child(SubService.routes)
    except TypeError as exc:
        assert "instance" in str(exc)
    else:
        raise AssertionError("add_child should reject Router descriptors")

    # Passing the instance works
    attached = root.api.add_child(users)
    assert isinstance(attached, BoundRouter)


def test_add_child_accepts_mapping_for_named_children():
    root = RootAPI()
    users = SubService("users")
    products = SubService("products")

    root.api.add_child({"users": users, "products": products})

    assert root.api.get("users.list")() == "users:list"
    assert root.api.get("products.detail")(7) == "products:detail:7"


def test_add_child_handles_nested_iterables_and_pairs():
    root = RootAPI()
    users = SubService("users")
    products = SubService("products")
    registry = [
        {"users": users},
        [("products", products)],
    ]

    root.api.add_child(registry)

    assert root.api.get("users.list")() == "users:list"
    assert root.api.get("products.detail")(3) == "products:detail:3"


def test_plugins_are_per_instance_and_accessible():
    svc = PluginService()
    assert svc.api.capture.calls == []
    result = svc.api.get("do_work")()
    assert result == "ok"
    assert svc.touched is True
    assert svc.api.capture.calls == ["wrap"]
    other = PluginService()
    assert other.api.capture.calls == []


def test_parent_plugins_inherit_to_children():
    class ParentAPI(RoutedClass):
        api = Router(name="parent").plug(CapturePlugin())

    parent = ParentAPI()
    child = SubService("child")
    parent.api.add_child(child, name="child")

    # Child router should now expose inherited plugin
    assert hasattr(child.routes, "capture")
    assert child.routes.capture.calls == []

    assert child.routes.get("list")() == "child:list"
    assert child.routes.capture.calls == ["wrap"]


def test_get_with_default_returns_callable():
    svc = PluginService()

    def fallback():
        return "fallback"

    handler = svc.api.get("missing", default_handler=fallback)
    assert handler() == "fallback"


def test_get_with_smartasync(monkeypatch):
    calls = []

    def fake_smartasync(fn):
        def wrapper(*a, **k):
            calls.append("wrapped")
            return fn(*a, **k)

        return wrapper

    fake_module = type(sys)("smartasync")
    fake_module.smartasync = fake_smartasync
    monkeypatch.setitem(sys.modules, "smartasync", fake_module)
    svc = PluginService()
    handler = svc.api.get("do_work", use_smartasync=True)
    handler()
    assert calls == ["wrapped"]


def test_get_uses_init_default_handler():
    class DefaultService(RoutedClass):
        api = Router(get_default_handler=lambda: "init-default")

    svc = DefaultService()
    handler = svc.api.get("missing")
    assert handler() == "init-default"


def test_get_runtime_override_init_default_handler():
    class DefaultService(RoutedClass):
        api = Router(get_default_handler=lambda: "init-default")

    svc = DefaultService()
    handler = svc.api.get("missing", default_handler=lambda: "runtime")
    assert handler() == "runtime"


def test_get_without_default_raises():
    svc = PluginService()
    with pytest.raises(NotImplementedError):
        svc.api.get("unknown")


def test_get_uses_init_smartasync(monkeypatch):
    calls = []

    def fake_smartasync(fn):
        def wrapper(*args, **kwargs):
            calls.append("wrapped")
            return fn(*args, **kwargs)

        return wrapper

    fake_module = type(sys)("smartasync")
    fake_module.smartasync = fake_smartasync
    monkeypatch.setitem(sys.modules, "smartasync", fake_module)

    class AsyncService(RoutedClass):
        api = Router(get_use_smartasync=True)

        @route("api")
        def do_work(self):
            return "ok"

    svc = AsyncService()
    handler = svc.api.get("do_work")
    assert handler() == "ok"
    assert calls == ["wrapped"]


def test_get_can_disable_init_smartasync(monkeypatch):
    calls = []

    def fake_smartasync(fn):
        def wrapper(*args, **kwargs):
            calls.append("wrapped")
            return fn(*args, **kwargs)

        return wrapper

    fake_module = type(sys)("smartasync")
    fake_module.smartasync = fake_smartasync
    monkeypatch.setitem(sys.modules, "smartasync", fake_module)

    class AsyncService(RoutedClass):
        api = Router(get_use_smartasync=True)

        @route("api")
        def do_work(self):
            return "ok"

    svc = AsyncService()
    handler = svc.api.get("do_work", use_smartasync=False)
    assert handler() == "ok"
    assert calls == []


def test_plugin_enable_disable_runtime_data():
    svc = ToggleService()
    handler = svc.api.get("touch")
    # Initially enabled
    handler()
    assert svc.api.get_runtime_data("touch", "toggle", "last") is True
    # Disable and verify
    svc.api.set_plugin_enabled("touch", "toggle", False)
    svc.api.set_runtime_data("touch", "toggle", "last", None)
    handler()
    assert svc.api.get_runtime_data("touch", "toggle", "last") is None
    # Re-enable
    svc.api.set_plugin_enabled("touch", "toggle", True)
    handler()
    assert svc.api.get_runtime_data("touch", "toggle", "last") is True


def test_nested_child_discovery():
    root = NestedRoot()
    assert root.api.get("leaf_switch.leaf_ping")() == "leaf"
