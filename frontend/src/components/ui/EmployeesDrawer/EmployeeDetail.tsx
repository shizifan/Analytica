import { useState, useEffect } from 'react';
import { Icon } from '../Icon';
import { api } from '../../../api/client';
import type {
  EmployeeDetail as EmployeeDetailType,
  EmployeeFAQ,
  EmployeeUpdatePayload,
  EmployeeVersionSummary,
} from '../../../types';

interface Props {
  employeeId: string;
  editing: boolean;
  onExit(): void;
  onToggleEdit(): void;
  onUse(): void;
  onSaved(updated: EmployeeDetailType): void;
}

interface DraftState {
  name: string;
  description: string;
  version: string;
  initials: string;
  status: string;
  domains: string[];
  endpoints: string[];
  faqs: EmployeeFAQ[];
}

function detailToDraft(d: EmployeeDetailType): DraftState {
  return {
    name: d.name,
    description: d.description,
    version: d.version,
    initials: d.initials ?? '',
    status: d.status ?? 'active',
    domains: [...d.domains],
    endpoints: [...(d.endpoints ?? [])],
    faqs: d.faqs.map((f) => ({ ...f })),
  };
}

export function EmployeeDetail({
  employeeId,
  editing,
  onExit,
  onToggleEdit,
  onUse,
  onSaved,
}: Props) {
  const [detail, setDetail] = useState<EmployeeDetailType | null>(null);
  const [draft, setDraft] = useState<DraftState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<EmployeeVersionSummary[]>([]);

  // Load detail + versions
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      api.getEmployee(employeeId),
      api.listEmployeeVersions(employeeId).catch(() => ({ items: [], count: 0 })),
    ])
      .then(([d, v]) => {
        if (cancelled) return;
        setDetail(d);
        setDraft(detailToDraft(d));
        setVersions(v.items);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [employeeId]);

  // When editing toggles off externally, reset draft from server copy.
  useEffect(() => {
    if (!editing && detail) setDraft(detailToDraft(detail));
  }, [editing, detail]);

  if (loading) {
    return <div style={{ color: 'var(--an-ink-4)', padding: 20 }}>加载中…</div>;
  }
  if (error || !detail || !draft) {
    return <div style={{ color: 'var(--an-err)', padding: 20 }}>加载失败: {error}</div>;
  }

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload: EmployeeUpdatePayload = {
        name: draft.name,
        description: draft.description,
        version: draft.version,
        initials: draft.initials || null,
        status: draft.status,
        domains: draft.domains,
        endpoints: draft.endpoints,
        faqs: draft.faqs,
        snapshot_note: `UI edit`,
      };
      const updated = await api.updateEmployee(employeeId, payload);
      setDetail(updated);
      setDraft(detailToDraft(updated));
      onSaved(updated);
      onToggleEdit(); // exit edit mode
      // Refresh versions
      const v = await api.listEmployeeVersions(employeeId).catch(() => ({ items: [], count: 0 }));
      setVersions(v.items);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const addDomain = () => {
    const v = window.prompt('新增业务领域（D1/D2/...）');
    if (v && /^D\d$/.test(v.trim()) && !draft.domains.includes(v.trim())) {
      setDraft({ ...draft, domains: [...draft.domains, v.trim()] });
    }
  };
  const removeDomain = (d: string) =>
    setDraft({ ...draft, domains: draft.domains.filter((x) => x !== d) });

  const addEndpoint = () => {
    const v = window.prompt('新增 endpoint id（如 getThroughputAnalysisByYear）');
    if (v && !draft.endpoints.includes(v.trim())) {
      setDraft({ ...draft, endpoints: [...draft.endpoints, v.trim()] });
    }
  };
  const removeEndpoint = (e: string) =>
    setDraft({ ...draft, endpoints: draft.endpoints.filter((x) => x !== e) });

  const addFaq = () => {
    const id = `faq-${Date.now().toString(36)}`;
    setDraft({ ...draft, faqs: [...draft.faqs, { id, question: '' }] });
  };
  const updateFaq = (idx: number, patch: Partial<EmployeeFAQ>) => {
    const next = [...draft.faqs];
    next[idx] = { ...next[idx], ...patch };
    setDraft({ ...draft, faqs: next });
  };
  const removeFaq = (idx: number) =>
    setDraft({ ...draft, faqs: draft.faqs.filter((_, i) => i !== idx) });

  return (
    <>
      <div className="an-drawer-body">
        <div className="an-emp-detail">
          <div className="an-emp-detail-head">
            <button
              type="button"
              className="an-btn ghost"
              onClick={onExit}
              title="返回列表"
            >
              <Icon name="chev-left" size={14} />
              返回
            </button>
            <div className="an-emp-avatar">
              {detail.initials || detail.name.slice(0, 2)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              {editing ? (
                <>
                  <input
                    className="an-emp-input"
                    style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      className="an-emp-input"
                      placeholder="版本号"
                      style={{ width: 100 }}
                      value={draft.version}
                      onChange={(e) => setDraft({ ...draft, version: e.target.value })}
                    />
                    <input
                      className="an-emp-input"
                      placeholder="简称"
                      style={{ width: 100 }}
                      value={draft.initials}
                      onChange={(e) => setDraft({ ...draft, initials: e.target.value })}
                    />
                    <select
                      className="an-emp-input"
                      style={{ width: 100 }}
                      value={draft.status}
                      onChange={(e) => setDraft({ ...draft, status: e.target.value })}
                    >
                      <option value="active">active</option>
                      <option value="draft">draft</option>
                      <option value="archived">archived</option>
                    </select>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--an-ink)' }}>
                    {detail.name}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: 'var(--an-ink-4)',
                      fontFamily: 'var(--an-font-mono)',
                      marginTop: 4,
                    }}
                  >
                    {detail.employee_id} · v{detail.version} · {detail.status}
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="an-emp-detail-stats">
            <div className="stat-card">
              <div className="label">SKILLS</div>
              <div className="value">{detail.tools.length}</div>
            </div>
            <div className="stat-card">
              <div className="label">APIS</div>
              <div className="value">{detail.endpoints.length || '—'}</div>
            </div>
            <div className="stat-card">
              <div className="label">FAQS</div>
              <div className="value">{detail.faqs.length}</div>
            </div>
            <div className="stat-card">
              <div className="label">VERSIONS</div>
              <div className="value">{versions.length}</div>
            </div>
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label">描述</div>
            {editing ? (
              <textarea
                className="an-emp-textarea"
                rows={3}
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            ) : (
              <div style={{ fontSize: 13, color: 'var(--an-ink-2)', lineHeight: 1.6 }}>
                {detail.description || '（暂无描述）'}
              </div>
            )}
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>业务领域</span>
              {editing && (
                <button type="button" className="an-btn ghost" onClick={addDomain} style={{ padding: '2px 8px' }}>
                  <Icon name="plus" size={10} /> 添加
                </button>
              )}
            </div>
            <div className="an-emp-chips">
              {draft.domains.length === 0 && (
                <span style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>（未指定）</span>
              )}
              {draft.domains.map((d) => (
                <span key={d} className="an-emp-chip">
                  {d}
                  {editing && <button onClick={() => removeDomain(d)}>×</button>}
                </span>
              ))}
            </div>
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>API 端点（空 = 按领域自动推导）</span>
              {editing && (
                <button type="button" className="an-btn ghost" onClick={addEndpoint} style={{ padding: '2px 8px' }}>
                  <Icon name="plus" size={10} /> 添加
                </button>
              )}
            </div>
            {draft.endpoints.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--an-ink-4)', fontFamily: 'var(--an-font-mono)' }}>
                自动推导（{detail.domains.join(' + ')}）
              </div>
            ) : (
              <div className="an-emp-chips">
                {draft.endpoints.map((e) => (
                  <span key={e} className="an-emp-chip an-mono" style={{ fontSize: 10 }}>
                    {e}
                    {editing && <button onClick={() => removeEndpoint(e)}>×</button>}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>常见问题（FAQ）</span>
              {editing && (
                <button type="button" className="an-btn ghost" onClick={addFaq} style={{ padding: '2px 8px' }}>
                  <Icon name="plus" size={10} /> 添加
                </button>
              )}
            </div>
            <div className="an-emp-faq-list">
              {draft.faqs.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>暂无 FAQ</div>
              )}
              {draft.faqs.map((f, i) => (
                <div key={f.id} className={`an-emp-faq-row${editing ? ' editing' : ''}`}>
                  {editing ? (
                    <input
                      className="an-emp-input"
                      value={f.question}
                      placeholder={`FAQ ${i + 1}`}
                      onChange={(e) => updateFaq(i, { question: e.target.value })}
                    />
                  ) : (
                    <div className="an-emp-faq-q">{f.question}</div>
                  )}
                  {editing && (
                    <button
                      type="button"
                      className="an-btn ghost"
                      style={{ padding: '2px 6px' }}
                      onClick={() => removeFaq(i)}
                    >
                      <Icon name="x" size={10} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {versions.length > 0 && (
            <div className="an-emp-section">
              <div className="an-emp-section-label">版本历史</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {versions.map((v) => (
                  <div
                    key={v.version}
                    style={{
                      fontSize: 11,
                      fontFamily: 'var(--an-font-mono)',
                      color: 'var(--an-ink-3)',
                      display: 'flex',
                      gap: 12,
                    }}
                  >
                    <span style={{ minWidth: 40 }}>v{v.version}</span>
                    <span style={{ minWidth: 120 }}>{new Date(v.created_at).toLocaleString('zh-CN')}</span>
                    <span style={{ flex: 1, color: 'var(--an-ink-4)' }}>{v.note ?? '—'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && <div style={{ color: 'var(--an-err)', fontSize: 12 }}>{error}</div>}
        </div>
      </div>

      <div className="an-drawer-footer">
        {editing ? (
          <>
            <button type="button" className="an-btn" onClick={onToggleEdit} disabled={saving}>
              取消
            </button>
            <button
              type="button"
              className="an-btn primary"
              onClick={handleSave}
              disabled={saving || !draft.name.trim()}
            >
              {saving ? '保存中…' : '保存（新建版本快照）'}
            </button>
          </>
        ) : (
          <>
            <button type="button" className="an-btn" onClick={onToggleEdit}>
              <Icon name="sliders" size={12} /> 编辑
            </button>
            <button type="button" className="an-btn primary" onClick={onUse}>
              使用该员工
            </button>
          </>
        )}
      </div>
    </>
  );
}
