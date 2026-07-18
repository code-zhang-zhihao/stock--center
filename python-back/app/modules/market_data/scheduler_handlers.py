from app.db.session import get_sessionmaker
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.indicator_engine.backfill import FactorBackfillRequest, FactorBackfillService
from app.modules.market_data.close_ingest import DailyMarketCloseIngestRequest, DailyMarketCloseIngestService
from app.modules.market_data.entity_history_backfill import (
    IndexDailyFactsBackfillRequest,
    IndexDailyFactsBackfillService,
    SectorDailyFactsBackfillRequest,
    SectorDailyFactsBackfillService,
)
from app.modules.market_data.history_backfill import StockDailyBackfillRequest, StockDailyBackfillService
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.sync_service import (
    CORE_INDEX_DEFINITIONS,
    IndexCatalogSyncRequest,
    MarketDataSyncError,
    MarketDataSyncService,
    SectorCatalogSyncRequest,
    StockBasicSyncRequest,
    TradeCalendarSyncRequest,
)
from app.modules.scheduler_center.handlers import JobExecutionContext, job_handler_registry
from app.modules.scheduler_center.schemas import JobResult


class SyncSectorCatalogHandler:
    job_code = "sync_sector_catalog"
    job_type = "market_data"
    parameter_schema = {
        "sector_types": {
            "label": "板块类型",
            "type": "array",
            "default": ["concept", "industry"],
            "required": False,
            "description": "同步哪些板块类型。第一版支持 concept 和 industry。",
            "options": ["concept", "industry"],
        },
        "sync_components": {
            "label": "同步成分股",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "是否同步板块与股票关联关系。",
        },
        "limit_sectors": {
            "label": "板块上限",
            "type": "number",
            "required": False,
            "description": "调试时限制每类同步多少个板块；为空表示全量。",
        },
        "max_concurrency": {
            "label": "最大并发",
            "type": "number",
            "default": 1,
            "required": False,
            "description": "外部 provider 成分股查询并发数；同花顺回退源建议保持 1。",
        },
        "source": {
            "label": "数据源",
            "type": "string",
            "default": "tushare",
            "required": False,
            "options": ["tushare", "akshare"],
            "description": "Tushare Pro 为主源；无可用 Token 或权限失败时可手动切换 AkShare。",
        },
        "delete_missing_components": {
            "label": "删除缺失成分",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "仅当单板块返回完整快照时，物理删除本次未出现的旧关联。",
        },
        "ths_request_interval_seconds": {
            "label": "同花顺请求间隔秒数",
            "type": "number",
            "default": 0.8,
            "required": False,
            "description": "同花顺每次请求之间的最小间隔，降低 403 限流概率。",
        },
        "provider_timeout_seconds": {
            "label": "Provider 超时秒数",
            "type": "number",
            "default": 45,
            "required": False,
            "description": "单次外部 provider 请求超时时间，防止任务长期卡在外部网络。",
        },
    }
    default_payload = {
        "sector_types": ["concept", "industry"],
        "sync_components": True,
        "limit_sectors": None,
        "max_concurrency": 1,
        "source": "tushare",
        "delete_missing_components": True,
        "ths_request_interval_seconds": 0.8,
        "provider_timeout_seconds": 45,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = SectorCatalogSyncRequest(**{**self.default_payload, **context.payload})
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = MarketDataSyncService(MarketDataRepository(session))
            result = await service.sync_sector_catalog(payload)
        return JobResult(affected_rows=result.sector_count + result.component_count, summary=result.model_dump(mode="json"))


class SyncTradeCalendarHandler:
    job_code = "sync_trade_calendar"
    job_type = "market_data"
    parameter_schema = {
        "year": {
            "label": "同步年份",
            "type": "number",
            "required": False,
            "description": "生成并同步哪一年的 CN 交易日历；为空时使用当前年份。",
            "min": 1990,
            "max": 2100,
        },
        "market": {
            "label": "市场",
            "type": "string",
            "default": "CN",
            "required": False,
            "options": ["CN"],
            "description": "当前 A 股流程固定使用 CN。",
        },
        "mode": {
            "label": "写入模式",
            "type": "string",
            "default": "upsert",
            "required": False,
            "options": ["upsert", "rebuild"],
            "description": "upsert 会增量覆盖同年日期；rebuild 会先删除该年再重建。",
        },
        "source": {
            "label": "来源",
            "type": "string",
            "default": "chinese_calendar",
            "required": False,
            "description": "沿用旧项目逻辑：周一到周五且 chinese_calendar 判断为中国法定工作日即开市。",
        },
    }
    default_payload = {
        "year": None,
        "market": "CN",
        "mode": "upsert",
        "source": "chinese_calendar",
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        payload_data = {**self.default_payload, **context.payload}
        if payload_data.get("year") is None:
            payload_data["year"] = datetime.now(ZoneInfo("Asia/Shanghai")).year
        payload = TradeCalendarSyncRequest(**payload_data)
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = MarketDataSyncService(MarketDataRepository(session))
            result = await service.sync_trade_calendar(payload)
            await session.commit()
        return JobResult(
            affected_rows=result.upserted_count,
            summary=result.model_dump(mode="json"),
        )


class SyncStockBasicHandler:
    job_code = "sync_stock_basic"
    job_type = "market_data"
    parameter_schema = {
        "source": {
            "label": "主数据源",
            "type": "string",
            "default": "tushare",
            "required": False,
            "options": ["tushare", "akshare", "mootdx"],
            "description": "Tushare 为状态最高优先级来源；AkShare/MooTDX fallback 只补沪深 active 列表。",
        },
        "include_detail": {
            "label": "补充详情",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "是否渐进补充行业、上市日期和更名信息。",
        },
        "detail_mode": {
            "label": "详情模式",
            "type": "string",
            "default": "missing_or_stale",
            "required": False,
            "options": ["missing_or_stale", "missing", "stale", "all", "none"],
            "description": "选择补充缺失、过期或全部详情。",
        },
        "max_detail_per_run": {
            "label": "详情补充上限",
            "type": "number",
            "default": 300,
            "required": False,
            "description": "单次最多补充多少只股票详情。",
        },
        "detail_refresh_days": {
            "label": "详情刷新天数",
            "type": "number",
            "default": 90,
            "required": False,
            "description": "超过多少天视为详情过期。",
        },
        "fallback_to_mootdx": {
            "label": "启用 fallback",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "AkShare 列表失败或异常时是否降级 MooTDX。",
        },
        "mark_delisted": {
            "label": "标记退市",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "是否根据明确退市数据更新 delisted 状态。",
        },
        "min_expected_count": {
            "label": "最小返回数量",
            "type": "number",
            "default": 3000,
            "required": False,
            "description": "AkShare 返回数量低于该值时视为异常。",
        },
        "provider_timeout_seconds": {
            "label": "Provider 超时秒数",
            "type": "number",
            "default": 120,
            "required": False,
            "description": "单次外部 provider 请求超时时间，AkShare 超时后可 fallback 到 MooTDX。",
        },
    }
    default_payload = {
        "source": "tushare",
        "include_detail": True,
        "detail_mode": "missing_or_stale",
        "max_detail_per_run": 300,
        "detail_refresh_days": 90,
        "fallback_to_mootdx": True,
        "mark_delisted": True,
        "min_expected_count": 3000,
        "provider_timeout_seconds": 120,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = StockBasicSyncRequest(**{**self.default_payload, **context.payload})
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = MarketDataSyncService(MarketDataRepository(session))
            try:
                result = await service.sync_stock_basic(payload)
            except MarketDataSyncError:
                raise
        return JobResult(
            affected_rows=result.upserted_count + result.detail_enriched_count + result.delisted_marked_count,
            summary=result.model_dump(mode="json"),
        )


class SyncIndexCatalogHandler:
    job_code = "sync_index_catalog"
    job_type = "market_data"
    _default_index_codes = list(CORE_INDEX_DEFINITIONS.keys())
    _default_component_codes = [
        code for code, definition in CORE_INDEX_DEFINITIONS.items() if definition.get("component_required")
    ]
    parameter_schema = {
        "index_codes": {
            "label": "核心指数代码",
            "type": "array",
            "default": _default_index_codes,
            "required": False,
            "description": "需要同步基础资料的指数代码，使用 Tushare 官方代码，例如 000300.SH。",
        },
        "sync_components": {
            "label": "同步指数成分",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "是否同步指数成分股。上证综指这类宽市场指数默认不拉成分。",
        },
        "component_index_codes": {
            "label": "成分指数代码",
            "type": "array",
            "default": _default_component_codes,
            "required": False,
            "description": "需要同步成分股的指数代码；为空时使用核心指数中的成分型指数。",
        },
        "weight_lookback_months": {
            "label": "权重回看月数",
            "type": "number",
            "default": 3,
            "required": False,
            "min": 1,
            "max": 24,
            "description": "Tushare index_weight 按最近几个自然月查询，并取最新完整 trade_date 作为当前指数成分。",
        },
        "source": {
            "label": "主数据源",
            "type": "string",
            "default": "tushare",
            "required": False,
            "options": ["tushare", "akshare"],
            "description": "Tushare 为指数基础和权重主源；AkShare 可作为 fallback。",
        },
        "fallback_to_akshare": {
            "label": "启用 AkShare fallback",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "Tushare 无权限、返回空或失败时，是否尝试 AkShare 成分接口。",
        },
        "provider_timeout_seconds": {
            "label": "Provider 超时秒数",
            "type": "number",
            "default": 120,
            "required": False,
            "min": 5,
            "max": 600,
            "description": "单个指数基础/成分请求的超时时间。",
        },
    }
    default_payload = {
        "index_codes": _default_index_codes,
        "sync_components": True,
        "component_index_codes": _default_component_codes,
        "weight_lookback_months": 3,
        "source": "tushare",
        "fallback_to_akshare": True,
        "provider_timeout_seconds": 120,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = IndexCatalogSyncRequest(**{**self.default_payload, **context.payload})
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = MarketDataSyncService(MarketDataRepository(session))
            result = await service.sync_index_catalog(payload)
        return JobResult(
            affected_rows=result.index_count + result.component_count,
            summary=result.model_dump(mode="json"),
        )


class BackfillStockDailyFactsHandler:
    job_code = "backfill_stock_daily_facts"
    job_type = "market_data"
    parameter_schema = {
        "pool_code": {
            "label": "股票池编码",
            "type": "string",
            "default": "all_a_share",
            "required": True,
            "description": "指定需要回填四类个股日频事实的股票池；all_a_share 表示沪深 active 动态全市场。",
        },
        "start_date": {
            "label": "开始日期",
            "type": "string",
            "default": "2024-01-01",
            "required": True,
            "description": "日线、daily_basic、资金流和专业技术因子回填开始日期，格式 YYYY-MM-DD。",
        },
        "end_date": {
            "label": "结束日期",
            "type": "string",
            "required": False,
            "description": "为空时使用交易日历中的最近开市日。",
        },
        "ingest_mode": {
            "label": "入库模式",
            "type": "string",
            "default": "append_safe",
            "required": False,
            "options": ["append_safe", "rebuild"],
            "description": "append_safe 幂等补缺，不重复入库；rebuild 会先删除目标股票池和日期范围内的本类数据再重建。",
        },
        "only_missing": {
            "label": "只补缺失",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "兼容参数：append_safe 模式下为 true 表示只补缺失；rebuild 模式会忽略它。",
        },
        "max_stocks": {
            "label": "股票数量上限",
            "type": "number",
            "required": False,
            "min": 1,
            "description": "调试时限制回填股票数量；为空表示整个股票池。",
        },
        "workers": {
            "label": "并发 worker 数",
            "type": "number",
            "default": 12,
            "required": False,
            "min": 1,
            "max": 20,
            "description": "每个事实阶段并发逐股调用 Tushare 的 worker 数；默认 12，仍受 Token 池实际限频控制。",
        },
        "commit_stock_batch_size": {
            "label": "提交批次股票数",
            "type": "number",
            "default": 20,
            "required": False,
            "min": 1,
            "max": 200,
            "description": "每个 worker 累积多少只股票的数据后提交一次；底层 upsert 仍会按 PostgreSQL 参数上限拆分。",
        },
        "max_upsert_rows_per_commit": {
            "label": "单次提交最大行数",
            "type": "number",
            "default": 5000,
            "required": False,
            "min": 100,
            "max": 50000,
            "description": "每个 worker 单次事务最多提交的行数；四个接口仍按单股完整日期区间各请求一次。",
        },
        "fail_fast": {
            "label": "遇错立即失败",
            "type": "boolean",
            "default": False,
            "required": False,
            "description": "关闭时单只股票失败只记录错误并继续其他股票。",
        },
    }
    default_payload = {
        "pool_code": "all_a_share",
        "start_date": "2024-01-01",
        "end_date": None,
        "ingest_mode": "append_safe",
        "only_missing": True,
        "max_stocks": None,
        "workers": 12,
        "commit_stock_batch_size": 20,
        "max_upsert_rows_per_commit": 5000,
        "fail_fast": False,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = StockDailyBackfillRequest(**{**self.default_payload, **context.payload})
        service = StockDailyBackfillService(get_sessionmaker())
        result = await service.run_all(payload)
        return JobResult(
            status="success",
            affected_rows=result.upserted_rows,
            summary=result.model_dump(mode="json"),
        )


class BackfillSectorDailyFactsHandler:
    job_code = "backfill_sector_daily_facts"
    job_type = "market_data"
    parameter_schema = {
        "start_date": {"label": "开始日期", "type": "string", "default": "2024-01-01", "required": True},
        "end_date": {"label": "结束日期", "type": "string", "required": False, "description": "为空时使用最近开市日。"},
        "ingest_mode": {
            "label": "入库模式",
            "type": "string",
            "default": "append_safe",
            "required": False,
            "options": ["append_safe", "rebuild"],
        },
        "max_sectors": {
            "label": "板块数量上限",
            "type": "number",
            "required": False,
            "min": 1,
            "description": "Smoke 时限制板块数量；为空表示全部 Tushare THS 板块。",
        },
        "workers": {
            "label": "板块日 K worker 数",
            "type": "number",
            "default": 12,
            "required": False,
            "min": 1,
            "max": 20,
            "description": "按板块代码并发调用一次完整 start_date/end_date 区间的 ths_daily；仍受 Tushare Token 池限频。",
        },
        "moneyflow_workers": {
            "label": "资金流窗口 worker 数",
            "type": "number",
            "default": 2,
            "required": False,
            "min": 1,
            "max": 4,
            "description": "并发处理概念/行业资金流日期窗口；单窗口返回行数较多，独立限制数据库压力。",
        },
        "moneyflow_window_trade_days": {
            "label": "资金流区间交易日数",
            "type": "number",
            "default": 20,
            "required": False,
            "min": 1,
            "max": 20,
            "description": "moneyflow_cnt_ths/moneyflow_ind_ths 每次按多少个交易日成组查询；20 日区间已通过与逐日返回集合对照验证。",
        },
        "fail_fast": {"label": "遇错立即失败", "type": "boolean", "default": False, "required": False},
    }
    default_payload = {
        "start_date": "2024-01-01",
        "end_date": None,
        "ingest_mode": "append_safe",
        "max_sectors": None,
        "workers": 12,
        "moneyflow_workers": 2,
        "moneyflow_window_trade_days": 20,
        "fail_fast": False,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = SectorDailyFactsBackfillRequest(**{**self.default_payload, **context.payload})
        result = await SectorDailyFactsBackfillService(get_sessionmaker()).run(payload)
        return JobResult(
            status="success",
            affected_rows=result.sector_bar_rows + result.sector_moneyflow_rows,
            summary=result.model_dump(mode="json"),
        )


class BackfillIndexDailyFactsHandler:
    job_code = "backfill_index_daily_facts"
    job_type = "market_data"
    parameter_schema = {
        "start_date": {"label": "开始日期", "type": "string", "default": "2024-01-01", "required": True},
        "end_date": {"label": "结束日期", "type": "string", "required": False, "description": "为空时使用最近开市日。"},
        "ingest_mode": {
            "label": "入库模式",
            "type": "string",
            "default": "append_safe",
            "required": False,
            "options": ["append_safe", "rebuild"],
        },
        "only_missing": {"label": "只补缺失", "type": "boolean", "default": True, "required": False},
        "max_indexes": {"label": "指数数量上限", "type": "number", "required": False, "min": 1},
        "workers": {
            "label": "外部请求 worker 数",
            "type": "number",
            "default": 4,
            "required": False,
            "min": 1,
            "max": 8,
            "description": "并发处理指数；每个指数的 index_daily 和 index_dailybasic 各按完整区间查询一次。",
        },
        "fail_fast": {"label": "遇错立即失败", "type": "boolean", "default": False, "required": False},
    }
    default_payload = {
        "start_date": "2024-01-01",
        "end_date": None,
        "ingest_mode": "append_safe",
        "only_missing": True,
        "max_indexes": None,
        "workers": 4,
        "fail_fast": False,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = IndexDailyFactsBackfillRequest(**{**self.default_payload, **context.payload})
        result = await IndexDailyFactsBackfillService(get_sessionmaker()).run(payload)
        return JobResult(
            status="success",
            affected_rows=result.index_bar_rows + result.index_daily_basic_rows,
            summary=result.model_dump(mode="json"),
        )


_FACTOR_BACKFILL_COMMON_SCHEMA = {
    "start_date": {
        "label": "开始日期",
        "type": "string",
        "default": "2024-01-01",
        "required": True,
        "description": "因子回填开始日期，格式 YYYY-MM-DD。只读取已沉淀 canonical 数据，不触发外部 Provider。",
    },
    "end_date": {
        "label": "结束日期",
        "type": "string",
        "required": False,
        "description": "为空时使用交易日历中的最近开市日。",
    },
    "ingest_mode": {
        "label": "入库模式",
        "type": "string",
        "default": "append_safe",
        "required": False,
        "options": ["append_safe", "rebuild"],
        "description": "append_safe 幂等补缺；rebuild 会先删除目标日期范围内的本类因子再重算。",
    },
    "only_missing": {
        "label": "只补缺失日期",
        "type": "boolean",
        "default": True,
        "required": False,
        "description": "兼容参数：append_safe 模式下为 true 表示跳过完整日期；rebuild 模式会忽略它。",
    },
    "batch_size": {
        "label": "计算批次大小",
        "type": "number",
        "default": 200,
        "required": False,
        "min": 20,
        "max": 1000,
        "description": "每批加载多少只股票计算日频因子。",
    },
    "fail_fast": {
        "label": "遇错立即失败",
        "type": "boolean",
        "default": False,
        "required": False,
        "description": "关闭时，某交易日失败只记录错误并继续后续日期。",
    },
}


class BackfillStockDailyFactorsHandler:
    job_code = "backfill_stock_daily_factors"
    job_type = "market_data"
    parameter_schema = {
        "pool_code": {
            "label": "股票池编码",
            "type": "string",
            "default": "all_a_share",
            "required": True,
            "description": "指定需要回填日频因子的股票池；all_a_share 表示沪深 active 动态全市场。",
        },
        **{key: value for key, value in _FACTOR_BACKFILL_COMMON_SCHEMA.items() if key != "batch_size"},
        "max_stocks": {
            "label": "股票数量上限",
            "type": "number",
            "required": False,
            "min": 1,
            "description": "调试时限制回填股票数量；为空表示整个股票池。",
        },
        "factor_window_trade_days": {
            "label": "回填时间窗口（交易日）",
            "type": "number",
            "default": 20,
            "required": False,
            "min": 5,
            "max": 60,
            "description": "每个窗口由 PostgreSQL 一次性计算并入库。窗口越大，单次数据库负载越高；默认 20 个交易日适合云端 PostgreSQL。",
        },
        "sql_stock_chunk_size": {
            "label": "数据库分片股票数",
            "type": "number",
            "default": 200,
            "required": False,
            "min": 50,
            "max": 500,
            "description": "每个 PostgreSQL 集合计算分片包含的股票数。默认 200，避免单条全市场 SQL 占用过多云端数据库内存；每个分片独立提交，append_safe 可安全续跑。",
        },
        "calculate_stock_fund": {
            "label": "计算资金因子",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "从 t_stock_fund_flow_daily 读取资金流，补充资金占比、连续流入、横截面分位等 features。",
        },
        "include_external_technical": {
            "label": "合并专业技术因子",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "从 t_stock_technical_factor_daily 读取 stk_factor_pro 摘要并写入 features.tushare_technical。",
        },
    }
    default_payload = {
        "pool_code": "all_a_share",
        "start_date": "2024-01-01",
        "end_date": None,
        "ingest_mode": "append_safe",
        "only_missing": True,
        "max_stocks": None,
        "factor_window_trade_days": 20,
        "sql_stock_chunk_size": 200,
        "fail_fast": False,
        "calculate_stock_fund": True,
        "include_external_technical": True,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = FactorBackfillRequest(**{**self.default_payload, **context.payload})
        service = FactorBackfillService(get_sessionmaker())
        result = await service.backfill_stock_daily_pipeline(payload)
        return JobResult(
            status="success",
            affected_rows=result.daily_factor_rows + result.technical_snapshot_rows,
            summary=result.model_dump(mode="json"),
        )


class BackfillSectorDailyFactorsHandler:
    job_code = "backfill_sector_daily_factors"
    job_type = "market_data"
    parameter_schema = {
        **_FACTOR_BACKFILL_COMMON_SCHEMA,
        "calculation_workers": {
            "label": "计算 worker 数",
            "type": "number",
            "default": 2,
            "required": False,
            "min": 1,
            "max": 4,
            "description": "按交易日并行计算板块因子；默认 2，避免同时放大成分股聚合查询。",
        },
    }
    default_payload = {
        "start_date": "2024-01-01",
        "end_date": None,
        "ingest_mode": "append_safe",
        "only_missing": True,
        "batch_size": 200,
        "calculation_workers": 2,
        "fail_fast": False,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = FactorBackfillRequest(**{**self.default_payload, **context.payload})
        service = FactorBackfillService(get_sessionmaker())
        result = await service.backfill_sector(payload)
        return JobResult(
            status="success" if result.failed_trade_dates == 0 else "success",
            affected_rows=result.sector_factor_rows,
            summary=result.model_dump(mode="json"),
        )


class BackfillIndexDailyFactorsHandler:
    job_code = "backfill_index_daily_factors"
    job_type = "market_data"
    parameter_schema = {
        **{key: value for key, value in _FACTOR_BACKFILL_COMMON_SCHEMA.items() if key != "batch_size"},
        "max_indexes": {
            "label": "指数数量上限",
            "type": "number",
            "required": False,
            "min": 1,
            "description": "调试时限制指数数量；为空表示 t_index_basic 中的全部指数。",
        },
        "factor_window_trade_days": {
            "label": "回填时间窗口（交易日）",
            "type": "number",
            "default": 20,
            "required": False,
            "min": 5,
            "max": 60,
        },
        "sql_stock_chunk_size": {
            "label": "数据库分片指数数",
            "type": "number",
            "default": 200,
            "required": False,
            "min": 50,
            "max": 500,
        },
    }
    default_payload = {
        "start_date": "2024-01-01",
        "end_date": None,
        "ingest_mode": "append_safe",
        "only_missing": True,
        "max_indexes": None,
        "factor_window_trade_days": 20,
        "sql_stock_chunk_size": 200,
        "fail_fast": False,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = FactorBackfillRequest(**{**self.default_payload, **context.payload})
        result = await FactorBackfillService(get_sessionmaker()).backfill_index(payload)
        return JobResult(
            status="success",
            affected_rows=result.index_factor_rows,
            summary=result.model_dump(mode="json"),
        )


_COMMON_CLOSE_SCHEMA = {
    "trade_date": {"label": "交易日期", "type": "string", "required": False, "description": "为空时使用当前上海交易日。"},
    "ingest_mode": {"label": "入库模式", "type": "string", "default": "append_safe", "required": False, "options": ["append_safe", "rebuild"]},
    "fail_on_enrichment_error": {"label": "增强数据失败即中断", "type": "boolean", "default": False, "required": False, "description": "关闭时，非核心块失败会记录 warning 并继续本阶段剩余工作。"},
}

_MINUTE_SCHEMA = {
    "minute_retention_trade_days": {"label": "分钟数据保留交易日", "type": "number", "default": 10, "required": False, "min": 1, "max": 60},
    "minute_max_concurrency": {
        "label": "MooTDX worker 数",
        "type": "number",
        "default": 4,
        "required": False,
        "min": 1,
        "max": 10,
        "description": "每个 worker 使用独立 MooTDX 连接串行拉取。",
    },
    "minute_batch_size": {
        "label": "分钟线批次大小",
        "type": "number",
        "default": 200,
        "required": False,
        "min": 20,
        "max": 1000,
        "description": "分钟线按批次拉取并提交，降低内存峰值和单次失败影响范围。",
    },
}

_ENRICHMENT_CONCURRENCY_SCHEMA = {
    "enrichment_block_concurrency": {
        "label": "增强块并发数",
        "type": "number",
        "default": 4,
        "required": False,
        "min": 1,
        "max": 10,
        "description": "同时运行多少个独立增强数据块；仍受 Tushare Token 池和调度超时限制。",
    },
}


def _daily_close_affected_rows(result) -> int:
    return (
        result.daily_rows
        + result.daily_basic_rows
        + result.stock_technical_factor_rows
        + result.stock_moneyflow_rows
        + result.stock_limit_rows
        + result.lhb_event_rows
        + result.lhb_seat_rows
        + result.index_bar_rows
        + result.index_daily_basic_rows
        + result.north_hold_rows
        + result.market_stat_rows
        + result.sector_bar_rows
        + result.sector_moneyflow_rows
        + result.daily_factor_rows
        + result.minute_factor_rows
        + result.technical_snapshot_rows
        + result.sector_factor_rows
    )


class _DailyCloseBaseHandler:
    job_type = "market_data"
    force_async = True

    async def _run_payload(self, context: JobExecutionContext) -> JobResult:
        payload = DailyMarketCloseIngestRequest(**{**self.default_payload, **context.payload})
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = DailyMarketCloseIngestService(
                MarketDataRepository(session),
                ConfigCenterRepository(session),
            )
            result = await service.run(payload)
        return JobResult(
            status=result.status if result.status == "skipped" else "success",
            affected_rows=_daily_close_affected_rows(result),
            summary=result.model_dump(mode="json"),
        )


class DailyCloseCoreIngestHandler(_DailyCloseBaseHandler):
    job_code = "daily_close_core_ingest"
    parameter_schema = {
        **_COMMON_CLOSE_SCHEMA,
        **_MINUTE_SCHEMA,
    }
    default_payload = {
        "sync_daily": True,
        "sync_daily_basic": True,
        "sync_stock_technical_factor_pro": False,
        "sync_stock_moneyflow": True,
        "sync_stock_limit_status": True,
        "sync_lhb": False,
        "sync_index_bars": True,
        "sync_index_daily_basic": False,
        "sync_north_hold": False,
        "sync_market_stats": False,
        "sync_sector_bars": True,
        "sync_sector_moneyflow": False,
        "sync_minute": True,
        "calculate_daily_factors": True,
        "calculate_minute_factors": True,
        "calculate_technical_snapshot": True,
        "calculate_stock_fund_factors": True,
        "calculate_external_technical_factors": False,
        "calculate_sector_factors": True,
        "fail_on_enrichment_error": False,
        "minute_retention_trade_days": 10,
        "minute_max_concurrency": 4,
        "minute_batch_size": 200,
        "ingest_mode": "append_safe",
    }

    async def run(self, context: JobExecutionContext) -> JobResult:
        return await self._run_payload(context)


class DailyCloseEnrichmentIngestHandler(_DailyCloseBaseHandler):
    job_code = "daily_close_enrichment_ingest"
    parameter_schema = {
        **_COMMON_CLOSE_SCHEMA,
        **_ENRICHMENT_CONCURRENCY_SCHEMA,
    }
    default_payload = {
        "sync_daily": False,
        "sync_daily_basic": False,
        "sync_stock_technical_factor_pro": True,
        "sync_stock_moneyflow": False,
        "sync_stock_limit_status": False,
        "sync_lhb": True,
        "sync_index_bars": False,
        "sync_index_daily_basic": True,
        "sync_north_hold": False,
        "sync_market_stats": True,
        "sync_sector_bars": False,
        "sync_sector_moneyflow": True,
        "sync_minute": False,
        "calculate_daily_factors": True,
        "calculate_minute_factors": False,
        "calculate_technical_snapshot": False,
        "calculate_stock_fund_factors": True,
        "calculate_external_technical_factors": True,
        "calculate_sector_factors": True,
        "fail_on_enrichment_error": False,
        "enrichment_block_concurrency": 4,
        "ingest_mode": "append_safe",
    }

    async def run(self, context: JobExecutionContext) -> JobResult:
        return await self._run_payload(context)


class DailyCloseRepairIngestHandler:
    job_code = "daily_close_repair_ingest"
    job_type = "market_data"
    parameter_schema = {
        "trade_date": {"label": "指定交易日期", "type": "string", "required": False, "description": "为空时修复最近 N 个交易日。"},
        "repair_trade_days": {"label": "修复交易日数量", "type": "number", "default": 3, "required": False, "min": 1, "max": 10},
        **_ENRICHMENT_CONCURRENCY_SCHEMA,
        "fail_on_enrichment_error": {"label": "增强数据失败即中断", "type": "boolean", "default": False, "required": False},
    }
    default_payload = {
        "repair_trade_days": 3,
        "enrichment_block_concurrency": 4,
        "fail_on_enrichment_error": False,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = {**self.default_payload, **context.payload}
        sessionmaker = get_sessionmaker()
        summaries: list[dict] = []
        affected_rows = 0
        async with sessionmaker() as session:
            repository = MarketDataRepository(session)
            service = DailyMarketCloseIngestService(repository, ConfigCenterRepository(session))
            if payload.get("trade_date"):
                dates = [DailyMarketCloseIngestRequest(trade_date=payload["trade_date"]).trade_date]
            else:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                up_to = datetime.now(ZoneInfo("Asia/Shanghai")).date()
                dates = await repository.recent_open_trade_dates(
                    up_to=up_to,
                    limit=int(payload.get("repair_trade_days") or 3),
                )
            enhancement_start_date = min(dates) if dates else None
            enhancement_end_date = max(dates) if dates else None
            for index, trade_date in enumerate(dates):
                sync_range_enhancement = index == 0
                result = await service.run(
                    DailyMarketCloseIngestRequest(
                        trade_date=trade_date,
                        sync_daily=False,
                        sync_daily_basic=False,
                        sync_stock_technical_factor_pro=True,
                        enhancement_start_date=enhancement_start_date if sync_range_enhancement else None,
                        enhancement_end_date=enhancement_end_date if sync_range_enhancement else None,
                        sync_stock_moneyflow=False,
                        sync_stock_limit_status=False,
                        sync_lhb=True,
                        sync_lhb_events=sync_range_enhancement,
                        sync_lhb_seats=True,
                        sync_index_bars=False,
                        sync_index_daily_basic=sync_range_enhancement,
                        sync_north_hold=False,
                        sync_market_stats=sync_range_enhancement,
                        sync_sector_bars=False,
                        sync_sector_moneyflow=sync_range_enhancement,
                        sync_minute=False,
                        calculate_daily_factors=True,
                        calculate_minute_factors=False,
                        calculate_technical_snapshot=False,
                        calculate_stock_fund_factors=True,
                        calculate_external_technical_factors=True,
                        calculate_sector_factors=True,
                        fail_on_enrichment_error=bool(payload.get("fail_on_enrichment_error")),
                        enrichment_block_concurrency=int(payload.get("enrichment_block_concurrency") or 4),
                        ingest_mode="append_safe",
                    )
                )
                if not sync_range_enhancement:
                    result.enrichment_blocks.extend(
                        [
                            {
                                "label": label,
                                "status": "reused",
                                "mode": "date_range",
                                "range_start_date": enhancement_start_date.isoformat() if enhancement_start_date else None,
                                "range_end_date": enhancement_end_date.isoformat() if enhancement_end_date else None,
                                "reused_for_trade_date": trade_date.isoformat(),
                                "rows": 0,
                            }
                            for label in ("lhb events", "index daily basic", "market stats", "sector moneyflow")
                        ]
                    )
                affected_rows += _daily_close_affected_rows(result)
                summaries.append(result.model_dump(mode="json"))
        status = "success"
        if any(item.get("status") == "partial" for item in summaries):
            status = "success"
        if all(item.get("status") == "skipped" for item in summaries):
            status = "skipped"
        return JobResult(status=status, affected_rows=affected_rows, summary={"repaired_trade_days": summaries})


class DailyMarketCloseIngestHandler(DailyCloseCoreIngestHandler):
    job_code = "daily_market_close_ingest"
    default_payload = {
        **DailyCloseCoreIngestHandler.default_payload,
        "sync_stock_technical_factor_pro": True,
        "sync_lhb": True,
        "sync_index_daily_basic": True,
        "sync_market_stats": True,
        "sync_sector_moneyflow": True,
        "calculate_external_technical_factors": True,
    }


def register_market_data_jobs() -> None:
    job_handler_registry.register(SyncSectorCatalogHandler())
    job_handler_registry.register(SyncTradeCalendarHandler())
    job_handler_registry.register(SyncStockBasicHandler())
    job_handler_registry.register(SyncIndexCatalogHandler())
    job_handler_registry.register(BackfillStockDailyFactsHandler())
    job_handler_registry.register(BackfillStockDailyFactorsHandler())
    job_handler_registry.register(BackfillSectorDailyFactsHandler())
    job_handler_registry.register(BackfillSectorDailyFactorsHandler())
    job_handler_registry.register(BackfillIndexDailyFactsHandler())
    job_handler_registry.register(BackfillIndexDailyFactorsHandler())
    job_handler_registry.register(DailyCloseCoreIngestHandler())
    job_handler_registry.register(DailyCloseEnrichmentIngestHandler())
    job_handler_registry.register(DailyCloseRepairIngestHandler())
    job_handler_registry.register(DailyMarketCloseIngestHandler())
