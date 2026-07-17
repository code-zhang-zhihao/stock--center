-- Tushare Pro configuration and A-share canonical fact expansion.
-- Safe to re-run. It only creates/updates t_ prefixed assets and does not delete legacy data.

INSERT INTO t_system_config (category_code, config_code, config_name, description, sort_order, is_default, is_enabled, metadata)
VALUES ('market_data', 'tushare_pro', 'Tushare Pro', 'Tushare Pro A-share structured data source and encrypted Token pool.', 10, true, true, '{"source":"tushare-pro-bootstrap"}'::jsonb)
ON CONFLICT (category_code, config_code) DO UPDATE SET
    config_name = EXCLUDED.config_name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    metadata = t_system_config.metadata || EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_config_option (system_config_id, option_key, option_name, value_type, option_value, default_value, is_required, is_enabled, description, metadata)
SELECT sc.id, item.option_key, item.option_name, item.value_type, item.option_value, item.default_value, item.is_required, true, item.description, '{"source":"tushare-pro-bootstrap"}'::jsonb
FROM t_system_config sc
CROSS JOIN (
    VALUES
      ('api_url', 'API URL', 'string', '"http://api.tushare.pro"'::jsonb, '"http://api.tushare.pro"'::jsonb, true, 'Tushare Pro HTTP API address.'),
      ('timeout_seconds', '请求超时秒数', 'number', '30'::jsonb, '30'::jsonb, true, 'Single Tushare request timeout.'),
      ('rate_limit_per_minute', '每分钟请求上限', 'number', '60'::jsonb, '60'::jsonb, true, 'Local per-process rate limiter; tune according to account entitlement.'),
      ('retry_count', '网络重试次数', 'number', '1'::jsonb, '1'::jsonb, false, 'Retries for transport failures only.'),
      ('cooldown_seconds', '限频冷却秒数', 'number', '60'::jsonb, '60'::jsonb, false, 'A rate-limited Token is temporarily excluded for this duration.')
) AS item(option_key, option_name, value_type, option_value, default_value, is_required, description)
WHERE sc.category_code = 'market_data' AND sc.config_code = 'tushare_pro'
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();

CREATE TABLE IF NOT EXISTS t_stock_daily_basic (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    turnover_rate NUMERIC(18,6), volume_ratio NUMERIC(18,6), pe NUMERIC(24,6), pb NUMERIC(24,6),
    total_share NUMERIC(24,4), float_share NUMERIC(24,4), total_mv NUMERIC(24,2), circ_mv NUMERIC(24,2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_daily_basic_business UNIQUE (stock_code, trade_date, source)
);
CREATE TABLE IF NOT EXISTS t_stock_adjust_factor (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, trade_date DATE NOT NULL, source VARCHAR(80) NOT NULL, adj_factor NUMERIC(24,10) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_adjust_factor_business UNIQUE (stock_code, trade_date, source)
);
CREATE TABLE IF NOT EXISTS t_financial_statement (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, report_type VARCHAR(40) NOT NULL, report_period DATE NOT NULL, announcement_date DATE,
    source VARCHAR(80) NOT NULL, fields JSONB NOT NULL DEFAULT '{}'::jsonb, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_financial_statement_business UNIQUE (stock_code, report_type, report_period, source)
);
CREATE TABLE IF NOT EXISTS t_financial_indicator (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, report_period DATE NOT NULL, announcement_date DATE, source VARCHAR(80) NOT NULL,
    indicators JSONB NOT NULL DEFAULT '{}'::jsonb, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_financial_indicator_business UNIQUE (stock_code, report_period, source)
);
CREATE TABLE IF NOT EXISTS t_corporate_action (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, action_type VARCHAR(60) NOT NULL, ex_date DATE, announcement_date DATE,
    record_date DATE, source VARCHAR(80) NOT NULL, fields JSONB NOT NULL DEFAULT '{}'::jsonb, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_corporate_action_business UNIQUE (stock_code, action_type, ex_date, announcement_date, source)
);
CREATE TABLE IF NOT EXISTS t_margin_summary_daily (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL, exchange VARCHAR(20) NOT NULL, source VARCHAR(80) NOT NULL,
    rzye NUMERIC(24,2), rz_mre NUMERIC(24,2), rzche NUMERIC(24,2), rqye NUMERIC(24,2), rq_mcl NUMERIC(24,2), rzrqye NUMERIC(24,2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_margin_summary_daily_business UNIQUE (trade_date, exchange, source)
);
CREATE TABLE IF NOT EXISTS t_margin_detail_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, trade_date DATE NOT NULL, exchange VARCHAR(20), source VARCHAR(80) NOT NULL,
    rzye NUMERIC(24,2), rz_mre NUMERIC(24,2), rzche NUMERIC(24,2), rqye NUMERIC(24,2), rq_mcl NUMERIC(24,2), rzrqye NUMERIC(24,2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_margin_detail_daily_business UNIQUE (stock_code, trade_date, source)
);
CREATE TABLE IF NOT EXISTS t_limit_event_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, trade_date DATE NOT NULL, event_type VARCHAR(30) NOT NULL, source VARCHAR(80) NOT NULL,
    close_price NUMERIC(18,4), limit_price NUMERIC(18,4), first_time TIME, last_time TIME, open_count INTEGER,
    turnover_amount NUMERIC(24,2), metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_limit_event_daily_business UNIQUE (stock_code, trade_date, event_type, source)
);
CREATE TABLE IF NOT EXISTS t_stock_holder_count (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, report_period DATE NOT NULL, announcement_date DATE, holder_count NUMERIC(24,2), source VARCHAR(80) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_holder_count_business UNIQUE (stock_code, report_period, source)
);
CREATE TABLE IF NOT EXISTS t_stock_top_holder (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL, report_period DATE NOT NULL, holder_name VARCHAR(300) NOT NULL, holder_type VARCHAR(80),
    hold_amount NUMERIC(24,4), hold_ratio NUMERIC(18,8), source VARCHAR(80) NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_top_holder_business UNIQUE (stock_code, report_period, holder_name, source)
);

DO $$
BEGIN
    BEGIN CREATE INDEX IF NOT EXISTS idx_t_financial_statement_stock_period ON t_financial_statement(stock_code, report_period DESC); EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'Skipping idx_t_financial_statement_stock_period: current role is not table owner'; END;
    BEGIN CREATE INDEX IF NOT EXISTS idx_t_financial_indicator_stock_period ON t_financial_indicator(stock_code, report_period DESC); EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'Skipping idx_t_financial_indicator_stock_period: current role is not table owner'; END;
    BEGIN CREATE INDEX IF NOT EXISTS idx_t_margin_detail_stock_date ON t_margin_detail_daily(stock_code, trade_date DESC); EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'Skipping idx_t_margin_detail_stock_date: current role is not table owner'; END;
    BEGIN CREATE INDEX IF NOT EXISTS idx_t_limit_event_stock_date ON t_limit_event_daily(stock_code, trade_date DESC); EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'Skipping idx_t_limit_event_stock_date: current role is not table owner'; END;
    BEGIN CREATE INDEX IF NOT EXISTS idx_t_stock_top_holder_stock_period ON t_stock_top_holder(stock_code, report_period DESC); EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'Skipping idx_t_stock_top_holder_stock_period: current role is not table owner'; END;
END $$;

DO $$
DECLARE
    target_table TEXT;
    column_row RECORD;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        't_stock_daily_basic', 't_stock_adjust_factor', 't_financial_statement', 't_financial_indicator',
        't_corporate_action', 't_margin_summary_daily', 't_margin_detail_daily', 't_limit_event_daily',
        't_stock_holder_count', 't_stock_top_holder'
    ] LOOP
        BEGIN
            EXECUTE format('COMMENT ON TABLE public.%I IS %L', target_table, 'Tushare A-share canonical fact table.');
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'Skipping table comment for % because current role is not the owner', target_table;
        END;
        FOR column_row IN
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = target_table
        LOOP
            BEGIN
                EXECUTE format(
                    'COMMENT ON COLUMN public.%I.%I IS %L',
                    target_table,
                    column_row.column_name,
                    'Tushare A-share canonical field: ' || column_row.column_name || '.'
                );
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'Skipping column comment for %.% because current role is not the owner', target_table, column_row.column_name;
            END;
        END LOOP;
    END LOOP;
