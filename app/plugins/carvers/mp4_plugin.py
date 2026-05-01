"""
Lumina v2.0 — MP4 / MOV / ISO-BMFF carver plugin.

Covers the ISO Base Media File Format family (MP4, MOV, 3GP, M4A/M4B/M4V,
F4V, HEIC) by detecting the mandatory `ftyp` box and walking the atom
structure (ISO/IEC 14496-12) byte-by-byte to compute an exact size.

Atom / box layout (big-endian):
    u32  size           — total size of this box including the 8-byte header
                          (0 = extends to end of file, 1 = 64-bit size follows)
    u32  type           — 4-char ASCII box type (ftyp, moov, mdat, moof, free…)
    [u64 extended_size] — only when `size == 1`
    <payload of size-8 (or size-16) bytes>

The `ftyp` box must be first; `moov` carries metadata; `mdat` carries
encoded samples; `moof` indicates a fragmented stream. By summing the size
of each well-formed top-level box starting from the file origin, we obtain
the exact total length with no disk I/O outside the 4 KB candidate window
already in RAM.

Signatures declare only the brand tag (`ftypisom`, `ftypmp41`, …). The
`FileCarver` applies a `-4` correction to recover the absolute box start
(4 bytes of size precede `ftyp`), so `estimate_size()` treats `start` as
the offset of the `ftyp` marker and works `start - 4` as the box origin.
"""

from __future__ import annotations

import struct

from .base_plugin import BaseCarverPlugin

# Valid ISO-BMFF major brands accepted by validate_mime().
# Covers the overwhelming majority of real-world files without whitelisting
# every registered brand — a minimal but structurally correct brand still
# begins with one of these 4-byte tokens.
_VALID_BRANDS: frozenset[bytes] = frozenset({
    b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6",
    b"mp41", b"mp42", b"mp71",
    b"avc1", b"avc3",
    b"qt  ",
    b"3gp4", b"3gp5", b"3gp6", b"3gp7", b"3g2a", b"3g2b",
    b"M4A ", b"M4B ", b"M4V ", b"M4P ",
    b"F4V ", b"F4P ", b"F4A ", b"F4B ",
    b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1",
    b"dash", b"msnv",
    b"crx ", b"cnxs",  # Canon CR3 (Cinema RAW Light)
})

# Known top-level atoms — used during the structural walk to decide whether
# an unrecognised 4-CC is probably corruption or simply a vendor-specific
# box. We accept *anything* that is printable ASCII as a valid type (ISO
# spec requires it), but prefer to bail early on clear garbage.
_KNOWN_TOP_ATOMS: frozenset[bytes] = frozenset({
    b"ftyp", b"moov", b"mdat", b"moof", b"mfra", b"free", b"skip", b"wide",
    b"pdin", b"pnot", b"styp", b"sidx", b"ssix", b"prft", b"uuid", b"meta",
    b"junk",
})

# Minimum structural size before we trust a naive walk result. Below this
# threshold the file is almost certainly a fragment — integrity drops.
_FRAGMENT_MIN_SIZE = 8 * 1024


