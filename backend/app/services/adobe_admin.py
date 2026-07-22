"""Adobe Admin Console 管理服务。

封装:管理员登录(自动收验证码)→ 发现组织/产品/授权组 → 批量加子账号并授权
→ 检测有效性 → 删除成员。所有网络请求复用内置协议(curl_cffi Chrome 指纹)。
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from app.services.adobe_otp import make_otp_poller
from app.services.adobe_protocol import admin_member_protocol as _p
from app.services.adobe_protocol.admin_member_protocol import (
    AdminAuth,
    ProtocolError,
    add_member,
    assign_product_to_member,
    choose_org,
    choose_product,
    client_from_state,
    find_member_id_by_email,
    get_organizations,
    get_products,
    list_members,
    list_product_users,
    remove_members,
)

LogFn = Callable[[str], None]
_AUTH_HOST = _p.AUTH_HOST

# 被邀请子号首次登录需"补全账号":统一设置的密码(可按需修改)
COMPLETE_PASSWORD = "Aa1230123.."

_FIRST_NAMES = [
    "Daniel", "Michael", "James", "David", "John", "Robert", "William", "Joseph",
    "Thomas", "Charles", "Emily", "Sarah", "Jessica", "Ashley", "Jennifer",
    "Amanda", "Laura", "Olivia", "Emma", "Sophia", "Ryan", "Kevin", "Brian",
    "Eric", "Steven", "Andrew", "Joshua", "Brandon", "Justin", "Aaron",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Taylor",
    "Moore", "Jackson", "Martin", "Lee", "Thompson", "White", "Harris",
    "Clark", "Lewis", "Walker", "Hall", "Allen", "Young", "King", "Wright",
]

# marketingConsent 文案(与浏览器抓包一致,服务端会校验存在性)
_MARKETING_CONSENT_TEXT = (
    '<section data-id="MarketingConsent-Implicit"><p>By clicking Complete account, '
    "I agree that:</p><ul class=\"pl-300\"><li>I have read and accepted the "
    '<a href="https://www.adobe.com/legal/terms-linkfree.html" target="_blank" '
    'rel="noreferrer">Terms of Use</a>.</li><li>The '
    '<a href="https://www.adobe.com/privacy/policy-linkfree.html" target="_blank" '
    'rel="noreferrer">Adobe family of companies</a> may keep me informed with '
    '<a href="https://www.adobe.com/privacy/marketing-linkfree.html#mktg-email" '
    'target="_blank" rel="noreferrer">personalized</a> emails about products and '
    'services.</li></ul><p>See our <a '
    'href="https://www.adobe.com/privacy/policy-linkfree.html#info-share" '
    'target="_blank" rel="noreferrer">Privacy Policy</a> for more details or to '
    "opt-out at any time.</p></section>"
)


def _register_region() -> tuple[str, str]:
    """读取注册/补全账号所用的国家与 locale(默认 SG / en_US)。

    US 区会被 Adobe 的 firefly_geoip_blocking 及第三方模型地区灰度挡掉,
    SG(新加坡)实测放行。可在「系统设置」里调整。
    """
    try:
        from app.crud import setting as _setting_crud
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            s = _setting_crud.get_settings(db)
            return (s.register_country or "SG"), (s.register_locale or "en_US")
        finally:
            db.close()
    except Exception:
        return "SG", "en_US"


def _random_name() -> tuple[str, str]:
    return random.choice(_FIRST_NAMES), random.choice(_LAST_NAMES)


def _random_dob() -> dict[str, int]:
    """随机生成一个成年人的出生日期(规避 COPPA 未成年限制)。"""
    return {
        "day": random.randint(1, 28),
        "month": random.randint(1, 12),
        "year": random.randint(1980, 2000),
    }


def complete_sub_account(
    auth: "AdminAuth", email: str, lf: LogFn, password: str = COMPLETE_PASSWORD,
    *, country: str = "", locale: str = "",
) -> None:
    """被邀请子号首次登录:若账号未补全,自动填写姓名/密码/生日并接受条款,
    然后激活并切换到企业(被邀请)资料,使后续可换取 firefly token。

    复用收到验证码后的 incompleteAccount 会话(auth.susi_token)。幂等:已补全则只切资料。
    """
    try:
        r = auth.client.get(
            f"{_AUTH_HOST}/signin/v1/accounts/me?client_id={auth.client_id}",
            headers=auth.headers(), timeout=20,
        )
        data = r.json() if r.status_code == 200 else {}
    except Exception as e:  # noqa: BLE001
        lf(f"读取子号资料失败:{e}")
        return
    if not isinstance(data, dict) or not data:
        return

    profile = data.get("profileData") or {}
    actions = profile.get("actions") or []
    incomplete = any(
        (a.get("code") == "IncompleteProfile") for a in actions if isinstance(a, dict)
    ) or not data.get("firstName")

    if incomplete:
        if not country or not locale:
            cfg_country, cfg_locale = _register_region()
            country = country or cfg_country
            locale = locale or cfg_locale
        first, last = _random_name()
        dob = _random_dob()
        lf(f"账号未补全,自动补全资料(姓名 {first} {last} / 生日 {dob['year']} / "
           f"地区 {country} / 设置密码)…")
        # 密码合规 / 泄露校验(best-effort,失败不阻断)
        for path, body in (
            ("/signin/v1/passwords/validity?existingUser=true", {"password": password}),
            ("/signin/v1/passwords/leak_verification",
             {"username": email, "password": password}),
        ):
            try:
                auth.client.post(
                    f"{_AUTH_HOST}{path}", headers=auth.headers(), json=body, timeout=15
                )
            except Exception:
                pass

        payload = {
            "account": {
                "email": email,
                "phoneNumber": None,
                "firstName": first,
                "lastName": last,
                "password": password,
                "countryCode": country,
                "phoneticFirstName": None,
                "phoneticLastName": None,
                "termsOfUseAcceptances": [
                    {"accepted": True, "name": "ADOBE_MASTER", "language": locale}
                ],
                "marketingConsent": {"text": _MARKETING_CONSENT_TEXT, "accepted": True},
                "isPasswordless": False,
                "type": "individual",
                "dateOfBirth": dob,
                "userId": data.get("userId") or "",
            },
            "regionalOptInKorea": None,
            "regionalOptInChina": None,
            "locale": locale,
        }
        try:
            r = auth.client.put(
                f"{_AUTH_HOST}/signin/v2/accounts",
                headers=auth.headers(), json=payload, timeout=25,
            )
        except Exception as e:  # noqa: BLE001
            lf(f"补全账号请求异常:{e}")
            return
        if r.status_code != 200:
            lf(f"✗ 补全账号失败 {r.status_code}: {(r.text or '')[:200]}")
            return
        lf("✓ 已补全账号资料")
        # 重新拉取资料,拿到更新后的链接
        try:
            r = auth.client.get(
                f"{_AUTH_HOST}/signin/v1/accounts/me?client_id={auth.client_id}",
                headers=auth.headers(), timeout=20,
            )
            data = r.json() if r.status_code == 200 else data
            profile = data.get("profileData") or {}
        except Exception:
            pass

    # 选择并激活企业(被邀请)资料。这里必须拿到企业资料 token;
    # 否则后续 Firefly token 会落在个人上下文,额度接口会返回 ErrMismatchOauthToken。
    last_switch_error = ""
    for switch_attempt in range(1, 4):
        links = profile.get("links") or []
        link = next((lk for lk in links if lk.get("status") == "active"), None) \
            or next((lk for lk in links if lk.get("ident")), None)
        if not link:
            raise AdminError("无企业资料链接,无法切换到团队资料")
        ident = link.get("ident")
        guid = link.get("entitlementAccountUserId") or ""
        desc = link.get("description") or "-"
        if not ident:
            raise AdminError("企业资料缺少 linkId,无法切换")

        if link.get("status") != "active":
            try:
                r = auth.client.post(
                    f"{_AUTH_HOST}/signin/v2/links/{ident}",
                    headers=auth.headers(), json={"status": "active"}, timeout=20,
                )
                if r.status_code not in (200, 204):
                    last_switch_error = f"激活企业资料失败 {r.status_code}: {(r.text or '')[:160]}"
                    lf(last_switch_error)
                    if r.status_code == 401 or "invalid_token" in (r.text or "").lower():
                        raise AdminError(
                            "企业资料会话 token 已失效(401),转入 FF-iOS 授权刷新"
                        )
                else:
                    lf(f"已激活企业资料:{desc}")
                    time.sleep(3)
            except Exception as e:  # noqa: BLE001
                if isinstance(e, AdminError):
                    raise
                last_switch_error = f"激活企业资料异常:{e}"
                lf(last_switch_error)

        if guid:
            try:
                auth.client.put(
                    f"{_AUTH_HOST}/signin/v1/filterprofilemapping",
                    headers=auth.headers(),
                    json={"filter": '{"preferForwardProfile": true};', "guid": guid},
                    timeout=20,
                )
            except Exception as e:  # noqa: BLE001
                lf(f"设置企业资料偏好异常:{e}")

        try:
            lf(f"切换企业资料尝试 {switch_attempt}/3:{desc}")
            r = auth.client.post(
                f"{_AUTH_HOST}/signin/v1/accounts/tokens",
                headers=auth.headers(), json={"linkId": ident}, timeout=25,
            )
            tok = (r.json() or {}).get("token") if r.status_code == 200 else ""
            if tok:
                auth.susi_token = tok
                lf("✓ 已切换到企业资料(可换取 firefly token)")
                return
            last_switch_error = f"切换企业资料未返回 token {r.status_code}: {(r.text or '')[:160]}"
            lf(last_switch_error)
            if r.status_code == 401 or "invalid_token" in (r.text or "").lower():
                raise AdminError(
                    "切换企业资料会话 token 已失效(401),转入 FF-iOS 授权刷新"
                )
        except Exception as e:  # noqa: BLE001
            if isinstance(e, AdminError):
                raise
            last_switch_error = f"切换企业资料异常:{e}"
            lf(last_switch_error)

        # 重新拉取资料,Adobe 后台有时需要几秒才把 active/link 状态写稳。
        time.sleep(5 * switch_attempt)
        try:
            r = auth.client.get(
                f"{_AUTH_HOST}/signin/v1/accounts/me?client_id={auth.client_id}",
                headers=auth.headers(), timeout=20,
            )
            if r.status_code == 200:
                data = r.json() if isinstance(r.json(), dict) else data
                profile = data.get("profileData") or profile
        except Exception:
            pass

    raise AdminError(last_switch_error or "切换企业资料失败,无法继续获取团队 Firefly token")

def _mklog(log: Optional[LogFn]) -> LogFn:
    return log if callable(log) else (lambda _m: None)


class AdminError(RuntimeError):
    pass


_MANUAL_LOGIN_TTL_SECONDS = 600
_manual_login_lock = threading.Lock()
_manual_login_sessions: dict[str, dict[str, Any]] = {}


def _cleanup_manual_login_sessions() -> None:
    now = time.time()
    expired: list[str] = []
    with _manual_login_lock:
        for sid, item in _manual_login_sessions.items():
            if now - float(item.get("created_at") or 0) > _MANUAL_LOGIN_TTL_SECONDS:
                expired.append(sid)
        for sid in expired:
            item = _manual_login_sessions.pop(sid, None)
            client = item.get("client") if isinstance(item, dict) else None
            try:
                if client:
                    client.close()
            except Exception:
                pass


def _store_manual_login_session(payload: dict[str, Any]) -> str:
    _cleanup_manual_login_sessions()
    sid = uuid.uuid4().hex
    payload["created_at"] = time.time()
    with _manual_login_lock:
        _manual_login_sessions[sid] = payload
    return sid


def _pop_manual_login_session(session_id: str, *, keep: bool = False) -> dict[str, Any] | None:
    _cleanup_manual_login_sessions()
    with _manual_login_lock:
        item = _manual_login_sessions.get(session_id) if keep else _manual_login_sessions.pop(session_id, None)
    return item


# ----------------------------------------------------------------------------
# 登录流程辅助(自动识别 密码 / 免密码 / MFA 账号)
# ----------------------------------------------------------------------------

def _probe_auth_methods(auth: "AdminAuth", email: str) -> list[str]:
    r = auth.client.post(
        f"{_AUTH_HOST}/signin/v2/users/accounts",
        headers=auth.headers(), json={"email": email}, timeout=20,
    )
    auth.auth_state_encrypted = r.headers.get(
        "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
    auth.identity_verification_token = r.headers.get(
        "x-identity-verification-token", auth.identity_verification_token)
    methods: list[str] = []
    try:
        data = r.json()
        accounts = data if isinstance(data, list) else [data]
        for acc in accounts:
            if isinstance(acc, dict):
                methods += [str(m) for m in (acc.get("authenticationMethods") or [])]
    except Exception:
        pass
    return methods


def _fresh_auth_session(client, email: str) -> "AdminAuth":
    auth = AdminAuth(client)
    auth.authorize(email, "en_US")
    _probe_auth_methods(auth, email)
    return auth


# 收验证码:单次 30 秒;没收到就重新提交验证码邮件,不继续空等旧邮件。
_OTP_RETRY_ATTEMPTS = 3
_OTP_PER_TRY_SECONDS = 120


def _otp_per_try_seconds(otp_timeout: int) -> int:
    del otp_timeout
    return _OTP_PER_TRY_SECONDS


def _poll_email_code_with_retry(
    email: str,
    poll: Callable,
    lf: LogFn,
    otp_timeout: int,
    *,
    resend: Callable[[], None],
    refresh: Callable[[], None] | None = None,
) -> str:
    """分轮收取验证码:每轮只等 30 秒,超时则重新提交验证码邮件。"""
    per_try = _otp_per_try_seconds(otp_timeout)
    last_err: Exception | None = None
    for attempt in range(1, _OTP_RETRY_ATTEMPTS + 1):
        if attempt > 1:
            lf(f"第 {attempt}/{_OTP_RETRY_ATTEMPTS} 次重发验证码(本轮最多等 {per_try}s)…")
            if refresh:
                refresh()
            resend()
        else:
            lf(f"等待收取验证码(本轮 {per_try}s,超时自动重发,最多 {_OTP_RETRY_ATTEMPTS} 轮)…")
        try:
            return poll(email, timeout=per_try)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < _OTP_RETRY_ATTEMPTS:
                lf(f"本轮未收到验证码,准备重试…")
    raise AdminError(str(last_err)[:200] if last_err else "收取 Adobe 验证码超时")


def _refresh_incomplete_challenge(auth: "AdminAuth") -> None:
    try:
        r = auth.client.get(
            f"{_AUTH_HOST}/signin/v3/challenges?purpose=incompleteAccount",
            headers=auth.headers(), timeout=15,
        )
        auth.auth_state_encrypted = r.headers.get(
            "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
        auth.identity_verification_token = r.headers.get(
            "x-identity-verification-token", auth.identity_verification_token)
    except Exception:
        pass


def _send_incomplete_account_email(auth: "AdminAuth") -> None:
    r = auth.client.post(
        f"{_AUTH_HOST}/signin/v3/challenges"
        "?purpose=incompleteAccount&factor=email&extendedAuthState=false",
        headers=auth.headers(), json={}, timeout=15,
    )
    if r.status_code != 200:
        raise AdminError(f"发送验证码邮件失败 {r.status_code}: {(r.text or '')[:200]}")
    auth.auth_state_encrypted = r.headers.get(
        "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
    auth.identity_verification_token = r.headers.get(
        "x-identity-verification-token", auth.identity_verification_token)


def _refresh_mfa_challenge(auth: "AdminAuth") -> None:
    try:
        r = auth.client.get(
            f"{_AUTH_HOST}/signin/v3/challenges?purpose=multiFactorAuthentication",
            headers=auth.headers(), timeout=15,
        )
        auth.auth_state_encrypted = r.headers.get(
            "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
        auth.identity_verification_token = r.headers.get(
            "x-identity-verification-token", auth.identity_verification_token)
    except Exception:
        pass


def _try_email_mfa_with_log(
    auth: "AdminAuth", email: str, lf: LogFn, poll: Optional[Callable] = None,
    otp_timeout: int = 180,
) -> bool:
    poll = poll or _p.poll_otp
    if not auth.start_email_mfa(email):
        lf("✗ 发起邮箱 MFA 失败 (authenticationstate)")
        return False
    try:
        r = auth.client.get(
            f"{_AUTH_HOST}/signin/v3/challenges?purpose=multiFactorAuthentication",
            headers=auth.headers(), timeout=15,
        )
        auth.auth_state_encrypted = r.headers.get(
            "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
        auth.identity_verification_token = r.headers.get(
            "x-identity-verification-token", auth.identity_verification_token)
    except Exception:
        pass
    if not auth.send_email_challenge():
        lf("✗ Adobe 拒绝发送验证码邮件(会话可能已失效)")
        return False
    lf("✓ 已请求 Adobe 发送验证码 …")

    def _resend_mfa() -> None:
        if not auth.send_email_challenge():
            raise AdminError("重发验证码邮件失败")

    try:
        code = _poll_email_code_with_retry(
            email, poll, lf, otp_timeout,
            resend=_resend_mfa, refresh=lambda: _refresh_mfa_challenge(auth),
        )
    except AdminError as e:
        lf(f"✗ 收验证码失败:{e}")
        return False
    if not auth.verify_email_challenge(code):
        lf("✗ 验证码校验失败(可能已过期或会话失效)")
        return False
    lf("✓ 邮箱 MFA 验证成功")
    return True


def _passwordless_login(
    auth: "AdminAuth", email: str, lf: LogFn, poll: Optional[Callable] = None,
    otp_timeout: int = 180,
) -> None:
    poll = poll or _p.poll_otp
    if not auth.start_email_mfa(email):
        raise AdminError("发起邮箱验证失败 (authenticationstate)")
    _refresh_incomplete_challenge(auth)
    _send_incomplete_account_email(auth)
    lf("已发送验证码邮件 …")

    r = None
    for attempt in range(1, 4):
        if attempt > 1:
            lf(f"验证码被 Adobe 拒绝,第 {attempt}/3 次重发新验证码…")
            _refresh_incomplete_challenge(auth)
            _send_incomplete_account_email(auth)
        code = _poll_email_code_with_retry(
            email, poll, lf, otp_timeout,
            resend=lambda: _send_incomplete_account_email(auth),
            refresh=lambda: _refresh_incomplete_challenge(auth),
        )
        lf("收到验证码后等待 20 秒再提交,避免 Adobe 验证节流…")
        time.sleep(20)
        r = auth.client.post(
            f"{_AUTH_HOST}/signin/v3/tokens?credential=code",
            headers=auth.headers(),
            json={"purpose": "incompleteAccount", "code": str(code)}, timeout=25,
        )
        body = r.text or ""
        if r.status_code == 200:
            break
        if "invalid_code" not in body or attempt >= 3:
            raise AdminError(f"验证码换 token 失败 {r.status_code}: {body[:200]}")
    if r is None or r.status_code != 200:
        raise AdminError("验证码换 token 失败")
    try:
        data = r.json()
    except Exception:
        data = {}
    token = (data.get("token") or data.get("access_token") or "") if isinstance(data, dict) else ""
    if not token:
        raise AdminError(f"验证码登录未返回 token: {str(data)[:200]}")
    auth.susi_token = token
    auth.auth_state_encrypted = r.headers.get(
        "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
    auth.identity_verification_token = r.headers.get(
        "x-identity-verification-token", auth.identity_verification_token)
    lf("✓ 验证码登录成功")


def _select_org_profile(auth: "AdminAuth", lf: LogFn) -> None:
    """type2e(个人邮箱开通的企业资料)需要先选择企业资料才能拿到 admin token。"""
    try:
        r = auth.client.get(
            f"{_AUTH_HOST}/signin/v1/accounts/me"
            f"?client_id={_p.ONESIE_CLIENT_ID}",
            headers=auth.headers(), timeout=20,
        )
        data = r.json() if r.status_code == 200 else {}
    except Exception as e:
        lf(f"读取账号资料失败:{e}")
        return
    links = ((data.get("profileData") or {}).get("links")) or []
    active = [lk for lk in links if lk.get("ident")
             and lk.get("status", "active") == "active"]
    if not active:
        lf("无企业资料链接,按普通账号继续")
        return
    link = active[0]
    link_id = link["ident"]
    guid = link.get("entitlementAccountUserId") or ""
    lf(f"选择企业资料:{link.get('description') or '-'}")
    admin_filter = (
        '{"fallbackToAA":true};'
        "hasRole('ORG_ADMIN') or hasRole('STORAGE_ADMIN') or "
        "hasRole('DEPLOYMENT_ADMIN') or hasRole('PRODUCT_ADMIN') or "
        "hasRole('PRODUCT_SUPPORT_ADMIN') or hasRole('LICENSE_ADMIN') or "
        "hasRole('SUPPORT_ADMIN') or hasRole('USER_GROUP_ADMIN') or "
        "hasRole('CONTRACT_ADMIN')"
    )
    if guid:
        try:
            auth.client.put(
                f"{_AUTH_HOST}/signin/v1/filterprofilemapping",
                headers=auth.headers(),
                json={"filter": admin_filter, "guid": guid}, timeout=15,
            )
        except Exception:
            pass
    try:
        r = auth.client.post(
            f"{_AUTH_HOST}/signin/v1/accounts/tokens",
            headers=auth.headers(), json={"linkId": link_id}, timeout=20,
        )
    except Exception as e:
        lf(f"切换企业资料异常:{e}")
        return
    if r.status_code != 200:
        lf(f"切换企业资料失败 {r.status_code}: {(r.text or '')[:200]}")
        return
    try:
        tok = (r.json() or {}).get("token") or ""
    except Exception:
        tok = ""
    if tok:
        auth.susi_token = tok
        lf("✓ 已切换到企业资料")


def _acquire_admin_token(auth: "AdminAuth", lf: LogFn) -> str:
    try:
        r = auth.client.post(
            f"{_AUTH_HOST}/signin/v1/ims/tokens",
            headers=auth.headers(),
            json={"rememberMe": True, "reauthenticate": None}, timeout=25,
        )
        tok = ""
        try:
            tok = _p.extract_token_from_obj(r.json())
        except Exception:
            pass
        if tok:
            auth.susi_token = tok
            lf("✓ ims/tokens 换取成功")
    except Exception as e:
        lf(f"ims/tokens 异常:{e}")

    try:
        auth.from_susi_token(None)
    except Exception as e:
        lf(f"fromSusi 预热:{e}")

    def _check_token():
        r = auth.client.post(
            f"{_p.IMS_BACKEND}/ims/check/v6/token"
            "?jslVersion=v2-v0.31.0-2-g1e8a8a8",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "client_id": _p.ONESIE_CLIENT_ID,
                "Origin": "https://adminconsole.adobe.com",
                "Referer": "https://adminconsole.adobe.com/",
            },
            data=urlencode({
                "client_id": _p.ONESIE_CLIENT_ID,
                "scope": _p.ADMIN_SCOPE,
            }),
            timeout=25,
        )
        try:
            return r, (r.json() if isinstance(r.json(), dict) else {})
        except Exception:
            return r, {}

    try:
        r, data = _check_token()
        tok = data.get("access_token") if isinstance(data, dict) else ""
        if r.status_code == 200 and tok:
            lf("✓ 通过 check/v6/token 获取正式 access_token")
            return tok
        err = data.get("error") if isinstance(data, dict) else ""
        if err == "ride_AdobeID_acct_eoaChoose":
            raise AdminError(
                "该账号是 type2e(个人邮箱开通的企业资料),IMS 要求选择账号资料"
                "(eoaChoose),当前流程无法自动完成此选择。"
            )
        lf(f"check/v6/token 未返回 token status={r.status_code}")
    except AdminError:
        raise
    except Exception as e:
        lf(f"check/v6/token 异常:{e}")
    raise AdminError("无法获取有效的 admin access_token")


def _session_cookie_str(client) -> str:
    parts: dict[str, str] = {}
    try:
        jar = client.session.cookies
        d = jar.get_dict() if hasattr(jar, "get_dict") else dict(jar)
        parts.update({k: v for k, v in d.items() if v})
    except Exception:
        pass
    try:
        parts.update({k: v for k, v in (client.cookies or {}).items() if v})
    except Exception:
        pass
    return "; ".join(f"{k}={v}" for k, v in parts.items())


def _run_admin_login(email: str, password: str, proxy_url: str,
                     lf: LogFn, *, otp_timeout: int = 180,
                     poll: Optional[Callable] = None) -> tuple[str, str]:
    """统一登录,返回 (admin_access_token, cookie 字符串)。"""
    client = _p.HttpClient(proxy=proxy_url)
    try:
        auth = AdminAuth(client)
        auth.authorize(email, "en_US")
        methods = _probe_auth_methods(auth, email)
        has_password = any("password" in m.lower() for m in methods)
        lf(f"账号认证方式:{', '.join(methods) if methods else '无(免密码账号)'}")
        if has_password and password:
            lf("使用密码登录 …")
            if not auth.password_susi(email, password):
                lf("密码直登未成功(Adobe 常要求先邮箱验证),重新建立会话 …")
                auth = _fresh_auth_session(client, email)
                code_logged_in = False
                try:
                    lf("尝试验证码登录 (incompleteAccount) …")
                    _passwordless_login(auth, email, lf, poll=poll, otp_timeout=otp_timeout)
                    code_logged_in = True
                except AdminError as e:
                    lf(f"验证码登录未成功:{e}")
                if not code_logged_in:
                    lf("改试邮箱 MFA 流程 …")
                    auth = _fresh_auth_session(client, email)
                    if not _try_email_mfa_with_log(
                        auth, email, lf, poll=poll, otp_timeout=otp_timeout,
                    ):
                        raise AdminError("未收到 Adobe 验证码(验证码登录与 MFA 均未成功)")
                    lf("邮箱 MFA 通过,再次尝试密码登录 …")
                    if not auth.password_susi(email, password):
                        raise AdminError("MFA 后密码仍失败,请检查 Adobe 密码")
        else:
            lf("账号无密码,改用验证码登录(incompleteAccount)…")
            _passwordless_login(auth, email, lf, poll=poll, otp_timeout=otp_timeout)
        _select_org_profile(auth, lf)
        token = _acquire_admin_token(auth, lf)
        cookie_str = _session_cookie_str(client)
        return token, cookie_str
    finally:
        try:
            client.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# 对外服务接口
# ----------------------------------------------------------------------------

def _discover(token: str, proxy_url: str, lf: LogFn) -> dict[str, Any]:
    """发现组织 / 产品 / 授权组。返回含 has_org/product_name 的 dict。"""
    client = client_from_state({"proxy": proxy_url})
    try:
        orgs = get_organizations(client, token)
        org = choose_org(orgs)
        org_id = str(org.get("id") or org.get("orgId") or "")
        lf(f"✓ 发现组织 {len(orgs)} 个,选用 org_id={org_id}")
        products = get_products(client, token, org_id)
        pid, lgid, pinfo = choose_product(products)
        pname = (pinfo.get("longName") or pinfo.get("shortName")
                 or pinfo.get("code") or "").strip()
        lf(f"✓ 发现产品 {len(products)} 个,选用 {pname or pid}")
        return {
            "has_org": True,
            "org_id": org_id,
            "product_id": pid,
            "product_name": pname,
            "license_group_id": lgid,
            "org_count": len(orgs),
            "product_count": len(products),
        }
    finally:
        client.close()


def login_account(
    *, email: str, adobe_password: str, refresh_token: str, client_id: str,
    proxy_url: str = "", otp_timeout: int = 180, log: Optional[LogFn] = None,
) -> dict[str, Any]:
    """登录管理账号并发现组织/产品。返回管理态 + 轮换后的 refresh_token。"""
    lf = _mklog(log)
    if not (refresh_token and client_id):
        raise AdminError("缺少 Refresh Token / Client ID,无法自动收取验证码")

    poller, holder = make_otp_poller(
        refresh_token=refresh_token, client_id=client_id,
        proxy_url=proxy_url, timeout=otp_timeout,
        use_proxy_for_mail=bool(proxy_url), log=lf,
    )
    original_poll = _p.poll_otp
    original_log = getattr(_p, "log", None)

    def _tee(msg: Any) -> None:
        try:
            lf(str(msg))
        finally:
            if callable(original_log):
                original_log(msg)

    _p.poll_otp = poller
    _p.log = _tee
    try:
        lf(f"开始登录 {email}(自动识别密码/免密码,如需验证码会自动等待)…")
        lf(f"使用代理:{proxy_url or '(无)'}")
        token, cookie = _run_admin_login(
            email, adobe_password, proxy_url, lf,
            otp_timeout=otp_timeout, poll=poller,
        )
        lf("✓ 登录成功,已获取 admin token")
        result: dict[str, Any] = {
            "token": token,
            "cookie": cookie,
            "rotated_refresh_token": holder.refresh_token if holder.rotated else "",
            "has_org": False,
            "org_id": "",
            "product_id": "",
            "product_name": "",
            "license_group_id": "",
            "org_count": 0,
            "product_count": 0,
        }
        try:
            lf("正在发现组织 / 产品 / 授权组 …")
            disc = _discover(token, proxy_url, lf)
            result.update(disc)
        except ProtocolError as e:
            lf(f"⚠ 未发现可用组织/产品:{e}")
            result["has_org"] = False
            result["message"] = "登录成功但无可用组织/产品"
        return result
    finally:
        _p.poll_otp = original_poll
        if callable(original_log):
            _p.log = original_log


def begin_manual_login(
    *, email: str, adobe_password: str, proxy_url: str = "", log: Optional[LogFn] = None,
) -> dict[str, Any]:
    """发起手动验证码登录:发送 Adobe 邮箱验证码,返回 session_id 等待用户输入。"""
    lf = _mklog(log)
    client = _p.HttpClient(proxy=proxy_url)
    try:
        auth = AdminAuth(client)
        auth.authorize(email, "en_US")
        methods = _probe_auth_methods(auth, email)
        lf(f"账号认证方式:{', '.join(methods) if methods else '无(免密码账号)'}")
        if adobe_password and any("password" in m.lower() for m in methods):
            lf("已检测到密码账号。手动验证码登录将直接发起邮箱验证码备用流程。")
        if not auth.start_email_mfa(email):
            raise AdminError("发起邮箱验证失败 (authenticationstate)")
        _refresh_incomplete_challenge(auth)
        _send_incomplete_account_email(auth)
        lf("✓ 已发送 Adobe 验证码邮件,请查看邮箱并输入 6 位验证码")
        sid = _store_manual_login_session(
            {
                "email": email,
                "proxy_url": proxy_url,
                "client": client,
                "auth": auth,
            }
        )
        return {
            "success": True,
            "message": "已发送验证码邮件",
            "session_id": sid,
        }
    except Exception:
        try:
            client.close()
        except Exception:
            pass
        raise


def complete_manual_login(
    *, session_id: str, code: str, log: Optional[LogFn] = None,
) -> dict[str, Any]:
    """用用户手动输入的验证码完成登录并发现组织/产品。"""
    lf = _mklog(log)
    session_id = str(session_id or "").strip()
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not session_id:
        raise AdminError("手动登录会话为空,请重新发送验证码")
    if len(code) < 4:
        raise AdminError("请输入邮箱收到的验证码")
    item = _pop_manual_login_session(session_id, keep=True)
    if not item:
        raise AdminError("验证码会话已过期,请重新发送验证码")
    auth: AdminAuth = item["auth"]
    client = item["client"]
    proxy_url = str(item.get("proxy_url") or "")
    try:
        r = auth.client.post(
            f"{_AUTH_HOST}/signin/v3/tokens?credential=code",
            headers=auth.headers(),
            json={"purpose": "incompleteAccount", "code": code},
            timeout=25,
        )
        body = r.text or ""
        if r.status_code != 200:
            if "invalid_code" in body:
                raise AdminError("验证码不正确或已过期,请确认后重试")
            raise AdminError(f"验证码换 token 失败 {r.status_code}: {body[:200]}")
        try:
            data = r.json()
        except Exception:
            data = {}
        token = (data.get("token") or data.get("access_token") or "") if isinstance(data, dict) else ""
        if not token:
            raise AdminError(f"验证码登录未返回 token: {str(data)[:200]}")
        auth.susi_token = token
        auth.auth_state_encrypted = r.headers.get(
            "x-ims-authentication-state-encrypted", auth.auth_state_encrypted)
        auth.identity_verification_token = r.headers.get(
            "x-identity-verification-token", auth.identity_verification_token)
        lf("✓ 验证码登录成功")
        _select_org_profile(auth, lf)
        admin_token = _acquire_admin_token(auth, lf)
        cookie = _session_cookie_str(client)
        lf("✓ 登录成功,已获取 admin token")
        result: dict[str, Any] = {
            "token": admin_token,
            "cookie": cookie,
            "has_org": False,
            "org_id": "",
            "product_id": "",
            "product_name": "",
            "license_group_id": "",
            "org_count": 0,
            "product_count": 0,
        }
        try:
            lf("正在发现组织 / 产品 / 授权组 …")
            disc = _discover(admin_token, proxy_url, lf)
            result.update(disc)
        except ProtocolError as e:
            lf(f"⚠ 未发现可用组织/产品:{e}")
            result["has_org"] = False
            result["message"] = "登录成功但无可用组织/产品"
        _pop_manual_login_session(session_id)
        try:
            client.close()
        except Exception:
            pass
        return result
    except AdminError:
        raise
    except Exception as exc:
        raise AdminError(str(exc)[:300]) from exc


def check_admin(*, token: str, org_id: str = "", proxy_url: str = "",
                log: Optional[LogFn] = None) -> dict[str, Any]:
    """用已有 token 检测组织/产品是否可读,判断是否仍有管理权限。"""
    lf = _mklog(log)
    if not token:
        raise AdminError("token 为空,请先登录")
    client = client_from_state({"proxy": proxy_url})
    try:
        orgs = get_organizations(client, token)
        oid = org_id or str(choose_org(orgs).get("id") or "")
        products = get_products(client, token, oid)
        lf(f"✓ 组织 {len(orgs)} 个 / 产品 {len(products)} 个,token 有效")
        return {
            "has_org": True,
            "org_id": oid,
            "org_count": len(orgs),
            "product_count": len(products),
        }
    finally:
        client.close()


def find_complimentary_products(
    *, token: str, org_id: str, product_id: str = "", license_group_id: str = "",
    proxy_url: str = "", log: Optional[LogFn] = None
) -> list[tuple[str, str]]:
    """查找 Adobe Admin Console 里的“免费会员资格/Complimentary Membership”产品。"""
    lf = _mklog(log)
    client = client_from_state({"proxy": proxy_url})
    try:
        products = get_products(client, token, org_id)
    except Exception as exc:  # noqa: BLE001
        lf(f"读取免费会员资格产品失败:{str(exc)[:160]}")
        return []
    finally:
        client.close()

    extras: list[tuple[str, str]] = []
    main_key = (str(product_id or ""), str(license_group_id or ""))
    for p in products:
        name = " ".join(
            str(p.get(k) or "") for k in ("shortName", "longName", "code", "id")
        ).lower()
        if not (
            "complimentary" in name
            or "free membership" in name
            or "免费会员" in name
            or str(p.get("code") or "").upper() == "CCFM"
        ):
            continue
        lgs = p.get("licenseGroupSummaries") or p.get("licenseGroups") or []
        if not lgs:
            continue
        key = (str(p.get("id") or ""), str(lgs[0].get("id") or ""))
        if not key[0] or not key[1] or key == main_key:
            continue
        extras.append(key)
    if extras:
        lf(f"✓ 已发现免费会员资格产品 {len(extras)} 个,将随子号授权一起勾选")
    return extras


def get_product_license_availability(
    *, token: str, org_id: str, product_id: str, proxy_url: str = ""
) -> dict[str, Any]:
    """返回主产品远端授权数量,用于拉号前避免在许可已满时继续消耗邮箱。"""
    client = client_from_state({"proxy": proxy_url})
    try:
        products = get_products(client, token, org_id)
    finally:
        client.close()

    for p in products:
        if str(p.get("id") or "") != str(product_id or ""):
            continue
        assigned = int(p.get("assignedQuantity") or 0)
        unlimited = False
        total = 0
        for q in p.get("licenseQuantities") or []:
            raw = str(q.get("quantity") or "").strip().upper()
            if raw == "UNLIMITED":
                unlimited = True
                continue
            try:
                total += int(raw)
            except Exception:
                pass
        available = 999999 if unlimited else max(total - assigned, 0)
        return {
            "found": True,
            "assigned": assigned,
            "total": "UNLIMITED" if unlimited else total,
            "available": available,
            "name": p.get("longName") or p.get("shortName") or p.get("code") or "",
        }
    return {"found": False, "assigned": 0, "total": 0, "available": 0, "name": ""}


def grant_member(*, token: str, org_id: str, product_id: str,
                 license_group_id: str, email: str,
                 proxy_url: str = "",
                 extra_products: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """添加子账号并分配产品(=授权)。返回 {ok, member_id, message}。"""
    extras = extra_products or []

    def _error_payload(exc: ProtocolError) -> dict[str, Any]:
        message = str(exc)
        error_code = ""
        if "ALLOWABLE_LICENSE_COUNT_EXCEEDED" in message:
            error_code = "license_exhausted"
            message = "Creative Cloud Pro 授权许可数量已满,请先释放母号里的席位或更换有可用许可的母号"
        elif "TRIAL_ALREADY_CONSUMED" in message:
            error_code = "trial_already_consumed"
            message = "免费会员资格/试用已被消耗"
        return {
            "ok": False,
            "member_id": "",
            "message": message[:480],
            "error_code": error_code,
        }

    client = client_from_state({"proxy": proxy_url})
    try:
        def _product_member_id() -> str:
            try:
                users = list_product_users(
                    client,
                    token,
                    org_id,
                    product_id,
                    license_group_id,
                    pages=1,
                    page_size=20,
                    search=email,
                )
            except Exception:
                return ""
            target = str(email or "").strip().lower()
            for user in users:
                if str(user.get("email") or "").strip().lower() == target:
                    return str(user.get("member_id") or "")
            return ""

        def _assign_existing_member(*, warning_code: str = "", warning_msg: str = "") -> dict[str, Any] | None:
            product_mid = _product_member_id()
            if product_mid:
                out = {
                    "ok": True,
                    "member_id": product_mid,
                    "message": "远端已在 Creative Cloud Pro 产品组,跳过重复授权",
                }
                if warning_code:
                    out["warning_code"] = warning_code
                return out
            try:
                mid = find_member_id_by_email(client, token, org_id, email)
            except Exception:
                mid = ""
            if not mid:
                return None
            res = assign_product_to_member(
                client,
                token,
                org_id,
                mid,
                product_id,
                license_group_id,
            )
            if not res.get("ok"):
                text = (
                    (res.get("text") or "")
                    + str(res.get("json") or "")
                ).upper()
                error_code = "trial_already_consumed" if "TRIAL_ALREADY_CONSUMED" in text else "assign_product_failed"
                return {
                    "ok": False,
                    "member_id": mid,
                    "message": f"补授权失败:{(res.get('text') or '')[:360]}",
                    "error_code": error_code,
                }
            message = "已为已有成员补授权 Creative Cloud Pro"
            if warning_msg:
                message += f"({warning_msg})"
            out = {"ok": True, "member_id": mid, "message": message}
            if warning_code:
                out["warning_code"] = warning_code
            return out

        already_mid = _product_member_id()
        if already_mid:
            return {
                "ok": True,
                "member_id": already_mid,
                "message": "远端已在 Creative Cloud Pro 产品组,跳过重复授权",
            }

        try:
            add_member(
                client,
                token,
                org_id,
                email,
                product_id,
                license_group_id,
                extra_products=extras,
            )
        except ProtocolError as e:
            # 免费会员资格经常返回 TRIAL_ALREADY_CONSUMED。此时主产品授权本身
            # 可能仍可用,所以降级为“只授权主产品”再试一次。
            if extras and "TRIAL_ALREADY_CONSUMED" in str(e):
                try:
                    add_member(
                        client,
                        token,
                        org_id,
                        email,
                        product_id,
                        license_group_id,
                        extra_products=[],
                    )
                    try:
                        mid = find_member_id_by_email(client, token, org_id, email)
                    except Exception:
                        mid = ""
                    return {
                        "ok": True,
                        "member_id": mid,
                        "message": "已授权(免费会员资格已消耗,已自动跳过)",
                        "warning_code": "trial_already_consumed",
                    }
                except ProtocolError as retry_exc:
                    assigned = _assign_existing_member(
                        warning_code="trial_already_consumed",
                        warning_msg="免费会员资格已消耗",
                    )
                    if assigned:
                        return assigned
                    return _error_payload(retry_exc)
            if any(
                marker in str(e)
                for marker in (
                    "TRIAL_ALREADY_CONSUMED",
                    "TYPE2E not allowed",
                    "ALREADY",
                    "already",
                    "EXISTS",
                    "exists",
                )
            ):
                assigned = _assign_existing_member(
                    warning_code="existing_member_assigned",
                    warning_msg="成员已存在",
                )
                if assigned:
                    return assigned
            return _error_payload(e)
        try:
            mid = find_member_id_by_email(client, token, org_id, email)
        except Exception:
            mid = ""
        msg = "已授权"
        if extras:
            msg += "+免费会员资格"
        return {"ok": True, "member_id": mid, "message": msg}
    finally:
        client.close()


def remove_member(*, token: str, org_id: str, member_id: str = "",
                  email: str = "", proxy_url: str = "") -> dict[str, Any]:
    client = client_from_state({"proxy": proxy_url})
    try:
        mid = (member_id or "").strip()
        if not mid and email:
            mid = find_member_id_by_email(client, token, org_id, email)
        if not mid:
            return {"ok": False, "message": f"未找到成员:{email or member_id}"}
        res = remove_members(client, token, org_id, [mid])
        return {"ok": bool(res.get("ok")), "message": "已移除" if res.get("ok")
                else f"移除失败:{(res.get('text') or '')[:200]}"}
    finally:
        client.close()


def fetch_members(*, token: str, org_id: str, proxy_url: str = "",
                  search: str = "", pages: int = 20,
                  product_id: str = "", license_group_id: str = "") -> list[dict[str, Any]]:
    client = client_from_state({"proxy": proxy_url})
    try:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in list_members(
            client, token, org_id, pages=pages, page_size=100, search=search
        ):
            email = str(item.get("email") or "").strip().lower()
            key = email or str(item.get("member_id") or "")
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
        if product_id:
            try:
                product_users = list_product_users(
                    client,
                    token,
                    org_id,
                    product_id,
                    license_group_id=license_group_id,
                    pages=pages,
                    page_size=100,
                    search=search,
                )
            except Exception:
                product_users = []
            for item in product_users:
                email = str(item.get("email") or "").strip().lower()
                key = email or str(item.get("member_id") or "")
                if key and key not in seen:
                    seen.add(key)
                    merged.append(item)
        return merged
    finally:
        client.close()
