from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import Setting
from app.schemas.setting import SettingsOut, SettingsUpdate

DEFAULTS: dict[str, str] = {
    "proxy_enabled": "false",
    "proxy_url": "",
    "concurrency": "5",
    "request_timeout": "30",
    # 注册/补全账号所用的地区与语言。US 区会被 Adobe 的 firefly_geoip_blocking
    # 及第三方模型(gemini/gpt-image)地区灰度挡掉,SG(新加坡)实测放行。
    "register_country": "SG",
    "register_locale": "en_US",
    # 号池默认导出格式:token=FF-iOS 全量(cookie+access_token+device_token),
    # cookie=纯 CK 格式([{cookie, name}])。
    "export_format": "token",
}


def _get_all(db: Session) -> dict[str, str]:
    rows = db.scalars(select(Setting)).all()
    data = dict(DEFAULTS)
    for row in rows:
        data[row.key] = row.value
    return data


def get_settings(db: Session) -> SettingsOut:
    data = _get_all(db)
    return SettingsOut(
        proxy_enabled=data["proxy_enabled"].lower() == "true",
        proxy_url=data["proxy_url"],
        concurrency=int(data["concurrency"] or 5),
        request_timeout=int(data["request_timeout"] or 30),
        register_country=data["register_country"] or "SG",
        register_locale=data["register_locale"] or "en_US",
        export_format=(data.get("export_format") or "token").lower(),
    )


def _set(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def update_settings(db: Session, data: SettingsUpdate) -> SettingsOut:
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        _set(db, key, str(value))
    db.commit()
    return get_settings(db)
