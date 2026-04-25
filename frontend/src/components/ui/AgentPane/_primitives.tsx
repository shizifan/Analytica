/**
 * Shared rendering primitives for AgentPane tabs (Status / Thinking / Trace).
 *
 * Replace verbose `JSON.stringify(...)` fallbacks with type-aware renderers:
 *   - <SmartValue>      — picks the best renderer for any value
 *   - <TimeRange>       — pretty-print {start, end, description?}
 *   - <SourceTag>       — Chinese source labels with colour coding
 *   - <SmartJSON>       — collapsible per-key view, no pretty-printed JSON dump
 *   - <CollapsibleSection> — generic open/close container
 */
import { useState, useMemo, type ReactNode } from 'react';

// ── Types ───────────────────────────────────────────────────────

type Primitive = string | number | boolean | null | undefined;

interface TimeRangeValue {
  start?: string;
  end?: string;
  description?: string;
  [k: string]: unknown;
}

// ── Detection helpers ───────────────────────────────────────────

function isPrimitive(v: unknown): v is Primitive {
  return v === null || v === undefined ||
    typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean';
}

function looksLikeTimeRange(v: unknown): v is TimeRangeValue {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return false;
  const o = v as Record<string, unknown>;
  return typeof o.start === 'string' || typeof o.end === 'string';
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.length > 0 && v.every((x) => typeof x === 'string');
}

function isPrimitiveArray(v: unknown): v is Primitive[] {
  return Array.isArray(v) && v.every(isPrimitive);
}

// ── TimeRange ───────────────────────────────────────────────────

function shorten(date: string): string {
  // 2026-01-01 → 2026-01-01; 2026-01 → 2026-01; full ISO → YYYY-MM-DD
  if (!date) return date;
  return date.slice(0, 10);
}

export function TimeRange({ value }: { value: TimeRangeValue }) {
  const start = value.start ? shorten(value.start) : '';
  const end = value.end ? shorten(value.end) : '';
  const desc = value.description;

  let main: string;
  if (start && end) {
    if (start === end) main = start;
    else main = `${start} → ${end}`;
  } else {
    main = start || end || '—';
  }

  return (
    <span className="an-prim-time" title={JSON.stringify(value)}>
      <span className="an-prim-time-main">{main}</span>
      {desc && <span className="an-prim-time-desc">{desc}</span>}
    </span>
  );
}

// ── SourceTag ───────────────────────────────────────────────────

const SOURCE_META: Record<string, { label: string; cls: string }> = {
  user_input:            { label: '用户', cls: 'src-user' },
  memory:                { label: '记忆', cls: 'src-memory' },
  memory_low_confidence: { label: '记忆?', cls: 'src-memory-low' },
  inferred:              { label: '推断', cls: 'src-inferred' },
  default:               { label: '默认', cls: 'src-default' },
  history:               { label: '历史', cls: 'src-history' },
};

export function SourceTag({ source }: { source: string }) {
  const meta = SOURCE_META[source] ?? { label: source, cls: 'src-default' };
  return (
    <span className={`an-prim-srctag ${meta.cls}`} title={`来源：${meta.label} (${source})`}>
      {meta.label}
    </span>
  );
}

// ── SmartValue ──────────────────────────────────────────────────

interface SmartValueProps {
  value: unknown;
  /** When > 0, long strings are clipped; clicking expands. */
  maxStringLen?: number;
}

const STRING_INLINE_LIMIT = 60;
const STRING_LONG_LIMIT = 500;

export function SmartValue({ value, maxStringLen = STRING_INLINE_LIMIT }: SmartValueProps) {
  // null / undefined / ""
  if (value === null || value === undefined || value === '') {
    return <span className="an-prim-val v-empty">—</span>;
  }

  // boolean / number
  if (typeof value === 'boolean') {
    return <span className="an-prim-val v-bool">{value ? '是' : '否'}</span>;
  }
  if (typeof value === 'number') {
    return <span className="an-prim-val v-num">{value}</span>;
  }

  // string
  if (typeof value === 'string') {
    return <SmartString value={value} maxLen={maxStringLen} />;
  }

  // primitive array → chip list
  if (isStringArray(value) || isPrimitiveArray(value)) {
    return (
      <span className="an-prim-chips">
        {(value as Primitive[]).map((v, i) => (
          <span key={i} className="an-prim-chip">{String(v)}</span>
        ))}
      </span>
    );
  }

  // time-range-shaped object
  if (looksLikeTimeRange(value)) {
    return <TimeRange value={value} />;
  }

  // array of objects → collapsible
  if (Array.isArray(value)) {
    return <SmartJSON data={{ items: value } as Record<string, unknown>} initialOpen={false} />;
  }

  // generic object → SmartJSON
  return <SmartJSON data={value as Record<string, unknown>} initialOpen={false} />;
}

