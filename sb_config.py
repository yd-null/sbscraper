from __future__ import annotations

import getpass
import json
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


def get_config_path() -> Path:
    return get_execution_dir() / CONFIG_FILE


def _prompt_and_write_config(config_path: Path) -> bool:
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

    with config_path.open("w", encoding="utf-8") as f:
        json.dump({"username": username, "password": password}, f, indent=2)
        f.write("\n")

    print(f"Saved credentials to {config_path}.")
    return True


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
