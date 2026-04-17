import { useEffect, useRef, useCallback } from 'react';
import { useWsStore } from '../stores/wsStore';
import { useSlotStore } from '../stores/slotStore';
import { usePlanStore } from '../stores/planStore';
import { useSessionStore, makeMessageId } from '../stores/sessionStore';
import type { ReflectionSummary } from '../types';

const MAX_RETRIES = 10;
const MAX_BACKOFF_MS = 30_000;

function backoffMs(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
}

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  const setConnected = useWsStore((s) => s.setConnected);
  const setWsStatus = useWsStore((s) => s.setStatus);
  const incrementReconnect = useWsStore((s) => s.incrementReconnect);

  const setSlots = useSlotStore((s) => s.setSlots);
  const setCurrentAsking = useSlotStore((s) => s.setCurrentAsking);

  const setPlan = usePlanStore((s) => s.setPlan);
  const setPlanStatus = usePlanStore((s) => s.setStatus);
  const updateTaskStatus = usePlanStore((s) => s.updateTaskStatus);

  const addMessage = useSessionStore((s) => s.addMessage);
  const setPhase = useSessionStore((s) => s.setPhase);
  const setSending = useSessionStore((s) => s.setSending);

  // Mutable ref for reflection callback
  const onReflectionRef = useRef<((s: ReflectionSummary) => void) | null>(null);

  const connect = useCallback(() => {
    if (!sessionId || unmountedRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/chat/${sessionId}`;

    setWsStatus('connecting');
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      setConnected(true);
    };

    ws.onmessage = (evt) => {
      let data: Record<string, unknown>;
      try { data = JSON.parse(evt.data); } catch { return; }

      const eventType = (data.event ?? data.type) as string;

      switch (eventType) {
        case 'connected':
          break;

        case 'slot_update':
          setSlots(data.slots as Record<string, never>);
          setCurrentAsking((data.current_asking as string) ?? null);
          setPhase('perception');
          break;

        case 'message':
          addMessage({
            id: makeMessageId(),
            role: 'assistant',
            content: data.content as string,
            phase: data.phase as string,
            timestamp: Date.now(),
          });
          if (data.phase) setPhase(data.phase as never);
          break;

        case 'intent_ready':
          setPhase('planning');
          break;

        case 'plan_update':
          setPlan(data.plan as never);
          setPlanStatus('ready');
          setPhase('planning');
          break;

        case 'task_update':
          updateTaskStatus(data.task_id as string, data.status as never);
          setPlanStatus('executing');
          setPhase('executing');
          break;

        case 'reflection':
          setPhase('reflection');
          onReflectionRef.current?.(data.summary as ReflectionSummary);
          addMessage({
            id: makeMessageId(),
            role: 'assistant',
            content: '',
            type: 'reflection_card',
            phase: 'reflection',
            timestamp: Date.now(),
          });
          break;

        case 'turn_complete':
          setSending(false);
          break;

        case 'error':
          addMessage({
            id: makeMessageId(),
            role: 'system',
            content: `Error: ${data.message ?? 'unknown'}`,
            timestamp: Date.now(),
          });
          setSending(false);
          break;

        case 'pong':
          break;
      }
    };

    ws.onclose = () => {
      if (unmountedRef.current) return;
      setConnected(false);

      if (retryRef.current < MAX_RETRIES) {
        const delay = backoffMs(retryRef.current);
        retryRef.current += 1;
        incrementReconnect();
        timerRef.current = setTimeout(connect, delay);
      } else {
        setWsStatus('failed');
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [sessionId, setConnected, setWsStatus, incrementReconnect, setSlots, setCurrentAsking, setPlan, setPlanStatus, updateTaskStatus, addMessage, setPhase, setSending]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback(
    (content: string, userId = 'anonymous') => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      setSending(true);
      addMessage({
        id: makeMessageId(),
        role: 'user',
        content,
        timestamp: Date.now(),
      });
      ws.send(JSON.stringify({ type: 'message', message: content, user_id: userId }));
    },
    [addMessage, setSending],
  );

  const reconnect = useCallback(() => {
    retryRef.current = 0;
    wsRef.current?.close();
    connect();
  }, [connect]);

  return { sendMessage, reconnect, onReflectionRef };
}
