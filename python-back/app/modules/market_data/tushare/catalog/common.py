from __future__ import annotations

from typing import Any

from app.modules.market_data.tushare.contracts import TushareApiSpec, TushareFieldSpec, TushareParamSpec


def p(name: str, required: bool = False, value_type: str = "string", enum: tuple[str, ...] = (), description: str = "") -> TushareParamSpec:
    return TushareParamSpec(name, required, value_type, enum, description)


def fields(*names: str) -> tuple[TushareFieldSpec, ...]:
    return tuple(TushareFieldSpec(name) for name in names)


def api(
    api_name: str,
    category: str,
    doc_id: int,
    *,
    min_points: int | None,
    params: tuple[TushareParamSpec, ...] = (),
    output_fields: tuple[TushareFieldSpec, ...] = (),
    audit_params: dict[str, Any] | None = None,
    point_status: str = "confirmed",
    status: frozenset[str] = frozenset({"documented"}),
    allow_extra_params: bool = False,
) -> TushareApiSpec:
    return TushareApiSpec(
        api_name=api_name,
        category=category,
        doc_id=doc_id,
        min_points=min_points,
        point_status=point_status,  # type: ignore[arg-type]
        params=params,
        fields=output_fields,
        audit_params=audit_params or {},
        status=status,  # type: ignore[arg-type]
        allow_extra_params=allow_extra_params,
    )
