"""Optional Lumina premium module layer."""

from app.modules.registry import (
    MODULE_IDS,
    ModuleRegistry,
    get_module_registry,
    is_module_enabled,
)

__all__ = [
    "MODULE_IDS",
    "ModuleRegistry",
    "get_module_registry",
    "is_module_enabled",
]
