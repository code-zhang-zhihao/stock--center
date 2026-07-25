import { requestData } from './client';
import type { SchedulerJob, SchedulerRun, SchedulerRunPage, SchedulerStatus, SchedulerTag } from '@/types/scheduler';

export const schedulerApi = {
  status: () => requestData<SchedulerStatus>({ method: 'GET', url: '/scheduler/status' }),
  jobs: (tagCode?: string | null) =>
    requestData<SchedulerJob[]>({
      method: 'GET',
      url: '/scheduler/jobs',
      params: tagCode ? { tag_code: tagCode } : undefined,
    }),
  tags: () => requestData<SchedulerTag[]>({ method: 'GET', url: '/scheduler/tags' }),
  updateJob: (jobCode: string, payload: Record<string, unknown>) =>
    requestData<SchedulerJob>({ method: 'PATCH', url: `/scheduler/jobs/${encodeURIComponent(jobCode)}`, data: payload }),
  pauseJob: (jobCode: string) => requestData<SchedulerJob>({ method: 'POST', url: `/scheduler/jobs/${jobCode}/pause` }),
  resumeJob: (jobCode: string) => requestData<SchedulerJob>({ method: 'POST', url: `/scheduler/jobs/${jobCode}/resume` }),
  runJob: (jobCode: string, payload: Record<string, unknown>, runAsync = false) =>
    requestData<SchedulerRun>({
      method: 'POST',
      url: `/scheduler/jobs/${jobCode}/run`,
      data: { payload, run_async: runAsync },
    }),
  reload: () => requestData<SchedulerStatus>({ method: 'POST', url: '/scheduler/reload' }),
  runs: (jobCode?: string | null, limit = 20) =>
    requestData<SchedulerRunPage>({
      method: 'GET',
      url: '/scheduler/runs',
      params: { ...(jobCode ? { job_code: jobCode } : {}), limit },
    }),
  runDetail: (runId: string) => requestData<SchedulerRun>({ method: 'GET', url: `/scheduler/runs/${runId}` }),
  cancelRun: (runId: string) =>
    requestData<{ cancel_requested: boolean; active: boolean; run: SchedulerRun | null }>({
      method: 'POST',
      url: `/scheduler/runs/${runId}/cancel`,
    }),
};
