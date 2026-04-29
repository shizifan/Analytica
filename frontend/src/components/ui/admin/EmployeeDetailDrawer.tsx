import { useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import type { EmployeeDetail, EmployeeFAQ } from '../../../types';

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
  const [faqs, setFaqs] = useState<EmployeeFAQ[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  // P3.1 — perception/planning prompt drafts + dry-run gates
  const [perceptionPrompt, setPerceptionPrompt] = useState('');
  const [planningPrompt, setPlanningPrompt] = useState('');
  const [perceptionQuery, setPerceptionQuery] = useState(
    '查 2026 年集装箱吞吐量',
  );
  const [planningQuery, setPlanningQuery] = useState(
    '查 2026 年集装箱吞吐量',
  );

  // Dry-run state. ``ok=true && promptSnapshot===currentPrompt`` is the
  // gate for enabling save on the perception/planning tab. Any edit to
  // the prompt invalidates the snapshot, forcing re-test.
  type DryRunState = {
    status: 'idle' | 'running' | 'ok' | 'error';
    message: string;
    result: unknown;
    promptSnapshot: string;  // prompt value at the time of last run
  };
  const initialDryRun = (): DryRunState => ({
    status: 'idle', message: '', result: null, promptSnapshot: '',
  });
  const [perceptionDryRun, setPerceptionDryRun] = useState<DryRunState>(initialDryRun);
  const [planningDryRun, setPlanningDryRun] = useState<DryRunState>(initialDryRun);

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
        setFaqs(d.faqs.map((f) => ({ ...f })));
        setPerceptionPrompt((d.perception?.system_prompt_suffix as string) ?? '');
        setPlanningPrompt((d.planning?.prompt_suffix as string) ?? '');
        setPerceptionDryRun(initialDryRun());
        setPlanningDryRun(initialDryRun());
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [employeeId]);

  const handleSave = async () => {
    if (!detail) return;
    setSaving(true);
    setSaveErr(null);
    try {
      // PUT replaces perception/planning with the dict supplied; merge our
      // edits onto the loaded values so other fields (extra_slots, etc.)
      // survive.
      const perception = {
        ...(detail.perception ?? {}),
        system_prompt_suffix: perceptionPrompt,
      };
      const planning = {
        ...(detail.planning ?? {}),
        prompt_suffix: planningPrompt,
      };
      const updated = await api.updateEmployee(detail.employee_id, {
        name, description, faqs,
        perception, planning,
        snapshot_note: 'admin edit',
      });
      setDetail(updated);
      setFaqs(updated.faqs.map((f) => ({ ...f })));
      setPerceptionPrompt((updated.perception?.system_prompt_suffix as string) ?? '');
      setPlanningPrompt((updated.planning?.prompt_suffix as string) ?? '');
      // Saved snapshot becomes the new baseline; dry-run results stay
      // valid only if the prompt didn't change after the run, which the
      // ``promptSnapshot`` check below enforces.
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const runPerceptionDryRun = async () => {
    setPerceptionDryRun({
      status: 'running', message: '', result: null,
      promptSnapshot: perceptionPrompt,
    });
    try {
      const r = await api.dryrunPerception(employeeId, {
        query: perceptionQuery,
        perception: { system_prompt_suffix: perceptionPrompt },
      });
      const intent = r.structured_intent;
      if (!intent) {
        setPerceptionDryRun({
          status: 'error',
          message: r.empty_required_slots.length
            ? `仍有未填槽位：${r.empty_required_slots.join(', ')}`
            : 'perception 未产出 intent',
          result: r,
          promptSnapshot: perceptionPrompt,
        });
        return;
      }
      setPerceptionDryRun({
        status: 'ok',
        message: `已识别 ${Object.keys((intent as Record<string, unknown>).slots ?? {}).length} 个槽位`,
        result: r,
        promptSnapshot: perceptionPrompt,
      });
    } catch (e) {
      setPerceptionDryRun({
        status: 'error',
        message: e instanceof Error ? e.message : String(e),
        result: null,
        promptSnapshot: perceptionPrompt,
      });
    }
  };

  const runPlanningDryRun = async () => {
    setPlanningDryRun({
      status: 'running', message: '', result: null,
      promptSnapshot: planningPrompt,
    });
    try {
      const r = await api.dryrunPlanning(employeeId, {
        query: planningQuery,
        perception: { system_prompt_suffix: perceptionPrompt },
        planning: { prompt_suffix: planningPrompt },
      });
      setPlanningDryRun({
        status: 'ok',
        message: `生成 ${r.task_count} 个任务`,
        result: r,
        promptSnapshot: planningPrompt,
      });
    } catch (e) {
      setPlanningDryRun({
        status: 'error',
        message: e instanceof Error ? e.message : String(e),
        result: null,
        promptSnapshot: planningPrompt,
      });
    }
  };

  const restoreInitialVersion = async () => {
    if (!window.confirm(
      '恢复到首版（v1.0）？\n当前未保存的改动会丢失，但需要点保存才会写入。'
    )) return;
    try {
      const v = await api.getEmployeeVersion(employeeId, '1.0');
      const snap = v.snapshot as Record<string, unknown>;
      const perception = (snap.perception ?? {}) as Record<string, unknown>;
      const planning = (snap.planning ?? {}) as Record<string, unknown>;
      setPerceptionPrompt((perception.system_prompt_suffix as string) ?? '');
      setPlanningPrompt((planning.prompt_suffix as string) ?? '');
      setPerceptionDryRun(initialDryRun());
      setPlanningDryRun(initialDryRun());
    } catch (e) {
      window.alert(`恢复失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // Save-button gate. The gate diverges by tab:
  //   * overview         — basic edit, no dry-run guard
  //   * perception/plan  — current draft must have a green dry-run for
  //                        the same prompt content (promptSnapshot match).
  const perceptionGateOk =
    perceptionDryRun.status === 'ok'
    && perceptionDryRun.promptSnapshot === perceptionPrompt;
  const planningGateOk =
    planningDryRun.status === 'ok'
    && planningDryRun.promptSnapshot === planningPrompt;

  const perceptionPromptDirty =
    perceptionPrompt !== ((detail?.perception?.system_prompt_suffix as string) ?? '');
  const planningPromptDirty =
    planningPrompt !== ((detail?.planning?.prompt_suffix as string) ?? '');

  // Save is allowed when:
  //   - basic fields are valid (name not empty), AND
  //   - if the perception prompt changed → that tab's dry-run must be green,
  //   - if the planning prompt changed   → that tab's dry-run must be green.
  const saveDisabled =
    saving
    || !name.trim()
    || (perceptionPromptDirty && !perceptionGateOk)
    || (planningPromptDirty && !planningGateOk);

  const addFaq = () => {
    const id = `faq-${Date.now().toString(36)}`;
    setFaqs([...faqs, { id, question: '' }]);
  };
  const updateFaq = (idx: number, patch: Partial<EmployeeFAQ>) => {
    const next = [...faqs];
    next[idx] = { ...next[idx], ...patch };
    setFaqs(next);
  };
  const removeFaq = (idx: number) => setFaqs(faqs.filter((_, i) => i !== idx));

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
                    <StatCard label="工具" value={String(detail.tools?.length ?? 0)} />
                    <StatCard label="FAQ" value={String(faqs.length)} />
                  </div>
                </section>

                {/* 绑定工具列表 */}
                {(detail.tools?.length ?? 0) > 0 && (
                  <section>
                    <SectionLabel>绑定工具</SectionLabel>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {detail.tools.map((s) => (
                        <span key={s} className="an-admin-chip"
                          style={{ fontFamily: 'var(--an-font-mono)', fontSize: 11 }}>{s}</span>
                      ))}
                    </div>
                  </section>
                )}

                {/* FAQ 编辑 */}
                <section>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <SectionLabel>常见问题（FAQ）</SectionLabel>
                    <button
                      type="button"
                      className="an-btn ghost"
                      onClick={addFaq}
                      style={{ padding: '2px 8px', fontSize: 11 }}
                    >
                      + 添加
                    </button>
                  </div>
                  {faqs.length === 0 ? (
                    <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>暂无 FAQ</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {faqs.map((f, i) => (
                        <div key={f.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <input
                            type="text"
                            value={f.question}
                            placeholder={`FAQ ${i + 1}`}
                            onChange={(e) => updateFaq(i, { question: e.target.value })}
                            style={{ ...inputStyle, flex: 1 }}
                          />
                          <button
                            type="button"
                            className="an-btn ghost"
                            onClick={() => removeFaq(i)}
                            style={{ padding: '2px 8px', fontSize: 11, flexShrink: 0 }}
                            aria-label={`删除 FAQ ${i + 1}`}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </div>
            )}

            {/* ── 感知配置 ── */}
            {tab === 'perception' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <PromptEditor
                  label="system_prompt_suffix"
                  value={perceptionPrompt}
                  onChange={(v) => {
                    setPerceptionPrompt(v);
                    // Any edit invalidates the dry-run gate.
                    if (perceptionDryRun.status !== 'idle') {
                      setPerceptionDryRun({ ...perceptionDryRun, status: 'idle', message: '' });
                    }
                  }}
                  onRestoreDefault={restoreInitialVersion}
                  dirty={perceptionPromptDirty}
                />
                <DryRunPanel
                  query={perceptionQuery}
                  onQueryChange={setPerceptionQuery}
                  state={perceptionDryRun}
                  onRun={runPerceptionDryRun}
                  runLabel="试运行感知"
                  promptDirty={perceptionPromptDirty}
                  emptyHint="保存前请试运行感知，确认 prompt 改动可生成 intent。"
                />
                <JsonBlock label="extra_slots（只读）" value={detail.perception?.extra_slots} />
                <JsonBlock label="完整配置（只读）" value={detail.perception} collapsed />
              </div>
            )}

            {/* ── 规划配置 ── */}
            {tab === 'planning' && (
              <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <PromptEditor
                  label="prompt_suffix"
                  value={planningPrompt}
                  onChange={(v) => {
                    setPlanningPrompt(v);
                    if (planningDryRun.status !== 'idle') {
                      setPlanningDryRun({ ...planningDryRun, status: 'idle', message: '' });
                    }
                  }}
                  onRestoreDefault={restoreInitialVersion}
                  dirty={planningPromptDirty}
                />
                <DryRunPanel
                  query={planningQuery}
                  onQueryChange={setPlanningQuery}
                  state={planningDryRun}
                  onRun={runPlanningDryRun}
                  runLabel="试运行规划"
                  promptDirty={planningPromptDirty}
                  emptyHint="保存前请试运行规划，确认 prompt 改动可生成 plan.tasks。"
                />
                <JsonBlock label="完整配置（只读）" value={detail.planning} collapsed />
              </div>
            )}
          </>
        )}

        {/* 底栏：所有 tab 都可保存；perception/planning tab 受试运行门控 */}
        {!loading && detail && (
          <div className="an-drawer-footer">
            {saveErr && (
              <div style={{ flex: 1, fontSize: 11, color: 'var(--an-err)' }}>{saveErr}</div>
            )}
            <button type="button" className="an-btn ghost" onClick={onClose}
              disabled={saving} style={{ fontSize: 12 }}>取消</button>
            <button
              type="button"
              className="an-btn primary"
              onClick={handleSave}
              disabled={saveDisabled}
              title={
                saveDisabled && (perceptionPromptDirty && !perceptionGateOk)
                  ? '感知 prompt 已改但试运行未通过 — 请在感知 tab 先点试运行'
                  : saveDisabled && (planningPromptDirty && !planningGateOk)
                    ? '规划 prompt 已改但试运行未通过 — 请在规划 tab 先点试运行'
                    : ''
              }
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

function PromptEditor({
  label, value, onChange, onRestoreDefault, dirty,
}: {
  label: string;
  value: string;
  onChange(v: string): void;
  onRestoreDefault(): void;
  dirty: boolean;
}) {
  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          {label}{dirty && <span style={{ color: 'var(--an-warn)', marginLeft: 6 }}>·已改</span>}
        </span>
        <button
          type="button"
          className="an-btn ghost"
          onClick={onRestoreDefault}
          style={{ padding: '2px 8px', fontSize: 11 }}
        >
          ↺ 恢复默认（v1.0）
        </button>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={10}
        style={{
          width: '100%',
          padding: '8px 10px',
          border: '1px solid var(--an-border)',
          borderRadius: 'var(--an-radius)',
          background: 'var(--an-bg-raised)',
          color: 'var(--an-ink)',
          fontSize: 12,
          fontFamily: 'var(--an-font-mono)',
          lineHeight: 1.55,
          outline: 'none',
          resize: 'vertical',
          boxSizing: 'border-box',
        }}
      />
    </section>
  );
}

interface DryRunPanelProps {
  query: string;
  onQueryChange(v: string): void;
  state: {
    status: 'idle' | 'running' | 'ok' | 'error';
    message: string;
    result: unknown;
    promptSnapshot: string;
  };
  onRun(): void;
  runLabel: string;
  promptDirty: boolean;
  emptyHint: string;
}

function DryRunPanel({
  query, onQueryChange, state, onRun, runLabel, promptDirty, emptyHint,
}: DryRunPanelProps) {
  const statusColor =
    state.status === 'ok' ? 'var(--an-ok, #2e7d32)'
    : state.status === 'error' ? 'var(--an-err)'
    : state.status === 'running' ? 'var(--an-ink-4)'
    : 'var(--an-ink-4)';
  const statusLabel =
    state.status === 'ok' ? '✓ 通过'
    : state.status === 'error' ? '✗ 失败'
    : state.status === 'running' ? '运行中…'
    : '未运行';

  return (
    <section style={{
      padding: 12,
      border: '1px solid var(--an-border)',
      borderRadius: 'var(--an-radius)',
      background: 'var(--an-bg-sunken)',
    }}>
      <div style={{
        fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)',
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8,
      }}>
        试运行（保存门控）
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <input
          type="text"
          value={query}
          placeholder="样例 query"
          onChange={(e) => onQueryChange(e.target.value)}
          style={{
            flex: 1, height: 30, padding: '0 8px',
            border: '1px solid var(--an-border)',
            borderRadius: 'var(--an-radius-sm)',
            background: 'var(--an-bg-raised)', color: 'var(--an-ink)',
            fontSize: 12, outline: 'none', boxSizing: 'border-box',
          }}
        />
        <button
          type="button"
          className="an-btn"
          onClick={onRun}
          disabled={state.status === 'running' || !query.trim()}
          style={{ fontSize: 12, minWidth: 92 }}
        >
          {state.status === 'running' ? '运行中…' : runLabel}
        </button>
      </div>
      <div style={{ fontSize: 11, color: statusColor, marginBottom: 6 }}>
        <strong>{statusLabel}</strong>
        {state.message && <span style={{ marginLeft: 6 }}>· {state.message}</span>}
      </div>
      {promptDirty && state.status === 'idle' && (
        <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>{emptyHint}</div>
      )}
      {state.result != null && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--an-ink-4)' }}>
            结果详情 ▾
          </summary>
          <pre style={{
            margin: '6px 0 0 0', padding: '8px 10px',
            background: 'var(--an-bg-raised)',
            border: '1px solid var(--an-border-subtle)',
            borderRadius: 'var(--an-radius-sm)',
            fontFamily: 'var(--an-font-mono)',
            fontSize: 10, lineHeight: 1.55,
            color: 'var(--an-ink-2)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            maxHeight: 220, overflow: 'auto',
          }}>
            {JSON.stringify(state.result, null, 2)}
          </pre>
        </details>
      )}
    </section>
  );
}

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
