"""号池批量登录:对已注册子号重新执行协议登录,刷新 access_token / cookie / 额度。

复用 firefly.register_account(纯 API 协议登录:Graph 收验证码 → Adobe IMS 换 token),
每个子号用自己库里存的 refresh_token + client_id 收码,互不影响。并发数取「设置」。
"""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.crud import adobe_member as member_crud
from app.crud import email as email_crud
from app.crud import setting as setting_crud
from app.db.session import SessionLocal
from app.services import firefly, firefly_ios, proxy_pool
from app.services.job_manager import Job


COOKIE_REFRESH_REQUIRED = frozenset({"ims_sid", "aux_sid", "fg"})


def cookie_refresh_ready(cookie: str) -> bool:
    names = {
        part.split("=", 1)[0].strip()
        for part in str(cookie or "").split(";")
        if "=" in part
    }
    return COOKIE_REFRESH_REQUIRED.issubset(names)


def _refreshable_cookie_or_existing(new_cookie: str, existing_cookie: str) -> str:
    return new_cookie if cookie_refresh_ready(new_cookie) else existing_cookie


def _login_one(payload: dict, proxy_raw: str, job: Job) -> bool:
    email = payload["email"]
    mid = payload["id"]
    if not ((payload["refresh_token"] and payload["client_id"]) or payload.get("mail_url")):
        job.bump(fail=1)
        job.log(f"✗ [{email}] 缺少 Refresh Token / Client ID 或取信配置,跳过")
        _save(mid, status="failed", message="缺少子号 Refresh Token / Client ID 或取信配置")
        return False

    job.log(f"[{email}] FF-iOS 协议登录中(验证码登录→换设备 token,免密码)…")
    try:
        proxy_url = proxy_pool.next_proxy(proxy_raw)
        rec = firefly_ios.login_pool_ff_ios(
            email=email,
            refresh_token=payload["refresh_token"],
            client_id=payload["client_id"],
            mail_url=payload.get("mail_url", ""),
            device_id=payload.get("device_id", ""),
            proxy_url=proxy_url,
            otp_timeout=180,
            use_proxy_for_mail=bool(proxy_url),
            log=lambda m: job.log(f"[{email}] {m}"),
        )
    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {str(e)[:200]}"
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__, limit=6))
        err_text = str(e)
        if "access_denied" in err_text or "authorization code" in err_text:
            job.bump(fail=1)
            job.log(f"⚠ [{email}] 登录成功但 Firefly 未授权:{detail}")
            job.log(f"[{email}] 异常堆栈摘要:\n{tb[-1200:]}")
            _save(
                mid,
                status="needs_authorization",
                message=f"待母号审批授权:{str(e)[:220]}",
                extra={"registered": False},
            )
            return False
        job.bump(fail=1)
        job.log(f"✗ [{email}] 登录失败:{detail}")
        job.log(f"[{email}] 异常堆栈摘要:\n{tb[-1200:]}")
        _save(mid, status="failed", message=f"登录失败:{str(e)[:200]}")
        return False

    access_token = rec.get("access_token") or ""
    proxy_url = proxy_pool.next_proxy(proxy_raw)
    detail = (
        firefly.fetch_credits_detail(
            access_token,
            proxy_url=proxy_url,
            log=lambda m: job.log(f"[{email}] {m}"),
        )
        if access_token
        else {"ok": False, "credits": None, "message": "未获取 access_token"}
    )
    credits = detail.get("credits")
    if not detail.get("ok") or not firefly.has_team_credits(credits):
        msg = detail.get("message") or "额度为空/过低,可能未完成母号审批或只有个人免费额度"
        if credits is not None:
            msg = f"额度 {credits} 低于团队可用阈值,可能只有个人免费额度"
        _save(
            mid,
            status="needs_authorization",
            message=f"待母号审批授权:{msg}"[:500],
            extra={
                "registered": False,
                "display_name": rec.get("display_name") or "",
                "cookie": _refreshable_cookie_or_existing(
                    rec.get("cookie") or "", payload.get("cookie") or ""
                ),
                "access_token": access_token,
                "device_token": rec.get("device_token") or "",
                "device_id": rec.get("device_id") or "",
                "credits": credits,
                "expires_at": rec.get("expires_at"),
                "refresh_token": rec.get("rotated_refresh_token") or payload["refresh_token"],
            },
        )
        job.bump(fail=1)
        job.log(f"⚠ [{email}] 登录成功但额度不可用,待母号审批授权(额度 {credits})")
        return False
    _save(
        mid,
        status="registered",
        message="已获取 FF-iOS 受信任 token",
        extra={
            "registered": True,
            "display_name": rec.get("display_name") or "",
            "cookie": _refreshable_cookie_or_existing(
                rec.get("cookie") or "", payload.get("cookie") or ""
            ),
            "access_token": access_token,
            "device_token": rec.get("device_token") or "",
            "device_id": rec.get("device_id") or "",
            "credits": credits,
            "expires_at": rec.get("expires_at"),
            "refresh_token": rec.get("rotated_refresh_token") or payload["refresh_token"],
        },
    )
    job.bump(success=1)
    job.log(f"✓ [{email}] 登录成功,已获取 FF-iOS token(额度 {credits})")
    return True


