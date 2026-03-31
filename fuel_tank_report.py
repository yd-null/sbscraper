import asyncio
import sys
import os
import re
from pathlib import Path

import pdfplumber
from playwright.async_api import async_playwright
from sb_config import load_credentials
from sb_login import LoginError, login_to_sb
from sb_ui import run_with_spinner, wait_with_spinner


LOGIN_URL = "https://sb.ventia.com.au/"
TARGET_URL = "https://sb.ventia.com.au/FuelTankRegister/DisplaySiteDetails?siteID="
PDF_OUTPUT_DIR = "output"

RED = "\033[91m"
RESET = "\033[0m"
PAGE_RECHECK_DELAY_MS = 7000
PAGE_RELOAD_DELAY_MS = 3000
MIN_PAGE_TEXT_LENGTH = 120


def _configure_playwright_env() -> None:
    if getattr(sys, "frozen", False) and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"


def _path_with_uri(path: str) -> str:
    resolved = Path(path).resolve()
    return resolved.as_uri()


def _is_pdf_blank(pdf_path: str) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return True

        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            if text:
                return False

            has_chars = len(getattr(page, "chars", [])) > 0
            has_images = len(getattr(page, "images", [])) > 0
            has_vectors = (
                len(getattr(page, "lines", []))
                + len(getattr(page, "rects", []))
                + len(getattr(page, "curves", []))
            ) > 0

            if has_chars or has_images or has_vectors:
                return False

    return True


def _warn_if_blank_pdf(pdf_path: str) -> None:
    try:
        is_blank = _is_pdf_blank(pdf_path)
    except Exception as exc:
        print(
            f"{RED}Warning: Could not validate PDF content ({pdf_path}): {exc}{RESET}"
        )
        return

    if is_blank:
        print(
            f"{RED}Warning: Saved PDF appears blank. "
            "This may be a failed report render or an auth/session issue."
            f"{RESET}"
        )


async def _page_has_report_content(page) -> tuple[bool, str]:
    try:
        body_text = await page.evaluate(
            "() => (document.body && document.body.innerText) ? document.body.innerText : ''"
        )
    except Exception as exc:
        return False, f"could not read page content ({exc})"

    normalized = " ".join(str(body_text).split()).strip()
    if len(normalized) < MIN_PAGE_TEXT_LENGTH:
        return False, "page content too short"

    lowered = normalized.lower()
    has_login_markers = (
        "username" in lowered and "password" in lowered
    ) or "sign in" in lowered
    has_error_markers = any(
        marker in lowered
        for marker in ("access denied", "unauthor", "forbidden", "error")
    )

    if has_login_markers:
        return False, "page looks like a login page"

    if has_error_markers:
        return False, "page shows an error/access page"

    return True, ""


async def _wait_until_report_ready(page) -> tuple[bool, str]:
    await page.wait_for_load_state("networkidle")

    is_ready, reason = await _page_has_report_content(page)
    if is_ready:
        return True, ""

    print(f"{RED}Warning: Tank report not ready for PDF ({reason}).{RESET}")
    await wait_with_spinner("Waiting before retry", PAGE_RECHECK_DELAY_MS)
    is_ready, reason = await _page_has_report_content(page)
    if is_ready:
        return True, ""

    print(f"{RED}Warning: Tank report still not ready ({reason}).{RESET}")
    await run_with_spinner(
        "Reloading report page", page.reload(wait_until="networkidle")
    )
    await wait_with_spinner("Allowing report render to settle", PAGE_RELOAD_DELAY_MS)
    return await _page_has_report_content(page)


def _remove_file_if_exists(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


async def _save_pdf_if_report_ready(
    page, pdf_path: str, context_label: str, failed_saves: list[str]
) -> bool:
    is_ready, reason = await _wait_until_report_ready(page)
    if not is_ready:
        failed_saves.append(f"Tank report | {context_label} | {reason}")
        print(
            f"{RED}Skipping save: Tank report still blank after wait+reload. "
            f"{context_label}{RESET}"
        )
        return False

    await page.pdf(path=pdf_path, format="A4", print_background=True)

    try:
        is_blank_pdf = _is_pdf_blank(pdf_path)
    except Exception as exc:
        print(
            f"{RED}Warning: Could not validate PDF content ({pdf_path}): {exc}{RESET}"
        )
        print(f"Saved: {Path(pdf_path).name}")
        return True

    if is_blank_pdf:
        failed_saves.append(
            f"Tank report | {context_label} | saved file was blank and removed"
        )
        _warn_if_blank_pdf(pdf_path)
        _remove_file_if_exists(pdf_path)
        return False

    print(f"Saved: {Path(pdf_path).name}")
    return True


async def run(site_ids):
    _configure_playwright_env()
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    username, password = load_credentials()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await login_to_sb(page, username, password, LOGIN_URL)
        except LoginError as exc:
            print(f"{RED}{exc}{RESET}")
            await browser.close()
            raise SystemExit(1) from exc

        saved_count = 0
        failed_saves: list[str] = []

        for site_id in site_ids:
            url = f"{TARGET_URL}{site_id}"
            print(f"Fetching: {url}")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")

            element = await page.query_selector(
                "tbody tr:nth-of-type(1) td:nth-of-type(2)"
            )
            site_name = await element.inner_text() if element else ""
            site_name = re.sub(r"[^\w\- ]", "_", site_name).strip()

            if not site_name:
                print(
                    f"{RED}Warning: Site ID {site_id} may not exist or has no valid name. Skipping...{RESET}"
                )
                continue

            content = await page.content()
            suffix = "__No Tank__" if "No Tank details available" in content else ""
            pdf_filename = f"Tank Report - {site_name} {suffix}.pdf"
            pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)

            saved = await _save_pdf_if_report_ready(
                page=page,
                pdf_path=pdf_path,
                context_label=f"Site ID {site_id}",
                failed_saves=failed_saves,
            )
            if saved:
                saved_count += 1

        await browser.close()

        if saved_count == 0:
            print("\nNo reports to process and save.\n")
        elif saved_count == 1:
            print(
                f"\n{saved_count} report saved successfully.\n{_path_with_uri(PDF_OUTPUT_DIR)}\n"
            )
        else:
            print(
                f"\n{saved_count} reports saved successfully.\n{_path_with_uri(PDF_OUTPUT_DIR)}\n"
            )

        if failed_saves:
            print(
                f"{RED}Skipped {len(failed_saves)} report(s) due to blank content:{RESET}"
            )
            for failure in failed_saves:
                print(f" - {failure}")
            print("")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scriptname.py 10 20 30 40  # Numbers are Site IDs")
        sys.exit(1)

    # Skip the first argv (script name) and convert to strings
    site_ids = sys.argv[1:]
    asyncio.run(run(site_ids))
