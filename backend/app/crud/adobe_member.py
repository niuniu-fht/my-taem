import base64
import json
from urllib.parse import unquote
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.adobe_account import AdobeAccount
from app.models.adobe_member import AdobeMember


def list_by_admin(
    db: Session, admin_id: int, *, page: int = 1, size: int = 50, keyword: str = ""
) -> tuple[list[AdobeMember], int]:
    # 子号列表不含母号自身镜像行
    stmt = select(AdobeMember).where(
        AdobeMember.admin_id == admin_id, AdobeMember.is_admin == False  # noqa: E712
    )
    if keyword:
        stmt = stmt.where(AdobeMember.email.like(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.scalars(
            stmt.order_by(AdobeMember.id.desc()).offset((page - 1) * size).limit(size)
        )
    )
    return items, total


def count_by_admin(db: Session, admin_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AdobeMember)
        .where(
            AdobeMember.admin_id == admin_id,
            AdobeMember.is_admin == False,  # noqa: E712
        )
    ) or 0


def get(db: Session, member_id: int) -> AdobeMember | None:
    return db.get(AdobeMember, member_id)


def get_by_email(db: Session, admin_id: int, email: str) -> AdobeMember | None:
    return db.scalar(
        select(AdobeMember).where(
            AdobeMember.admin_id == admin_id, AdobeMember.email == email
        )
    )


def find_child_by_email(db: Session, email: str) -> AdobeMember | None:
    """Find a non-admin child account and thereby identify its mother account."""
    normalized = str(email or "").strip().lower()
    if not normalized:
        return None
    return db.scalar(
        select(AdobeMember)
        .where(func.lower(AdobeMember.email) == normalized)
        .where(AdobeMember.admin_id > 0)
        .where(AdobeMember.is_admin == False)  # noqa: E712
        .order_by(AdobeMember.updated_at.desc(), AdobeMember.id.desc())
        .limit(1)
    )


def email_exists_any(db: Session, email: str) -> bool:
    normalized = str(email or "").strip().lower()
    if not normalized:
        return False
    return bool(
        db.scalar(
            select(AdobeMember.id)
            .where(func.lower(AdobeMember.email) == normalized)
            .where(
                or_(
                    AdobeMember.registered == True,  # noqa: E712
                    AdobeMember.is_admin == True,  # noqa: E712
                    AdobeMember.is_imported == True,  # noqa: E712
                    AdobeMember.member_id != "",
                    AdobeMember.access_token != "",
                    AdobeMember.cookie != "",
                )
            )
            .limit(1)
        )
    )


def used_email_set(db: Session) -> set[str]:
    return {
        str(email or "").strip().lower()
        for email in db.scalars(
            select(AdobeMember.email).where(
                or_(
                    AdobeMember.registered == True,  # noqa: E712
                    AdobeMember.is_admin == True,  # noqa: E712
                    AdobeMember.is_imported == True,  # noqa: E712
                    AdobeMember.member_id != "",
                    AdobeMember.access_token != "",
                    AdobeMember.cookie != "",
                )
            )
        )
        if str(email or "").strip()
    }


def count_registered(db: Session, admin_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AdobeMember)
        .where(
            AdobeMember.admin_id == admin_id,
            AdobeMember.registered == True,  # noqa: E712
            AdobeMember.is_admin == False,  # noqa: E712
        )
    ) or 0


def upsert(
    db: Session,
    admin_id: int,
    *,
    email: str,
    member_id: str = "",
    status: str = "",
    message: str = "",
    extra: dict | None = None,
) -> AdobeMember:
    """新增或更新成员。extra 可携带 newbanana 字段(cookie/access_token/credits 等)。"""
    row = get_by_email(db, admin_id, email)
    if row:
        if member_id:
            row.member_id = member_id
        row.status = status or row.status
        row.message = message
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = AdobeMember(
            admin_id=admin_id,
            email=email,
            member_id=member_id,
            status=status,
            message=message,
        )
        db.add(row)
    for key, value in (extra or {}).items():
        setattr(row, key, value)
    return row


