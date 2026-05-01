import { useEffect, useRef, useCallback, useState } from 'react';
import { useSessionStore } from '../stores/sessionStore';
import { useWsStore } from '../stores/wsStore';
import { usePlanStore } from '../stores/planStore';
import { useSlotStore } from '../stores/slotStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useEmployeeStore } from '../stores/employeeStore';
import { api } from '../api/client';
import { universalFAQPages } from '../data/employeeFaq';

import { InputBar } from '../components/InputBar';

import { ChatMessage } from '../components/ui/ChatMessage';
import { Icon } from '../components/ui/Icon';
import { ReflectionCard } from '../components/ui/ReflectionCard';
import { TaskResultsBlock } from '../components/ui/TaskResultsBlock';
import { ThinkingIndicator } from '../components/ui/ThinkingIndicator';
import { Topbar } from '../components/ui/Topbar';
import { HistoryPane } from '../components/ui/HistoryPane';
import { AgentPane } from '../components/ui/AgentPane';
import { EmptyHero } from '../components/ui/EmptyHero';
import { TweaksPanel } from '../components/ui/TweaksPanel';
import { EmployeesDrawer } from '../components/ui/EmployeesDrawer';
import { useTweakStore, applyTweaksToDocument } from '../lib/tweaks';
import { hydrateSession } from '../lib/hydrate';
import { useThinkingStore } from '../stores/thinkingStore';
import { useTraceStore } from '../stores/traceStore';
import { PHASE_LABELS } from '../lib/labels';
import { DEFAULT_EMPLOYEE_ID } from '../config/app';

import type { ReflectionSummary } from '../types';
import type { ConversationItem } from '../components/ui/HistoryPane';

/**
 * V2 workbench layout — three-pane (History / Chat / Agent Inspector).
 *
 * Behavior is intentionally the same as ChatPage v1: all stores, the
 * useWebSocket hook, and the message rendering components are reused. Only
 * layout and visual shell change. Phase 2/3 will refactor Slot/Plan/Reflection
 * into tabbed panels and persisted history.
 */
