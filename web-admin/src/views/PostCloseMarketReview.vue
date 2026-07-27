<template>
  <main class="workspace post-close-review-page">
    <header class="topbar">
      <div>
        <div class="eyebrow">收盘后日频事实</div>
        <h1>盘后市场复盘</h1>
        <p>这里呈现已完成入库的涨停、跌停、炸板和连板生态；与盘中 Quote 驾驶舱分开，后续情绪分与阶段判断将在这份可追溯事实之上建立。</p>
      </div>
      <div class="header-actions">
        <n-tag :type="structure?.available ? 'success' : 'warning'" :bordered="false">{{ structure?.available ? '日频事实已完成' : '等待事件完成' }}</n-tag>
        <div class="round-meta"><span>报告日</span><strong>{{ structure?.trade_date || '尚未确定' }}</strong></div>
        <n-button secondary :loading="loading" @click="loadStructure(false)"><template #icon><RefreshCw :size="16" /></template>刷新事实</n-button>
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
              <p>情绪分、冰点/混沌/主升阶段、热点原因与买卖建议尚未生成，避免将主观判断伪装成数据事实。</p>
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
import { realtimeMarketApi } from '@/api/realtime-market';
import type { PostCloseMarketStructure } from '@/types/realtime-market';

const message = useMessage();
const loading = ref(false);
const structure = ref<PostCloseMarketStructure | null>(null);
let refreshTimer: number | null = null;

const summary = computed(() => structure.value?.summary || null);
const unavailableLabel = computed(() => ({
  daily_bar_unavailable: '尚无最新日线事实，无法确定盘后结构。',
  limit_event_ingest_incomplete: '涨跌停/炸板事件尚未完成入库，系统不会把零行误判为无事件。',
  post_close_structure_load_failed: '盘后事件事实暂时无法读取，请稍后重试。',
}[String(structure.value?.reason)] || '等待最近交易日的涨跌停事件事实。'));

async function loadStructure(silent = false) {
  if (!silent) loading.value = true;
  try {
    structure.value = await realtimeMarketApi.postCloseStructure();
  } catch (error) {
    if (!silent) message.warning(error instanceof Error ? error.message : '读取盘后市场事实失败');
  } finally {
    if (!silent) loading.value = false;
  }
}

function formatInteger(value: number | null | undefined) { return typeof value === 'number' ? value.toLocaleString('zh-CN') : '-'; }
function formatPercent(value: number | null | undefined) { return typeof value === 'number' ? `${value.toFixed(2)}%` : '-'; }
function formatAmount(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)} 亿`;
  if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(1)} 万`;
  return value.toFixed(0);
}

onMounted(() => {
  void loadStructure(false);
  refreshTimer = window.setInterval(() => void loadStructure(true), 60_000);
});
onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
});
</script>

<style scoped>
.post-close-review-page { padding: 22px 24px 32px; color: #17212b; }.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 16px; }.eyebrow, .panel-kicker { color: #9a6700; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }.topbar h1 { margin: 4px 0 0; font-size: 26px; line-height: 1.2; }.topbar p { max-width: 820px; margin: 8px 0 0; color: #667085; line-height: 1.55; }.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }.round-meta { display: grid; gap: 2px; text-align: right; font-size: 12px; color: #667085; }.round-meta strong { color: #344054; font-variant-numeric: tabular-nums; }.page-alert { margin-bottom: 14px; }
.review-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }.summary-card, .surface { border: 1px solid #dce5e9; background: #fff; box-shadow: 0 1px 2px rgba(16,24,40,.03); }.summary-card { min-height: 112px; padding: 14px; display: grid; align-content: start; gap: 6px; border-radius: 8px; }.summary-card.primary { border-color: #f5c77a; background: linear-gradient(135deg, #fff8e8, #fff 70%); }.summary-card span, .summary-card small { color: #667085; font-size: 12px; }.summary-card strong { color: #1d2939; font-size: 20px; font-variant-numeric: tabular-nums; }.summary-card i { font-style: normal; }.up { color: #d92d20; }.down { color: #07845f; }
.review-grid { display: grid; grid-template-columns: minmax(0, 1.32fr) minmax(340px, .68fr); gap: 14px; margin-top: 14px; }.surface { border-radius: 8px; padding: 15px; }.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }.panel-heading h2 { margin: 3px 0 0; font-size: 17px; }.compact-heading { margin-bottom: 8px; }.muted { color: #667085; font-size: 12px; line-height: 1.5; }.ladder-list { display: grid; max-height: 680px; overflow: auto; padding-right: 4px; }.ladder-row { display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid #edf1f3; }.ladder-count { display: grid; align-content: start; gap: 2px; }.ladder-count strong { color: #d92d20; font-size: 15px; }.ladder-count span, .ladder-stocks small, .ladder-stocks em { color: #667085; font-size: 11px; font-style: normal; }.ladder-stocks { display: flex; flex-wrap: wrap; align-items: stretch; gap: 7px; }.ladder-stocks > span { display: grid; gap: 2px; min-width: 100px; padding: 7px 8px; border-left: 3px solid #f79009; background: #fff8ed; }.ladder-stocks b { max-width: 120px; overflow: hidden; color: #344054; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.ladder-stocks em { align-self: center; }.side-stack { display: grid; align-content: start; gap: 14px; }.break-list { display: grid; max-height: 450px; overflow: auto; }.break-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; min-height: 48px; align-items: center; border-bottom: 1px solid #edf1f3; }.break-row:last-child { border-bottom: 0; }.break-row > div { display: grid; gap: 2px; min-width: 0; }.break-row > div:last-child { text-align: right; }.break-row strong, .break-row span { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.break-row small { color: #667085; font-size: 11px; }.method-surface { background: #fffcf5; border-color: #f3dfae; }.method-surface h2 { margin: 4px 0 8px; font-size: 17px; }.method-surface p { margin: 8px 0 0; color: #667085; font-size: 12px; line-height: 1.65; }
@media (max-width: 1280px) { .review-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }.review-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .post-close-review-page { padding: 14px; }.topbar { flex-direction: column; }.header-actions { justify-content: flex-start; }.round-meta { text-align: left; }.review-summary { grid-template-columns: 1fr 1fr; }.ladder-row { grid-template-columns: 54px minmax(0, 1fr); }.ladder-stocks > span { min-width: 92px; } }
</style>
