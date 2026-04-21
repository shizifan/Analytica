import { useEffect, useRef, useCallback, useState } from 'react';
import { useSessionStore } from '../stores/sessionStore';
import { useWsStore } from '../stores/wsStore';
import { usePlanStore } from '../stores/planStore';
import { useSlotStore } from '../stores/slotStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useEmployeeStore } from '../stores/employeeStore';
import { api } from '../api/client';
import { getEmployeeFAQs } from '../data/employeeFaq';

import { ChatMessage } from '../components/ChatMessage';
import { ExecutionProgress } from '../components/ExecutionProgress';
import { ReflectionCard } from '../components/ReflectionCard';
import { InputBar } from '../components/InputBar';
import { EmployeeSelector } from '../components/EmployeeSelector';
import { SlotStatusCard } from '../components/SlotStatusCard';
import { PlanCard } from '../components/PlanCard';

import { Topbar } from '../components/ui/Topbar';
import { HistoryPane } from '../components/ui/HistoryPane';
import { AgentPane } from '../components/ui/AgentPane';
import { EmptyHero } from '../components/ui/EmptyHero';
import { TweaksPanel } from '../components/ui/TweaksPanel';
import { useTweakStore, applyTweaksToDocument } from '../lib/tweaks';

import type { ReflectionSummary } from '../types';
import type { ConversationItem } from '../components/ui/HistoryPane';

const PHASE_SHORT: Record<string, string> = {
  idle: '待机',
  perception: '感知中',
  planning: '规划中',
  executing: '执行中',
  reflection: '反思中',
  done: '已完成',
};

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
  const sending = useSessionStore((s) => s.sending);
  const phase = useSessionStore((s) => s.phase);
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
  const [reflectionSummary, setReflectionSummary] = useState<ReflectionSummary | null>(null);

  // Local history rail — Phase 2 replaces with GET /api/sessions.
  const [history] = useState<ConversationItem[]>([]);

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

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    if (sessionId) return;
    api
      .createSession(userId, selectedId ?? undefined)
      .then(({ session_id }) => setSession(session_id, userId, selectedId))
      .catch(() => {});
  }, [sessionId, selectedId, userId, setSession]);

  useEffect(() => {
    if (!initRef.current) return;
    if (sessionId) {
      clearConversation();
      resetPlan();
      resetSlots();
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
    },
    [sendMessage, userId, agentCollapsed],
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
    setReflectionSummary(null);
    setAgentCollapsed(true);
    api
      .createSession(userId, selectedId ?? undefined)
      .then(({ session_id }) => setSession(session_id, userId, selectedId))
      .catch(() => {});
  }, [userId, selectedId, clearConversation, resetPlan, resetSlots, setSession]);

  const selectedEmployee = employees.find((e) => e.employee_id === selectedId) ?? null;
  const faqs = getEmployeeFAQs(selectedId);
  const inputDisabled = !sessionId || wsStatus !== 'connected';

  return (
    <div className="an-app">
      <Topbar onTweaks={() => setTweaksOpen((v) => !v)} />

      <div className="an-workbench">
        <HistoryPane
          items={history}
          activeId={sessionId}
          onSelect={() => {
            /* Phase 2 wires session switching */
          }}
          onNew={handleNewConversation}
        />

        <main className="an-pane an-chat-pane">
          <div className="an-chat-toolbar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
              <EmployeeSelector
                employees={employees}
                selectedId={selectedId}
                onChange={(id) => setSelectedId(id)}
              />
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
                  faqs={faqs}
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
                    return <ExecutionProgress key={msg.id} />;
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

              {planStatus === 'executing' && <ExecutionProgress />}

              {sending && (
                <div style={{ color: 'var(--an-ink-4)', fontSize: 12, padding: '6px 4px' }}>
                  正在思考<span className="an-mono">…</span>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          <InputBar onSend={handleSend} disabled={inputDisabled} />
        </main>

        <AgentPane
          collapsed={agentCollapsed}
          onToggle={() => setAgentCollapsed((v) => !v)}
          phaseLabel={PHASE_SHORT[phase] ?? phase}
        >
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <SlotStatusCard />
            <PlanCard />
          </div>
        </AgentPane>
      </div>

      <TweaksPanel open={tweaksOpen} onClose={() => setTweaksOpen(false)} />
    </div>
  );
}
