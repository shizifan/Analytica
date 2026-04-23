/**
 * Build a full session snapshot and trigger a browser JSON download.
 *
 * Exported payload:
 *   exported_at   – ISO timestamp
 *   session_id    – current session
 *   messages      – chat history (role / content pairs)
 *   slots         – slot fill state with values and provenance
 *   plan          – analysis plan + per-task execution statuses
 *   trace         – all API/LLM spans grouped by task_id
 */

import { useSessionStore } from '../stores/sessionStore';
import { useSlotStore } from '../stores/slotStore';
import { usePlanStore } from '../stores/planStore';
import { useTraceStore } from '../stores/traceStore';

export function buildExportPayload() {
  const session = useSessionStore.getState();
  const slotStore = useSlotStore.getState();
  const planStore = usePlanStore.getState();
  const traceStore = useTraceStore.getState();

  const messages = session.messages.map((m) => ({
    role: m.role,
    content: m.content,
    timestamp: m.timestamp,
    ...(m.type ? { type: m.type } : {}),
  }));

  const plan = planStore.plan
    ? {
        ...planStore.plan,
        task_statuses: planStore.taskStatuses,
      }
    : null;

  return {
    exported_at: new Date().toISOString(),
    session_id: session.sessionId,
    messages,
    slots: slotStore.slots,
    plan,
    trace: traceStore.spansByTask,
  };
}

export function downloadSessionJSON() {
  const payload = buildExportPayload();
  const sessionId = payload.session_id ?? 'unknown';
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const filename = `analytica_${sessionId.slice(0, 8)}_${ts}.json`;

  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
