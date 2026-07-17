import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.email import Email
from app.models.adobe_account import AdobeAccount
from app.models.adobe_member import AdobeMember
from app.schemas.common import BatchImportResult
from app.schemas.email import EmailCreate, EmailUpdate

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_MOEMAIL_DOMAINS = {"edu0.buzz", "edu1.store", "edu6.site", "edu8.buzz"}


def _parse_email_line(line: str) -> dict[str, str] | None:
    """智能解析一行账号,兼容两种分隔符与字段顺序。

    支持::

        邮箱|密码|RefreshToken|ClientID
        邮箱----密码----ClientID----RefreshToken
        邮箱----密码----https://api.xxx/mail-new?refresh_token=...&client_id=...

    按字段特征归位:含 ``@`` 的是邮箱;UUID 形态的是 client_id;
    取信 URL 会保存为 mail_url,若 query 里带 refresh_token/client_id 则提取;
    以 ``M.`` 开头的是 Microsoft refresh_token;其余短串当作密码。
    """
    if "----" in line:
        parts = [p.strip() for p in line.split("----")]
    elif "|" in line:
        parts = [p.strip() for p in line.split("|")]
    else:
        parts = [line.strip()]
    parts = [p for p in parts if p]
    if not parts:
        return None

    email = ""
    rest: list[str] = []
    for p in parts:
        if "@" in p and not email:
            email = p
        else:
            rest.append(p)
    if not email or "@" not in email:
        return None

    client_id = ""
    refresh_token = ""
    mail_url = ""
    moemail_api_key = ""
    moemail_email_id = ""
    leftover: list[str] = []
    for p in rest:
        parsed = urlparse(p)
        if parsed.scheme == "moemail":
            mail_url = p
            continue
        if p.startswith("mk_"):
            moemail_api_key = p
            continue
        if parsed.scheme in ("http", "https"):
            mail_url = mail_url or p
            if parsed.query:
                qs = parse_qs(parsed.query)
                if not refresh_token:
                    refresh_token = (qs.get("refresh_token") or [""])[0].strip()
                if not client_id:
                    client_id = (qs.get("client_id") or [""])[0].strip()
                if not moemail_api_key:
                    moemail_api_key = (qs.get("api_key") or qs.get("key") or [""])[0].strip()
                if not moemail_email_id:
                    moemail_email_id = (qs.get("email_id") or qs.get("emailId") or [""])[0].strip()
            continue
        if not client_id and _UUID_RE.match(p):
            if moemail_api_key:
                moemail_email_id = p
            else:
                client_id = p
        elif p.startswith("M."):
            refresh_token = p
        elif not refresh_token and len(p) > 60:
            refresh_token = p
        else:
            leftover.append(p)

    domain = email.rsplit("@", 1)[-1].lower()
    if moemail_api_key and domain in _MOEMAIL_DOMAINS and not mail_url.startswith("moemail://"):
        qs = {"api_key": moemail_api_key}
        if moemail_email_id:
            qs["email_id"] = moemail_email_id
        mail_url = f"moemail://edu6.site?{urlencode(qs)}"

    password = leftover[0] if leftover else ""
    return {
        "email": email,
        "password": password,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "mail_url": mail_url,
    }


def list_emails(
    db: Session,
    *,
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    remark: str = "",
    is_used: bool | None = None,
    is_disabled: bool | None = None,
) -> tuple[list[Email], int]:
    stmt = select(Email)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Email.email.like(like), Email.remark.like(like)))
    if remark:
        stmt = stmt.where(Email.remark == remark)
    if is_used is not None:
        stmt = stmt.where(Email.is_used == is_used)
    if is_disabled is not None:
        stmt = stmt.where(Email.is_disabled == is_disabled)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.scalars(stmt.order_by(Email.id.desc()).offset((page - 1) * size).limit(size))
    )
    return items, total


def get(db: Session, email_id: int) -> Email | None:
    return db.get(Email, email_id)


def get_by_email(db: Session, email: str) -> Email | None:
    return db.scalar(select(Email).where(Email.email == email))


def disabled_email_set(db: Session, emails: list[str]) -> set[str]:
    normalized = {str(e or "").strip().lower() for e in emails if str(e or "").strip()}
    if not normalized:
        return set()
    return {
        str(email or "").strip().lower()
        for email in db.scalars(
            select(Email.email).where(
                func.lower(Email.email).in_(normalized),
                Email.is_disabled == True,  # noqa: E712
            )
        )
        if str(email or "").strip()
    }


def take_unused(
    db: Session, count: int, exclude: set[str] | None = None
) -> list[Email]:
    """取出最多 count 个未使用的邮箱(不在此处标记已用)。

    ``exclude`` 是已被其它任务预占的邮箱(小写),用于并发拉号时避免争用。
    """
    if count <= 0:
        return []
    exclude = exclude or set()
    used_member_emails = select(func.lower(AdobeMember.email)).where(
        AdobeMember.email != "",
        or_(
            AdobeMember.registered == True,  # noqa: E712
            AdobeMember.is_admin == True,  # noqa: E712
            AdobeMember.is_imported == True,  # noqa: E712
            AdobeMember.member_id != "",
            AdobeMember.access_token != "",
            AdobeMember.cookie != "",
        ),
    )
    admin_emails = select(func.lower(AdobeAccount.email)).where(
        AdobeAccount.email != ""
    )
    normalized_email = func.lower(Email.email)
    # 历史上加过的子号/导入号/母号都不再取出,避免删除后又重复拉同一个邮箱。
    rows = list(
        db.scalars(
            select(Email)
            .where(Email.is_used == False)  # noqa: E712
            .where(Email.is_disabled == False)  # noqa: E712
            .where(normalized_email.not_in(used_member_emails))
            .where(normalized_email.not_in(admin_emails))
            .order_by(Email.id.asc())
            .limit(count + len(exclude) + 200)
        )
    )
    if exclude:
        rows = [r for r in rows if r.email.lower() not in exclude]
    return rows[:count]


