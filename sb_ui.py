from __future__ import annotations

import asyncio
import itertools
import sys
from typing import Awaitable, TypeVar


T = TypeVar("T")
SPINNER_FRAMES = ("|", "/", "-", "\\")
SPINNER_INTERVAL_SECONDS = 0.1


def _supports_spinner() -> bool:
    stream = getattr(sys, "stdout", None)
    return bool(stream and hasattr(stream, "isatty") and stream.isatty())


async def _spin(message: str, stop_event: asyncio.Event) -> None:
    for frame in itertools.cycle(SPINNER_FRAMES):
        if stop_event.is_set():
            break

        print(f"\r{message} {frame}", end="", flush=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SPINNER_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue


def _print_final(message: str, status: str) -> None:
    print(f"\r{message} {status}   ")


async def run_with_spinner(message: str, operation: Awaitable[T]) -> T:
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
        _print_final(message, "failed.")
        raise

    stop_event.set()
    await spinner_task
    _print_final(message, "done.")
    return result


async def wait_with_spinner(message: str, delay_ms: int) -> None:
    await run_with_spinner(message, asyncio.sleep(delay_ms / 1000))
