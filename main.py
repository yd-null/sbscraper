import argparse
import asyncio
import sys

from sb_config import ensure_config_ready
from sb_version import get_app_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run SBScraper apps from a single entrypoint."
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {get_app_version()}",
    )

    app_group = parser.add_mutually_exclusive_group(required=True)
    app_group.add_argument(
        "-pwrid",
        action="store_true",
        help="Run Report by ID (expects one or more PWRIDs).",
    )
    app_group.add_argument(
        "-fuel",
        action="store_true",
        help="Run Fuel Tank Report (expects one or more site IDs).",
    )
    app_group.add_argument(
        "-coord",
        action="store_true",
        help="Run Coordinate Extraction (expects a PDF directory path).",
    )

    parser.add_argument(
        "ids",
        nargs="*",
        help="IDs or input path (PWRIDs for -pwrid, Site IDs for -fuel, PDF directory for -coord).",
    )
    parser.add_argument(
        "--output",
        default="sites.csv",
        help="Output CSV path for -coord (default: sites.csv).",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not ensure_config_ready():
        sys.exit(1)

    if args.pwrid:
        if not args.ids:
            parser.error("-pwrid requires one or more IDs.")

        from report_by_id import run as run_report_by_id

        asyncio.run(run_report_by_id(args.ids))
        return

    if args.fuel:
        if not args.ids:
            parser.error("-fuel requires one or more IDs.")

        from fuel_tank_report import run as run_fuel_tank_report

        asyncio.run(run_fuel_tank_report(args.ids))
        return

    if args.coord:
        if len(args.ids) != 1:
            parser.error("-coord requires exactly one directory path.")

        from coord_from_id import run as run_coord_from_id

        run_coord_from_id(args.ids[0], args.output)
        return

    parser.error("You must choose one app flag.")


if __name__ == "__main__":
    main()
