-- Canonical single-fact consolidation for daily quantitative ingestion.
-- Safe to re-run after 16-20. It preserves superseded multi-source rows in
-- t_canonical_source_conflict_backup before enforcing business-level uniqueness.

CREATE TABLE IF NOT EXISTS t_canonical_source_conflict_backup (
    id BIGSERIAL PRIMARY KEY,
    source_table VARCHAR(120) NOT NULL,
    business_key TEXT NOT NULL,
    row_data JSONB NOT NULL,
    reason TEXT NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE t_canonical_source_conflict_backup IS '审计备份：canonical 单事实收口前被归并的多 source 历史行。';
COMMENT ON COLUMN t_canonical_source_conflict_backup.source_table IS '来源 canonical 表名。';
COMMENT ON COLUMN t_canonical_source_conflict_backup.business_key IS '归并业务键。';
COMMENT ON COLUMN t_canonical_source_conflict_backup.row_data IS '被归并行的完整 JSON 快照。';
COMMENT ON COLUMN t_canonical_source_conflict_backup.reason IS '归并原因。';

ALTER TABLE t_stock_fund_flow_daily
    ADD COLUMN IF NOT EXISTS small_buy_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS small_sell_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS medium_buy_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS medium_sell_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS large_buy_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS large_sell_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS super_large_buy_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS super_large_sell_amount NUMERIC(24,4);

ALTER TABLE t_sector_fund_flow_daily
    ADD COLUMN IF NOT EXISTS net_buy_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS net_sell_amount NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS close_price NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS company_num INTEGER,
    ADD COLUMN IF NOT EXISTS lead_stock VARCHAR(120),
    ADD COLUMN IF NOT EXISTS lead_stock_change_pct NUMERIC(18,6);

ALTER TABLE t_sector_bar
    ADD COLUMN IF NOT EXISTS pre_close_price NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS change_amount NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS volume NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS turnover_rate NUMERIC(18,6);

ALTER TABLE t_index_bar
    ADD COLUMN IF NOT EXISTS volume NUMERIC(24,4);

CREATE TABLE IF NOT EXISTS t_stock_north_hold_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(120),
    trade_date DATE NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    source VARCHAR(80) NOT NULL,
    hold_volume NUMERIC(24,4),
    hold_ratio NUMERIC(18,8),
    hold_market_value NUMERIC(24,4),
    hold_volume_change NUMERIC(24,4),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_north_hold_daily_business UNIQUE (stock_code, trade_date, exchange)
);

CREATE TABLE IF NOT EXISTS t_sector_factor_daily (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(80) NOT NULL,
    sector_name VARCHAR(160),
    sector_type VARCHAR(40) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL DEFAULT 'system:daily_close',
    fund_strength NUMERIC(24,6),
    net_inflow_3d NUMERIC(24,6),
    net_inflow_5d NUMERIC(24,6),
    net_inflow_10d NUMERIC(24,6),
    continuous_inflow_days INTEGER,
    rising_stock_count INTEGER,
    limit_up_stock_count INTEGER,
    average_change_pct NUMERIC(18,6),
    volatility_20d NUMERIC(18,6),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_sector_factor_daily_business UNIQUE (sector_code, trade_date)
);

COMMENT ON TABLE t_stock_north_hold_daily IS 'Canonical 层：北向资金每日持股事实。';
COMMENT ON TABLE t_sector_factor_daily IS 'Derived 层：板块/概念/行业日频衍生因子。';

