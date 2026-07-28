<template>
  <main class="workspace post-close-review-page">
    <header class="topbar">
      <div>
        <div class="eyebrow">收盘后日频事实</div>
        <h1>每日盘后报告</h1>
        <p>按同一交易日读取已沉淀的涨停、跌停、炸板、连板生态、题材与规则化市场状态；与盘中 Quote 驾驶舱分开，所有结论都可回查到日频事实。</p>
      </div>
      <div class="header-actions">
        <n-tag :type="structure?.available ? 'success' : 'warning'" :bordered="false">{{ structure?.available ? '日频事实已完成' : '等待事件完成' }}</n-tag>
        <div class="date-selector">
          <span>报告日</span>
          <n-input v-model:value="requestedTradeDate" size="small" clearable placeholder="YYYY-MM-DD" @keyup.enter="applyTradeDate" />
        </div>
        <div class="round-meta"><span>当前事实日</span><strong>{{ reportTradeDate || '尚未确定' }}</strong></div>
        <n-button secondary :loading="loading" @click="applyTradeDate">查看</n-button>
        <n-button v-if="activeTradeDate" tertiary :disabled="loading" @click="returnToLatest">回到最新</n-button>
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
          <article class="summary-card coverage-card"><span>日线覆盖</span><strong>{{ formatPercent(structure.daily_bar_coverage_pct) }}</strong><small>报告日可用日 K / active 股票</small></article>
        </section>

        <section class="report-context">
          <article class="report-context-card">
            <span>报告事实完成度</span>
            <strong>{{ completedReportBlockCount }}/{{ reportBlocks.length }}</strong>
            <small>只把已入库、同一交易日的事实纳入报告</small>
          </article>
          <article class="report-context-card market-state">
            <span>规则市场状态</span>
            <strong>{{ reportStage }}</strong>
            <small>{{ reportStageDetail }}</small>
          </article>
          <article v-for="block in reportBlocks" :key="block.key" class="report-context-card fact-block" :class="{ complete: block.complete }">
            <span>{{ block.label }}</span>
            <strong>{{ block.complete ? '已就绪' : '待完成' }}</strong>
            <small>{{ block.detail }}</small>
          </article>
          <article class="report-context-card boundary-card">
            <span>策略与 LLM</span>
            <strong>尚未生成</strong>
            <small>本报告暂不输出候选、买卖建议或 LLM 结论</small>
          </article>
        </section>

        <section class="surface emotion-v2-surface">
          <div class="panel-heading">
            <div><span class="panel-kicker">V2 双分情绪</span><h2>接力环境、风险偏好与周期</h2></div>
            <span class="muted">{{ emotion?.model?.model_name || '等待管理员启用 V2 模型' }}</span>
          </div>
          <template v-if="emotion?.available">
            <div class="emotion-v2-summary">
              <article class="dual-score short"><span>短线接力情绪分</span><strong>{{ formatScore(emotion.short_term_score) }}</strong><small>越高代表次日接力环境越好</small></article>
              <article class="dual-score risk"><span>大盘风险偏好分</span><strong>{{ formatScore(emotion.market_risk_on_score) }}</strong><small>越高代表全市场越支持进攻</small></article>
              <article class="emotion-stage"><span>主阶段</span><strong>{{ emotion.primary_stage_label }}</strong><small>{{ emotion.auxiliary_state_label }} · {{ emotion.trade_date }}</small></article>
              <article class="emotion-stage"><span>数据质量</span><strong>{{ emotion.status === 'degraded' ? '降级可用' : '完整' }}</strong><small>日线覆盖 {{ formatPercent(numberValue(emotion.coverage?.daily_bar_coverage_pct)) }}</small></article>
            </div>
            <div class="stage-evidence"><span v-for="item in emotion.stage_evidence || []" :key="`${item.rule}-${item.detail}`"><b>{{ item.rule }}</b>{{ item.detail }}</span></div>
            <div class="emotion-scorecard-grid">
              <article v-for="card in emotionScorecards" :key="card.key" class="emotion-card"><div class="emotion-card-head"><strong>{{ card.label }}</strong><b>{{ formatScore(card.score) }}</b></div><div class="emotion-metric-list"><div v-for="item in Object.entries(card.items)" :key="item[0]" class="emotion-metric"><span>{{ item[1].label || item[0] }}</span><b>{{ item[1].available ? `${formatScore(item[1].score)} 分` : '暂缺' }}</b><small>原始 {{ formatRaw(item[1].raw_value) }} {{ item[1].unit || '' }} · 120 日分位 {{ formatPercent(item[1].percentile_120d) }} · 贡献 {{ formatScore(item[1].contribution) }}</small></div></div></article>
            </div>
            <details class="emotion-details"><summary>查看全部 V2 指标、来源与公式</summary><div class="emotion-details-table"><article v-for="metric in emotionMetrics" :key="metric.key"><strong>{{ metric.value.label || metric.key }}</strong><span>原始 {{ formatRaw(metric.value.raw_value) }} {{ metric.value.unit || '' }}</span><span>分位 {{ formatPercent(metric.value.percentile_120d) }} · 得分 {{ formatScore(metric.value.score) }}</span><small>{{ metric.value.formula || '-' }} · 来源 {{ metric.value.source || '-' }} · {{ metric.value.freshness || '-' }}</small></article></div></details>
            <div class="external-confirmation"><b>辅助确认（不参与评分）</b><span>北向持仓最新披露日 {{ String(emotion.external_confirmations?.north_hold_latest_trade_date || '未披露') }}</span><span>两融最新披露日 {{ String(emotion.external_confirmations?.margin_latest_trade_date || '未披露') }}</span></div>
          </template>
          <n-alert v-else type="info" :show-icon="true">{{ emotionUnavailableLabel }}</n-alert>
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

        <section class="surface theme-surface">
          <div class="panel-heading">
            <div><span class="panel-kicker">概念主线</span><h2>收盘热点与板块龙头</h2></div>
            <span class="muted">由成分股日线、资金流与涨停直接聚合</span>
          </div>
          <div v-if="dailyReview?.sectors?.length" class="theme-grid">
            <article v-for="sector in dailyReview.sectors" :key="sector.sector_code" class="theme-card">
              <div class="theme-title"><span>#{{ sector.heat_rank }}</span><strong>{{ sector.sector_name }}</strong><b>{{ formatScore(sector.heat_score) }}</b></div>
              <div class="theme-metrics"><span>均涨 <i :class="changeClass(sector.metrics.average_change_pct)">{{ formatPercent(sector.metrics.average_change_pct) }}</i></span><span>上涨 {{ formatInteger(sector.metrics.rising_stock_count) }}/{{ formatInteger(sector.metrics.priced_component_count) }}</span><span>涨停 {{ formatInteger(sector.metrics.limit_up_stock_count) }}</span></div>
              <div v-if="sector.leaders.length" class="theme-leaders">
                <span v-for="leader in sector.leaders" :key="leader.stock_code" :class="{ limit: leader.is_limit_up }">{{ leader.stock_name }} <i :class="changeClass(leader.change_pct)">{{ formatPercent(leader.change_pct) }}</i></span>
              </div>
            </article>
          </div>
          <n-alert v-else type="info" :show-icon="true">{{ dailyReviewUnavailableLabel }}</n-alert>
          <p class="panel-note">热度是同日概念间的相对排序，不是策略评分；它刻意不依赖可能晚发布的 `ths_daily` 板块日 K。</p>
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
              <p>情绪分、概念热度和龙头由可审计规则生成；涨停关联会展示概念归属、龙虎榜和已沉淀公告，但它们不是“涨停原因”的因果断言。新闻归因、买卖建议与 LLM 分析尚未生成。</p>
            </article>
          </aside>
        </section>

        <section class="surface evidence-surface">
          <div class="panel-heading">
            <div><span class="panel-kicker">涨停关联证据</span><h2>概念归属、龙虎榜与已沉淀公告</h2></div>
            <span class="muted">{{ dailyReview?.coverage?.limit_up_evidence_count || 0 }}/{{ dailyReview?.coverage?.limit_up_evidence_expected_count || 0 }} 只已生成快照</span>
          </div>
          <div v-if="dailyReview?.limit_up_evidence?.length" class="evidence-list">
            <article v-for="item in dailyReview.limit_up_evidence" :key="item.stock_code" class="evidence-card">
              <div class="evidence-stock"><strong>{{ item.stock_name || item.stock_code }}</strong><span>{{ item.stock_code }} · {{ item.board_count || 1 }} 板 · <i class="up">{{ formatPercent(numberValue(item.market_snapshot.change_pct)) }}</i></span></div>
              <div class="evidence-context"><span v-for="sector in item.sector_context" :key="sector.sector_code">概念 #{{ sector.heat_rank }} {{ sector.sector_name }}</span><small v-if="!item.sector_context.length">未关联至当日有效热点概念</small></div>
              <div class="evidence-source"><span v-if="item.evidence.lhb?.records?.length">龙虎榜：{{ item.evidence.lhb.records.map((record) => record.reason).join('；') }}</span><span v-else>龙虎榜：{{ item.evidence.lhb?.complete ? '当日无已沉淀记录' : '未完成/未发布' }}</span><span v-if="item.evidence.announcements?.records?.length">公告：{{ item.evidence.announcements.records.map((record) => record.title).join('；') }}</span><span v-else>公告：仅查已沉淀记录，当前无可用条目</span></div>
            </article>
          </div>
          <n-alert v-else type="info" :show-icon="true">{{ dailyReviewUnavailableLabel }}</n-alert>
        </section>
      </template>
      <n-empty v-else description="等待最近交易日的涨跌停事件事实" />
    </n-spin>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { NAlert, NButton, NEmpty, NInput, NSpin, NTag, useMessage } from 'naive-ui';
