<template>
  <main class="workspace data-center-page">
    <header class="topbar">
      <div>
        <h1>数据中心</h1>
        <p>查看核心数据资产、最新交易日、缺口状态和最近任务运行情况。</p>
      </div>
      <n-button secondary :loading="refreshing || loading" @click="refreshCache">
        <template #icon><RefreshCw :size="16" /></template>
        刷新缓存
      </n-button>
    </header>

    <n-alert v-if="errorMessage" class="page-alert" type="error" title="数据资产加载失败">{{ errorMessage }}</n-alert>
    <n-alert v-for="note in summary?.notes || []" :key="note" class="page-alert" type="warning">{{ note }}</n-alert>

    <section class="summary-grid">
      <div class="summary-card"><span>资产项</span><strong>{{ summary?.totals.assets ?? 0 }}</strong></div>
      <div class="summary-card success"><span>正常</span><strong>{{ summary?.totals.ok ?? 0 }}</strong></div>
      <div class="summary-card warning"><span>预警</span><strong>{{ summary?.totals.warning ?? 0 }}</strong></div>
      <div class="summary-card"><span>最近交易日</span><strong>{{ summary?.latest_open_trade_date || '-' }}</strong></div>
      <div class="summary-card"><span>生成时间</span><strong>{{ formatDateTime(summary?.generated_at) }}</strong></div>
    </section>

    <section class="cache-panel">
      <div class="cache-item" v-for="item in cacheStatus?.items || []" :key="item.snapshot_key">
        <span>{{ cacheLabel(item.snapshot_key) }}</span>
        <n-tag size="small" :type="cacheTagType(item.status)" :bordered="false">{{ cacheStatusLabel(item.status) }}</n-tag>
        <small>生成 {{ formatDateTime(item.generated_at) }}</small>
        <small>过期 {{ formatDateTime(item.expires_at) }}</small>
        <small v-if="item.error_message" class="cache-error">{{ item.error_message }}</small>
      </div>
    </section>

    <section class="realtime-panel">
      <div class="panel-heading">
        <span>实时行情运行状态</span>
        <n-tag size="small" :type="realtimeHealth?.enabled ? (realtimeHealth.market_session ? 'success' : 'warning') : 'default'" :bordered="false">
          {{ realtimeLabel }} 
        </n-tag>
      </div>
      <div class="realtime-grid">
        <div><span>缓存后端</span><strong>{{ realtimeHealth?.cache_backend || '-' }}</strong></div>
        <div><span>Quote 缓存</span><strong>{{ formatNumber(realtimeHealth?.quote_cache_count) }}</strong></div>
        <div><span>Quote 过期</span><strong>{{ formatNumber(realtimeHealth?.quote_stale_count) }}</strong></div>
        <div><span>分钟登记 / 保障</span><strong>{{ formatNumber(realtimeHealth?.minute_registered_count) }} / {{ formatNumber(realtimeHealth?.minute_guaranteed_count) }}</strong></div>
        <div><span>最新 Quote 轮次</span><strong>{{ formatDateTime(realtimeHealth?.last_quote_round.finished_at) }}</strong></div>
        <div><span>Quote 覆盖</span><strong>{{ formatNumber(realtimeHealth?.last_quote_round.received_count) }} / {{ formatNumber(realtimeHealth?.last_quote_round.expected_count) }}</strong></div>
        <div><span>分钟更新 / 空分时</span><strong>{{ formatNumber(realtimeHealth?.last_minute_round.updated_count) }} / {{ formatNumber(realtimeHealth?.last_minute_round.no_intraday_data_count) }}</strong></div>
        <div><span>轮次耗时</span><strong>{{ formatNumber(realtimeHealth?.last_quote_round.duration_ms) }}ms</strong></div>
      </div>
      <n-alert v-if="realtimeHealth?.error" class="realtime-error" type="warning">{{ realtimeHealth.error }}</n-alert>
    </section>

    <section class="health-panel">
      <div class="panel-heading">
        <span>最近交易日完整性</span>
        <span class="muted">停牌/无交易会作为可解释缺口，不计入真实缺失</span>
      </div>
      <div class="health-table-wrap">
        <table class="health-table">
          <thead>
            <tr>
              <th>交易日</th>
              <th v-for="asset in healthAssets" :key="asset.asset_code">{{ asset.asset_name }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in dailyHealth?.rows || []" :key="row.trade_date">
              <td class="health-date">{{ row.trade_date }}</td>
              <td v-for="asset in healthAssets" :key="asset.asset_code">
                <button
                  v-if="cellFor(row, asset.asset_code)"
                  class="health-cell"
                  :class="`health-${cellFor(row, asset.asset_code)?.status.level || 'default'}`"
                  type="button"
                  @click="openDailyHealthGap(asset.asset_code, row.trade_date)"
                >
                  <strong>{{ cellFor(row, asset.asset_code)?.effective_completeness_pct ?? '-' }}%</strong>
                  <span>已有 {{ formatNumber(cellFor(row, asset.asset_code)?.actual_count) }}</span>
                  <span>缺 {{ formatNumber(cellFor(row, asset.asset_code)?.missing_count) }} / 解释 {{ formatNumber(cellFor(row, asset.asset_code)?.exempt_count) }}</span>
                </button>
                <span v-else class="muted">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="asset-panel">
      <div class="panel-toolbar">
        <n-tabs v-model:value="categoryFilter" type="segment" size="small">
          <n-tab-pane v-for="item in categoryOptions" :key="item.value" :name="item.value" :tab="item.label" />
        </n-tabs>
        <n-input v-model:value="keyword" clearable size="small" placeholder="搜索资产 / 表名" />
      </div>

      <n-spin :show="loading">
        <n-data-table
          :columns="assetColumns"
          :data="filteredAssets"
          :pagination="{ pageSize: 20 }"
          :scroll-x="1360"
          size="small"
          striped
        />
      </n-spin>
    </section>

    <section class="runs-panel">
      <div class="panel-heading">
        <span>最近调度运行</span>
        <span class="muted">{{ summary?.scheduler_runs.length || 0 }} 个任务</span>
      </div>
      <n-data-table
        :columns="runColumns"
        :data="summary?.scheduler_runs || []"
        :pagination="{ pageSize: 8 }"
        :scroll-x="900"
        size="small"
        striped
      />
    </section>

    <n-modal v-model:show="gapModalVisible" preset="card" class="gap-modal" :title="gapReportTitle" :bordered="false">
      <n-spin :show="gapLoading">
        <div v-if="gapReport" class="gap-summary">
          <span>日期 {{ gapReport.trade_date || '-' }}</span>
          <span>应有 {{ formatNumber(gapReport.expected_count) }}</span>
          <span>已有 {{ formatNumber(gapReport.actual_count) }}</span>
          <span>停牌解释 {{ formatNumber(gapReport.exempt_count) }}</span>
          <span>真实缺失 {{ formatNumber(gapReport.missing_count) }}</span>
        </div>
        <n-alert v-if="gapReport?.truncated" class="gap-alert" type="warning">
          缺口列表已按当前限制截断，仅展示前 {{ gapReport.rows.length }} 条。
        </n-alert>
        <n-data-table
          :columns="gapColumns"
          :data="gapReport?.rows || []"
          :pagination="{ pageSize: 20 }"
          :scroll-x="760"
          size="small"
          striped
        />
      </n-spin>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue';
import { NAlert, NButton, NDataTable, NInput, NModal, NSpin, NTabPane, NTabs, NTag, useMessage, type DataTableColumns } from 'naive-ui';
import { RefreshCw } from 'lucide-vue-next';
import { dataAssetsApi } from '@/api/data-assets';
import type {
  DataAssetCacheStatusReport,
  DataAssetDailyHealthCell,
  DataAssetDailyHealthReport,
  DataAssetDailyHealthRow,
  DataAssetGapReport,
  DataAssetGapRow,
  DataAssetItem,
  DataAssetSummary,
  RealtimeHealth,
  SchedulerRunBrief,
} from '@/types/data-assets';

const loading = ref(false);
const refreshing = ref(false);
const summary = ref<DataAssetSummary | null>(null);
const dailyHealth = ref<DataAssetDailyHealthReport | null>(null);
const cacheStatus = ref<DataAssetCacheStatusReport | null>(null);
const realtimeHealth = ref<RealtimeHealth | null>(null);
const errorMessage = ref('');
const keyword = ref('');
const categoryFilter = ref('all');
const gapLoading = ref(false);
const gapModalVisible = ref(false);
const gapReport = ref<DataAssetGapReport | null>(null);
const message = useMessage();

const realtimeLabel = computed(() => {
  if (!realtimeHealth.value?.enabled) return '未启用';
  return realtimeHealth.value.market_session ? '盘中运行' : '等待交易时段';
});

const categoryOptions = [
  { label: '全部', value: 'all' },
  { label: '主数据', value: 'master' },
  { label: '日频事实', value: 'daily_fact' },
  { label: '分钟快照', value: 'minute_snapshot' },
  { label: 'Derived', value: 'derived' },
];

const filteredAssets = computed(() => {
  const term = keyword.value.trim().toLowerCase();
  return (summary.value?.assets || []).filter((asset) => {
    const categoryMatched = categoryFilter.value === 'all' || asset.category === categoryFilter.value;
    const keywordMatched = !term
      || asset.asset_name.toLowerCase().includes(term)
      || asset.asset_code.toLowerCase().includes(term)
      || asset.table_name.toLowerCase().includes(term);
    return categoryMatched && keywordMatched;
  });
});

const healthAssets = computed(() => {
  const firstRow = dailyHealth.value?.rows?.[0];
  return firstRow?.cells || [];
});

const assetColumns = computed<DataTableColumns<DataAssetItem>>(() => [
  {
    title: '资产',
    key: 'asset_name',
    fixed: 'left',
    width: 210,
    render: (row) => h('div', { class: 'asset-name-cell' }, [
      h('strong', row.asset_name),
      h('code', row.asset_code),
    ]),
  },
  { title: '表', key: 'table_name', width: 220, render: (row) => h('code', row.table_name) },
  { title: '分类', key: 'category', width: 100, render: (row) => categoryLabel(row.category) },
  { title: '阶段', key: 'data_phase', width: 120, render: (row) => row.data_phase || '-' },
  {
    title: '生产任务',
    key: 'producer_job_codes',
    width: 240,
    render: (row) => row.producer_job_codes.length
      ? h('div', { class: 'producer-cell' }, row.producer_job_codes.slice(0, 4).map((code) => h('code', code)))
      : '-',
  },
  { title: '频率', key: 'frequency', width: 90 },
  { title: '行数', key: 'row_count', width: 120, align: 'right', render: (row) => formatNumber(row.row_count) },
  { title: '最新日期', key: 'latest_trade_date', width: 130, render: (row) => row.latest_trade_date || formatDate(row.latest_at) },
  { title: '最新数量', key: 'latest_count', width: 110, align: 'right', render: (row) => row.latest_count == null ? '-' : formatNumber(row.latest_count) },
  {
    title: '完整率',
    key: 'coverage',
    width: 180,
    render: (row) => row.coverage ? h('div', { class: 'coverage-cell' }, [
      h('strong', `${row.coverage.effective_completeness_pct ?? row.coverage.completeness_pct ?? '-'}%`),
      h('span', coverageText(row)),
    ]) : '-',
  },
  {
    title: '状态',
    key: 'status',
    width: 110,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: statusTagType(row.status.level) }, { default: () => row.status.label }),
  },
  {
    title: '补充信息',
    key: 'warnings',
    minWidth: 260,
    render: (row) => {
      const metrics = row.metrics.map((metric) => `${metric.label}: ${metric.value ?? '-'}${metric.unit || ''}`);
      const warnings = row.warnings.length ? row.warnings : metrics;
      const nodes = warnings.slice(0, 3).map((text) => h('span', text));
      if (row.coverage) {
        nodes.push(h(NButton, { size: 'tiny', text: true, type: 'primary', onClick: () => void openGaps(row) }, { default: () => '查看缺口' }));
      }
      return h('div', { class: 'warning-cell' }, nodes);
    },
  },
]);