def _save(member_id: int, *, status: str, message: str, extra: dict | None = None) -> None:
    """单独开一个 Session 落库(并发线程各用各的连接)。"""
    db = SessionLocal()
    try:
        row = member_crud.get(db, member_id)
        if not row:
            return
        row.status = status
        row.message = message
        row.updated_at = datetime.now(timezone.utc)
        for k, v in (extra or {}).items():
            setattr(row, k, v)
        db.commit()
    finally:
        db.close()


def _resolve_creds(db, member) -> tuple[str, str, str]:
    """解析子号收码凭据:成员行优先,缺失则回退邮箱池并回填。"""
    rt = member.refresh_token or ""
    cid = member.client_id or ""
    mail_url = member.mail_url or ""
    if not (rt and cid):
        pool_email = email_crud.get_by_email(db, member.email)
        if pool_email:
            rt = rt or (pool_email.refresh_token or "")
            cid = cid or (pool_email.client_id or "")
            mail_url = mail_url or (pool_email.mail_url or "")
            if rt and cid and not (member.refresh_token and member.client_id):
                member.refresh_token = rt
                member.client_id = cid
                member.mail_url = mail_url
                db.commit()
    return rt, cid, mail_url


def _build_payloads(db, member_ids: list[int]) -> list[dict]:
    members = member_crud.get_many(db, member_ids)
    payloads = []
    for m in members:
        rt, cid, mail_url = _resolve_creds(db, m)
        payloads.append(
            {
                "id": m.id,
                "email": m.email,
                "refresh_token": rt,
                "client_id": cid,
                "mail_url": mail_url,
                "device_id": m.device_id or "",
                "cookie": m.cookie or "",
            }
        )
    db.commit()
    return payloads


def _ids_without_token(member_ids: list[int]) -> list[int]:
    db = SessionLocal()
    try:
        members = member_crud.get_many(db, member_ids)
        return [m.id for m in members if not (m.access_token or "").strip()]
    finally:
        db.close()


def _refresh_credits_one(payload: dict, proxy_raw: str, job: Job) -> bool:
    email = payload["email"]
    mid = payload["id"]
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        job.bump(fail=1)
        job.log(f"✗ [{email}] 没有 access_token,跳过")
        _save(mid, status="failed", message="没有 access_token,无法刷新额度")
        return False

    try:
        proxy_url = proxy_pool.next_proxy(proxy_raw)
        detail = firefly.fetch_credits_detail(
            access_token,
            proxy_url=proxy_url,
            log=lambda m: job.log(f"[{email}] {m}"),
        )
        credits = detail.get("credits")
    except Exception as e:  # noqa: BLE001
        job.bump(fail=1)
        job.log(f"✗ [{email}] 查询额度失败:{str(e)[:180]}")
        _save(mid, status="failed", message=f"查询额度失败:{str(e)[:200]}")
        return False

    if not detail.get("ok") or credits is None:
        job.bump(fail=1)
        msg = detail.get("message") or "额度查询返回为空"
        job.log(f"⚠ [{email}] 待母号审批授权:{msg}")
        _save(
            mid,
            status="needs_authorization",
            message=f"待母号审批授权:{msg}"[:500],
            extra={"registered": False, "credits": credits},
        )
        return False

    if not firefly.has_team_credits(credits):
        job.bump(fail=1)
        job.log(f"⚠ [{email}] 额度 {credits} 低于团队可用阈值,可能只有个人免费额度")
        _save(
            mid,
            status="needs_authorization",
            message=f"额度 {credits} 低于团队可用阈值,可能只有个人免费额度",
            extra={"registered": False, "credits": credits},
        )
        return False

    _save(
        mid,
        status="registered",
        message=f"已刷新额度:{credits}",
        extra={"registered": True, "credits": credits},
    )
    job.bump(success=1)
    job.log(f"✓ [{email}] 额度 {credits}")
    return True


