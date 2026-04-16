import asyncio
import sys
import os
import re
from pathlib import Path

import pdfplumber
from playwright.async_api import async_playwright
from sb_config import get_execution_dir, load_credentials
from sb_login import LoginError, login_to_sb
from sb_ui import run_with_spinner, wait_with_spinner


LOGIN_URL = "https://sb.ventia.com.au/"
SEARCH_URL = "https://sb.ventia.com.au/Search/Search"
TARGET_URL = "https://sb.ventia.com.au/HierarchyBuilder/LoadHierarchy?OrgCode=ORG01&SiteCode=SITE001&ClientCode=TELSTRA&SystemId=MAIN001&StructureCode="
PDF_OUTPUT_DIR = "output"

RED = "\033[91m"
ORANGE = "\033[33m"
RESET = "\033[0m"
PAGE_RECHECK_DELAY_MS = 7000
PAGE_RELOAD_DELAY_MS = 3000
PARENT_READY_TIMEOUT_MS = 20000
PARENT_READY_POLL_MS = 500
SITE_NAME_READY_TIMEOUT_MS = 10000
SITE_NAME_READY_POLL_MS = 500
REPORT_ACTION_DELAY_MS = 4000
REPORT_TRIGGER_ATTEMPTS = 2
SITE_NAME_SELECTOR = (
    '//table[@id="tblReport"]/tbody[2]/tr[1]/td[1]/table/tbody[1]/tr[1]/td[1]'
)


def _configure_playwright_env() -> None:
    if getattr(sys, "frozen", False) and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"


def _path_with_uri(path: str) -> str:
    resolved = Path(path).resolve()
    return resolved.as_uri()


def _sanitize(value: str | None) -> str:
    return re.sub(r"[^\w\- ]", "_", str(value or "")).strip()


def _report_suffix(status: str) -> str:
    if "DECOMMISSIONED" in status:
        return "__Decommissioned__"
    if "INVALID" in status:
        return "__Invalid__"
    return ""


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

    if normalized:
        return True, ""

    iframe_count = await report_page.locator("iframe").count()
    if iframe_count > 0:
        return True, ""

    if await report_page.locator("object").count() > 0:
        return True, ""

    if await report_page.locator("embed").count() > 0:
        return True, ""

    return False, "page content empty"


