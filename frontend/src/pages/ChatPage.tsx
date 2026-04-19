import { useEffect, useRef, useCallback, useState } from 'react';
import { useSessionStore } from '../stores/sessionStore';
import { useWsStore } from '../stores/wsStore';
import { usePlanStore } from '../stores/planStore';
import { useSlotStore } from '../stores/slotStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useEmployeeStore } from '../stores/employeeStore';
import { api } from '../api/client';
import { getEmployeeFAQs } from '../data/employeeFaq';

import { SlotStatusCard } from '../components/SlotStatusCard';
import { PlanCard } from '../components/PlanCard';
import { ChatMessage } from '../components/ChatMessage';
import { ExecutionProgress } from '../components/ExecutionProgress';
import { ReflectionCard } from '../components/ReflectionCard';
import { InputBar } from '../components/InputBar';
import { EmployeeSelector } from '../components/EmployeeSelector';

import type { ReflectionSummary } from '../types';

export function ChatPage() {
  const sessionId = useSessionStore((s) => s.sessionId);
  const userId = useSessionStore((s) => s.userId);
  const setSession = useSessionStore((s) => s.setSession);
  const messages = useSessionStore((s) => s.messages);
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

  const [reflectionSummary, setReflectionSummary] = useState<ReflectionSummary | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const initRef = useRef(false);

  // Bind reflection callback
  useEffect(() => {
    onReflectionRef.current = (s: ReflectionSummary) => setReflectionSummary(s);
  }, [onReflectionRef]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, planStatus, reflectionSummary]);

  // Fetch employees on mount
  useEffect(() => {
    if (employees.length === 0) {
      fetchEmployees();
    }
  }, [employees.length, fetchEmployees]);

  // Create session when selectedId changes or when no session exists
  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;

    if (sessionId) return;
    api.createSession(userId, selectedId ?? undefined).then(({ session_id }) => {
      setSession(session_id, userId, selectedId);
    }).catch(() => {});
  }, [sessionId, selectedId, userId, setSession]);

  // Rebuild session when selected employee changes
  useEffect(() => {
    if (!initRef.current) return; // Skip first mount
    if (sessionId) {
      clearConversation();
      resetPlan();
      resetSlots();
      api.createSession(userId, selectedId ?? undefined).then(({ session_id }) => {
        setSession(session_id, userId, selectedId);
      }).catch(() => {});
    }
  }, [selectedId]);

  const handleSend = useCallback(
    (content: string) => {
      sendMessage(content, userId);
    },
    [sendMessage, userId],
  );

  const handlePlanAction = useCallback(
    (action: 'confirm' | 'modify' | 'regenerate') => {
      if (!sessionId || wsStatus !== 'connected') return;
      const actionMessages: Record<string, string> = {
        confirm: '确认执行',
        modify: '修改方案',
        regenerate: '重新规划',
      };
      handleSend(actionMessages[action]);
    },
    [sessionId, wsStatus, handleSend],
  );

  const handleNewConversation = useCallback(() => {
    clearConversation();
    resetPlan();
    resetSlots();
    api.createSession(userId, selectedId ?? undefined).then(({ session_id }) => {
      setSession(session_id, userId, selectedId);
    }).catch(() => {});
  }, [userId, selectedId, clearConversation, resetPlan, resetSlots, setSession]);

  const selectedEmployee = employees.find((e) => e.employee_id === selectedId);
  const faqs = getEmployeeFAQs(selectedId);

  return (
    <>
      {/* Main body: Left panel + Chat area */}
      <div className="flex min-h-0 flex-1">
        {/* Left panel (300px) */}
        <aside className="flex w-[300px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-gray-200 bg-white p-3">
          <SlotStatusCard />
          <PlanCard />
        </aside>

        {/* Main content area */}
        <main className="flex min-w-0 flex-1 flex-col">
          {/* Employee selector toolbar */}
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-500">
                <EmployeeSelector
                  employees={employees}
                  selectedId={selectedId}
                  onChange={(id) => setSelectedId(id)}
                />
              </span>
              {selectedEmployee && (
                <span className="text-xs text-gray-400">
                  — {selectedEmployee.description.slice(0, 30)}
                  {selectedEmployee.description.length > 30 ? '...' : ''}
                </span>
              )}
            </div>
            <button
              onClick={handleNewConversation}
              className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 transition-colors hover:bg-gray-50"
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              新对话
            </button>
          </div>

          {/* Chat messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <div className="flex flex-col items-center gap-6">
                  <div className="text-center">
                    <h2 className="bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-2xl font-bold text-transparent">
                      {selectedEmployee ? selectedEmployee.name : '多维能动决策智能体'}
                    </h2>
                    <p className="mt-2 text-sm text-gray-400">
                      {selectedEmployee ? selectedEmployee.description : '我是你的专属数据分析师'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center gap-3 w-full max-w-lg">
                    <div className="flex items-center gap-1.5 text-xs text-gray-400">
                      <svg className="h-4 w-4 text-amber-400" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2L9.19 8.63L2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2z" />
                      </svg>
                      <span>常见问题</span>
                    </div>
                    <div className="grid grid-cols-1 gap-2 w-full">
                      {faqs.map((faq) => (
                        <button
                          key={faq.id}
                          type="button"
                          onClick={() => handleSend(faq.question)}
                          disabled={!sessionId || wsStatus !== 'connected'}
                          className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-left text-sm text-gray-600 shadow-sm transition hover:border-blue-300 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {faq.question}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {messages.map((msg) => {
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
              return <ChatMessage key={msg.id} message={msg} onPlanAction={handlePlanAction} />;
            })}

            {/* Inline execution progress when executing */}
            {planStatus === 'executing' && <ExecutionProgress />}

            {/* Typing indicator when sending */}
            {sending && (
              <div className="my-2 flex justify-start">
                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-500">
                  <span className="inline-flex gap-1">
                    <span className="animate-bounce">.</span>
                    <span className="animate-bounce [animation-delay:0.1s]">.</span>
                    <span className="animate-bounce [animation-delay:0.2s]">.</span>
                  </span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <InputBar
            onSend={handleSend}
            disabled={!sessionId || wsStatus !== 'connected'}
          />
        </main>
      </div>
    </>
  );
}
