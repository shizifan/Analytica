import { useEffect, useMemo, useRef, useState } from 'react';
import { AdminListShell } from '../../components/ui/admin/AdminListShell';
import { SkillDetailDrawer } from '../../components/ui/admin/SkillDetailDrawer';
import { api, type AgentSkill } from '../../api/client';

export function SkillsView() {
  const [items, setItems] = useState<AgentSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<AgentSkill | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      const { items } = await api.admin.listAgentSkills();
      setItems(items);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) =>
      it.name.toLowerCase().includes(q) ||
      (it.description ?? '').toLowerCase().includes(q) ||
      (it.tags ?? []).some((t) => t.toLowerCase().includes(q)),
    );
  }, [items, query]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setUploading(true);
    try {
      await api.admin.uploadAgentSkill(file);
      await load();
    } catch (ex) {
      window.alert(`上传失败：${ex instanceof Error ? ex.message : String(ex)}`);
    } finally {
      setUploading(false);
    }
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await api.admin.toggleAgentSkill(id, enabled);
      setItems((arr) =>
        arr.map((it) => (it.skill_id === id ? { ...it, enabled } : it)),
      );
      setSelected((prev) => prev?.skill_id === id ? { ...prev, enabled } : prev);
    } catch (e) {
      window.alert(`切换失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('确认删除此技能？')) return;
    try {
      await api.admin.deleteAgentSkill(id);
      setItems((arr) => arr.filter((it) => it.skill_id !== id));
      if (selected?.skill_id === id) setSelected(null);
    } catch (e) {
      window.alert(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <>
      <AdminListShell
        title="技能"
        count={filtered.length}
        onSearch={setQuery}
        searchPlaceholder="搜索技能名称 / 描述 / 标签..."
        actions={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md"
              style={{ display: 'none' }}
              onChange={handleFileChange}
            />
            <button
              type="button"
              className="an-btn primary"
              style={{ fontSize: 12 }}
              disabled={uploading}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploading ? '上传中…' : '上传 SKILL.md'}
            </button>
          </>
        }
      >
        {loading && <div className="an-admin-empty">加载中…</div>}
        {err && <div className="an-admin-empty"><strong>加载失败</strong>{err}</div>}
        {!loading && !err && filtered.length === 0 && (
          <div className="an-admin-empty">
            暂无技能。点击「上传 SKILL.md」添加 Agent 技能文件。
          </div>
        )}
        {!loading && !err && filtered.length > 0 && (
          <table className="an-admin-table">
            <thead>
              <tr>
                <th>技能名称</th>
                <th>描述</th>
                <th style={{ width: 120 }}>标签</th>
                <th style={{ width: 80 }}>版本</th>
                <th style={{ width: 80 }}>作者</th>
                <th style={{ width: 92 }}>状态</th>
                <th style={{ width: 60 }}></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((it) => (
                <tr
                  key={it.skill_id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelected(it)}
                >
                  <td style={{ fontWeight: 500 }}>{it.name}</td>
                  <td style={{ color: 'var(--an-ink-3)' }}>{it.description ?? '—'}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {(it.tags ?? []).slice(0, 3).map((t) => (
                        <span key={t} className="an-admin-chip">{t}</span>
                      ))}
                    </div>
                  </td>
                  <td className="mono">{it.version ?? '—'}</td>
                  <td style={{ color: 'var(--an-ink-3)' }}>{it.author ?? '—'}</td>
                  <td>
                    <button
                      type="button"
                      className={`an-admin-chip ${it.enabled ? 'ok' : 'err'}`}
                      style={{ cursor: 'pointer', border: 0 }}
                      onClick={(e) => { e.stopPropagation(); handleToggle(it.skill_id, !it.enabled); }}
                      title={`点击 ${it.enabled ? '停用' : '启用'}`}
                    >
                      {it.enabled ? '启用' : '停用'}
                    </button>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="an-btn ghost"
                      style={{ padding: '2px 8px', fontSize: 11, color: 'var(--an-err)' }}
                      onClick={(e) => { e.stopPropagation(); handleDelete(it.skill_id); }}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </AdminListShell>

      {selected && (
        <SkillDetailDrawer
          item={selected}
          onClose={() => setSelected(null)}
          onToggle={handleToggle}
          onDelete={handleDelete}
        />
      )}
    </>
  );
}
