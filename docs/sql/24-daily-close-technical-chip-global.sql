-- Extend daily_market_close_ingest with professional technical factors,
-- chip performance facts, market-wide stats, and index daily basic facts.
-- Safe to re-run. Existing rows are preserved.

BEGIN;

ALTER TABLE t_stock_daily_basic
    ADD COLUMN IF NOT EXISTS close_price NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS turnover_rate_f NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS pe_ttm NUMERIC(24,6),
    ADD COLUMN IF NOT EXISTS ps NUMERIC(24,6),
    ADD COLUMN IF NOT EXISTS ps_ttm NUMERIC(24,6),
    ADD COLUMN IF NOT EXISTS dv_ratio NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS dv_ttm NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS free_share NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS limit_status INTEGER;

CREATE TABLE IF NOT EXISTS t_stock_technical_factor_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    factors JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_technical_factor_daily_business UNIQUE (stock_code, trade_date)
);

CREATE TABLE IF NOT EXISTS t_stock_chip_perf_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    his_low NUMERIC(18,4),
    his_high NUMERIC(18,4),
    cost_5pct NUMERIC(18,4),
    cost_15pct NUMERIC(18,4),
    cost_50pct NUMERIC(18,4),
    cost_85pct NUMERIC(18,4),
    cost_95pct NUMERIC(18,4),
    weight_avg NUMERIC(18,4),
    winner_rate NUMERIC(18,6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_chip_perf_daily_business UNIQUE (stock_code, trade_date)
);

