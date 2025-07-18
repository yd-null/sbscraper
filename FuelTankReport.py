import asyncio
import sys
import os
import re
import json

from playwright.async_api import async_playwright


LOGIN_URL = "https://sb.ventia.com.au/"
TARGET_URL = "https://sb.ventia.com.au/FuelTankRegister/DisplaySiteDetails?siteID="
PDF_OUTPUT_DIR = "output"

with open("config.json", "r") as f:
    config = json.load(f)

USERNAME = config["username"]
PASSWORD = config["password"]

RED = "\033[91m"
RESET = "\033[0m"

async def run(site_ids):

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

        await page.wait_for_load_state('networkidle')
        print("Login successful.\n")

        i = 0

        for site_id in site_ids:
            url = f"{TARGET_URL}{site_id}"
            print(f"Fetching: {url}")
            await page.goto(url)
            await page.wait_for_load_state('networkidle')

            element = await page.query_selector("tbody tr:nth-of-type(1) td:nth-of-type(2)")
            site_name = await element.inner_text() if element else ""
            site_name = re.sub(r"[^\w\- ]", "_", site_name).strip()

            if not site_name:
                print(f"{RED}Warning: Site ID {site_id} may not exist or has no valid name. Skipping...{RESET}")
                continue
            
            content = await page.content()
            suffix = "__No Tank__" if "No Tank details available" in content else ""
            pdf_filename = f"Tank Report - {site_name} {suffix}.pdf"
            pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)
            
            await page.pdf(path=pdf_path, format="A4", print_background=True)
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
        print("Usage: python scriptname.py 10 20 30 40  # Numbers are Site IDs")
        sys.exit(1)

    # Skip the first argv (script name) and convert to strings
    site_ids = sys.argv[1:]
    asyncio.run(run(site_ids))
