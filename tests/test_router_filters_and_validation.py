"""Coverage for Router filter normalization and plugin filtering."""

from __future__ import annotations

import pytest

from smartroute import RoutedClass, Router, route
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry


class _FilterPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="filtertest")
        self.calls: list[dict] = []

    def filter_entry(self, router, entry, **filters):
        self.calls.append(filters)
        # Hide when scopes filter is present, otherwise keep entry visible.
        return False if filters.get("scopes") else None


class _BadDescribePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="baddescribe")

    def describe_entry(self, router, entry, base_description):
        return ["not-a-dict"]


class _GoodDescribePlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="gooddescribe")

    def describe_entry(self, router, entry, base_description):
        return {"extra": {"via": self.name}}


def _make_router():
    class Owner:
        pass

    return Router(Owner(), name="api")


def test_prepare_filter_args_normalizes_scopes_and_channel():
    router = _make_router()
    filters = router._prepare_filter_args(scopes="a,b", channel="CLI")
    assert filters["scopes"] == {"a", "b"}
    assert filters["channel"] == "CLI"

    filters = router._prepare_filter_args(scopes=None, channel=None)
    assert "scopes" not in filters and "channel" not in filters


def test_should_include_entry_respects_filter_plugins():
    Router.register_plugin("filtertest", _FilterPlugin)
    router = _make_router().plug("filtertest")
    entry = MethodEntry("demo", lambda: None, router, plugins=[])

    # scopes filter triggers plugin veto
    assert router._should_include_entry(entry, scopes={"s1"}) is False
    # without scopes filter plugin returns None and entry passes through
    assert router._should_include_entry(entry) is True
    plugin = router._plugins_by_name["filtertest"]
    assert len(plugin.calls) == 2


def test_describe_entry_extra_rejects_non_dict_from_plugin():
    Router.register_plugin("baddescribe", _BadDescribePlugin)
    router = _make_router().plug("baddescribe")
    entry = MethodEntry("demo", lambda: None, router, plugins=[])

    with pytest.raises(TypeError):
        router._describe_entry_extra(entry, {})


def test_describe_merges_plugin_contrib():
    Router.register_plugin("gooddescribe", _GoodDescribePlugin)

    class Service(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("gooddescribe")

        @route("api")
        def hello(self):
            return "ok"

    svc = Service()
    info = svc.api.describe()
    assert info["methods"]["hello"]["extra"] == {"via": "gooddescribe"}


def test_normalize_scope_filter_validation_paths():
    router = _make_router()
    assert router._normalize_scope_filter(None) is None
    assert router._normalize_scope_filter(False) is None
    assert router._normalize_scope_filter(" a , b ") == {"a", "b"}
    assert router._normalize_scope_filter([]) is None
    with pytest.raises(TypeError):
        router._normalize_scope_filter(123)


def test_normalize_channel_filter_validation_paths():
    router = _make_router()
    assert router._normalize_channel_filter(None) is None
    assert router._normalize_channel_filter(False) is None
    assert router._normalize_channel_filter("CLI") == "CLI"
    with pytest.raises(ValueError):
        router._normalize_channel_filter("cli")  # not uppercase
    with pytest.raises(ValueError):
        router._normalize_channel_filter("  ")  # empty after strip
    with pytest.raises(TypeError):
        router._normalize_channel_filter(123)


def test_members_respects_plugin_filter_skip():
    Router.register_plugin("filtertest", _FilterPlugin)
    router = _make_router().plug("filtertest")
    router.add_entry(lambda: "ok", name="hidden")

    tree = router.members(scopes="internal")
    assert tree["handlers"] == {}
