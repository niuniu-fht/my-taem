"""Shared member removal workflow used by the UI and replacement jobs."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.crud import adobe_member as member_crud
from app.crud import email as email_crud
from app.services import adobe_admin, proxy_pool


class MemberRemovalError(RuntimeError):
    """A member cannot be removed with the currently available credentials."""


def remove_members(
    db: Session,
    account,
    rows: Sequence,
    proxy_raw: str,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, int | str]:
    """Remove members remotely when possible and clean up local records.

    This is intentionally the same workflow used by the existing batch-remove
    endpoint.  ``log`` is optional so background jobs can expose each step.
    """

    rows = list(rows)
    if not rows:
        return {
            "total": 0,
            "removed": 0,
            "local_cleaned": 0,
            "remote_failed": 0,
            "message": "未找到要移除的成员",
        }

    def emit(message: str) -> None:
        if log:
            log(message)

    def can_local_cleanup(row) -> bool:
        status_text = str(row.status or "").strip().lower()
        if status_text in {"failed", "removed_failed"}:
            return True
        try:
            return row.credits is not None and float(row.credits) <= 0
        except (TypeError, ValueError):
            return False

    needs_remote = [row for row in rows if not can_local_cleanup(row)]
    can_remote = bool(account.admin_token and account.org_id)
    if needs_remote and not can_remote:
        raise MemberRemovalError(
            "尚未登录,只能本地移除失败/额度用完的成员;正常成员请先登录后再移除"
        )

    removed = 0
    local_cleaned = 0
    remote_failed = 0
    removed_emails: list[str] = []
    for row in rows:
        local_cleanup = can_local_cleanup(row)
        email = str(row.email or "").strip()
        emit(f"开始移除子号 [{email}] …")
        result = {"ok": False, "message": ""}
        if can_remote:
            try:
                result = adobe_admin.remove_member(
                    token=account.admin_token,
                    org_id=account.org_id,
                    member_id=row.member_id,
                    email=email,
                    proxy_url=proxy_pool.next_proxy(proxy_raw),
                )
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "message": str(exc)[:200]}
        if result.get("ok") or local_cleanup:
            removed_emails.append(email)
            db.delete(row)
            removed += 1
            if local_cleanup and not result.get("ok"):
                local_cleaned += 1
                emit(f"✓ [{email}] 远端未调用,已本地清理失败/额度用完记录")
            else:
                emit(f"✓ [{email}] 已从母号移除")
        else:
            remote_failed += 1
            row.status = "removed_failed"
            row.message = result.get("message") or "移除失败"
            emit(f"✗ [{email}] 移除失败:{row.message}")

    deleted_emails = email_crud.delete_by_emails(
        db,
        removed_emails,
        exclude_emails={account.email},
    )
    account.member_count = member_crud.count_by_admin(db, account.id)
    db.commit()

    message = f"已移除 {removed} / {len(rows)} 个成员"
    if deleted_emails:
        message += f",并删除邮箱管理记录 {deleted_emails} 条"
    if local_cleaned:
        message += f",其中本地清理 {local_cleaned} 个失败/额度用完成员"
    if remote_failed:
        message += f",远端移除失败 {remote_failed} 个"
    emit(message)
    return {
        "total": len(rows),
        "removed": removed,
        "local_cleaned": local_cleaned,
        "remote_failed": remote_failed,
        "message": message,
    }
