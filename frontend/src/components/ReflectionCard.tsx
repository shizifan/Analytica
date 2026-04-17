import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type { ReflectionSummary } from '../types';

interface Props {
  summary: ReflectionSummary | null;
  sessionId: string;
}

export function ReflectionCard({ summary, sessionId }: Props) {
  const [savedKeys, setSavedKeys] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState(false);
  const [saving, setSaving] = useState(false);

  const handleSaveAll = useCallback(async () => {
    setSaving(true);
    try {
      await api.saveReflection(sessionId, {
        save_preferences: true,
        save_template: true,
        save_skill_notes: true,
      });
      setSavedKeys(new Set(['all']));
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  }, [sessionId]);

  const handleDismiss = useCallback(async () => {
    try {
      await api.saveReflection(sessionId, {
        save_preferences: false,
        save_template: false,
        save_skill_notes: false,
      });
    } catch {
      // ok
    }
    setDismissed(true);
  }, [sessionId]);

  if (dismissed || !summary) return null;

  const prefs = summary.user_preferences ?? {};
  const prefEntries = Object.entries(prefs).filter(
    ([, v]) => v != null && v !== '' && !(Array.isArray(v) && v.length === 0) && !(typeof v === 'object' && !Array.isArray(v) && Object.keys(v as Record<string, unknown>).length === 0),
  );
  const template = summary.analysis_template;
  const feedback = summary.skill_feedback ?? {};
  const slotReview = summary.slot_quality_review ?? { slots_corrected: [], slots_corrected_detail: {} };

  const allSaved = savedKeys.has('all');

  return (
    <div data-testid="reflection-card"
      className="my-2 overflow-hidden rounded-lg border border-blue-200 bg-blue-50 transition-all duration-300"
    >
      <div className="p-4">
        <h4 className="mb-2 text-sm font-semibold text-gray-800">
          &#129504; 分析完成 &middot; 反思摘要
        </h4>

        {/* Preferences */}
        {prefEntries.length > 0 && (
          <div className="mb-3">
            <p className="mb-1 text-xs font-medium text-gray-600">发现的偏好：</p>
            <ul className="space-y-0.5">
              {prefEntries.map(([key, val]) => (
                <li key={key} className="flex items-center justify-between text-xs">
                  <span className="text-gray-700">{key}: {typeof val === 'object' ? JSON.stringify(val) : String(val)}</span>
                  <button
                    data-testid={`reflection-save-${key}`}
                    disabled={allSaved}
                    className="rounded bg-blue-100 px-2 py-0.5 text-blue-700 hover:bg-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {allSaved ? '\u2713 已保存' : '保存'}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Template */}
        {template && (
          <div className="mb-3 text-xs text-gray-600">
            <span className="font-medium">可保存模板：</span>{' '}
            {(template as Record<string, string>).template_name ?? '未命名'}
          </div>
        )}

        {/* Skill feedback */}
        {(feedback as Record<string, unknown[]>).well_performed?.length ? (
          <div className="mb-3 text-xs text-gray-600">
            <span className="font-medium">技能反馈：</span>{' '}
            {((feedback as Record<string, string[]>).well_performed ?? []).join(', ')} 表现良好
          </div>
        ) : null}

        {/* Slot corrections */}
        {slotReview.slots_corrected.length > 0 && (
          <div className="mb-3 text-xs text-gray-600">
            <span className="font-medium">槽位纠正：</span>{' '}
            {slotReview.slots_corrected.map((s) => {
              const d = slotReview.slots_corrected_detail[s];
              return d ? `${s}: ${d.from} \u2192 ${d.to}` : s;
            }).join(', ')}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 border-t border-blue-200 pt-3">
          <button
            onClick={handleSaveAll}
            disabled={allSaved || saving}
            className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {allSaved ? '\u2713 已全部保存' : saving ? '保存中...' : '全部保存'}
          </button>
          <button
            onClick={handleDismiss}
            className="rounded bg-gray-200 px-3 py-1 text-xs text-gray-600 hover:bg-gray-300"
          >
            忽略本次
          </button>
        </div>
      </div>
      {allSaved && (
        <div data-testid="save-success-toast"
          className="bg-green-100 px-4 py-1 text-xs text-green-700">
          偏好已记录，下次分析将自动应用
        </div>
      )}
    </div>
  );
}
