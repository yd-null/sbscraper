import contextlib
import io
import unittest
from unittest.mock import patch

import main


class NoninteractiveCliTests(unittest.TestCase):
    def test_no_mode_prints_help_without_loading_credentials(self):
        output = io.StringIO()
        with patch.object(main.sys, "argv", ["sbscraper"]), patch.object(
            main, "ensure_config_ready"
        ) as ensure_config_ready, contextlib.redirect_stdout(output):
            main.main()

        ensure_config_ready.assert_not_called()
        self.assertIn("usage:", output.getvalue())

    def test_positional_value_without_mode_prints_help(self):
        output = io.StringIO()
        with patch.object(
            main.sys, "argv", ["sbscraper", "PNGDMG01"]
        ), patch.object(
            main, "ensure_config_ready"
        ) as ensure_config_ready, contextlib.redirect_stdout(output):
            main.main()

        ensure_config_ready.assert_not_called()
        self.assertIn("usage:", output.getvalue())

    def test_short_options(self):
        args = main.build_parser().parse_args(
            ["-p", "-b", "-o", "reports", "PNGDMG01"]
        )

        self.assertTrue(args.pwrid)
        self.assertTrue(args.battery)
        self.assertEqual(args.output, "reports")
        self.assertEqual(args.ids, ["PNGDMG01"])

    def test_long_options(self):
        args = main.build_parser().parse_args(
            ["--pwrid", "--battery", "--output", "reports", "PNGDMG01"]
        )

        self.assertTrue(args.pwrid)
        self.assertTrue(args.battery)
        self.assertEqual(args.output, "reports")
        self.assertEqual(args.ids, ["PNGDMG01"])

    def test_version_does_not_load_credentials(self):
        with patch.object(main.sys, "argv", ["sbscraper", "--version"]), patch.object(
            main, "ensure_config_ready"
        ) as ensure_config_ready, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "0"):
                main.main()

        ensure_config_ready.assert_not_called()

    def test_invalid_arguments_do_not_load_credentials(self):
        with patch.object(main.sys, "argv", ["sbscraper", "-p"]), patch.object(
            main, "ensure_config_ready"
        ) as ensure_config_ready, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "2"):
                main.main()

        ensure_config_ready.assert_not_called()


if __name__ == "__main__":
    unittest.main()
