from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    proxy_enabled: bool = False
    proxy_url: str = ""
    concurrency: int = 5
    request_timeout: int = 30
    register_country: str = "SG"
    register_locale: str = "en_US"
    # 号池默认导出格式:token(FF-iOS 全量) / cookie(纯 CK)
    export_format: str = "token"


class SettingsUpdate(BaseModel):
    proxy_enabled: bool | None = None
    proxy_url: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=1000)
    request_timeout: int | None = Field(default=None, ge=1, le=600)
    register_country: str | None = Field(default=None, min_length=2, max_length=2)
    register_locale: str | None = Field(default=None, min_length=2, max_length=10)
    export_format: str | None = Field(default=None, pattern="^(token|cookie)$")


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class ProxyTestRequest(BaseModel):
    # 留空则测试当前已保存的代理配置;否则测试传入的多行文本
    proxy_url: str | None = None


class ProxyTestItem(BaseModel):
    proxy: str
    ok: bool
    ip: str = ""
    latency_ms: int = 0
    message: str = ""


class ProxyTestResult(BaseModel):
    total: int = 0
    ok_count: int = 0
    items: list[ProxyTestItem] = []