def sync_remote_members(
    db: Session,
    admin_id: int,
    members: list[dict[str, Any]],
    admin_email: str = "",
    *,
    allow_prune: bool = True,
) -> dict[str, int]:
    """把 Adobe 远端成员同步到本地,便于在项目里统一查看/移除。

    只补齐远端成员身份,不覆盖已有子号的 token/cookie/额度等可导出数据。
    """
    created = 0
    updated = 0
    skipped = 0
    pruned = 0
    admin_email_norm = str(admin_email or "").strip().lower()
    remote_emails: set[str] = set()
    now = datetime.now(timezone.utc)
    for item in members:
        email = str(item.get("email") or "").strip().lower()
        if not email or "@" not in email:
            skipped += 1
            continue
        if admin_email_norm and email == admin_email_norm:
            skipped += 1
            continue
        remote_emails.add(email)

        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        display_name = ""
        profile = raw.get("profile") if isinstance(raw, dict) else {}
        user = raw.get("user") if isinstance(raw, dict) else {}
        for obj in (raw, profile if isinstance(profile, dict) else {}, user if isinstance(user, dict) else {}):
            first = str(obj.get("firstName") or obj.get("givenName") or "").strip()
            last = str(obj.get("lastName") or obj.get("familyName") or "").strip()
            display_name = " ".join(x for x in (first, last) if x).strip()
            if not display_name:
                display_name = str(obj.get("name") or obj.get("displayName") or "").strip()
            if display_name:
                break

        row = get_by_email(db, admin_id, email)
        if row is None:
            row = AdobeMember(
                admin_id=admin_id,
                email=email,
                member_id=str(item.get("member_id") or ""),
                status="member",
                message="从 Adobe 远端同步",
                display_name=display_name,
                registered=False,
            )
            db.add(row)
            created += 1
            continue

        if item.get("member_id"):
            row.member_id = str(item.get("member_id") or "")
        if display_name and not row.display_name:
            row.display_name = display_name
        if not (row.registered or row.access_token or row.cookie):
            row.status = "member"
            row.message = "从 Adobe 远端同步"
        row.updated_at = now
        updated += 1

    if allow_prune:
        stale_rows = list(
            db.scalars(
                select(AdobeMember).where(
                    AdobeMember.admin_id == admin_id,
                    AdobeMember.is_admin == False,  # noqa: E712
                    AdobeMember.is_imported == False,  # noqa: E712
                    AdobeMember.registered == False,  # noqa: E712
                    AdobeMember.access_token == "",
                    AdobeMember.cookie == "",
                    AdobeMember.status == "member",
                )
            )
        )
        for row in stale_rows:
            if str(row.email or "").strip().lower() not in remote_emails:
                db.delete(row)
                pruned += 1
    return {"created": created, "updated": updated, "skipped": skipped, "pruned": pruned}


def ensure_admin_self_rows(db: Session) -> None:
    """为每个母号(adobe_accounts)在号池里建立/同步一条镜像行(is_admin=True)。

    幂等:已存在则补齐缺失的收码凭据;不存在则创建。这样母号本身也能在
    号池里协议拉取「前端生成 token」(与管理控制台的 admin_token 不同)。
    """
    accounts = list(db.scalars(select(AdobeAccount)))
    account_ids = {acc.id for acc in accounts}
    account_email_by_id = {
        acc.id: str(acc.email or "").strip().lower()
        for acc in accounts
    }
    changed = False
    stale_admin_rows = list(
        db.scalars(
            select(AdobeMember).where(
                AdobeMember.is_admin == True,  # noqa: E712
            )
        )
    )
    for row in stale_admin_rows:
        expected_email = account_email_by_id.get(row.admin_id)
        current_email = str(row.email or "").strip().lower()
        if not expected_email or current_email != expected_email:
            db.delete(row)
            changed = True
    for acc in accounts:
        row = db.scalar(
            select(AdobeMember).where(
                AdobeMember.admin_id == acc.id,
                AdobeMember.email == acc.email,
            )
        )
        if row is None:
            row = AdobeMember(
                admin_id=acc.id,
                email=acc.email,
                is_admin=True,
                status="",
                message="母号(可协议拉取前端 token)",
                refresh_token=acc.refresh_token or "",
                client_id=acc.client_id or "",
            )
            db.add(row)
            changed = True
        else:
            # 已存在则标记为母号并补齐收码凭据
            if not row.is_admin:
                row.is_admin = True
                changed = True
            if not row.refresh_token and acc.refresh_token:
                row.refresh_token = acc.refresh_token
                changed = True
            if not row.client_id and acc.client_id:
                row.client_id = acc.client_id
                changed = True
    if changed:
        db.commit()


