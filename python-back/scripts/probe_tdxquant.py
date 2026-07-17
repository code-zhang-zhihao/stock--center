"""Probe a locally running TdxQuant client without writing project data.

The official TdxQuant runtime is exposed by a compatible Tongdaxin client on
``http://127.0.0.1:17709/``.  This probe intentionally stays outside the
runtime provider chain: it verifies the local client and reports its actual
payload shapes before stock-center adopts it as a realtime source.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_ENDPOINT = "http://127.0.0.1:17709/"
DEFAULT_CODES = ("600519.SH", "000001.SZ", "002281.SZ")


@dataclass(frozen=True)
class ProbeTarget:
    code: str
    name: str


class TdxQuantProbe:
    """Minimal HTTP client and capability probe for the official TQ service."""

    def __init__(self, endpoint: str, *, timeout_seconds: float = 15) -> None:
        self.endpoint = endpoint.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self._request_id = 0

    async def call(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        started = time.perf_counter()
        try:
            response = await client.post(
                self.endpoint,
                json={"id": self._request_id, "method": method, "params": params},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            return {
                "status": "transport_error",
                "method": method,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "invalid_response",
                "method": method,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }

        result = payload.get("result") if isinstance(payload, dict) else None
        error_id = result.get("ErrorId") if isinstance(result, dict) else None
        return {
            "status": "available" if error_id in {None, "0", 0} else "provider_error",
            "method": method,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "error_id": error_id,
            "error": result.get("ErrorMsg") if isinstance(result, dict) else None,
            "payload": payload,
        }

    async def run(
        self,
        *,
        codes: list[str],
        minute_code: str,
        snapshot_sample_size: int,
        check_pricevol: bool,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 5))
        # TdxQuant is a loopback service. System proxy settings must never
        # intercept calls to a locally running Tongdaxin client.
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            daily = await self.call(
                client,
                "get_market_data",
                {
                    "field_list": ["Open", "High", "Low", "Close", "Volume", "Amount"],
                    "stock_list": codes,
                    "period": "1d",
                    "count": 5,
                    "dividend_type": "none",
                    "fill_data": False,
                },
            )
            minute = await self.call(
                client,
                "get_market_data",
                {
                    "field_list": ["Open", "High", "Low", "Close", "Volume", "Amount"],
                    "stock_list": [minute_code],
                    "period": "1m",
                    "count": 240,
                    "dividend_type": "none",
                    "fill_data": False,
                },
            )
            sector_catalog = await self.call(client, "get_sector_list", {})
            universe = await self.call(client, "get_stock_list", {"market": "5", "list_type": 1})

            snapshots = []
            for code in codes[:snapshot_sample_size]:
                snapshots.append(
                    await self.call(
                        client,
                        "get_market_snapshot",
                        {"stock_code": code, "field_list": []},
                    )
                )

            pricevol = None
            if check_pricevol:
                pricevol = await self.call(client, "get_pricevol", {"stock_list": codes[:snapshot_sample_size]})

        return {
            "endpoint": self.endpoint,
            "probe_targets": [target.__dict__ for target in self._targets(codes)],
            "daily_kline": self._summarize_kline(daily),
            "minute_kline": self._summarize_kline(minute),
            "sector_catalog": self._summarize_generic(sector_catalog),
            "a_share_universe": self._summarize_generic(universe),
            "snapshot_sample": [self._summarize_snapshot(result) for result in snapshots],
            "batch_price_volume": self._summarize_generic(pricevol) if pricevol else {"status": "not_requested"},
            "notes": [
                "本探测不写 PostgreSQL、Redis 或 t_provider_raw_record。",
                "全市场快照不默认执行；先根据 sample 的实际耗时、字段和客户端并发能力决定批量策略。",
                "get_pricevol 是官方版本说明中新增的批量价量接口；其参数形状以本机 TQ 客户端实际返回为准。",
            ],
        }

    @staticmethod
    def _targets(codes: list[str]) -> list[ProbeTarget]:
        return [ProbeTarget(code=code, name="sample") for code in codes]

    @staticmethod
    def _summarize_kline(result: dict[str, Any]) -> dict[str, Any]:
        summary = TdxQuantProbe._summarize_generic(result)
        value = ((result.get("payload") or {}).get("result") or {}).get("Value")
        if isinstance(value, dict):
            summary["stocks_returned"] = sorted(value.keys())
            summary["fields_returned"] = sorted({field for item in value.values() if isinstance(item, dict) for field in item})
        return summary

    @staticmethod
    def _summarize_snapshot(result: dict[str, Any]) -> dict[str, Any]:
        summary = TdxQuantProbe._summarize_generic(result)
        value = ((result.get("payload") or {}).get("result") or {}).get("Value")
        if isinstance(value, dict):
            summary["fields_returned"] = sorted(value.keys())
            summary["has_five_level_depth"] = all(field in value for field in ("Buyp", "Buyv", "Sellp", "Sellv"))
        return summary

    @staticmethod
    def _summarize_generic(result: dict[str, Any] | None) -> dict[str, Any]:
        if not result:
            return {"status": "not_requested"}
        return {
            "status": result.get("status"),
            "method": result.get("method"),
            "duration_ms": result.get("duration_ms"),
            "error_id": result.get("error_id"),
            "error": result.get("error"),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe a local TdxQuant client without persisting data.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="TdxQuant HTTP endpoint")
    parser.add_argument("--timeout-seconds", type=float, default=15, help="HTTP request timeout")
    parser.add_argument("--codes", nargs="+", default=list(DEFAULT_CODES), help="Sample security codes with exchange suffix")
    parser.add_argument("--minute-code", default="600519.SH", help="Security used to test 1-minute K-line")
    parser.add_argument("--snapshot-sample-size", type=int, default=3, help="How many sample snapshots to call")
    parser.add_argument("--check-pricevol", action="store_true", help="Also probe the new get_pricevol batch method")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    result = await TdxQuantProbe(args.endpoint, timeout_seconds=args.timeout_seconds).run(
        codes=args.codes,
        minute_code=args.minute_code,
        snapshot_sample_size=max(1, args.snapshot_sample_size),
        check_pricevol=args.check_pricevol,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    statuses = [
        result["daily_kline"]["status"],
        result["minute_kline"]["status"],
        *[item["status"] for item in result["snapshot_sample"]],
    ]
    return 0 if any(status == "available" for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
