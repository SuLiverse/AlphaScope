const labels: Record<string, string> = {
  actual: '实际使用', requested: '请求配置', resolved: '解析后配置', fundamental: '基本面', technical: '技术面',
  final: '综合结论', avg_confidence: '平均置信度', votes: '投票', buy: '看多', sell: '看空', hold: '观望',
  sentiment: '市场情绪', macro: '宏观', risk: '风险', chairman: '主持人', critic: '风控复核',
  signal: '观点', confidence: '置信度', reason: '理由', risk_points: '风险点', ok: '执行成功',
  vendor: '服务商', model: '模型', fallback_used: '使用备用模型', mode: '研究模式',
  as_of: '截止日', research_question: '研究问题', report_template: '报告模板', materials: '研究资料',
  fundamentals: '基本面指标', financial_metrics: '财务指标', pe: '市盈率', pb: '市净率', roe: '净资产收益率',
  revenue: '营业收入', net_profit: '净利润', gross_margin: '毛利率', operating_cash_flow: '经营现金流',
  price: '价格', current_price: '当前价格', change_pct: '涨跌幅', volume: '成交量', market_cap: '总市值',
  source: '来源', source_url: '原文链接', published_at: '发布日期', excerpt: '原文摘录', preview: '摘录',
  evidence_id: '证据编号', doc_type: '资料类型', title: '标题', agent_configs: 'Agent 配置',
  global_ai_settings: '全局模型配置', provider: '服务商', provider_name: '服务商', model_id: '模型',
};

export function researchFieldLabel(field: string): string {
  return field.split('.').map(part => labels[part] || part).join(' · ');
}

export function researchValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未记录';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.length ? value.map(researchValue).join('\n') : '无记录';
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${researchFieldLabel(key)}：${researchValue(item)}`).join('\n');
  return String(value);
}

export function safeResearchUrl(value?: string) {
  try { const url = new URL(value || ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}