const runColumns = computed<DataTableColumns<SchedulerRunBrief>>(() => [
  { title: '任务', key: 'job_name', minWidth: 220, render: (row) => h('div', { class: 'asset-name-cell' }, [h('strong', row.job_name || row.job_code), h('code', row.job_code)]) },
  { title: '状态', key: 'status', width: 110, render: (row) => h(NTag, { size: 'small', bordered: false, type: runTagType(row.status) }, { default: () => row.status || 'no-run' }) },
  { title: '开始时间', key: 'started_at', width: 180, render: (row) => formatDateTime(row.started_at) },
  { title: '结束时间', key: 'finished_at', width: 180, render: (row) => formatDateTime(row.finished_at) },
  { title: '错误', key: 'error_code', minWidth: 240, render: (row) => row.error_code ? `${row.error_code}: ${row.error_message || ''}` : '-' },
]);

const gapColumns = computed<DataTableColumns<DataAssetGapRow>>(() => [
  { title: '代码', key: 'stock_code', width: 120, render: (row) => h('code', row.stock_code) },
  { title: '名称', key: 'stock_name', minWidth: 150, render: (row) => row.stock_name || '-' },
  { title: '交易所', key: 'exchange', width: 90, render: (row) => row.exchange || '-' },
  { title: '状态', key: 'status', width: 90, render: (row) => row.status || '-' },
  {
    title: '原因',
    key: 'reason_label',
    minWidth: 180,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: row.reason === 'missing_data' ? 'warning' : 'info' }, { default: () => row.reason_label }),
  },
]);

