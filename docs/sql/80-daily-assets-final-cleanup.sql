-- Daily data assets final convergence: destructive cleanup after observation.
-- Requires 79 cut-over, the final application build, and at least seven full
-- days of production observation. This script is intentionally irreversible;
-- take a database backup before running it.

\set ON_ERROR_STOP on

BEGIN;

SELECT pg_advisory_xact_lock(hashtext('daily_assets_final_cleanup'));

DO $$
DECLARE
    v_status TEXT;
    v_cutover_at TIMESTAMPTZ;
    v_running BIGINT;
    v_latest DATE;
    v_eligible BIGINT;
    v_bar BIGINT;
    v_basic BIGINT;
    v_fund BIGINT;
    v_factor BIGINT;
    v_price_ready BIGINT;
    v_core_ready BIGINT;
    v_raw_without_audit BIGINT;
    v_sector_unit_mismatch BIGINT;
    v_minute_factor BIGINT;
    v_minute_final BIGINT;
BEGIN
    SELECT status, cutover_at INTO v_status, v_cutover_at
    FROM t_data_asset_migration_state
    WHERE migration_code = 'daily_assets_final'
    FOR UPDATE;
    IF v_status IS DISTINCT FROM 'running_observation' THEN
        RAISE EXCEPTION 'cleanup blocked: migration status is %, require running_observation', v_status;
    END IF;
    IF v_cutover_at IS NULL OR v_cutover_at > now() - INTERVAL '7 days' THEN
        RAISE EXCEPTION 'cleanup blocked: seven-day observation window ends at %',
            v_cutover_at + INTERVAL '7 days';
    END IF;

    SELECT count(*) INTO v_running
    FROM t_scheduler_job_run
    WHERE job_code IN (
        'daily_close_minute_ingest', 'daily_close_core_ingest',
        'daily_close_enrichment_ingest', 'daily_close_repair_ingest',
        'calculate_market_daily_sentiment', 'backfill_stock_daily_factors',
        'backfill_sector_daily_factors', 'backfill_index_daily_factors'
    ) AND status IN ('queued', 'running');
    IF v_running > 0 THEN
        RAISE EXCEPTION 'cleanup blocked: % related scheduler runs are active', v_running;
    END IF;

    SELECT max(trade_date) INTO v_latest FROM t_daily_bar;
    SELECT count(*) INTO v_eligible FROM t_stock
    WHERE status = 'active' AND coalesce(is_st, false) IS FALSE
      AND exchange IN ('SH', 'SZ', 'SSE', 'SZSE');
    SELECT count(DISTINCT stock_code) INTO v_bar FROM t_daily_bar WHERE trade_date = v_latest;
    SELECT count(*) INTO v_basic FROM t_stock_daily_basic WHERE trade_date = v_latest;
    SELECT count(*) INTO v_fund FROM t_stock_fund_flow_daily WHERE trade_date = v_latest;
    SELECT count(*),
           count(*) FILTER (WHERE price_status = 'ready'),
           count(*) FILTER (WHERE technical_core_status = 'ready')
    INTO v_factor, v_price_ready, v_core_ready
    FROM t_stock_factor_daily WHERE trade_date = v_latest;
    IF v_bar < v_eligible * 0.98 OR v_basic < v_eligible * 0.98
       OR v_fund < v_eligible * 0.98 OR v_factor < v_eligible * 0.98
       OR v_price_ready < v_eligible * 0.98 OR v_core_ready < v_eligible * 0.98 THEN
        RAISE EXCEPTION
            'cleanup blocked on %: eligible %, bar %, basic %, fund %, factor %, price ready %, core ready %',
            v_latest, v_eligible, v_bar, v_basic, v_fund, v_factor, v_price_ready, v_core_ready;
    END IF;

    IF to_regclass('public.t_provider_raw_record') IS NOT NULL THEN
        EXECUTE $sql$
            SELECT count(*)
            FROM t_provider_raw_record raw
            LEFT JOIN t_provider_ingest_audit audit ON audit.trace_id = raw.trace_id
            WHERE audit.trace_id IS NULL
        $sql$ INTO v_raw_without_audit;
        IF v_raw_without_audit > 0 THEN
            RAISE EXCEPTION 'cleanup blocked: % raw completion rows have no compact audit', v_raw_without_audit;
        END IF;
    END IF;

    SELECT count(*) INTO v_sector_unit_mismatch
    FROM t_sector_fund_flow_daily
    WHERE source IN ('tushare:moneyflow_ind_ths', 'tushare:moneyflow_cnt_ths')
      AND main_net_inflow IS NOT NULL
      AND abs(coalesce(main_net_inflow_yuan, 0) - main_net_inflow * 10000.0) > 0.01;
    IF v_sector_unit_mismatch > 0 THEN
        RAISE EXCEPTION 'cleanup blocked: % THS sector rows still violate 亿元->元 correction',
            v_sector_unit_mismatch;
    END IF;

    SELECT count(*), count(*) FILTER (
        WHERE return_1m_pct IS NOT NULL OR return_5m_pct IS NOT NULL
           OR return_15m_pct IS NOT NULL OR ma5 IS NOT NULL
    ) INTO v_minute_factor, v_minute_final
    FROM t_stock_factor_minute;
    IF v_minute_factor > 0 AND v_minute_final < v_minute_factor * 0.95 THEN
        RAISE EXCEPTION 'cleanup blocked: final minute columns cover only %/% rows',
            v_minute_final, v_minute_factor;
    END IF;
