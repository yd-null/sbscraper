import asyncio
import csv
import sys
import os
import re
from pathlib import Path

import pdfplumber
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
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
PARENT_READY_TIMEOUT_MS = 20000
PARENT_READY_POLL_MS = 500
SITE_NAME_READY_TIMEOUT_MS = 10000
SITE_NAME_READY_POLL_MS = 500
REPORT_ACTION_DELAY_MS = 8000
REPORT_READY_TIMEOUT_MS = 20000
REPORT_READY_POLL_MS = 500
REPORT_TRIGGER_ATTEMPTS = 2
PARENT_READY_RECOVERY_ATTEMPTS = 2
SITE_NAME_SELECTOR = (
    '//table[@id="tblReport"]/tbody[2]/tr[1]/td[1]/table/tbody[1]/tr[1]/td[1]'
)
BATTERY_CSV_FIELDS = [
    "Site Name",
    "PWRID",
    "Status",
    "String #",
    "F/S/R/SR/Pos",
    "Description",
    "Equipment #",
    "Serial #",
    "Equipment Status",
    "DOM",
    "Battery Monitoring Sensor?",
    "Number of Cases",
    "Date of Install",
    "Fuse/Circuit Breaker Rating [Amps]",
    "Fuse/Circuit Breaker Type",
]
BATTERY_DETAIL_LABEL_PATTERNS = (
    r"Battery\s+Monitoring\s+Sensor\?",
    r"Number\s+of\s+Cases",
    r"Date\s+of\s+Install",
    r"Fuse/Circuit\s+Breaker\s+Rating\s+\[Amps\]",
    r"Fuse/Circuit\s+Breaker\s+Type",
    r"String\s+#",
)
BATTERY_STATUS_PATTERN = r"ONLINE|OFFLINE|ACTIVE|INACTIVE|OPERATING|INVALID|DECOMMISSIONED"
SYSTEM_REPORT_PDF_STYLE = """
@page {
  size: A4 landscape;
  margin: 5mm;
}

html,
body,
table,
tr,
td,
th,
div,
span {
  font-size: 7px !important;
  line-height: 1.05 !important;
}

td,
th {
  padding: 0 1px !important;
}
"""


def _configure_playwright_env() -> None:
    if getattr(sys, "frozen", False) and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"


def _path_with_uri(path: str) -> str:
    resolved = Path(path).resolve()
    return resolved.as_uri()


def _sanitize(value: str | None) -> str:
    return re.sub(r"[^\w\- ]", "_", str(value or "")).strip()


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _strip_trailing_address_id(value: str) -> str:
    return re.sub(r"\s+\d+$", "", value).strip()


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


async def _get_page_text(page) -> str:
    return await page.evaluate(
        "() => (document.body && document.body.innerText) ? document.body.innerText : ''"
    )


def _text_has_login_markers(text: str) -> bool:
    lowered = text.lower()
    return ("username" in lowered and "password" in lowered) or "sign in" in lowered


async def _page_looks_like_login(page) -> bool:
    try:
        url = page.url.lower()
        title = (await page.title()).lower()
        if "login" in url or "login" in title:
            return True

        username_count = await page.locator('input[name="UserName"]').count()
        password_count = await page.locator('input[name="Password"]').count()
        if username_count > 0 and password_count > 0:
            return True

        return _text_has_login_markers(await _get_page_text(page))
    except Exception:
        return False


async def _recover_login_if_needed(
    page, username: str, password: str, return_url: str, context_label: str
) -> bool:
    if not await _page_looks_like_login(page):
        return False

    print(f"{ORANGE}Warning: {context_label} reached login page; re-authenticating.{RESET}")
    await login_to_sb(page, username, password, LOGIN_URL)
    await page.goto(return_url, wait_until="networkidle")
    return True


async def _page_has_report_content(report_page) -> tuple[bool, str]:
    try:
        body_text = await _get_page_text(report_page)
    except Exception as exc:
        return False, f"could not read page content ({exc})"

    normalized = " ".join(str(body_text).split()).strip()

    lowered = normalized.lower()
    has_error_markers = any(
        marker in lowered
        for marker in ("access denied", "unauthor", "forbidden", "error")
    )

    if _text_has_login_markers(normalized):
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


