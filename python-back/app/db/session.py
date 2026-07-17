from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


def database_connect_args() -> dict:
    settings = get_settings()
    connect_args: dict = {"timeout": max(int(settings.database_connect_timeout_seconds or 10), 1)}
    if settings.database_ssl == "disable":
        connect_args["ssl"] = False
    elif settings.database_ssl == "require":
        connect_args["ssl"] = True
    return connect_args


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        connect_args=database_connect_args(),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_use_lifo=True,
        echo_pool=settings.database_echo_pool,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


def get_pool_status() -> str:
    return get_engine().sync_engine.pool.status()


async def check_database_health() -> dict:
    try:
        async with get_engine().connect() as conn:
            value = await conn.scalar(text("select 1"))
        return {
            "status": "ok",
            "ok": value == 1,
            "error_type": None,
            "error": None,
            "pool_status": get_pool_status(),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc).splitlines()[0],
            "pool_status": _safe_pool_status(),
        }


def _safe_pool_status() -> str | None:
    try:
        return get_pool_status()
    except Exception:
        return None


async def dispose_engine() -> None:
    await get_engine().dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async_session_local = get_sessionmaker()
    async with async_session_local() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
