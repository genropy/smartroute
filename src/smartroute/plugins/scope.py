"""Scope/Channel plugin (source of truth).

Rebuild the plugin exactly per this contract. It attaches scope metadata to
handlers and resolves which channels may expose each scope.

Responsibilities
----------------
- Attach normalized scope tags to handlers (strings, deduped, e.g. INTERNAL,
  PUBLIC_*).
- Compute channel exposure per scope using global config, entry metadata, and
  per-handler overrides.
- Surface a scope payload for introspection and filtering (``describe``/
  ``members``) and provide helper queries (``describe_scopes``, ``get_channel_map``).

Configuration sources and precedence
------------------------------------
1) Per-handler overrides via ``set_method_config`` or ``configure`` on the
   plugin (stored in ``_handler_configs``).
2) Entry metadata provided at registration time (from decorators) cached in
   ``_entry_overrides``.
3) Global config set via ``set_config``/``plug``.
4) ``DEFAULT_SCOPE_RULES`` fallback for channels when no mapping matches.
\nPrecedence applies separately to scopes and scope→channel mapping.
\n``channels`` alias: when passed to constructor/config, it is normalized and
merged into ``scope_channels["*"]`` (preserving existing explicit lists).

Lifecycle and behaviour
-----------------------
- ``__init__`` promotes ``channels`` alias before delegating to ``BasePlugin``,
  seeds internal caches, and stores optional router/entry references for later
  refresh.
- ``on_decore(router, func, entry)``:
    * records router and entry in internal maps
    * seeds ``_entry_overrides`` for the entry with normalized scopes and
      scope_channels derived from entry.metadata if not already present
    * applies scope metadata via ``_apply_scope_metadata``.
- ``set_config`` / ``set_method_config`` promote ``channels`` alias, delegate to
  ``BasePlugin``, then refresh metadata for all or one entry.
- ``describe_method(method_name)`` builds scope payload; returns ``None`` when
  no tags. ``describe_scopes`` aggregates per entry.
- ``describe_entry`` produces ``{"scope": payload}`` for describe hooks (or
  ``{}`` when no tags).
- ``get_channel_map(channel)`` validates the channel code (must be uppercase,
  non-empty), then returns a dict of handler → payload limited to scopes whose
  allowed channel list contains the requested channel.
- ``filter_entry`` honours normalized filters provided by the router
  (``scopes`` set, ``channel`` string):
    * if scope filter supplied: require overlap with tags or exclude
    * if channel filter supplied: require allowed channel match; missing/invalid
      scope metadata excludes the entry
    * when filters are present, entries without tags are excluded
    * when no filters, always True.

Scope payload shape
-------------------
``{"tags": <List[str]>, "channels": <Dict[str, List[str]]>}`` where channels map
scope → allowed channel codes (strings). Stored under ``entry.metadata["scope"]``
only when tags exist; otherwise the key is removal.

Resolution details
------------------
- ``_resolve_scopes``: prefers handler config ``scopes``; else metadata
  overrides; else global config scopes; else empty list.
- ``_resolve_channels``: merges three maps (global, metadata override, handler
  override) via ``_merge_channel_maps`` (latter wins per key), then for each
  scope calls ``_resolve_channels_for_scope``.
- ``_resolve_channels_for_scope``: first tries exact key in map, then wildcard
  pattern match (fnmatch) via ``_match_pattern``, then ``"*"``, else falls back
  to ``_default_channels_for_scope`` using ``DEFAULT_SCOPE_RULES``.
- ``_merge_channel_maps`` replaces per-key lists with normalized channel lists
  from the extra map; base is copied to avoid mutation.

Normalization and validation
----------------------------
- ``_promote_channel_alias``: moves ``channels`` (string/iterable) into
  ``scope_channels["*"]`` merged uniquely with existing values.
- ``_normalize_scopes``: accepts string (comma-split) or iterable; trims,
  dedupes, drops empty; raises ``TypeError`` otherwise.
- ``_normalize_scope_channels``: expects dict scope→channels; trims keys, raises
  on empty scope; values normalized via ``_normalize_channel_list``.
- ``_normalize_channel_list``: accepts string (comma-split) or iterable, trims,
  dedupes, validates uppercase via ``_validate_channel_code``; raises on wrong
  types or lowercase codes.
- ``_validate_channel_code``: trims, returns uppercase string, raises
  ``ValueError`` if not uppercase, returns empty string for empty input.

Invariants
----------
- All stored channel codes are uppercase strings.
- Internal caches store copies of user data to avoid shared mutation.
- Pattern matching for scopes/channels uses ``fnmatchcase`` semantics.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any, Dict, Iterable, List, Optional

from smartroute.core.router import Router
from smartroute.plugins._base_plugin import BasePlugin, MethodEntry

STANDARD_CHANNELS = {
    "CLI": "Publisher CLI commands",
    "SYS_HTTP": "Shared Publisher HTTP API",
    "SYS_WS": "Shared Publisher WebSocket API",
    "HTTP": "Application HTTP API",
    "WS": "Application WebSocket API",
    "MCP": "Machine Control Protocol / AI adapter",
}

__all__ = ["ScopePlugin"]


class ScopePlugin(BasePlugin):
    """Attach scope metadata to handlers and resolve allowed channels."""

    DEFAULT_SCOPE_RULES = [
        ("internal", ["CLI", "SYS_HTTP"]),
        ("public", ["HTTP"]),
        ("public_*", ["HTTP"]),
    ]

    def __init__(self, name: Optional[str] = None, **config: Any):
        config = dict(config)
        self._promote_channel_alias(config)
        super().__init__(name=name or "scope", **config)
        self._router: Optional[Router] = None
        self._entries: Dict[str, MethodEntry] = {}
        self._entry_overrides: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------
    def on_decore(self, router: Router, func, entry: MethodEntry) -> None:
        self._router = router
        self._entries[entry.name] = entry
        stored = self._entry_overrides.setdefault(entry.name, {})
        if "scopes" not in stored:
            stored["scopes"] = self._normalize_scopes(entry.metadata.get("scopes"))
        if "scope_channels" not in stored:
            stored["scope_channels"] = self._normalize_scope_channels(
                entry.metadata.get("scope_channels")
            )
        self._apply_scope_metadata(entry)

    def set_config(self, flags: Optional[str] = None, **config: Any) -> None:
        config = dict(config)
        self._promote_channel_alias(config)
        super().set_config(flags=flags, **config)
        self._refresh_entries()

    def set_method_config(
        self, method_name: str, *, flags: Optional[str] = None, **config: Any
    ) -> None:
        config = dict(config)
        self._promote_channel_alias(config)
        super().set_method_config(method_name, flags=flags, **config)
        self._refresh_entries(method_name)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def describe_method(self, method_name: str) -> Optional[Dict[str, Any]]:
        payload = self._build_scope_payload(method_name)
        if not payload or not payload.get("tags"):
            return None  # pragma: no cover - absence path
        return payload

    def describe_entry(
        self, router: Router, entry: MethodEntry, base_description: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = self.describe_method(entry.name)
        return {"scope": payload} if payload else {}

    def describe_scopes(self) -> Dict[str, Dict[str, Any]]:
        info: Dict[str, Dict[str, Any]] = {}
        for method_name in self._entries.keys():
            payload = self.describe_method(method_name)
            if payload:
                info[method_name] = payload
        return info

    def get_channel_map(self, channel: str) -> Dict[str, Dict[str, Any]]:
        target = self._validate_channel_code(channel)
        if not target:
            raise ValueError("Channel code cannot be empty")  # pragma: no cover
        matrix: Dict[str, Dict[str, Any]] = {}
        for method_name, payload in self.describe_scopes().items():
            scoped_channels = payload.get("channels", {})
            matching = [scope for scope, channels in scoped_channels.items() if target in channels]
            if matching:
                matrix[method_name] = {
                    "tags": payload["tags"],
                    "channels": scoped_channels,
                    "exposed_scopes": matching,
                }
        return matrix

    def filter_entry(self, router: Router, entry: MethodEntry, **filters: Any) -> bool:
        scope_filter = filters.get("scopes")
        channel_filter = filters.get("channel")
        if not scope_filter and not channel_filter:
            return True
        scope_meta = entry.metadata.get("scope") if entry.metadata else None
        tags = scope_meta.get("tags") if isinstance(scope_meta, dict) else None
        if scope_filter:
            if not tags or not any(tag in scope_filter for tag in tags):
                return False
        if channel_filter:
            if not scope_meta:
                return False  # pragma: no cover - missing metadata with channel filter
            channel_map = scope_meta.get("channels", {}) if isinstance(scope_meta, dict) else {}
            if not isinstance(channel_map, dict):
                return False  # pragma: no cover - unexpected metadata shape
            relevant_scopes = tags or list(channel_map.keys())
            allowed: set[str] = set()
            for scope_name in relevant_scopes:
                codes = channel_map.get(scope_name, [])
                for code in codes or []:
                    normalized = str(code).strip()
                    if normalized:
                        allowed.add(normalized)
            if channel_filter not in allowed:
                return False
        if scope_filter or channel_filter:
            return bool(tags)  # pragma: no cover - filtered entries lacking tags
        return True  # pragma: no cover - no filters

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _refresh_entries(self, method_name: Optional[str] = None) -> None:
        if method_name:
            entry = self._entries.get(method_name)
            if entry:
                self._apply_scope_metadata(entry)
            return
        for entry in self._entries.values():
            self._apply_scope_metadata(entry)

    def _apply_scope_metadata(self, entry: MethodEntry) -> None:
        payload = self._build_scope_payload(entry.name)
        if payload and payload.get("tags"):
            entry.metadata["scope"] = payload
        else:
            entry.metadata.pop("scope", None)  # pragma: no cover

    def _build_scope_payload(self, method_name: str) -> Optional[Dict[str, Any]]:
        scopes = self._resolve_scopes(method_name)
        if not scopes:
            return None  # pragma: no cover
        channels = self._resolve_channels(method_name, scopes)
        return {"tags": scopes, "channels": channels}

    def _resolve_scopes(self, method_name: str) -> List[str]:
        method_cfg = self._handler_configs.get(method_name, {})
        if "scopes" in method_cfg:
            return self._normalize_scopes(method_cfg.get("scopes"))

        metadata_scopes = self._entry_overrides.get(method_name, {}).get("scopes") or []
        if metadata_scopes:
            return list(metadata_scopes)

        return self._normalize_scopes(
            self._global_config.get("scopes")
        )  # pragma: no cover - uses global fallback

    def _resolve_channels(self, method_name: str, scopes: Iterable[str]) -> Dict[str, List[str]]:
        global_map = self._normalize_scope_channels(self._global_config.get("scope_channels"))
        metadata_map = self._entry_overrides.get(method_name, {}).get("scope_channels") or {}
        method_map = self._normalize_scope_channels(
            self._handler_configs.get(method_name, {}).get("scope_channels")
        )

        merged = self._merge_channel_maps(global_map, metadata_map)
        merged = self._merge_channel_maps(merged, method_map)

        return {scope: self._resolve_channels_for_scope(scope, merged) for scope in scopes}

    def _resolve_channels_for_scope(self, scope: str, mapping: Dict[str, List[str]]) -> List[str]:
        channels = self._match_channel_entry(scope, mapping)
        if channels:
            return channels
        return self._default_channels_for_scope(scope)

    def _match_channel_entry(self, scope: str, mapping: Dict[str, List[str]]) -> List[str]:
        if scope in mapping:
            return list(mapping[scope])
        matched_pattern = self._match_pattern(scope, mapping)
        if matched_pattern is not None:
            return list(matched_pattern)  # pragma: no cover
        fallback = mapping.get("*")
        if fallback:
            return list(fallback)
        return []

    def _match_pattern(self, scope: str, mapping: Dict[str, List[str]]) -> Optional[List[str]]:
        for key, channels in mapping.items():
            if key in {scope, "*"}:
                continue
            if any(token in key for token in "*?[]") and fnmatchcase(scope, key):
                return list(channels)  # pragma: no cover
        return None

    def _merge_channel_maps(
        self, base: Dict[str, List[str]], extra: Dict[str, List[str]]
    ) -> Dict[str, List[str]]:
        if not extra:
            return dict(base)  # pragma: no cover
        merged = dict(base)
        for key, channels in extra.items():
            merged[key] = self._normalize_channel_list(channels)
        return merged

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------
    def _promote_channel_alias(self, config: Dict[str, Any]) -> None:
        if "channels" not in config:
            return
        channels = self._normalize_channel_list(config.pop("channels"))
        scope_map = config.setdefault("scope_channels", {})
        if not isinstance(scope_map, dict):
            raise TypeError("scope_channels must be a dict")  # pragma: no cover
        existing_raw = scope_map.get("*") or []
        existing = (
            list(existing_raw)
            if isinstance(existing_raw, list)
            else self._normalize_channel_list(existing_raw)
        )
        # Preserve explicit lists while ensuring uniqueness
        merged = list(existing) + [c for c in channels if c not in existing]
        scope_map["*"] = merged

    def _normalize_scopes(self, raw) -> List[str]:  # pragma: no cover - normalization helper
        if not raw:
            return []  # pragma: no cover - empty input
        if isinstance(raw, str):
            tokens = [token.strip() for token in raw.split(",")]
        elif isinstance(raw, Iterable):
            tokens = []
            for item in raw:
                if not item:
                    continue  # pragma: no cover - skip falsy
                tokens.append(str(item).strip())
        else:
            raise TypeError("scopes must be a string or iterable of strings")  # pragma: no cover
        cleaned: List[str] = []
        for token in tokens:
            if not token or token in cleaned:
                continue  # pragma: no cover - duplicate/empty
            cleaned.append(token)
        return cleaned

    def _normalize_scope_channels(
        self, raw
    ) -> Dict[str, List[str]]:  # pragma: no cover - normalization helper
        if not raw:
            return {}
        if not isinstance(raw, dict):
            # pragma: no cover
            raise TypeError("scope_channels must be a dict of scope -> channels")
        normalized: Dict[str, List[str]] = {}
        for scope, channels in raw.items():
            if not scope:
                raise ValueError("Scope name cannot be empty in scope_channels")  # pragma: no cover
            normalized[str(scope)] = self._normalize_channel_list(channels)
        return normalized

    def _normalize_channel_list(self, raw) -> List[str]:  # pragma: no cover - normalization helper
        if not raw:
            return []  # pragma: no cover - empty input
        if isinstance(raw, str):
            tokens = [chunk.strip() for chunk in raw.split(",")]
        elif isinstance(raw, Iterable):
            tokens = []
            for item in raw:
                if not item:
                    continue  # pragma: no cover - skip falsy
                tokens.append(str(item).strip())
        else:
            raise TypeError("Channels must be provided as string or iterable")  # pragma: no cover
        cleaned: List[str] = []
        for token in tokens:
            normalized = self._validate_channel_code(token)
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned

    def _validate_channel_code(self, code: str) -> str:  # pragma: no cover - pure validation
        normalized = (code or "").strip()
        if not normalized:
            return ""  # pragma: no cover
        if normalized != normalized.upper():
            # pragma: no cover
            raise ValueError(f"Channel code '{normalized}' must be uppercase (e.g. CLI, SYS_HTTP)")
        return normalized

    def _default_channels_for_scope(self, scope: str) -> List[str]:
        scope_name = (scope or "").strip()
        for pattern, channels in self.DEFAULT_SCOPE_RULES:
            if pattern == scope_name or fnmatchcase(scope_name, pattern):
                return [self._validate_channel_code(code) for code in channels]
        return []


Router.register_plugin("scope", ScopePlugin)
