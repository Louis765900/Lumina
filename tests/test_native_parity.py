from __future__ import annotations

import pytest

from app.core.native.client import NativeScanClient
from app.core.native.protocol import NativeCandidate, NativeSignature, NativeSource


def test_rust_helper_simple_synthetic_parity_when_available(tmp_path):
    client = NativeScanClient(engine="native")
    helper = client.helper_path()
    if not helper.exists():
        pytest.skip(f"native helper not built: {helper}")

    image = tmp_path / "sample.img"
    image.write_bytes(b"xxPNGyyPDFzz")
    found: list[NativeCandidate] = []

    summary = client.scan_candidates(
        NativeSource(kind="image", path=str(image), size_bytes=image.stat().st_size),
        [
            NativeSignature("png", ".png", b"PNG"),
            NativeSignature("pdf", ".pdf", b"PDF"),
        ],
        on_candidates=lambda batch: found.extend(batch),
    )

    assert summary.engine == "native"
    assert {(item.offset, item.signature_id, item.ext) for item in found} == {
        (2, "png", ".png"),
        (7, "pdf", ".pdf"),
    }
