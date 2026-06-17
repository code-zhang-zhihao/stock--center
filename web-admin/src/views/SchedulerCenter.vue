<template>
  <main class="workspace scheduler-page">
    <header class="topbar">
      <div>
        <h1>调度任务</h1>
        <p>管理任务定义、手动触发和运行记录；当前阶段只接入调度底座。</p>
      </div>
      <n-space>
        <n-button secondary :loading="loading" @click="reloadAll">
          <template #icon><RefreshCw :size="16" /></template>
        </n-button>
        <n-button secondary :loading="reloadingScheduler" @click="reloadScheduler">
          <template #icon><RotateCcw :size="16" /></template>
          重载调度器
        </n-button>
      </n-space>
    </header>

    <section class="status-strip">
      <div class="metric">
        <span>运行开关</span>
        <strong>{{ status?.enabled ? 'enabled' : 'disabled' }}</strong>
      </div>
      <div class="metric">
        <span>APScheduler</span>
        <strong>{{ status?.installed ? 'installed' : 'missing' }}</strong>
      </div>
      <div class="metric">
        <span>运行状态</span>
        <strong>{{ status?.running ? 'running' : 'stopped' }}</strong>
      </div>
      <div class="metric">
        <span>已注册任务</span>
        <strong>{{ status?.job_count ?? 0 }}</strong>
      </div>
    </section>

    <div class="content-grid">
      <section class="object-panel">
        <div class="panel-title">
          <span>任务定义</span>
          <n-checkbox v-model:checked="includeHidden">包含内部任务</n-checkbox>
        </div>
        <n-input v-model:value="keyword" clearable size="small" placeholder="筛选任务名称 / code" />
        <n-spin :show="loading">
          <n-empty v-if="filteredJobs.length === 0" description="暂无任务" />
          <div v-else class="object-list">
            <button
              v-for="job in filteredJobs"
              :key="job.job_code"
              type="button"
              class="object-item"
              :class="{ active: selectedJob?.job_code === job.job_code }"
              @click="selectJob(job.job_code)"
            >
              <div class="object-main">
                <span>{{ job.job_name }}</span>
                <code>{{ job.job_code }}</code>
              </div>
              <div class="object-meta">
                <n-tag size="small" :type="job.is_enabled ? 'success' : 'warning'" :bordered="false">
                  {{ job.is_enabled ? 'enabled' : 'disabled' }}
                </n-tag>
                <n-tag v-if="job.is_hidden" size="small" :bordered="false">hidden</n-tag>
              </div>
            </button>
          </div>
        </n-spin>
      </section>

      <section class="detail-panel">
        <n-empty v-if="!selectedJob" description="请选择一个任务" />
        <template v-else>
          <div class="detail-head">
            <div>
              <div class="title-row">
                <h2>{{ selectedJob.job_name }}</h2>
                <n-tag size="small" :type="selectedJob.is_enabled ? 'success' : 'warning'">
                  {{ selectedJob.is_enabled ? 'enabled' : 'disabled' }}
                </n-tag>
                <n-tag v-if="selectedJob.is_system" size="small" type="info">system</n-tag>
              </div>
              <div class="mono muted">{{ selectedJob.job_type }} / {{ selectedJob.job_code }}</div>
            </div>
            <n-space>
              <n-button secondary :loading="savingJobState" @click="toggleJobState">
                <template #icon><Power :size="16" /></template>
                {{ selectedJob.is_enabled ? '暂停' : '恢复' }}
              </n-button>
              <n-button type="primary" secondary @click="openRunModal">
                <template #icon><Play :size="16" /></template>
                手动运行
              </n-button>
            </n-space>
          </div>

          <div class="metric-row">
            <div class="metric">
              <span>Cron</span>
              <strong class="mono">{{ selectedJob.cron_expr || 'manual' }}</strong>
            </div>
            <div class="metric">
              <span>下次运行</span>
              <strong>{{ formatTime(selectedJob.next_run_at) }}</strong>
            </div>
            <div class="metric">
              <span>最近运行</span>
              <strong>{{ formatTime(selectedJob.last_run_at) }}</strong>
            </div>
          </div>

          <n-tabs type="segment" animated>
            <n-tab-pane name="definition" tab="任务信息">
              <div class="definition-grid">
                <div class="definition-item">
                  <span>描述</span>
                  <p>{{ selectedJob.description || '-' }}</p>
                </div>
                <div class="definition-item">
                  <span>时区</span>
                  <p>{{ selectedJob.timezone }}</p>
                </div>
                <div class="definition-item">
                  <span>超时 / 重试</span>
                  <p>{{ selectedJob.timeout_seconds || '-' }}s / {{ selectedJob.retry_count }}</p>
                </div>
                <div class="definition-item">
                  <span>默认 Payload</span>
                  <pre>{{ stringifyJson(selectedJob.default_payload) }}</pre>
                </div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="runs" tab="运行记录">
              <div class="panel-toolbar">
                <n-button secondary :loading="loadingRuns" @click="loadRuns(selectedJob.job_code)">
                  <template #icon><RefreshCw :size="16" /></template>
                </n-button>
              </div>
              <div class="table-wrap">
                <n-data-table :columns="runColumns" :data="runs" :pagination="{ pageSize: 10 }" size="small" striped />
              </div>
            </n-tab-pane>
          </n-tabs>
        </template>
      </section>
    </div>

    <n-modal v-model:show="runModalOpen" preset="card" title="手动运行任务" class="scheduler-modal">
      <n-form label-placement="top">
        <n-form-item label="任务">
          <n-input :value="selectedJob?.job_code || ''" disabled class="mono" />
        </n-form-item>
        <n-form-item label="Payload JSON">
          <n-input v-model:value="runPayloadText" type="textarea" class="mono" :autosize="{ minRows: 6, maxRows: 14 }" />
        </n-form-item>
        <n-form-item label="异步执行">
          <n-switch v-model:value="runAsync" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="runModalOpen = false">取消</n-button>
          <n-button type="primary" :loading="runningJob" @click="runSelectedJob">运行</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="runDetailOpen" preset="card" title="运行详情" class="scheduler-modal">
      <n-spin :show="loadingRunDetail">
        <pre class="detail-json">{{ stringifyJson(runDetail) }}</pre>
      </n-spin>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue';
