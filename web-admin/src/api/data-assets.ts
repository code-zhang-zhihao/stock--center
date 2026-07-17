import { requestData } from './client';
import type {
  DataAssetCacheStatusReport,
  DataAssetDailyHealthReport,
  DataAssetGapReport,
  DataAssetRefreshQueuedResult,
  DataAssetRefreshResult,
  DataAssetSummary,
  RealtimeHealth,
} from '@/types/data-assets';

export const dataAssetsApi = {
  summary: () => requestData<DataAssetSummary>({
    method: 'GET',
    url: '/data-assets/summary',
  }),
  dailyHealth: (params?: { days?: number }) => requestData<DataAssetDailyHealthReport>({
    method: 'GET',
    url: '/data-assets/daily-health',
    params,
  }),
  cacheStatus: () => requestData<DataAssetCacheStatusReport>({
    method: 'GET',
    url: '/data-assets/cache-status',
  }),
  realtimeHealth: () => requestData<RealtimeHealth>({
    method: 'GET',
    url: '/data-assets/realtime-health',
  }),
  refresh: (params?: { days?: number; snapshot_key?: 'all' | 'summary' | 'daily_health'; async?: boolean }) => requestData<DataAssetRefreshResult | DataAssetRefreshQueuedResult>({
    method: 'POST',
    url: '/data-assets/refresh',
    params,
  }),
  gaps: (assetCode: string, params?: { trade_date?: string | null; limit?: number }) => requestData<DataAssetGapReport>({
    method: 'GET',
    url: `/data-assets/assets/${assetCode}/gaps`,
    params,
  }),
};
