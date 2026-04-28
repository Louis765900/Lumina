"""
Lumina Scan Worker (QThread)

Production scans are real-only. The legacy simulation path is available only
when LUMINA_ENABLE_DEMO=1 is set for development.
"""

import bisect
import logging
import os
import random
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.i18n import t
from app.core.settings import is_demo_enabled

_log = logging.getLogger("lumina.recovery")
_NATIVE_IMAGE_ONLY_ERROR = "Native engine Phase 4 supports image files only."
_NATIVE_VALIDATION_WINDOW = 4 * 1024 * 1024


class _DedupIndex:
    """
    Interval index for silent dedup between the filesystem phase and the
    carving phase. Phase 1 calls add() for every data run harvested from
    the MFT (or equivalent); freeze() then merges overlaps so Phase 2 can
    query overlaps() in O(log n).

    Any overlap (tout chevauchement) between a carved candidate and a
    recorded MFT run is treated as the same file — the carved candidate
    is silently dropped. This matches the user-validated semantics:
    results should be clean, no partial-fragment duplicates of named files.
    """

    def __init__(self) -> None:
        self._raw: list[tuple[int, int]] = []
        self._starts: list[int] = []
        self._ends:   list[int] = []

    def add(self, start: int, length: int) -> None:
        if length > 0 and start >= 0:
            self._raw.append((start, start + length))

    def freeze(self) -> None:
        """Sort + merge overlapping ranges; enables O(log n) overlaps() queries."""
        if not self._raw:
            return
        self._raw.sort()
        merged: list[tuple[int, int]] = []
        for s, e in self._raw:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        self._starts = [r[0] for r in merged]
        self._ends   = [r[1] for r in merged]

    def overlaps(self, start: int, length: int) -> bool:
        if length <= 0 or start < 0 or not self._starts:
            return False
        end = start + length
        pos = bisect.bisect_right(self._starts, start)
        if pos > 0 and self._ends[pos - 1] > start:
            return True
        if pos < len(self._starts) and self._starts[pos] < end:
            return True
        return False

    def __len__(self) -> int:
        return len(self._starts)


def _to_raw_device(device: str) -> str:
    """Convertit un chemin de lecteur (ex: 'C:') en chemin brut Windows."""
    dev = device.strip()
    if not dev:
        raise ValueError("Chemin de périphérique vide")
    if dev.startswith("\\\\.\\") or dev.startswith("\\\\?\\"):
        return dev
    if len(dev) >= 2 and dev[1] == ":":
        return f"\\\\.\\{dev[0].upper()}:"
    if dev.startswith("\\\\"):
        return dev
    raise ValueError(f"Chemin invalide : {dev!r}")


def _is_local_image_source(device: str) -> bool:
    dev = device.strip()
    if not dev:
        return False
    if dev.startswith("\\\\.\\") or dev.startswith("\\\\?\\"):
        return False
    if len(dev) == 2 and dev[1] == ":":
        return False
    try:
        path = Path(dev)
        return path.is_file()
    except OSError:
        return False


