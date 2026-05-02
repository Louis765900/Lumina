"""Tests for the Lumina CLI (app/cli/main.py)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

from app.cli.main import (
    _emit_csv,
    _emit_dfxml,
    _emit_json,
    build_parser,
    cmd_list_disks,
    cmd_version,
)


class TestBuildParser(unittest.TestCase):
    def test_scan_subcommand_exists(self):
        p = build_parser()
        args = p.parse_args(["scan", "C:"])
        self.assertEqual(args.command, "scan")
        self.assertEqual(args.source, "C:")
        self.assertEqual(args.mode, "deep")

    def test_list_disks_subcommand(self):
        p = build_parser()
        args = p.parse_args(["list-disks"])
        self.assertEqual(args.command, "list-disks")
        self.assertEqual(args.format, "table")

    def test_list_disks_json_format(self):
        p = build_parser()
        args = p.parse_args(["list-disks", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_scan_with_types_filter(self):
        p = build_parser()
        args = p.parse_args(["scan", "disk.img", "--types", "jpg,png"])
        self.assertEqual(args.types, "jpg,png")

    def test_scan_no_recover_flag(self):
        p = build_parser()
        args = p.parse_args(["scan", "disk.img", "--no-recover"])
        self.assertTrue(args.no_recover)

    def test_scan_format_dfxml(self):
        p = build_parser()
        args = p.parse_args(["scan", "disk.img", "--format", "dfxml"])
        self.assertEqual(args.format, "dfxml")

    def test_version_subcommand(self):
        p = build_parser()
        args = p.parse_args(["version"])
        self.assertEqual(args.command, "version")

    def test_scan_engine_choices(self):
        p = build_parser()
        args = p.parse_args(["scan", "disk.img", "--engine", "python"])
        self.assertEqual(args.engine, "python")

    def test_scan_mode_quick(self):
        p = build_parser()
        args = p.parse_args(["scan", "disk.img", "--mode", "quick"])
        self.assertEqual(args.mode, "quick")

    def test_recover_subcommand(self):
        p = build_parser()
        args = p.parse_args(["recover", "/dev/sda", "--files", "report.json", "--output", "/tmp/out"])
        self.assertEqual(args.command, "recover")
        self.assertEqual(args.source, "/dev/sda")
        self.assertEqual(args.files, "report.json")

    def test_info_subcommand(self):
        p = build_parser()
        args = p.parse_args(["info", "/dev/sda"])
        self.assertEqual(args.command, "info")
        self.assertEqual(args.source, "/dev/sda")

    def test_scan_min_max_size(self):
        p = build_parser()
        args = p.parse_args(["scan", "disk.img", "--min-size", "10", "--max-size", "500"])
        self.assertEqual(args.min_size, 10)
        self.assertEqual(args.max_size, 500)


class TestCmdVersion(unittest.TestCase):
    def test_version_exits_zero(self):
        args = Namespace()
        code = cmd_version(args)
        self.assertEqual(code, 0)


class TestCmdListDisks(unittest.TestCase):
    def test_list_disks_returns_zero_on_table(self):
        """list-disks command returns 0 with mocked DiskDetector."""
        args = Namespace(format="table")
        import sys
        import types
        fake_dd_module = types.ModuleType("app.core.disk_detector")
        fake_dd_class = MagicMock()
        fake_dd_class.list_disks.return_value = []
        fake_dd_module.DiskDetector = fake_dd_class
        with patch.dict(sys.modules, {"app.core.disk_detector": fake_dd_module}):
            code = cmd_list_disks(args)
        self.assertEqual(code, 0)

    def test_list_disks_returns_zero_on_json(self):
        """list-disks --format json returns 0."""
        args = Namespace(format="json")
        import sys
        import types
        fake_dd_module = types.ModuleType("app.core.disk_detector")
        fake_dd_class = MagicMock()
        fake_dd_class.list_disks.return_value = []
        fake_dd_module.DiskDetector = fake_dd_class
        with patch.dict(sys.modules, {"app.core.disk_detector": fake_dd_module}):
            code = cmd_list_disks(args)
        self.assertEqual(code, 0)

    def test_list_disks_json_with_data(self):
        """list-disks returns 0 even with disk data present."""
        fake_disks = [{"device": "C:", "name": "Test", "size_gb": 100.0, "model": "SSD"}]
        args = Namespace(format="json")
        import sys
        import types
        fake_dd_module = types.ModuleType("app.core.disk_detector")
        fake_dd_class = MagicMock()
        fake_dd_class.list_disks.return_value = fake_disks
        fake_dd_module.DiskDetector = fake_dd_class
        with patch.dict(sys.modules, {"app.core.disk_detector": fake_dd_module}):
            code = cmd_list_disks(args)
        self.assertEqual(code, 0)


class TestEmitJson(unittest.TestCase):
    def test_emit_json_to_file(self):
        files = [{"name": "photo.jpg", "type": "JPG", "size_kb": 100}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            _emit_json(files, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "photo.jpg")
        finally:
            os.unlink(path)

    def test_emit_json_empty_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            _emit_json([], path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [])
        finally:
            os.unlink(path)

    def test_emit_json_multiple_files(self):
        files = [
            {"name": "a.jpg", "type": "JPG"},
            {"name": "b.pdf", "type": "PDF"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            _emit_json(files, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[1]["name"], "b.pdf")
        finally:
            os.unlink(path)


class TestEmitDfxml(unittest.TestCase):
    def test_dfxml_produces_xml_content(self):
        """DFXML output should be non-empty XML-like content with expected tags."""
        files = [{"name": "doc.pdf", "type": "PDF", "size_kb": 50, "offset": 1024}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            path = f.name
        try:
            _emit_dfxml(files, "C:", path)
            content = open(path).read()
            # Check key structural elements are present
            self.assertIn("dfxml", content)
            self.assertIn("doc.pdf", content)
            self.assertIn("fileobject", content)
        finally:
            os.unlink(path)

    def test_dfxml_with_sha256(self):
        files = [{"name": "photo.jpg", "sha256": "abc123", "size_kb": 100, "offset": 512}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            path = f.name
        try:
            _emit_dfxml(files, "/dev/sda", path)
            content = open(path).read()
            self.assertIn("abc123", content)
        finally:
            os.unlink(path)

    def test_dfxml_contains_source_device(self):
        files = []
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            path = f.name
        try:
            _emit_dfxml(files, "/dev/sda", path)
            content = open(path).read()
            self.assertIn("/dev/sda", content)
        finally:
            os.unlink(path)


class TestEmitCsv(unittest.TestCase):
    def test_csv_has_header(self):
        files = [{"name": "file.doc", "type": "DOC", "size_kb": 10,
                  "offset": 512, "integrity": 80, "device": "C:"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name
        try:
            _emit_csv(files, path)
            with open(path) as f:
                content = f.read()
            self.assertIn("name", content)
            self.assertIn("file.doc", content)
        finally:
            os.unlink(path)

    def test_csv_multiple_rows(self):
        files = [
            {"name": "a.jpg", "type": "JPG", "size_kb": 100, "offset": 0, "integrity": 95},
            {"name": "b.png", "type": "PNG", "size_kb": 50, "offset": 1024, "integrity": 80},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name
        try:
            _emit_csv(files, path)
            with open(path) as f:
                lines = f.readlines()
            # header + 2 data rows
            self.assertGreaterEqual(len(lines), 3)
        finally:
            os.unlink(path)


class TestPlatformModule(unittest.TestCase):
    def test_settings_dir_returns_string(self):
        from app.core.platform import settings_dir
        result = settings_dir()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_log_dir_returns_string(self):
        from app.core.platform import log_dir
        result = log_dir()
        self.assertIsInstance(result, str)

    def test_to_raw_device_win32(self):
        from app.core.platform import to_raw_device
        with patch("app.core.platform.PLATFORM", "win32"):
            result = to_raw_device("C:")
            self.assertEqual(result, "\\\\.\\C:")

    def test_to_raw_device_linux(self):
        from app.core.platform import to_raw_device
        with patch("app.core.platform.PLATFORM", "linux"):
            result = to_raw_device("/dev/sda")
            self.assertEqual(result, "/dev/sda")

    def test_to_raw_device_macos(self):
        from app.core.platform import to_raw_device
        with patch("app.core.platform.PLATFORM", "darwin"):
            result = to_raw_device("/dev/disk0")
            self.assertEqual(result, "/dev/rdisk0")

    def test_is_admin_returns_bool(self):
        from app.core.platform import is_admin
        result = is_admin()
        self.assertIsInstance(result, bool)

    def test_smart_command_linux(self):
        from app.core.platform import smart_command
        with patch("app.core.platform.PLATFORM", "linux"):
            cmd = smart_command("/dev/sda")
            self.assertIn("smartctl", cmd)

    def test_fsck_command_linux(self):
        from app.core.platform import fsck_command
        with patch("app.core.platform.PLATFORM", "linux"):
            cmd = fsck_command("/dev/sda")
            self.assertIn("fsck", cmd)

    def test_to_raw_device_win32_already_raw(self):
        from app.core.platform import to_raw_device
        with patch("app.core.platform.PLATFORM", "win32"):
            result = to_raw_device("\\\\.\\C:")
            self.assertEqual(result, "\\\\.\\C:")

    def test_to_raw_device_macos_already_raw(self):
        from app.core.platform import to_raw_device
        with patch("app.core.platform.PLATFORM", "darwin"):
            result = to_raw_device("/dev/rdisk0")
            self.assertEqual(result, "/dev/rdisk0")

    def test_smart_command_win32(self):
        from app.core.platform import smart_command
        with patch("app.core.platform.PLATFORM", "win32"):
            cmd = smart_command("C:")
            self.assertIn("powershell", cmd)

    def test_fsck_command_win32(self):
        from app.core.platform import fsck_command
        with patch("app.core.platform.PLATFORM", "win32"):
            cmd = fsck_command("C:")
            self.assertIn("chkdsk", cmd)

    def test_fsck_command_darwin(self):
        from app.core.platform import fsck_command
        with patch("app.core.platform.PLATFORM", "darwin"):
            cmd = fsck_command("/dev/disk0")
            self.assertIn("diskutil", cmd)

    def test_settings_dir_linux(self):
        from app.core.platform import settings_dir
        with patch("app.core.platform.PLATFORM", "linux"), \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=False):
            result = settings_dir()
            self.assertIn("lumina", result.lower())

    def test_log_dir_darwin(self):
        from app.core.platform import log_dir
        with patch("app.core.platform.PLATFORM", "darwin"):
            result = log_dir()
            self.assertIn("Lumina", result)
