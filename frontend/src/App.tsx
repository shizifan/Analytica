import { Routes, Route, Navigate } from 'react-router-dom';
import { ChatPageV2 } from './pages/ChatPageV2';
import { EmployeesPage } from './pages/EmployeesPage';
import { AdminLayout } from './components/ui/admin/AdminLayout';
import { AdminHome } from './pages/admin/AdminHome';
import { EmployeesView } from './pages/admin/EmployeesView';
import { ApisView } from './pages/admin/ApisView';
import { ToolsView } from './pages/admin/ToolsView';
import { SkillsView } from './pages/admin/SkillsView';
import { DomainsView } from './pages/admin/DomainsView';
import { MemoriesView } from './pages/admin/MemoriesView';
import { AuditView } from './pages/admin/AuditView';

function App() {
  return (
    <Routes>
      <Route index element={<ChatPageV2 />} />
      <Route path="employees" element={<EmployeesPage />} />
      <Route path="admin" element={<AdminLayout />}>
        <Route index element={<AdminHome />} />
        <Route path="employees" element={<EmployeesView />} />
        <Route path="apis" element={<ApisView />} />
        <Route path="tools" element={<ToolsView />} />
        <Route path="skills" element={<SkillsView />} />
        <Route path="domains" element={<DomainsView />} />
        <Route path="memories" element={<MemoriesView />} />
        <Route path="audit" element={<AuditView />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
