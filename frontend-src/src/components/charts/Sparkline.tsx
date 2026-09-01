/**
 * 迷你 sparkline（design.md §6-4）
 * 默认走 Insight Cards 折线工艺：渐变面积、终点、首绘 draw-line。
 */
import { memo } from 'react';
import InsightLineChart from './InsightLineChart';

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  change: number;
  variant?: 'line' | 'area';
  className?: string;
}

const Sparkline = memo(function Sparkline({
  data,
  width,
  height = 20,
  change,
  className,
}: SparklineProps) {
  return (
    <InsightLineChart
      data={data}
      height={height}
      change={change}
      interactive={false}
      showLiveDot
      className={className}
      width={width}
    />
  );
});

export default Sparkline;
