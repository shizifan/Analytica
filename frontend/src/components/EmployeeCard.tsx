import type { EmployeeSummary } from '../types';

interface Props {
  employee: EmployeeSummary;
  onViewDetail: (id: string) => void;
}

const DOMAIN_LABELS: Record<string, string> = {
  D1: '生产运营',
  D2: '市场商务',
  D3: '战略客户',
  D4: '公司治理',
  D5: '资产管理',
  D6: '投资项目',
  D7: '设备运营',
};

export function EmployeeCard({ employee, onViewDetail }: Props) {
  const initials = employee.name.slice(0, 2);

  return (
    <div className="flex flex-col rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      {/* Header: Avatar + Name + Version */}
      <div className="mb-3 flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-sm font-bold text-white">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-gray-800">{employee.name}</h3>
          <span className="text-xs text-gray-400">v{employee.version}</span>
        </div>
      </div>

      {/* Description */}
      <p className="mb-3 line-clamp-2 text-sm text-gray-500">{employee.description}</p>

      {/* Domains */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {employee.domains.map((d) => (
          <span
            key={d}
            className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600"
          >
            {d} {DOMAIN_LABELS[d] || ''}
          </span>
        ))}
      </div>

      {/* Actions */}
      <div className="mt-auto">
        <button
          type="button"
          onClick={() => onViewDetail(employee.employee_id)}
          className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          查看详情
        </button>
      </div>
    </div>
  );
}