const gapReportTitle = computed(() => gapReport.value ? `${gapReport.value.asset_name}缺口` : '数据缺口');

function categoryLabel(category: string) {
  return ({ master: '主数据', daily_fact: '日频事实', minute_snapshot: '分钟快照', derived: 'Derived' } as Record<string, string>)[category] || category;
}

function statusTagType(level: string) {
  if (level === 'success') return 'success';
  if (level === 'error') return 'error';
  if (level === 'warning') return 'warning';
  return 'default';
}

function runTagType(status: string | null) {
  if (status === 'success') return 'success';
  if (status === 'failed' || status === 'cancelled') return 'error';
  if (status === 'running') return 'info';
  if (status === 'partial' || status === 'skipped') return 'warning';
  return 'default';
}

function cacheLabel(snapshotKey: string) {
  return ({ summary: '资产总览缓存', daily_health: '交易日完整性缓存' } as Record<string, string>)[snapshotKey] || snapshotKey;
}

function cacheStatusLabel(status: string | null) {
  return ({ success: '正常', failed: '失败', missing: '未生成', disabled: '已关闭' } as Record<string, string>)[status || ''] || (status || '未知');
}

function cacheTagType(status: string | null) {
  if (status === 'success') return 'success';
  if (status === 'failed') return 'error';
  if (status === 'missing') return 'warning';
  return 'default';
}

