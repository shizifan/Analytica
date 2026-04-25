import { create } from 'zustand';

export type DegradationSeverity = 'info' | 'warn' | 'error';
export type DegradationLayer =
  | 'planning'
  | 'execution'
  | 'collector'
  | 'parser'
  | 'visualization'
  | string;

export interface DegradationEvent {
  layer: DegradationLayer;
  severity: DegradationSeverity;
  reason: string;
  affected?: Record<string, unknown>;
  ts?: number;
}

interface DegradationState {
  events: DegradationEvent[];
  setEvents(events: DegradationEvent[]): void;
  appendEvent(event: DegradationEvent): void;
  reset(): void;
}

/**
 * Cross-cutting degradation channel — mirrors backend
 * `state["degradations"]` (see `backend/agent/degradation.py`).
 *
 * Populated on session hydrate from `state_json.degradations`. When new
 * degradations are produced by a fresh execution, the next hydrate / session
 * fetch picks them up.
 */
export const useDegradationStore = create<DegradationState>((set) => ({
  events: [],
  setEvents: (events) => set({ events: [...events] }),
  appendEvent: (event) =>
    set((s) => ({ events: [...s.events, event] })),
  reset: () => set({ events: [] }),
}));
