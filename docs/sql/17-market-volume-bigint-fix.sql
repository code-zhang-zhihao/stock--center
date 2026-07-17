-- stock-center market volume bigint fix.
-- Purpose: early databases may still have INTEGER volume columns, while
-- all-market Tushare daily data can exceed PostgreSQL int32 range.

DO $$
BEGIN
    IF to_regclass('public.t_daily_bar') IS NOT NULL THEN
        ALTER TABLE t_daily_bar
            ALTER COLUMN volume_hand TYPE BIGINT USING volume_hand::bigint,
            ALTER COLUMN volume_share TYPE BIGINT USING volume_share::bigint;
    END IF;

    IF to_regclass('public.t_daily_bar_legacy') IS NOT NULL THEN
        ALTER TABLE t_daily_bar_legacy
            ALTER COLUMN volume_hand TYPE BIGINT USING volume_hand::bigint,
            ALTER COLUMN volume_share TYPE BIGINT USING volume_share::bigint;
    END IF;

    IF to_regclass('public.t_minute_bar') IS NOT NULL THEN
        ALTER TABLE t_minute_bar
            ALTER COLUMN volume_hand TYPE BIGINT USING volume_hand::bigint,
            ALTER COLUMN volume_share TYPE BIGINT USING volume_share::bigint;
    END IF;

    IF to_regclass('public.t_minute_bar_legacy') IS NOT NULL THEN
        ALTER TABLE t_minute_bar_legacy
            ALTER COLUMN volume_hand TYPE BIGINT USING volume_hand::bigint,
            ALTER COLUMN volume_share TYPE BIGINT USING volume_share::bigint;
    END IF;

    IF to_regclass('public.t_quote_snapshot') IS NOT NULL THEN
        ALTER TABLE t_quote_snapshot
            ALTER COLUMN volume_hand TYPE BIGINT USING volume_hand::bigint;
    END IF;

    IF to_regclass('public.t_tick_trade') IS NOT NULL THEN
        ALTER TABLE t_tick_trade
            ALTER COLUMN volume_hand TYPE BIGINT USING volume_hand::bigint;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.t_daily_bar') IS NOT NULL THEN
        COMMENT ON COLUMN t_daily_bar.volume_hand IS '成交量，单位手；使用 BIGINT 以容纳全市场沉淀中的超 int32 成交量。';
        COMMENT ON COLUMN t_daily_bar.volume_share IS '成交量，单位股；使用 BIGINT 以容纳全市场沉淀中的超 int32 成交量。';
    END IF;
    IF to_regclass('public.t_minute_bar') IS NOT NULL THEN
        COMMENT ON COLUMN t_minute_bar.volume_hand IS '成交量，单位手；使用 BIGINT。';
        COMMENT ON COLUMN t_minute_bar.volume_share IS '成交量，单位股；使用 BIGINT。';
    END IF;
    IF to_regclass('public.t_quote_snapshot') IS NOT NULL THEN
        COMMENT ON COLUMN t_quote_snapshot.volume_hand IS '成交量，单位手；使用 BIGINT。';
    END IF;
    IF to_regclass('public.t_tick_trade') IS NOT NULL THEN
        COMMENT ON COLUMN t_tick_trade.volume_hand IS '成交量，单位手；使用 BIGINT。';
    END IF;
END $$;
