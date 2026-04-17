import { useRef, useEffect, useCallback } from 'react';
import ReactECharts from 'echarts-for-react';
import type { ECharts } from 'echarts';

interface EChartsViewerProps {
  option: Record<string, unknown>;
  height?: number;
  loading?: boolean;
  onExport?: () => void;
}

export function EChartsViewer({
  option,
  height = 400,
  loading = false,
  onExport,
}: EChartsViewerProps) {
  const chartRef = useRef<ReactECharts | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // ResizeObserver to auto-resize chart when container width changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ro = new ResizeObserver(() => {
      const instance = chartRef.current?.getEchartsInstance();
      instance?.resize();
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  const handleExport = useCallback(() => {
    const instance = chartRef.current?.getEchartsInstance() as
      | (ECharts & { getDataURL: (opts: Record<string, unknown>) => string })
      | undefined;
    if (!instance) return;

    if (onExport) {
      onExport();
      return;
    }

    // Default export: download as PNG
    const url = instance.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#fff',
    });
    const a = document.createElement('a');
    a.href = url;
    a.download = `chart_${Date.now()}.png`;
    a.click();
  }, [onExport]);

  if (loading) {
    return (
      <div
        data-testid="echart-skeleton"
        className="animate-pulse rounded-lg bg-gray-200"
        style={{ height }}
      />
    );
  }

  return (
    <div ref={containerRef} data-testid="echart-viewer" className="relative">
      <div className="absolute right-2 top-2 z-10">
        <button
          onClick={handleExport}
          className="rounded bg-white/80 px-2 py-1 text-xs text-gray-600 shadow hover:bg-white"
          title="导出 PNG"
        >
          &#128190; 导出
        </button>
      </div>
      <ReactECharts
        ref={chartRef}
        option={option}
        style={{ height }}
        notMerge={false}
        lazyUpdate
      />
    </div>
  );
}
