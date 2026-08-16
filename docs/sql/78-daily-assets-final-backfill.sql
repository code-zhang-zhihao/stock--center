-- Daily data assets final convergence: resumable historical backfill.
-- Requires 77-daily-assets-final-prepare.sql.
--
-- psql executes one statement per 20 open trading days. Every window commits
-- independently, so a failed run can be restarted without rolling back prior
-- windows or issuing one unbounded multi-million-row transaction.

\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION fn_backfill_daily_assets_final_window(
    p_start_date DATE,
    p_end_date DATE
) RETURNS TABLE (
    factor_rows BIGINT,
    professional_rows BIGINT,
    basic_rows BIGINT,
    fund_rows BIGINT,
    sector_fund_rows BIGINT,
    north_flow_rows BIGINT
) LANGUAGE plpgsql AS $$
DECLARE
    v_factor BIGINT := 0;
    v_professional BIGINT := 0;
    v_basic BIGINT := 0;
    v_fund BIGINT := 0;
    v_sector_fund BIGINT := 0;
    v_north BIGINT := 0;
BEGIN
    UPDATE t_stock_daily_basic
    SET turnover_rate_pct = turnover_rate,
        turnover_rate_free_pct = turnover_rate_f,
        provider_volume_ratio = volume_ratio,
        dividend_yield_pct = dv_ratio,
        dividend_yield_ttm_pct = dv_ttm,
        total_share_shares = total_share * 10000.0,
        float_share_shares = float_share * 10000.0,
        free_share_shares = free_share * 10000.0,
        total_market_value_yuan = total_mv * 10000.0,
        circulating_market_value_yuan = circ_mv * 10000.0
    WHERE trade_date BETWEEN p_start_date AND p_end_date
      AND (total_share_shares IS NULL OR total_market_value_yuan IS NULL);
    GET DIAGNOSTICS v_basic = ROW_COUNT;

    UPDATE t_stock_fund_flow_daily
    SET main_net_inflow_yuan = main_net_inflow,
        big_order_net_inflow_yuan = big_order_net_inflow,
        super_large_net_inflow_yuan = super_large_net_inflow,
        medium_net_inflow_yuan = medium_net_inflow,
        small_net_inflow_yuan = small_net_inflow,
        small_buy_amount_yuan = small_buy_amount,
        small_sell_amount_yuan = small_sell_amount,
        medium_buy_amount_yuan = medium_buy_amount,
        medium_sell_amount_yuan = medium_sell_amount,
        large_buy_amount_yuan = large_buy_amount,
        large_sell_amount_yuan = large_sell_amount,
        super_large_buy_amount_yuan = super_large_buy_amount,
        super_large_sell_amount_yuan = super_large_sell_amount
    WHERE trade_date BETWEEN p_start_date AND p_end_date
      AND main_net_inflow_yuan IS NULL;
    GET DIAGNOSTICS v_fund = ROW_COUNT;

    -- Existing canonical rows used 万元->元; the two THS sector money-flow
    -- APIs are actually 亿元. Multiplying the old normalized value by 10,000
    -- repairs that historical error without changing unrelated sources.
    UPDATE t_sector_fund_flow_daily
    SET main_net_inflow_yuan = CASE WHEN source IN ('tushare:moneyflow_ind_ths', 'tushare:moneyflow_cnt_ths')
            THEN main_net_inflow * 10000.0 ELSE main_net_inflow END,
        net_buy_amount_yuan = CASE WHEN source IN ('tushare:moneyflow_ind_ths', 'tushare:moneyflow_cnt_ths')
            THEN net_buy_amount * 10000.0 ELSE net_buy_amount END,
        net_sell_amount_yuan = CASE WHEN source IN ('tushare:moneyflow_ind_ths', 'tushare:moneyflow_cnt_ths')
            THEN net_sell_amount * 10000.0 ELSE net_sell_amount END
    WHERE trade_date BETWEEN p_start_date AND p_end_date
      AND main_net_inflow_yuan IS NULL;
    GET DIAGNOSTICS v_sector_fund = ROW_COUNT;

    UPDATE t_market_north_flow_daily
    SET hgt_yuan = hgt * 1000000.0,
        sgt_yuan = sgt * 1000000.0,
        north_money_yuan = north_money * 1000000.0,
        ggt_ss_yuan = ggt_ss * 1000000.0,
        ggt_sz_yuan = ggt_sz * 1000000.0,
        south_money_yuan = south_money * 1000000.0
    WHERE trade_date BETWEEN p_start_date AND p_end_date
      AND north_money_yuan IS NULL;
    GET DIAGNOSTICS v_north = ROW_COUNT;

    UPDATE t_index_daily_basic
    SET total_market_value_yuan = total_mv,
        float_market_value_yuan = float_mv,
        total_share_shares = total_share,
        float_share_shares = float_share,
        free_share_shares = free_share,
        turnover_rate_pct = turnover_rate,
        turnover_rate_free_pct = turnover_rate_f
    WHERE trade_date BETWEEN p_start_date AND p_end_date
      AND total_market_value_yuan IS NULL;

    UPDATE t_margin_summary_daily
    SET financing_balance_yuan = rzye,
        financing_buy_yuan = rz_mre,
        financing_repay_yuan = rzche,
        securities_lending_balance_yuan = rqye,
        securities_lending_sell_shares = rq_mcl,
        margin_total_balance_yuan = rzrqye
    WHERE trade_date BETWEEN p_start_date AND p_end_date
      AND margin_total_balance_yuan IS NULL;

    INSERT INTO t_stock_factor_daily_final_shadow (
        stock_code, trade_date, price_basis, price_status,
        technical_core_status, technical_extended_status,
        valuation_status, fund_status, quality_flags,
        price_source, technical_source, basic_source, fund_source, local_source,
        calculation_revision, history_days,
        open_qfq, high_qfq, low_qfq, close_qfq, pre_close_qfq,
        ma5, ma10, ma20, ma30, ma60, ma90, ma250,
        ema5, ema10, ema20, ema30, ema60,
        macd, macd_dif, macd_dea, kdj_j, kdj_k, kdj_d,
        rsi6, rsi12, rsi14, rsi24, boll_upper, boll_mid, boll_lower,
        atr, cci, vr, wr, wr1, bias1, bias2, bias3, obv, mfi, roc, mtm,
        return_1d_pct, return_3d_pct, return_5d_pct,
        return_10d_pct, return_20d_pct, amplitude_1d_pct,
        volume_ratio_5d, amount_ratio_5d, volatility_20d,
        close_position_ratio, high_20d, low_20d, high_60d, low_60d,
        drawdown_20d_pct, drawdown_60d_pct,
        turnover_rate_pct, circulating_market_value_yuan, total_market_value_yuan,
        main_net_inflow_yuan, provider_main_net_ratio, main_net_amount_ratio,
        big_order_net_inflow_yuan, big_order_net_amount_ratio,
        super_large_net_inflow_yuan, super_large_net_amount_ratio,
        main_net_inflow_3d_yuan, main_net_inflow_5d_yuan,
        main_net_inflow_10d_yuan, continuous_main_inflow_days,
        main_net_inflow_percentile, created_at, updated_at, calculated_at
    )
    SELECT
        v.stock_code, v.trade_date, 'qfq',
        CASE WHEN v.close_qfq IS NOT NULL THEN 'ready' ELSE 'partial' END,
        'partial', 'partial',
        CASE WHEN b.id IS NOT NULL THEN 'ready' ELSE 'missing' END,
        CASE WHEN f.id IS NOT NULL THEN 'ready' ELSE 'missing' END,
        ARRAY(SELECT jsonb_array_elements_text(coalesce(v.missing_factors, '[]'::jsonb))),
        coalesce(v.source_map ->> 'technical', v.source_map ->> 'adjust_factor'),
        v.technical_source, b.source, f.source, v.local_source,
        'stock_daily_final_migrated', v.history_days,
        v.open_qfq, v.high_qfq, v.low_qfq, v.close_qfq, v.pre_close_qfq,
        v.ma5, v.ma10, v.ma20, v.ma30, v.ma60, v.ma90, v.ma250,
        v.ema5, v.ema10, v.ema20, v.ema30, v.ema60,
        v.macd, v.macd_dif, v.macd_dea, v.kdj_j, v.kdj_k, v.kdj_d,
        v.rsi6, v.rsi12, v.rsi14, v.rsi24,
        v.boll_upper, v.boll_mid, v.boll_lower,
        v.atr, v.cci, v.vr, v.wr, v.wr1,
        v.bias1, v.bias2, v.bias3, v.obv, v.mfi, v.roc, v.mtm,
        v.return_1d, v.return_3d, v.return_5d, v.return_10d, v.return_20d,
        v.amplitude_1d, v.volume_ratio_5d, v.amount_ratio_5d,
        v.volatility_20d, v.close_position_1d,
        v.high_20d, v.low_20d, v.high_60d, v.low_60d,
        v.drawdown_20d, v.drawdown_60d,
        b.turnover_rate_pct, b.circulating_market_value_yuan, b.total_market_value_yuan,
        f.main_net_inflow_yuan, f.main_net_ratio,
        f.main_net_inflow_yuan / nullif(d.amount_yuan, 0),
        f.big_order_net_inflow_yuan,
        f.big_order_net_inflow_yuan / nullif(d.amount_yuan, 0),
        f.super_large_net_inflow_yuan,
        f.super_large_net_inflow_yuan / nullif(d.amount_yuan, 0),
        v.main_net_inflow_3d, v.main_net_inflow_5d, v.main_net_inflow_10d,
        v.continuous_main_inflow_days, v.fund_strength_percentile,
        v.created_at, v.updated_at, now()
    FROM t_stock_factor_daily_v2 v
    LEFT JOIN t_stock_daily_basic b
      ON b.stock_code = v.stock_code AND b.trade_date = v.trade_date
    LEFT JOIN t_stock_fund_flow_daily f
      ON f.stock_code = v.stock_code AND f.trade_date = v.trade_date
    LEFT JOIN t_daily_bar d
      ON d.stock_code = v.stock_code AND d.trade_date = v.trade_date
    WHERE v.trade_date BETWEEN p_start_date AND p_end_date
      AND v.factor_set_version = 'stock_daily_v2'
    ON CONFLICT (stock_code, trade_date) DO UPDATE SET
        price_status = EXCLUDED.price_status,
        valuation_status = EXCLUDED.valuation_status,
        fund_status = EXCLUDED.fund_status,
        quality_flags = EXCLUDED.quality_flags,
        price_source = EXCLUDED.price_source,
        basic_source = EXCLUDED.basic_source,
        fund_source = EXCLUDED.fund_source,
        local_source = EXCLUDED.local_source,
        history_days = EXCLUDED.history_days,
        open_qfq = EXCLUDED.open_qfq, high_qfq = EXCLUDED.high_qfq,
        low_qfq = EXCLUDED.low_qfq, close_qfq = EXCLUDED.close_qfq,
        pre_close_qfq = EXCLUDED.pre_close_qfq,
        ma5 = coalesce(t_stock_factor_daily_final_shadow.ma5, EXCLUDED.ma5),
        ma10 = coalesce(t_stock_factor_daily_final_shadow.ma10, EXCLUDED.ma10),
        ma20 = coalesce(t_stock_factor_daily_final_shadow.ma20, EXCLUDED.ma20),
        ma30 = coalesce(t_stock_factor_daily_final_shadow.ma30, EXCLUDED.ma30),
        ma60 = coalesce(t_stock_factor_daily_final_shadow.ma60, EXCLUDED.ma60),
        ma90 = coalesce(t_stock_factor_daily_final_shadow.ma90, EXCLUDED.ma90),
        ma250 = coalesce(t_stock_factor_daily_final_shadow.ma250, EXCLUDED.ma250),
        rsi14 = EXCLUDED.rsi14,
        return_1d_pct = EXCLUDED.return_1d_pct,
        return_3d_pct = EXCLUDED.return_3d_pct,
        return_5d_pct = EXCLUDED.return_5d_pct,
        return_10d_pct = EXCLUDED.return_10d_pct,
        return_20d_pct = EXCLUDED.return_20d_pct,
        amplitude_1d_pct = EXCLUDED.amplitude_1d_pct,
        volume_ratio_5d = EXCLUDED.volume_ratio_5d,
        amount_ratio_5d = EXCLUDED.amount_ratio_5d,
        volatility_20d = EXCLUDED.volatility_20d,
        close_position_ratio = EXCLUDED.close_position_ratio,
        turnover_rate_pct = EXCLUDED.turnover_rate_pct,
        circulating_market_value_yuan = EXCLUDED.circulating_market_value_yuan,
        total_market_value_yuan = EXCLUDED.total_market_value_yuan,
        main_net_inflow_yuan = EXCLUDED.main_net_inflow_yuan,
        provider_main_net_ratio = EXCLUDED.provider_main_net_ratio,
        main_net_amount_ratio = EXCLUDED.main_net_amount_ratio,
        updated_at = now(), calculated_at = now();
    GET DIAGNOSTICS v_factor = ROW_COUNT;

    UPDATE t_stock_factor_daily_final_shadow target
    SET technical_source = technical.source,
        price_source = technical.source,
        open_qfq = coalesce(nullif(technical.factors ->> 'open_qfq', '')::double precision, target.open_qfq),
        high_qfq = coalesce(nullif(technical.factors ->> 'high_qfq', '')::double precision, target.high_qfq),
        low_qfq = coalesce(nullif(technical.factors ->> 'low_qfq', '')::double precision, target.low_qfq),
        close_qfq = coalesce(nullif(technical.factors ->> 'close_qfq', '')::double precision, target.close_qfq),
        ma5 = coalesce(nullif(technical.factors ->> 'ma_qfq_5', '')::double precision, target.ma5),
        ma10 = coalesce(nullif(technical.factors ->> 'ma_qfq_10', '')::double precision, target.ma10),
        ma20 = coalesce(nullif(technical.factors ->> 'ma_qfq_20', '')::double precision, target.ma20),
        ma30 = coalesce(nullif(technical.factors ->> 'ma_qfq_30', '')::double precision, target.ma30),
        ma60 = coalesce(nullif(technical.factors ->> 'ma_qfq_60', '')::double precision, target.ma60),
        ma90 = coalesce(nullif(technical.factors ->> 'ma_qfq_90', '')::double precision, target.ma90),
        ma250 = coalesce(nullif(technical.factors ->> 'ma_qfq_250', '')::double precision, target.ma250),
        ema5 = coalesce(nullif(technical.factors ->> 'ema_qfq_5', '')::double precision, target.ema5),
        ema10 = coalesce(nullif(technical.factors ->> 'ema_qfq_10', '')::double precision, target.ema10),
        ema20 = coalesce(nullif(technical.factors ->> 'ema_qfq_20', '')::double precision, target.ema20),
        ema30 = coalesce(nullif(technical.factors ->> 'ema_qfq_30', '')::double precision, target.ema30),
        ema60 = coalesce(nullif(technical.factors ->> 'ema_qfq_60', '')::double precision, target.ema60),
        ema90 = nullif(technical.factors ->> 'ema_qfq_90', '')::double precision,
        ema250 = nullif(technical.factors ->> 'ema_qfq_250', '')::double precision,
        macd = coalesce(nullif(technical.factors ->> 'macd_qfq', '')::double precision, target.macd),
        macd_dif = coalesce(nullif(technical.factors ->> 'macd_dif_qfq', '')::double precision, target.macd_dif),
        macd_dea = coalesce(nullif(technical.factors ->> 'macd_dea_qfq', '')::double precision, target.macd_dea),
        kdj_j = coalesce(nullif(technical.factors ->> 'kdj_qfq', '')::double precision, target.kdj_j),
        kdj_k = coalesce(nullif(technical.factors ->> 'kdj_k_qfq', '')::double precision, target.kdj_k),
        kdj_d = coalesce(nullif(technical.factors ->> 'kdj_d_qfq', '')::double precision, target.kdj_d),
        rsi6 = coalesce(nullif(technical.factors ->> 'rsi_qfq_6', '')::double precision, target.rsi6),
        rsi12 = coalesce(nullif(technical.factors ->> 'rsi_qfq_12', '')::double precision, target.rsi12),
        rsi24 = coalesce(nullif(technical.factors ->> 'rsi_qfq_24', '')::double precision, target.rsi24),
        boll_upper = coalesce(nullif(technical.factors ->> 'boll_upper_qfq', '')::double precision, target.boll_upper),
        boll_mid = coalesce(nullif(technical.factors ->> 'boll_mid_qfq', '')::double precision, target.boll_mid),
        boll_lower = coalesce(nullif(technical.factors ->> 'boll_lower_qfq', '')::double precision, target.boll_lower),
        atr = coalesce(nullif(technical.factors ->> 'atr_qfq', '')::double precision, target.atr),
        bbi = nullif(technical.factors ->> 'bbi_qfq', '')::double precision,
        bias1 = coalesce(nullif(technical.factors ->> 'bias1_qfq', '')::double precision, target.bias1),
        bias2 = coalesce(nullif(technical.factors ->> 'bias2_qfq', '')::double precision, target.bias2),
        bias3 = coalesce(nullif(technical.factors ->> 'bias3_qfq', '')::double precision, target.bias3),
        cci = coalesce(nullif(technical.factors ->> 'cci_qfq', '')::double precision, target.cci),
        vr = coalesce(nullif(technical.factors ->> 'vr_qfq', '')::double precision, target.vr),
        wr = coalesce(nullif(technical.factors ->> 'wr_qfq', '')::double precision, target.wr),
        wr1 = coalesce(nullif(technical.factors ->> 'wr1_qfq', '')::double precision, target.wr1),
        obv = coalesce(nullif(technical.factors ->> 'obv_qfq', '')::double precision, target.obv),
        mfi = coalesce(nullif(technical.factors ->> 'mfi_qfq', '')::double precision, target.mfi),
        roc = coalesce(nullif(technical.factors ->> 'roc_qfq', '')::double precision, target.roc),
        mtm = coalesce(nullif(technical.factors ->> 'mtm_qfq', '')::double precision, target.mtm),
        mtmma = nullif(technical.factors ->> 'mtmma_qfq', '')::double precision,
        asi = nullif(technical.factors ->> 'asi_qfq', '')::double precision,
        asit = nullif(technical.factors ->> 'asit_qfq', '')::double precision,
        brar_ar = nullif(technical.factors ->> 'brar_ar_qfq', '')::double precision,
        brar_br = nullif(technical.factors ->> 'brar_br_qfq', '')::double precision,
        cr = nullif(technical.factors ->> 'cr_qfq', '')::double precision,
        dfma_dif = nullif(technical.factors ->> 'dfma_dif_qfq', '')::double precision,
        dfma_difma = nullif(technical.factors ->> 'dfma_difma_qfq', '')::double precision,
        dmi_adx = nullif(technical.factors ->> 'dmi_adx_qfq', '')::double precision,
        dmi_adxr = nullif(technical.factors ->> 'dmi_adxr_qfq', '')::double precision,
        dmi_mdi = nullif(technical.factors ->> 'dmi_mdi_qfq', '')::double precision,
        dmi_pdi = nullif(technical.factors ->> 'dmi_pdi_qfq', '')::double precision,
        dpo = nullif(technical.factors ->> 'dpo_qfq', '')::double precision,
        madpo = nullif(technical.factors ->> 'madpo_qfq', '')::double precision,
        emv = nullif(technical.factors ->> 'emv_qfq', '')::double precision,
        maemv = nullif(technical.factors ->> 'maemv_qfq', '')::double precision,
        expma12 = nullif(technical.factors ->> 'expma_12_qfq', '')::double precision,
        expma50 = nullif(technical.factors ->> 'expma_50_qfq', '')::double precision,
        keltner_lower = nullif(technical.factors ->> 'ktn_down_qfq', '')::double precision,
        keltner_mid = nullif(technical.factors ->> 'ktn_mid_qfq', '')::double precision,
        keltner_upper = nullif(technical.factors ->> 'ktn_upper_qfq', '')::double precision,
        mass = nullif(technical.factors ->> 'mass_qfq', '')::double precision,
        ma_mass = nullif(technical.factors ->> 'ma_mass_qfq', '')::double precision,
        maroc = nullif(technical.factors ->> 'maroc_qfq', '')::double precision,
        psy = nullif(technical.factors ->> 'psy_qfq', '')::double precision,
        psyma = nullif(technical.factors ->> 'psyma_qfq', '')::double precision,
        taq_lower = nullif(technical.factors ->> 'taq_down_qfq', '')::double precision,
        taq_mid = nullif(technical.factors ->> 'taq_mid_qfq', '')::double precision,
        taq_upper = nullif(technical.factors ->> 'taq_up_qfq', '')::double precision,
        trix = nullif(technical.factors ->> 'trix_qfq', '')::double precision,
        trma = nullif(technical.factors ->> 'trma_qfq', '')::double precision,
        xsii_td1 = nullif(technical.factors ->> 'xsii_td1_qfq', '')::double precision,
        xsii_td2 = nullif(technical.factors ->> 'xsii_td2_qfq', '')::double precision,
        xsii_td3 = nullif(technical.factors ->> 'xsii_td3_qfq', '')::double precision,
        xsii_td4 = nullif(technical.factors ->> 'xsii_td4_qfq', '')::double precision,
        -- Historical JSON stored the four integral counters as JSON numbers
        -- rendered like 0.0/13.0.  PostgreSQL cannot cast those texts straight
        -- to integer, so preserve their integral value through numeric first.
        updays = nullif(technical.factors ->> 'updays', '')::numeric::integer,
        downdays = nullif(technical.factors ->> 'downdays', '')::numeric::integer,
        topdays = nullif(technical.factors ->> 'topdays', '')::numeric::integer,
        lowdays = nullif(technical.factors ->> 'lowdays', '')::numeric::integer,
        updated_at = now(), calculated_at = now()
    FROM t_stock_technical_factor_daily technical
    WHERE target.stock_code = technical.stock_code
      AND target.trade_date = technical.trade_date
      AND technical.trade_date BETWEEN p_start_date AND p_end_date;
    GET DIAGNOSTICS v_professional = ROW_COUNT;

    UPDATE t_stock_factor_daily_final_shadow
    SET price_status = CASE WHEN open_qfq IS NOT NULL AND high_qfq IS NOT NULL
            AND low_qfq IS NOT NULL AND close_qfq IS NOT NULL THEN 'ready' ELSE 'partial' END,
        technical_core_status = CASE WHEN num_nonnulls(
            open_qfq, high_qfq, low_qfq, close_qfq,
            ma5, ma10, ma20, ma30, ma60,
            ema5, ema10, ema20,
            macd, macd_dif, macd_dea,
            kdj_j, kdj_k, kdj_d,
            rsi6, rsi12, rsi24,
            boll_upper, boll_mid, boll_lower, atr
        ) = 25 THEN 'ready' ELSE 'partial' END,
        technical_extended_status = CASE WHEN num_nonnulls(
            ma90, ma250, ema30, ema60, ema90, ema250,
            bbi, bias1, bias2, bias3, cci, vr, wr, wr1, obv, mfi, roc,
            mtm, mtmma, asi, asit, brar_ar, brar_br, cr,
            dfma_dif, dfma_difma, dmi_adx, dmi_adxr, dmi_mdi, dmi_pdi,
            dpo, madpo, emv, maemv, expma12, expma50,
            keltner_lower, keltner_mid, keltner_upper,
            mass, ma_mass, maroc, psy, psyma,
            taq_lower, taq_mid, taq_upper, trix, trma,
            xsii_td1, xsii_td2, xsii_td3, xsii_td4
        ) = 53 THEN 'ready' ELSE 'partial' END,
        calculation_revision = 'stock_daily_final_migrated', calculated_at = now()
    WHERE trade_date BETWEEN p_start_date AND p_end_date;

    RETURN QUERY SELECT v_factor, v_professional, v_basic, v_fund, v_sector_fund, v_north;