function formatNumber(value: number | null | undefined) {
  return value == null ? '-' : value.toLocaleString('zh-CN');
}

function formatDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : '-';
}

function formatDateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-';
}

function coverageText(row: DataAssetItem) {
  const coverage = row.coverage;
  if (!coverage) return '';
  return `已有 ${formatNumber(coverage.actual_count)} / 应有 ${formatNumber(coverage.expected_count)}，停牌 ${formatNumber(coverage.exempt_count)}，缺 ${formatNumber(coverage.missing_count)}`;
}

function cellFor(row: DataAssetDailyHealthRow, assetCode: string): DataAssetDailyHealthCell | undefined {
  return row.cells.find((cell) => cell.asset_code === assetCode);
}

function openDailyHealthGap(assetCode: string, tradeDate: string) {
  const asset = summary.value?.assets.find((item) => item.asset_code === assetCode);
  if (!asset?.coverage) return;
  void openGaps({ ...asset, latest_trade_date: tradeDate, coverage: { ...asset.coverage, trade_date: tradeDate } });
}

async function openGaps(row: DataAssetItem) {
  gapModalVisible.value = true;
  gapLoading.value = true;
  gapReport.value = null;
  try {
    gapReport.value = await dataAssetsApi.gaps(row.asset_code, {
      trade_date: row.coverage?.trade_date || row.latest_trade_date,
      limit: 500,
    });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺口加载失败';
    gapModalVisible.value = false;
  } finally {
    gapLoading.value = false;
  }
}

async function loadSummary() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const [loadedSummary, loadedDailyHealth, loadedCacheStatus, loadedRealtimeHealth] = await Promise.all([
      dataAssetsApi.summary(),
      dataAssetsApi.dailyHealth({ days: 3 }),
      dataAssetsApi.cacheStatus(),
      dataAssetsApi.realtimeHealth(),
    ]);
    summary.value = loadedSummary;
    dailyHealth.value = loadedDailyHealth;
    cacheStatus.value = loadedCacheStatus;
    realtimeHealth.value = loadedRealtimeHealth;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据中心加载失败';
  } finally {
    loading.value = false;
  }
}

