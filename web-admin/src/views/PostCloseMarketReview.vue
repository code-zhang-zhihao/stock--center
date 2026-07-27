<template>
  <main class="workspace post-close-review-page">
    <header class="topbar">
      <div>
        <div class="eyebrow">收盘后日频事实</div>
        <h1>盘后市场复盘</h1>
        <p>这里呈现已完成入库的涨停、跌停、炸板、连板生态和规则化市场状态；与盘中 Quote 驾驶舱分开，所有结论都可回查到日频事实。</p>
      </div>
      <div class="header-actions">
        <n-tag :type="structure?.available ? 'success' : 'warning'" :bordered="false">{{ structure?.available ? '日频事实已完成' : '等待事件完成' }}</n-tag>
        <div class="round-meta"><span>报告日</span><strong>{{ structure?.trade_date || '尚未确定' }}</strong></div>
        <n-button secondary :loading="loading" @click="loadReview(false)"><template #icon><RefreshCw :size="16" /></template>刷新事实</n-button>
      </div>
    </header>

    <n-alert v-if="!structure?.available" class="page-alert" type="warning" :show-icon="true">
      {{ unavailableLabel }}
    </n-alert>

    <n-spin :show="loading && !structure">
      <template v-if="structure?.available && summary">
        <section class="review-summary">
          <article class="summary-card primary"><span>涨停 / 跌停</span><strong><i class="up">{{ formatInteger(summary.limit_up_count) }}</i> / <i class="down">{{ formatInteger(summary.limit_down_count) }}</i></strong><small>沪深 active、非 ST 标的</small></article>
          <article class="summary-card"><span>炸板</span><strong>{{ formatInteger(summary.limit_break_count) }}</strong><small>Tushare 明确事件</small></article>
          <article class="summary-card"><span>封板率</span><strong>{{ formatPercent(summary.seal_rate_pct) }}</strong><small>涨停 ÷（涨停 + 炸板）</small></article>
          <article class="summary-card"><span>最高连板</span><strong>{{ summary.highest_board_count ? `${summary.highest_board_count} 板` : '无' }}</strong><small>{{ formatInteger(summary.highest_board_stock_count) }} 只处于最高梯队</small></article>
          <article class="summary-card coverage-card"><span>日线覆盖</span><strong>{{ formatPercent(structure.daily_bar_coverage_pct) }}</strong><small>最新日可用日 K / active 股票</small></article>
        </section>

        <section class="surface sentiment-surface">
          <div class="panel-heading">
            <div><span class="panel-kicker">规则化市场状态</span><h2>今日情绪分与阶段</h2></div>
            <span class="muted">{{ sentiment?.calculation_version ? `计算版本 ${sentiment.calculation_version}` : '等待每日情绪任务' }}</span>
          </div>
          <template v-if="sentiment?.available">
            <div class="sentiment-layout">
              <div class="sentiment-score"><strong>{{ formatScore(sentiment.sentiment_score) }}</strong><span>情绪分 / 100</span></div>
              <div class="stage-card"><span>当前阶段</span><strong>{{ sentiment.stage_label || '-' }}</strong><small>{{ sentiment.trade_date }} · 覆盖 {{ formatPercent(sentiment.coverage?.daily_bar_coverage_pct) }}</small></div>
              <div class="sentiment-facts">
                <span>昨日涨停溢价 <b :class="changeClass(sentiment.metrics?.previous_limit_up_premium_pct)">{{ formatPercent(sentiment.metrics?.previous_limit_up_premium_pct) }}</b></span>
                <span>成交额 / 5 日均值 <b>{{ formatRatio(sentiment.metrics?.amount_vs_5d_average) }}</b></span>
                <span>最高连板 <b>{{ formatInteger(sentiment.metrics?.highest_board_count) }} 板</b></span>
              </div>
            </div>
            <div class="component-grid">
              <article v-for="component in sentimentComponents" :key="component.key" :title="component.formula" class="component-card" :class="{ unavailable: !component.available }">
                <span>{{ component.label }}</span><strong>{{ component.available ? formatScore(component.score) : '暂缺' }}</strong><small>权重 {{ formatWeight(component.weight) }} · 原始值 {{ formatRaw(component.raw_value) }}</small>
              </article>
            </div>
            <p class="panel-note">评分只使用已完成的日线、涨跌停/炸板与交易日历。阶段中的“主升期”还要求连续两日高分、至少 3 板高度和昨日涨停正溢价；LLM 不参与评分。</p>
          </template>
          <n-alert v-else type="info" :show-icon="true">{{ sentimentUnavailableLabel }}</n-alert>
        </section>

        <section class="review-grid">
          <article class="surface ladder-surface">
            <div class="panel-heading">
              <div><span class="panel-kicker">连板生态</span><h2>涨停梯队</h2></div>
              <span class="muted">按连续开市日涨停分层</span>
            </div>
            <div v-if="structure.ladders.length" class="ladder-list">
              <article v-for="ladder in structure.ladders" :key="ladder.board_count" class="ladder-row">
                <div class="ladder-count"><strong>{{ ladder.board_count }} 板</strong><span>{{ ladder.stock_count }} 只</span></div>
                <div class="ladder-stocks">
                  <span v-for="stock in ladder.stocks" :key="stock.stock_code" :title="`${stock.stock_code} · 首封 ${stock.first_time || '未知'} · 炸板 ${stock.open_count ?? '未知'} 次`">
                    <b>{{ stock.stock_name || stock.stock_code }}</b>
                    <small>{{ stock.stock_code }} · {{ formatPercent(stock.change_pct) }} · {{ stock.first_time || '首封未知' }}</small>
                  </span>
                  <em v-if="ladder.truncated">仅展示前 {{ ladder.stocks.length }} 只</em>
                </div>
              </article>
            </div>
            <n-empty v-else size="small" description="该交易日已完成事件入库，且没有沪深非 ST 涨停股" />
          </article>

          <aside class="side-stack">
            <article class="surface break-surface">
              <div class="panel-heading compact-heading"><div><span class="panel-kicker">收盘事件</span><h2>炸板观察</h2></div><span class="muted">按开板次数、成交额</span></div>
              <div v-if="structure.limit_breaks.length" class="break-list">
                <div v-for="stock in structure.limit_breaks" :key="stock.stock_code" class="break-row">
                  <div><strong>{{ stock.stock_name || stock.stock_code }}</strong><small>{{ stock.stock_code }} · {{ formatPercent(stock.change_pct) }}</small></div>
                  <div><span>开板 {{ formatInteger(stock.open_count) }} 次</span><small>成交 {{ formatAmount(stock.turnover_amount) }}</small></div>
                </div>
              </div>
              <n-empty v-else size="small" description="该交易日没有炸板事件" />
            </article>

            <article class="surface method-surface">
              <span class="panel-kicker">数据边界</span>
              <h2>这是一份事实底稿</h2>
              <p>连板只来自连续交易日的 `limit_up` 记录；炸板只来自 `limit_break`。没有完成 Raw 标记时，系统不会以零值补齐。</p>
              <p>情绪分和阶段由可审计规则生成；热点原因、新闻证据、买卖建议与 LLM 分析尚未生成，避免将主观判断伪装成数据事实。</p>
            </article>
          </aside>
        </section>
      </template>
      <n-empty v-else description="等待最近交易日的涨跌停事件事实" />
    </n-spin>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { NAlert, NButton, NEmpty, NSpin, NTag, useMessage } from 'naive-ui';
