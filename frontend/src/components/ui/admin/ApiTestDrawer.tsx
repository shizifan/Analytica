import { useEffect, useRef, useState } from 'react';
import { api, type AdminApi } from '../../../api/client';

// 常用参数默认值（覆盖注册表中出现频率最高的参数名）
const PARAM_DEFAULTS: Record<string, string> = {
  // 年度
  dateYear: '2025',
  currYear: '2025',
  curDateYear: '2025',
  preYear: '2024',
  yearDateYear: '2024',
  // 年月 yyyy-MM
  dateMonth: '2025-01',
  curDateMonth: '2025-01',
  yearDateMonth: '2024-01',
  preDateMonth: '2024-01',
  date: '2025-01',
  curDate: '2025-01',
  yearDate: '2024-01',
  momDate: '2025-01',
  yoyDate: '2025-01',
  // 区间
  startDate: '2025-01',
  endDate: '2025-03',
  startMonth: '2025-01',
  endMonth: '2025-03',
  yoyStartDate: '2024-01',
  yoyEndDate: '2025-01',
  momStartDate: '2024-12',
  momEndDate: '2025-01',
  // 分页
  pageNo: '1',
  pageSize: '20',
  topN: '10',
  // 其他常见枚举
  shipStatus: 'D',
};

function getDefault(param: string): string {
  return PARAM_DEFAULTS[param] ?? '';
}

type Mode = 'mock' | 'prod';

interface TestResponse {
  status_code: number;
  duration_ms: number;
  url: string;
  mode: string;
  data: unknown;
}

interface Props {
  item: AdminApi;
  onClose: () => void;
}

