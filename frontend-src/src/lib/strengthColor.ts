/** 强度分色阶；与界面组件分离，供不同图表和指标共用。 */
export function strengthBarClass(score: number): string {
  if (score >= 85) return 'bg-up-600';
  if (score >= 70) return 'bg-brand-600';
  if (score >= 50) return 'bg-brand-400';
  return 'bg-ink-300';
}

/** 追高 / 拥挤等风险分：越高越危险，反向着色。 */
export function riskBarClass(score: number): string {
  if (score >= 70) return 'bg-down-600';
  if (score >= 50) return 'bg-warn-600';
  return 'bg-ink-300';
}
