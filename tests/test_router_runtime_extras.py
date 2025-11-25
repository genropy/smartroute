"""Additional coverage tests for runtime-only Router behavior."""

import pytest

from smartroute import RoutedClass, Router, route
from smartroute.core.base_router import ROUTER_REGISTRY_ATTR_NAME, _format_annotation
from smartroute.core.routed import is_routed_class
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry


class ManualService(RoutedClass):
    """Service with manual router registration."""

    def __init__(self):
        self.api = Router(self, name="api", auto_discover=False)

    def first(self):
        return "first"

    def second(self):
        return "second"

    @route("api", marker="yes")
    def auto(self):
        return "auto"


class DualRoutes(RoutedClass):
    def __init__(self):
        self.one = Router(self, name="one", auto_discover=False)
        self.two = Router(self, name="two", auto_discover=False)

    @route("one")
    @route("two", name="two_alias")
    def shared(self):
        return "shared"


class MultiChild(RoutedClass):
    def __init__(self):
        self.router_a = Router(self, name="router_a", auto_discover=False)
        self.router_b = Router(self, name="router_b", auto_discover=False)


class SlotRouted(RoutedClass):
    __slots__ = ("slot_router",)

    def __init__(self):
        self.slot_router = Router(self, name="slot", auto_discover=False)