def _build_credit_payloads(db, member_ids: list[int]) -> list[dict]:
    members = member_crud.get_many(db, member_ids)
    payloads = []
    for m in members:
        payloads.append(
            {
                "id": m.id,
                "email": m.email,
                "access_token": m.access_token or "",
            }
        )
    return payloads


def pool_refresh_credits_batch_worker(job: Job) -> None:
    member_ids = [int(x) for x in (job.meta.get("member_ids") or [])]
    job.target = len(member_ids)
    if not member_ids:
        job.log("没有可刷新额度的账号")
        return

    db = SessionLocal()
    try:
        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        concurrency = max(1, int(settings.concurrency or 1))
        n_proxy = proxy_pool.proxy_count(proxy_raw)
        payloads = _build_credit_payloads(db, member_ids)
        if n_proxy:
            job.log(f"已配置 {n_proxy} 个代理,刷新额度时按行轮换出口")
    finally:
        db.close()

    if not payloads:
        job.log("没有找到账号")
        return

    job.log(f"开始批量刷新额度,共 {len(payloads)} 个,并发 {min(concurrency, len(payloads))}")

    def _do(p: dict) -> bool:
        if job.cancelled:
            return False
        return _refresh_credits_one(p, proxy_raw, job)

    with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as ex:
        for _ in ex.map(_do, payloads):
            pass

    job.result = {
        "total": len(payloads),
        "success": job.success,
        "fail": job.fail,
    }
    job.log(f"=== 完成:成功 {job.success} / 失败 {job.fail} ===")


