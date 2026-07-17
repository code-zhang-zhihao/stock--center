<template>
  <main class="workspace scheduler-page">
    <header class="topbar">
      <div>
        <h1>调度任务</h1>
        <p>管理任务时间、执行策略、默认参数和运行记录。</p>
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
      <div class="metric"><span>运行开关</span><strong>{{ status?.enabled ? 'enabled' : 'disabled' }}</strong></div>
      <div class="metric"><span>APScheduler</span><strong>{{ status?.installed ? 'installed' : 'missing' }}</strong></div>
      <div class="metric"><span>运行状态</span><strong>{{ status?.running ? 'running' : 'stopped' }}</strong></div>
      <div class="metric"><span>已注册任务</span><strong>{{ status?.job_count ?? 0 }}</strong></div>
    </section>
    <n-alert v-if="status?.error" class="scheduler-error" type="error" title="调度器未正常启动">
      {{ status.error }}
    </n-alert>

    <div class="content-grid">
      <section class="object-panel">
        <div class="panel-title">
          <span>任务定义</span>
          <n-checkbox v-model:checked="includeHidden">包含内部任务</n-checkbox>
        </div>
        <n-input v-model:value="keyword" clearable size="small" placeholder="筛选任务名称 / code" />
        <div class="job-list-region">
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
                <div class="object-main"><span>{{ job.job_name }}</span><code>{{ job.job_code }}</code></div>
                <div class="object-meta">
                  <n-tag size="small" :type="job.is_enabled ? 'success' : 'warning'" :bordered="false">{{ job.is_enabled ? 'enabled' : 'disabled' }}</n-tag>
                  <n-tag v-if="job.is_hidden" size="small" :bordered="false">hidden</n-tag>
                </div>
              </button>
            </div>
          </n-spin>
        </div>
      </section>

      <section class="detail-panel">
        <n-empty v-if="!selectedJob" description="请选择一个任务" />
        <template v-else>
          <div class="detail-head">
            <div>
              <div class="title-row">
                <h2>{{ selectedJob.job_name }}</h2>
                <n-tag size="small" :type="selectedJob.is_enabled ? 'success' : 'warning'">{{ selectedJob.is_enabled ? 'enabled' : 'disabled' }}</n-tag>
                <n-tag v-if="selectedJob.is_system" size="small" type="info">system</n-tag>
              </div>
              <div class="mono muted">{{ selectedJob.job_type }} / {{ selectedJob.job_code }}</div>
            </div>
            <n-space>
              <n-button secondary :loading="savingJobState" @click="toggleJobState">
                <template #icon><Power :size="16" /></template>{{ selectedJob.is_enabled ? '暂停' : '恢复' }}
              </n-button>
              <n-button secondary @click="openSettingsModal">
                <template #icon><Settings2 :size="16" /></template>编辑配置
              </n-button>
              <n-button type="primary" secondary @click="openRunModal">
                <template #icon><Play :size="16" /></template>手动运行
              </n-button>
            </n-space>
          </div>

          <div class="metric-row">
            <div class="metric"><span>调度规则</span><strong>{{ scheduleSummary(selectedJob.cron_expr) }}</strong><code class="mono">{{ selectedJob.cron_expr || 'manual' }}</code></div>
            <div class="metric"><span>下次运行</span><strong>{{ formatTime(selectedJob.next_run_at) }}</strong></div>
            <div class="metric"><span>最近运行</span><strong>{{ formatTime(selectedJob.last_run_at) }}</strong></div>
          </div>

          <n-tabs type="segment" animated>
            <n-tab-pane name="definition" tab="任务信息">
              <div class="definition-grid">
                <div class="definition-item"><span>描述</span><p>{{ selectedJob.description || '-' }}</p></div>
                <div class="definition-item"><span>固定时区</span><p>{{ selectedJob.timezone }}</p></div>
                <div class="definition-item"><span>单次尝试超时 / 重试</span><p>{{ selectedJob.timeout_seconds ? `${selectedJob.timeout_seconds}s` : '不限制' }} / {{ selectedJob.retry_count }} 次，每次间隔 {{ selectedJob.retry_interval_seconds }}s</p></div>
                <div class="definition-item"><span>默认参数</span><pre>{{ stringifyJson(selectedJob.default_payload) }}</pre></div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="runs" tab="运行记录">
              <div class="panel-toolbar">
                <n-button secondary :loading="loadingRuns" @click="loadRuns(selectedJob.job_code)"><template #icon><RefreshCw :size="16" /></template></n-button>
              </div>
              <div class="table-wrap"><n-data-table :columns="runColumns" :data="runs" :pagination="{ pageSize: 10 }" size="small" striped /></div>
            </n-tab-pane>
          </n-tabs>
        </template>
      </section>
    </div>

    <n-modal v-model:show="settingsModalOpen" preset="card" title="编辑任务配置" :style="modalStyle" :content-style="modalContentStyle">
      <n-form label-placement="top">
        <n-form-item label="任务"><n-input :value="selectedJob?.job_name || ''" disabled /></n-form-item>
        <n-form-item label="调度模式">
          <n-select v-model:value="settingsForm.mode" :options="scheduleModeOptions" />
        </n-form-item>
        <div v-if="settingsForm.mode !== 'manual' && settingsForm.mode !== 'custom'" class="schedule-time-grid">
          <n-form-item label="小时"><n-input-number v-model:value="settingsForm.hour" :min="0" :max="23" :show-button="true" /></n-form-item>
          <n-form-item label="分钟"><n-input-number v-model:value="settingsForm.minute" :min="0" :max="59" :show-button="true" /></n-form-item>
        </div>
        <n-form-item v-if="settingsForm.mode === 'weekly'" label="每周执行日">
          <n-checkbox-group v-model:value="settingsForm.weekdays"><n-space wrap><n-checkbox v-for="day in weekdayOptions" :key="day.value" :value="day.value">{{ day.label }}</n-checkbox></n-space></n-checkbox-group>
        </n-form-item>
        <n-form-item v-if="settingsForm.mode === 'monthly'" label="每月执行日">
          <n-select v-model:value="settingsForm.monthlyDay" :options="monthlyDayOptions" />
        </n-form-item>
        <n-form-item v-if="settingsForm.mode === 'custom'" label="五段 Cron">
          <n-input v-model:value="settingsForm.customCron" class="mono" placeholder="例如：20 8 * * 1-5" />
        </n-form-item>
        <n-alert type="info" :show-icon="false">{{ schedulePreviewText }}</n-alert>

        <div class="settings-divider">执行策略</div>
        <n-form-item label="启用任务"><n-switch v-model:value="settingsForm.isEnabled"><template #checked>启用</template><template #unchecked>暂停</template></n-switch></n-form-item>
        <n-form-item label="限制单次尝试超时"><n-switch v-model:value="settingsForm.hasTimeout"><template #checked>限制</template><template #unchecked>不限制</template></n-switch></n-form-item>
        <n-form-item v-if="settingsForm.hasTimeout" label="单次尝试超时秒数"><n-input-number v-model:value="settingsForm.timeoutSeconds" :min="1" :max="86400" :show-button="true" /></n-form-item>
        <div class="schedule-time-grid">
          <n-form-item label="失败重试次数"><n-input-number v-model:value="settingsForm.retryCount" :min="0" :max="10" :show-button="true" /></n-form-item>
          <n-form-item label="重试间隔秒数"><n-input-number v-model:value="settingsForm.retryIntervalSeconds" :min="1" :max="3600" :show-button="true" /></n-form-item>
        </div>
      </n-form>

      <div class="settings-divider">默认参数</div>
      <SchedulerPayloadForm v-model="settingsPayload" :schema="selectedJob?.parameter_schema || {}" @validity-change="settingsPayloadValid = $event" />
      <n-collapse v-if="hasUnknownPayload(selectedJob?.default_payload || {}, selectedJob?.parameter_schema || {})" class="advanced-payload">
        <n-collapse-item title="高级保留参数" name="advanced">
          <n-input v-model:value="settingsExtrasText" type="textarea" class="mono" :autosize="{ minRows: 4, maxRows: 10 }" />
        </n-collapse-item>
      </n-collapse>
      <template #footer>
        <n-space justify="end"><n-button @click="settingsModalOpen = false">取消</n-button><n-button type="primary" :loading="savingSettings" @click="saveSettings">保存并重载</n-button></n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="runModalOpen" preset="card" title="手动运行任务" :style="modalStyle" :content-style="modalContentStyle">
      <n-form label-placement="top">
        <n-form-item label="任务"><n-input :value="selectedJob?.job_code || ''" disabled class="mono" /></n-form-item>
      </n-form>
      <SchedulerPayloadForm v-model="runPayload" :schema="selectedJob?.parameter_schema || {}" @validity-change="runPayloadValid = $event" />
      <n-collapse v-if="hasUnknownPayload(selectedJob?.default_payload || {}, selectedJob?.parameter_schema || {})" class="advanced-payload">
        <n-collapse-item title="高级保留参数" name="advanced"><n-input v-model:value="runExtrasText" type="textarea" class="mono" :autosize="{ minRows: 4, maxRows: 10 }" /></n-collapse-item>
      </n-collapse>
      <n-form label-placement="top"><n-form-item label="后台执行"><n-switch v-model:value="runAsync"><template #checked>后台运行</template><template #unchecked>等待结果</template></n-switch><small class="field-help">同步任务会自动转为后台执行，页面不会等待其完成。</small></n-form-item></n-form>
      <template #footer>
        <n-space justify="end"><n-button @click="runModalOpen = false">取消</n-button><n-button type="primary" :loading="runningJob" @click="runSelectedJob">运行</n-button></n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="runDetailOpen" preset="card" title="运行详情" :style="modalStyle"><n-spin :show="loadingRunDetail"><pre class="detail-json">{{ stringifyJson(runDetail) }}</pre></n-spin></n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch, type CSSProperties } from 'vue';
