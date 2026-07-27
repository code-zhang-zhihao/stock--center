-- Versioned daily market-sentiment fact and its post-close calculation task.
-- Safe to re-run.  It does not modify canonical market data or historical task runs.

BEGIN;

CREATE TABLE IF NOT EXISTS t_market_sentiment_daily (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    universe_code VARCHAR(80) NOT NULL,
    calculation_version VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    sentiment_score DOUBLE PRECISION,
    stage_code VARCHAR(40),
    components JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_sentiment_daily_business UNIQUE (trade_date, universe_code, calculation_version),
    CONSTRAINT ck_t_market_sentiment_daily_status CHECK (status IN ('pending', 'ready')),
    CONSTRAINT ck_t_market_sentiment_daily_score CHECK (sentiment_score IS NULL OR (sentiment_score >= 0 AND sentiment_score <= 100))
);

CREATE INDEX IF NOT EXISTS idx_t_market_sentiment_daily_lookup
    ON t_market_sentiment_daily (universe_code, calculation_version, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_provider_raw_record_limit_event_completion
    ON t_provider_raw_record (normalized_table, normalized_pk, capability)
    WHERE status = 'captured' AND normalized_table = 't_limit_event_daily';

COMMENT ON TABLE t_market_sentiment_daily IS 'Derived 层：按版本保存的日频市场情绪事实。仅由 canonical 日线、涨跌停事件和交易日历计算，不调用 LLM。';
COMMENT ON COLUMN t_market_sentiment_daily.status IS 'pending 表示日线覆盖或涨跌停 Raw 完成标记不足，ready 才可作为报告/策略输入。';
COMMENT ON COLUMN t_market_sentiment_daily.components IS '可审计的规则评分分项、权重、原始值和公式。';
COMMENT ON COLUMN t_market_sentiment_daily.metrics IS '日线涨跌、成交、涨跌停、连板和昨日涨停溢价等输入事实。';
COMMENT ON COLUMN t_market_sentiment_daily.coverage IS 'active universe 覆盖率、限价事件完成标记及待完成原因。';

INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema, trigger_type, cron_expr, timezone,
    default_payload, max_instances, misfire_grace_seconds, timeout_seconds, retry_count,
    retry_interval_seconds, is_enabled, is_system, is_hidden, metadata
)
VALUES (
    'calculate_market_daily_sentiment',
    '计算每日市场情绪事实',
    'market_insight',
    '22:15 在增强日频事实完成后，读取已入库日线、涨跌停/炸板事件和交易日历，计算可追溯的情绪分与市场阶段；不请求外部数据源、不调用 LLM。日线覆盖不足或涨跌停 Raw 未完成时写入 pending，不生成伪评分。',
    '{
        "trade_date":{"label":"指定交易日期","type":"string","required":false,"description":"为空时计算最新已有日 K 的交易日。"},
        "start_date":{"label":"历史开始日期","type":"string","required":false,"description":"与历史结束日期同时填写时，按开市日范围计算历史情绪事实。"},
        "end_date":{"label":"历史结束日期","type":"string","required":false,"description":"与历史开始日期同时填写时，按开市日范围计算历史情绪事实。"},
        "calculation_version":{"label":"计算版本","type":"string","default":"v1","required":false,"description":"算法版本；修改版本会保留旧版本行，不覆盖既有日报或回测口径。"}
    }'::jsonb,
    'cron',
    '15 22 * * 1-5',
    'Asia/Shanghai',
    '{"calculation_version":"v1"}'::jsonb,
    1, 600, 900, 1, 300, true, true, false,
    '{"stage":"post_close_report","source":"65-market-daily-sentiment.sql","calculation_version":"v1","depends_on":["daily_close_enrichment_ingest"],"writes":["t_market_sentiment_daily"],"external_provider_calls":false,"llm_calls":false}'::jsonb
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
    max_instances = EXCLUDED.max_instances,
    misfire_grace_seconds = EXCLUDED.misfire_grace_seconds,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    metadata = COALESCE(t_scheduler_job.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at = now();

DO $$
BEGIN
    IF to_regclass('public.t_scheduler_job_tag') IS NOT NULL THEN
        EXECUTE $sql$
            INSERT INTO t_scheduler_job_tag (job_code, tag_code)
            SELECT 'calculate_market_daily_sentiment', 'daily'
            WHERE EXISTS (SELECT 1 FROM t_scheduler_tag WHERE tag_code = 'daily')
            ON CONFLICT (job_code, tag_code) DO NOTHING
        $sql$;
    END IF;
END $$;

COMMIT;
