from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


ALLOWED_DAILY_PARTITION_PARENTS = {"t_minute_bar", "t_stock_factor_minute"}
PARTITION_OWNER_FIX_SQL = "docs/sql/18-market-partition-owner-fix.sql"


class MarketPartitionError(RuntimeError):
    """Raised when a market-data partition cannot be prepared by the app user."""

    code = "market_partition_prepare_failed"


def _child_name(parent_table: str, trade_date: date) -> str:
    _validate_parent(parent_table)
    return f"{parent_table}_p_{trade_date:%Y%m%d}"


def _validate_parent(parent_table: str) -> None:
    if parent_table not in ALLOWED_DAILY_PARTITION_PARENTS:
        raise ValueError(f"unsupported market partition parent: {parent_table}")


async def market_partition_exists(session: AsyncSession, *, parent_table: str, trade_date: date) -> bool:
    _validate_parent(parent_table)
    child = _child_name(parent_table, trade_date)
    result = await session.execute(
        text(
            "SELECT 1 "
            "FROM pg_inherits i "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE p.relname = :parent_table AND c.relname = :child_table "
            "LIMIT 1"
        ),
        {"parent_table": parent_table, "child_table": child},
    )
    return result.scalar_one_or_none() is not None


async def ensure_market_partition(session: AsyncSession, *, parent_table: str, trade_date: date) -> bool:
    """Ensure a daily child partition exists.

    Returns True when this call created the partition, False when it already existed.
    """
    _validate_parent(parent_table)
    child = _child_name(parent_table, trade_date)
    if await market_partition_exists(session, parent_table=parent_table, trade_date=trade_date):
        return False

    next_date = trade_date.fromordinal(trade_date.toordinal() + 1)
    try:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {child} PARTITION OF {parent_table} "
                f"FOR VALUES FROM ('{trade_date.isoformat()}') TO ('{next_date.isoformat()}')"
            )
        )
    except SQLAlchemyError as exc:
        try:
            await session.rollback()
        except Exception:
            pass
        detail = await market_partition_diagnostics(session, parent_table=parent_table, child_table=child)
        raise MarketPartitionError(
            "创建行情分区失败："
            f"parent={parent_table}, child={child}, current_user={detail.get('current_user')}, "
            f"parent_owner={detail.get('parent_owner')}, schema_create={detail.get('schema_create')}. "
            f"请使用表 owner/postgres 执行 {PARTITION_OWNER_FIX_SQL} 后重试。原始错误: {exc}"
        ) from exc
    return True


async def ensure_market_partitions(
    session: AsyncSession,
    *,
    trade_date: date,
    include_minute_bar: bool,
    include_minute_factor: bool,
) -> list[str]:
    created: list[str] = []
    if include_minute_bar:
        if await ensure_market_partition(session, parent_table="t_minute_bar", trade_date=trade_date):
            created.append(_child_name("t_minute_bar", trade_date))
    if include_minute_factor:
        if await ensure_market_partition(session, parent_table="t_stock_factor_minute", trade_date=trade_date):
            created.append(_child_name("t_stock_factor_minute", trade_date))
    return created


async def market_partition_diagnostics(session: AsyncSession, *, parent_table: str, child_table: str) -> dict:
    try:
        result = await session.execute(
            text(
                "SELECT current_user, "
                "pg_catalog.pg_get_userbyid(c.relowner) AS parent_owner, "
                "has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create "
                "FROM pg_class c WHERE c.relname = :parent_table LIMIT 1"
            ),
            {"parent_table": parent_table},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return {"current_user": None, "parent_owner": None, "schema_create": None, "child_table": child_table}
        return {
            "current_user": row["current_user"],
            "parent_owner": row["parent_owner"],
            "schema_create": row["schema_create"],
            "child_table": child_table,
        }
    except Exception as exc:  # Diagnostics must never hide the original DDL failure.
        return {"diagnostics_error": str(exc), "child_table": child_table}


def partition_date_from_child_name(child_name: str) -> date | None:
    suffix = str(child_name).rsplit("_p_", 1)[-1]
    try:
        return datetime.strptime(suffix, "%Y%m%d").date()
    except ValueError:
        return None