import { Play, Power, RefreshCw, RotateCcw, Settings2 } from 'lucide-vue-next';
import {
  NAlert, NButton, NCheckbox, NCheckboxGroup, NCollapse, NCollapseItem, NDataTable, NEmpty, NForm, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace, NSpin, NSwitch, NTabPane, NTabs, NTag, useMessage, type DataTableColumns,
} from 'naive-ui';
import SchedulerPayloadForm from '@/components/SchedulerPayloadForm.vue';
import { schedulerApi } from '@/api/scheduler';
import type { SchedulerJob, SchedulerParameterSchema, SchedulerRun, SchedulerRunListItem, SchedulerStatus } from '@/types/scheduler';
import { formatTime, parseJsonObject, stringifyJson } from '@/utils/json';

type ScheduleMode = 'manual' | 'daily' | 'weekly' | 'monthly' | 'custom';

interface ScheduleForm {
  mode: ScheduleMode;
  hour: number;
  minute: number;
  weekdays: number[];
  monthlyDay: number;
  customCron: string;
  isEnabled: boolean;
  hasTimeout: boolean;
  timeoutSeconds: number;
  retryCount: number;
  retryIntervalSeconds: number;
}

const message = useMessage();
const modalStyle = { width: 'min(860px, calc(100vw - 24px))' };
const modalContentStyle: CSSProperties = { maxHeight: 'calc(100vh - 190px)', overflowY: 'auto', paddingRight: '4px' };
const scheduleModeOptions = [
  { label: '仅手动运行', value: 'manual' },
  { label: '每天', value: 'daily' },
  { label: '每周', value: 'weekly' },
  { label: '每月', value: 'monthly' },
  { label: '自定义 Cron', value: 'custom' },
];
const weekdayOptions = [
  { label: '周一', value: 1 }, { label: '周二', value: 2 }, { label: '周三', value: 3 }, { label: '周四', value: 4 }, { label: '周五', value: 5 }, { label: '周六', value: 6 }, { label: '周日', value: 0 },
];
const monthlyDayOptions = Array.from({ length: 28 }, (_, index) => ({ label: `${index + 1} 日`, value: index + 1 }));

