from __future__ import annotations

import asyncio
import itertools
import sys
from typing import Awaitable, TypeVar


T = TypeVar("T")
SPINNER_FRAMES = ("|", "/", "-", "\\")
SPINNER_INTERVAL_SECONDS = 0.1
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
DEFAULT_SUCCESS_STATUS = f"{GREEN}Done.{RESET}"
DEFAULT_FAILURE_STATUS = f"{RED}Failed.{RESET}"


def _supports_spinner() -> bool:
    stream = getattr(sys, "stdout", None)
    return bool(stream and hasattr(stream, "isatty") and stream.isatty())


def _as_sentence(message: str) -> str:
    if message.endswith((".", "!", "?")):
        return message
    return f"{message}."


async def _spin(message: str, stop_event: asyncio.Event) -> None:
    display_message = _as_sentence(message)

    for frame in itertools.cycle(SPINNER_FRAMES):
        if stop_event.is_set():
            break

        print(f"\r{display_message} {frame}", end="", flush=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SPINNER_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue


def _print_final(message: str, status: str) -> None:
    print(f"\r{_as_sentence(message)} {status}   ")


async def run_with_spinner(
    message: str,
    operation: Awaitable[T],
    success_status: str | None = DEFAULT_SUCCESS_STATUS,
) -> T:
    if not _supports_spinner():
        print(f"{message}...")
        return await operation

    stop_event = asyncio.Event()
    spinner_task = asyncio.create_task(_spin(message, stop_event))

    try:
        result = await operation
    except Exception:
        stop_event.set()
        await spinner_task
        _print_final(message, DEFAULT_FAILURE_STATUS)
        raise

    stop_event.set()
    await spinner_task

    if success_status is not None:
        _print_final(message, success_status)

    return result


async def wait_with_spinner(message: str, delay_ms: int) -> None:
    await run_with_spinner(message, asyncio.sleep(delay_ms / 1000))
