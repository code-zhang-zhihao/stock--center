-- 股票池中心 v1：池定义和股票代码关联。可重复执行，不迁移旧 stock-analysis 的 daily_core。

CREATE TABLE IF NOT EXISTS t_stock_pool (
    id BIGSERIAL PRIMARY KEY,
    pool_code VARCHAR(80) NOT NULL UNIQUE,
    pool_name VARCHAR(160) NOT NULL,
    pool_type VARCHAR(40) NOT NULL,
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_t_stock_pool_code CHECK (pool_code ~ '^[a-z][a-z0-9_]{0,79}$')
);

CREATE TABLE IF NOT EXISTS t_stock_pool_member (
    id BIGSERIAL PRIMARY KEY,
    pool_id BIGINT NOT NULL REFERENCES t_stock_pool(id) ON DELETE CASCADE,
    stock_code VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_pool_member_pool_stock UNIQUE (pool_id, stock_code)
);

COMMENT ON TABLE t_stock_pool IS '股票池定义；系统池身份受保护，自定义池可维护。';
COMMENT ON COLUMN t_stock_pool.id IS '股票池主键 ID。';
COMMENT ON COLUMN t_stock_pool.pool_code IS '稳定业务编码；小写字母、数字和下划线。';
COMMENT ON COLUMN t_stock_pool.pool_name IS '股票池展示名称。';
COMMENT ON COLUMN t_stock_pool.pool_type IS '池类型：candidate、monitor、holding、strategy、custom。';
COMMENT ON COLUMN t_stock_pool.description IS '股票池业务说明。';
COMMENT ON COLUMN t_stock_pool.is_system IS '是否系统预置池；系统池代码、名称和类型不可修改或删除。';
COMMENT ON COLUMN t_stock_pool.is_enabled IS '是否启用；停用池仍保留成员关系。';
COMMENT ON COLUMN t_stock_pool.sort_order IS '列表排序值，数值越小越靠前。';
COMMENT ON COLUMN t_stock_pool.created_at IS '创建时间。';
COMMENT ON COLUMN t_stock_pool.updated_at IS '更新时间。';

COMMENT ON TABLE t_stock_pool_member IS '股票池成员关系；只保存池 ID 与 Canonical 股票代码。';
COMMENT ON COLUMN t_stock_pool_member.id IS '股票池成员关系主键 ID。';
COMMENT ON COLUMN t_stock_pool_member.pool_id IS '关联 t_stock_pool.id。';
COMMENT ON COLUMN t_stock_pool_member.stock_code IS '逻辑关联 t_stock.stock_code 的无后缀股票代码；写入前由应用层校验。';
COMMENT ON COLUMN t_stock_pool_member.created_at IS '加入股票池时间。';
COMMENT ON COLUMN t_stock_pool_member.updated_at IS '关系更新时间。';

CREATE INDEX IF NOT EXISTS idx_t_stock_pool_member_pool_created
    ON t_stock_pool_member(pool_id, created_at DESC, stock_code);
CREATE INDEX IF NOT EXISTS idx_t_stock_pool_member_stock
    ON t_stock_pool_member(stock_code, pool_id);
CREATE INDEX IF NOT EXISTS idx_t_stock_pool_enabled_sort
    ON t_stock_pool(is_enabled, sort_order, pool_code);

INSERT INTO t_stock_pool (
    pool_code, pool_name, pool_type, description, is_system, is_enabled, sort_order
)
VALUES
    ('candidate', '候选观察池', 'candidate', '策略、研究或人工加入的候选观察股票。', TRUE, TRUE, 10),
    ('focus', '重点监控池', 'monitor', '需要重点关注的股票。', TRUE, TRUE, 20),
    ('holding', '持仓监控池', 'holding', '实际或模拟持仓的监控股票。', TRUE, TRUE, 30),
    ('breakout_retake', '断板反包池', 'strategy', '断板反包形态的观察股票。', TRUE, TRUE, 40)
ON CONFLICT (pool_code) DO UPDATE SET
    pool_name = EXCLUDED.pool_name,
    pool_type = EXCLUDED.pool_type,
    description = EXCLUDED.description,
    is_system = TRUE,
    sort_order = EXCLUDED.sort_order,
    updated_at = now();
