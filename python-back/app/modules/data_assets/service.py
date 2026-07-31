from datetime import date, datetime, timedelta, timezone
import logging
from uuid import uuid4

from app.core.redis_client import redis_client
from app.modules.data_assets.repository import DataAssetsRepository
from app.modules.data_assets.schemas import (
    AssetDefinition,
    DataAssetCacheStatusReport,
    DataAssetDailyHealthCell,
    DataAssetDailyHealthReport,
    DataAssetDailyHealthRow,
    DataAssetGapReport,
    DataAssetItem,
    DataAssetRefreshResult,
    DataAssetStatus,
    DataAssetSummary,
)


SUMMARY_SNAPSHOT_KEY = "summary"
DAILY_HEALTH_SNAPSHOT_KEY = "daily_health"
DEFAULT_DAILY_HEALTH_DAYS = 3
SNAPSHOT_KEYS = [SUMMARY_SNAPSHOT_KEY, DAILY_HEALTH_SNAPSHOT_KEY]
LAST_GOOD_RETENTION_SECONDS = 48 * 60 * 60
REFRESH_LEASE_SECONDS = 6 * 60

logger = logging.getLogger(__name__)


class DataAssetCacheMissError(RuntimeError):
    """Raised when neither a fresh nor a last-known-good snapshot is available."""


def asset(
    asset_code: str,
    asset_name: str,
    category: str,
    table_name: str,
    frequency: str,
    data_phase: str | None = None,
    producer_job_codes: list[str] | None = None,
    date_column: str | None = None,
    timestamp_column: str | None = None,
    latest_count_column: str | None = None,
    where_clause: str | None = None,
    expected_lag_trade_days: int | None = None,
    approximate_row_count: bool = False,
    coverage_scope: str | None = None,
) -> AssetDefinition:
    return AssetDefinition(
        asset_code=asset_code,
        asset_name=asset_name,
        category=category,
        data_phase=data_phase,
        producer_job_codes=producer_job_codes or [],
        table_name=table_name,
        frequency=frequency,
        date_column=date_column,
        timestamp_column=timestamp_column,
        latest_count_column=latest_count_column,
        where_clause=where_clause,
        expected_lag_trade_days=expected_lag_trade_days,
        approximate_row_count=approximate_row_count,
        coverage_scope=coverage_scope,
    )


