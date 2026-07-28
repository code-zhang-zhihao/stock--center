<template>
  <main class="workspace emotion-model-page">
    <header class="topbar">
      <div>
        <div class="eyebrow">可配置 / 可审计</div>
        <h1>情绪模型</h1>
        <p>V2 将“短线接力环境”和“大盘风险偏好”拆分评分。发布前必须完成 250 个交易日基线校准；历史评分永远保留其参数快照。</p>
      </div>
      <n-button type="primary" @click="openCreate()"><template #icon><Plus :size="16" /></template>新建草稿</n-button>
    </header>

    <n-alert type="info" :show-icon="true" class="page-alert">
      当前页面不触发行情请求。校准仅调用已沉淀的日线、事件、因子和概念热度事实，并通过“生成每日市场报告与 V2 情绪事实”任务后台执行。
    </n-alert>

    <n-spin :show="loading">
      <section class="model-grid">
        <article v-for="model in models" :key="model.model_code" class="model-card" :class="{ selected: selected?.model_code === model.model_code }" @click="selectModel(model)">
          <div class="model-card-head"><div><strong>{{ model.model_name }}</strong><small>{{ model.model_code }}</small></div><n-tag :type="statusType(model.status)" :bordered="false">{{ statusLabel(model.status) }}</n-tag></div>
          <div class="model-stats"><span>分位窗口 <b>{{ model.percentile_window_days }} 日</b></span><span>最小历史 <b>{{ model.minimum_history_days }} 日</b></span><span>基线 <b>{{ model.baseline_trade_days }} 日</b></span></div>
          <p>{{ calibrationLabel(model) }}</p>
        </article>
        <n-empty v-if="!models.length" description="尚未创建情绪模型" />
      </section>

      <section v-if="selected" class="surface editor-surface">
        <div class="panel-heading"><div><span class="panel-kicker">模型配置</span><h2>{{ selected.model_name }}</h2></div><span class="muted">{{ selected.status === 'draft' ? '草稿可编辑；校准后需克隆再改' : '已冻结参数快照' }}</span></div>
        <div class="settings-grid">
          <label>名称<n-input v-model:value="form.model_name" :disabled="!isDraft" /></label>
          <label>滚动分位窗口（交易日）<n-input-number v-model:value="form.percentile_window_days" :min="60" :max="500" :disabled="!isDraft" /></label>
          <label>最小历史样本（交易日）<n-input-number v-model:value="form.minimum_history_days" :min="20" :max="500" :disabled="!isDraft" /></label>
          <label>基线长度（交易日）<n-input-number v-model:value="form.baseline_trade_days" :min="60" :max="1000" :disabled="!isDraft" /></label>
        </div>
        <div class="weight-panels">
          <article v-for="card in scorecardForms" :key="card.key" class="weight-panel"><h3>{{ card.label }} <small>合计 {{ weightTotal(card.key) }}%</small></h3><div class="weight-list"><label v-for="item in card.items" :key="item.key"><span>{{ metricLabel(item.key) }}</span><n-input-number v-model:value="parameters[card.key][item.key]" :min="0" :max="100" :disabled="!isDraft" /></label></div></article>
          <article class="weight-panel thresholds"><h3>阶段阈值</h3><div class="weight-list"><label v-for="key in thresholdKeys" :key="key"><span>{{ thresholdLabel(key) }}</span><n-input-number v-model:value="parameters.stage_thresholds[key]" :min="0" :max="100" :disabled="!isDraft" /></label></div></article>
        </div>
        <div class="editor-actions">
          <n-button v-if="isDraft" :loading="saving" @click="saveDraft">保存草稿</n-button>
          <n-button v-if="isDraft || selected.status === 'calibrating' || selected.status === 'ready'" type="primary" secondary :loading="calibrating" @click="calibrate">{{ selected.status === 'ready' ? '重新校准' : '开始基线校准' }}</n-button>
          <n-button v-if="selected.status === 'ready'" type="success" :loading="activating" @click="activate">确认并启用</n-button>
          <n-button v-if="!isDraft" @click="openCreate(selected.model_code)">克隆为草稿</n-button>
        </div>
        <n-alert v-if="parameterError" type="warning" :show-icon="true" class="parameter-alert">{{ parameterError }}</n-alert>
      </section>

      <section v-if="selected" class="surface validation-surface">
        <div class="panel-heading"><div><span class="panel-kicker">校准与验证预览</span><h2>基线结果</h2></div><span class="muted">管理员确认后方可启用</span></div>
        <div class="validation-grid"><article><span>处理交易日</span><strong>{{ calibrationValue('baseline_trade_days_processed') }} / {{ selected.baseline_trade_days }}</strong></article><article><span>可评分日</span><strong>{{ calibrationValue('ready_or_degraded_days') }}</strong></article><article><span>短线分均值</span><strong>{{ calibrationValue('short_term_score_average') }}</strong></article><article><span>T+1 市场广度</span><strong>{{ validationValue('t_plus_1', 'average_market_breadth_pct', '%') }}</strong></article><article><span>T+1 指数变化</span><strong>{{ validationValue('t_plus_1', 'average_core_index_change_pct', '%') }}</strong></article><article><span>T+3 市场广度</span><strong>{{ validationValue('t_plus_3', 'average_market_breadth_pct', '%') }}</strong></article><article><span>T+3 指数变化</span><strong>{{ validationValue('t_plus_3', 'average_core_index_change_pct', '%') }}</strong></article><article><span>状态</span><strong>{{ calibrationStatus }}</strong></article></div>
        <div v-if="stageDays.length" class="stage-days"><span v-for="item in stageDays" :key="item[0]">{{ stageLabel(item[0]) }} {{ item[1] }} 日</span></div>
        <p class="panel-note">T+1/T+3 市场广度和核心指数验证会由后续策略/回测层写入；当前校准预览明确显示其未计算状态，不使用未来数据倒灌当日评分。</p>
      </section>
    </n-spin>

    <n-modal v-model:show="createOpen" preset="card" title="新建 V2 情绪模型草稿" style="width: min(520px, calc(100vw - 28px))">
      <n-form label-placement="top"><n-form-item label="模型代码"><n-input v-model:value="createForm.model_code" placeholder="例如 cn_a_emotion_v2_test" /></n-form-item><n-form-item label="模型名称"><n-input v-model:value="createForm.model_name" placeholder="例如 A 股短线情绪实验版" /></n-form-item><n-form-item label="克隆来源"><n-select v-model:value="createForm.clone_from" clearable :options="models.map((item) => ({ label: `${item.model_name} (${item.model_code})`, value: item.model_code }))" placeholder="不选则使用默认参数" /></n-form-item></n-form>
      <template #footer><div class="modal-actions"><n-button @click="createOpen = false">取消</n-button><n-button type="primary" :loading="creating" @click="create">创建草稿</n-button></div></template>
    </n-modal>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { NAlert, NButton, NEmpty, NForm, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpin, NTag, useMessage } from 'naive-ui';
