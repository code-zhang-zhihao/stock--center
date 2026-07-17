-- stock-center market partition owner fix.
-- Purpose: allow the backend runtime role to create and prune daily partitions
-- for t_minute_bar and t_stock_factor_minute.
--
-- Run this as postgres or as the current owner of the partition parent tables.

DO $$
DECLARE
    app_role CONSTANT text := 'stock_analysis_app';
    smoke_date CONSTANT date := DATE '2026-06-26';
    next_date date := smoke_date + 1;
    parent_name text;
    child_name text;
    child_record record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
        RAISE EXCEPTION 'role % does not exist', app_role;
    END IF;

    BEGIN
        EXECUTE format('GRANT USAGE, CREATE ON SCHEMA public TO %I', app_role);
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'skip schema grant: current role cannot grant on schema public; verify % already has USAGE and CREATE', app_role;
    END;

    IF to_regclass('public.t_minute_bar') IS NOT NULL THEN
        child_name := 't_minute_bar_p_' || to_char(smoke_date, 'YYYYMMDD');
        IF to_regclass('public.' || child_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE public.%I PARTITION OF public.t_minute_bar FOR VALUES FROM (%L) TO (%L)',
                child_name,
                smoke_date,
                next_date
            );
        END IF;
    END IF;

    IF to_regclass('public.t_stock_factor_minute') IS NOT NULL THEN
        child_name := 't_stock_factor_minute_p_' || to_char(smoke_date, 'YYYYMMDD');
        IF to_regclass('public.' || child_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE public.%I PARTITION OF public.t_stock_factor_minute FOR VALUES FROM (%L) TO (%L)',
                child_name,
                smoke_date,
                next_date
            );
        END IF;
    END IF;

    FOREACH parent_name IN ARRAY ARRAY['t_minute_bar', 't_stock_factor_minute']
    LOOP
        IF to_regclass('public.' || parent_name) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I OWNER TO %I', parent_name, app_role);
        END IF;
    END LOOP;

    FOR child_record IN
        SELECT c.relname AS child_table
        FROM pg_inherits i
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND p.relname IN ('t_minute_bar', 't_stock_factor_minute')
    LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO %I', child_record.child_table, app_role);
    END LOOP;
END $$;

SELECT
    c.relname AS table_name,
    pg_catalog.pg_get_userbyid(c.relowner) AS table_owner
FROM pg_class c
WHERE c.relname IN (
    't_minute_bar',
    't_stock_factor_minute',
    't_minute_bar_p_20260626',
    't_stock_factor_minute_p_20260626'
)
ORDER BY c.relname;
