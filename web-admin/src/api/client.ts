import axios, { type AxiosRequestConfig } from 'axios';
import type { ApiEnvelope } from '@/types/config';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1',
  timeout: 30000,
});

export async function requestData<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await apiClient.request<ApiEnvelope<T>>(config);
  const envelope = response.data;
  if (!envelope.success) {
    const error = new Error(envelope.error?.message || 'API request failed') as Error & {
      code?: string;
      details?: unknown;
    };
    error.code = envelope.error?.code;
    error.details = envelope.error?.details;
    throw error;
  }
  return envelope.data;
}
