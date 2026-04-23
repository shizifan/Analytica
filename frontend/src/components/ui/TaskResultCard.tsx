import { useRef, useState } from 'react';
import { Icon } from './Icon';
import { ChartView, type ChartViewHandle } from './ChartView';
import { DataTable, tableToCSV, downloadText } from './DataTable';
import type {
  TaskResult,
  TaskResultChart,
  TaskResultTable,
  TaskResultText,
} from '../../types';

type TabKey = 'chart' | 'table' | 'text';

interface Props {
  primary: TaskResult;
  /** Optional table data to merge as the "数据" tab for chart tasks. */
  tableSource?: TaskResult;
}

function SanitizedCSVName(name: string): string {
  const stripped = name.replace(/[\\/:*?"<>|]+/g, '').trim();
  return (stripped || 'data').slice(0, 60);
}

function durationLabel(ms?: number): string | null {
  if (!ms || ms <= 0) return null;
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Phase 3.7 — single result card. Input is a "primary" task (chart or
 * table or text); a chart card can optionally carry a sibling
 * `tableSource` whose data becomes the "数据" tab + CSV download.
 */
export function TaskResultCard({ primary, tableSource }: Props) {
  const chartRef = useRef<ChartViewHandle>(null);

  const hasChart = primary.output_type === 'chart';
  const hasTable = hasChart ? !!tableSource : primary.output_type === 'table';
  const hasText = primary.output_type === 'text';

  const [active, setActive] = useState<TabKey>(
    hasChart ? 'chart' : hasTable ? 'table' : 'text',
  );

  const chartData = hasChart ? (primary.data as TaskResultChart | null) : null;
  const tableData = hasTable
    ? ((hasChart ? tableSource!.data : primary.data) as TaskResultTable | null)
    : null;
  const textData = hasText ? (primary.data as TaskResultText | null) : null;

  const canDownloadCSV = !!tableData;
  const canDownloadPNG = !!chartData;

  const handleDownloadCSV = () => {
    if (!tableData) return;
    const source = hasChart ? tableSource! : primary;
    const csv = tableToCSV(tableData, ['deptName', 'ownerLgZoneName']);
    downloadText(
      `${SanitizedCSVName(source.name || primary.name)}.csv`,
      csv,
      'text/csv;charset=utf-8',
    );
  };

  const handleDownloadPNG = () => {
    chartRef.current?.downloadPNG(
      `${SanitizedCSVName(primary.name)}.png`,
    );
  };

  // Meta line (source api / rows / duration)
  const metaBits: string[] = [];
  if (primary.source_api) metaBits.push(primary.source_api);
  else if (hasChart && tableSource?.source_api) metaBits.push(tableSource.source_api);
  if (tableData) metaBits.push(`${tableData.total_rows} 行 × ${tableData.columns.length} 列`);
  const duration = durationLabel(primary.duration_ms);
  if (duration) metaBits.push(duration);
  if (primary.skill) metaBits.push(primary.skill);

  return (
    <div className="an-result-card">
      <div className="an-result-head">
        <div className="an-result-title">
          <div className="an-result-name" title={primary.name}>{primary.name}</div>
          {metaBits.length > 0 && (
            <div className="an-result-meta">
              {metaBits.map((bit, i) => (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {i > 0 && <span className="sep" />}
                  <span>{bit}</span>
                </span>
              ))}
            </div>
          )}
        </div>

        {(hasChart || hasTable) && (hasChart && hasTable ? true : !hasText) && (
          <div className="an-result-tabs" role="tablist">
            {hasChart && (
              <button
                type="button"
                role="tab"
                aria-selected={active === 'chart'}
                className={`an-result-tab${active === 'chart' ? ' active' : ''}`}
                onClick={() => setActive('chart')}
              >
                图表
              </button>
            )}
            {hasTable && (
              <button
                type="button"
                role="tab"
                aria-selected={active === 'table'}
                className={`an-result-tab${active === 'table' ? ' active' : ''}`}
                onClick={() => setActive('table')}
              >
                数据
                {tableData && (
                  <span className="an-result-tab-count">{tableData.total_rows}</span>
                )}
              </button>
            )}
          </div>
        )}
      </div>

      <div className={`an-result-body${active === 'table' ? ' no-pad' : ''}`}>
        {active === 'chart' && chartData && (
          <ChartView ref={chartRef} option={chartData.option} height={320} />
        )}
        {active === 'table' && tableData && (
          <DataTable
            data={tableData}
            priorityCols={['deptName', 'ownerLgZoneName']}
          />
        )}
        {active === 'text' && textData && (
          <div className="an-result-text">{textData.text}</div>
        )}
      </div>

      {(canDownloadCSV || canDownloadPNG) && (
        <div className="an-result-footer">
          {active === 'chart' && canDownloadPNG && (
            <button type="button" className="an-btn" onClick={handleDownloadPNG}>
              <Icon name="check" size={12} />
              下载 PNG
            </button>
          )}
          {active === 'table' && canDownloadCSV && (
            <button type="button" className="an-btn" onClick={handleDownloadCSV}>
              <Icon name="check" size={12} />
              下载 CSV
            </button>
          )}
          {/* When chart is active, also expose quick CSV access if data is bound. */}
          {active === 'chart' && canDownloadCSV && (
            <button type="button" className="an-btn ghost" onClick={handleDownloadCSV}>
              下载 CSV
            </button>
          )}
        </div>
      )}
    </div>
  );
}