END $$;

-- Stop compatibility triggers before removing their legacy source columns.
DROP TRIGGER IF EXISTS trg_daily_assets_final_basic_dual_write ON t_stock_daily_basic;
DROP TRIGGER IF EXISTS trg_daily_assets_final_fund_dual_write ON t_stock_fund_flow_daily;
DROP TRIGGER IF EXISTS trg_daily_assets_final_sector_fund_dual_write ON t_sector_fund_flow_daily;
DROP TRIGGER IF EXISTS trg_daily_assets_final_north_dual_write ON t_market_north_flow_daily;
DROP FUNCTION IF EXISTS fn_daily_assets_final_fact_dual_write();
DROP FUNCTION IF EXISTS fn_backfill_daily_assets_final_window(DATE, DATE);
DROP FUNCTION IF EXISTS fn_backfill_minute_factor_final(DATE);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 't_minute_bar'::regclass
          AND conname = 'uq_t_minute_bar_stock_date_time_interval_source_v2'
    ) THEN
        ALTER TABLE t_minute_bar
            RENAME CONSTRAINT uq_t_minute_bar_stock_date_time_interval_source_v2
            TO uq_t_minute_bar_stock_date_time_interval_source;
    END IF;
END $$;

DROP VIEW IF EXISTS v_stock_factor_daily_active_basis;
DROP VIEW IF EXISTS v_stock_factor_daily_active;
DROP VIEW IF EXISTS v_stock_factor_daily_v2_validation;

DROP TABLE IF EXISTS t_stock_factor_daily_legacy_final;
DROP TABLE IF EXISTS t_stock_factor_daily_v2;
DROP TABLE IF EXISTS t_factor_set_version;
DROP TABLE IF EXISTS t_stock_technical_factor_daily;
DROP TABLE IF EXISTS t_technical_indicator_snapshot;
DROP TABLE IF EXISTS t_market_sentiment_daily;
DROP TABLE IF EXISTS t_market_sector_heat_daily;
DROP TABLE IF EXISTS t_market_daily_stat;
DROP TABLE IF EXISTS t_stock_chip_perf_daily;
DROP TABLE IF EXISTS t_stock_north_hold_daily;
DROP TABLE IF EXISTS t_provider_raw_record;

DELETE FROM t_factor_definition
WHERE factor_code ~* '(^|[._-])v[12]($|[._-])';
UPDATE t_factor_definition
SET source_table = CASE
        WHEN source_table IN ('t_stock_factor_daily_v2', 'v_stock_factor_daily_active', 'v_stock_factor_daily_active_basis')
        THEN 't_stock_factor_daily' ELSE source_table END,
    metadata = coalesce(metadata, '{}'::jsonb)
        - 'version' - 'factor_set_version' - 'asset_convergence_version',
    updated_at = now();

UPDATE t_provider_ingest_audit
SET schema_version = 'canonical_final_r1'
WHERE schema_version IN ('canonical_v2', 'stock_daily_asset_v2', 'stock_daily_v2');

