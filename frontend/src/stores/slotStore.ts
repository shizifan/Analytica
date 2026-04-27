import { create } from 'zustand/react';
import type { SlotState } from '../types';

interface SlotStore {
  slots: Record<string, SlotState>;
  currentAsking: string | null;

  updateSlot: (name: string, data: Partial<SlotState>) => void;
  setSlots: (slots: Record<string, SlotState>) => void;
  setCurrentAsking: (name: string | null) => void;
  resetSlots: () => void;
}

export const useSlotStore = create<SlotStore>((set) => ({
  slots: {},
  currentAsking: null,

  updateSlot: (name, data) =>
    set((s) => ({
      slots: {
        ...s.slots,
        [name]: { ...s.slots[name], ...data } as SlotState,
      },
    })),

  setSlots: (slots) => set({ slots }),

  setCurrentAsking: (name) => set({ currentAsking: name }),

  resetSlots: () => set({ slots: {}, currentAsking: null }),
}));
