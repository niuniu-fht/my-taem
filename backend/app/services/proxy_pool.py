"""多代理支持:一行一个,外呼时轮换(round-robin)使用。

设置里的 ``proxy_url`` 现在是多行文本,每行一个代理,例如::

    user:pass@host:port
    socks5://host:port
    http://user:pass@host:port

没写协议头的默认按 ``http://`` 处理。每次取号/请求会按轮询取下一个,
这样多个并发子号会分散到不同出口 IP。
"""

from __future__ import annotations

import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

try:
    from curl_cffi import requests as _http

    _HAS_CFFI = True
    from app.services.adobe_protocol.http_client import IMPERSONATE_TARGET
except ImportError:  # pragma: no cover
    import requests as _http  # type: ignore

    _HAS_CFFI = False
    IMPERSONATE_TARGET = "chrome124"

# 测试代理出口 IP 用的回显服务(返回纯 IP 文本)
_IP_ECHO_URL = "https://api.ipify.org"

_lock = threading.Lock()
_cycle: Optional["itertools.cycle"] = None
_signature: tuple[str, ...] = ()


def parse_proxies(raw: str) -> list[str]:
    """把多行文本解析成规范化的代理 URL 列表(自动补 http:// 头)。"""
    out: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "://" not in s:
            s = "http://" + s
        out.append(s)
    return out


def next_proxy(raw: str) -> str:
    """轮询返回下一个代理 URL;没有配置时返回空串。

    代理列表变化时会自动重建轮询游标。
    """
    proxies = parse_proxies(raw)
    if not proxies:
        return ""
    global _cycle, _signature
    with _lock:
        sig = tuple(proxies)
        if sig != _signature or _cycle is None:
            _signature = sig
            _cycle = itertools.cycle(sig)
        return next(_cycle)


def pick(settings) -> str:
    """根据设置对象选下一个代理(未启用或为空 → 空串)。"""
    if not getattr(settings, "proxy_enabled", False):
        return ""
    return next_proxy(getattr(settings, "proxy_url", "") or "")


def proxy_count(raw: str) -> int:
    return len(parse_proxies(raw))


def mask(proxy: str) -> str:
    """隐藏代理里的密码,便于在前端展示。"""
    try:
        scheme, rest = proxy.split("://", 1)
    except ValueError:
        scheme, rest = "", proxy
    if "@" in rest:
        creds, host = rest.rsplit("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            creds = f"{user}:***"
        rest = f"{creds}@{host}"
    return f"{scheme}://{rest}" if scheme else rest


def test_one(proxy: str, timeout: int = 12) -> dict:
    """通过单个代理请求 IP 回显服务,返回出口 IP / 延迟 / 错误。"""
    start = time.time()
    try:
        if _HAS_CFFI:
            resp = _http.get(
                _IP_ECHO_URL,
                proxies={"http": proxy, "https": proxy},
                timeout=timeout,
                verify=False,
                impersonate=IMPERSONATE_TARGET,
            )
        else:
            resp = _http.get(
                _IP_ECHO_URL,
                proxies={"http": proxy, "https": proxy},
                timeout=timeout,
            )
        latency = int((time.time() - start) * 1000)
        if resp.status_code != 200:
            return {
                "proxy": mask(proxy), "ok": False, "ip": "", "latency_ms": latency,
                "message": f"HTTP {resp.status_code}",
            }
        ip = (resp.text or "").strip()[:64]
        return {
            "proxy": mask(proxy), "ok": True, "ip": ip,
            "latency_ms": latency, "message": "",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "proxy": mask(proxy), "ok": False, "ip": "",
            "latency_ms": int((time.time() - start) * 1000),
            "message": str(e)[:200],
        }


def test_all(raw: str, *, timeout: int = 12, max_workers: int = 8) -> list[dict]:
    """并发测试多行代理,保持输入顺序返回结果。"""
    proxies = parse_proxies(raw)
    if not proxies:
        return []
    workers = max(1, min(max_workers, len(proxies)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda p: test_one(p, timeout=timeout), proxies))