async function refreshCache() {
  refreshing.value = true;
  errorMessage.value = '';
  try {
    const result = await dataAssetsApi.refresh({ days: 3, snapshot_key: 'all', async: true });
    message.success('数据资产缓存刷新已提交后台执行');
    if ('message' in result && result.message) {
      cacheStatus.value = await dataAssetsApi.cacheStatus();
    }
    window.setTimeout(() => {
      void loadSummary();
    }, 5000);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据中心缓存刷新失败';
  } finally {
    refreshing.value = false;
  }
}

onMounted(() => {
  void loadSummary();
});
</script>

<style scoped>
.data-center-page { padding: 22px 24px 24px; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
.topbar h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
.topbar p { margin: 6px 0 0; color: #667085; }
.page-alert { margin-bottom: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 12px; margin-bottom: 14px; }
.summary-card { min-height: 76px; border: 1px solid #d8e0e5; background: #fff; padding: 12px; display: grid; gap: 6px; align-content: center; }
.summary-card span { color: #667085; font-size: 12px; }
.summary-card strong { color: #1f2933; font-size: 22px; line-height: 1.1; }
.summary-card.success strong { color: #17975b; }
.summary-card.warning strong { color: #b7791f; }
.cache-panel { border: 1px solid #d8e0e5; background: #fff; padding: 10px 12px; display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin-bottom: 14px; }
.cache-item { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; color: #667085; font-size: 12px; }
.cache-item > span { color: #344054; font-weight: 700; }
.cache-error { color: #b42318; max-width: 520px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-panel, .runs-panel, .health-panel, .realtime-panel { border: 1px solid #d8e0e5; background: #fff; padding: 14px; margin-top: 14px; }
.realtime-grid { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 10px; }
.realtime-grid div { min-width: 0; border: 1px solid #e4e9ee; background: #f8fafb; padding: 9px; display: grid; gap: 4px; }
.realtime-grid span { color: #667085; font-size: 12px; }
.realtime-grid strong { color: #1f2933; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.realtime-error { margin-top: 10px; }
.panel-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.panel-toolbar :deep(.n-input) { width: 260px; }
.panel-heading { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; font-weight: 700; color: #344054; }
.asset-name-cell { display: grid; gap: 2px; min-width: 0; }
.asset-name-cell strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-name-cell code { color: #667085; font-size: 12px; }
.producer-cell { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.producer-cell code { color: #667085; font-size: 11px; background: #f3f6f8; border: 1px solid #e4e9ee; padding: 1px 4px; }
.warning-cell { display: grid; gap: 2px; color: #667085; font-size: 12px; line-height: 1.45; }
.coverage-cell { display: grid; gap: 2px; min-width: 0; }
.coverage-cell strong { color: #1f2933; font-size: 13px; }
.coverage-cell span { color: #667085; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gap-modal { width: min(920px, calc(100vw - 32px)); }
.gap-summary { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 12px; color: #475467; font-size: 13px; }
.gap-alert { margin-bottom: 12px; }
.muted { color: #98a2b3; font-size: 12px; font-weight: 400; }
.health-table-wrap { overflow-x: auto; }
.health-table { width: 100%; min-width: 1180px; border-collapse: collapse; table-layout: fixed; }
.health-table th,
.health-table td { border-bottom: 1px solid #eef2f5; padding: 8px; text-align: left; vertical-align: top; }
.health-table th { color: #667085; font-size: 12px; font-weight: 700; background: #f8fafb; }
.health-date { color: #344054; font-weight: 700; width: 112px; }
.health-cell { width: 100%; border: 1px solid #e4e9ee; background: #fff; display: grid; gap: 2px; padding: 8px; text-align: left; cursor: pointer; }
.health-cell strong { color: #1f2933; font-size: 14px; line-height: 1.2; }
.health-cell span { color: #667085; font-size: 12px; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.health-success { border-color: #c8ead9; background: #f3fbf6; }
.health-warning { border-color: #f0d79d; background: #fff9eb; }
.health-error { border-color: #f2b8b5; background: #fff5f5; }
@media (max-width: 980px) {
  .data-center-page { padding: 14px; }
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .realtime-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .panel-toolbar { align-items: stretch; flex-direction: column; }
  .panel-toolbar :deep(.n-input) { width: 100%; }
}
</style>