import { Plus } from 'lucide-vue-next';
import { marketInsightApi } from '@/api/market-insight';
import { schedulerApi } from '@/api/scheduler';
import type { MarketEmotionModel } from '@/types/market-insight';

type WeightCard = 'short_term' | 'risk_on';
const message = useMessage();
const models = ref<MarketEmotionModel[]>([]);
const selected = ref<MarketEmotionModel | null>(null);
const loading = ref(false); const saving = ref(false); const creating = ref(false); const calibrating = ref(false); const activating = ref(false); const createOpen = ref(false);
const createForm = reactive({ model_code: '', model_name: '', clone_from: null as string | null });
const form = reactive({ model_name: '', percentile_window_days: 120, minimum_history_days: 60, baseline_trade_days: 250 });
const parameters = reactive<any>({ short_term: {}, risk_on: {}, stage_thresholds: {} });
const thresholdKeys = ['ice_point', 'retreat', 'recovery', 'active', 'climax'];
const metricNames: Record<string, string> = { natural_limit_up_count: '换手自然涨停', qualified_limit_down_count: '合格跌停', limit_break_rate: '炸板率', board_promotion_rate: '连板晋级率', board_structure: '连板高度及梯队', up_ratio_pct: '上涨比例', median_change_pct: '中位涨跌幅', wide_move_ratio: '宽幅涨跌比', previous_limit_up_premium: '昨日涨停溢价', theme_limit_up_density: '热点概念涨停密度', theme_persistence: '热点持续性', leader_strength: '龙头强度', amount_vs_5d_average: '成交额相对5日均值', main_net_inflow_strength: '全市场主力资金', north_money: '北向资金', above_ma20_ratio: '站上MA20比例', above_ma60_ratio: '站上MA60比例', new_high_low_spread: '创新高减创新低', turnover_volume_expansion: '换手/量能扩散', core_index_trend: '核心指数趋势', index_amplitude: '指数振幅', qualified_limit_down_density: '跌停密度', volatility_20d: '20日波动率' };
const scorecardForms = computed(() => ([{ key: 'short_term' as WeightCard, label: '短线接力情绪分（权重合计必须为 100%）', items: Object.keys(parameters.short_term || {}).map((key) => ({ key })) }, { key: 'risk_on' as WeightCard, label: '大盘风险偏好分（权重合计必须为 100%）', items: Object.keys(parameters.risk_on || {}).map((key) => ({ key })) }]));
const isDraft = computed(() => selected.value?.status === 'draft');
const parameterError = computed(() => { if (!selected.value) return ''; const totals = (['short_term', 'risk_on'] as WeightCard[]).map(weightTotal); if (totals.some((total) => total !== 100)) return '每张评分卡权重必须恰好合计 100%。'; const t = parameters.stage_thresholds || {}; if (!(Number(t.ice_point) < Number(t.retreat) && Number(t.retreat) < Number(t.recovery) && Number(t.recovery) < Number(t.active) && Number(t.active) < Number(t.climax))) return '阶段阈值必须依次满足：冰点 < 退潮 < 修复 < 活跃 < 高潮。'; return ''; });
const stageDays = computed(() => Object.entries((selected.value?.calibration_summary?.stage_days || {}) as Record<string, number>));
const calibrationStatus = computed(() => selected.value?.calibration_summary?.baseline_complete ? '基线完成' : (selected.value?.calibration_summary?.status === 'running' ? '校准中' : '待校准'));

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }
function statusLabel(status: string) { return ({ draft: '草稿', calibrating: '校准中', ready: '待启用', active: '已启用', archived: '已归档' } as Record<string, string>)[status] || status; }
function statusType(status: string) { return ({ active: 'success', ready: 'info', calibrating: 'warning', draft: 'default', archived: 'default' } as Record<string, 'success' | 'info' | 'warning' | 'default'>)[status] || 'default'; }
function metricLabel(key: string) { return metricNames[key] || key; }
function thresholdLabel(key: string) { return ({ ice_point: '冰点', retreat: '退潮', recovery: '修复', active: '活跃', climax: '高潮' } as Record<string, string>)[key] || key; }
function stageLabel(key: string) { return thresholdLabel(key); }
function weightTotal(key: WeightCard) { return Math.round(Object.values(parameters[key] || {}).reduce((sum: number, value) => sum + Number(value || 0), 0) * 100) / 100; }
function calibrationValue(key: string) { const value = selected.value?.calibration_summary?.[key]; return typeof value === 'number' ? (Number.isInteger(value) ? value.toLocaleString('zh-CN') : value.toFixed(2)) : '-'; }
function validationValue(horizon: string, key: string, suffix = '') { const validation = selected.value?.calibration_summary?.validation as Record<string, Record<string, unknown>> | undefined; const value = validation?.[horizon]?.[key]; return typeof value === 'number' ? `${value.toFixed(2)}${suffix}` : '-'; }
function calibrationLabel(model: MarketEmotionModel) { const summary = model.calibration_summary || {}; return summary.baseline_complete ? `基线完成：${summary.ready_or_degraded_days || 0} 个可评分交易日` : (model.status === 'calibrating' ? '后台正在按 20 个交易日分批校准' : '尚未完成基线校准'); }
function selectModel(model: MarketEmotionModel) { selected.value = model; form.model_name = model.model_name; form.percentile_window_days = model.percentile_window_days; form.minimum_history_days = model.minimum_history_days; form.baseline_trade_days = model.baseline_trade_days; const value = clone(model.parameter_json || {}); parameters.short_term = value.short_term || {}; parameters.risk_on = value.risk_on || {}; parameters.stage_thresholds = value.stage_thresholds || {}; }
async function load() { loading.value = true; try { models.value = (await marketInsightApi.emotionModels()).items; const chosen = selected.value && models.value.find((item) => item.model_code === selected.value?.model_code); if (chosen) selectModel(chosen); else if (models.value[0]) selectModel(models.value[0]); } catch (error) { message.error(error instanceof Error ? error.message : '加载情绪模型失败'); } finally { loading.value = false; } }
function openCreate(cloneFrom?: string) { createForm.model_code = ''; createForm.model_name = ''; createForm.clone_from = cloneFrom || selected.value?.model_code || null; createOpen.value = true; }
async function create() { if (!createForm.model_code || !createForm.model_name) { message.warning('请填写模型代码和名称'); return; } creating.value = true; try { const model = await marketInsightApi.createEmotionModel(createForm); createOpen.value = false; await load(); const created = models.value.find((item) => item.model_code === model.model_code); if (created) selectModel(created); message.success('草稿已创建'); } catch (error) { message.error(error instanceof Error ? error.message : '创建草稿失败'); } finally { creating.value = false; } }
async function saveDraft() { if (!selected.value || parameterError.value) { message.warning(parameterError.value || '没有可保存的草稿'); return; } saving.value = true; try { await marketInsightApi.updateEmotionModel(selected.value.model_code, { ...form, parameter_json: clone(parameters) }); await load(); message.success('草稿已保存'); } catch (error) { message.error(error instanceof Error ? error.message : '保存草稿失败'); } finally { saving.value = false; } }
async function calibrate() { if (!selected.value) return; if (isDraft.value && parameterError.value) { message.warning(parameterError.value); return; } calibrating.value = true; try { if (isDraft.value) await saveDraft(); const job = await marketInsightApi.calibrateEmotionModel(selected.value.model_code); await schedulerApi.runJob(job.job_code, job.payload, true); message.success('基线校准已在后台启动，可在调度中心查看进度'); await load(); } catch (error) { message.error(error instanceof Error ? error.message : '启动校准失败'); } finally { calibrating.value = false; } }
async function activate() { if (!selected.value) return; activating.value = true; try { await marketInsightApi.activateEmotionModel(selected.value.model_code); await load(); message.success('V2 情绪模型已启用，后续 22:15 任务将计算双分'); } catch (error) { message.error(error instanceof Error ? error.message : '启用模型失败'); } finally { activating.value = false; } }
onMounted(() => { void load(); });
</script>

