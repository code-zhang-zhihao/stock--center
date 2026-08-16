-- Resume the daily pipeline only after the final application build is live.
-- This script is idempotent and intentionally separate from atomic cut-over.

\set ON_ERROR_STOP on

BEGIN;

SELECT pg_advisory_xact_lock(hashtext('daily_assets_final_resume'));

DO $$
DECLARE
    v_status TEXT;
    v_running BIGINT;
    v_latest DATE;
    v_bar BIGINT;
    v_factor BIGINT;
    v_price BIGINT;
    v_technical_core BIGINT;
    v_local BIGINT;
    v_sector_bar BIGINT;
    v_sector_factor BIGINT;
    v_index_factor BIGINT;
    v_market_ready BOOLEAN;
BEGIN
    SELECT status INTO v_status
    FROM t_data_asset_migration_state
    WHERE migration_code = 'daily_assets_final'
    FOR UPDATE;
    IF v_status NOT IN ('cutover', 'running_observation') THEN
        RAISE EXCEPTION 'resume blocked: migration status is %', v_status;
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
        RAISE EXCEPTION 'resume blocked: % related jobs are still active', v_running;
    END IF;

    SELECT max(trade_date) INTO v_latest FROM t_daily_bar;
    SELECT count(DISTINCT stock_code) INTO v_bar
    FROM t_daily_bar WHERE trade_date = v_latest;
    SELECT count(*), count(*) FILTER (WHERE price_status = 'ready'),
           count(*) FILTER (WHERE technical_core_status = 'ready'),
           count(*) FILTER (WHERE calculation_revision = 'stock_daily_final_r1')
    INTO v_factor, v_price, v_technical_core, v_local
    FROM t_stock_factor_daily WHERE trade_date = v_latest;
    IF v_factor < v_bar * 0.98 OR v_price < v_bar * 0.98
       OR v_technical_core < v_bar * 0.98 OR v_local < v_bar * 0.98 THEN
        RAISE EXCEPTION 'resume blocked on %: bars %, factors %, price ready %, technical core %, local revision %',
            v_latest, v_bar, v_factor, v_price, v_technical_core, v_local;
    END IF;

    SELECT count(DISTINCT sector_code) INTO v_sector_bar
    FROM t_sector_bar WHERE trade_date = v_latest;
    SELECT count(*) INTO v_sector_factor
    FROM t_sector_factor_daily
    WHERE trade_date = v_latest AND calculation_revision = 'sector_daily_final_r1';
    SELECT count(*) INTO v_index_factor
    FROM t_index_factor_daily
    WHERE trade_date = v_latest
      AND index_code IN ('000001','399001','399006','000300','000905','000852','000016')
      AND calculation_revision = 'index_daily_final_r1';
    SELECT core_ready INTO v_market_ready
    FROM t_market_summary_daily WHERE trade_date = v_latest;
    IF v_sector_bar > 0 AND v_sector_factor < v_sector_bar * 0.98 THEN
        RAISE EXCEPTION 'resume blocked: sector factors %/% on %',
            v_sector_factor, v_sector_bar, v_latest;
    END IF;
    IF v_index_factor < 7 OR coalesce(v_market_ready, false) IS FALSE THEN
        RAISE EXCEPTION 'resume blocked: index factors %, market core_ready % on %',
            v_index_factor, v_market_ready, v_latest;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM t_provider_ingest_audit
        WHERE trade_date = v_latest AND status IN ('captured', 'complete_zero')
    ) THEN
        RAISE EXCEPTION 'resume blocked: no compact provider audit exists for %', v_latest;
    END IF;
END $$;

UPDATE t_scheduler_job job
SET is_enabled = coalesce(
    (state.details -> 'scheduler_enabled_before_cutover' ->> job.job_code)::boolean,
    false
)
FROM t_data_asset_migration_state state
WHERE state.migration_code = 'daily_assets_final'
  AND job.job_code IN (
      'daily_close_minute_ingest', 'daily_close_core_ingest',
      'daily_close_enrichment_ingest', 'daily_close_repair_ingest',
      'calculate_market_daily_sentiment'
  );

UPDATE t_data_asset_migration_state
SET status = 'running_observation',
    details = details || jsonb_build_object(
        'resume_required', false,
        'resumed_at', now()
    )
WHERE migration_code = 'daily_assets_final';

COMMIT;

SELECT migration_code, status, cutover_at, details
FROM t_data_asset_migration_state
WHERE migration_code = 'daily_assets_final';
