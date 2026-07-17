from __future__ import annotations

import asyncio
from datetime import date

from app.modules.market_data.tushare_provider import TushareProvider, TushareProviderError
from app.modules.market_data.tushare_catalog import TushareApiRequest
from app.modules.market_data.tushare_mappers import TushareCanonicalMapper, _ts_code


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def post(self, url: str, *, json: dict, timeout: int):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(self.responses.pop(0))


def response(fields: list[str], items: list[list]) -> dict:
    return {"code": 0, "data": {"fields": fields, "items": items}}


def provider(responses: list[dict]) -> tuple[TushareProvider, FakeSession]:
    session = FakeSession(responses)
    return (
        TushareProvider(
            token="test-token",
            api_url="http://example.test",
            timeout_seconds=5,
            rate_limit_per_minute=60,
            session=session,
        ),
        session,
    )


def test_daily_bar_mapper_normalizes_tushare_units_outside_transport() -> None:
    client, session = provider([
        response(
            ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
            [["600519.SH", "20260620", 1500, 1510, 1490, 1505, 1490, 15, 1.01, 123, 4567.8]],
        )
    ])

    rows, raw = asyncio.run(TushareCanonicalMapper().daily_bars(client, "600519", start_date=date(2026, 6, 1), end_date=date(2026, 6, 20)))

    assert rows[0]["stock_code"] == "600519"
    assert rows[0]["volume_hand"] == 123
    assert rows[0]["amount_yuan"] == 4567800.0
    assert raw[0]["api_name"] == "daily"
    assert session.requests[0]["json"]["token"] == "test-token"


def test_daily_connectivity_makes_one_minimal_daily_request_and_allows_empty_data() -> None:
    client, session = provider([response(["ts_code", "trade_date", "close"], [])])
    result = asyncio.run(client.daily_connectivity(end_date=date(2026, 6, 22)))

    assert result.records == []
    assert result.raw_payload["api_name"] == "daily"
    assert len(session.requests) == 1
    assert session.requests[0]["json"] == {
        "api_name": "daily",
        "token": "test-token",
        "params": {"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"},
        "fields": "ts_code,trade_date,close",
    }


def test_raw_request_preserves_tushare_fields_without_canonical_mapping() -> None:
    client, session = provider([response(["ts_code", "trade_date", "amount"], [["600519.SH", "20260620", 123.45]])])

    raw = asyncio.run(client.request(TushareApiRequest("daily", {"ts_code": "600519.SH", "trade_date": "20260620"})))

    assert raw.records == [{"ts_code": "600519.SH", "trade_date": "20260620", "amount": 123.45}]
    assert raw.raw_payload["api_name"] == "daily"
    assert "source" not in raw.records[0]
    assert session.requests[0]["json"]["params"] == {"ts_code": "600519.SH", "trade_date": "20260620"}


def test_sw_industry_catalog_and_member_mapping_stays_outside_transport() -> None:
    client, session = provider([
        response(
            ["index_code", "industry_name", "parent_code", "level", "industry_code", "is_pub", "src"],
            [["801010.SI", "农林牧渔", "0", "L1", "110000", "1", "SW2021"]],
        ),
        response(
            ["l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name", "ts_code", "name", "in_date", "out_date", "is_new"],
            [["110000", "农林牧渔", None, None, None, None, "000998.SZ", "隆平高科", None, None, "Y"]],
        ),
    ])

    mapper = TushareCanonicalMapper()
    sectors, _ = asyncio.run(mapper.sectors(client, "industry"))
    members, _ = asyncio.run(mapper.sector_components(client, "sw2021_110000"))

    assert sectors[0]["sector_code"] == "sw2021_110000"
    assert sectors[0]["metadata_json"]["taxonomy"] == "SW2021"
    assert members[0]["stock_code"] == "000998"
    assert members[0]["source"] == "tushare:index_member_all:SW2021"
    assert session.requests[1]["json"]["params"] == {"l1_code": "110000", "is_new": "Y"}


def test_stock_code_mapping_is_a_caller_concern() -> None:
    assert _ts_code("600519") == "600519.SH"
    assert _ts_code("000001") == "000001.SZ"
    assert _ts_code("430047") == "430047.BJ"


def test_stock_basic_mapper_prefers_symbol_for_canonical_stock_code() -> None:
    mapper = TushareCanonicalMapper()

    class Transport:
        async def request(self, _request):
            from types import SimpleNamespace

            return SimpleNamespace(
                records=[{"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台", "list_date": "20010827"}],
                raw_payload={"api_name": "stock_basic"},
            )

    row, _ = asyncio.run(mapper.stock_basic(Transport(), "600519.SH"))
    assert row["stock_code"] == "600519"
