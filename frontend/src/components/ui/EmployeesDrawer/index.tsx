import { useEffect, useState } from 'react';
import { Icon } from '../Icon';
import { EmployeeDetail } from './EmployeeDetail';
import { useEmployeeStore } from '../../../stores/employeeStore';
import type { EmployeeDetail as EmployeeDetailType, EmployeeSummary } from '../../../types';

interface Props {
  open: boolean;
  selectedId: string | null;
  onSelect(id: string | null): void;
  onClose(): void;
}

const DEFAULT_EMPLOYEE_ID = 'asset_investment';

function sortEmployees(list: EmployeeSummary[]): EmployeeSummary[] {
  return [...list].sort((a, b) => {
    if (a.employee_id === DEFAULT_EMPLOYEE_ID) return -1;
    if (b.employee_id === DEFAULT_EMPLOYEE_ID) return 1;
    return 0;
  });
}

/**
 * Phase 4 — Employees drawer.
 *
 * Two modes:
 *   - list: grid of employee cards; clicking one → detail view
 *   - detail: full profile with edit toggle + version history
 *
 * Kept self-contained so it can mount anywhere (ChatPageV2 header chip
 * as of Phase 4.1; future admin console will reuse it).
 */
export function EmployeesDrawer({ open, selectedId, onSelect, onClose }: Props) {
  const employees = useEmployeeStore((s) => s.employees);
  const fetchEmployees = useEmployeeStore((s) => s.fetchEmployees);
  const updateInList = useEmployeeStore((s) => s.updateInList);

  const [viewingId, setViewingId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (open) {
      fetchEmployees();
      setViewingId(null);
      setEditing(false);
    }
  }, [open, fetchEmployees]);

  // Esc closes drawer
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="an-drawer-overlay" onClick={onClose} aria-hidden />
      <aside
        className="an-drawer"
        role="dialog"
        aria-label="数字员工管理"
      >
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            <Icon name="sparkles" size={14} />
            {viewingId ? '员工详情' : '数字员工'}
            <span
              className="an-mono"
              style={{ fontSize: 10, color: 'var(--an-ink-4)', fontWeight: 400 }}
            >
              {viewingId ? viewingId : `${employees.length} 个`}
            </span>
          </div>
          <div className="an-drawer-actions">
            <button
              type="button"
              className="an-icon-btn"
              title="关闭"
              onClick={onClose}
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>

        {viewingId ? (
          <EmployeeDetail
            employeeId={viewingId}
            editing={editing}
            onExit={() => {
              setViewingId(null);
              setEditing(false);
            }}
            onToggleEdit={() => setEditing((v) => !v)}
            onUse={() => {
              onSelect(viewingId);
              onClose();
            }}
            onSaved={(updated: EmployeeDetailType) => {
              updateInList({
                employee_id: updated.employee_id,
                name: updated.name,
                description: updated.description,
                domains: updated.domains,
                version: updated.version,
                initials: updated.initials,
                status: updated.status,
                faqs_count: updated.faqs.length,
                tools_count: updated.tools.length,
                endpoints_count: updated.endpoints.length,
              });
            }}
          />
        ) : (
          <>
            <div className="an-drawer-body">
              <div className="an-emp-grid">
                {sortEmployees(employees).map((e: EmployeeSummary) => (
                  <button
                    key={e.employee_id}
                    type="button"
                    className={`an-emp-card${e.employee_id === selectedId ? ' active' : ''}${
                      e.status === 'draft' ? ' draft' : ''
                    }${e.status === 'archived' ? ' archived' : ''}`}
                    onClick={() => setViewingId(e.employee_id)}
                  >
                    <div className="an-emp-head">
                      <div className="an-emp-avatar">
                        {e.initials || e.name.slice(0, 2)}
                      </div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div className="an-emp-name">{e.name}</div>
                        <div className="an-emp-ver">
                          v{e.version}
                          {e.status && e.status !== 'active' ? ` · ${e.status}` : ''}
                        </div>
                      </div>
                    </div>
                    <div className="an-emp-desc">{e.description || '（暂无描述）'}</div>
                    <div className="an-emp-stats">
                      {(e.domains ?? []).map((d) => (
                        <span key={d} className="stat">{d}</span>
                      ))}
                      <span className="stat">Tools {e.tools_count ?? '—'}</span>
                      <span className="stat">FAQs {e.faqs_count ?? '—'}</span>
                    </div>
                  </button>
                ))}

                <button
                  type="button"
                  className={`an-emp-card${selectedId === null ? ' active' : ''}`}
                  onClick={() => {
                    onSelect(null);
                    onClose();
                  }}
                >
                  <div className="an-emp-head">
                    <div className="an-emp-avatar" style={{ background: 'var(--an-bg-sunken)', color: 'var(--an-ink-3)', borderColor: 'var(--an-border)' }}>
                      ANY
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div className="an-emp-name">通用模式</div>
                      <div className="an-emp-ver">无员工限制</div>
                    </div>
                  </div>
                  <div className="an-emp-desc">
                    不绑定具体数字员工，使用全域 API 与技能。
                  </div>
                </button>
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
