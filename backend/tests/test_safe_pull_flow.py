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
            patch.object(firefly._adm, "_probe_auth_methods", return_value=[]),
            patch.object(firefly._adm, "_passwordless_login"),
            patch.object(
                firefly._adm,
                "register_sub_account_profile",
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


if __name__ == "__main__":
    unittest.main()
