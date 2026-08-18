import argparse
import asyncio
import sys

from sb_config import ensure_config_ready
from sb_version import get_app_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Structure Builder reports and export related CSV data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Common Windows examples:
  sbscraper.exe -PWRID PNGDMG01 CFURMG01
  sbscraper.exe -battery PNGDMG01 CFURMG01
  sbscraper.exe -PWRID -battery PNGDMG01 CFURMG01
  sbscraper.exe -battery --output battery_report.csv PNGDMG01 CFURMG01
  sbscraper.exe -fuel 12345 67890
  sbscraper.exe -coord output --output sites.csv

Notes:
  - Use -PWRID or -pwrid to save SY/System PDF reports.
  - Use -battery to export all battery strings to CSV.
  - -PWRID and -battery can be used together.
  - -fuel and -coord must be run on their own.
  - --output is optional and can be placed before or after the ID list.
  - Battery CSV defaults to battery_report.csv when --output is omitted.
  - Coordinate CSV defaults to sites.csv when --output is omitted.
  - PDF reports are saved under the output folder in the current directory.
""",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {get_app_version()}",
    )

    parser.add_argument(
        "-pwrid",
        "-PWRID",
        action="store_true",
        help="Save SY/System PDF reports for one or more PWRIDs.",
    )
    parser.add_argument(
        "-battery",
        action="store_true",
        help="Export all battery strings for one or more PWRIDs to CSV.",
    )
    parser.add_argument(
        "-fuel",
        action="store_true",
        help="Save fuel tank PDF reports for one or more Site IDs.",
    )
    parser.add_argument(
        "-coord",
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
        "--output",
        metavar="CSV_PATH",
        default=None,
        help="CSV output path for -battery or -coord. Defaults: battery_report.csv or sites.csv.",
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
        parser.error("-fuel and -coord cannot be combined with -pwrid or -battery.")
    if pwrid_mode and not args.ids:
        parser.error("-pwrid/-battery requires one or more PWRIDs.")
    if args.fuel and not args.ids:
        parser.error("-fuel requires one or more IDs.")
    if args.coord and len(args.ids) != 1:
        parser.error("-coord requires exactly one directory path.")

    if not ensure_config_ready():
        sys.exit(1)

    if args.pwrid and args.battery:
        from report_by_id import run_reports_and_battery_csv

        asyncio.run(
            run_reports_and_battery_csv(args.ids, args.output or "battery_report.csv")
        )
        return

    if args.pwrid:
        from report_by_id import run as run_report_by_id

        asyncio.run(run_report_by_id(args.ids))
        return

    if args.battery:
        from report_by_id import run_battery_csv

        asyncio.run(run_battery_csv(args.ids, args.output or "battery_report.csv"))
        return

    if args.fuel:
        from fuel_tank_report import run as run_fuel_tank_report

        asyncio.run(run_fuel_tank_report(args.ids))
        return

    if args.coord:
        from coord_from_id import run as run_coord_from_id

        run_coord_from_id(args.ids[0], args.output or "sites.csv")
        return

    parser.error("You must choose one app flag.")


if __name__ == "__main__":
    main()
