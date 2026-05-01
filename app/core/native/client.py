from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.native.anomaly import (
    NativeAnomaly,
    NativeAnomalyDetector,
    NativeScanContext,
    critical_anomalies,
)
from app.core.native.protocol import (
    NativeCandidate,
    NativeCandidateBatch,
    NativeEvent,
    NativeFinished,
    NativeProgress,
    NativeSignature,
    NativeSource,
    build_scan_command,
    build_stop_command,
    parse_event_line,
)
from app.core.native.settings import ScanEngine, get_scan_engine

_log = logging.getLogger("lumina.native")


class NativeScanError(RuntimeError):
    pass


class NativeProtocolError(NativeScanError):
    pass


class NativeAnomalyError(NativeScanError):
    def __init__(self, anomalies: list[NativeAnomaly]) -> None:
        self.anomalies = anomalies
        message = "; ".join(f"{a.code}: {a.message}" for a in anomalies)
        super().__init__(message or "native scan anomaly")


class NativeUnavailableError(NativeScanError):
    pass


@dataclass(frozen=True)
class NativeScanSummary:
    engine: Literal["native", "python"]
    bytes_scanned: int
    duration_ms: int
    mbps: float
    candidate_count: int
    stopped: bool
    fallback_reason: str | None = None


class _StdoutClosed:
    pass


