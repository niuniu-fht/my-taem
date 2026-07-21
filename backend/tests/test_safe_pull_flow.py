from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import firefly, team_builder


class _FakeAuth:
    def __init__(self, client, **_kwargs):
        self.client = client
        self.susi_token = "personal-session"

    def authorize(self, _email: str, _locale: str) -> None:
        return None


class SafePullFlowTests(unittest.TestCase):
    def test_register_account_runs_grant_between_registration_and_switch(self) -> None:
        events: list[str] = []
        client = Mock()
        holder = SimpleNamespace(rotated=False, refresh_token="refresh")

        with (
            patch.object(firefly, "make_otp_poller", return_value=(Mock(), holder)),
            patch.object(firefly._p, "HttpClient", return_value=client),
            patch.object(firefly, "AdminAuth", _FakeAuth),
            patch.object(firefly._adm, "_probe_auth_accounts", return_value=[]),
            patch.object(
                firefly._adm,
                "create_sub_account",
                side_effect=lambda *_args, **_kwargs: events.append("register") or {},
            ),
            patch.object(
                firefly._adm,
                "switch_sub_account_to_enterprise",
                side_effect=lambda *_args, **_kwargs: events.append("switch"),
            ),
            patch.object(firefly, "_acquire_firefly_token", return_value="access"),
            patch.object(firefly._adm, "_session_cookie_str", return_value="cookie"),
            patch.object(
                firefly,
                "fetch_account_info",
                return_value={"user_id": "user", "display_name": "User"},
            ),
            patch.object(
                firefly,
                "fetch_credits_detail",
                return_value={
                    "ok": True,
                    "credits": 1000,
                    "needs_authorization": False,
                    "message": "",
                },
            ),
            patch.object(firefly, "extract_jwt_expiry", return_value=123),
        ):
            result = firefly.register_account(
                email="child@example.com",
                refresh_token="refresh",
                client_id="client",
                before_enterprise_switch=lambda: events.append("grant"),
            )

        self.assertEqual(events, ["register", "grant", "switch"])
        self.assertEqual(result["access_token"], "access")
        client.close.assert_called_once()

    def test_create_sub_account_uses_create_endpoint_and_logs_in(self) -> None:
        create_response = Mock(
            status_code=201,
            headers={"x-ims-authentication-state-encrypted": "created-state"},
            text="",
        )
        create_response.json.return_value = {}
        auxiliary_response = Mock(status_code=200, headers={}, text="")
        client = Mock()
        client.post.side_effect = lambda url, **_kwargs: (
            create_response if url.endswith("/signin/v2/accounts") else auxiliary_response
        )
        auth = SimpleNamespace(
            client=client,
            client_id="client",
            redirect="https://firefly.adobe.com/",
            auth_state_encrypted="",
            identity_verification_token="",
            susi_token="",
            last_auth_error="",
            headers=lambda: {},
            password_susi=Mock(return_value=True),
        )

        with (
            patch.object(firefly._adm, "_register_region", return_value=("SG", "en_US")),
            patch.object(firefly._adm, "_random_name", return_value=("Test", "User")),
            patch.object(
                firefly._adm,
                "_random_dob",
                return_value={"day": 1, "month": 2, "year": 1990},
            ),
            patch.object(
                firefly._adm,
                "_read_sub_account",
                return_value={"firstName": "Test"},
            ),
        ):
            data = firefly._adm.create_sub_account(
                auth, "child@example.com", Mock(),
            )

        create_call = next(
            call for call in client.post.call_args_list
            if call.args[0].endswith("/signin/v2/accounts")
        )
        payload = create_call.kwargs["json"]
        self.assertEqual(payload["account"]["email"], "child@example.com")
        self.assertEqual(payload["account"]["type"], "individual")
        self.assertEqual(auth.auth_state_encrypted, "created-state")
        auth.password_susi.assert_called_once()
        self.assertEqual(data["firstName"], "Test")

    def test_safe_pull_stops_before_switch_when_grant_fails(self) -> None:
        events: list[str] = []
        job = SimpleNamespace(log=Mock())

        def fake_register_account(**kwargs):
            events.append("register")
            kwargs["before_enterprise_switch"]()
            events.append("switch")
            return {}

        with (
            patch.object(firefly, "register_account", side_effect=fake_register_account),
            patch.object(
                team_builder.adobe_admin,
                "grant_member",
                side_effect=lambda **_kwargs: events.append("grant") or {
                    "ok": False,
                    "error_code": "license_exhausted",
                    "message": "full",
                },
            ),
            patch.object(team_builder.adobe_admin, "remove_member") as remove_member,
        ):
            ok, record, message = team_builder._register_one(
                token="admin-token",
                org_id="org",
                product_id="product",
                lgid="group",
                proxy_url="",
                email="child@example.com",
                refresh_token="refresh",
                client_id="client",
                job=job,
            )

        self.assertFalse(ok)
        self.assertEqual(events, ["register", "grant"])
        self.assertEqual(record["error_code"], "license_exhausted")
        self.assertIn("拉取用户/授权失败", message)
        remove_member.assert_not_called()

    def test_safe_pull_preserves_email_when_signup_environment_is_blocked(self) -> None:
        job = SimpleNamespace(log=Mock())

        with (
            patch.object(
                firefly,
                "register_account",
                side_effect=RuntimeError(
                    "创建个人账号失败 400: captcha_required genuine_token"
                ),
            ),
            patch.object(team_builder.adobe_admin, "remove_member") as remove_member,
        ):
            ok, record, message = team_builder._register_one(
                token="admin-token",
                org_id="org",
                product_id="product",
                lgid="group",
                proxy_url="",
                email="child@example.com",
                refresh_token="refresh",
                client_id="client",
                job=job,
            )

        self.assertFalse(ok)
        self.assertEqual(record["error_code"], "registration_environment_blocked")
        self.assertIn("captcha_required", message)
        remove_member.assert_not_called()


if __name__ == "__main__":
    unittest.main()