ASSET_DEFINITIONS: tuple[AssetDefinition, ...] = (
    AssetDefinition(
        asset_code="stocks",
        asset_name="股票主数据",
        category="master",
        data_phase="主数据",
        producer_job_codes=["sync_stock_basic"],
        table_name="t_stock",
        frequency="master",
        metric_sql={
            "active": "select count(*) from t_stock where status = 'active'",
            "excluded": "select count(*) from t_stock where status = 'excluded'",
            "delisted": "select count(*) from t_stock where status = 'delisted'",
            "suspended": "select count(*) from t_stock where status = 'suspended'",
        },
    ),
    AssetDefinition(
        asset_code="trade_calendar",
        asset_name="交易日历",
        category="master",
        data_phase="主数据",
        producer_job_codes=["sync_trade_calendar"],
        table_name="t_trade_calendar",
        frequency="calendar",
        date_column="trade_date",
        latest_count_column="market",
        where_clause="market = 'CN' and is_open = true",
        metric_sql={"open_days": "select count(*) from t_trade_calendar where market = 'CN' and is_open = true"},
    ),
    AssetDefinition(
        asset_code="sectors",
        asset_name="板块目录",
        category="master",
        data_phase="主数据",
        producer_job_codes=["sync_sector_catalog"],
        table_name="t_sector_basic",
        frequency="master",
        metric_sql={
            "concept": "select count(*) from t_sector_basic where sector_type = 'concept'",
            "industry": "select count(*) from t_sector_basic where sector_type = 'industry'",
        },
    ),
    AssetDefinition(
        asset_code="sector_components",
        asset_name="板块成分股",
        category="master",
        data_phase="主数据",
        producer_job_codes=["sync_sector_catalog"],
        table_name="t_sector_component",
        frequency="master",
        where_clause="end_date is null",
        metric_sql={
            "distinct_sectors": "select count(distinct sector_code) from t_sector_component where end_date is null",
            "distinct_stocks": "select count(distinct stock_code) from t_sector_component where end_date is null",
            "empty_sectors": """
                select count(*)
                from t_sector_basic b
                where not exists (
                    select 1
                    from t_sector_component c
                    where c.sector_code = b.sector_code
                      and c.end_date is null
                )
            """,
        },
    ),
    AssetDefinition(
        asset_code="indexes",
        asset_name="指数主数据",
        category="master",
        data_phase="主数据",
        producer_job_codes=["sync_index_catalog"],
        table_name="t_index_basic",
        frequency="master",
        metric_sql={
            "core_indexes": "select count(*) from t_index_basic where index_code in ('000001','399001','399006','000300','000905','000852','000016')",
            "total_indexes": "select count(*) from t_index_basic",
        },
    ),
    AssetDefinition(
        asset_code="index_components",
        asset_name="指数成分股",
        category="master",
        data_phase="主数据",
        producer_job_codes=["sync_index_catalog"],
        table_name="t_index_component",
        frequency="master",
        metric_sql={
            "distinct_indexes": "select count(distinct index_code) from t_index_component",
            "distinct_stocks": "select count(distinct stock_code) from t_index_component",
            "component_rows": "select count(*) from t_index_component",
            "上证50": "select count(*)::text || '/50' from t_index_component where index_code = '000016'",
            "沪深300": "select count(*)::text || '/300' from t_index_component where index_code = '000300'",
            "中证500": "select count(*)::text || '/500' from t_index_component where index_code = '000905'",
            "中证1000": "select count(*)::text || '/1000' from t_index_component where index_code = '000852'",
            "深证成指": "select count(*)::text || '/500' from t_index_component where index_code = '399001'",
            "创业板指": "select count(*)::text || '/100' from t_index_component where index_code = '399006'",
        },
    ),
    asset("daily_bars", "个股日线", "daily_fact", "t_daily_bar", "daily", "核心收盘", ["daily_close_core_ingest", "backfill_stock_daily_facts"], "trade_date", None, "stock_code", expected_lag_trade_days=2, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("daily_basic", "每日估值与流动性", "daily_fact", "t_stock_daily_basic", "daily", "核心收盘", ["daily_close_core_ingest", "backfill_stock_daily_facts"], "trade_date", None, "stock_code", expected_lag_trade_days=2, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("stock_fund_flow", "个股资金流", "daily_fact", "t_stock_fund_flow_daily", "daily", "核心收盘", ["daily_close_core_ingest", "backfill_stock_daily_facts"], "trade_date", None, "stock_code", expected_lag_trade_days=2, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("stock_adjust_factor", "个股复权因子", "daily_fact", "t_stock_adjust_factor", "daily", "核心收盘", ["daily_close_core_ingest", "daily_close_repair_ingest"], "trade_date", None, "stock_code", expected_lag_trade_days=2, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("limit_events", "涨跌停与停复牌", "daily_fact", "t_limit_event_daily", "daily", "核心收盘", ["daily_close_core_ingest", "backfill_stock_daily_facts"], "trade_date", None, "stock_code", expected_lag_trade_days=2),
    asset("lhb_events", "龙虎榜事件", "daily_fact", "t_lhb_event", "event_daily", "晚间增强", ["daily_close_enrichment_ingest", "daily_close_repair_ingest"], "trade_date", None, "stock_code", expected_lag_trade_days=5),
    asset("index_bars", "核心指数日线", "daily_fact", "t_index_bar", "daily", "核心收盘", ["daily_close_core_ingest", "backfill_index_daily_facts"], "trade_date", None, "index_code", expected_lag_trade_days=2),
    asset("index_daily_basic", "指数每日指标", "daily_fact", "t_index_daily_basic", "daily", "晚间增强", ["daily_close_enrichment_ingest", "daily_close_repair_ingest", "backfill_index_daily_facts"], "trade_date", None, "index_code", expected_lag_trade_days=5),
    asset("market_daily_stats", "市场交易统计", "daily_fact", "t_market_daily_stat", "daily", "晚间增强", ["daily_close_enrichment_ingest", "daily_close_repair_ingest"], "trade_date", None, "ts_code", expected_lag_trade_days=5),
    asset("sector_bars", "板块日线", "daily_fact", "t_sector_bar", "daily", "核心收盘", ["daily_close_core_ingest", "backfill_sector_daily_facts"], "trade_date", None, "sector_code", expected_lag_trade_days=2),
    asset("sector_fund_flow", "板块资金流", "daily_fact", "t_sector_fund_flow_daily", "daily", "晚间增强", ["daily_close_enrichment_ingest", "daily_close_repair_ingest", "backfill_sector_daily_facts"], "trade_date", None, "sector_code", expected_lag_trade_days=5),
    asset("stock_technical_factor", "Tushare 专业技术因子", "daily_fact", "t_stock_technical_factor_daily", "daily", "晚间增强", ["daily_close_enrichment_ingest", "daily_close_repair_ingest", "backfill_stock_daily_facts"], "trade_date", None, "stock_code", expected_lag_trade_days=5, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("minute_bars", "分钟线", "minute_snapshot", "t_minute_bar", "minute", "分钟沉淀", ["daily_close_minute_ingest"], "trade_date", None, "stock_code", expected_lag_trade_days=3, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("stock_factor_daily", "个股日频因子 V1（兼容）", "derived", "t_stock_factor_daily", "daily", "兼容观察", ["daily_close_core_ingest"], "trade_date", None, "stock_code", expected_lag_trade_days=2, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("stock_factor_daily_v2", "个股标准日频因子 V2", "derived", "t_stock_factor_daily_v2", "daily", "增强因子", ["daily_close_enrichment_ingest", "daily_close_repair_ingest", "backfill_stock_daily_factors"], "trade_date", None, "stock_code", "factor_status = 'ready'", expected_lag_trade_days=2, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("provider_ingest_audit", "数据源沉淀审计", "audit", "t_provider_ingest_audit", "event_daily", "接口审计", ["daily_close_core_ingest", "daily_close_enrichment_ingest", "daily_close_repair_ingest"], "trade_date", None, "capability", expected_lag_trade_days=5, approximate_row_count=True),
    asset("stock_factor_minute", "分钟因子", "derived", "t_stock_factor_minute", "minute", "分钟沉淀", ["daily_close_minute_ingest"], "trade_date", None, "stock_code", expected_lag_trade_days=3, approximate_row_count=True, coverage_scope="active_stock_daily"),
    asset("sector_factor_daily", "板块日频因子", "derived", "t_sector_factor_daily", "daily", "增强因子", ["daily_close_enrichment_ingest", "daily_close_repair_ingest", "backfill_sector_daily_factors"], "trade_date", None, "sector_code", expected_lag_trade_days=3),
    asset("index_factor_daily", "指数日频因子", "derived", "t_index_factor_daily", "daily", "历史因子", ["backfill_index_daily_factors"], "trade_date", None, "index_code", expected_lag_trade_days=3),
)

SCHEDULER_JOB_CODES = (
    "sync_trade_calendar",
    "sync_stock_basic",
    "sync_sector_catalog",
    "sync_index_catalog",
    "daily_close_minute_ingest",
    "daily_close_core_ingest",
    "daily_close_enrichment_ingest",
    "daily_close_repair_ingest",
    "backfill_stock_daily_facts",
    "backfill_stock_daily_factors",
    "backfill_sector_daily_facts",
    "backfill_sector_daily_factors",
    "backfill_index_daily_facts",
    "backfill_index_daily_factors",
)


class DataAssetsService:
    def __init__(self, repository: DataAssetsRepository):
        self.repository = repository

    async def cached_summary(self) -> DataAssetSummary:
        payload = await self._read_cached_payload(SUMMARY_SNAPSHOT_KEY)
        if isinstance(payload, dict):
            return DataAssetSummary.model_validate(payload)
        raise DataAssetCacheMissError("资产总览缓存正在生成，请稍后重试。")

    async def cached_daily_health(self, days: int = 3) -> DataAssetDailyHealthReport:
        cache_key = self._daily_health_snapshot_key(days)
        payload = await self._read_cached_payload(cache_key)
        if isinstance(payload, dict):
            return DataAssetDailyHealthReport.model_validate(payload)
        raise DataAssetCacheMissError("交易日完整性缓存正在生成，请稍后重试。")

    async def refresh_cache(self, days: int = 3, snapshot_key: str = "all") -> DataAssetRefreshResult:
        refreshed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        summary_rows = 0
        daily_health_rows = 0
        requested = SNAPSHOT_KEYS if snapshot_key == "all" else [snapshot_key]
        owner = str(uuid4())
        lease_key = await self._refresh_lease_key()
        if not await redis_client.acquire_lease(lease_key, owner, ttl_seconds=REFRESH_LEASE_SECONDS):
            skipped = [self._daily_health_snapshot_key(days) if key == DAILY_HEALTH_SNAPSHOT_KEY else key for key in requested]
            return DataAssetRefreshResult(
                refreshed_keys=[],
                failed_keys=[],
                skipped_keys=skipped,
                refresh_in_progress=True,
                generated_at=datetime.now(timezone.utc),
            )

        try:
            if SUMMARY_SNAPSHOT_KEY in requested:
                try:
                    summary = await self.summary()
                    summary_rows = len(summary.assets)
                    await self._write_success_snapshot(SUMMARY_SNAPSHOT_KEY, summary.model_dump(mode="json"))
                    refreshed.append(SUMMARY_SNAPSHOT_KEY)
                except Exception as exc:
                    logger.exception("data asset summary refresh failed")
                    failed.append(SUMMARY_SNAPSHOT_KEY)
                    await self._write_failed_snapshot(SUMMARY_SNAPSHOT_KEY, exc)
                finally:
                    await self.repository.release_read_transaction()
            if DAILY_HEALTH_SNAPSHOT_KEY in requested:
                cache_key = self._daily_health_snapshot_key(days)
                try:
                    daily_health = await self.daily_health(days=days)
                    daily_health_rows = len(daily_health.rows)
                    await self._write_success_snapshot(cache_key, daily_health.model_dump(mode="json"))
                    refreshed.append(cache_key)
                except Exception as exc:
                    logger.exception("data asset daily health refresh failed: days=%s", days)
                    failed.append(cache_key)
                    await self._write_failed_snapshot(cache_key, exc)
                finally:
                    await self.repository.release_read_transaction()
            return DataAssetRefreshResult(
                refreshed_keys=refreshed,
                failed_keys=failed,
                skipped_keys=skipped,
                summary_rows=summary_rows,
                daily_health_rows=daily_health_rows,
                generated_at=datetime.now(timezone.utc),
            )
        finally:
            await redis_client.release_lease(lease_key, owner)

    async def cache_status(self) -> DataAssetCacheStatusReport:
        return DataAssetCacheStatusReport(
            generated_at=datetime.now(timezone.utc),
            items=[await self._cache_status_item(snapshot_key) for snapshot_key in SNAPSHOT_KEYS],
        )

    async def summary(self) -> DataAssetSummary:
        latest_open_trade_date = await self.repository.latest_open_trade_date()
        assets: list[DataAssetItem] = []
        notes: list[str] = []
        stats_by_code = {}
        coverage_dates: list[date] = []
        coverage_definitions: list[AssetDefinition] = []
        for definition in ASSET_DEFINITIONS:
            stats = await self.repository.table_stats(
                definition,
                skip_latest_count=bool(definition.coverage_scope),
            )
            stats_by_code[definition.asset_code] = stats
            if stats.exists and definition.coverage_scope:
                coverage_date = stats.latest_trade_date
                if coverage_date is None and stats.latest_at is not None:
                    coverage_date = stats.latest_at.date()
                if coverage_date is not None:
                    coverage_dates.append(coverage_date)
                    coverage_definitions.append(definition)

        coverage_map = await self.repository.batch_stock_daily_coverages(
            coverage_definitions,
            list(dict.fromkeys(coverage_dates)),
        )
        for definition in ASSET_DEFINITIONS:
            stats = stats_by_code[definition.asset_code]
            warnings: list[str] = [*stats.warnings]
            stale_days = None
            coverage = None
            if definition.approximate_row_count:
                warnings.append("行数为 PostgreSQL 统计估算；大批量历史写入后应执行 ANALYZE。")
            if not stats.exists:
                warnings.append("表不存在，可能尚未执行对应 SQL。")
                status = self._status("missing")
            else:
                if definition.coverage_scope:
                    coverage_date = stats.latest_trade_date
                    if coverage_date is None and stats.latest_at is not None:
                        coverage_date = stats.latest_at.date()
                    coverage = coverage_map.get((definition.asset_code, coverage_date)) if coverage_date else None
                    if coverage is not None:
                        stats.latest_count = coverage.actual_count
                        if stats.row_count <= 0 and coverage.actual_count > 0:
                            stats.row_count = coverage.actual_count
                if stats.row_count == 0:
                    warnings.append("暂无数据。")
                    status = self._status("empty")
                    assets.append(
                        DataAssetItem(
                            asset_code=definition.asset_code,
                            asset_name=definition.asset_name,
                            category=definition.category,
                            data_phase=definition.data_phase,
                            producer_job_codes=definition.producer_job_codes,
                            table_name=definition.table_name,
                            frequency=definition.frequency,
                            row_count=stats.row_count,
                            row_count_is_estimate=definition.approximate_row_count,
                            latest_trade_date=stats.latest_trade_date,
                            earliest_trade_date=stats.earliest_trade_date,
                            latest_at=stats.latest_at,
                            latest_count=stats.latest_count,
                            stale_trade_days=stale_days,
                            coverage=coverage,
                            status=status,
                            metrics=stats.metrics,
                            warnings=warnings,
                        )
                    )
                    continue
                if definition.expected_lag_trade_days is not None:
                    asset_date = stats.latest_trade_date
                    if asset_date is None and stats.latest_at is not None:
                        asset_date = stats.latest_at.date()
                    if asset_date is None and stats.warnings:
                        status = self._status("limited")
                    else:
                        stale_days = await self.repository.open_trade_days_between(asset_date, latest_open_trade_date)
                        if stale_days is not None and stale_days > definition.expected_lag_trade_days:
                            warnings.append(f"最新数据落后最近交易日 {stale_days} 个交易日。")
                            status = self._status("stale")
                        else:
                            status = self._status("ok")
                elif stats.warnings:
                    status = self._status("limited")
                else:
                    status = self._status("ok")
            if coverage and coverage.missing_count > 0:
                warnings.append(
                    f"最新日真实缺失 {coverage.missing_count} 只；"
                    f"停牌/无交易解释 {coverage.exempt_count} 只；"
                    f"有效完整率 {coverage.effective_completeness_pct or 0}%."
                )
                if status.code == "ok":
                    status = self._status("partial")
            assets.append(
                DataAssetItem(
                    asset_code=definition.asset_code,
                    asset_name=definition.asset_name,
                    category=definition.category,
                    data_phase=definition.data_phase,
                    producer_job_codes=definition.producer_job_codes,
                    table_name=definition.table_name,
                    frequency=definition.frequency,
                    row_count=stats.row_count,
                    row_count_is_estimate=definition.approximate_row_count,
                    latest_trade_date=stats.latest_trade_date,
                    earliest_trade_date=stats.earliest_trade_date,
                    latest_at=stats.latest_at,
                    latest_count=stats.latest_count,
                    stale_trade_days=stale_days,
                    coverage=coverage,
                    status=status,
                    metrics=stats.metrics,
                    warnings=warnings,
                )
            )

        scheduler_runs = await self.repository.latest_scheduler_runs(SCHEDULER_JOB_CODES)
        totals = {
            "assets": len(assets),
            "ok": sum(1 for item in assets if item.status.code == "ok"),
            "warning": sum(1 for item in assets if item.status.code in {"stale", "missing", "limited", "partial"}),
            "empty": sum(1 for item in assets if item.status.code == "empty"),
            "stale": sum(1 for item in assets if item.status.code == "stale"),
            "missing": sum(1 for item in assets if item.status.code == "missing"),
            "limited": sum(1 for item in assets if item.status.code == "limited"),
            "partial": sum(1 for item in assets if item.status.code == "partial"),
        }
        if latest_open_trade_date is None:
            notes.append("未找到最近开市交易日，请先检查 t_trade_calendar。")
        return DataAssetSummary(
            generated_at=datetime.now(timezone.utc),
            latest_open_trade_date=latest_open_trade_date,
            totals=totals,
            assets=assets,
            scheduler_runs=scheduler_runs,
            notes=notes,
        )

    async def daily_health(self, days: int = 3) -> DataAssetDailyHealthReport:
        trade_dates = await self.repository.recent_open_trade_dates(limit=days)
        definitions = [
            definition
            for definition in ASSET_DEFINITIONS
            if definition.coverage_scope == "active_stock_daily"
        ]
        coverage_map = await self.repository.batch_stock_daily_coverages(definitions, trade_dates)
        rows: list[DataAssetDailyHealthRow] = []
        for trade_date in trade_dates:
            cells: list[DataAssetDailyHealthCell] = []
            for definition in definitions:
                coverage = coverage_map.get((definition.asset_code, trade_date))
                if coverage is None:
                    continue
                status = self._daily_health_status(coverage.effective_completeness_pct, coverage.missing_count)
                cells.append(
                    DataAssetDailyHealthCell(
                        asset_code=definition.asset_code,
                        asset_name=definition.asset_name,
                        expected_count=coverage.expected_count,
                        actual_count=coverage.actual_count,
                        exempt_count=coverage.exempt_count,
                        missing_count=coverage.missing_count,
                        effective_completeness_pct=coverage.effective_completeness_pct,
                        status=status,
                    )
                )
            rows.append(DataAssetDailyHealthRow(trade_date=trade_date, cells=cells))
        return DataAssetDailyHealthReport(
            generated_at=datetime.now(timezone.utc),
            trade_dates=trade_dates,
            asset_codes=[definition.asset_code for definition in definitions],
            rows=rows,
        )

    async def stock_daily_gaps(self, asset_code: str, *, trade_date: date | None = None, limit: int = 200) -> DataAssetGapReport:
        definition = self._asset_definition(asset_code)
        if definition.coverage_scope != "active_stock_daily":
            raise ValueError(f"{asset_code} 暂不支持股票缺口下钻")
        target_date = trade_date
        if target_date is None:
            stats = await self.repository.table_stats(definition)
            target_date = stats.latest_trade_date
            if target_date is None and stats.latest_at is not None:
                target_date = stats.latest_at.date()
        if target_date is None:
            raise ValueError(f"{asset_code} 暂无可下钻的最新日期")
        return await self.repository.stock_daily_gap_report(definition, trade_date=target_date, limit=max(1, min(limit, 1000)))

    @staticmethod
    def _asset_definition(asset_code: str) -> AssetDefinition:
        for definition in ASSET_DEFINITIONS:
            if definition.asset_code == asset_code:
                return definition
        raise ValueError(f"未知数据资产: {asset_code}")

    @staticmethod
    def _status(code: str) -> DataAssetStatus:
        mapping = {
            "ok": ("正常", "success"),
            "empty": ("空数据", "warning"),
            "stale": ("滞后", "warning"),
            "partial": ("部分缺失", "warning"),
            "limited": ("待巡检", "warning"),
            "missing": ("缺表", "error"),
        }
        label, level = mapping.get(code, ("未知", "default"))
        return DataAssetStatus(code=code, label=label, level=level)

    @classmethod
    def _daily_health_status(cls, effective_completeness_pct: float | None, missing_count: int) -> DataAssetStatus:
        if missing_count == 0 and (effective_completeness_pct is None or effective_completeness_pct >= 99.5):
            return cls._status("ok")
        if effective_completeness_pct is not None and effective_completeness_pct >= 98:
            return cls._status("partial")
        return cls._status("stale")

    async def _write_success_snapshot(self, snapshot_key: str, payload: dict) -> None:
        generated_at = datetime.now(timezone.utc)
        cache_config = await redis_client.runtime_config()
        ttl_seconds = cache_config.ttl_for(snapshot_key)
        expires_at = generated_at + timedelta(seconds=ttl_seconds)
        meta = {
            "snapshot_key": snapshot_key,
            "status": "success",
            "generated_at": generated_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "refreshed_at": generated_at.isoformat(),
            "error_message": None,
        }
        if cache_config.data_asset_cache_enabled:
            last_good_ttl = max(LAST_GOOD_RETENTION_SECONDS, ttl_seconds * 3)
            await redis_client.set_many_json(
                [
                    (await self._payload_key(snapshot_key), payload, ttl_seconds),
                    (await self._meta_key(snapshot_key), meta, ttl_seconds),
                    (await self._last_good_payload_key(snapshot_key), payload, last_good_ttl),
                    (await self._last_good_meta_key(snapshot_key), meta, last_good_ttl),
                ]
            )

    async def _write_failed_snapshot(self, snapshot_key: str, exc: Exception) -> None:
        cache_config = await redis_client.runtime_config()
        if not cache_config.data_asset_cache_enabled:
            return
        ttl_seconds = cache_config.ttl_for(snapshot_key)
        now = datetime.now(timezone.utc)
        previous = await redis_client.get_json(await self._meta_key(snapshot_key))
        meta = previous if isinstance(previous, dict) else {"snapshot_key": snapshot_key}
        meta.update(
            {
                "status": "failed",
                "refreshed_at": now.isoformat(),
                "error_message": f"{type(exc).__name__}: {exc}",
            }
        )
        await redis_client.set_json(
            await self._meta_key(snapshot_key),
            meta,
            ttl_seconds=ttl_seconds,
        )

    async def _read_cache(self, snapshot_key: str) -> dict | list | None:
        cache_config = await redis_client.runtime_config()
        if not cache_config.data_asset_cache_enabled:
            return None
        return await redis_client.get_json(await self._payload_key(snapshot_key))

    async def _read_cached_payload(self, snapshot_key: str) -> dict | list | None:
        payload = await self._read_cache(snapshot_key)
        if isinstance(payload, (dict, list)):
            return payload
        cache_config = await redis_client.runtime_config()
        if not cache_config.data_asset_cache_enabled:
            return None
        return await redis_client.get_json(await self._last_good_payload_key(snapshot_key))

    async def _cache_status_item(self, snapshot_key: str) -> dict:
        cache_config = await redis_client.runtime_config()
        refresh_in_progress = await self._refresh_in_progress()
        if not cache_config.data_asset_cache_enabled:
            return {
                "snapshot_key": snapshot_key,
                "status": "disabled",
                "generated_at": None,
                "expires_at": None,
                "refreshed_at": None,
                "is_stale": True,
                "has_last_good": False,
                "refresh_in_progress": False,
                "error_message": "DATA_ASSET_CACHE_ENABLED=false",
            }
        payload = await redis_client.get_json(await self._payload_key(snapshot_key))
        meta = await redis_client.get_json(await self._meta_key(snapshot_key))
        ttl = await redis_client.ttl(await self._payload_key(snapshot_key))
        if isinstance(payload, (dict, list)) and isinstance(meta, dict):
            return {
                "snapshot_key": snapshot_key,
                "status": meta.get("status"),
                "generated_at": meta.get("generated_at"),
                "expires_at": meta.get("expires_at"),
                "refreshed_at": meta.get("refreshed_at"),
                "is_stale": ttl is None or ttl <= 0,
                "has_last_good": True,
                "refresh_in_progress": refresh_in_progress,
                "error_message": meta.get("error_message"),
            }

        last_good_payload = await redis_client.get_json(await self._last_good_payload_key(snapshot_key))
        last_good_meta = await redis_client.get_json(await self._last_good_meta_key(snapshot_key))
        if isinstance(last_good_payload, (dict, list)) and isinstance(last_good_meta, dict):
            failure_message = meta.get("error_message") if isinstance(meta, dict) else None
            return {
                "snapshot_key": snapshot_key,
                "status": "building" if refresh_in_progress else "stale",
                "generated_at": last_good_meta.get("generated_at"),
                "expires_at": last_good_meta.get("expires_at"),
                "refreshed_at": last_good_meta.get("refreshed_at"),
                "is_stale": True,
                "has_last_good": True,
                "refresh_in_progress": refresh_in_progress,
                "error_message": failure_message or "正在展示最后一次成功缓存。",
            }
        return {
            "snapshot_key": snapshot_key,
            "status": "building" if refresh_in_progress else "missing",
            "generated_at": None,
            "expires_at": None,
            "refreshed_at": None,
            "is_stale": True,
            "has_last_good": False,
            "refresh_in_progress": refresh_in_progress,
            "error_message": "缓存为空，后台正在生成。" if refresh_in_progress else "缓存为空或不可用，请手动刷新或等待调度预热。",
        }

    @staticmethod
    async def _payload_key(snapshot_key: str) -> str:
        return await redis_client.key("data-assets", snapshot_key)

    @staticmethod
    async def _meta_key(snapshot_key: str) -> str:
        return await redis_client.key("data-assets", f"{snapshot_key}:meta")

    @staticmethod
    async def _last_good_payload_key(snapshot_key: str) -> str:
        return await redis_client.key("data-assets", f"{snapshot_key}:last-good")

    @staticmethod
    async def _last_good_meta_key(snapshot_key: str) -> str:
        return await redis_client.key("data-assets", f"{snapshot_key}:last-good:meta")

    @staticmethod
    async def _refresh_lease_key() -> str:
        return await redis_client.key("data-assets", "refresh-lease")

    async def _refresh_in_progress(self) -> bool:
        ttl = await redis_client.ttl(await self._refresh_lease_key())
        return bool(ttl and ttl > 0)

    @staticmethod
    def _daily_health_snapshot_key(days: int) -> str:
        if days == DEFAULT_DAILY_HEALTH_DAYS:
            return DAILY_HEALTH_SNAPSHOT_KEY
        return f"{DAILY_HEALTH_SNAPSHOT_KEY}:{days}"