ALTER TABLE t_daily_bar
    DROP COLUMN IF EXISTS turnover_rate,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_minute_bar DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_stock_daily_basic
    DROP COLUMN IF EXISTS close_price,
    DROP COLUMN IF EXISTS limit_status,
    DROP COLUMN IF EXISTS turnover_rate,
    DROP COLUMN IF EXISTS turnover_rate_f,
    DROP COLUMN IF EXISTS volume_ratio,
    DROP COLUMN IF EXISTS dv_ratio,
    DROP COLUMN IF EXISTS dv_ttm,
    DROP COLUMN IF EXISTS total_share,
    DROP COLUMN IF EXISTS float_share,
    DROP COLUMN IF EXISTS free_share,
    DROP COLUMN IF EXISTS total_mv,
    DROP COLUMN IF EXISTS circ_mv,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_stock_adjust_factor DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_stock_fund_flow_daily
    DROP COLUMN IF EXISTS close_price,
    DROP COLUMN IF EXISTS change_pct,
    DROP COLUMN IF EXISTS rank,
    DROP COLUMN IF EXISTS main_net_inflow,
    DROP COLUMN IF EXISTS big_order_net_inflow,
    DROP COLUMN IF EXISTS super_large_net_inflow,
    DROP COLUMN IF EXISTS medium_net_inflow,
    DROP COLUMN IF EXISTS small_net_inflow,
    DROP COLUMN IF EXISTS small_buy_amount,
    DROP COLUMN IF EXISTS small_sell_amount,
    DROP COLUMN IF EXISTS medium_buy_amount,
    DROP COLUMN IF EXISTS medium_sell_amount,
    DROP COLUMN IF EXISTS large_buy_amount,
    DROP COLUMN IF EXISTS large_sell_amount,
    DROP COLUMN IF EXISTS super_large_buy_amount,
    DROP COLUMN IF EXISTS super_large_sell_amount,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_sector_bar DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_sector_fund_flow_daily
    DROP COLUMN IF EXISTS main_net_inflow,
    DROP COLUMN IF EXISTS net_buy_amount,
    DROP COLUMN IF EXISTS net_sell_amount,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_index_bar DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_index_daily_basic
    DROP COLUMN IF EXISTS total_mv,
    DROP COLUMN IF EXISTS float_mv,
    DROP COLUMN IF EXISTS total_share,
    DROP COLUMN IF EXISTS float_share,
    DROP COLUMN IF EXISTS free_share,
    DROP COLUMN IF EXISTS turnover_rate,
    DROP COLUMN IF EXISTS turnover_rate_f,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_market_north_flow_daily
    DROP COLUMN IF EXISTS hgt,
    DROP COLUMN IF EXISTS sgt,
    DROP COLUMN IF EXISTS north_money,
    DROP COLUMN IF EXISTS ggt_ss,
    DROP COLUMN IF EXISTS ggt_sz,
    DROP COLUMN IF EXISTS south_money,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_margin_summary_daily
    DROP COLUMN IF EXISTS rzye,
    DROP COLUMN IF EXISTS rz_mre,
    DROP COLUMN IF EXISTS rzche,
    DROP COLUMN IF EXISTS rqye,
    DROP COLUMN IF EXISTS rq_mcl,
    DROP COLUMN IF EXISTS rzrqye,
    DROP COLUMN IF EXISTS metadata;
ALTER TABLE t_stock_factor_minute
    DROP COLUMN IF EXISTS minute_return,
    DROP COLUMN IF EXISTS volume_spike_ratio,
    DROP COLUMN IF EXISTS intraday_strength,
    DROP COLUMN IF EXISTS features;
ALTER TABLE t_sector_factor_daily
    DROP COLUMN IF EXISTS net_inflow_3d,
    DROP COLUMN IF EXISTS net_inflow_5d,
    DROP COLUMN IF EXISTS net_inflow_10d,
    DROP COLUMN IF EXISTS tags,
    DROP COLUMN IF EXISTS features;
ALTER TABLE t_index_factor_daily
    DROP COLUMN IF EXISTS return_1d,
    DROP COLUMN IF EXISTS amplitude,
    DROP COLUMN IF EXISTS volume_ratio,
    DROP COLUMN IF EXISTS amount_ratio,
    DROP COLUMN IF EXISTS turnover_rate,
    DROP COLUMN IF EXISTS features;

UPDATE t_data_asset_migration_state
SET status = 'verified', verified_at = now(),
    details = details || jsonb_build_object(
        'cleanup_completed_at', now(),
        'official_factor_rows', (SELECT count(*) FROM t_stock_factor_daily),
        'legacy_assets_removed', true
    )
WHERE migration_code = 'daily_assets_final';

COMMIT;

ANALYZE t_daily_bar;
ANALYZE t_stock_daily_basic;
ANALYZE t_stock_fund_flow_daily;
ANALYZE t_stock_factor_daily;
ANALYZE t_sector_factor_daily;
ANALYZE t_index_factor_daily;
ANALYZE t_market_summary_daily;
ANALYZE t_provider_ingest_audit;

SELECT migration_code, status, cutover_at, verified_at, details
FROM t_data_asset_migration_state
WHERE migration_code = 'daily_assets_final';