class NativeScanClient:
    def __init__(
        self,
        helper_path: str | Path | None = None,
        *,
        helper_command: Sequence[str] | None = None,
        engine: ScanEngine | None = None,
        timeout_s: float = 10.0,
        cleanup_timeout_s: float = 2.0,
    ) -> None:
        self._helper_path = Path(helper_path) if helper_path is not None else None
        self._helper_command = list(helper_command) if helper_command is not None else None
        self._engine = engine or get_scan_engine()
        self._timeout_s = timeout_s
        self._cleanup_timeout_s = cleanup_timeout_s

    def available(self) -> bool:
        if self._helper_command is not None:
            return True
        return self.helper_path().is_file()

    def helper_path(self) -> Path:
        if self._helper_path is not None:
            return self._helper_path

        binary = "lumina_scan.exe" if os.name == "nt" else "lumina_scan"
        if getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", ""))
            return base / "native" / "lumina_scan" / binary

        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "native" / "lumina_scan" / "target" / "release" / binary

    def scan_candidates(
        self,
        source: NativeSource,
        signatures: Sequence[NativeSignature],
        *,
        on_candidates: Callable[[list[NativeCandidate]], None],
        on_progress: Callable[[NativeProgress], None] | None = None,
        stop_flag: Callable[[], bool] | None = None,
        python_fallback: Callable[[], NativeScanSummary] | None = None,
        chunk_size: int = 16 * 1024 * 1024,
        candidate_batch_size: int = 512,
        progress_interval_ms: int = 250,
    ) -> NativeScanSummary:
        if self._engine == "python":
            return self._run_python_fallback("engine forced to python", python_fallback)

        if not self.available():
            err = NativeUnavailableError(f"native helper not found: {self.helper_path()}")
            if self._engine == "auto":
                return self._run_python_fallback(str(err), python_fallback)
            raise err

        return self._scan_native(
            source,
            signatures,
            on_candidates=on_candidates,
            on_progress=on_progress,
            stop_flag=stop_flag,
            python_fallback=python_fallback,
            chunk_size=chunk_size,
            candidate_batch_size=candidate_batch_size,
            progress_interval_ms=progress_interval_ms,
        )

    def _scan_native(
        self,
        source: NativeSource,
        signatures: Sequence[NativeSignature],
        *,
        on_candidates: Callable[[list[NativeCandidate]], None],
        on_progress: Callable[[NativeProgress], None] | None,
        stop_flag: Callable[[], bool] | None,
        python_fallback: Callable[[], NativeScanSummary] | None,
        chunk_size: int,
        candidate_batch_size: int,
        progress_interval_ms: int,
    ) -> NativeScanSummary:
        request_id = uuid.uuid4().hex
        signature_map = {sig.signature_id: sig for sig in signatures}
        detector = NativeAnomalyDetector(
            NativeScanContext(
                request_id=request_id,
                source_size=source.size_bytes,
                signatures=signature_map,
                max_batch_size=candidate_batch_size,
            )
        )

        command = build_scan_command(
            request_id,
            source,
            signatures,
            chunk_size=chunk_size,
            candidate_batch_size=candidate_batch_size,
            progress_interval_ms=progress_interval_ms,
        )
        proc: subprocess.Popen[str] | None = None
        stdout_queue: queue.Queue[NativeEvent | Exception | _StdoutClosed] = queue.Queue()
        stderr_tail: list[str] = []
        candidates_delivered = False
        stop_sent = False
        finished: NativeFinished | None = None
        last_event_at = time.monotonic()

        try:
            proc = self._start_process()
            assert proc.stdin is not None
            proc.stdin.write(command + "\n")
            proc.stdin.flush()
            self._start_stdout_reader(proc, stdout_queue, request_id)
            self._start_stderr_drain(proc, stderr_tail)

            while True:
                if stop_flag is not None and stop_flag() and not stop_sent:
                    self._send_stop(proc, request_id)
                    detector.mark_stop_requested()
                    stop_sent = True

                try:
                    item = stdout_queue.get(timeout=0.25)
                except queue.Empty:
                    if proc.poll() is not None:
                        anomalies = detector.finalize()
                        if anomalies:
                            self._handle_critical(
                                anomalies,
                                candidates_delivered,
                                python_fallback,
                            )
                        return self._handle_protocol_error(
                            f"native helper exited before finished; stderr={stderr_tail[-3:]}",
                            candidates_delivered,
                            python_fallback,
                        )
                    if time.monotonic() - last_event_at > self._timeout_s:
                        return self._handle_protocol_error(
                            "native helper timed out without events",
                            candidates_delivered,
                            python_fallback,
                        )
                    continue

                last_event_at = time.monotonic()
                if isinstance(item, _StdoutClosed):
                    anomalies = detector.finalize()
                    if anomalies:
                        return self._handle_critical(
                            anomalies,
                            candidates_delivered,
                            python_fallback,
                        )
                    if finished is None:
                        return self._handle_protocol_error(
                            "native stdout closed before finished",
                            candidates_delivered,
                            python_fallback,
                        )
                    return self._summary_from_finished(finished)

                if isinstance(item, Exception):
                    return self._handle_protocol_error(
                        str(item),
                        candidates_delivered,
                        python_fallback,
                    )

                anomalies = detector.observe(item)
                critical = critical_anomalies(anomalies)
                if critical:
                    return self._handle_critical(
                        critical,
                        candidates_delivered,
                        python_fallback,
                    )
                self._log_warnings(anomalies)

                if isinstance(item, NativeCandidateBatch):
                    batch = list(item.items)
                    on_candidates(batch)
                    candidates_delivered = candidates_delivered or bool(batch)
                elif isinstance(item, NativeProgress):
                    if on_progress is not None:
                        on_progress(item)
                elif isinstance(item, NativeFinished):
                    finished = item
                    return self._summary_from_finished(item)

        except OSError as exc:
            err = NativeUnavailableError(f"failed to start native helper: {exc}")
            if self._engine == "auto" and not candidates_delivered:
                return self._run_python_fallback(str(err), python_fallback)
            raise err from exc
        finally:
            self._cleanup_process(proc)

    def _start_process(self) -> subprocess.Popen[str]:
        cmd = self._helper_command or [str(self.helper_path())]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags,
        )

    def _start_stdout_reader(
        self,
        proc: subprocess.Popen[str],
        out: queue.Queue[NativeEvent | Exception | _StdoutClosed],
        request_id: str,
    ) -> None:
        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if line.strip():
                        out.put(parse_event_line(line, request_id))
            except Exception as exc:  # thread boundary: propagate through queue
                out.put(exc)
            finally:
                out.put(_StdoutClosed())

        threading.Thread(target=_reader, name="lumina-native-stdout", daemon=True).start()

    def _start_stderr_drain(
        self,
        proc: subprocess.Popen[str],
        stderr_tail: list[str],
    ) -> None:
        def _drain() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_tail.append(line.rstrip())
                del stderr_tail[:-20]

        threading.Thread(target=_drain, name="lumina-native-stderr", daemon=True).start()

    def _send_stop(self, proc: subprocess.Popen[str], request_id: str) -> None:
        if proc.stdin is None or proc.stdin.closed:
            return
        proc.stdin.write(build_stop_command(request_id) + "\n")
        proc.stdin.flush()

    def _cleanup_process(self, proc: subprocess.Popen[str] | None) -> None:
        if proc is None:
            return
        if proc.stdin is not None and not proc.stdin.closed:
            with suppress(OSError):
                proc.stdin.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=self._cleanup_timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=self._cleanup_timeout_s)

    def _handle_critical(
        self,
        anomalies: list[NativeAnomaly],
        candidates_delivered: bool,
        python_fallback: Callable[[], NativeScanSummary] | None,
    ) -> NativeScanSummary:
        err = NativeAnomalyError(anomalies)
        if self._engine == "auto" and not candidates_delivered:
            return self._run_python_fallback(str(err), python_fallback)
        raise err

    def _handle_protocol_error(
        self,
        message: str,
        candidates_delivered: bool,
        python_fallback: Callable[[], NativeScanSummary] | None,
    ) -> NativeScanSummary:
        err = NativeProtocolError(message)
        if self._engine == "auto" and not candidates_delivered:
            return self._run_python_fallback(str(err), python_fallback)
        raise err

    def _run_python_fallback(
        self,
        reason: str,
        python_fallback: Callable[[], NativeScanSummary] | None,
    ) -> NativeScanSummary:
        if python_fallback is None:
            raise NativeUnavailableError(
                f"python fallback required but not provided: {reason}"
            )
        _log.warning("Using Python scan fallback: %s", reason)
        summary = python_fallback()
        if summary.engine != "python":
            return NativeScanSummary(
                engine="python",
                bytes_scanned=summary.bytes_scanned,
                duration_ms=summary.duration_ms,
                mbps=summary.mbps,
                candidate_count=summary.candidate_count,
                stopped=summary.stopped,
                fallback_reason=reason,
            )
        if summary.fallback_reason is not None:
            return summary
        return NativeScanSummary(
            engine="python",
            bytes_scanned=summary.bytes_scanned,
            duration_ms=summary.duration_ms,
            mbps=summary.mbps,
            candidate_count=summary.candidate_count,
            stopped=summary.stopped,
            fallback_reason=reason,
        )

    def _summary_from_finished(self, event: NativeFinished) -> NativeScanSummary:
        return NativeScanSummary(
            engine="native",
            bytes_scanned=event.bytes_scanned,
            duration_ms=event.duration_ms,
            mbps=event.mbps,
            candidate_count=event.candidates,
            stopped=event.stopped,
        )

    def _log_warnings(self, anomalies: list[NativeAnomaly]) -> None:
        for anomaly in anomalies:
            _log.warning("Native scan warning %s: %s", anomaly.code, anomaly.message)
