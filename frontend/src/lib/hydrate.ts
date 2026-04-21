/** Hydrate client state from the server after refresh / session switch.
 *
 * Only replays recently-persisted chat messages + thinking events —
 * slot/plan/reflection state still comes from the next WS tick. Replay is
 * best-effort: if the request fails, we keep whatever the WS handshake
 * gives us.
 */
import { api } from '../api/client';
import { useSessionStore, makeMessageId } from '../stores/sessionStore';
import { useThinkingStore } from '../stores/thinkingStore';
import type { ChatMessage, ThinkingEvent } from '../types';

export async function hydrateSession(sessionId: string): Promise<void> {
  try {
    const [msgRes, thkRes] = await Promise.all([
      api.replayMessages(sessionId),
      api.replayThinking(sessionId),
    ]);

    const store = useSessionStore.getState();
    // If the user is mid-stream, don't clobber the in-flight buffer.
    if (store.messages.length === 0) {
      const KNOWN_TYPES = new Set(['text', 'reflection_card', 'execution_progress']);
      const hydrated: ChatMessage[] = msgRes.items.map((m) => {
        const msgType = KNOWN_TYPES.has(m.type) ? (m.type as ChatMessage['type']) : undefined;
        return {
          id: `persisted_${m.id}`,
          role: m.role,
          content: m.content ?? '',
          ...(msgType === 'text' || msgType === undefined ? {} : { type: msgType }),
          phase: m.phase ?? undefined,
          timestamp: m.created_at ? new Date(m.created_at).getTime() : Date.now(),
        };
      });
      for (const msg of hydrated) {
        store.addMessage(msg);
      }
    }

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
  } catch (err) {
    // Hydration is best-effort; swallow errors (first-load sessions will 404).
    if (import.meta.env.DEV) {
      console.warn('[hydrate] replay failed', err);
    }
  }
  // Ensure unused import warning doesn't fire — makeMessageId is kept for
  // future use when we need client-side ids for hydrated messages.
  void makeMessageId;
}
