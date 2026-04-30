import { useEffect, useState } from 'react';
import { Icon } from '../Icon';
import { EmployeeDetail } from './EmployeeDetail';
import { useEmployeeStore } from '../../../stores/employeeStore';
import { DEFAULT_EMPLOYEE_ID } from '../../../config/app';
import type { EmployeeSummary } from '../../../types';

interface Props {
  open: boolean;
  selectedId: string | null;
  onSelect(id: string | null): void;
  onClose(): void;
}

function sortEmployees(list: EmployeeSummary[]): EmployeeSummary[] {
  return [...list].sort((a, b) => {
    if (a.employee_id === DEFAULT_EMPLOYEE_ID) return -1;
    if (b.employee_id === DEFAULT_EMPLOYEE_ID) return 1;
    return 0;
  });
}

/**
 * Employees drawer (chat workspace).
 *
 * Two modes:
 *   - list: one-row-per-employee list; clicking a row switches employee
 *     directly. A small "详情" button on each row opens the detail view.
 *   - detail: read-only profile + version history. Edit happens in
 *     /admin/employees only (link in the detail footer).
 */
export function EmployeesDrawer({ open, selectedId, onSelect, onClose }: Props) {
  const employees = useEmployeeStore((s) => s.employees);
  const fetchEmployees = useEmployeeStore((s) => s.fetchEmployees);

  const [viewingId, setViewingId] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      fetchEmployees();
      setViewingId(null);
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
            onExit={() => setViewingId(null)}
            onUse={() => {
              onSelect(viewingId);
              onClose();
            }}
          />
        ) : (
          <>
            <div className="an-drawer-body">
              <div className="an-emp-list">
                {sortEmployees(employees).map((e: EmployeeSummary) => (
                  <div
                    key={e.employee_id}
                    role="button"
                    tabIndex={0}
                    className={`an-emp-row${e.employee_id === selectedId ? ' active' : ''}${
                      e.status === 'draft' ? ' draft' : ''
                    }${e.status === 'archived' ? ' archived' : ''}`}
                    onClick={() => {
                      onSelect(e.employee_id);
                      onClose();
                    }}
                    onKeyDown={(ev) => {
                      if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.preventDefault();
                        onSelect(e.employee_id);
                        onClose();
                      }
                    }}
                  >
                    <div className="an-emp-row-id">
                      <div className="an-emp-avatar">
                        {e.initials || e.name.slice(0, 2)}
                      </div>
                      <div className="an-emp-row-id-text">
                        <div className="an-emp-name">{e.name}</div>
                        <div className="an-emp-ver">
                          v{e.version}
                          {e.status && e.status !== 'active' ? ` · ${e.status}` : ''}
                        </div>
                      </div>
                    </div>
                    <div className="an-emp-row-desc">
                      {e.description || '（暂无描述）'}
                    </div>
                    <div className="an-emp-row-stats">
                      {(e.domains ?? []).map((d) => (
                        <span key={d} className="stat">{d}</span>
                      ))}
                      <span className="stat">Tools {e.tools_count ?? '—'}</span>
                      <span className="stat">FAQs {e.faqs_count ?? '—'}</span>
                    </div>
                    <button
                      type="button"
                      className="an-emp-row-info"
                      title="查看详情"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        setViewingId(e.employee_id);
                      }}
                    >
                      详情
                    </button>
                  </div>
                ))}

                <div
                  role="button"
                  tabIndex={0}
                  className={`an-emp-row${selectedId === null ? ' active' : ''}`}
                  onClick={() => {
                    onSelect(null);
                    onClose();
                  }}
                  onKeyDown={(ev) => {
                    if (ev.key === 'Enter' || ev.key === ' ') {
                      ev.preventDefault();
                      onSelect(null);
                      onClose();
                    }
                  }}
                >
                  <div className="an-emp-row-id">
                    <div
                      className="an-emp-avatar"
                      style={{
                        background: 'var(--an-bg-sunken)',
                        color: 'var(--an-ink-3)',
                        borderColor: 'var(--an-border)',
                      }}
                    >
                      ANY
                    </div>
                    <div className="an-emp-row-id-text">
                      <div className="an-emp-name">通用模式</div>
                      <div className="an-emp-ver">无员工限制</div>
                    </div>
                  </div>
                  <div className="an-emp-row-desc">
                    不绑定具体数字员工，使用全域 API 与技能。
                  </div>
                  <div className="an-emp-row-stats" />
                </div>
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
