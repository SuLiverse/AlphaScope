import { fetchApi, API_BASE_URL, API_KEY } from './api';
import { AgentOpinion, AnalysisResult, DebatePoint, DebateResult, ProviderEvidence, ProviderTrace, SourceAppendixItem } from '../types';
import { mockAnalysisResult } from './mockAnalysisData';
import { getEnabledAgentRuntimeConfigs } from './agentConfigs';

interface AnalysisRunData {
  stock_symbol?: string;
  stock_name?: string;
  mode?: string;
  result?: unknown;
}

interface AsyncAnalysisStartData {
  task_id: string;
  status: string;
}

interface TaskResultData {
  id?: string;
  status?: 'pending' | 'running' | 'success' | 'failed' | 'cancelled';
  progress?: number;
  message?: string;
  error?: string;
  output_json?: string;
  [key: string]: unknown;
}

export type TaskStatus = NonNullable<TaskResultData['status']>;

export interface TaskStatusSnapshot {
  id: string;
  status: TaskStatus;
  progress: number;
  message: string;
  error: string;
}

const SIGNAL_MAP: Record<string, AgentOpinion['signal']> = {
  BUY: 'BUY',
  LONG: 'BUY',
  BULLISH: 'BUY',
  买入: 'BUY',
  看多: 'BUY',
  增持: 'BUY',
  强烈推荐: 'BUY',
  SELL: 'SELL',
  SHORT: 'SELL',
  BEARISH: 'SELL',
  卖出: 'SELL',
  看空: 'SELL',
  减持: 'SELL',
  HOLD: 'HOLD',
  NEUTRAL: 'HOLD',
  WAIT: 'HOLD',
  观望: 'HOLD',
  中性: 'HOLD',
  持有: 'HOLD',
};

function normalizeSignal(value: unknown): AgentOpinion['signal'] {
  const raw = String(value ?? '').trim();
  if (!raw) return 'HOLD';
  return SIGNAL_MAP[raw] || SIGNAL_MAP[raw.toUpperCase()] || 'HOLD';
}

function normalizeConfidence(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.max(0, Math.min(1, n > 1 ? n / 100 : n));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function formatInlineValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatTextValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    return value.map(formatTextValue).filter(Boolean).join('\n');
  }

  const record = asRecord(value);
  const summaryParts: string[] = [];
  if (record.final) summaryParts.push(`综合结论：${formatInlineValue(record.final)}`);
  if (record.avg_confidence !== undefined) summaryParts.push(`平均置信度：${formatInlineValue(record.avg_confidence)}%`);
  if (record.buy !== undefined || record.sell !== undefined || record.hold !== undefined) {
    summaryParts.push(`投票分布：买入 ${formatInlineValue(record.buy ?? 0)} / 卖出 ${formatInlineValue(record.sell ?? 0)} / 观望 ${formatInlineValue(record.hold ?? 0)}`);
  }
  if (summaryParts.length) return summaryParts.join('\n');

  return Object.entries(record)
    .map(([key, entryValue]) => `${key}: ${formatInlineValue(entryValue)}`)
    .join('\n');
}

function stripMarkdownJsonFence(value: string): string {
  const trimmed = value.trim();
  const fenceMatch = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenceMatch ? fenceMatch[1].trim() : trimmed;
}

function tryParseJsonObject(value: string): Record<string, unknown> | null {
  const stripped = stripMarkdownJsonFence(value);
  const normalized = stripped.replace(/^json\s*/i, '').trim();
  if (!normalized.startsWith('{') || !normalized.endsWith('}')) return null;
  try {
    const parsed = JSON.parse(normalized);
    return asRecord(parsed);
  } catch {
    return null;
  }
}

