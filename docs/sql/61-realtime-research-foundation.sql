-- 第一期实时研究底座：TickFlow REST 轮询 + 五档深度。
-- 幂等迁移：不删除任何历史行情、分钟因子或股票池数据。

ALTER TABLE t_stock
    ADD COLUMN IF NOT EXISTS is_st BOOLEAN NOT NULL DEFAULT FALSE;

-- 名称由 sync_stock_basic 持续维护；这里仅为已有主数据建立初始标识。
UPDATE t_stock
SET is_st = upper(regexp_replace(coalesce(stock_name, ''), '^[* ]+', '')) LIKE 'ST%'
WHERE is_st IS DISTINCT FROM (upper(regexp_replace(coalesce(stock_name, ''), '^[* ]+', '')) LIKE 'ST%');

CREATE INDEX IF NOT EXISTS idx_t_stock_realtime_eligible
    ON t_stock (status, is_st, exchange, stock_code);

CREATE TABLE IF NOT EXISTS t_market_universe (
    id BIGSERIAL PRIMARY KEY,
    provider_code VARCHAR(40) NOT NULL,
    universe_id VARCHAR(160) NOT NULL,
    universe_name VARCHAR(240) NOT NULL,
    description TEXT,
    region VARCHAR(40),
    category VARCHAR(80),
    taxonomy_level VARCHAR(40),
    logical_group_key VARCHAR(320),
    source_symbol_count INTEGER NOT NULL DEFAULT 0,
    catalog_hash VARCHAR(128),
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_universe_provider_id UNIQUE (provider_code, universe_id)
);

CREATE INDEX IF NOT EXISTS idx_t_market_universe_provider_taxonomy
    ON t_market_universe (provider_code, taxonomy_level, logical_group_key);

