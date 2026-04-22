import { useEffect, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { api, type AdminDomain } from '../../api/client';

export function DomainsView() {
  const [items, setItems] = useState<AdminDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { items } = await api.admin.listDomains();
        setItems(items);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <AdminListShell title="业务域" count={items.length}>
      {loading && <div className="an-admin-empty">加载中…</div>}
      {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
      {!loading && !err && (
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
            </div>
          ))}
        </div>
      )}
    </AdminListShell>
  );
}