END $$;

-- One generated SELECT per 20 open trading days; psql \gexec executes and
-- commits them independently because this script intentionally has no BEGIN.
WITH windows AS (
    SELECT min(trade_date) AS start_date, max(trade_date) AS end_date
    FROM (
        SELECT trade_date,
               (row_number() OVER (ORDER BY trade_date) - 1) / 20 AS window_no
        FROM t_trade_calendar
        WHERE market = 'CN' AND is_open IS TRUE
          AND trade_date >= DATE '2021-01-01'
          AND trade_date <= (SELECT max(trade_date) FROM t_daily_bar)
    ) d
    GROUP BY window_no
    ORDER BY window_no
)
SELECT format(
    'SELECT %L::date AS start_date, %L::date AS end_date, r.* FROM fn_backfill_daily_assets_final_window(%L::date, %L::date) r;',
    start_date, end_date, start_date, end_date
)
FROM windows
\gexec

-- Minute factors only retain the available minute partitions (normally 30
-- trading days). Recalculate one session per transaction because the old
-- ``minute_return`` represented return since the open, not a one-minute
-- return, and therefore cannot be renamed safely.
CREATE OR REPLACE FUNCTION fn_backfill_minute_factor_final(p_trade_date DATE)
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    v_rows BIGINT := 0;
BEGIN
    WITH metrics AS (
        SELECT minute.stock_code, minute.trade_date, minute.bar_time, minute.price,
               minute.volume_hand,
               sum(minute.amount_yuan) FILTER (
                   WHERE minute.amount_yuan IS NOT NULL AND minute.volume_hand > 0
               ) OVER w_running AS cumulative_amount,
               sum(minute.volume_hand) FILTER (
                   WHERE minute.amount_yuan IS NOT NULL AND minute.volume_hand > 0
               ) OVER w_running AS cumulative_amount_volume,
               lag(minute.price, 1) OVER w AS price_1m_ago,
               lag(minute.price, 5) OVER w AS price_5m_ago,
               lag(minute.price, 15) OVER w AS price_15m_ago,
               avg(minute.price) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
               avg(minute.price) OVER (w ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS ma10,
               avg(minute.price) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
               avg(minute.volume_hand) FILTER (WHERE minute.volume_hand > 0)
                   OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS prior_volume_20,
               count(minute.volume_hand) FILTER (WHERE minute.volume_hand > 0)
                   OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS prior_volume_count_20,
               min(minute.price) OVER w_running AS running_low,
               max(minute.price) OVER w_running AS running_high
        FROM t_minute_bar minute
        WHERE minute.trade_date = p_trade_date
        WINDOW
            w AS (PARTITION BY minute.stock_code, minute.trade_date ORDER BY minute.bar_time, minute.id),
            w_running AS (PARTITION BY minute.stock_code, minute.trade_date ORDER BY minute.bar_time, minute.id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
    )
    UPDATE t_stock_factor_minute target
    SET vwap = metrics.cumulative_amount / nullif(metrics.cumulative_amount_volume * 100, 0),
        return_1m_pct = (metrics.price / nullif(metrics.price_1m_ago, 0) - 1) * 100,
        return_5m_pct = (metrics.price / nullif(metrics.price_5m_ago, 0) - 1) * 100,
        return_15m_pct = (metrics.price / nullif(metrics.price_15m_ago, 0) - 1) * 100,
        ma5 = metrics.ma5,
        ma10 = metrics.ma10,
        ma20 = metrics.ma20,
        volume_ratio_20m = CASE WHEN metrics.prior_volume_count_20 = 20
            THEN metrics.volume_hand / nullif(metrics.prior_volume_20, 0) END,
        intraday_position_ratio = (metrics.price - metrics.running_low)
            / nullif(metrics.running_high - metrics.running_low, 0)
    FROM metrics
    WHERE target.stock_code = metrics.stock_code
      AND target.trade_date = metrics.trade_date
      AND target.bar_time = metrics.bar_time;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END $$;

SELECT format('SELECT %L::date AS trade_date, fn_backfill_minute_factor_final(%L::date) AS factor_rows;', trade_date, trade_date)
FROM (SELECT DISTINCT trade_date FROM t_minute_bar ORDER BY trade_date) dates
\gexec

ANALYZE t_stock_factor_daily_final_shadow;
ANALYZE t_stock_factor_minute;
ANALYZE t_stock_daily_basic;
ANALYZE t_stock_fund_flow_daily;
ANALYZE t_sector_fund_flow_daily;

UPDATE t_data_asset_migration_state
SET status = 'backfilled',
    details = details || jsonb_build_object(
        'shadow_rows', (SELECT count(*) FROM t_stock_factor_daily_final_shadow),
        'shadow_max_date', (SELECT max(trade_date) FROM t_stock_factor_daily_final_shadow),
        'backfilled_at', now()
    )
WHERE migration_code = 'daily_assets_final';

-- Validation output. Do not run cut-over unless coverage is >= 98% and Pro
-- samples match the legacy JSON checks in migration 79.
SELECT
    f.trade_date,
    count(*) AS factor_rows,
    count(*) FILTER (WHERE price_status = 'ready') AS price_ready_rows,
    count(*) FILTER (WHERE technical_core_status = 'ready') AS technical_core_ready_rows,
    round(count(*) FILTER (WHERE price_status = 'ready')::numeric / nullif(count(*), 0), 4) AS price_coverage
FROM t_stock_factor_daily_final_shadow f
WHERE f.trade_date = (SELECT max(trade_date) FROM t_daily_bar)
GROUP BY f.trade_date;