import { RefreshCw } from 'lucide-vue-next';
import { marketInsightApi } from '@/api/market-insight';
import { realtimeMarketApi } from '@/api/realtime-market';
import type { MarketDailyReview, MarketDailySentiment, MarketEmotionDaily, MarketEmotionScorecard } from '@/types/market-insight';
import type { PostCloseMarketStructure } from '@/types/realtime-market';

const message = useMessage();
const loading = ref(false);
const structure = ref<PostCloseMarketStructure | null>(null);
const sentiment = ref<MarketDailySentiment | null>(null);
const emotion = ref<MarketEmotionDaily | null>(null);
const dailyReview = ref<MarketDailyReview | null>(null);
const requestedTradeDate = ref('');
const activeTradeDate = ref<string | undefined>();
let refreshTimer: number | null = null;
let loadSequence = 0;

const summary = computed(() => structure.value?.summary || null);
const reportTradeDate = computed(() => (
  structure.value?.trade_date
  || emotion.value?.trade_date
  || sentiment.value?.trade_date
  || dailyReview.value?.trade_date
  || activeTradeDate.value
  || null
));
const reportBlocks = computed(() => [
  {
    key: 'structure',
    label: '涨跌停与连板',
    complete: Boolean(structure.value?.available),
    detail: structure.value?.available ? '涨停、跌停、炸板与梯队' : '等待涨跌停事件 Raw 完成标记',
  },
  {
    key: 'emotion',
    label: 'V2 双分情绪',
    complete: Boolean(emotion.value?.available),
    detail: emotion.value?.available ? `${emotion.value.primary_stage_label} · ${emotion.value.status === 'degraded' ? '降级可用' : '完整'}` : '等待模型或当日计算完成',
  },
  {
    key: 'theme',
    label: '题材与证据',
    complete: Boolean(dailyReview.value?.available),
    detail: dailyReview.value?.available ? '概念热度、龙头与关联证据' : '等待报告事实生成',
  },
]);
const completedReportBlockCount = computed(() => reportBlocks.value.filter((item) => item.complete).length);
const reportStage = computed(() => (
  emotion.value?.available ? emotion.value.primary_stage_label : sentiment.value?.available ? sentiment.value.stage_label || '规则状态待定' : '待完成'
));
const reportStageDetail = computed(() => (
  emotion.value?.available
    ? `短线 ${formatScore(emotion.value.short_term_score)} · 风险偏好 ${formatScore(emotion.value.market_risk_on_score)}`
    : sentiment.value?.available
      ? `V1 情绪分 ${formatScore(sentiment.value.sentiment_score)}`
      : '不以缺失数据推断市场阶段'
));
const unavailableLabel = computed(() => ({
  daily_bar_unavailable: '所选报告日尚无日线事实，无法确定盘后结构。',
  limit_event_ingest_incomplete: '涨跌停/炸板事件尚未完成入库，系统不会把零行误判为无事件。',
  post_close_structure_load_failed: '盘后事件事实暂时无法读取，请稍后重试。',
}[String(structure.value?.reason)] || '等待最近交易日的涨跌停事件事实。'));
const sentimentComponents = computed(() => Object.entries(sentiment.value?.components || {}).map(([key, component]) => ({ key, ...component })));
const emotionScorecards = computed(() => Object.entries(emotion.value?.scorecards || {}).map(([key, card]) => ({ key, ...(card as MarketEmotionScorecard) })));
const emotionMetrics = computed(() => Object.entries(emotion.value?.metrics || {}).map(([key, value]) => ({ key, value })));
const emotionUnavailableLabel = computed(() => {
  if (emotion.value?.reason === 'market_emotion_model_not_active') return '尚未启用 V2 情绪模型。请先在“情绪模型”完成 250 日基线校准，并由管理员确认启用。';
  if (emotion.value?.reason === 'market_emotion_not_calculated') return '已启用 V2 模型，但当日双分尚未由 22:15 盘后任务计算。';
  if (emotion.value?.status === 'pending') return '当日日线或涨跌停事件完成门槛不足，系统不会用零值生成双分。';
  return '等待 V2 双分情绪事实完成。';
});
const sentimentUnavailableLabel = computed(() => {
  const reasons = sentiment.value?.coverage?.unavailable_reasons || [];
  if (reasons.includes('daily_bar_coverage_below_threshold')) return '日线覆盖率尚未达到 95%，不会生成不完整的情绪分。';
  if (reasons.includes('limit_event_ingest_incomplete')) return '涨跌停/炸板 Raw 完成标记尚未到位，情绪分保持待完成。';
  return sentiment.value?.reason === 'market_sentiment_not_calculated'
    ? '每日情绪任务尚未运行。可在调度中心执行“计算每日市场情绪事实”，历史首次使用时请按日期范围回填。'
    : '等待每日市场情绪事实完成。';
});
const dailyReviewUnavailableLabel = computed(() => {
  if (dailyReview.value?.reason === 'market_sentiment_pending') return '市场情绪事实尚未完成，热点与涨停证据保持待生成。';
  if (dailyReview.value?.reason === 'sector_heat_not_calculated') return '每日市场报告任务尚未生成概念热度；可在调度中心执行“生成每日市场报告事实”。';
  if (dailyReview.value?.reason === 'limit_up_evidence_incomplete') return '涨停关联证据尚未全部沉淀，请等待任务完成。';
  return '等待每日市场报告事实完成。';
});

