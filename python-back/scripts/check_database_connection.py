from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import Settings  # noqa: E402


def _normalized_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    query = dict(url.query)
    query.pop("ssl", None)
    query.pop("sslmode", None)
    return url.set(query=query)


def _connect_args(mode: str, timeout_seconds: int) -> dict[str, Any]:
    args: dict[str, Any] = {"timeout": max(int(timeout_seconds or 10), 1)}
    if mode == "disable":
        args["ssl"] = False
    elif mode == "require":
        args["ssl"] = True
    return args


def _recommend(error_type: str, mode: str) -> str:
    if error_type in {"InvalidPasswordError", "InvalidAuthorizationSpecificationError"}:
        return "检查 DATABASE_URL 用户名、密码和数据库名。"
    if error_type in {"ConnectionRefusedError", "TimeoutError", "OSError"}:
        return "检查云服务器安全组、防火墙、PostgreSQL listen_addresses 和端口开放。"
    if mode in {"auto", "require"} and error_type in {"ConnectionError", "ConnectionDoesNotExistError"}:
        return "SSL 握手被断开，尝试 DATABASE_SSL=disable；如果 disable 也失败，检查服务端 pg_hba.conf、SSL 配置或中间网络。"
    if mode == "disable" and error_type in {"ConnectionError", "ConnectionDoesNotExistError"}:
        return "非 SSL 连接执行中被断开，检查 pg_hba.conf 是否允许该客户端 IP、服务端日志和云厂商连接策略。"
    return "查看 PostgreSQL 服务端日志，并确认当前客户端 IP 在白名单或 pg_hba.conf 允许范围内。"


async def _probe(raw_url: str, mode: str, timeout_seconds: int) -> dict[str, Any]:
    url = _normalized_url(raw_url)
    engine = create_async_engine(
        url,
        connect_args=_connect_args(mode, timeout_seconds),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=timeout_seconds,
    )
    try:
        async with engine.connect() as conn:
            value = await conn.scalar(text("select 1"))
        return {"mode": mode, "ok": value == 1, "error_type": None, "error": None, "recommendation": None}
    except Exception as exc:
        error_type = type(exc).__name__
        return {
            "mode": mode,
            "ok": False,
            "error_type": error_type,
            "error": str(exc).splitlines()[0],
            "recommendation": _recommend(error_type, mode),
        }
    finally:
        await engine.dispose()


async def main() -> int:
    settings = Settings(_env_file=ROOT_DIR / ".env")
    timeout_seconds = settings.database_connect_timeout_seconds
    redacted_url = _normalized_url(settings.database_url).render_as_string(hide_password=True)
    print(f"Database URL: {redacted_url}")
    print(f"Configured DATABASE_SSL: {settings.database_ssl}")
    print(f"Connect timeout seconds: {timeout_seconds}")
    print("")
    any_ok = False
    for mode in ("auto", "disable", "require"):
        result = await _probe(settings.database_url, mode, timeout_seconds)
        status = "OK" if result["ok"] else "FAILED"
        print(f"[{status}] ssl={mode}")
        if result["error_type"]:
            print(f"  error_type: {result['error_type']}")
            print(f"  error: {result['error']}")
            print(f"  recommendation: {result['recommendation']}")
        else:
            any_ok = True
            print(f"  recommendation: 可设置 DATABASE_SSL={mode}。")
        print("")
    return 0 if any_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
