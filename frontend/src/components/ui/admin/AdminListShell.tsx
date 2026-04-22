import type { ReactNode } from 'react';
import { Icon } from '../Icon';

interface Props {
  title: string;
  count?: number | string;
  onSearch?: (query: string) => void;
  searchPlaceholder?: string;
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Phase 6 — shared list-page shell: title + count + search + action
 * button. Pages that need filters beyond simple text search can pass
 * extra UI via `actions`.
 */
export function AdminListShell({
  title,
  count,
  onSearch,
  searchPlaceholder = '搜索...',
  actions,
  children,
}: Props) {
  return (
    <div className="an-admin-page">
      <div className="an-admin-head">
        <div className="an-admin-head-left">
          <h2 className="an-admin-title">{title}</h2>
          {count !== undefined && (
            <span className="an-admin-count an-mono">{count}</span>
          )}
        </div>
        <div className="an-admin-head-right">
          {onSearch && (
            <label className="an-search-box" style={{ width: 220 }}>
              <Icon name="search" size={12} />
              <input
                type="text"
                placeholder={searchPlaceholder}
                onChange={(e) => onSearch(e.target.value)}
              />
            </label>
          )}
          {actions}
        </div>
      </div>
      <div className="an-admin-body-inner">{children}</div>
    </div>
  );
}