async function loadReview(silent = false) {
  const sequence = ++loadSequence;
  const selectedTradeDate = activeTradeDate.value;
  if (!silent) loading.value = true;
  try {
    const structureResult = await realtimeMarketApi.postCloseStructure(selectedTradeDate ? { trade_date: selectedTradeDate } : undefined)
      .then((value) => ({ status: 'fulfilled' as const, value }))
      .catch((reason) => ({ status: 'rejected' as const, reason }));
    if (sequence !== loadSequence) return;
    if (structureResult.status === 'fulfilled') {
      structure.value = structureResult.value;
    } else if (!silent) {
      message.warning(structureResult.reason instanceof Error ? structureResult.reason.message : '读取盘后市场事实失败');
    }
    // When no date was chosen, resolve the report date from the structure
    // first.  Every remaining card then queries that exact persisted date,
    // avoiding a mixed latest/latest-1 report during an ingest boundary.
    const factTradeDate = selectedTradeDate || (structureResult.status === 'fulfilled' ? structureResult.value.trade_date || undefined : undefined);
    const factParams = factTradeDate ? { trade_date: factTradeDate } : undefined;
    const [sentimentResult, emotionResult, reviewResult] = await Promise.allSettled([
      marketInsightApi.dailySentiment(factParams),
      marketInsightApi.emotionDaily(factParams),
      marketInsightApi.dailyReview(factParams),
    ]);
    if (sequence !== loadSequence) return;
    if (sentimentResult.status === 'fulfilled') {
      sentiment.value = sentimentResult.value;
    } else if (!silent) {
      message.warning(sentimentResult.reason instanceof Error ? sentimentResult.reason.message : '读取每日情绪事实失败');
    }
    if (emotionResult.status === 'fulfilled') {
      emotion.value = emotionResult.value;
    } else if (!silent) {
      message.warning(emotionResult.reason instanceof Error ? emotionResult.reason.message : '读取 V2 双分情绪失败');
    }
    if (reviewResult.status === 'fulfilled') {
      dailyReview.value = reviewResult.value;
    } else if (!silent) {
      message.warning(reviewResult.reason instanceof Error ? reviewResult.reason.message : '读取每日市场报告事实失败');
    }
  } finally {
    if (!silent && sequence === loadSequence) loading.value = false;
  }
}

