/** Hydrate client state from the server after refresh / session switch.
 *
 * Replays:
 *   - chat_messages → sessionStore.messages
 *   - thinking_events → thinkingStore.events
 *   - state_json.slots / analysis_plan / task_statuses → slot + plan stores
 *
 * Replay is best-effort: if any request fails we keep whatever the WS
 * handshake gives us instead.
 */
import { api } from '../api/client';
import { useSessionStore, makeMessageId } from '../stores/sessionStore';
import { useSlotStore } from '../stores/slotStore';
import { usePlanStore } from '../stores/planStore';
import { useThinkingStore } from '../stores/thinkingStore';
import type {
  AnalysisPlan,
  ChatMessage,
  PlanStatus,
  SlotState,
  TaskStatus,
  ThinkingEvent,
} from '../types';

const KNOWN_MSG_TYPES = new Set([
  'text', 'reflection_card', 'execution_progress', 'task_results',
]);

const TERMINAL_TASK_STATES: Set<TaskStatus> = new Set([
  'done', 'error',
]);

function derivePlanStatus(
  taskStatuses: Record<string, TaskStatus>,
  totalTasks: number,
): PlanStatus {
  const vals = Object.values(taskStatuses);
  if (vals.length === 0) return 'ready';
  // If the DB snapshot only has some of the plan's tasks recorded, the
  // backend is still mid-execution — treat as executing even if every
  // recorded entry is terminal. (P1 per-layer persistence makes this
  // partial-state case reachable during normal session switches.)
  if (vals.length < totalTasks) return 'executing';
  const allTerminal = vals.every((v) => TERMINAL_TASK_STATES.has(v));
  if (allTerminal) return 'done';
  if (vals.some((v) => v === 'running' || v === 'pending')) return 'executing';
  return 'ready';
}

export async function hydrateSession(sessionId: string): Promise<void> {
  try {
    const [msgRes, thkRes, sessionRes] = await Promise.all([
      api.replayMessages(sessionId),
      api.replayThinking(sessionId),
      api.getSession(sessionId).catch(() => null),
    ]);

    // ── chat messages ─────────────────────────────────────
    const store = useSessionStore.getState();
    if (store.messages.length === 0) {
      const hydrated: ChatMessage[] = msgRes.items.map((m) => {
        const msgType = KNOWN_MSG_TYPES.has(m.type) ? (m.type as ChatMessage['type']) : undefined;
        return {
          id: `persisted_${m.id}`,
          role: m.role,
          content: m.content ?? '',
          ...(msgType === 'text' || msgType === undefined ? {} : { type: msgType }),
          phase: m.phase ?? undefined,
          timestamp: m.created_at ? new Date(m.created_at).getTime() : Date.now(),
          payload: m.payload ?? null,
        };
      });
      for (const msg of hydrated) {
        store.addMessage(msg);
      }
    }

    // ── thinking events ───────────────────────────────────
    const thkStore = useThinkingStore.getState();
    if (thkStore.events.length === 0) {
      const events: ThinkingEvent[] = thkRes.items.map((e) => ({
        id: e.id,
        kind: e.kind,
        phase: e.phase,
        ts_ms: e.ts_ms,
        payload: e.payload,
        created_at: e.created_at,
      }));
      thkStore.setEvents(events);
    }

    // ── slot + plan state (Phase 3.7.1) ───────────────────
    if (sessionRes && typeof sessionRes === 'object') {
      const stateJson = (sessionRes as { state_json?: Record<string, unknown> }).state_json;
      if (stateJson && typeof stateJson === 'object') {
        const slots = stateJson.slots as Record<string, SlotState> | undefined;
        if (slots && typeof slots === 'object' && Object.keys(slots).length > 0) {
          if (Object.keys(useSlotStore.getState().slots).length === 0) {
            useSlotStore.getState().setSlots(slots);
          }
        }

        const analysisPlan = stateJson.analysis_plan as AnalysisPlan | undefined;
        const taskStatuses = stateJson.task_statuses as Record<string, TaskStatus> | undefined;
        const planStore = usePlanStore.getState();
        if (analysisPlan && !planStore.plan) {
          planStore.setPlan(analysisPlan);
          if (taskStatuses && typeof taskStatuses === 'object') {
            for (const [tid, st] of Object.entries(taskStatuses)) {
              planStore.updateTaskStatus(tid, st);
            }
            planStore.setStatus(
              derivePlanStatus(taskStatuses, analysisPlan.tasks.length),
            );
          }
        }
      }
    }
  } catch (err) {
    if (import.meta.env.DEV) {
      console.warn('[hydrate] replay failed', err);
    }
  }
  void makeMessageId;
}
