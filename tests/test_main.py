import contextlib
import io
import unittest
from unittest.mock import patch

import main


class NoninteractiveCliTests(unittest.TestCase):
    def test_version_does_not_load_credentials(self):
        with patch.object(main.sys, "argv", ["sbscraper", "--version"]), patch.object(
            main, "ensure_config_ready"
        ) as ensure_config_ready, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "0"):
                main.main()

        ensure_config_ready.assert_not_called()

    def test_invalid_arguments_do_not_load_credentials(self):
        with patch.object(main.sys, "argv", ["sbscraper", "-pwrid"]), patch.object(
            main, "ensure_config_ready"
        ) as ensure_config_ready, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "2"):
                main.main()

        ensure_config_ready.assert_not_called()


if __name__ == "__main__":
    unittest.main()