CREATE TABLE IF NOT EXISTS t_market_daily_stat (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    ts_code VARCHAR(40) NOT NULL,
    ts_name VARCHAR(120),
    exchange VARCHAR(20) NOT NULL,
    source VARCHAR(80) NOT NULL,
    company_count INTEGER,
    total_share NUMERIC(24,6),
    float_share NUMERIC(24,6),
    total_mv NUMERIC(24,6),
    float_mv NUMERIC(24,6),
    amount NUMERIC(24,6),
    volume NUMERIC(24,6),
    transaction_count NUMERIC(24,6),
    pe NUMERIC(24,6),
    turnover_rate NUMERIC(18,6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_daily_stat_business UNIQUE (trade_date, ts_code, exchange)
);

CREATE TABLE IF NOT EXISTS t_index_daily_basic (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    total_mv NUMERIC(24,6),
    float_mv NUMERIC(24,6),
    total_share NUMERIC(24,6),
    float_share NUMERIC(24,6),
    free_share NUMERIC(24,6),
    turnover_rate NUMERIC(18,6),
    turnover_rate_f NUMERIC(18,6),
    pe NUMERIC(24,6),
    pe_ttm NUMERIC(24,6),
    pb NUMERIC(24,6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_index_daily_basic_business UNIQUE (index_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_t_stock_technical_factor_daily_stock_date ON t_stock_technical_factor_daily(stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_stock_chip_perf_daily_stock_date ON t_stock_chip_perf_daily(stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_market_daily_stat_date ON t_market_daily_stat(trade_date DESC, exchange);
CREATE INDEX IF NOT EXISTS idx_t_index_daily_basic_index_date ON t_index_daily_basic(index_code, trade_date DESC);

COMMENT ON TABLE t_stock_technical_factor_daily IS 'Canonical/Derived hybrid: Tushare stk_factor_pro professional daily technical factors, stored as raw factor JSON.';
COMMENT ON TABLE t_stock_chip_perf_daily IS 'Canonical fact: Tushare cyq_perf daily chip cost and winner-rate facts.';
COMMENT ON TABLE t_market_daily_stat IS 'Canonical fact: Tushare daily_info exchange and board market-wide daily statistics.';
COMMENT ON TABLE t_index_daily_basic IS 'Canonical fact: Tushare index_dailybasic broad index valuation and turnover indicators.';

DO $$
DECLARE
    target_table TEXT;
    column_row RECORD;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        't_stock_daily_basic',
        't_stock_technical_factor_daily',
        't_stock_chip_perf_daily',
        't_market_daily_stat',
        't_index_daily_basic'
    ] LOOP
        FOR column_row IN
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = target_table
        LOOP
            EXECUTE format(
                'COMMENT ON COLUMN public.%I.%I IS %L',
                target_table,
                column_row.column_name,
                target_table || ' field: ' || column_row.column_name || '.'
            );
        END LOOP;
    END LOOP;
END $$;

INSERT INTO t_factor_definition (
    factor_code,
    factor_name,
    factor_group,
    frequency,
    source_table,
    compute_method,
    is_rebuildable,
    metadata
)
VALUES
    ('tushare_technical_factor_pro', 'Tushare 专业技术因子', 'technical', 'daily', 't_stock_technical_factor_daily', '从 Tushare stk_factor_pro 原始字段落地，常用指标同步到 t_stock_factor_daily.features.tushare_technical。', TRUE, '{"source":"daily_market_close_ingest","api_name":"stk_factor_pro"}'::jsonb),
    ('chip_winner_rate', '筹码胜率', 'chip', 'daily', 't_stock_chip_perf_daily', 'Tushare cyq_perf.winner_rate。', TRUE, '{"source":"daily_market_close_ingest","api_name":"cyq_perf"}'::jsonb),
    ('chip_cost_90_width', '筹码 90% 成本宽度', 'chip', 'daily', 't_stock_chip_perf_daily', '(cost_95pct - cost_5pct) / weight_avg * 100。', TRUE, '{"source":"daily_market_close_ingest","api_name":"cyq_perf"}'::jsonb),
    ('chip_cost_70_width', '筹码 70% 成本宽度', 'chip', 'daily', 't_stock_chip_perf_daily', '(cost_85pct - cost_15pct) / weight_avg * 100。', TRUE, '{"source":"daily_market_close_ingest","api_name":"cyq_perf"}'::jsonb),
    ('chip_close_vs_avg_cost_pct', '收盘价相对筹码均价偏离', 'chip', 'daily', 't_stock_chip_perf_daily,t_daily_bar', '(close - weight_avg) / weight_avg * 100。', TRUE, '{"source":"daily_market_close_ingest","api_name":"cyq_perf"}'::jsonb),
    ('market_daily_stat', '市场每日交易统计', 'market', 'daily', 't_market_daily_stat', 'Tushare daily_info 交易所及板块市场统计。', TRUE, '{"source":"daily_market_close_ingest","api_name":"daily_info"}'::jsonb),
    ('index_daily_basic', '大盘指数每日指标', 'index', 'daily', 't_index_daily_basic', 'Tushare index_dailybasic 指数市值、换手率、估值指标。', TRUE, '{"source":"daily_market_close_ingest","api_name":"index_dailybasic"}'::jsonb)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    metadata = t_factor_definition.metadata || EXCLUDED.metadata,
    updated_at = now();

UPDATE t_scheduler_job
SET
    cron_expr = '30 19 * * 1-5',
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || '{
            "sync_stock_technical_factor_pro":{"label":"同步专业技术因子","type":"boolean","default":true,"required":false,"description":"通过 Tushare stk_factor_pro 沉淀专业技术因子 JSON。"},
            "sync_chip_perf":{"label":"同步筹码胜率","type":"boolean","default":true,"required":false,"description":"通过 Tushare cyq_perf 沉淀筹码成本和胜率。"},
            "chip_universe":{"label":"筹码同步范围","type":"string","default":"all_a_share","required":false,"description":"all_a_share 或股票池 pool_code。"},
            "chip_limit_stocks":{"label":"筹码股票上限","type":"number","default":null,"required":false,"description":"调试或小范围运行时限制筹码接口股票数量。"},
            "sync_market_stats":{"label":"同步市场统计","type":"boolean","default":true,"required":false,"description":"通过 Tushare daily_info 沉淀 SH/SZ 市场统计。"},
            "sync_index_daily_basic":{"label":"同步指数每日指标","type":"boolean","default":true,"required":false,"description":"通过 Tushare index_dailybasic 沉淀核心指数估值和换手。"},
            "sync_north_hold":{"label":"同步北向持股","type":"boolean","default":false,"required":false,"description":"已不建议作为每日任务启用；日度北向 A 股持股披露口径不稳定。"}
        }'::jsonb,
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{
            "sync_stock_technical_factor_pro":true,
            "sync_chip_perf":true,
            "chip_universe":"all_a_share",
            "chip_limit_stocks":null,
            "sync_market_stats":true,
            "sync_index_daily_basic":true,
            "sync_north_hold":false
        }'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_market_close_ingest';

COMMIT;
