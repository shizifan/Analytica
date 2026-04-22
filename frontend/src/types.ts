/** Shared TypeScript types for Analytica frontend. */

export type SlotSource = 'user_input' | 'memory' | 'memory_low_confidence' | 'inferred' | 'default' | 'history';

export interface SlotState {
  value: unknown;
  source: SlotSource;
  confirmed: boolean;
}

export type PlanStatus = 'idle' | 'planning' | 'ready' | 'executing' | 'done' | 'failed';
export type TaskStatus = 'pending' | 'running' | 'done' | 'error';

export interface TaskItem {
  task_id: string;
  type: string;
  name: string;
  description: string;
  depends_on: string[];
  skill: string;
  params: Record<string, unknown>;
  estimated_seconds: number;
  status: TaskStatus;
  output_ref: string;
}

export interface AnalysisPlan {
  plan_id: string;
  version: number;
  title: string;
  analysis_goal: string;
  estimated_duration: number;
  tasks: TaskItem[];
  report_structure?: Record<string, unknown>;
  revision_log: Array<Record<string, unknown>>;
}

export interface ReflectionSummary {
  user_preferences: Record<string, unknown>;
  analysis_template: Record<string, unknown> | null;
  skill_feedback: Record<string, unknown>;
  slot_quality_review: {
    slots_auto_filled_correctly: string[];
    slots_corrected: string[];
    slots_corrected_detail: Record<string, { from: string; to: string }>;
  };
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  type?: 'text' | 'reflection_card' | 'execution_progress' | 'task_results';
  phase?: string;
  timestamp: number;
  payload?: Record<string, unknown> | null;
}

export type AgentPhase = 'idle' | 'perception' | 'planning' | 'executing' | 'reflection' | 'done';

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'failed';

/** WebSocket incoming event types from backend */
export interface WsSlotUpdateEvent {
  event: 'slot_update';
  slots: Record<string, SlotState>;
  current_asking: string | null;
}

export interface WsMessageEvent {
  event: 'message';
  content: string;
  phase: string;
}

export interface WsIntentReadyEvent {
  event: 'intent_ready';
  intent: Record<string, unknown>;
}

export interface WsPlanUpdateEvent {
  event: 'plan_update';
  plan: AnalysisPlan;
}

export interface WsTaskUpdateEvent {
  event: 'task_update';
  task_id: string;
  status: TaskStatus;
  duration_ms?: number;
}

export interface WsReflectionEvent {
  event: 'reflection';
  summary: ReflectionSummary;
}

export interface WsTurnCompleteEvent {
  event: 'turn_complete';
}

export interface WsConnectedEvent {
  type: 'connected';
  session_id: string;
  employee_id: string | null;
}

export type WsIncomingEvent =
  | WsSlotUpdateEvent
  | WsMessageEvent
  | WsIntentReadyEvent
  | WsPlanUpdateEvent
  | WsTaskUpdateEvent
  | WsReflectionEvent
  | WsTurnCompleteEvent;

// ── Digital Employee types ────────────────────────────────────

export interface EmployeeFAQ {
  id: string;
  question: string;
  tag?: string | null;
  type?: string | null;
}

export interface EmployeeSummary {
  employee_id: string;
  name: string;
  description: string;
  domains: string[];
  version: string;
  initials?: string | null;
  status?: string;
  faqs_count?: number;
  skills_count?: number;
  endpoints_count?: number;
}

export interface EmployeeDetail extends EmployeeSummary {
  skills: string[];
  endpoints: string[];
  faqs: EmployeeFAQ[];
  perception: Record<string, unknown>;
  planning: Record<string, unknown>;
}

export interface EmployeeUpdatePayload {
  name?: string;
  description?: string;
  version?: string;
  initials?: string | null;
  status?: string;
  domains?: string[];
  endpoints?: string[];
  skills?: string[];
  faqs?: EmployeeFAQ[];
  perception?: Record<string, unknown>;
  planning?: Record<string, unknown>;
  snapshot_note?: string;
}

export interface EmployeeVersionSummary {
  version: string;
  note?: string | null;
  created_at: string;
}

// ── Phase 2: thinking stream + persisted messages ─────────────

export type ThinkingKind = 'thinking' | 'tool' | 'decision' | 'phase';

export interface ThinkingEvent {
  id: number;
  session_id?: string;
  kind: ThinkingKind;
  phase?: string | null;
  ts_ms: number;
  payload: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface PersistedMessage {
  id: number;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  type: string;
  phase?: string | null;
  content?: string | null;
  payload?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface SessionSummary {
  session_id: string;
  user_id: string;
  employee_id?: string | null;
  title?: string | null;
  pinned: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

// ── Phase 3.7: structured task results ───────────────────────

export type TaskOutputKind = 'table' | 'chart' | 'text' | 'json' | 'file';

export interface TaskResultTable {
  columns: string[];
  rows: Array<Array<string | number | boolean | null>>;
  total_rows: number;
}

export interface TaskResultChart {
  option: Record<string, unknown>;
}

export interface TaskResultText {
  text: string;
}

export interface TaskResultFile {
  format: string;
  path?: string | null;
}

export interface TaskResult {
  task_id: string;
  name: string;
  skill: string;
  type: string;             // task.type — data_fetch / visualization / analysis / report_gen
  output_type: TaskOutputKind;
  depends_on: string[];
  source_api?: string;
  duration_ms?: number;
  data: TaskResultTable | TaskResultChart | TaskResultText | TaskResultFile | { object: Record<string, unknown> } | null;
}

export interface TaskResultsPayload {
  tasks: TaskResult[];
}
