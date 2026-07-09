/** 量化页回测区间日期工具（纯函数）。 */

export function formatIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** 以今天为终点，回看 lookbackDays 自然日。 */
export function lookbackRange(lookbackDays: number): { start_date: string; end_date: string } {
  const endDate = new Date();
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - Math.max(1, lookbackDays));
  return {
    start_date: formatIsoDate(startDate),
    end_date: formatIsoDate(endDate),
  };
}
