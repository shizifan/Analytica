import { useEffect, useMemo, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { api, type AdminAuditEntry } from '../../api/client';

const ACTION_CHIP: Record<string, string> = {
  create: 'accent',
  update: '',
  delete: 'err',
  toggle: 'warn',
  invoke: 'ok',
};

export function AuditView() {
  const [items, setItems] = useState<AdminAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [resourceFilter, setResourceFilter] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { items } = await api.admin.listAudit({
        resourceType: resourceFilter || undefined,
        limit: 200,
      });
      setItems(items);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [resourceFilter]);

  const types = useMemo(
    () => Array.from(new Set(items.map((i) => i.resource_type).filter(Boolean))) as string[],
    [items],
  );

  return (
    <AdminListShell
      title="审计日志"
      count={items.length}
      actions={
        <select
          className="an-search-box"
          style={{ width: 140, paddingLeft: 8 }}
          value={resourceFilter}
          onChange={(e) => setResourceFilter(e.target.value)}
        >
          <option value="">全部资源</option>
          {types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      }
    >
      {loading && <div className="an-admin-empty">加载中…</div>}
      {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
      {!loading && !err && items.length === 0 && (
        <div className="an-admin-empty">
          <strong>暂无审计记录</strong>
          管理操作产生的日志会在这里出现
        </div>
      )}
      {!loading && !err && items.length > 0 && (
        <table className="an-admin-table">
          <thead>
            <tr>
              <th style={{ width: 150 }}>时间</th>
              <th style={{ width: 90 }}>Actor</th>
              <th style={{ width: 100 }}>Action</th>
              <th style={{ width: 120 }}>资源类型</th>
              <th>资源 ID</th>
              <th style={{ width: 80 }}>结果</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} title={it.diff ? JSON.stringify(it.diff).slice(0, 400) : undefined}>
                <td className="mono">{(it.ts || '').slice(0, 19)}</td>
                <td>
                  <span className={`an-admin-chip ${it.actor_type === 'agent' ? 'accent' : ''}`}>
                    {it.actor_type}
                  </span>
                </td>
                <td>
                  <span className={`an-admin-chip ${ACTION_CHIP[it.action] ?? ''}`}>
                    {it.action}
                  </span>
                </td>
                <td className="mono">{it.resource_type ?? '—'}</td>
                <td className="mono">{it.resource_id ?? '—'}</td>
                <td>
                  <span className={`an-admin-chip ${it.result === 'success' ? 'ok' : 'err'}`}>
                    {it.result}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminListShell>
  );
}
