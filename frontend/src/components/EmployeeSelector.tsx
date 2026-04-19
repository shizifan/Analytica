import { useState, useRef, useEffect } from 'react';
import type { EmployeeSummary } from '../types';

interface Props {
  employees: EmployeeSummary[];
  selectedId: string | null;
  onChange: (id: string | null) => void;
  disabled?: boolean;
}

export function EmployeeSelector({ employees, selectedId, onChange, disabled = false }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selected = employees.find((e) => e.employee_id === selectedId);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen(!open)}
        className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <svg className="h-4 w-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
        <span className={selected ? 'font-medium' : ''}>
          {selected ? selected.name : '通用模式'}
        </span>
        <svg className="h-4 w-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-lg border border-gray-200 bg-white shadow-lg">
          <div className="p-1">
            {/* Universal mode option */}
            <button
              type="button"
              onClick={() => { onChange(null); setOpen(false); }}
              className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                selectedId === null
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-700 hover:bg-gray-50'
              }`}
            >
              <div className="font-medium">通用模式</div>
              <div className="text-xs text-gray-400">不限定数字员工</div>
            </button>

            <div className="my-1 border-t border-gray-100" />

            {employees.map((emp) => (
              <button
                key={emp.employee_id}
                type="button"
                onClick={() => { onChange(emp.employee_id); setOpen(false); }}
                className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                  selectedId === emp.employee_id
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-700 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{emp.name}</span>
                  <span className="text-xs text-gray-400">v{emp.version}</span>
                </div>
                <div className="mt-0.5 line-clamp-1 text-xs text-gray-400">
                  {emp.description}
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {emp.domains.map((d) => (
                    <span key={d} className="rounded-full bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">
                      {d}
                    </span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
