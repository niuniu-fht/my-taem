"""拉号编排:为 Adobe 母号凑满 N 个已注册可用的子号(支持单主号 / 多主号批量)。

流程(每个子号):从邮箱池取未使用邮箱 → 邀请并分配产品(授权)→ 子号自助登录拿
firefly token/cookie/credits(注册)。登录成功但额度不可用时保留为待母号审批;
失败则把该成员从组织移除并换下一个邮箱重拉,直到注册成功数达到目标或邮箱池耗尽。
批量时按主号顺序处理,主号未登录会自动登录。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time

from app.crud import adobe_account as adobe_crud
from app.crud import adobe_member as member_crud
from app.crud import email as email_crud
from app.crud import setting as setting_crud
from app.db.session import SessionLocal
from app.services import adobe_admin, firefly, member_removal, pool_claim, proxy_pool
from app.services.job_manager import Job


_MAX_CONSECUTIVE_RATE_LIMITS = 1
_MAX_ATTEMPT_MULTIPLIER = 3
_MAX_ATTEMPTS_PER_TEAM = 30
_BUILD_CONCURRENCY_CAP = 1


def _rate_limit_guidance(consecutive: int = 1) -> str:
    return (
        "检测到 Adobe 429 限流,已立即自动停止以保护母号和邮箱池;"
        "建议隔夜后再继续,至少等待 12-24 小时,中途不要重复拉号"
    )


def _is_rate_limited(message: str, rec: dict | None = None) -> bool:
    text = f"{message or ''} {rec or ''}".lower()
    return any(
        marker in text
        for marker in (
            "429",
            "too many",
            "rate limit",
            "ratelimit",
            "too_many_requests",
        )
    )


def _max_attempts_for_target(count: int, remaining: int) -> int:
    base = max(int(count or 0), int(remaining or 0), 1)
    return max(remaining, min(_MAX_ATTEMPTS_PER_TEAM, base * _MAX_ATTEMPT_MULTIPLIER))


def _remote_product_email_set(
    *, token: str, org_id: str, product_id: str, license_group_id: str,
    proxy_url: str, admin_email: str = "",
) -> set[str] | None:
    """读取远端产品组邮箱,用于避免本地历史重复号影响拉号目标计数。"""
    client = adobe_admin.client_from_state({"proxy": proxy_url})
    try:
        users = adobe_admin.list_product_users(
            client,
            token,
            org_id,
            product_id,
            license_group_id,
            pages=3,
            page_size=100,
        )
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass
    admin_norm = str(admin_email or "").strip().lower()
    emails = {
        str(item.get("email") or "").strip().lower()
        for item in users
        if str(item.get("email") or "").strip()
    }
    if admin_norm:
        emails.discard(admin_norm)
    return emails


def _registered_count_for_admin(
    db, admin_id: int, remote_product_emails: set[str] | None
) -> int:
    if remote_product_emails is None:
        return member_crud.count_registered(db, admin_id)
    if not remote_product_emails:
        return 0
    existing_rows, _ = member_crud.list_by_admin(db, admin_id, page=1, size=1000)
    return sum(
        1
        for row in existing_rows
        if row.registered
        and str(row.email or "").strip().lower() in remote_product_emails
    )


def _register_one(
    *, token: str, org_id: str, product_id: str, lgid: str, proxy_url: str,
    email: str, refresh_token: str, client_id: str, job: Job, prefix: str = "",
    extra_products: list[tuple[str, str]] | None = None,
) -> tuple[bool, dict, str]:
    """对单个邮箱执行:授权 + 注册。返回 (是否成功, newbanana记录, 失败原因)。"""
    job.log(f"{prefix}[{email}] 邀请 + 分配产品(授权)…")
    g = adobe_admin.grant_member(
        token=token, org_id=org_id, product_id=product_id,
        license_group_id=lgid, email=email, proxy_url=proxy_url,
        extra_products=extra_products or [],
    )
    if not g.get("ok"):
        if g.get("error_code") in {"trial_already_consumed", "assign_product_failed"}:
            try:
                adobe_admin.remove_member(
                    token=token,
                    org_id=org_id,
                    member_id=g.get("member_id", ""),
                    email=email,
                    proxy_url=proxy_url,
                )
            except Exception:
                pass
        return (
            False,
            {"error_code": g.get("error_code") or ""},
            f"授权失败:{g.get('message') or ''}"[:480],
        )

    job.log(f"{prefix}[{email}] 授权成功,子号登录注册中(收验证码,最长约 3 分钟)…")
    sub_logs: list[str] = []

    def _sub_log(message: str) -> None:
        sub_logs.append(str(message or ""))
        job.log(f"{prefix}[{email}] {message}")

    try:
        rec = firefly.register_account(
            email=email, refresh_token=refresh_token, client_id=client_id,
            proxy_url=proxy_url, otp_timeout=180,
            log=_sub_log,
        )
    except Exception as e:  # noqa: BLE001
        # 失败:把刚加入的成员从组织移除(失败的删除),以便换号重拉
        try:
            adobe_admin.remove_member(
                token=token, org_id=org_id, email=email, proxy_url=proxy_url
            )
        except Exception:
            pass
        detail = str(e)[:220]
        if "429" not in detail and any(_is_rate_limited(x) for x in sub_logs):
            detail = f"{detail} (检测到 Adobe 429 限流)"
        return (
            False,
            {"error_code": "registration_failed_after_grant"},
            f"注册失败:{detail}",
        )

    rec["member_id"] = g.get("member_id", "")
    credits = rec.get("credits")
    if rec.get("needs_authorization") or not firefly.has_team_credits(credits):
        rec["error_code"] = "needs_authorization"
        msg = rec.get("credit_message") or "子号已加入组织,但 Firefly 额度不可用"
        if credits is not None:
            msg = f"额度 {credits} 低于团队可用阈值,可能只有个人免费额度"
        try:
            adobe_admin.remove_member(
                token=token,
                org_id=org_id,
                member_id=rec.get("member_id", ""),
                email=email,
                proxy_url=proxy_url,
            )
        except Exception:
            pass
        return (
            False,
            rec,
            (
                "未拿到团队积分,已自动移除远端成员并换号:"
                f"{msg}"
            )[:480],
        )
    return True, rec, ""


def _apply_login_result(account, res: dict) -> None:
    rotated = res.get("rotated_refresh_token") or ""
    if rotated and rotated != account.refresh_token:
        account.refresh_token = rotated
    account.admin_token = res.get("token") or ""
    account.admin_cookie = res.get("cookie") or ""
    account.org_id = res.get("org_id") or ""
    account.product_id = res.get("product_id") or ""
    account.product_name = res.get("product_name") or ""
    account.license_group_id = res.get("license_group_id") or ""
    account.has_org = bool(res.get("has_org"))
    account.is_valid = bool(res.get("has_org"))
    account.last_login_at = datetime.now(timezone.utc)
    account.last_checked_at = datetime.now(timezone.utc)


def _ensure_admin(db, account, proxy_raw: str, job: Job, prefix: str) -> bool:
    """确保主号已取得管理权限;缺失或失效时自动登录。返回是否可用。"""
    has_creds = bool(account.admin_token and account.org_id
                     and account.product_id and account.license_group_id)
    if has_creds:
        try:
            adobe_admin.check_admin(
                token=account.admin_token, org_id=account.org_id,
                proxy_url=proxy_pool.next_proxy(proxy_raw),
            )
            return True
        except Exception as e:  # noqa: BLE001
            job.log(f"{prefix}管理 token 已失效,尝试重新登录:{str(e)[:120]}")

    if not (account.refresh_token and account.client_id):
        job.log(f"{prefix}✗ 缺少 Refresh Token / Client ID,无法自动登录,跳过")
        return False

    job.log(f"{prefix}自动登录获取管理权限 …")
    try:
        res = adobe_admin.login_account(
            email=account.email, adobe_password=account.adobe_password,
            refresh_token=account.refresh_token, client_id=account.client_id,
            proxy_url=proxy_pool.next_proxy(proxy_raw), otp_timeout=180,
            log=lambda m: job.log(f"{prefix}{m}"),
        )
    except Exception as e:  # noqa: BLE001
        account.is_valid = False
        account.check_message = str(e)[:500]
        db.commit()
        job.log(f"{prefix}✗ 登录失败:{str(e)[:160]}")
        return False

    _apply_login_result(account, res)
    db.commit()
    if not account.has_org:
        job.log(f"{prefix}✗ 登录成功但未发现可用组织/产品,跳过")
        return False
    job.log(f"{prefix}✓ 已获取管理权限,授权产品:{account.product_name or account.product_id}")
    return True


def _build_one_team(
    db, job: Job, account, count: int, proxy_raw: str, concurrency: int, team: dict,
    mode: str = "fill",
) -> None:
    """为单个主号凑满 count 个已注册子号,进度写入 team(并累加到 job)。"""
    admin_id = account.id
    prefix = team.get("prefix", "")

    token = account.admin_token
    org_id = account.org_id
    product_id = account.product_id
    lgid = account.license_group_id
    extra_products = adobe_admin.find_complimentary_products(
        token=token,
        org_id=org_id,
        product_id=product_id,
        license_group_id=lgid,
        proxy_url=proxy_pool.next_proxy(proxy_raw),
        log=lambda m: job.log(f"{prefix}{m}"),
    )

    remote_product_emails = _remote_product_email_set(
        token=token,
        org_id=org_id,
        product_id=product_id,
        license_group_id=lgid,
        proxy_url=proxy_pool.next_proxy(proxy_raw),
        admin_email=account.email,
    )
    if remote_product_emails is not None:
        registered_now = _registered_count_for_admin(db, admin_id, remote_product_emails)
        local_registered = member_crud.count_registered(db, admin_id)
        if registered_now != local_registered:
            job.log(
                f"{prefix}按 Adobe 产品组校准已注册数:"
                f"本地 {local_registered} → 远端匹配 {registered_now}"
            )
    else:
        job.log(f"{prefix}读取 Adobe 产品组成员失败,暂按本地已注册数计算")
        registered_now = member_crud.count_registered(db, admin_id)
    team["success"] = registered_now
    job.bump(success=registered_now)
    if mode == "one_by_one" and registered_now < count:
        original_count = count
        count = registered_now + 1
        team["target"] = count
        job.target = count
        job.log(
            f"{prefix}安全补号模式:本轮只补 1 个成功子号,"
            f"总目标从 {original_count} 临时收敛为 {count}"
        )
    remaining = count - registered_now
    job.log(f"{prefix}目标 {count} · 已注册 {registered_now} · 还需 {remaining}")
    if remaining <= 0:
        team["status"] = "done"
        team["message"] = "已满足目标"
        return

    try:
        availability = adobe_admin.get_product_license_availability(
            token=token,
            org_id=org_id,
            product_id=product_id,
            proxy_url=proxy_pool.next_proxy(proxy_raw),
        )
    except Exception as exc:  # noqa: BLE001
        availability = {}
        job.log(f"{prefix}读取远端授权余量失败,继续按原流程拉号:{str(exc)[:160]}")
    if availability.get("found"):
        available = int(availability.get("available") or 0)
        job.log(
            f"{prefix}远端授权余量:{availability.get('assigned')}/"
            f"{availability.get('total')} 已用,可用 {available}"
        )
        if available <= 0:
            team["status"] = "partial"
            team["message"] = "Creative Cloud Pro 授权许可数量已满"
            job.log(
                f"{prefix}⚠ Adobe 产品授权汇总显示许可已满,停止拉号;"
                "如果后台成员列表人数更少,通常是 Adobe 释放席位延迟或隐藏占用"
            )
            return
        if available < remaining:
            remaining = available
            team["message"] = f"远端仅剩 {available} 个可用授权许可"
            job.log(f"{prefix}⚠ 远端可用授权不足,本次最多再拉 {available} 个")

    existing, _ = member_crud.list_by_admin(db, admin_id, page=1, size=1000)
    attempted: set[str] = {m.email.lower() for m in existing}
    attempted.update(remote_product_emails or set())
    attempted_count = 0
    consecutive_rate_limited = 0
    max_attempts = _max_attempts_for_target(count, remaining)
    safe_concurrency = max(1, min(concurrency, _BUILD_CONCURRENCY_CAP))
    job.log(
        f"{prefix}安全拉号策略:并发 {safe_concurrency},最多尝试 {max_attempts} 个邮箱,"
        f"检测到 1 次 429 立即自动停止;可随时点停止拉号"
    )

    while remaining > 0 and not job.cancelled and attempted_count < max_attempts:
        batch_size = max(1, min(safe_concurrency, remaining, max_attempts - attempted_count))
        rows = pool_claim.claim(db, batch_size, extra_exclude=attempted)
        if not rows:
            job.log(f"{prefix}⚠ 邮箱池已无可用未使用邮箱,提前结束")
            team["message"] = "邮箱池不足"
            break

        claimed_emails = [r.email for r in rows]
        for r in rows:
            attempted.add(r.email.lower())
        payloads = [
            {"email": r.email, "refresh_token": r.refresh_token,
             "client_id": r.client_id}
            for r in rows
        ]
        attempted_count += len(payloads)

        try:
            job.log(f"{prefix}本批拉取 {len(payloads)} 个(并发 {len(payloads)},尝试 {attempted_count}/{max_attempts})…")

            def _do(p: dict) -> tuple[dict, tuple[bool, dict, str]]:
                return p, _register_one(
                    token=token, org_id=org_id, product_id=product_id, lgid=lgid,
                    proxy_url=proxy_pool.next_proxy(proxy_raw), email=p["email"],
                    refresh_token=p["refresh_token"], client_id=p["client_id"],
                    job=job, prefix=prefix, extra_products=extra_products,
                )

            results: list[tuple[dict, tuple[bool, dict, str]]] = []
            with ThreadPoolExecutor(max_workers=len(payloads)) as ex:
                for res in ex.map(_do, payloads):
                    results.append(res)
        finally:
            pool_claim.release(claimed_emails)

        stop_reason = ""
        for p, (ok, rec, msg) in results:
            email = p["email"]
            rate_limited = _is_rate_limited(msg, rec)
            if ok:
                consecutive_rate_limited = 0
                email_crud.mark_used_by_email(db, email, account.email)
                extra = {
                    "registered": True,
                    "display_name": rec.get("display_name") or "",
                    "cookie": rec.get("cookie") or "",
                    "access_token": rec.get("access_token") or "",
                    "device_token": rec.get("device_token") or "",
                    "device_id": rec.get("device_id") or "",
                    "credits": rec.get("credits"),
                    "expires_at": rec.get("expires_at"),
                    "refresh_token": rec.get("rotated_refresh_token")
                    or p["refresh_token"],
                    "client_id": p["client_id"],
                }
                member_crud.upsert(
                    db, admin_id, email=email, member_id=rec.get("member_id", ""),
                    status="registered", message="已注册可用", extra=extra,
                )
                job.bump(success=1)
                team["success"] = team.get("success", 0) + 1
                if remote_product_emails is not None:
                    remote_product_emails.add(email.lower())
                remaining -= 1
                job.log(f"{prefix}✓ [{email}] 注册成功(额度 {rec.get('credits')})")
            elif rec.get("error_code") == "needs_authorization":
                email_crud.disable_by_emails(
                    db,
                    [email],
                    remark=f"{account.email}:未拿到团队积分",
                )
                extra = {
                    "registered": False,
                    "display_name": rec.get("display_name") or "",
                    "cookie": "",
                    "access_token": "",
                    "device_token": rec.get("device_token") or "",
                    "device_id": rec.get("device_id") or "",
                    "credits": rec.get("credits"),
                    "expires_at": rec.get("expires_at"),
                    "refresh_token": rec.get("rotated_refresh_token")
                    or p["refresh_token"],
                    "client_id": p["client_id"],
                }
                member_crud.upsert(
                    db, admin_id, email=email, member_id="",
                    status="removed_no_credits", message=msg, extra=extra,
                )
                job.bump(fail=1)
                team["fail"] = team.get("fail", 0) + 1
                job.log(f"{prefix}⚠ [{email}] {msg}")
                if rate_limited:
                    consecutive_rate_limited += 1
                    guidance = _rate_limit_guidance(consecutive_rate_limited)
                    team["message"] = guidance
                    job.log(f"{prefix}⚠ {guidance} ({consecutive_rate_limited}/{_MAX_CONSECUTIVE_RATE_LIMITS})")
                    if consecutive_rate_limited >= _MAX_CONSECUTIVE_RATE_LIMITS:
                        stop_reason = guidance
                else:
                    consecutive_rate_limited = 0
            else:
                if rec.get("error_code") == "trial_already_consumed":
                    email_crud.disable_by_emails(
                        db,
                        [email],
                        remark=f"{account.email}:免费会员资格已消耗",
                    )
                    job.log(f"{prefix}⚠ [{email}] 免费会员资格已消耗,已自动停用该邮箱")
                elif rec.get("error_code") == "registration_failed_after_grant":
                    email_crud.disable_by_emails(
                        db,
                        [email],
                        remark=f"{account.email}:注册失败已触碰 Adobe",
                    )
                    member_crud.upsert(
                        db,
                        admin_id,
                        email=email,
                        status="removed_register_failed",
                        message=msg,
                        extra={
                            "registered": False,
                            "refresh_token": p["refresh_token"],
                            "client_id": p["client_id"],
                        },
                    )
                    job.log(f"{prefix}⚠ [{email}] 注册失败,已自动停用该邮箱并换号")
                elif rec.get("error_code") == "license_exhausted":
                    email_crud.mark_unused_by_email(db, email)
                else:
                    email_crud.disable_by_emails(
                        db,
                        [email],
                        remark=f"{account.email}:拉号失败",
                    )
                    member_crud.upsert(
                        db,
                        admin_id,
                        email=email,
                        status="failed_disabled",
                        message=msg,
                        extra={
                            "registered": False,
                            "refresh_token": p["refresh_token"],
                            "client_id": p["client_id"],
                        },
                    )
                    job.log(f"{prefix}⚠ [{email}] 拉号失败,已自动停用该邮箱")
                job.bump(fail=1)
                team["fail"] = team.get("fail", 0) + 1
                job.log(f"{prefix}✗ [{email}] {msg}")
                if rate_limited:
                    consecutive_rate_limited += 1
                    guidance = _rate_limit_guidance(consecutive_rate_limited)
                    team["message"] = guidance
                    job.log(f"{prefix}⚠ {guidance} ({consecutive_rate_limited}/{_MAX_CONSECUTIVE_RATE_LIMITS})")
                    if consecutive_rate_limited >= _MAX_CONSECUTIVE_RATE_LIMITS:
                        stop_reason = guidance
                else:
                    consecutive_rate_limited = 0
                if rec.get("error_code") == "license_exhausted":
                    stop_reason = "Creative Cloud Pro 授权许可数量已满"

        email_crud.reconcile_usage_by_emails(db, claimed_emails)
        account.member_count = member_crud.count_by_admin(db, admin_id)
        db.commit()

        if stop_reason:
            pending_authorization = int(team.get("pending_authorization") or 0)
            if pending_authorization:
                team["message"] = f"已有 {pending_authorization} 个子号待母号审批授权"
                job.log(
                    f"{prefix}⚠ 已有 {pending_authorization} 个子号待母号审批授权,"
                    "请审批后刷新额度;本轮已停止继续拉号"
                )
            else:
                team["message"] = stop_reason
                job.log(f"{prefix}⚠ {stop_reason},已停止继续拉号,避免继续消耗邮箱池")
            break

    if job.cancelled:
        team["message"] = team.get("message") or "已手动停止拉号"
        job.log(f"{prefix}已停止:不会再继续取新邮箱")
    elif remaining > 0 and attempted_count >= max_attempts:
        team["message"] = (
            f"已尝试 {attempted_count}/{max_attempts} 个邮箱仍未凑满,"
            "已停止以保护邮箱池;稍后可继续一键拉满"
        )
        job.log(f"{prefix}⚠ {team['message']}")

    regd = _registered_count_for_admin(db, admin_id, remote_product_emails)
    account.member_count = member_crud.count_by_admin(db, admin_id)
    db.commit()
    team["success"] = regd
    if job.cancelled:
        team["status"] = "cancelled"
        job.status = "cancelled"
    else:
        team["status"] = "done" if regd >= count else "partial"
    pending_authorization = int(team.get("pending_authorization") or 0)
    if pending_authorization:
        team["message"] = f"注册可用 {regd}/{count},待母号审批 {pending_authorization} 个"
    elif not team.get("message"):
        team["message"] = f"注册可用 {regd}/{count}"


def build_team_worker(job: Job) -> None:
    """单主号拉号。"""
    admin_id = int(job.meta.get("admin_id"))
    count = int(job.meta.get("count") or 9)
    mode = str(job.meta.get("mode") or "fill")
    db = SessionLocal()
    try:
        account = adobe_crud.get(db, admin_id)
        if not account:
            job.status = "error"
            job.error = "母号不存在"
            return

        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        concurrency = max(1, min(int(settings.concurrency or 1), _BUILD_CONCURRENCY_CAP))
        n_proxy = proxy_pool.proxy_count(proxy_raw)
        if n_proxy:
            job.log(f"已配置 {n_proxy} 个代理,拉号时按行轮换出口")

        job.target = count
        team = {"admin_id": admin_id, "email": account.email, "target": count,
                "success": 0, "fail": 0, "status": "running", "message": "",
                "prefix": ""}
        job.set_extra("teams", [team])

        if not _ensure_admin(db, account, proxy_raw, job, ""):
            team["status"] = "error"
            team["message"] = account.check_message or "未取得管理权限"
            job.status = "error"
            job.error = team["message"]
            return

        _build_one_team(db, job, account, count, proxy_raw, concurrency, team, mode)
        job.set_extra("teams", [team])
        regd = member_crud.count_registered(db, admin_id)
        job.result = {"target": count, "registered_total": regd}
        job.log(f"=== 完成:当前注册可用 {regd}/{count} ===")
    finally:
        db.close()


def build_team_batch_worker(job: Job) -> None:
    """多主号批量拉号(按主号顺序处理,每号内子号并发)。"""
    admin_ids = [int(a) for a in (job.meta.get("admin_ids") or [])]
    count = int(job.meta.get("count") or 9)
    db = SessionLocal()
    try:
        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        concurrency = max(1, min(int(settings.concurrency or 1), _BUILD_CONCURRENCY_CAP))
        n_proxy = proxy_pool.proxy_count(proxy_raw)
        if n_proxy:
            job.log(f"已配置 {n_proxy} 个代理,拉号时按行轮换出口")

        job.target = count * len(admin_ids)
        teams: list[dict] = []
        for aid in admin_ids:
            acc = adobe_crud.get(db, aid)
            teams.append({
                "admin_id": aid,
                "email": acc.email if acc else f"#{aid}",
                "target": count, "success": 0, "fail": 0,
                "status": "pending", "message": "", "prefix": "",
            })
        job.set_extra("teams", teams)

        for idx, aid in enumerate(admin_ids, start=1):
            if job.cancelled:
                break
            team = teams[idx - 1]
            team["prefix"] = f"[{idx}/{len(admin_ids)} {team['email']}] "
            account = adobe_crud.get(db, aid)
            if not account:
                team["status"] = "error"
                team["message"] = "母号不存在"
                job.set_extra("teams", teams)
                continue

            team["status"] = "running"
            job.log(f"===== 开始处理母号 {team['email']} ({idx}/{len(admin_ids)}) =====")
            job.set_extra("teams", teams)
            try:
                if not _ensure_admin(db, account, proxy_raw, job, team["prefix"]):
                    team["status"] = "error"
                    team["message"] = account.check_message or "未取得管理权限,已跳过"
                    job.set_extra("teams", teams)
                    continue
                _build_one_team(db, job, account, count, proxy_raw, concurrency, team)
            except Exception as e:  # noqa: BLE001
                team["status"] = "error"
                team["message"] = str(e)[:200]
                job.log(f"{team['prefix']}✗ 异常:{str(e)[:200]}")
            job.set_extra("teams", teams)

        done = sum(1 for t in teams if t["status"] == "done")
        if job.cancelled:
            job.status = "cancelled"
            job.log("=== 批量拉号已手动停止 ===")
        job.result = {"teams": len(admin_ids), "fully_done": done}
        job.log(f"=== 批量完成:{done}/{len(admin_ids)} 个主号已凑满 ===")
    finally:
        db.close()


def replace_member_worker(job: Job) -> None:
    """Remove a child by email, wait five seconds, then safely add one replacement."""
    email = str(job.meta.get("email") or "").strip().lower()
    db = SessionLocal()
    try:
        row = member_crud.find_child_by_email(db, email)
        if not row:
            job.status = "error"
            job.error = f"未找到子号:{email}"
            job.log(job.error)
            return

        account = adobe_crud.get(db, row.admin_id)
        if not account:
            job.status = "error"
            job.error = "子号对应的母号不存在"
            job.log(job.error)
            return

        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        concurrency = max(1, min(int(settings.concurrency or 1), _BUILD_CONCURRENCY_CAP))
        job.target = 1
        team = {
            "admin_id": account.id,
            "email": account.email,
            "target": 1,
            "success": 0,
            "fail": 0,
            "status": "running",
            "message": "",
            "prefix": "",
        }
        job.set_extra("teams", [team])
        job.log(f"已找到子号 [{email}],母号 [{account.email}]")

        try:
            result = member_removal.remove_members(
                db,
                account,
                [row],
                proxy_raw,
                log=job.log,
            )
        except member_removal.MemberRemovalError as exc:
            team["status"] = "error"
            team["message"] = str(exc)
            job.status = "error"
            job.error = str(exc)
            job.log(f"✗ {exc}")
            job.set_extra("teams", [team])
            return

        if int(result.get("removed") or 0) != 1:
            team["status"] = "error"
            team["message"] = str(result.get("message") or "移除失败")
            job.status = "error"
            job.error = team["message"]
            job.set_extra("teams", [team])
            return

        if job.cancelled:
            team["status"] = "cancelled"
            team["message"] = "已移除,但在等待补号前停止"
            job.status = "cancelled"
            job.log("已停止:不会继续安全补号")
            job.set_extra("teams", [team])
            return

        job.log("移除完成,等待 5 秒后开始安全补号")
        for remaining in range(5, 0, -1):
            if job.cancelled:
                team["status"] = "cancelled"
                team["message"] = "已移除,但在等待补号前停止"
                job.status = "cancelled"
                job.log("已停止:不会继续安全补号")
                job.set_extra("teams", [team])
                return
            job.log(f"等待 {remaining} 秒 …")
            time.sleep(1)

        if job.cancelled:
            team["status"] = "cancelled"
            team["message"] = "已移除,但在补号前停止"
            job.status = "cancelled"
            job.set_extra("teams", [team])
            return

        if not _ensure_admin(db, account, proxy_raw, job, ""):
            team["status"] = "error"
            team["message"] = account.check_message or "未取得管理权限"
            job.status = "error"
            job.error = team["message"]
            job.set_extra("teams", [team])
            return

        # The one-by-one mode uses the current registered count as its baseline.
        # Adding one to that baseline restores exactly the removed slot.
        safe_target = max(1, member_crud.count_registered(db, account.id) + 1)
        before_member_ids = {
            member.id
            for member in member_crud.list_by_admin(db, account.id, page=1, size=1000)[0]
        }
        job.log(f"开始安全补号:目标 {safe_target},本轮只补 1 个成功子号")
        _build_one_team(
            db,
            job,
            account,
            safe_target,
            proxy_raw,
            concurrency,
            team,
            mode="one_by_one",
        )
        job.set_extra("teams", [team])
        after_members, _ = member_crud.list_by_admin(
            db, account.id, page=1, size=1000
        )
        replacement_member = next(
            (
                member
                for member in reversed(after_members)
                if member.id not in before_member_ids
                and member.registered
                and str(member.cookie or "").strip()
            ),
            None,
        )
        replacement_cookie = str(replacement_member.cookie or "").strip() if replacement_member else ""
        job.result = {
            "email": email,
            "admin_id": account.id,
            "replacement_target": safe_target,
            "replacement": {
                "email": replacement_member.email if replacement_member else "",
                "cookie": replacement_cookie,
            },
        }
        job.log("=== 子号移除并安全补号流程完成 ===")
        if replacement_cookie:
            job.log(
                f"=== 新补子号 Cookie [{replacement_member.email}] (可复制) ==="
            )
            job.log(replacement_cookie)
        else:
            job.log("=== 新补子号未返回 Cookie,请到成员列表查看该子号详情 ===")
    finally:
        db.close()
