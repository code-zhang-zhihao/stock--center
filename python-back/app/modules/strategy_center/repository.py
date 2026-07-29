from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from types import SimpleNamespace
from typing import Iterable

from sqlalchemy import Integer, and_, cast, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import (
    DailyBar,
    LimitEventDaily,
    SectorBasic,
    SectorComponent,
    Stock,
    StockDailyBasic,
    StockFactorDaily,
    StockFundFlowDaily,
    TradeCalendar,
)
from app.modules.market_insight.models import (
    MarketEmotionDaily,
    MarketEmotionModel,
    MarketLimitUpEvidenceDaily,
    MarketSectorHeatDaily,
    MarketSentimentDaily,
)
from app.modules.market_insight.service import MARKET_SENTIMENT_CALCULATION_VERSION
from app.modules.stock_pool.models import StockPool, StockPoolRealtimePolicy
from app.modules.strategy_center.models import (
    StrategyBacktestRun,
    StrategyBacktestTrade,
    StrategyCandidate,
    StrategyDefinition,
    StrategyOptimizationRun,
    StrategyOptimizationTrial,
    StrategyPaperTrade,
    StrategyPaperTradeLeg,
    StrategySignalEvent,
    StrategyVersion,
)


class StrategyCenterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Event strategies evaluate many five-day batches.  Cache the stable
        # concept membership snapshot for that one research/session scope so
        # adding hot-concept context does not repeatedly join every board to
        # every candidate stock.
        self._concept_memberships_cache: dict[str, list[tuple[str, str, date | None, date | None]]] | None = None

    async def list_definitions(self) -> list[dict]:
        rows = await self.session.execute(
            select(StrategyDefinition, StockPool.pool_code, StockPool.pool_name)
            .outerjoin(StockPool, StockPool.id == StrategyDefinition.pool_id)
            .order_by(StrategyDefinition.updated_at.desc(), StrategyDefinition.strategy_code)
        )
        definitions = [
            {"definition": definition, "pool_code": pool_code, "pool_name": pool_name}
            for definition, pool_code, pool_name in rows.all()
        ]
        if not definitions:
            return []
        strategy_ids = [item["definition"].id for item in definitions]
        candidate_rows = await self.session.execute(
            select(
                StrategyCandidate.strategy_id,
                func.count(StrategyCandidate.id).label("total_count"),
                func.max(StrategyCandidate.signal_trade_date).label("latest_signal_trade_date"),
                func.count(StrategyCandidate.id).filter(
                    StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching"))
                ).label("awaiting_count"),
                func.count(StrategyCandidate.id).filter(
                    StrategyCandidate.candidate_status == "not_triggered"
                ).label("not_triggered_count"),
            )
            .where(StrategyCandidate.strategy_id.in_(strategy_ids))
            .group_by(StrategyCandidate.strategy_id)
        )
        candidate_summary = {
            row.strategy_id: {
                "total_count": int(row.total_count or 0),
                "latest_signal_trade_date": row.latest_signal_trade_date,
                "awaiting_count": int(row.awaiting_count or 0),
                "not_triggered_count": int(row.not_triggered_count or 0),
            }
            for row in candidate_rows
        }
        trade_rows = await self.session.execute(
            select(
                StrategyPaperTrade.strategy_id,
                func.count(StrategyPaperTrade.id).label("total_count"),
                func.count(StrategyPaperTrade.id).filter(StrategyPaperTrade.trade_status == "open").label("open_count"),
                func.count(StrategyPaperTrade.id).filter(StrategyPaperTrade.trade_status == "closed").label("closed_count"),
                func.avg(StrategyPaperTrade.realized_pnl_pct).filter(
                    StrategyPaperTrade.trade_status == "closed"
                ).label("average_realized_pnl_pct"),
            )
            .where(StrategyPaperTrade.strategy_id.in_(strategy_ids))
            .group_by(StrategyPaperTrade.strategy_id)
        )
        trade_summary = {
            row.strategy_id: {
                "total_count": int(row.total_count or 0),
                "open_count": int(row.open_count or 0),
                "closed_count": int(row.closed_count or 0),
                "average_realized_pnl_pct": _number_or_none(row.average_realized_pnl_pct),
            }
            for row in trade_rows
        }
        for item in definitions:
            strategy_id = item["definition"].id
            item["candidate_summary"] = candidate_summary.get(strategy_id, _empty_candidate_summary())
            item["trade_summary"] = trade_summary.get(strategy_id, _empty_trade_summary())
        return definitions

    async def get_definition(self, strategy_code: str) -> StrategyDefinition | None:
        return (
            await self.session.execute(
                select(StrategyDefinition).where(StrategyDefinition.strategy_code == strategy_code)
            )
        ).scalar_one_or_none()

    async def get_version(
        self,
        *,
        strategy_id: int,
        version_no: int | None = None,
        version_id: int | None = None,
    ) -> StrategyVersion | None:
        statement = select(StrategyVersion).where(StrategyVersion.strategy_id == strategy_id)
        if version_id is not None:
            statement = statement.where(StrategyVersion.id == version_id)
        elif version_no is not None:
            statement = statement.where(StrategyVersion.version_no == version_no)
        else:
            statement = statement.order_by(StrategyVersion.version_no.desc()).limit(1)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_versions(self, *, strategy_id: int) -> list[StrategyVersion]:
        return list(
            (
                await self.session.execute(
                    select(StrategyVersion)
                    .where(StrategyVersion.strategy_id == strategy_id)
                    .order_by(StrategyVersion.version_no.desc())
                )
            ).scalars().all()
        )

    async def list_paper_versions(self, *, strategy_code: str | None = None) -> list[dict]:
        statement = (
            select(StrategyDefinition, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.strategy_id == StrategyDefinition.id)
            .where(
                StrategyDefinition.status == "paper",
                StrategyVersion.status == "paper",
            )
            .order_by(StrategyDefinition.strategy_code, StrategyVersion.version_no)
        )
        if strategy_code:
            statement = statement.where(StrategyDefinition.strategy_code == strategy_code)
        rows = await self.session.execute(statement)
        return [{"definition": definition, "version": version} for definition, version in rows.all()]

    async def create_version(
        self,
        *,
        strategy_id: int,
        implementation_code: str,
        rule_config: dict,
        risk_config: dict,
        status: str = "draft",
    ) -> StrategyVersion:
        version_no = int(
            await self.session.scalar(
                select(func.coalesce(func.max(StrategyVersion.version_no), 0) + 1).where(
                    StrategyVersion.strategy_id == strategy_id
                )
            )
            or 1
        )
        version = StrategyVersion(
            strategy_id=strategy_id,
            version_no=version_no,
            implementation_code=implementation_code,
            status=status,
            rule_config=rule_config,
            risk_config=risk_config,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def update_version(self, version: StrategyVersion, values: dict) -> StrategyVersion:
        for field, value in values.items():
            setattr(version, field, value)
        version.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return version

    async def latest_ready_report_trade_date(self) -> date | None:
        return await self.session.scalar(
            select(func.max(MarketSentimentDaily.trade_date)).where(
                MarketSentimentDaily.calculation_version == MARKET_SENTIMENT_CALCULATION_VERSION,
                MarketSentimentDaily.status == "ready",
            )
        )

    async def open_trade_dates_between(self, *, start_date: date, end_date: date) -> list[date]:
        if end_date < start_date:
            return []
        rows = await self.session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == "CN",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date.between(start_date, end_date),
            )
            .order_by(TradeCalendar.trade_date)
        )
        return list(rows.scalars().all())

    async def open_trade_dates_ending_at(self, *, end_date: date, limit: int) -> list[date]:
        if limit <= 0:
            return []
        rows = await self.session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == "CN",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit)
        )
        return list(reversed(rows.scalars().all()))

    async def next_open_trade_date(self, trade_date: date) -> date | None:
        result = await self.session.scalar(
            select(TradeCalendar.next_trade_date).where(
                TradeCalendar.market == "CN",
                TradeCalendar.trade_date == trade_date,
                TradeCalendar.is_open.is_(True),
            )
        )
        if result:
            return result
        return await self.session.scalar(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == "CN",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date > trade_date,
            )
            .order_by(TradeCalendar.trade_date)
            .limit(1)
        )

    async def get_pool(self, pool_code: str) -> StockPool | None:
        return (await self.session.execute(select(StockPool).where(StockPool.pool_code == pool_code))).scalar_one_or_none()

    async def create_definition_with_pool(self, *, definition_values: dict, pool_code: str) -> StrategyDefinition:
        pool = StockPool(
            pool_code=pool_code,
            pool_name=f"{definition_values['strategy_name']}策略池",
            pool_type="strategy",
            description="由策略候选事实动态维护；不能手工修改成员。",
            is_system=True,
            is_enabled=True,
            is_dynamic=True,
            dynamic_rule="strategy_candidates",
            sort_order=50,
        )
        self.session.add(pool)
        await self.session.flush()
        self.session.add(
            StockPoolRealtimePolicy(
                pool_id=pool.id,
                is_enabled=False,
                priority=30,
                quote_lane="off",
                minute_lane="off",
            )
        )
        definition = StrategyDefinition(pool_id=pool.id, **definition_values)
        self.session.add(definition)
        await self.session.flush()
        return definition

    async def update_definition(self, definition: StrategyDefinition, values: dict) -> StrategyDefinition:
        for field, value in values.items():
            setattr(definition, field, value)
        definition.updated_at = datetime.now(timezone.utc)
        pool_values: dict = {"updated_at": definition.updated_at}
        if "strategy_name" in values:
            pool_values["pool_name"] = f"{definition.strategy_name}策略池"
        if "status" in values:
            # A strategy-owned pool is system managed. Archiving a strategy
            # removes stale candidates from active pool views; restoring a
            # draft/research definition makes its dedicated pool visible again.
            pool_values["is_enabled"] = definition.status != "archived"
        if definition.pool_id is not None:
            await self.session.execute(
                update(StockPool).where(StockPool.id == definition.pool_id).values(**pool_values)
            )
        await self.session.flush()
        return definition

    async def load_daily_evaluation_contexts(
        self,
        *,
        feature_trade_dates: Iterable[date],
        decision_trade_dates: Iterable[date],
        universe: dict | None = None,
        stock_codes: set[str] | None = None,
    ) -> dict[date, dict[str, dict]]:
        """Load canonical facts for local strategy evaluation in bounded batches.

        ``feature_trade_dates`` contains the lookback window (usually at most
        80 sessions).  The heavier limit-up evidence and concept joins run for
        decision dates only, and concept members are limited to the day's
        limit-up stocks.  This avoids a cartesian all-stock/all-concept scan
        during historical calibration.
        """

        feature_dates = sorted(set(feature_trade_dates))
        decision_dates = sorted(set(decision_trade_dates))
        if not feature_dates:
            return {}
        if stock_codes is not None and not stock_codes:
            return {}
        universe = universe or {}
        factor_join = and_(
            StockFactorDaily.stock_code == DailyBar.stock_code,
            StockFactorDaily.trade_date == DailyBar.trade_date,
            StockFactorDaily.source == "system:daily_close",
        )
        fact_columns = (
            DailyBar.trade_date.label("trade_date"),
            DailyBar.stock_code.label("stock_code"),
            DailyBar.open_price,
            DailyBar.high_price,
            DailyBar.low_price,
            DailyBar.close_price,
            DailyBar.pre_close_price,
            DailyBar.change_pct,
            DailyBar.amount_yuan,
            StockFactorDaily.ma5,
            StockFactorDaily.ma10,
            StockFactorDaily.ma20,
            StockFactorDaily.ma30,
            StockFactorDaily.ma60,
            StockFactorDaily.volume_ratio,
            StockFactorDaily.amount_ratio,
            StockFactorDaily.volatility_20d,
            StockFactorDaily.close_position,
            # The strategy evaluator only needs the listing-day scalar.
            # Loading/parsing the complete JSONB feature payload for every
            # stock/date dominates historical backtest input time.
            StockFactorDaily.features.op("->>")("history_days").label("history_days"),
        )
        stock_metadata: dict[str, dict] = {}
        if stock_codes is None:
            statement = (
                select(
                    Stock.stock_name.label("stock_name"),
                    Stock.exchange.label("exchange"),
                    Stock.status.label("stock_status"),
                    Stock.is_st.label("is_st"),
                    *fact_columns,
                )
                .select_from(DailyBar)
                .join(Stock, Stock.stock_code == DailyBar.stock_code)
                .outerjoin(StockFactorDaily, factor_join)
                .where(DailyBar.trade_date.in_(feature_dates))
            )
            markets = [str(value).upper() for value in universe.get("markets") or []]
            if markets:
                statement = statement.where(Stock.exchange.in_(markets))
            if bool(universe.get("exclude_st", True)):
                statement = statement.where(Stock.is_st.is_(False))
            if bool(universe.get("active_only", True)):
                statement = statement.where(Stock.status == "active")
        else:
            metadata_rows = await self.session.execute(
                select(Stock.stock_code, Stock.stock_name, Stock.exchange, Stock.status, Stock.is_st).where(
                    Stock.stock_code.in_(stock_codes)
                )
            )
            stock_metadata = {
                str(row.stock_code): {
                    "stock_name": row.stock_name,
                    "exchange": row.exchange,
                    "stock_status": row.status,
                    "is_st": bool(row.is_st),
                }
                for row in metadata_rows
            }
            statement = (
                select(*fact_columns)
                .select_from(DailyBar)
                .outerjoin(StockFactorDaily, factor_join)
                .where(DailyBar.trade_date.in_(feature_dates), DailyBar.stock_code.in_(stock_codes))
            )
        contexts: dict[date, dict[str, dict]] = defaultdict(dict)
        if stock_codes is None:
            rows = await self.session.execute(statement)
            for row in rows.mappings().all():
                stock_code = str(row["stock_code"])
                contexts[row["trade_date"]][stock_code] = _evaluation_context(
                    stock_code=stock_code,
                    metadata=row,
                    facts=row,
                )
        else:
            # asyncpg's eager ``fetch`` becomes the dominant latency when a
            # cloud connection receives tens of thousands of narrow rows.
            # Aggregate each selected stock's ordered lookback server-side so
            # the wire protocol returns one row per candidate stock.
            history_payload = func.jsonb_build_object(
                "trade_date", DailyBar.trade_date,
                "open_price", DailyBar.open_price,
                "high_price", DailyBar.high_price,
                "low_price", DailyBar.low_price,
                "close_price", DailyBar.close_price,
                "pre_close_price", DailyBar.pre_close_price,
                "change_pct", DailyBar.change_pct,
                "amount_yuan", DailyBar.amount_yuan,
                "ma5", StockFactorDaily.ma5,
                "ma10", StockFactorDaily.ma10,
                "ma20", StockFactorDaily.ma20,
                "ma30", StockFactorDaily.ma30,
                "ma60", StockFactorDaily.ma60,
                "volume_ratio", StockFactorDaily.volume_ratio,
                "amount_ratio", StockFactorDaily.amount_ratio,
                "volatility_20d", StockFactorDaily.volatility_20d,
                "close_position", StockFactorDaily.close_position,
                "history_days", StockFactorDaily.features.op("->>")("history_days"),
            )
            history_rows = await self.session.execute(
                select(
                    DailyBar.stock_code,
                    func.jsonb_agg(aggregate_order_by(history_payload, DailyBar.trade_date)).label("history"),
                )
                .select_from(DailyBar)
                .outerjoin(StockFactorDaily, factor_join)
                .where(DailyBar.trade_date.in_(feature_dates), DailyBar.stock_code.in_(stock_codes))
                .group_by(DailyBar.stock_code)
            )
            for row in history_rows.mappings().all():
                stock_code = str(row["stock_code"])
                metadata = stock_metadata.get(stock_code)
                if metadata is None:
                    continue
                for facts in row["history"] or []:
                    trade_date = facts.get("trade_date")
                    if isinstance(trade_date, str):
                        trade_date = date.fromisoformat(trade_date)
                    if not isinstance(trade_date, date):
                        continue
                    contexts[trade_date][stock_code] = _evaluation_context(
                        stock_code=stock_code,
                        metadata=metadata,
                        facts=facts,
                    )
        if not decision_dates:
            return contexts

        # Turnover and fund-flow values are only inspected on a signal date.
        # Keeping these outer joins out of the full lookback query makes the
        # historical payload bounded by the actual rule horizon instead of
        # joining three large fact tables for every historical row.
        basic_join = and_(
            StockDailyBasic.stock_code == DailyBar.stock_code,
            StockDailyBasic.trade_date == DailyBar.trade_date,
            StockDailyBasic.source == "tushare:daily_basic",
        )
        fund_join = and_(
            StockFundFlowDaily.stock_code == DailyBar.stock_code,
            StockFundFlowDaily.trade_date == DailyBar.trade_date,
            StockFundFlowDaily.source == "tushare:moneyflow",
        )
        decision_statement = (
            select(
                DailyBar.trade_date,
                DailyBar.stock_code,
                StockDailyBasic.turnover_rate,
                StockFundFlowDaily.main_net_inflow,
                StockFundFlowDaily.main_net_ratio,
            )
            .select_from(DailyBar)
            .outerjoin(StockDailyBasic, basic_join)
            .outerjoin(StockFundFlowDaily, fund_join)
            .where(DailyBar.trade_date.in_(decision_dates))
        )
        if stock_codes is not None:
            decision_statement = decision_statement.where(DailyBar.stock_code.in_(stock_codes))
        decision_rows = await self.session.execute(decision_statement)
        for row in decision_rows.mappings().all():
            context = contexts.get(row["trade_date"], {}).get(str(row["stock_code"]))
            if context is None:
                continue
            current = context["current"]
            current["turnover_rate"] = _number(row["turnover_rate"])
            current["main_net_inflow"] = _number(row["main_net_inflow"])
            current["main_net_ratio"] = _number(row["main_net_ratio"])

        event_rows = await self.session.execute(
            select(LimitEventDaily).where(
                LimitEventDaily.trade_date.in_(decision_dates),
                LimitEventDaily.event_type.in_(("limit_up", "limit_break")),
            )
        )
        limit_up_codes: set[str] = set()
        for event in event_rows.scalars().all():
            context = contexts.get(event.trade_date, {}).get(event.stock_code)
            if context is None:
                continue
            context["events"][event.event_type] = {
                "event_type": event.event_type,
                "close_price": _number(event.close_price),
                "limit_price": _number(event.limit_price),
                "first_time": event.first_time.isoformat() if event.first_time else None,
                "last_time": event.last_time.isoformat() if event.last_time else None,
                "open_count": event.open_count,
                "turnover_amount": _number(event.turnover_amount),
                "source": event.source,
            }
            if event.event_type == "limit_up":
                limit_up_codes.add(event.stock_code)

        evidence_rows = await self.session.execute(
            select(MarketLimitUpEvidenceDaily).where(
                MarketLimitUpEvidenceDaily.trade_date.in_(decision_dates),
                MarketLimitUpEvidenceDaily.calculation_version == MARKET_SENTIMENT_CALCULATION_VERSION,
                MarketLimitUpEvidenceDaily.status == "ready",
            )
        )
        for evidence in evidence_rows.scalars().all():
            context = contexts.get(evidence.trade_date, {}).get(evidence.stock_code)
            if context is not None:
                context["limit_evidence"] = {
                    "board_count": evidence.board_count,
                    "market_snapshot": evidence.market_snapshot or {},
                    "sector_context": evidence.sector_context or [],
                    "coverage": evidence.coverage or {},
                }

        await self._attach_active_emotion(contexts, decision_dates)
        if limit_up_codes:
            await self._attach_limit_up_concepts(contexts, decision_dates, limit_up_codes)
        return contexts

    async def load_backtest_evaluation_contexts(
        self,
        *,
        feature_trade_dates: Iterable[date],
        decision_trade_dates: Iterable[date],
        implementation_code: str,
        universe: dict | None = None,
    ) -> tuple[dict[date, dict[str, dict]], dict[date, set[str]]]:
        """Load only stocks that can still satisfy a fixed builtin rule.

        The SQL prefilter contains only necessary conditions from the immutable
        rule registry.  The Python evaluator remains the matching authority;
        this merely avoids transporting all-market lookback rows that cannot
        become a candidate on the signal day.
        """

        eligible_by_date = await self.prefilter_backtest_stock_codes(
            trade_dates=decision_trade_dates,
            implementation_code=implementation_code,
            universe=universe,
        )
        stock_codes = set().union(*eligible_by_date.values()) if eligible_by_date else set()
        contexts = await self._load_compact_backtest_contexts(
            feature_trade_dates=feature_trade_dates,
            decision_trade_dates=decision_trade_dates,
            stock_codes=stock_codes,
            eligible_by_date=eligible_by_date,
        )
        return contexts, eligible_by_date

    async def _load_compact_backtest_contexts(
        self,
        *,
        feature_trade_dates: Iterable[date],
        decision_trade_dates: Iterable[date],
        stock_codes: set[str],
        eligible_by_date: dict[date, set[str]],
    ) -> dict[date, dict[str, dict]]:
        """Build the minimum date matrix needed by daily baseline simulation."""

        feature_dates = sorted(set(feature_trade_dates))
        decision_dates = sorted(set(decision_trade_dates))
        if not feature_dates or not stock_codes:
            return {}
        metadata_rows = await self.session.execute(
            select(Stock.stock_code, Stock.stock_name, Stock.exchange, Stock.status, Stock.is_st).where(
                Stock.stock_code.in_(stock_codes)
            )
        )
        metadata = {
            str(row.stock_code): {
                "stock_name": row.stock_name,
                "exchange": row.exchange,
                "stock_status": row.status,
                "is_st": bool(row.is_st),
            }
            for row in metadata_rows
        }
        factor_join = and_(
            StockFactorDaily.stock_code == DailyBar.stock_code,
            StockFactorDaily.trade_date == DailyBar.trade_date,
            StockFactorDaily.source == "system:daily_close",
        )
        order_date = DailyBar.trade_date
        series_rows = await self.session.execute(
            select(
                DailyBar.stock_code,
                func.array_agg(aggregate_order_by(DailyBar.trade_date, order_date)).label("trade_dates"),
                func.array_agg(aggregate_order_by(DailyBar.open_price, order_date)).label("open_prices"),
                func.array_agg(aggregate_order_by(DailyBar.close_price, order_date)).label("close_prices"),
                func.array_agg(aggregate_order_by(DailyBar.high_price, order_date)).label("high_prices"),
                func.array_agg(aggregate_order_by(DailyBar.low_price, order_date)).label("low_prices"),
                func.array_agg(aggregate_order_by(StockFactorDaily.ma5, order_date)).label("ma5_values"),
                func.array_agg(aggregate_order_by(StockFactorDaily.ma10, order_date)).label("ma10_values"),
            )
            .select_from(DailyBar)
            .outerjoin(StockFactorDaily, factor_join)
            .where(DailyBar.trade_date.in_(feature_dates), DailyBar.stock_code.in_(stock_codes))
            .group_by(DailyBar.stock_code)
        )
        contexts: dict[date, dict[str, dict]] = defaultdict(dict)
        for row in series_rows.mappings().all():
            stock_code = str(row["stock_code"])
            stock = metadata.get(stock_code)
            if stock is None:
                continue
            for values in zip(
                row["trade_dates"] or [],
                row["open_prices"] or [],
                row["close_prices"] or [],
                row["high_prices"] or [],
                row["low_prices"] or [],
                row["ma5_values"] or [],
                row["ma10_values"] or [],
            ):
                trade_date, open_price, close_price, high_price, low_price, ma5, ma10 = values
                if not isinstance(trade_date, date):
                    continue
                contexts[trade_date][stock_code] = _evaluation_context(
                    stock_code=stock_code,
                    metadata=stock,
                    facts={
                        "open_price": open_price,
                        "close_price": close_price,
                        "high_price": high_price,
                        "low_price": low_price,
                        "ma5": ma5,
                        "ma10": ma10,
                    },
                )

        eligible_pairs = [
            (trade_date, stock_code)
            for trade_date, codes in eligible_by_date.items()
            for stock_code in codes
        ]
        if not eligible_pairs:
            return contexts

        basic_join = and_(
            StockDailyBasic.stock_code == DailyBar.stock_code,
            StockDailyBasic.trade_date == DailyBar.trade_date,
            StockDailyBasic.source == "tushare:daily_basic",
        )
        fund_join = and_(
            StockFundFlowDaily.stock_code == DailyBar.stock_code,
            StockFundFlowDaily.trade_date == DailyBar.trade_date,
            StockFundFlowDaily.source == "tushare:moneyflow",
        )
        target_rows = await self.session.execute(
            select(
                DailyBar.trade_date,
                DailyBar.stock_code,
                DailyBar.open_price,
                DailyBar.high_price,
                DailyBar.low_price,
                DailyBar.close_price,
                DailyBar.pre_close_price,
                DailyBar.change_pct,
                DailyBar.amount_yuan,
                StockFactorDaily.ma5,
                StockFactorDaily.ma10,
                StockFactorDaily.ma20,
                StockFactorDaily.ma30,
                StockFactorDaily.ma60,
                StockFactorDaily.volume_ratio,
                StockFactorDaily.amount_ratio,
                StockFactorDaily.volatility_20d,
                StockFactorDaily.close_position,
                StockFactorDaily.features.op("->>")("history_days").label("history_days"),
                StockDailyBasic.turnover_rate,
                StockFundFlowDaily.main_net_inflow,
                StockFundFlowDaily.main_net_ratio,
            )
            .select_from(DailyBar)
            .outerjoin(StockFactorDaily, factor_join)
            .outerjoin(StockDailyBasic, basic_join)
            .outerjoin(StockFundFlowDaily, fund_join)
            .where(tuple_(DailyBar.trade_date, DailyBar.stock_code).in_(eligible_pairs))
        )
        for row in target_rows.mappings().all():
            stock_code = str(row["stock_code"])
            context = contexts.get(row["trade_date"], {}).get(stock_code)
            if context is None:
                continue
            current = context["current"]
            current.update(
                {
                    "open_price": _number(row["open_price"]),
                    "high_price": _number(row["high_price"]),
                    "low_price": _number(row["low_price"]),
                    "close_price": _number(row["close_price"]),
                    "pre_close_price": _number(row["pre_close_price"]),
                    "change_pct": _number(row["change_pct"]),
                    "amount_yuan": _number(row["amount_yuan"]),
                    "ma5": _number(row["ma5"]),
                    "ma10": _number(row["ma10"]),
                    "ma20": _number(row["ma20"]),
                    "ma30": _number(row["ma30"]),
                    "ma60": _number(row["ma60"]),
                    "volume_ratio": _number(row["volume_ratio"]),
                    "amount_ratio": _number(row["amount_ratio"]),
                    "volatility_20d": _number(row["volatility_20d"]),
                    "close_position": _number(row["close_position"]),
                    "turnover_rate": _number(row["turnover_rate"]),
                    "main_net_inflow": _number(row["main_net_inflow"]),
                    "main_net_ratio": _number(row["main_net_ratio"]),
                    "history_days": _int_or_none(row["history_days"]),
                }
            )

        await self._attach_backtest_events_and_emotion(
            contexts=contexts,
            decision_dates=decision_dates,
            eligible_pairs=eligible_pairs,
        )
        return contexts

    async def _attach_backtest_events_and_emotion(
        self,
        *,
        contexts: dict[date, dict[str, dict]],
        decision_dates: list[date],
        eligible_pairs: list[tuple[date, str]],
    ) -> None:
        event_rows = await self.session.execute(
            select(LimitEventDaily).where(
                LimitEventDaily.event_type.in_(("limit_up", "limit_break")),
                tuple_(LimitEventDaily.trade_date, LimitEventDaily.stock_code).in_(eligible_pairs),
            )
        )
        limit_up_codes: set[str] = set()
        for event in event_rows.scalars().all():
            context = contexts.get(event.trade_date, {}).get(event.stock_code)
            if context is None:
                continue
            context["events"][event.event_type] = {
                "event_type": event.event_type,
                "close_price": _number(event.close_price),
                "limit_price": _number(event.limit_price),
                "first_time": event.first_time.isoformat() if event.first_time else None,
                "last_time": event.last_time.isoformat() if event.last_time else None,
                "open_count": event.open_count,
                "turnover_amount": _number(event.turnover_amount),
                "source": event.source,
            }
            if event.event_type == "limit_up":
                limit_up_codes.add(event.stock_code)

        evidence_rows = await self.session.execute(
            select(MarketLimitUpEvidenceDaily).where(
                MarketLimitUpEvidenceDaily.trade_date.in_(decision_dates),
                MarketLimitUpEvidenceDaily.calculation_version == MARKET_SENTIMENT_CALCULATION_VERSION,
                MarketLimitUpEvidenceDaily.status == "ready",
            )
        )
        for evidence in evidence_rows.scalars().all():
            context = contexts.get(evidence.trade_date, {}).get(evidence.stock_code)
            if context is not None:
                context["limit_evidence"] = {
                    "board_count": evidence.board_count,
                    "market_snapshot": evidence.market_snapshot or {},
                    "sector_context": evidence.sector_context or [],
                    "coverage": evidence.coverage or {},
                }
        await self._attach_active_emotion(contexts, decision_dates)
        if limit_up_codes:
            await self._attach_limit_up_concepts(contexts, decision_dates, limit_up_codes)

    async def prefilter_backtest_stock_codes(
        self,
        *,
        trade_dates: Iterable[date],
        implementation_code: str,
        universe: dict | None = None,
    ) -> dict[date, set[str]]:
        """Return date-scoped stocks satisfying a rule's necessary fields."""

        dates = sorted(set(trade_dates))
        if not dates:
            return {}
        universe = universe or {}
        factor_join = and_(
            StockFactorDaily.stock_code == DailyBar.stock_code,
            StockFactorDaily.trade_date == DailyBar.trade_date,
            StockFactorDaily.source == "system:daily_close",
        )
        statement = (
            select(DailyBar.trade_date, DailyBar.stock_code)
            .select_from(DailyBar)
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
            .outerjoin(StockFactorDaily, factor_join)
            .where(DailyBar.trade_date.in_(dates))
        )
        markets = [str(value).upper() for value in universe.get("markets") or []]
        if markets:
            statement = statement.where(Stock.exchange.in_(markets))
        if bool(universe.get("exclude_st", True)):
            statement = statement.where(Stock.is_st.is_(False))
        if bool(universe.get("active_only", True)):
            statement = statement.where(Stock.status == "active")
        try:
            minimum_amount = float(universe.get("minimum_amount_yuan") or 0)
        except (TypeError, ValueError):
            minimum_amount = 0.0
        if minimum_amount > 0:
            statement = statement.where(DailyBar.amount_yuan >= minimum_amount)
        try:
            minimum_listing_days = int(universe.get("minimum_listing_trade_days") or 0)
        except (TypeError, ValueError):
            minimum_listing_days = 0
        if minimum_listing_days > 0:
            statement = statement.where(
                cast(StockFactorDaily.features.op("->>")("history_days"), Integer) >= minimum_listing_days
            )

        if implementation_code == "high_turnover_surge":
            basic_join = and_(
                StockDailyBasic.stock_code == DailyBar.stock_code,
                StockDailyBasic.trade_date == DailyBar.trade_date,
                StockDailyBasic.source == "tushare:daily_basic",
            )
            fund_join = and_(
                StockFundFlowDaily.stock_code == DailyBar.stock_code,
                StockFundFlowDaily.trade_date == DailyBar.trade_date,
                StockFundFlowDaily.source == "tushare:moneyflow",
            )
            statement = statement.outerjoin(StockDailyBasic, basic_join).outerjoin(StockFundFlowDaily, fund_join)
        statement = statement.where(*_backtest_prefilter_conditions(implementation_code))
        rows = await self.session.execute(statement)
        result: dict[date, set[str]] = {item: set() for item in dates}
        for row in rows:
            result[row.trade_date].add(str(row.stock_code))
        return result

    async def _attach_active_emotion(self, contexts: dict[date, dict[str, dict]], trade_dates: list[date]) -> None:
        rows = await self.session.execute(
            select(MarketEmotionDaily)
            .join(MarketEmotionModel, MarketEmotionModel.model_code == MarketEmotionDaily.model_code)
            .where(
                MarketEmotionDaily.trade_date.in_(trade_dates),
                MarketEmotionModel.status == "active",
            )
        )
        by_date = {row.trade_date: row for row in rows.scalars().all()}
        for trade_date, stock_contexts in contexts.items():
            emotion = by_date.get(trade_date)
            if emotion is None:
                continue
            payload = {
                "model_code": emotion.model_code,
                "status": emotion.status,
                "short_term_score": _number(emotion.short_term_score),
                "market_risk_on_score": _number(emotion.market_risk_on_score),
                "primary_stage_code": emotion.primary_stage_code,
                "auxiliary_state_code": emotion.auxiliary_state_code,
                "coverage": emotion.coverage or {},
            }
            for context in stock_contexts.values():
                context["emotion"] = payload

    async def _attach_limit_up_concepts(
        self,
        contexts: dict[date, dict[str, dict]],
        trade_dates: list[date],
        stock_codes: set[str],
    ) -> None:
        if not contexts or not trade_dates or not stock_codes:
            return
        heat_rows = await self.session.execute(
            select(
                MarketSectorHeatDaily.trade_date,
                MarketSectorHeatDaily.sector_code,
                MarketSectorHeatDaily.sector_name,
                MarketSectorHeatDaily.heat_rank,
                MarketSectorHeatDaily.heat_score,
                MarketSectorHeatDaily.metrics,
            )
            .where(
                MarketSectorHeatDaily.trade_date.in_(trade_dates),
                MarketSectorHeatDaily.calculation_version == MARKET_SENTIMENT_CALCULATION_VERSION,
                MarketSectorHeatDaily.status == "ready",
            )
        )
        heat_by_date_sector = {
            (row["trade_date"], str(row["sector_code"])): {
                "sector_code": str(row["sector_code"]),
                "sector_name": row["sector_name"],
                "heat_rank": _int_or_none(row["heat_rank"]),
                "heat_score": _number(row["heat_score"]),
                "metrics": dict(row["metrics"] or {}),
            }
            for row in heat_rows.mappings().all()
        }
        if not heat_by_date_sector:
            return
        memberships = await self._concept_memberships()
        for trade_date, stock_contexts in contexts.items():
            for stock_code in stock_contexts:
                if stock_code not in stock_codes:
                    continue
                context = stock_contexts[stock_code]
                seen_sector_codes: set[str] = set()
                for sector_code, _sector_name, start_date, end_date in memberships.get(stock_code) or []:
                    if sector_code in seen_sector_codes:
                        continue
                    if start_date is not None and start_date > trade_date:
                        continue
                    if end_date is not None and end_date < trade_date:
                        continue
                    heat = heat_by_date_sector.get((trade_date, sector_code))
                    if heat is None:
                        continue
                    seen_sector_codes.add(sector_code)
                    context["concept_context"].append(dict(heat))

    async def _concept_memberships(self) -> dict[str, list[tuple[str, str, date | None, date | None]]]:
        if self._concept_memberships_cache is not None:
            return self._concept_memberships_cache
        rows = await self.session.execute(
            select(
                SectorComponent.stock_code,
                SectorBasic.sector_code,
                SectorBasic.sector_name,
                SectorComponent.start_date,
                SectorComponent.end_date,
            )
            .join(SectorBasic, SectorBasic.sector_code == SectorComponent.sector_code)
            .where(SectorBasic.sector_type == "concept", SectorBasic.source.like("tushare:%"))
        )
        memberships: dict[str, list[tuple[str, str, date | None, date | None]]] = defaultdict(list)
        for row in rows:
            memberships[str(row.stock_code)].append(
                (str(row.sector_code), str(row.sector_name), row.start_date, row.end_date)
            )
        self._concept_memberships_cache = dict(memberships)
        return self._concept_memberships_cache

    async def list_candidates(
        self,
        *,
        strategy_code: str | None,
        signal_trade_date: date | None,
        limit: int,
    ) -> list[dict]:
        statement = (
            select(
                StrategyCandidate,
                StrategyDefinition.strategy_code,
                StrategyDefinition.strategy_name,
                Stock.stock_name,
                StrategyPaperTrade,
            )
            .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
            .outerjoin(Stock, Stock.stock_code == StrategyCandidate.stock_code)
            .outerjoin(StrategyPaperTrade, StrategyPaperTrade.candidate_id == StrategyCandidate.id)
        )
        if strategy_code:
            statement = statement.where(StrategyDefinition.strategy_code == strategy_code)
        if signal_trade_date:
            statement = statement.where(StrategyCandidate.signal_trade_date == signal_trade_date)
        rows = await self.session.execute(
            statement.order_by(
                StrategyCandidate.signal_trade_date.desc(),
                StrategyCandidate.rank_no.asc().nulls_last(),
                StrategyCandidate.score.desc().nulls_last(),
                StrategyCandidate.stock_code,
            ).limit(limit)
        )
        return [
            {
                "candidate": candidate,
                "strategy_code": code,
                "strategy_name": name,
                "stock_name": stock_name,
                "paper_trade": paper_trade,
            }
            for candidate, code, name, stock_name, paper_trade in rows.all()
        ]

    async def upsert_daily_candidates(
        self,
        *,
        definition: StrategyDefinition,
        version: StrategyVersion,
        signal_trade_date: date,
        confirmation_deadline: date | None,
        matched: list[dict],
    ) -> dict:
        """Idempotently reconcile one version's post-close candidate list."""

        existing_rows = await self.session.execute(
            select(StrategyCandidate).where(
                StrategyCandidate.strategy_version_id == version.id,
                StrategyCandidate.signal_trade_date == signal_trade_date,
            )
        )
        existing = {row.stock_code: row for row in existing_rows.scalars().all()}
        matched_codes = {str(item["stock_code"]) for item in matched}
        created = 0
        refreshed = 0
        cancelled = 0
        for rank_no, item in enumerate(sorted(matched, key=lambda value: (-float(value["score"] or 0), value["stock_code"])), start=1):
            stock_code = str(item["stock_code"])
            values = {
                "score": item.get("score"),
                "rank_no": rank_no,
                "confirmation_deadline": confirmation_deadline,
                "candidate_snapshot": item.get("candidate_snapshot") or {},
                "entry_plan": item.get("entry_plan") or {},
                "updated_at": datetime.now(timezone.utc),
            }
            candidate = existing.get(stock_code)
            if candidate is None:
                candidate = StrategyCandidate(
                    strategy_id=definition.id,
                    strategy_version_id=version.id,
                    signal_trade_date=signal_trade_date,
                    stock_code=stock_code,
                    candidate_status="pending_confirmation",
                    **values,
                )
                self.session.add(candidate)
                await self.session.flush()
                created += 1
                await self.record_signal_event(
                    strategy_id=definition.id,
                    strategy_version_id=version.id,
                    candidate_id=candidate.id,
                    stock_code=stock_code,
                    trade_date=signal_trade_date,
                    market_phase="post_close",
                    event_type="daily_candidate_created",
                    decision="matched",
                    reason_code="daily_rule_matched",
                    evidence={"score": item.get("score"), "reasons": (item.get("candidate_snapshot") or {}).get("reasons", [])},
                )
                continue
            if candidate.candidate_status in {"pending_confirmation", "watching"}:
                for key, value in values.items():
                    setattr(candidate, key, value)
                refreshed += 1

        for candidate in existing.values():
            if candidate.stock_code in matched_codes or candidate.candidate_status not in {"pending_confirmation", "watching"}:
                continue
            candidate.candidate_status = "cancelled"
            candidate.outcome_note = "同日事实重算后不再满足策略规则；未产生模拟成交。"
            candidate.updated_at = datetime.now(timezone.utc)
            cancelled += 1
            await self.record_signal_event(
                strategy_id=definition.id,
                strategy_version_id=version.id,
                candidate_id=candidate.id,
                stock_code=candidate.stock_code,
                trade_date=signal_trade_date,
                market_phase="post_close",
                event_type="daily_candidate_cancelled",
                decision="rejected",
                reason_code="daily_rule_no_longer_matched",
                evidence={"reason": candidate.outcome_note},
            )
        await self.session.flush()
        return {"created": created, "refreshed": refreshed, "cancelled": cancelled, "matched": len(matched)}

    async def record_signal_event(
        self,
        *,
        strategy_id: int,
        strategy_version_id: int,
        candidate_id: int | None,
        stock_code: str,
        trade_date: date,
        market_phase: str,
        event_type: str,
        decision: str,
        reason_code: str | None,
        evidence: dict,
        paper_trade_id: int | None = None,
        event_time: datetime | None = None,
    ) -> None:
        event_time = event_time or datetime.now(timezone.utc)
        fingerprint_payload = {
            "strategy_version_id": strategy_version_id,
            "candidate_id": candidate_id,
            "paper_trade_id": paper_trade_id,
            "stock_code": stock_code,
            "trade_date": trade_date.isoformat(),
            "market_phase": market_phase,
            "event_type": event_type,
            "decision": decision,
            "reason_code": reason_code,
        }
        fingerprint = sha256(json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        statement = insert(StrategySignalEvent).values(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            candidate_id=candidate_id,
            paper_trade_id=paper_trade_id,
            stock_code=stock_code,
            trade_date=trade_date,
            event_time=event_time,
            market_phase=market_phase,
            event_type=event_type,
            decision=decision,
            reason_code=reason_code,
            event_fingerprint=fingerprint,
            evidence=evidence,
        )
        await self.session.execute(statement.on_conflict_do_nothing(index_elements=[StrategySignalEvent.event_fingerprint]))

    async def create_backtest_run(
        self,
        *,
        run_code: str,
        strategy_id: int,
        strategy_version_id: int,
        start_date: date,
        end_date: date,
        fee_rate: float,
        slippage_bps: float,
        parameter_snapshot: dict,
    ) -> StrategyBacktestRun:
        run = StrategyBacktestRun(
            run_code=run_code,
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            start_date=start_date,
            end_date=end_date,
            execution_model="next_open_daily",
            status="running",
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            parameter_snapshot=parameter_snapshot,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def insert_backtest_trades(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for offset in range(0, len(rows), 500):
            statement = insert(StrategyBacktestTrade).values(rows[offset : offset + 500])
            await self.session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[
                        StrategyBacktestTrade.backtest_run_id,
                        StrategyBacktestTrade.stock_code,
                        StrategyBacktestTrade.signal_trade_date,
                    ]
                )
            )
        return len(rows)

    async def complete_backtest_run(self, run: StrategyBacktestRun, summary: dict) -> None:
        run.status = "completed"
        run.summary = summary
        run.finished_at = datetime.now(timezone.utc)
        run.updated_at = run.finished_at
        await self.session.flush()

    async def fail_backtest_run(self, run: StrategyBacktestRun, message: str) -> None:
        run.status = "failed"
        run.error_message = message[:4000]
        run.finished_at = datetime.now(timezone.utc)
        run.updated_at = run.finished_at
        await self.session.flush()

    async def cancel_backtest_run(self, run: StrategyBacktestRun, message: str) -> int:
        """Discard an interrupted run's partial trades and retain its audit row.

        A cancelled baseline must never look like a usable research sample.  The
        backtest persists completed batches for bounded transactions, so clear
        those rows before finalising the run as ``cancelled``.
        """

        deleted = await self.session.execute(
            delete(StrategyBacktestTrade).where(StrategyBacktestTrade.backtest_run_id == run.id)
        )
        run.status = "cancelled"
        run.error_message = message[:4000]
        run.summary = {
            **dict(run.summary or {}),
            "cancelled": True,
            "discarded_partial_trade_count": int(deleted.rowcount or 0),
        }
        run.finished_at = datetime.now(timezone.utc)
        run.updated_at = run.finished_at
        await self.session.flush()
        return int(deleted.rowcount or 0)

    async def list_backtest_runs(self, *, strategy_id: int, limit: int = 50) -> list[StrategyBacktestRun]:
        return list(
            (
                await self.session.execute(
                    select(StrategyBacktestRun)
                    .where(StrategyBacktestRun.strategy_id == strategy_id)
                    .order_by(StrategyBacktestRun.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def get_completed_backtest_run(
        self,
        *,
        strategy_id: int,
        strategy_version_id: int,
        run_code: str | None = None,
    ) -> StrategyBacktestRun | None:
        statement = select(StrategyBacktestRun).where(
            StrategyBacktestRun.strategy_id == strategy_id,
            StrategyBacktestRun.strategy_version_id == strategy_version_id,
            StrategyBacktestRun.status == "completed",
        )
        if run_code:
            statement = statement.where(StrategyBacktestRun.run_code == run_code)
        else:
            statement = statement.order_by(StrategyBacktestRun.finished_at.desc(), StrategyBacktestRun.id.desc()).limit(1)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_backtest_trades(self, *, backtest_run_id: int) -> list[SimpleNamespace]:
        """Load only the frozen facts required for parameter replay.

        Optimisation never reads entry/exit prices or execution snapshots.  A
        full ORM load for a high-frequency baseline needlessly transfers those
        JSONB payloads once per tuning round and can dominate its runtime.
        """

        rows = await self.session.execute(
            select(
                StrategyBacktestTrade.signal_trade_date,
                StrategyBacktestTrade.net_return_pct,
                StrategyBacktestTrade.candidate_snapshot,
            )
            .where(StrategyBacktestTrade.backtest_run_id == backtest_run_id)
            .order_by(StrategyBacktestTrade.signal_trade_date, StrategyBacktestTrade.id)
        )
        return [
            SimpleNamespace(
                signal_trade_date=row.signal_trade_date,
                net_return_pct=row.net_return_pct,
                candidate_snapshot=row.candidate_snapshot or {},
            )
            for row in rows
        ]

    async def max_backtest_trades_per_signal_date(self, *, backtest_run_id: int) -> int:
        """Return the largest persisted candidate count for one signal date.

        A subset replay is only defensible when the source baseline was not
        clipped by ``selection.max_candidates``.  The caller uses this cheap
        aggregate as a conservative guard before it evaluates threshold
        variants from the persisted candidate snapshots.
        """

        daily_counts = (
            select(
                StrategyBacktestTrade.signal_trade_date.label("signal_trade_date"),
                func.count(StrategyBacktestTrade.id).label("trade_count"),
            )
            .where(StrategyBacktestTrade.backtest_run_id == backtest_run_id)
            .group_by(StrategyBacktestTrade.signal_trade_date)
            .subquery()
        )
        value = (await self.session.execute(select(func.max(daily_counts.c.trade_count)))).scalar_one_or_none()
        return int(value or 0)

    async def create_optimization_run(
        self,
        *,
        run_code: str,
        strategy_id: int,
        strategy_version_id: int,
        baseline_backtest_run_id: int,
        train_end_date: date,
        search_space: dict,
        requirements: dict,
    ) -> StrategyOptimizationRun:
        run = StrategyOptimizationRun(
            run_code=run_code,
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            baseline_backtest_run_id=baseline_backtest_run_id,
            status="running",
            train_end_date=train_end_date,
            search_space=search_space,
            requirements=requirements,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def insert_optimization_trials(self, *, optimization_run_id: int, rows: list[dict]) -> int:
        if not rows:
            return 0
        for offset in range(0, len(rows), 200):
            await self.session.execute(
                insert(StrategyOptimizationTrial)
                .values(rows[offset : offset + 200])
                .on_conflict_do_nothing(
                    index_elements=[StrategyOptimizationTrial.optimization_run_id, StrategyOptimizationTrial.trial_no]
                )
            )
        return len(rows)

    async def complete_optimization_run(self, run: StrategyOptimizationRun, summary: dict) -> None:
        run.status = "completed"
        run.summary = summary
        run.finished_at = datetime.now(timezone.utc)
        run.updated_at = run.finished_at
        await self.session.flush()

    async def fail_optimization_run(self, run: StrategyOptimizationRun, message: str) -> None:
        run.status = "failed"
        run.error_message = message[:4000]
        run.finished_at = datetime.now(timezone.utc)
        run.updated_at = run.finished_at
        await self.session.flush()

    async def list_optimization_runs(self, *, strategy_id: int, limit: int = 20) -> list[StrategyOptimizationRun]:
        return list(
            (
                await self.session.execute(
                    select(StrategyOptimizationRun)
                    .where(StrategyOptimizationRun.strategy_id == strategy_id)
                    .order_by(StrategyOptimizationRun.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def list_optimization_trials(self, *, optimization_run_id: int, limit: int = 50) -> list[StrategyOptimizationTrial]:
        return list(
            (
                await self.session.execute(
                    select(StrategyOptimizationTrial)
                    .where(StrategyOptimizationTrial.optimization_run_id == optimization_run_id)
                    .order_by(StrategyOptimizationTrial.rank_no.asc().nulls_last(), StrategyOptimizationTrial.trial_no)
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def list_runtime_candidates(self, *, trade_date: date) -> list[dict]:
        rows = await self.session.execute(
            select(StrategyCandidate, StrategyDefinition, StrategyVersion)
            .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
            .join(StrategyVersion, StrategyVersion.id == StrategyCandidate.strategy_version_id)
            .where(
                StrategyDefinition.status == "paper",
                StrategyVersion.status == "paper",
                StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching")),
                StrategyCandidate.confirmation_deadline == trade_date,
            )
            .order_by(StrategyCandidate.rank_no.asc().nulls_last(), StrategyCandidate.score.desc().nulls_last())
        )
        return [
            {"candidate": candidate, "definition": definition, "version": version}
            for candidate, definition, version in rows.all()
        ]

    async def list_open_paper_trades(self) -> list[dict]:
        rows = await self.session.execute(
            select(StrategyPaperTrade, StrategyCandidate, StrategyDefinition, StrategyVersion)
            .join(StrategyCandidate, StrategyCandidate.id == StrategyPaperTrade.candidate_id)
            .join(StrategyDefinition, StrategyDefinition.id == StrategyPaperTrade.strategy_id)
            .join(StrategyVersion, StrategyVersion.id == StrategyCandidate.strategy_version_id)
            .where(
                StrategyPaperTrade.trade_status == "open",
                StrategyDefinition.status == "paper",
                StrategyVersion.status == "paper",
            )
            .order_by(StrategyPaperTrade.entry_at, StrategyPaperTrade.id)
        )
        return [
            {"paper_trade": trade, "candidate": candidate, "definition": definition, "version": version}
            for trade, candidate, definition, version in rows.all()
        ]

    async def mark_candidate_status(
        self,
        candidate: StrategyCandidate,
        *,
        status: str,
        outcome_note: str | None = None,
        confirmed_at: datetime | None = None,
    ) -> None:
        candidate.candidate_status = status
        candidate.outcome_note = outcome_note
        if confirmed_at is not None:
            candidate.confirmed_at = confirmed_at
        candidate.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def create_paper_trade_with_entry(
        self,
        *,
        candidate: StrategyCandidate,
        definition: StrategyDefinition,
        entry_at: datetime,
        entry_price: float,
        quantity: int,
        evidence: dict,
        risk_plan: dict,
    ) -> StrategyPaperTrade:
        trade = StrategyPaperTrade(
            candidate_id=candidate.id,
            strategy_id=definition.id,
            stock_code=candidate.stock_code,
            trade_status="open",
            entry_at=entry_at,
            entry_price=entry_price,
            quantity=quantity,
            initial_quantity=quantity,
            open_quantity=quantity,
            entry_amount=entry_price * quantity,
            entry_evidence=evidence,
            risk_plan=risk_plan,
        )
        self.session.add(trade)
        await self.session.flush()
        self.session.add(
            StrategyPaperTradeLeg(
                paper_trade_id=trade.id,
                leg_no=1,
                side="buy",
                execution_time=entry_at,
                price=entry_price,
                quantity=quantity,
                amount=entry_price * quantity,
                trigger_code="entry_confirmation",
                evidence=evidence,
            )
        )
        await self.session.flush()
        return trade

    async def append_paper_sell_leg(
        self,
        *,
        trade: StrategyPaperTrade,
        execution_at: datetime,
        price: float,
        quantity: int,
        trigger_code: str,
        evidence: dict,
    ) -> StrategyPaperTrade:
        leg_no = int(
            await self.session.scalar(
                select(func.coalesce(func.max(StrategyPaperTradeLeg.leg_no), 0) + 1).where(
                    StrategyPaperTradeLeg.paper_trade_id == trade.id
                )
            )
            or 2
        )
        self.session.add(
            StrategyPaperTradeLeg(
                paper_trade_id=trade.id,
                leg_no=leg_no,
                side="sell",
                execution_time=execution_at,
                price=price,
                quantity=quantity,
                amount=price * quantity,
                trigger_code=trigger_code,
                evidence=evidence,
            )
        )
        trade.open_quantity = max(0, int(trade.open_quantity) - quantity)
        risk_plan = dict(trade.risk_plan or {})
        runtime_state = dict(risk_plan.get("runtime_state") or {})
        runtime_state["last_exit_trigger_code"] = trigger_code
        runtime_state["last_exit_at"] = execution_at.isoformat()
        risk_plan["runtime_state"] = runtime_state
        trade.risk_plan = risk_plan
        if trade.open_quantity == 0:
            legs = (
                await self.session.execute(
                    select(StrategyPaperTradeLeg).where(StrategyPaperTradeLeg.paper_trade_id == trade.id)
                )
            ).scalars().all()
            sell_amount = sum(float(item.amount or 0) for item in legs if item.side == "sell")
            entry_amount = float(trade.entry_amount or (trade.entry_price * trade.initial_quantity))
            fee_rate = float((risk_plan.get("fee_rate") or 0.0005))
            fees = (entry_amount + sell_amount) * fee_rate
            trade.trade_status = "closed"
            trade.exit_at = execution_at
            trade.exit_price = sell_amount / max(1, int(trade.initial_quantity))
            trade.exit_amount = sell_amount
            trade.realized_pnl_amount = sell_amount - entry_amount - fees
            trade.realized_pnl_pct = (sell_amount - entry_amount - fees) / entry_amount * 100 if entry_amount else None
            trade.exit_evidence = evidence
        trade.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return trade

    async def count_open_trade_days(self, *, start_date: date, end_date: date) -> int:
        if end_date < start_date:
            return 0
        return int(
            await self.session.scalar(
                select(func.count()).select_from(TradeCalendar).where(
                    TradeCalendar.market == "CN",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date.between(start_date, end_date),
                )
            )
            or 0
        )

    async def dashboard_counts(self) -> tuple[date | None, dict, dict]:
        latest_signal_trade_date = await self.session.scalar(select(func.max(StrategyCandidate.signal_trade_date)))
        candidate_rows = await self.session.execute(
            select(StrategyCandidate.candidate_status, func.count(StrategyCandidate.id)).group_by(
                StrategyCandidate.candidate_status
            )
        )
        trade_rows = await self.session.execute(
            select(StrategyPaperTrade.trade_status, func.count(StrategyPaperTrade.id)).group_by(StrategyPaperTrade.trade_status)
        )
        return (
            latest_signal_trade_date,
            {str(status): int(count or 0) for status, count in candidate_rows.all()},
            {str(status): int(count or 0) for status, count in trade_rows.all()},
        )

    async def commit(self) -> None:
        await self.session.commit()


def _backtest_prefilter_conditions(implementation_code: str):
    """Necessary, no-false-negative SQL conditions for fixed builtin rules."""

    if implementation_code == "trend_breakout":
        return (
            DailyBar.close_price >= _prior_daily_window_aggregate("high_price", func.max),
            DailyBar.change_pct >= 2.0,
            DailyBar.change_pct < 9.5,
            StockFactorDaily.amount_ratio >= 1.5,
            StockFactorDaily.close_position >= 0.65,
        )
    if implementation_code == "bullish_alignment":
        return (
            DailyBar.close_price > StockFactorDaily.ma5,
            StockFactorDaily.ma5 > StockFactorDaily.ma10,
            StockFactorDaily.ma10 > StockFactorDaily.ma20,
            StockFactorDaily.ma20 > StockFactorDaily.ma60,
            DailyBar.change_pct >= 1.0,
            StockFactorDaily.volume_ratio >= 1.2,
        )
    if implementation_code == "ma_golden_cross":
        return (
            DailyBar.change_pct > 0,
            StockFactorDaily.ma5 > StockFactorDaily.ma10,
            StockFactorDaily.volume_ratio >= 1.2,
        )
    if implementation_code == "volume_price_surge":
        return (
            DailyBar.change_pct >= 3.0,
            DailyBar.change_pct < 9.5,
            StockFactorDaily.volume_ratio >= 1.8,
            StockFactorDaily.amount_ratio >= 1.5,
            StockFactorDaily.close_position >= 0.70,
        )
    if implementation_code == "high_turnover_surge":
        return (
            DailyBar.change_pct >= 3.0,
            DailyBar.change_pct < 9.5,
            StockDailyBasic.turnover_rate >= 8.0,
            StockFundFlowDaily.main_net_inflow > 0,
            StockFundFlowDaily.main_net_ratio > 0,
            StockFactorDaily.close_position >= 0.65,
        )
    if implementation_code == "low_volatility_leader":
        return (
            DailyBar.close_price > StockFactorDaily.ma20,
            StockFactorDaily.volatility_20d <= 2.5,
            DailyBar.change_pct >= 2.0,
            StockFactorDaily.volume_ratio >= 1.3,
            StockFactorDaily.close_position >= 0.65,
        )
    if implementation_code == "pullback_ma20_bounce":
        return (
            DailyBar.low_price <= StockFactorDaily.ma20 * 1.01,
            DailyBar.close_price >= StockFactorDaily.ma20,
            DailyBar.close_price > DailyBar.open_price,
            StockFactorDaily.ma5 >= StockFactorDaily.ma10,
            StockFactorDaily.ma10 >= StockFactorDaily.ma20,
            StockFactorDaily.volume_ratio >= 1.0,
            StockFactorDaily.close_position >= 0.60,
        )
    if implementation_code == "n_day_low_reversal":
        return (
            DailyBar.low_price <= _prior_daily_window_aggregate("low_price", func.min) * 1.02,
            DailyBar.close_price > DailyBar.open_price,
            DailyBar.change_pct >= 2.0,
            StockFactorDaily.close_position >= 0.70,
            StockFactorDaily.volume_ratio >= 1.2,
        )
    if implementation_code in {"theme_first_board_relay", "consecutive_limit_up_relay"}:
        return (
            select(LimitEventDaily.id)
            .where(
                LimitEventDaily.stock_code == DailyBar.stock_code,
                LimitEventDaily.trade_date == DailyBar.trade_date,
                LimitEventDaily.event_type == "limit_up",
            )
            .exists(),
        )
    if implementation_code == "broken_board_recovery":
        return (
            DailyBar.change_pct >= 3.0,
            StockFactorDaily.close_position >= 0.72,
            StockFactorDaily.volume_ratio >= 1.5,
            select(LimitEventDaily.id)
            .where(
                LimitEventDaily.stock_code == DailyBar.stock_code,
                LimitEventDaily.trade_date == DailyBar.trade_date,
                LimitEventDaily.event_type == "limit_break",
            )
            .exists(),
        )
    raise ValueError(f"unsupported builtin strategy implementation: {implementation_code}")


def _prior_daily_window_aggregate(column_name: str, aggregate):
    prior = DailyBar.__table__.alias(f"prior_{column_name}")
    window = (
        select(prior.c[column_name])
        .where(
            prior.c.stock_code == DailyBar.stock_code,
            prior.c.trade_date < DailyBar.trade_date,
        )
        .order_by(prior.c.trade_date.desc())
        .limit(20)
        .correlate(DailyBar)
        .subquery()
    )
    return select(aggregate(window.c[column_name])).scalar_subquery()


def _evaluation_context(*, stock_code: str, metadata: dict, facts: dict) -> dict:
    return {
        "stock_code": stock_code,
        "stock": {
            "stock_name": metadata["stock_name"],
            "exchange": metadata["exchange"],
            "status": metadata["stock_status"],
            "is_st": bool(metadata["is_st"]),
        },
        "current": {
            "open_price": _number(facts.get("open_price")),
            "high_price": _number(facts.get("high_price")),
            "low_price": _number(facts.get("low_price")),
            "close_price": _number(facts.get("close_price")),
            "pre_close_price": _number(facts.get("pre_close_price")),
            "change_pct": _number(facts.get("change_pct")),
            "amount_yuan": _number(facts.get("amount_yuan")),
            "ma5": _number(facts.get("ma5")),
            "ma10": _number(facts.get("ma10")),
            "ma20": _number(facts.get("ma20")),
            "ma30": _number(facts.get("ma30")),
            "ma60": _number(facts.get("ma60")),
            "volume_ratio": _number(facts.get("volume_ratio")),
            "amount_ratio": _number(facts.get("amount_ratio")),
            "volatility_20d": _number(facts.get("volatility_20d")),
            "close_position": _number(facts.get("close_position")),
            "turnover_rate": None,
            "main_net_inflow": None,
            "main_net_ratio": None,
            "history_days": _int_or_none(facts.get("history_days")),
        },
        "events": {},
        "limit_evidence": {},
        "concept_context": [],
        "emotion": {"status": "unavailable"},
    }


def _number_or_none(value) -> float | None:
    return float(value) if value is not None else None


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _empty_candidate_summary() -> dict:
    return {
        "total_count": 0,
        "latest_signal_trade_date": None,
        "awaiting_count": 0,
        "not_triggered_count": 0,
    }


def _empty_trade_summary() -> dict:
    return {
        "total_count": 0,
        "open_count": 0,
        "closed_count": 0,
        "average_realized_pnl_pct": None,
    }
