-- t_sector_component 当前快照同步任务升级
-- 不修改 t_sector_component 表结构，确保应用账号无需 ALTER TABLE 权限。
-- 运行时不再写入 end_date；完整快照中的缺失关联由同步服务物理删除。
-- 旧 end_date 来自曾经的部分抓取，不能视为已确认移除，因此先恢复为当前关联。

BEGIN;

UPDATE t_sector_component
SET end_date = NULL
WHERE end_date IS NOT NULL;

UPDATE t_scheduler_job
SET
    description = '每日同步 A 股概念/行业板块列表与当前成分股快照；仅完整结果可物理删除旧关联。',
    parameter_schema = '{
      "sector_types":{"label":"板块类型","type":"array","default":["concept","industry"],"required":false,"description":"同步哪些板块类型。","options":["concept","industry"]},
      "sync_components":{"label":"同步成分股","type":"boolean","default":true,"required":false,"description":"是否同步板块与股票当前关联。"},
      "limit_sectors":{"label":"板块上限","type":"number","required":false,"description":"调试时限制每类同步多少个板块；为空表示全量。"},
      "max_concurrency":{"label":"最大并发","type":"number","default":1,"required":false,"description":"外部成分股查询并发数；同花顺回退源建议保持 1。","min":1,"max":10},
      "source":{"label":"数据源","type":"string","default":"akshare","required":false,"options":["akshare"],"description":"板块同步通过 AkShare provider chain。"},
      "delete_missing_components":{"label":"删除缺失成分","type":"boolean","default":true,"required":false,"description":"仅当单板块返回完整快照时，物理删除本次未出现的旧关联。"},
      "ths_request_interval_seconds":{"label":"同花顺请求间隔秒数","type":"number","default":0.8,"required":false,"description":"同花顺每次请求之间的最小间隔，降低 403 限流概率。","min":0.1,"max":10},
      "provider_timeout_seconds":{"label":"Provider 超时秒数","type":"number","default":45,"required":false,"description":"单次外部 provider 请求超时时间。","min":5,"max":600}
    }'::jsonb,
    default_payload = '{"sector_types":["concept","industry"],"sync_components":true,"limit_sectors":null,"max_concurrency":1,"source":"akshare","delete_missing_components":true,"ths_request_interval_seconds":0.8,"provider_timeout_seconds":45}'::jsonb,
    updated_at = now()
WHERE job_code = 'sync_sector_catalog';

COMMIT;