const loading = ref(false);
const loadingRuns = ref(false);
const loadingRunDetail = ref(false);
const reloadingScheduler = ref(false);
const savingJobState = ref(false);
const savingSettings = ref(false);
const runningJob = ref(false);
const cancellingRunId = ref<string | null>(null);
const includeHidden = ref(true);
const keyword = ref('');
const status = ref<SchedulerStatus | null>(null);
const jobs = ref<SchedulerJob[]>([]);
const selectedJob = ref<SchedulerJob | null>(null);
const runs = ref<SchedulerRunListItem[]>([]);
const settingsModalOpen = ref(false);
const settingsPayload = ref<Record<string, unknown>>({});
const settingsExtrasText = ref('{}');
const settingsPayloadValid = ref(true);
const settingsForm = ref<ScheduleForm>(emptyScheduleForm());
const runModalOpen = ref(false);
const runAsync = ref(false);
const runPayload = ref<Record<string, unknown>>({});
const runBasePayload = ref<Record<string, unknown>>({});
const runExtrasText = ref('{}');
const runBaseExtras = ref<Record<string, unknown>>({});
const runPayloadValid = ref(true);
const runDetailOpen = ref(false);
const runDetail = ref<SchedulerRun | null>(null);

const filteredJobs = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return jobs.value;
  return jobs.value.filter((job) => [job.job_name, job.job_code, job.job_type].some((value) => value.toLowerCase().includes(needle)));
});
const settingsCron = computed(() => buildCron(settingsForm.value));
const schedulePreviewText = computed(() => settingsForm.value.mode === 'manual'
  ? '仅手动运行：不会注册 APScheduler 定时触发。'
  : `将保存为 ${settingsCron.value}，固定使用 Asia/Shanghai 时区。`);

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
    width: 150,
    render: (row) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, { size: 'tiny', secondary: true, onClick: () => openRunDetail(row.run_id) }, { default: () => '详情' }),
        row.status === 'running'
          ? h(
              NButton,
              {
                size: 'tiny',
                type: 'error',
                secondary: true,
                loading: cancellingRunId.value === row.run_id,
                onClick: () => cancelRun(row),
              },
              { default: () => '终止' },
            )
          : null,
      ],
    }),
  },
];

