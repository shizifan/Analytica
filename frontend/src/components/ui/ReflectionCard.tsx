import { useState, useCallback } from 'react';
import { Icon } from './Icon';
import { api } from '../../api/client';
import type { ReflectionSummary } from '../../types';

interface Props {
  summary: ReflectionSummary | null;
  sessionId: string;
}

/**
 * Phase 3.5 — reflection summary rendered as an inline card inside the
 * assistant bubble, with new design tokens. Shares the same data-testids
 * as v1 so tests can target either.
 */
export function ReflectionCard({ summary, sessionId }: Props) {
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const handleSaveAll = useCallback(async () => {
    setSaving(true);
    try {
      await api.saveReflection(sessionId, {
        save_preferences: true,
        save_template: true,
        save_tool_notes: true,
      });
      setSaved(true);
    } catch {
      /* noop — silent fail mirrors v1 */
    } finally {
      setSaving(false);
    }
  }, [sessionId]);

  const handleDismiss = useCallback(async () => {
    try {
      await api.saveReflection(sessionId, {
        save_preferences: false,
        save_template: false,
        save_tool_notes: false,
      });
    } catch {
      /* noop */
    }
    setDismissed(true);
  }, [sessionId]);

  if (dismissed || !summary) return null;

  const prefs = summary.user_preferences ?? {};
  const prefEntries = Object.entries(prefs).filter(([, v]) =>
    v != null && v !== '' &&
    !(Array.isArray(v) && v.length === 0) &&
    !(typeof v === 'object' && !Array.isArray(v) && Object.keys(v as Record<string, unknown>).length === 0),
  );
  const template = summary.analysis_template as Record<string, string> | undefined;
  const feedback = summary.tool_feedback as Record<string, string[]> | undefined;
  const slotReview = summary.slot_quality_review ?? {
    slots_corrected: [],
    slots_corrected_detail: {},
  };

  return (
    <div className="an-msg-row assistant">
      <div className="an-role-avatar assistant">A</div>
      <div
        className="an-msg-bubble"
        style={{ flex: 1, minWidth: 0, padding: 0, overflow: 'hidden' }}
        data-testid="reflection-card"
      >
        <div className="an-inline-head">
          <span className="an-inline-title">
            <Icon name="sparkles" size={12} />
            分析完成 · 反思摘要
          </span>
          <span className="an-inline-meta">
            {prefEntries.length} 偏好 · {template ? 1 : 0} 模板
          </span>
        </div>

        <div className="an-inline-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {prefEntries.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--an-ink-4)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
                发现的偏好
              </div>
              {prefEntries.map(([k, v]) => (
                <div
                  key={k}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 12,
                    padding: '4px 0',
                    fontSize: 12,
                    borderBottom: '1px solid var(--an-border-subtle)',
                  }}
                >
                  <span style={{ color: 'var(--an-ink-3)' }}>{k}</span>
                  <span
                    className="an-mono"
                    style={{
                      color: 'var(--an-ink)',
                      maxWidth: 260,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    data-testid={`reflection-save-${k}`}
                  >
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {template && (
            <div style={{ fontSize: 12, color: 'var(--an-ink-3)' }}>
              <strong style={{ color: 'var(--an-ink-2)' }}>可保存模板：</strong>{' '}
              {template.template_name ?? '未命名'}
            </div>
          )}

          {feedback?.well_performed?.length ? (
            <div style={{ fontSize: 12, color: 'var(--an-ink-3)' }}>
              <strong style={{ color: 'var(--an-ink-2)' }}>工具反馈：</strong>{' '}
              {feedback.well_performed.join(', ')} 表现良好
            </div>
          ) : null}

          {slotReview.slots_corrected.length > 0 && (
            <div style={{ fontSize: 12, color: 'var(--an-ink-3)' }}>
              <strong style={{ color: 'var(--an-ink-2)' }}>槽位纠正：</strong>{' '}
              {slotReview.slots_corrected
                .map((s) => {
                  const d = slotReview.slots_corrected_detail[s];
                  return d ? `${s}: ${d.from} → ${d.to}` : s;
                })
                .join(', ')}
            </div>
          )}
        </div>

        <div className="an-inline-actions">
          <button
            type="button"
            className="an-btn primary"
            onClick={handleSaveAll}
            disabled={saved || saving}
          >
            {saved ? (
              <>
                <Icon name="check" size={12} /> 已全部保存
              </>
            ) : saving ? (
              '保存中…'
            ) : (
              '全部保存'
            )}
          </button>
          <button
            type="button"
            className="an-btn"
            onClick={handleDismiss}
            disabled={saved}
          >
            忽略本次
          </button>
        </div>

        {saved && (
          <div
            data-testid="save-success-toast"
            style={{
              padding: '6px 12px',
              background: 'var(--an-ok-bg)',
              color: 'var(--an-ok)',
              fontSize: 11,
              borderTop: '1px solid color-mix(in oklch, var(--an-ok) 30%, transparent)',
            }}
          >
            偏好已记录，下次分析将自动应用
          </div>
        )}
      </div>
    </div>
  );
}
