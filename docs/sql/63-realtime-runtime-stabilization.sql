-- Realtime runtime stabilization: explicit stock-pool policies and 90% budgets.
-- Safe to re-run.  It does not alter historical facts, minute bars or pool members.

CREATE TABLE IF NOT EXISTS t_stock_pool_realtime_policy (
    pool_id BIGINT PRIMARY KEY REFERENCES t_stock_pool(id) ON DELETE CASCADE,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    priority INTEGER NOT NULL DEFAULT 1000,
    quote_lane VARCHAR(20) NOT NULL DEFAULT 'off',
    minute_lane VARCHAR(20) NOT NULL DEFAULT 'off',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_t_stock_pool_realtime_policy_priority CHECK (priority BETWEEN 0 AND 10000),
    CONSTRAINT ck_t_stock_pool_realtime_policy_quote_lane CHECK (quote_lane IN ('hot', 'warm', 'off')),
    CONSTRAINT ck_t_stock_pool_realtime_policy_minute_lane CHECK (minute_lane IN ('guaranteed', 'rotating', 'off'))
);

COMMENT ON TABLE t_stock_pool_realtime_policy IS
    'One-to-one realtime policy for stock pools; membership is separate from runtime refresh priority and lanes.';

-- Seed only missing policy rows so explicit user changes remain intact on re-run.
INSERT INTO t_stock_pool_realtime_policy (pool_id, is_enabled, priority, quote_lane, minute_lane)
SELECT p.id,
       CASE p.pool_code
           WHEN 'holding' THEN TRUE
           WHEN 'focus' THEN TRUE
           WHEN 'candidate' THEN TRUE
           WHEN 'breakout_retake' THEN TRUE
           ELSE p.pool_type = 'strategy'
       END,
       CASE p.pool_code
           WHEN 'holding' THEN 0
           WHEN 'focus' THEN 10
           WHEN 'candidate' THEN 20
           WHEN 'breakout_retake' THEN 30
           ELSE CASE WHEN p.pool_type = 'strategy' THEN 30 ELSE 1000 END
       END,
       CASE p.pool_code
           WHEN 'holding' THEN 'hot'
           WHEN 'focus' THEN 'hot'
           WHEN 'candidate' THEN 'hot'
           WHEN 'breakout_retake' THEN 'hot'
           ELSE CASE WHEN p.pool_type = 'strategy' THEN 'hot' ELSE 'off' END
       END,
       CASE p.pool_code
           WHEN 'holding' THEN 'guaranteed'
           WHEN 'focus' THEN 'guaranteed'
           WHEN 'candidate' THEN 'rotating'
           WHEN 'breakout_retake' THEN 'guaranteed'
           ELSE CASE WHEN p.pool_type = 'strategy' THEN 'guaranteed' ELSE 'off' END
       END
FROM t_stock_pool p
ON CONFLICT (pool_id) DO NOTHING;

-- The dynamic all-market universe is deliberately never a target pool.
UPDATE t_stock_pool_realtime_policy policy
SET is_enabled = FALSE,
    quote_lane = 'off',
    minute_lane = 'off',
    updated_at = now()
FROM t_stock_pool pool
WHERE policy.pool_id = pool.id
  AND pool.is_dynamic IS TRUE
  AND pool.dynamic_rule = 'active_a_share';

-- The configured vendor limit remains visible; runtime dispatch uses 90% of it.
UPDATE t_config_option option_row
SET option_value = '0.9'::jsonb,
    default_value = '0.9'::jsonb,
    updated_at = now()
FROM t_system_config config
WHERE option_row.system_config_id = config.id
  AND config.category_code = 'market_data'
  AND config.config_code = 'tickflow'
  AND option_row.option_key = 'realtime_safety_ratio';