def refresh_one_sync(member_id: int, log=None) -> dict:
    """对单个子号同步刷新 AT,刷新后查询额度。返回 {success,message,credits,expires_at}。

    优先用 device_token 免验证码刷新(快);无 device_token 或刷新失败时回退整登。
    """
    lf = log if callable(log) else (lambda _m: None)
    db = SessionLocal()
    try:
        m = member_crud.get(db, member_id)
        if not m:
            return {"success": False, "message": "条目不存在", "credits": None, "expires_at": None}
        email = m.email
        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        device_token = m.device_token or ""
        device_id = m.device_id or ""
        rt, cid, mail_url = _resolve_creds(db, m)
    finally:
        db.close()

    # 快路径:device_token 免验证码刷新 access_token
    if device_token and device_id:
        proxy_url = proxy_pool.next_proxy(proxy_raw)
        lf(f"[{email}] 用 device_token 刷新 AT(免验证码)…")
        try:
            rec = firefly_ios.refresh_with_device_token(
                device_token=device_token, device_id=device_id,
                proxy_url=proxy_url, log=lambda mm: lf(f"[{email}] {mm}"),
            )
            token = rec.get("access_token") or ""
            detail = (
                firefly.fetch_credits_detail(
                    token,
                    proxy_url=proxy_url,
                    log=lambda mm: lf(f"[{email}] {mm}"),
                )
                if token
                else {"ok": False, "credits": None, "message": "未获取 access_token"}
            )
            credits = detail.get("credits")
            if not detail.get("ok") or credits is None:
                msg = detail.get("message") or "额度查询返回为空"
                _save(
                    member_id,
                    status="needs_authorization",
                    message=f"待母号审批授权:{msg}"[:500],
                    extra={
                        "registered": False,
                        "access_token": token,
                        "credits": credits,
                        "expires_at": rec.get("expires_at"),
                        "device_token": rec.get("device_token") or device_token,
                    },
                )
                lf(f"[{email}] ⚠ device_token 已刷新,但额度不可用:{msg}")
                return {"success": False, "message": f"待母号审批授权:{msg}",
                        "credits": credits, "expires_at": rec.get("expires_at")}
            if not firefly.has_team_credits(credits):
                msg = f"额度 {credits} 低于团队可用阈值,可能只有个人免费额度"
                _save(
                    member_id,
                    status="needs_authorization",
                    message=msg,
                    extra={
                        "registered": False,
                        "access_token": token,
                        "credits": credits,
                        "expires_at": rec.get("expires_at"),
                        "device_token": rec.get("device_token") or device_token,
                    },
                )
                lf(f"[{email}] ⚠ {msg}")
                return {"success": False, "message": msg,
                        "credits": credits, "expires_at": rec.get("expires_at")}
            _save(
                member_id, status="registered", message="device_token 已刷新 AT",
                extra={
                    "registered": True,
                    "access_token": token,
                    "credits": credits,
                    "expires_at": rec.get("expires_at"),
                    "device_token": rec.get("device_token") or device_token,
                },
            )
            lf(f"[{email}] ✓ device_token 刷新成功,额度 {credits}")
            return {"success": True, "message": "device_token 已刷新 AT 并查询额度",
                    "credits": credits, "expires_at": rec.get("expires_at")}
        except Exception as e:  # noqa: BLE001
            lf(f"[{email}] device_token 刷新失败({str(e)[:120]}),回退整登")

    if not ((rt and cid) or mail_url):
        _save(member_id, status="failed", message="缺少子号 Refresh Token / Client ID 或取信配置")
        return {"success": False, "message": "缺少子号 Refresh Token / Client ID 或取信配置",
                "credits": None, "expires_at": None}

    proxy_url = proxy_pool.next_proxy(proxy_raw)
    lf(f"[{email}] FF-iOS 协议登录刷新(验证码登录→换设备 token)…")
    try:
        rec = firefly_ios.login_pool_ff_ios(
            email=email, refresh_token=rt, client_id=cid,
            mail_url=mail_url, device_id=device_id, proxy_url=proxy_url, otp_timeout=180,
            use_proxy_for_mail=bool(proxy_url),
            log=lambda mm: lf(f"[{email}] {mm}"),
        )
    except Exception as e:  # noqa: BLE001
        _save(member_id, status="failed", message=f"刷新失败:{str(e)[:200]}")
        return {"success": False, "message": f"刷新失败:{str(e)[:200]}",
                "credits": None, "expires_at": None}

    token = rec.get("access_token") or ""
    detail = (
        firefly.fetch_credits_detail(
            token,
            proxy_url=proxy_url,
            log=lambda mm: lf(f"[{email}] {mm}"),
        )
        if token
        else {"ok": False, "credits": None, "message": "未获取 access_token"}
    )
    credits = detail.get("credits")
    if token:
        lf(f"[{email}] 登录成功,查询额度 …")
    expires_at = rec.get("expires_at")
    if not detail.get("ok") or credits is None:
        msg = detail.get("message") or "额度查询返回为空"
        _save(
            member_id, status="needs_authorization",
            message=f"待母号审批授权:{msg}"[:500],
            extra={
                "registered": False,
                "display_name": rec.get("display_name") or "",
                "access_token": token,
                "device_token": rec.get("device_token") or "",
                "device_id": rec.get("device_id") or "",
                "credits": credits,
                "expires_at": expires_at,
                "refresh_token": rec.get("rotated_refresh_token") or rt,
            },
        )
        lf(f"[{email}] ⚠ 登录成功但额度不可用:{msg}")
        return {"success": False, "message": f"待母号审批授权:{msg}",
                "credits": credits, "expires_at": expires_at}
    if not firefly.has_team_credits(credits):
        msg = f"额度 {credits} 低于团队可用阈值,可能只有个人免费额度"
        _save(
            member_id, status="needs_authorization",
            message=msg,
            extra={
                "registered": False,
                "display_name": rec.get("display_name") or "",
                "access_token": token,
                "device_token": rec.get("device_token") or "",
                "device_id": rec.get("device_id") or "",
                "credits": credits,
                "expires_at": expires_at,
                "refresh_token": rec.get("rotated_refresh_token") or rt,
            },
        )
        lf(f"[{email}] ⚠ {msg}")
        return {"success": False, "message": msg,
                "credits": credits, "expires_at": expires_at}
    _save(
        member_id, status="registered", message="已获取 FF-iOS 受信任 token",
        extra={
            "registered": True,
            "display_name": rec.get("display_name") or "",
            "access_token": token,
            "device_token": rec.get("device_token") or "",
            "device_id": rec.get("device_id") or "",
            "credits": credits,
            "expires_at": expires_at,
            "refresh_token": rec.get("rotated_refresh_token") or rt,
        },
    )
    lf(f"[{email}] ✓ 已获取 FF-iOS token,额度 {credits}")
    return {"success": True, "message": "已获取 FF-iOS 受信任 token 并查询额度",
            "credits": credits, "expires_at": expires_at}


