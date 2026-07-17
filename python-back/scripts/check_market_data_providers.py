from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.market_data.providers import AkShareProvider, MootdxProvider
from app.db.session import get_sessionmaker
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.tushare_runtime import TushareProviderFactory


def preview(value, *, limit: int = 2):
    if isinstance(value, list):
        return value[:limit]
    return value


async def check_mootdx(stock_code: str) -> dict:
    provider = MootdxProvider()
    try:
        quote, quote_raw = await provider.quote(stock_code)
        minute_rows, minute_raw = await provider.minute_bars(stock_code)
        daily_rows, daily_raw = await provider.daily_bars(stock_code, limit=5)
        return {
            "provider": "mootdx",
            "ok": bool(quote or minute_rows or daily_rows),
            "quote": quote,
            "quote_raw_count": len(quote_raw),
            "minute_count": len(minute_rows),
            "minute_preview": preview(minute_rows),
            "minute_raw_count": len(minute_raw),
            "daily_count": len(daily_rows),
            "daily_preview": preview(daily_rows),
            "daily_raw_count": len(daily_raw),
        }
    finally:
        provider._close_client()


async def check_akshare(stock_code: str) -> dict:
    provider = AkShareProvider()
    end_date = date.today()
    start_date = end_date - timedelta(days=14)
    stock, stock_raw = await provider.stock_basic(stock_code)
    daily_rows, daily_raw = await provider.daily_bars(stock_code, start_date=start_date, end_date=end_date)
    quote, quote_raw = await provider.quote(stock_code)
    return {
        "provider": "akshare",
        "ok": bool(stock or daily_rows or quote),
        "stock": stock,
        "stock_raw_count": len(stock_raw),
        "quote": quote,
        "quote_raw_count": len(quote_raw),
        "daily_count": len(daily_rows),
        "daily_preview": preview(daily_rows),
        "daily_raw_count": len(daily_raw),
    }


async def check_tushare() -> dict:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        factory = TushareProviderFactory(ConfigCenterRepository(session))
        end_date = date.today()
        response = await factory.call(
            "tushare_daily_connectivity_test",
            lambda provider: provider.daily_connectivity(end_date=end_date),
            request_summary={"api_name": "daily", "stock_code": "600519.SH", "end_date": end_date.isoformat()},
        )
        return {
            "provider": "tushare",
            "ok": True,
            "api_name": "daily",
            "stock_code": "600519.SH",
            "daily_count": response.row_count,
            "daily_raw_api_name": response.raw_payload.get("api_name"),
        }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check MooTDX, AkShare and optional Tushare provider connectivity.")
    parser.add_argument("--stock-code", default="600519", help="A-share stock code, default: 600519")
    parser.add_argument("--provider", choices=["all", "mootdx", "akshare", "tushare"], default="all")
    args = parser.parse_args()

    checks = []
    if args.provider in {"all", "mootdx"}:
        checks.append(("mootdx", check_mootdx(args.stock_code)))
    if args.provider in {"all", "akshare"}:
        checks.append(("akshare", check_akshare(args.stock_code)))
    if args.provider == "tushare":
        checks.append(("tushare", check_tushare()))

    results = []
    failed = False
    for name, task in checks:
        try:
            result = await task
            results.append(result)
            failed = failed or not result.get("ok")
        except Exception as exc:
            failed = True
            results.append({"provider": name, "ok": False, "error": str(exc)})

    print(json.dumps({"stock_code": args.stock_code, "results": results}, ensure_ascii=False, indent=2, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
