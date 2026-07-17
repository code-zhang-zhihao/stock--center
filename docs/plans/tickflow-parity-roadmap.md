# TickFlow Parity Roadmap

## Summary

This roadmap aligns `stock-center` with the product capability of `tickflow-stock-panel` without copying its data source or storage stack. `stock-center` keeps PostgreSQL raw/canonical/derived layers and uses Tushare, MooTDX, AkShare, Skill, LLM Runtime, and local services.

The first implementation priority is quant field standardization, then the data foundation, followed by a unified real-time market layer. UI pages should be built only when their data dependencies, freshness labels, and empty states are clear.

## Current State

Implemented or partially implemented:

- Market data query APIs and page-level stock/sector analysis APIs.
- Scheduler center, config center, LLM runtime, Skill runtime.
- Stock master data, trade calendar, daily bars, minute bars, EOD quote, daily basic, fund flow, limit events, LHB, technical factors, chip performance, sector catalog, sector components, sector bars, sector fund flow, sector factors.
- Frontend pages: settings, scheduler, sector center, sector dashboard, sector detail, stock pool, stock market workbench.

Major missing capabilities:

- Market overview dashboard.
- Watchlist-grade stock pool table with real-time metrics and column configuration.
- Strategy screener and custom signals.
- Backtest engine.
- Monitor center and alert records.
- Financial analysis page and financial sync pipeline.
- Limit-up ladder and market emotion page.
- Data center for data assets and job health.
- Unified real-time quote/cache/push service.
- External data ingestion.
- AI review, AI strategy generation, stock/financial AI reports.

## Implementation Phases

### Phase 0: Quant Field Standardization And Init SQL

- Define standard internal params: `stock_code`, `sector_code`, `index_code`, `trade_date`, `start_date`, `end_date`, `interval`, `adjust_mode`, `query_mode`, and `engine_priority`.
- Define standard units: prices in yuan, amounts in yuan, volumes in shares, percentage fields as percentage points, ratio fields as `0-1` ratios.
- Add or extend metric/factor definitions with `factor_code`, source tables, unit, calculation method, frequency, recomputability, and data stage.
- Introduce Provider Adapter boundaries: transport/client returns raw data; adapters map raw fields to canonical DTOs; services handle fallback, raw/audit, canonical upsert, and scheduler orchestration.
- Standardize logs for provider, api name, request range, raw rows, mapped rows, upserted rows, missing count, unit conversions, and warning samples.
- Plan product deployment SQL entrypoints: `docs/sql/init.sql` and `docs/sql/db-init.sql`; keep old incremental scripts as migrations/archive.
- Remove full-market batch `cyq_perf` from daily enrichment. Keep it only as an optional on-demand stock-detail capability.

Acceptance:

- Business services no longer consume Tushare `ts_code`, AkShare Chinese columns, or MooTDX raw fields directly.
- Different providers produce the same canonical DTO for the same capability.
- Missing data can be diagnosed from structured logs.
- New deployments can initialize the product schema from one or two SQL entrypoints.
- Daily enrichment is not blocked by slow full-market `cyq_perf`.

### Phase 1: Data Assets And Data Center

- Add data asset inspection APIs and a Data Center page.
- Show row count, latest trade date, missing ranges, table freshness, scheduler status, and provider/runtime errors.
- Complete index basics and index components; `t_index_basic` and `t_index_component` should not remain empty.
- Split Tushare catalog status into `documented`, `callable`, `persisted`, and `used_by_page`.
- Add one-shot deployment backfill jobs for historical daily bars, daily basic, fund flow, indices, and sector history. Daily close jobs should remain incremental.

Acceptance:

- Every core data category has a visible health card.
- Daily close jobs expose completeness by block.
- Index metadata is usable by pages and backtests.

### Phase 2: Real-Time Market Layer

- Add `RealtimeMarketService` for quote cache, minute cache, sector real-time cache, provider fallback, and runtime logs.
- Use MooTDX as the primary source for real-time quote, intraday minute, order book, and ticks.
- Use MooTDX `quote_batch` for full-market quote polling. Current baseline: 5,210 active SH/SZ stocks, `batch_size=80`, 66 batches, about 8.9 seconds per full round in non-trading testing. Batch sizes above 80 are silently truncated by MooTDX and must be rejected or clamped.
- Default full-market interval is 60 seconds. Aggressive mode can be 30 seconds. Watchlist/current-page scopes can refresh every 15-30 seconds. Do not run full-market 15-second polling in v1.
- Use AkShare/Eastmoney-like endpoints for quasi real-time sector ranking and fallback.
- Keep Tushare as the daily/post-close canonical source.
- Keep Skill for semantic/news/event enrichment, not real-time price, order book, tick, or canonical market facts.
- Cache layers: normalized latest quote cache, quote round metadata, sector member maps, stock-sector reverse maps, sector strength cache, market breadth cache, and bounded minute/order-book caches for focused scopes.
- Sector real-time strength should be aggregated from the full-market quote cache plus `t_sector_component/t_sector_basic`; external sector endpoints are supplemental, especially for quasi real-time fund-flow ranking.
- Memory budget for v1 is 50-150MB. Do not cache full-market raw payloads, full-market ticks, full-market order books, or every quote round.
- Add SSE or WebSocket push for dashboard, watchlist, stock workbench, and monitor center.
- Label UI data as real-time, quasi real-time, post-close, or historical.

