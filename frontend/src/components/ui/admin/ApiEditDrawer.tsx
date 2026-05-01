import { useEffect, useRef, useState } from 'react';
import { api, type AdminApi } from '../../../api/client';

const DOMAIN_OPTIONS: Array<{ code: string; label: string }> = [
  { code: 'D1', label: '生产运营' },
  { code: 'D2', label: '市场商务' },
  { code: 'D3', label: '客户管理' },
  { code: 'D4', label: '投企管理' },
  { code: 'D5', label: '资产管理' },
  { code: 'D6', label: '投资管理' },
  { code: 'D7', label: '设备子屏' },
];

const TIME_TYPE_OPTIONS: Array<{ code: string; label: string }> = [
  { code: 'T_RT',    label: '实时' },
  { code: 'T_DAY',   label: '日度' },
  { code: 'T_MON',   label: '月度' },
  { code: 'T_TREND', label: '月度趋势' },
  { code: 'T_CUM',   label: '累计' },
  { code: 'T_YOY',   label: '同比年度' },
  { code: 'T_HIST',  label: '历史' },
];

const GRANULARITY_OPTIONS: Array<{ code: string; label: string }> = [
  { code: 'G_PORT',   label: '港区' },
  { code: 'G_ZONE',   label: '区域' },
  { code: 'G_BIZ',    label: '业务板块' },
  { code: 'G_CARGO',  label: '货类' },
  { code: 'G_CLIENT', label: '客户' },
  { code: 'G_CMP',    label: '公司' },
  { code: 'G_BERTH',  label: '泊位' },
  { code: 'G_EQUIP',  label: '设备' },
];

function codeLabel(options: Array<{ code: string; label: string }>, code: string): string {
  return options.find((o) => o.code === code)?.label ?? code;
}

interface Props {
  /** API endpoint name to load / edit. Drawer fetches its own copy via GET. */
  name: string;
  onClose: () => void;
  onSaved?: (updated: AdminApi) => void;
  /** When true, all fields are read-only and the save button is hidden. */
  readOnly?: boolean;
}

type Tab = 'basic' | 'params' | 'schema' | 'semantic';

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'basic', label: '基础' },
  { key: 'params', label: '参数' },
  { key: 'schema', label: '字段' },
  { key: 'semantic', label: '语义' },
];

interface Draft {
  method: string;
  path: string;
  domain: string;
  intent: string;
  time_type: string;
  granularity: string;
  tags: string[];
  required_params: string[];
  optional_params: string[];
  param_note: string;
  returns: string;
  disambiguate: string;
  source: string;
  enabled: boolean;
  // ``field_schema`` rows: 3 elements (name/type/desc) or 4 (+ label_zh).
  // Always edited as a 4-cell row in the UI; an empty 4th cell is dropped
  // on save so the on-wire shape stays minimal.
  field_schema: Array<[string, string, string, string]>;
  use_cases: string[];
  chain_with: string[];
  analysis_note: string;
}

function emptyDraft(): Draft {
  return {
    method: 'GET', path: '', domain: '', intent: '',
    time_type: '', granularity: '',
    tags: [], required_params: [], optional_params: [],
    param_note: '', returns: '', disambiguate: '',
    source: 'prod', enabled: true,
    field_schema: [],
    use_cases: [], chain_with: [], analysis_note: '',
  };
}

function detailToDraft(d: AdminApi): Draft {
  const fs = (d.field_schema ?? []).map<[string, string, string, string]>((row) => [
    row[0] ?? '', row[1] ?? '', row[2] ?? '', row[3] ?? '',
  ]);
  return {
    method: d.method, path: d.path, domain: d.domain,
    intent: d.intent ?? '',
    time_type: d.time_type ?? '',
    granularity: d.granularity ?? '',
    tags: [...(d.tags ?? [])],
    required_params: [...(d.required_params ?? [])],
    optional_params: [...(d.optional_params ?? [])],
    param_note: d.param_note ?? '',
    returns: d.returns ?? '',
    disambiguate: d.disambiguate ?? '',
    source: d.source,
    enabled: d.enabled,
    field_schema: fs,
    use_cases: [...(d.use_cases ?? [])],
    chain_with: [...(d.chain_with ?? [])],
    analysis_note: d.analysis_note ?? '',
  };
}