import { RefreshCw } from 'lucide-vue-next';
import { marketInsightApi } from '@/api/market-insight';
import { realtimeMarketApi } from '@/api/realtime-market';
import type { MarketDailySentiment } from '@/types/market-insight';
import type { PostCloseMarketStructure } from '@/types/realtime-market';

const message = useMessage();
const loading = ref(false);
const structure = ref<PostCloseMarketStructure | null>(null);
const sentiment = ref<MarketDailySentiment | null>(null);
let refreshTimer: number | null = null;

const summary = computed(() => structure.value?.summary || null);
const unavailableLabel = computed(() => ({
  daily_bar_unavailable: '尚无最新日线事实，无法确定盘后结构。',
  limit_event_ingest_incomplete: '涨跌停/炸板事件尚未完成入库，系统不会把零行误判为无事件。',
  post_close_structure_load_failed: '盘后事件事实暂时无法读取，请稍后重试。',
}[String(structure.value?.reason)] || '等待最近交易日的涨跌停事件事实。'));
const sentimentComponents = computed(() => Object.entries(sentiment.value?.components || {}).map(([key, component]) => ({ key, ...component })));
const sentimentUnavailableLabel = computed(() => {
  const reasons = sentiment.value?.coverage?.unavailable_reasons || [];
  if (reasons.includes('daily_bar_coverage_below_threshold')) return '日线覆盖率尚未达到 95%，不会生成不完整的情绪分。';
  if (reasons.includes('limit_event_ingest_incomplete')) return '涨跌停/炸板 Raw 完成标记尚未到位，情绪分保持待完成。';
  return sentiment.value?.reason === 'market_sentiment_not_calculated'
    ? '每日情绪任务尚未运行。可在调度中心执行“计算每日市场情绪事实”，历史首次使用时请按日期范围回填。'
    : '等待每日市场情绪事实完成。';
});

