import type { CitationValidationResult, QuantRefereeResult } from '../types';

export type ReviewTone = 'ok' | 'degraded' | 'skipped' | 'error';

export interface ReviewDisplayState {
  tone: ReviewTone;
  label: string;
  fallback: string;
}

export function getQuantRefereeDisplayState(referee: QuantRefereeResult): ReviewDisplayState {
  const status = String(referee.status || 'unknown').toLowerCase();
  if (status === 'ok') {
    return { tone: 'ok', label: '规则计算完成', fallback: '' };
  }
  if (status === 'degraded') {
    return {
      tone: 'degraded',
      label: '规则输入不完整',
      fallback: '部分量化字段缺失，当前规则信号不能视为完整裁判结论。',
    };
  }
  if (status === 'insufficient' || status === 'skipped' || status === 'unavailable') {
    return {
      tone: 'skipped',
      label: '证据不足',
      fallback: '本次数据不足，未形成可用的量化裁判结论。',
    };
  }
  return {
    tone: 'error',
    label: status === 'error' ? '规则计算失败' : '规则状态未知',
    fallback: '量化裁判没有返回可验证的完成状态，请勿据此作出判断。',
  };
}

export function getCitationDisplayState(citation: CitationValidationResult): ReviewDisplayState {
  const status = String(citation.status || 'unknown').toLowerCase();
  if (status === 'error' || status === 'failed') {
    return {
      tone: 'error',
      label: '核验失败',
      fallback: '引用核验执行失败，当前不能判断数字或证据引用是否可靠。',
    };
  }
  if (status === 'skipped' || status === 'insufficient' || status === 'unavailable') {
    return {
      tone: 'skipped',
      label: '未完成核验',
      fallback: '本次引用核验被跳过或输入不足，不能显示为核验通过。',
    };
  }
  if (status === 'degraded' || citation.n_unverified > 0 || citation.n_citation_bad > 0) {
    return {
      tone: 'degraded',
      label: '核验降级',
      fallback: '核验结果存在未对齐数字或异常引用，请结合问题列表审阅。',
    };
  }
  if (status === 'ok') {
    return {
      tone: 'ok',
      label: '核验完成',
      fallback: '当前核验范围内未发现明显未对齐数字或异常引用。',
    };
  }
  return {
    tone: 'error',
    label: '核验状态未知',
    fallback: '引用核验没有返回受支持的状态，不能推断为健康。',
  };
}
