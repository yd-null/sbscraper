import argparse
import asyncio
import sys

from sb_config import ensure_config_ready, get_output_dirs
from sb_version import get_app_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Structure Builder reports and export related CSV data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Common Windows examples:
  sbscraper.exe -p PNGDMG01 CFURMG01
  sbscraper.exe -b PNGDMG01 CFURMG01
  sbscraper.exe -p -b PNGDMG01 CFURMG01
  sbscraper.exe -b -o C:\Reports PNGDMG01 CFURMG01
  sbscraper.exe -f 12345 67890
  sbscraper.exe -c C:\Reports\output -o C:\Reports

Notes:
  - Use -p or --pwrid to save SY/System PDF reports.
  - Use -b or --battery to export all battery strings to CSV.
  - PWRID and battery modes can be used together.
  - Fuel and coordinate modes must be run on their own.
  - -o/--output sets the base directory for output/ and csv/.
  - On Windows, the default base is %LOCALAPPDATA%\sbscraper.
""",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {get_app_version()}",
    )

    parser.add_argument(
        "-p",
        "--pwrid",
        action="store_true",
        help="Save SY/System PDF reports for one or more PWRIDs.",
    )
    parser.add_argument(
        "-b",
        "--battery",
        action="store_true",
        help="Export all battery strings for one or more PWRIDs to CSV.",
    )
    parser.add_argument(
        "-f",
        "--fuel",
        action="store_true",
        help="Save fuel tank PDF reports for one or more Site IDs.",
    )
    parser.add_argument(
        "-c",
        "--coord",
        action="store_true",
        help="Extract site address/latitude/longitude from a PDF folder to CSV.",
    )

    parser.add_argument(
        "ids",
        nargs="*",
        metavar="ID_OR_PATH",
        help="PWRIDs, Site IDs, or a PDF folder path depending on the selected mode.",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="DIRECTORY",
        default=None,
        help="Base directory for output/ PDFs and csv/ files.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    pwrid_mode = args.pwrid or args.battery
    selected_mode_count = sum(
        bool(mode) for mode in (pwrid_mode, args.fuel, args.coord)
    )
    if selected_mode_count == 0:
        parser.error("You must choose one app flag.")
    if selected_mode_count > 1:
        parser.error(
            "--fuel and --coord cannot be combined with --pwrid or --battery."
        )
    if pwrid_mode and not args.ids:
        parser.error("--pwrid/--battery requires one or more PWRIDs.")
    if args.fuel and not args.ids:
        parser.error("--fuel requires one or more IDs.")
    if args.coord and len(args.ids) != 1:
        parser.error("--coord requires exactly one directory path.")

    if not ensure_config_ready():
        sys.exit(1)

    pdf_output_dir, csv_output_dir = get_output_dirs(args.output)

    if args.pwrid and args.battery:
        from report_by_id import run_reports_and_battery_csv

        asyncio.run(
            run_reports_and_battery_csv(
                args.ids,
                str(csv_output_dir / "battery_report.csv"),
                pdf_output_dir,
            )
        )
        return

    if args.pwrid:
        from report_by_id import run as run_report_by_id

        asyncio.run(run_report_by_id(args.ids, output_dir=pdf_output_dir))
        return

    if args.battery:
        from report_by_id import run_battery_csv

        asyncio.run(
            run_battery_csv(args.ids, str(csv_output_dir / "battery_report.csv"))
        )
        return

    if args.fuel:
        from fuel_tank_report import run as run_fuel_tank_report

        asyncio.run(run_fuel_tank_report(args.ids, output_dir=pdf_output_dir))
        return

    if args.coord:
        from coord_from_id import run as run_coord_from_id

        run_coord_from_id(args.ids[0], str(csv_output_dir / "sites.csv"))
        return

    parser.error("You must choose one app flag.")


if __name__ == "__main__":
    main()
