-- Daily data assets final convergence: validated atomic cut-over.
-- Requires successful 77 prepare and 78 backfill.
-- Run in a maintenance window after stopping/reloading Scheduler workers.

\set ON_ERROR_STOP on

BEGIN;

SELECT pg_advisory_xact_lock(hashtext('daily_assets_final_cutover'));

DO $$
DECLARE
    v_status TEXT;
    v_running BIGINT;
BEGIN
    SELECT status INTO v_status
    FROM t_data_asset_migration_state
    WHERE migration_code = 'daily_assets_final'
    FOR UPDATE;
    IF v_status IS DISTINCT FROM 'backfilled' THEN
        RAISE EXCEPTION 'cutover blocked: migration status is %, require backfilled', v_status;
    END IF;

    SELECT count(*) INTO v_running
    FROM t_scheduler_job_run
    WHERE job_code IN (
        'daily_close_minute_ingest', 'daily_close_core_ingest',
        'daily_close_enrichment_ingest', 'daily_close_repair_ingest',
        'calculate_market_daily_sentiment'
    ) AND status IN ('queued', 'running');
    IF v_running > 0 THEN
        RAISE EXCEPTION 'cutover blocked: % daily scheduler runs are still active', v_running;
    END IF;
END $$;

UPDATE t_data_asset_migration_state
SET details = details || jsonb_build_object(
        'scheduler_enabled_before_cutover', (
            SELECT coalesce(jsonb_object_agg(job_code, is_enabled), '{}'::jsonb)
            FROM t_scheduler_job
            WHERE job_code IN (
                'daily_close_minute_ingest', 'daily_close_core_ingest',
                'daily_close_enrichment_ingest', 'daily_close_repair_ingest',
                'calculate_market_daily_sentiment'
            )
        )
    )
WHERE migration_code = 'daily_assets_final';

UPDATE t_scheduler_job SET is_enabled = false
WHERE job_code IN (
    'daily_close_minute_ingest', 'daily_close_core_ingest',
    'daily_close_enrichment_ingest', 'daily_close_repair_ingest',
    'calculate_market_daily_sentiment'
);

-- Capture any legacy completion records written after migration 72. Workers
-- are stopped at this point, so this is the final Raw -> compact-audit delta.
-- Payload bodies are deliberately not copied.
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
    CASE WHEN coalesce(raw.payload_summary ->> 'row_count', '') ~ '^[0-9]+$'
        THEN (raw.payload_summary ->> 'row_count')::integer ELSE 0 END,
    CASE WHEN coalesce(raw.payload_summary ->> 'row_count', '') ~ '^[0-9]+$'
        THEN (raw.payload_summary ->> 'row_count')::integer ELSE 0 END,
    coalesce(raw.payload ->> 'sha256', raw.payload_summary ->> 'sha256'),
    raw.normalized_table,
    'legacy_migrated_final',
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
FROM t_provider_raw_record raw
ON CONFLICT (trace_id) DO UPDATE SET
    trade_date = coalesce(t_provider_ingest_audit.trade_date, EXCLUDED.trade_date),
    request_params = EXCLUDED.request_params,
    requested_fields = EXCLUDED.requested_fields,
    response_row_count = EXCLUDED.response_row_count,
    normalized_row_count = EXCLUDED.normalized_row_count,
    payload_sha256 = coalesce(t_provider_ingest_audit.payload_sha256, EXCLUDED.payload_sha256),
    normalized_table = coalesce(t_provider_ingest_audit.normalized_table, EXCLUDED.normalized_table),
    schema_version = EXCLUDED.schema_version,
    status = EXCLUDED.status,
    error_code = EXCLUDED.error_code,
    error_message = EXCLUDED.error_message,
    finished_at = EXCLUDED.finished_at;

