import { fetchApi } from './api';

export interface ResearchMaterial {
  title: string;
  source_url: string;
  published_at: string | null;
  excerpt: string;
}

export interface ResearchDraft {
  stock_symbol: string;
  stock_name: string;
  research_question: string;
  as_of: string | null;
  report_template: string;
  materials: ResearchMaterial[];
}

export interface ResearchVersionSummary {
  id: string;
  number: number;
  task_id: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled';
  stage: string;
  error: string;
  created_at: string;
}

export interface Workspace {
  id: string;
  draft: ResearchDraft;
  versions: ResearchVersionSummary[];
}

export type ReviewStatus = 'supported' | 'partial' | 'unsupported' | 'needs_evidence';
export type EvidenceRelation = 'supports' | 'opposes' | 'unclassified';
export interface ClaimReview {
  status: ReviewStatus;
  reason: string;
  revised_text: string;
  evidence_relations: Record<string, EvidenceRelation>;
  revision: number;
  created_at: string;
}

export interface ResearchClaim {
  id: string;
  agent_id: string;
  agent_name: string;
  text: string;
  evidence_ids: string[];
  agent_evidence_ids: string[];
}

export interface ResearchVersion extends ResearchVersionSummary {
  workspace_id: string;
  input: ResearchDraft;
  result: Record<string, unknown> | null;
  claims: ResearchClaim[];
  reviews: Record<string, ClaimReview[]>;
}

export interface VersionChange {
  field: string;
  before: unknown;
  after: unknown;
  status: string;
}

export interface VersionComparison {
  summary: string;
  warnings: string[];
  conclusion: { before: unknown; after: unknown; changed: boolean };
  context: VersionChange[];
  evidence: VersionChange[];
  metrics: VersionChange[];
  agents: VersionChange[];
  models: VersionChange[];
}

export const WORKSPACE_API = '/api/research-workspaces';
export const LAST_WORKSPACE_KEY = 'alphascope.lastResearchWorkspace';
export const REVIEW_LABELS: Record<ReviewStatus, string> = {
  supported: '支持', partial: '部分支持', unsupported: '不支持', needs_evidence: '待补充',
};
export const VERSION_LABELS: Record<ResearchVersionSummary['status'], string> = {
  pending: '排队中', running: '进行中', success: '已完成', failed: '失败', cancelled: '已取消',
};

export async function saveResearchDraft(draft: ResearchDraft, workspaceId: string): Promise<Workspace> {
  return fetchApi<Workspace>(`${WORKSPACE_API}${workspaceId ? `/${workspaceId}` : ''}`, {
    method: workspaceId ? 'PUT' : 'POST', body: JSON.stringify(draft),
  });
}
