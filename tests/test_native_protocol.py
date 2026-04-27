from __future__ import annotations

import json

import pytest

from app.core.native.protocol import (
    NativeCandidateBatch,
    NativeFinished,
    NativeProgress,
    NativeSignature,
    NativeSource,
    ProtocolError,
    build_scan_command,
    build_stop_command,
    parse_event_line,
)
from app.core.native.settings import get_scan_engine


def test_build_scan_command_serializes_hex_headers():
    command = build_scan_command(
        "req",
        NativeSource(kind="image", path="sample.img", size_bytes=100),
        [NativeSignature("png", ".png", b"\x89PNG")],
    )

    data = json.loads(command)
    assert data["cmd"] == "scan"
    assert data["signatures"][0]["header_hex"] == "89504e47"


def test_build_stop_command():
    assert json.loads(build_stop_command("req")) == {
        "cmd": "stop",
        "request_id": "req",
    }


def test_parse_progress_event_strict():
    event = parse_event_line(
        '{"event":"progress","request_id":"req","bytes_scanned":10,'
        '"total_bytes":100,"percent":10,"mbps":42.5}',
        "req",
    )

    assert isinstance(event, NativeProgress)
    assert event.bytes_scanned == 10
    assert event.mbps == 42.5


def test_parse_candidates_event_strict():
    event = parse_event_line(
        '{"event":"candidates","request_id":"req","batch_index":0,'
        '"items":[{"offset":2,"signature_id":"png","ext":".png"}]}',
        "req",
    )

    assert isinstance(event, NativeCandidateBatch)
    assert event.items[0].offset == 2


def test_parse_finished_event_strict_bool():
    event = parse_event_line(
        '{"event":"finished","request_id":"req","bytes_scanned":100,'
        '"candidates":1,"duration_ms":5,"mbps":20.0,"stopped":false}',
        "req",
    )

    assert isinstance(event, NativeFinished)
    assert event.stopped is False


def test_rejects_wrong_request_id():
    with pytest.raises(ProtocolError):
        parse_event_line(
            '{"event":"progress","request_id":"other","bytes_scanned":0,'
            '"total_bytes":1,"percent":0,"mbps":0}',
            "req",
        )


def test_rejects_unknown_event():
    with pytest.raises(ProtocolError):
        parse_event_line('{"event":"surprise","request_id":"req"}', "req")


def test_rejects_extra_fields():
    with pytest.raises(ProtocolError):
        parse_event_line(
            '{"event":"finished","request_id":"req","bytes_scanned":1,'
            '"candidates":0,"duration_ms":1,"mbps":1,"stopped":false,"x":1}',
            "req",
        )


def test_rejects_bool_as_int():
    with pytest.raises(ProtocolError):
        parse_event_line(
            '{"event":"progress","request_id":"req","bytes_scanned":true,'
            '"total_bytes":1,"percent":0,"mbps":0}',
            "req",
        )


def test_invalid_scan_engine_warns_and_returns_auto(caplog):
    with caplog.at_level("WARNING", logger="lumina.native"):
        engine = get_scan_engine({"LUMINA_SCAN_ENGINE": "turbo"})

    assert engine == "auto"
    assert "Invalid LUMINA_SCAN_ENGINE" in caplog.text
