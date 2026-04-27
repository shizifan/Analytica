import { create } from 'zustand/react';
import type { ThinkingEvent } from '../types';

interface ThinkingState {
  events: ThinkingEvent[];
  /** Highest id seen — used by replay to fetch new rows without overlap. */
  highWater: number;

  appendEvent(evt: ThinkingEvent): void;
  setEvents(evts: ThinkingEvent[]): void;
  reset(): void;
}

let _localCounter = 0;

/** WS-delivered events have no DB id until message_persisted arrives.
 *  Stamp them with a local negative id so they sort sensibly relative
 *  to persisted rows. Replay prunes these when the DB row surfaces. */
export function ephemeralThinkingId(): number {
  return -(++_localCounter);
}

export const useThinkingStore = create<ThinkingState>((set) => ({
  events: [],
  highWater: 0,

  appendEvent: (evt) =>
    set((s) => ({
      events: [...s.events, evt],
      highWater: evt.id > 0 ? Math.max(s.highWater, evt.id) : s.highWater,
    })),

  setEvents: (evts) =>
    set({
      events: evts,
      highWater: evts.reduce((m, e) => (e.id > m ? e.id : m), 0),
    }),

  reset: () => set({ events: [], highWater: 0 }),
}));