function normalizeTradeDate(value: string): string | undefined | null {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return null;
  return trimmed;
}

function resetRefreshTimer() {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (!activeTradeDate.value) refreshTimer = window.setInterval(() => void loadReview(true), 60_000);
}

function applyTradeDate() {
  const normalized = normalizeTradeDate(requestedTradeDate.value);
  if (normalized === null) {
    message.warning('报告日格式应为 YYYY-MM-DD。');
    return;
  }
  activeTradeDate.value = normalized;
  requestedTradeDate.value = normalized || '';
  resetRefreshTimer();
  void loadReview(false);
}

function returnToLatest() {
  activeTradeDate.value = undefined;
  requestedTradeDate.value = '';
  resetRefreshTimer();
  void loadReview(false);
}

function formatInteger(value: number | null | undefined) { return typeof value === 'number' ? value.toLocaleString('zh-CN') : '-'; }
function formatPercent(value: number | null | undefined) { return typeof value === 'number' ? `${value.toFixed(2)}%` : '-'; }
function formatScore(value: number | null | undefined) { return typeof value === 'number' ? value.toFixed(1) : '-'; }
function formatRatio(value: number | null | undefined) { return typeof value === 'number' ? `${value.toFixed(2)} 倍` : '-'; }
function formatWeight(value: number | null | undefined) { return typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : '-'; }
function formatRaw(value: number | null | undefined) { return typeof value === 'number' ? value.toFixed(Math.abs(value) < 10 ? 2 : 0) : '-'; }
function numberValue(value: unknown) { return typeof value === 'number' ? value : null; }
function changeClass(value: number | null | undefined) { return typeof value === 'number' ? (value > 0 ? 'up' : value < 0 ? 'down' : '') : ''; }
function formatAmount(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)} 亿`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(1)} 万`;
  return value.toFixed(0);
}

