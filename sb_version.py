from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


PACKAGE_NAME = "sbscraper"
UNKNOWN_VERSION = "0.0.0"


def _normalize_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def _version_from_metadata() -> str | None:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return None


def _version_from_git(repo_dir: Path) -> str | None:
    commands = [
        ["git", "describe", "--tags", "--exact-match"],
        ["git", "describe", "--tags", "--abbrev=0"],
    ]

    for command in commands:
        try:
            value = subprocess.check_output(
                command,
                cwd=repo_dir,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            continue

        if value:
            return _normalize_tag(value)

    return None


def get_app_version() -> str:
    git_version = _version_from_git(Path(__file__).resolve().parent)
    if git_version:
        return git_version

    metadata_version = _version_from_metadata()
    if metadata_version:
        return metadata_version

    return UNKNOWN_VERSION