def _pool_base_stmt():
    return select(AdobeMember, AdobeAccount.email).outerjoin(
        AdobeAccount, AdobeAccount.id == AdobeMember.admin_id
    )


def _pool_filters(
    stmt,
    *,
    keyword: str = "",
    admin_id: int | None = None,
    registered_only: bool = True,
    pool_type: str = "",
    has_token: bool | None = None,
    credit_status: str = "",
    credit_value: float | None = None,
    status_filter: str = "",
):
    sf = (status_filter or "").strip().lower()
    if registered_only and sf != "needs_authorization":
        # 母号镜像行 / 导入账号始终展示(便于拉取);子号仅展示已注册可用的
        stmt = stmt.where(
            or_(
                AdobeMember.registered == True,  # noqa: E712
                AdobeMember.is_admin == True,  # noqa: E712
                AdobeMember.is_imported == True,  # noqa: E712
            )
        )
    pt = (pool_type or "").strip().lower()
    if pt == "imported":
        stmt = stmt.where(AdobeMember.is_imported == True)  # noqa: E712
    elif pt == "admin":
        stmt = stmt.where(AdobeMember.is_admin == True)  # noqa: E712
    elif pt == "sub":
        stmt = stmt.where(
            AdobeMember.is_admin == False,  # noqa: E712
            AdobeMember.is_imported == False,  # noqa: E712
        )
    if admin_id:
        stmt = stmt.where(AdobeMember.admin_id == admin_id)
    if has_token is True:
        stmt = stmt.where(AdobeMember.access_token != "")
    elif has_token is False:
        stmt = stmt.where(or_(AdobeMember.access_token == "", AdobeMember.access_token.is_(None)))
    cs = (credit_status or "").strip().lower()
    if cs == "unknown":
        stmt = stmt.where(
            AdobeMember.access_token != "",
            or_(AdobeMember.credits.is_(None), AdobeMember.credits < 0),
        )
    elif cs == "known":
        stmt = stmt.where(AdobeMember.credits.is_not(None), AdobeMember.credits >= 0)
    if credit_value is not None:
        # 额度通常是整数,这里用很小区间避免浮点存储导致等值比较漏掉。
        stmt = stmt.where(
            AdobeMember.credits.is_not(None),
            AdobeMember.credits >= credit_value - 0.0001,
            AdobeMember.credits <= credit_value + 0.0001,
        )
    if sf == "failed":
        stmt = stmt.where(AdobeMember.status == "failed")
    elif sf == "registered":
        stmt = stmt.where(AdobeMember.access_token != "")
    elif sf == "needs_authorization":
        stmt = stmt.where(AdobeMember.status == "needs_authorization")
    elif sf == "pending":
        stmt = stmt.where(or_(AdobeMember.access_token == "", AdobeMember.access_token.is_(None)))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(AdobeMember.email.like(like), AdobeAccount.email.like(like))
        )
    return stmt