def refresh_cookie_sync(member_id: int, log=None) -> dict:
    lf = log if callable(log) else (lambda _m: None)
    db = SessionLocal()
    try:
        member = member_crud.get(db, member_id)
        if not member:
            return {
                "success": False,
                "message": "条目不存在",
                "cookie_refresh_ready": False,
            }
        email = member.email
        current_status = member.status or ("registered" if member.registered else "")
        current_cookie = member.cookie or ""
        device_id = member.device_id or ""
        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        refresh_token, client_id, mail_url = _resolve_creds(db, member)
    finally:
        db.close()

    if not ((refresh_token and client_id) or mail_url):
        return {
            "success": False,
            "message": "缺少子号 Refresh Token / Client ID 或取信配置",
            "cookie_refresh_ready": cookie_refresh_ready(current_cookie),
        }

    proxy_url = proxy_pool.next_proxy(proxy_raw)
    lf(f"[{email}] 重新登录并建立 Firefly Web 会话 Cookie…")
    try:
        rec = firefly_ios.login_pool_ff_ios(
            email=email,
            refresh_token=refresh_token,
            client_id=client_id,
            mail_url=mail_url,
            device_id=device_id,
            proxy_url=proxy_url,
            otp_timeout=180,
            use_proxy_for_mail=bool(proxy_url),
            complete_profile=True,
            log=lambda message: lf(f"[{email}] {message}"),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "message": f"重新登录失败:{str(exc)[:200]}",
            "cookie_refresh_ready": cookie_refresh_ready(current_cookie),
        }

    cookie = rec.get("cookie") or ""
    ready = cookie_refresh_ready(cookie)
    extra = {
        "access_token": rec.get("access_token") or "",
        "device_token": rec.get("device_token") or "",
        "device_id": rec.get("device_id") or device_id,
        "expires_at": rec.get("expires_at"),
        "refresh_token": rec.get("rotated_refresh_token") or refresh_token,
    }
    if ready:
        extra["cookie"] = cookie
        _save(
            member_id,
            status=current_status,
            message="已重新获取可续期 Web Cookie",
            extra=extra,
        )
        return {
            "success": True,
            "message": "已重新获取可用于 adobe2api 续期的 Cookie",
            "cookie_refresh_ready": True,
        }

    _save(
        member_id,
        status=current_status,
        message="重新登录成功，但 Web Cookie 字段不完整",
        extra=extra,
    )
    missing = ", ".join(
        sorted(
            COOKIE_REFRESH_REQUIRED
            - {
                part.split("=", 1)[0].strip()
                for part in cookie.split(";")
                if "=" in part
            }
        )
    )
    return {
        "success": False,
        "message": f"Web Cookie 字段不完整，缺少:{missing}",
        "cookie_refresh_ready": cookie_refresh_ready(current_cookie),
    }


def _run_round(payloads: list[dict], proxy_raw: str, concurrency: int, job: Job) -> None:
    def _do(p: dict) -> bool:
        if job.cancelled:
            return False
        return _login_one(p, proxy_raw, job)

    with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as ex:
        for _ in ex.map(_do, payloads):
            pass


def pool_login_batch_worker(job: Job) -> None:
    all_member_ids = [int(x) for x in (job.meta.get("member_ids") or [])]
    auto_retry = bool(job.meta.get("auto_retry", True))
    max_retries = max(0, int(job.meta.get("max_retries") if job.meta.get("max_retries") is not None else 2))

    db = SessionLocal()
    try:
        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        concurrency = max(1, int(settings.concurrency or 1))
        n_proxy = proxy_pool.proxy_count(proxy_raw)
        if n_proxy:
            job.log(f"已配置 {n_proxy} 个代理,登录时按行轮换出口")
    finally:
        db.close()

    job.target = len(all_member_ids)
    if not all_member_ids:
        job.log("没有可登录的子号")
        return

    retry_hint = f",失败自动重试最多 {max_retries} 轮" if auto_retry and max_retries else ""
    job.log(
        f"开始批量协议登录,共 {len(all_member_ids)} 个,"
        f"并发 {min(concurrency, len(all_member_ids))}{retry_hint}"
    )

    pending_ids = list(all_member_ids)
    round_num = 0
    max_rounds = 1 + (max_retries if auto_retry else 0)

    while pending_ids and round_num < max_rounds:
        round_num += 1
        if round_num > 1:
            job.log(f"=== 第 {round_num} 轮重试,{len(pending_ids)} 个仍无 token,30s 后开始 ===")
            time.sleep(30)

        db = SessionLocal()
        try:
            payloads = _build_payloads(db, pending_ids)
        finally:
            db.close()

        if not payloads:
            break

        if round_num == 1:
            job.log(f"首轮 {len(payloads)} 个")
        _run_round(payloads, proxy_raw, concurrency, job)

        if job.cancelled:
            job.log("任务已取消")
            break

        pending_ids = _ids_without_token(all_member_ids)
        if not pending_ids:
            job.log("全部账号已拿到 token")
            break

    still = len(_ids_without_token(all_member_ids))
    job.result = {
        "total": len(all_member_ids),
        "success": job.success,
        "fail": job.fail,
        "still_no_token": still,
    }
    job.log(f"=== 完成:成功 {job.success} / 失败 {job.fail} / 仍无 token {still} ===")
