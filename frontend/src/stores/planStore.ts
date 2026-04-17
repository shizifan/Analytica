import { create } from 'zustand';
import type { AnalysisPlan, PlanStatus, TaskStatus } from '../types';

interface PlanStore {
  plan: AnalysisPlan | null;
  status: PlanStatus;
  taskStatuses: Record<string, TaskStatus>;

  setPlan: (plan: AnalysisPlan) => void;
  setStatus: (status: PlanStatus) => void;
  updateTaskStatus: (taskId: string, status: TaskStatus) => void;
  reset: () => void;
}

export const usePlanStore = create<PlanStore>((set) => ({
  plan: null,
  status: 'idle',
  taskStatuses: {},

  setPlan: (plan) =>
    set({
      plan,
      status: 'ready',
      taskStatuses: Object.fromEntries(
        plan.tasks.map((t) => [t.task_id, 'pending' as TaskStatus]),
      ),
    }),

  setStatus: (status) => set({ status }),

  updateTaskStatus: (taskId, status) =>
    set((s) => ({
      taskStatuses: { ...s.taskStatuses, [taskId]: status },
    })),

  reset: () =>
    set({ plan: null, status: 'idle', taskStatuses: {} }),
}));
