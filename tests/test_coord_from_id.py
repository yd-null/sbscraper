import csv
import tempfile
import unittest
from pathlib import Path

import coord_from_id


class CoordinateOutputTests(unittest.TestCase):
    def test_run_creates_csv_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf_dir = root / "pdfs"
            output_csv = root / "results" / "csv" / "sites.csv"
            pdf_dir.mkdir()

            coord_from_id.run(str(pdf_dir), str(output_csv))

            self.assertTrue(output_csv.is_file())
            with output_csv.open(newline="", encoding="utf-8") as output_file:
                self.assertEqual(
                    next(csv.reader(output_file)),
                    [
                        "Site Name",
                        "Site Address",
                        "Latitude",
                        "Longitude",
                        "Source File",
                    ],
                )


if __name__ == "__main__":
    unittest.main()