onMounted(() => {
  void loadReview(false);
  resetRefreshTimer();
});
onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
});
</script>

<style scoped>
.post-close-review-page { padding: 22px 24px 32px; color: #17212b; }.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 16px; }.eyebrow, .panel-kicker { color: #9a6700; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }.topbar h1 { margin: 4px 0 0; font-size: 26px; line-height: 1.2; }.topbar p { max-width: 820px; margin: 8px 0 0; color: #667085; line-height: 1.55; }.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }.date-selector { display: grid; gap: 2px; width: 132px; color: #667085; font-size: 12px; }.round-meta { display: grid; gap: 2px; text-align: right; font-size: 12px; color: #667085; }.round-meta strong { color: #344054; font-variant-numeric: tabular-nums; }.page-alert { margin-bottom: 14px; }
.review-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }.summary-card, .surface { border: 1px solid #dce5e9; background: #fff; box-shadow: 0 1px 2px rgba(16,24,40,.03); }.summary-card { min-height: 112px; padding: 14px; display: grid; align-content: start; gap: 6px; border-radius: 8px; }.summary-card.primary { border-color: #f5c77a; background: linear-gradient(135deg, #fff8e8, #fff 70%); }.summary-card span, .summary-card small { color: #667085; font-size: 12px; }.summary-card strong { color: #1d2939; font-size: 20px; font-variant-numeric: tabular-nums; }.summary-card i { font-style: normal; }.up { color: #d92d20; }.down { color: #07845f; }
.report-context { display: grid; grid-template-columns: 1.25fr 1.45fr repeat(3, minmax(0, 1fr)) 1.35fr; gap: 10px; margin-top: 14px; }.report-context-card { display: grid; align-content: start; gap: 5px; min-height: 96px; padding: 12px; border: 1px solid #dce5e9; border-radius: 8px; background: #fff; }.report-context-card > span, .report-context-card small { color: #667085; font-size: 11px; line-height: 1.45; }.report-context-card > strong { color: #344054; font-size: 17px; }.report-context-card.market-state { border-color: #b9d6f4; background: linear-gradient(135deg, #eff8ff, #fff); }.report-context-card.market-state > strong { color: #175cd3; }.report-context-card.fact-block { background: #fafbfc; }.report-context-card.fact-block.complete { border-color: #a7e0c2; background: #f0fdf4; }.report-context-card.fact-block.complete > strong { color: #027a48; }.report-context-card.boundary-card { border-color: #f0d7a0; background: #fffcf5; }.report-context-card.boundary-card > strong { color: #9a6700; }
.emotion-v2-surface,.sentiment-surface { margin-top: 14px; }.emotion-v2-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.dual-score,.emotion-stage{display:grid;gap:6px;min-height:110px;padding:13px;border-radius:8px}.dual-score{color:#fff}.dual-score.short{background:linear-gradient(145deg,#7c2d12,#ea580c)}.dual-score.risk{background:linear-gradient(145deg,#0f766e,#0ea5a4)}.dual-score span,.dual-score small,.emotion-stage span,.emotion-stage small{font-size:12px}.dual-score small{color:rgba(255,255,255,.76)}.dual-score strong{font-size:34px;line-height:1;font-variant-numeric:tabular-nums}.emotion-stage{border:1px solid #dce7ef;background:#f8fbff}.emotion-stage span,.emotion-stage small{color:#667085}.emotion-stage strong{color:#1d4ed8;font-size:21px}.stage-evidence{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.stage-evidence span{display:flex;gap:6px;padding:5px 8px;border-radius:5px;color:#475467;background:#f2f4f7;font-size:12px}.stage-evidence b{color:#b54708}.emotion-scorecard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}.emotion-card{padding:11px;border:1px solid #e1e8ee;border-radius:8px}.emotion-card-head{display:flex;align-items:center;justify-content:space-between}.emotion-card-head strong{font-size:14px}.emotion-card-head b{color:#b54708;font-size:22px}.emotion-metric-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:8px}.emotion-metric{display:grid;gap:3px;padding:7px;border-radius:5px;background:#f8fafc}.emotion-metric span,.emotion-metric small{color:#667085;font-size:11px}.emotion-metric b{color:#1d2939;font-size:13px}.emotion-details{margin-top:11px;padding-top:10px;border-top:1px solid #eaecf0}.emotion-details summary{cursor:pointer;color:#175cd3;font-size:12px}.emotion-details-table{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:9px}.emotion-details-table article{display:grid;gap:3px;padding:8px;border:1px solid #e4e9ef;border-radius:5px}.emotion-details-table strong{font-size:12px}.emotion-details-table span,.emotion-details-table small{color:#667085;font-size:10px;line-height:1.45}.external-confirmation{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;color:#667085;font-size:11px}.external-confirmation b{color:#475467}.sentiment-layout { display: grid; grid-template-columns: 140px minmax(160px, .8fr) minmax(260px, 1.3fr); gap: 12px; align-items: stretch; }.sentiment-score { display: grid; align-content: center; justify-items: center; min-height: 118px; border-radius: 8px; color: #fff; background: linear-gradient(145deg, #172554, #1d4ed8); }.sentiment-score strong { font-size: 38px; line-height: 1; font-variant-numeric: tabular-nums; }.sentiment-score span, .stage-card span, .stage-card small, .sentiment-facts span, .component-card span, .component-card small { font-size: 12px; }.sentiment-score span { margin-top: 7px; color: #bfdbfe; }.stage-card, .sentiment-facts { display: grid; align-content: center; gap: 6px; padding: 15px; border: 1px solid #dbe7f2; border-radius: 8px; background: #f8fbff; }.stage-card span, .stage-card small, .sentiment-facts span, .component-card span, .component-card small { color: #667085; }.stage-card strong { color: #1d4ed8; font-size: 22px; }.sentiment-facts { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }.sentiment-facts span { display: grid; gap: 4px; }.sentiment-facts b { color: #17212b; font-size: 15px; font-variant-numeric: tabular-nums; }.sentiment-facts b.up { color: #d92d20; }.sentiment-facts b.down { color: #07845f; }.component-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 9px; margin-top: 12px; }.component-card { min-height: 88px; padding: 10px; display: grid; align-content: start; gap: 5px; border: 1px solid #e3eaf0; border-radius: 7px; background: #fff; }.component-card strong { font-size: 19px; color: #1d2939; font-variant-numeric: tabular-nums; }.component-card.unavailable { opacity: .65; background: #f8fafc; }
.theme-surface, .evidence-surface { margin-top: 14px; }.theme-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.theme-card { display: grid; gap: 8px; min-height: 118px; padding: 11px; border: 1px solid #e4e9ef; border-radius: 8px; background: linear-gradient(145deg, #fff, #f8fbff); }.theme-title { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 7px; }.theme-title > span { color: #667085; font-size: 12px; }.theme-title strong { overflow: hidden; color: #1d2939; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }.theme-title b { color: #b54708; font-size: 17px; font-variant-numeric: tabular-nums; }.theme-metrics { display: flex; flex-wrap: wrap; gap: 7px; color: #667085; font-size: 11px; }.theme-metrics i, .theme-leaders i, .evidence-stock i { font-style: normal; }.theme-leaders { display: flex; flex-wrap: wrap; gap: 5px; }.theme-leaders span { max-width: 100%; overflow: hidden; padding: 3px 5px; color: #475467; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; border-radius: 4px; background: #f2f4f7; }.theme-leaders span.limit { color: #b42318; background: #fef3f2; }.evidence-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; max-height: 720px; overflow: auto; }.evidence-card { display: grid; gap: 8px; padding: 11px; border: 1px solid #e4e9ef; border-left: 3px solid #f79009; border-radius: 7px; }.evidence-stock { display: grid; gap: 2px; }.evidence-stock strong { color: #1d2939; font-size: 14px; }.evidence-stock span, .evidence-context, .evidence-source { color: #667085; font-size: 11px; line-height: 1.5; }.evidence-context { display: flex; flex-wrap: wrap; gap: 5px; }.evidence-context > span { padding: 2px 5px; color: #175cd3; border-radius: 4px; background: #eff8ff; }.evidence-source { display: grid; gap: 3px; }.evidence-source span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.review-grid { display: grid; grid-template-columns: minmax(0, 1.32fr) minmax(340px, .68fr); gap: 14px; margin-top: 14px; }.surface { border-radius: 8px; padding: 15px; }.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }.panel-heading h2 { margin: 3px 0 0; font-size: 17px; }.compact-heading { margin-bottom: 8px; }.muted { color: #667085; font-size: 12px; line-height: 1.5; }.ladder-list { display: grid; max-height: 680px; overflow: auto; padding-right: 4px; }.ladder-row { display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid #edf1f3; }.ladder-count { display: grid; align-content: start; gap: 2px; }.ladder-count strong { color: #d92d20; font-size: 15px; }.ladder-count span, .ladder-stocks small, .ladder-stocks em { color: #667085; font-size: 11px; font-style: normal; }.ladder-stocks { display: flex; flex-wrap: wrap; align-items: stretch; gap: 7px; }.ladder-stocks > span { display: grid; gap: 2px; min-width: 100px; padding: 7px 8px; border-left: 3px solid #f79009; background: #fff8ed; }.ladder-stocks b { max-width: 120px; overflow: hidden; color: #344054; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.ladder-stocks em { align-self: center; }.side-stack { display: grid; align-content: start; gap: 14px; }.break-list { display: grid; max-height: 450px; overflow: auto; }.break-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; min-height: 48px; align-items: center; border-bottom: 1px solid #edf1f3; }.break-row:last-child { border-bottom: 0; }.break-row > div { display: grid; gap: 2px; min-width: 0; }.break-row > div:last-child { text-align: right; }.break-row strong, .break-row span { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.break-row small { color: #667085; font-size: 11px; }.method-surface { background: #fffcf5; border-color: #f3dfae; }.method-surface h2 { margin: 4px 0 8px; font-size: 17px; }.method-surface p { margin: 8px 0 0; color: #667085; font-size: 12px; line-height: 1.65; }
@media (max-width: 1280px) { .review-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }.report-context { grid-template-columns: repeat(3, minmax(0, 1fr)); }.emotion-v2-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.sentiment-layout { grid-template-columns: 130px 1fr; }.sentiment-facts { grid-column: 1 / -1; }.component-grid, .theme-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.review-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .post-close-review-page { padding: 14px; }.topbar { flex-direction: column; }.header-actions { justify-content: flex-start; }.round-meta { text-align: left; }.review-summary, .report-context, .emotion-v2-summary, .emotion-scorecard-grid, .emotion-metric-list, .emotion-details-table, .theme-grid, .evidence-list { grid-template-columns: 1fr; }.date-selector { width: 100%; }.ladder-row { grid-template-columns: 54px minmax(0, 1fr); }.ladder-stocks > span { min-width: 92px; } }
</style>
