from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.crud import adobe_account as crud
from app.crud import adobe_member as member_crud
from app.crud import email as email_crud
from app.crud import setting as setting_crud
from app.db.session import SessionLocal, get_db
from app.models.adobe_account import AdobeAccount
from app.models.email import Email
from app.schemas.adobe_account import (
    AdminActionResult,
    AdobeAccountCreate,
    AdobeAccountOut,
    AdobeAccountUpdate,
    BatchBuildTeamRequest,
    BatchGrantRequest,
    BatchGrantResult,
    BatchReloginAccountsRequest,
    BuildTeamRequest,
    GrantItemResult,
    JobStatusOut,
    ManualLoginStartResult,
    ManualLoginVerifyRequest,
    MemberOut,
    QuickAddAccountRequest,
    QuickAddAccountResult,
    TestEmailResult,
)
from app.schemas.common import (
    BatchIds,
    BatchImportRequest,
    BatchImportResult,
    MessageResult,
    Page,
)
from app.services import adobe_admin, firefly, firefly_ios, proxy_pool, team_builder
from app.services.job_manager import JOBS
from app.services.mail_test import test_receive_email

router = APIRouter(
    prefix="/adobe-accounts",
    tags=["Adobe账号管理"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=Page[AdobeAccountOut], summary="分页查询")
def list_accounts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    db: Session = Depends(get_db),
) -> Page[AdobeAccountOut]:
    items, total = crud.list_accounts(db, page=page, size=size, keyword=keyword.strip())
    return Page(items=items, total=total, page=page, size=size)


@router.post("", response_model=AdobeAccountOut, summary="新增单个账号")
def create_account(
    data: AdobeAccountCreate, db: Session = Depends(get_db)
) -> AdobeAccountOut:
    if crud.get_by_email(db, data.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已存在")
    return crud.create(db, data)


@router.put("/{account_id}", response_model=AdobeAccountOut, summary="编辑账号")
def update_account(
    account_id: int, data: AdobeAccountUpdate, db: Session = Depends(get_db)
) -> AdobeAccountOut:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if data.email and data.email != account.email and crud.get_by_email(db, data.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已存在")
    return crud.update(db, account, data)


@router.delete("/{account_id}", response_model=MessageResult, summary="删除单个账号")
def delete_account(account_id: int, db: Session = Depends(get_db)) -> MessageResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    crud.delete(db, account)
    return MessageResult(message="删除成功")


@router.post("/batch-delete", response_model=MessageResult, summary="批量删除")
def batch_delete(payload: BatchIds, db: Session = Depends(get_db)) -> MessageResult:
    count = crud.delete_many(db, payload.ids)
    return MessageResult(message=f"已删除 {count} 条")


@router.post("/batch-import", response_model=BatchImportResult, summary="批量导入")
def batch_import(
    payload: BatchImportRequest, db: Session = Depends(get_db)
) -> BatchImportResult:
    return crud.batch_import(db, payload.content, payload.on_duplicate)


def _parse_quick_add_account(content: str) -> dict[str, str]:
    line = next((item.strip() for item in content.splitlines() if item.strip()), "")
    if not line:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请粘贴账号内容"
        )
    if "----" in line and "|" not in line:
        parts = [part.strip() for part in line.split("----")]
    else:
        parts = [part.strip() for part in line.split("|")]
    if len(parts) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="格式应为:邮箱|Hotmail密码|母号密码|Refresh Token|Client ID",
        )

    email = parts[0].lower()
    hotmail_password = parts[1]
    adobe_password = parts[2]
    refresh_token = "|".join(parts[3:-1]).strip()
    client_id = parts[-1]
    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱格式无效"
        )
    if not adobe_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="母号密码不能为空"
        )
    if not refresh_token or not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh Token / Client ID 不能为空",
        )
    return {
        "email": email,
        "hotmail_password": hotmail_password,
        "adobe_password": adobe_password,
        "refresh_token": refresh_token,
        "client_id": client_id,
    }


def _apply_admin_login_result(account: AdobeAccount, res: dict) -> None:
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
    if res.get("has_org"):
        account.check_message = (
            f"组织 {res.get('org_count', 0)} 个 / 产品 {res.get('product_count', 0)} 个;"
            f"授权产品:{res.get('product_name') or res.get('product_id') or '-'}"
        )[:500]
    else:
        account.check_message = res.get("message") or "登录成功但未发现可用组织/产品"


