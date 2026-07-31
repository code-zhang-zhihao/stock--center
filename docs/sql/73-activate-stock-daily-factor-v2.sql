-- Activate the QFQ stock daily factor set after five completed shadow dates.
--
-- This script is intentionally gated and reversible: it only switches the
-- factor-set registry consumed by v_stock_factor_daily_active.  It does not
-- rename or delete either physical factor table.

BEGIN;

DO $$
DECLARE
    observed_dates INTEGER;
    failing_dates INTEGER;
BEGIN
    SELECT count(*)
    INTO observed_dates
    FROM (
        SELECT trade_date
        FROM v_stock_factor_daily_v2_validation
        WHERE v2_count > 0
        ORDER BY trade_date DESC
        LIMIT 5
    ) AS latest;

    IF observed_dates < 5 THEN
        RAISE EXCEPTION 'V2 activation blocked: only % completed shadow dates, require 5', observed_dates;
    END IF;

    SELECT count(*)
    INTO failing_dates
    FROM (
        SELECT trade_date, ready_coverage, adjust_fallback_count
        FROM v_stock_factor_daily_v2_validation
        WHERE v2_count > 0
        ORDER BY trade_date DESC
        LIMIT 5
    ) AS latest
    WHERE ready_coverage < 0.98 OR adjust_fallback_count > 0;

    IF failing_dates > 0 THEN
        RAISE EXCEPTION 'V2 activation blocked: % of latest 5 dates fail 98%% ready coverage or still use incomplete adjustment history', failing_dates;
    END IF;
END
$$;

UPDATE t_factor_set_version
SET status = 'archived',
    updated_at = now(),
    metadata = coalesce(metadata, '{}'::jsonb) || '{"read_mode":"legacy_rollback"}'::jsonb
WHERE status = 'active'
  AND factor_set_code <> 'stock_daily_v2';

UPDATE t_factor_set_version
SET status = 'active',
    activated_at = now(),
    updated_at = now(),
    metadata = coalesce(metadata, '{}'::jsonb)
        || '{"validation_trade_days":5,"minimum_ready_coverage":0.98}'::jsonb
WHERE factor_set_code = 'stock_daily_v2';

ANALYZE t_stock_factor_daily_v2;

COMMIT;
