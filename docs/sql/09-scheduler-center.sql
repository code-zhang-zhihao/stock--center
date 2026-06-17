-- stock-center 调度中心底座
-- 第一阶段只创建调度任务定义与运行日志，不迁移旧 stock-analysis 具体任务。

CREATE TABLE IF NOT EXISTS t_scheduler_job (
    id BIGSERIAL PRIMARY KEY,
    job_code VARCHAR(120) NOT NULL,
    job_name VARCHAR(160) NOT NULL,
    job_type VARCHAR(80) NOT NULL DEFAULT 'maintenance',
    description TEXT,
    parameter_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    trigger_type VARCHAR(40) NOT NULL DEFAULT 'cron',
    cron_expr VARCHAR(120),
    timezone VARCHAR(80) NOT NULL DEFAULT 'Asia/Shanghai',
    default_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    max_instances INTEGER NOT NULL DEFAULT 1,
    misfire_grace_seconds INTEGER NOT NULL DEFAULT 300,
    timeout_seconds INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0,
    retry_interval_seconds INTEGER NOT NULL DEFAULT 60,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    is_system BOOLEAN NOT NULL DEFAULT false,
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_scheduler_job_code UNIQUE (job_code),
    CONSTRAINT ck_t_scheduler_job_trigger_type CHECK (trigger_type IN ('cron')),
    CONSTRAINT ck_t_scheduler_job_max_instances CHECK (max_instances BETWEEN 1 AND 10),
    CONSTRAINT ck_t_scheduler_job_misfire CHECK (misfire_grace_seconds BETWEEN 1 AND 86400),
    CONSTRAINT ck_t_scheduler_job_timeout CHECK (timeout_seconds IS NULL OR timeout_seconds BETWEEN 1 AND 86400),
    CONSTRAINT ck_t_scheduler_job_retry_count CHECK (retry_count BETWEEN 0 AND 10),
    CONSTRAINT ck_t_scheduler_job_retry_interval CHECK (retry_interval_seconds BETWEEN 1 AND 3600)
);

COMMENT ON TABLE t_scheduler_job IS '调度任务定义表；APScheduler 读取启用且有 cron_expr 的任务并注册执行';
COMMENT ON COLUMN t_scheduler_job.id IS '主键 ID';
COMMENT ON COLUMN t_scheduler_job.job_code IS '任务编码，必须匹配后端 JobHandlerRegistry 中的 handler';
COMMENT ON COLUMN t_scheduler_job.job_name IS '任务展示名称';
COMMENT ON COLUMN t_scheduler_job.job_type IS '任务分类，例如 data_sync、market_data、indicator、strategy、news、alert、maintenance';
COMMENT ON COLUMN t_scheduler_job.description IS '任务说明';
COMMENT ON COLUMN t_scheduler_job.parameter_schema IS '任务运行参数 schema，用于后续前端渲染运行表单';
COMMENT ON COLUMN t_scheduler_job.trigger_type IS '触发器类型，第一阶段只支持 cron';
COMMENT ON COLUMN t_scheduler_job.cron_expr IS '五段 cron 表达式；为空表示仅支持手动运行，不注册 APScheduler';
COMMENT ON COLUMN t_scheduler_job.timezone IS '任务时区，默认 Asia/Shanghai';
COMMENT ON COLUMN t_scheduler_job.default_payload IS '定时执行或手动运行时的默认 payload';
COMMENT ON COLUMN t_scheduler_job.max_instances IS '同一任务在 APScheduler 中允许的最大并发实例数';
COMMENT ON COLUMN t_scheduler_job.misfire_grace_seconds IS '错过执行时间后的容忍秒数';
COMMENT ON COLUMN t_scheduler_job.timeout_seconds IS '任务超时时间，单位秒；为空表示不额外限制';
COMMENT ON COLUMN t_scheduler_job.retry_count IS '任务失败后的重试次数';
COMMENT ON COLUMN t_scheduler_job.retry_interval_seconds IS '任务失败重试间隔，单位秒';
COMMENT ON COLUMN t_scheduler_job.next_run_at IS '下一次计划执行时间，由调度运行时刷新';
COMMENT ON COLUMN t_scheduler_job.last_run_at IS '最近一次触发时间';
COMMENT ON COLUMN t_scheduler_job.is_enabled IS '是否启用；禁用后不会注册 cron，手动运行也应谨慎';
COMMENT ON COLUMN t_scheduler_job.is_system IS '是否系统内置任务；系统任务不可通过常规 API 删除';
COMMENT ON COLUMN t_scheduler_job.is_hidden IS '是否默认隐藏；用于 scheduler_noop 等内部验证任务';
COMMENT ON COLUMN t_scheduler_job.metadata IS '扩展元数据';
COMMENT ON COLUMN t_scheduler_job.created_at IS '创建时间';
COMMENT ON COLUMN t_scheduler_job.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS idx_t_scheduler_job_enabled_next_run
ON t_scheduler_job (is_enabled, next_run_at);

