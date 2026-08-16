-- Daily data assets final convergence: non-destructive prepare phase.
--
-- Safe to run while the existing V2 pipeline is online. This phase creates
-- the official shadow table, typed derived assets and dual-write helpers. It
-- does not rename or drop any production table.

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS t_data_asset_migration_state (
    migration_code VARCHAR(80) PRIMARY KEY,
    status VARCHAR(24) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cutover_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

INSERT INTO t_data_asset_migration_state (migration_code, status, details)
VALUES ('daily_assets_final', 'preparing', '{"revision":"stock_daily_final_r1"}'::jsonb)
ON CONFLICT (migration_code) DO UPDATE
SET status = CASE
        WHEN t_data_asset_migration_state.status IN ('cutover', 'verified')
        THEN t_data_asset_migration_state.status ELSE 'preparing' END,
    details = t_data_asset_migration_state.details || EXCLUDED.details;

CREATE TABLE IF NOT EXISTS t_stock_factor_daily_final_shadow (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    price_basis VARCHAR(20) NOT NULL DEFAULT 'qfq' CHECK (price_basis = 'qfq'),
    price_status VARCHAR(24) NOT NULL DEFAULT 'partial',
    technical_core_status VARCHAR(24) NOT NULL DEFAULT 'partial',
    technical_extended_status VARCHAR(24) NOT NULL DEFAULT 'partial',
    valuation_status VARCHAR(24) NOT NULL DEFAULT 'partial',
    fund_status VARCHAR(24) NOT NULL DEFAULT 'partial',
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    price_source VARCHAR(80), technical_source VARCHAR(80),
    basic_source VARCHAR(80), fund_source VARCHAR(80),
    local_source VARCHAR(80) NOT NULL DEFAULT 'system:stock_daily_factor',
    calculation_revision VARCHAR(80) NOT NULL DEFAULT 'stock_daily_final_r1',
    history_days INTEGER NOT NULL DEFAULT 0,

    open_qfq DOUBLE PRECISION, high_qfq DOUBLE PRECISION,
    low_qfq DOUBLE PRECISION, close_qfq DOUBLE PRECISION,
    pre_close_qfq DOUBLE PRECISION,
    ma5 DOUBLE PRECISION, ma10 DOUBLE PRECISION, ma20 DOUBLE PRECISION,
    ma30 DOUBLE PRECISION, ma60 DOUBLE PRECISION, ma90 DOUBLE PRECISION,
    ma250 DOUBLE PRECISION, ema5 DOUBLE PRECISION, ema10 DOUBLE PRECISION,
    ema20 DOUBLE PRECISION, ema30 DOUBLE PRECISION, ema60 DOUBLE PRECISION,
    ema90 DOUBLE PRECISION, ema250 DOUBLE PRECISION,
    macd DOUBLE PRECISION, macd_dif DOUBLE PRECISION, macd_dea DOUBLE PRECISION,
    kdj_j DOUBLE PRECISION, kdj_k DOUBLE PRECISION, kdj_d DOUBLE PRECISION,
    rsi6 DOUBLE PRECISION, rsi12 DOUBLE PRECISION, rsi14 DOUBLE PRECISION,
    rsi24 DOUBLE PRECISION, boll_upper DOUBLE PRECISION,
    boll_mid DOUBLE PRECISION, boll_lower DOUBLE PRECISION,
    atr DOUBLE PRECISION, bbi DOUBLE PRECISION,
    bias1 DOUBLE PRECISION, bias2 DOUBLE PRECISION, bias3 DOUBLE PRECISION,
    cci DOUBLE PRECISION, vr DOUBLE PRECISION, wr DOUBLE PRECISION,
    wr1 DOUBLE PRECISION, obv DOUBLE PRECISION, mfi DOUBLE PRECISION,
    roc DOUBLE PRECISION, mtm DOUBLE PRECISION, mtmma DOUBLE PRECISION,
    asi DOUBLE PRECISION, asit DOUBLE PRECISION,
    brar_ar DOUBLE PRECISION, brar_br DOUBLE PRECISION, cr DOUBLE PRECISION,
    dfma_dif DOUBLE PRECISION, dfma_difma DOUBLE PRECISION,
    dmi_adx DOUBLE PRECISION, dmi_adxr DOUBLE PRECISION,
    dmi_mdi DOUBLE PRECISION, dmi_pdi DOUBLE PRECISION,
    dpo DOUBLE PRECISION, madpo DOUBLE PRECISION,
    emv DOUBLE PRECISION, maemv DOUBLE PRECISION,
    expma12 DOUBLE PRECISION, expma50 DOUBLE PRECISION,
    keltner_lower DOUBLE PRECISION, keltner_mid DOUBLE PRECISION,
    keltner_upper DOUBLE PRECISION, mass DOUBLE PRECISION,
    ma_mass DOUBLE PRECISION, maroc DOUBLE PRECISION,
    psy DOUBLE PRECISION, psyma DOUBLE PRECISION,
    taq_lower DOUBLE PRECISION, taq_mid DOUBLE PRECISION,
    taq_upper DOUBLE PRECISION, trix DOUBLE PRECISION,
    trma DOUBLE PRECISION, xsii_td1 DOUBLE PRECISION,
    xsii_td2 DOUBLE PRECISION, xsii_td3 DOUBLE PRECISION,
    xsii_td4 DOUBLE PRECISION,
    updays INTEGER, downdays INTEGER, topdays INTEGER, lowdays INTEGER,

    return_1d_pct DOUBLE PRECISION, return_3d_pct DOUBLE PRECISION,
    return_5d_pct DOUBLE PRECISION, return_10d_pct DOUBLE PRECISION,
    return_20d_pct DOUBLE PRECISION, return_60d_pct DOUBLE PRECISION,
    return_120d_pct DOUBLE PRECISION, return_250d_pct DOUBLE PRECISION,
    amplitude_1d_pct DOUBLE PRECISION, open_gap_pct DOUBLE PRECISION,
    close_position_ratio DOUBLE PRECISION,
    volume_ratio_5d DOUBLE PRECISION, volume_ratio_10d DOUBLE PRECISION,
    volume_ratio_20d DOUBLE PRECISION, amount_ratio_5d DOUBLE PRECISION,
    amount_ratio_10d DOUBLE PRECISION, amount_ratio_20d DOUBLE PRECISION,
    average_amount_5d_yuan DOUBLE PRECISION,
    average_amount_20d_yuan DOUBLE PRECISION,
    average_amount_60d_yuan DOUBLE PRECISION,
    volatility_5d DOUBLE PRECISION, volatility_10d DOUBLE PRECISION,
    volatility_20d DOUBLE PRECISION, volatility_60d DOUBLE PRECISION,
    high_20d DOUBLE PRECISION, low_20d DOUBLE PRECISION,
    high_60d DOUBLE PRECISION, low_60d DOUBLE PRECISION,
    high_120d DOUBLE PRECISION, low_120d DOUBLE PRECISION,
    high_250d DOUBLE PRECISION, low_250d DOUBLE PRECISION,
    distance_high_20d_ratio DOUBLE PRECISION,
    distance_low_20d_ratio DOUBLE PRECISION,
    distance_high_60d_ratio DOUBLE PRECISION,
    distance_low_60d_ratio DOUBLE PRECISION,
    drawdown_20d_pct DOUBLE PRECISION, drawdown_60d_pct DOUBLE PRECISION,
    drawdown_120d_pct DOUBLE PRECISION, drawdown_250d_pct DOUBLE PRECISION,
    relative_csi300_5d_pct DOUBLE PRECISION,
    relative_csi300_20d_pct DOUBLE PRECISION,
    relative_csi300_60d_pct DOUBLE PRECISION,
    return_percentile_1d DOUBLE PRECISION,
    return_percentile_5d DOUBLE PRECISION,
    return_percentile_20d DOUBLE PRECISION,
    amount_percentile DOUBLE PRECISION, turnover_percentile DOUBLE PRECISION,
    main_net_inflow_percentile DOUBLE PRECISION,

    turnover_rate_pct DOUBLE PRECISION, turnover_rate_free_pct DOUBLE PRECISION,
    pe DOUBLE PRECISION, pe_ttm DOUBLE PRECISION, pb DOUBLE PRECISION,
    ps_ttm DOUBLE PRECISION, dividend_yield_pct DOUBLE PRECISION,
    total_share_shares DOUBLE PRECISION, float_share_shares DOUBLE PRECISION,
    free_share_shares DOUBLE PRECISION,
    total_market_value_yuan DOUBLE PRECISION,
    circulating_market_value_yuan DOUBLE PRECISION,
    main_net_inflow_yuan DOUBLE PRECISION,
    provider_main_net_ratio DOUBLE PRECISION,
    main_net_amount_ratio DOUBLE PRECISION,
    big_order_net_inflow_yuan DOUBLE PRECISION,
    big_order_net_amount_ratio DOUBLE PRECISION,
    super_large_net_inflow_yuan DOUBLE PRECISION,
    super_large_net_amount_ratio DOUBLE PRECISION,
    main_net_inflow_3d_yuan DOUBLE PRECISION,
    main_net_inflow_5d_yuan DOUBLE PRECISION,
    main_net_inflow_10d_yuan DOUBLE PRECISION,
    main_net_inflow_20d_yuan DOUBLE PRECISION,
    continuous_main_inflow_days INTEGER,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_factor_daily_final_shadow_business UNIQUE (stock_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_final_shadow_date_stock
    ON t_stock_factor_daily_final_shadow (trade_date, stock_code);
CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_final_shadow_stock_date
    ON t_stock_factor_daily_final_shadow (stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_final_shadow_core
    ON t_stock_factor_daily_final_shadow (trade_date, stock_code)
    WHERE price_status = 'ready' AND technical_core_status = 'ready';

CREATE TABLE IF NOT EXISTS t_sector_leader_daily (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(80) NOT NULL,
    trade_date DATE NOT NULL,
    leader_rank INTEGER NOT NULL CHECK (leader_rank BETWEEN 1 AND 5),
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(120),
    change_pct DOUBLE PRECISION,
    amount_yuan DOUBLE PRECISION,
    limit_board_count INTEGER,
    leader_score DOUBLE PRECISION,
    source VARCHAR(80) NOT NULL DEFAULT 'system:sector_factor',
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_sector_leader_daily_business UNIQUE (sector_code, trade_date, leader_rank)
);
CREATE INDEX IF NOT EXISTS idx_t_sector_leader_daily_date_sector
    ON t_sector_leader_daily (trade_date DESC, sector_code);

CREATE TABLE IF NOT EXISTS t_market_summary_daily (
    trade_date DATE PRIMARY KEY,
    eligible_count INTEGER NOT NULL DEFAULT 0,
    daily_bar_count INTEGER NOT NULL DEFAULT 0,
    daily_basic_count INTEGER NOT NULL DEFAULT 0,
    fund_flow_count INTEGER NOT NULL DEFAULT 0,
    factor_count INTEGER NOT NULL DEFAULT 0,
    up_count INTEGER NOT NULL DEFAULT 0,
    down_count INTEGER NOT NULL DEFAULT 0,
    flat_count INTEGER NOT NULL DEFAULT 0,
    average_change_pct DOUBLE PRECISION, median_change_pct DOUBLE PRECISION,
    up_1pct_count INTEGER, down_1pct_count INTEGER,
    up_3pct_count INTEGER, down_3pct_count INTEGER,
    up_5pct_count INTEGER, down_5pct_count INTEGER,
    up_7pct_count INTEGER, down_7pct_count INTEGER,
    total_amount_yuan DOUBLE PRECISION,
    amount_ratio_5d DOUBLE PRECISION, amount_ratio_20d DOUBLE PRECISION,
    average_turnover_pct DOUBLE PRECISION, median_turnover_pct DOUBLE PRECISION,
    average_volatility_20d_pct DOUBLE PRECISION,
    main_net_inflow_yuan DOUBLE PRECISION, main_net_inflow_ratio DOUBLE PRECISION,
    above_ma5_ratio DOUBLE PRECISION, above_ma20_ratio DOUBLE PRECISION,
    above_ma60_ratio DOUBLE PRECISION, above_ma250_ratio DOUBLE PRECISION,
    new_high_20d_count INTEGER, new_low_20d_count INTEGER,
    new_high_60d_count INTEGER, new_low_60d_count INTEGER,
    new_high_250d_count INTEGER, new_low_250d_count INTEGER,
    limit_up_count INTEGER, limit_down_count INTEGER, limit_break_count INTEGER,
    one_word_limit_up_count INTEGER, natural_limit_up_count INTEGER,
    highest_board_count INTEGER, promotion_rate DOUBLE PRECISION,
    core_index_ready_count INTEGER NOT NULL DEFAULT 0,
    core_index_rising_count INTEGER,
    core_index_average_return_1d_pct DOUBLE PRECISION,
    core_index_average_amplitude_pct DOUBLE PRECISION,
    north_flow_yuan DOUBLE PRECISION, north_flow_disclosure_date DATE,
    margin_balance_yuan DOUBLE PRECISION, margin_disclosure_date DATE,
    core_ready BOOLEAN NOT NULL DEFAULT false,
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    calculation_revision VARCHAR(80) NOT NULL DEFAULT 'market_summary_final_r1',
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE t_market_summary_daily
    ADD COLUMN IF NOT EXISTS average_volatility_20d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS core_index_average_return_1d_pct DOUBLE PRECISION;

-- Add the final, unit-explicit columns alongside legacy columns. Existing
-- writers keep working until cut-over; the trigger below fills these columns.
ALTER TABLE t_stock_daily_basic
    ADD COLUMN IF NOT EXISTS turnover_rate_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS turnover_rate_free_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS provider_volume_ratio DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dividend_yield_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dividend_yield_ttm_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS total_share_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS float_share_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS free_share_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS total_market_value_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS circulating_market_value_yuan DOUBLE PRECISION;

ALTER TABLE t_stock_fund_flow_daily
    ADD COLUMN IF NOT EXISTS main_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS big_order_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS super_large_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS medium_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS small_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS small_buy_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS small_sell_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS medium_buy_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS medium_sell_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS large_buy_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS large_sell_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS super_large_buy_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS super_large_sell_amount_yuan DOUBLE PRECISION;

ALTER TABLE t_sector_fund_flow_daily
    ADD COLUMN IF NOT EXISTS main_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS net_buy_amount_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS net_sell_amount_yuan DOUBLE PRECISION;

ALTER TABLE t_market_north_flow_daily
    ADD COLUMN IF NOT EXISTS hgt_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sgt_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS north_money_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ggt_ss_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ggt_sz_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS south_money_yuan DOUBLE PRECISION;

ALTER TABLE t_stock_factor_minute
    ADD COLUMN IF NOT EXISTS return_1m_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_5m_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_15m_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma5 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma10 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma20 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS volume_ratio_20m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS intraday_position_ratio DOUBLE PRECISION;

ALTER TABLE t_index_daily_basic
    ADD COLUMN IF NOT EXISTS total_market_value_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS float_market_value_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS total_share_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS float_share_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS free_share_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS turnover_rate_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS turnover_rate_free_pct DOUBLE PRECISION;

ALTER TABLE t_margin_summary_daily
    ADD COLUMN IF NOT EXISTS financing_balance_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS financing_buy_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS financing_repay_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS securities_lending_balance_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS securities_lending_sell_shares DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS margin_total_balance_yuan DOUBLE PRECISION;

-- The final derived tables are extended in place because they are small and
-- fully rebuildable from narrow facts.
ALTER TABLE t_sector_factor_daily
    ADD COLUMN IF NOT EXISTS ma5 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma10 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma20 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma60 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_1d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_5d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_20d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS drawdown_20d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS main_net_inflow_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS main_net_inflow_3d_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS main_net_inflow_5d_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS main_net_inflow_10d_yuan DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fund_rank INTEGER,
    ADD COLUMN IF NOT EXISTS component_count INTEGER,
    ADD COLUMN IF NOT EXISTS component_coverage_ratio DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS falling_stock_count INTEGER,
    ADD COLUMN IF NOT EXISTS flat_stock_count INTEGER,
    ADD COLUMN IF NOT EXISTS limit_down_stock_count INTEGER,
    ADD COLUMN IF NOT EXISTS limit_break_stock_count INTEGER,
    ADD COLUMN IF NOT EXISTS one_word_limit_up_count INTEGER,
    ADD COLUMN IF NOT EXISTS natural_limit_up_count INTEGER,
    ADD COLUMN IF NOT EXISTS median_change_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS above_ma20_ratio DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS above_ma60_ratio DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS new_high_20d_count INTEGER,
    ADD COLUMN IF NOT EXISTS new_low_20d_count INTEGER,
    ADD COLUMN IF NOT EXISTS new_high_60d_count INTEGER,
    ADD COLUMN IF NOT EXISTS new_low_60d_count INTEGER,
    ADD COLUMN IF NOT EXISTS heat_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS heat_rank INTEGER,
    ADD COLUMN IF NOT EXISTS persistence_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS leader_strength_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS calculation_revision VARCHAR(80) NOT NULL DEFAULT 'sector_daily_final_r1',
    ADD COLUMN IF NOT EXISTS quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

ALTER TABLE t_index_factor_daily
    ADD COLUMN IF NOT EXISTS ma120 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ma250 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema5 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema10 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema20 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema30 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema60 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_1d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_5d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_10d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_20d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_60d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amplitude_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS volume_ratio_5d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amount_ratio_5d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS volatility_60d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS high_20d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS low_20d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS high_60d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS low_60d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS drawdown_20d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS drawdown_60d_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS trend_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS turnover_rate_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pe_ttm DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pb DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS calculation_revision VARCHAR(80) NOT NULL DEFAULT 'index_daily_final_r1',
    ADD COLUMN IF NOT EXISTS quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

CREATE OR REPLACE FUNCTION fn_daily_assets_final_fact_dual_write()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 't_stock_daily_basic' THEN
        NEW.turnover_rate_pct := coalesce(NEW.turnover_rate_pct, NEW.turnover_rate);
        NEW.turnover_rate_free_pct := coalesce(NEW.turnover_rate_free_pct, NEW.turnover_rate_f);
        NEW.provider_volume_ratio := coalesce(NEW.provider_volume_ratio, NEW.volume_ratio);
        NEW.dividend_yield_pct := coalesce(NEW.dividend_yield_pct, NEW.dv_ratio);
        NEW.dividend_yield_ttm_pct := coalesce(NEW.dividend_yield_ttm_pct, NEW.dv_ttm);
        NEW.total_share_shares := coalesce(NEW.total_share_shares, NEW.total_share * 10000.0);
        NEW.float_share_shares := coalesce(NEW.float_share_shares, NEW.float_share * 10000.0);
        NEW.free_share_shares := coalesce(NEW.free_share_shares, NEW.free_share * 10000.0);
        NEW.total_market_value_yuan := coalesce(NEW.total_market_value_yuan, NEW.total_mv * 10000.0);
        NEW.circulating_market_value_yuan := coalesce(NEW.circulating_market_value_yuan, NEW.circ_mv * 10000.0);
    ELSIF TG_TABLE_NAME = 't_stock_fund_flow_daily' THEN
        NEW.main_net_inflow_yuan := coalesce(NEW.main_net_inflow_yuan, NEW.main_net_inflow);
        NEW.big_order_net_inflow_yuan := coalesce(NEW.big_order_net_inflow_yuan, NEW.big_order_net_inflow);
        NEW.super_large_net_inflow_yuan := coalesce(NEW.super_large_net_inflow_yuan, NEW.super_large_net_inflow);
        NEW.medium_net_inflow_yuan := coalesce(NEW.medium_net_inflow_yuan, NEW.medium_net_inflow);
        NEW.small_net_inflow_yuan := coalesce(NEW.small_net_inflow_yuan, NEW.small_net_inflow);
        NEW.small_buy_amount_yuan := coalesce(NEW.small_buy_amount_yuan, NEW.small_buy_amount);
        NEW.small_sell_amount_yuan := coalesce(NEW.small_sell_amount_yuan, NEW.small_sell_amount);
        NEW.medium_buy_amount_yuan := coalesce(NEW.medium_buy_amount_yuan, NEW.medium_buy_amount);
        NEW.medium_sell_amount_yuan := coalesce(NEW.medium_sell_amount_yuan, NEW.medium_sell_amount);
        NEW.large_buy_amount_yuan := coalesce(NEW.large_buy_amount_yuan, NEW.large_buy_amount);
        NEW.large_sell_amount_yuan := coalesce(NEW.large_sell_amount_yuan, NEW.large_sell_amount);
        NEW.super_large_buy_amount_yuan := coalesce(NEW.super_large_buy_amount_yuan, NEW.super_large_buy_amount);
        NEW.super_large_sell_amount_yuan := coalesce(NEW.super_large_sell_amount_yuan, NEW.super_large_sell_amount);
    ELSIF TG_TABLE_NAME = 't_sector_fund_flow_daily' THEN
        IF NEW.source IN ('tushare:moneyflow_ind_ths', 'tushare:moneyflow_cnt_ths') THEN
            NEW.main_net_inflow_yuan := coalesce(NEW.main_net_inflow_yuan, NEW.main_net_inflow * 10000.0);
            NEW.net_buy_amount_yuan := coalesce(NEW.net_buy_amount_yuan, NEW.net_buy_amount * 10000.0);
            NEW.net_sell_amount_yuan := coalesce(NEW.net_sell_amount_yuan, NEW.net_sell_amount * 10000.0);
        ELSE
            NEW.main_net_inflow_yuan := coalesce(NEW.main_net_inflow_yuan, NEW.main_net_inflow);
            NEW.net_buy_amount_yuan := coalesce(NEW.net_buy_amount_yuan, NEW.net_buy_amount);
            NEW.net_sell_amount_yuan := coalesce(NEW.net_sell_amount_yuan, NEW.net_sell_amount);
        END IF;
    ELSIF TG_TABLE_NAME = 't_market_north_flow_daily' THEN
        NEW.hgt_yuan := coalesce(NEW.hgt_yuan, NEW.hgt * 1000000.0);
        NEW.sgt_yuan := coalesce(NEW.sgt_yuan, NEW.sgt * 1000000.0);
        NEW.north_money_yuan := coalesce(NEW.north_money_yuan, NEW.north_money * 1000000.0);
        NEW.ggt_ss_yuan := coalesce(NEW.ggt_ss_yuan, NEW.ggt_ss * 1000000.0);
        NEW.ggt_sz_yuan := coalesce(NEW.ggt_sz_yuan, NEW.ggt_sz * 1000000.0);
        NEW.south_money_yuan := coalesce(NEW.south_money_yuan, NEW.south_money * 1000000.0);
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_daily_assets_final_basic_dual_write ON t_stock_daily_basic;
CREATE TRIGGER trg_daily_assets_final_basic_dual_write
BEFORE INSERT OR UPDATE ON t_stock_daily_basic FOR EACH ROW
EXECUTE FUNCTION fn_daily_assets_final_fact_dual_write();
DROP TRIGGER IF EXISTS trg_daily_assets_final_fund_dual_write ON t_stock_fund_flow_daily;
CREATE TRIGGER trg_daily_assets_final_fund_dual_write
BEFORE INSERT OR UPDATE ON t_stock_fund_flow_daily FOR EACH ROW
EXECUTE FUNCTION fn_daily_assets_final_fact_dual_write();
DROP TRIGGER IF EXISTS trg_daily_assets_final_sector_fund_dual_write ON t_sector_fund_flow_daily;
CREATE TRIGGER trg_daily_assets_final_sector_fund_dual_write
BEFORE INSERT OR UPDATE ON t_sector_fund_flow_daily FOR EACH ROW
EXECUTE FUNCTION fn_daily_assets_final_fact_dual_write();
DROP TRIGGER IF EXISTS trg_daily_assets_final_north_dual_write ON t_market_north_flow_daily;
CREATE TRIGGER trg_daily_assets_final_north_dual_write
BEFORE INSERT OR UPDATE ON t_market_north_flow_daily FOR EACH ROW
EXECUTE FUNCTION fn_daily_assets_final_fact_dual_write();

COMMIT;

-- Read-only preflight. Confirm the database tablespace has enough external
-- free space before starting the 20-trading-day backfill in migration 78.
SELECT current_database() AS database_name,
       pg_size_pretty(pg_database_size(current_database())) AS database_size,
       pg_size_pretty(pg_total_relation_size('t_stock_factor_daily_v2')) AS v2_size,
       pg_size_pretty(pg_total_relation_size('t_stock_technical_factor_daily')) AS professional_json_size;
