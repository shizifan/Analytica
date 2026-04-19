import { useEffect, useCallback } from 'react';
import { useEmployeeStore } from '../stores/employeeStore';
import { api } from '../api/client';
import { EmployeeCard } from '../components/EmployeeCard';
import { EmployeeDetailModal } from '../components/EmployeeDetailModal';
import type { EmployeeUpdatePayload } from '../types';

export function EmployeesPage() {
  const employees = useEmployeeStore((s) => s.employees);
  const loading = useEmployeeStore((s) => s.loading);
  const detail = useEmployeeStore((s) => s.detail);
  const detailLoading = useEmployeeStore((s) => s.detailLoading);
  const fetchEmployees = useEmployeeStore((s) => s.fetchEmployees);
  const fetchDetail = useEmployeeStore((s) => s.fetchDetail);
  const clearDetail = useEmployeeStore((s) => s.clearDetail);
  const updateInList = useEmployeeStore((s) => s.updateInList);

  useEffect(() => {
    if (employees.length === 0) {
      fetchEmployees();
    }
  }, [employees.length, fetchEmployees]);

  const handleViewDetail = useCallback(
    (id: string) => {
      fetchDetail(id);
    },
    [fetchDetail],
  );

  const handleCloseDetail = useCallback(() => {
    clearDetail();
  }, [clearDetail]);

  const handleSave = useCallback(
    async (id: string, payload: EmployeeUpdatePayload) => {
      // Filter out undefined values and send only defined fields
      const body: Record<string, string> = {};
      if (payload.name !== undefined) body.name = payload.name;
      if (payload.description !== undefined) body.description = payload.description;
      const updated = await api.updateEmployee(id, body);
      updateInList({
        employee_id: updated.employee_id,
        name: updated.name,
        description: updated.description,
        domains: updated.domains,
        version: updated.version,
      });
    },
    [updateInList],
  );

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-800">数字员工管理</h2>
          <p className="mt-1 text-sm text-gray-500">
            {employees.length > 0 ? `共 ${employees.length} 个数字员工` : '加载中...'}
          </p>
        </div>
        <button
          onClick={() => fetchEmployees()}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-50"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          刷新
        </button>
      </div>

      {/* Loading skeleton */}
      {loading && employees.length === 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="mb-3 flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-gray-200" />
                <div className="flex-1">
                  <div className="h-4 w-24 rounded bg-gray-200" />
                  <div className="mt-1 h-3 w-16 rounded bg-gray-100" />
                </div>
              </div>
              <div className="mb-3 h-8 w-full rounded bg-gray-100" />
              <div className="flex gap-1.5">
                <div className="h-5 w-16 rounded-full bg-gray-100" />
                <div className="h-5 w-16 rounded-full bg-gray-100" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Employee cards */}
      {!loading && employees.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {employees.map((emp) => (
            <EmployeeCard key={emp.employee_id} employee={emp} onViewDetail={handleViewDetail} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && employees.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-gray-400">
          <svg className="mb-4 h-16 w-16 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
          </svg>
          <p className="text-sm">暂无数字员工配置</p>
          <p className="mt-1 text-xs">请联系管理员添加员工配置</p>
        </div>
      )}

      {/* Detail modal */}
      <EmployeeDetailModal
        detail={detail}
        loading={detailLoading}
        onClose={handleCloseDetail}
        onSave={handleSave}
      />
    </div>
  );
}