async function loadReview(silent = false) {
  if (!silent) loading.value = true;
  try {
    const [structureResult, sentimentResult] = await Promise.allSettled([
      realtimeMarketApi.postCloseStructure(),
      marketInsightApi.dailySentiment(),
    ]);
    if (structureResult.status === 'fulfilled') {
      structure.value = structureResult.value;
    } else if (!silent) {
      message.warning(structureResult.reason instanceof Error ? structureResult.reason.message : '读取盘后市场事实失败');
    }
    if (sentimentResult.status === 'fulfilled') {
      sentiment.value = sentimentResult.value;
    } else if (!silent) {
      message.warning(sentimentResult.reason instanceof Error ? sentimentResult.reason.message : '读取每日情绪事实失败');
    }
  } finally {
    if (!silent) loading.value = false;
  }
}

function formatInteger(value: number | null | undefined) { return typeof value === 'number' ? value.toLocaleString('zh-CN') : '-'; }
function formatPercent(value: number | null | undefined) { return typeof value === 'number' ? `${value.toFixed(2)}%` : '-'; }
function formatScore(value: number | null | undefined) { return typeof value === 'number' ? value.toFixed(1) : '-'; }
function formatRatio(value: number | null | undefined) { return typeof value === 'number' ? `${value.toFixed(2)} 倍` : '-'; }
function formatWeight(value: number | null | undefined) { return typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : '-'; }
function formatRaw(value: number | null | undefined) { return typeof value === 'number' ? value.toFixed(Math.abs(value) < 10 ? 2 : 0) : '-'; }
function changeClass(value: number | null | undefined) { return typeof value === 'number' ? (value > 0 ? 'up' : value < 0 ? 'down' : '') : ''; }
function formatAmount(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)} 亿`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(1)} 万`;
  return value.toFixed(0);
}

onMounted(() => {
  void loadReview(false);
  refreshTimer = window.setInterval(() => void loadReview(true), 60_000);
});
onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
});
</script>

