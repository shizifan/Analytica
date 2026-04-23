import { useEffect, useRef, useState } from 'react';
import { api, type AgentSkill } from '../../../api/client';

type Tab = 'overview' | 'content';

interface Props {
  item: AgentSkill;
  onClose: () => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

export function SkillDetailDrawer({ item, onClose, onToggle, onDelete }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<Tab>('overview');

  const [content, setContent] = useState<string | null>(item.content ?? null);
  const [contentLoading, setContentLoading] = useState(false);
  const [contentErr, setContentErr] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    if (tab !== 'content' || content !== null || contentLoading) return;
    setContentLoading(true);
    setContentErr(null);
    api.admin.getAgentSkill(item.skill_id)
      .then((r) => setContent(r.content ?? null))
      .catch((e) => setContentErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setContentLoading(false));
  }, [tab, item.skill_id, content, contentLoading]);

  const handleToggle = async () => {
    try {
      await api.admin.toggleAgentSkill(item.skill_id, !item.enabled);
      onToggle(item.skill_id, !item.enabled);
    } catch (e) {
      window.alert(`切换失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <>
      <div
        className="an-drawer-overlay"
        ref={overlayRef}
        onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      />
      <div className="an-drawer" style={{ width: 'min(760px, 100vw)' }}>
        {/* 标题栏 */}
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            <span className="an-admin-chip accent">技能</span>
            <span style={{ fontWeight: 600 }}>{item.name}</span>
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
            <button
              type="button"
              className="an-btn ghost"
              style={{ padding: '3px 8px', fontSize: 12, color: 'var(--an-err)' }}
              onClick={() => { onDelete(item.skill_id); onClose(); }}
            >
              删除
            </button>
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ padding: '3px 8px', fontSize: 12 }}>关闭</button>
          </div>
        </div>

        {/* 标签页 */}
        <div className="an-memory-tabs" style={{ padding: '0 20px' }}>
          {(['overview', 'content'] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              className={`an-memory-tab${tab === t ? ' active' : ''}`}
              onClick={() => setTab(t)}
            >
              {t === 'overview' ? '概览' : '技能内容'}
            </button>
          ))}
        </div>

        {/* 概览 */}
        {tab === 'overview' && (
          <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <section>
              <SectionLabel>基本信息</SectionLabel>
              <div className="an-admin-kv">
                <span className="k">技能 ID</span>
                <span className="v" style={{ fontFamily: 'var(--an-font-mono)', fontSize: 12 }}>
                  {item.skill_id}
                </span>
                {item.version && (
                  <>
                    <span className="k">版本</span>
                    <span className="v">{item.version}</span>
                  </>
                )}
                {item.author && (
                  <>
                    <span className="k">作者</span>
                    <span className="v">{item.author}</span>
                  </>
                )}
                {item.created_at && (
                  <>
                    <span className="k">创建时间</span>
                    <span className="v">{item.created_at.replace('T', ' ').slice(0, 19)}</span>
                  </>
                )}
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

            {(item.tags ?? []).length > 0 && (
              <section>
                <SectionLabel>标签</SectionLabel>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {item.tags!.map((t) => (
                    <span key={t} className="an-admin-chip accent">{t}</span>
                  ))}
                </div>
              </section>
            )}

            <section>
              <SectionLabel>规划层注入说明</SectionLabel>
              <p style={{
                margin: 0, fontSize: 12, color: 'var(--an-ink-3)', lineHeight: 1.7,
                padding: '10px 12px',
                background: 'var(--an-bg-sunken)',
                border: '1px solid var(--an-border-subtle)',
                borderRadius: 'var(--an-radius)',
              }}>
                {item.enabled
                  ? '此技能已启用，其描述会注入到 Agent 规划层 Prompt，指导 Agent 编排工具执行步骤。'
                  : '此技能已停用，不会注入到规划层 Prompt。'}
              </p>
            </section>
          </div>
        )}

        {/* 技能内容（SKILL.md 原文）*/}
        {tab === 'content' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{
              padding: '6px 20px',
              background: 'var(--an-bg-sunken)',
              borderBottom: '1px solid var(--an-border-subtle)',
              fontFamily: 'var(--an-font-mono)',
              fontSize: 11,
              color: 'var(--an-ink-4)',
            }}>
              {item.skill_id}.md
            </div>
            {contentLoading && <div className="an-admin-empty">加载内容…</div>}
            {contentErr && (
              <div className="an-admin-empty">
                <strong>加载失败</strong>{contentErr}
              </div>
            )}
            {content && !contentLoading && (
              <div style={{ flex: 1, overflow: 'auto' }}>
                <pre style={{
                  margin: 0,
                  padding: '16px 20px',
                  fontFamily: 'var(--an-font-mono)',
                  fontSize: 12,
                  lineHeight: 1.75,
                  color: 'var(--an-ink-2)',
                  background: 'var(--an-bg-raised)',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  tabSize: 2,
                }}>
                  {content}
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
