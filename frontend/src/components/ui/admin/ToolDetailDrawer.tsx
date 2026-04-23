import { useEffect, useRef, useState } from 'react';
import { api, type AdminTool } from '../../../api/client';

const KIND_LABEL: Record<string, string> = {
  data_fetch: '数据获取',
  analysis: '分析',
  visualization: '可视化',
  report: '报告生成',
  search: '检索',
};

type Tab = 'overview' | 'source';

interface Props {
  item: AdminTool;
  onClose: () => void;
  onToggle: (id: string, enabled: boolean) => void;
}

export function ToolDetailDrawer({ item, onClose, onToggle }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<Tab>('overview');

  const [source, setSource] = useState<string | null>(null);
  const [sourceFile, setSourceFile] = useState<string | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceErr, setSourceErr] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    if (tab !== 'source' || source !== null || sourceLoading) return;
    setSourceLoading(true);
    setSourceErr(null);
    api.admin.getToolSource(item.skill_id)
      .then((r) => { setSource(r.source); setSourceFile(r.file); })
      .catch((e) => setSourceErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setSourceLoading(false));
  }, [tab, item.skill_id, source, sourceLoading]);

  const handleToggle = async () => {
    try {
      await api.admin.toggleTool(item.skill_id, !item.enabled);
      onToggle(item.skill_id, !item.enabled);
    } catch (e) {
      window.alert(`切换失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const errRate = item.run_count > 0
    ? ((item.error_count / item.run_count) * 100).toFixed(1)
    : null;

  return (
    <>
      <div
        className="an-drawer-overlay"
        ref={overlayRef}
        onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      />
      <div className="an-drawer" style={{ width: 'min(700px, 100vw)' }}>
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            <span className="an-admin-chip accent">
              {KIND_LABEL[item.kind] ?? item.kind}
            </span>
            <span style={{ fontFamily: 'var(--an-font-mono)', fontSize: 13 }}>
              {item.skill_id}
            </span>
          </div>
          <div className="an-drawer-actions">
            <button
              type="button"
              className={`an-admin-chip ${item.enabled ? 'ok' : 'err'}`}
              style={{ cursor: 'pointer', border: 0 }}
              onClick={handleToggle}
              title={`点击${item.enabled ? '停用' : '启用'}`}
            >
              {item.enabled ? '启用' : '停用'}
            </button>
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ padding: '3px 8px', fontSize: 12 }}>关闭</button>
          </div>
        </div>

        <div className="an-memory-tabs" style={{ padding: '0 20px' }}>
          {(['overview', 'source'] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              className={`an-memory-tab${tab === t ? ' active' : ''}`}
              onClick={() => setTab(t)}
            >
              {t === 'overview' ? '概览' : '源码'}
            </button>
          ))}
        </div>

        {tab === 'overview' && (
          <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <section>
              <SectionLabel>基本信息</SectionLabel>
              <div className="an-admin-kv">
                <span className="k">名称</span>
                <span className="v">{item.name || item.skill_id}</span>
                <span className="k">类别</span>
                <span className="v">{KIND_LABEL[item.kind] ?? item.kind}</span>
                {item.updated_at && (
                  <>
                    <span className="k">更新时间</span>
                    <span className="v">{item.updated_at.replace('T', ' ').slice(0, 19)}</span>
                  </>
                )}
              </div>
            </section>

            {item.description && (
              <section>
                <SectionLabel>描述</SectionLabel>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--an-ink-2)', lineHeight: 1.7 }}>
                  {item.description}
                </p>
              </section>
            )}

            {(item.input_spec || item.output_spec) && (
              <section>
                <SectionLabel>输入 / 输出规格</SectionLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {item.input_spec && <SpecBlock label="输入" value={item.input_spec} />}
                  {item.output_spec && <SpecBlock label="输出" value={item.output_spec} />}
                </div>
              </section>
            )}

            {item.domains.length > 0 && (
              <section>
                <SectionLabel>适用域</SectionLabel>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {item.domains.map((d) => (
                    <span key={d} className="an-admin-chip accent">{d}</span>
                  ))}
                </div>
              </section>
            )}

            <section>
              <SectionLabel>运行统计</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                <StatCard label="总运行次数" value={String(item.run_count)} />
                <StatCard
                  label="错误率"
                  value={errRate != null ? `${errRate}%` : '—'}
                  warn={errRate != null && parseFloat(errRate) > 10}
                />
                <StatCard
                  label="平均耗时"
                  value={item.avg_latency_ms != null ? `${item.avg_latency_ms} ms` : '—'}
                />
              </div>
            </section>

            {item.last_error_msg && (
              <section>
                <SectionLabel>最近错误</SectionLabel>
                <div style={{
                  padding: '10px 12px',
                  background: 'var(--an-err-bg)',
                  border: '1px solid color-mix(in oklch, var(--an-err) 30%, transparent)',
                  borderRadius: 'var(--an-radius)',
                  display: 'flex', flexDirection: 'column', gap: 4,
                }}>
                  {item.last_error_at && (
                    <span style={{ fontSize: 10, color: 'var(--an-err)', fontFamily: 'var(--an-font-mono)' }}>
                      {item.last_error_at.replace('T', ' ').slice(0, 19)}
                    </span>
                  )}
                  <span style={{ fontSize: 12, color: 'var(--an-err)', lineHeight: 1.6 }}>
                    {item.last_error_msg}
                  </span>
                </div>
              </section>
            )}
          </div>
        )}

        {tab === 'source' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {sourceFile && (
              <div style={{
                padding: '6px 20px',
                background: 'var(--an-bg-sunken)',
                borderBottom: '1px solid var(--an-border-subtle)',
                fontFamily: 'var(--an-font-mono)',
                fontSize: 11,
                color: 'var(--an-ink-4)',
              }}>
                {sourceFile}
              </div>
            )}
            {sourceLoading && <div className="an-admin-empty">加载源码…</div>}
            {sourceErr && (
              <div className="an-admin-empty">
                <strong>加载失败</strong>{sourceErr}
              </div>
            )}
            {source && !sourceLoading && (
              <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
                <pre style={{
                  margin: 0,
                  padding: '16px 20px',
                  fontFamily: 'var(--an-font-mono)',
                  fontSize: 12,
                  lineHeight: 1.65,
                  color: 'var(--an-ink-2)',
                  background: 'var(--an-bg-raised)',
                  whiteSpace: 'pre',
                  tabSize: 4,
                }}>
                  <code>{source}</code>
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </>
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

function SpecBlock({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <span style={{
        flexShrink: 0, width: 32, fontSize: 10, fontWeight: 600,
        color: 'var(--an-ink-4)', textAlign: 'right', paddingTop: 6,
      }}>
        {label}
      </span>
      <code style={{
        flex: 1, display: 'block', padding: '6px 10px',
        background: 'var(--an-bg-sunken)', border: '1px solid var(--an-border-subtle)',
        borderRadius: 'var(--an-radius-sm)', fontFamily: 'var(--an-font-mono)',
        fontSize: 12, color: 'var(--an-ink-2)', lineHeight: 1.6,
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      }}>
        {value}
      </code>
    </div>
  );
}

function StatCard({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={{
      padding: '10px 12px', border: '1px solid var(--an-border)',
      borderRadius: 'var(--an-radius)', background: 'var(--an-bg-raised)',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <span style={{ fontSize: 10, color: 'var(--an-ink-4)' }}>{label}</span>
      <span style={{
        fontFamily: 'var(--an-font-mono)', fontSize: 18, fontWeight: 600,
        color: warn ? 'var(--an-err)' : 'var(--an-ink)',
      }}>
        {value}
      </span>
    </div>
  );
}
