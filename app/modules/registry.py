"""Registry and feature flags for optional Lumina modules."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from app.modules.base import ModuleManifest

MODULE_IDS: tuple[str, ...] = (
    "core-scan-engine",
    "storage-index",
    "integrity-score",
    "disk-health",
    "rescue-imaging",
    "filesystem-analyzers",
    "evidence-readers",
    "file-identification",
    "metadata-extraction",
    "preview-engine",
    "security-scan",
    "hash-dedup",
    "reporting-suite",
    "forensic-chain",
    "premium-ui",
    "search-filters",
    "smart-recovery",
    "windows-deep-recovery",
    "format-validators",
    "content-intelligence",
    "timeline",
    "observability",
    "quality-lab",
    "release-engine",
    "plugin-sdk",
    "help-center",
    "local-assistant",
)

_IMPLEMENTED: dict[str, tuple[int, str]] = {
    "storage-index": (1, "SQLite-backed scan index with FTS5 search."),
    "integrity-score": (2, "Recoverability scoring enrichment for file candidates."),
    "search-filters": (3, "Shared filtering, query, and sorting engine."),
    "reporting-suite": (4, "Reusable JSON, CSV, DFXML, and HTML report emitters."),
    "disk-health": (5, "Read-only disk health collector with optional smartctl adapter."),
}

_DESCRIPTIONS: dict[str, str] = {
    "core-scan-engine": "Future optional orchestration layer for scan engines.",
    "rescue-imaging": "Future read-only imaging and unstable-disk acquisition tools.",
    "filesystem-analyzers": "Future filesystem-specific analyzers.",
    "evidence-readers": "Future forensic evidence container readers.",
    "file-identification": "Future richer file type identification.",
    "metadata-extraction": "Future metadata extractors.",
    "preview-engine": "Future preview rendering layer.",
    "security-scan": "Future malware and unsafe-content checks.",
    "hash-dedup": "Future hash-based duplicate detection.",
    "forensic-chain": "Future chain-of-custody log and sealing layer.",
    "premium-ui": "Future premium UI surfaces.",
    "smart-recovery": "Future strategy selection for recovery plans.",
    "windows-deep-recovery": "Future Windows-specific deep recovery adapters.",
    "format-validators": "Future validators for recovered file formats.",
    "content-intelligence": "Future local content understanding features.",
    "timeline": "Future timeline reconstruction.",
    "observability": "Future metrics and structured telemetry for local diagnostics.",
    "quality-lab": "Future regression corpus and quality gates.",
    "release-engine": "Future release automation support.",
    "plugin-sdk": "Future public SDK for third-party modules.",
    "help-center": "Future in-app help and recovery guidance.",
    "local-assistant": "Future local assistant integration.",
}


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _falsy(value: object) -> bool:
    return str(value).strip().lower() in {"0", "false", "no", "off", "disabled"}


def _split_env(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip().lower() for part in value.replace(";", ",").split(",") if part.strip()}


def _module_setting_enabled(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, Mapping):
        enabled = raw.get("enabled")
        if isinstance(enabled, bool):
            return enabled
        if isinstance(enabled, str):
            if _truthy(enabled):
                return True
            if _falsy(enabled):
                return False
    if isinstance(raw, str):
        if _truthy(raw):
            return True
        if _falsy(raw):
            return False
    return None


def _build_manifests() -> dict[str, ModuleManifest]:
    manifests: dict[str, ModuleManifest] = {}
    for module_id in MODULE_IDS:
        if module_id in _IMPLEMENTED:
            priority, description = _IMPLEMENTED[module_id]
            manifests[module_id] = ModuleManifest(
                module_id=module_id,
                title=module_id.replace("-", " ").title(),
                description=description,
                status="implemented",
                enabled_by_default=True,
                priority=priority,
            )
        else:
            manifests[module_id] = ModuleManifest(
                module_id=module_id,
                title=module_id.replace("-", " ").title(),
                description=_DESCRIPTIONS.get(module_id, "Future optional module."),
                status="planned",
                enabled_by_default=False,
            )
    return manifests


class ModuleRegistry:
    """Resolves module availability from defaults, settings, and environment."""

    def __init__(
        self,
        settings: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings or {}
        self._env = env if env is not None else os.environ
        self._manifests = _build_manifests()

    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._manifests[module_id] for module_id in MODULE_IDS)

    def get(self, module_id: str) -> ModuleManifest:
        try:
            return self._manifests[module_id]
        except KeyError as exc:
            raise KeyError(f"unknown Lumina module: {module_id}") from exc

    def is_enabled(self, module_id: str) -> bool:
        manifest = self.get(module_id)
        enabled = manifest.enabled_by_default

        modules_settings = self._settings.get("modules")
        if isinstance(modules_settings, Mapping):
            setting_value = _module_setting_enabled(modules_settings.get(module_id))
            if setting_value is not None:
                enabled = setting_value

        disabled = _split_env(self._env.get("LUMINA_MODULES_DISABLED"))
        if "all" in disabled or module_id in disabled or manifest.env_key.lower() in disabled:
            enabled = False

        enabled_list = _split_env(self._env.get("LUMINA_MODULES_ENABLED"))
        if module_id in enabled_list or manifest.env_key.lower() in enabled_list:
            enabled = True

        direct = self._env.get(f"LUMINA_MODULE_{manifest.env_key}")
        if direct is not None:
            if _truthy(direct):
                enabled = True
            elif _falsy(direct):
                enabled = False

        disabled_direct = self._env.get(f"LUMINA_DISABLE_{manifest.env_key}")
        if disabled_direct is not None and _truthy(disabled_direct):
            enabled = False

        if manifest.status != "implemented" and module_id not in enabled_list:
            return False
        return enabled

    def enabled_manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(manifest for manifest in self.manifests() if self.is_enabled(manifest.module_id))


def get_module_registry(
    settings: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ModuleRegistry:
    if settings is None:
        try:
            from app.core.settings import load_settings

            settings = load_settings()
        except Exception:
            settings = {}
    return ModuleRegistry(settings=settings, env=env)


def is_module_enabled(
    module_id: str,
    settings: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    return get_module_registry(settings=settings, env=env).is_enabled(module_id)
