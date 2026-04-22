import { NavLink, Routes, Route, Navigate } from 'react-router-dom';
import { useSessionStore } from './stores/sessionStore';
import { useWsStore } from './stores/wsStore';
import { ChatPage } from './pages/ChatPage';
import { ChatPageV2 } from './pages/ChatPageV2';
import { EmployeesPage } from './pages/EmployeesPage';
import { AdminLayout } from './components/ui/admin/AdminLayout';
import { AdminHome } from './pages/admin/AdminHome';
import { AdminPlaceholder } from './pages/admin/AdminPlaceholder';
import { ApisView } from './pages/admin/ApisView';
import { SkillsView } from './pages/admin/SkillsView';
import { DomainsView } from './pages/admin/DomainsView';
import { MemoriesView } from './pages/admin/MemoriesView';
import { AuditView } from './pages/admin/AuditView';
import { isNewUIEnabled } from './lib/featureFlags';

function App() {
  const phase = useSessionStore((s) => s.phase);
  const wsStatus = useWsStore((s) => s.status);
  const reconnectCount = useWsStore((s) => s.reconnectCount);

  const phaseLabel: Record<string, string> = {
    idle: '等待输入',
    perception: '感知中',
    planning: '规划中',
    executing: '执行中',
    reflection: '反思中',
    done: '已完成',
  };

  // ChatPageV2 renders its own shell (Topbar + Workbench). The legacy header
  // and banner below are only for the v1 routes.
  const newUI = isNewUIEnabled();

  if (newUI) {
    return (
      <Routes>
        <Route index element={<ChatPageV2 />} />
        <Route path="employees" element={<EmployeesPage />} />
        <Route path="admin" element={<AdminLayout />}>
          <Route index element={<AdminHome />} />
          <Route
            path="employees"
            element={
              <AdminPlaceholder
                title="数字员工"
                hint="点击主工作台的「员工」chip 可打开同一个详情/编辑抽屉。"
              />
            }
          />
          <Route path="apis" element={<ApisView />} />
          <Route path="skills" element={<SkillsView />} />
          <Route path="domains" element={<DomainsView />} />
          <Route path="memories" element={<MemoriesView />} />
          <Route path="audit" element={<AuditView />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50 text-gray-800">
      {/* ===== Header ===== */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
        <div className="flex items-center gap-6">
          <h1 className="text-sm font-bold text-gray-800">Analytica</h1>
          <nav className="flex gap-1">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `rounded px-3 py-1 text-sm transition-colors ${
                  isActive
                    ? 'bg-blue-50 font-medium text-blue-700'
                    : 'text-gray-500 hover:text-gray-700'
                }`
              }
            >
              智能问答
            </NavLink>
            <NavLink
              to="/employees"
              className={({ isActive }) =>
                `rounded px-3 py-1 text-sm transition-colors ${
                  isActive
                    ? 'bg-blue-50 font-medium text-blue-700'
                    : 'text-gray-500 hover:text-gray-700'
                }`
              }
            >
              数字员工
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className={`rounded px-2 py-0.5 ${
            phase === 'executing' ? 'bg-blue-100 text-blue-700'
            : phase === 'reflection' ? 'bg-purple-100 text-purple-700'
            : phase === 'done' ? 'bg-green-100 text-green-700'
            : 'bg-gray-100 text-gray-600'
          }`}>
            {phaseLabel[phase] ?? phase}
          </span>
          <span className={`h-2 w-2 rounded-full ${
            wsStatus === 'connected' ? 'bg-green-500'
            : wsStatus === 'connecting' ? 'animate-pulse bg-yellow-400'
            : 'bg-red-500'
          }`} title={`WebSocket: ${wsStatus}`} />
        </div>
      </header>

      {/* ===== WS disconnection banner ===== */}
      {wsStatus === 'disconnected' && (
        <div className="flex items-center justify-center gap-2 bg-red-500 px-3 py-1 text-xs text-white">
          连接已断开，正在重连... (第 {reconnectCount} 次)
        </div>
      )}
      {wsStatus === 'failed' && (
        <div className="flex items-center justify-center gap-2 bg-red-600 px-3 py-1 text-xs text-white">
          连接失败，已达最大重试次数
          <button
            onClick={() => {
              useWsStore.getState().setStatus('connecting');
              useWsStore.getState().setConnected(false);
            }}
            className="rounded bg-white/20 px-2 py-0.5 hover:bg-white/30"
          >
            手动重连
          </button>
        </div>
      )}

      {/* ===== Routes ===== */}
      <Routes>
        <Route index element={<ChatPage />} />
        <Route path="employees" element={<EmployeesPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

export default App;