CREATE INDEX IF NOT EXISTS idx_t_stock_north_hold_daily_stock_date ON t_stock_north_hold_daily(stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_sector_factor_daily_type_date ON t_sector_factor_daily(sector_type, trade_date DESC);

DO $$
DECLARE
    spec RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('t_daily_bar', ARRAY['stock_code','trade_date'], 'CASE WHEN source = ''tushare:daily'' THEN 0 WHEN source = ''akshare_qfq'' THEN 1 WHEN source = ''mootdx'' THEN 2 ELSE 9 END, updated_at DESC NULLS LAST, id DESC', 'uq_t_daily_bar_stock_date_source', 'uq_t_daily_bar_stock_date'),
            ('t_stock_daily_basic', ARRAY['stock_code','trade_date'], 'CASE WHEN source = ''tushare:daily_basic'' THEN 0 ELSE 9 END, updated_at DESC NULLS LAST, id DESC', 'uq_t_stock_daily_basic_business', 'uq_t_stock_daily_basic_business'),
            ('t_stock_fund_flow_daily', ARRAY['stock_code','trade_date'], 'CASE WHEN source LIKE ''tushare:%'' THEN 0 WHEN source LIKE ''akshare:%'' THEN 1 ELSE 9 END, updated_at DESC NULLS LAST, id DESC', 'uq_t_stock_fund_flow_daily_stock_date_source', 'uq_t_stock_fund_flow_daily_stock_date'),
            ('t_sector_fund_flow_daily', ARRAY['sector_code','trade_date'], 'CASE WHEN source LIKE ''tushare:%'' THEN 0 WHEN source LIKE ''akshare:%'' THEN 1 ELSE 9 END, updated_at DESC NULLS LAST, id DESC', 'uq_t_sector_fund_flow_daily_sector_date_source', 'uq_t_sector_fund_flow_daily_sector_date'),
            ('t_sector_bar', ARRAY['sector_code','trade_date'], 'CASE WHEN source LIKE ''tushare:%'' THEN 0 WHEN source LIKE ''akshare:%'' THEN 1 ELSE 9 END, id DESC', 'uq_t_sector_bar_sector_date_source', 'uq_t_sector_bar_sector_date'),
            ('t_index_bar', ARRAY['index_code','trade_date'], 'CASE WHEN source LIKE ''tushare:%'' THEN 0 WHEN source LIKE ''akshare:%'' THEN 1 WHEN source LIKE ''mootdx:%'' THEN 2 ELSE 9 END, id DESC', 'uq_t_index_bar_index_date_source', 'uq_t_index_bar_index_date'),
            ('t_lhb_event', ARRAY['stock_code','trade_date','reason'], 'CASE WHEN source LIKE ''tushare:%'' THEN 0 WHEN source LIKE ''akshare:%'' THEN 1 ELSE 9 END, updated_at DESC NULLS LAST, id DESC', 'uq_t_lhb_event_stock_date_reason_source', 'uq_t_lhb_event_stock_date_reason'),
            ('t_limit_event_daily', ARRAY['stock_code','trade_date','event_type'], 'CASE WHEN source LIKE ''tushare:%'' THEN 0 ELSE 9 END, id DESC', 'uq_t_limit_event_daily_business', 'uq_t_limit_event_daily_business')
        ) AS t(table_name, key_columns, order_sql, old_constraint, new_constraint)
    LOOP
        EXECUTE format(
            'WITH ranked AS (
                SELECT id, row_to_json(t)::jsonb AS row_data,
                       concat_ws(''|'', %s) AS business_key,
                       row_number() OVER (PARTITION BY %s ORDER BY %s) AS rn
                FROM %I t
             )
             INSERT INTO t_canonical_source_conflict_backup(source_table, business_key, row_data, reason)
             SELECT %L, business_key, row_data, ''canonical_single_fact_consolidation''
             FROM ranked WHERE rn > 1',
            (SELECT string_agg(format('t.%I::text', col), ', ') FROM unnest(spec.key_columns) AS col),
            (SELECT string_agg(format('%I', col), ', ') FROM unnest(spec.key_columns) AS col),
            spec.order_sql,
            spec.table_name,
            spec.table_name
        );
        EXECUTE format(
            'WITH ranked AS (
                SELECT id, row_number() OVER (PARTITION BY %s ORDER BY %s) AS rn
                FROM %I
             )
             DELETE FROM %I d USING ranked r WHERE d.id = r.id AND r.rn > 1',
            (SELECT string_agg(format('%I', col), ', ') FROM unnest(spec.key_columns) AS col),
            spec.order_sql,
            spec.table_name,
            spec.table_name
        );
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', spec.table_name, spec.old_constraint);
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', spec.table_name, spec.new_constraint);
        EXECUTE format(
            'ALTER TABLE %I ADD CONSTRAINT %I UNIQUE (%s)',
            spec.table_name,
            spec.new_constraint,
            (SELECT string_agg(format('%I', col), ', ') FROM unnest(spec.key_columns) AS col)
        );
    END LOOP;
END $$;

UPDATE t_scheduler_job
SET is_enabled = false,
    is_hidden = true,
    description = '已废弃：日频量化事实统一由 daily_market_close_ingest 沉淀；历史回填后续使用 backfill_* 任务。',
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"deprecated":true,"replaced_by":"daily_market_close_ingest"}'::jsonb,
    updated_at = now()
