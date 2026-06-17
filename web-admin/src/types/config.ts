export type ConfigCategory = 'search' | 'llm' | 'notification';
export type ValueStatus = 'active' | 'cooldown' | 'invalid' | 'disabled';

export interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface SystemConfig {
  id: number;
  category_code: ConfigCategory;
  config_code: string;
  config_name: string;
  description: string | null;
  sort_order: number;
  is_default: boolean;
  is_enabled: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConfigOption {
  id: number;
  system_config_id: number;
  option_key: string;
  option_name: string;
  value_type: string;
  value: unknown;
  default_value: unknown;
  is_required: boolean;
  is_enabled: boolean;
  description: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConfigValue {
  id: number;
  system_config_id: number;
  value_name: string;
  value_kind: string;
  fingerprint: string;
  priority: number;
  weight: number;
  status: ValueStatus;
  failure_count: number;
  last_used_at: string | null;
  cooldown_until: string | null;
  is_enabled: boolean;
  description: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConfigValueTestResult {
  value_id: number;
  available: boolean;
  fingerprint: string;
  status: string;
  error: string | null;
}

export interface ConfigItem {
  config: SystemConfig;
  options: ConfigOption[];
  values: ConfigValue[];
  available_value_count: number;
}

export interface ConfigSummary {
  categories: Record<string, number>;
  active_values: Record<string, number>;
}