function normalizeAgentReason(value: unknown): string {
  const text = formatTextValue(value);
  const parsed = tryParseJsonObject(text);
  if (parsed?.reason) return formatTextValue(parsed.reason);
  const reasonMatch = text.match(/"reason"\s*:\s*"([^"]+)/);
  if (reasonMatch?.[1]) return reasonMatch[1].trim();

  const cleaned = text
    .replace(/^```(?:json)?/i, '')
    .replace(/```$/i, '')
    .replace(/^json\s*/i, '')
    .replace(/[{}"]/g, '')
    .replace(/\\n/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!cleaned || cleaned === '{' || cleaned === '}') {
    return '模型返回内容未能稳定结构化，建议修复模型配置后复核。';
  }
  return cleaned;
}

function normalizeStringArray(value: unknown): string[] {
  return asArray(value)
    .map(formatTextValue)
    .filter(Boolean);
}

function normalizeStringRecord(value: unknown): Record<string, string> {
  return Object.fromEntries(
    Object.entries(asRecord(value)).map(([key, entryValue]) => [key, formatInlineValue(entryValue)]),
  );
}

function sanitizeModelError(value: unknown): string {
  const text = formatTextValue(value)
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, '[REDACTED]')
    .replace(/(api\s*key\s*[:：]?\s*)[^,\s'"}]+/gi, '$1[REDACTED]')
    .replace(/\s+/g, ' ')
    .trim();
  if (/401|unauthori[sz]ed|authentication|authenticat|api\s*key|invalid\s*key|鉴权|认证|密钥/i.test(text)) {
    return '模型鉴权失败，请在系统设置中检查 Provider Base URL、API Key 和模型名。';
  }
  return text.slice(0, 220);
}

function normalizeEvidenceItems(value: unknown): ProviderEvidence[] {
  return asArray(value).map((item, index) => {
    const record = asRecord(item);
    const id = formatInlineValue(record.id || record.ref_id || `evidence-${index + 1}`) || `evidence-${index + 1}`;
    const claim = formatTextValue(record.claim || record.summary || record.reason || item);
    return {
      id,
      ref_id: formatInlineValue(record.ref_id || id),
      type: formatInlineValue(record.type || record.evidence_type || 'other'),
      title: formatInlineValue(record.title || claim || `证据 ${index + 1}`),
      claim,
      source: formatInlineValue(record.source || record.provider || record.data_source || 'analysis'),
      retrieved_at: formatInlineValue(record.retrieved_at || record.data_date || ''),
      raw_value: record.raw_value ?? item,
      derivation: formatInlineValue(record.derivation || record.invalid_if || '模型输出结构化提取'),
      source_call: formatInlineValue(record.source_call || record.endpoint || 'analysis.result'),
      provider_trace_id: formatInlineValue(record.provider_trace_id || ''),
      confidence: normalizeConfidence(record.confidence ?? 0.5),
    };
  });
}

function normalizeProviderTraces(value: unknown): ProviderTrace[] {
  return asArray(value).map((item, index) => {
    const record = asRecord(item);
    return {
      data_type: formatInlineValue(record.data_type || record.type || `trace-${index + 1}`),
      provider_trace_id: formatInlineValue(record.provider_trace_id || record.id || ''),
      selected_provider: formatInlineValue(record.selected_provider || record.provider || ''),
      source_chain: normalizeStringArray(record.source_chain),
      fallback_attempts: asArray(record.fallback_attempts).map((attempt) => {
        const attemptRecord = asRecord(attempt);
        return {
          provider: formatInlineValue(attemptRecord.provider || ''),
          endpoint: formatInlineValue(attemptRecord.endpoint || ''),
          status: formatInlineValue(attemptRecord.status || ''),
          latency_ms: Number(attemptRecord.latency_ms) || 0,
          items_count: Number(attemptRecord.items_count) || 0,
          error: formatTextValue(attemptRecord.error || ''),
          fallback_to: formatInlineValue(attemptRecord.fallback_to || ''),
        };
      }),
      field_fill_map: normalizeStringRecord(record.field_fill_map),
      errors: asArray(record.errors),
      degraded: Boolean(record.degraded),
      items_count: Number(record.items_count) || 0,
    };
  });
}

function normalizeSourceAppendix(value: unknown): SourceAppendixItem[] {
  return asArray(value).map((item, index) => {
    const record = asRecord(item);
    return {
      data_type: formatInlineValue(record.data_type || record.type || `source-${index + 1}`),
      selected_provider: formatInlineValue(record.selected_provider || record.provider || ''),
      source_chain: normalizeStringArray(record.source_chain),
      degraded: Boolean(record.degraded),
      items_count: Number(record.items_count) || 0,
      field_fill_map: normalizeStringRecord(record.field_fill_map),
      last_error: formatTextValue(record.last_error || record.error || ''),
      provider_trace_id: formatInlineValue(record.provider_trace_id || ''),
    };
  });
}

function normalizeDebate(value: unknown): DebateResult | undefined {
  const rec = asRecord(value);
  if (!Object.keys(rec).length) return undefined;
  const toPoints = (arr: unknown): DebatePoint[] =>
    asArray(arr).map((p) => {
      const r = asRecord(p);
      return {
        side: formatInlineValue(r.side),
        source: formatInlineValue(r.source),
        kind: formatInlineValue(r.kind),
        claim: formatTextValue(r.claim),
        weight: Number(r.weight) || 0,
        confidence: Number(r.confidence) || 0,
        evidence_ids: asArray(r.evidence_ids).map((e) =>
          typeof e === 'number' ? e : formatInlineValue(e),
        ),
      };
    });
  return {
    status: formatInlineValue(rec.status) || 'ok',
    consensus: formatInlineValue(rec.consensus),
    consensus_score: Number(rec.consensus_score) || 0,
    divergence_level: formatInlineValue(rec.divergence_level),
    bull_strength: Number(rec.bull_strength) || 0,
    bear_strength: Number(rec.bear_strength) || 0,
    n_bull: Number(rec.n_bull) || 0,
    n_bear: Number(rec.n_bear) || 0,
    n_neutral: Number(rec.n_neutral) || 0,
    bull_points: toPoints(rec.bull_points),
    bear_points: toPoints(rec.bear_points),
    ruling: formatTextValue(rec.ruling),
    disclaimer: formatInlineValue(rec.disclaimer),
  };
}

/**
 * Normalizes the raw backend response into a consistent frontend AnalysisResult.
 * This adapter layer protects UI components from backend schema drift.
 */
export function normalizeAnalysisResult(raw: any): AnalysisResult {
  // Extract fields with safe defaults
  const agents = raw?.agents || raw?.result?.agents || {};
  const evidence = normalizeEvidenceItems(raw?.evidence || raw?.result?.evidence || []);
  const provider_traces = normalizeProviderTraces(raw?.provider_traces || raw?.result?.provider_traces || []);
  const source_appendix = normalizeSourceAppendix(raw?.source_appendix || raw?.result?.source_appendix || []);
  const degraded = raw?.degraded ?? raw?.result?.degraded ?? false;
  const source_errors = asArray(raw?.source_errors || raw?.result?.source_errors || []);
  const summary = formatTextValue(raw?.summary || raw?.result?.summary || raw?.brief || raw?.result?.brief || '');
  const brief = formatTextValue(raw?.brief || raw?.result?.brief || '');
  // 结构化评级(确定性公式输出) — 后端 summary 是 dict 时直接抽取
  const summaryRecord = asRecord(raw?.summary || raw?.result?.summary || {});
  const rawScore = Number(summaryRecord.score);
  const rawRating = formatInlineValue(summaryRecord.rating);
  const score = Number.isFinite(rawScore) ? Math.max(0, Math.min(100, rawScore)) : undefined;
  const rating = rawRating || undefined;
  const rating_breakdown = asRecord(summaryRecord.rating_breakdown || {});
  const hasBreakdown = Object.keys(rating_breakdown).length > 0;
  const research_report = formatTextValue(raw?.research_report || raw?.result?.research_report || '');
  const rawCritic = raw?.critic || raw?.result?.critic || '';
  const criticRecord = asRecord(rawCritic);
  const critic = Object.keys(criticRecord).length
    ? criticRecord.ok === false
      ? formatTextValue(criticRecord.error || '风控复核模型未完成，暂以系统规则提示为主。')
      : formatTextValue(criticRecord.divergence || criticRecord.summary || rawCritic)
    : formatTextValue(rawCritic);
  const chairman_summary = formatTextValue(raw?.chairman_summary || raw?.result?.chairman_summary || '');
  const debate = normalizeDebate(raw?.debate || raw?.result?.debate);
  const modelStatusRecord = asRecord(raw?.model_status || raw?.result?.model_status || {});
  const model_status = Object.keys(modelStatusRecord).length
    ? {
        status: formatInlineValue(modelStatusRecord.status || ''),
        degraded: Boolean(modelStatusRecord.degraded),
        failure_type: formatInlineValue(modelStatusRecord.failure_type || ''),
        message: formatTextValue(modelStatusRecord.message || ''),
        ok_agents: Number(modelStatusRecord.ok_agents) || 0,
        total_agents: Number(modelStatusRecord.total_agents) || 0,
        failed_agents: asArray(modelStatusRecord.failed_agents).map((item) => {
          const record = asRecord(item);
          return {
            key: formatInlineValue(record.key || ''),
            name: formatInlineValue(record.name || ''),
            reason: sanitizeModelError(record.reason || ''),
          };
        }),
        action: formatTextValue(modelStatusRecord.action || ''),
      }
    : undefined;

  // Ensure agent references are mapped properly
  const normalizedAgents: Record<string, any> = {};
  for (const [key, agentData] of Object.entries<any>(agents)) {
    const agentRecord = asRecord(agentData);
    // Collect refs from agent's own data, deduplicate
    const refs = normalizeStringArray(agentRecord.evidence_refs);
    const uniqueRefs = Array.from(new Set(refs));
    
    normalizedAgents[key] = {
      signal: normalizeSignal(agentRecord.signal),
      confidence: normalizeConfidence(agentRecord.confidence),
      reason: sanitizeModelError(normalizeAgentReason(agentRecord.reason || agentRecord.summary || '')),
      name: formatInlineValue(agentRecord.name || agentRecord.role || key),
      vendor: formatInlineValue(agentRecord.vendor || agentRecord.primary_vendor || ''),
      model: formatInlineValue(agentRecord.model || ''),
      risk_points: normalizeStringArray(agentRecord.risk_points || agentRecord.risks || []),
      evidence_refs: uniqueRefs,
    };
  }

  return {
    summary,
    brief,
    research_report,
    mode: formatInlineValue(raw?.mode || raw?.result?.mode || ''),
    mode_name: formatInlineValue(raw?.mode_name || raw?.result?.mode_name || ''),
    critic,
    chairman_summary,
    debate,
    model_status,
    agents: normalizedAgents,
    evidence,
    provider_traces,
    source_appendix,
    degraded,
    source_errors,
    score,
    rating,
    rating_breakdown: hasBreakdown ? (rating_breakdown as any) : undefined,
  };
}

/**
 * Evaluates the actual integrity severity based on traces and evidence,
 * rather than relying solely on the binary `degraded` flag.
 */
export function deriveDataIntegritySeverity(result: AnalysisResult): 'green' | 'yellow' | 'red' {
  const textCorpus = [result.brief, result.summary, result.chairman_summary, result.critic]
    .filter(Boolean)
    .join('\n');
  if (/暂无可用价格数据|数据缺失|完全信息黑箱|N\/A|最新价:\s*¥?0\.00|当日成交量:\s*0/.test(textCorpus)) {
    return result.evidence.length === 0 && result.provider_traces.length === 0 ? 'red' : 'yellow';
  }

  // If explicitly healthy, it's green
  if (!result.degraded && result.source_errors.length === 0) {
    return 'green';
  }

  // Check if critical data is entirely missing
  const quoteTrace = result.provider_traces.find(t => t.data_type === 'quote');
  const riskTrace = result.provider_traces.find(t => t.data_type === 'risk_events');
  
  const quoteMissing = !quoteTrace || quoteTrace.items_count === 0;
  const riskMissing = !riskTrace || riskTrace.items_count === 0;

  // If both critical traces are missing, or there are no traces at all but it claims degraded
  if (result.degraded && (quoteMissing || riskMissing || result.provider_traces.length === 0)) {
    return 'red';
  }

  // Otherwise, it's partially degraded (e.g. fallback successful or non-critical trace failed)
  return 'yellow';
}

/**
 * Runs analysis via real API. Mock data is only used when explicitly requested.
 */
export async function runAnalysisWithFallback(
  stockSymbol: string,
  stockName: string,
  mode: string = 'deep',
  useMockForcefully: boolean = false,
  globalAiSettings?: Record<string, unknown>,
): Promise<AnalysisResult> {
  if (useMockForcefully) {
    console.log('[Adapter] Using forced mock data');
    // Simulate network delay
    await new Promise(r => setTimeout(r, 1500));
    return normalizeAnalysisResult(mockAnalysisResult);
  }

  try {
    const rawResult = await fetchApi<AnalysisRunData>('/api/analysis/run', {
      method: 'POST',
      body: JSON.stringify({
        stock_symbol: stockSymbol,
        stock_name: stockName,
        mode: mode,
        agent_configs: getEnabledAgentRuntimeConfigs(),
        global_ai_settings: globalAiSettings,
      })
    });
    
    return normalizeAnalysisResult(rawResult);
  } catch (err) {
    console.warn(`[Adapter] Real API failed:`, err);
    if (import.meta.env.VITE_USE_MOCK_REPORT === 'true') {
      console.log('[Adapter] Falling back to mock data in development mode');
      return normalizeAnalysisResult(mockAnalysisResult);
    }
    throw err;
  }
}

/**
 * Starts an async analysis task. Returns the task ID.
 */
export async function startAsyncAnalysis(
  stockSymbol: string,
  stockName: string,
  mode: string = 'deep',
  useMockForcefully: boolean = false,
  globalAiSettings?: Record<string, unknown>,
  reportTemplate?: string,
): Promise<string> {
  if (useMockForcefully) {
    return 'mock-task-123';
  }

  try {
    const rawResult = await fetchApi<AsyncAnalysisStartData>('/api/analysis/async', {
      method: 'POST',
      body: JSON.stringify({
        stock_symbol: stockSymbol,
        stock_name: stockName,
        mode: mode,
        conversation_id: '',
        agent_configs: getEnabledAgentRuntimeConfigs(),
        global_ai_settings: globalAiSettings,
        report_template: reportTemplate || 'standard',
      })
    });
    return rawResult.task_id;
  } catch (err) {
    console.warn(`[Adapter] Async API failed:`, err);
    if (import.meta.env.VITE_USE_MOCK_REPORT === 'true') {
      return 'mock-task-123';
    }
    throw err;
  }
}

/** 已完成研报的 Markdown 导出 URL(浏览器直接下载)。 */
export function getReportExportUrl(taskId: string): string {
  const base = API_BASE_URL.replace(/\/+$/, '');
  const url = new URL(`${base}/api/export/report/${taskId}.md`);
  if (API_KEY) {
    url.searchParams.set('token', API_KEY);
  }
  return url.toString();
}

/**
 * Fetches the result of a completed task.
 */
export async function getTaskResult(taskId: string, useMockForcefully: boolean = false): Promise<AnalysisResult> {
  if (useMockForcefully || taskId === 'mock-task-123') {
    return normalizeAnalysisResult(mockAnalysisResult);
  }
  const rawResult = await fetchApi<TaskResultData>(`/api/tasks/${taskId}`);
  
  // The backend task returns { output_json: "{...}" }
  if (rawResult.output_json) {
    let parsed;
    try {
      parsed = JSON.parse(rawResult.output_json);
    } catch {
      parsed = rawResult;
    }
    return normalizeAnalysisResult(parsed);
  }
  
  return normalizeAnalysisResult(rawResult);
}

export async function getTaskStatus(taskId: string): Promise<TaskStatusSnapshot> {
  const rawResult = await fetchApi<TaskResultData>(`/api/tasks/${taskId}`);
  const status = rawResult.status || 'pending';
  const isTerminal = ['success', 'failed', 'cancelled'].includes(status);
  return {
    id: rawResult.id || taskId,
    status,
    progress: typeof rawResult.progress === 'number'
      ? rawResult.progress
      : isTerminal
        ? 100
        : status === 'running'
          ? 35
          : 8,
    message: rawResult.message || '',
    error: rawResult.error || '',
  };
}

/**
 * Returns the SSE endpoint URL for tasks
 */
export function getTaskEventsUrl(taskId?: string): string {
  const base = API_BASE_URL.replace(/\/+$/, '');
  const url = new URL(`${base}/api/tasks/events`);
  if (taskId) {
    url.searchParams.set('task_id', taskId);
  }
  if (API_KEY) {
    url.searchParams.set('token', API_KEY);
  }
  return url.toString();
}
