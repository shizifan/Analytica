import { useState, useEffect } from 'react';
import type { EmployeeDetail, EmployeeUpdatePayload } from '../types';

interface Props {
  detail: EmployeeDetail | null;
  loading: boolean;
  onClose: () => void;
  onSave: (id: string, payload: EmployeeUpdatePayload) => Promise<void>;
}

const DOMAIN_LABELS: Record<string, string> = {
  D1: '生产运营',
  D2: '市场商务',
  D3: '战略客户',
  D4: '公司治理',
  D5: '资产管理',
  D6: '投资项目',
  D7: '设备运营',
};

export function EmployeeDetailModal({ detail, loading, onClose, onSave }: Props) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync local state when detail changes
  useEffect(() => {
    if (detail) {
      setName(detail.name);
      setDescription(detail.description);
    }
  }, [detail]);

  const handleSave = async () => {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(detail.employee_id, { name, description });
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  if (!detail && !loading) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* Panel */}
      <div className="relative z-10 max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
        {loading ? (
          <div className="flex items-center justify-center p-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />
          </div>
        ) : detail ? (
          <>
            {/* Header */}
            <div className="sticky top-0 flex items-center justify-between border-b border-gray-100 bg-white px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-800">员工详情</h2>
              <button
                onClick={onClose}
                className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              {/* Editable fields */}
              <div className="mb-6 space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-500">名称</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-500">人设描述</label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={3}
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  />
                </div>
              </div>

              {/* Read-only info */}
              <div className="space-y-4">
                <div className="flex items-center gap-6">
                  <div>
                    <span className="text-xs text-gray-400">版本</span>
                    <p className="mt-0.5 text-sm font-medium text-gray-700">v{detail.version}</p>
                  </div>
                  <div>
                    <span className="text-xs text-gray-400">ID</span>
                    <p className="mt-0.5 text-sm font-mono text-gray-600">{detail.employee_id}</p>
                  </div>
                </div>

                <div>
                  <span className="text-xs text-gray-400">关联域</span>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {detail.domains.map((d) => (
                      <span key={d} className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-600">
                        {d} {DOMAIN_LABELS[d] || ''}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <span className="text-xs text-gray-400">关联技能</span>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {detail.tools.map((s) => (
                      <span key={s} className="rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-600">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Perception config */}
                <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                  <span className="text-xs font-medium text-gray-500">感知配置</span>
                  <div className="mt-2 space-y-1.5">
                    {detail.perception.system_prompt_suffix != null && String(detail.perception.system_prompt_suffix).length > 0 ? (
                      <div>
                        <span className="text-xs text-gray-400">system_prompt_suffix</span>
                        <p className="mt-0.5 text-xs text-gray-600 line-clamp-2">
                          {String(detail.perception.system_prompt_suffix).slice(0, 100)}...
                        </p>
                      </div>
                    ) : null}
                    {detail.perception.extra_slots != null && (
                      <div>
                        <span className="text-xs text-gray-400">extra_slots</span>
                        <p className="mt-0.5 text-xs text-gray-600">
                          {Array.isArray(detail.perception.extra_slots) ? detail.perception.extra_slots.length : 0} 个额外槽位
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Planning config */}
                <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                  <span className="text-xs font-medium text-gray-500">规划配置</span>
                  <div className="mt-2">
                    <span className="text-xs text-gray-400">prompt_suffix</span>
                    <p className="mt-0.5 text-xs text-gray-600 line-clamp-2">
                      {String(detail.planning.prompt_suffix || '').slice(0, 100)}...
                    </p>
                  </div>
                </div>
              </div>

              {/* Error */}
              {error && (
                <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</div>
              )}
            </div>

            {/* Footer */}
            <div className="sticky bottom-0 flex justify-end gap-2 border-t border-gray-100 bg-white px-6 py-4">
              <button
                onClick={onClose}
                className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? '保存中...' : '保存'}
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
