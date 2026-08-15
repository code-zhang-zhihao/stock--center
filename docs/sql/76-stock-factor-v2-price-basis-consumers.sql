-- Keep every active-factor consumer on one internally consistent price basis.
-- The additive view keeps the existing compatibility view untouched while
-- giving strategy, backtest and emotion consumers index-friendly V1/V2 arms.

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE OR REPLACE VIEW v_stock_factor_daily_active_basis AS
SELECT
    legacy.id,
    legacy.stock_code,
    legacy.trade_date,
    legacy.source,
    legacy.ma5,
    legacy.ma10,
    legacy.ma20,
    legacy.ma30,
    legacy.ma60,
    legacy.return_1d,
    legacy.amplitude,
    legacy.volume_ratio,
    legacy.amount_ratio,
    legacy.volatility_20d,
    legacy.close_position,
    legacy.features,
    'stock_daily_v1'::varchar AS factor_set_version,
    'bfq'::varchar AS price_basis,
    'ready'::varchar AS factor_status,
    jsonb_build_object('local', legacy.source) AS source_map,
    coalesce(legacy.features -> 'missing_windows', '[]'::jsonb) AS missing_factors,
    legacy.created_at,
    legacy.created_at AS updated_at,
    NULL::double precision AS basis_open_price,
    NULL::double precision AS basis_high_price,
    NULL::double precision AS basis_low_price,
    NULL::double precision AS basis_close_price,
    NULL::double precision AS basis_pre_close_price
FROM t_stock_factor_daily AS legacy
WHERE EXISTS (
    SELECT 1 FROM t_factor_set_version
    WHERE factor_set_code = 'stock_daily_v1' AND status = 'active'
)
UNION ALL
SELECT
    v2.id,
    v2.stock_code,
    v2.trade_date,
    'system:daily_close'::varchar AS source,
    v2.ma5,
    v2.ma10,
    v2.ma20,
    v2.ma30,
    v2.ma60,
    v2.return_1d,
    v2.amplitude_1d AS amplitude,
    v2.volume_ratio_5d AS volume_ratio,
    v2.amount_ratio_5d AS amount_ratio,
    v2.volatility_20d,
    v2.close_position_1d AS close_position,
    jsonb_build_object('history_days', v2.history_days) AS features,
    v2.factor_set_version,
    v2.price_basis,
    v2.factor_status,
    v2.source_map,
    v2.missing_factors,
    v2.created_at,
    v2.updated_at,
    v2.open_qfq AS basis_open_price,
    v2.high_qfq AS basis_high_price,
    v2.low_qfq AS basis_low_price,
    v2.close_qfq AS basis_close_price,
    v2.pre_close_qfq AS basis_pre_close_price
FROM t_stock_factor_daily_v2 AS v2
WHERE v2.factor_status = 'ready'
  AND EXISTS (
      SELECT 1 FROM t_factor_set_version
      WHERE factor_set_code = v2.factor_set_version AND status = 'active'
  );

COMMENT ON VIEW v_stock_factor_daily_active_basis IS
    '当前激活因子集的同口径消费视图；V1 由消费者回退 BFQ 日 K，V2 使用 QFQ OHLC 与 QFQ 技术因子。';

COMMIT;
