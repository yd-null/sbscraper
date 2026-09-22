import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sb_config


class ConfigPathTests(unittest.TestCase):
    def test_windows_config_uses_local_app_data(self):
        with patch.object(sb_config.sys, "platform", "win32"), patch.dict(
            sb_config.os.environ, {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"}
        ):
            self.assertEqual(
                sb_config.get_config_path(),
                Path(r"C:\Users\test\AppData\Local") / "sbscraper" / "config.json",
            )

    def test_windows_outputs_default_to_config_directory(self):
        with patch.object(sb_config.sys, "platform", "win32"), patch.dict(
            sb_config.os.environ, {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"}
        ):
            pdf_dir, csv_dir = sb_config.get_output_dirs()

        base_dir = Path(r"C:\Users\test\AppData\Local") / "sbscraper"
        self.assertEqual(pdf_dir, base_dir / "output")
        self.assertEqual(csv_dir, base_dir / "csv")

    def test_non_windows_outputs_default_to_current_directory(self):
        current_dir = Path("/tmp/sbscraper-run")
        with patch.object(sb_config.sys, "platform", "linux"), patch.object(
            sb_config.Path, "cwd", return_value=current_dir
        ):
            pdf_dir, csv_dir = sb_config.get_output_dirs()

        self.assertEqual(pdf_dir, current_dir / "output")
        self.assertEqual(csv_dir, current_dir / "csv")

    def test_explicit_output_directory_overrides_default(self):
        pdf_dir, csv_dir = sb_config.get_output_dirs("reports")

        self.assertEqual(pdf_dir, Path("reports/output"))
        self.assertEqual(csv_dir, Path("reports/csv"))

    def test_legacy_config_is_copied_to_user_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            legacy_path = root / "legacy" / "config.json"
            config_path = root / "user" / "config.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text('{"username":"user","password":"pass"}\n')

            with patch.object(sb_config, "get_execution_dir", return_value=legacy_path.parent):
                sb_config._migrate_legacy_config(config_path)

            self.assertEqual(config_path.read_text(), legacy_path.read_text())

    def test_password_update_preserves_username(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            config_path.write_text(
                '{"username":"user","password":"old","setting":true}\n'
            )

            with patch.object(
                sb_config, "get_config_path", return_value=config_path
            ), patch("builtins.input", return_value="yes"), patch.object(
                sb_config.getpass, "getpass", return_value="new"
            ):
                password = sb_config.prompt_to_update_password()

            self.assertEqual(password, "new")
            self.assertEqual(
                json.loads(config_path.read_text()),
                {"username": "user", "password": "new", "setting": True},
            )

    def test_declined_password_update_leaves_config_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            original = '{"username":"user","password":"old"}\n'
            config_path.write_text(original)

            with patch.object(
                sb_config, "get_config_path", return_value=config_path
            ), patch("builtins.input", return_value="n"):
                password = sb_config.prompt_to_update_password()

            self.assertIsNone(password)
            self.assertEqual(config_path.read_text(), original)

    def test_empty_password_leaves_config_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            original = '{"username":"user","password":"old"}\n'
            config_path.write_text(original)

            with patch.object(
                sb_config, "get_config_path", return_value=config_path
            ), patch("builtins.input", return_value="y"), patch.object(
                sb_config.getpass, "getpass", return_value=""
            ):
                password = sb_config.prompt_to_update_password()

            self.assertIsNone(password)
            self.assertEqual(config_path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
