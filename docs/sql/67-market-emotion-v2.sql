-- V2 dual-score market emotion: model definitions, immutable daily facts and
-- delayed market-level northbound-flow facts.  Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS t_market_north_flow_daily (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    hgt DOUBLE PRECISION,
    sgt DOUBLE PRECISION,
    north_money DOUBLE PRECISION,
    ggt_ss DOUBLE PRECISION,
    ggt_sz DOUBLE PRECISION,
    south_money DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_north_flow_daily_business UNIQUE (trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_t_market_north_flow_daily_trade_date
    ON t_market_north_flow_daily (trade_date DESC, source);

CREATE TABLE IF NOT EXISTS t_market_emotion_model (
    id BIGSERIAL PRIMARY KEY,
    model_code VARCHAR(80) NOT NULL,
    model_name VARCHAR(160) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    percentile_window_days BIGINT NOT NULL DEFAULT 120,
    minimum_history_days BIGINT NOT NULL DEFAULT 60,
    baseline_trade_days BIGINT NOT NULL DEFAULT 250,
    parameter_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    calibration_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_emotion_model_code UNIQUE (model_code),
    CONSTRAINT ck_t_market_emotion_model_status CHECK (status IN ('draft', 'calibrating', 'ready', 'active', 'archived')),
    CONSTRAINT ck_t_market_emotion_model_windows CHECK (
        percentile_window_days >= 60 AND minimum_history_days >= 20
        AND minimum_history_days <= percentile_window_days AND baseline_trade_days >= percentile_window_days
    )
);

CREATE INDEX IF NOT EXISTS idx_t_market_emotion_model_status
    ON t_market_emotion_model (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS t_market_emotion_daily (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    model_code VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    short_term_score DOUBLE PRECISION,
    market_risk_on_score DOUBLE PRECISION,
    primary_stage_code VARCHAR(40),
    auxiliary_state_code VARCHAR(40),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    scorecards JSONB NOT NULL DEFAULT '{}'::jsonb,
    stage_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameter_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    external_confirmations JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_emotion_daily_business UNIQUE (trade_date, model_code),
    CONSTRAINT ck_t_market_emotion_daily_status CHECK (status IN ('pending', 'ready', 'degraded', 'insufficient_history')),
    CONSTRAINT ck_t_market_emotion_daily_short_score CHECK (short_term_score IS NULL OR (short_term_score >= 0 AND short_term_score <= 100)),
    CONSTRAINT ck_t_market_emotion_daily_risk_score CHECK (market_risk_on_score IS NULL OR (market_risk_on_score >= 0 AND market_risk_on_score <= 100))
);

CREATE INDEX IF NOT EXISTS idx_t_market_emotion_daily_lookup
    ON t_market_emotion_daily (model_code, trade_date DESC, status);

COMMENT ON TABLE t_market_north_flow_daily IS 'Canonical/事实层：Tushare moneyflow_hsgt 的市场级北向/南向资金流；数值口径保留 Provider 原始单位。';
COMMENT ON TABLE t_market_emotion_model IS 'Derived 配置层：V2 双分情绪模型。仅 draft 可编辑；发布/启用前需完成基线校准。';
COMMENT ON TABLE t_market_emotion_daily IS 'Derived 层：按模型版本保存双分、阶段、原始指标、分位、贡献、质量与阶段证据；新参数不会覆盖历史版本。';

INSERT INTO t_market_emotion_model (
    model_code, model_name, status, percentile_window_days, minimum_history_days, baseline_trade_days, parameter_json
)
VALUES (
    'cn_a_emotion_v2',
    'A 股双分情绪 V2（默认草稿）',
    'draft', 120, 60, 250,
    '{
      "universe":{"exclude_st":true,"exclude_bse":true,"exclude_first_trade_days":5},
      "short_term":{"natural_limit_up_count":8,"qualified_limit_down_count":6,"limit_break_rate":8,"board_promotion_rate":9,"board_structure":9,"up_ratio_pct":6,"median_change_pct":6,"wide_move_ratio":7,"previous_limit_up_premium":6,"theme_limit_up_density":7,"theme_persistence":7,"leader_strength":6,"amount_vs_5d_average":6,"main_net_inflow_strength":5,"north_money":4},
      "risk_on":{"up_ratio_pct":10,"median_change_pct":10,"wide_move_ratio":10,"above_ma20_ratio":8,"above_ma60_ratio":8,"new_high_low_spread":9,"amount_vs_5d_average":8,"main_net_inflow_strength":8,"north_money":4,"turnover_volume_expansion":5,"core_index_trend":8,"index_amplitude":5,"qualified_limit_down_density":4,"volatility_20d":3},
      "stage_thresholds":{"ice_point":28,"recovery":48,"active":65,"climax":82,"retreat":42}
    }'::jsonb
)
ON CONFLICT (model_code) DO NOTHING;

UPDATE t_scheduler_job
SET
    job_name = '生成每日市场报告与 V2 情绪事实',
    description = '22:15 从已沉淀的日频事实生成 V1 兼容报告、V2 双分情绪与周期。V2 不调用 Provider/LLM；基线校准按 20 个交易日分批，只允许已校准模型启用。',
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb) || '{
      "include_v2_emotion":{"label":"计算 V2 双分情绪","type":"boolean","default":true,"required":false,"description":"日常仅计算当前 active V2 模型；没有启用模型时跳过。"},
      "emotion_model_code":{"label":"V2 模型代码","type":"string","required":false,"description":"仅校准模式使用，指定 draft/calibrating 模型。"},
      "emotion_mode":{"label":"V2 运行模式","type":"string","default":"daily","required":false,"description":"daily 计算启用模型当日；baseline 按模型基线交易日分批回填并生成验证摘要。"}
    }'::jsonb,
    default_payload = COALESCE(default_payload, '{}'::jsonb) || '{"include_v2_emotion":true,"emotion_mode":"daily"}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"source":"67-market-emotion-v2.sql","writes":["t_market_sentiment_daily","t_market_sector_heat_daily","t_market_limit_up_evidence_daily","t_market_emotion_daily"],"external_provider_calls":false,"llm_calls":false}'::jsonb,
    updated_at = now()
WHERE job_code = 'calculate_market_daily_sentiment';

UPDATE t_scheduler_job
SET
    description = '21:30 沉淀晚发布增强事实：涨跌停/炸板、停复牌、板块日线、专业技术因子、龙虎榜、市场统计、板块资金流与市场级北向资金流；北向持仓与两融按最近五个实际披露日补数，仅作延迟确认。',
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb) || '{
      "sync_market_north_flow":{"label":"同步市场级北向资金流","type":"boolean","default":true,"required":false,"description":"调用 moneyflow_hsgt 写入 t_market_north_flow_daily；未发布时标记延后。"},
      "sync_delayed_external_confirmations":{"label":"补北向持仓与两融延迟确认","type":"boolean","default":true,"required":false,"description":"读取最近五个开市日的实际披露结果，不作为当日报告完成条件。"}
    }'::jsonb,
    default_payload = COALESCE(default_payload, '{}'::jsonb) || '{"sync_market_north_flow":true,"sync_delayed_external_confirmations":true}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"source":"67-market-emotion-v2.sql","writes":["t_market_north_flow_daily","t_stock_north_hold_daily","t_margin_summary_daily"]}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_enrichment_ingest';

COMMIT;
