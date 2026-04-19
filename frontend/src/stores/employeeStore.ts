import { create } from 'zustand';
import { api } from '../api/client';
import type { EmployeeSummary, EmployeeDetail } from '../types';

interface EmployeeState {
  employees: EmployeeSummary[];
  selectedId: string | null;
  loading: boolean;
  detail: EmployeeDetail | null;
  detailLoading: boolean;
  error: string | null;

  fetchEmployees: () => Promise<void>;
  setSelectedId: (id: string | null) => void;
  fetchDetail: (id: string) => Promise<void>;
  clearDetail: () => void;
  updateInList: (updated: EmployeeSummary) => void;
}

export const useEmployeeStore = create<EmployeeState>((set, get) => ({
  employees: [],
  selectedId: null,
  loading: false,
  detail: null,
  detailLoading: false,
  error: null,

  fetchEmployees: async () => {
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const employees = await api.listEmployees();
      set({ employees, loading: false });
    } catch (err) {
      set({ error: String(err), loading: false });
    }
  },

  setSelectedId: (id) => set({ selectedId: id }),

  fetchDetail: async (id) => {
    set({ detailLoading: true, error: null });
    try {
      const detail = await api.getEmployee(id);
      set({ detail, detailLoading: false });
    } catch (err) {
      set({ error: String(err), detailLoading: false });
    }
  },

  clearDetail: () => set({ detail: null }),

  updateInList: (updated) =>
    set((s) => ({
      employees: s.employees.map((e) =>
        e.employee_id === updated.employee_id ? updated : e
      ),
    })),
}));
