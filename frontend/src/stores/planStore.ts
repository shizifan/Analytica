import { create } from 'zustand';
import type { AnalysisPlan, PlanStatus, TaskStatus } from '../types';

interface PlanStore {
  plan: AnalysisPlan | null;
  status: PlanStatus;
  taskStatuses: Record<string, TaskStatus>;

  /** Multi-turn: archived plans from previous turns. */
  planHistory: AnalysisPlan[];
  /** Multi-turn: which turn's plan is currently displayed (0 = current). */
  selectedTurnIndex: number;

  setPlan: (plan: AnalysisPlan) => void;
  setStatus: (status: PlanStatus) => void;
  updateTaskStatus: (taskId: string, status: TaskStatus) => void;
  reset: () => void;

  /** Multi-turn: set the plan history from state_json.plan_history. */
  setPlanHistory: (plans: AnalysisPlan[]) => void;
  /** Multi-turn: select a turn's plan for viewing. */
  setSelectedTurnIndex: (idx: number) => void;
}

export const usePlanStore = create<PlanStore>((set) => ({
  plan: null,
  status: 'idle',
  taskStatuses: {},
  planHistory: [],
  selectedTurnIndex: 0,

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
    set({ plan: null, status: 'idle', taskStatuses: {}, planHistory: [], selectedTurnIndex: 0 }),

  setPlanHistory: (plans) => set({ planHistory: plans }),

  setSelectedTurnIndex: (idx) => set({ selectedTurnIndex: idx }),
}));
