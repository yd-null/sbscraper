from __future__ import annotations

import getpass
import json
import os
import shutil
import sys
from pathlib import Path


CONFIG_FILE = "config.json"


def _program_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()

    if sys.argv and sys.argv[0] and sys.argv[0] not in {"-c", "-m"}:
        argv0 = Path(sys.argv[0])
        if not argv0.is_absolute():
            argv0 = Path.cwd() / argv0
        return argv0.resolve()

    return Path(__file__).resolve()


def get_execution_dir() -> Path:
    program = _program_path()
    return program if program.is_dir() else program.parent


def get_config_dir() -> Path:
    if sys.platform == "win32":
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    return base_dir / "sbscraper"


def get_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE


def get_output_dirs(output_base: str | Path | None = None) -> tuple[Path, Path]:
    if output_base is not None:
        base_dir = Path(output_base).expanduser()
    elif sys.platform == "win32":
        base_dir = get_config_dir()
    else:
        base_dir = Path.cwd()

    return base_dir / "output", base_dir / "csv"


def _migrate_legacy_config(config_path: Path) -> None:
    legacy_path = get_execution_dir() / CONFIG_FILE
    if config_path.exists() or not legacy_path.is_file() or legacy_path == config_path:
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_path, config_path)
    print(f"Migrated credentials to {config_path}.")


def _prompt_and_write_config(config_path: Path) -> bool:
    try:
        print("Set up credentials for the Structure Builder scraper.")
        username = input("Username: ").strip()
        password = getpass.getpass("Password: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCredential setup cancelled.")
        return False

    if not username or not password:
        print("Username and password are required.")
        return False

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump({"username": username, "password": password}, f, indent=2)
        f.write("\n")

    print(f"Saved credentials to {config_path}.")
    return True


def prompt_to_update_password() -> str | None:
    config_path = get_config_path()
    print("Login failed. Your Structure Builder password may have expired or been reset.")
    print(
        "You may need to sign in to Structure Builder in your web browser "
        "to reset or change it."
    )

    try:
        answer = (
            input("Update the password saved in config.json? [y/N]: ").strip().lower()
        )
        if answer not in {"y", "yes"}:
            return None
        password = getpass.getpass("New password: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nPassword update cancelled.")
        return None

    if not password:
        print("Password cannot be empty.")
        return None

    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    config["password"] = password
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Updated the saved password in {config_path}.")
    return password


def load_credentials() -> tuple[str, str]:
    config_path = get_config_path()
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    username = str(config.get("username", "")).strip()
    password = str(config.get("password", "")).strip()

    if not username or not password:
        raise ValueError(f"{config_path} is missing username/password.")

    return username, password


def ensure_config_ready() -> bool:
    config_path = get_config_path()
    _migrate_legacy_config(config_path)

    if not config_path.is_file():
        return _prompt_and_write_config(config_path)

    try:
        load_credentials()
    except json.JSONDecodeError:
        print(f"Invalid JSON in {config_path}. Recreating it now.")
        return _prompt_and_write_config(config_path)
    except ValueError:
        print(f"{config_path} is missing username/password. Let's update it now.")
        return _prompt_and_write_config(config_path)

    return True
