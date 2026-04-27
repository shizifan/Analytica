import { create } from 'zustand/react';

export type SpanStatus = 'start' | 'ok' | 'error';
export type SpanType = 'api_call' | 'llm_call' | 'param_resolve';

export interface Span {
  span_id: string;
  span_type: SpanType;
  task_id: string;
  status: SpanStatus;
  ts_ms: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
}

interface TraceState {
  /** task_id → Span[] ordered by ts_ms */
  spansByTask: Record<string, Span[]>;
  appendSpan(span: Span): void;
  /** Bulk load from GET /api/sessions/{id}/trace (history replay) */
  loadTasks(tasks: Array<{ task_id: string; spans: Span[] }>): void;
  reset(): void;
}

export const useTraceStore = create<TraceState>((set) => ({
  spansByTask: {},

  appendSpan: (span) =>
    set((s) => {
      const prev = s.spansByTask[span.task_id] ?? [];
      return {
        spansByTask: { ...s.spansByTask, [span.task_id]: [...prev, span] },
      };
    }),

  loadTasks: (tasks) => {
    const grouped: Record<string, Span[]> = {};
    for (const { task_id, spans } of tasks) {
      grouped[task_id] = spans;
    }
    set({ spansByTask: grouped });
  },

  reset: () => set({ spansByTask: {} }),
}));
