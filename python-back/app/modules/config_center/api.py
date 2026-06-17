from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.config_center.schemas import (
    ConfigCategory,
    ConfigOptionsPut,
    ConfigValueCreate,
    ConfigValueUpdate,
    SystemConfigUpdate,
)
from app.modules.config_center.service import ConfigCenterService


router = APIRouter()


def service(session: AsyncSession) -> ConfigCenterService:
    return ConfigCenterService(ConfigCenterRepository(session))


@router.get("/summary")
async def get_config_summary(session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).summary())
    except Exception as exc:
        return ApiResponse.fail(code="config_summary_failed", message=str(exc))


@router.get("/items")
async def list_config_items(category: ConfigCategory, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).list_items(category_code=category))
    except Exception as exc:
        return ApiResponse.fail(code="config_items_query_failed", message=str(exc))


@router.patch("/items/{config_id}")
async def update_config_item(config_id: int, payload: SystemConfigUpdate, session: AsyncSession = Depends(get_session)):
    try:
        item = await service(session).update_item(config_id, payload)
        if item is None:
            return ApiResponse.fail(code="config_item_not_found", message=f"config item not found: {config_id}")
        return ApiResponse.ok(item)
    except Exception as exc:
        return ApiResponse.fail(code="config_item_update_failed", message=str(exc))


@router.get("/items/{config_id}/options")
async def get_config_options(config_id: int, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).list_options(config_id))
    except Exception as exc:
        return ApiResponse.fail(code="config_options_query_failed", message=str(exc))


@router.put("/items/{config_id}/options")
async def put_config_options(config_id: int, payload: ConfigOptionsPut, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).put_options(config_id, payload.options))
    except Exception as exc:
        return ApiResponse.fail(code="config_options_update_failed", message=str(exc))


@router.get("/items/{config_id}/values")
async def get_config_values(
    config_id: int,
    value_kind: str | None = None,
    only_available: bool = False,
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).list_values(
                config_id,
                value_kind=value_kind,
                only_available=only_available,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="config_values_query_failed", message=str(exc))


@router.post("/items/{config_id}/values")
async def create_config_value(config_id: int, payload: ConfigValueCreate, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).create_value(config_id, payload))
    except Exception as exc:
        return ApiResponse.fail(code="config_value_create_failed", message=str(exc))


@router.patch("/values/{value_id}")
async def update_config_value(value_id: int, payload: ConfigValueUpdate, session: AsyncSession = Depends(get_session)):
    try:
        value = await service(session).update_value(value_id, payload)
        if value is None:
            return ApiResponse.fail(code="config_value_not_found", message=f"config value not found: {value_id}")
        return ApiResponse.ok(value)
    except Exception as exc:
        return ApiResponse.fail(code="config_value_update_failed", message=str(exc))


@router.post("/values/{value_id}/disable")
async def disable_config_value(value_id: int, session: AsyncSession = Depends(get_session)):
    try:
        value = await service(session).disable_value(value_id)
        if value is None:
            return ApiResponse.fail(code="config_value_not_found", message=f"config value not found: {value_id}")
        return ApiResponse.ok(value)
    except Exception as exc:
        return ApiResponse.fail(code="config_value_disable_failed", message=str(exc))


@router.delete("/values/{value_id}")
async def delete_config_value(value_id: int, session: AsyncSession = Depends(get_session)):
    try:
        deleted = await service(session).delete_value(value_id)
        if not deleted:
            return ApiResponse.fail(code="config_value_not_found", message=f"config value not found: {value_id}")
        return ApiResponse.ok({"deleted": True, "value_id": value_id})
    except Exception as exc:
        return ApiResponse.fail(code="config_value_delete_failed", message=str(exc))


@router.post("/values/{value_id}/test")
async def test_config_value(value_id: int, session: AsyncSession = Depends(get_session)):
    try:
        result = await service(session).test_value(value_id)
        if result is None:
            return ApiResponse.fail(code="config_value_not_found", message=f"config value not found: {value_id}")
        return ApiResponse.ok(result)
    except Exception as exc:
        return ApiResponse.fail(code="config_value_test_failed", message=str(exc))


@router.get("/migration/dry-run")
async def config_migration_dry_run(session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).migration_dry_run())
    except Exception as exc:
        return ApiResponse.fail(code="config_migration_dry_run_failed", message=str(exc))