CREATE INDEX IF NOT EXISTS idx_t_scheduler_job_type
ON t_scheduler_job (job_type, job_code);

CREATE TABLE IF NOT EXISTS t_scheduler_job_run (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(80) NOT NULL,
    job_code VARCHAR(120) NOT NULL,
    trigger_source VARCHAR(40) NOT NULL DEFAULT 'manual',
    status VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    affected_rows INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    error_code VARCHAR(120),
    error_message TEXT,
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_scheduler_job_run_id UNIQUE (run_id),
    CONSTRAINT ck_t_scheduler_job_run_trigger_source CHECK (trigger_source IN ('manual', 'cron', 'retry', 'system')),
    CONSTRAINT ck_t_scheduler_job_run_status CHECK (status IN ('queued', 'running', 'success', 'failed', 'timeout', 'cancelled', 'skipped'))
);

COMMENT ON TABLE t_scheduler_job_run IS '调度任务运行日志表；保存手动和 cron 触发的执行记录';
COMMENT ON COLUMN t_scheduler_job_run.id IS '主键 ID';
COMMENT ON COLUMN t_scheduler_job_run.run_id IS '单次运行追踪 ID';
COMMENT ON COLUMN t_scheduler_job_run.job_code IS '任务编码';
COMMENT ON COLUMN t_scheduler_job_run.trigger_source IS '触发来源：manual、cron、retry、system';
COMMENT ON COLUMN t_scheduler_job_run.status IS '运行状态：queued、running、success、failed、timeout、cancelled、skipped';
COMMENT ON COLUMN t_scheduler_job_run.payload IS '本次运行实际 payload';
COMMENT ON COLUMN t_scheduler_job_run.affected_rows IS '本次运行影响行数或处理数量';
COMMENT ON COLUMN t_scheduler_job_run.started_at IS '开始时间';
COMMENT ON COLUMN t_scheduler_job_run.finished_at IS '结束时间';
COMMENT ON COLUMN t_scheduler_job_run.error_code IS '错误编码';
COMMENT ON COLUMN t_scheduler_job_run.error_message IS '错误摘要';
COMMENT ON COLUMN t_scheduler_job_run.result_summary IS '运行结果摘要；列表接口只读取大小和预览，详情接口读取完整内容';
COMMENT ON COLUMN t_scheduler_job_run.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_t_scheduler_job_run_started
ON t_scheduler_job_run (started_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_t_scheduler_job_run_code_started
ON t_scheduler_job_run (job_code, started_at DESC, id DESC);

INSERT INTO t_scheduler_job (
    job_code,
    job_name,
    job_type,
    description,
    parameter_schema,
    trigger_type,
    cron_expr,
    timezone,
    default_payload,
    max_instances,
    misfire_grace_seconds,
    timeout_seconds,
    retry_count,
    retry_interval_seconds,
    is_enabled,
    is_system,
    is_hidden,
    metadata
)
VALUES (
    'scheduler_noop',
    '调度中心链路验证任务',
    'maintenance',
    '内部 smoke test 任务，只用于验证调度中心手动触发、运行日志和 handler 注册链路。',
    '{"echo":{"label":"回显内容","type":"string","required":false,"description":"调度中心 smoke test 使用的回显文本。"}}'::jsonb,
    'cron',
    NULL,
    'Asia/Shanghai',
    '{"echo":"ok"}'::jsonb,
    1,
    300,
    60,
    0,
    60,
    true,
    true,
    true,
    '{"source":"stock-center-bootstrap","hidden_reason":"internal smoke test"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    default_payload = EXCLUDED.default_payload,
    is_system = true,
    is_hidden = true,
    metadata = EXCLUDED.metadata,
    updated_at = now();
