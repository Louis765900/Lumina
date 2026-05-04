"""
Lumina Scan Worker (QThread)

Production scans are real-only. The legacy simulation path is available only
when LUMINA_ENABLE_DEMO=1 is set for development.
"""

import logging
import os
import random
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.dedup import _DedupIndex
from app.core.i18n import t
from app.core.platform import to_raw_device as _to_raw_device
from app.core.recovery import ensure_lumina_log
from app.core.settings import is_demo_enabled

ensure_lumina_log()
_log = logging.getLogger("lumina.recovery")
_NATIVE_UNAVAILABLE_ERROR = "Native engine unavailable for this source."
_NATIVE_VALIDATION_WINDOW = 4 * 1024 * 1024


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

    progress = pyqtSignal(int)
    status_text = pyqtSignal(str)
    files_batch_found = pyqtSignal(list)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    # Demo data is loaded lazily to keep demo code out of the production bundle.
    # Access via self._sim_files / self._phases in _run_simulation() only.
    @property
    def _sim_files(self):  # type: ignore[override]
        from app.workers._demo import SIM_FILES

        return SIM_FILES

    @property
    def _phases(self):  # type: ignore[override]
        from app.workers._demo import PHASES

        return PHASES

    def __init__(
        self,
        disk: dict,
        simulate: bool = False,
        preloaded_files: list[dict] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        if simulate and not is_demo_enabled():
            raise ValueError(t("scan.demo_disabled"))
        self._disk = disk
        self._simulate = simulate
        self._stop_requested = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._found_files: list[dict] = list(preloaded_files) if preloaded_files else []
        self._lock = threading.Lock()

    # ── Contrôle public ───────────────────────────────────────────────────────

    def stop(self):
        self._stop_requested = True
        self._pause_event.set()  # débloquer si en pause pour permettre la sortie

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    # ── Entrée du thread ──────────────────────────────────────────────────────

    def run(self):
        # _found_files may already contain preloaded checkpoint data — don't reset.
        self._stop_requested = False
        self._pause_event.set()
        try:
            if self._simulate:
                self._found_files = []
                self._run_simulation()
            else:
                self._clear_checkpoint()
                self._run_real()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            with self._lock:
                snapshot = list(self._found_files)
            if snapshot:
                self._save_checkpoint()
            self.finished.emit(snapshot)

    # ── Mode simulation ───────────────────────────────────────────────────────

    def _run_simulation(self):
        if not is_demo_enabled():
            raise RuntimeError(t("scan.demo_disabled"))

        device = self._disk.get("device", "Disque")
        size_gb = self._disk.get("size_gb", 0)

        self.status_text.emit(f"Initialisation du scan sur {device} ({size_gb} Go)…")
        self.progress.emit(0)
        self.msleep(500)

        used_names: set[str] = set()
        phase_step = 80 // len(self._phases)

        for i, phase in enumerate(self._phases):
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
                    (n, e, s, q) for n, e, s, q in self._sim_files if f"{n}{e}" not in used_names
                ]
                to_add = available[: random.randint(1, 3)]
                batch = []

                for name, ext, size_kb, integrity in to_add:
                    self._pause_event.wait()
                    if self._stop_requested:
                        return
                    info = {
                        "name": f"{name}{ext}",
                        "type": ext.upper().lstrip("."),
                        "offset": random.randint(0, 500_000_000),
                        "size_kb": size_kb,
                        "device": device,
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
        for name, ext, size_kb, integrity in self._sim_files:
            self._pause_event.wait()
            if self._stop_requested:
                return
            fname = f"{name}{ext}"
            if fname not in used_names:
                pct = min(97, pct + 1)
                self.progress.emit(pct)
                info = {
                    "name": fname,
                    "type": ext.upper().lstrip("."),
                    "offset": random.randint(0, 500_000_000),
                    "size_kb": size_kb,
                    "device": device,
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

    _CHECKPOINT_INTERVAL = 60.0  # seconds between auto-saves during carving

    def _save_checkpoint(self) -> None:
        """Persist current results to logs/scan_checkpoint.json (crash recovery)."""
        import json as _json

        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            checkpoint = log_dir / "scan_checkpoint.json"
            with self._lock:
                snapshot = list(self._found_files)
            checkpoint.write_text(
                _json.dumps(snapshot, ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
            _log.debug("[ScanWorker] Checkpoint saved: %d file(s).", len(snapshot))
        except Exception as exc:
            _log.debug("[ScanWorker] Checkpoint save failed: %s", exc)

    def _clear_checkpoint(self) -> None:
        try:
            checkpoint = Path("logs") / "scan_checkpoint.json"
            if checkpoint.exists():
                checkpoint.unlink()
        except Exception:
            pass

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
        last_checkpoint = time.monotonic()

        def _on_progress(pct: int) -> None:
            self._pause_event.wait()
            if not self._stop_requested:
                self.progress.emit(pct_base + pct * pct_scale // 100)

        def _on_file(info: dict) -> None:
            nonlocal local_batch, last_emit, last_checkpoint
            self._pause_event.wait()
            with self._lock:
                self._found_files.append(info)
            local_batch.append(info)
            now = time.monotonic()
            if len(local_batch) >= 50 or (now - last_emit) > 0.2:
                self.files_batch_found.emit(list(local_batch))
                local_batch.clear()
                last_emit = now
            if now - last_checkpoint >= self._CHECKPOINT_INTERVAL:
                self._save_checkpoint()
                last_checkpoint = now

        carver.scan(
            raw_dev,
            progress_cb=_on_progress,
            file_found_cb=_on_file,
            stop_flag=lambda: self._stop_requested,
            dedup_check=dedup_check,
        )

        if local_batch:
            self.files_batch_found.emit(local_batch)

    def _run_native_carving(
        self,
        *,
        raw_path: str,
        is_image: bool,
        carver,
        dedup_check,
        pct_base: int,
        pct_scale: int,
    ) -> None:
        from app.core.native.client import NativeScanClient
        from app.core.native.protocol import NativeCandidate, NativeSignature, NativeSource

        if is_image:
            size_bytes = Path(raw_path).stat().st_size
            source_kind = "image"
        else:
            size_bytes = self._disk.get("size_bytes", 0)
            source_kind = "device"

        source = NativeSource(kind=source_kind, path=raw_path, size_bytes=size_bytes)
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

        self.status_text.emit("Moteur natif rapide — analyse des signatures.")

        with open(raw_path, "rb") as fh:

            def _on_candidates(batch: list[NativeCandidate]) -> None:
                for candidate in batch:
                    key = (candidate.offset, candidate.signature_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    info = self._native_candidate_to_file_info(
                        fh,
                        carver,
                        raw_path,
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
            self.status_text.emit("Scan interrompu — validation des résultats partiels.")

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
            fd = os.open(raw_dev, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                self.status_text.emit("Détection du système de fichiers…")
                parser = detect_fs(raw_dev, fd)

                if parser is not None:
                    fs_name = parser.name
                    self.status_text.emit(f"Analyse {fs_name} — récupération des noms d'origine…")

                    def _fs_progress(pct: int) -> None:
                        self._pause_event.wait()
                        if not self._stop_requested:
                            self.progress.emit(progress_map(pct))

                    _fs_pending: list[dict] = []
                    _fs_batch = 100

                    def _fs_file(info: dict) -> None:
                        self._pause_event.wait()
                        for start, length in info.get("data_runs", ()):
                            dedup_index.add(start, length)
                        with self._lock:
                            self._found_files.append(info)
                        _fs_pending.append(info)
                        if len(_fs_pending) >= _fs_batch:
                            self.files_batch_found.emit(list(_fs_pending))
                            _fs_pending.clear()

                    count = parser.enumerate_files(
                        stop_flag=lambda: self._stop_requested,
                        progress_cb=_fs_progress,
                        file_found_cb=_fs_file,
                    )
                    if _fs_pending:
                        self.files_batch_found.emit(list(_fs_pending))
                    self.status_text.emit(
                        f"{fs_name} : {count} fichier(s) récupéré(s) avec leur nom d'origine."
                    )
                    fs_ok = True
                else:
                    _log.info(
                        "[ScanWorker] Aucun FS reconnu sur %s — passage direct au carving brut.",
                        raw_dev,
                    )
                    self.status_text.emit(
                        "Système de fichiers non reconnu — analyse par signature directe."
                    )
            finally:
                os.close(fd)

        except OSError as exc:
            _log.warning(
                "[ScanWorker] Impossible d'ouvrir %s pour l'analyse FS : %s.",
                raw_dev,
                exc,
            )
            self.status_text.emit("Périphérique illisible — analyse par signature directe.")

        return dedup_index, fs_ok, fs_name, count

    def _run_quick_metadata(self, raw_dev: str) -> None:
        self.status_text.emit("Scan rapide — lecture des métadonnées NTFS.")
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
            if n == 0:
                message = t("scan.quick_few_results")
                self.status_text.emit(message)
                self.error.emit(message)
            else:
                self.status_text.emit(
                    f"Scan rapide terminé — {n} fichier(s) supprimé(s) récupérable(s)."
                )
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
            _log.info("scan_start mode=quick engine=metadata source=%s", raw_dev)
            self._run_quick_metadata(raw_dev)
            return

        engine = get_scan_engine()
        _log.info("scan_start mode=deep engine=%s source=%s", engine, raw_dev)
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
                len(dedup_index),
                fs_name,
            )

        # Phase 1 always occupies 0-20% of the visual bar, whether it succeeded
        # or not. If we reset pct_base to 0 when fs_ok=False the bar visibly
        # jumps backward; keeping it at 20 gives a monotonically increasing bar.
        pct_base = 20
        pct_scale = 80

        from app.core.file_carver import FileCarver

        carver = FileCarver()
        dedup_check = dedup_index.overlaps if fs_ok else None

        if engine in {"auto", "native"}:
            try:
                self._run_native_carving(
                    raw_path=raw_dev,
                    is_image=is_image_source,
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
                    self.status_text.emit("Scan interrompu.")
                    return
                if engine == "auto":
                    _log.warning(
                        "[ScanWorker] Native scan failed before UI commit; falling back to Python: %s",
                        exc,
                    )
                    self.status_text.emit("Moteur natif indisponible — moteur compatible Python.")
                    self._run_python_carving(raw_dev, carver, dedup_check, pct_base, pct_scale)
                else:
                    self.error.emit(str(exc))
                    return
        else:
            self.status_text.emit("Moteur compatible Python — analyse des signatures.")
            self._run_python_carving(raw_dev, carver, dedup_check, pct_base, pct_scale)

        with self._lock:
            n = len(self._found_files)
        self.status_text.emit(f"Terminé — {n} fichier(s) trouvé(s).")
        self.progress.emit(100)
