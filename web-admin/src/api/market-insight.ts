import { requestData } from './client';
import type { MarketDailySentiment } from '@/types/market-insight';

export const marketInsightApi = {
  dailySentiment: (params?: { trade_date?: string; calculation_version?: string }) => requestData<MarketDailySentiment>({
    method: 'GET',
    url: '/market-insights/daily-sentiment',
    params,
  }),
};
