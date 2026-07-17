from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal


PointStatus = Literal["confirmed", "unknown"]
ApiStatus = Literal["documented", "called_by_business", "persisted", "audited_available"]


@dataclass(frozen=True)
class TushareParamSpec:
    name: str
    required: bool = False
    value_type: str = "string"
    enum: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class TushareFieldSpec:
    name: str
    value_type: str = "string"
    description: str = ""


@dataclass(frozen=True)
class TushareApiSpec:
    api_name: str
    category: str
    doc_id: int
    min_points: int | None
    point_status: PointStatus
    params: tuple[TushareParamSpec, ...]
    fields: tuple[TushareFieldSpec, ...]
    audit_params: dict[str, Any]
    status: frozenset[ApiStatus] = frozenset({"documented"})
    allow_extra_params: bool = False

    @property
    def family(self) -> str:
        """Compatibility name used by older callers and audit filtering."""
        return self.category

    @property
    def doc_url(self) -> str:
        return f"https://tushare.pro/document/2?doc_id={self.doc_id}"

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


@dataclass(frozen=True)
class TushareApiRequest:
    api_name: str
    params: dict[str, Any]
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TushareApiResponse:
    api_name: str
    request_params: dict[str, Any]
    fields: tuple[str, ...]
    records: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    token_fingerprint: str | None = None
    endpoint_url: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.records)


def validate_tushare_request(request: TushareApiRequest, catalog: dict[str, TushareApiSpec]) -> TushareApiRequest:
    try:
        spec = catalog[request.api_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported Tushare A-share API: {request.api_name}") from exc
    params = dict(request.params)
    declared = {item.name: item for item in spec.params}
    missing = [item.name for item in spec.params if item.required and not params.get(item.name)]
    if missing:
        raise ValueError(f"{request.api_name} missing required parameters: {', '.join(missing)}")
    unknown = sorted(set(params) - set(declared))
    if unknown and not spec.allow_extra_params:
        raise ValueError(f"{request.api_name} unsupported parameters: {', '.join(unknown)}")
    for name, value in params.items():
        item = declared.get(name)
        if item is None or value is None:
            continue
        if item.value_type == "date":
            if isinstance(value, date):
                params[name] = value.strftime("%Y%m%d")
            elif not (isinstance(value, str) and len(value) == 8 and value.isdigit()):
                raise ValueError(f"{request.api_name}.{name} must use YYYYMMDD")
        if item.enum and str(value) not in item.enum:
            raise ValueError(f"{request.api_name}.{name} must be one of: {', '.join(item.enum)}")
    fields = tuple(request.fields)
    if fields and spec.fields:
        unsupported_fields = sorted(set(fields) - set(spec.field_names))
        if unsupported_fields:
            raise ValueError(f"{request.api_name} unsupported fields: {', '.join(unsupported_fields)}")
    return TushareApiRequest(api_name=request.api_name, params=params, fields=fields)