watch(includeHidden, () => void loadJobs());
onMounted(() => void reloadAll());

async function reloadAll() {
  loading.value = true;
  try {
    await Promise.all([loadStatus(), loadJobs()]);
    selectJob(selectedJob.value?.job_code || jobs.value[0]?.job_code || null);
  } finally { loading.value = false; }
}

async function loadStatus() {
  try { status.value = await schedulerApi.status(); } catch (error) { message.error(errorMessage(error, '加载调度状态失败')); }
}

async function loadJobs() {
  try { jobs.value = await schedulerApi.jobs(includeHidden.value); } catch (error) { message.error(errorMessage(error, '加载任务失败')); }
}

async function reloadScheduler() {
  reloadingScheduler.value = true;
  try {
    status.value = await schedulerApi.reload();
    await loadJobs();
    selectJob(selectedJob.value?.job_code || null);
    message.success('调度器已重载');
  } catch (error) { message.error(errorMessage(error, '重载调度器失败')); } finally { reloadingScheduler.value = false; }
}

function selectJob(jobCode: string | null) {
  if (!jobCode) { selectedJob.value = null; runs.value = []; return; }
  selectedJob.value = jobs.value.find((job) => job.job_code === jobCode) || jobs.value[0] || null;
  if (selectedJob.value) void loadRuns(selectedJob.value.job_code);
}

async function loadRuns(jobCode: string) {
  loadingRuns.value = true;
  try { runs.value = (await schedulerApi.runs(jobCode, 20)).items; } catch (error) { message.error(errorMessage(error, '加载运行记录失败')); } finally { loadingRuns.value = false; }
}

async function toggleJobState() {
  if (!selectedJob.value) return;
  savingJobState.value = true;
  try {
    const next = selectedJob.value.is_enabled ? await schedulerApi.pauseJob(selectedJob.value.job_code) : await schedulerApi.resumeJob(selectedJob.value.job_code);
    await refreshSelectedJob(next.job_code);
    message.success(next.is_enabled ? '任务已恢复' : '任务已暂停');
  } catch (error) { message.error(errorMessage(error, '更新任务状态失败')); } finally { savingJobState.value = false; }
}

