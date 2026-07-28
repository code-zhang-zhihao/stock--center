-- Versioned strategy evaluation, paper-trading and backtest lifecycle.
-- Requires 69-strategy-research-foundation.sql.  It does not connect to a
-- broker and only enables paper-mode strategy definitions after validation.

BEGIN;

UPDATE t_strategy_definition
SET status = 'research'
WHERE status = 'enabled';

ALTER TABLE t_strategy_definition
    DROP CONSTRAINT IF EXISTS ck_t_strategy_definition_status;
ALTER TABLE t_strategy_definition
    ADD CONSTRAINT ck_t_strategy_definition_status
    CHECK (status IN ('draft', 'research', 'paper', 'archived'));

CREATE TABLE IF NOT EXISTS t_strategy_version (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    implementation_code VARCHAR(80) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'draft',
    rule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_version_business UNIQUE (strategy_id, version_no),
    CONSTRAINT ck_t_strategy_version_no CHECK (version_no >= 1),
    CONSTRAINT ck_t_strategy_version_status CHECK (status IN ('draft', 'backtest_ready', 'paper', 'retired')),
    CONSTRAINT ck_t_strategy_version_implementation CHECK (implementation_code ~ '^[a-z][a-z0-9_]{0,79}$')
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_version_strategy_status
    ON t_strategy_version (strategy_id, status, version_no DESC);

-- Existing research definitions become immutable version 1.  New writes must
-- always create a new version rather than updating historical candidates.
INSERT INTO t_strategy_version (
    strategy_id, version_no, implementation_code, status, rule_config, risk_config, validation_summary
)
SELECT
    definition.id,
    1,
    COALESCE(NULLIF(definition.rule_config ->> 'implementation_code', ''), definition.strategy_code),
    CASE WHEN definition.status = 'paper' THEN 'paper' ELSE 'draft' END,
    definition.rule_config,
    definition.risk_config,
    '{}'::jsonb
FROM t_strategy_definition AS definition
WHERE NOT EXISTS (
    SELECT 1 FROM t_strategy_version AS version
    WHERE version.strategy_id = definition.id
);

ALTER TABLE t_strategy_candidate
    ADD COLUMN IF NOT EXISTS strategy_version_id BIGINT REFERENCES t_strategy_version(id) ON DELETE RESTRICT;

UPDATE t_strategy_candidate AS candidate
SET strategy_version_id = version.id
FROM t_strategy_version AS version
WHERE version.strategy_id = candidate.strategy_id
  AND version.version_no = 1
  AND candidate.strategy_version_id IS NULL;

ALTER TABLE t_strategy_candidate
    ALTER COLUMN strategy_version_id SET NOT NULL;

-- The original research table was unique by definition.  That would make two
-- different parameter versions overwrite/block one another on the same signal
-- date, defeating immutable strategy research.
ALTER TABLE t_strategy_candidate
    DROP CONSTRAINT IF EXISTS uq_t_strategy_candidate_business;
ALTER TABLE t_strategy_candidate
    ADD CONSTRAINT uq_t_strategy_candidate_version_business
    UNIQUE (strategy_version_id, signal_trade_date, stock_code);

CREATE INDEX IF NOT EXISTS idx_t_strategy_candidate_version_date
    ON t_strategy_candidate (strategy_version_id, signal_trade_date DESC, candidate_status, rank_no);

CREATE TABLE IF NOT EXISTS t_strategy_signal_event (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE CASCADE,
    strategy_version_id BIGINT NOT NULL REFERENCES t_strategy_version(id) ON DELETE RESTRICT,
    candidate_id BIGINT REFERENCES t_strategy_candidate(id) ON DELETE CASCADE,
    paper_trade_id BIGINT REFERENCES t_strategy_paper_trade(id) ON DELETE SET NULL,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    market_phase VARCHAR(24) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    decision VARCHAR(24) NOT NULL,
    reason_code VARCHAR(100),
    event_fingerprint CHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_signal_event_fingerprint UNIQUE (event_fingerprint),
    CONSTRAINT ck_t_strategy_signal_event_phase CHECK (market_phase IN ('post_close', 'auction', 'open', 'intraday', 'exit', 'system')),
    CONSTRAINT ck_t_strategy_signal_event_decision CHECK (decision IN ('matched', 'rejected', 'skipped', 'triggered', 'executed', 'degraded'))
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_signal_event_candidate_time
    ON t_strategy_signal_event (candidate_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_t_strategy_signal_event_trade_time
    ON t_strategy_signal_event (paper_trade_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_t_strategy_signal_event_stock_time
    ON t_strategy_signal_event (stock_code, event_time DESC);

ALTER TABLE t_strategy_paper_trade
    ADD COLUMN IF NOT EXISTS initial_quantity INTEGER;
ALTER TABLE t_strategy_paper_trade
    ADD COLUMN IF NOT EXISTS open_quantity INTEGER;

UPDATE t_strategy_paper_trade
SET initial_quantity = COALESCE(initial_quantity, quantity),
    open_quantity = COALESCE(open_quantity, CASE WHEN trade_status = 'open' THEN quantity ELSE 0 END);

ALTER TABLE t_strategy_paper_trade
    ALTER COLUMN initial_quantity SET NOT NULL;
ALTER TABLE t_strategy_paper_trade
    ALTER COLUMN open_quantity SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_t_strategy_paper_trade_open_quantity'
          AND conrelid = 't_strategy_paper_trade'::regclass
    ) THEN
        ALTER TABLE t_strategy_paper_trade
            ADD CONSTRAINT ck_t_strategy_paper_trade_open_quantity
            CHECK (open_quantity >= 0 AND open_quantity <= initial_quantity);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS t_strategy_paper_trade_leg (
    id BIGSERIAL PRIMARY KEY,
    paper_trade_id BIGINT NOT NULL REFERENCES t_strategy_paper_trade(id) ON DELETE CASCADE,
    leg_no INTEGER NOT NULL,
    side VARCHAR(8) NOT NULL,
    execution_time TIMESTAMPTZ NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    amount DOUBLE PRECISION,
    trigger_code VARCHAR(100) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_paper_trade_leg_business UNIQUE (paper_trade_id, leg_no),
    CONSTRAINT ck_t_strategy_paper_trade_leg_side CHECK (side IN ('buy', 'sell')),
    CONSTRAINT ck_t_strategy_paper_trade_leg_price CHECK (price > 0),
    CONSTRAINT ck_t_strategy_paper_trade_leg_quantity CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_paper_trade_leg_trade
    ON t_strategy_paper_trade_leg (paper_trade_id, execution_time, leg_no);

CREATE TABLE IF NOT EXISTS t_strategy_backtest_run (
    id BIGSERIAL PRIMARY KEY,
    run_code VARCHAR(64) NOT NULL,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE CASCADE,
    strategy_version_id BIGINT NOT NULL REFERENCES t_strategy_version(id) ON DELETE RESTRICT,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    execution_model VARCHAR(40) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    fee_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0005,
    slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 10,
    parameter_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_backtest_run_code UNIQUE (run_code),
    CONSTRAINT ck_t_strategy_backtest_run_dates CHECK (end_date >= start_date),
    CONSTRAINT ck_t_strategy_backtest_run_status CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    CONSTRAINT ck_t_strategy_backtest_run_execution_model CHECK (execution_model IN ('next_open_daily')),
    CONSTRAINT ck_t_strategy_backtest_run_fee CHECK (fee_rate >= 0 AND fee_rate <= 0.05),
    CONSTRAINT ck_t_strategy_backtest_run_slippage CHECK (slippage_bps >= 0 AND slippage_bps <= 1000)
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_backtest_run_version_created
    ON t_strategy_backtest_run (strategy_version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS t_strategy_backtest_trade (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id BIGINT NOT NULL REFERENCES t_strategy_backtest_run(id) ON DELETE CASCADE,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE CASCADE,
    strategy_version_id BIGINT NOT NULL REFERENCES t_strategy_version(id) ON DELETE RESTRICT,
    stock_code VARCHAR(20) NOT NULL,
    signal_trade_date DATE NOT NULL,
    entry_trade_date DATE NOT NULL,
    exit_trade_date DATE NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION NOT NULL,
    gross_return_pct DOUBLE PRECISION NOT NULL,
    net_return_pct DOUBLE PRECISION NOT NULL,
    holding_trade_days INTEGER NOT NULL,
    exit_reason VARCHAR(100) NOT NULL,
    candidate_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_backtest_trade_business UNIQUE (backtest_run_id, stock_code, signal_trade_date),
    CONSTRAINT ck_t_strategy_backtest_trade_entry_price CHECK (entry_price > 0),
    CONSTRAINT ck_t_strategy_backtest_trade_exit_price CHECK (exit_price > 0),
    CONSTRAINT ck_t_strategy_backtest_trade_holding CHECK (holding_trade_days >= 1)
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_backtest_trade_run
    ON t_strategy_backtest_trade (backtest_run_id, signal_trade_date, stock_code);

INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema, trigger_type,
    cron_expr, timezone, default_payload, max_instances, misfire_grace_seconds,
    timeout_seconds, retry_count, retry_interval_seconds, is_enabled, is_system,
    is_hidden, metadata
)
VALUES (
    'evaluate_strategy_daily_candidates',
    '生成策略盘后候选',
    'strategy',
    '仅从已完成的盘后报告事实生成 paper 策略候选；不调用行情 Provider、不创建真实订单。',
    '{"trade_date":{"label":"指定交易日期","type":"string","required":false,"description":"为空时使用最新已完成的盘后报告事实日。"},"strategy_code":{"label":"指定策略代码","type":"string","required":false,"description":"为空时评估所有 paper 状态的策略。"}}'::jsonb,
    'cron', '25 22 * * 1-5', 'Asia/Shanghai', '{}'::jsonb,
    1, 300, 600, 1, 300, true, true, false,
    '{"stage":"post_close","safe_mode":"paper_only"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    cron_expr = EXCLUDED.cron_expr,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_system = EXCLUDED.is_system,
    is_hidden = EXCLUDED.is_hidden,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_scheduler_job_tag (job_code, tag_code)
VALUES ('evaluate_strategy_daily_candidates', 'strategy')
ON CONFLICT DO NOTHING;

INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema, trigger_type,
    timezone, default_payload, max_instances, misfire_grace_seconds,
    timeout_seconds, retry_count, retry_interval_seconds, is_enabled, is_system,
    is_hidden, metadata
)
VALUES (
    'run_strategy_backtest',
    '运行策略日频基线回测',
    'strategy',
    '从本地历史事实按 next_open_daily 执行模型运行单版本基线回测；不调用行情 Provider、不连接券商。',
    '{"strategy_code":{"label":"策略代码","type":"string","required":true},"version_no":{"label":"版本号","type":"integer","required":true},"start_date":{"label":"开始日期","type":"string","required":true},"end_date":{"label":"结束日期","type":"string","required":true},"fee_rate":{"label":"单边费率","type":"number","default":0.0005,"required":false},"slippage_bps":{"label":"单边滑点（bps）","type":"number","default":10,"required":false}}'::jsonb,
    'cron', 'Asia/Shanghai', '{"fee_rate":0.0005,"slippage_bps":10}'::jsonb,
    1, 300, 3600, 0, 60, true, true, false,
    '{"stage":"research","execution_model":"next_open_daily","safe_mode":"local_facts_only"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    trigger_type = EXCLUDED.trigger_type,
    cron_expr = EXCLUDED.cron_expr,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_system = EXCLUDED.is_system,
    is_hidden = EXCLUDED.is_hidden,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_scheduler_job_tag (job_code, tag_code)
VALUES ('run_strategy_backtest', 'strategy')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE t_strategy_version IS '策略参数与实现代码的不可变版本。候选、信号、回测和模拟交易均绑定具体版本。';
COMMENT ON TABLE t_strategy_signal_event IS '策略每次有效决策的审计事件。只记录状态/理由变化，不持久化所有轮询快照。';
COMMENT ON TABLE t_strategy_paper_trade_leg IS '模拟交易的买入、减仓和清仓分笔，支持 T+1 下的分批退出。';
COMMENT ON TABLE t_strategy_backtest_run IS '严格 next_open_daily 日频基线回测运行，不冒充盘口或分钟级成交回测。';
COMMENT ON TABLE t_strategy_backtest_trade IS '回测逐笔交易，保存候选和执行快照以复现指标。';

COMMIT;
