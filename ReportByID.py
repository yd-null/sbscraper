import asyncio
import sys
import os
import re
import json

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


LOGIN_URL = "https://sb.ventia.com.au/"
SEARCH_URL = "https://sb.ventia.com.au/Search/Search"
TARGET_URL = "https://sb.ventia.com.au/HierarchyBuilder/LoadHierarchy?OrgCode=ORG01&SiteCode=SITE001&ClientCode=TELSTRA&SystemId=MAIN001&StructureCode="
PDF_OUTPUT_DIR = "output"

with open("config.json", "r") as f:
    config = json.load(f)

USERNAME = config["username"]
PASSWORD = config["password"]

RED = "\033[91m"
RESET = "\033[0m"

async def run(target_ids):

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

        await page.wait_for_load_state('networkidle')
        print("Login successful.\n")

        i = 0
        structure_code_list = []

        for target_id in target_ids:
            
            await page.goto(SEARCH_URL)

            print(f"Searching by PWRID {target_id}")
            await page.fill('input[name="StructCode"]', target_id)
            await page.click('button[name="btnSearch"]')
            await page.wait_for_load_state('networkidle')

            # XPath to find a row that contains a cell with exact target_id
            selector = f'//tbody/tr[td[@role="gridcell" and normalize-space(text())="{target_id}"]]'
            row = await page.query_selector(selector)
        
            if row:
                first_td = await row.query_selector('td:nth-of-type(1)')
                if first_td:
                    structure_code = (await first_td.inner_text()).strip()
                    if structure_code:
                        structure_code_list.append(structure_code)
                    else:
                        print("First <td> is empty.")
                else:
                    print("First <td> not found in the row.")
            else:
                print(f"{RED}No matching record found for {target_id}. Skipping...{RESET}")

        for structure_id in structure_code_list:
            url = f"{TARGET_URL}{structure_id}&ExpandLast=False"
            print(f"Fetching: {url}")
            await page.goto(url)
            await page.wait_for_load_state('networkidle')

            status = await page.get_attribute('input[name="Status"]', 'value')
            status = str(status)
            status = re.sub(r"[^\w\- ]", "_", status).strip()

            client_ref_id = await page.get_attribute('input[name="ClientRef"]', 'value')
            client_ref_id = str(client_ref_id)
            client_ref_id = re.sub(r"[^\w\- ]", "_", client_ref_id).strip()

            
            await page.evaluate("TelstraSystemSYReportClick()")

            await page.wait_for_timeout(4000)  # wait for action to complete

            async with context.expect_page() as report_page_info:
                await page.evaluate("PrintReportByName(TelstraSystemSYReportModalWindow, 'TelstraSystemSYReport')")

            report_page = await report_page_info.value
            
            await report_page.wait_for_load_state('networkidle')

            element = await page.query_selector('//table[@id="tblReport"]/tbody[2]/tr[1]/td[1]/table/tbody[1]/tr[1]/td[1]')
            site_name = await element.inner_text() if element else ""
            site_name = re.sub(r"[^\w\- ]", "_", site_name).strip()
            
            suffix = "__Decommissioned__" if "DECOMMISSIONED" in status else ""
            pdf_filename = f"SystemReport - {site_name} ({client_ref_id}) {suffix}.pdf"
            pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)
            
            await report_page.pdf(path=pdf_path, format="A4", print_background=True)
            print(f"Saved: {pdf_path}")

            i += 1

        await browser.close()

        if i == 0:
            print("\nNo reports to process and save.\n")
        elif i == 1:
            print(f"\n{i} report processed and saved successfully.\n{os.path.abspath(PDF_OUTPUT_DIR)}\n")
        else:    
            print(f"\n{i} reports processed and saved successfully.\n{os.path.abspath(PDF_OUTPUT_DIR)}\n")



if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scriptname.py 10 20 30 40  # Numbers are PWRIDs")
        sys.exit(1)

    # Skip the first argv (script name) and convert to strings
    site_ids = sys.argv[1:]
    asyncio.run(run(site_ids))
