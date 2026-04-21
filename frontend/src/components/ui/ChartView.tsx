import { useEffect, useImperativeHandle, useRef, forwardRef } from 'react';
import ReactECharts from 'echarts-for-react';
import type { ECharts } from 'echarts';

export interface ChartViewHandle {
  /** Trigger a PNG download; returns true if the chart was ready. */
  downloadPNG(filename?: string): boolean;
}

interface Props {
  option: Record<string, unknown>;
  height?: number;
}

/**
 * Phase 3.7 — thin ECharts wrapper exposing a ref handle so the parent
 * result card can drive PNG downloads from its own toolbar. Does NOT
 * render its own export button (handled at the card level).
 */
export const ChartView = forwardRef<ChartViewHandle, Props>(
  function ChartView({ option, height = 320 }: Props, ref) {
    const chartRef = useRef<ReactECharts | null>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);

    // ResizeObserver to keep the chart honest on pane resize.
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

    useImperativeHandle(ref, () => ({
      downloadPNG: (filename?: string) => {
        const instance = chartRef.current?.getEchartsInstance() as
          | (ECharts & { getDataURL: (opts: Record<string, unknown>) => string })
          | undefined;
        if (!instance) return false;
        const url = instance.getDataURL({
          type: 'png',
          pixelRatio: 2,
          backgroundColor: '#fff',
        });
        const a = document.createElement('a');
        a.href = url;
        a.download = filename ?? `chart_${Date.now()}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        return true;
      },
    }));

    return (
      <div ref={containerRef}>
        <ReactECharts
          ref={chartRef}
          option={option}
          style={{ height, width: '100%' }}
          notMerge={false}
          lazyUpdate
        />
      </div>
    );
  },
);
