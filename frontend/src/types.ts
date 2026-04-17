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
  type?: 'text' | 'reflection_card' | 'execution_progress';
  phase?: string;
  timestamp: number;
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