def mark_used_by_email(db: Session, email: str, admin_email: str = "") -> None:
    row = get_by_email(db, email)
    if row:
        row.is_used = True
        row.used_at = datetime.now(timezone.utc)
        if admin_email:
            row.remark = admin_email


def mark_unused_by_email(db: Session, email: str) -> None:
    row = get_by_email(db, email)
    if row and row.is_used:
        row.is_used = False
        row.used_at = None


def reconcile_usage_by_emails(db: Session, emails: list[str]) -> None:
    """按真实成功子号校准邮箱占用状态。

    成功注册/拿到 member_id/token/cookie 的子号必须占用邮箱;
    失败邮箱恢复未使用,但如果已经被停用,保留停用状态和失败备注。
    """
    normalized = {str(e or "").strip().lower() for e in emails if str(e or "").strip()}
    if not normalized:
        return
    db.flush()
    success_pairs = db.execute(
        select(func.lower(AdobeMember.email), AdobeAccount.email)
        .join(AdobeAccount, AdobeAccount.id == AdobeMember.admin_id)
        .where(
            func.lower(AdobeMember.email).in_(normalized),
            AdobeMember.is_admin == False,  # noqa: E712
            AdobeMember.is_imported == False,  # noqa: E712
            or_(
                AdobeMember.registered == True,  # noqa: E712
                AdobeMember.member_id != "",
                AdobeMember.access_token != "",
                AdobeMember.cookie != "",
            ),
        )
    ).all()
    success_admin_by_email = {email: admin_email or "" for email, admin_email in success_pairs}
    rows = list(db.scalars(select(Email).where(func.lower(Email.email).in_(normalized))))
    now = datetime.now(timezone.utc)
    for row in rows:
        admin_email = success_admin_by_email.get(row.email.lower(), "")
        if admin_email:
            row.is_used = True
            row.used_at = now
            row.remark = admin_email
            continue
        row.is_used = False
        row.used_at = None
        if not row.is_disabled:
            row.remark = ""


def set_used_many(db: Session, ids: list[int], is_used: bool) -> int:
    objs = list(db.scalars(select(Email).where(Email.id.in_(ids))))
    now = datetime.now(timezone.utc)
    for obj in objs:
        obj.is_used = bool(is_used)
        obj.used_at = now if is_used else None
    db.commit()
    return len(objs)


def set_disabled_many(db: Session, ids: list[int], is_disabled: bool) -> int:
    objs = list(db.scalars(select(Email).where(Email.id.in_(ids))))
    for obj in objs:
        obj.is_disabled = bool(is_disabled)
    db.commit()
    return len(objs)


def disable_by_emails(db: Session, emails: list[str], remark: str = "") -> int:
    normalized = {str(e or "").strip().lower() for e in emails if str(e or "").strip()}
    if not normalized:
        return 0
    rows = list(db.scalars(select(Email).where(func.lower(Email.email).in_(normalized))))
    for row in rows:
        row.is_disabled = True
        row.is_used = False
        row.used_at = None
        if remark:
            row.remark = remark
    db.commit()
    return len(rows)


def create(db: Session, data: EmailCreate) -> Email:
    obj = Email(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, obj: Email, data: EmailUpdate) -> Email:
    payload = data.model_dump(exclude_unset=True)
    if "is_used" in payload:
        obj.used_at = datetime.now(timezone.utc) if payload["is_used"] else None
    for field, value in payload.items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


def delete_many(db: Session, ids: list[int]) -> int:
    objs = list(db.scalars(select(Email).where(Email.id.in_(ids))))
    for obj in objs:
        db.delete(obj)
    db.commit()
    return len(objs)


def delete_by_emails(db: Session, emails: list[str], *, exclude_emails: set[str] | None = None) -> int:
    normalized = {str(e or "").strip().lower() for e in emails if str(e or "").strip()}
    if exclude_emails:
        normalized -= {str(e or "").strip().lower() for e in exclude_emails if str(e or "").strip()}
    if not normalized:
        return 0
    objs = list(db.scalars(select(Email).where(func.lower(Email.email).in_(normalized))))
    for obj in objs:
        db.delete(obj)
    return len(objs)


def batch_import(db: Session, content: str, on_duplicate: str = "skip") -> BatchImportResult:
    """批量导入,兼容两种格式(每行一条):

    - ``邮箱|密码|RefreshToken|ClientID``
    - ``邮箱----密码----ClientID----RefreshToken``
    """
    result = BatchImportResult(created=0, updated=0, skipped=0, failed=0)

    for line_no, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        fields = _parse_email_line(line)
        if not fields:
            result.failed += 1
            result.errors.append(f"第 {line_no} 行:邮箱格式无效")
            continue
        email = fields["email"]

        existing = get_by_email(db, email)
        if existing:
            if on_duplicate == "overwrite":
                for k, v in fields.items():
                    setattr(existing, k, v)
                result.updated += 1
            else:
                result.skipped += 1
            continue

        db.add(Email(**fields))
        result.created += 1

    db.commit()
    return result
