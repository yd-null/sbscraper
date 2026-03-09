import argparse
import asyncio
import getpass
import json
import os
import sys


CONFIG_FILE = "config.json"


def _prompt_and_write_config(config_path: str) -> bool:
    try:
        print("Set up credentials for SBScraper.")
        username = input("Username: ").strip()
        password = getpass.getpass("Password: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCredential setup cancelled.")
        return False

    if not username or not password:
        print("Username and password are required.")
        return False

    config = {
        "username": username,
        "password": password,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Saved credentials to {config_path}.")
    return True


def ensure_config_ready() -> bool:
    config_path = os.path.join(os.getcwd(), CONFIG_FILE)

    if not os.path.isfile(config_path):
        return _prompt_and_write_config(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError:
        print(f"Invalid JSON in {config_path}. Recreating it now.")
        return _prompt_and_write_config(config_path)

    username = str(config.get("username", ""))
    password = str(config.get("password", ""))

    if not username or not password:
        print(f"{config_path} is missing username/password. Let's update it now.")
        return _prompt_and_write_config(config_path)

    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run SBScraper apps from a single entrypoint."
    )

    app_group = parser.add_mutually_exclusive_group(required=True)
    app_group.add_argument(
        "-pwrid",
        action="store_true",
        help="Run ReportByID app (expects one or more PWRIDs).",
    )
    app_group.add_argument(
        "-fuel",
        action="store_true",
        help="Run FuelTankReport app (expects one or more site IDs).",
    )
    app_group.add_argument(
        "-coord",
        action="store_true",
        help="Run CoordFromID app (expects a PDF directory path).",
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
    if not ensure_config_ready():
        sys.exit(1)

    parser = build_parser()
    args = parser.parse_args()

    if args.pwrid:
        if not args.ids:
            parser.error("-pwrid requires one or more IDs.")

        from ReportByID import run as run_report_by_id

        asyncio.run(run_report_by_id(args.ids))
        return

    if args.fuel:
        if not args.ids:
            parser.error("-fuel requires one or more IDs.")

        from FuelTankReport import run as run_fuel_tank_report

        asyncio.run(run_fuel_tank_report(args.ids))
        return

    if args.coord:
        if len(args.ids) != 1:
            parser.error("-coord requires exactly one directory path.")

        from CoordFromID import run as run_coord_from_id

        run_coord_from_id(args.ids[0], args.output)
        return

    parser.error("You must choose one app flag.")


if __name__ == "__main__":
    main()
