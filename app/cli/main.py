"""
Lumina CLI — scriptable data recovery interface.

Usage:
    lumina scan <source> [options]
    lumina list-disks [--format json|table]
    lumina recover <source> --files <report.json> --output <dir>
    lumina info <source>
    lumina version

Exit codes:
    0 — success
    1 — error
    2 — scan interrupted (Ctrl+C)
    3 — no files found
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import signal
import sys
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_VERSION = "1.0.0"
_log = logging.getLogger("lumina.cli")
_stop_event = threading.Event()


def _setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.WARNING)
    logging.basicConfig(stream=sys.stderr, level=level,
                        format="%(levelname)s %(name)s: %(message)s")


def _handle_sigint(signum: int, frame: Any) -> None:  # noqa: ARG001
    _stop_event.set()


# ── list-disks ────────────────────────────────────────────────────────────────

def cmd_list_disks(args: argparse.Namespace) -> int:
    from app.core.disk_detector import DiskDetector
    disks = DiskDetector.list_disks()
    if args.format == "json":
        print(json.dumps(disks, indent=2))
    else:
        # Table
        header = f"{'Device':<10} {'Name':<30} {'Size GB':>8} {'Model':<20}"
        print(header)
        print("-" * len(header))
        for d in disks:
            print(
                f"{d.get('device', '?'):<10} {d.get('name', '?'):<30} "
                f"{d.get('size_gb', 0):>8.1f} {d.get('model', '?'):<20}"
            )
    return 0


# ── info ─────────────────────────────────────────────────────────────────────

def cmd_info(args: argparse.Namespace) -> int:
    from app.core.platform import to_raw_device, PLATFORM
    source = args.source
    raw = to_raw_device(source) if PLATFORM == "win32" else source
    print(f"Source : {source}")
    print(f"Raw    : {raw}")
    # Try to detect FS
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY  # type: ignore[attr-defined]
        fd = os.open(raw, flags)
        try:
            from app.core.fs_parser import detect_fs
            parser = detect_fs(raw, fd)
            if parser:
                print(f"FS     : {parser.name}")
            else:
                print("FS     : Unknown (carving only)")
        finally:
            os.close(fd)
    except OSError as exc:
        print(f"FS     : Cannot open device — {exc}")
    # File size if it's a regular file
    try:
        size = os.path.getsize(source)
        print(f"Size   : {size:,} bytes ({size / 1024 / 1024:.1f} MB)")
    except OSError:
        pass
    return 0


# ── version ───────────────────────────────────────────────────────────────────

def cmd_version(args: argparse.Namespace) -> int:  # noqa: ARG001
    print(f"Lumina v{_VERSION}")
    return 0


# ── Report formatters ─────────────────────────────────────────────────────────

def _emit_json(files: list[dict], output_file: str | None) -> None:
    data = json.dumps(files, indent=2, default=str)
    if output_file:
        Path(output_file).write_text(data, encoding="utf-8")
    else:
        print(data)


def _emit_jsonl(file_info: dict) -> None:
    print(json.dumps(file_info, default=str))


def _emit_dfxml(files: list[dict], source: str, output_file: str | None) -> None:
    ns = "http://www.forensicswiki.org/wiki/Category:Digital_Forensics_XML"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}dfxml")
    root.set("version", "1.2.0")
    meta = ET.SubElement(root, f"{{{ns}}}metadata")
    ET.SubElement(meta, f"{{{ns}}}dc:title").text = "Lumina Recovery Report"
    src = ET.SubElement(root, f"{{{ns}}}source")
    ET.SubElement(src, f"{{{ns}}}device").text = source
    ET.SubElement(src, f"{{{ns}}}acquisition_date").text = datetime.now(timezone.utc).isoformat()
    for fi in files:
        fobj = ET.SubElement(root, f"{{{ns}}}fileobject")
        ET.SubElement(fobj, f"{{{ns}}}filename").text = fi.get("name", "")
        ET.SubElement(fobj, f"{{{ns}}}filesize").text = str(fi.get("size_kb", 0) * 1024)
        br = ET.SubElement(fobj, f"{{{ns}}}byte_runs")
        run = ET.SubElement(br, f"{{{ns}}}byte_run")
        run.set("img_offset", str(fi.get("offset", 0)))
        run.set("len", str(fi.get("size_kb", 0) * 1024))
        if fi.get("sha256"):
            h = ET.SubElement(fobj, f"{{{ns}}}hashdigest")
            h.set("type", "sha256")
            h.text = fi["sha256"]
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    if output_file:
        tree.write(output_file, encoding="unicode", xml_declaration=True)
    else:
        import io
        buf = io.StringIO()
        tree.write(buf, encoding="unicode", xml_declaration=True)
        print(buf.getvalue())


def _emit_csv(files: list[dict], output_file: str | None) -> None:
    fields = ["name", "type", "offset", "size_kb", "integrity", "device", "source", "fs"]
    if output_file:
        fh = open(output_file, "w", newline="", encoding="utf-8")
        close = True
    else:
        fh = sys.stdout  # type: ignore[assignment]
        close = False
    try:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(files)
    finally:
        if close:
            fh.close()


# ── scan ─────────────────────────────────────────────────────────────────────

def _run_scan_sync(
    source: str,
    scan_mode: str,
    engine: str,
    types_filter: set[str] | None,
    min_size_kb: int,
    max_size_kb: int | None,
    progress: bool,
    quiet: bool,
    jsonl_streaming: bool,
) -> tuple[list[dict], bool]:
    """
    Run a synchronous (non-Qt) scan. Returns (files, was_interrupted).
    Uses FileCarver + fs_parser directly, bypassing ScanWorker/QThread.
    """
    from app.core.file_carver import FileCarver
    from app.core.fs_parser import detect_fs
    from app.core.platform import to_raw_device, PLATFORM
    from app.core.dedup import _DedupIndex

    raw = to_raw_device(source) if PLATFORM == "win32" else source
    files: list[dict] = []
    was_interrupted = False

    def _stop() -> bool:
        return _stop_event.is_set()

    def _progress(pct: int) -> None:
        if progress and not quiet:
            print(f"\r[{pct:3d}%] Scanning...", end="", file=sys.stderr, flush=True)

    def _file_found(fi: dict) -> None:
        # Apply filters
        if types_filter and fi.get("type", "").upper() not in types_filter:
            return
        sz = fi.get("size_kb", 0)
        if sz < min_size_kb:
            return
        if max_size_kb is not None and sz > max_size_kb:
            return
        if jsonl_streaming:
            _emit_jsonl(fi)
        files.append(fi)

    # Phase 1: FS metadata
    dedup = _DedupIndex()
    fs_ok = False
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY  # type: ignore[attr-defined]
    try:
        fd = os.open(raw, flags)
    except OSError as exc:
        print(f"Error: cannot open {raw!r}: {exc}", file=sys.stderr)
        return [], False

    try:
        parser = detect_fs(raw, fd)
        if parser and scan_mode != "quick":
            def _mft_found(fi: dict) -> None:
                for start, length in fi.get("data_runs", []):
                    dedup.add(start, length)
                _file_found(fi)
            parser.enumerate_files(
                stop_flag=_stop,
                progress_cb=lambda p: _progress(p // 5),
                file_found_cb=_mft_found,
            )
            dedup.freeze()
            fs_ok = bool(len(dedup))

        # Phase 2: carving (deep scan only)
        if scan_mode == "deep":
            carver = FileCarver()
            dedup_check = dedup.overlaps if fs_ok else None
            carver.scan(
                raw_dev=raw,
                progress_cb=lambda p: _progress(20 + p * 80 // 100),
                file_found_cb=_file_found,
                stop_flag=_stop_event,
                dedup_check=dedup_check,
            )
    except KeyboardInterrupt:
        was_interrupted = True
    except OSError as exc:
        print(f"Error during scan: {exc}", file=sys.stderr)
    finally:
        os.close(fd)

    if progress and not quiet:
        print(file=sys.stderr)  # newline after progress

    return files, was_interrupted or _stop_event.is_set()


def _recover_files(
    files: list[dict], output_dir: str, compute_hash: bool, source: str
) -> list[dict]:
    """Extract files to output_dir. Returns list of successfully recovered file_infos."""
    from app.core.platform import to_raw_device, PLATFORM

    os.makedirs(output_dir, exist_ok=True)
    raw = to_raw_device(source) if PLATFORM == "win32" else source
    recovered = []

    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY  # type: ignore[attr-defined]
    try:
        fd = os.open(raw, flags)
    except OSError as exc:
        print(f"Error: cannot open {raw!r} for extraction: {exc}", file=sys.stderr)
        return []

    try:
        for fi in files:
            if _stop_event.is_set():
                break
            offset = fi.get("offset", 0)
            size = fi.get("size_kb", 0) * 1024
            if not offset or not size:
                continue
            dest = os.path.join(output_dir, fi.get("name", f"recovered_{offset}"))
            try:
                os.lseek(fd, offset, os.SEEK_SET)
                data = os.read(fd, min(size, 500 * 1024 * 1024))
                if compute_hash:
                    h = hashlib.sha256(data).hexdigest()
                    fi["sha256"] = h
                with open(dest, "wb") as out:
                    out.write(data)
                fi["extracted_name"] = dest
                recovered.append(fi)
            except OSError as exc:
                print(f"  Warning: failed to extract {fi.get('name')}: {exc}", file=sys.stderr)
    finally:
        os.close(fd)
    return recovered


def cmd_scan(args: argparse.Namespace) -> int:
    source = args.source
    scan_mode = args.mode
    fmt = args.format
    types_filter = {t.strip().upper() for t in args.types.split(",")} if args.types else None
    min_size_kb = args.min_size or 0
    max_size_kb = args.max_size

    jsonl_streaming = fmt == "json" and not args.report
    _setup_logging(args.verbose, args.quiet)

    if not args.quiet:
        print(f"Scanning {source!r} ({scan_mode} mode)...", file=sys.stderr)

    files, interrupted = _run_scan_sync(
        source=source,
        scan_mode=scan_mode,
        engine=args.engine,
        types_filter=types_filter,
        min_size_kb=min_size_kb,
        max_size_kb=max_size_kb,
        progress=args.progress,
        quiet=args.quiet,
        jsonl_streaming=jsonl_streaming,
    )

    if not args.quiet:
        print(f"Found {len(files)} file(s).", file=sys.stderr)

    # Recovery
    if not args.no_recover and args.output and files:
        recovered = _recover_files(files, args.output, args.hash, source)
        if not args.quiet:
            print(f"Recovered {len(recovered)} file(s) to {args.output!r}.", file=sys.stderr)

    # Report
    if not jsonl_streaming:
        if fmt == "json":
            _emit_json(files, args.report)
        elif fmt == "csv":
            _emit_csv(files, args.report)
        elif fmt == "dfxml":
            _emit_dfxml(files, source, args.report)

    if interrupted:
        return 2
    if not files:
        return 3
    return 0


# ── recover ───────────────────────────────────────────────────────────────────

def cmd_recover(args: argparse.Namespace) -> int:
    report_path = args.files
    output_dir = args.output
    try:
        with open(report_path, encoding="utf-8") as f:
            files = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading report {report_path!r}: {exc}", file=sys.stderr)
        return 1

    recovered = _recover_files(files, output_dir, getattr(args, "hash", False), args.source)
    print(f"Recovered {len(recovered)}/{len(files)} file(s) to {output_dir!r}.")
    return 0 if recovered else 1


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lumina",
        description="Lumina — data recovery CLI",
    )
    sub = p.add_subparsers(dest="command")

    # scan
    ps = sub.add_parser("scan", help="Scan a disk or image for recoverable files")
    ps.add_argument("source", help="Device or image path (e.g. C:, /dev/sda, disk.img)")
    ps.add_argument("--mode", choices=["quick", "deep"], default="deep")
    ps.add_argument("--engine", choices=["auto", "native", "python"], default="auto")
    ps.add_argument("--output", "-o", help="Output directory for recovered files")
    ps.add_argument("--format", "-f", choices=["json", "csv", "dfxml"], default="json")
    ps.add_argument("--report", "-r", help="Write report to this file instead of stdout")
    ps.add_argument("--types", help="Comma-separated file extensions to include (e.g. jpg,png)")
    ps.add_argument("--min-size", type=int, default=0, metavar="KB")
    ps.add_argument("--max-size", type=int, default=None, metavar="KB")
    ps.add_argument("--no-recover", action="store_true", help="Scan only, do not extract files")
    ps.add_argument("--hash", action="store_true", help="Compute SHA-256 after extraction")
    ps.add_argument("--verbose", "-v", action="store_true")
    ps.add_argument("--quiet", "-q", action="store_true")
    ps.add_argument("--progress", action="store_true", help="Show progress on stderr")

    # list-disks
    pl = sub.add_parser("list-disks", help="List available disks")
    pl.add_argument("--format", choices=["json", "table"], default="table")

    # recover
    pr = sub.add_parser("recover", help="Recover files from a previous scan report")
    pr.add_argument("source", help="Device or image path")
    pr.add_argument("--files", required=True, help="Path to scan report JSON")
    pr.add_argument("--output", "-o", required=True, help="Output directory")
    pr.add_argument("--hash", action="store_true")

    # info
    pi = sub.add_parser("info", help="Show volume information")
    pi.add_argument("source")

    # version
    sub.add_parser("version", help="Show version")

    return p


def main() -> None:
    signal.signal(signal.SIGINT, _handle_sigint)
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "scan": cmd_scan,
        "list-disks": cmd_list_disks,
        "recover": cmd_recover,
        "info": cmd_info,
        "version": cmd_version,
    }
    fn = dispatch.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    try:
        code = fn(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Fatal error: {exc}", file=sys.stderr)
        _log.exception("CLI fatal error")
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
