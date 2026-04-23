import { useEffect, useMemo, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { ApiTestDrawer } from '../../components/ui/admin/ApiTestDrawer';
import { api, type AdminApi } from '../../api/client';

/**
 * Phase 6b — API 端点列表。只读表格 + 搜索 + 删除。编辑抽屉留在后续
 * 迭代（现在后端 PUT 已经就绪）。
 */
export function ApisView() {
  const [items, setItems] = useState<AdminApi[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [domainFilter, setDomainFilter] = useState<string>('');

  const [domainNames, setDomainNames] = useState<Record<string, string>>({});
  const [testTarget, setTestTarget] = useState<AdminApi | null>(null);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [{ items }, { items: doms }] = await Promise.all([
        api.admin.listApis({ limit: 500 }),
        api.admin.listDomains(),
      ]);
      setItems(items);
      setDomainNames(Object.fromEntries(doms.map((d) => [d.code, d.name])));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (domainFilter && it.domain !== domainFilter) return false;
      if (!q) return true;
      return (
        it.name.toLowerCase().includes(q) ||
        (it.intent ?? '').toLowerCase().includes(q) ||
        it.path.toLowerCase().includes(q)
      );
    });
  }, [items, query, domainFilter]);

  const domains = useMemo(
    () => Array.from(new Set(items.map((i) => i.domain))).sort(),
    [items],
  );

  const handleDelete = async (name: string) => {
    if (!window.confirm(`删除 API 端点 "${name}"？\n对应技能调用会在下次请求失败。`)) return;
    try {
      await api.admin.deleteApi(name);
      setItems((arr) => arr.filter((it) => it.name !== name));
    } catch (e) {
      window.alert(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const actions = (
    <>
      <select
        className="an-search-box"
        style={{ width: 110, paddingLeft: 8 }}
        value={domainFilter}
        onChange={(e) => setDomainFilter(e.target.value)}
      >
        <option value="">全部域</option>
        {domains.map((d) => (
          <option key={d} value={d}>{d}</option>
        ))}
      </select>
    </>
  );

  return (
    <>
    <AdminListShell
      title="API 端点"
      count={filtered.length}
      onSearch={setQuery}
      searchPlaceholder="搜索 API 名 / 路径 / 语义..."
      actions={actions}
    >
      {loading && <div className="an-admin-empty">加载中…</div>}
      {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
      {!loading && !err && filtered.length === 0 && (
        <div className="an-admin-empty">
          <strong>无匹配 API</strong>
          尝试调整过滤条件
        </div>
      )}
      {!loading && !err && filtered.length > 0 && (
        <table className="an-admin-table">
          <thead>
            <tr>
              <th style={{ width: 72 }}>方法</th>
              <th style={{ width: 260 }}>名称</th>
              <th>语义</th>
              <th style={{ width: 80 }}>域</th>
              <th style={{ width: 80 }}>状态</th>
              <th style={{ width: 72 }}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((it) => (
              <tr key={it.name}>
                <td>
                  <span className={`an-admin-chip method ${it.method.toLowerCase()}`}>
                    {it.method}
                  </span>
                </td>
                <td className="mono" title={it.path}>
                  {it.name}
                  <div style={{ color: 'var(--an-ink-4)', fontSize: 10, marginTop: 2 }}>
                    {it.path}
                  </div>
                </td>
                <td>{it.intent ?? '—'}</td>
                <td>{domainNames[it.domain] ?? it.domain}</td>
                <td>
                  <span className={`an-admin-chip ${it.enabled ? 'ok' : 'err'}`}>
                    {it.enabled ? '启用' : '停用'}
                  </span>
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <button
                    type="button"
                    className="an-btn ghost"
                    onClick={() => setTestTarget(it)}
                    style={{ padding: '2px 8px', fontSize: 11, marginRight: 4 }}
                  >
                    测试
                  </button>
                  <button
                    type="button"
                    className="an-btn ghost"
                    onClick={() => handleDelete(it.name)}
                    style={{ padding: '2px 8px', fontSize: 11 }}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminListShell>

    {testTarget && (
      <ApiTestDrawer item={testTarget} onClose={() => setTestTarget(null)} />
    )}
    </>
  );
}
