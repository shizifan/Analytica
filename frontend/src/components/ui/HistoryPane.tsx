import { useMemo, useState } from 'react';
import { Icon } from './Icon';

/**
 * Placeholder conversation shape. Phase 2 will replace `items` with data
 * from `GET /api/sessions` once the chat_messages table lands.
 */
export interface ConversationItem {
  id: string;
  title: string;
  employeeTag?: string;
  updatedAt: string; // ISO
}

interface Props {
  items: ConversationItem[];
  activeId: string | null;
  onSelect(id: string): void;
  onNew(): void;
}

function formatGroup(dateIso: string): string {
  const d = new Date(dateIso);
  if (Number.isNaN(d.getTime())) return '其他';
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor(
    (startOfToday.getTime() - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) /
      (24 * 3600 * 1000),
  );
  if (diffDays <= 0) return '今天';
  if (diffDays === 1) return '昨天';
  if (diffDays < 7) return '本周';
  if (diffDays < 30) return '本月';
  return '更早';
}

export function HistoryPane({ items, activeId, onSelect, onNew }: Props) {
  const [query, setQuery] = useState('');

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? items.filter((it) => it.title.toLowerCase().includes(q)) : items;
    const order = ['今天', '昨天', '本周', '本月', '更早', '其他'];
    const byGroup = new Map<string, ConversationItem[]>();
    for (const it of filtered) {
      const g = formatGroup(it.updatedAt);
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g)!.push(it);
    }
    return order
      .filter((g) => byGroup.has(g))
      .map((g) => ({ label: g, items: byGroup.get(g)! }));
  }, [items, query]);

  return (
    <aside className="an-pane an-history-pane">
      <div className="an-pane-header">
        <span className="an-title">对话历史</span>
        <span className="an-actions an-mono" style={{ fontSize: 10 }}>
          {items.length}
        </span>
      </div>

      <button type="button" className="an-new-chat-btn" onClick={onNew}>
        <Icon name="plus" size={12} />
        新建对话
      </button>

      <div className="an-history-search">
        <label className="an-search-box">
          <Icon name="search" size={12} />
          <input
            type="text"
            placeholder="搜索历史..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>

      <div className="an-history-list">
        {grouped.length === 0 ? (
          <div className="an-history-empty">
            暂无历史
            <br />
            <span className="an-mono" style={{ fontSize: 10 }}>
              发送第一条消息后会出现在这里
            </span>
          </div>
        ) : (
          grouped.map((g) => (
            <div key={g.label}>
              <div className="an-history-group-label">{g.label}</div>
              {g.items.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  className={`an-history-item${activeId === it.id ? ' active' : ''}`}
                  onClick={() => onSelect(it.id)}
                >
                  <div className="an-h-title">{it.title || '(未命名会话)'}</div>
                  <div className="an-h-meta">
                    {it.employeeTag && <span>{it.employeeTag}</span>}
                    <span>{new Date(it.updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                </button>
              ))}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
