-- Activate the QFQ stock daily factor set after five completed shadow dates.
--
-- This script is intentionally gated and reversible: it only switches the
-- factor-set registry consumed by v_stock_factor_daily_active.  It does not
-- rename or delete either physical factor table.

BEGIN;

DO $$
DECLARE
    observed_dates INTEGER;
    failing_dates INTEGER := 0;
    latest_dates DATE[];
    target_date DATE;
    daily_bar_count BIGINT;
    ready_count BIGINT;
    adjust_fallback_count BIGINT;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'v_stock_factor_daily_active_basis'
          AND column_name = 'basis_close_price'
    ) THEN
        RAISE EXCEPTION 'V2 activation blocked: execute 76-stock-factor-v2-price-basis-consumers.sql first';
    END IF;

    -- Do not read the all-history comparison view here. Once V2 contains
    -- millions of rows that view also scans V1 and can make activation look
    -- hung. Five index-backed MAX lookups resolve the latest dates directly.
    WITH RECURSIVE latest(trade_date, ordinal) AS (
        SELECT max(trade_date), 1
        FROM t_stock_factor_daily_v2
        WHERE factor_set_version = 'stock_daily_v2'
        UNION ALL
        SELECT (
            SELECT max(candidate.trade_date)
            FROM t_stock_factor_daily_v2 AS candidate
            WHERE candidate.factor_set_version = 'stock_daily_v2'
              AND candidate.trade_date < latest.trade_date
        ), ordinal + 1
        FROM latest
        WHERE ordinal < 5 AND trade_date IS NOT NULL
    )
    SELECT array_agg(trade_date ORDER BY trade_date DESC)
    INTO latest_dates
    FROM latest
    WHERE trade_date IS NOT NULL;

    observed_dates := coalesce(cardinality(latest_dates), 0);

    IF observed_dates < 5 THEN
        RAISE EXCEPTION 'V2 activation blocked: only % completed shadow dates, require 5', observed_dates;
    END IF;

    FOREACH target_date IN ARRAY latest_dates LOOP
        SELECT count(*)
        INTO daily_bar_count
        FROM t_daily_bar
        WHERE trade_date = target_date;

        SELECT
            count(*) FILTER (WHERE factor_status = 'ready'),
            count(*) FILTER (
                WHERE missing_factors ?| ARRAY['adjust_factor', 'adjust_factor_history']
            )
        INTO ready_count, adjust_fallback_count
        FROM t_stock_factor_daily_v2
        WHERE trade_date = target_date
          AND factor_set_version = 'stock_daily_v2';

        IF daily_bar_count = 0
           OR ready_count::numeric / daily_bar_count < 0.98
           OR adjust_fallback_count > 0 THEN
            failing_dates := failing_dates + 1;
        END IF;
    END LOOP;

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
