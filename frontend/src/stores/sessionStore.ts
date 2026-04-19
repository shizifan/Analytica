import { create } from 'zustand';
import type { AgentPhase, ChatMessage } from '../types';

interface SessionState {
  sessionId: string | null;
  userId: string;
  employeeId: string | null;
  phase: AgentPhase;
  messages: ChatMessage[];
  sending: boolean;

  setSession: (sessionId: string, userId: string, employeeId?: string | null) => void;
  setPhase: (phase: AgentPhase) => void;
  addMessage: (msg: ChatMessage) => void;
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

  setSession: (sessionId, userId, employeeId = null) =>
    set({ sessionId, userId, employeeId }),

  setPhase: (phase) => set({ phase }),

  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),

  setSending: (sending) => set({ sending }),

  clearConversation: () =>
    set(() => ({
      sessionId: null,
      phase: 'idle',
      messages: [],
      sending: false,
      // Keep userId and employeeId
    })),

  reset: () =>
    set({
      sessionId: null,
      userId: 'anonymous',
      employeeId: null,
      phase: 'idle',
      messages: [],
      sending: false,
    }),
}));
