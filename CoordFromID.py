import argparse
import csv
import os
import re

import pdfplumber


def run(pdf_folder: str, output_csv: str = "sites.csv") -> None:
    if not os.path.isdir(pdf_folder):
        raise FileNotFoundError(f"Directory not found: {pdf_folder}")

    rows = []

    for file in os.listdir(pdf_folder):
        if not file.lower().endswith(".pdf"):
            continue

        path = os.path.join(pdf_folder, file)
        clean_name = file.replace("SYReport - ", "").replace(".pdf", "")

        with pdfplumber.open(path) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"

        site = None
        lat = None
        lon = None

        site_match = re.search(r"Site Address\s*:\s*(.+)", text)
        lat_match = re.search(r"Latt?itude\s*:\s*(-?\d+\.\d+)", text, re.IGNORECASE)
        lon_match = re.search(r"Longitude\s*:\s*(-?\d+\.\d+)", text, re.IGNORECASE)

        if site_match:
            site = site_match.group(1).strip()

        if lat_match:
            lat = lat_match.group(1)

        if lon_match:
            lon = lon_match.group(1)

        rows.append([clean_name, site, lat, lon, file])

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Site Name", "Site Address", "Latitude", "Longitude", "Source File"]
        )
        writer.writerows(rows)

    print(f"Extraction complete: {os.path.abspath(output_csv)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Site Address/Latitude/Longitude from PDFs into a CSV."
    )
    parser.add_argument("pdf_dir", help="Directory containing PDF files.")
    parser.add_argument(
        "--output",
        default="sites.csv",
        help="CSV output path (default: sites.csv).",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    run(args.pdf_dir, args.output)