async def _page_has_expected_report_content(
    report_page, report_name: str
) -> tuple[bool, str]:
    is_ready, reason = await _page_has_report_content(report_page)
    if not is_ready:
        return False, reason

    text = _clean_text(await _get_page_text(report_page))
    if report_name == "SY report" and "Telstra System (SY) Report" not in text:
        return False, "SY report text not present yet"
    if report_name == "System report" and "System Information Report" not in text:
        return False, "System report text not present yet"

    return True, ""


async def _wait_until_parent_page_ready(page) -> tuple[bool, str, str, str]:
    await page.wait_for_load_state("domcontentloaded")

    attempts = max(1, PARENT_READY_TIMEOUT_MS // PARENT_READY_POLL_MS)
    last_reason = "required fields/functions not ready"

    for _ in range(attempts):
        if await _page_looks_like_login(page):
            return False, "", "", "parent page looks like a login page"

        try:
            status_input = page.locator('input[name="Status"]').first
            has_status_input = await status_input.count() > 0
            status = (
                await status_input.get_attribute("value", timeout=1000)
                if has_status_input
                else None
            )
        except PlaywrightTimeoutError:
            status = None
        except Exception as exc:
            status = None
            last_reason = f"could not read Status ({exc})"

        try:
            js_ready = await page.evaluate(
                "() => typeof TelstraSystemSYReportClick === 'function'"
                " && typeof SystemReportClick === 'function'"
                " && typeof PrintReportByName === 'function'"
            )
        except Exception as exc:
            js_ready = False
            last_reason = f"could not check report javascript ({exc})"

        missing = []
        if status is None:
            missing.append("Status")
        if not js_ready:
            missing.append("report javascript")

        if not missing:
            return True, _sanitize(status), "", ""

        if missing:
            last_reason = "missing " + ", ".join(missing)
        await page.wait_for_timeout(PARENT_READY_POLL_MS)

    return False, "", "", last_reason


async def _ensure_parent_page_ready(
    page, url: str, username: str, password: str, context_label: str
) -> tuple[bool, str, str, str]:
    last_reason = "parent page not ready"

    for attempt in range(1, PARENT_READY_RECOVERY_ATTEMPTS + 1):
        parent_ready, status, client_ref, reason = await _wait_until_parent_page_ready(
            page
        )
        if parent_ready:
            return True, status, client_ref, ""

        last_reason = reason
        if attempt >= PARENT_READY_RECOVERY_ATTEMPTS:
            break

        if "login" in reason.lower() or await _page_looks_like_login(page):
            await _recover_login_if_needed(page, username, password, url, context_label)
        else:
            await run_with_spinner(
                f"Reloading parent page for {context_label}",
                page.goto(url, wait_until="networkidle"),
            )

    return False, "", "", last_reason


async def _wait_until_site_name_ready(
    page, sanitize: bool = True
) -> tuple[str, str]:
    attempts = max(1, SITE_NAME_READY_TIMEOUT_MS // SITE_NAME_READY_POLL_MS)
    last_reason = "site name empty"

    for _ in range(attempts):
        try:
            element = await page.query_selector(SITE_NAME_SELECTOR)
            site_name = _clean_text(await element.inner_text() if element else "")
            site_name = _strip_trailing_address_id(site_name)
            if sanitize:
                site_name = _sanitize(site_name)
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
    await report_page.wait_for_load_state("domcontentloaded")

    attempts = max(1, REPORT_READY_TIMEOUT_MS // REPORT_READY_POLL_MS)
    last_reason = "report content not ready"

    for _ in range(attempts):
        is_ready, reason = await _page_has_expected_report_content(
            report_page, report_name
        )
        if is_ready:
            return True, ""

        last_reason = reason
        await report_page.wait_for_timeout(REPORT_READY_POLL_MS)

    return False, last_reason


def _remove_file_if_exists(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _build_pdf_filename(
    report_prefix: str, report_id: str, site_name: str, suffix: str
) -> str:
    suffix_part = f" {suffix}" if suffix else ""
    return f"{report_prefix} - ({report_id}) {site_name}{suffix_part}.pdf"


def _report_identifier(client_locn: str, target_id: str) -> str:
    return _sanitize(client_locn or target_id)


def _is_battery_row_start(line: str) -> bool:
    return bool(re.search(r"\bBattery\s+String\b", line, re.IGNORECASE))


def _is_battery_detail_start(line: str) -> bool:
    return bool(
        re.match(
            r"^-?(?:"
            + "|".join(BATTERY_DETAIL_LABEL_PATTERNS)
            + r")(?:\s|$)",
            line,
            re.IGNORECASE,
        )
    )


def _is_report_section_start(line: str) -> bool:
    if re.match(r"^[A-Za-z].*\(DCP-SS-[^)]+\)\s+-", line):
        return True
    return line in {
        "Housing",
        "Power Conversion",
        "Batteries",
        "DC Distribution",
        "Controls",
    }


def _collect_battery_blocks(text: str) -> list[list[str]]:
    lines = [_clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if _is_battery_row_start(line):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        elif current_block and _is_report_section_start(line):
            blocks.append(current_block)
            current_block = []
        elif current_block:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)

    return blocks


def _extract_labeled_battery_value(block_text: str, label_pattern: str) -> str:
    stop_pattern = "|".join(BATTERY_DETAIL_LABEL_PATTERNS)
    match = re.search(
        rf"{label_pattern}\s*(?P<value>.*?)(?=\s*-?(?:{stop_pattern})\s*|$)",
        block_text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    return _clean_text(match.group("value").strip(" -"))


def _parse_battery_block(
    block_lines: list[str],
    site_name: str,
    target_id: str,
    site_status: str,
    sequence: int,
) -> dict[str, str]:
    detail_start = next(
        (
            index
            for index, line in enumerate(block_lines)
            if _is_battery_detail_start(line)
        ),
        len(block_lines),
    )

    row_text = _clean_text(" ".join(block_lines[:detail_start]))
    block_text = _clean_text(" ".join(block_lines))
    battery_match = re.search(r"\bBattery\s+String\b", row_text, re.IGNORECASE)

    fsr_pos = ""
    description = row_text
    equipment_number = ""
    serial_number = ""
    status = ""
    dom = ""

    if battery_match:
        fsr_pos = _clean_text(row_text[: battery_match.start()])
        battery_text = row_text[battery_match.start() :].strip()
        equipment_match = re.search(r"\s(?P<equipment>\d{7,})(?P<tail>.*)$", battery_text)
        if equipment_match:
            description = _clean_text(battery_text[: equipment_match.start()])
            equipment_number = equipment_match.group("equipment")
            tail = _clean_text(equipment_match.group("tail"))
            status_match = re.search(
                rf"(?P<serial>.*?)(?P<status>{BATTERY_STATUS_PATTERN})\s*"
                r"(?P<dom>\d{2}/\d{2}/\d{4})\s*$",
                tail,
                re.IGNORECASE,
            )
            if status_match:
                serial_number = _clean_text(status_match.group("serial"))
                status = status_match.group("status").upper()
                dom = status_match.group("dom")
            else:
                dom_match = re.search(r"(?P<dom>\d{2}/\d{2}/\d{4})\s*$", tail)
                if dom_match:
                    serial_number = _clean_text(tail[: dom_match.start()])
                    dom = dom_match.group("dom")
                else:
                    serial_number = tail
        else:
            description = _clean_text(battery_text)

    string_match = re.search(r"String\s+#\s*(\d+)", block_text, re.IGNORECASE)
    string_number = string_match.group(1) if string_match else str(sequence)

    return {
        "Site Name": site_name,
        "PWRID": target_id,
        "Status": site_status,
        "String #": string_number,
        "F/S/R/SR/Pos": fsr_pos,
        "Description": description,
        "Equipment #": equipment_number,
        "Serial #": serial_number,
        "Equipment Status": status,
        "DOM": dom,
        "Battery Monitoring Sensor?": _extract_labeled_battery_value(
            block_text, r"Battery\s+Monitoring\s+Sensor\?"
        ),
        "Number of Cases": _extract_labeled_battery_value(
            block_text, r"Number\s+of\s+Cases"
        ),
        "Date of Install": _extract_labeled_battery_value(
            block_text, r"Date\s+of\s+Install"
        ),
        "Fuse/Circuit Breaker Rating [Amps]": _extract_labeled_battery_value(
            block_text, r"Fuse/Circuit\s+Breaker\s+Rating\s+\[Amps\]"
        ),
        "Fuse/Circuit Breaker Type": _extract_labeled_battery_value(
            block_text, r"Fuse/Circuit\s+Breaker\s+Type"
        ),
    }


def _extract_battery_rows_from_text(
    text: str, site_name: str, target_id: str, site_status: str
) -> list[dict[str, str]]:
    return [
        _parse_battery_block(
            block_lines=block,
            site_name=site_name,
            target_id=target_id,
            site_status=site_status,
            sequence=index,
        )
        for index, block in enumerate(_collect_battery_blocks(text), start=1)
    ]


def _parse_system_battery_block(
    block_lines: list[str],
    site_name: str,
    target_id: str,
    site_status: str,
    sequence: int,
) -> dict[str, str]:
    detail_start = next(
        (
            index
            for index, line in enumerate(block_lines)
            if _is_battery_detail_start(line)
        ),
        len(block_lines),
    )

    row_text = _clean_text(" ".join(block_lines[:detail_start]))
    block_text = _clean_text(" ".join(block_lines))

    description = row_text
    equipment_number = ""
    fsr_pos = ""
    serial_number = ""
    status = ""
    dom = ""

    equipment_match = re.search(r"\((?P<equipment>\d{7,})\)", row_text)
    if equipment_match:
        description = _clean_text(row_text[: equipment_match.start()])
        equipment_number = equipment_match.group("equipment")
        tail = _clean_text(row_text[equipment_match.end() :])

        dom_match = re.search(r"(?P<dom>\d{2}/\d{2}/\d{4})", tail)
        if dom_match:
            fsr_pos = _clean_text(tail[: dom_match.start()])
            dom = dom_match.group("dom")
            rest = _clean_text(tail[dom_match.end() :])
            project_match = re.search(r"\b\d{7,}/\S*", rest)
            if project_match:
                serial_number = _clean_text(rest[: project_match.start()])
                status_search_text = rest[project_match.end() :]
            else:
                status_search_text = rest

            status_match = re.search(
                rf"({BATTERY_STATUS_PATTERN})", status_search_text, re.IGNORECASE
            )
            if status_match:
                status = status_match.group(1).upper()
        else:
            fsr_pos = tail

    string_match = re.search(r"String\s+#\s*(\d+)", block_text, re.IGNORECASE)
    string_number = string_match.group(1) if string_match else str(sequence)

    return {
        "Site Name": site_name,
        "PWRID": target_id,
        "Status": site_status,
        "String #": string_number,
        "F/S/R/SR/Pos": fsr_pos,
        "Description": description,
        "Equipment #": equipment_number,
        "Serial #": serial_number,
        "Equipment Status": status,
        "DOM": dom,
        "Battery Monitoring Sensor?": _extract_labeled_battery_value(
            block_text, r"Battery\s+Monitoring\s+Sensor\?"
        ),
        "Number of Cases": _extract_labeled_battery_value(
            block_text, r"Number\s+of\s+Cases"
        ),
        "Date of Install": _extract_labeled_battery_value(
            block_text, r"Date\s+of\s+Install"
        ),
        "Fuse/Circuit Breaker Rating [Amps]": _extract_labeled_battery_value(
            block_text, r"Fuse/Circuit\s+Breaker\s+Rating\s+\[Amps\]"
        ),
        "Fuse/Circuit Breaker Type": _extract_labeled_battery_value(
            block_text, r"Fuse/Circuit\s+Breaker\s+Type"
        ),
    }


def _extract_battery_rows_from_system_text(
    text: str, site_name: str, target_id: str, site_status: str
) -> list[dict[str, str]]:
    return [
        _parse_system_battery_block(
            block_lines=block,
            site_name=site_name,
            target_id=target_id,
            site_status=site_status,
            sequence=index,
        )
        for index, block in enumerate(_collect_battery_blocks(text), start=1)
    ]


def _extract_site_name_from_report_text(text: str) -> str:
    lines = [_clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    for index, line in enumerate(lines):
        if line == "Site Details" and index > 0:
            return lines[index - 1]

    return ""


def _extract_site_name_from_system_report_text(text: str) -> str:
    lines = [_clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    for index, line in enumerate(lines):
        if line.startswith("System:") and index > 0:
            return _strip_trailing_address_id(lines[index - 1])

    return ""


def _extract_client_locn_from_system_report_text(text: str) -> str:
    normalized = _clean_text(text)
    match = re.search(
        r"\bClient\s+Locn?\.?\s*:\s*(?P<value>.*?)(?=\s+"
        r"(?:Float|Load|EST\s+Capacity|PMS|Address\s+ID)\s*:|$)",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return ""

    value = _clean_text(match.group("value"))
    return value.split()[0] if value else ""


async def _save_ready_report_pdf(
    report_page,
    pdf_path: str,
    report_name: str,
    context_label: str,
    pdf_style: str | None = None,
) -> tuple[bool, str]:
    if pdf_style:
        await report_page.add_style_tag(content=pdf_style)

    await report_page.pdf(
        path=pdf_path, format="A4", landscape=True, print_background=True
    )

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


async def _save_pdf_if_report_ready(
    report_page,
    pdf_path: str,
    report_name: str,
    context_label: str,
    pdf_style: str | None = None,
) -> tuple[bool, str]:
    is_ready, reason = await _wait_until_report_ready(report_page, report_name)
    if not is_ready:
        return False, f"{report_name} | {context_label} | {reason}"

    return await _save_ready_report_pdf(
        report_page=report_page,
        pdf_path=pdf_path,
        report_name=report_name,
        context_label=context_label,
        pdf_style=pdf_style,
    )


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


async def _open_ready_report_with_retries(
    context,
    page,
    parent_url: str,
    report_name: str,
    context_label: str,
    action_js: str,
    print_js: str,
    username: str | None = None,
    password: str | None = None,
) -> tuple[object | None, str, str]:
    last_failure = f"{report_name} | {context_label} | unknown failure"

    for attempt in range(1, REPORT_TRIGGER_ATTEMPTS + 1):
        if attempt > 1:
            await run_with_spinner(
                f"Refreshing parent page for {report_name} retry",
                page.goto(parent_url, wait_until="networkidle"),
            )
            if username and password:
                parent_ready, _, _, parent_reason = await _ensure_parent_page_ready(
                    page, parent_url, username, password, context_label
                )
            else:
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
        report_ready = False
        try:
            report_page = await _open_report_page(
                context=context,
                page=page,
                report_name=report_name,
                action_js=action_js,
                print_js=print_js,
            )
            is_ready, reason = await _wait_until_report_ready(report_page, report_name)
            if is_ready:
                report_ready = True
                return report_page, await _get_page_text(report_page), ""

            last_failure = f"{report_name} | {context_label} | {reason}"
            if reason == "report window looks like a login page" and username and password:
                await _recover_login_if_needed(
                    page, username, password, parent_url, context_label
                )
        except Exception as exc:
            last_failure = f"{report_name} | {context_label} | report window failed ({exc})"
            print(
                f"{RED}Warning: {report_name} trigger attempt {attempt}/"
                f"{REPORT_TRIGGER_ATTEMPTS} failed ({exc}).{RESET}"
            )
        finally:
            if report_page is not None and not report_ready:
                try:
                    await report_page.close()
                except Exception:
                    pass

        if attempt < REPORT_TRIGGER_ATTEMPTS:
            print(
                f"{ORANGE}Warning: {report_name} failed on trigger attempt "
                f"{attempt}/{REPORT_TRIGGER_ATTEMPTS}; retrying from parent page.{RESET}"
            )

    return None, "", last_failure


async def _search_row_by_pwrid(page, target_id: str):
    await page.fill('input[name="StructCode"]', target_id)
    await page.click('button[name="btnSearch"]')
    await page.wait_for_load_state("networkidle")

    selector = (
        f'//tbody/tr[td[@role="gridcell" and normalize-space(text())="{target_id}"]]'
    )
    return await page.query_selector(selector)


async def _search_row_by_pwrid_with_retries(page, target_id: str):
    for attempt in range(1, REPORT_TRIGGER_ATTEMPTS + 1):
        row = await _search_row_by_pwrid(page, target_id)
        if row:
            return row

        if attempt < REPORT_TRIGGER_ATTEMPTS:
            await page.wait_for_timeout(REPORT_READY_POLL_MS)

    return None


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
    pdf_style: str | None = None,
    username: str | None = None,
    password: str | None = None,
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
            if username and password:
                parent_ready, _, _, parent_reason = await _ensure_parent_page_ready(
                    page, parent_url, username, password, context_label
                )
            else:
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
                pdf_style=pdf_style,
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


async def _extract_system_battery_rows_with_retries(
    context,
    page,
    parent_url: str,
    target_id: str,
    site_name: str,
    site_status: str,
    username: str | None = None,
    password: str | None = None,
) -> tuple[list[dict[str, str]], str]:
    report_page, report_text, failure_reason = await _open_ready_report_with_retries(
        context=context,
        page=page,
        parent_url=parent_url,
        report_name="System report",
        context_label=f"PWRID {target_id}",
        action_js="SystemReportClick()",
        print_js=(
            "PrintReportByName(SystemInformationReportWindow, "
            "'SystemInformationReport')"
        ),
        username=username,
        password=password,
    )
    if report_page is None:
        return [], failure_reason

    try:
        resolved_site_name = (
            _extract_site_name_from_system_report_text(report_text)
            or site_name
            or f"UnknownSite-{target_id}"
        )
        rows = _extract_battery_rows_from_system_text(
            text=report_text,
            site_name=resolved_site_name,
            target_id=target_id,
            site_status=site_status,
        )
        if rows:
            return rows, ""

        return (
            [],
            f"Battery CSV | PWRID {target_id} | "
            "no Battery String rows found in System report",
        )
    finally:
        try:
            await report_page.close()
        except Exception:
            pass


async def _extract_battery_rows_with_retries(
    context,
    page,
    parent_url: str,
    target_id: str,
    site_name: str,
    site_status: str,
    failed_exports: list[str],
    username: str | None = None,
    password: str | None = None,
) -> list[dict[str, str]]:
    system_rows, system_failure = await _extract_system_battery_rows_with_retries(
        context=context,
        page=page,
        parent_url=parent_url,
        target_id=target_id,
        site_name=site_name,
        site_status=site_status,
        username=username,
        password=password,
    )
    if system_rows:
        return system_rows

    failed_exports.append(system_failure)
    print(
        f"{RED}Skipping battery CSV export for PWRID {target_id}: "
        f"{system_failure}{RESET}"
    )
    return []


class _BatteryCsvWriter:
    def __init__(self, output_csv: str):
        self.output_path = Path(output_csv)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=BATTERY_CSV_FIELDS)
        self._writer.writeheader()
        self.flush()

    def writerows(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return

        self._writer.writerows(rows)
        self.flush()

    def flush(self) -> None:
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


async def run_battery_csv(target_ids, output_csv: str = "battery_report.csv"):
    _configure_playwright_env()
    username, password = load_credentials()

    csv_writer = _BatteryCsvWriter(output_csv)
    exported_count = 0
    failed_exports: list[str] = []

    try:
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

            for target_id in target_ids:
                await page.goto(SEARCH_URL)
                await _recover_login_if_needed(
                    page, username, password, SEARCH_URL, "Search page"
                )

                row = await run_with_spinner(
                    f"Searching by PWRID {target_id}",
                    _search_row_by_pwrid_with_retries(page, target_id),
                    success_status=None,
                )

                if not row:
                    message = f"Battery CSV | PWRID {target_id} | no matching record found"
                    failed_exports.append(message)
                    print(
                        f"\rSearching by PWRID {target_id}  --  "
                        f"{RED}No matching record found for {target_id}. Skipping.{RESET}"
                    )
                    continue

                first_td = await row.query_selector("td:nth-of-type(1)")
                structure_code = (await first_td.inner_text()).strip() if first_td else ""
                if not structure_code:
                    message = f"Battery CSV | PWRID {target_id} | structure code missing"
                    failed_exports.append(message)
                    print(
                        f"\rSearching by PWRID {target_id}  --  "
                        f"{RED}Structure Code missing. Skipping.{RESET}"
                    )
                    continue

                print(
                    f"\rSearching by PWRID {target_id}  --  "
                    f"Found record with Structure Code: {structure_code}"
                )

                url = f"{TARGET_URL}{structure_code}&ExpandLast=False"
                print(f"Fetching battery data for PWRID {ORANGE}{target_id}{RESET}: {url}")
                await page.goto(url)
                (
                    parent_ready,
                    status,
                    _,
                    parent_reason,
                ) = await _ensure_parent_page_ready(
                    page, url, username, password, f"PWRID {target_id}"
                )
                if not parent_ready:
                    message = (
                        f"Battery CSV | PWRID {target_id} | "
                        f"parent page not ready ({parent_reason})"
                    )
                    failed_exports.append(message)
                    print(
                        f"{RED}Skipping PWRID {target_id}: "
                        f"parent page not ready ({parent_reason}).{RESET}"
                    )
                    print("")
                    continue

                site_name, _ = await _wait_until_site_name_ready(page, sanitize=False)

                rows = await _extract_battery_rows_with_retries(
                    context=context,
                    page=page,
                    parent_url=url,
                    target_id=target_id,
                    site_name=site_name,
                    site_status=status,
                    failed_exports=failed_exports,
                    username=username,
                    password=password,
                )
                csv_writer.writerows(rows)
                exported_count += len(rows)
                if rows:
                    print(
                        f"Exported {len(rows)} battery string(s) for PWRID {target_id}."
                    )
                print("")

            await browser.close()
    finally:
        csv_writer.close()

    if exported_count:
        print(
            f"\n{exported_count} battery string(s) exported successfully.\n"
            f"{_path_with_uri(str(csv_writer.output_path))}\n"
        )
    else:
        print(
            f"\nNo battery strings exported.\n"
            f"{_path_with_uri(str(csv_writer.output_path))}\n"
        )

    if failed_exports:
        print(f"{RED}Skipped {len(failed_exports)} battery export(s):{RESET}")
        for failure in failed_exports:
            print(f" - {failure}")
        print("")


async def run_reports_and_battery_csv(
    target_ids, output_csv: str = "battery_report.csv"
):
    await run(target_ids, battery_output_csv=output_csv)


async def run(target_ids, battery_output_csv: str | None = None):
    _configure_playwright_env()
    output_dir = get_execution_dir() / PDF_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    username, password = load_credentials()
    csv_writer = (
        _BatteryCsvWriter(battery_output_csv)
        if battery_output_csv is not None
        else None
    )
    exported_count = 0
    saved_count = 0
    failed_saves: list[str] = []
    failed_exports: list[str] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport={"width": 1920, "height": 1080})
                page = await context.new_page()

                try:
                    await login_to_sb(page, username, password, LOGIN_URL)
                except LoginError as exc:
                    print(exc)
                    raise SystemExit(1) from exc

                for target_id in target_ids:
                    await page.goto(SEARCH_URL)
                    await _recover_login_if_needed(
                        page, username, password, SEARCH_URL, "Search page"
                    )

                    row = await run_with_spinner(
                        f"Searching by PWRID {target_id}",
                        _search_row_by_pwrid_with_retries(page, target_id),
                        success_status=None,
                    )

                    if not row:
                        print(
                            f"\rSearching by PWRID {target_id}  --  "
                            f"{RED}No matching record found for {target_id}. "
                            f"Skipping.{RESET}"
                        )
                        continue

                    first_td = await row.query_selector("td:nth-of-type(1)")
                    structure_id = (await first_td.inner_text()).strip() if first_td else ""
                    if not structure_id:
                        print(
                            f"\rSearching by PWRID {target_id}  --  "
                            f"{RED}Structure Code missing. Skipping.{RESET}"
                        )
                        continue

                    print(
                        f"\rSearching by PWRID {target_id}  --  "
                        f"Found record with Structure Code: {structure_id}"
                    )

                    url = f"{TARGET_URL}{structure_id}&ExpandLast=False"
                    print(f"Fetching PWRID {ORANGE}{target_id}{RESET}: {url}")
                    await page.goto(url)
                    (
                        parent_ready,
                        status,
                        _,
                        parent_reason,
                    ) = await _ensure_parent_page_ready(
                        page, url, username, password, f"PWRID {target_id}"
                    )
                    if not parent_ready:
                        print(
                            f"{RED}Skipping PWRID {target_id}: parent page not ready "
                            f"({parent_reason}).{RESET}"
                        )
                        failed_saves.append(
                            f"SY report | PWRID {target_id} | parent page not ready "
                            f"({parent_reason})"
                        )
                        failed_saves.append(
                            f"System report | PWRID {target_id} | parent page not ready "
                            f"({parent_reason})"
                        )
                        if csv_writer is not None:
                            failed_exports.append(
                                f"Battery CSV | PWRID {target_id} | parent page not "
                                f"ready ({parent_reason})"
                            )
                        print("")
                        continue

                    site_name = f"UnknownSite-{target_id}"
                    client_locn = ""
                    suffix = _report_suffix(status)

                    system_report_page, system_report_text, system_failure = (
                        await _open_ready_report_with_retries(
                            context=context,
                            page=page,
                            parent_url=url,
                            report_name="System report",
                            context_label=f"PWRID {target_id}",
                            action_js="SystemReportClick()",
                            print_js=(
                                "PrintReportByName(SystemInformationReportWindow, "
                                "'SystemInformationReport')"
                            ),
                            username=username,
                            password=password,
                        )
                    )
                    if system_report_page is None:
                        failed_saves.append(system_failure)
                        print(
                            f"{RED}Skipping save: System report failed. "
                            f"PWRID {target_id}{RESET}"
                        )
                        if csv_writer is not None:
                            failed_exports.append(
                                f"Battery CSV | PWRID {target_id} | {system_failure}"
                            )
                    else:
                        try:
                            system_site_name = (
                                _extract_site_name_from_system_report_text(
                                    system_report_text
                                )
                                or site_name
                            )
                            site_name = _sanitize(system_site_name)
                            client_locn = _extract_client_locn_from_system_report_text(
                                system_report_text
                            )
                            report_id = _report_identifier(client_locn, target_id)

                            system_pdf_filename = _build_pdf_filename(
                                "SystemReport",
                                report_id,
                                site_name,
                                suffix,
                            )
                            system_pdf_path = str(output_dir / system_pdf_filename)
                            system_saved, system_failure = await _save_ready_report_pdf(
                                report_page=system_report_page,
                                pdf_path=system_pdf_path,
                                report_name="System report",
                                context_label=f"PWRID {target_id}",
                                pdf_style=SYSTEM_REPORT_PDF_STYLE,
                            )
                            if system_saved:
                                saved_count += 1
                            else:
                                failed_saves.append(system_failure)

                            if csv_writer is not None:
                                rows = _extract_battery_rows_from_system_text(
                                    text=system_report_text,
                                    site_name=system_site_name,
                                    target_id=target_id,
                                    site_status=status,
                                )
                                csv_writer.writerows(rows)
                                exported_count += len(rows)
                                if rows:
                                    print(
                                        f"Exported {len(rows)} battery string(s) for "
                                        f"PWRID {target_id}."
                                    )
                                else:
                                    failed_exports.append(
                                        f"Battery CSV | PWRID {target_id} | "
                                        "no Battery String rows found in System report"
                                    )
                        finally:
                            try:
                                await system_report_page.close()
                            except Exception:
                                pass

                    report_id = _report_identifier(client_locn, target_id)
                    sy_pdf_filename = _build_pdf_filename(
                        "SYReport", report_id, site_name, suffix
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
                        username=username,
                        password=password,
                    )
                    if sy_saved:
                        saved_count += 1

                    if not resolved_site_name:
                        print(
                            f"{ORANGE}Warning: Could not resolve site name for "
                            f"PWRID {target_id} ({site_name_reason}); using "
                            f"{site_name}.{RESET}"
                        )

                    print("")
            finally:
                await browser.close()
    finally:
        if csv_writer is not None:
            csv_writer.close()

    if saved_count == 0:
        print("\nNo reports to process and save.\n")
    elif saved_count == 1:
        print(f"\n{saved_count} report saved successfully.\n{_path_with_uri(output_dir)}\n")
    else:
        print(
            f"\n{saved_count} reports saved successfully.\n"
            f"{_path_with_uri(output_dir)}\n"
        )

    if failed_saves:
        print(f"{RED}Skipped {len(failed_saves)} report(s) due to blank content:{RESET}")
        for failure in failed_saves:
            print(f" - {failure}")
        print("")

    if csv_writer is not None:
        output_path = csv_writer.output_path
        if exported_count:
            print(
                f"\n{exported_count} battery string(s) exported successfully.\n"
                f"{_path_with_uri(str(output_path))}\n"
            )
        else:
            print(f"\nNo battery strings exported.\n{_path_with_uri(str(output_path))}\n")

        if failed_exports:
            print(f"{RED}Skipped {len(failed_exports)} battery export(s):{RESET}")
            for failure in failed_exports:
                print(f" - {failure}")
            print("")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scriptname.py 10 20 30 40  # Numbers are PWRIDs")
        sys.exit(1)

    # Skip the first argv (script name) and convert to strings
    site_ids = sys.argv[1:]
    asyncio.run(run(site_ids))
