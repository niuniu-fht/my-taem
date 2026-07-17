"""极简的内存后台任务管理器(用于拉号等耗时操作的进度/日志展示)。

注意:进程内存储,重启即丢。适合单实例管理后台。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional


class Job:
    def __init__(self, job_id: int, job_type: str, meta: dict[str, Any]):
        self.id = job_id
        self.type = job_type
        self.meta = meta
        self.status = "running"  # running / done / error / cancelled
        self.created_at = int(time.time())
        self.finished_at: int | None = None
        self.logs: list[str] = []
        self.target = int(meta.get("target") or 0)
        self.success = 0
        self.fail = 0
        self.result: Any = None
        self.error = ""
        self.extra: dict[str, Any] = {}
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ---- 供 worker 调用 ----
    def log(self, msg: str) -> None:
        with self._lock:
            self.logs.append(f"{time.strftime('%H:%M:%S')} {msg}")
            if len(self.logs) > 1000:
                self.logs = self.logs[-1000:]

    def bump(self, *, success: int = 0, fail: int = 0) -> None:
        with self._lock:
            self.success += success
            self.fail += fail

    def set_extra(self, key: str, value: Any) -> None:
        with self._lock:
            self.extra[key] = value

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def clear_logs(self) -> None:
        with self._lock:
            self.logs.clear()

    def to_dict(self, *, log_offset: int = 0) -> dict[str, Any]:
        with self._lock:
            logs = self.logs[log_offset:] if log_offset > 0 else self.logs
            return {
                "id": self.id,
                "type": self.type,
                "status": self.status,
                "target": self.target,
                "success": self.success,
                "fail": self.fail,
                "result": self.result,
                "error": self.error,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "log_total": len(self.logs),
                "logs": logs,
                "meta": self.meta,
                "extra": dict(self.extra),
            }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._counter = 0
        self._lock = threading.Lock()

    def start(
        self, job_type: str, worker: Callable[[Job], None], *, meta: dict | None = None
    ) -> Job:
        with self._lock:
            self._counter += 1
            job = Job(self._counter, job_type, meta or {})
            self._jobs[job.id] = job
            # 防止无限增长:仅保留最近 50 个任务
            if len(self._jobs) > 50:
                for k in sorted(self._jobs)[:-50]:
                    self._jobs.pop(k, None)

        def _runner() -> None:
            try:
                worker(job)
                job.status = "done" if job.status == "running" else job.status
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = str(e)[:500]
                job.log(f"任务异常:{e}")
            finally:
                job.finished_at = int(time.time())

        threading.Thread(target=_runner, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: int) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_recent(self, limit: int = 30) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.id, reverse=True)
        return jobs[:limit]

    def find_active(self, job_type: str, admin_id: int) -> Optional[Job]:
        for job in self._jobs.values():
            if (
                job.type == job_type
                and job.status == "running"
                and job.meta.get("admin_id") == admin_id
            ):
                return job
        return None

    def clear_logs(self, job_id: int) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.clear_logs()
        return True

    def cancel_job(self, job_id: int) -> tuple[bool, str]:
        job = self._jobs.get(job_id)
        if not job:
            return False, "任务不存在"
        if job.status != "running":
            return False, "任务已结束,无需停止"
        job.cancel()
        job.log("已请求停止拉号;当前正在进行的单个邮箱会处理完,不会再取新邮箱")
        return True, "已请求停止拉号"

    def delete_many(self, job_ids: list[int]) -> tuple[int, list[int]]:
        """删除任务。进行中的任务会跳过并返回其 ID。"""
        deleted = 0
        skipped_running: list[int] = []
        with self._lock:
            for jid in job_ids:
                job = self._jobs.get(jid)
                if not job:
                    continue
                if job.status == "running":
                    skipped_running.append(jid)
                    continue
                self._jobs.pop(jid, None)
                deleted += 1
        return deleted, skipped_running


JOBS = JobManager()
