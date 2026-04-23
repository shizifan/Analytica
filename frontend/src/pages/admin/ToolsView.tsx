import { useEffect, useMemo, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { ToolDetailDrawer } from '../../components/ui/admin/ToolDetailDrawer';
import { api, type AdminTool } from '../../api/client';

const KIND_LABEL: Record<string, string> = {
  data_fetch: '数据获取',
  analysis: '分析',
  visualization: '可视化',
  report: '报告生成',
  search: '检索',
};

export function ToolsView() {
  const [items, setItems] = useState<AdminTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<AdminTool | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const { items } = await api.admin.listTools();
      setItems(items);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) =>
      it.skill_id.toLowerCase().includes(q) ||
      (it.description ?? '').toLowerCase().includes(q),
    );
  }, [items, query]);

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await api.admin.toggleTool(id, enabled);
      setItems((arr) =>
        arr.map((it) => (it.skill_id === id ? { ...it, enabled } : it)),
      );
      setSelected((prev) => prev?.skill_id === id ? { ...prev, enabled } : prev);
    } catch (e) {
      window.alert(`切换失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <>
      <AdminListShell
        title="工具"
        count={filtered.length}
        onSearch={setQuery}
        searchPlaceholder="搜索工具 ID / 描述..."
      >
        {loading && <div className="an-admin-empty">加载中…</div>}
        {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
        {!loading && !err && filtered.length > 0 && (
          <table className="an-admin-table">
            <thead>
              <tr>
                <th style={{ width: 220 }}>工具 ID</th>
                <th style={{ width: 100 }}>类别</th>
                <th>描述</th>
                <th style={{ width: 84 }} className="num">运行次数</th>
                <th style={{ width: 80 }} className="num">错误率</th>
                <th style={{ width: 90 }} className="num">平均耗时</th>
                <th style={{ width: 92 }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((it) => {
                const errRate = it.run_count > 0
                  ? Math.round((it.error_count / it.run_count) * 100)
                  : 0;
                return (
                  <tr
                    key={it.skill_id}
                    title={it.last_error_msg ?? undefined}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSelected(it)}
                  >
                    <td className="mono">{it.skill_id}</td>
                    <td>
                      <span className="an-admin-chip">
                        {KIND_LABEL[it.kind] ?? it.kind}
                      </span>
                    </td>
                    <td>{it.description ?? '—'}</td>
                    <td className="num">{it.run_count}</td>
                    <td className="num">
                      <span className={errRate > 10 ? 'an-admin-chip err' : ''}>
                        {errRate > 0 ? `${errRate}%` : '—'}
                      </span>
                    </td>
                    <td className="num">
                      {it.avg_latency_ms != null ? `${it.avg_latency_ms} ms` : '—'}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`an-admin-chip ${it.enabled ? 'ok' : 'err'}`}
                        style={{ cursor: 'pointer', border: 0 }}
                        onClick={(e) => { e.stopPropagation(); handleToggle(it.skill_id, !it.enabled); }}
                        title={`点击 ${it.enabled ? '停用' : '启用'}`}
                      >
                        {it.enabled ? '启用' : '停用'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </AdminListShell>

      {selected && (
        <ToolDetailDrawer
          item={selected}
          onClose={() => setSelected(null)}
          onToggle={handleToggle}
        />
      )}
    </>
  );
}
