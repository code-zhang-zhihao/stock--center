-- Deterministic historical parameter optimisation audit trail.
-- Requires 70-strategy-evaluation-lifecycle.sql.  It only stores research
-- runs/trials; it neither changes a strategy version nor promotes paper mode.

BEGIN;

CREATE TABLE IF NOT EXISTS t_strategy_optimization_run (
    id BIGSERIAL PRIMARY KEY,
    run_code VARCHAR(64) NOT NULL,
    strategy_id BIGINT NOT NULL REFERENCES t_strategy_definition(id) ON DELETE CASCADE,
    strategy_version_id BIGINT NOT NULL REFERENCES t_strategy_version(id) ON DELETE RESTRICT,
    baseline_backtest_run_id BIGINT NOT NULL REFERENCES t_strategy_backtest_run(id) ON DELETE RESTRICT,
    status VARCHAR(24) NOT NULL DEFAULT 'running',
    train_end_date DATE NOT NULL,
    search_space JSONB NOT NULL DEFAULT '{}'::jsonb,
    requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_optimization_run_code UNIQUE (run_code),
    CONSTRAINT ck_t_strategy_optimization_run_status CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_optimization_run_version_created
    ON t_strategy_optimization_run (strategy_version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS t_strategy_optimization_trial (
    id BIGSERIAL PRIMARY KEY,
    optimization_run_id BIGINT NOT NULL REFERENCES t_strategy_optimization_run(id) ON DELETE CASCADE,
    trial_no INTEGER NOT NULL,
    parameter_patch JSONB NOT NULL DEFAULT '{}'::jsonb,
    train_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    robustness_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    verdict VARCHAR(24) NOT NULL,
    rank_no INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_strategy_optimization_trial_business UNIQUE (optimization_run_id, trial_no),
    CONSTRAINT ck_t_strategy_optimization_trial_verdict CHECK (verdict IN ('eligible', 'rejected', 'baseline', 'data_insufficient'))
);

CREATE INDEX IF NOT EXISTS idx_t_strategy_optimization_trial_run_rank
    ON t_strategy_optimization_trial (optimization_run_id, rank_no NULLS LAST, trial_no);

INSERT INTO t_scheduler_job (
    job_code, job_name, job_type, description, parameter_schema, trigger_type,
    timezone, default_payload, max_instances, misfire_grace_seconds,
    timeout_seconds, retry_count, retry_interval_seconds, is_enabled, is_system,
    is_hidden, metadata
)
VALUES (
    'optimize_strategy_parameters',
    '优化策略历史参数',
    'strategy',
    '只用已完成日频基线交易做训练/验证分段、样本量和稳定性约束的确定性参数研究；不调用 Provider/LLM，不改版本、不提升 paper。',
    '{"strategy_code":{"label":"策略代码","type":"string","required":true},"version_no":{"label":"版本号","type":"integer","required":true},"baseline_run_code":{"label":"基线回测运行代码","type":"string","required":false,"description":"为空时选择该版本最近一条已完成的基线回测。"},"train_ratio":{"label":"训练样本比例","type":"number","default":0.7,"required":false},"max_trials":{"label":"最大试验数","type":"integer","default":500,"required":false}}'::jsonb,
    'cron', 'Asia/Shanghai', '{"train_ratio":0.7,"max_trials":500}'::jsonb,
    1, 300, 1800, 0, 60, true, true, false,
    '{"stage":"research","safe_mode":"local_backtest_subset_only"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    trigger_type = EXCLUDED.trigger_type,
    cron_expr = EXCLUDED.cron_expr,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_system = EXCLUDED.is_system,
    is_hidden = EXCLUDED.is_hidden,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_scheduler_job_tag (job_code, tag_code)
VALUES ('optimize_strategy_parameters', 'strategy')
ON CONFLICT DO NOTHING;

-- A full candidate set is required for subset replay.  Keep the strategy's
-- actual selection cap unchanged; this optional, manual-only override is a
-- research baseline and the backend explicitly refuses to use it for paper.
UPDATE t_scheduler_job
SET parameter_schema = COALESCE(parameter_schema, '{}'::jsonb) ||
        '{"baseline_candidate_limit":{"label":"研究回测每日候选上限","type":"integer","required":false,"description":"仅用于参数研究；高于策略实际候选上限的回测不会解锁 paper。"}}'::jsonb,
    updated_at = now()
WHERE job_code = 'run_strategy_backtest';

COMMENT ON TABLE t_strategy_optimization_run IS '策略参数历史寻优运行；保存训练/验证切分、搜索空间、样本门槛与结论，不自动修改版本。';
COMMENT ON TABLE t_strategy_optimization_trial IS '单个参数试验的可审计训练、验证与稳定性统计；仅已完成基线候选的收紧筛选可复放。';

COMMIT;
