from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmailBase(BaseModel):
    email: str
    password: str = ""
    refresh_token: str = ""
    client_id: str = ""
    mail_url: str = ""
    remark: str = ""


class EmailCreate(EmailBase):
    pass


class EmailUpdate(BaseModel):
    email: str | None = None
    password: str | None = None
    refresh_token: str | None = None
    client_id: str | None = None
    mail_url: str | None = None
    is_used: bool | None = None
    is_disabled: bool | None = None
    remark: str | None = None


class CheckedEmailImportRequest(BaseModel):
    content: str
    on_duplicate: str = "skip"
    check_mail: bool = True


class CheckedEmailImportItem(BaseModel):
    line_no: int
    email: str = ""
    success: bool
    message: str
    source: str = ""


class CheckedEmailImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    checked: int = 0
    passed: int = 0
    rejected: int = 0
    errors: list[str] = []
    checks: list[CheckedEmailImportItem] = []


class MoeMailGenerateRequest(BaseModel):
    api_key: str = Field(min_length=1)
    count: int = Field(default=1, ge=1, le=500)
    domain: str = "edu6.site"
    name_prefix: str = ""
    expiry_time: int = 0
    password: str = ""
    on_duplicate: str = "overwrite"


class EmailOut(EmailBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_used: bool
    is_disabled: bool = False
    used_at: datetime | None
    created_at: datetime


class MailSummaryOut(BaseModel):
    id: str
    subject: str = ""
    from_addr: str = ""
    date: str = ""
    folder: str = ""
    preview: str = ""
    is_read: bool | None = None
    source: str = ""


class MailListOut(BaseModel):
    success: bool
    message: str
    source: str = ""
    messages: list[MailSummaryOut] = []


class MailDetailOut(BaseModel):
    success: bool
    message: str
    subject: str = ""
    from_addr: str = ""
    to_addr: str = ""
    date: str = ""
    body_html: str = ""
    body_text: str = ""
