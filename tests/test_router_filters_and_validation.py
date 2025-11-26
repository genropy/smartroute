"""Coverage for Router plugin filtering."""

from __future__ import annotations

import pytest

from smartroute import Router
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry


class _FilterPlugin(BasePlugin):
    plugin_code = "filtertest"
    plugin_description = "Filter test plugin"

    def __init__(self, router, **config):
        super().__init__(router, **config)
        self.calls: list[dict] = []

    def allow_entry(self, router, entry, **filters):
        self.calls.append(filters)
        # Hide when scopes filter is present, otherwise keep entry visible.
        return False if filters.get("scopes") else None


class _BadMetadataPlugin(BasePlugin):
    plugin_code = "badmetadata"
    plugin_description = "Bad metadata test plugin"

    def __init__(self, router, **config):
        super().__init__(router, **config)

    def entry_metadata(self, router, entry):
        return ["not-a-dict"]


class _GoodMetadataPlugin(BasePlugin):
    plugin_code = "goodmetadata"
    plugin_description = "Good metadata test plugin"

    def __init__(self, router, **config):
        super().__init__(router, **config)

    def entry_metadata(self, router, entry):
        return {"extra": {"via": self.name}}


def _make_router():
    class Owner:
        pass

    return Router(Owner(), name="api")


def test_allow_entry_respects_plugins():
    Router.register_plugin(_FilterPlugin)
    router = _make_router().plug("filtertest")
    entry = MethodEntry("demo", lambda: None, router, plugins=[])

    # scopes filter triggers plugin veto (plugin receives raw filter value)
    assert router._allow_entry(entry, scopes="internal") is False
    # without scopes filter plugin returns None and entry passes through
    assert router._allow_entry(entry) is True
    plugin = router._plugins_by_name["filtertest"]
    assert len(plugin.calls) == 2


def test_members_entry_extra_rejects_non_dict_from_plugin():
    Router.register_plugin(_BadMetadataPlugin)
    router = _make_router().plug("badmetadata")
    entry = MethodEntry("demo", lambda: None, router, plugins=[])

    with pytest.raises(TypeError):
        router._describe_entry_extra(entry, {})


def test_members_respects_plugin_allow_skip():
    Router.register_plugin(_FilterPlugin)
    router = _make_router().plug("filtertest")
    router.add_entry(lambda: "ok", name="hidden")

    # Filter is passed as-is to plugin; plugin decides how to interpret it
    tree = router.members(scopes="internal")
    assert tree == {}
