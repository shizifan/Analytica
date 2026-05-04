/**
 * TC-UI01~15: React component render & interaction tests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useSlotStore } from '../stores/slotStore';
import { usePlanStore } from '../stores/planStore';
import { useWsStore } from '../stores/wsStore';
import { useSessionStore } from '../stores/sessionStore';

import { SlotStatusCard } from '../components/SlotStatusCard';
import { PlanCard } from '../components/PlanCard';
import { ExecutionProgress } from '../components/ExecutionProgress';
import { ReflectionCard } from '../components/ReflectionCard';
import { ChatMessage } from '../components/ChatMessage';
import { InputBar } from '../components/InputBar';

import type { AnalysisPlan, TaskItem, ReflectionSummary } from '../types';

// ── Helpers ──────────────────────────────────────────────────

function makePlan(taskIds: string[]): AnalysisPlan {
  const tasks: TaskItem[] = taskIds.map((id) => ({
    task_id: id,
    type: 'analysis',
    name: `Task ${id}`,
    description: `Description for ${id}`,
    depends_on: [],
    tool: 'mock_tool',
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

function resetAllStores() {
  useSlotStore.getState().resetSlots();
  usePlanStore.getState().reset();
  useWsStore.setState({ status: 'disconnected', reconnectCount: 0 });
  useSessionStore.getState().reset();
}

// ── TC-UI01: SlotStatusCard initial render ────────────────────
describe('TC-UI01: SlotStatusCard initial render', () => {
  beforeEach(resetAllStores);

  it('renders empty state with waiting text', () => {
    render(<SlotStatusCard />);
    expect(screen.getByText('等待分析开始...')).toBeInTheDocument();
    expect(screen.queryByTestId('slot-complete-banner')).not.toBeInTheDocument();
  });
});

// ── TC-UI02: SlotStatusCard memory pre-fill badge ─────────────
describe('TC-UI02: SlotStatusCard memory pre-fill badge', () => {
  beforeEach(resetAllStores);

  it('shows blue badge with "来自记忆" for memory source', () => {
    useSlotStore.getState().setSlots({
      output_format: { value: 'chart_text', source: 'memory', confirmed: true },
    });

    render(<SlotStatusCard />);
    const slot = screen.getByTestId('slot-output_format');
    expect(slot).toBeInTheDocument();
    expect(slot.getAttribute('data-source')).toBe('memory');
    expect(screen.getByText('来自记忆')).toBeInTheDocument();
  });
});

// ── TC-UI03: SlotStatusCard "信息完整" banner ──────────────────
describe('TC-UI03: SlotStatusCard complete banner', () => {
  beforeEach(resetAllStores);

  it('shows green banner when all required slots are filled', () => {
    useSlotStore.getState().setSlots({
      analysis_subject: { value: 'port', source: 'user_input', confirmed: true },
      time_range: { value: '2024', source: 'user_input', confirmed: true },
      output_complexity: { value: 'simple', source: 'inferred', confirmed: true },
    });

    render(<SlotStatusCard />);
    expect(screen.getByTestId('slot-complete-banner')).toBeInTheDocument();
  });

  it('does NOT show banner when required slot is missing', () => {
    useSlotStore.getState().setSlots({
      analysis_subject: { value: 'port', source: 'user_input', confirmed: true },
      // time_range is missing!
      output_complexity: { value: 'simple', source: 'inferred', confirmed: true },
    });

    render(<SlotStatusCard />);
    expect(screen.queryByTestId('slot-complete-banner')).not.toBeInTheDocument();
  });
});

// ── TC-UI04: PlanCard planning state ──────────────────────────
describe('TC-UI04: PlanCard planning state', () => {
  beforeEach(resetAllStores);

  it('shows spinner and loading text during planning', () => {
    usePlanStore.getState().setStatus('planning');
    render(<PlanCard />);
    expect(screen.getByText('规划方案生成中...')).toBeInTheDocument();
  });
});

// ── TC-UI05: PlanCard ready state with task list ──────────────
describe('TC-UI05: PlanCard ready state', () => {
  beforeEach(resetAllStores);

  it('renders task list when plan is ready', () => {
    const plan = makePlan(['T1', 'T2', 'T3']);
    usePlanStore.getState().setPlan(plan);

    render(<PlanCard />);
    const taskList = screen.getByTestId('plan-task-list');
    expect(taskList).toBeInTheDocument();
    // Task names rendered as "{i}. {name}" across child nodes
    expect(taskList.textContent).toContain('Task T1');
    expect(taskList.textContent).toContain('Task T2');
    expect(taskList.textContent).toContain('Task T3');
  });
});

// ── TC-UI06: ExecutionProgress concurrent tasks ───────────────
describe('TC-UI06: ExecutionProgress concurrent running tasks', () => {
  beforeEach(resetAllStores);

  it('shows running animation for multiple concurrent tasks', () => {
    const plan = makePlan(['T1', 'T2', 'T3', 'T4']);
    usePlanStore.getState().setPlan(plan);
    usePlanStore.getState().setStatus('executing');
    usePlanStore.getState().updateTaskStatus('T1', 'done');
    usePlanStore.getState().updateTaskStatus('T2', 'running');
    usePlanStore.getState().updateTaskStatus('T3', 'running');

    render(<ExecutionProgress />);
    const progress = screen.getByTestId('execution-progress');
    expect(progress).toBeInTheDocument();
    // Should show [1/4] since only T1 is done
    expect(screen.getByText(/\[1\/4\]/)).toBeInTheDocument();
    // Should show at least one "进行中..."
    expect(screen.getAllByText('进行中...').length).toBeGreaterThanOrEqual(1);
  });

  it('returns null when status is not executing', () => {
    usePlanStore.getState().setStatus('ready');
    const { container } = render(<ExecutionProgress />);
    expect(container.innerHTML).toBe('');
  });
});

// ── TC-UI07: ReflectionCard save interaction ──────────────────
describe('TC-UI07: ReflectionCard save preferences', () => {
  beforeEach(resetAllStores);

  const mockSummary: ReflectionSummary = {
    user_preferences: { output_format: 'chart_text', time_granularity: 'monthly' },
    analysis_template: { template_name: 'port_analysis' },
    tool_feedback: { well_performed: ['data_fetch'] },
    slot_quality_review: {
      slots_auto_filled_correctly: ['analysis_subject'],
      slots_corrected: [],
      slots_corrected_detail: {},
    },
  };

  it('renders preferences and save/dismiss buttons', () => {
    render(<ReflectionCard summary={mockSummary} sessionId="s1" />);
    expect(screen.getByTestId('reflection-card')).toBeInTheDocument();
    expect(screen.getByText('全部保存')).toBeInTheDocument();
    expect(screen.getByText('忽略本次')).toBeInTheDocument();
  });

  it('returns null when summary is null', () => {
    const { container } = render(<ReflectionCard summary={null} sessionId="s1" />);
    expect(container.innerHTML).toBe('');
  });
});

// ── TC-UI08: ReflectionCard dismiss hides card ────────────────
describe('TC-UI08: ReflectionCard dismiss', () => {
  beforeEach(resetAllStores);

  const mockSummary: ReflectionSummary = {
    user_preferences: { output_format: 'chart_text' },
    analysis_template: null,
    tool_feedback: {},
    slot_quality_review: {
      slots_auto_filled_correctly: [],
      slots_corrected: [],
      slots_corrected_detail: {},
    },
  };

  it('hides the card after clicking dismiss', async () => {
    // Mock the api.saveReflection
    vi.mock('../api/client', () => ({
      api: {
        saveReflection: vi.fn().mockResolvedValue({ status: 'ok', saved: {} }),
      },
    }));

    render(<ReflectionCard summary={mockSummary} sessionId="s1" />);
    expect(screen.getByTestId('reflection-card')).toBeInTheDocument();

    await userEvent.click(screen.getByText('忽略本次'));

    // Card should disappear
    await waitFor(() => {
      expect(screen.queryByTestId('reflection-card')).not.toBeInTheDocument();
    });
  });
});

// ── TC-UI09: EChartsViewer loading skeleton ───────────────────
describe('TC-UI09: EChartsViewer loading skeleton', () => {
  it('renders skeleton when loading=true', async () => {
    // Dynamic import to avoid echarts SSR issues
    const { EChartsViewer } = await import('../components/EChartsViewer');
    render(<EChartsViewer option={{}} loading={true} height={300} />);
    const skeleton = screen.getByTestId('echart-skeleton');
    expect(skeleton).toBeInTheDocument();
    expect(skeleton.style.height).toBe('300px');
  });
});

// ── TC-UI13: ChatMessage Markdown rendering ───────────────────
describe('TC-UI13: ChatMessage Markdown rendering', () => {
  it('renders user message as plain text in blue bubble', () => {
    render(
      <ChatMessage
        message={{
          id: 'msg1',
          role: 'user',
          content: 'Hello world',
          timestamp: Date.now(),
        }}
      />,
    );
    const msg = screen.getByTestId('chat-message-user');
    expect(msg).toBeInTheDocument();
    expect(screen.getByText('Hello world')).toBeInTheDocument();
  });

  it('renders assistant message with markdown', () => {
    render(
      <ChatMessage
        message={{
          id: 'msg2',
          role: 'assistant',
          content: '**Bold text** and `code`',
          timestamp: Date.now(),
        }}
      />,
    );
    const msg = screen.getByTestId('chat-message-assistant');
    expect(msg).toBeInTheDocument();
    // Check that bold is rendered
    const strong = msg.querySelector('strong');
    expect(strong).toBeTruthy();
    expect(strong?.textContent).toBe('Bold text');
    // Check code is rendered
    const code = msg.querySelector('code');
    expect(code).toBeTruthy();
    expect(code?.textContent).toBe('code');
  });

  it('renders system message centered', () => {
    render(
      <ChatMessage
        message={{
          id: 'msg3',
          role: 'system',
          content: 'Connection established',
          timestamp: Date.now(),
        }}
      />,
    );
    expect(screen.getByTestId('chat-message-system')).toBeInTheDocument();
  });
});

// ── TC-UI14: InputBar send button states ──────────────────────
describe('TC-UI14: InputBar send button states', () => {
  it('disables send button when input is empty', () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} />);
    const btn = screen.getByTestId('send-button');
    expect(btn).toBeDisabled();
  });

  it('disables send button for whitespace-only input', async () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} />);
    const textarea = screen.getByTestId('input-textarea');
    await userEvent.type(textarea, '   ');
    expect(screen.getByTestId('send-button')).toBeDisabled();
  });

  it('enables send button when content is entered', async () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} />);
    const textarea = screen.getByTestId('input-textarea');
    await userEvent.type(textarea, '查一下港口数据');
    expect(screen.getByTestId('send-button')).not.toBeDisabled();
  });

  it('disables send button when disabled prop is true', async () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} disabled={true} />);
    const textarea = screen.getByTestId('input-textarea');
    expect(textarea).toBeDisabled();
    expect(screen.getByTestId('send-button')).toBeDisabled();
  });
});

// ── TC-UI15: InputBar Enter key sends message ─────────────────
describe('TC-UI15: InputBar Enter key behavior', () => {
  it('sends on Enter and clears input', async () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} />);
    const textarea = screen.getByTestId('input-textarea');

    await userEvent.type(textarea, '上个月各业务线吞吐量');
    await userEvent.keyboard('{Enter}');

    expect(onSend).toHaveBeenCalledWith('上个月各业务线吞吐量');
    expect(textarea).toHaveValue('');
  });

  it('does not send on Shift+Enter (newline)', async () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} />);
    const textarea = screen.getByTestId('input-textarea');

    await userEvent.type(textarea, 'line1');
    await userEvent.keyboard('{Shift>}{Enter}{/Shift}');

    expect(onSend).not.toHaveBeenCalled();
  });

  it('sends on button click', async () => {
    const onSend = vi.fn();
    render(<InputBar onSend={onSend} webSearchEnabled={false} onToggleWebSearch={vi.fn()} />);
    const textarea = screen.getByTestId('input-textarea');

    await userEvent.type(textarea, '分析数据');
    await userEvent.click(screen.getByTestId('send-button'));

    expect(onSend).toHaveBeenCalledWith('分析数据');
  });
});
