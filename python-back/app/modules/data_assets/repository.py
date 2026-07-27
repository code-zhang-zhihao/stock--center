from collections.abc import Iterable
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.data_assets.schemas import (
    AssetDefinition,
    DataAssetCoverage,
    DataAssetGapReport,
    DataAssetGapRow,
    DataAssetMetric,
    SchedulerRunBrief,
    TableStats,
)


class DataAssetsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def latest_open_trade_date(self) -> date | None:
        return await self.session.scalar(
            text(
                """
                select max(trade_date)
                from t_trade_calendar
                where market = 'CN'
                  and is_open = true
                  and trade_date <= current_date
                """
            )
        )

    async def recent_open_trade_dates(self, limit: int = 5) -> list[date]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select trade_date
                    from t_trade_calendar
                    where market = 'CN'
                      and is_open = true
                      and trade_date <= current_date
                    order by trade_date desc
                    limit :limit
                    """
                ),
                {"limit": max(1, min(limit, 30))},
            )
        ).scalars().all()
        return list(rows)

    async def table_stats(self, definition: AssetDefinition, *, skip_latest_count: bool = False) -> TableStats:
        exists = bool(await self.session.scalar(text("select to_regclass(:table_name)"), {"table_name": definition.table_name}))
        if not exists:
            return TableStats(exists=False)

        where_sql = f" where {definition.where_clause}" if definition.where_clause else ""
        if definition.approximate_row_count and not definition.where_clause:
            row_count = await self._estimated_row_count(definition.table_name)
        else:
            row_count = int(await self.session.scalar(text(f"select count(*) from {definition.table_name}{where_sql}")) or 0)

        latest_trade_date = None
        earliest_trade_date = None
        latest_count = None
        warnings: list[str] = []
        if definition.date_column:
            if await self._has_leading_index(definition.table_name, definition.date_column):
                latest_trade_date = await self.session.scalar(
                    text(f"select {definition.date_column} from {definition.table_name}{where_sql} order by {definition.date_column} desc limit 1")
                )
                if latest_trade_date and definition.latest_count_column and not skip_latest_count:
                    latest_where = self._append_where(where_sql, f"{definition.date_column} = :latest_date")
                    latest_count = int(
                        await self.session.scalar(
                            text(f"select count(distinct {definition.latest_count_column}) from {definition.table_name}{latest_where}"),
                            {"latest_date": latest_trade_date},
                        )
                        or 0
                    )
                if definition.approximate_row_count and row_count <= 0 and latest_count:
                    nonempty_partitions = await self._nonempty_partition_count(definition.table_name)
                    if nonempty_partitions > 0:
                        row_count = int(latest_count) * 240 * nonempty_partitions
            else:
                warnings.append(f"{definition.table_name}.{definition.date_column} 缺少前导索引，已跳过最新日期扫描。")

        latest_at = None
        if definition.timestamp_column:
            if await self._has_leading_index(definition.table_name, definition.timestamp_column):
                latest_at = await self.session.scalar(
                    text(f"select {definition.timestamp_column} from {definition.table_name}{where_sql} order by {definition.timestamp_column} desc limit 1")
                )
            else:
                warnings.append(f"{definition.table_name}.{definition.timestamp_column} 缺少前导索引，已跳过最新时间扫描。")

        metrics: list[DataAssetMetric] = []
        for label, sql in definition.metric_sql.items():
            value = await self.session.scalar(text(sql))
            metrics.append(DataAssetMetric(label=label, value=value, unit=definition.metric_units.get(label)))

        return TableStats(
            exists=True,
            row_count=row_count,
            latest_trade_date=latest_trade_date,
            earliest_trade_date=earliest_trade_date,
            latest_at=latest_at,
            latest_count=latest_count,
            metrics=metrics,
            warnings=warnings,
        )

    async def release_read_transaction(self) -> None:
        """Release read locks between independent cache snapshots."""
        await self.session.rollback()

    async def stock_daily_coverage(self, definition: AssetDefinition, trade_date: date | None) -> DataAssetCoverage | None:
        if definition.coverage_scope != "active_stock_daily" or not trade_date:
            return None
        return (await self.batch_stock_daily_coverages([definition], [trade_date])).get((definition.asset_code, trade_date))

    async def batch_stock_daily_coverages(
        self,
        definitions: list[AssetDefinition],
        trade_dates: list[date],
    ) -> dict[tuple[str, date], DataAssetCoverage]:
        definitions = [item for item in definitions if item.coverage_scope == "active_stock_daily" and self._date_predicate(item, "target_date")]
        if not definitions or not trade_dates:
            return {}

        params: dict[str, object] = {f"date_{index}": item for index, item in enumerate(trade_dates)}
        date_placeholders = ", ".join(f":date_{index}" for index in range(len(trade_dates)))
        base_rows = (
            await self.session.execute(
                text(
                    f"""
                    with dates as (
                        select unnest(array[{date_placeholders}]::date[]) as trade_date
                    ),
                    universe as (
                        select stock_code
                        from t_stock
                        where status = 'active'
                          and (
                            exchange in ('SH', 'SZ', 'SSE', 'SZSE')
                            or (
                              coalesce(exchange, '') = ''
                              and (stock_code like '0%' or stock_code like '3%' or stock_code like '6%')
                            )
                          )
                    ),
                    suspended as (
                        select e.trade_date, e.stock_code
                        from t_limit_event_daily e
                        join universe u on u.stock_code = e.stock_code
                        where e.event_type = 'suspend'
                          and e.trade_date in (select trade_date from dates)
                    ),
                    core_actual as (
                        select trade_date, stock_code from t_daily_bar where trade_date in (select trade_date from dates)
                        union
                        select trade_date, stock_code from t_stock_daily_basic where trade_date in (select trade_date from dates)
                        union
                        select trade_date, stock_code from t_stock_fund_flow_daily where trade_date in (select trade_date from dates)
                    ),
                    date_universe as (
                        select d.trade_date, u.stock_code
                        from dates d
                        cross join universe u
                    ),
                    missing_base as (
                        select
                            du.trade_date,
                            du.stock_code,
                            case
                                when s.stock_code is not null then 'suspended_on_trade_date'
                                when ca.stock_code is null then 'no_market_record_on_trade_date'
                                else null
                            end as reason
                        from date_universe du
                        left join suspended s on s.trade_date = du.trade_date and s.stock_code = du.stock_code
                        left join core_actual ca on ca.trade_date = du.trade_date and ca.stock_code = du.stock_code
                    )
                    select
                        d.trade_date,
                        (select count(*) from universe) as expected_count,
                        coalesce(sum(case when m.reason = 'suspended_on_trade_date' then 1 else 0 end), 0) as suspended_count,
                        coalesce(sum(case when m.reason = 'no_market_record_on_trade_date' then 1 else 0 end), 0) as no_market_record_count
                    from dates d
                    left join missing_base m on m.trade_date = d.trade_date
                    group by d.trade_date
                    order by d.trade_date desc
                    """
                ),
                params,
            )
        ).mappings().all()
        base_by_date = {
            row["trade_date"]: {
                "expected_count": int(row["expected_count"] or 0),
                "suspended_count": int(row["suspended_count"] or 0),
                "no_market_record_count": int(row["no_market_record_count"] or 0),
            }
            for row in base_rows
        }

        coverage_map: dict[tuple[str, date], DataAssetCoverage] = {}
        for definition in definitions:
            actual_by_date = await self._actual_counts_by_date(definition, trade_dates)
            for trade_date in trade_dates:
                base = base_by_date.get(trade_date, {"expected_count": 0, "suspended_count": 0, "no_market_record_count": 0})
                expected_count = int(base["expected_count"])
                actual_count = int(actual_by_date.get(trade_date, 0))
                raw_missing_count = max(expected_count - actual_count, 0)
                suspended_count = min(raw_missing_count, int(base["suspended_count"]))
                remaining_missing = max(raw_missing_count - suspended_count, 0)
                no_market_record_count = min(remaining_missing, int(base["no_market_record_count"]))
                exempt_count = suspended_count + no_market_record_count
                missing_count = max(raw_missing_count - exempt_count, 0)
                breakdown = {}
                if suspended_count:
                    breakdown["suspended_on_trade_date"] = suspended_count
                if no_market_record_count:
                    breakdown["no_market_record_on_trade_date"] = no_market_record_count
                if missing_count:
                    breakdown["missing_data"] = missing_count
                completeness_pct = round(actual_count * 100 / expected_count, 2) if expected_count else None
                effective_completeness_pct = round((actual_count + exempt_count) * 100 / expected_count, 2) if expected_count else None
                coverage_map[(definition.asset_code, trade_date)] = DataAssetCoverage(
                    scope="active_stock_daily",
                    trade_date=trade_date,
                    expected_count=expected_count,
                    actual_count=actual_count,
                    exempt_count=exempt_count,
                    missing_count=missing_count,
                    completeness_pct=completeness_pct,
                    effective_completeness_pct=effective_completeness_pct,
                    reason_breakdown=breakdown,
                )
        return coverage_map

    async def _actual_counts_by_date(self, definition: AssetDefinition, trade_dates: list[date]) -> dict[date, int]:
        if not trade_dates:
            return {}
        params: dict[str, object] = {f"date_{index}": item for index, item in enumerate(trade_dates)}
        date_placeholders = ", ".join(f":date_{index}" for index in range(len(trade_dates)))
        stock_column = definition.latest_count_column or "stock_code"
        if definition.date_column:
            date_expr = definition.date_column
            date_filter = f"{definition.date_column} in ({date_placeholders})"
        elif definition.timestamp_column:
            date_expr = f"({definition.timestamp_column} at time zone 'Asia/Shanghai')::date"
            date_filter = f"{date_expr} in ({date_placeholders})"
        else:
            return {}
        where_sql = self._append_condition(date_filter, definition.where_clause)
        if definition.approximate_row_count and definition.frequency == "minute":
            rows = (
                await self.session.execute(
                    text(
                        f"""
                        select {date_expr} as trade_date, ceil(count(*)::numeric / 240)::int as actual_count
                        from {definition.table_name}
                        where {where_sql}
                        group by {date_expr}
                        """
                    ),
                    params,
                )
            ).mappings().all()
            return {row["trade_date"]: int(row["actual_count"] or 0) for row in rows}
        rows = (
            await self.session.execute(
                text(
                    f"""
                    select {date_expr} as trade_date, count(distinct {stock_column}) as actual_count
                    from {definition.table_name}
                    where {where_sql}
                    group by {date_expr}
                    """
                ),
                params,
            )
        ).mappings().all()
        return {row["trade_date"]: int(row["actual_count"] or 0) for row in rows}

    async def stock_daily_gap_report(
        self,
        definition: AssetDefinition,
        *,
        trade_date: date,
        limit: int,
    ) -> DataAssetGapReport:
        date_predicate = self._date_predicate(definition, "target_date")
        if definition.coverage_scope != "active_stock_daily" or not date_predicate:
            raise ValueError(f"{definition.asset_code} 暂不支持股票缺口下钻")
        source_where = self._append_condition(date_predicate, definition.where_clause)
        stock_column = definition.latest_count_column or "stock_code"
        coverage = await self.stock_daily_coverage(definition, trade_date)
        rows = (
            await self.session.execute(
                text(
                    f"""
                    with universe as (
                        select stock_code, stock_name, exchange, status
                        from t_stock
                        where status = 'active'
                          and (
                            exchange in ('SH', 'SZ', 'SSE', 'SZSE')
                            or (
                              coalesce(exchange, '') = ''
                              and (stock_code like '0%' or stock_code like '3%' or stock_code like '6%')
                            )
                          )
                    ),
                    actual as (
                        select distinct {stock_column} as stock_code
                        from {definition.table_name}
                        where {source_where}
                    )
                    select
                        u.stock_code,
                        u.stock_name,
                        u.exchange,
                        u.status,
                        case
                            when exists (
                                select 1
                                from t_limit_event_daily e
                                where e.stock_code = u.stock_code
                                  and e.trade_date = :target_date
                                  and e.event_type = 'suspend'
                            ) then 'suspended_on_trade_date'
                            when not exists (
                                select 1 from t_daily_bar d
                                where d.stock_code = u.stock_code
                                  and d.trade_date = :target_date
                            )
                            and not exists (
                                select 1 from t_stock_daily_basic b
                                where b.stock_code = u.stock_code
                                  and b.trade_date = :target_date
                            )
                            and not exists (
                                select 1 from t_stock_fund_flow_daily f
                                where f.stock_code = u.stock_code
                                  and f.trade_date = :target_date
                            ) then 'no_market_record_on_trade_date'
                            else 'missing_data'
                        end as reason
                    from universe u
                    left join actual a on a.stock_code = u.stock_code
                    where a.stock_code is null
                    order by
                        case
                            when exists (
                                select 1
                                from t_limit_event_daily e
                                where e.stock_code = u.stock_code
                                  and e.trade_date = :target_date
                                  and e.event_type = 'suspend'
                            ) then 1
                            when not exists (
                                select 1 from t_daily_bar d
                                where d.stock_code = u.stock_code
                                  and d.trade_date = :target_date
                            )
                            and not exists (
                                select 1 from t_stock_daily_basic b
                                where b.stock_code = u.stock_code
                                  and b.trade_date = :target_date
                            )
                            and not exists (
                                select 1 from t_stock_fund_flow_daily f
                                where f.stock_code = u.stock_code
                                  and f.trade_date = :target_date
                            ) then 1
                            else 0
                        end,
                        u.stock_code
                    limit :limit
                    """
                ),
                {"target_date": trade_date, "limit": limit},
            )
        ).mappings().all()
        reason_labels = {
            "suspended_on_trade_date": "当日停牌，可解释缺口",
            "no_market_record_on_trade_date": "无日频市场记录，疑似停牌/无交易",
            "missing_data": "真实缺失",
        }
        report_rows = [
            DataAssetGapRow(
                stock_code=str(row["stock_code"]),
                stock_name=row["stock_name"],
                exchange=row["exchange"],
                status=row["status"],
                reason=str(row["reason"]),
                reason_label=reason_labels.get(str(row["reason"]), str(row["reason"])),
            )
            for row in rows
        ]
        expected_count = coverage.expected_count if coverage else 0
        actual_count = coverage.actual_count if coverage else 0
        exempt_count = coverage.exempt_count if coverage else 0
        missing_count = coverage.missing_count if coverage else 0
        reason_breakdown = coverage.reason_breakdown if coverage else {}
        total_gap_count = exempt_count + missing_count
        return DataAssetGapReport(
            asset_code=definition.asset_code,
            asset_name=definition.asset_name,
            table_name=definition.table_name,
            trade_date=trade_date,
            expected_count=expected_count,
            actual_count=actual_count,
            exempt_count=exempt_count,
            missing_count=missing_count,
            reason_breakdown=reason_breakdown,
            rows=report_rows,
            truncated=total_gap_count > len(report_rows),
        )

    async def open_trade_days_between(self, start: date | None, end: date | None) -> int | None:
        if not start or not end or start >= end:
            return 0
        return int(
            await self.session.scalar(
                text(
                    """
                    select count(*)
                    from t_trade_calendar
                    where market = 'CN'
                      and is_open = true
                      and trade_date > :start_date
                      and trade_date <= :end_date
                    """
                ),
                {"start_date": start, "end_date": end},
            )
            or 0
        )

    async def latest_scheduler_runs(self, job_codes: Iterable[str]) -> list[SchedulerRunBrief]:
        codes = [code for code in job_codes if code]
        if not codes:
            return []
        params = {f"code_{index}": code for index, code in enumerate(codes)}
        placeholders = ", ".join(f":{key}" for key in params)
        rows = (
            await self.session.execute(
                text(
                    f"""
                    select distinct on (j.job_code)
                        j.job_code,
                        j.job_name,
                        r.status,
                        r.started_at,
                        r.finished_at,
                        r.error_code,
                        r.error_message
                    from t_scheduler_job j
                    left join t_scheduler_job_run r on r.job_code = j.job_code
                    where j.job_code in ({placeholders})
                    order by j.job_code, r.started_at desc nulls last
                    """
                ),
                params,
            )
        ).mappings().all()
        return [SchedulerRunBrief(**dict(row)) for row in rows]

    @staticmethod
    def _append_where(where_sql: str, condition: str) -> str:
        if where_sql:
            return f"{where_sql} and {condition}"
        return f" where {condition}"

    @staticmethod
    def _append_condition(condition: str, extra_condition: str | None) -> str:
        if extra_condition:
            return f"{condition} and {extra_condition}"
        return condition

    @staticmethod
    def _date_predicate(definition: AssetDefinition, bind_name: str) -> str | None:
        if definition.date_column:
            return f"{definition.date_column} = :{bind_name}"
        if definition.timestamp_column:
            return f"({definition.timestamp_column} at time zone 'Asia/Shanghai')::date = :{bind_name}"
        return None

    async def _estimated_row_count(self, table_name: str) -> int:
        value = await self.session.scalar(
            text(
                """
                with rels as (
                    select to_regclass(:table_name)::oid as oid
                    union
                    select inhrelid
                    from pg_inherits
                    where inhparent = to_regclass(:table_name)
                )
                select greatest(coalesce(sum(c.reltuples), 0), 0)::bigint
                from pg_class c
                join rels r on r.oid = c.oid
                """
            ),
            {"table_name": table_name},
        )
        return int(value or 0)

    async def _has_leading_index(self, table_name: str, column_name: str) -> bool:
        return bool(
            await self.session.scalar(
                text(
                    """
                    select exists (
                        select 1
                        from pg_indexes
                        where schemaname = 'public'
                          and tablename = :table_name
                          and regexp_replace(indexdef, '\\s+', ' ', 'g') ~ :pattern
                    )
                    """
                ),
                {"table_name": table_name, "pattern": rf"\({column_name}( DESC)?(,|\))"},
            )
        )

    async def _nonempty_partition_count(self, table_name: str) -> int:
        value = await self.session.scalar(
            text(
                """
                select count(*)
                from pg_class c
                join pg_inherits i on i.inhrelid = c.oid
                where i.inhparent = to_regclass(:table_name)
                  and pg_total_relation_size(c.oid) > 1024 * 1024
                """
            ),
            {"table_name": table_name},
        )
        return int(value or 0)
