from __future__ import annotations

from datetime import date, datetime, timezone
from statistics import mean, median
from uuid import uuid4

from sqlalchemy import select

from app.modules.strategy_center.builtins import (
    BUILTIN_STRATEGY_IMPLEMENTATION_VERSION,
    default_risk_config,
    default_rule_config,
    evaluate_daily_candidate,
    get_builtin_spec,
    list_builtin_specs,
    resolve_strategy_configs,
)
from app.modules.strategy_center.models import (
    StrategyBacktestRun,
    StrategyBacktestTrade,
    StrategyDefinition,
    StrategyPaperTrade,
    StrategyVersion,
)
from app.modules.strategy_center.repository import StrategyCenterRepository
from app.modules.strategy_center.schemas import (
    StrategyDefinitionCreate,
    StrategyDefinitionUpdate,
    StrategyVersionCreate,
    StrategyVersionUpdate,
)


# The fixed builtin registry only reads the current bar plus the prior 20
# sessions (trend-breakout and n-day-low).  Listing age is supplied by the
# persisted factor scalar, so a 60-row payload is neither required nor safe
# for every backtest batch.
PRIOR_DAILY_RULE_LOOKBACK = 20
BACKTEST_SIGNAL_DAYS_PER_BATCH = 5
MINIMUM_PAPER_REVIEW_COMPLETED_TRADES = 30
# A short smoke test can easily generate more than 30 independent signals in
# a strong market.  It is useful for proving the pipeline, but it must not
# unlock paper trading without a representative historical sample.
MINIMUM_PAPER_REVIEW_SIGNAL_DATES = 120


class StrategyCenterError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _qualifies_for_paper_review(summary: dict) -> bool:
    """Return whether a completed run is large enough for human review.

    This deliberately does *not* approve or promote a strategy.  It only
    unlocks the explicit, human-operated paper promotion endpoint after both
    a sufficiently broad historical interval and enough closed T+1 trades.
    """

    return (
        int(summary.get("signal_trade_date_count") or 0) >= MINIMUM_PAPER_REVIEW_SIGNAL_DATES
        and int(summary.get("completed_trade_count") or 0) >= MINIMUM_PAPER_REVIEW_COMPLETED_TRADES
    )


