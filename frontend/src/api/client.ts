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

const BASE = '';

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
};