export function ChatPageV2() {
  const sessionId = useSessionStore((s) => s.sessionId);
  const userId = useSessionStore((s) => s.userId);
  const setSession = useSessionStore((s) => s.setSession);
  const messages = useSessionStore((s) => s.messages);
  const phase = useSessionStore((s) => s.phase);
  const sending = useSessionStore((s) => s.sending);
  const clearConversation = useSessionStore((s) => s.clearConversation);

  const wsStatus = useWsStore((s) => s.status);

  const planStatus = usePlanStore((s) => s.status);
  const resetPlan = usePlanStore((s) => s.reset);
  const resetSlots = useSlotStore((s) => s.resetSlots);

  const { sendMessage, onReflectionRef } = useWebSocket(sessionId);

  const employees = useEmployeeStore((s) => s.employees);
  const selectedId = useEmployeeStore((s) => s.selectedId);
  const fetchEmployees = useEmployeeStore((s) => s.fetchEmployees);
  const setSelectedId = useEmployeeStore((s) => s.setSelectedId);

  const tweaks = useTweakStore();
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [agentCollapsed, setAgentCollapsed] = useState(true);
  const [employeesDrawerOpen, setEmployeesDrawerOpen] = useState(false);
  const [reflectionSummary, setReflectionSummary] = useState<ReflectionSummary | null>(null);

  const [history, setHistory] = useState<ConversationItem[]>([]);
  const resetThinking = useThinkingStore((s) => s.reset);
  const resetTrace = useTraceStore((s) => s.reset);

  const refreshHistory = useCallback(async () => {
    try {
      const { items } = await api.listSessions(userId, 50);
      setHistory(
        items.map((s) => ({
          id: s.session_id,
          title: s.title ?? '(未命名会话)',
          employeeTag: s.employee_id ?? undefined,
          updatedAt: s.updated_at ?? new Date().toISOString(),
        })),
      );
    } catch {
      /* best-effort */
    }
  }, [userId]);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const initRef = useRef(false);

  // Apply tweaks + mark <html> for v2 styling scope
  useEffect(() => {
    document.documentElement.classList.add('analytica-v2');
    applyTweaksToDocument(tweaks);
    return () => {
      document.documentElement.classList.remove('analytica-v2');
      document.documentElement.removeAttribute('data-theme');
      document.documentElement.removeAttribute('data-density');
      document.documentElement.removeAttribute('data-accent');
      document.documentElement.removeAttribute('data-layout');
    };
  }, [tweaks]);

  // Auto-expand agent pane when a phase starts, collapse when reset
  useEffect(() => {
    if (phase !== 'idle' && agentCollapsed) setAgentCollapsed(false);
  }, [phase, agentCollapsed]);

  useEffect(() => {
    onReflectionRef.current = (s: ReflectionSummary) => setReflectionSummary(s);
  }, [onReflectionRef]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, planStatus, reflectionSummary]);

  useEffect(() => {
    if (employees.length === 0) fetchEmployees();
  }, [employees.length, fetchEmployees]);

  const defaultSelectedAppliedRef = useRef(false);
  useEffect(() => {
    if (defaultSelectedAppliedRef.current) return;
    if (employees.length === 0) return;
    defaultSelectedAppliedRef.current = true;
    if (selectedId !== null) return;
    if (sessionId) return;
    const fallback = employees.find((e) => e.employee_id === DEFAULT_EMPLOYEE_ID);
    if (fallback) setSelectedId(fallback.employee_id);
  }, [employees, selectedId, sessionId, setSelectedId]);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    if (sessionId) return;
    api
      .createSession(userId, selectedId ?? undefined)
      .then(({ session_id }) => setSession(session_id, userId, selectedId))
      .catch(() => {});
  }, [sessionId, selectedId, userId, setSession]);

  // Phase 2: replay history + hydrate messages on session change
  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    if (!sessionId) return;
    hydrateSession(sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!initRef.current) return;
    if (sessionId) {
      clearConversation();
      resetPlan();
      resetSlots();
      resetThinking();
      resetTrace();
      setReflectionSummary(null);
      api
        .createSession(userId, selectedId ?? undefined)
        .then(({ session_id }) => setSession(session_id, userId, selectedId))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const handleSend = useCallback(
    (content: string) => {
      sendMessage(content, userId);
      if (agentCollapsed) setAgentCollapsed(false);
      // Refresh the history rail once the backend has a title; fire-and-
      // forget with a short delay so the INSERT lands first.
      setTimeout(refreshHistory, 1200);
    },
    [sendMessage, userId, agentCollapsed, refreshHistory],
  );

  const handlePlanAction = useCallback(
    (action: 'confirm' | 'modify' | 'regenerate') => {
      if (!sessionId || wsStatus !== 'connected') return;
      const map: Record<string, string> = {
        confirm: '确认执行',
        modify: '修改方案',
        regenerate: '重新规划',
      };
      handleSend(map[action]);
    },
    [sessionId, wsStatus, handleSend],
  );

  const handleNewConversation = useCallback(() => {
    clearConversation();
    resetPlan();
    resetSlots();
    resetThinking();
    resetTrace();
    setReflectionSummary(null);
    setAgentCollapsed(true);
    api
      .createSession(userId, selectedId ?? undefined)
      .then(({ session_id }) => setSession(session_id, userId, selectedId))
      .catch(() => {});
    setTimeout(refreshHistory, 500);
  }, [
    userId,
    selectedId,
    clearConversation,
    resetPlan,
    resetSlots,
    resetThinking,
    resetTrace,
    setSession,
    refreshHistory,
  ]);

  const handleDeleteHistory = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
      } catch {
        // If backend fails, still refresh to reflect current server state.
      }
      // Drop it from the rail optimistically.
      setHistory((h) => h.filter((it) => it.id !== id));
      // If the user just deleted the active conversation, spin up a fresh one.
      if (id === sessionId) {
        clearConversation();
        resetPlan();
        resetSlots();
        resetThinking();
        resetTrace();
        setReflectionSummary(null);
        setAgentCollapsed(true);
        api
          .createSession(userId, selectedId ?? undefined)
          .then(({ session_id }) => setSession(session_id, userId, selectedId))
          .catch(() => {});
      }
      // Sync with server truth in the background.
      setTimeout(refreshHistory, 300);
    },
    [
      sessionId,
      userId,
      selectedId,
      clearConversation,
      resetPlan,
      resetSlots,
      resetThinking,
      resetTrace,
      setSession,
      refreshHistory,
    ],
  );

  const handleSelectHistory = useCallback(
    (id: string) => {
      if (id === sessionId) return;
      clearConversation();
      resetPlan();
      resetSlots();
      resetThinking();
      resetTrace();
      setReflectionSummary(null);
      // Jump into the existing session; WS hook will re-connect, hydrate
      // effect will replay messages.
      setSession(id, userId, selectedId);
    },
    [
      sessionId,
      clearConversation,
      resetPlan,
      resetSlots,
      resetThinking,
      resetTrace,
      setSession,
      userId,
      selectedId,
    ],
  );

  const selectedEmployee = employees.find((e) => e.employee_id === selectedId) ?? null;

  // Phase 4: prefer the profile's DB FAQs, fall back to legacy hardcoded
  // file when an employee hasn't been seeded yet (or in "通用模式").
  const detail = useEmployeeStore((s) => s.detail);
  const fetchDetail = useEmployeeStore((s) => s.fetchDetail);
  const clearDetail = useEmployeeStore((s) => s.clearDetail);
  useEffect(() => {
    if (selectedId) fetchDetail(selectedId);
    else clearDetail();
  }, [selectedId, fetchDetail, clearDetail]);

  const faqPages = (() => {
    if (selectedId && detail?.employee_id === selectedId && detail.faqs?.length) {
      const flat = detail.faqs.map((f) => ({ id: f.id, question: f.question }));
      const PAGE_SIZE = 5;
      const pages: { id: string; question: string }[][] = [];
      for (let i = 0; i < flat.length; i += PAGE_SIZE) {
        pages.push(flat.slice(i, i + PAGE_SIZE));
      }
      return pages.length > 0 ? pages : [flat];
    }
    return universalFAQPages;
  })();

  const inputDisabled = !sessionId || wsStatus !== 'connected';
  const isRunning = sending || phase === 'executing';

  const handleCancel = useCallback(async () => {
    if (!sessionId) return;
    try {
      await api.cancelExecution(sessionId);
    } catch {
      // ignore — backend may already have finished
    }
  }, [sessionId]);

  return (
    <div className="an-app">
      <Topbar onTweaks={() => setTweaksOpen((v) => !v)} />

      <div className="an-workbench">
        <HistoryPane
          items={history}
          activeId={sessionId}
          onSelect={handleSelectHistory}
          onNew={handleNewConversation}
          onDelete={handleDeleteHistory}
        />

        <main className="an-pane an-chat-pane">
          <div className="an-chat-toolbar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
              <button
                type="button"
                className="an-employee-chip"
                onClick={() => setEmployeesDrawerOpen(true)}
                title="切换 / 管理数字员工"
              >
                <span className="name">
                  {selectedEmployee ? selectedEmployee.name : '通用模式'}
                </span>

                <Icon name="chev-right" size={12} />
              </button>
              {selectedEmployee && (
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--an-ink-4)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {selectedEmployee.description.slice(0, 60)}
                  {selectedEmployee.description.length > 60 ? '...' : ''}
                </span>
              )}
            </div>
          </div>

          <div className="an-chat-messages">
            <div className="an-chat-inner">
              {messages.length === 0 ? (
                <EmptyHero
                  employee={selectedEmployee}
                  pages={faqPages}
                  onPick={handleSend}
                  disabled={inputDisabled}
                />
              ) : (
                messages.map((msg) => {
                  if (msg.type === 'reflection_card') {
                    return (
                      <ReflectionCard
                        key={msg.id}
                        summary={reflectionSummary}
                        sessionId={sessionId ?? ''}
                      />
                    );
                  }
                  if (msg.type === 'execution_progress') {
                    // Phase 3.5.3 — execution progress is owned by the
                    // Agent Inspector · 计划 Tab (plus a compact preview
                    // in ThinkingIndicator). Rendering another full list
                    // here just duplicated the information. Swallow the
                    // legacy marker message silently.
                    return null;
                  }
                  if (msg.type === 'task_results' && msg.payload) {
                    // Phase 3.7 — structured result cards (chart / table
                    // / text). Phase 5.8 — for report pipelines, the
                    // payload carries `pipeline: "report"` + only file
                    // entries; we also render the short summary text
                    // (msg.content) above the file card.
                    const payload = msg.payload as unknown as import('../types').TaskResultsPayload;
                    const summaryText =
                      payload.pipeline === 'report' && msg.content ? msg.content : '';
                    return (
                      <div
                        key={msg.id}
                        data-testid="task-results"
                        className="an-msg-row assistant"
                      >
                        <div className="an-role-avatar assistant">A</div>
                        <div
                          className="an-msg-bubble"
                          style={{ flex: 1, minWidth: 0, padding: 0, background: 'transparent', border: 0 }}
                        >
                          {summaryText && (
                            <div
                              className="an-msg-bubble"
                              style={{ marginBottom: 8 }}
                            >
                              {summaryText}
                            </div>
                          )}
                          <TaskResultsBlock payload={payload} />
                        </div>
                      </div>
                    );
                  }
                  return (
                    <ChatMessage
                      key={msg.id}
                      message={msg}
                      onPlanAction={handlePlanAction}
                    />
                  );
                })
              )}

              <ThinkingIndicator />

              <div ref={messagesEndRef} />
            </div>
          </div>

          <InputBar
            onSend={handleSend}
            onCancel={handleCancel}
            disabled={inputDisabled && !isRunning}
            isRunning={isRunning}
          />
        </main>

        <AgentPane
          collapsed={agentCollapsed}
          onToggle={() => setAgentCollapsed((v) => !v)}
          phaseLabel={PHASE_LABELS[phase] ?? phase}
        />
      </div>

      <TweaksPanel open={tweaksOpen} onClose={() => setTweaksOpen(false)} />

      <EmployeesDrawer
        open={employeesDrawerOpen}
        selectedId={selectedId}
        onSelect={(id) => setSelectedId(id)}
        onClose={() => setEmployeesDrawerOpen(false)}
      />
    </div>
  );
}
