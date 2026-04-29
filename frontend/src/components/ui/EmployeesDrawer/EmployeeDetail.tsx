import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../Icon';
import { api } from '../../../api/client';
import type {
  EmployeeDetail as EmployeeDetailType,
  EmployeeVersionSummary,
} from '../../../types';

interface Props {
  employeeId: string;
  onExit(): void;
  onUse(): void;
}

/**
 * Read-only employee detail (chat workspace).
 *
 * Editing happens exclusively in the admin console. The footer link deep-links
 * the user there with the current employee preselected.
 */
export function EmployeeDetail({ employeeId, onExit, onUse }: Props) {
  const [detail, setDetail] = useState<EmployeeDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<EmployeeVersionSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      api.getEmployee(employeeId),
      api.listEmployeeVersions(employeeId).catch(() => ({ items: [], count: 0 })),
    ])
      .then(([d, v]) => {
        if (cancelled) return;
        setDetail(d);
        setVersions(v.items);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [employeeId]);

  if (loading) {
    return <div style={{ color: 'var(--an-ink-4)', padding: 20 }}>加载中…</div>;
  }
  if (error || !detail) {
    return <div style={{ color: 'var(--an-err)', padding: 20 }}>加载失败: {error}</div>;
  }

  return (
    <>
      <div className="an-drawer-body">
        <div className="an-emp-detail">
          <div className="an-emp-detail-head">
            <button
              type="button"
              className="an-btn ghost"
              onClick={onExit}
              title="返回列表"
            >
              <Icon name="chev-left" size={14} />
              返回
            </button>
            <div className="an-emp-avatar">
              {detail.initials || detail.name.slice(0, 2)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--an-ink)' }}>
                {detail.name}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--an-ink-4)',
                  fontFamily: 'var(--an-font-mono)',
                  marginTop: 4,
                }}
              >
                {detail.employee_id} · v{detail.version} · {detail.status}
              </div>
            </div>
          </div>

          <div className="an-emp-detail-stats">
            <div className="stat-card">
              <div className="label">SKILLS</div>
              <div className="value">{detail.tools.length}</div>
            </div>
            <div className="stat-card">
              <div className="label">APIS</div>
              <div className="value">{detail.endpoints.length || '—'}</div>
            </div>
            <div className="stat-card">
              <div className="label">FAQS</div>
              <div className="value">{detail.faqs.length}</div>
            </div>
            <div className="stat-card">
              <div className="label">VERSIONS</div>
              <div className="value">{versions.length}</div>
            </div>
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label">描述</div>
            <div style={{ fontSize: 13, color: 'var(--an-ink-2)', lineHeight: 1.6 }}>
              {detail.description || '（暂无描述）'}
            </div>
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label">业务领域</div>
            <div className="an-emp-chips">
              {detail.domains.length === 0 && (
                <span style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>（未指定）</span>
              )}
              {detail.domains.map((d) => (
                <span key={d} className="an-emp-chip">{d}</span>
              ))}
            </div>
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label">API 端点（空 = 按领域自动推导）</div>
            {detail.endpoints.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--an-ink-4)', fontFamily: 'var(--an-font-mono)' }}>
                自动推导（{detail.domains.join(' + ')}）
              </div>
            ) : (
              <div className="an-emp-chips">
                {detail.endpoints.map((e) => (
                  <span key={e} className="an-emp-chip an-mono" style={{ fontSize: 10 }}>
                    {e}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="an-emp-section">
            <div className="an-emp-section-label">常见问题（FAQ）</div>
            <div className="an-emp-faq-list">
              {detail.faqs.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--an-ink-4)' }}>暂无 FAQ</div>
              )}
              {detail.faqs.map((f) => (
                <div key={f.id} className="an-emp-faq-row">
                  <div className="an-emp-faq-q">{f.question}</div>
                </div>
              ))}
            </div>
          </div>

          {versions.length > 0 && (
            <div className="an-emp-section">
              <div className="an-emp-section-label">版本历史</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {versions.map((v) => (
                  <div
                    key={v.version}
                    style={{
                      fontSize: 11,
                      fontFamily: 'var(--an-font-mono)',
                      color: 'var(--an-ink-3)',
                      display: 'flex',
                      gap: 12,
                    }}
                  >
                    <span style={{ minWidth: 40 }}>v{v.version}</span>
                    <span style={{ minWidth: 120 }}>{new Date(v.created_at).toLocaleString('zh-CN')}</span>
                    <span style={{ flex: 1, color: 'var(--an-ink-4)' }}>{v.note ?? '—'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="an-drawer-footer">
        <Link
          to={`/admin/employees?selected=${encodeURIComponent(employeeId)}`}
          className="an-btn"
          title="在控制台编辑此员工"
        >
          <Icon name="sliders" size={12} /> 前往控制台编辑
        </Link>
        <button type="button" className="an-btn primary" onClick={onUse}>
          使用该员工
        </button>
      </div>
    </>
  );
}
