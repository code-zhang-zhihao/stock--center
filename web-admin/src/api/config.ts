import { requestData } from './client';
import type { ConfigCategory, ConfigItem, ConfigOption, ConfigSummary, ConfigValue, ConfigValueTestResult, SystemConfig } from '@/types/config';

export interface ConfigUpdatePayload {
  config_name?: string;
  description?: string | null;
  sort_order?: number;
  is_default?: boolean;
  is_enabled?: boolean;
  metadata?: Record<string, unknown>;
}

export interface OptionPayload {
  option_key: string;
  option_name: string;
  value_type: string;
  value: unknown;
  default_value: unknown;
  is_required: boolean;
  is_enabled: boolean;
  description?: string | null;
  metadata: Record<string, unknown>;
}

export interface ValueCreatePayload {
  value_name: string;
  value_kind: string;
  endpoint_url?: string | null;
  secret: string;
  priority: number;
  weight: number;
  status: string;
  is_enabled: boolean;
  description?: string | null;
  metadata: Record<string, unknown>;
}

export interface ValueUpdatePayload {
  value_name?: string;
  value_kind?: string;
  endpoint_url?: string | null;
  secret?: string;
  priority?: number;
  weight?: number;
  status?: string;
  failure_count?: number;
  cooldown_until?: string | null;
  is_enabled?: boolean;
  description?: string | null;
  metadata?: Record<string, unknown>;
}

export const configApi = {
  summary: () => requestData<ConfigSummary>({ method: 'GET', url: '/config/summary' }),
  items: (category: ConfigCategory) => requestData<ConfigItem[]>({ method: 'GET', url: '/config/items', params: { category } }),
  updateItem: (configId: number, data: ConfigUpdatePayload) => requestData<SystemConfig>({ method: 'PATCH', url: `/config/items/${configId}`, data }),
  options: (configId: number) => requestData<ConfigOption[]>({ method: 'GET', url: `/config/items/${configId}/options` }),
  putOptions: (configId: number, options: OptionPayload[]) =>
    requestData<ConfigOption[]>({ method: 'PUT', url: `/config/items/${configId}/options`, data: { options } }),
  values: (configId: number, valueKind?: string | null) =>
    requestData<ConfigValue[]>({
      method: 'GET',
      url: `/config/items/${configId}/values`,
      params: valueKind ? { value_kind: valueKind } : undefined,
    }),
  createValue: (configId: number, data: ValueCreatePayload) => requestData<ConfigValue>({ method: 'POST', url: `/config/items/${configId}/values`, data }),
  updateValue: (valueId: number, data: ValueUpdatePayload) => requestData<ConfigValue>({ method: 'PATCH', url: `/config/values/${valueId}`, data }),
  disableValue: (valueId: number) => requestData<ConfigValue>({ method: 'POST', url: `/config/values/${valueId}/disable` }),
  deleteValue: (valueId: number) => requestData<{ deleted: boolean; value_id: number }>({ method: 'DELETE', url: `/config/values/${valueId}` }),
  testValue: (valueId: number) => requestData<ConfigValueTestResult>({ method: 'POST', url: `/config/values/${valueId}/test` }),
};
