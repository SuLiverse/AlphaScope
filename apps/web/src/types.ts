export type TabID = 'workbench' | 'dashboard' | 'news' | 'detailed' | 'agents' | 'saved' | 'experts' | 'tasks' | 'strategy_lab' | 'market' | 'fund_dca' | 'chart' | 'valuation' | 'dragon_tiger' | 'investors' | 'brief' | 'monitor' | 'research_memory' | 'report_archive' | 'tickflow' | 'datalake' | 'factor_registry' | 'integration_center' | 'settings';

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'critic';
  agentName?: string;
  content: string;
  timestamp: string;
}

export interface AgentModule {
  id: string;
  name: string;
  role: string;
  status: 'idle' | 'analyzing' | 'completed' | 'offline';
  description: string;
  department: 'san-sheng' | 'liu-bu'; // 三省(Decision) or 六部(Functional)
}

export interface BacktestResult {
  id: string;
  strategyName: string;
  returnRate: number;
  maxDrawdown: number;
  winRate: number;
  sharpeRatio: number;
  dateRange: string;
}

// --- Backend Data Source Tracing Types ---

export interface FallbackAttempt {
  provider: string;
  endpoint: string;
  status: string;
  latency_ms: number;
  items_count: number;
  error: string;
  fallback_to: string;
}

export interface ProviderTrace {
  data_type: string;
  provider_trace_id: string;
  selected_provider: string;
  source_chain: string[];
  fallback_attempts: FallbackAttempt[];
  field_fill_map: Record<string, string>;
  errors: any[];
  degraded: boolean;
  items_count: number;
}

export interface SourceAppendixItem {
  data_type: string;
  selected_provider: string;
  source_chain: string[];
  degraded: boolean;
  items_count: number;
  field_fill_map: Record<string, string>;
  last_error: string;
  provider_trace_id: string;
}

export interface ProviderEvidence {
  id: string;
  ref_id: string;
  type: string;
  evidence_type?: string;
  title: string;
  claim: string;
  source: string;
  retrieved_at: string;
  raw_value: any;
  derivation: string;
  source_call: string;
  provider_trace_id: string;
  confidence: number;
}

export interface AgentOpinion {
  signal: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  reason: string;
  name?: string;
  vendor?: string;
  model?: string;
  ok?: boolean;
  fallback_used?: boolean;
  structured_fallback?: boolean;
  risk_points?: string[];
  evidence_refs?: string[];
  /** 结论反链到的真实 evidence_id 列表(可溯源)。 */
  evidence_ids?: string[];
}

/** 简报里 [n] 编号对应的证据池条目,供结论反查。 */
export interface EvidencePoolItem {
  number: number;
  evidence_id: string;
  doc_type?: string;
  source?: string;
  source_url?: string;
  published_at?: string;
  preview?: string;
}

export interface AnalysisModelStatus {
  status?: 'ok' | 'degraded' | string;
  degraded?: boolean;
  failure_type?: 'auth' | 'model' | string;
  message?: string;
  ok_agents?: number;
  total_agents?: number;
  failed_agents?: Array<{
    key?: string;
    name?: string;
    reason?: string;
  }>;
  action?: string;
}

export interface DebatePoint {
  side: string;
  source: string;
  kind: string;
  claim: string;
  weight: number;
  confidence: number;
  evidence_ids: (string | number)[];
}

export interface DebateResult {
  status: string;
  consensus: string;
  consensus_score: number;
  divergence_level: string;
  bull_strength: number;
  bear_strength: number;
  n_bull: number;
  n_bear: number;
  n_neutral: number;
  bull_points: DebatePoint[];
  bear_points: DebatePoint[];
  ruling: string;
  disclaimer?: string;
}

export interface RatingBreakdown {
  n_agents: number;
  W: number;
  D: number;
  raw: number;
  avg_conf: number;
  conf_factor: number;
  risk_vetoed: boolean;
}

export interface AnalysisResult {
  summary?: string;
  brief?: string;
  research_report?: string;
  mode?: string;
  mode_name?: string;
  agents: Record<string, AgentOpinion>;
  critic?: string;
  chairman_summary?: string;
  debate?: DebateResult;
  model_status?: AnalysisModelStatus;
  evidence_pool?: EvidencePoolItem[];
  evidence: ProviderEvidence[];
  provider_traces: ProviderTrace[];
  source_appendix: SourceAppendixItem[];
  degraded: boolean;
  source_errors: any[];
  data_status?: string;
  score?: number;
  rating?: string;
  rating_breakdown?: RatingBreakdown;
}

export interface AnalysisTask {
  id: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled';
  progress: number;
  message: string;
  input_json: string;
  output_json: string;
  error: string;
  created_at: number;
}

export interface ProviderHealthItem {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  consecutive_failures: number;
  avg_latency_ms: number;
  last_error: string;
  last_success?: string | number;
  empty_count: number;
  recent_calls?: number;
  stability: 'stable' | 'fragile';
  risk_note: string;
  data_types: string[];
  markets: string[];
  // v1.9.4 质量分
  quality_score?: number;
  grade?: 'good' | 'warn' | 'poor';
  success_rate?: number;
  freshness_score?: number;
  completeness_score?: number;
}
