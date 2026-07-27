import { requestData } from './client';
import type { MarketDailyReview, MarketDailySentiment } from '@/types/market-insight';

export const marketInsightApi = {
  dailySentiment: (params?: { trade_date?: string; calculation_version?: string }) => requestData<MarketDailySentiment>({
    method: 'GET',
    url: '/market-insights/daily-sentiment',
    params,
  }),
  dailyReview: (params?: { trade_date?: string; calculation_version?: string; sector_limit?: number; evidence_limit?: number }) => requestData<MarketDailyReview>({
    method: 'GET',
    url: '/market-insights/daily-review',
    params,
  }),
};
