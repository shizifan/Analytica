/**
 * TC-STORE01~05: Zustand Store unit tests.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useSlotStore } from '../stores/slotStore';
import { usePlanStore } from '../stores/planStore';
import { useWsStore } from '../stores/wsStore';
import { useSessionStore, makeMessageId } from '../stores/sessionStore';
import type { AnalysisPlan, TaskItem } from '../types';

// Helper: create a minimal plan with N tasks
function makePlan(taskIds: string[]): AnalysisPlan {
  const tasks: TaskItem[] = taskIds.map((id) => ({
    task_id: id,
    type: 'analysis',
    name: `Task ${id}`,
    description: `Description for ${id}`,
    depends_on: [],
    skill: 'mock_skill',
    params: {},
    estimated_seconds: 10,
    status: 'pending',
    output_ref: '',
  }));
  return {
    plan_id: 'plan_1',
    version: 1,
    title: 'Test Plan',
    analysis_goal: 'Test goal',
    estimated_duration: 30,
    tasks,
    revision_log: [],
  };
}

// ── TC-STORE01: slotStore.updateSlot ──────────────────────────
describe('TC-STORE01: slotStore.updateSlot', () => {
  beforeEach(() => {
    useSlotStore.getState().resetSlots();
  });

  it('updates the specified slot without affecting others', () => {
    const { updateSlot } = useSlotStore.getState();

    // Pre-fill two slots
    updateSlot('analysis_subject', { value: 'port_data', source: 'user_input', confirmed: true });
    updateSlot('time_range', { value: '2024Q1', source: 'inferred', confirmed: false });

    // Update only time_range
    updateSlot('time_range', { value: '2024Q1', confirmed: true });

    const { slots } = useSlotStore.getState();
    expect(slots['time_range'].value).toBe('2024Q1');
    expect(slots['time_range'].confirmed).toBe(true);
    // analysis_subject should be unchanged
    expect(slots['analysis_subject'].value).toBe('port_data');
    expect(slots['analysis_subject'].confirmed).toBe(true);
  });
});

// ── TC-STORE02: slotStore.resetSlots ──────────────────────────
describe('TC-STORE02: slotStore.resetSlots', () => {
  beforeEach(() => {
    useSlotStore.getState().resetSlots();
  });

  it('clears all slots to empty object', () => {
    const { updateSlot, resetSlots } = useSlotStore.getState();

    // Fill 3 slots
    updateSlot('analysis_subject', { value: 'a', source: 'user_input', confirmed: true });
    updateSlot('time_range', { value: 'b', source: 'user_input', confirmed: true });
    updateSlot('output_format', { value: 'c', source: 'memory', confirmed: true });

    expect(Object.keys(useSlotStore.getState().slots)).toHaveLength(3);

    resetSlots();

    expect(useSlotStore.getState().slots).toEqual({});
    expect(useSlotStore.getState().currentAsking).toBeNull();
  });
});

// ── TC-STORE03: planStore.updateTaskStatus ────────────────────
describe('TC-STORE03: planStore.updateTaskStatus', () => {
  beforeEach(() => {
    usePlanStore.getState().reset();
  });

  it('updates one task status without affecting others', () => {
    const { setPlan, updateTaskStatus } = usePlanStore.getState();
    const plan = makePlan(['T1', 'T2', 'T3']);

    setPlan(plan);

    // All should be pending after setPlan
    const initial = usePlanStore.getState().taskStatuses;
    expect(initial['T1']).toBe('pending');
    expect(initial['T2']).toBe('pending');
    expect(initial['T3']).toBe('pending');

    // Update only T2
    updateTaskStatus('T2', 'done');

    const updated = usePlanStore.getState().taskStatuses;
    expect(updated['T2']).toBe('done');
    expect(updated['T1']).toBe('pending');
    expect(updated['T3']).toBe('pending');
  });
});

// ── TC-STORE04: planStore state transitions ───────────────────
describe('TC-STORE04: planStore state transitions', () => {
  beforeEach(() => {
    usePlanStore.getState().reset();
  });

  it('follows idle → planning → ready → executing → idle', () => {
    const { setStatus, setPlan, reset } = usePlanStore.getState();

    // Initial state
    expect(usePlanStore.getState().status).toBe('idle');

    // idle → planning
    setStatus('planning');
    expect(usePlanStore.getState().status).toBe('planning');

    // planning → ready (via setPlan)
    const plan = makePlan(['T1']);
    setPlan(plan);
    expect(usePlanStore.getState().status).toBe('ready');

    // ready → executing
    setStatus('executing');
    expect(usePlanStore.getState().status).toBe('executing');

    // executing → idle (via reset)
    reset();
    expect(usePlanStore.getState().status).toBe('idle');
  });
});

// ── TC-STORE05: wsStore reconnect count + reset ───────────────
describe('TC-STORE05: wsStore reconnect count and reset', () => {
  beforeEach(() => {
    useWsStore.setState({ status: 'disconnected', reconnectCount: 0 });
  });

  it('accumulates reconnect count, resets on connected', () => {
    const { incrementReconnect, setConnected } = useWsStore.getState();

    // Increment 3 times
    incrementReconnect();
    incrementReconnect();
    incrementReconnect();
    expect(useWsStore.getState().reconnectCount).toBe(3);
    expect(useWsStore.getState().status).toBe('disconnected');

    // Simulate reconnection success
    setConnected(true);
    expect(useWsStore.getState().status).toBe('connected');
    expect(useWsStore.getState().reconnectCount).toBe(0);
  });

  it('sets status to disconnected when setConnected(false)', () => {
    useWsStore.getState().setConnected(true);
    expect(useWsStore.getState().status).toBe('connected');

    useWsStore.getState().setConnected(false);
    expect(useWsStore.getState().status).toBe('disconnected');
  });
});

// ── Additional: sessionStore basic tests ──────────────────────
describe('sessionStore basic operations', () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
  });

  it('setSession sets session data', () => {
    useSessionStore.getState().setSession('s1', 'user1', 'emp1');
    const state = useSessionStore.getState();
    expect(state.sessionId).toBe('s1');
    expect(state.userId).toBe('user1');
    expect(state.employeeId).toBe('emp1');
  });

  it('addMessage appends to messages list', () => {
    const { addMessage } = useSessionStore.getState();
    addMessage({ id: 'msg1', role: 'user', content: 'hello', timestamp: 1 });
    addMessage({ id: 'msg2', role: 'assistant', content: 'hi', timestamp: 2 });

    const { messages } = useSessionStore.getState();
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe('user');
    expect(messages[1].role).toBe('assistant');
  });

  it('makeMessageId generates unique IDs', () => {
    const id1 = makeMessageId();
    const id2 = makeMessageId();
    expect(id1).not.toBe(id2);
    expect(id1.startsWith('msg_')).toBe(true);
  });

  it('reset clears all state', () => {
    useSessionStore.getState().setSession('s1', 'user1');
    useSessionStore.getState().addMessage({
      id: 'msg1', role: 'user', content: 'test', timestamp: 1,
    });

    useSessionStore.getState().reset();
    const state = useSessionStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.messages).toHaveLength(0);
    expect(state.phase).toBe('idle');
  });
});
