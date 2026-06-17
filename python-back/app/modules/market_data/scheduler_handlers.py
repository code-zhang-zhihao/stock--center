from app.db.session import get_sessionmaker
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.sync_service import (
    MarketDataSyncError,
    MarketDataSyncService,
    SectorCatalogSyncRequest,
    StockBasicSyncRequest,
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
            "default": 3,
            "required": False,
            "description": "外部 provider 成分股查询并发数。",
        },
        "source": {
            "label": "数据源",
            "type": "string",
            "default": "akshare",
            "required": False,
            "options": ["akshare"],
            "description": "第一版板块同步使用 AkShare。",
        },
        "expire_missing_components": {
            "label": "过期缺失成分",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "完整同步某板块后，将本次未出现的旧成分标记 end_date。",
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
        "max_concurrency": 3,
        "source": "akshare",
        "expire_missing_components": True,
        "provider_timeout_seconds": 45,
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = SectorCatalogSyncRequest(**{**self.default_payload, **context.payload})
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = MarketDataSyncService(MarketDataRepository(session))
            result = await service.sync_sector_catalog(payload)
        return JobResult(affected_rows=result.sector_count + result.component_count, summary=result.model_dump())


class SyncStockBasicHandler:
    job_code = "sync_stock_basic"
    job_type = "market_data"
    parameter_schema = {
        "source": {
            "label": "主数据源",
            "type": "string",
            "default": "akshare",
            "required": False,
            "options": ["akshare", "mootdx"],
            "description": "基础资料主数据源。",
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
        "source": "akshare",
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
        return JobResult(affected_rows=result.upserted_count + result.detail_enriched_count + result.delisted_marked_count, summary=result.model_dump())


def register_market_data_jobs() -> None:
    job_handler_registry.register(SyncSectorCatalogHandler())
    job_handler_registry.register(SyncStockBasicHandler())
