"""Shared contracts for optional Lumina modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModuleStatus = Literal["implemented", "planned", "experimental"]


@dataclass(frozen=True)
class ModuleManifest:
    """Describes a module without importing its implementation."""

    module_id: str
    title: str
    description: str
    status: ModuleStatus = "planned"
    enabled_by_default: bool = False
    priority: int | None = None
    dependencies: tuple[str, ...] = ()
    windows_v2_safe: bool = True
    pyinstaller_safe: bool = True

    @property
    def env_key(self) -> str:
        return self.module_id.upper().replace("-", "_")