function SmartString({ value, maxLen }: { value: string; maxLen: number }) {
  const [open, setOpen] = useState(false);
  if (value.length <= maxLen) {
    return <span className="an-prim-val v-str">{value}</span>;
  }
  if (value.length > STRING_LONG_LIMIT) {
    return (
      <span className="an-prim-val v-str-long">
        <button
          type="button"
          className="an-prim-toggle"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? '▾' : '▸'} [文本 {value.length} 字符]
        </button>
        {open && <pre className="an-prim-pre">{value}</pre>}
      </span>
    );
  }
  // medium length — clip with tooltip
  return (
    <span
      className="an-prim-val v-str"
      title={value}
    >
      {value.slice(0, maxLen)}…
    </span>
  );
}

// ── SmartJSON ───────────────────────────────────────────────────

interface SmartJSONProps {
  data: Record<string, unknown> | unknown[];
  initialOpen?: boolean;
  /** Top-level header label, optional. */
  label?: string;
}

function summarize(v: unknown): string {
  if (v === null) return 'null';
  if (v === undefined) return '—';
  if (typeof v === 'string') {
    if (v.length <= 30) return JSON.stringify(v);
    return `"${v.slice(0, 30)}…" (${v.length})`;
  }
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) {
    if (v.length === 0) return '[]';
    return `[${v.length} 项]`;
  }
  if (typeof v === 'object') {
    const keys = Object.keys(v as Record<string, unknown>);
    if (keys.length === 0) return '{}';
    return `{${keys.length} 字段}`;
  }
  return String(v);
}

export function SmartJSON({ data, initialOpen = false, label }: SmartJSONProps) {
  const [allOpen, setAllOpen] = useState(initialOpen);
  const entries = useMemo(() => {
    if (Array.isArray(data)) {
      return data.map((v, i) => [String(i), v] as [string, unknown]);
    }
    return Object.entries(data);
  }, [data]);

  const handleCopy = () => {
    try {
      navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    } catch { /* noop */ }
  };

  return (
    <div className="an-prim-json">
      {label && (
        <div className="an-prim-json-label">
          {label}
          <button type="button" className="an-prim-json-action" onClick={() => setAllOpen((x) => !x)}>
            {allOpen ? '全部折叠' : '全部展开'}
          </button>
          <button type="button" className="an-prim-json-action" onClick={handleCopy}>
            复制 JSON
          </button>
        </div>
      )}
      <ul className="an-prim-json-list">
        {entries.map(([k, v]) => (
          <SmartJSONRow key={k} k={k} v={v} forceOpen={allOpen} />
        ))}
      </ul>
      {!label && (
        <div className="an-prim-json-footer">
          <button type="button" className="an-prim-json-action" onClick={handleCopy}>
            复制 JSON
          </button>
        </div>
      )}
    </div>
  );
}

function SmartJSONRow({
  k,
  v,
  forceOpen,
}: {
  k: string;
  v: unknown;
  forceOpen: boolean;
}) {
  const [open, setOpen] = useState(forceOpen);
  const expandable = (Array.isArray(v) && v.length > 0) ||
    (v !== null && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length > 0);
  const isOpen = forceOpen || open;
  const summaryText = summarize(v);

  return (
    <li className={`an-prim-json-row${isOpen && expandable ? ' is-open' : ''}`}>
      <div className="an-prim-json-line">
        {expandable ? (
          <button
            type="button"
            className="an-prim-json-toggle"
            onClick={() => setOpen((o) => !o)}
          >
            {isOpen ? '▾' : '▸'}
          </button>
        ) : (
          <span className="an-prim-json-toggle-spacer" />
        )}
        <span className="an-prim-json-key">{k}</span>
        <span className="an-prim-json-sep">:</span>
        {!isOpen || !expandable ? (
          <span className="an-prim-json-summary">{summaryText}</span>
        ) : null}
      </div>
      {isOpen && expandable && (
        <div className="an-prim-json-children">
          {Array.isArray(v) || (typeof v === 'object' && v !== null) ? (
            <SmartJSON
              data={v as Record<string, unknown> | unknown[]}
              initialOpen={false}
            />
          ) : null}
        </div>
      )}
    </li>
  );
}

// ── CollapsibleSection ──────────────────────────────────────────

export function CollapsibleSection({
  summary,
  children,
  defaultOpen = false,
  /** Optional storage key — when set, open/close state persists in localStorage. */
  storageKey,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  storageKey?: string;
}) {
  const [open, setOpenRaw] = useState(() => {
    if (storageKey && typeof window !== 'undefined') {
      const v = window.localStorage.getItem(`an-coll:${storageKey}`);
      if (v === '1') return true;
      if (v === '0') return false;
    }
    return defaultOpen;
  });

  const setOpen = (next: boolean) => {
    setOpenRaw(next);
    if (storageKey && typeof window !== 'undefined') {
      window.localStorage.setItem(`an-coll:${storageKey}`, next ? '1' : '0');
    }
  };

  return (
    <div className={`an-prim-coll${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="an-prim-coll-head"
        onClick={() => setOpen(!open)}
      >
        <span className="an-prim-coll-chev">{open ? '▾' : '▸'}</span>
        {summary}
      </button>
      {open && <div className="an-prim-coll-body">{children}</div>}
    </div>
  );
}
