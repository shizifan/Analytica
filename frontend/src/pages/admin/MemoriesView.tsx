import { useEffect, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { api } from '../../api/client';

type Tab = 'preferences' | 'templates' | 'tool_notes';

interface Bundle {
  preferences: Array<Record<string, unknown>>;
  templates: Array<Record<string, unknown>>;
  tool_notes: Array<Record<string, unknown>>;
}

function str(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function MemoriesView() {
  const [data, setData] = useState<Bundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('preferences');

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.admin.listMemories();
      setData(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (kind: string, id: string) => {
    if (!window.confirm(`删除 ${kind} 记录 ${id}？`)) return;
    try {
      await api.admin.deleteMemory(kind === 'tool_notes' ? 'tool_note' : kind.replace(/s$/, ''), id);
      await load();
    } catch (e) {
      window.alert(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const counts = {
    preferences: data?.preferences.length ?? 0,
    templates: data?.templates.length ?? 0,
    tool_notes: data?.tool_notes.length ?? 0,
  };
  const activeCount = counts[tab];

  return (
    <AdminListShell title="记忆 / 偏好" count={activeCount}>
      <nav className="an-memory-tabs" role="tablist">
        {(['preferences', 'templates', 'tool_notes'] as const).map((k) => (
          <button
            key={k}
            type="button"
            className={`an-memory-tab${tab === k ? ' active' : ''}`}
            onClick={() => setTab(k)}
          >
            {k === 'preferences' ? '用户偏好'
              : k === 'templates' ? '分析模板'
              : '工具反馈'}
            <span className="count">{counts[k]}</span>
          </button>
        ))}
      </nav>

      {loading && <div className="an-admin-empty">加载中…</div>}
      {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}

      {!loading && !err && data && tab === 'preferences' && (
        <table className="an-admin-table">
          <thead>
            <tr>
              <th style={{ width: 160 }}>用户</th>
              <th style={{ width: 200 }}>键</th>
              <th>值</th>
              <th style={{ width: 150 }}>更新时间</th>
              <th style={{ width: 72 }}></th>
            </tr>
          </thead>
          <tbody>
            {data.preferences.map((p) => (
              <tr key={str(p.id)}>
                <td className="mono">{str(p.user_id)}</td>
                <td className="mono">{str(p.key)}</td>
                <td>{str(p.value)}</td>
                <td className="mono">{str(p.updated_at).slice(0, 19)}</td>
                <td style={{ textAlign: 'right' }}>
                  <button className="an-btn ghost" style={{ padding: '2px 8px', fontSize: 11 }}
                    onClick={() => handleDelete('preferences', str(p.id))}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && !err && data && tab === 'templates' && (
        <table className="an-admin-table">
          <thead>
            <tr>
              <th style={{ width: 160 }}>用户</th>
              <th>模板名</th>
              <th style={{ width: 80 }}>域</th>
              <th style={{ width: 100 }}>复杂度</th>
              <th style={{ width: 72 }} className="num">命中</th>
              <th style={{ width: 150 }}>最近使用</th>
              <th style={{ width: 72 }}></th>
            </tr>
          </thead>
          <tbody>
            {data.templates.map((t) => (
              <tr key={str(t.template_id)}>
                <td className="mono">{str(t.user_id)}</td>
                <td>{str(t.name)}</td>
                <td>{str(t.domain)}</td>
                <td>{str(t.output_complexity)}</td>
                <td className="num">{str(t.usage_count)}</td>
                <td className="mono">{(str(t.last_used) || '').slice(0, 19)}</td>
                <td style={{ textAlign: 'right' }}>
                  <button className="an-btn ghost" style={{ padding: '2px 8px', fontSize: 11 }}
                    onClick={() => handleDelete('templates', str(t.template_id))}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && !err && data && tab === 'tool_notes' && (
        <table className="an-admin-table">
          <thead>
            <tr>
              <th style={{ width: 200 }}>技能 ID</th>
              <th style={{ width: 160 }}>用户</th>
              <th>反馈</th>
              <th style={{ width: 90 }} className="num">分数</th>
              <th style={{ width: 150 }}>更新</th>
              <th style={{ width: 72 }}></th>
            </tr>
          </thead>
          <tbody>
            {data.tool_notes.map((n) => (
              <tr key={str(n.id)}>
                <td className="mono">{str(n.tool_id)}</td>
                <td className="mono">{str(n.user_id)}</td>
                <td>{str(n.notes)}</td>
                <td className="num">{str(n.performance_score)}</td>
                <td className="mono">{(str(n.updated_at) || '').slice(0, 19)}</td>
                <td style={{ textAlign: 'right' }}>
                  <button className="an-btn ghost" style={{ padding: '2px 8px', fontSize: 11 }}
                    onClick={() => handleDelete('tool_notes', str(n.id))}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminListShell>
  );
}
