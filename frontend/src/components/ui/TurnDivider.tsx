/** TurnDivider — visual separator between multi-turn conversation rounds.
 *
 * Shows turn index, plan title, turn type, and key findings.
 * Click to expand/collapse. The latest (active) turn stays expanded.
 */

import { useState } from 'react';
import type { TurnMeta } from '../../stores/sessionStore';

interface Props {
  turnIndex: number;
  meta: TurnMeta;
  /** Whether this turn is the latest (currently active or most recent). */
  isLatest: boolean;
}

export default function TurnDivider({ turnIndex, meta, isLatest }: Props) {
  const [open, setOpen] = useState(isLatest);

  const typeLabel: Record<string, string> = {
    new: '新分析',
    continue: '延续分析',
    amend: '格式变换',
  };

  return (
    <div className={`an-turn-divider ${open ? 'expanded' : ''}`}>
      <button
        type="button"
        className="an-turn-divider-bar"
        onClick={() => setOpen((v) => !v)}
        aria-label={`第 ${turnIndex} 轮：${meta.planTitle || '分析'}`}
      >
        <span className="an-turn-label">R{turnIndex}</span>
        <span className="an-turn-dot">·</span>
        <span className="an-turn-title">{meta.planTitle || '分析'}</span>
        <span className="an-turn-toggle">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="an-turn-body">
          <div className="an-turn-type">
            类型：{typeLabel[meta.turnType] ?? meta.turnType}
          </div>
          {meta.keyFindings.length > 0 && (
            <ul className="an-turn-findings">
              {meta.keyFindings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
