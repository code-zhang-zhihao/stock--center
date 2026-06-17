export interface SchedulerJob {
  id: number;
  job_code: string;
  job_name: string;
  job_type: string;
  description: string | null;
  parameter_schema: Record<string, unknown>;
  trigger_type: string;
  cron_expr: string | null;
  timezone: string;
  default_payload: Record<string, unknown>;
  max_instances: number;
  misfire_grace_seconds: number;
  timeout_seconds: number | null;
  retry_count: number;
  retry_interval_seconds: number;
  next_run_at: string | null;
  last_run_at: string | null;
  is_enabled: boolean;
  is_system: boolean;
  is_hidden: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SchedulerRun {
  id: number;
  run_id: string;
  job_code: string;
  trigger_source: string;
  status: string;
  payload: Record<string, unknown>;
  affected_rows: number;
  started_at: string;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  result_summary: Record<string, unknown>;
  created_at: string;
}

export interface SchedulerRunListItem {
  id: number;
  run_id: string;
  job_code: string;
  trigger_source: string;
  status: string;
  payload: Record<string, unknown>;
  affected_rows: number;
  started_at: string;
  finished_at: string | null;
  created_at: string;
  has_error: boolean;
  error_code: string | null;
  error_message_preview: string | null;
  error_message_bytes: number;
  result_summary_bytes: number;
}

export interface SchedulerRunPage {
  items: SchedulerRunListItem[];
  limit: number;
  has_more: boolean;
}

export interface SchedulerStatus {
  enabled: boolean;
  installed: boolean;
  running: boolean;
  job_count: number;
  jobs: Array<Record<string, unknown>>;
  error: string | null;
}
