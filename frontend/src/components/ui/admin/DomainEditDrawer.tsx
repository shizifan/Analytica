import { useEffect, useRef, useState } from 'react';
import { api, type AdminDomain } from '../../../api/client';

interface Props {
  /** Domain to edit. ``null`` opens the drawer in create mode. */
  domain: AdminDomain | null;
  onClose: () => void;
  onSaved?: (saved: AdminDomain) => void;
}

interface Draft {
  code: string;
  name: string;
  description: string;
  color: string;
  top_tags: string[];
}

function emptyDraft(): Draft {
  return { code: '', name: '', description: '', color: '', top_tags: [] };
}

function fromDomain(d: AdminDomain): Draft {
  return {
    code: d.code,
    name: d.name,
    description: d.description ?? '',
    color: d.color ?? '',
    top_tags: [...d.top_tags],
  };
}

export function DomainEditDrawer({ domain, onClose, onSaved }: Props) {
  const isCreate = domain === null;
  const overlayRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Draft>(() => domain ? fromDomain(domain) : emptyDraft());
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // ``code`` length cap from the DB schema (VARCHAR(8)). Keep this in
  // sync with migrations/versions/20260422_0001_admin_tables.py.
  const CODE_MAX = 8;

  const handleSave = async () => {
    const code = draft.code.trim();
    const name = draft.name.trim();
    if (isCreate && !code) { setSaveErr('请填写域代码'); return; }
    if (!name) { setSaveErr('请填写域名称'); return; }
    if (code.length > CODE_MAX) {
      setSaveErr(`域代码最长 ${CODE_MAX} 个字符`); return;
    }
    setSaving(true);
    setSaveErr(null);
    try {
      const saved = await api.admin.upsertDomain(code, {
        name,
        description: draft.description || null,
        color: draft.color || null,
        top_tags: draft.top_tags.map((t) => t.trim()).filter(Boolean),
      });
      onSaved?.(saved);
      onClose();
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const updateTag = (i: number, v: string) => {
    const next = [...draft.top_tags];
    next[i] = v;
    setDraft({ ...draft, top_tags: next });
  };
  const removeTag = (i: number) =>
    setDraft({ ...draft, top_tags: draft.top_tags.filter((_, idx) => idx !== i) });
  const addTag = () => setDraft({ ...draft, top_tags: [...draft.top_tags, ''] });

  return (
    <>
      <div
        className="an-drawer-overlay"
        ref={overlayRef}
        onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      />
      <div className="an-drawer" style={{ width: 'min(560px, 100vw)' }}>
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            <span style={{ fontWeight: 600 }}>{isCreate ? '新建域' : '编辑域'}</span>
            {!isCreate && (
              <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 11, color: 'var(--an-ink-4)' }}>
                {draft.code}
              </span>
            )}
          </div>
          <div className="an-drawer-actions">
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ padding: '3px 8px', fontSize: 12 }}>关闭</button>
          </div>
        </div>

        <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FieldRow label="域代码">
            {isCreate ? (
              <input
                type="text"
                value={draft.code}
                onChange={(e) => setDraft({ ...draft, code: e.target.value })}
                placeholder={`如 D8（最长 ${CODE_MAX} 字符）`}
                maxLength={CODE_MAX}
                style={{ ...inputStyle, fontFamily: 'var(--an-font-mono)', width: 200 }}
              />
            ) : (
              <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 12, color: 'var(--an-ink-3)' }}>
                {draft.code}
              </span>
            )}
          </FieldRow>

          <FieldRow label="名称">
            <input
              type="text"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="如 设备子屏"
              style={inputStyle}
            />
          </FieldRow>

          <FieldRow label="描述">
            <textarea
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              placeholder="该域的业务范围 / 端点类别说明"
              rows={3}
              style={{ ...inputStyle, height: 'auto', resize: 'vertical' }}
            />
          </FieldRow>

          <FieldRow label="颜色">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="text"
                value={draft.color}
                onChange={(e) => setDraft({ ...draft, color: e.target.value })}
                placeholder="oklch(0.70 0.12 220) 或 #RRGGBB"
                style={{ ...inputStyle, fontFamily: 'var(--an-font-mono)', flex: 1 }}
              />
              {draft.color && (
                <span
                  title="颜色预览"
                  style={{
                    display: 'inline-block', width: 24, height: 24, borderRadius: 4,
                    background: draft.color, border: '1px solid var(--an-border)',
                  }}
                />
              )}
            </div>
          </FieldRow>

          <FieldRow label="标签">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {draft.top_tags.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>（空）</div>
              )}
              {draft.top_tags.map((t, i) => (
                <div key={i} style={{ display: 'flex', gap: 6 }}>
                  <input
                    type="text"
                    value={t}
                    onChange={(e) => updateTag(i, e.target.value)}
                    placeholder="如 月度趋势"
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  <button type="button" className="an-btn ghost"
                    onClick={() => removeTag(i)}
                    style={{ padding: '2px 8px', fontSize: 11 }}>×</button>
                </div>
              ))}
              <button type="button" className="an-btn ghost"
                onClick={addTag}
                style={{ alignSelf: 'flex-start', padding: '2px 10px', fontSize: 11 }}>+ 添加</button>
            </div>
          </FieldRow>
        </div>

        <div className="an-drawer-foot" style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '12px 20px',
          borderTop: '1px solid var(--an-border)',
        }}>
          {saveErr && (
            <div style={{ flex: 1, fontSize: 11, color: 'var(--an-err)' }}>{saveErr}</div>
          )}
          <button type="button" className="an-btn ghost" onClick={onClose} disabled={saving}
            style={{ fontSize: 12 }}>取消</button>
          <button
            type="button"
            className="an-btn primary"
            onClick={handleSave}
            disabled={saving || !draft.name.trim() || (isCreate && !draft.code.trim())}
            style={{ fontSize: 12, minWidth: 72 }}
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '88px 1fr', gap: 10, alignItems: 'flex-start' }}>
      <span style={{ fontSize: 12, color: 'var(--an-ink-4)', paddingTop: 6 }}>{label}</span>
      <div>{children}</div>
    </div>
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