WHERE job_code = 'sync_tushare_a_share_topic';

UPDATE t_scheduler_job
SET description = '每日全市场收盘数据沉淀：统一沉淀日线、daily basic、分钟线、EOD quote、资金流、涨跌停/停复牌、龙虎榜、核心指数、北向持股、板块行情/资金流和基础因子；不运行策略、市场状态、情绪、LLM 或 Skill。',
    default_payload = COALESCE(default_payload, '{}'::jsonb)
      || '{"sync_stock_moneyflow":true,"sync_stock_limit_status":true,"sync_lhb":true,"sync_index_bars":true,"sync_north_hold":true,"sync_sector_bars":true,"sync_sector_moneyflow":true,"calculate_stock_fund_factors":true,"calculate_sector_factors":true,"fail_on_enrichment_error":false}'::jsonb,
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
      || '{
        "sync_stock_moneyflow":{"label":"同步个股资金流","type":"boolean","default":true,"required":false,"description":"Tushare moneyflow 按交易日批量沉淀到 t_stock_fund_flow_daily。"},
        "sync_stock_limit_status":{"label":"同步涨跌停/停复牌","type":"boolean","default":true,"required":false,"description":"Tushare limit_list_d 与 suspend_d 沉淀到 t_limit_event_daily。"},
        "sync_lhb":{"label":"同步龙虎榜","type":"boolean","default":true,"required":false,"description":"Tushare top_list/top_inst 沉淀龙虎榜事件和席位。"},
        "sync_index_bars":{"label":"同步核心指数日线","type":"boolean","default":true,"required":false,"description":"沉淀上证、深证、创业板、沪深300、中证500、中证1000等核心指数。"},
        "sync_north_hold":{"label":"同步北向持股","type":"boolean","default":true,"required":false,"description":"Tushare hk_hold 沉淀到 t_stock_north_hold_daily。"},
        "sync_sector_bars":{"label":"同步板块日线","type":"boolean","default":true,"required":false,"description":"Tushare ths_daily 沉淀同花顺概念/行业日线。"},
        "sync_sector_moneyflow":{"label":"同步板块资金流","type":"boolean","default":true,"required":false,"description":"Tushare moneyflow_cnt_ths/moneyflow_ind_ths 沉淀板块资金流。"},
        "calculate_stock_fund_factors":{"label":"计算资金因子","type":"boolean","default":true,"required":false,"description":"从 t_stock_fund_flow_daily 写入 t_stock_factor_daily.features。"},
        "calculate_sector_factors":{"label":"计算板块因子","type":"boolean","default":true,"required":false,"description":"从板块行情和资金流生成 t_sector_factor_daily。"},
        "fail_on_enrichment_error":{"label":"增强数据失败即中断","type":"boolean","default":false,"required":false,"description":"关闭时增强块失败只记录 warning，核心行情沉淀继续。"}
      }'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_market_close_ingest';

INSERT INTO t_factor_definition (factor_code, factor_name, factor_group, frequency, source_table, compute_method, is_rebuildable, metadata)
VALUES
    ('main_net_inflow_3d', '近 3 日主力净流入', 'fund_flow', 'daily', 't_stock_fund_flow_daily', '近 3 个可用交易日 main_net_inflow 求和。', TRUE, '{"source":"daily_market_close_ingest"}'::jsonb),
    ('main_net_inflow_5d', '近 5 日主力净流入', 'fund_flow', 'daily', 't_stock_fund_flow_daily', '近 5 个可用交易日 main_net_inflow 求和。', TRUE, '{"source":"daily_market_close_ingest"}'::jsonb),
    ('main_net_inflow_10d', '近 10 日主力净流入', 'fund_flow', 'daily', 't_stock_fund_flow_daily', '近 10 个可用交易日 main_net_inflow 求和。', TRUE, '{"source":"daily_market_close_ingest"}'::jsonb),
    ('sector_fund_strength', '板块资金强度', 'sector', 'daily', 't_sector_factor_daily', '板块资金流和行情事实派生。', TRUE, '{"source":"daily_market_close_ingest"}'::jsonb)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    metadata = t_factor_definition.metadata || EXCLUDED.metadata,
    updated_at = now();
