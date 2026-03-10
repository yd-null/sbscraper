import asyncio
import sys
import os
import re
import json
from pathlib import Path

import pdfplumber
from playwright.async_api import async_playwright


LOGIN_URL = "https://sb.ventia.com.au/"
TARGET_URL = "https://sb.ventia.com.au/FuelTankRegister/DisplaySiteDetails?siteID="
PDF_OUTPUT_DIR = "output"


def _load_config() -> dict:
    exe_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    config_candidates = [
        os.path.join(os.getcwd(), "config.json"),
        os.path.join(exe_dir, "config.json"),
    ]

    for config_path in config_candidates:
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)

    checked = "\n - ".join(config_candidates)
    raise FileNotFoundError("Could not find config.json. Checked:\n - " + checked)


config = _load_config()

USERNAME = config["username"]
PASSWORD = config["password"]

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

    print(
        f"{RED}Warning: Tank report not ready for PDF ({reason}). "
        f"Waiting {PAGE_RECHECK_DELAY_MS}ms before retry...{RESET}"
    )
    await page.wait_for_timeout(PAGE_RECHECK_DELAY_MS)
    is_ready, reason = await _page_has_report_content(page)
    if is_ready:
        return True, ""

    print(
        f"{RED}Warning: Tank report still not ready ({reason}). "
        f"Reloading page once...{RESET}"
    )
    await page.reload(wait_until="networkidle")
    await page.wait_for_timeout(PAGE_RELOAD_DELAY_MS)
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
        print(f"Saved: {_path_with_uri(pdf_path)}")
        return True

    if is_blank_pdf:
        failed_saves.append(
            f"Tank report | {context_label} | saved file was blank and removed"
        )
        _warn_if_blank_pdf(pdf_path)
        _remove_file_if_exists(pdf_path)
        return False

    print(f"Saved: {_path_with_uri(pdf_path)}")
    return True


async def run(site_ids):
    _configure_playwright_env()
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Go to login page
        print("\nLoading login page...")
        await page.goto(LOGIN_URL)

        print("Submitting login form...")
        await page.fill('input[name="UserName"]', USERNAME)
        await page.fill('input[name="Password"]', PASSWORD)
        await page.click('input[type="submit"]')

        await page.wait_for_load_state("networkidle")
        print("Login successful.\n")

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