Acceptance:

- Watchlist and stock workbench read one real-time service instead of calling providers row by row.
- One full-market quote round completes within the default 60-second interval without silent truncation. Failed, missing, and stale quote counts are exposed.
- Sector strength is computed from quote cache and sector membership mapping, including breadth, amount, leaders, laggards, limit-up/down counts, and coverage ratio.
- Monitor rules can trigger from real-time cache.
- The service does not write high-frequency ticks to canonical tables by default.

### Phase 3: Market Overview Dashboard

- Build market breadth from canonical daily bars and limit events.
- Show indices, total amount, up/down counts, limit-up/down, broken boards, max board height, sector fund flow, sector strength, and event stream.
- Read local canonical/derived tables for post-close facts and the real-time service for optional intraday quote/sector overlays.

Acceptance:

- Latest trading day dashboard can load without external calls.
- Empty states point to the missing scheduler/data block.

### Phase 4: Watchlist And Stock Pool Workspace

- Upgrade stock pools into a watchlist workspace.
- Support table/card views, column configuration, sorting, filtering, quote refresh, factor columns, fund-flow columns, and sector tags.
- Keep pool membership as `stock_code` only.

Acceptance:

- System pools and custom pools can be used as analysis scopes.
- Rows can jump to stock workbench, monitoring setup, and screener/backtest flows.

### Phase 5: Indicator Pipeline And Screener

- Expand `indicator_engine` with MA, EMA, MACD, RSI, KDJ, BOLL, ATR, volume ratio, high/low breakout, limit-up signals, and reusable signal columns.
- Create an indicator dictionary for field name, source table, frequency, and recomputability.
- Add built-in strategy definitions and configurable condition strategies.
- Add screener result persistence and a Screener page.

Initial built-ins:

- Trend breakout.
- Bullish MA alignment.
- MACD golden cross with volume.
- BOLL breakout.
- Volume-price surge.
- High-turnover strength.
- Consecutive limit-ups.
- Broken-board retake.
- Oversold bounce.

Acceptance:

- Strategies can run on all A-share or a stock pool.
- Results can be added to a pool, exported, or used by monitors.

### Phase 6: Backtest Engine

- Start with strategy backtest.
- Inputs: strategy, universe, date range, max holdings, fee, slippage, stop loss, max holding days.
- Outputs: equity curve, drawdown, Sharpe, win rate, trades.
- Add factor IC/IR, grouped returns, and long-short portfolios later.

Acceptance:

- Screener strategies can be backtested reproducibly.
- Results are persisted or archived with parameters.

### Phase 7: Monitor Center And Notification

- Add monitor rules and trigger records.
- Support strategy-result changes, stock factor conditions, price movement, and market anomaly rules.
- Intraday rules read the real-time service cache; post-close rules read canonical/derived tables.
- Reuse Notification config for Feishu, email, and webhook delivery.

Acceptance:

- Rules can be enabled, disabled, cooled down, and inspected.
- Trigger records explain the matched condition.

### Phase 8: Analysis Pages

- Limit-up ladder from limit events and EOD/quote data.
- Financial analysis from income, balancesheet, cashflow, and fina_indicator.
- Stock analysis enhancements: support/resistance, key levels, volume profile approximation, AI entry point.
- Sector analysis enhancements: RPS rotation, persistent leaders, rising themes, fading themes, constituents drilldown.

Acceptance:

- Analysis pages read canonical/derived data only.
- Missing data states identify the required sync job.

### Phase 9: AI And External Data

- AI market review from dashboard, sector rotation, limit events, LHB, and fund flow.
- AI strategy generation from a strict strategy guide and safe validation.
- Stock/financial AI reports from fixed context packs.
- External data ingestion via CSV/Excel upload, HTTP pull, JSON ingest, schema discovery, stock-code normalization, and optional table columns.

Acceptance:

- AI reports are archived and downloadable.
- Generated strategies cannot modify core code.
- External fields can appear in watchlist/screener columns.

## Data Source Rules

- Tushare is the main daily canonical source.
- MooTDX is the main real-time quote, minute, tick, and盘口 source.
- AkShare is fallback and a real-time ranking supplement.
- Skill is for semantic/search/news-like enrichment, not real-time quote, tick, order book, or canonical market facts.
- Raw can preserve multiple providers. Canonical facts should not duplicate by provider source.
