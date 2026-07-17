from app.db.session import get_sessionmaker
from app.modules.data_assets.repository import DataAssetsRepository
from app.modules.data_assets.service import DataAssetsService
from app.modules.scheduler_center.handlers import JobExecutionContext, job_handler_registry
from app.modules.scheduler_center.schemas import JobResult


class RefreshDataAssetHealthHandler:
    job_code = "refresh_data_asset_health"
    job_type = "data_assets"
    parameter_schema = {
        "days": {
            "label": "完整性交易日数",
            "type": "number",
            "default": 3,
            "required": False,
            "min": 1,
            "max": 15,
            "description": "刷新最近多少个交易日的数据完整性矩阵。默认 3 天，避免巡检扫大表过慢。",
        }
    }
    default_payload = {"days": 3}
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        days = int(context.payload.get("days") or self.default_payload["days"])
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await DataAssetsService(DataAssetsRepository(session)).refresh_cache(days=days)
        return JobResult(
            status="success" if not result.failed_keys else "skipped",
            affected_rows=result.summary_rows + result.daily_health_rows,
            summary=result.model_dump(mode="json"),
        )


def register_data_asset_jobs() -> None:
    job_handler_registry.register(RefreshDataAssetHealthHandler())
