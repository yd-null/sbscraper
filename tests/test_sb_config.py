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


if __name__ == "__main__":
    unittest.main()
