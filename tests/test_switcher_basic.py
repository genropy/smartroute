"""Tests for instance-based Router core functionality."""

import sys

import pytest

from smartroute import RoutedClass, Router, route
from smartroute.plugins._base_plugin import BasePlugin  # Not public API


def test_orders_quick_example():
    class OrdersAPI(RoutedClass):
        def __init__(self, label: str):
            self.label = label
            self.api = Router(self, name="orders")

        @route("orders")
        def list(self):
            return ["order-1", "order-2"]

        @route("orders")
        def retrieve(self, ident: str):
            return f"{self.label}:{ident}"

        @route("orders")
        def create(self, payload: dict):
            return {"status": "created", **payload}

    orders = OrdersAPI("acme")
    assert orders.api.get("list")() == ["order-1", "order-2"]
    assert orders.api.get("retrieve")("42") == "acme:42"
    overview = orders.api.members()
    assert set(overview["handlers"].keys()) == {"list", "retrieve", "create"}


def test_dashboard_hierarchy():
    class Report(RoutedClass):
        def __init__(self, name: str):
            self.name = name
            self.routes = Router(self, name="report")

        @route("report")
        def summary(self):
            return f"{self.name}:summary"

    class Dashboard(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="dashboard")
            self.sales = Report("sales")
            self.finance = Report("finance")
            self.api.add_child(self.sales, name="sales")
            self.api.add_child(self.finance, name="finance")

    dashboard = Dashboard()
    assert dashboard.api.get("sales.summary")() == "sales:summary"
    assert dashboard.api.get("finance.summary")() == "finance:summary"


def test_portal_composition():
    class Emails(RoutedClass):
        def __init__(self):
            self.routes = Router(self, name="emails")

        @route("emails")
        def send(self, to: str):
            return f"email:{to}"

    class Reports(RoutedClass):
        def __init__(self):
            self.routes = Router(self, name="reports")

        @route("reports")
        def summary(self):
            return "reports:summary"

    class Portal(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="portal")
            modules = {"reports": Reports(), "emails": Emails()}
            self.api.add_child(modules)

    portal = Portal()
    assert portal.api.get("reports.summary")() == "reports:summary"
    assert portal.api.get("emails.send")("user") == "email:user"


class Service(RoutedClass):
    def __init__(self, label: str):
        self.label = label
        self.api = Router(self, name="api")

    @route("api")
    def describe(self):
        return f"service:{self.label}"


class SubService(RoutedClass):
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.routes = Router(self, name="routes", prefix="handle_")

    @route("routes")
    def handle_list(self):
        return f"{self.prefix}:list"

    @route("routes", name="detail")
    def handle_detail(self, ident: int):
        return f"{self.prefix}:detail:{ident}"


class RootAPI(RoutedClass):
    def __init__(self):
        self.services: list[Service] = []
        self.api = Router(self, name="api")


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


# Register custom plugin
Router.register_plugin("capture", CapturePlugin)


class PluginService(RoutedClass):
    def __init__(self):
        self.touched = False
        self.api = Router(self, name="api").plug("capture")

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


# Register custom plugin
Router.register_plugin("toggle", TogglePlugin)


class ToggleService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("toggle")

    @route("api")
    def touch(self):
        return "done"


class NestedLeaf(RoutedClass):
    def __init__(self):
        self.leaf_switch = Router(self, name="leaf_switch")

    @route("leaf_switch")
    def leaf_ping(self):
        return "leaf"


class NestedBranch:
    def __init__(self):
        self.child_leaf = NestedLeaf()


class NestedRoot(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")
        self.branch = NestedBranch()
        self.api.add_child(self.branch.child_leaf, name="leaf_switch")


class DynamicRouterService(RoutedClass):
    def __init__(self):
        self.dynamic = Router(self, name="dynamic", auto_discover=False)
        self.dynamic.add_entry(self.dynamic_alpha)
        self.dynamic.add_entry("dynamic_beta")

    def dynamic_alpha(self):
        return "alpha"

    def dynamic_beta(self):
        return "beta"


def test_instance_bound_methods_are_isolated():
    first = Service("alpha")
    second = Service("beta")

    assert first.api.get("describe")() == "service:alpha"
    assert second.api.get("describe")() == "service:beta"
    # Ensure handlers are distinct objects (bound to each instance)
    assert first.api.get("describe") != second.api.get("describe")


def test_prefix_and_name_override():
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

    # Passing a class instead of an instance should fail
    with pytest.raises(TypeError):
        root.api.add_child(SubService)

    # Passing the instance works
    attached = root.api.add_child(users)
    assert attached is not None  # Returns the bound router


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


def test_add_child_accepts_attribute_names():
    class AttrParent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.users = SubService("users")
            self.products = SubService("products")
            self.api.add_child("users")
            self.api.add_child("products")

    parent = AttrParent()
    assert parent.api.get("users.list")() == "users:list"
    assert parent.api.get("products.detail")(8) == "products:detail:8"


def test_add_child_accepts_comma_separated_attributes():
    class MultiAttrParent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.users = SubService("users")
            self.products = SubService("products")
            self.api.add_child("users, products")

    parent = MultiAttrParent()
    assert parent.api.get("users.list")() == "users:list"
    assert parent.api.get("products.detail")(9) == "products:detail:9"


def test_add_child_blank_attribute_string_noop():
    class BlankParent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.users = SubService("users")

    parent = BlankParent()
    parent.api.add_child(" , ")
    with pytest.raises(KeyError):
        parent.api.get_child("users")


def test_plugins_are_per_instance_and_accessible():
    svc = PluginService()
    assert svc.api.capture.calls == []
    result = svc.api.get("do_work")()
    assert result == "ok"
    assert svc.touched is True
    assert svc.api.capture.calls == ["wrap"]
    other = PluginService()
    assert other.api.capture.calls == []


def test_dynamic_router_add_entry_runtime():
    svc = DynamicRouterService()
    assert svc.dynamic.get("dynamic_alpha")() == "alpha"
    assert svc.dynamic.get("dynamic_beta")() == "beta"
    # Adding via string
    svc.dynamic.add_entry("dynamic_alpha", name="alpha_alias")
    assert svc.dynamic.get("alpha_alias")() == "alpha"


def test_parent_plugins_inherit_to_children():
    class ParentAPI(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("capture")

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
        def __init__(self):
            self.api = Router(self, name="api", get_default_handler=lambda: "init-default")

    svc = DefaultService()
    handler = svc.api.get("missing")
    assert handler() == "init-default"


def test_get_runtime_override_init_default_handler():
    class DefaultService(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api", get_default_handler=lambda: "init-default")

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
        def __init__(self):
            self.api = Router(self, name="api", get_use_smartasync=True)

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
        def __init__(self):
            self.api = Router(self, name="api", get_use_smartasync=True)

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


def test_describe_returns_hierarchy():
    root = NestedRoot()
    info = root.api.describe()
    assert "children" in info
    assert "leaf_switch" in info["children"]
    leaf_info = info["children"]["leaf_switch"]
    assert "leaf_ping" in leaf_info["methods"]
