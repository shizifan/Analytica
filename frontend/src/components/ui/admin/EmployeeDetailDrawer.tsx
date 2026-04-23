import { useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import type { EmployeeDetail } from '../../../types';

const DOMAIN_LABELS: Record<string, string> = {
  D1: '生产运营', D2: '市场商务', D3: '战略客户',
  D4: '公司治理', D5: '资产管理', D6: '投资项目', D7: '设备运营',
};

type Tab = 'overview' | 'perception' | 'planning';

interface Props {
  employeeId: string;
  onClose: () => void;
}

export function EmployeeDetailDrawer({ employeeId, onClose }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<Tab>('overview');
  const [detail, setDetail] = useState<EmployeeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 编辑状态
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    setLoading(true);
    api.getEmployee(employeeId)
      .then((d) => {
        setDetail(d);
        setName(d.name);
        setDescription(d.description);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [employeeId]);

  const handleSave = async () => {
    if (!detail) return;
    setSaving(true);
    setSaveErr(null);
    try {
      const updated = await api.updateEmployee(detail.employee_id, { name, description });
      setDetail({ ...detail, name: updated.name, description: updated.description });
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'overview', label: '概览' },
    { key: 'perception', label: '感知配置' },
    { key: 'planning', label: '规划配置' },
  ];

  return (
    <>
      <div
        className="an-drawer-overlay"
        ref={overlayRef}
        onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      />
      <div className="an-drawer" style={{ width: 'min(720px, 100vw)' }}>
        {/* 标题栏 */}
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            {loading ? (
              <span style={{ color: 'var(--an-ink-4)' }}>加载中…</span>
            ) : detail ? (
              <>
                <span
                  style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 28, height: 28, borderRadius: '50%',
                    background: 'var(--an-accent-bg)',
                    color: 'var(--an-accent-ink)',
                    fontWeight: 700, fontSize: 12,
                    flexShrink: 0,
                  }}
                >
                  {(detail.initials || detail.name).slice(0, 2)}
                </span>
                <span style={{ fontWeight: 600 }}>{detail.name}</span>
                <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 11, color: 'var(--an-ink-4)' }}>
                  v{detail.version}
                </span>
              </>
            ) : null}
          </div>
          <div className="an-drawer-actions">
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ padding: '3px 8px', fontSize: 12 }}>关闭</button>
          </div>
        </div>

        {/* 标签页 */}
        <div className="an-memory-tabs" style={{ padding: '0 20px' }}>
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`an-memory-tab${tab === key ? ' active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {/* 错误 */}
        {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
        {loading && <div className="an-admin-empty">加载中…</div>}

        {!loading && detail && (
          <>
            {/* ── 概览 ── */}
            {tab === 'overview' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                {/* 可编辑字段 */}
                <section>
                  <SectionLabel>基本信息</SectionLabel>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <FieldRow label="名称">
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        style={inputStyle}
                      />
                    </FieldRow>
                    <FieldRow label="ID">
                      <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 12, color: 'var(--an-ink-3)' }}>
                        {detail.employee_id}
                      </span>
                    </FieldRow>
                    <FieldRow label="描述">
                      <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={3}
                        style={{ ...inputStyle, height: 'auto', resize: 'vertical' }}
                      />
                    </FieldRow>
                  </div>
                  {saveErr && (
                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--an-err)' }}>{saveErr}</div>
                  )}
                </section>

                {/* 关联域 */}
                {detail.domains.length > 0 && (
                  <section>
                    <SectionLabel>关联业务域</SectionLabel>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {detail.domains.map((d) => (
                        <span key={d} className="an-admin-chip accent">
                          {d} {DOMAIN_LABELS[d] ?? ''}
                        </span>
                      ))}
                    </div>
                  </section>
                )}

                {/* 数量统计 */}
                <section>
                  <SectionLabel>资源绑定</SectionLabel>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                    <StatCard label="API 端点" value={String(detail.endpoints?.length ?? 0)} />
                    <StatCard label="工具" value={String(detail.skills?.length ?? 0)} />
                    <StatCard label="FAQ" value={String(detail.faqs?.length ?? 0)} />
                  </div>
                </section>

                {/* 绑定工具列表 */}
                {(detail.skills?.length ?? 0) > 0 && (
                  <section>
                    <SectionLabel>绑定工具</SectionLabel>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {detail.skills.map((s) => (
                        <span key={s} className="an-admin-chip"
                          style={{ fontFamily: 'var(--an-font-mono)', fontSize: 11 }}>{s}</span>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}

            {/* ── 感知配置 ── */}
            {tab === 'perception' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <JsonBlock label="system_prompt_suffix" value={detail.perception?.system_prompt_suffix} />
                <JsonBlock label="extra_slots" value={detail.perception?.extra_slots} />
                <JsonBlock label="完整配置" value={detail.perception} collapsed />
              </div>
            )}

            {/* ── 规划配置 ── */}
            {tab === 'planning' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <JsonBlock label="prompt_suffix" value={detail.planning?.prompt_suffix} />
                <JsonBlock label="完整配置" value={detail.planning} collapsed />
              </div>
            )}
          </>
        )}

        {/* 底栏（仅概览 tab 显示保存按钮）*/}
        {!loading && detail && tab === 'overview' && (
          <div className="an-drawer-footer">
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ fontSize: 12 }}>取消</button>
            <button
              type="button"
              className="an-btn primary"
              onClick={handleSave}
              disabled={saving}
              style={{ fontSize: 12, minWidth: 72 }}
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        )}
      </div>
    </>
  );
}

// ── 小组件 ──────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)',
      textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10,
    }}>
      {children}
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '72px 1fr', gap: 10, alignItems: 'flex-start' }}>
      <span style={{ fontSize: 12, color: 'var(--an-ink-4)', paddingTop: 6 }}>{label}</span>
      <div>{children}</div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: '10px 12px', border: '1px solid var(--an-border)',
      borderRadius: 'var(--an-radius)', background: 'var(--an-bg-raised)',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <span style={{ fontSize: 10, color: 'var(--an-ink-4)' }}>{label}</span>
      <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 18, fontWeight: 600, color: 'var(--an-ink)' }}>
        {value}
      </span>
    </div>
  );
}

function JsonBlock({ label, value, collapsed }: { label: string; value: unknown; collapsed?: boolean }) {
  const [open, setOpen] = useState(!collapsed);
  const text = value == null
    ? '—'
    : typeof value === 'string'
      ? value || '（空）'
      : JSON.stringify(value, null, 2);
  return (
    <section>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {label}
        </span>
        <span style={{ fontSize: 10, color: 'var(--an-ink-5)' }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <pre style={{
          margin: 0, padding: '10px 12px',
          background: 'var(--an-bg-sunken)', border: '1px solid var(--an-border-subtle)',
          borderRadius: 'var(--an-radius)', fontFamily: 'var(--an-font-mono)',
          fontSize: 11, lineHeight: 1.65, color: 'var(--an-ink-2)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 280, overflow: 'auto',
        }}>
          {text}
        </pre>
      )}
    </section>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  height: 30,
  padding: '0 8px',
  border: '1px solid var(--an-border)',
  borderRadius: 'var(--an-radius-sm)',
  background: 'var(--an-bg-raised)',
  color: 'var(--an-ink)',
  fontSize: 12,
  outline: 'none',
  boxSizing: 'border-box',
};
