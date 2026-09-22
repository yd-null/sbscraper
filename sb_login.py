from sb_config import load_credentials, prompt_to_update_password
from sb_ui import run_with_spinner


RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"


class LoginError(RuntimeError):
    pass


async def _get_login_failure_message(page) -> str | None:
    failure_cell = page.locator("td.login-failure").first
    if not await failure_cell.is_visible():
        return None

    message = (await failure_cell.inner_text()).strip()
    if message:
        return message

    return "Login failed! Please check your username and password."


async def _submit_login_form(page, username: str, password: str) -> None:
    await page.fill('input[name="UserName"]', username)
    await page.fill('input[name="Password"]', password)
    await page.click('input[type="submit"]')
    await page.wait_for_load_state("domcontentloaded")


async def _attempt_login(page, username: str, password: str, login_url: str) -> None:
    print("")
    await run_with_spinner("Loading login page", page.goto(login_url))
    await run_with_spinner(
        "Submitting login form", _submit_login_form(page, username, password)
    )

    failure_message = await _get_login_failure_message(page)
    if failure_message:
        raise LoginError(f"{RED}{failure_message}{RESET}")

    await run_with_spinner(
        "Finalizing authenticated session", page.wait_for_load_state("networkidle")
    )


async def login_to_sb(page, username: str, password: str, login_url: str) -> None:
    try:
        await _attempt_login(page, username, password, login_url)
    except LoginError as exc:
        stored_username, stored_password = load_credentials()
        if stored_username == username and stored_password != password:
            try:
                await _attempt_login(page, username, stored_password, login_url)
            except LoginError as retry_exc:
                print(retry_exc)
                raise
        else:
            print(exc)
            updated_password = prompt_to_update_password()
            if updated_password is None:
                raise
            try:
                await _attempt_login(page, username, updated_password, login_url)
            except LoginError as retry_exc:
                print(retry_exc)
                raise

    print(f"{GREEN}Login successful.{RESET}\n")