END $$;

UPDATE t_scheduler_job
SET
    description = '每日同步 A 股概念/行业板块与成分快照；Tushare Pro 为主源，仅完整快照可物理删除旧关联。',
    default_payload = jsonb_set(COALESCE(default_payload, '{}'::jsonb), '{source}', '"tushare"'::jsonb, true),
    parameter_schema = jsonb_set(
        COALESCE(parameter_schema, '{}'::jsonb),
        '{source}',
        '{"label":"数据源","type":"string","default":"tushare","required":false,"options":["tushare","akshare"],"description":"Tushare Pro 为主源；AkShare 为备用。"}'::jsonb,
        true
    ),
    updated_at = now()
WHERE job_code = 'sync_sector_catalog';

UPDATE t_scheduler_job
SET
    description = '每周同步 A 股基础资料，Tushare 为主源，AkShare 和 MooTDX 依次 fallback。',
    default_payload = jsonb_set(COALESCE(default_payload, '{}'::jsonb), '{source}', '"tushare"'::jsonb, true),
    parameter_schema = jsonb_set(
        COALESCE(parameter_schema, '{}'::jsonb),
        '{source}',
        '{"label":"主数据源","type":"string","default":"tushare","required":false,"options":["tushare","akshare","mootdx"],"description":"Tushare 为主源，失败时依次回退。"}'::jsonb,
        true
    ),
    updated_at = now()
WHERE job_code = 'sync_stock_basic';

INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema, trigger_type, cron_expr, timezone,
    default_payload, max_instances, misfire_grace_seconds, timeout_seconds, retry_count,
    retry_interval_seconds, is_enabled, is_system, is_hidden, metadata
)
VALUES (
    'sync_tushare_a_share_topic', '同步 Tushare A 股专题数据', 'market_data',
    '按指定专题同步 Tushare 基础指标、财务、公司行动、融资融券、涨跌停或股东数据；默认禁用。',
    '{"topic":{"label":"Tushare 数据主题","type":"string","required":true,"options":["daily_basic","adj_factor","income","balancesheet","cashflow","fina_indicator","dividend","margin","margin_detail","limit_list_d","stk_holdernumber","top10_holders"]},"params":{"label":"Tushare 参数 JSON","type":"json","default":{},"required":false},"fields":{"label":"字段列表","type":"string","default":"","required":false},"limit":{"label":"写入上限","type":"number","default":5000,"min":1,"max":10000}}'::jsonb,
    'cron', NULL, 'Asia/Shanghai',
    '{"topic":"daily_basic","params":{},"fields":"","limit":5000}'::jsonb,
    1, 1800, 7200, 0, 300, false, false, false,
    '{"source":"tushare-pro-bootstrap","phase":"a_share_expansion"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name, description = EXCLUDED.description, parameter_schema = EXCLUDED.parameter_schema,
    trigger_type = EXCLUDED.trigger_type, cron_expr = EXCLUDED.cron_expr, timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload, timeout_seconds = EXCLUDED.timeout_seconds,
    is_enabled = EXCLUDED.is_enabled, metadata = EXCLUDED.metadata, updated_at = now();
