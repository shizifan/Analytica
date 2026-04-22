/** Lightweight API client — no Axios, uses native fetch. */

import type {
  EmployeeDetail,
  EmployeeSummary,
  EmployeeUpdatePayload,
  EmployeeVersionSummary,
  PersistedMessage,
  SessionSummary,
  ThinkingEvent,
} from '../types';

// 统一用 Vite 的 BASE_URL（即 vite.config 里的 `base`）做前缀，
// 这样无论部署在根路径还是 `/analytica/` 子路径下都能正确拼接。
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '');

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${method} ${path} → ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  createSession: (userId: string, employeeId?: string) =>
    request<{ session_id: string }>('POST', '/api/sessions', {
      user_id: userId,
      employee_id: employeeId ?? null,
    }),

  getSession: (sessionId: string) =>
    request<Record<string, unknown>>('GET', `/api/sessions/${sessionId}`),

  getPlan: (sessionId: string) =>
    request<Record<string, unknown>>('GET', `/api/sessions/${sessionId}/plan`),

  confirmPlan: (sessionId: string, confirmed = true, modifications: unknown[] = []) =>
    request<Record<string, unknown>>('POST', `/api/sessions/${sessionId}/plan/confirm`, {
      confirmed,
      modifications,
    }),

  saveReflection: (
    sessionId: string,
    opts: { save_preferences?: boolean; save_template?: boolean; save_skill_notes?: boolean } = {},
  ) =>
    request<{ status: string; saved: Record<string, unknown> }>(
      'POST',
      `/api/sessions/${sessionId}/reflection/save`,
      {
        save_preferences: opts.save_preferences ?? true,
        save_template: opts.save_template ?? true,
        save_skill_notes: opts.save_skill_notes ?? true,
      },
    ),

  listEmployees: () =>
    request<EmployeeSummary[]>('GET', '/api/employees'),

  getEmployee: (id: string) =>
    request<EmployeeDetail>('GET', `/api/employees/${id}`),

  updateEmployee: (id: string, payload: EmployeeUpdatePayload) =>
    request<EmployeeDetail>('PUT', `/api/employees/${id}`, payload),

  createEmployee: (id: string, payload: EmployeeUpdatePayload) =>
    request<EmployeeDetail>('POST', `/api/employees/${id}`, payload),

  deleteEmployee: (id: string) =>
    request<{ status: string; employee_id: string }>(
      'DELETE', `/api/employees/${id}`,
    ),

  listEmployeeVersions: (id: string) =>
    request<{ items: EmployeeVersionSummary[]; count: number }>(
      'GET', `/api/employees/${id}/versions`,
    ),

  // ── Phase 2 ──────────────────────────────────────────────
  listSessions: (userId?: string, limit = 50, offset = 0) => {
    const params = new URLSearchParams();
    if (userId) params.set('user_id', userId);
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    return request<{ items: SessionSummary[]; count: number }>(
      'GET',
      `/api/sessions?${params.toString()}`,
    );
  },

  replayMessages: (sessionId: string, sinceId = 0, limit = 200) =>
    request<{ items: PersistedMessage[]; count: number; since_id: number }>(
      'GET',
      `/api/sessions/${sessionId}/messages?since_id=${sinceId}&limit=${limit}`,
    ),

  replayThinking: (
    sessionId: string,
    opts: { sinceId?: number; kind?: string; limit?: number } = {},
  ) => {
    const params = new URLSearchParams();
    params.set('since_id', String(opts.sinceId ?? 0));
    if (opts.kind) params.set('kind', opts.kind);
    params.set('limit', String(opts.limit ?? 500));
    return request<{ items: ThinkingEvent[]; count: number; since_id: number }>(
      'GET',
      `/api/sessions/${sessionId}/thinking?${params.toString()}`,
    );
  },

  deleteSession: (sessionId: string) =>
    request<{ status: string; session_id: string }>(
      'DELETE',
      `/api/sessions/${sessionId}`,
    ),

  convertReport: (artifactId: string, format: 'docx' | 'pptx') =>
    request<{ artifact_id: string; format: string; status: string }>(
      'POST',
      `/api/reports/${artifactId}/convert?format=${format}`,
    ),

  // ── Phase 6 · Admin Console ──────────────────────────────
  admin: {
    listApis: (opts: { domain?: string; q?: string; limit?: number } = {}) => {
      const p = new URLSearchParams();
      if (opts.domain) p.set('domain', opts.domain);
      if (opts.q) p.set('q', opts.q);
      p.set('limit', String(opts.limit ?? 500));
      return request<{ items: AdminApi[]; count: number }>(
        'GET',
        `/api/admin/apis?${p.toString()}`,
      );
    },
    getApiStats: (name: string, days = 7) =>
      request<{ api_name: string; days: number; series: Array<Record<string, unknown>>; total_calls: number; total_errors: number; error_rate: number; last_called_at?: string }>(
        'GET',
        `/api/admin/apis/${encodeURIComponent(name)}/stats?days=${days}`,
      ),
    deleteApi: (name: string) =>
      request<{ status: string; name: string }>(
        'DELETE',
        `/api/admin/apis/${encodeURIComponent(name)}`,
      ),

    listSkills: () =>
      request<{ items: AdminSkill[]; count: number }>('GET', '/api/admin/skills'),
    toggleSkill: (id: string, enabled: boolean) =>
      request<{ status: string; skill_id: string; enabled: boolean }>(
        'POST',
        `/api/admin/skills/${encodeURIComponent(id)}/toggle?enabled=${enabled}`,
      ),

    listDomains: () =>
      request<{ items: AdminDomain[]; count: number }>('GET', '/api/admin/domains'),

    listMemories: (userId?: string, limit = 100) => {
      const p = new URLSearchParams();
      if (userId) p.set('user_id', userId);
      p.set('limit', String(limit));
      return request<{
        preferences: Array<Record<string, unknown>>;
        templates: Array<Record<string, unknown>>;
        skill_notes: Array<Record<string, unknown>>;
      }>('GET', `/api/admin/memories?${p.toString()}`);
    },
    deleteMemory: (kind: string, entryId: string) =>
      request<{ status: string; kind: string; id: string }>(
        'DELETE',
        `/api/admin/memories/${kind}/${encodeURIComponent(entryId)}`,
      ),

    listAudit: (opts: { resourceType?: string; actorId?: string; limit?: number; offset?: number } = {}) => {
      const p = new URLSearchParams();
      if (opts.resourceType) p.set('resource_type', opts.resourceType);
      if (opts.actorId) p.set('actor_id', opts.actorId);
      p.set('limit', String(opts.limit ?? 100));
      p.set('offset', String(opts.offset ?? 0));
      return request<{ items: AdminAuditEntry[]; count: number }>(
        'GET',
        `/api/admin/audit?${p.toString()}`,
      );
    },
  },
};

// ── Admin types (local — a proper types file can consolidate later) ─

export interface AdminApi {
  name: string;
  method: string;
  path: string;
  domain: string;
  intent?: string | null;
  tags: string[];
  required_params: string[];
  optional_params: string[];
  source: string;
  enabled: boolean;
  updated_at?: string;
}

export interface AdminSkill {
  skill_id: string;
  name: string;
  kind: string;
  description?: string | null;
  domains: string[];
  enabled: boolean;
  run_count: number;
  error_count: number;
  avg_latency_ms?: number | null;
  last_error_at?: string | null;
  last_error_msg?: string | null;
  updated_at?: string;
}

export interface AdminDomain {
  code: string;
  name: string;
  description?: string | null;
  color?: string | null;
  top_tags: string[];
  api_count: number;
  employee_count: number;
  updated_at?: string;
}

export interface AdminAuditEntry {
  id: number;
  ts: string;
  actor_id?: string | null;
  actor_type: string;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  result: string;
  duration_ms?: number | null;
  diff?: Record<string, unknown> | null;
  ip?: string | null;
}