class ScanWorker(QThread):
    """
    Signaux :
        progress(int)           — 0 à 100
        status_text(str)        — message de statut lisible
        files_batch_found(list) — lot de fichiers détectés
        finished(list)          — liste complète à la fin
        error(str)              — erreur irrécupérable
    """

    progress          = pyqtSignal(int)
    status_text       = pyqtSignal(str)
    files_batch_found = pyqtSignal(list)
    finished          = pyqtSignal(list)
    error             = pyqtSignal(str)

    # ── Données de simulation ─────────────────────────────────────────────────
    _SIM_FILES = [
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

    _PHASES = [
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

    def __init__(self, disk: dict, simulate: bool = False, parent=None):
        super().__init__(parent)
        if simulate and not is_demo_enabled():
            raise ValueError(t("scan.demo_disabled"))
        self._disk            = disk
        self._simulate        = simulate
        self._stop_requested  = False
        self._pause_event     = threading.Event()
        self._pause_event.set()          # non mis en pause par défaut
        self._found_files: list[dict] = []
        self._lock = threading.Lock()

    # ── Contrôle public ───────────────────────────────────────────────────────

    def stop(self):
        self._stop_requested = True
        self._pause_event.set()   # débloquer si en pause pour permettre la sortie

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    # ── Entrée du thread ──────────────────────────────────────────────────────

    def run(self):
        self._found_files    = []
        self._stop_requested = False
        self._pause_event.set()
        try:
            if self._simulate:
                self._run_simulation()
            else:
                self._run_real()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            with self._lock:
                snapshot = list(self._found_files)
            self.finished.emit(snapshot)

    # ── Mode simulation ───────────────────────────────────────────────────────

    def _run_simulation(self):
        if not is_demo_enabled():
            raise RuntimeError(t("scan.demo_disabled"))

        device  = self._disk.get("device", "Disque")
        size_gb = self._disk.get("size_gb", 0)

        self.status_text.emit(f"Initialisation du scan sur {device} ({size_gb} Go)…")
        self.progress.emit(0)
        self.msleep(500)

        used_names: set[str] = set()
        phase_step = 80 // len(self._PHASES)

        for i, phase in enumerate(self._PHASES):
            self._pause_event.wait()
            if self._stop_requested:
                self.status_text.emit("Scan annulé par l'utilisateur.")
                return

            self.status_text.emit(phase)
            self.progress.emit(i * phase_step)

            # À partir de la phase 3, on commence à trouver des fichiers
            if i >= 3:
                with self._lock:
                    used_names = {f["name"] for f in self._found_files}

                available = [
                    (n, e, s, q) for n, e, s, q in self._SIM_FILES
                    if f"{n}{e}" not in used_names
                ]
                to_add = available[: random.randint(1, 3)]
                batch = []

                for name, ext, size_kb, integrity in to_add:
                    self._pause_event.wait()
                    if self._stop_requested:
                        return
                    info = {
                        "name":      f"{name}{ext}",
                        "type":      ext.upper().lstrip("."),
                        "offset":    random.randint(0, 500_000_000),
                        "size_kb":   size_kb,
                        "device":    device,
                        "integrity": integrity,
                        "simulated": True,
                    }
                    with self._lock:
                        self._found_files.append(info)
                    batch.append(info)

                if batch:
                    self.files_batch_found.emit(batch)

            self.msleep(random.randint(280, 560))

        # Balayage final : ajouter les fichiers restants
        self.status_text.emit("Analyse des secteurs restants…")
        with self._lock:
            used_names = {f["name"] for f in self._found_files}

        pct = 82
        for name, ext, size_kb, integrity in self._SIM_FILES:
            self._pause_event.wait()
            if self._stop_requested:
                return
            fname = f"{name}{ext}"
            if fname not in used_names:
                pct = min(97, pct + 1)
                self.progress.emit(pct)
                info = {
                    "name":      fname,
                    "type":      ext.upper().lstrip("."),
                    "offset":    random.randint(0, 500_000_000),
                    "size_kb":   size_kb,
                    "device":    device,
                    "integrity": integrity,
                    "simulated": True,
                }
                with self._lock:
                    self._found_files.append(info)
                self.files_batch_found.emit([info])
                self.msleep(100)

        with self._lock:
            n = len(self._found_files)
        self.status_text.emit(f"Analyse terminée — {n} fichier(s) récupérable(s).")
        self.progress.emit(100)
        self.msleep(300)

    def _run_python_carving(
        self,
        raw_dev: str,
        carver,
        dedup_check,
        pct_base: int,
        pct_scale: int,
    ) -> None:
        local_batch: list[dict] = []
        last_emit = time.monotonic()

        def _on_progress(pct: int) -> None:
            self._pause_event.wait()
            if not self._stop_requested:
                self.progress.emit(pct_base + pct * pct_scale // 100)

        def _on_file(info: dict) -> None:
            nonlocal local_batch, last_emit
            self._pause_event.wait()
            with self._lock:
                self._found_files.append(info)
            local_batch.append(info)
            now = time.monotonic()
            if len(local_batch) >= 50 or (now - last_emit) > 0.2:
                self.files_batch_found.emit(list(local_batch))
                local_batch.clear()
                last_emit = now

        carver.scan(
            raw_dev,
            progress_cb=_on_progress,
            file_found_cb=_on_file,
            stop_flag=lambda: self._stop_requested,
            dedup_check=dedup_check,
        )

        if local_batch:
            self.files_batch_found.emit(local_batch)

    def _run_native_image_carving(
        self,
        *,
        image_path: str,
        carver,
        dedup_check,
        pct_base: int,
        pct_scale: int,
    ) -> None:
        from app.core.native.client import NativeScanClient
        from app.core.native.protocol import NativeCandidate, NativeSignature, NativeSource

        image = Path(image_path)
        source = NativeSource(kind="image", path=str(image), size_bytes=image.stat().st_size)
        signatures = [
            NativeSignature(signature_id, ext, header)
            for signature_id, ext, header in carver.native_signature_records()
        ]
        client = NativeScanClient(engine="native")
        if not client.available():
            raise RuntimeError(f"native helper not found: {client.helper_path()}")

        native_buffer: list[dict] = []
        seen: set[tuple[int, str]] = set()
        counter: dict[str, int] = {}

        self.status_text.emit("Analyse native des signatures binaires...")

        with image.open("rb") as fh:

            def _on_candidates(batch: list[NativeCandidate]) -> None:
                for candidate in batch:
                    key = (candidate.offset, candidate.signature_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    info = self._native_candidate_to_file_info(
                        fh,
                        carver,
                        image_path,
                        candidate,
                        counter,
                        dedup_check,
                    )
                    if info is not None:
                        native_buffer.append(info)

            def _on_progress(progress) -> None:
                self._pause_event.wait()
                if not self._stop_requested:
                    self.progress.emit(pct_base + progress.percent * pct_scale // 100)

            summary = client.scan_candidates(
                source,
                signatures,
                on_candidates=_on_candidates,
                on_progress=_on_progress,
                stop_flag=lambda: self._stop_requested,
            )

        if summary.stopped:
            self.status_text.emit("Scan natif annule - validation des resultats partiels.")

        if native_buffer:
            with self._lock:
                self._found_files.extend(native_buffer)
            self.files_batch_found.emit(list(native_buffer))

    def _native_candidate_to_file_info(
        self,
        fh,
        carver,
        image_path: str,
        candidate,
        counter: dict[str, int],
        dedup_check,
    ) -> dict | None:
        window_base = max(0, candidate.offset - 4)
        fh.seek(window_base)
        data = fh.read(_NATIVE_VALIDATION_WINDOW)
        file_info, _reason = carver.build_file_info_from_candidate(
            signature_id=candidate.signature_id,
            candidate_offset=candidate.offset,
            data=data,
            data_base_offset=window_base,
            device=image_path,
            counter=counter,
            dedup_check=dedup_check,
            source="native_carver",
        )
        return file_info

    def _enumerate_filesystem_metadata(
        self,
        raw_dev: str,
        progress_map,
    ) -> tuple[_DedupIndex, bool, str, int]:
        from app.core.fs_parser import detect_fs

        dedup_index = _DedupIndex()
        fs_ok = False
        fs_name = ""
        count = 0

        try:
            fd = os.open(raw_dev, os.O_RDONLY | os.O_BINARY)
            try:
                self.status_text.emit("Détection du système de fichiers…")
                parser = detect_fs(raw_dev, fd)

                if parser is not None:
                    fs_name = parser.name
                    self.status_text.emit(
                        f"Analyse {fs_name} — récupération des noms d'origine…"
                    )

                    def _fs_progress(pct: int) -> None:
                        self._pause_event.wait()
                        if not self._stop_requested:
                            self.progress.emit(progress_map(pct))

                    def _fs_file(info: dict) -> None:
                        self._pause_event.wait()
                        for start, length in info.get("data_runs", ()):
                            dedup_index.add(start, length)
                        with self._lock:
                            self._found_files.append(info)
                        self.files_batch_found.emit([info])

                    count = parser.enumerate_files(
                        stop_flag=lambda: self._stop_requested,
                        progress_cb=_fs_progress,
                        file_found_cb=_fs_file,
                    )
                    self.status_text.emit(
                        f"{fs_name} : {count} fichier(s) récupéré(s) avec leur nom d'origine."
                    )
                    fs_ok = True
                else:
                    _log.info(
                        "[ScanWorker] Aucun FS reconnu sur %s — passage direct au carving brut.",
                        raw_dev,
                    )
            finally:
                os.close(fd)

        except OSError as exc:
            _log.warning(
                "[ScanWorker] Impossible d'ouvrir %s pour l'analyse FS : %s.",
                raw_dev,
                exc,
            )

        return dedup_index, fs_ok, fs_name, count

    def _run_quick_metadata(self, raw_dev: str) -> None:
        self.status_text.emit("Scan rapide metadata — lecture NTFS MFT…")
        self.progress.emit(0)

        _dedup_index, fs_ok, _fs_name, _count = self._enumerate_filesystem_metadata(
            raw_dev,
            progress_map=lambda pct: max(0, min(100, pct)),
        )

        if self._stop_requested:
            return

        if not fs_ok:
            message = t("scan.quick_unavailable")
            self.status_text.emit(message)
            self.error.emit(message)
        else:
            with self._lock:
                n = len(self._found_files)
            self.status_text.emit(f"Scan rapide terminé — {n} fichier(s) metadata trouvé(s).")
        self.progress.emit(100)

    # ── Mode réel (FS metadata + FileCarver, avec dédup) ─────────────────────

    def _run_real(self):
        from app.core.native.settings import get_scan_engine

        device = self._disk.get("device", "")
        if not device:
            self.error.emit("Aucun disque sélectionné.")
            return

        scan_mode = str(self._disk.get("scan_mode", "deep")).strip().lower()
        is_image_source = _is_local_image_source(device)

        if is_image_source:
            raw_dev = str(Path(device))
        else:
            try:
                raw_dev = _to_raw_device(device)
            except ValueError as exc:
                self.error.emit(str(exc))
                return

        self.status_text.emit(f"Ouverture du périphérique {raw_dev}…")
        self.progress.emit(0)

        if scan_mode == "quick":
            self._run_quick_metadata(raw_dev)
            return

        engine = get_scan_engine()
        if not is_image_source and engine == "native":
            self.error.emit(_NATIVE_IMAGE_ONLY_ERROR)
            return

        # ── Phase 1 : énumération FS (MFT / ext4 / APFS / …) — 0-20 % ─────────
        # The fd lifecycle is owned here; the parser only calls os.lseek/read on it.
        dedup_index, fs_ok, fs_name, _count = self._enumerate_filesystem_metadata(
            raw_dev,
            progress_map=lambda pct: pct // 5,
        )

        if self._stop_requested:
            return

        # Geler l'index dédup avant de laisser le carver tourner.
        dedup_index.freeze()
        if fs_ok:
            _log.info(
                "[ScanWorker] Dédup actif : %d intervalle(s) indexé(s) depuis %s.",
                len(dedup_index), fs_name,
            )

        # ── Phase 2 : FileCarver — 20-100 % (ou 0-100 % en fallback) ──────────
        self.status_text.emit("Analyse des signatures binaires (carving brut)…")

        pct_base  = 20 if fs_ok else 0
        pct_scale = 80 if fs_ok else 100

        from app.core.file_carver import FileCarver

        carver = FileCarver()
        dedup_check = dedup_index.overlaps if fs_ok else None

        if is_image_source and engine in {"auto", "native"}:
            try:
                self._run_native_image_carving(
                    image_path=raw_dev,
                    carver=carver,
                    dedup_check=dedup_check,
                    pct_base=pct_base,
                    pct_scale=pct_scale,
                )
            except Exception as exc:
                if self._stop_requested:
                    _log.warning(
                        "[ScanWorker] Native scan stopped with error; discarding transaction buffer: %s",
                        exc,
                    )
                    self.status_text.emit("Scan natif annulÃ©.")
                    return
                if engine == "auto":
                    _log.warning(
                        "[ScanWorker] Native scan failed before UI commit; falling back to Python: %s",
                        exc,
                    )
                    self.status_text.emit("Moteur natif indisponible â€” fallback Python.")
                    self._run_python_carving(raw_dev, carver, dedup_check, pct_base, pct_scale)
                else:
                    self.error.emit(str(exc))
                    return
        else:
            self._run_python_carving(raw_dev, carver, dedup_check, pct_base, pct_scale)

        with self._lock:
            n = len(self._found_files)
        self.status_text.emit(f"Terminé — {n} fichier(s) trouvé(s).")
        self.progress.emit(100)
