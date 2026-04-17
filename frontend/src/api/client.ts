/** Lightweight API client — no Axios, uses native fetch. */

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
};
