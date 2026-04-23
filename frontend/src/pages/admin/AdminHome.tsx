import { Link } from 'react-router-dom';
import { Icon } from '../../components/ui/Icon';

const MODULES: Array<{
  to: string;
  label: string;
  description: string;
  icon: Parameters<typeof Icon>[0]['name'];
}> = [
  {
    to: '/admin/employees',
    label: '数字员工',
    description: '管理数字员工画像、领域、绑定的 API 与工具',
    icon: 'users',
  },
  {
    to: '/admin/apis',
    label: 'API 端点',
    description: '管理后端 API 注册表、调用统计与错误率',
    icon: 'terminal',
  },
  {
    to: '/admin/tools',
    label: '工具',
    description: '查看 Python 工具元数据、运行统计与最近错误',
    icon: 'bolt',
  },
  {
    to: '/admin/skills',
    label: '技能',
    description: '上传和管理 SKILL.md 工作流技能，注入规划层 Prompt',
    icon: 'layers',
  },
  {
    to: '/admin/domains',
    label: '业务域',
    description: '维护业务域 D1–D7 的元数据',
    icon: 'database',
  },
  {
    to: '/admin/memories',
    label: '记忆 / 偏好',
    description: '用户偏好、分析模板、工具反馈一站查看',
    icon: 'clipboard',
  },
  {
    to: '/admin/audit',
    label: '审计日志',
    description: '管理操作与 Agent 关键动作的审计流水',
    icon: 'clipboard',
  },
];

export function AdminHome() {
  return (
    <div className="an-admin-page">
      <div className="an-admin-head">
        <div className="an-admin-head-left">
          <h2 className="an-admin-title">控制台</h2>
          <span className="an-admin-count an-mono">7 模块</span>
        </div>
      </div>
      <div className="an-admin-body-inner">
        <div className="an-admin-home-grid">
          {MODULES.map((m) => (
            <Link key={m.to} to={m.to} className="an-admin-home-card">
              <div className="an-admin-home-icon">
                <Icon name={m.icon} size={18} />
              </div>
              <div className="an-admin-home-body">
                <div className="an-admin-home-title">{m.label}</div>
                <div className="an-admin-home-desc">{m.description}</div>
              </div>
              <Icon name="chev-right" size={14} />
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