function openSettingsModal() {
  if (!selectedJob.value) return;
  settingsForm.value = scheduleFormFromJob(selectedJob.value);
  const [known, extras] = splitPayload(selectedJob.value.default_payload, selectedJob.value.parameter_schema);
  settingsPayload.value = known;
  settingsExtrasText.value = stringifyJson(extras) || '{}';
  settingsPayloadValid.value = true;
  settingsModalOpen.value = true;
}

async function saveSettings() {
  if (!selectedJob.value) return;
  if (!settingsPayloadValid.value) { message.warning('请先修正参数中的 JSON 格式'); return; }
  if (settingsForm.value.mode === 'weekly' && settingsForm.value.weekdays.length === 0) { message.warning('每周任务至少选择一个执行日'); return; }
  const cronExpr = settingsCron.value;
  if (settingsForm.value.mode === 'custom' && !cronExpr) { message.warning('请输入五段 Cron 表达式'); return; }
  let defaultPayload: Record<string, unknown>;
  try { defaultPayload = mergePayload(settingsPayload.value, settingsExtrasText.value); } catch (error) { message.warning(errorMessage(error, '高级参数必须是 JSON object')); return; }
  savingSettings.value = true;
  try {
    await schedulerApi.updateJob(selectedJob.value.job_code, {
      cron_expr: cronExpr,
      timezone: 'Asia/Shanghai',
      default_payload: defaultPayload,
      is_enabled: settingsForm.value.isEnabled,
      timeout_seconds: settingsForm.value.hasTimeout ? settingsForm.value.timeoutSeconds : null,
      retry_count: settingsForm.value.retryCount,
      retry_interval_seconds: settingsForm.value.retryIntervalSeconds,
    });
    settingsModalOpen.value = false;
    await reloadScheduler();
    message.success('任务配置已保存');
  } catch (error) { message.error(errorMessage(error, '保存任务配置失败')); } finally { savingSettings.value = false; }
}

function openRunModal() {
  if (!selectedJob.value) return;
  const [known, extras] = splitPayload(selectedJob.value.default_payload, selectedJob.value.parameter_schema);
  runBasePayload.value = cloneValue(known);
  runPayload.value = cloneValue(known);
  runBaseExtras.value = cloneValue(extras);
  runExtrasText.value = stringifyJson(extras) || '{}';
  runPayloadValid.value = true;
  runAsync.value = false;
  runModalOpen.value = true;
}

async function runSelectedJob() {
  if (!selectedJob.value) return;
  if (!runPayloadValid.value) { message.warning('请先修正参数中的 JSON 格式'); return; }
  let currentPayload: Record<string, unknown>;
  try { currentPayload = mergePayload(runPayload.value, runExtrasText.value); } catch (error) { message.warning(errorMessage(error, '高级参数必须是 JSON object')); return; }
  const baseline = { ...runBaseExtras.value, ...runBasePayload.value };
  const overrides = payloadOverrides(baseline, currentPayload);
  runningJob.value = true;
  try {
    const run = await schedulerApi.runJob(selectedJob.value.job_code, overrides, runAsync.value);
    runModalOpen.value = false;
    message.success(`任务已触发：${run.status}`);
    await Promise.all([loadJobs(), loadRuns(selectedJob.value.job_code)]);
  } catch (error) { message.error(errorMessage(error, '运行任务失败')); } finally { runningJob.value = false; }
}

async function openRunDetail(runId: string) {
  runDetailOpen.value = true;
  loadingRunDetail.value = true;
  runDetail.value = null;
  try { runDetail.value = await schedulerApi.runDetail(runId); } catch (error) { message.error(errorMessage(error, '加载运行详情失败')); } finally { loadingRunDetail.value = false; }
}

async function cancelRun(row: SchedulerRunListItem) {
  cancellingRunId.value = row.run_id;
  try {
    const result = await schedulerApi.cancelRun(row.run_id);
    message.success(result.active ? '已发送终止请求' : '已标记为终止');
    if (selectedJob.value) await loadRuns(selectedJob.value.job_code);
    await loadStatus();
  } catch (error) {
    message.error(errorMessage(error, '终止任务失败'));
  } finally {
    cancellingRunId.value = null;
  }
}