<style scoped>
.emotion-model-page { padding: 22px 24px 34px; color: #17212b; }.topbar { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; margin-bottom:14px; }.eyebrow,.panel-kicker{color:#9a6700;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.topbar h1{margin:4px 0 0;font-size:26px}.topbar p{max-width:830px;margin:8px 0 0;color:#667085;line-height:1.6}.page-alert{margin-bottom:14px}.model-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.model-card,.surface{border:1px solid #dce5e9;border-radius:9px;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.03)}.model-card{padding:14px;cursor:pointer;display:grid;gap:11px}.model-card.selected{border-color:#3182ce;box-shadow:0 0 0 2px #bee3f8}.model-card-head{display:flex;justify-content:space-between;gap:10px}.model-card-head>div{display:grid;gap:3px}.model-card strong{font-size:15px}.model-card small,.model-card p,.muted{color:#667085;font-size:12px}.model-card p{margin:0;line-height:1.5}.model-stats{display:flex;flex-wrap:wrap;gap:6px}.model-stats span,.stage-days span{padding:3px 6px;border-radius:4px;color:#475467;background:#f2f4f7;font-size:11px}.model-stats b{color:#1d2939}.surface{padding:16px;margin-top:14px}.panel-heading{display:flex;justify-content:space-between;gap:12px;margin-bottom:14px}.panel-heading h2{margin:3px 0 0;font-size:18px}.settings-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.settings-grid>label,.weight-list>label{display:grid;gap:5px;color:#475467;font-size:12px}.weight-panels{display:grid;grid-template-columns:1fr 1fr .75fr;gap:12px;margin-top:14px}.weight-panel{padding:12px;border:1px solid #e4e9ef;border-radius:7px;background:#fbfcfd}.weight-panel h3{display:flex;justify-content:space-between;gap:10px;margin:0 0 9px;font-size:14px}.weight-panel h3 small{color:#667085;font-size:11px;font-weight:400}.weight-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.weight-list>label{grid-template-columns:minmax(0,1fr) 88px;align-items:center}.editor-actions,.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}.parameter-alert{margin-top:12px}.validation-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.validation-grid article{display:grid;gap:6px;padding:12px;border:1px solid #e4e9ef;border-radius:7px}.validation-grid span{color:#667085;font-size:12px}.validation-grid strong{font-size:18px}.stage-days{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}.panel-note{margin:12px 0 0;color:#667085;font-size:12px;line-height:1.6}@media(max-width:1100px){.model-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.settings-grid,.validation-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.weight-panels{grid-template-columns:1fr}}@media(max-width:700px){.emotion-model-page{padding:14px}.topbar{flex-direction:column}.model-grid,.settings-grid,.validation-grid,.weight-list{grid-template-columns:1fr}}
</style>
