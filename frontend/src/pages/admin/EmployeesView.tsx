import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { EmployeeDetailDrawer } from '../../components/ui/admin/EmployeeDetailDrawer';
import { api } from '../../api/client';
import type { EmployeeSummary } from '../../types';

const DOMAIN_LABELS: Record<string, string> = {
  D1: '生产运营', D2: '市场商务', D3: '战略客户',
  D4: '公司治理', D5: '资产管理', D6: '投资项目', D7: '设备运营',
};

export function EmployeesView() {
  const [items, setItems] = useState<EmployeeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('selected');

  const openDetail = (id: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('selected', id);
    setSearchParams(next, { replace: false });
  };
  const closeDetail = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('selected');
    setSearchParams(next, { replace: false });
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.listEmployees();
      setItems(data);
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
      it.name.toLowerCase().includes(q) ||
      it.employee_id.toLowerCase().includes(q) ||
      (it.description ?? '').toLowerCase().includes(q) ||
      it.domains.some((d) => d.toLowerCase().includes(q) || (DOMAIN_LABELS[d] ?? '').includes(q)),
    );
  }, [items, query]);

  return (
    <>
      <AdminListShell
        title="数字员工"
        count={filtered.length}
        onSearch={setQuery}
        searchPlaceholder="搜索员工名称 / ID / 业务域..."
      >
        {loading && <div className="an-admin-empty">加载中…</div>}
        {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
        {!loading && !err && filtered.length > 0 && (
          <table className="an-admin-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}></th>
                <th>员工名称</th>
                <th>业务域</th>
                <th>描述</th>
                <th style={{ width: 60 }} className="num">版本</th>
                <th style={{ width: 72 }} className="num">API</th>
                <th style={{ width: 64 }} className="num">工具</th>
                <th style={{ width: 60 }} className="num">FAQ</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((emp) => (
                <tr
                  key={emp.employee_id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openDetail(emp.employee_id)}
                >
                  <td>
                    <div style={{
                      width: 28, height: 28, borderRadius: '50%',
                      background: 'var(--an-accent-bg)',
                      color: 'var(--an-accent-ink)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 700, fontSize: 11,
                    }}>
                      {(emp.initials || emp.name).slice(0, 2)}
                    </div>
                  </td>
                  <td>
                    <div style={{ fontWeight: 500 }}>{emp.name}</div>
                    <div style={{ fontSize: 10, color: 'var(--an-ink-5)', fontFamily: 'var(--an-font-mono)' }}>
                      {emp.employee_id}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {emp.domains.map((d) => (
                        <span key={d} className="an-admin-chip accent" style={{ fontSize: 10 }}>
                          {d} {DOMAIN_LABELS[d] ?? ''}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td style={{ color: 'var(--an-ink-3)', fontSize: 12 }}>
                    {emp.description
                      ? emp.description.length > 60
                        ? emp.description.slice(0, 60) + '…'
                        : emp.description
                      : '—'}
                  </td>
                  <td className="num mono">v{emp.version}</td>
                  <td className="num">{emp.endpoints_count ?? '—'}</td>
                  <td className="num">{emp.tools_count ?? '—'}</td>
                  <td className="num">{emp.faqs_count ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </AdminListShell>

      {selectedId && (
        <EmployeeDetailDrawer
          employeeId={selectedId}
          onClose={closeDetail}
        />
      )}
    </>
  );
}