async def _wait_until_parent_page_ready(page) -> tuple[bool, str, str, str]:
    await page.wait_for_load_state("domcontentloaded")

    attempts = max(1, PARENT_READY_TIMEOUT_MS // PARENT_READY_POLL_MS)
    last_reason = "required fields/functions not ready"

    for _ in range(attempts):
        status = await page.get_attribute('input[name="Status"]', "value")
        client_ref_id = await page.get_attribute('input[name="ClientRef"]', "value")
        js_ready = await page.evaluate(
            "() => typeof TelstraSystemSYReportClick === 'function'"
            " && typeof SystemReportClick === 'function'"
            " && typeof PrintReportByName === 'function'"
        )

        missing = []
        if status is None:
            missing.append("Status")
        if client_ref_id is None:
            missing.append("ClientRef")
        if not js_ready:
            missing.append("report javascript")

        if not missing:
            return True, _sanitize(status), _sanitize(client_ref_id), ""

        last_reason = "missing " + ", ".join(missing)
        await page.wait_for_timeout(PARENT_READY_POLL_MS)

    return False, "", "", last_reason


async def _wait_until_site_name_ready(page) -> tuple[str, str]:
    attempts = max(1, SITE_NAME_READY_TIMEOUT_MS // SITE_NAME_READY_POLL_MS)
    last_reason = "site name empty"

    for _ in range(attempts):
        try:
            element = await page.query_selector(SITE_NAME_SELECTOR)
            site_name = _sanitize(await element.inner_text() if element else "")
        except Exception as exc:
            site_name = ""
            last_reason = f"could not read site name ({exc})"
        else:
            if site_name:
                return site_name, ""
            last_reason = "site name empty"

        await page.wait_for_timeout(SITE_NAME_READY_POLL_MS)

    return "", last_reason


async def _wait_until_report_ready(report_page, report_name: str) -> tuple[bool, str]:
    await report_page.wait_for_load_state("networkidle")

    is_ready, reason = await _page_has_report_content(report_page)
    if is_ready:
        return True, ""

    print(f"{RED}Warning: {report_name} not ready for PDF ({reason}).{RESET}")
    await wait_with_spinner("Waiting before retry", PAGE_RECHECK_DELAY_MS)
    is_ready, reason = await _page_has_report_content(report_page)
    if is_ready:
        return True, ""

    print(f"{RED}Warning: {report_name} still not ready ({reason}).{RESET}")
    await run_with_spinner(
        "Reloading report window", report_page.reload(wait_until="networkidle")
    )
    await wait_with_spinner("Allowing report render to settle", PAGE_RELOAD_DELAY_MS)
    return await _page_has_report_content(report_page)


def _remove_file_if_exists(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _build_pdf_filename(
    report_prefix: str, client_ref_id: str, site_name: str, suffix: str
) -> str:
    suffix_part = f" {suffix}" if suffix else ""
    return f"{report_prefix} - ({client_ref_id}) {site_name}{suffix_part}.pdf"


async def _save_pdf_if_report_ready(
    report_page,
    pdf_path: str,
    report_name: str,
    context_label: str,
) -> tuple[bool, str]:
    is_ready, reason = await _wait_until_report_ready(report_page, report_name)
    if not is_ready:
        return False, f"{report_name} | {context_label} | {reason}"

    await report_page.pdf(path=pdf_path, format="A4", print_background=True)

    try:
        is_blank_pdf = _is_pdf_blank(pdf_path)
    except Exception as exc:
        print(
            f"{RED}Warning: Could not validate PDF content ({pdf_path}): {exc}{RESET}"
        )
        print(f"Saved: {Path(pdf_path).name}")
        return True, ""

    if is_blank_pdf:
        _warn_if_blank_pdf(pdf_path, report_name)
        _remove_file_if_exists(pdf_path)
        return (
            False,
            f"{report_name} | {context_label} | saved file was blank and removed",
        )

    print(f"Saved: {Path(pdf_path).name}")
    return True, ""


async def _open_report_page(
    context, page, report_name: str, action_js: str, print_js: str
):
    await page.evaluate(action_js)
    await wait_with_spinner(f"Waiting for {report_name} action", REPORT_ACTION_DELAY_MS)

    async with context.expect_page() as report_page_info:
        await page.evaluate(print_js)

    report_page = await report_page_info.value
    await report_page.wait_for_load_state("networkidle")
    return report_page


async def _search_row_by_pwrid(page, target_id: str):
    await page.fill('input[name="StructCode"]', target_id)
    await page.click('button[name="btnSearch"]')
    await page.wait_for_load_state("networkidle")

    selector = (
        f'//tbody/tr[td[@role="gridcell" and normalize-space(text())="{target_id}"]]'
    )
    return await page.query_selector(selector)


async def _save_report_with_retries(
    context,
    page,
    parent_url: str,
    pdf_path: str,
    site_name_fallback: str | None,
    report_name: str,
    context_label: str,
    action_js: str,
    print_js: str,
    failed_saves: list[str],
) -> tuple[bool, str, str]:
    last_failure = f"{report_name} | {context_label} | unknown failure"
    resolved_site_name = ""
    last_site_name_reason = "site name empty"
    effective_pdf_path = pdf_path

    for attempt in range(1, REPORT_TRIGGER_ATTEMPTS + 1):
        if attempt > 1:
            await run_with_spinner(
                f"Refreshing parent page for {report_name} retry",
                page.goto(parent_url, wait_until="networkidle"),
            )
            parent_ready, _, _, parent_reason = await _wait_until_parent_page_ready(
                page
            )
            if not parent_ready:
                last_failure = (
                    f"{report_name} | {context_label} | "
                    f"parent page not ready on retry ({parent_reason})"
                )
                continue

        report_page = None
        try:
            report_page = await _open_report_page(
                context=context,
                page=page,
                report_name=report_name,
                action_js=action_js,
                print_js=print_js,
            )

            attempt_site_name, site_name_reason = await _wait_until_site_name_ready(
                page
            )
            if attempt_site_name:
                resolved_site_name = attempt_site_name
                last_site_name_reason = ""
                if site_name_fallback:
                    effective_pdf_path = pdf_path.replace(
                        site_name_fallback,
                        attempt_site_name,
                    )
            else:
                last_site_name_reason = site_name_reason
                if site_name_fallback and resolved_site_name:
                    effective_pdf_path = pdf_path.replace(
                        site_name_fallback,
                        resolved_site_name,
                    )
                else:
                    effective_pdf_path = pdf_path

            saved, failure_reason = await _save_pdf_if_report_ready(
                report_page=report_page,
                pdf_path=effective_pdf_path,
                report_name=report_name,
                context_label=context_label,
            )
        except Exception as exc:
            saved = False
            failure_reason = (
                f"{report_name} | {context_label} | report window failed ({exc})"
            )
            print(
                f"{RED}Warning: {report_name} trigger attempt {attempt}/"
                f"{REPORT_TRIGGER_ATTEMPTS} failed ({exc}).{RESET}"
            )
        finally:
            if report_page is not None:
                try:
                    await report_page.close()
                except Exception:
                    pass

        if saved:
            return True, resolved_site_name, last_site_name_reason

        last_failure = failure_reason
        if attempt < REPORT_TRIGGER_ATTEMPTS:
            print(
                f"{ORANGE}Warning: {report_name} failed on trigger attempt "
                f"{attempt}/{REPORT_TRIGGER_ATTEMPTS}; retrying from parent page.{RESET}"
            )

    failed_saves.append(last_failure)
    print(
        f"{RED}Skipping save: {report_name} failed after "
        f"{REPORT_TRIGGER_ATTEMPTS} trigger attempt(s). {context_label}{RESET}"
    )
    return False, resolved_site_name, last_site_name_reason


async def run(target_ids):
    _configure_playwright_env()
    output_dir = get_execution_dir() / PDF_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    username, password = load_credentials()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        try:
            await login_to_sb(page, username, password, LOGIN_URL)
        except LoginError as exc:
            print(exc)
            await browser.close()
            raise SystemExit(1) from exc

        saved_count = 0
        structure_targets = []
        failed_saves: list[str] = []

        for target_id in target_ids:
            await page.goto(SEARCH_URL)

            row = await run_with_spinner(
                f"Searching by PWRID {target_id}",
                _search_row_by_pwrid(page, target_id),
                success_status=None,
            )

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
            (
                parent_ready,
                status,
                client_ref_id,
                parent_reason,
            ) = await _wait_until_parent_page_ready(page)
            if not parent_ready:
                print(
                    f"{RED}Skipping PWRID {target_id}: parent page not ready ({parent_reason}).{RESET}"
                )
                failed_saves.append(
                    f"SY report | PWRID {target_id} | parent page not ready ({parent_reason})"
                )
                failed_saves.append(
                    f"System report | PWRID {target_id} | parent page not ready ({parent_reason})"
                )
                print("")
                continue

            site_name = f"UnknownSite-{target_id}"
            suffix = _report_suffix(status)

            sy_pdf_filename = _build_pdf_filename(
                "SYReport",
                client_ref_id,
                site_name,
                suffix,
            )
            sy_pdf_path = str(output_dir / sy_pdf_filename)

            (
                sy_saved,
                resolved_site_name,
                site_name_reason,
            ) = await _save_report_with_retries(
                context=context,
                page=page,
                parent_url=url,
                pdf_path=sy_pdf_path,
                site_name_fallback=site_name,
                report_name="SY report",
                context_label=f"PWRID {target_id}",
                action_js="TelstraSystemSYReportClick()",
                print_js=(
                    "PrintReportByName(TelstraSystemSYReportModalWindow, "
                    "'TelstraSystemSYReport')"
                ),
                failed_saves=failed_saves,
            )
            if sy_saved:
                saved_count += 1

            if resolved_site_name:
                site_name = resolved_site_name
            else:
                print(
                    f"{ORANGE}Warning: Could not resolve site name for PWRID {target_id} "
                    f"({site_name_reason}); using {site_name}.{RESET}"
                )

            system_pdf_filename = _build_pdf_filename(
                "SystemReport",
                client_ref_id,
                site_name,
                suffix,
            )
            system_pdf_path = str(output_dir / system_pdf_filename)

            system_saved, _, _ = await _save_report_with_retries(
                context=context,
                page=page,
                parent_url=url,
                pdf_path=system_pdf_path,
                site_name_fallback=None,
                report_name="System report",
                context_label=f"PWRID {target_id}",
                action_js="SystemReportClick()",
                print_js=(
                    "PrintReportByName(SystemInformationReportWindow, "
                    "'SystemInformationReport')"
                ),
                failed_saves=failed_saves,
            )
            if system_saved:
                saved_count += 1

            print("")

        await browser.close()

        if saved_count == 0:
            print("\nNo reports to process and save.\n")
        elif saved_count == 1:
            print(
                f"\n{saved_count} report saved successfully.\n{_path_with_uri(output_dir)}\n"
            )
        else:
            print(
                f"\n{saved_count} reports saved successfully.\n{_path_with_uri(output_dir)}\n"
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
