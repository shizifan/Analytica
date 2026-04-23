import { useState } from 'react';
import type { TaskResultTable } from '../../types';

interface Props {
  data: TaskResultTable;
  /** Collapse after this many rows until "展开全部" is clicked. */
  collapseAfter?: number;
  /** Pin these column names to the front, in order, before auto-sort. */
  priorityCols?: string[];
}

const DEFAULT_COLLAPSE = 10;

function isNumericCol(rows: Array<Array<unknown>>, colIdx: number): boolean {
  // Heuristic: a column is numeric if ≥80% of non-null values are numbers.
  let total = 0;
  let numeric = 0;
  for (const row of rows) {
    const v = row[colIdx];
    if (v == null) continue;
    total += 1;
    if (typeof v === 'number' || (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v))) {
      numeric += 1;
    }
  }
  return total > 0 && numeric / total >= 0.8;
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return v.toLocaleString('en-US');
    return v.toLocaleString('en-US', {
      maximumFractionDigits: 4,
      minimumFractionDigits: 0,
    });
  }
  return String(v);
}

/** Sort order: pinned cols first, then non-numeric, then numeric. */
function reorderColumns(
  columns: string[],
  rows: Array<Array<unknown>>,
  priorityCols: string[] = [],
): { orderedCols: string[]; colIndices: number[] } {
  const pinned = priorityCols.filter((c) => columns.includes(c));
  const pinnedSet = new Set(pinned);
  const rest = columns.filter((c) => !pinnedSet.has(c));
  const colIdx = (c: string) => columns.indexOf(c);
  const nonNumeric = rest.filter((c) => !isNumericCol(rows, colIdx(c)));
  const numeric = rest.filter((c) => isNumericCol(rows, colIdx(c)));
  const orderedCols = [...pinned, ...nonNumeric, ...numeric];
  return { orderedCols, colIndices: orderedCols.map(colIdx) };
}

export function DataTable({ data, collapseAfter = DEFAULT_COLLAPSE, priorityCols }: Props) {
  const [expanded, setExpanded] = useState(false);
  const total = data.total_rows ?? data.rows.length;
  const canCollapse = total > collapseAfter;
  const visibleRows = expanded || !canCollapse ? data.rows : data.rows.slice(0, collapseAfter);

  const { orderedCols, colIndices } = reorderColumns(data.columns, data.rows, priorityCols);
  const numericCols = orderedCols.map((_, i) => isNumericCol(data.rows, colIndices[i]));

  return (
    <>
      <div className="an-data-table-wrapper">
        <table className="an-data-table">
          <thead>
            <tr>
              {orderedCols.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, i) => (
              <tr key={i}>
                {colIndices.map((ci, j) => (
                  <td key={j} className={numericCols[j] ? 'num' : ''}>
                    {formatCell(row[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canCollapse && (
        <div className="an-data-table-footer">
          <span>
            {expanded ? `共 ${total} 行` : `显示 ${collapseAfter} / ${total} 行`}
          </span>
          <button type="button" onClick={() => setExpanded((v) => !v)}>
            {expanded ? '收起' : `展开全部 ${total} 行`}
          </button>
        </div>
      )}
    </>
  );
}

/** Convert a TaskResultTable to CSV string (UTF-8, Excel-friendly). */
export function tableToCSV(data: TaskResultTable, priorityCols?: string[]): string {
  const escape = (v: unknown): string => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const { orderedCols, colIndices } = reorderColumns(data.columns, data.rows, priorityCols);
  const header = orderedCols.map(escape).join(',');
  const body = data.rows.map((row) => colIndices.map((ci) => escape(row[ci])).join(',')).join('\n');
  return `${header}\n${body}`;
}

/** Trigger a browser download for the given text content. */
export function downloadText(filename: string, text: string, mime = 'text/plain;charset=utf-8'): void {
  // Prefix UTF-8 BOM so Excel renders Chinese correctly.
  const blob = new Blob([`\uFEFF${text}`], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
