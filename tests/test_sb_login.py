import unittest
from unittest.mock import ANY, AsyncMock, patch

import sb_login


class LoginCorrectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_login_updates_password_and_retries_once(self):
        failure = sb_login.LoginError("bad password")
        attempt_login = AsyncMock(side_effect=[failure, None])

        with patch.object(sb_login, "_attempt_login", attempt_login), patch.object(
            sb_login, "load_credentials", return_value=("user", "old")
        ), patch.object(
            sb_login, "prompt_to_update_password", return_value="new"
        ) as update_password:
            await sb_login.login_to_sb(object(), "user", "old", "https://example.com")

        update_password.assert_called_once_with()
        self.assertEqual(attempt_login.await_count, 2)
        attempt_login.assert_awaited_with(
            ANY, "user", "new", "https://example.com"
        )

    async def test_declined_update_does_not_retry(self):
        failure = sb_login.LoginError("bad password")
        attempt_login = AsyncMock(side_effect=failure)

        with patch.object(sb_login, "_attempt_login", attempt_login), patch.object(
            sb_login, "load_credentials", return_value=("user", "old")
        ), patch.object(sb_login, "prompt_to_update_password", return_value=None):
            with self.assertRaises(sb_login.LoginError):
                await sb_login.login_to_sb(
                    object(), "user", "old", "https://example.com"
                )

        self.assertEqual(attempt_login.await_count, 1)

    async def test_newer_saved_password_is_used_without_prompting(self):
        failure = sb_login.LoginError("bad password")
        attempt_login = AsyncMock(side_effect=[failure, None])

        with patch.object(sb_login, "_attempt_login", attempt_login), patch.object(
            sb_login, "load_credentials", return_value=("user", "new")
        ), patch.object(sb_login, "prompt_to_update_password") as update_password:
            await sb_login.login_to_sb(object(), "user", "old", "https://example.com")

        update_password.assert_not_called()
        attempt_login.assert_awaited_with(
            ANY, "user", "new", "https://example.com"
        )

    async def test_failed_retry_does_not_prompt_again(self):
        first_failure = sb_login.LoginError("old password rejected")
        second_failure = sb_login.LoginError("new password rejected")
        attempt_login = AsyncMock(side_effect=[first_failure, second_failure])

        with patch.object(sb_login, "_attempt_login", attempt_login), patch.object(
            sb_login, "load_credentials", return_value=("user", "old")
        ), patch.object(
            sb_login, "prompt_to_update_password", return_value="new"
        ) as update_password:
            with self.assertRaises(sb_login.LoginError):
                await sb_login.login_to_sb(
                    object(), "user", "old", "https://example.com"
                )

        update_password.assert_called_once_with()
        self.assertEqual(attempt_login.await_count, 2)


if __name__ == "__main__":
    unittest.main()
