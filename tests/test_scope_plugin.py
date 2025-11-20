"""Tests for the ScopePlugin."""

import pytest

from smartroute import RoutedClass, Router, channels, route


class ScopedService(RoutedClass):
    def __init__(self):
        self.api = Router(self, name="api").plug("scope")

    @route("api", scopes="internal,admin")
    def admin(self):
        return "ok"

    @route("api", scopes="public_shop")
    def public(self):
        return "public"


def test_scope_plugin_describe_and_channel_matrix():
    svc = ScopedService()
    info = svc.api.describe()
    admin_scope = info["methods"]["admin"]["scope"]
    assert admin_scope["tags"] == ["internal", "admin"]
    assert admin_scope["channels"]["internal"] == ["CLI", "SYS_HTTP"]

    public_scope = info["methods"]["public"]["scope"]
    assert public_scope["tags"] == ["public_shop"]
    assert public_scope["channels"]["public_shop"] == ["HTTP"]

    matrix = svc.api.scope.get_channel_map("CLI")
    assert set(matrix.keys()) == {"admin"}
    assert matrix["admin"]["exposed_scopes"] == ["internal"]


def test_scope_plugin_describe_filters_by_scope_and_channel():
    svc = ScopedService()

    filtered_scope = svc.api.describe(scopes="internal")
    assert set(filtered_scope["methods"].keys()) == {"admin"}

    filtered_channel = svc.api.describe(channel="HTTP")
    assert set(filtered_channel["methods"].keys()) == {"public"}

    combined = svc.api.describe(scopes="internal", channel="CLI")
    assert set(combined["methods"].keys()) == {"admin"}

    empty = svc.api.describe(scopes="unknown")
    assert empty["methods"] == {}


def test_scope_plugin_runtime_configuration_updates_entries():
    svc = ScopedService()

    # Apply defaults for every handler via configure()
    svc.routedclass.configure("api:scope/_all_", scopes="internal,sales")
    all_scopes = svc.api.scope.describe_scopes()
    assert all_scopes["admin"]["tags"] == ["internal", "admin"]
    assert all_scopes["public"]["tags"] == ["public_shop"]

    # Override individual handlers
    svc.routedclass.configure("api:scope/admin", scopes="internal,sales")
    assert svc.api.scope.describe_method("admin")["tags"] == ["internal", "sales"]

    svc.routedclass.configure("api:scope/public", scopes="public_shop,internal")
    assert svc.api.scope.describe_method("public")["tags"] == ["public_shop", "internal"]

    svc.routedclass.configure(
        "api:scope/_all_",
        scope_channels={
            "sales": ["OPS_HTTP", "CLI"],
            "internal": ["OPS_HTTP", "CLI"],
            "*": ["CLI"],
        },
    )

    cli_map = svc.api.scope.get_channel_map("CLI")
    assert set(cli_map.keys()) == {"admin", "public"}
    ops_map = svc.api.scope.get_channel_map("OPS_HTTP")
    assert set(ops_map.keys()) == {"admin", "public"}
    assert ops_map["admin"]["exposed_scopes"] == ["internal", "sales"]


def test_scope_plugin_accepts_custom_channel_names_without_registry():
    class ManualScoped(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api", auto_discover=False).plug("scope")

        def ping(self):
            return "pong"

    svc = ManualScoped()
    svc.api.scope.set_config(scope_channels={"internal": ["GHOST"]})
    svc.api.add_entry(svc.ping, name="call", metadata={"scopes": "internal"})
    info = svc.api.describe()
    assert info["methods"]["call"]["scope"]["channels"]["internal"] == ["GHOST"]


def test_scope_plugin_channels_alias_sets_fallbacks():
    class AliasScoped(RoutedClass):
        def __init__(self):
            self.api = Router(self, name="api").plug("scope", channels="ALPHA,BETA")

        @route("api", scopes="internal")
        def handler(self):
            return "ok"

    svc = AliasScoped()
    scope_meta = svc.api.describe()["methods"]["handler"]["scope"]
    assert scope_meta["channels"]["internal"] == ["ALPHA", "BETA"]

    svc.routedclass.configure("api:scope/handler", channels="GAMMA")
    updated = svc.api.describe()["methods"]["handler"]["scope"]
    assert updated["channels"]["internal"] == ["GAMMA"]


def test_members_scope_filtering_limits_handlers():
    svc = ScopedService()

    tree_all = svc.api.members()
    assert set(tree_all["handlers"].keys()) == {"admin", "public"}

    filtered = svc.api.members(scopes="internal")
    assert set(filtered["handlers"].keys()) == {"admin"}
    assert "public" not in filtered["handlers"]

    filtered_multi = svc.api.members(scopes=["public_shop", "unknown"])
    assert set(filtered_multi["handlers"].keys()) == {"public"}

    with pytest.raises(TypeError):
        svc.api.members(scopes=123)  # type: ignore[arg-type]


def test_members_channel_filter_limits_handlers():
    svc = ScopedService()

    cli_only = svc.api.members(channel="CLI")
    assert set(cli_only["handlers"].keys()) == {"admin"}

    app_http = svc.api.members(channel="HTTP")
    assert set(app_http["handlers"].keys()) == {"public"}

    combined = svc.api.members(scopes="internal", channel="CLI")
    assert set(combined["handlers"].keys()) == {"admin"}

    with pytest.raises(TypeError):
        svc.api.members(channel=123)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        svc.api.members(channel="cli")


def test_public_channels_mapping_is_read_only():
    assert channels["CLI"].startswith("Publisher")
    assert set(channels.keys()) >= {"CLI", "SYS_HTTP", "HTTP"}
    with pytest.raises(TypeError):  # mappingproxy is immutable
        channels["CLI"] = "override"  # type: ignore[index]
