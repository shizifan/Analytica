import type { ReactNode } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Icon } from '../Icon';

const NAV: Array<{
  to: string;
  label: string;
  icon: Parameters<typeof Icon>[0]['name'];
}> = [
  { to: '/admin/employees', label: '数字员工', icon: 'users' },
  { to: '/admin/apis', label: 'API 端点', icon: 'terminal' },
  { to: '/admin/tools', label: '工具', icon: 'bolt' },
  { to: '/admin/skills', label: '技能', icon: 'layers' },
  { to: '/admin/domains', label: '业务域', icon: 'database' },
  { to: '/admin/memories', label: '记忆 / 偏好', icon: 'clipboard' },
  { to: '/admin/audit', label: '审计日志', icon: 'clipboard' },
];

const ROUTE_TITLES: Record<string, string> = {
  '/admin': '控制台',
  '/admin/employees': '数字员工',
  '/admin/apis': 'API 端点',
  '/admin/tools': '工具',
  '/admin/skills': '技能',
  '/admin/domains': '业务域',
  '/admin/memories': '记忆 / 偏好',
  '/admin/audit': '审计日志',
};

interface Props {
  actions?: ReactNode;
}

export function AdminLayout({ actions }: Props) {
  const location = useLocation();
  const title = ROUTE_TITLES[location.pathname] ?? '控制台';

  return (
    <div className="an-app">
      <header className="an-topbar">
        <div className="an-brand">
          <span className="an-mark">A</span>
          Analytica
          <span className="an-brand-sub">/ 控制台 · {title}</span>
        </div>
        <div className="an-meta">
          {actions}
          <Link
            to="/"
            className="an-console-btn"
            title="返回工作台"
          >
            <Icon name="arrow-left" size={12} />
            <span>返回工作台</span>
          </Link>
        </div>
      </header>

      <div className="an-admin-body">
        <aside className="an-admin-nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `an-admin-nav-item${isActive ? ' active' : ''}`
              }
            >
              <Icon name={item.icon} size={14} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </aside>

        <main className="an-admin-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
