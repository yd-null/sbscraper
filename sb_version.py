from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


PACKAGE_NAME = "sbscraper"
UNKNOWN_VERSION = "0.0.0"


def _normalize_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def _version_from_env() -> str | None:
    value = os.getenv("SBSCRAPER_VERSION", "").strip()
    if not value:
        return None
    return _normalize_tag(value)


def _version_from_file() -> str | None:
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "VERSION")

    candidates.append(Path(__file__).resolve().parent / "VERSION")

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        if value:
            return _normalize_tag(value)

    return None


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
    env_version = _version_from_env()
    if env_version:
        return env_version

    file_version = _version_from_file()
    if file_version:
        return file_version

    git_version = _version_from_git(Path(__file__).resolve().parent)
    if git_version:
        return git_version

    metadata_version = _version_from_metadata()
    if metadata_version:
        return metadata_version

    return UNKNOWN_VERSION