class StrategyCenterService:
    """Strategy definition, daily candidate and strict baseline backtest flow.

    The service only accepts a fixed implementation registry.  It deliberately
    separates a post-close *candidate* from a T+1 simulated execution: the
    former is a fact-based research output, the latter can occur only after a
    later confirmation engine records a real-time signal.
    """

    def __init__(self, repository: StrategyCenterRepository) -> None:
        self.repository = repository

    async def dashboard(self) -> dict:
        definitions = [self._read_definition(item) for item in await self.repository.list_definitions()]
        latest_signal_trade_date, candidate_counts, paper_trade_counts = await self.repository.dashboard_counts()
        return {
            "definitions": definitions,
            "latest_signal_trade_date": latest_signal_trade_date,
            "candidate_counts": candidate_counts,
            "paper_trade_counts": paper_trade_counts,
            "execution_ready": bool(any(item["status"] == "paper" for item in definitions)),
            "execution_readiness_reason": "只有完成 next_open_daily 基线回测并由人工切换为 paper 的版本，才会生成 T 日候选并进入 T+1 模拟确认；不会连接券商。",
        }

    async def builtin_templates(self) -> list[dict]:
        return [spec.template() for spec in list_builtin_specs()]

    async def bootstrap_builtin_definitions(self) -> dict:
        created: list[str] = []
        skipped: list[str] = []
        for spec in list_builtin_specs():
            if await self.repository.get_definition(spec.implementation_code):
                skipped.append(spec.implementation_code)
                continue
            pool_code = f"strategy_{spec.implementation_code}"
            definition = await self.repository.create_definition_with_pool(
                definition_values={
                    "strategy_code": spec.implementation_code,
                    "strategy_name": spec.strategy_name,
                    "description": spec.description,
                    "status": "research",
                    "strategy_type": "short_term",
                    "entry_mode": spec.entry_mode,
                    "max_holding_trade_days": spec.max_holding_trade_days,
                    "rule_config": default_rule_config(spec.implementation_code),
                    "risk_config": default_risk_config(spec.implementation_code),
                },
                pool_code=pool_code,
            )
            await self.repository.create_version(
                strategy_id=definition.id,
                implementation_code=spec.implementation_code,
                rule_config=default_rule_config(spec.implementation_code),
                risk_config=default_risk_config(spec.implementation_code),
            )
            created.append(spec.implementation_code)
        await self.repository.commit()
        return {"created": created, "skipped": skipped, "implementation_version": BUILTIN_STRATEGY_IMPLEMENTATION_VERSION}

    async def create_definition(self, payload: StrategyDefinitionCreate) -> dict:
        if await self.repository.get_definition(payload.strategy_code):
            raise StrategyCenterError("strategy_code_exists", f"策略代码已存在: {payload.strategy_code}")
        pool_code = f"strategy_{payload.strategy_code}"
        if await self.repository.get_pool(pool_code):
            raise StrategyCenterError("strategy_pool_code_exists", f"策略专属股票池代码已存在: {pool_code}")
        implementation_code = str(payload.implementation_code or payload.strategy_code)
        spec = get_builtin_spec(implementation_code)
        if spec is None:
            raise StrategyCenterError(
                "unsupported_strategy_implementation",
                "当前只能基于已实现、可审计的策略模板创建策略定义；新增实现需先补齐 evaluator 与测试。",
                {"implementation_code": implementation_code},
            )
        if payload.entry_mode != spec.entry_mode or payload.max_holding_trade_days != spec.max_holding_trade_days:
            raise StrategyCenterError(
                "strategy_contract_mismatch",
                "内置实现的确认时点和默认持有周期属于实现契约；请使用模板默认值，后续风险周期通过新版本调整。",
                {
                    "implementation_code": implementation_code,
                    "entry_mode": spec.entry_mode,
                    "max_holding_trade_days": spec.max_holding_trade_days,
                },
            )
        rule_config = {**default_rule_config(implementation_code), **(payload.rule_config or {})}
        rule_config["implementation_code"] = implementation_code
        risk_config = {**default_risk_config(implementation_code), **(payload.risk_config or {})}
        definition = await self.repository.create_definition_with_pool(
            definition_values={
                **payload.model_dump(exclude={"implementation_code"}),
                "status": "draft",
                "strategy_type": "short_term",
                "rule_config": rule_config,
                "risk_config": risk_config,
            },
            pool_code=pool_code,
        )
        await self.repository.create_version(
            strategy_id=definition.id,
            implementation_code=implementation_code,
            rule_config=rule_config,
            risk_config=risk_config,
        )
        await self.repository.commit()
        return self._read_definition(
            {
                "definition": definition,
                "pool_code": pool_code,
                "pool_name": f"{definition.strategy_name}策略池",
                "candidate_summary": {},
                "trade_summary": {},
            }
        )

    async def update_definition(self, strategy_code: str, payload: StrategyDefinitionUpdate) -> dict:
        definition = await self._require_definition(strategy_code)
        values = payload.model_dump(exclude_unset=True)
        if values.get("status") in {"enabled", "paper"}:
            raise StrategyCenterError(
                "strategy_status_invalid",
                "策略状态改为 paper；启用模拟运行只能通过具体版本完成基线回测并显式提升。",
            )
        immutable_fields = {"entry_mode", "max_holding_trade_days", "rule_config", "risk_config"}
        attempted = sorted(immutable_fields.intersection(values))
        if attempted:
            raise StrategyCenterError(
                "strategy_version_required",
                "确认时点、持有周期、规则和风控参数必须新建策略版本，不能直接改写定义或历史候选。",
                {"fields": attempted},
            )
        updated = await self.repository.update_definition(definition, values)
        await self.repository.commit()
        definitions = await self.repository.list_definitions()
        row = next((item for item in definitions if item["definition"].strategy_code == updated.strategy_code), None)
        if row is None:  # pragma: no cover - database consistency guard.
            raise StrategyCenterError("strategy_not_found", f"策略不存在: {strategy_code}")
        return self._read_definition(row)

    async def versions(self, strategy_code: str) -> list[dict]:
        definition = await self._require_definition(strategy_code)
        versions = await self.repository.list_versions(strategy_id=definition.id)
        return [self._read_version(item) for item in versions]

    async def create_version(self, strategy_code: str, payload: StrategyVersionCreate) -> dict:
        definition = await self._require_definition(strategy_code)
        spec = get_builtin_spec(payload.implementation_code)
        if spec is None:
            raise StrategyCenterError("unsupported_strategy_implementation", f"未实现的策略 evaluator: {payload.implementation_code}")
        latest = await self.repository.get_version(strategy_id=definition.id)
        if latest is not None and payload.implementation_code != latest.implementation_code:
            raise StrategyCenterError(
                "strategy_implementation_immutable",
                "同一策略定义不能切换实现模板；请为另一套选股逻辑新建策略定义。",
            )
        if definition.entry_mode != spec.entry_mode:
            raise StrategyCenterError(
                "strategy_contract_mismatch",
                "策略定义的确认时点与实现模板不一致，拒绝创建无法准确执行的版本。",
            )
        base_rule = dict(latest.rule_config or {}) if latest else default_rule_config(spec.implementation_code)
        base_risk = dict(latest.risk_config or {}) if latest else default_risk_config(spec.implementation_code)
        rule_config = {**default_rule_config(spec.implementation_code), **base_rule, **(payload.rule_config or {})}
        rule_config["implementation_code"] = spec.implementation_code
        risk_config = {**default_risk_config(spec.implementation_code), **base_risk, **(payload.risk_config or {})}
        version = await self.repository.create_version(
            strategy_id=definition.id,
            implementation_code=spec.implementation_code,
            rule_config=rule_config,
            risk_config=risk_config,
        )
        await self.repository.commit()
        return self._read_version(version)

    async def update_version(self, strategy_code: str, version_no: int, payload: StrategyVersionUpdate) -> dict:
        definition = await self._require_definition(strategy_code)
        version = await self.repository.get_version(strategy_id=definition.id, version_no=version_no)
        if version is None:
            raise StrategyCenterError("strategy_version_not_found", f"策略版本不存在: {strategy_code} v{version_no}")
        if version.status != "draft":
            raise StrategyCenterError("strategy_version_immutable", "只有草稿版本可编辑；回测或 paper 版本必须新建版本。")
        values = payload.model_dump(exclude_unset=True)
        if "implementation_code" in values:
            spec = get_builtin_spec(values["implementation_code"])
            if spec is None:
                raise StrategyCenterError("unsupported_strategy_implementation", f"未实现的策略 evaluator: {values['implementation_code']}")
        else:
            spec = get_builtin_spec(version.implementation_code)
        if spec is None:  # pragma: no cover - migration guard.
            raise StrategyCenterError("unsupported_strategy_implementation", "历史策略没有可用 evaluator。")
        if values.get("implementation_code") and values["implementation_code"] != version.implementation_code:
            raise StrategyCenterError(
                "strategy_implementation_immutable",
                "已创建版本的实现模板不可修改；请创建新的策略定义。",
            )
        if "rule_config" in values:
            values["rule_config"] = {**default_rule_config(spec.implementation_code), **(version.rule_config or {}), **values["rule_config"]}
            values["rule_config"]["implementation_code"] = spec.implementation_code
        if "risk_config" in values:
            values["risk_config"] = {**default_risk_config(spec.implementation_code), **(version.risk_config or {}), **values["risk_config"]}
        updated = await self.repository.update_version(version, values)
        await self.repository.commit()
        return self._read_version(updated)

    async def candidates(self, *, strategy_code: str | None, signal_trade_date, limit: int) -> list[dict]:
        rows = await self.repository.list_candidates(
            strategy_code=strategy_code,
            signal_trade_date=signal_trade_date,
            limit=limit,
        )
        return [self._read_candidate(item) for item in rows]

    async def backtests(self, *, strategy_code: str, limit: int = 20) -> list[dict]:
        definition = await self._require_definition(strategy_code)
        runs = await self.repository.list_backtest_runs(strategy_id=definition.id, limit=limit)
        return [self._read_backtest_run(run) for run in runs]

    async def evaluate_daily_candidates(
        self,
        *,
        trade_date: date | None = None,
        strategy_code: str | None = None,
        progress_reporter=None,
    ) -> dict:
        target_date = trade_date or await self.repository.latest_ready_report_trade_date()
        if target_date is None:
            raise StrategyCenterError("strategy_daily_facts_not_ready", "没有完成的盘后报告事实，不能生成策略候选。")
        versions = await self.repository.list_paper_versions(strategy_code=strategy_code)
        if not versions:
            return {
                "trade_date": target_date,
                "strategies": [],
                "reason": "没有 paper 状态的策略版本；需先完成历史基线回测，再由人工提升版本。",
            }
        feature_dates = await self.repository.open_trade_dates_ending_at(end_date=target_date, limit=61)
        if not feature_dates or feature_dates[-1] != target_date:
            raise StrategyCenterError("trade_calendar_incomplete", f"交易日历缺少 {target_date} 的开市日记录。")
        contexts = await self.repository.load_daily_evaluation_contexts(
            feature_trade_dates=feature_dates,
            decision_trade_dates=[target_date],
        )
        target_contexts = contexts.get(target_date, {})
        next_date = await self.repository.next_open_trade_date(target_date)
        if next_date is None:
            raise StrategyCenterError(
                "next_trade_date_missing",
                f"交易日历没有 {target_date} 之后的下一开市日，拒绝生成无法确认的 T+1 候选。",
            )
        summaries: list[dict] = []
        for offset, item in enumerate(versions, start=1):
            definition: StrategyDefinition = item["definition"]
            version: StrategyVersion = item["version"]
            matched = self._evaluate_context_map(
                definition=definition,
                version=version,
                target_date=target_date,
                feature_dates=feature_dates,
                contexts=contexts,
            )
            max_candidates = _candidate_limit(version.rule_config)
            summary = await self.repository.upsert_daily_candidates(
                definition=definition,
                version=version,
                signal_trade_date=target_date,
                confirmation_deadline=next_date,
                matched=matched[:max_candidates],
            )
            summary.update(
                {
                    "strategy_code": definition.strategy_code,
                    "strategy_name": definition.strategy_name,
                    "version_no": version.version_no,
                    "implementation_code": version.implementation_code,
                    "scanned_stock_count": len(target_contexts),
                    "rule_matched_count": len(matched),
                    "candidate_limit": max_candidates,
                }
            )
            summaries.append(summary)
            if progress_reporter:
                await progress_reporter(
                    {
                        "stage": "daily_candidates",
                        "trade_date": target_date.isoformat(),
                        "completed_strategies": offset,
                        "total_strategies": len(versions),
                        "strategy_code": definition.strategy_code,
                        "matched": len(matched),
                    }
                )
        await self.repository.commit()
        return {
            "trade_date": target_date,
            "next_open_trade_date": next_date,
            "strategies": summaries,
            "provider_calls": 0,
            "llm_calls": 0,
        }

    async def run_backtest(
        self,
        *,
        strategy_code: str,
        version_no: int,
        start_date: date,
        end_date: date,
        fee_rate: float = 0.0005,
        slippage_bps: float = 10.0,
        progress_reporter=None,
    ) -> dict:
        definition = await self._require_definition(strategy_code)
        version = await self.repository.get_version(strategy_id=definition.id, version_no=version_no)
        if version is None:
            raise StrategyCenterError("strategy_version_not_found", f"策略版本不存在: {strategy_code} v{version_no}")
        spec = get_builtin_spec(version.implementation_code)
        if spec is None:
            raise StrategyCenterError("unsupported_strategy_implementation", f"未实现的策略 evaluator: {version.implementation_code}")
        if end_date < start_date:
            raise StrategyCenterError("backtest_date_range_invalid", "回测结束日期不能早于开始日期。")
        signal_dates = await self.repository.open_trade_dates_between(start_date=start_date, end_date=end_date)
        if not signal_dates:
            raise StrategyCenterError("backtest_trade_dates_empty", "指定区间没有开市日。")
        run = await self.repository.create_backtest_run(
            run_code=f"bt_{strategy_code}_{version_no}_{uuid4().hex[:16]}",
            strategy_id=definition.id,
            strategy_version_id=version.id,
            start_date=start_date,
            end_date=end_date,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            parameter_snapshot={
                "implementation_code": version.implementation_code,
                "implementation_version": BUILTIN_STRATEGY_IMPLEMENTATION_VERSION,
                "rule_config": version.rule_config or {},
                "risk_config": version.risk_config or {},
                "execution_assumptions": {
                    "model": "next_open_daily",
                    "entry": "T 日收盘产生信号，T+1 开盘按 open ± 滑点模拟；不宣称盘口成交。",
                    "exit": "收盘触发退出条件后下一开市日开盘卖出；最早 T+2，遵守 A 股 T+1。",
                    "portfolio": "独立信号基线，不做资金占用、组合容量或同标的并发仓位约束。",
                },
            },
        )
        await self.repository.commit()
        try:
            result = await self._execute_backtest(
                run=run,
                definition=definition,
                version=version,
                signal_dates=signal_dates,
                fee_rate=fee_rate,
                slippage_bps=slippage_bps,
                progress_reporter=progress_reporter,
            )
            await self.repository.complete_backtest_run(run, result["summary"])
            if _qualifies_for_paper_review(result["summary"]):
                validation = dict(version.validation_summary or {})
                validation["latest_completed_backtest"] = {
                    "run_code": run.run_code,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    **result["summary"],
                }
                validation["qualified_for_paper_review"] = True
                await self.repository.update_version(version, {"status": "backtest_ready", "validation_summary": validation})
            await self.repository.commit()
            return {"run": self._read_backtest_run(run), **result}
        except Exception as exc:
            await self.repository.fail_backtest_run(run, str(exc))
            await self.repository.commit()
            raise

    async def promote_version_to_paper(self, strategy_code: str, version_no: int) -> dict:
        definition = await self._require_definition(strategy_code)
        version = await self.repository.get_version(strategy_id=definition.id, version_no=version_no)
        if version is None:
            raise StrategyCenterError("strategy_version_not_found", f"策略版本不存在: {strategy_code} v{version_no}")
        if version.status != "backtest_ready" or not bool((version.validation_summary or {}).get("qualified_for_paper_review")):
            raise StrategyCenterError(
                "strategy_backtest_required",
                "只有覆盖至少 120 个有效信号交易日且完成至少 30 笔独立信号基线交易的 backtest_ready 版本可以进入 paper；这不是自动上线。",
            )
        for other in await self.repository.list_versions(strategy_id=definition.id):
            if other.id != version.id and other.status == "paper":
                await self.repository.update_version(other, {"status": "retired"})
        now = datetime.now(timezone.utc)
        await self.repository.update_version(version, {"status": "paper", "published_at": now})
        await self.repository.update_definition(definition, {"status": "paper"})
        if definition.pool_id is not None:
            # Paper candidates enter the shared realtime target selection only
            # after explicit promotion; research pools remain fully offline.
            from sqlalchemy import update
            from app.modules.stock_pool.models import StockPoolRealtimePolicy

            await self.repository.session.execute(
                update(StockPoolRealtimePolicy)
                .where(StockPoolRealtimePolicy.pool_id == definition.pool_id)
                .values(is_enabled=True, priority=30, quote_lane="hot", minute_lane="guaranteed", updated_at=now)
            )
        await self.repository.commit()
        # The runtime merges strategy pools from its reference snapshot.  A
        # promotion is immediately relevant during a live session, so do not
        # wait for its normal reference refresh interval.
        from app.modules.realtime_market.service import realtime_market_service

        realtime_market_service.invalidate_reference()
        return self._read_version(version)

    def _evaluate_context_map(
        self,
        *,
        definition: StrategyDefinition,
        version: StrategyVersion,
        target_date: date,
        feature_dates: list[date],
        contexts: dict[date, dict[str, dict]],
        history_by_stock: dict[str, list[tuple[date, dict]]] | None = None,
        eligible_stock_codes: set[str] | None = None,
    ) -> list[dict]:
        target_contexts = contexts.get(target_date, {})
        results: list[dict] = []
        resolved_rule, resolved_risk = resolve_strategy_configs(
            version.implementation_code,
            rule_config=version.rule_config or {},
            risk_config=version.risk_config or {},
        )
        universe = resolved_rule.get("universe") or {}
        for stock_code, item in target_contexts.items():
            if eligible_stock_codes is not None and stock_code not in eligible_stock_codes:
                continue
            if not _passes_fast_universe_bounds(item, universe):
                continue
            if history_by_stock is None:
                history = []
                for item_date in feature_dates:
                    historical = contexts.get(item_date, {}).get(stock_code)
                    if historical is None:
                        continue
                    history.append(historical.get("current") or {})
            else:
                # A suspended/missing bar must not shift a later row into the
                # target's history.  Filter by its actual date to preserve the
                # no-future-data backtest boundary.
                history = [
                    values
                    for history_date, values in history_by_stock.get(stock_code, [])
                    if history_date <= target_date
                ]
            if not history:
                continue
            event_type = "limit_break" if version.implementation_code == "broken_board_recovery" else "limit_up"
            context = {
                **item,
                "trade_date": target_date,
                "previous": history[-2] if len(history) >= 2 else {},
                "history": history,
                "limit_event": (item.get("events") or {}).get(event_type, {}),
            }
            evaluation = evaluate_daily_candidate(
                version.implementation_code,
                context,
                resolved_rule_config=resolved_rule,
                resolved_risk_config=resolved_risk,
            )
            if evaluation.matched:
                results.append(
                    {
                        "stock_code": stock_code,
                        "score": evaluation.score,
                        "candidate_snapshot": evaluation.candidate_snapshot,
                        "entry_plan": evaluation.entry_plan,
                    }
                )
        return sorted(results, key=lambda item: (-float(item["score"] or 0), item["stock_code"]))

    async def _execute_backtest(
        self,
        *,
        run: StrategyBacktestRun,
        definition: StrategyDefinition,
        version: StrategyVersion,
        signal_dates: list[date],
        fee_rate: float,
        slippage_bps: float,
        progress_reporter=None,
    ) -> dict:
        all_dates = await self.repository.open_trade_dates_ending_at(end_date=signal_dates[-1], limit=len(signal_dates) + 70)
        # Give each signal enough future sessions for a T+1 entry and the
        # declared time exit.  This read stays calendar-bounded and chunks the
        # heavy daily rows in 20 signal dates rather than materialising years.
        future_dates = await self.repository.open_trade_dates_between(
            start_date=signal_dates[-1],
            end_date=date.fromordinal(signal_dates[-1].toordinal() + 45),
        )
        full_calendar = _ordered_unique(all_dates + future_dates)
        date_index = {item: index for index, item in enumerate(full_calendar)}
        trade_rows: list[dict] = []
        signal_count = 0
        max_holding = max(1, int((version.risk_config or {}).get("max_holding_trade_days") or definition.max_holding_trade_days))
        resolved_rule, _ = resolve_strategy_configs(
            version.implementation_code,
            rule_config=version.rule_config or {},
            risk_config=version.risk_config or {},
        )
        universe = resolved_rule.get("universe") or {}
        for chunk_index, batch_signal_dates in enumerate(_chunks(signal_dates, BACKTEST_SIGNAL_DAYS_PER_BATCH), start=1):
            first = date_index[batch_signal_dates[0]]
            last = date_index[batch_signal_dates[-1]]
            feature_start = max(0, first - PRIOR_DAILY_RULE_LOOKBACK)
            feature_end = min(len(full_calendar), last + max_holding + 3)
            feature_dates = full_calendar[feature_start:feature_end]
            if progress_reporter:
                await progress_reporter(
                    {
                        "stage": "loading_inputs",
                        "strategy_code": definition.strategy_code,
                        "version_no": version.version_no,
                        "batch_index": chunk_index,
                        "batch_count": (len(signal_dates) + BACKTEST_SIGNAL_DAYS_PER_BATCH - 1)
                        // BACKTEST_SIGNAL_DAYS_PER_BATCH,
                        "signal_date_start": batch_signal_dates[0],
                        "signal_date_end": batch_signal_dates[-1],
                        "feature_trade_date_count": len(feature_dates),
                    }
                )
            contexts, eligible_by_date = await self.repository.load_backtest_evaluation_contexts(
                feature_trade_dates=feature_dates,
                decision_trade_dates=batch_signal_dates,
                implementation_code=version.implementation_code,
                universe=universe,
            )
            history_by_stock = _history_by_stock(feature_dates, contexts)
            for signal_date in batch_signal_dates:
                matched = self._evaluate_context_map(
                    definition=definition,
                    version=version,
                    target_date=signal_date,
                    feature_dates=[item for item in feature_dates if item <= signal_date],
                    contexts=contexts,
                    history_by_stock=history_by_stock,
                    eligible_stock_codes=eligible_by_date.get(signal_date, set()),
                )
                selected = matched[:_candidate_limit(version.rule_config)]
                signal_count += len(selected)
                for candidate in selected:
                    trade = self._simulate_next_open_daily_trade(
                        candidate=candidate,
                        signal_date=signal_date,
                        full_calendar=full_calendar,
                        date_index=date_index,
                        contexts=contexts,
                        max_holding=max_holding,
                        fee_rate=fee_rate,
                        slippage_bps=slippage_bps,
                    )
                    if trade is not None:
                        trade_rows.append(
                            {
                                "backtest_run_id": run.id,
                                "strategy_id": definition.id,
                                "strategy_version_id": version.id,
                                **trade,
                            }
                        )
            if trade_rows:
                # Existing rows are unique by this new run and signal; batched
                # inserts keep the transaction and memory bounded.
                await self.repository.insert_backtest_trades(trade_rows)
                await self.repository.commit()
                trade_rows.clear()
            if progress_reporter:
                await progress_reporter(
                    {
                        "stage": "backtest_daily_baseline",
                        "strategy_code": definition.strategy_code,
                        "version_no": version.version_no,
                        "completed_signal_date_count": min(
                            chunk_index * BACKTEST_SIGNAL_DAYS_PER_BATCH,
                            len(signal_dates),
                        ),
                        "total_signal_date_count": len(signal_dates),
                    }
                )
        persisted_rows = await self.repository.session.execute(
            # Pull only the completed rows for this new run to summarize.  It
            # is intentionally not a cross-run aggregation.
            select(StrategyBacktestTrade).where(StrategyBacktestTrade.backtest_run_id == run.id)
        )
        trades = list(persisted_rows.scalars().all())
        returns = [float(item.net_return_pct) for item in trades]
        wins = [item for item in returns if item > 0]
        summary = {
            "execution_model": "next_open_daily",
            "signal_trade_date_count": len(signal_dates),
            "signal_count": signal_count,
            "completed_trade_count": len(trades),
            "not_materialized_count": max(signal_count - len(trades), 0),
            "win_count": len(wins),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if trades else None,
            "average_net_return_pct": round(mean(returns), 6) if returns else None,
            "median_net_return_pct": round(median(returns), 6) if returns else None,
            "best_net_return_pct": round(max(returns), 6) if returns else None,
            "worst_net_return_pct": round(min(returns), 6) if returns else None,
            "fee_rate": fee_rate,
            "slippage_bps": slippage_bps,
            "paper_review_requirements": {
                "minimum_signal_trade_date_count": MINIMUM_PAPER_REVIEW_SIGNAL_DATES,
                "minimum_completed_trade_count": MINIMUM_PAPER_REVIEW_COMPLETED_TRADES,
            },
            "qualified_for_paper_review": False,
            "limitations": [
                "独立信号基线，不代表组合净值、资金容量或真实成交。",
                "T+1 开盘价假设可成交；不使用未来盘口、逐笔或分钟数据。",
                "卖出信号由收盘事实在下一开市日开盘执行，最早为 T+2。",
                "缺少下一开市日开盘价或完整退出窗口的信号不计入已结束交易。",
            ],
        }
        summary["qualified_for_paper_review"] = _qualifies_for_paper_review(summary)
        return {"summary": summary}

    @staticmethod
    def _simulate_next_open_daily_trade(
        *,
        candidate: dict,
        signal_date: date,
        full_calendar: list[date],
        date_index: dict[date, int],
        contexts: dict[date, dict[str, dict]],
        max_holding: int,
        fee_rate: float,
        slippage_bps: float,
    ) -> dict | None:
        signal_index = date_index.get(signal_date)
        if signal_index is None or signal_index + 2 >= len(full_calendar):
            return None
        stock_code = str(candidate["stock_code"])
        entry_date = full_calendar[signal_index + 1]
        entry_context = contexts.get(entry_date, {}).get(stock_code) or {}
        entry_open = _number((entry_context.get("current") or {}).get("open_price"))
        if entry_open is None or entry_open <= 0:
            return None
        slip = slippage_bps / 10_000
        entry_price = entry_open * (1 + slip)
        risk = ((candidate.get("entry_plan") or {}).get("risk_plan") or {})
        stop_loss = float(risk.get("hard_stop_loss_pct") or -4.0)
        take_profit = _first_take_profit_pct(risk)
        trailing = risk.get("trailing_stop") or {}
        activate_return = float(trailing.get("activate_return_pct") or 6.0)
        trailing_drawdown = float(trailing.get("drawdown_pct") or 3.0)
        highest_close = entry_price
        exit_reason = None
        exit_date = None
        # Examine only EOD facts after entry; a trigger at close D is executed
        # at D+1 open.  This guarantees no same-day A-share sell in a baseline.
        for day_index in range(signal_index + 1, min(len(full_calendar) - 1, signal_index + max_holding + 1)):
            close_date = full_calendar[day_index]
            current = (contexts.get(close_date, {}).get(stock_code) or {}).get("current") or {}
            close = _number(current.get("close_price"))
            if close is None or close <= 0:
                continue
            highest_close = max(highest_close, close)
            close_return = (close / entry_price - 1) * 100
            if close_return <= stop_loss:
                exit_reason = "hard_stop_close_confirmed"
            elif take_profit is not None and close_return >= take_profit:
                exit_reason = "take_profit_close_confirmed"
            elif (highest_close / entry_price - 1) * 100 >= activate_return and (highest_close - close) / highest_close * 100 >= trailing_drawdown:
                exit_reason = "trailing_stop_close_confirmed"
            elif day_index - (signal_index + 1) + 1 >= max_holding:
                exit_reason = "time_exit_close_confirmed"
            if exit_reason:
                exit_date = full_calendar[day_index + 1]
                break
        if exit_date is None:
            return None
        exit_context = contexts.get(exit_date, {}).get(stock_code) or {}
        exit_open = _number((exit_context.get("current") or {}).get("open_price"))
        if exit_open is None or exit_open <= 0:
            return None
        exit_price = exit_open * (1 - slip)
        gross_return = (exit_price / entry_price - 1) * 100
        net_return = gross_return - fee_rate * 2 * 100
        return {
            "stock_code": stock_code,
            "signal_trade_date": signal_date,
            "entry_trade_date": entry_date,
            "exit_trade_date": exit_date,
            "entry_price": round(entry_price, 6),
            "exit_price": round(exit_price, 6),
            "gross_return_pct": round(gross_return, 6),
            "net_return_pct": round(net_return, 6),
            "holding_trade_days": max(1, date_index[exit_date] - date_index[entry_date]),
            "exit_reason": exit_reason,
            "candidate_snapshot": candidate.get("candidate_snapshot") or {},
            "execution_snapshot": {
                "entry_open_price": entry_open,
                "exit_open_price": exit_open,
                "slippage_bps": slippage_bps,
                "fee_rate": fee_rate,
                "entry_assumption": "T+1 open executable baseline",
                "exit_assumption": "close-confirmed condition at next open",
            },
        }

    async def _require_definition(self, strategy_code: str) -> StrategyDefinition:
        definition = await self.repository.get_definition(strategy_code)
        if definition is None:
            raise StrategyCenterError("strategy_not_found", f"策略不存在: {strategy_code}")
        return definition

    @staticmethod
    def _read_version(version: StrategyVersion) -> dict:
        return {
            "version_no": version.version_no,
            "implementation_code": version.implementation_code,
            "status": version.status,
            "rule_config": version.rule_config or {},
            "risk_config": version.risk_config or {},
            "validation_summary": version.validation_summary or {},
            "published_at": version.published_at,
            "created_at": version.created_at,
            "updated_at": version.updated_at,
        }

    @staticmethod
    def _read_backtest_run(run: StrategyBacktestRun) -> dict:
        return {
            "run_code": run.run_code,
            "strategy_version_id": run.strategy_version_id,
            "start_date": run.start_date,
            "end_date": run.end_date,
            "execution_model": run.execution_model,
            "status": run.status,
            "fee_rate": run.fee_rate,
            "slippage_bps": run.slippage_bps,
            "parameter_snapshot": run.parameter_snapshot or {},
            "summary": run.summary or {},
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_message": run.error_message,
        }

    @staticmethod
    def _read_definition(row: dict) -> dict:
        definition: StrategyDefinition = row["definition"]
        return {
            "strategy_code": definition.strategy_code,
            "strategy_name": definition.strategy_name,
            "description": definition.description,
            "status": definition.status,
            "strategy_type": definition.strategy_type,
            "entry_mode": definition.entry_mode,
            "max_holding_trade_days": definition.max_holding_trade_days,
            "rule_config": definition.rule_config or {},
            "risk_config": definition.risk_config or {},
            "pool_code": row.get("pool_code"),
            "pool_name": row.get("pool_name"),
            "candidate_summary": row.get("candidate_summary") or {},
            "trade_summary": row.get("trade_summary") or {},
            "created_at": definition.created_at,
            "updated_at": definition.updated_at,
        }

    @staticmethod
    def _read_candidate(row: dict) -> dict:
        candidate = row["candidate"]
        paper_trade: StrategyPaperTrade | None = row.get("paper_trade")
        return {
            "id": candidate.id,
            "strategy_code": row["strategy_code"],
            "strategy_name": row["strategy_name"],
            "signal_trade_date": candidate.signal_trade_date,
            "stock_code": candidate.stock_code,
            "stock_name": row.get("stock_name"),
            "candidate_status": candidate.candidate_status,
            "score": candidate.score,
            "rank_no": candidate.rank_no,
            "confirmation_deadline": candidate.confirmation_deadline,
            "candidate_snapshot": candidate.candidate_snapshot or {},
            "entry_plan": candidate.entry_plan or {},
            "outcome_note": candidate.outcome_note,
            "confirmed_at": candidate.confirmed_at,
            "paper_trade": StrategyCenterService._read_paper_trade(paper_trade),
        }

    @staticmethod
    def _read_paper_trade(paper_trade: StrategyPaperTrade | None) -> dict | None:
        if paper_trade is None:
            return None
        return {
            "trade_status": paper_trade.trade_status,
            "entry_at": paper_trade.entry_at,
            "entry_price": paper_trade.entry_price,
            "quantity": paper_trade.quantity,
            "initial_quantity": paper_trade.initial_quantity,
            "open_quantity": paper_trade.open_quantity,
            "entry_amount": paper_trade.entry_amount,
            "exit_at": paper_trade.exit_at,
            "exit_price": paper_trade.exit_price,
            "exit_amount": paper_trade.exit_amount,
            "realized_pnl_amount": paper_trade.realized_pnl_amount,
            "realized_pnl_pct": paper_trade.realized_pnl_pct,
            "risk_plan": paper_trade.risk_plan or {},
        }