import { Play, Power, RefreshCw, RotateCcw } from 'lucide-vue-next';
import {
  NButton,
  NCheckbox,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSpace,
  NSpin,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui';
import { schedulerApi } from '@/api/scheduler';
import type { SchedulerJob, SchedulerRun, SchedulerRunListItem, SchedulerStatus } from '@/types/scheduler';
import { formatTime, parseLooseValue, stringifyJson } from '@/utils/json';

const message = useMessage();

const loading = ref(false);
const loadingRuns = ref(false);
const loadingRunDetail = ref(false);
const reloadingScheduler = ref(false);
const savingJobState = ref(false);
const runningJob = ref(false);
const includeHidden = ref(true);
const keyword = ref('');
const status = ref<SchedulerStatus | null>(null);
const jobs = ref<SchedulerJob[]>([]);
const selectedJob = ref<SchedulerJob | null>(null);
const runs = ref<SchedulerRunListItem[]>([]);
const runModalOpen = ref(false);
const runAsync = ref(false);
const runPayloadText = ref('{}');
const runDetailOpen = ref(false);
const runDetail = ref<SchedulerRun | null>(null);

const filteredJobs = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return jobs.value;
  return jobs.value.filter((job) =>
    [job.job_name, job.job_code, job.job_type].some((value) => value.toLowerCase().includes(needle)),
  );
});

const runColumns: DataTableColumns<SchedulerRunListItem> = [
  { title: 'Run ID', key: 'run_id', width: 190, ellipsis: { tooltip: true }, className: 'mono' },
  { title: '状态', key: 'status', width: 100, render: (row) => statusTag(row.status) },
  { title: '触发', key: 'trigger_source', width: 90 },
  { title: '开始时间', key: 'started_at', width: 170, render: (row) => formatTime(row.started_at) },
  { title: '结束时间', key: 'finished_at', width: 170, render: (row) => formatTime(row.finished_at) },
  { title: '影响行', key: 'affected_rows', width: 90 },
  { title: '错误', key: 'error_message_preview', ellipsis: { tooltip: true }, render: (row) => row.error_message_preview || '-' },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render(row) {
      return h(NButton, { size: 'tiny', secondary: true, onClick: () => openRunDetail(row.run_id) }, { default: () => '详情' });
    },
  },
];

watch(includeHidden, async () => {
  await loadJobs();
});

onMounted(async () => {
  await reloadAll();
});

async function reloadAll() {
  loading.value = true;
  try {
    await Promise.all([loadStatus(), loadJobs()]);
    selectJob(selectedJob.value?.job_code || jobs.value[0]?.job_code || null);
  } finally {
    loading.value = false;
  }
}

async function loadStatus() {
  try {
    status.value = await schedulerApi.status();
  } catch (error) {
    message.error(errorMessage(error, '加载调度状态失败'));
  }
}

async function loadJobs() {
  try {
    jobs.value = await schedulerApi.jobs(includeHidden.value);
  } catch (error) {
    message.error(errorMessage(error, '加载任务失败'));
  }
}

async function reloadScheduler() {
  reloadingScheduler.value = true;
  try {
    status.value = await schedulerApi.reload();
    await loadJobs();
    message.success('调度器已重载');
  } catch (error) {
    message.error(errorMessage(error, '重载调度器失败'));
  } finally {
    reloadingScheduler.value = false;
  }
}