async function refreshSelectedJob(jobCode: string) {
  await Promise.all([loadStatus(), loadJobs()]);
  selectJob(jobCode);
}

function emptyScheduleForm(): ScheduleForm {
  return { mode: 'manual', hour: 8, minute: 0, weekdays: [1], monthlyDay: 1, customCron: '', isEnabled: false, hasTimeout: true, timeoutSeconds: 60, retryCount: 0, retryIntervalSeconds: 60 };
}

function scheduleFormFromJob(job: SchedulerJob): ScheduleForm {
  const form = { ...emptyScheduleForm(), isEnabled: job.is_enabled, hasTimeout: Boolean(job.timeout_seconds), timeoutSeconds: job.timeout_seconds || 60, retryCount: job.retry_count, retryIntervalSeconds: job.retry_interval_seconds };
  const cron = job.cron_expr?.trim();
  if (!cron) return form;
  const parts = cron.split(/\s+/);
  const minute = Number(parts[0]);
  const hour = Number(parts[1]);
  if (!Number.isInteger(hour) || !Number.isInteger(minute) || parts.length !== 5) return { ...form, mode: 'custom', customCron: cron };
  if (parts[2] === '*' && parts[3] === '*' && parts[4] === '*') return { ...form, mode: 'daily', hour, minute };
  if (parts[2] === '*' && parts[3] === '*' && /^[0-7,\-/]+$/.test(parts[4])) return { ...form, mode: 'weekly', hour, minute, weekdays: parseWeekdays(parts[4]), customCron: cron };
  if (/^(?:[1-9]|1\d|2[0-8])$/.test(parts[2]) && parts[3] === '*' && parts[4] === '*') return { ...form, mode: 'monthly', hour, minute, monthlyDay: Number(parts[2]) };
  return { ...form, mode: 'custom', customCron: cron };
}

function parseWeekdays(value: string) {
  const days = new Set<number>();
  for (const token of value.split(',')) {
    const [range] = token.split('/');
    if (range.includes('-')) {
      const [start, end] = range.split('-').map(Number);
      if (Number.isInteger(start) && Number.isInteger(end)) for (let day = start; day <= end; day += 1) days.add(day === 7 ? 0 : day);
    } else if (/^\d$/.test(range)) days.add(Number(range) === 7 ? 0 : Number(range));
  }
  return [...days].filter((day) => day >= 0 && day <= 6).sort((a, b) => a - b);
}

function buildCron(form: ScheduleForm): string | null {
  if (form.mode === 'manual') return null;
  if (form.mode === 'custom') return form.customCron.trim() || null;
  if (form.mode === 'daily') return `${form.minute} ${form.hour} * * *`;
  if (form.mode === 'weekly') return `${form.minute} ${form.hour} * * ${[...form.weekdays].sort((a, b) => a - b).join(',')}`;
  return `${form.minute} ${form.hour} ${form.monthlyDay} * *`;
}

function scheduleSummary(cronExpr: string | null) {
  if (!cronExpr) return '仅手动运行';
  const form = scheduleFormFromJob({ ...selectedJob.value!, cron_expr: cronExpr });
  if (form.mode === 'daily') return `每天 ${formatClock(form.hour, form.minute)}`;
  if (form.mode === 'weekly') return `每周 ${form.weekdays.map((day) => weekdayOptions.find((item) => item.value === day)?.label).join('、')} ${formatClock(form.hour, form.minute)}`;
  if (form.mode === 'monthly') return `每月 ${form.monthlyDay} 日 ${formatClock(form.hour, form.minute)}`;
  return '自定义 Cron';
}

