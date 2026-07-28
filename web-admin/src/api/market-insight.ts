import { requestData } from './client';
import type { MarketDailyReview, MarketDailySentiment, MarketEmotionDaily, MarketEmotionModel, MarketEmotionValidationPreview } from '@/types/market-insight';

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
  emotionDaily: (params?: { trade_date?: string; model_code?: string; history_limit?: number }) => requestData<MarketEmotionDaily>({
    method: 'GET',
    url: '/market-insights/emotion-daily',
    params,
  }),
  emotionModels: () => requestData<{ items: MarketEmotionModel[] }>({ method: 'GET', url: '/market-insights/emotion-models' }),
  emotionModelValidation: (modelCode: string, params?: { history_limit?: number }) => requestData<MarketEmotionValidationPreview>({ method: 'GET', url: `/market-insights/emotion-models/${encodeURIComponent(modelCode)}/validation`, params }),
  createEmotionModel: (payload: { model_code: string; model_name: string; clone_from?: string | null }) => requestData<MarketEmotionModel>({ method: 'POST', url: '/market-insights/emotion-models', data: payload }),
  updateEmotionModel: (modelCode: string, payload: Partial<Pick<MarketEmotionModel, 'model_name' | 'percentile_window_days' | 'minimum_history_days' | 'baseline_trade_days' | 'parameter_json'>>) => requestData<MarketEmotionModel>({ method: 'PATCH', url: `/market-insights/emotion-models/${encodeURIComponent(modelCode)}`, data: payload }),
  calibrateEmotionModel: (modelCode: string) => requestData<{ model: MarketEmotionModel; job_code: string; payload: Record<string, unknown> }>({ method: 'POST', url: `/market-insights/emotion-models/${encodeURIComponent(modelCode)}/calibrate` }),
  activateEmotionModel: (modelCode: string) => requestData<MarketEmotionModel>({ method: 'POST', url: `/market-insights/emotion-models/${encodeURIComponent(modelCode)}/activate` }),
};
