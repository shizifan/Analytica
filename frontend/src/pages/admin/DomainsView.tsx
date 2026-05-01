import { useEffect, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { DomainEditDrawer } from '../../components/ui/admin/DomainEditDrawer';
import { api, type AdminDomain } from '../../api/client';

export function DomainsView() {
  const [items, setItems] = useState<AdminDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<AdminDomain | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const { items } = await api.admin.listDomains();
      setItems(items);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleDelete = async (d: AdminDomain) => {
    if (d.api_count > 0) {
      window.alert(
        `域 "${d.name}"（${d.code}）下还有 ${d.api_count} 个 API 端点，` +
        '请先迁移或删除这些端点后再删除域。',
      );
      return;
    }
    if (!window.confirm(`删除域 "${d.name}"（${d.code}）？此操作不可撤销。`)) {
      return;
    }
    try {
      await api.admin.deleteDomain(d.code);
      setItems((arr) => arr.filter((x) => x.code !== d.code));
    } catch (e) {
      window.alert(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const upsertLocal = (saved: AdminDomain) => {
    setItems((arr) => {
      if (arr.some((x) => x.code === saved.code)) {
        return arr.map((x) => x.code === saved.code ? saved : x);
      }
      return [...arr, saved].sort((a, b) => a.code.localeCompare(b.code));
    });
  };

  const actions = (
    <button
      type="button"
      className="an-btn primary"
      onClick={() => setCreateOpen(true)}
      style={{ padding: '4px 12px', fontSize: 12 }}
    >
      + 新建域
    </button>
  );

  return (
    <>
      <AdminListShell title="业务域" count={items.length} actions={actions}>
        {loading && <div className="an-admin-empty">加载中…</div>}
        {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
        {!loading && !err && items.length === 0 && (
          <div className="an-admin-empty">
            <strong>暂无业务域</strong>
            点击右上角"新建域"开始
          </div>
        )}
        {!loading && !err && items.length > 0 && (
          <div className="an-domain-grid">
            {items.map((d) => (
              <div key={d.code} className="an-domain-card">
                <div className="head">
                  <span
                    className="code"
                    style={d.color ? { background: d.color, color: 'white', borderColor: 'transparent' } : undefined}
                  >
                    {d.code}
                  </span>
                  <span className="an-mono" style={{ color: 'var(--an-ink-4)', fontSize: 10 }}>
                    {d.api_count} APIs · {d.employee_count} 员工
                  </span>
                </div>
                <div className="name">{d.name}</div>
                <div className="desc">{d.description ?? '—'}</div>
                {d.top_tags.length > 0 && (
                  <div className="stats">
                    {d.top_tags.slice(0, 6).map((t) => (
                      <span key={t} className="an-admin-chip" style={{ height: 18, fontSize: 10 }}>
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div style={{
                  display: 'flex', gap: 6, justifyContent: 'flex-end',
                  marginTop: 10, paddingTop: 8, borderTop: '1px dashed var(--an-border)',
                }}>
                  <button
                    type="button"
                    className="an-btn ghost"
                    onClick={() => setEditTarget(d)}
                    style={{ padding: '2px 10px', fontSize: 11 }}
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    className="an-btn ghost"
                    onClick={() => handleDelete(d)}
                    disabled={d.api_count > 0}
                    title={d.api_count > 0 ? '请先迁移该域下的 API 端点' : ''}
                    style={{ padding: '2px 10px', fontSize: 11 }}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </AdminListShell>

      {editTarget && (
        <DomainEditDrawer
          domain={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={upsertLocal}
        />
      )}
      {createOpen && (
        <DomainEditDrawer
          domain={null}
          onClose={() => setCreateOpen(false)}
          onSaved={upsertLocal}
        />
      )}
    </>
  );
}