@router.post("/quick-add", response_model=QuickAddAccountResult, summary="快速增加并登录母号")
def quick_add_account(
    payload: QuickAddAccountRequest, db: Session = Depends(get_db)
) -> QuickAddAccountResult:
    fields = _parse_quick_add_account(payload.content)
    remark = (payload.remark or "").strip() or "母号"
    email = fields["email"]

    pool_email = email_crud.get_by_email(db, email)
    email_created = pool_email is None
    if pool_email is None:
        pool_email = Email(email=email)
        db.add(pool_email)
    pool_email.password = fields["hotmail_password"]
    pool_email.refresh_token = fields["refresh_token"]
    pool_email.client_id = fields["client_id"]
    pool_email.mail_url = pool_email.mail_url or ""
    pool_email.remark = remark
    pool_email.is_disabled = False

    account = crud.get_by_email(db, email)
    account_created = account is None
    if account is None:
        account = AdobeAccount(email=email)
        db.add(account)
    account.hotmail_password = fields["hotmail_password"]
    account.adobe_password = fields["adobe_password"]
    account.refresh_token = fields["refresh_token"]
    account.client_id = fields["client_id"]
    account.remark = remark
    db.commit()
    db.refresh(account)

    logs: list[str] = []
    if not payload.login:
        member_crud.ensure_admin_self_rows(db)
        return QuickAddAccountResult(
            success=True,
            message="已加入母号管理和邮箱管理",
            account_id=account.id,
            email=account.email,
            account_created=account_created,
            email_created=email_created,
            email_synced=True,
            login_attempted=False,
            has_org=account.has_org,
            org_id=account.org_id,
            product_name=account.product_name,
            logs=logs,
        )

    def _log(msg: str) -> None:
        logs.append(msg)

    proxy_raw, _timeout = _proxy_and_timeout(db)
    proxy_url = proxy_pool.next_proxy(proxy_raw)
    try:
        res = adobe_admin.login_account(
            email=account.email,
            adobe_password=account.adobe_password,
            refresh_token=account.refresh_token,
            client_id=account.client_id,
            proxy_url=proxy_url,
            otp_timeout=180,
            log=_log,
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.check_message = str(exc)[:500]
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        member_crud.ensure_admin_self_rows(db)
        return QuickAddAccountResult(
            success=False,
            message=f"已加入母号和邮箱管理,但登录失败:{str(exc)[:420]}",
            account_id=account.id,
            email=account.email,
            account_created=account_created,
            email_created=email_created,
            email_synced=True,
            login_attempted=True,
            has_org=False,
            logs=logs,
        )

    rotated = res.get("rotated_refresh_token") or ""
    if rotated and rotated != account.refresh_token:
        account.refresh_token = rotated
        pool_email.refresh_token = rotated
    _apply_admin_login_result(account, res)
    db.commit()
    member_crud.ensure_admin_self_rows(db)

    msg = (
        "已加入母号和邮箱管理,并登录成功"
        if res.get("has_org")
        else account.check_message
    )
    return QuickAddAccountResult(
        success=bool(res.get("has_org")),
        message=msg,
        account_id=account.id,
        email=account.email,
        account_created=account_created,
        email_created=email_created,
        email_synced=True,
        login_attempted=True,
        has_org=account.has_org,
        org_id=account.org_id,
        product_name=account.product_name,
        org_count=int(res.get("org_count") or 0),
        product_count=int(res.get("product_count") or 0),
        logs=logs,
    )


def _sync_rotated_account_refresh_token(db: Session, account: AdobeAccount, rotated: str) -> None:
    if not rotated or rotated == account.refresh_token:
        return
    account.refresh_token = rotated
    pool_email = email_crud.get_by_email(db, account.email)
    if pool_email:
        pool_email.refresh_token = rotated


def _admin_relogin_batch_worker(job) -> None:
    admin_ids = [int(a) for a in (job.meta.get("admin_ids") or [])]
    only_invalid = bool(job.meta.get("only_invalid", True))
    db = SessionLocal()
    try:
        settings = setting_crud.get_settings(db)
        proxy_raw = settings.proxy_url if settings.proxy_enabled else ""
        n_proxy = proxy_pool.proxy_count(proxy_raw)
        if n_proxy:
            job.log(f"已配置 {n_proxy} 个代理,检测/重登时按行轮换出口")

        accounts_by_id = {acc.id: acc for acc in crud.list_by_ids(db, admin_ids)}
        teams: list[dict] = []
        for aid in admin_ids:
            acc = accounts_by_id.get(aid)
            teams.append({
                "admin_id": aid,
                "email": acc.email if acc else f"#{aid}",
                "target": 1,
                "success": 0,
                "fail": 0,
                "status": "pending",
                "message": "",
                "prefix": "",
            })
        job.target = len(teams)
        job.set_extra("teams", teams)

        for idx, aid in enumerate(admin_ids, start=1):
            if job.cancelled:
                break
            team = teams[idx - 1]
            team["prefix"] = f"[{idx}/{len(admin_ids)} {team['email']}] "
            team["status"] = "running"
            job.set_extra("teams", teams)

            account = accounts_by_id.get(aid)
            if not account:
                team["status"] = "error"
                team["fail"] = 1
                team["message"] = "母号不存在"
                job.bump(fail=1)
                job.log(f"{team['prefix']}✗ 母号不存在")
                job.set_extra("teams", teams)
                continue

            prefix = team["prefix"]
            needs_login = True
            if account.admin_token and account.org_id:
                try:
                    adobe_admin.check_admin(
                        token=account.admin_token,
                        org_id=account.org_id,
                        proxy_url=proxy_pool.next_proxy(proxy_raw),
                    )
                    account.is_valid = True
                    account.has_org = True
                    account.check_message = "检测有效,无需重登"
                    account.last_checked_at = datetime.now(timezone.utc)
                    db.commit()
                    if only_invalid:
                        needs_login = False
                        team["status"] = "done"
                        team["success"] = 1
                        team["message"] = "当前有效,无需重登"
                        job.bump(success=1)
                        job.log(f"{prefix}✓ 当前管理 token 有效,跳过重登")
                except Exception as exc:  # noqa: BLE001
                    account.is_valid = False
                    account.has_org = False
                    account.check_message = f"检测失败,准备重登:{str(exc)[:360]}"
                    account.last_checked_at = datetime.now(timezone.utc)
                    db.commit()
                    job.log(f"{prefix}检测失效,开始自动验证码重登:{str(exc)[:140]}")
            else:
                job.log(f"{prefix}缺少管理 token/组织信息,开始自动验证码登录")

            if not needs_login:
                job.set_extra("teams", teams)
                continue

            if not (account.refresh_token and account.client_id):
                team["status"] = "error"
                team["fail"] = 1
                team["message"] = "缺少 Refresh Token / Client ID,无法自动收验证码"
                account.is_valid = False
                account.check_message = team["message"]
                account.last_checked_at = datetime.now(timezone.utc)
                db.commit()
                job.bump(fail=1)
                job.log(f"{prefix}✗ {team['message']}")
                job.set_extra("teams", teams)
                continue

            try:
                res = adobe_admin.login_account(
                    email=account.email,
                    adobe_password=account.adobe_password,
                    refresh_token=account.refresh_token,
                    client_id=account.client_id,
                    proxy_url=proxy_pool.next_proxy(proxy_raw),
                    otp_timeout=180,
                    log=lambda m, p=prefix: job.log(f"{p}{m}"),
                )
            except Exception as exc:  # noqa: BLE001
                team["status"] = "error"
                team["fail"] = 1
                team["message"] = f"重登失败:{str(exc)[:180]}"
                account.is_valid = False
                account.check_message = str(exc)[:500]
                account.last_checked_at = datetime.now(timezone.utc)
                db.commit()
                job.bump(fail=1)
                job.log(f"{prefix}✗ {team['message']}")
                job.set_extra("teams", teams)
                continue

            _sync_rotated_account_refresh_token(
                db, account, res.get("rotated_refresh_token") or ""
            )
            _apply_admin_login_result(account, res)
            if res.get("has_org"):
                team["status"] = "done"
                team["success"] = 1
                team["message"] = f"重登成功:{account.product_name or account.product_id or '-'}"
                job.bump(success=1)
                job.log(f"{prefix}✓ 重新登录成功,授权产品:{account.product_name or account.product_id or '-'}")
            else:
                team["status"] = "error"
                team["fail"] = 1
                team["message"] = account.check_message or "登录成功但未发现可用组织/产品"
                job.bump(fail=1)
                job.log(f"{prefix}✗ {team['message']}")
            db.commit()
            member_crud.ensure_admin_self_rows(db)
            job.set_extra("teams", teams)

        job.result = {
            "total": len(teams),
            "success": job.success,
            "fail": job.fail,
            "only_invalid": only_invalid,
        }
        job.log(f"=== 完成:处理 {job.success}/{len(teams)},失败 {job.fail} ===")
    finally:
        db.close()


@router.post(
    "/batch-relogin",
    response_model=JobStatusOut,
    summary="批量检测并重新登录失效母号",
)
def batch_relogin_accounts(
    payload: BatchReloginAccountsRequest, db: Session = Depends(get_db)
) -> JobStatusOut:
    admin_ids = [a for a in dict.fromkeys(payload.ids)]
    if not admin_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请至少选择一个母号"
        )
    found = {a.id for a in crud.list_by_ids(db, admin_ids)}
    missing = [a for a in admin_ids if a not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"母号不存在:{missing}"
        )

    job = JOBS.start(
        "admin_relogin_batch",
        _admin_relogin_batch_worker,
        meta={
            "admin_ids": admin_ids,
            "only_invalid": payload.only_invalid,
            "target": len(admin_ids),
        },
    )
    return JobStatusOut(**job.to_dict())


