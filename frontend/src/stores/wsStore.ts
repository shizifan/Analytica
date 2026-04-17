import { create } from 'zustand';
import type { WsStatus } from '../types';

interface WsStore {
  status: WsStatus;
  reconnectCount: number;

  setConnected: (connected: boolean) => void;
  setStatus: (status: WsStatus) => void;
  incrementReconnect: () => void;
}

export const useWsStore = create<WsStore>((set) => ({
  status: 'disconnected',
  reconnectCount: 0,

  setConnected: (connected) =>
    set(connected
      ? { status: 'connected', reconnectCount: 0 }
      : { status: 'disconnected' },
    ),

  setStatus: (status) => set({ status }),

  incrementReconnect: () =>
    set((s) => ({ reconnectCount: s.reconnectCount + 1 })),
}));
