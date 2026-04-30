from __future__ import annotations

TEXT: dict[str, dict[str, str]] = {
    "fr": {
        "scan.quick_unavailable": (
            "Scan rapide non disponible pour cette source. Lancez un scan profond."
        ),
        "scan.quick_few_results": (
            "Scan rapide : aucun fichier supprimé récent trouvé dans la MFT. "
            "Lancez un Scan Complet pour une récupération approfondie par signature."
        ),
        "scan.demo_disabled": (
            "Le mode démo est désactivé en production. "
            "Définissez LUMINA_ENABLE_DEMO=1 pour les tests de développement."
        ),
        "scan.engine_native": "Moteur natif rapide",
        "scan.engine_python": "Moteur compatible Python",
        "settings.language": "Langue",
        "settings.recovery_dir": "Dossier de récupération",
        "settings.scan_engine": "Moteur de scan",
        "disclaimer.title": "Avertissement récupération",
    },
    "en": {
        "scan.quick_unavailable": (
            "Quick Scan is not available for this source. Run Deep Scan instead."
        ),
        "scan.quick_few_results": (
            "Quick Scan: no recently-deleted files found in the MFT. "
            "Run a Deep Scan for signature-based recovery."
        ),
        "scan.demo_disabled": (
            "Demo mode is disabled in production. Set LUMINA_ENABLE_DEMO=1 "
            "for development tests."
        ),
        "scan.engine_native": "Fast native engine",
        "scan.engine_python": "Compatible Python engine",
        "settings.language": "Language",
        "settings.recovery_dir": "Recovery folder",
        "settings.scan_engine": "Scan engine",
        "disclaimer.title": "Recovery disclaimer",
    },
}


def t(key: str, language: str = "fr") -> str:
    lang = language if language in TEXT else "fr"
    return TEXT.get(lang, {}).get(key) or TEXT["fr"].get(key) or key