def _candidate_limit(rule_config: dict | None) -> int:
    selection = (rule_config or {}).get("selection") or {}
    try:
        return min(max(int(selection.get("max_candidates") or 30), 1), 200)
    except (TypeError, ValueError):
        return 30


def _passes_fast_universe_bounds(context: dict, universe: dict) -> bool:
    """Reject only facts the canonical evaluator will always reject.

    This happens before copying a stock's lookback list.  It deliberately does
    not implement strategy rules or market gates; ``evaluate_daily_candidate``
    remains the sole matching authority.
    """

    current = context.get("current") or {}
    amount = _number(current.get("amount_yuan"))
    try:
        minimum_amount = float(universe.get("minimum_amount_yuan") or 0)
    except (TypeError, ValueError):
        minimum_amount = 0.0
    if amount is None or amount < minimum_amount:
        return False
    try:
        history_days = int(current.get("history_days"))
    except (TypeError, ValueError):
        return True
    try:
        minimum_listing_days = int(universe.get("minimum_listing_trade_days") or 0)
    except (TypeError, ValueError):
        minimum_listing_days = 0
    return history_days >= minimum_listing_days


def _history_by_stock(
    feature_dates: list[date], contexts: dict[date, dict[str, dict]]
) -> dict[str, list[tuple[date, dict]]]:
    """Build ascending histories once per loaded batch instead of per signal."""

    histories: dict[str, list[tuple[date, dict]]] = {}
    for item_date in feature_dates:
        for stock_code, context in contexts.get(item_date, {}).items():
            histories.setdefault(stock_code, []).append((item_date, context.get("current") or {}))
    return histories


def _chunks(values: list[date], size: int):
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _ordered_unique(values: list[date]) -> list[date]:
    return sorted(set(values))


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_take_profit_pct(risk_config: dict) -> float | None:
    legs = list(risk_config.get("take_profit_legs") or [])
    values = []
    for leg in legs:
        try:
            values.append(float(leg.get("trigger_return_pct")))
        except (TypeError, ValueError, AttributeError):
            continue
    return min(values) if values else None
