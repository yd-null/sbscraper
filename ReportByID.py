import asyncio
import sys
import os
import re
import json
from pathlib import Path

import pdfplumber
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


LOGIN_URL = "https://sb.ventia.com.au/"
SEARCH_URL = "https://sb.ventia.com.au/Search/Search"
TARGET_URL = "https://sb.ventia.com.au/HierarchyBuilder/LoadHierarchy?OrgCode=ORG01&SiteCode=SITE001&ClientCode=TELSTRA&SystemId=MAIN001&StructureCode="
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
ORANGE = "\033[33m"
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


def _warn_if_blank_pdf(pdf_path: str, report_name: str) -> None:
    try:
        is_blank = _is_pdf_blank(pdf_path)
    except Exception as exc:
        print(
            f"{RED}Warning: Could not validate PDF content ({pdf_path}): {exc}{RESET}"
        )
        return

    if is_blank:
        print(
            f"{RED}Warning: {report_name} appears blank. "
            "This may be a failed report render or an auth/session issue."
            f"{RESET}"
        )


async def _page_has_report_content(report_page) -> tuple[bool, str]:
    try:
        body_text = await report_page.evaluate(
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
        return False, "report window looks like a login page"

    if has_error_markers:
        return False, "report window shows an error/access page"

    return True, ""


async def _wait_until_report_ready(report_page, report_name: str) -> tuple[bool, str]:
    await report_page.wait_for_load_state("networkidle")

    is_ready, reason = await _page_has_report_content(report_page)
    if is_ready:
        return True, ""

    print(
        f"{RED}Warning: {report_name} not ready for PDF ({reason}). "
        f"Waiting {PAGE_RECHECK_DELAY_MS}ms before retry...{RESET}"
    )
    await report_page.wait_for_timeout(PAGE_RECHECK_DELAY_MS)
    is_ready, reason = await _page_has_report_content(report_page)
    if is_ready:
        return True, ""

    print(
        f"{RED}Warning: {report_name} still not ready ({reason}). "
        f"Reloading report window once...{RESET}"
    )
    await report_page.reload(wait_until="networkidle")
    await report_page.wait_for_timeout(PAGE_RELOAD_DELAY_MS)
    return await _page_has_report_content(report_page)


def _remove_file_if_exists(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


async def _save_pdf_if_report_ready(
    report_page,
    pdf_path: str,
    report_name: str,
    context_label: str,
    failed_saves: list[str],
) -> bool:
    is_ready, reason = await _wait_until_report_ready(report_page, report_name)
    if not is_ready:
        failed_saves.append(
            f"{report_name} | {context_label} | {reason} | {_path_with_uri(pdf_path)}"
        )
        print(
            f"{RED}Skipping save: {report_name} still blank after wait+reload. "
            f"{context_label}{RESET}"
        )
        return False

    await report_page.pdf(path=pdf_path, format="A4", print_background=True)

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
            f"{report_name} | {context_label} | saved file still blank | {_path_with_uri(pdf_path)}"
        )
        _warn_if_blank_pdf(pdf_path, report_name)
        _remove_file_if_exists(pdf_path)
        print(f"{RED}Removed blank PDF after save: {_path_with_uri(pdf_path)}{RESET}")
        return False

    print(f"Saved: {_path_with_uri(pdf_path)}")
    return True


async def run(target_ids):
    _configure_playwright_env()
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
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
        structure_targets = []
        failed_saves: list[str] = []

        for target_id in target_ids:
            await page.goto(SEARCH_URL)

            print(f"Searching by PWRID {target_id}...", end="", flush=True)
            await page.fill('input[name="StructCode"]', target_id)
            await page.click('button[name="btnSearch"]')
            await page.wait_for_load_state("networkidle")

            # XPath to find a row that contains a cell with exact target_id
            selector = f'//tbody/tr[td[@role="gridcell" and normalize-space(text())="{target_id}"]]'
            row = await page.query_selector(selector)

            if row:
                first_td = await row.query_selector("td:nth-of-type(1)")
                if first_td:
                    structure_code = (await first_td.inner_text()).strip()
                    if structure_code:
                        structure_targets.append((target_id, structure_code))
                        print(
                            f"\rSearching by PWRID {target_id}  --  Found record with Structure Code: {structure_code}"
                        )
                    else:
                        print("First <td> is empty.")
                else:
                    print("First <td> not found in the row.")
            else:
                print(
                    f"\rSearching by PWRID {target_id}  --  {RED}No matching record found for {target_id}. Skipping.{RESET}"
                )

        print("")

        for target_id, structure_id in structure_targets:
            url = f"{TARGET_URL}{structure_id}&ExpandLast=False"
            print(f"Fetching PWRID {ORANGE}{target_id}{RESET}: {url}")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")

            status = await page.get_attribute('input[name="Status"]', "value")
            status = str(status)
            status = re.sub(r"[^\w\- ]", "_", status).strip()

            client_ref_id = await page.get_attribute('input[name="ClientRef"]', "value")
            client_ref_id = str(client_ref_id)
            client_ref_id = re.sub(r"[^\w\- ]", "_", client_ref_id).strip()

            ### SY REPORT ###
            await page.evaluate("TelstraSystemSYReportClick()")

            await page.wait_for_timeout(4000)  # wait for action to complete

            async with context.expect_page() as report_page_info:
                await page.evaluate(
                    "PrintReportByName(TelstraSystemSYReportModalWindow, 'TelstraSystemSYReport')"
                )

            report_page = await report_page_info.value

            await report_page.wait_for_load_state("networkidle")

            element = await page.query_selector(
                '//table[@id="tblReport"]/tbody[2]/tr[1]/td[1]/table/tbody[1]/tr[1]/td[1]'
            )
            site_name = await element.inner_text() if element else ""
            site_name = re.sub(r"[^\w\- ]", "_", site_name).strip()

            suffix = (
                "__Decommissioned__"
                if "DECOMMISSIONED" in status
                else "__Invalid__"
                if "INVALID" in status
                else ""
            )
            pdf_filename = f"SYReport - ({client_ref_id}) {site_name} {suffix}.pdf"
            pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)

            sy_saved = await _save_pdf_if_report_ready(
                report_page=report_page,
                pdf_path=pdf_path,
                report_name="SY report",
                context_label=f"PWRID {client_ref_id}",
                failed_saves=failed_saves,
            )
            if sy_saved:
                saved_count += 1

            await report_page.close()

            # await page.click('a.k-button.k-bare.k-button-icon.k-window-action[aria-label="Close"]')
            # await page.locator('a.k-window-action[aria-label="Close"]').first().click({ force: true });

            ### SYSTEM REPORT ###
            await page.evaluate("SystemReportClick()")

            await page.wait_for_timeout(4000)  # wait for action to complete

            async with context.expect_page() as report_page_info:
                await page.evaluate(
                    "PrintReportByName(SystemInformationReportWindow, 'SystemInformationReport')"
                )

            report_page = await report_page_info.value

            await report_page.wait_for_load_state("networkidle")

            # element = await page.query_selector('//table[@id="tblReport"]/tbody[2]/tr[1]/td[1]/table/tbody[1]/tr[1]/td[1]')
            # site_name = await element.inner_text() if element else ""
            # site_name = re.sub(r"[^\w\- ]", "_", site_name).strip()

            suffix = (
                "__Decommissioned__"
                if "DECOMMISSIONED" in status
                else "__Invalid__"
                if "INVALID" in status
                else ""
            )
            pdf_filename = f"SystemReport - ({client_ref_id}) {site_name} {suffix}.pdf"
            pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)

            system_saved = await _save_pdf_if_report_ready(
                report_page=report_page,
                pdf_path=pdf_path,
                report_name="System report",
                context_label=f"PWRID {client_ref_id}",
                failed_saves=failed_saves,
            )
            if system_saved:
                saved_count += 1

            await report_page.close()

            # await page.click('a.k-button.k-bare.k-button-icon.k-window-action[aria-label="Close"]')

            print("")

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
        print("Usage: python scriptname.py 10 20 30 40  # Numbers are PWRIDs")
        sys.exit(1)

    # Skip the first argv (script name) and convert to strings
    site_ids = sys.argv[1:]
    asyncio.run(run(site_ids))