@router.post(
    "/{account_id}/test-email", response_model=TestEmailResult, summary="测试收邮件"
)
def test_email(account_id: int, db: Session = Depends(get_db)) -> TestEmailResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")

    settings = setting_crud.get_settings(db)
    proxy_url = proxy_pool.pick(settings)

    result = test_receive_email(
        email_addr=account.email,
        refresh_token=account.refresh_token,
        client_id=account.client_id,
        proxy_url=proxy_url,
        timeout=settings.request_timeout,
    )

    account.mail_ok = result.success
    account.mail_message = result.message[:500]
    account.mail_checked_at = datetime.now(timezone.utc)
    # 微软的 Refresh Token 是一次性轮换的,换令牌成功后必须存回新 token,
    # 否则旧 token 已作废,下次测试会失败。
    if result.new_refresh_token and result.new_refresh_token != account.refresh_token:
        account.refresh_token = result.new_refresh_token
    db.commit()

    return TestEmailResult(
        success=result.success,
        message=result.message,
        inbox_total=result.inbox_total,
        latest_subject=result.latest_subject,
        latest_from=result.latest_from,
    )


# ----------------------------------------------------------------------------
# Adobe Admin Console:登录 / 检测 / 成员(子账号)管理
# ----------------------------------------------------------------------------

def _proxy_and_timeout(db: Session) -> tuple[str, int]:
    """返回 (代理原始多行文本, 超时)。具体外呼时用 proxy_pool 轮询取单个。"""
    s = setting_crud.get_settings(db)
    return (s.proxy_url if s.proxy_enabled else ""), s.request_timeout