-- Catch up facts that arrived after migration 78. The function is idempotent.
SELECT * FROM fn_backfill_daily_assets_final_window(
    (SELECT min(trade_date) FROM (
        SELECT DISTINCT trade_date FROM t_daily_bar ORDER BY trade_date DESC LIMIT 20
    ) d),
    (SELECT max(trade_date) FROM t_daily_bar)
);

CREATE TEMP TABLE tmp_pro_factor_mapping (
    provider_field TEXT PRIMARY KEY,
    final_column TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_pro_factor_mapping VALUES
('open_qfq','open_qfq'),('high_qfq','high_qfq'),('low_qfq','low_qfq'),('close_qfq','close_qfq'),
('ma_qfq_5','ma5'),('ma_qfq_10','ma10'),('ma_qfq_20','ma20'),('ma_qfq_30','ma30'),
('ma_qfq_60','ma60'),('ma_qfq_90','ma90'),('ma_qfq_250','ma250'),
('ema_qfq_5','ema5'),('ema_qfq_10','ema10'),('ema_qfq_20','ema20'),
('ema_qfq_30','ema30'),('ema_qfq_60','ema60'),('ema_qfq_90','ema90'),('ema_qfq_250','ema250'),
('macd_qfq','macd'),('macd_dif_qfq','macd_dif'),('macd_dea_qfq','macd_dea'),
('kdj_qfq','kdj_j'),('kdj_k_qfq','kdj_k'),('kdj_d_qfq','kdj_d'),
('rsi_qfq_6','rsi6'),('rsi_qfq_12','rsi12'),('rsi_qfq_24','rsi24'),
('boll_upper_qfq','boll_upper'),('boll_mid_qfq','boll_mid'),('boll_lower_qfq','boll_lower'),
('atr_qfq','atr'),('bbi_qfq','bbi'),('bias1_qfq','bias1'),('bias2_qfq','bias2'),('bias3_qfq','bias3'),
('cci_qfq','cci'),('vr_qfq','vr'),('wr_qfq','wr'),('wr1_qfq','wr1'),
('obv_qfq','obv'),('mfi_qfq','mfi'),('roc_qfq','roc'),('mtm_qfq','mtm'),('mtmma_qfq','mtmma'),
('asi_qfq','asi'),('asit_qfq','asit'),('brar_ar_qfq','brar_ar'),('brar_br_qfq','brar_br'),
('cr_qfq','cr'),('dfma_dif_qfq','dfma_dif'),('dfma_difma_qfq','dfma_difma'),
('dmi_adx_qfq','dmi_adx'),('dmi_adxr_qfq','dmi_adxr'),('dmi_mdi_qfq','dmi_mdi'),('dmi_pdi_qfq','dmi_pdi'),
('dpo_qfq','dpo'),('madpo_qfq','madpo'),('emv_qfq','emv'),('maemv_qfq','maemv'),
('expma_12_qfq','expma12'),('expma_50_qfq','expma50'),
('ktn_down_qfq','keltner_lower'),('ktn_mid_qfq','keltner_mid'),('ktn_upper_qfq','keltner_upper'),
('mass_qfq','mass'),('ma_mass_qfq','ma_mass'),('maroc_qfq','maroc'),
('psy_qfq','psy'),('psyma_qfq','psyma'),
('taq_down_qfq','taq_lower'),('taq_mid_qfq','taq_mid'),('taq_up_qfq','taq_upper'),
('trix_qfq','trix'),('trma_qfq','trma'),
('xsii_td1_qfq','xsii_td1'),('xsii_td2_qfq','xsii_td2'),
('xsii_td3_qfq','xsii_td3'),('xsii_td4_qfq','xsii_td4'),
('updays','updays'),('downdays','downdays'),('topdays','topdays'),('lowdays','lowdays');

-- Freeze the factor dictionary against the one official physical table. The
-- provider field is audit metadata only; consumers use the typed column.
INSERT INTO t_factor_definition (
    factor_code, factor_name, factor_group, frequency, source_table,
    compute_method, is_rebuildable, metadata
)
SELECT
    'stock_daily.' || final_column,
    upper(final_column),
    CASE
        WHEN final_column IN ('open_qfq','high_qfq','low_qfq','close_qfq') THEN 'daily_price'
        WHEN final_column IN ('updays','downdays','topdays','lowdays') THEN 'daily_structure'
        ELSE 'daily_technical'
    END,
    'daily',
    't_stock_factor_daily',
    'Tushare stk_factor_pro.' || provider_field || ' 直接映射；核心组缺失时允许本地 QFQ 回退',
    final_column IN (
        'open_qfq','high_qfq','low_qfq','close_qfq',
        'ma5','ma10','ma20','ma30','ma60','ma90','ma250',
        'ema5','ema10','ema20','ema30','ema60','ema90','ema250',
        'macd','macd_dif','macd_dea','kdj_j','kdj_k','kdj_d',
        'rsi6','rsi12','rsi24','boll_upper','boll_mid','boll_lower','atr'
    ),
    jsonb_build_object(
        'price_basis', 'qfq',
        'provider', 'tushare',
        'provider_api', 'stk_factor_pro',
        'provider_field', provider_field,
        'typed_column', final_column
    )
FROM tmp_pro_factor_mapping
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_factor_definition (
    factor_code, factor_name, factor_group, frequency, source_table,
    compute_method, is_rebuildable, metadata
)
VALUES
('minute.return_1m_pct','1分钟收益率','minute_price','minute','t_stock_factor_minute','当前分钟价/前1分钟价-1',true,'{"unit":"pct","window":1}'::jsonb),
('minute.return_5m_pct','5分钟收益率','minute_price','minute','t_stock_factor_minute','当前分钟价/前5分钟价-1',true,'{"unit":"pct","window":5}'::jsonb),
('minute.return_15m_pct','15分钟收益率','minute_price','minute','t_stock_factor_minute','当前分钟价/前15分钟价-1',true,'{"unit":"pct","window":15}'::jsonb),
('minute.vwap','分钟累计VWAP','minute_price','minute','t_stock_factor_minute','真实累计成交额/真实累计成交股数；成交额缺失时为空',true,'{"unit":"yuan"}'::jsonb),
('minute.volume_ratio_20m','20分钟量比','minute_volume','minute','t_stock_factor_minute','当前分钟量/前20分钟平均量',true,'{"unit":"ratio","window":20}'::jsonb),
('minute.intraday_position_ratio','日内位置','minute_price','minute','t_stock_factor_minute','(当前价-日内最低)/(日内最高-日内最低)',true,'{"unit":"ratio"}'::jsonb),
('stock_daily.return_1d_pct','QFQ 1日收益','daily_price','daily','t_stock_factor_daily','QFQ收盘价1交易日收益',true,'{"unit":"pct","price_basis":"qfq","window":1}'::jsonb),
('stock_daily.return_5d_pct','QFQ 5日收益','daily_price','daily','t_stock_factor_daily','QFQ收盘价5交易日收益',true,'{"unit":"pct","price_basis":"qfq","window":5}'::jsonb),
('stock_daily.return_20d_pct','QFQ 20日收益','daily_price','daily','t_stock_factor_daily','QFQ收盘价20交易日收益',true,'{"unit":"pct","price_basis":"qfq","window":20}'::jsonb),
('stock_daily.volatility_20d','20日实际波动率','daily_risk','daily','t_stock_factor_daily','近20交易日1日收益总体标准差',true,'{"unit":"pct","window":20}'::jsonb),
('stock_daily.close_position_ratio','日内收盘位置','daily_price','daily','t_stock_factor_daily','(收盘-最低)/(最高-最低)',true,'{"unit":"ratio"}'::jsonb),
('stock_daily.main_net_inflow_percentile','主力资金横截面分位','daily_fund','daily','t_stock_factor_daily','当日合格股票主力净流入cume_dist',true,'{"unit":"score_0_100"}'::jsonb)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    metadata = EXCLUDED.metadata,
    updated_at = now();

UPDATE t_factor_definition
SET source_table = 't_stock_factor_daily',
    metadata = (coalesce(metadata, '{}'::jsonb) - 'version')
        || '{"physical_contract":"official"}'::jsonb,
    updated_at = now()
WHERE source_table IN ('t_stock_factor_daily_v2', 'v_stock_factor_daily_active', 'v_stock_factor_daily_active_basis');

CREATE TEMP TABLE tmp_factor_sample ON COMMIT DROP AS
SELECT stock_code, trade_date
FROM t_stock_factor_daily_final_shadow
WHERE trade_date >= (SELECT min(trade_date) FROM (
    SELECT DISTINCT trade_date FROM t_stock_factor_daily_final_shadow ORDER BY trade_date DESC LIMIT 20
) d)
ORDER BY stock_code, trade_date
LIMIT 2000;

DO $$
DECLARE
    mapping RECORD;
    mismatch_count BIGINT;
    latest_date DATE;
    bar_count BIGINT;
    factor_count BIGINT;
    price_ready_count BIGINT;
BEGIN
    FOR mapping IN SELECT * FROM tmp_pro_factor_mapping ORDER BY provider_field LOOP
        EXECUTE format($sql$
            SELECT count(*)
            FROM tmp_factor_sample sample
            JOIN t_stock_factor_daily_final_shadow target USING (stock_code, trade_date)
            JOIN t_stock_technical_factor_daily technical USING (stock_code, trade_date)
            WHERE technical.factors ? %L
              AND abs(coalesce(target.%I, 0)::double precision
                    - coalesce(nullif(technical.factors ->> %L, '')::double precision, 0)) > 1e-8
        $sql$, mapping.provider_field, mapping.final_column, mapping.provider_field)
        INTO mismatch_count;
        IF mismatch_count > 0 THEN
            RAISE EXCEPTION 'cutover blocked: Pro field % -> % has % sampled mismatches',
                mapping.provider_field, mapping.final_column, mismatch_count;
        END IF;
    END LOOP;

    SELECT max(trade_date) INTO latest_date FROM t_daily_bar;
    SELECT count(DISTINCT stock_code) INTO bar_count
    FROM t_daily_bar WHERE trade_date = latest_date;
    SELECT count(*), count(*) FILTER (WHERE price_status = 'ready')
    INTO factor_count, price_ready_count
    FROM t_stock_factor_daily_final_shadow WHERE trade_date = latest_date;
    -- A partial Pro response must not make cut-over circular: after the final
    -- application is deployed, the bounded stock-factor backfill fills the
    -- local QFQ core. Migration 79b enforces >=98% technical-core coverage
    -- before any daily scheduler is resumed.
    IF factor_count < bar_count * 0.98 OR price_ready_count < bar_count * 0.98 THEN
        RAISE EXCEPTION 'cutover blocked on %: bars %, factors %, price ready %',
            latest_date, bar_count, factor_count, price_ready_count;
    END IF;
END $$;

DROP VIEW IF EXISTS v_stock_factor_daily_active_basis;
DROP VIEW IF EXISTS v_stock_factor_daily_active;
DROP VIEW IF EXISTS v_stock_factor_daily_v2_validation;
DROP VIEW IF EXISTS v_stock_daily_fact;

DO $$
BEGIN
    IF to_regclass('public.t_stock_factor_daily_legacy_final') IS NOT NULL THEN
        RAISE EXCEPTION 'cutover blocked: t_stock_factor_daily_legacy_final already exists';
    END IF;
    ALTER TABLE t_stock_factor_daily RENAME TO t_stock_factor_daily_legacy_final;
    ALTER TABLE t_stock_factor_daily_final_shadow RENAME TO t_stock_factor_daily;
END $$;

CREATE OR REPLACE VIEW v_stock_daily_fact AS
SELECT
    bar.stock_code,
    bar.trade_date,
    bar.open_price AS bfq_open_price,
    bar.high_price AS bfq_high_price,
    bar.low_price AS bfq_low_price,
    bar.close_price AS bfq_close_price,
    bar.pre_close_price AS bfq_pre_close_price,
    bar.change_amount,
    bar.change_pct,
    bar.volume_share,
    bar.amount_yuan,
    basic.turnover_rate_pct,
    basic.turnover_rate_free_pct,
    basic.provider_volume_ratio,
    basic.pe, basic.pe_ttm, basic.pb, basic.ps, basic.ps_ttm,
    basic.dividend_yield_pct, basic.dividend_yield_ttm_pct,
    basic.total_share_shares, basic.float_share_shares, basic.free_share_shares,
    basic.total_market_value_yuan, basic.circulating_market_value_yuan,
    fund.main_net_inflow_yuan, fund.main_net_ratio AS provider_main_net_ratio,
    fund.big_order_net_inflow_yuan, fund.big_order_net_ratio,
    fund.super_large_net_inflow_yuan, fund.medium_net_inflow_yuan,
    fund.small_net_inflow_yuan,
    bar.source AS daily_bar_source,
    basic.source AS daily_basic_source,
    fund.source AS fund_flow_source,
    bar.updated_at AS daily_bar_updated_at,
    basic.updated_at AS daily_basic_updated_at,
    fund.updated_at AS fund_flow_updated_at
FROM t_daily_bar bar
LEFT JOIN t_stock_daily_basic basic USING (stock_code, trade_date)
LEFT JOIN t_stock_fund_flow_daily fund USING (stock_code, trade_date);

UPDATE t_scheduler_job
SET default_payload = default_payload
        - ARRAY[
            'assemble_daily_factors_v2', 'calculate_external_technical_factors',
            'merge_external_technical_factors', 'calculate_technical_snapshot',
            'sync_north_hold', 'sync_market_stats', 'sync_chip_perf',
            'calculate_stock_fund_factors', 'calculate_stock_fund'
          ]
        || CASE
            WHEN job_code = 'daily_close_core_ingest'
                THEN '{"calculate_daily_factors":false}'::jsonb
            WHEN job_code IN ('daily_close_enrichment_ingest', 'daily_close_repair_ingest')
                THEN '{"calculate_daily_factors":true}'::jsonb
            ELSE '{}'::jsonb
           END,
    parameter_schema = parameter_schema
        - ARRAY[
            'assemble_daily_factors_v2', 'calculate_external_technical_factors',
            'merge_external_technical_factors', 'calculate_technical_snapshot',
            'sync_north_hold', 'sync_market_stats', 'sync_chip_perf',
            'calculate_stock_fund_factors', 'calculate_stock_fund'
          ],
    metadata = coalesce(metadata, '{}'::jsonb)
        || '{"daily_asset_contract":"final","stock_factor_table":"t_stock_factor_daily"}'::jsonb
WHERE job_code IN (
    'daily_close_core_ingest', 'daily_close_enrichment_ingest',
    'daily_close_repair_ingest', 'backfill_stock_daily_factors'
);

UPDATE t_data_asset_migration_state
SET status = 'cutover', cutover_at = now(),
    details = details || jsonb_build_object(
        'official_table', 't_stock_factor_daily',
        'legacy_table', 't_stock_factor_daily_legacy_final',
        'cutover_at', now(),
        'resume_required', true
    )
WHERE migration_code = 'daily_assets_final';

COMMIT;

ANALYZE t_stock_factor_daily;
ANALYZE t_stock_daily_basic;
ANALYZE t_stock_fund_flow_daily;

SELECT migration_code, status, cutover_at, details
FROM t_data_asset_migration_state
WHERE migration_code = 'daily_assets_final';

\echo 'CUTOVER COMPLETE: keep Scheduler workers stopped, deploy/restart the final application, run bounded historical derived backfills, then execute 79b-daily-assets-final-resume.sql.'
