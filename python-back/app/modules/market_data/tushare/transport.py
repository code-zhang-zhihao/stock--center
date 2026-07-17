from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import requests

from app.modules.market_data.tushare.catalog import TUSHARE_A_SHARE_CATALOG
from app.modules.market_data.tushare.contracts import TushareApiRequest, TushareApiResponse, validate_tushare_request


class TushareTransportError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider_error", api_name: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.api_name = api_name


class TushareTransport:
    """Catalog-validated Tushare Pro transport with no domain mapping or persistence."""

    def __init__(
        self,
        *,
        token: str,
        api_url: str = "http://api.tushare.pro",
        timeout_seconds: int = 30,
        rate_limit_per_minute: int = 60,
        session: requests.Session | None = None,
        token_fingerprint: str | None = None,
    ) -> None:
        self.token = token.strip()
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.rate_limit_per_minute = rate_limit_per_minute
        self.token_fingerprint = token_fingerprint
        self._session = session or requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    async def request(self, request: TushareApiRequest) -> TushareApiResponse:
        try:
            validated = validate_tushare_request(request, TUSHARE_A_SHARE_CATALOG)
        except ValueError as exc:
            raise TushareTransportError(str(exc), kind="input", api_name=request.api_name) from exc
        records, raw = await asyncio.to_thread(
            self._query,
            validated.api_name,
            params=validated.params,
            fields=",".join(validated.fields),
        )
        return TushareApiResponse(
            api_name=validated.api_name,
            request_params=validated.params,
            fields=tuple(raw.get("fields") or ()),
            records=records,
            raw_payload=raw,
            token_fingerprint=self.token_fingerprint,
            endpoint_url=self.api_url,
        )

    async def daily_connectivity(self, *, end_date: date | None = None) -> TushareApiResponse:
        resolved_end_date = end_date or date.today()
        return await self.request(
            TushareApiRequest(
                api_name="daily",
                params={
                    "ts_code": "600519.SH",
                    "start_date": (resolved_end_date - timedelta(days=9)).strftime("%Y%m%d"),
                    "end_date": resolved_end_date.strftime("%Y%m%d"),
                },
                fields=("ts_code", "trade_date", "close"),
            )
        )

    def _query(self, api_name: str, *, params: dict[str, Any], fields: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.token:
            raise TushareTransportError("Tushare token is not configured", kind="token_missing", api_name=api_name)
        payload = {"api_name": api_name, "token": self.token, "params": params, "fields": fields}
        try:
            response = self._session.post(self.api_url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise TushareTransportError(f"Tushare {api_name} transport error: {type(exc).__name__}: {exc}", kind="transport", api_name=api_name) from exc
        except ValueError as exc:
            raise TushareTransportError(f"Tushare {api_name} returned invalid JSON", kind="transport", api_name=api_name) from exc
        if result.get("code") != 0:
            message = str(result.get("msg") or "unknown")
            raise TushareTransportError(
                f"Tushare {api_name} error {result.get('code')}: {message}",
                kind=self._error_kind(message),
                api_name=api_name,
            )
        data = result.get("data") or {}
        field_names = data.get("fields") or []
        items = data.get("items") or []
        return [dict(zip(field_names, values, strict=False)) for values in items], {
            "api_name": api_name,
            "params": params,
            "fields": field_names,
            "items": items,
        }

    @staticmethod
    def _error_kind(message: str) -> str:
        lower = message.lower()
        if any(token in lower for token in ("token", "权限token", "invalid token", "认证")):
            return "token_invalid"
        if any(token in lower for token in ("权限", "积分", "permission", "privilege")):
            return "permission"
        if any(token in lower for token in ("频率", "限频", "rate limit", "too many")):
            return "rate_limit"
        return "provider_error"
