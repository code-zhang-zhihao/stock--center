-- Persist reproducible post-close concept heat and limit-up associated evidence.
-- Safe to re-run.  It neither changes canonical facts nor infers a causal news reason.

BEGIN;

CREATE TABLE IF NOT EXISTS t_market_sector_heat_daily (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    sector_code VARCHAR(80) NOT NULL,
    sector_name VARCHAR(160) NOT NULL,
    calculation_version VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    heat_score DOUBLE PRECISION,
    heat_rank BIGINT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    components JSONB NOT NULL DEFAULT '{}'::jsonb,
    leaders JSONB NOT NULL DEFAULT '[]'::jsonb,
    coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_sector_heat_daily_business UNIQUE (trade_date, sector_code, calculation_version),
    CONSTRAINT ck_t_market_sector_heat_daily_status CHECK (status IN ('pending', 'ready')),
    CONSTRAINT ck_t_market_sector_heat_daily_score CHECK (heat_score IS NULL OR (heat_score >= 0 AND heat_score <= 100))
);

CREATE INDEX IF NOT EXISTS idx_t_market_sector_heat_daily_lookup
    ON t_market_sector_heat_daily (trade_date DESC, calculation_version, status, heat_rank);

CREATE TABLE IF NOT EXISTS t_market_limit_up_evidence_daily (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(120),
    calculation_version VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    board_count BIGINT,
    market_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    sector_context JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_limit_up_evidence_daily_business UNIQUE (trade_date, stock_code, calculation_version),
    CONSTRAINT ck_t_market_limit_up_evidence_daily_status CHECK (status IN ('pending', 'ready')),
    CONSTRAINT ck_t_market_limit_up_evidence_daily_board_count CHECK (board_count IS NULL OR board_count >= 1)
);

CREATE INDEX IF NOT EXISTS idx_t_market_limit_up_evidence_daily_lookup
    ON t_market_limit_up_evidence_daily (trade_date DESC, calculation_version, status, board_count DESC);

COMMENT ON TABLE t_market_sector_heat_daily IS 'Derived 层：由成分股日线、资金流、涨停事件直接聚合的同花顺概念热度，不依赖可能延迟的 ths_daily。';
COMMENT ON TABLE t_market_limit_up_evidence_daily IS 'Derived 层：涨停股的概念归属、龙虎榜和已沉淀公告关联证据快照；不构成涨停因果结论。';

-- Historical versions of the enrichment task recorded an empty ths_daily
-- response as captured.  A configured THS universe cannot have a valid
-- zero-row board-bar result, so retain the audit row but remove its false
-- completion status.  Future runs write this status directly in Python.
UPDATE t_provider_raw_record
SET
    status = 'failed',
    error_code = 'ths_daily_empty_or_not_published',
    error_message = 'ths_daily 未返回任何目标板块的当日行情'
WHERE capability = 'daily_market_close_sector_bars'
  AND normalized_table = 't_sector_bar'
  AND status = 'captured'
  AND COALESCE(payload_summary ->> 'row_count', '0') = '0';

UPDATE t_scheduler_job
SET
    job_name = '生成每日市场报告事实',
    description = '22:15 在增强日频事实完成后，计算市场情绪、同花顺概念热度、板块龙头及涨停关联证据。热度直接聚合成分股日线、资金流与涨停事件，不依赖 ths_daily；龙虎榜/公告只作为关联证据，不生成因果结论，不调用 LLM。',
    parameter_schema = '{
        "trade_date":{"label":"指定交易日期","type":"string","required":false,"description":"为空时计算最新已有日 K 的交易日。"},
        "start_date":{"label":"历史开始日期","type":"string","required":false,"description":"与历史结束日期同时填写时，按开市日范围计算历史市场情绪。"},
        "end_date":{"label":"历史结束日期","type":"string","required":false,"description":"与历史开始日期同时填写时，按开市日范围计算历史市场情绪。"},
        "calculation_version":{"label":"计算版本","type":"string","default":"v1","required":false,"description":"算法版本；修改版本会保留旧版本行，不覆盖既有日报或回测口径。"},
        "include_report_facts":{"label":"生成热点与涨停证据","type":"boolean","default":true,"required":false,"description":"默认同时沉淀概念热度、板块龙头和涨停关联证据；大范围历史情绪回填可关闭以缩短执行时间。"}
    }'::jsonb,
    default_payload = '{"calculation_version":"v1","include_report_facts":true}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stage":"post_close_report","source":"66-market-daily-review-facts.sql","calculation_version":"v1","depends_on":["daily_close_enrichment_ingest"],"writes":["t_market_sentiment_daily","t_market_sector_heat_daily","t_market_limit_up_evidence_daily"],"external_provider_calls":false,"llm_calls":false}'::jsonb,
    updated_at = now()
WHERE job_code = 'calculate_market_daily_sentiment';

COMMIT;