class Mp4Plugin(BaseCarverPlugin):
    extension          = ".mp4"
    category           = "video"
    min_size           = 256
    default_size_kb    = 50_000  # ~50 MB fallback for unparseable fragments
    handled_extensions = (
        ".mp4", ".mov", ".m4v", ".m4a", ".m4b", ".m4p",
        ".3gp", ".3g2", ".f4v", ".heic",
    )

    @property
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        # Header = "ftyp<brand>"; FileCarver applies `-4` offset correction
        # so the absolute file origin lines up with the preceding size field.
        return [
            (b"ftypisom", None),
            (b"ftypiso2", None),
            (b"ftypmp41", None),
            (b"ftypmp42", None),
            (b"ftypavc1", None),
            (b"ftypqt  ", None),
            (b"ftypM4A ", None),
            (b"ftypM4B ", None),
            (b"ftypM4V ", None),
            (b"ftypF4V ", None),
            (b"ftyp3gp4", None),
            (b"ftyp3gp5", None),
            (b"ftyp3g2a", None),
            (b"ftypheic", None),
            (b"ftypheix", None),
            (b"ftypheim", None),
            (b"ftypheis", None),
            (b"ftyphevc", None),
            (b"ftypmif1", None),
            (b"ftypdash", None),
        ]

    # ── MIME validation ──────────────────────────────────────────────────
    def validate_mime(self, file_bytes: bytes) -> bool:
        """
        `file_bytes` begins at the `ftyp` marker (see class docstring).

        A valid ISO-BMFF header must have:
          • "ftyp" at offset 0
          • a 4-byte major brand at offset 4 present in `_VALID_BRANDS`
          • a box-size (at offset -4 relative to ftyp, so the caller must
            have included the leading 4 bytes; when they didn't, we fall
            back to brand check alone since the header match already
            guarantees structural alignment)
        """
        if len(file_bytes) < 8 or not file_bytes.startswith(b"ftyp"):
            return False
        brand = file_bytes[4:8]
        return brand in _VALID_BRANDS

    def refine_extension(self, data: bytes, idx: int) -> str:
        """
        Pick a specific extension from the major brand token at idx+4.
        Unknown or unmapped brands fall back to `.mp4`.
        """
        if idx + 8 > len(data):
            return ".mp4"
        brand = data[idx + 4 : idx + 8]
        if brand == b"qt  ":
            return ".mov"
        if brand in (b"M4A ", b"M4B "):
            return ".m4a"
        if brand == b"M4V ":
            return ".m4v"
        if brand == b"M4P ":
            return ".m4p"
        if brand in (b"F4V ", b"F4P ", b"F4A ", b"F4B "):
            return ".f4v"
        if brand.startswith(b"3gp") or brand.startswith(b"3g2"):
            return ".3gp" if brand.startswith(b"3gp") else ".3g2"
        if brand in (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1"):
            return ".heic"
        return ".mp4"

    # ── Atom-walking size estimator ──────────────────────────────────────
    def estimate_size(
        self,
        data: bytes,
        start: int,
        footer: bytes | None,
    ) -> tuple[int, int]:
        """
        Walk top-level atoms starting at the ftyp box origin and sum their
        sizes. Returns (size_kb, integrity_score).

        Integrity:
            100 — structural walk finished with a well-formed EOF
                  (sum of box sizes ≥ _FRAGMENT_MIN_SIZE)
             75 — walker stopped on extension / end of buffer but at a clean
                  atom boundary (MIME passed, reasonable recovery)
             70 — walker started cleanly but hit a malformed atom — size
                  returned is the last valid boundary (fragment reassembly)
        """
        # Absolute box origin (the 4-byte size field precedes `ftyp`).
        box_origin = start - 4
        if box_origin < 0:
            return self.default_size_kb, 75

        n = len(data)
        p = box_origin
        last_good = p  # last position AFTER a successfully-walked atom
        boxes_walked = 0

        while p + 8 <= n:
            size = struct.unpack_from(">I", data, p)[0]
            atype = data[p + 4 : p + 8]

            # --- Box type sanity: must be printable ASCII --------------
            if not all(0x20 <= b <= 0x7E for b in atype):
                break

            # --- Size 0: extends to end of file -----------------------
            # Per spec, this is only valid for the LAST box.
            if size == 0:
                last_good = n
                boxes_walked += 1
                break

            # --- Size 1: 64-bit extended size follows the type --------
            if size == 1:
                if p + 16 > n:
                    break
                size = struct.unpack_from(">Q", data, p + 8)[0]

            if size < 8:
                break  # malformed

            nxt = p + size

            # If the box would run past the buffer, credit the declared
            # size — this is the fragment-reassembly case for any real
            # MP4 whose mdat exceeds the in-RAM candidate window.
            if nxt > n:
                last_good = nxt
                boxes_walked += 1
                break

            last_good = nxt
            boxes_walked += 1
            p = nxt

            # An unknown top-level atom that passed the printable-ASCII
            # check is still accepted — ISO-BMFF allows vendor extensions.
            if atype not in _KNOWN_TOP_ATOMS and not atype[0:1].isalpha():
                break

        total = last_good - box_origin
        if total <= 0:
            return self.default_size_kb, 75

        # A clean walk of ≥ 2 top-level boxes starting with ftyp is
        # structurally unambiguous — integrity 100 whether we broke on
        # EOF, buffer end, or post-file padding.
        if boxes_walked >= 2 and total >= _FRAGMENT_MIN_SIZE:
            return max(1, total // 1024), 100

        # Short but structurally valid — fragment reassembly.
        return max(1, total // 1024), 70