<style scoped>
.post-close-review-page { padding: 22px 24px 32px; color: #17212b; }.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 16px; }.eyebrow, .panel-kicker { color: #9a6700; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }.topbar h1 { margin: 4px 0 0; font-size: 26px; line-height: 1.2; }.topbar p { max-width: 820px; margin: 8px 0 0; color: #667085; line-height: 1.55; }.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }.round-meta { display: grid; gap: 2px; text-align: right; font-size: 12px; color: #667085; }.round-meta strong { color: #344054; font-variant-numeric: tabular-nums; }.page-alert { margin-bottom: 14px; }
.review-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }.summary-card, .surface { border: 1px solid #dce5e9; background: #fff; box-shadow: 0 1px 2px rgba(16,24,40,.03); }.summary-card { min-height: 112px; padding: 14px; display: grid; align-content: start; gap: 6px; border-radius: 8px; }.summary-card.primary { border-color: #f5c77a; background: linear-gradient(135deg, #fff8e8, #fff 70%); }.summary-card span, .summary-card small { color: #667085; font-size: 12px; }.summary-card strong { color: #1d2939; font-size: 20px; font-variant-numeric: tabular-nums; }.summary-card i { font-style: normal; }.up { color: #d92d20; }.down { color: #07845f; }
.sentiment-surface { margin-top: 14px; }.sentiment-layout { display: grid; grid-template-columns: 140px minmax(160px, .8fr) minmax(260px, 1.3fr); gap: 12px; align-items: stretch; }.sentiment-score { display: grid; align-content: center; justify-items: center; min-height: 118px; border-radius: 8px; color: #fff; background: linear-gradient(145deg, #172554, #1d4ed8); }.sentiment-score strong { font-size: 38px; line-height: 1; font-variant-numeric: tabular-nums; }.sentiment-score span, .stage-card span, .stage-card small, .sentiment-facts span, .component-card span, .component-card small { font-size: 12px; }.sentiment-score span { margin-top: 7px; color: #bfdbfe; }.stage-card, .sentiment-facts { display: grid; align-content: center; gap: 6px; padding: 15px; border: 1px solid #dbe7f2; border-radius: 8px; background: #f8fbff; }.stage-card span, .stage-card small, .sentiment-facts span, .component-card span, .component-card small { color: #667085; }.stage-card strong { color: #1d4ed8; font-size: 22px; }.sentiment-facts { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }.sentiment-facts span { display: grid; gap: 4px; }.sentiment-facts b { color: #17212b; font-size: 15px; font-variant-numeric: tabular-nums; }.sentiment-facts b.up { color: #d92d20; }.sentiment-facts b.down { color: #07845f; }.component-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 9px; margin-top: 12px; }.component-card { min-height: 88px; padding: 10px; display: grid; align-content: start; gap: 5px; border: 1px solid #e3eaf0; border-radius: 7px; background: #fff; }.component-card strong { font-size: 19px; color: #1d2939; font-variant-numeric: tabular-nums; }.component-card.unavailable { opacity: .65; background: #f8fafc; }
.review-grid { display: grid; grid-template-columns: minmax(0, 1.32fr) minmax(340px, .68fr); gap: 14px; margin-top: 14px; }.surface { border-radius: 8px; padding: 15px; }.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }.panel-heading h2 { margin: 3px 0 0; font-size: 17px; }.compact-heading { margin-bottom: 8px; }.muted { color: #667085; font-size: 12px; line-height: 1.5; }.ladder-list { display: grid; max-height: 680px; overflow: auto; padding-right: 4px; }.ladder-row { display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid #edf1f3; }.ladder-count { display: grid; align-content: start; gap: 2px; }.ladder-count strong { color: #d92d20; font-size: 15px; }.ladder-count span, .ladder-stocks small, .ladder-stocks em { color: #667085; font-size: 11px; font-style: normal; }.ladder-stocks { display: flex; flex-wrap: wrap; align-items: stretch; gap: 7px; }.ladder-stocks > span { display: grid; gap: 2px; min-width: 100px; padding: 7px 8px; border-left: 3px solid #f79009; background: #fff8ed; }.ladder-stocks b { max-width: 120px; overflow: hidden; color: #344054; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.ladder-stocks em { align-self: center; }.side-stack { display: grid; align-content: start; gap: 14px; }.break-list { display: grid; max-height: 450px; overflow: auto; }.break-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; min-height: 48px; align-items: center; border-bottom: 1px solid #edf1f3; }.break-row:last-child { border-bottom: 0; }.break-row > div { display: grid; gap: 2px; min-width: 0; }.break-row > div:last-child { text-align: right; }.break-row strong, .break-row span { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.break-row small { color: #667085; font-size: 11px; }.method-surface { background: #fffcf5; border-color: #f3dfae; }.method-surface h2 { margin: 4px 0 8px; font-size: 17px; }.method-surface p { margin: 8px 0 0; color: #667085; font-size: 12px; line-height: 1.65; }
@media (max-width: 1280px) { .review-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }.sentiment-layout { grid-template-columns: 130px 1fr; }.sentiment-facts { grid-column: 1 / -1; }.component-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.review-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .post-close-review-page { padding: 14px; }.topbar { flex-direction: column; }.header-actions { justify-content: flex-start; }.round-meta { text-align: left; }.review-summary { grid-template-columns: 1fr 1fr; }.ladder-row { grid-template-columns: 54px minmax(0, 1fr); }.ladder-stocks > span { min-width: 92px; } }
</style>