function draftToPayload(name: string, d: Draft) {
  // Drop trailing empty 4th cell so unchanged 3-element rows stay 3-element
  // on save. Empty 4th = "no per-endpoint label override".
  const fs = d.field_schema
    .filter((row) => (row[0] ?? '').trim())
    .map((row) => (row[3] ?? '').trim() ? row : [row[0], row[1], row[2]]);
  return {
    name,
    method: d.method,
    path: d.path,
    domain: d.domain,
    intent: d.intent || null,
    time_type: d.time_type || null,
    granularity: d.granularity || null,
    tags: d.tags.filter((s) => s.trim()),
    required_params: d.required_params.filter((s) => s.trim()),
    optional_params: d.optional_params.filter((s) => s.trim()),
    param_note: d.param_note || null,
    returns: d.returns || null,
    disambiguate: d.disambiguate || null,
    source: d.source,
    enabled: d.enabled,
    field_schema: fs,
    use_cases: d.use_cases.filter((s) => s.trim()),
    chain_with: d.chain_with.filter((s) => s.trim()),
    analysis_note: d.analysis_note || null,
  };
}

export function ApiEditDrawer({ name, onClose, onSaved, readOnly = false }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<Tab>('basic');
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    api.admin.getApi(name)
      .then((d) => setDraft(detailToDraft(d)))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [name]);

  const handleSave = async () => {
    setSaving(true);
    setSaveErr(null);
    try {
      await api.admin.upsertApi(name, draftToPayload(name, draft));
      const fresh = await api.admin.getApi(name);
      onSaved?.(fresh);
      onClose();
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  // ── List-row helpers (required_params / optional_params / use_cases / chain_with / tags) ──
  const setListField = (key: keyof Pick<Draft,
    'tags' | 'required_params' | 'optional_params' | 'use_cases' | 'chain_with'
  >) => ({
    add: () => setDraft({ ...draft, [key]: [...draft[key], ''] }),
    update: (i: number, v: string) => {
      const next = [...draft[key]];
      next[i] = v;
      setDraft({ ...draft, [key]: next });
    },
    remove: (i: number) =>
      setDraft({ ...draft, [key]: draft[key].filter((_, idx) => idx !== i) }),
  });

  // ── field_schema row helpers ──
  const addSchemaRow = () =>
    setDraft({ ...draft, field_schema: [...draft.field_schema, ['', '', '', '']] });
  const updateSchemaCell = (i: number, col: 0 | 1 | 2 | 3, v: string) => {
    const next = draft.field_schema.map<[string, string, string, string]>(
      (row, idx) => idx === i
        ? [
          col === 0 ? v : row[0],
          col === 1 ? v : row[1],
          col === 2 ? v : row[2],
          col === 3 ? v : row[3],
        ]
        : row,
    );
    setDraft({ ...draft, field_schema: next });
  };
  const removeSchemaRow = (i: number) =>
    setDraft({ ...draft, field_schema: draft.field_schema.filter((_, idx) => idx !== i) });

  return (
    <>
      <div
        className="an-drawer-overlay"
        ref={overlayRef}
        onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      />
      <div className="an-drawer" style={{ width: 'min(820px, 100vw)' }}>
        {/* Header */}
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            <span style={{ fontWeight: 600 }}>{readOnly ? '查看 API' : '编辑 API'}</span>
            <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 11, color: 'var(--an-ink-4)' }}>
              {name}
            </span>
          </div>
          <div className="an-drawer-actions">
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ padding: '3px 8px', fontSize: 12 }}>关闭</button>
          </div>
        </div>

        {/* Tabs */}
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

        {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
        {loading && <div className="an-admin-empty">加载中…</div>}

        {!loading && !err && (
          <>
            {tab === 'basic' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <FieldRow label="名称">
                  <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 12, color: 'var(--an-ink-3)' }}>
                    {name}
                  </span>
                </FieldRow>
                <FieldRow label="HTTP 方法">
                  <select
                    value={draft.method}
                    onChange={(e) => setDraft({ ...draft, method: e.target.value })}
                    disabled={readOnly}
                    style={{ ...inputStyle, width: 140 }}
                  >
                    {['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </FieldRow>
                <FieldRow label="路径">
                  <input type="text" value={draft.path}
                    onChange={(e) => setDraft({ ...draft, path: e.target.value })}
                    disabled={readOnly}
                    style={{ ...inputStyle, fontFamily: 'var(--an-font-mono)' }} />
                </FieldRow>
                <FieldRow label="域">
                  {readOnly ? (
                    <span style={{ fontSize: 12, color: 'var(--an-ink-2)' }}>
                      {codeLabel(DOMAIN_OPTIONS, draft.domain) || '—'}
                    </span>
                  ) : (
                    <select
                      value={draft.domain}
                      onChange={(e) => setDraft({ ...draft, domain: e.target.value })}
                      style={{ ...inputStyle, width: 160 }}
                    >
                      <option value="">请选择…</option>
                      {DOMAIN_OPTIONS.map((o) => (
                        <option key={o.code} value={o.code}>{o.label}（{o.code}）</option>
                      ))}
                    </select>
                  )}
                </FieldRow>
                <FieldRow label="语义说明">
                  <textarea value={draft.intent}
                    onChange={(e) => setDraft({ ...draft, intent: e.target.value })}
                    disabled={readOnly}
                    rows={2}
                    style={{ ...inputStyle, height: 'auto', resize: readOnly ? 'none' : 'vertical' }} />
                </FieldRow>
                <FieldRow label="时间类型">
                  {readOnly ? (
                    <span style={{ fontSize: 12, color: 'var(--an-ink-2)' }}>
                      {codeLabel(TIME_TYPE_OPTIONS, draft.time_type) || '—'}
                    </span>
                  ) : (
                    <select
                      value={draft.time_type}
                      onChange={(e) => setDraft({ ...draft, time_type: e.target.value })}
                      style={{ ...inputStyle, width: 200 }}
                    >
                      <option value="">请选择…</option>
                      {TIME_TYPE_OPTIONS.map((o) => (
                        <option key={o.code} value={o.code}>{o.label}（{o.code}）</option>
                      ))}
                    </select>
                  )}
                </FieldRow>
                <FieldRow label="粒度">
                  {readOnly ? (
                    <span style={{ fontSize: 12, color: 'var(--an-ink-2)' }}>
                      {codeLabel(GRANULARITY_OPTIONS, draft.granularity) || '—'}
                    </span>
                  ) : (
                    <select
                      value={draft.granularity}
                      onChange={(e) => setDraft({ ...draft, granularity: e.target.value })}
                      style={{ ...inputStyle, width: 200 }}
                    >
                      <option value="">请选择…</option>
                      {GRANULARITY_OPTIONS.map((o) => (
                        <option key={o.code} value={o.code}>{o.label}（{o.code}）</option>
                      ))}
                    </select>
                  )}
                </FieldRow>
                <FieldRow label="数据源">
                  <select value={draft.source}
                    onChange={(e) => setDraft({ ...draft, source: e.target.value })}
                    disabled={readOnly}
                    style={{ ...inputStyle, width: 140 }}>
                    <option value="prod">生产</option>
                    <option value="mock">模拟</option>
                  </select>
                </FieldRow>
                <FieldRow label="启用">
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                    <input type="checkbox" checked={draft.enabled}
                      onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                      disabled={readOnly} />
                    {draft.enabled ? '启用中' : '已停用'}
                  </label>
                </FieldRow>
                <FieldRow label="标签">
                  <ListEditor
                    values={draft.tags}
                    onAdd={setListField('tags').add}
                    onUpdate={setListField('tags').update}
                    onRemove={setListField('tags').remove}
                    placeholder="如 同比 / 月度 / 港区"
                    readOnly={readOnly}
                  />
                </FieldRow>
              </div>
            )}

            {tab === 'params' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <FieldRow label="必填参数">
                  <ListEditor
                    values={draft.required_params}
                    onAdd={setListField('required_params').add}
                    onUpdate={setListField('required_params').update}
                    onRemove={setListField('required_params').remove}
                    placeholder="参数名（如 startDate）"
                    mono
                    readOnly={readOnly}
                  />
                </FieldRow>
                <FieldRow label="可选参数">
                  <ListEditor
                    values={draft.optional_params}
                    onAdd={setListField('optional_params').add}
                    onUpdate={setListField('optional_params').update}
                    onRemove={setListField('optional_params').remove}
                    placeholder="参数名"
                    mono
                    readOnly={readOnly}
                  />
                </FieldRow>
                <FieldRow label="参数说明">
                  <textarea value={draft.param_note}
                    onChange={(e) => setDraft({ ...draft, param_note: e.target.value })}
                    disabled={readOnly}
                    rows={3}
                    style={{ ...inputStyle, height: 'auto', resize: readOnly ? 'none' : 'vertical' }} />
                </FieldRow>
                <FieldRow label="返回字段">
                  <textarea value={draft.returns}
                    onChange={(e) => setDraft({ ...draft, returns: e.target.value })}
                    disabled={readOnly}
                    rows={2} placeholder="如 dateMonth/qty/yoyRate"
                    style={{ ...inputStyle, height: 'auto', resize: readOnly ? 'none' : 'vertical', fontFamily: 'var(--an-font-mono)' }} />
                </FieldRow>
              </div>
            )}

            {tab === 'schema' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <SectionLabel>field_schema</SectionLabel>
                  {!readOnly && (
                    <button type="button" className="an-btn ghost" onClick={addSchemaRow}
                      style={{ padding: '2px 8px', fontSize: 11 }}>+ 添加字段</button>
                  )}
                </div>
                <div style={{ fontSize: 11, color: 'var(--an-ink-4)', marginTop: -6 }}>
                  4 列：字段名 / 类型 / 含义 / 中文显示名（最后一列留空表示沿用全局映射）
                </div>
                {draft.field_schema.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>暂无字段定义</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {draft.field_schema.map((row, i) => (
                      <div key={i} style={{ display: 'grid', gridTemplateColumns: readOnly ? '1.4fr 0.8fr 2fr 1.4fr' : '1.4fr 0.8fr 2fr 1.4fr auto', gap: 6, alignItems: 'center' }}>
                        <input value={row[0]} placeholder="字段名"
                          onChange={(e) => updateSchemaCell(i, 0, e.target.value)}
                          disabled={readOnly}
                          style={{ ...inputStyle, fontFamily: 'var(--an-font-mono)' }} />
                        <input value={row[1]} placeholder="类型"
                          onChange={(e) => updateSchemaCell(i, 1, e.target.value)}
                          disabled={readOnly}
                          style={{ ...inputStyle, fontFamily: 'var(--an-font-mono)' }} />
                        <input value={row[2]} placeholder="含义"
                          onChange={(e) => updateSchemaCell(i, 2, e.target.value)}
                          disabled={readOnly}
                          style={inputStyle} />
                        <input value={row[3]} placeholder="中文显示名（可空）"
                          onChange={(e) => updateSchemaCell(i, 3, e.target.value)}
                          disabled={readOnly}
                          style={inputStyle} />
                        {!readOnly && (
                          <button type="button" className="an-btn ghost"
                            onClick={() => removeSchemaRow(i)}
                            style={{ padding: '2px 8px', fontSize: 11 }}>×</button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === 'semantic' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <FieldRow label="消歧">
                  <textarea value={draft.disambiguate}
                    onChange={(e) => setDraft({ ...draft, disambiguate: e.target.value })}
                    disabled={readOnly}
                    rows={2}
                    placeholder="如 区别getXxx=A；本接口=B"
                    style={{ ...inputStyle, height: 'auto', resize: readOnly ? 'none' : 'vertical' }} />
                </FieldRow>
                <FieldRow label="典型用例">
                  <ListEditor
                    values={draft.use_cases}
                    onAdd={setListField('use_cases').add}
                    onUpdate={setListField('use_cases').update}
                    onRemove={setListField('use_cases').remove}
                    placeholder="如 历年投资计划完成趋势"
                    readOnly={readOnly}
                  />
                </FieldRow>
                <FieldRow label="建议组合">
                  <ListEditor
                    values={draft.chain_with}
                    onAdd={setListField('chain_with').add}
                    onUpdate={setListField('chain_with').update}
                    onRemove={setListField('chain_with').remove}
                    placeholder="组合调用的端点名"
                    mono
                    readOnly={readOnly}
                  />
                </FieldRow>
                <FieldRow label="分析要点">
                  <textarea value={draft.analysis_note}
                    onChange={(e) => setDraft({ ...draft, analysis_note: e.target.value })}
                    disabled={readOnly}
                    rows={3}
                    placeholder="数据结构特征 / 注意事项"
                    style={{ ...inputStyle, height: 'auto', resize: readOnly ? 'none' : 'vertical' }} />
                </FieldRow>
              </div>
            )}
          </>
        )}

        {/* Footer */}
        {!loading && !err && (
          <div className="an-drawer-footer">
            {saveErr && (
              <div style={{ flex: 1, fontSize: 11, color: 'var(--an-err)' }}>{saveErr}</div>
            )}
            <button type="button" className="an-btn ghost" onClick={onClose} disabled={saving}
              style={{ fontSize: 12 }}>{readOnly ? '关闭' : '取消'}</button>
            {!readOnly && (
              <button
                type="button"
                className="an-btn primary"
                onClick={handleSave}
                disabled={saving || !draft.path.trim() || !draft.domain.trim()}
                style={{ fontSize: 12, minWidth: 72 }}
              >
                {saving ? '保存中…' : '保存'}
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

interface ListEditorProps {
  values: string[];
  onAdd(): void;
  onUpdate(i: number, v: string): void;
  onRemove(i: number): void;
  placeholder?: string;
  mono?: boolean;
  readOnly?: boolean;
}

function ListEditor({ values, onAdd, onUpdate, onRemove, placeholder, mono, readOnly }: ListEditorProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {values.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>（空）</div>
      )}
      {values.map((v, i) => (
        <div key={i} style={{ display: 'flex', gap: 6 }}>
          <input
            type="text"
            value={v}
            placeholder={placeholder}
            onChange={(e) => onUpdate(i, e.target.value)}
            disabled={readOnly}
            style={{ ...inputStyle, flex: 1, ...(mono ? { fontFamily: 'var(--an-font-mono)' } : {}) }}
          />
          {!readOnly && (
            <button type="button" className="an-btn ghost"
              onClick={() => onRemove(i)}
              style={{ padding: '2px 8px', fontSize: 11 }}>×</button>
          )}
        </div>
      ))}
      {!readOnly && (
        <button type="button" className="an-btn ghost"
          onClick={onAdd}
          style={{ alignSelf: 'flex-start', padding: '2px 10px', fontSize: 11 }}>+ 添加</button>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)',
      textTransform: 'uppercase', letterSpacing: '0.06em',
    }}>
      {children}
    </div>
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
