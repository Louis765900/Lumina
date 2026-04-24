"""
Lumina - C Engine Bridge (ctypes wrapper for lumina_engine.dll)

Exposes:
    DLL_AVAILABLE  : bool  — True if the DLL was loaded successfully
    deep_scan(device, on_progress, on_file_found) -> int
    quick_scan(device, on_progress, on_file_found) -> int
    stop_scan()

Callbacks received from C:
    on_progress(pct: int)
    on_file_found(name: str, ftype: str, offset: int, size_est: int)

The scan functions are BLOCKING — call them from a QThread, never from the
main thread.  ctypes CFUNCTYPE callbacks are called synchronously in the
same thread that called deep_scan / quick_scan, so PyQt6 signal emission
from inside a callback is safe (signals are auto-queued cross-thread).
"""

import ctypes
import os

# ── DLL location: handles bundled mode ─────────────────────────────────────────
def _get_dll_path():
    import sys
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    # In bundled mode, it's at the root. In dev mode, it's at Lumina/
    path_root = os.path.join(base_path, "lumina_engine.dll")
    if os.path.exists(path_root):
        return path_root
    
    # Fallback to dev structure Lumina/lumina_engine.dll
    dev_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lumina_engine.dll")
    return dev_path

_DLL_PATH = _get_dll_path()

try:
    _dll = ctypes.CDLL(os.path.abspath(_DLL_PATH))
    DLL_AVAILABLE = True
except OSError:
    _dll = None
    DLL_AVAILABLE = False

# ── C callback types ──────────────────────────────────────────────────────────
ProgressCbType  = ctypes.CFUNCTYPE(None, ctypes.c_int)
FileFoundCbType = ctypes.CFUNCTYPE(
    None,
    ctypes.c_char_p,   # name    (UTF-8 bytes)
    ctypes.c_char_p,   # ftype   (e.g. b"JPG")
    ctypes.c_uint64,   # offset  (byte offset on device)
    ctypes.c_uint64,   # size_est
)

if DLL_AVAILABLE:
    # lumina_deep_scan(device_path_w, progress_cb, file_found_cb) -> int
    _dll.lumina_deep_scan.restype  = ctypes.c_int
    _dll.lumina_deep_scan.argtypes = [
        ctypes.c_wchar_p,
        ProgressCbType,
        FileFoundCbType,
    ]

    # lumina_quick_scan(device_path_w, progress_cb, file_found_cb) -> int
    _dll.lumina_quick_scan.restype  = ctypes.c_int
    _dll.lumina_quick_scan.argtypes = [
        ctypes.c_wchar_p,
        ProgressCbType,
        FileFoundCbType,
    ]

    # lumina_stop_scan() -> void
    _dll.lumina_stop_scan.restype  = None
    _dll.lumina_stop_scan.argtypes = []


# ── Public API ────────────────────────────────────────────────────────────────

def _make_callbacks(on_progress, on_file_found):
    """
    Wrap Python callables into ctypes callback objects.
    The returned objects MUST stay alive for the entire duration of the
    C call — assign them to local variables in the calling function.
    """
    @ProgressCbType
    def _prog(pct: int):
        on_progress(pct)

    @FileFoundCbType
    def _file(name: bytes, ftype: bytes, offset: int, size_est: int):
        on_file_found(
            name.decode("utf-8",  errors="replace") if name  else "",
            ftype.decode("utf-8", errors="replace") if ftype else "???",
            offset,
            size_est,
        )

    return _prog, _file


def deep_scan(device: str, on_progress, on_file_found) -> int:
    """
    Run lumina_deep_scan (AVX2 file carving on raw device).

    Parameters
    ----------
    device       : Windows device path, e.g. r'\\\\.\\PhysicalDrive0'
    on_progress  : callable(pct: int)
    on_file_found: callable(name: str, ftype: str, offset: int, size_est: int)

    Returns C return code (0 = OK, negative = error).
    Raises RuntimeError if DLL is not available.
    """
    if not DLL_AVAILABLE:
        raise RuntimeError(
            "lumina_engine.dll introuvable. "
            "Compilez-le d'abord avec cl.exe (voir README)."
        )
    _prog, _file = _make_callbacks(on_progress, on_file_found)
    return _dll.lumina_deep_scan(device, _prog, _file)


def quick_scan(device: str, on_progress, on_file_found) -> int:
    """
    Run lumina_quick_scan (NTFS MFT parser for deleted files).

    Same signature as deep_scan.
    Returns -5 if the volume is not NTFS.
    """
    if not DLL_AVAILABLE:
        raise RuntimeError(
            "lumina_engine.dll introuvable. "
            "Compilez-le d'abord avec cl.exe (voir README)."
        )
    _prog, _file = _make_callbacks(on_progress, on_file_found)
    return _dll.lumina_quick_scan(device, _prog, _file)


def stop_scan() -> None:
    """Signal the running scan to stop.  Thread-safe, non-blocking."""
    if DLL_AVAILABLE:
        _dll.lumina_stop_scan()