class DuplicateMarkers(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api")

    @route("api")
    def original(self):
        return "ok"

    alias = original


class StampPlugin(BasePlugin):
    def on_decore(self, router, func, entry: MethodEntry):
        entry.metadata["stamped"] = True


if "stamp_extra" not in Router.available_plugins():
    Router.register_plugin("stamp_extra", StampPlugin)


class LoggingService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("logging")

    @route("api")
    def hello(self):
        return "ok"


def test_router_requires_owner():
    with pytest.raises(ValueError):
        Router(None)  # type: ignore[arg-type]


def test_register_plugin_requires_non_empty_name():
    class DummyPlugin(BasePlugin):
        pass

    with pytest.raises(ValueError):
        Router.register_plugin("", DummyPlugin)


def test_plug_validates_type_and_known_plugin():
    svc = ManualService()
    with pytest.raises(TypeError):
        svc.api.plug(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        svc.api.plug("missing_plugin")


def test_add_entry_variants_and_wildcards():
    svc = ManualService()
    svc.api.add_entry(["first", "second"])
    assert set(svc.api.entries()) == {"first", "second"}

    svc.api.add_entry("first, second", replace=True)
    before = set(svc.api.entries())
    assert svc.api.add_entry("   ") is svc.api
    assert set(svc.api.entries()) == before

    with pytest.raises(TypeError):
        svc.api.add_entry(123)

    svc.api.add_entry("*", metadata={"source": "wild"})
    entry = svc.api._entries["auto"]
    assert entry.metadata["marker"] == "yes"
    assert entry.metadata["source"] == "wild"


def test_plugin_on_decore_runs_for_existing_entries():
    svc = ManualService()
    svc.api.plug("stamp_extra")
    svc.api.add_entry(svc.first, name="alias_first")
    assert svc.api._entries["alias_first"].metadata["stamped"] is True


def test_iter_marked_methods_skip_other_router_markers():
    svc = DualRoutes()
    svc.one.add_entry("*")
    svc.two.add_entry("*")
    assert "shared" in svc.one.entries()
    assert "two_alias" in svc.two.entries()


def test_iter_marked_methods_deduplicate_same_function():
    svc = DuplicateMarkers()
    assert svc.api.get("original")() == "ok"
    assert len(svc.api.entries()) == 1


def test_router_call_and_members_structure():
    svc = ManualService()
    svc.api.add_entry(svc.first)
    assert svc.api.call("first") == "first"
    tree = svc.api.members()
    assert tree["handlers"]
    assert tree["children"] == {}


def test_inherit_plugins_branches():
    parent = ManualService()
    child = ManualService()
    parent.api.plug("stamp_extra")
    before = len(child.api._plugins)
    child.api._on_attached_to_parent(parent.api)
    after = len(child.api._plugins)
    assert after > before
    child.api._on_attached_to_parent(parent.api)
    assert len(child.api._plugins) == after
    # Force missing plugin bucket to exercise seed path
    parent.api._plugin_info.pop("stamp_extra", None)
    child.api._on_attached_to_parent(parent.api)

    orphan = ManualService()
    plain = ManualService()
    plain_before = len(orphan.api._plugins)
    orphan.api._on_attached_to_parent(plain.api)
    assert len(orphan.api._plugins) == plain_before


def test_inherit_plugins_seed_from_empty_parent_bucket():
    parent = ManualService()
    parent.api.plug("stamp_extra")
    parent.api._plugin_info.pop("stamp_extra", None)
    child = ManualService()
    child.api._on_attached_to_parent(parent.api)
    assert child.api._plugin_info["stamp_extra"]["--base--"]["config"]["enabled"] is True


def test_iter_child_routers_override_deduplicates():
    root = ManualService()
    holder = MultiChild()
    results = root.api._collect_child_routers({"bundle": holder})
    assert results == []


def test_iter_instance_attributes_skip_registry_and_slots():
    inst = SlotRouted()
    setattr(inst, ROUTER_REGISTRY_ATTR_NAME, {"slot": inst.slot_router})
    attrs = list(inst.slot_router._iter_instance_attributes(inst))
    keys = [name for name, _ in attrs]
    assert ROUTER_REGISTRY_ATTR_NAME not in keys
    assert "slot_router" in keys

    class WeirdSlots:
        __slots__ = ROUTER_REGISTRY_ATTR_NAME

        def __init__(self):
            setattr(self, ROUTER_REGISTRY_ATTR_NAME, "value")

    weird = WeirdSlots()
    assert list(inst.slot_router._iter_instance_attributes(weird)) == []

    class RegistryHolder:
        pass

    holder = RegistryHolder()
    setattr(holder, ROUTER_REGISTRY_ATTR_NAME, "registry")
    holder.extra = "value"
    attrs = list(inst.slot_router._iter_instance_attributes(holder))
    assert all(name != ROUTER_REGISTRY_ATTR_NAME for name, _ in attrs)
    assert any(name == "extra" for name, _ in attrs)


def test_router_members_include_metadata_tree():
    parent = ManualService()
    info = parent.api.members()
    assert "children" in info


def test_format_annotation_branches():
    assert _format_annotation(None) == "Any"
    assert _format_annotation("Custom") == "Custom"

    class LocalType:
        pass

    assert _format_annotation(LocalType).endswith("LocalType")


def test_configure_validates_inputs_and_targets():
    svc = LoggingService()
    with pytest.raises(ValueError):
        svc.routedclass.configure([], enabled=True)
    with pytest.raises(ValueError):
        svc.routedclass.configure({"flags": "on"})
    with pytest.raises(TypeError):
        svc.routedclass.configure(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        svc.routedclass.configure("?", foo="bar")
    with pytest.raises(ValueError):
        svc.routedclass.configure("missingcolon", mode="x")
    with pytest.raises(ValueError):
        svc.routedclass.configure(":logging/_all_", mode="x")
    with pytest.raises(ValueError):
        svc.routedclass.configure("api:/_all_", mode="x")
    with pytest.raises(AttributeError):
        svc.routedclass.configure("api:ghost/_all_", flags="on")
    with pytest.raises(ValueError):
        svc.routedclass.configure("api:logging/_all_")
    with pytest.raises(KeyError):
        svc.routedclass.configure("api:logging/missing*", flags="trace")
    result = svc.routedclass.configure("api:logging", flags="trace")
    assert result["updated"] == ["_all_"]


def test_configure_question_success_and_router_proxy_errors():
    svc = LoggingService()
    tree = svc.routedclass.configure("?")
    assert "api" in tree
    with pytest.raises(AttributeError):
        svc.routedclass.get_router("missing")
    registry = getattr(svc, ROUTER_REGISTRY_ATTR_NAME)
    registry.pop("api")
    router = svc.routedclass.get_router("api")
    assert router is svc.api


def test_router_calling_members_handles_custom_pydantic_metadata():
    svc = ManualService()
    svc.api.add_entry(svc.first)
    entry = svc.api._entries["first"]

    class FakeField:
        annotation = str
        default = "value"
        metadata = ("tag",)
        json_schema_extra = {"k": "v"}
        description = "desc"
        examples = ["ex"]
        is_required = None

    class FakeModel:
        model_fields = {"text": FakeField()}

    entry.metadata["pydantic"] = {
        "enabled": True,
        "model": FakeModel(),
    }
    info = svc.api.members()
    param = info["handlers"]["first"]["parameters"]["text"]
    assert param["validation"]["metadata"] == ["tag"]

def test_iter_registered_routers_lists_entries():
    svc = ManualService()
    pairs = list(svc._iter_registered_routers())
    assert pairs and pairs[0][0] == "api"


def test_get_router_skips_empty_segments():
    class Leaf(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="leaf", auto_discover=False)

    class Parent(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = Leaf()
            self.api._children["child"] = self.child.api  # direct attach for test

    svc = Parent()
    router = svc.routedclass.get_router("api.child..")
    assert router.name == "leaf"


def test_iter_child_routers_handles_repeated_objects():
    class DummyChild(RoutedClass):
        def __init__(self):
            self.routes = Router(self, name="routes")

    class RepeatContainer:
        def __init__(self):
            self.api = Router(self, name="api")
            self.child = DummyChild()

    container = RepeatContainer()
    # Iterable inputs no longer scanned; expect empty result
    routes = container.api._collect_child_routers([container.child, container.child])
    assert routes == []


def test_is_routed_class_helper():
    svc = ManualService()
    assert is_routed_class(svc) is True
    assert is_routed_class(object()) is False