function selectJob(jobCode: string | null) {
  if (!jobCode) {
    selectedJob.value = null;
    runs.value = [];
    return;
  }
  selectedJob.value = jobs.value.find((job) => job.job_code === jobCode) || jobs.value[0] || null;
  if (selectedJob.value) loadRuns(selectedJob.value.job_code);
}

async function loadRuns(jobCode: string) {
  loadingRuns.value = true;
  try {
    const page = await schedulerApi.runs(jobCode, 20);
    runs.value = page.items;
  } catch (error) {
    message.error(errorMessage(error, '加载运行记录失败'));
  } finally {
    loadingRuns.value = false;
  }
}

async function toggleJobState() {
  if (!selectedJob.value) return;
  savingJobState.value = true;
  try {
    const next = selectedJob.value.is_enabled
      ? await schedulerApi.pauseJob(selectedJob.value.job_code)
      : await schedulerApi.resumeJob(selectedJob.value.job_code);
    selectedJob.value = next;
    await Promise.all([loadStatus(), loadJobs()]);
    selectJob(next.job_code);
    message.success(next.is_enabled ? '任务已恢复' : '任务已暂停');
  } catch (error) {
    message.error(errorMessage(error, '更新任务状态失败'));
  } finally {
    savingJobState.value = false;
  }
}

function openRunModal() {
  if (!selectedJob.value) return;
  runPayloadText.value = stringifyJson(selectedJob.value.default_payload || {});
  runAsync.value = false;
  runModalOpen.value = true;
}

async function runSelectedJob() {
  if (!selectedJob.value) return;
  runningJob.value = true;
  try {
    const payload = parseLooseValue(runPayloadText.value, 'json');
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      message.warning('Payload 必须是 JSON object');
      return;
    }
    const run = await schedulerApi.runJob(selectedJob.value.job_code, payload as Record<string, unknown>, runAsync.value);
    runModalOpen.value = false;
    message.success(`任务已触发：${run.status}`);
    await Promise.all([loadJobs(), loadRuns(selectedJob.value.job_code)]);
  } catch (error) {
    message.error(errorMessage(error, '运行任务失败'));
  } finally {
    runningJob.value = false;
  }
}

async function openRunDetail(runId: string) {
  runDetailOpen.value = true;
  loadingRunDetail.value = true;
  runDetail.value = null;
  try {
    runDetail.value = await schedulerApi.runDetail(runId);
  } catch (error) {
    message.error(errorMessage(error, '加载运行详情失败'));
  } finally {
    loadingRunDetail.value = false;
  }
}

function statusTag(statusText: string) {
  const type = statusText === 'success' ? 'success' : statusText === 'running' ? 'info' : statusText === 'failed' || statusText === 'timeout' ? 'error' : 'warning';
  return h(NTag, { size: 'small', type, bordered: false }, { default: () => statusText });
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
</script>

<style scoped>
.scheduler-page {
  min-width: 0;
  padding: 20px;
}

.topbar,
.detail-head,
.panel-toolbar,
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.topbar {
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.topbar h1,
.title-row h2 {
  margin: 0;
}

.topbar h1 {
  font-size: 24px;
  line-height: 1.25;
}

.topbar p {
  margin: 6px 0 0;
  color: #64748b;
}

.status-strip,
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.metric-row {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 12px;
}

.metric {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  display: grid;
  gap: 4px;
}

.metric span,
.definition-item span {
  color: #64748b;
  font-size: 12px;
}

.metric strong {
  font-size: 18px;
  word-break: break-word;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.object-panel,
.detail-panel {
  background: #fff;
  border: 1px solid #dbe3ea;
  border-radius: 8px;
  padding: 14px;
}

.object-panel {
  display: grid;
  gap: 12px;
  max-height: calc(100vh - 170px);
  overflow: auto;
}

.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-weight: 700;
}

.object-list {
  display: grid;
  gap: 8px;
}

.object-item {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  padding: 10px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  text-align: left;
  cursor: pointer;
}

.object-item:hover,
.object-item.active {
  border-color: #1f8a70;
  background: #f4fbf8;
}

.object-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.object-main span {
  font-weight: 650;
}

.object-main code,
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.object-main code,
.muted {
  color: #64748b;
}

.object-meta {
  display: flex;
  gap: 4px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.detail-panel {
  min-width: 0;
}

.detail-head {
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.title-row {
  flex-wrap: wrap;
}

.title-row h2 {
  font-size: 20px;
}

.definition-grid {
  display: grid;
  gap: 12px;
}

.definition-item {
  display: grid;
  gap: 4px;
}

.definition-item p {
  margin: 0;
}

.definition-item pre,
.detail-json {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  background: #f8fafc;
  overflow: auto;
  font-size: 12px;
}

.table-wrap {
  min-width: 0;
  overflow-x: auto;
}

.scheduler-modal {
  width: min(760px, calc(100vw - 24px));
}

@media (max-width: 980px) {
  .status-strip,
  .metric-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .status-strip,
  .metric-row {
    grid-template-columns: 1fr;
  }
}
</style>
