"""
Tests for app.core.c_bridge — ctypes wrapper for lumina_engine.dll.
"""

import ctypes

from app.core.c_bridge import (
    DLL_AVAILABLE,
    FileFoundCbType,
    ProgressCbType,
    stop_scan,
)


class TestCBridge:
    """Tests for the C bridge module (works regardless of DLL availability)."""

    def test_dll_available_is_bool(self):
        """DLL_AVAILABLE should be a boolean."""
        assert isinstance(DLL_AVAILABLE, bool)

    def test_progress_cb_type(self):
        """ProgressCbType should be a ctypes CFUNCTYPE."""
        assert hasattr(ProgressCbType, "_argtypes_")

    def test_file_found_cb_type(self):
        """FileFoundCbType should be a ctypes CFUNCTYPE."""
        assert hasattr(FileFoundCbType, "_argtypes_")

    def test_stop_scan_no_crash(self):
        """stop_scan() should not raise even when DLL is missing."""
        # This should silently do nothing if DLL isn't loaded
        stop_scan()

    def test_progress_callback_can_be_created(self):
        """We should be able to instantiate a ProgressCb from a Python function."""
        values = []

        @ProgressCbType
        def cb(pct):
            values.append(pct)

        cb(42)
        assert values == [42]

    def test_file_found_callback_can_be_created(self):
        """We should be able to instantiate a FileFoundCb from a Python function."""
        results = []

        @FileFoundCbType
        def cb(name, ftype, offset, size_est):
            results.append((name, ftype, offset, size_est))

        cb(b"test.jpg", b"JPG", 1024, 2048)
        assert len(results) == 1
        assert results[0] == (b"test.jpg", b"JPG", 1024, 2048)

    def test_dll_path_construction(self):
        """The DLL path should point to lumina_engine.dll in the project root."""
        from app.core import c_bridge
        import os

        expected_name = "lumina_engine.dll"
        assert c_bridge._DLL_PATH.endswith(expected_name)
        # The directory should be the project root
        dll_dir = os.path.dirname(c_bridge._DLL_PATH)
        assert os.path.isdir(dll_dir)
