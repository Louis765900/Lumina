"""Optional report emitters shared by CLI and UI."""

from __future__ import annotations

import csv
import html
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.version import DISPLAY_VERSION, VERSION

CSV_FIELDS = [
    "name",
    "type",
    "offset",
    "size_kb",
    "integrity",
    "integrity_score",
    "integrity_label",
    "device",
    "source",
    "fs",
]


def _integrity(info: dict[str, Any]) -> int:
    raw = info.get("integrity_score", info.get("integrity", 0))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def summary(files: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(info.get("type", "")).upper() for info in files)
    total_kb = sum(int(info.get("size_kb", 0) or 0) for info in files)
    avg_integrity = int(sum(_integrity(info) for info in files) / max(len(files), 1))
    return {
        "file_count": len(files),
        "type_count": len([key for key in counts if key]),
        "counts": dict(counts),
        "total_kb": total_kb,
        "avg_integrity": avg_integrity,
    }


def emit_json(files: list[dict[str, Any]], output_file: str | None) -> None:
    data = json.dumps(files, indent=2, default=str)
    if output_file:
        Path(output_file).write_text(data, encoding="utf-8")
    else:
        print(data)


def emit_jsonl(file_info: dict[str, Any]) -> None:
    print(json.dumps(file_info, default=str))


