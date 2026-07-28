-- Strategy research and paper-trading foundation.  This migration creates
-- configuration, candidate and simulated-trade audit records only; it does
-- not seed or enable any trading rule, schedule a scan, or place an order.
-- Safe to run after 67-market-emotion-v2.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS t_strategy_definition (
    id BIGSERIAL PRIMARY KEY,
    strategy_code VARCHAR(60) NOT NULL,
    strategy_name VARCHAR(160) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    strategy_type VARCHAR(40) NOT NULL DEFAULT 'short_term',
    entry_mode VARCHAR(20) NOT NULL DEFAULT 'auction',
    max_holding_trade_days INTEGER NOT NULL DEFAULT 3,
    rule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    pool_id BIGINT UNIQUE REFERENCES t_stock_pool(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_definition_code UNIQUE (strategy_code),
    CONSTRAINT ck_t_strategy_definition_code CHECK (strategy_code ~ '^[a-z][a-z0-9_]{0,59}$'),
    CONSTRAINT ck_t_strategy_definition_status CHECK (status IN ('draft', 'research', 'enabled', 'archived')),
    CONSTRAINT ck_t_strategy_definition_type CHECK (strategy_type IN ('short_term')),
    CONSTRAINT ck_t_strategy_definition_entry_mode CHECK (entry_mode IN ('auction', 'open', 'intraday')),
    CONSTRAINT ck_t_strategy_definition_max_holding CHECK (max_holding_trade_days BETWEEN 1 AND 20)
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_definition_status
    ON t_strategy_definition (status, updated_at DESC, strategy_code);

CREATE TABLE IF NOT EXISTS t_strategy_candidate (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE CASCADE,
    signal_trade_date DATE NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    candidate_status VARCHAR(32) NOT NULL DEFAULT 'pending_confirmation',
    score DOUBLE PRECISION,
    rank_no INTEGER,
    confirmation_deadline DATE,
    candidate_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    entry_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome_note TEXT,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_candidate_business UNIQUE (strategy_id, signal_trade_date, stock_code),
    CONSTRAINT ck_t_strategy_candidate_status CHECK (candidate_status IN (
        'pending_confirmation', 'watching', 'entry_triggered', 'not_triggered', 'expired', 'cancelled'
    )),
    CONSTRAINT ck_t_strategy_candidate_rank CHECK (rank_no IS NULL OR rank_no >= 1)
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_candidate_list
    ON t_strategy_candidate (strategy_id, signal_trade_date DESC, candidate_status, rank_no, stock_code);
CREATE INDEX IF NOT EXISTS idx_t_strategy_candidate_stock
    ON t_strategy_candidate (stock_code, signal_trade_date DESC);

CREATE TABLE IF NOT EXISTS t_strategy_paper_trade (
    id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL UNIQUE REFERENCES t_strategy_candidate(id) ON DELETE RESTRICT,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE RESTRICT,
    stock_code VARCHAR(20) NOT NULL,
    trade_status VARCHAR(20) NOT NULL DEFAULT 'open',
    entry_at TIMESTAMPTZ NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 100,
    entry_amount DOUBLE PRECISION,
    exit_at TIMESTAMPTZ,
    exit_price DOUBLE PRECISION,
    exit_amount DOUBLE PRECISION,
    realized_pnl_amount DOUBLE PRECISION,
    realized_pnl_pct DOUBLE PRECISION,
    entry_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    exit_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_t_strategy_paper_trade_status CHECK (trade_status IN ('open', 'closed', 'void')),
    CONSTRAINT ck_t_strategy_paper_trade_entry_price CHECK (entry_price > 0),
    CONSTRAINT ck_t_strategy_paper_trade_quantity CHECK (quantity > 0),
    CONSTRAINT ck_t_strategy_paper_trade_exit_consistency CHECK (
        (trade_status = 'open' AND exit_at IS NULL AND exit_price IS NULL)
        OR (trade_status = 'closed' AND exit_at IS NOT NULL AND exit_price IS NOT NULL AND exit_price > 0)
        OR trade_status = 'void'
    )
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_paper_trade_strategy_status
    ON t_strategy_paper_trade (strategy_id, trade_status, entry_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_strategy_paper_trade_stock
    ON t_strategy_paper_trade (stock_code, entry_at DESC);

COMMENT ON TABLE t_strategy_definition IS '策略定义与版本化配置。当前仅用于研究与模拟交易，不连接券商、不代表自动下单。';
COMMENT ON COLUMN t_strategy_definition.entry_mode IS '候选的确认时点：auction 集合竞价、open 开盘、intraday 盘中；实际触发规则由后续 evaluator 实现。';
COMMENT ON COLUMN t_strategy_definition.pool_id IS '策略专属动态股票池。池成员由候选事实派生，不能手工与候选混写。';
COMMENT ON TABLE t_strategy_candidate IS 'T 日收盘策略候选及 T+1 确认状态。not_triggered 表示未形成买点，不产生模拟成交且不得计为交易失败。';
COMMENT ON COLUMN t_strategy_candidate.candidate_snapshot IS '生成候选时冻结的日频事实、情绪、题材与规则证据。';
COMMENT ON COLUMN t_strategy_candidate.entry_plan IS '策略声明的确认窗口、触发条件与初始风险计划；不是券商订单。';
COMMENT ON TABLE t_strategy_paper_trade IS '由 entry_triggered 候选产生的模拟交易。只在触发时保存 Quote/五档/分钟线证据，不落全市场高频快照。';

COMMIT;