def list_pool(
    db: Session,
    *,
    page: int = 1,
    size: int = 50,
    keyword: str = "",
    admin_id: int | None = None,
    registered_only: bool = True,
    pool_type: str = "",
    has_token: bool | None = None,
    credit_status: str = "",
    credit_value: float | None = None,
    status_filter: str = "",
) -> tuple[list[tuple[AdobeMember, str]], int]:
    """号池:成员 + 母号自身 + 导入账号(默认只看已注册可用的),附带母号邮箱。"""
    stmt = _pool_base_stmt()
    stmt = _pool_filters(
        stmt,
        keyword=keyword,
        admin_id=admin_id,
        registered_only=registered_only,
        pool_type=pool_type,
        has_token=has_token,
        credit_status=credit_status,
        credit_value=credit_value,
        status_filter=status_filter,
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(AdobeMember.is_admin.desc(), AdobeMember.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return [(r[0], r[1] or "") for r in rows], total


def list_pool_ids(
    db: Session,
    *,
    keyword: str = "",
    admin_id: int | None = None,
    registered_only: bool = True,
    pool_type: str = "",
    has_token: bool | None = None,
    credit_status: str = "",
    credit_value: float | None = None,
    status_filter: str = "",
) -> list[int]:
    stmt = _pool_base_stmt()
    stmt = _pool_filters(
        stmt,
        keyword=keyword,
        admin_id=admin_id,
        registered_only=registered_only,
        pool_type=pool_type,
        has_token=has_token,
        credit_status=credit_status,
        credit_value=credit_value,
        status_filter=status_filter,
    )
    rows = db.execute(stmt.order_by(AdobeMember.id.desc())).all()
    return [r[0].id for r in rows]


def export_pool(
    db: Session,
    *,
    keyword: str = "",
    admin_id: int | None = None,
    registered_only: bool = True,
    pool_type: str = "",
    has_token: bool | None = None,
    credit_status: str = "",
    credit_value: float | None = None,
    status_filter: str = "",
) -> list[tuple[AdobeMember, str]]:
    stmt = _pool_base_stmt()
    stmt = _pool_filters(
        stmt,
        keyword=keyword,
        admin_id=admin_id,
        registered_only=registered_only,
        pool_type=pool_type,
        has_token=has_token,
        credit_status=credit_status,
        credit_value=credit_value,
        status_filter=status_filter,
    )
    rows = db.execute(
        stmt.order_by(AdobeMember.is_admin.desc(), AdobeMember.id.desc())
    ).all()
    return [(r[0], r[1] or "") for r in rows]


def import_pool_lines(db: Session, content: str) -> dict:
    """把 `邮箱----密码----ClientID----RefreshToken` 等格式直接导入号池为独立账号
    (admin_id=0, is_imported=True)。返回 {created, updated, skipped, failed, errors}。
    """
    from app.crud.email import _parse_email_line  # 复用智能解析

    def _json_items(raw: str) -> list[dict] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return None

    def _decode_token_user_id(token: str) -> str:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        except Exception:
            return ""
        return str(data.get("user_id") or data.get("aa_id") or data.get("sub") or "").strip()

    def _user_id_from_cookie(cookie: str) -> str:
        for part in str(cookie or "").split(";"):
            name = part.strip().split("=", 1)[0].strip()
            if name.startswith("TAB_personalisation_"):
                return unquote(name.removeprefix("TAB_personalisation_")).strip()
        return ""

    def _import_browser_cookie(fields: dict, line_label: str) -> tuple[bool, str, bool] | None:
        cookie = str(fields.get("cookie") or "").strip()
        if not cookie:
            return None
        email = str(fields.get("email") or fields.get("name") or "").strip()
        user_id = _user_id_from_cookie(cookie)
        row = None
        if email and "@" in email:
            row = db.scalar(select(AdobeMember).where(AdobeMember.email == email))
        if row is None and user_id:
            candidates = list(
                db.scalars(
                    select(AdobeMember).where(
                        AdobeMember.access_token != "",
                    )
                )
            )
            for candidate in candidates:
                token_user_id = _decode_token_user_id(candidate.access_token)
                if token_user_id and token_user_id == user_id:
                    row = candidate
                    break
        if row is None:
            hint = "缺少邮箱/name" if not user_id else f"未找到 Adobe user_id={user_id} 对应号池账号"
            return False, f"{line_label}:{hint}", False

        headers = fields.get("headers") if isinstance(fields.get("headers"), dict) else {}
        arp = ""
        for key, value in headers.items():
            if str(key or "").strip().lower() == "x-arp-session-id":
                arp = str(value or "").strip()
                break
        row.cookie = cookie
        if arp:
            row.arp_session_id = arp
        row.status = row.status or "registered"
        row.registered = True
        row.message = "已导入网页登录完整 Cookie"
        row.updated_at = datetime.now(timezone.utc)
        return True, "", True

    def _import_record(fields: dict, line_label: str) -> tuple[bool, str, bool]:
        """Return (ok, error, existed)."""
        browser_cookie_result = _import_browser_cookie(fields, line_label)
        if browser_cookie_result is not None:
            return browser_cookie_result

        email = (
            fields.get("email")
            or fields.get("name")
            or fields.get("user_id")
            or fields.get("display_name")
            or ""
        ).strip()
        if not email:
            return False, f"{line_label}:缺少邮箱/name", False
        rt = fields.get("refresh_token") or ""
        cid = fields.get("client_id") or ""
        mail_url = fields.get("mail_url") or ""
        access_token = fields.get("access_token") or ""
        device_token = fields.get("device_token") or ""
        device_id = fields.get("device_id") or ""
        cookie = fields.get("cookie") or ""
        has_ready_token = bool(access_token or device_token)
        if not (has_ready_token or (rt and cid) or mail_url):
            return False, f"{line_label}:缺少 token 或 Refresh Token / Client ID 或取信配置", False
        row = db.scalar(
            select(AdobeMember).where(
                AdobeMember.admin_id == 0, AdobeMember.email == email
            )
        )
        existed = bool(row)
        if row is None:
            row = AdobeMember(
                admin_id=0,
                email=email,
                is_imported=True,
            )
            db.add(row)
        row.is_imported = True
        row.status = "registered" if access_token else (row.status or "")
        row.message = "导入(已有 FF-iOS token)" if access_token else "导入(可协议拉取前端 token)"
        row.registered = bool(access_token) or row.registered
        if rt:
            row.refresh_token = rt
        if cid:
            row.client_id = cid
        if mail_url:
            row.mail_url = mail_url
        if access_token:
            row.access_token = access_token
        if device_token:
            row.device_token = device_token
        if device_id:
            row.device_id = device_id
        if cookie:
            row.cookie = cookie
        if fields.get("display_name"):
            row.display_name = fields.get("display_name") or ""
        if fields.get("credits") is not None:
            try:
                row.credits = float(fields.get("credits"))
            except (TypeError, ValueError):
                pass
        if fields.get("expires_at") is not None:
            try:
                row.expires_at = int(fields.get("expires_at"))
            except (TypeError, ValueError):
                pass
        row.updated_at = datetime.now(timezone.utc)
        return True, "", existed

    created = updated = failed = 0
    errors: list[str] = []
    json_items = _json_items(content.strip())
    if json_items is not None:
        for idx, item in enumerate(json_items, start=1):
            ok, err, existed = _import_record(item, f"第 {idx} 条")
            if ok:
                updated += 1 if existed else 0
                created += 0 if existed else 1
            else:
                failed += 1
                errors.append(err)
        db.commit()
        return {"created": created, "updated": updated, "skipped": 0,
                "failed": failed, "errors": errors}

    for line_no, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        fields = _parse_email_line(line)
        if not fields:
            failed += 1
            errors.append(f"第 {line_no} 行:邮箱格式无效")
            continue
        ok, err, existed = _import_record(fields, f"第 {line_no} 行")
        if ok:
            if existed:
                updated += 1
            else:
                created += 1
        else:
            failed += 1
            errors.append(err)
            continue
    db.commit()
    return {"created": created, "updated": updated, "skipped": 0,
            "failed": failed, "errors": errors}


def get_many(db: Session, ids: list[int]) -> list[AdobeMember]:
    return list(db.scalars(select(AdobeMember).where(AdobeMember.id.in_(ids))))


def delete_many(db: Session, admin_id: int, ids: list[int]) -> list[AdobeMember]:
    rows = list(
        db.scalars(
            select(AdobeMember).where(
                AdobeMember.admin_id == admin_id, AdobeMember.id.in_(ids)
            )
        )
    )
    return rows