export function ApiTestDrawer({ item, onClose }: Props) {
  const allParams = [
    ...item.required_params.map((p) => ({ name: p, required: true })),
    ...item.optional_params.map((p) => ({ name: p, required: false })),
  ];

  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(allParams.map(({ name }) => [name, getDefault(name)])),
  );
  const [mode, setMode] = useState<Mode>('mock');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<TestResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSend = async () => {
    setLoading(true);
    setErr(null);
    setResponse(null);
    const params: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) {
      if (v.trim() !== '') params[k] = v.trim();
    }
    try {
      const res = await api.admin.testApi(item.name, params, mode);
      setResponse(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const statusColor = (code: number) => {
    if (code >= 200 && code < 300) return 'var(--an-ok)';
    if (code >= 400) return 'var(--an-err)';
    return 'var(--an-warn)';
  };

  return (
    <>
      <div
        className="an-drawer-overlay"
        ref={overlayRef}
        onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
      />
      <div className="an-drawer" style={{ width: 'min(680px, 100vw)' }}>
        {/* 标题栏 */}
        <div className="an-drawer-head">
          <div className="an-drawer-title">
            <span className={`an-admin-chip method ${item.method.toLowerCase()}`}>
              {item.method}
            </span>
            <span>{item.name}</span>
            <span style={{ fontFamily: 'var(--an-font-mono)', fontWeight: 400, fontSize: 11, color: 'var(--an-ink-4)' }}>
              {item.path}
            </span>
          </div>
          <div className="an-drawer-actions">
            <button type="button" className="an-btn ghost" onClick={onClose}
              style={{ padding: '3px 8px', fontSize: 12 }}>关闭</button>
          </div>
        </div>

        {/* 正文 */}
        <div className="an-drawer-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* 语义描述 */}
          {item.intent && (
            <p style={{ margin: 0, fontSize: 12, color: 'var(--an-ink-3)', lineHeight: 1.6 }}>
              {item.intent}
            </p>
          )}

          {/* 接口模式切换 */}
          <section>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
              接口环境
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {(['mock', 'prod'] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => { setMode(m); setResponse(null); setErr(null); }}
                  style={{
                    padding: '4px 14px',
                    fontSize: 12,
                    borderRadius: 'var(--an-radius-sm)',
                    border: `1px solid ${mode === m ? 'var(--an-accent)' : 'var(--an-border)'}`,
                    background: mode === m ? 'var(--an-accent-bg)' : 'var(--an-bg-raised)',
                    color: mode === m ? 'var(--an-accent-ink)' : 'var(--an-ink-3)',
                    cursor: 'pointer',
                    fontWeight: mode === m ? 600 : 400,
                    transition: 'all 0.12s',
                  }}
                >
                  {m === 'mock' ? 'Mock' : '生产'}
                </button>
              ))}
              <span style={{ fontSize: 11, color: 'var(--an-ink-4)', alignSelf: 'center', marginLeft: 4 }}>
                {mode === 'mock' ? '使用 Mock Server 数据' : '使用真实生产接口'}
              </span>
            </div>
          </section>

          {/* 参数 */}
          <section>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
              参数
            </div>
            {allParams.length === 0 ? (
              <p style={{ fontSize: 12, color: 'var(--an-ink-4)', margin: 0 }}>此 API 无需参数</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {allParams.map(({ name, required }) => (
                  <div key={name} style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: 10, alignItems: 'center' }}>
                    <label style={{
                      fontSize: 12,
                      color: required ? 'var(--an-ink-2)' : 'var(--an-ink-4)',
                      fontFamily: 'var(--an-font-mono)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                    }}>
                      {name}
                      {required && <span style={{ color: 'var(--an-err)', fontSize: 10 }}>*</span>}
                    </label>
                    <input
                      type="text"
                      value={values[name] ?? ''}
                      placeholder={required ? '必填' : '可选'}
                      onChange={(e) => setValues((prev) => ({ ...prev, [name]: e.target.value }))}
                      style={{
                        height: 28,
                        padding: '0 8px',
                        border: '1px solid var(--an-border)',
                        borderRadius: 'var(--an-radius-sm)',
                        background: 'var(--an-bg-raised)',
                        color: 'var(--an-ink)',
                        fontFamily: 'var(--an-font-mono)',
                        fontSize: 12,
                        outline: 'none',
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
            {/* param_note 提示 */}
            {item.param_note && (
              <p style={{ margin: '10px 0 0', fontSize: 11, color: 'var(--an-ink-4)', lineHeight: 1.6, paddingLeft: 2 }}>
                {item.param_note}
              </p>
            )}
          </section>

          {/* 响应结果 */}
          {(response || err) && (
            <section>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--an-ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
                响应
              </div>
              {err && (
                <div style={{
                  padding: '10px 12px',
                  background: 'var(--an-err-bg)',
                  border: '1px solid color-mix(in oklch, var(--an-err) 30%, transparent)',
                  borderRadius: 'var(--an-radius)',
                  fontSize: 12,
                  color: 'var(--an-err)',
                }}>
                  {err}
                </div>
              )}
              {response && (
                <div style={{ border: '1px solid var(--an-border)', borderRadius: 'var(--an-radius)', overflow: 'hidden' }}>
                  {/* 状态栏 */}
                  <div style={{
                    padding: '7px 12px',
                    background: 'var(--an-bg-sunken)',
                    borderBottom: '1px solid var(--an-border)',
                    display: 'flex',
                    gap: 16,
                    fontSize: 11,
                    fontFamily: 'var(--an-font-mono)',
                    alignItems: 'center',
                  }}>
                    <span style={{ color: statusColor(response.status_code), fontWeight: 600 }}>
                      {response.status_code}
                    </span>
                    <span style={{ color: 'var(--an-ink-4)' }}>{response.duration_ms} ms</span>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      padding: '1px 6px',
                      background: response.mode === 'prod' ? 'var(--an-warn-bg)' : 'var(--an-accent-bg)',
                      color: response.mode === 'prod' ? 'var(--an-warn)' : 'var(--an-accent-ink)',
                      borderRadius: 3,
                      fontSize: 10,
                      fontWeight: 600,
                    }}>
                      {response.mode === 'prod' ? '生产' : 'Mock'}
                    </span>
                    <span style={{ color: 'var(--an-ink-5)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                      {response.url}
                    </span>
                  </div>
                  {/* JSON 正文 */}
                  <pre style={{
                    margin: 0,
                    padding: '12px',
                    fontSize: 11,
                    fontFamily: 'var(--an-font-mono)',
                    lineHeight: 1.6,
                    overflow: 'auto',
                    maxHeight: 360,
                    background: 'var(--an-bg-raised)',
                    color: 'var(--an-ink-2)',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}>
                    {JSON.stringify(response.data, null, 2)}
                  </pre>
                </div>
              )}
            </section>
          )}
        </div>

        {/* 底栏 */}
        <div className="an-drawer-footer">
          <button type="button" className="an-btn ghost" onClick={onClose}
            style={{ fontSize: 12 }}>取消</button>
          <button
            type="button"
            className="an-btn primary"
            onClick={handleSend}
            disabled={loading}
            style={{ fontSize: 12, minWidth: 80 }}
          >
            {loading ? '请求中…' : '发送请求'}
          </button>
        </div>
      </div>
    </>
  );
}
