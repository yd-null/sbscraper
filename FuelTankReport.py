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

async def run(site_ids):

    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Go to login page
        print("Loading login page...")
        await page.goto(LOGIN_URL)

        # Fill in login form — update selectors accordinglyi
        print("Submitting login form...")
        await page.fill('input[name="UserName"]', USERNAME)
        await page.fill('input[name="Password"]', PASSWORD)
        await page.click('input[type="submit"]')

        await page.wait_for_load_state('networkidle')
        print("Login successful.")

        # Step 2: Loop through siteIDs
        for site_id in site_ids:
            url = f"{TARGET_URL}{site_id}"
            print(f"Fetching: {url}")
            await page.goto(url)
            await page.wait_for_load_state('networkidle')

            # Extract name from <tbody>
            element = await page.query_selector("tbody tr:nth-of-type(1) td:nth-of-type(2)")
            site_name = await element.inner_text() if element else f"site_{site_id}"
            site_name = re.sub(r"[^\w\- ]", "_", site_name).strip()
            
            # Check for "No Tank" message
            content = await page.content()
            suffix = " - No Tank" if "No Tank details available" in content else ""
            pdf_filename = f"{site_name}{suffix}.pdf"
            pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)
            
            # Save PDF
            await page.pdf(path=pdf_path, format="A4", print_background=True)
            print(f"Saved: {pdf_path}")

        content = await page.content()



        # # Get content of the second row, first cell of the first tbody
        # element = await page.query_selector("tbody tr:nth-of-type(1) td:nth-of-type(2)")
        # site_name = await element.inner_text() if element else f"site_{site_id}"
        #
        # # Clean it up for safe filenames
        # safe_site_name = re.sub(r'[^\w\- ]', '_', site_name).strip()
        #
        # # Check for "No Tank" message
        # has_no_tank = "No Tank details available" in await page.content()
        # suffix = " -- No Tank --" if has_no_tank else ""
        #
        # # Final PDF filename
        # pdf_path = f"{PDF_OUTPUT_DIR}/{safe_site_name}{suffix}.pdf"
        # await page.pdf(path=pdf_path, format="A4", print_background=True)
        # print(f"Saved: {pdf_path}")
        #
        # await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scriptname.py 10 20 30 40")
        sys.exit(1)

    # Skip the first argv (script name) and convert to strings
    site_ids = sys.argv[1:]
    asyncio.run(run(site_ids))
