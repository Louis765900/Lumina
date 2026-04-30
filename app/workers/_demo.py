"""
Development-only demo scan data.
Imported by ScanWorker only when LUMINA_ENABLE_DEMO=1 is set.
"""

SIM_FILES: list[tuple[str, str, int, int]] = [
    ("photo_vacances_2023",  ".jpg",   2048, 95),
    ("IMG_4201",             ".jpg",   3584, 100),
    ("IMG_4202",             ".jpg",   2900, 100),
    ("screenshot_001",       ".png",    512, 90),
    ("logo_projet",          ".png",    768, 85),
    ("wallpaper_4k",         ".png",   4096, 100),
    ("video_anniversaire",   ".mp4",  98304, 70),
    ("clip_reunion_2023",    ".mp4",  45056, 80),
    ("screen_recording",     ".mp4",  12288, 65),
    ("rapport_annuel_2023",  ".pdf",    896, 100),
    ("facture_mars_2024",    ".pdf",    256, 95),
    ("cv_2024",              ".pdf",    384, 100),
    ("presentation_Q1",      ".pptx",  2048, 90),
    ("tableau_de_bord",      ".xlsx",  1024, 95),
    ("archive_projet_web",   ".zip",   6400, 80),
    ("backup_photos",        ".zip",  12800, 75),
    ("musique_playlist",     ".mp3",   4096, 70),
    ("document_contrat",     ".docx",   512, 100),
    ("photo_profil",         ".jpg",   1024, 90),
    ("export_donnees",       ".xlsx",  2048, 85),
]

PHASES: list[str] = [
    "Lecture de la table de partition MBR/GPT…",
    "Analyse du superbloc du système de fichiers…",
    "Parcours des clusters alloués…",
    "Recherche des signatures JPEG / PNG / BMP…",
    "Recherche des signatures MP4 / MOV / MKV…",
    "Recherche des signatures PDF / DOCX / XLSX…",
    "Recherche des signatures audio MP3 / WAV / FLAC…",
    "Vérification des clusters non alloués…",
    "Reconstruction des métadonnées de fichiers…",
    "Finalisation et déduplication des résultats…",
]