function formatClock(hour: number, minute: number) { return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`; }
function splitPayload(payload: Record<string, unknown>, schema: SchedulerParameterSchema): [Record<string, unknown>, Record<string, unknown>] {
  const known: Record<string, unknown> = {};
  const extras: Record<string, unknown> = {};
  for (const [key, spec] of Object.entries(schema)) known[key] = payload[key] ?? cloneValue(spec.default);
  for (const [key, value] of Object.entries(payload)) if (!(key in schema)) extras[key] = value;
  return [known, extras];
}
function hasUnknownPayload(payload: Record<string, unknown>, schema: SchedulerParameterSchema) { return Object.keys(payload).some((key) => !(key in schema)); }
function mergePayload(known: Record<string, unknown>, extrasText: string) { return { ...parseJsonObject(extrasText, {}), ...known }; }
function payloadOverrides(base: Record<string, unknown>, current: Record<string, unknown>) {
  const overrides: Record<string, unknown> = {};
  for (const key of new Set([...Object.keys(base), ...Object.keys(current)])) if (stringifyJson(base[key]) !== stringifyJson(current[key])) overrides[key] = current[key];
  return overrides;
}
function cloneValue<T>(value: T): T { return value === undefined ? value : JSON.parse(JSON.stringify(value)) as T; }
function statusTag(statusText: string) { const type = statusText === 'success' ? 'success' : statusText === 'running' ? 'info' : statusText === 'failed' || statusText === 'timeout' ? 'error' : 'warning'; return h(NTag, { size: 'small', type, bordered: false }, { default: () => statusText }); }
function errorMessage(error: unknown, fallback: string): string { return error instanceof Error ? error.message : fallback; }
</script>

<style scoped>
.scheduler-page { min-width: 0; padding: 20px; }
.topbar, .detail-head, .panel-toolbar, .title-row { display: flex; align-items: center; gap: 12px; }
.topbar { justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.topbar h1, .title-row h2 { margin: 0; }
.topbar h1 { font-size: 24px; line-height: 1.25; }
.topbar p { margin: 6px 0 0; color: #64748b; }
.status-strip, .metric-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.metric-row { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 12px; }
.metric { min-width: 0; background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; display: grid; gap: 4px; }
.scheduler-error { margin: -4px 0 16px; }
.metric span, .definition-item span { color: #64748b; font-size: 12px; }
.metric strong { font-size: 17px; word-break: break-word; }
.metric code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #64748b; }
.content-grid { display: grid; grid-template-columns: minmax(260px, 340px) minmax(0, 1fr); gap: 16px; align-items: start; }
.object-panel, .detail-panel { background: #fff; border: 1px solid #dbe3ea; border-radius: 8px; padding: 14px; }
.object-panel { display: flex; flex-direction: column; gap: 12px; height: calc(100vh - 170px); min-height: 520px; }
.job-list-region { min-height: 0; flex: 1; overflow-y: auto; }
.panel-title { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-weight: 700; }
.object-list { display: grid; gap: 8px; }
.object-item { width: 100%; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; padding: 10px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; text-align: left; cursor: pointer; }
.object-item:hover, .object-item.active { border-color: #1f8a70; background: #f4fbf8; }
.object-main { min-width: 0; display: grid; gap: 3px; }
.object-main span { font-weight: 650; }
.object-main code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #64748b; }
.object-meta { display: flex; gap: 4px; align-items: flex-start; flex-wrap: wrap; }
.detail-panel { min-width: 0; }
.detail-head { justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; }
.title-row { flex-wrap: wrap; }
.title-row h2 { font-size: 20px; }
.definition-grid { display: grid; gap: 12px; }
.definition-item { display: grid; gap: 4px; }
.definition-item p { margin: 0; }
.definition-item pre, .detail-json { margin: 0; padding: 10px; border-radius: 6px; background: #f8fafc; overflow: auto; font-size: 12px; }
.table-wrap { min-width: 0; overflow-x: auto; }
.schedule-time-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.settings-divider { margin: 18px 0 10px; padding-top: 14px; border-top: 1px solid #e2e8f0; color: #344054; font-size: 14px; font-weight: 700; }
.advanced-payload { margin-top: 12px; }
.field-help { display: block; margin-top: 8px; color: #64748b; line-height: 1.45; }
@media (max-width: 980px) { .status-strip, .metric-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } .content-grid { grid-template-columns: 1fr; } .object-panel { height: 360px; min-height: 0; } }
@media (max-width: 640px) { .scheduler-page { padding: 14px; } .topbar { flex-wrap: wrap; } .status-strip, .metric-row, .schedule-time-grid { grid-template-columns: 1fr; } }
</style>
