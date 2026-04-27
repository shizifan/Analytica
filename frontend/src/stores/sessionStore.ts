import { create } from 'zustand/react';
import type { AgentPhase, ChatMessage } from '../types';

interface SessionState {
  sessionId: string | null;
  userId: string;
  employeeId: string | null;
  phase: AgentPhase;
  messages: ChatMessage[];
  sending: boolean;
  /**
   * T3: highest DB chat_messages.id seen by this store instance.
   * Used as `since_id` for delta hydration on session switch / reconnect,
   * and as the dedup threshold for incoming live WS 'message' events.
   */
  maxMessageId: number;

  setSession: (sessionId: string, userId: string, employeeId?: string | null) => void;
  setPhase: (phase: AgentPhase) => void;
  /**
   * Add a message to the store.
   * @param msg  The chat message to display.
   * @param dbId Optional DB id (chat_messages.id).  When provided the store
   *             deduplicates: if dbId <= maxMessageId the message is silently
   *             dropped (already seen via hydration or a prior broadcast).
   */
  addMessage: (msg: ChatMessage, dbId?: number) => void;
  /** Advance maxMessageId to at least `id` (idempotent). */
  setMaxMessageId: (id: number) => void;
  setSending: (v: boolean) => void;
  clearConversation: () => void;
  reset: () => void;
}

let _msgCounter = 0;
export function makeMessageId(): string {
  return `msg_${Date.now()}_${++_msgCounter}`;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessionId: null,
  userId: 'anonymous',
  employeeId: null,
  phase: 'idle',
  messages: [],
  sending: false,
  maxMessageId: 0,

  setSession: (sessionId, userId, employeeId = null) =>
    set({ sessionId, userId, employeeId }),

  setPhase: (phase) => set({ phase }),

  addMessage: (msg, dbId) =>
    set((s) => {
      if (dbId !== undefined) {
        // T3: deduplicate — skip messages we have already rendered
        if (dbId <= s.maxMessageId) return s;
        return {
          messages: [...s.messages, msg],
          maxMessageId: dbId,
        };
      }
      return { messages: [...s.messages, msg] };
    }),

  setMaxMessageId: (id) =>
    set((s) => ({ maxMessageId: Math.max(s.maxMessageId, id) })),

  setSending: (sending) => set({ sending }),

  clearConversation: () =>
    set({
      sessionId: null,
      phase: 'idle',
      messages: [],
      sending: false,
      maxMessageId: 0,
    }),

  reset: () =>
    set({
      sessionId: null,
      userId: 'anonymous',
      employeeId: null,
      phase: 'idle',
      messages: [],
      sending: false,
      maxMessageId: 0,
    }),
}));