CREATE TABLE IF NOT EXISTS t_market_universe_member (
    id BIGSERIAL PRIMARY KEY,
    universe_row_id BIGINT NOT NULL REFERENCES t_market_universe(id) ON DELETE CASCADE,
    stock_code VARCHAR(32) NOT NULL,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to DATE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_market_universe_member_effective_from UNIQUE (universe_row_id, stock_code, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_t_market_universe_member_active
    ON t_market_universe_member (universe_row_id, stock_code)
    WHERE valid_to IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_t_market_universe_member_active
    ON t_market_universe_member (universe_row_id, stock_code)
    WHERE valid_to IS NULL;

COMMENT ON TABLE t_market_universe IS '第三方标的池目录；TickFlow SW 行业与 Tushare 概念板块严格分层保存';
COMMENT ON TABLE t_market_universe_member IS '第三方标的池成员有效期历史，不替代 t_stock_pool_member';
COMMENT ON COLUMN t_stock.is_st IS '由股票基础资料名称同步识别；实时情绪与策略候选统一排除';

UPDATE t_system_config
SET metadata = metadata || '{"source":"tickflow-realtime-research","capabilities":["quote_universe","quote_symbol_batch","depth_batch","universe_catalog"],"minute_provider":"mootdx"}'::jsonb,
    description = 'TickFlow REST 全市场/候选 Quote 与五档深度；MooTDX 继续提供实时分钟线。运行前必须通过全市场、50 Quote、200 深度权限测试。',
    updated_at = now()
WHERE category_code = 'market_data' AND config_code = 'tickflow';

-- TickFlow 购买额度。运行时以 80% 安全预算令牌桶执行，不再使用代码写死的 60/min。
INSERT INTO t_config_option (
    system_config_id, option_key, option_name, option_value, default_value,
    value_type, is_required, description, is_enabled, metadata
)
SELECT c.id, v.option_key, v.option_name, v.option_value, v.option_value,
       v.value_type, TRUE, v.description, TRUE, '{"source":"realtime-research-foundation"}'::jsonb
FROM t_system_config c
CROSS JOIN (
    VALUES
        ('quote_symbol_requests_per_minute', '标的 Quote 每分钟上限', '60'::jsonb, 'number', '按标的批量 Quote 的购买上限（次/分钟）'),
        ('quote_symbol_batch_max_symbols', '标的 Quote 单批上限', '50'::jsonb, 'number', '按标的批量 Quote 单次最大标的数'),
        ('quote_universe_requests_per_minute', '全市场 Quote 每分钟上限', '20'::jsonb, 'number', '全市场标的池 Quote 的购买上限（次/分钟）'),
        ('depth_batch_requests_per_minute', '五档深度每分钟上限', '60'::jsonb, 'number', '五档批量深度的购买上限（次/分钟）'),
        ('depth_batch_max_symbols', '五档深度单批上限', '200'::jsonb, 'number', '五档批量深度单次最大标的数'),
        ('realtime_safety_ratio', '实时限频安全比例', '0.8'::jsonb, 'number', '实时限频安全预算比例')
) AS v(option_key, option_name, option_value, value_type, description)
WHERE c.category_code = 'market_data' AND c.config_code = 'tickflow'
ON CONFLICT (system_config_id, option_key) DO UPDATE
SET option_name = EXCLUDED.option_name,
    option_value = EXCLUDED.option_value,
    default_value = EXCLUDED.default_value,
    value_type = EXCLUDED.value_type,
    description = EXCLUDED.description,
    is_enabled = TRUE,
    updated_at = now();

INSERT INTO t_config_option (
    system_config_id, option_key, option_name, option_value, default_value,
    value_type, is_required, description, is_enabled, metadata
)
SELECT c.id, v.option_key, v.option_name, v.option_value, v.option_value,
       v.value_type, TRUE, v.description, TRUE, '{"source":"realtime-research-foundation"}'::jsonb
FROM t_system_config c
CROSS JOIN (
    VALUES
        ('quote_batch_size', 'Quote 单批股票数', '50'::jsonb, 'number', 'TickFlow Quote 单批标的数，受购买额度限制'),
        ('minute_provider_pool_size', '分钟线 Provider 连接数', '6'::jsonb, 'number', 'MooTDX 分钟线连接池默认并发（最高 8）'),
        ('decision_target_limit', '实时决策池上限', '200'::jsonb, 'number', '10 秒实时决策 Quote / 五档深度最大标的数'),
        ('decision_quote_interval_seconds', '实时决策 Quote 刷新秒数', '10'::jsonb, 'number', '实时决策池 Quote 刷新间隔'),
        ('warm_quote_interval_seconds', '温观察池刷新秒数', '60'::jsonb, 'number', '温观察池 Quote 刷新间隔'),
        ('depth_refresh_interval_seconds', '五档深度刷新秒数', '10'::jsonb, 'number', '连续交易五档深度刷新间隔'),
        ('auction_depth_refresh_interval_seconds', '竞价五档深度刷新秒数', '5'::jsonb, 'number', '09:20–09:25 五档深度刷新间隔'),
        ('depth_cache_ttl_seconds', '五档深度缓存 TTL 秒数', '30'::jsonb, 'number', '五档当前/近三次快照 Redis TTL'),
        ('leader_lease_seconds', '实时租约秒数', '20'::jsonb, 'number', '实时外部拉取 Redis 租约时长')
) AS v(option_key, option_name, option_value, value_type, description)
WHERE c.category_code = 'market_data' AND c.config_code = 'realtime_market'
ON CONFLICT (system_config_id, option_key) DO UPDATE
SET option_name = EXCLUDED.option_name,
    option_value = EXCLUDED.option_value,
    default_value = EXCLUDED.default_value,
    value_type = EXCLUDED.value_type,
    description = EXCLUDED.description,
    is_enabled = TRUE,
    updated_at = now();

-- 旧版默认 80 已超过新购买 Key 的 50 标的/次限制，因此强制迁移到可运行值。
UPDATE t_config_option o
SET option_value = '50'::jsonb, updated_at = now()
FROM t_system_config c
WHERE o.system_config_id = c.id
  AND c.category_code = 'market_data'
  AND c.config_code = 'realtime_market'
  AND o.option_key = 'quote_batch_size';