def emit_csv(files: list[dict[str, Any]], output_file: str | None) -> None:
    if output_file:
        with open(output_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(files)
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(files)


def build_dfxml(files: list[dict[str, Any]], source: str) -> ET.ElementTree:
    ns = "http://www.forensicswiki.org/wiki/Category:Digital_Forensics_XML"
    lumina_ns = "https://lumina.local/dfxml-ext"
    ET.register_namespace("", ns)
    ET.register_namespace("lumina", lumina_ns)

    def dfxml(tag: str) -> str:
        return f"{{{ns}}}{tag}"

    def lumina(tag: str) -> str:
        return f"{{{lumina_ns}}}{tag}"

    root = ET.Element(dfxml("dfxml"))
    root.set("version", "1.2.0")
    meta = ET.SubElement(root, dfxml("metadata"))
    ET.SubElement(meta, dfxml("creator")).text = DISPLAY_VERSION
    src = ET.SubElement(root, dfxml("source"))
    ET.SubElement(src, dfxml("device")).text = source
    ET.SubElement(src, dfxml("acquisition_date")).text = datetime.now(UTC).isoformat()

    for info in files:
        fobj = ET.SubElement(root, dfxml("fileobject"))
        ET.SubElement(fobj, dfxml("filename")).text = str(info.get("name", ""))
        size_bytes = int(info.get("size_kb", 0) or 0) * 1024
        ET.SubElement(fobj, dfxml("filesize")).text = str(size_bytes)
        br = ET.SubElement(fobj, dfxml("byte_runs"))
        runs = info.get("data_runs") or []
        if runs:
            file_offset = 0
            for run_offset, run_length in runs:
                run = ET.SubElement(br, dfxml("byte_run"))
                run.set("file_offset", str(file_offset))
                run.set("img_offset", str(run_offset))
                run.set("len", str(run_length))
                file_offset += int(run_length)
        else:
            run = ET.SubElement(br, dfxml("byte_run"))
            run.set("img_offset", str(info.get("offset", 0)))
            run.set("len", str(size_bytes))
        if info.get("sha256"):
            digest = ET.SubElement(fobj, dfxml("hashdigest"))
            digest.set("type", "sha256")
            digest.text = str(info["sha256"])
        ET.SubElement(fobj, lumina("integrity")).text = str(_integrity(info))
        ET.SubElement(fobj, lumina("filetype")).text = str(info.get("type", "")).upper()
        if info.get("integrity_label"):
            ET.SubElement(fobj, lumina("integrity_label")).text = str(info["integrity_label"])
        if info.get("source"):
            ET.SubElement(fobj, lumina("source")).text = str(info["source"])
        if info.get("fs"):
            ET.SubElement(fobj, lumina("fs")).text = str(info["fs"])

    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def emit_dfxml(files: list[dict[str, Any]], source: str, output_file: str | None) -> None:
    tree = build_dfxml(files, source)
    if output_file:
        tree.write(output_file, encoding="unicode", xml_declaration=True)
    else:
        import io

        buf = io.StringIO()
        tree.write(buf, encoding="unicode", xml_declaration=True)
        print(buf.getvalue())


def build_html_report(
    files: list[dict[str, Any]],
    *,
    device: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    stats = summary(files)
    total_kb = stats["total_kb"]
    total_str = f"{total_kb / 1024:.1f} Mo" if total_kb >= 1024 else f"{total_kb} Ko"
    when = generated_at or datetime.now()
    now = when.strftime("%d/%m/%Y a %H:%M")
    resolved_device = device or (str(files[0].get("device", "-")) if files else "-")

    rows = []
    for info in sorted(files, key=_integrity, reverse=True):
        integrity = _integrity(info)
        col = "#34C759" if integrity >= 90 else ("#3B82F6" if integrity >= 60 else "#F59E0B")
        size_kb = int(info.get("size_kb", 0) or 0)
        size_str = f"{size_kb / 1024:.1f} Mo" if size_kb >= 1024 else f"{size_kb} Ko"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(info.get('name', '-')))}</td>"
            f"<td>{html.escape(str(info.get('type', '-')))}</td>"
            f"<td>{html.escape(size_str)}</td>"
            f"<td style='color:{col};font-weight:700'>{integrity}%</td>"
            f"<td>{html.escape(str(info.get('source', info.get('device', '-'))))}</td>"
            "</tr>"
        )

    badges = "".join(
        f"<span class='badge'>{html.escape(str(ftype))} <b>{count}</b></span>"
        for ftype, count in sorted(stats["counts"].items(), key=lambda item: -item[1])
        if ftype
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Lumina - Rapport de scan</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Inter, sans-serif; background: #0F172A; color: #F1F5F9; padding: 40px; }}
  h1 {{ font-size: 26px; font-weight: 700; color: #F1F5F9; }}
  h1 span {{ color: #3B82F6; }}
  .meta {{ color: #94A3B8; font-size: 13px; margin-top: 6px; }}
  .stats {{ display: flex; gap: 16px; margin: 28px 0; flex-wrap: wrap; }}
  .stat {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px 24px; min-width: 140px; }}
  .stat .val {{ font-size: 22px; font-weight: 700; color: #F1F5F9; }}
  .stat .lbl {{ font-size: 11px; color: #94A3B8; margin-top: 4px; letter-spacing: 0; text-transform: uppercase; }}
  .badges {{ margin-bottom: 24px; display: flex; flex-wrap: wrap; gap: 8px; }}
  .badge {{ background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); border-radius: 8px; padding: 4px 12px; font-size: 12px; color: #CBD5E1; }}
  .badge b {{ color: #60A5FA; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{ background: rgba(255,255,255,0.06); padding: 10px 14px; text-align: left; color: #94A3B8; font-size: 10px; letter-spacing: 0; text-transform: uppercase; }}
  tbody tr {{ border-bottom: 1px solid rgba(255,255,255,0.05); }}
  tbody td {{ padding: 9px 14px; }}
  .footer {{ margin-top: 32px; color: #64748B; font-size: 11px; text-align: center; }}
</style>
</head>
<body>
  <h1>Lumina - <span>Rapport de scan</span></h1>
  <p class="meta">Genere le {html.escape(now)} - Peripherique : {html.escape(resolved_device)}</p>
  <div class="stats">
    <div class="stat"><div class="val">{stats["file_count"]}</div><div class="lbl">Fichiers trouves</div></div>
    <div class="stat"><div class="val">{html.escape(total_str)}</div><div class="lbl">Volume total</div></div>
    <div class="stat"><div class="val">{stats["avg_integrity"]}%</div><div class="lbl">Integrite moy.</div></div>
    <div class="stat"><div class="val">{stats["type_count"]}</div><div class="lbl">Types detectes</div></div>
  </div>
  <div class="badges">{badges}</div>
  <table>
    <thead><tr><th>Nom</th><th>Type</th><th>Taille</th><th>Integrite</th><th>Source</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  <p class="footer">{html.escape(DISPLAY_VERSION)} - Rapport genere automatiquement - schema {html.escape(VERSION)}</p>
</body>
</html>"""