@router.post(
    "/{account_id}/login", response_model=AdminActionResult, summary="登录获取管理员权限"
)
def admin_login(account_id: int, db: Session = Depends(get_db)) -> AdminActionResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not (account.refresh_token and account.client_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该账号缺少 Refresh Token / Client ID,无法自动收取验证码",
        )

    proxy_raw, _timeout = _proxy_and_timeout(db)
    proxy_url = proxy_pool.next_proxy(proxy_raw)
    logs: list[str] = []

    def _log(msg: str) -> None:
        logs.append(msg)

    try:
        res = adobe_admin.login_account(
            email=account.email,
            adobe_password=account.adobe_password,
            refresh_token=account.refresh_token,
            client_id=account.client_id,
            proxy_url=proxy_url,
            otp_timeout=180,
            log=_log,
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.check_message = str(exc)[:500]
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        return AdminActionResult(
            success=False, message=str(exc)[:500], has_org=False, logs=logs
        )

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
    if res.get("has_org"):
        account.check_message = (
            f"组织 {res.get('org_count', 0)} 个 / 产品 {res.get('product_count', 0)} 个;"
            f"授权产品:{res.get('product_name') or res.get('product_id') or '-'}"
        )[:500]
        msg = "登录成功,已获取管理权限"
    else:
        account.check_message = res.get("message") or "登录成功但未发现可用组织/产品"
        msg = account.check_message
    db.commit()

    return AdminActionResult(
        success=bool(res.get("has_org")),
        message=msg,
        has_org=account.has_org,
        org_id=account.org_id,
        product_name=account.product_name,
        org_count=int(res.get("org_count") or 0),
        product_count=int(res.get("product_count") or 0),
        logs=logs,
    )


@router.post(
    "/{account_id}/login/manual/start",
    response_model=ManualLoginStartResult,
    summary="手动验证码登录-发送验证码",
)
def admin_manual_login_start(
    account_id: int, db: Session = Depends(get_db)
) -> ManualLoginStartResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")

    proxy_raw, _timeout = _proxy_and_timeout(db)
    proxy_url = proxy_pool.next_proxy(proxy_raw)
    logs: list[str] = []

    def _log(msg: str) -> None:
        logs.append(msg)

    try:
        res = adobe_admin.begin_manual_login(
            email=account.email,
            adobe_password=account.adobe_password,
            proxy_url=proxy_url,
            log=_log,
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.check_message = str(exc)[:500]
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        return ManualLoginStartResult(
            success=False, message=str(exc)[:500], logs=logs
        )
    return ManualLoginStartResult(
        success=True,
        message=res.get("message") or "已发送验证码邮件",
        session_id=res.get("session_id") or "",
        logs=logs,
    )


@router.post(
    "/{account_id}/login/manual/verify",
    response_model=AdminActionResult,
    summary="手动验证码登录-提交验证码",
)
def admin_manual_login_verify(
    account_id: int, payload: ManualLoginVerifyRequest, db: Session = Depends(get_db)
) -> AdminActionResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    logs: list[str] = []

    def _log(msg: str) -> None:
        logs.append(msg)

    try:
        res = adobe_admin.complete_manual_login(
            session_id=payload.session_id,
            code=payload.code,
            log=_log,
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.check_message = str(exc)[:500]
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        return AdminActionResult(
            success=False, message=str(exc)[:500], has_org=False, logs=logs
        )

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
    if res.get("has_org"):
        account.check_message = (
            f"组织 {res.get('org_count', 0)} 个 / 产品 {res.get('product_count', 0)} 个;"
            f"授权产品:{res.get('product_name') or res.get('product_id') or '-'}"
        )[:500]
        msg = "登录成功,已获取管理权限"
    else:
        account.check_message = res.get("message") or "登录成功但未发现可用组织/产品"
        msg = account.check_message
    db.commit()

    return AdminActionResult(
        success=bool(res.get("has_org")),
        message=msg,
        has_org=account.has_org,
        org_id=account.org_id,
        product_name=account.product_name,
        org_count=int(res.get("org_count") or 0),
        product_count=int(res.get("product_count") or 0),
        logs=logs,
    )


@router.post(
    "/{account_id}/check", response_model=AdminActionResult, summary="检测管理有效性"
)
def admin_check(account_id: int, db: Session = Depends(get_db)) -> AdminActionResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not account.admin_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="尚未登录,请先点击登录"
        )

    proxy_raw, _timeout = _proxy_and_timeout(db)
    proxy_url = proxy_pool.next_proxy(proxy_raw)
    try:
        res = adobe_admin.check_admin(
            token=account.admin_token, org_id=account.org_id, proxy_url=proxy_url
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.has_org = False
        account.check_message = f"检测失败(token 可能过期,请重新登录):{str(exc)[:400]}"
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        return AdminActionResult(
            success=False, message=account.check_message, has_org=False
        )

    account.is_valid = True
    account.has_org = True
    account.org_id = res.get("org_id") or account.org_id

    # 同步组织内真实成员数(让"成员数"列反映 Adobe 侧实际人数)
    member_total: int | None = None
    try:
        members = adobe_admin.fetch_members(
            token=account.admin_token,
            org_id=account.org_id,
            proxy_url=proxy_pool.next_proxy(proxy_raw),
            product_id=account.product_id,
            license_group_id=account.license_group_id,
        )
        member_total = len(
            [
                m
                for m in members
                if str(m.get("email") or "").strip().lower()
                != str(account.email or "").strip().lower()
            ]
        )
        account.member_count = member_total
    except Exception:  # noqa: BLE001
        pass

    account.check_message = (
        f"组织 {res.get('org_count', 0)} 个 / 产品 {res.get('product_count', 0)} 个"
        + (f" / 成员 {member_total} 个" if member_total is not None else "")
        + ",有效"
    )
    account.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    return AdminActionResult(
        success=True,
        message="有效(有组织/权限)"
        + (f",成员 {member_total} 个" if member_total is not None else ""),
        has_org=True,
        org_id=account.org_id,
        product_name=account.product_name,
        org_count=int(res.get("org_count") or 0),
        product_count=int(res.get("product_count") or 0),
    )


@router.get(
    "/{account_id}/members", response_model=Page[MemberOut], summary="子账号(成员)列表"
)
def list_members(
    account_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    keyword: str = "",
    db: Session = Depends(get_db),
) -> Page[MemberOut]:
    if not crud.get(db, account_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    items, total = member_crud.list_by_admin(
        db, account_id, page=page, size=size, keyword=keyword.strip()
    )
    disabled_emails = email_crud.disabled_email_set(db, [item.email for item in items])
    for item in items:
        item.email_disabled = str(item.email or "").strip().lower() in disabled_emails
    return Page(items=items, total=total, page=page, size=size)


@router.post(
    "/{account_id}/members/sync-remote",
    response_model=MessageResult,
    summary="同步 Adobe 远端成员到本地",
)
def sync_remote_members(
    account_id: int, db: Session = Depends(get_db)
) -> MessageResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not (account.admin_token and account.org_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="尚未登录或缺少组织信息,请先登录/检测母号",
        )

    proxy_raw, _timeout = _proxy_and_timeout(db)
    existing_total = member_crud.count_by_admin(db, account_id)
    remote_members: list[dict] = []
    errors: list[str] = []
    prefer_product_group = bool(account.product_id and account.license_group_id)
    product_lookup_ok = False
    for attempt in range(1, 4):
        try:
            if prefer_product_group:
                client = adobe_admin.client_from_state(
                    {"proxy": proxy_pool.next_proxy(proxy_raw)}
                )
                try:
                    found = adobe_admin.list_product_users(
                        client,
                        account.admin_token,
                        account.org_id,
                        account.product_id,
                        account.license_group_id,
                        pages=50,
                        page_size=100,
                    )
                finally:
                    client.close()
                product_lookup_ok = True
            else:
                found = adobe_admin.fetch_members(
                    token=account.admin_token,
                    org_id=account.org_id,
                    proxy_url=proxy_pool.next_proxy(proxy_raw),
                    pages=50,
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第 {attempt} 次失败:{str(exc)[:160]}")
            continue
        if len(found) > len(remote_members):
            remote_members = found
        child_count = len(
            [
                m
                for m in found
                if str(m.get("email") or "").strip().lower()
                != str(account.email or "").strip().lower()
            ]
        )
        if child_count > 0 or existing_total == 0 or (prefer_product_group and found):
            break
        errors.append(f"第 {attempt} 次远端返回 0 个子号")
    if not remote_members and errors:
        account.is_valid = False
        account.check_message = f"同步成员失败:{'; '.join(errors)[:400]}"
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"同步成员失败,请先重新登录母号:{'; '.join(errors)[:300]}",
        )

    child_total = len(
        [
            m
            for m in remote_members
            if str(m.get("email") or "").strip().lower()
            != str(account.email or "").strip().lower()
        ]
    )
    allow_prune = child_total > 0 or existing_total == 0 or (
        prefer_product_group and product_lookup_ok and bool(remote_members)
    )
    result = member_crud.sync_remote_members(
        db, account_id, remote_members, admin_email=account.email,
        allow_prune=allow_prune,
    )
    account.member_count = child_total
    account.check_message = f"已同步 Adobe 远端子号 {child_total} 个"
    if not allow_prune:
        account.check_message += ",本次远端返回为空,已保留本地成员列表"
    account.last_checked_at = datetime.now(timezone.utc)
    db.commit()

    keep_msg = ",本次远端返回为空已保留本地列表" if not allow_prune else ""
    return MessageResult(
        message=(
            f"同步完成:远端子号 {child_total} 个,"
            f"新增 {result['created']} 个,更新 {result['updated']} 个,"
            f"清理 {result.get('pruned', 0)} 个,跳过 {result['skipped']} 个"
            f"{keep_msg}"
        )
    )


@router.post(
    "/{account_id}/members/batch-grant",
    response_model=BatchGrantResult,
    summary="批量加子账号并授权",
)
def batch_grant(
    account_id: int, payload: BatchGrantRequest, db: Session = Depends(get_db)
) -> BatchGrantResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not (account.admin_token and account.org_id and account.product_id
            and account.license_group_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该账号尚未取得管理权限,请先登录(并确认已发现组织/产品)",
        )

    proxy_raw, _timeout = _proxy_and_timeout(db)
    proxy_url = proxy_pool.next_proxy(proxy_raw)

    # 1) 确定要授权的邮箱:优先用传入列表,否则从邮箱池取未使用的
    from_pool = False
    skipped_items: list[GrantItemResult] = []
    if payload.emails:
        emails = []
        seen: set[str] = set()
        used_emails = member_crud.used_email_set(db)
        for raw in payload.emails:
            email = raw.strip()
            normalized = email.lower()
            if not email or "@" not in email or normalized in seen:
                continue
            seen.add(normalized)
            if normalized in used_emails or member_crud.email_exists_any(db, email):
                skipped_items.append(
                    GrantItemResult(email=email, ok=False, message="邮箱已使用,已跳过")
                )
                continue
            emails.append(email)
    else:
        pool_rows = email_crud.take_unused(db, payload.count)
        emails = [r.email for r in pool_rows]
        from_pool = True
    if not emails:
        if skipped_items:
            return BatchGrantResult(
                total=len(skipped_items),
                granted=0,
                failed=len(skipped_items),
                items=skipped_items,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可用于授权的邮箱(邮箱池为空或未填写列表)",
        )

    # 2) 批量授权前先校验 token 仍有效,避免逐个失败
    try:
        adobe_admin.check_admin(
            token=account.admin_token, org_id=account.org_id, proxy_url=proxy_url
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.has_org = False
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"管理 token 已失效,请重新登录:{str(exc)[:200]}",
        ) from exc

    token = account.admin_token
    org_id = account.org_id
    product_id = account.product_id
    lgid = account.license_group_id
    extra_products = adobe_admin.find_complimentary_products(
        token=token,
        org_id=org_id,
        product_id=product_id,
        license_group_id=lgid,
        proxy_url=proxy_url,
    )
    try:
        availability = adobe_admin.get_product_license_availability(
            token=token, org_id=org_id, product_id=product_id, proxy_url=proxy_url
        )
    except Exception:
        availability = {}
    if availability.get("found"):
        available = int(availability.get("available") or 0)
        if available <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Creative Cloud Pro 授权许可数量已满,请先在 Adobe 后台释放席位",
            )
        if len(emails) > available:
            skipped_items.extend(
                GrantItemResult(email=email, ok=False, message="远端授权许可不足,已跳过")
                for email in emails[available:]
            )
            emails = emails[:available]

    def _do(email: str) -> tuple[str, dict]:
        return email, adobe_admin.grant_member(
            token=token, org_id=org_id, product_id=product_id,
            license_group_id=lgid, email=email,
            extra_products=extra_products,
            proxy_url=proxy_pool.next_proxy(proxy_raw),
        )

    # 3) 并发执行网络请求(不触碰数据库),回到主线程后统一落库
    s = setting_crud.get_settings(db)
    workers = max(1, min(s.concurrency, len(emails)))
    results: list[tuple[str, dict]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(_do, emails):
            results.append(r)

    items: list[GrantItemResult] = [*skipped_items]
    granted = 0
    for email, res in results:
        ok = bool(res.get("ok"))
        if ok:
            member_crud.upsert(
                db,
                account_id,
                email=email,
                member_id=res.get("member_id") or "",
                status="granted",
                message=res.get("message") or "",
            )
            email_crud.mark_used_by_email(db, email, account.email)
            granted += 1
        elif from_pool:
            email_crud.mark_unused_by_email(db, email)
        else:
            member_crud.upsert(
                db,
                account_id,
                email=email,
                member_id="",
                status="failed",
                message=res.get("message") or "",
            )
        items.append(GrantItemResult(email=email, ok=ok, message=res.get("message") or ""))

    if from_pool:
        email_crud.reconcile_usage_by_emails(db, emails)

    account.member_count = member_crud.count_by_admin(db, account_id)
    db.commit()

    return BatchGrantResult(
        total=len(items), granted=granted, failed=len(items) - granted, items=items
    )


@router.post(
    "/{account_id}/members/batch-disable-emails",
    response_model=MessageResult,
    summary="停用成员对应邮箱",
)
def batch_disable_member_emails(
    account_id: int, payload: BatchIds, db: Session = Depends(get_db)
) -> MessageResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    rows = [
        row
        for row in member_crud.get_many(db, payload.ids)
        if row.admin_id == account_id
    ]
    if not rows:
        return MessageResult(message="没有可停用的成员邮箱")
    count = email_crud.disable_by_emails(
        db, [row.email for row in rows], remark=account.email
    )
    message = f"已停用 {count} 个成员邮箱"
    if count < len(rows):
        message += f",有 {len(rows) - count} 个邮箱未在邮箱管理中找到"
    return MessageResult(message=message)


@router.post(
    "/{account_id}/members/batch-authorize-login",
    response_model=BatchGrantResult,
    summary="授权并刷新选中子号额度",
)
def batch_authorize_login_members(
    account_id: int, payload: BatchIds, db: Session = Depends(get_db)
) -> BatchGrantResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not (
        account.admin_token
        and account.org_id
        and account.product_id
        and account.license_group_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该母号尚未取得管理权限,请先登录/检测母号",
        )
    rows = [
        row
        for row in member_crud.get_many(db, payload.ids)
        if row.admin_id == account_id and not row.is_admin
    ]
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先选择子号")

    proxy_raw, _timeout = _proxy_and_timeout(db)
    try:
        adobe_admin.check_admin(
            token=account.admin_token,
            org_id=account.org_id,
            proxy_url=proxy_pool.next_proxy(proxy_raw),
        )
    except Exception as exc:  # noqa: BLE001
        account.is_valid = False
        account.has_org = False
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"管理 token 已失效,请重新登录:{str(exc)[:200]}",
        ) from exc

    extra_products = adobe_admin.find_complimentary_products(
        token=account.admin_token,
        org_id=account.org_id,
        product_id=account.product_id,
        license_group_id=account.license_group_id,
        proxy_url=proxy_pool.next_proxy(proxy_raw),
    )
    items: list[GrantItemResult] = []
    success = 0
    for row in rows:
        email = row.email
        try:
            granted = adobe_admin.grant_member(
                token=account.admin_token,
                org_id=account.org_id,
                product_id=account.product_id,
                license_group_id=account.license_group_id,
                email=email,
                proxy_url=proxy_pool.next_proxy(proxy_raw),
                extra_products=extra_products,
            )
        except Exception as exc:  # noqa: BLE001
            granted = {"ok": False, "message": str(exc)[:300]}

        if not granted.get("ok"):
            row.status = "needs_authorization"
            row.registered = False
            row.message = f"授权失败:{granted.get('message') or ''}"[:500]
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
            items.append(GrantItemResult(email=email, ok=False, message=row.message))
            continue

        if granted.get("member_id"):
            row.member_id = str(granted.get("member_id") or "")
        row.status = "granted"
        row.message = granted.get("message") or "已授权,正在刷新额度"
        row.updated_at = datetime.now(timezone.utc)

        mail = email_crud.get_by_email(db, email)
        refresh_token = row.refresh_token or (mail.refresh_token if mail else "")
        client_id = row.client_id or (mail.client_id if mail else "")
        mail_url = row.mail_url or (mail.mail_url if mail else "")
        if refresh_token and client_id:
            row.refresh_token = refresh_token
            row.client_id = client_id
            row.mail_url = mail_url or row.mail_url
        db.commit()

        if not ((refresh_token and client_id) or mail_url):
            email_crud.mark_used_by_email(db, email, account.email)
            db.commit()
            msg = "已授权,但缺少收码配置,无法刷新额度"
            row.message = msg
            items.append(GrantItemResult(email=email, ok=False, message=msg))
            continue

        try:
            rec = firefly_ios.login_pool_ff_ios(
                email=email,
                refresh_token=refresh_token,
                client_id=client_id,
                mail_url=mail_url,
                device_id=row.device_id or "",
                proxy_url=proxy_pool.next_proxy(proxy_raw),
                otp_timeout=180,
                use_proxy_for_mail=bool(proxy_raw),
            )
            if rec.get("rotated_refresh_token"):
                refresh_token = rec.get("rotated_refresh_token") or refresh_token
            access_token = rec.get("access_token") or ""
            detail = (
                firefly.fetch_credits_detail(
                    access_token,
                    proxy_url=proxy_pool.next_proxy(proxy_raw),
                )
                if access_token
                else {"ok": False, "credits": None, "message": "未获取 access_token"}
            )
            credits = detail.get("credits")
            team_ready = bool(detail.get("ok") and firefly.has_team_credits(credits))
            row.status = "registered" if team_ready else "needs_authorization"
            row.registered = team_ready
            row.display_name = rec.get("display_name") or row.display_name
            row.access_token = access_token
            row.cookie = rec.get("cookie") or row.cookie
            row.device_token = rec.get("device_token") or row.device_token
            row.device_id = rec.get("device_id") or row.device_id
            row.credits = credits
            row.expires_at = rec.get("expires_at")
            row.refresh_token = refresh_token
            row.client_id = client_id
            if team_ready:
                row.message = f"授权并刷新成功,额度 {credits}"
                success += 1
            else:
                reason = detail.get("message") or f"额度 {credits} 低于团队可用阈值"
                row.message = f"已授权但仍待审批/低额度:{reason}"[:500]
            email_crud.mark_used_by_email(db, email, account.email)
            db.commit()
            items.append(GrantItemResult(email=email, ok=team_ready, message=row.message))
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            row.status = "needs_authorization" if "access_denied" in text else "failed"
            row.registered = False
            row.message = (
                f"待母号审批授权:{text[:220]}"
                if row.status == "needs_authorization"
                else f"登录/刷新失败:{text[:220]}"
            )
            row.updated_at = datetime.now(timezone.utc)
            email_crud.mark_used_by_email(db, email, account.email)
            db.commit()
            items.append(GrantItemResult(email=email, ok=False, message=row.message))

    account.member_count = member_crud.count_by_admin(db, account_id)
    db.commit()
    return BatchGrantResult(
        total=len(items),
        granted=success,
        failed=len(items) - success,
        items=items,
    )


@router.post(
    "/{account_id}/members/batch-delete",
    response_model=MessageResult,
    summary="批量移除子账号",
)
def batch_delete_members(
    account_id: int, payload: BatchIds, db: Session = Depends(get_db)
) -> MessageResult:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")

    proxy_raw, _timeout = _proxy_and_timeout(db)
    rows = member_crud.delete_many(db, account_id, payload.ids)
    if not rows:
        return MessageResult(message="未找到要移除的成员")

    def _can_local_cleanup(row) -> bool:
        status_text = str(row.status or "").strip().lower()
        if status_text in {"failed", "removed_failed"}:
            return True
        try:
            return row.credits is not None and float(row.credits) <= 0
        except (TypeError, ValueError):
            return False

    needs_remote = [row for row in rows if not _can_local_cleanup(row)]
    can_remote = bool(account.admin_token and account.org_id)
    if needs_remote and not can_remote:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="尚未登录,只能本地移除失败/额度用完的成员;正常成员请先登录后再移除",
        )

    removed = 0
    local_cleaned = 0
    remote_failed = 0
    removed_emails: list[str] = []
    for row in rows:
        local_cleanup = _can_local_cleanup(row)
        res = {"ok": False, "message": ""}
        if can_remote:
            try:
                res = adobe_admin.remove_member(
                    token=account.admin_token,
                    org_id=account.org_id,
                    member_id=row.member_id,
                    email=row.email,
                    proxy_url=proxy_pool.next_proxy(proxy_raw),
                )
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "message": str(exc)[:200]}
        if res.get("ok") or local_cleanup:
            removed_emails.append(row.email)
            db.delete(row)
            removed += 1
            if local_cleanup and not res.get("ok"):
                local_cleaned += 1
        else:
            remote_failed += 1
            row.status = "removed_failed"
            row.message = res.get("message") or "移除失败"

    deleted_emails = email_crud.delete_by_emails(
        db,
        removed_emails,
        exclude_emails={account.email},
    )
    account.member_count = member_crud.count_by_admin(db, account_id)
    db.commit()
    message = f"已移除 {removed} / {len(rows)} 个成员"
    if deleted_emails:
        message += f",并删除邮箱管理记录 {deleted_emails} 条"
    if local_cleaned:
        message += f",其中本地清理 {local_cleaned} 个失败/额度用完成员"
    if remote_failed:
        message += f",远端移除失败 {remote_failed} 个"
    return MessageResult(message=message)


@router.post(
    "/{account_id}/members/build-team",
    response_model=JobStatusOut,
    summary="一键拉号:凑满 N 个已注册子号 / 安全补 1 个",
)
def build_team(
    account_id: int, payload: BuildTeamRequest, db: Session = Depends(get_db)
) -> JobStatusOut:
    account = crud.get(db, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not (account.admin_token and account.org_id and account.product_id
            and account.license_group_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该账号尚未取得管理权限,请先登录(并确认已发现组织/产品)",
        )
    existing = JOBS.find_active("build_team", account_id)
    if existing:
        return JobStatusOut(**existing.to_dict())

    count = max(1, min(50, payload.count or 9))
    mode = payload.mode if payload.mode in {"fill", "one_by_one"} else "fill"
    job = JOBS.start(
        "build_team",
        team_builder.build_team_worker,
        meta={"admin_id": account_id, "count": count, "target": count, "mode": mode},
    )
    return JobStatusOut(**job.to_dict())


@router.get("/jobs/{job_id}", response_model=JobStatusOut, summary="查询拉号任务进度")
def get_job(job_id: int, log_offset: int = 0) -> JobStatusOut:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return JobStatusOut(**job.to_dict(log_offset=log_offset))


@router.post(
    "/build-team-batch", response_model=JobStatusOut, summary="批量拉号(多主号)"
)
def build_team_batch(
    payload: BatchBuildTeamRequest, db: Session = Depends(get_db)
) -> JobStatusOut:
    admin_ids = [a for a in dict.fromkeys(payload.admin_ids)]  # 去重保序
    if not admin_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请至少选择一个主号"
        )
    found = {a.id for a in crud.list_by_ids(db, admin_ids)}
    missing = [a for a in admin_ids if a not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"主号不存在:{missing}"
        )
    count = max(1, min(50, payload.count or 9))
    job = JOBS.start(
        "build_team_batch",
        team_builder.build_team_batch_worker,
        meta={"admin_ids": admin_ids, "count": count, "target": count * len(admin_ids)},
    )
    return JobStatusOut(**job.to_dict())


@router.get("/jobs", response_model=list[JobStatusOut], summary="拉号任务列表")
def list_jobs(limit: int = 30) -> list[JobStatusOut]:
    out: list[JobStatusOut] = []
    for job in JOBS.list_recent(limit):
        d = job.to_dict()
        d["logs"] = []  # 列表只看汇总,详情走 /jobs/{id}
        out.append(JobStatusOut(**d))
    return out


@router.post("/jobs/batch-delete", response_model=MessageResult, summary="批量删除拉号任务")
def batch_delete_jobs(payload: BatchIds) -> MessageResult:
    if not payload.ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请先选择要删除的任务"
        )
    deleted, skipped = JOBS.delete_many(payload.ids)
    if skipped and not deleted:
        return MessageResult(
            success=False,
            message=f"进行中的任务不可删除(#{', #'.join(map(str, skipped))})",
        )
    if skipped:
        return MessageResult(
            message=(
                f"已删除 {deleted} 个任务;"
                f"跳过进行中的 #{', #'.join(map(str, skipped))}"
            ),
        )
    return MessageResult(message=f"已删除 {deleted} 个任务")


@router.post(
    "/jobs/{job_id}/cancel", response_model=MessageResult, summary="停止拉号任务"
)
def cancel_job(job_id: int) -> MessageResult:
    ok, message = JOBS.cancel_job(job_id)
    if not ok and message == "任务不存在":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return MessageResult(success=ok, message=message)


@router.post(
    "/jobs/{job_id}/clear-logs", response_model=MessageResult, summary="清空任务日志"
)
def clear_job_logs(job_id: int) -> MessageResult:
    if not JOBS.clear_logs(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return MessageResult(message="已清空任务日志")
