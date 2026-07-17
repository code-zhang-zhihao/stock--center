from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.db.session import check_database_health, dispose_engine
from app.modules.config_center.api import router as config_center_router
from app.modules.data_assets.api import router as data_assets_router
from app.modules.data_assets.scheduler_handlers import register_data_asset_jobs
from app.modules.market_data.api import router as market_data_router
from app.modules.market_data.scheduler_handlers import register_market_data_jobs
from app.modules.realtime_market.api import router as realtime_market_router
from app.modules.realtime_market.service import realtime_market_service
from app.modules.scheduler_center.api import router as scheduler_router
from app.modules.scheduler_center.runtime import scheduler_runtime
from app.modules.stock_pool.api import router as stock_pool_router


logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=False,
    )
    logging.getLogger("tdxpy").setLevel(logging.CRITICAL)


def _configure_market_data_no_proxy() -> None:
    settings = get_settings()
    domains = settings.market_data_no_proxy_list
    if not domains:
        return
    for env_name in ("NO_PROXY", "no_proxy"):
        existing = [item.strip() for item in os.environ.get(env_name, "").split(",") if item.strip()]
        merged = list(dict.fromkeys([*existing, *domains]))
        os.environ[env_name] = ",".join(merged)
    logger.info("configured market data no_proxy domains: %s", ",".join(domains))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        await scheduler_runtime.mark_orphaned_running_runs()
    except Exception:
        logger.exception("failed to mark orphaned scheduler runs during startup")
    if settings.scheduler_enabled:
        try:
            await scheduler_runtime.start()
        except Exception:
            logger.exception("scheduler startup failed; application will continue without scheduled jobs")
    try:
        await realtime_market_service.start()
    except Exception:
        logger.exception("realtime market startup failed; application will continue without realtime runtime")
    try:
        yield
    finally:
        await realtime_market_service.stop()
        await scheduler_runtime.stop()
        await redis_client.close()
        await dispose_engine()


def create_app() -> FastAPI:
    _configure_logging()
    _configure_market_data_no_proxy()
    settings = get_settings()
    register_data_asset_jobs()
    register_market_data_jobs()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(config_center_router, prefix="/api/v1/config", tags=["config"])
    app.include_router(market_data_router, prefix="/api/v1/market-data", tags=["market-data"])
    app.include_router(scheduler_router, prefix="/api/v1/scheduler", tags=["scheduler"])
    app.include_router(stock_pool_router, prefix="/api/v1/stock-pools", tags=["stock-pools"])
    app.include_router(data_assets_router, prefix="/api/v1/data-assets", tags=["data-assets"])
    app.include_router(realtime_market_router, prefix="/api/v1/realtime", tags=["realtime-market"])

    @app.get("/api/v1/health", tags=["system"])
    async def health():
        return {"status": "ok", "app": settings.app_name, "env": settings.app_env}

    @app.get("/api/v1/health/db", tags=["system"])
    async def database_health():
        return await check_database_health()

    return app


app = create_app()
