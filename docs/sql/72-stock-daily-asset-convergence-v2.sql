-- Stock daily asset convergence V2.
--
-- This migration is intentionally non-destructive.  It introduces the compact
-- ingest audit, canonical daily-fact view and a shadow V2 factor serving table.
-- Existing V1 factors and technical snapshots remain available until the
-- documented shadow validation and cut-over are complete.

BEGIN;

CREATE TABLE IF NOT EXISTS t_provider_ingest_audit (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(80) NOT NULL,
    provider_code VARCHAR(80) NOT NULL,
    capability VARCHAR(120) NOT NULL,
    trade_date DATE,
    request_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    response_row_count INTEGER NOT NULL DEFAULT 0,
    normalized_row_count INTEGER NOT NULL DEFAULT 0,
    payload_sha256 VARCHAR(64),
    normalized_table VARCHAR(120),
    schema_version VARCHAR(40) NOT NULL DEFAULT 'v1',
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(120),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_provider_ingest_audit_trace UNIQUE (trace_id),
    CONSTRAINT ck_t_provider_ingest_audit_status CHECK (
        status IN ('captured', 'complete_zero', 'deferred', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_t_provider_ingest_audit_completion
    ON t_provider_ingest_audit (normalized_table, trade_date, status);
CREATE INDEX IF NOT EXISTS idx_t_provider_ingest_audit_capability_date
    ON t_provider_ingest_audit (capability, trade_date DESC, created_at DESC);

-- Copy only completion metadata from the legacy raw store.  Payload bodies stay
-- in the legacy table during the shadow period and are never duplicated here.
INSERT INTO t_provider_ingest_audit (
    trace_id, provider_code, capability, trade_date, request_params,
    requested_fields, response_row_count, normalized_row_count, payload_sha256,
    normalized_table, schema_version, status, error_code, error_message,
    finished_at, created_at
)
SELECT
    raw.trace_id,
    raw.provider_code,
    raw.capability,
    CASE
        WHEN right(coalesce(raw.record_key, ''), 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        THEN right(raw.record_key, 10)::date
    END,
    coalesce(raw.request_params, '{}'::jsonb)
        - ARRAY['token', 'api_key', 'secret', 'password', 'authorization'],
    coalesce(raw.payload -> 'fields', raw.payload_summary -> 'fields', '[]'::jsonb),
    CASE
        WHEN coalesce(raw.payload_summary ->> 'row_count', '') ~ '^[0-9]+$'
        THEN (raw.payload_summary ->> 'row_count')::integer ELSE 0
    END,
    CASE
        WHEN coalesce(raw.payload_summary ->> 'row_count', '') ~ '^[0-9]+$'
        THEN (raw.payload_summary ->> 'row_count')::integer ELSE 0
    END,
    coalesce(raw.payload ->> 'sha256', raw.payload_summary ->> 'sha256'),
    raw.normalized_table,
    'legacy_migrated_v1',
    CASE
        WHEN raw.status = 'failed' THEN 'failed'
        WHEN raw.status = 'skipped' THEN 'deferred'
        WHEN coalesce(raw.payload_summary ->> 'row_count', '0') = '0' THEN 'complete_zero'
        ELSE 'captured'
    END,
    raw.error_code,
    raw.error_message,
    raw.created_at,
    raw.created_at
FROM t_provider_raw_record AS raw
ON CONFLICT (trace_id) DO UPDATE SET
    trade_date = coalesce(t_provider_ingest_audit.trade_date, EXCLUDED.trade_date),
    request_params = EXCLUDED.request_params,
    requested_fields = EXCLUDED.requested_fields,
    response_row_count = EXCLUDED.response_row_count,
    normalized_row_count = EXCLUDED.normalized_row_count,
    payload_sha256 = coalesce(t_provider_ingest_audit.payload_sha256, EXCLUDED.payload_sha256),
    normalized_table = coalesce(t_provider_ingest_audit.normalized_table, EXCLUDED.normalized_table);

CREATE TABLE IF NOT EXISTS t_factor_set_version (
    factor_set_code VARCHAR(80) PRIMARY KEY,
    factor_set_name VARCHAR(160) NOT NULL,
    version_no INTEGER NOT NULL,
    price_basis VARCHAR(20) NOT NULL,
    status VARCHAR(24) NOT NULL,
    activated_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_t_factor_set_version_price_basis CHECK (price_basis IN ('bfq', 'qfq', 'hfq')),
    CONSTRAINT ck_t_factor_set_version_status CHECK (status IN ('shadow', 'active', 'archived'))
);

INSERT INTO t_factor_set_version (
    factor_set_code, factor_set_name, version_no, price_basis, status, activated_at, metadata
)
VALUES
    ('stock_daily_v1', '个股日频因子 V1', 1, 'bfq', 'active', now(),
     '{"table":"t_stock_factor_daily","compatibility":true}'::jsonb),
    ('stock_daily_v2', '个股日频标准因子 V2', 2, 'qfq', 'shadow', NULL,
     '{"table":"t_stock_factor_daily_v2","professional_source":"tushare:stk_factor_pro"}'::jsonb)
ON CONFLICT (factor_set_code) DO NOTHING;

CREATE UNIQUE INDEX IF NOT EXISTS uq_t_factor_set_version_single_active
    ON t_factor_set_version ((status)) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS t_stock_factor_daily_v2 (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    factor_set_version VARCHAR(80) NOT NULL DEFAULT 'stock_daily_v2',
    price_basis VARCHAR(20) NOT NULL DEFAULT 'qfq',
    factor_status VARCHAR(24) NOT NULL DEFAULT 'partial',
    technical_source VARCHAR(80),
    local_source VARCHAR(80) NOT NULL DEFAULT 'system:daily_factor_v2',
    fund_source VARCHAR(80),
    source_map JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_factors JSONB NOT NULL DEFAULT '[]'::jsonb,

    open_qfq DOUBLE PRECISION,
    high_qfq DOUBLE PRECISION,
    low_qfq DOUBLE PRECISION,
    close_qfq DOUBLE PRECISION,
    pre_close_qfq DOUBLE PRECISION,

    ma5 DOUBLE PRECISION,
    ma10 DOUBLE PRECISION,
    ma20 DOUBLE PRECISION,
    ma30 DOUBLE PRECISION,
    ma60 DOUBLE PRECISION,
    ma90 DOUBLE PRECISION,
    ma250 DOUBLE PRECISION,
    ema5 DOUBLE PRECISION,
    ema10 DOUBLE PRECISION,
    ema20 DOUBLE PRECISION,
    ema30 DOUBLE PRECISION,
    ema60 DOUBLE PRECISION,
    macd DOUBLE PRECISION,
    macd_dif DOUBLE PRECISION,
    macd_dea DOUBLE PRECISION,
    kdj_j DOUBLE PRECISION,
    kdj_k DOUBLE PRECISION,
    kdj_d DOUBLE PRECISION,
    rsi6 DOUBLE PRECISION,
    rsi12 DOUBLE PRECISION,
    rsi14 DOUBLE PRECISION,
    rsi24 DOUBLE PRECISION,
    boll_upper DOUBLE PRECISION,
    boll_mid DOUBLE PRECISION,
    boll_lower DOUBLE PRECISION,
    atr DOUBLE PRECISION,
    cci DOUBLE PRECISION,
    vr DOUBLE PRECISION,
    wr DOUBLE PRECISION,
    wr1 DOUBLE PRECISION,
    bias1 DOUBLE PRECISION,
    bias2 DOUBLE PRECISION,
    bias3 DOUBLE PRECISION,
    obv DOUBLE PRECISION,
    mfi DOUBLE PRECISION,
    roc DOUBLE PRECISION,
    mtm DOUBLE PRECISION,

    return_1d DOUBLE PRECISION,
    return_3d DOUBLE PRECISION,
    return_5d DOUBLE PRECISION,
    return_10d DOUBLE PRECISION,
    return_20d DOUBLE PRECISION,
    amplitude_1d DOUBLE PRECISION,
    volume_ratio_5d DOUBLE PRECISION,
    amount_ratio_5d DOUBLE PRECISION,
    volatility_20d DOUBLE PRECISION,
    close_position_1d DOUBLE PRECISION,
    high_20d DOUBLE PRECISION,
    low_20d DOUBLE PRECISION,
    high_60d DOUBLE PRECISION,
    low_60d DOUBLE PRECISION,
    drawdown_20d DOUBLE PRECISION,
    drawdown_60d DOUBLE PRECISION,

    turnover_rate DOUBLE PRECISION,
    circ_mv DOUBLE PRECISION,
    total_mv DOUBLE PRECISION,
    main_net_inflow DOUBLE PRECISION,
    provider_main_net_ratio DOUBLE PRECISION,
    main_net_amount_ratio DOUBLE PRECISION,
    big_order_net_inflow DOUBLE PRECISION,
    big_order_net_amount_ratio DOUBLE PRECISION,
    super_large_net_inflow DOUBLE PRECISION,
    super_large_net_amount_ratio DOUBLE PRECISION,
    main_net_inflow_3d DOUBLE PRECISION,
    main_net_inflow_5d DOUBLE PRECISION,
    main_net_inflow_10d DOUBLE PRECISION,
    continuous_main_inflow_days INTEGER,
    fund_strength_percentile DOUBLE PRECISION,
    history_days INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_factor_daily_v2_business UNIQUE (stock_code, trade_date, factor_set_version),
    CONSTRAINT ck_t_stock_factor_daily_v2_price_basis CHECK (price_basis = 'qfq'),
    CONSTRAINT ck_t_stock_factor_daily_v2_status CHECK (factor_status IN ('partial', 'ready', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_v2_date_stock
    ON t_stock_factor_daily_v2 (trade_date, stock_code);
CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_v2_stock_date
    ON t_stock_factor_daily_v2 (stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_v2_ready_date
    ON t_stock_factor_daily_v2 (trade_date, stock_code) WHERE factor_status = 'ready';

CREATE OR REPLACE VIEW v_stock_daily_fact AS
SELECT
    bar.stock_code,
    bar.trade_date,
    bar.open_price,
    bar.high_price,
    bar.low_price,
    bar.close_price,
    bar.pre_close_price,
    bar.change_amount,
    bar.change_pct,
    bar.volume_hand,
    bar.volume_share,
    bar.amount_yuan,
    basic.turnover_rate,
    basic.turnover_rate_f,
    basic.volume_ratio AS provider_volume_ratio,
    basic.pe,
    basic.pe_ttm,
    basic.pb,
    basic.ps,
    basic.ps_ttm,
    basic.dv_ratio,
    basic.dv_ttm,
    basic.total_share,
    basic.float_share,
    basic.free_share,
    basic.total_mv,
    basic.circ_mv,
    flow.main_net_inflow,
    flow.main_net_ratio AS provider_main_net_ratio,
    flow.big_order_net_inflow,
    flow.big_order_net_ratio AS provider_big_order_net_ratio,
    flow.super_large_net_inflow,
    flow.medium_net_inflow,
    flow.small_net_inflow,
    flow.small_buy_amount,
    flow.small_sell_amount,
    flow.medium_buy_amount,
    flow.medium_sell_amount,
    flow.large_buy_amount,
    flow.large_sell_amount,
    flow.super_large_buy_amount,
    flow.super_large_sell_amount,
    flow.rank AS fund_flow_rank,
    bar.source AS daily_bar_source,
    basic.source AS daily_basic_source,
    flow.source AS fund_flow_source,
    jsonb_build_object(
        'daily_bar', true,
        'daily_basic', basic.id IS NOT NULL,
        'fund_flow', flow.id IS NOT NULL
    ) AS block_status,
    greatest(bar.updated_at, basic.updated_at, flow.updated_at) AS updated_at,
    bar.volume_hand / nullif(
        avg(bar.volume_hand) OVER (
            PARTITION BY bar.stock_code ORDER BY bar.trade_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ),
        0
    ) AS volume_ratio_5d,
    flow.main_net_inflow / nullif(bar.amount_yuan, 0) AS main_net_amount_ratio
FROM t_daily_bar AS bar
LEFT JOIN t_stock_daily_basic AS basic
  ON basic.stock_code = bar.stock_code
 AND basic.trade_date = bar.trade_date
LEFT JOIN t_stock_fund_flow_daily AS flow
  ON flow.stock_code = bar.stock_code
 AND flow.trade_date = bar.trade_date;

CREATE OR REPLACE VIEW v_stock_factor_daily_active AS
SELECT
    legacy.id,
    legacy.stock_code,
    legacy.trade_date,
    legacy.source,
    legacy.ma5,
    legacy.ma10,
    legacy.ma20,
    legacy.ma30,
    legacy.ma60,
    legacy.return_1d,
    legacy.amplitude,
    legacy.volume_ratio,
    legacy.amount_ratio,
    legacy.volatility_20d,
    legacy.close_position,
    legacy.features,
    'stock_daily_v1'::varchar AS factor_set_version,
    'bfq'::varchar AS price_basis,
    'ready'::varchar AS factor_status,
    jsonb_build_object('local', legacy.source) AS source_map,
    coalesce(legacy.features -> 'missing_windows', '[]'::jsonb) AS missing_factors,
    legacy.created_at,
    legacy.created_at AS updated_at
FROM t_stock_factor_daily AS legacy
WHERE EXISTS (
    SELECT 1 FROM t_factor_set_version
    WHERE factor_set_code = 'stock_daily_v1' AND status = 'active'
)
UNION ALL
SELECT
    v2.id,
    v2.stock_code,
    v2.trade_date,
    'system:daily_close'::varchar AS source,
    v2.ma5,
    v2.ma10,
    v2.ma20,
    v2.ma30,
    v2.ma60,
    v2.return_1d,
    v2.amplitude_1d AS amplitude,
    v2.volume_ratio_5d AS volume_ratio,
    v2.amount_ratio_5d AS amount_ratio,
    v2.volatility_20d,
    v2.close_position_1d AS close_position,
    jsonb_build_object('history_days', v2.history_days) AS features,
    v2.factor_set_version,
    v2.price_basis,
    v2.factor_status,
    v2.source_map,
    v2.missing_factors,
    v2.created_at,
    v2.updated_at
FROM t_stock_factor_daily_v2 AS v2
WHERE v2.factor_status = 'ready'
  AND EXISTS (
      SELECT 1 FROM t_factor_set_version
      WHERE factor_set_code = v2.factor_set_version AND status = 'active'
  );

CREATE OR REPLACE VIEW v_stock_factor_daily_v2_validation AS
WITH v2_coverage AS (
    SELECT
        trade_date,
        count(DISTINCT stock_code) AS v2_count,
        count(DISTINCT stock_code) FILTER (WHERE factor_status = 'ready') AS ready_count,
        count(DISTINCT stock_code) FILTER (WHERE missing_factors ? 'professional_technical') AS professional_fallback_count,
        count(DISTINCT stock_code) FILTER (
            WHERE missing_factors ?| ARRAY['adjust_factor', 'adjust_factor_history']
        ) AS adjust_fallback_count
    FROM t_stock_factor_daily_v2
    WHERE factor_set_version = 'stock_daily_v2'
    GROUP BY trade_date
),
daily_coverage AS (
    SELECT bar.trade_date, count(DISTINCT bar.stock_code) AS daily_bar_count
    FROM t_daily_bar AS bar
    JOIN v2_coverage AS v2 ON v2.trade_date = bar.trade_date
    GROUP BY bar.trade_date
),
comparison AS (
    SELECT
        v2.trade_date,
        count(*) AS comparison_count,
        avg(abs(v2.ma5 - v1.ma5)) FILTER (WHERE v2.ma5 IS NOT NULL AND v1.ma5 IS NOT NULL) AS avg_ma5_abs_diff,
        avg(abs(v2.ma20 - v1.ma20)) FILTER (WHERE v2.ma20 IS NOT NULL AND v1.ma20 IS NOT NULL) AS avg_ma20_abs_diff,
        avg(abs(v2.volume_ratio_5d - v1.volume_ratio)) FILTER (
            WHERE v2.volume_ratio_5d IS NOT NULL AND v1.volume_ratio IS NOT NULL
        ) AS avg_volume_ratio_abs_diff
    FROM t_stock_factor_daily_v2 AS v2
    JOIN t_stock_factor_daily AS v1
      ON v1.stock_code = v2.stock_code
     AND v1.trade_date = v2.trade_date
     AND v1.source = 'system:daily_close'
    WHERE v2.factor_set_version = 'stock_daily_v2'
    GROUP BY v2.trade_date
)
SELECT
    daily.trade_date,
    daily.daily_bar_count,
    coalesce(v2.v2_count, 0) AS v2_count,
    coalesce(v2.ready_count, 0) AS ready_count,
    round(coalesce(v2.ready_count, 0)::numeric / nullif(daily.daily_bar_count, 0), 6) AS ready_coverage,
    coalesce(v2.professional_fallback_count, 0) AS professional_fallback_count,
    coalesce(v2.adjust_fallback_count, 0) AS adjust_fallback_count,
    coalesce(comparison.comparison_count, 0) AS comparison_count,
    comparison.avg_ma5_abs_diff,
    comparison.avg_ma20_abs_diff,
    comparison.avg_volume_ratio_abs_diff
FROM daily_coverage AS daily
LEFT JOIN v2_coverage AS v2 USING (trade_date)
LEFT JOIN comparison USING (trade_date);

INSERT INTO t_factor_definition (
    factor_code, factor_name, factor_group, frequency, source_table,
    compute_method, is_rebuildable, metadata
)
VALUES
    ('minute_vwap', '分钟累计 VWAP', 'minute_price', 'minute', 't_stock_factor_minute', '累计成交额 / 累计成交股数', true, '{"version":"v2","window":"intraday"}'::jsonb),
    ('minute_return', '分钟日内收益', 'minute_price', 'minute', 't_stock_factor_minute', '当前价 / 当日首分钟价 - 1', true, '{"version":"v2","window":"intraday"}'::jsonb),
    ('minute_volume_spike_20', '分钟20期量能比', 'minute_volume', 'minute', 't_stock_factor_minute', '当前分钟量 / 前20分钟均量', true, '{"version":"v2","window":20}'::jsonb),
    ('minute_intraday_strength', '分钟日内位置', 'minute_price', 'minute', 't_stock_factor_minute', '(当前价-日内低)/(日内高-日内低)', true, '{"version":"v2","window":"intraday"}'::jsonb),
    ('volume_ratio_5d', '5日量比', 'daily_liquidity', 'daily', 't_stock_factor_daily_v2', '当日成交量 / 前5交易日平均成交量', true, '{"version":"stock_daily_v2"}'::jsonb),
    ('amount_ratio_5d', '5日额比', 'daily_liquidity', 'daily', 't_stock_factor_daily_v2', '当日成交额 / 前5交易日平均成交额', true, '{"version":"stock_daily_v2"}'::jsonb),
    ('volatility_20d', '20日实际波动率', 'daily_risk', 'daily', 't_stock_factor_daily_v2', '20交易日日收益总体标准差', true, '{"version":"stock_daily_v2"}'::jsonb),
    ('close_position_1d', '日内收盘位置', 'daily_price', 'daily', 't_stock_factor_daily_v2', '(收盘-最低)/(最高-最低)', true, '{"version":"stock_daily_v2"}'::jsonb),
    ('fund_strength_percentile', '资金强度横截面分位', 'daily_fund', 'daily', 't_stock_factor_daily_v2', '当日主力净流入全市场 cume_dist', true, '{"version":"stock_daily_v2"}'::jsonb),
    ('ma90', 'QFQ MA90', 'daily_technical', 'daily', 't_stock_factor_daily_v2', '专业 QFQ 优先；本地复权序列 90 日均值回退', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":90}'::jsonb),
    ('ma250', 'QFQ MA250', 'daily_technical', 'daily', 't_stock_factor_daily_v2', '专业 QFQ 优先；本地复权序列 250 日均值回退', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":250}'::jsonb),
    ('ema_qfq', 'QFQ EMA 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro EMA5/10/20/30/60', false, '{"version":"stock_daily_v2","price_basis":"qfq","columns":["ema5","ema10","ema20","ema30","ema60"]}'::jsonb),
    ('macd_qfq', 'QFQ MACD 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro MACD/DIF/DEA', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('kdj_qfq', 'QFQ KDJ 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro K/D/J', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('rsi_qfq', 'QFQ RSI 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', '专业 RSI6/12/24；本地 Wilder 14 日回退指标', true, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('boll_qfq', 'QFQ BOLL 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro 上轨/中轨/下轨', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('atr_qfq', 'QFQ ATR', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro ATR', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('cci_qfq', 'QFQ CCI', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro CCI', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('vr_qfq', 'QFQ VR', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro VR', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('wr_qfq', 'QFQ WR 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro WR/WR1', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('bias_qfq', 'QFQ BIAS 组', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro BIAS1/2/3', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('obv_qfq', 'QFQ OBV', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro OBV', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('mfi_qfq', 'QFQ MFI', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro MFI', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('roc_qfq', 'QFQ ROC', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro ROC', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('mtm_qfq', 'QFQ MTM', 'daily_technical', 'daily', 't_stock_factor_daily_v2', 'stk_factor_pro MTM', false, '{"version":"stock_daily_v2","price_basis":"qfq"}'::jsonb),
    ('return_3d', 'QFQ 3日收益', 'daily_price', 'daily', 't_stock_factor_daily_v2', '复权收盘价 3 日收益', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":3}'::jsonb),
    ('return_5d', 'QFQ 5日收益', 'daily_price', 'daily', 't_stock_factor_daily_v2', '复权收盘价 5 日收益', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":5}'::jsonb),
    ('return_10d', 'QFQ 10日收益', 'daily_price', 'daily', 't_stock_factor_daily_v2', '复权收盘价 10 日收益', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":10}'::jsonb),
    ('return_20d', 'QFQ 20日收益', 'daily_price', 'daily', 't_stock_factor_daily_v2', '复权收盘价 20 日收益', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":20}'::jsonb),
    ('drawdown_20d', '20日回撤', 'daily_risk', 'daily', 't_stock_factor_daily_v2', 'QFQ 收盘价 / 20日最高价 - 1', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":20}'::jsonb),
    ('drawdown_60d', '60日回撤', 'daily_risk', 'daily', 't_stock_factor_daily_v2', 'QFQ 收盘价 / 60日最高价 - 1', true, '{"version":"stock_daily_v2","price_basis":"qfq","window":60}'::jsonb)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    metadata = EXCLUDED.metadata,
    updated_at = now();

UPDATE t_scheduler_job
SET default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"sync_adjust_factor":true,"calculate_technical_snapshot":false}'::jsonb,
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || '{"sync_adjust_factor":{"label":"同步复权因子","type":"boolean","default":true,"required":false}}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"asset_convergence_version":2,"technical_snapshot_mode":"computed"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_core_ingest';

UPDATE t_scheduler_job
SET default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"assemble_daily_factors_v2":true,"merge_external_technical_factors":false}'::jsonb,
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || '{"assemble_daily_factors_v2":{"label":"组装V2标准因子","type":"boolean","default":true,"required":false}}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"asset_convergence_version":2,"factor_set":"stock_daily_v2","factor_mode":"shadow"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_enrichment_ingest';

UPDATE t_scheduler_job
SET job_name = '历史个股标准日频因子 V2 回填',
    description = '从 2021-01-01 开始按交易日、按股票分片组装 QFQ 标准因子；额外读取约 250 个交易日预热数据。技术快照由 API 动态生成，不再落库。',
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"start_date":"2021-01-01","include_external_technical":false}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"asset_convergence_version":2,"factor_set":"stock_daily_v2","technical_snapshot_mode":"computed"}'::jsonb,
    updated_at = now()
WHERE job_code = 'backfill_stock_daily_factors';

UPDATE t_scheduler_job
SET default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"start_date":"2020-01-01"}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"asset_convergence_version":2,"includes_adjust_factor":true,"factor_warmup_for":"2021-01-01","limit_event_completion_marker":"t_provider_ingest_audit"}'::jsonb,
    updated_at = now()
WHERE job_code = 'backfill_stock_daily_facts';

COMMENT ON TABLE t_provider_ingest_audit IS '接口级永久轻量审计；不保存完整 Provider 响应或敏感配置。';
COMMENT ON VIEW v_stock_daily_fact IS '个股日频统一事实视图；BFQ 行情、daily_basic 和资金流仍由各自窄事实表负责。';
COMMENT ON TABLE t_stock_factor_daily_v2 IS 'QFQ 标准日频因子影子表；专业全量 JSON 只保存在 t_stock_technical_factor_daily。';
COMMENT ON VIEW v_stock_factor_daily_active IS '当前激活因子集兼容视图；切换因子版本不要求策略改写查询口径。';
COMMENT ON VIEW v_stock_factor_daily_v2_validation IS 'V1/V2 影子验证：覆盖率、回退数量及关键兼容指标差异。';

COMMIT;
