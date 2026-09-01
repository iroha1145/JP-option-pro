/** ReactECharts 包装组件：按需 echarts 实例 + ResizeObserver 自适应 */
import { useEffect, useRef } from 'react';
import { echarts, type ChartOption, type EChartsInstance } from '@/lib/chart';

interface ReactEChartsProps {
  option: ChartOption;
  className?: string;
  style?: React.CSSProperties;
  onClick?: (params: unknown) => void;
  /** 实例创建后回调一次；实例随组件卸载 dispose，外部持有需以此回调刷新引用 */
  onInit?: (chart: EChartsInstance) => void;
  ariaLabel?: string;
}

export default function ReactECharts({ option, className, style, onClick, onInit, ariaLabel }: ReactEChartsProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsInstance | null>(null);
  const onInitRef = useRef(onInit);
  onInitRef.current = onInit;

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    onInitRef.current?.(chart);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setOption(option, { notMerge: true });
    // Always detach first so a transition to onClick=undefined removes the stale
    // handler (previously the off() lived inside the if and leaked the old binding).
    chart.off('click');
    if (onClick) chart.on('click', onClick);
  }, [option, onClick]);

  return (
    /* 尺寸只认 className（内联 height:100% 会压过 h-*，而父级是 auto 高时
       100% 退化为内容高——canvas 与容器互喂、图表塌成 ~130px）。 */
    <div
      ref={ref}
      className={className ?? 'h-full w-full'}
      style={style}
      role="img"
      aria-label={ariaLabel}
    />
  );
}
