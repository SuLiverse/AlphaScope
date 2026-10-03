import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  FileText,
  Sparkles,
  Award,
  FileCheck,
  Settings2,
  AlertTriangle,
  ClipboardCheck,
  LineChart,
  ShieldCheck,
  Scale,
  TrendingUp,
  TrendingDown,
  Cpu,
  CheckCircle2,
  XCircle,
  BarChart3,
  Download,
  Gauge,
  Link2,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { getCitationDisplayState, getQuantRefereeDisplayState } from '../lib/reviewStatus';
import { startAsyncAnalysis, getTaskResult, getTaskEventsUrl, getTaskStatus, getReportExportUrl, normalizeAnalysisResult } from '../lib/analysisAdapter';
import {
  AnalysisResult,
  CitationValidationResult,
  DebateResult,
  QuantRefereeResult,
  RatingBreakdown,
} from '../types';
import { DecisionSummary } from './report/DecisionSummary';
import { ReportCharts } from './ReportCharts';
import { AgentOpinionCards } from './report/AgentOpinionCards';
import { SourceTracePanel } from './report/SourceTracePanel';
import { FieldSourceTable } from './report/FieldSourceTable';
import { EvidenceAppendix } from './report/EvidenceAppendix';
import { ResearchTrustPanel } from './report/ResearchTrustPanel';
import { ResearchSnapshotBar } from './report/ResearchSnapshotBar';
import { mockAnalysisResult } from '../lib/mockAnalysisData';
import { STOCK_UNIVERSE, findStockTarget, formatStockLabel } from '../lib/stocks';
import { dispatchStockSelected, getPersistedStock, subscribeStockSelected, subscribeSettingsChanged } from '../lib/workspaceEvents';
import { fetchApi } from '../lib/api';
import {
  applyReportModelOverride,
  buildModelOptions,
  getModelKey,
  getRouteSelection,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
  type AiModelRoutes,
  ModelOption,
  ModelProvider,
  routesToGlobalAiSettings,
} from '../lib/aiModelRouting';
import { ThemedSelect } from './ThemedSelect';
import { ResearchWorkspacePanel } from './report/ResearchWorkspacePanel';
import { ResearchReviewPanel } from './report/ResearchReviewPanel';
import { ResearchStatusStrip, type ReviewProgress } from './report/ResearchStatusStrip';
import { LAST_WORKSPACE_KEY, saveResearchDraft, type ResearchDraft, type ResearchMaterial, type Workspace, type ResearchVersion } from '../lib/researchWorkspace';

const REPORT_VIEWS = [['overview', '概览'], ['full', '全文'], ['review', '复核'], ['compare', '差异'], ['sources', '资料']] as const;
type ReportView = typeof REPORT_VIEWS[number][0];

const REPORT_TEMPLATES = [
  { id: 'standard', name: '标准个股深度评级公司研报', desc: '包含宏观定位，深度报表分析以及三因素量化诊股。' },
  { id: 'macro', name: '行业及产业链专题跟踪报告', desc: '梳理上下游资本开支变化与库存周期的另类情报归纳。' },
  { id: 'risk', name: '黑天鹅情绪避险与信用预警评估', desc: '侧重于舆情违约风险、大股东股权质押及账外担保预警。' }
];

interface ReportGeneratorProps {
  onOpenModelSettings?: () => void;
}

function formatModelOption(option?: ModelOption) {
  if (!option) return '未配置';
  return `${option.providerName} / ${option.modelId}`;
}

function todayLocalDate() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function splitReportParagraphs(text?: string) {
  return (text || '')
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function cleanReportText(text: string) {
  return text
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/^-\s+/gm, '')
    .trim();
}

function ReportTextBlock({ text }: { text?: string }) {
  const paragraphs = splitReportParagraphs(text);
  if (!paragraphs.length) return null;

  return (
    <div className="min-w-0 space-y-4 break-words">
      {paragraphs.map((paragraph, index) => {
        const cleaned = cleanReportText(paragraph);
        const lines = cleaned.split('\n').map((line) => line.trim()).filter(Boolean);
        const firstLine = lines[0] || '';
        const isSectionHeading = lines.length === 1 && /^(\d+\.|[一二三四五六七八九十]+、|【.+】)/.test(firstLine);
        const isListLike = lines.length > 1;

        if (isSectionHeading) {
          return <h4 key={index} className="pt-2 text-sm font-semibold text-indigo-200">{firstLine}</h4>;
        }

        if (isListLike) {
          return (
            <div key={index} className="space-y-2">
              <p className="text-sm font-semibold text-neutral-100">{firstLine}</p>
              <ul className="space-y-2 text-sm leading-relaxed text-neutral-300">
                {lines.slice(1).map((line, lineIndex) => (
                  <li key={lineIndex} className="flex gap-2">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-indigo-300/60" />
                    <span className="min-w-0">{line}</span>
                  </li>
                ))}
              </ul>
            </div>
          );
        }

        return (
          <p key={index} className="whitespace-pre-line text-sm leading-7 text-neutral-300">
            {cleaned}
          </p>
        );
      })}
    </div>
  );
}

function ReportSection({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-white/10 py-6 first:border-t-0 first:pt-0">
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center text-sky-300">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-white">{title}</h3>
        </div>
      </div>
      {children}
    </section>
  );
}

function ModelStatusNotice({
  result,
  onOpenModelSettings,
}: {
  result: AnalysisResult;
  onOpenModelSettings?: () => void;
}) {
  const status = result.model_status;
  if (!status?.degraded) return null;

  const isAuth = status.failure_type === 'auth';
  return (
    <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-400/25 bg-amber-400/10 text-amber-300">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold text-amber-100">
              {isAuth ? '模型鉴权未通过' : '模型推理链路降级'}
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-6 text-amber-100/75">
              {status.message || '部分 AI 席位没有完成推理，当前研报包含系统结构化底稿。'}
            </p>
            {status.action && (
              <p className="mt-1 text-[11px] leading-5 text-amber-100/55">{status.action}</p>
            )}
          </div>
        </div>
        {onOpenModelSettings && (
          <button
            type="button"
            onClick={onOpenModelSettings}
            className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-xs font-semibold text-amber-100 transition-colors hover:border-amber-200/45 hover:bg-amber-300/15"
          >
            <Settings2 className="h-3.5 w-3.5" />
            打开模型设置
          </button>
        )}
      </div>
    </div>
  );
}

function ModelQualityPanel({ result }: { result: AnalysisResult }) {
  const status = result.model_status;
  const totalAgents = status?.total_agents ?? Object.keys(result.agents).length;
  const okAgents = status?.ok_agents ?? Object.values(result.agents).filter((agent) => agent.confidence > 0).length;
  const failedAgents = status?.failed_agents || [];
  const isDegraded = Boolean(status?.degraded);

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.025] p-5">
      <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">生成质量</div>
      <dl className="mt-4 space-y-4 text-sm">
        <div className="flex items-center justify-between gap-4">
          <dt className="text-neutral-400">专家席位</dt>
          <dd className="font-mono text-neutral-100">{okAgents}/{totalAgents}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt className="text-neutral-400">证据条目</dt>
          <dd className="font-mono text-neutral-100">{result.evidence.length}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt className="text-neutral-400">数据链路</dt>
          <dd className="font-mono text-neutral-100">{result.provider_traces.length}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt className="text-neutral-400">模型状态</dt>
          <dd className={cn('inline-flex items-center gap-1.5 text-xs font-semibold', isDegraded ? 'text-amber-300' : 'text-emerald-300')}>
            {isDegraded ? <XCircle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            {isDegraded ? '降级' : '正常'}
          </dd>
        </div>
      </dl>
      {failedAgents.length > 0 ? (
        <div className="mt-5 space-y-2 border-t border-white/5 pt-4">
          {failedAgents.slice(0, 3).map((agent, index) => (
            <div key={`${agent.key || agent.name || 'agent'}-${index}`} className="text-[11px] leading-5 text-neutral-500">
              <span className="text-neutral-300">{agent.name || agent.key || 'Agent'}</span>: {agent.reason}
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-5 text-xs leading-6 text-neutral-500">
          若行情、财务或成交数据为空，报告会保留风控结论，但不应被解释为完整估值报告。
        </p>
      )}
    </div>
  );
}

const DEBATE_CONSENSUS_TONE: Record<string, string> = {
  看多共识: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  偏看多: 'border-rose-500/25 bg-rose-500/[0.07] text-rose-200',
  看空共识: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  偏看空: 'border-emerald-500/25 bg-emerald-500/[0.07] text-emerald-200',
  多空分歧: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  高度分歧: 'border-amber-500/40 bg-amber-500/15 text-amber-200',
  中性观望: 'border-white/15 bg-white/5 text-neutral-300',
  风控否决: 'border-red-500/40 bg-red-500/15 text-red-300',
  未知: 'border-white/10 bg-white/5 text-neutral-400',
};

const RATING_TIER_TONE: Record<string, string> = {
  强烈推荐: 'border-rose-500/35 bg-rose-500/10 text-rose-300',
  推荐: 'border-orange-500/30 bg-orange-500/10 text-orange-300',
  中性: 'border-white/15 bg-white/5 text-neutral-300',
  谨慎: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  回避: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
};

const RATING_DISCLAIMER = '评级由多 Agent 投票与置信度确定性计算得出，仅为研究辅助，不构成投资建议。';

function RatingBadge({
  score,
  rating,
  breakdown,
}: {
  score?: number;
  rating?: string;
  breakdown?: RatingBreakdown;
}) {
  if (score === undefined || rating === undefined) return null;
  const tone = RATING_TIER_TONE[rating] || RATING_TIER_TONE['中性'];
  const vetoed = breakdown?.risk_vetoed === true;
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.035] p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col items-center justify-center">
          <div className="relative flex h-20 w-20 items-center justify-center">
            <svg className="absolute inset-0 -rotate-90" viewBox="0 0 80 80">
              <circle cx="40" cy="40" r="34" fill="none" stroke="currentColor" strokeWidth="6" className="text-white/8" />
              <circle
                cx="40"
                cy="40"
                r="34"
                fill="none"
                stroke="currentColor"
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={`${(pct / 100) * 2 * Math.PI * 34} ${2 * Math.PI * 34}`}
                className={tone.split(' ').find((c) => c.startsWith('text-')) || 'text-neutral-300'}
              />
            </svg>
            <span className="text-xl font-bold text-neutral-100">{Math.round(pct)}</span>
          </div>
          <span className="mt-1 text-[10px] text-neutral-500">评分 / 100</span>
        </div>
        <div className="flex-1 min-w-[180px]">
          <span className={cn('inline-flex items-center rounded-full border px-3 py-1 text-sm font-semibold', tone)}>
            {vetoed ? '⛔ 风控否决' : rating}
          </span>
          <p className="mt-2 text-[11px] leading-relaxed text-neutral-500">{RATING_DISCLAIMER}</p>
          {breakdown && (
            <p className="mt-1 text-[11px] text-neutral-600">
              加权方向 D={breakdown.D.toFixed(2)} · 平均置信度 {(breakdown.avg_conf ?? 0).toFixed(0)}% ·
              收缩因子 {(breakdown.conf_factor ?? 0).toFixed(2)} · {breakdown.n_agents ?? 0} Agents
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function DebatePanel({ debate }: { debate: DebateResult }) {
  const tone = DEBATE_CONSENSUS_TONE[debate.consensus] || DEBATE_CONSENSUS_TONE['未知'];
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.035] p-5">
      <div className={cn('mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3', tone)}>
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4" />
          <span className="text-sm font-semibold">主席裁决：{debate.consensus}</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] font-mono opacity-90">
          <span>共识度 {debate.consensus_score.toFixed(0)}/100</span>
          <span>分歧 {debate.divergence_level}</span>
          <span>多 {debate.n_bull} · 空 {debate.n_bear} · 中 {debate.n_neutral}</span>
        </div>
      </div>

      {debate.ruling && <p className="mb-4 text-sm leading-relaxed text-neutral-300">{debate.ruling}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-rose-500/15 bg-rose-500/[0.04] p-4">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-rose-300">
            <TrendingUp className="h-3.5 w-3.5" /> 看多方 ({debate.bull_points.length})
          </div>
          {debate.bull_points.length ? (
            <ul className="space-y-1.5">
              {debate.bull_points.map((p, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-neutral-300">· {p.claim}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-neutral-600">无看多论据</p>
          )}
        </div>
        <div className="rounded-lg border border-emerald-500/15 bg-emerald-500/[0.04] p-4">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-emerald-300">
            <TrendingDown className="h-3.5 w-3.5" /> 看空方 / 反方质询 ({debate.bear_points.length})
          </div>
          {debate.bear_points.length ? (
            <ul className="space-y-1.5">
              {debate.bear_points.map((p, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-neutral-300">
                  · {p.claim}
                  {p.kind === 'risk_veto' && <span className="ml-1 rounded bg-red-500/15 px-1 text-[9px] text-red-300">风控</span>}
                  {p.kind === 'data_gap' && <span className="ml-1 rounded bg-amber-500/15 px-1 text-[9px] text-amber-300">数据</span>}
                  {p.kind === 'critic_divergence' && <span className="ml-1 rounded bg-indigo-500/15 px-1 text-[9px] text-indigo-300">评审</span>}
                  {p.kind === 'low_conviction' && <span className="ml-1 rounded bg-neutral-500/15 px-1 text-[9px] text-neutral-300">信心</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-neutral-600">无反方质询</p>
          )}
        </div>
      </div>

      {debate.disclaimer && <p className="mt-4 text-[11px] leading-relaxed text-neutral-500">{debate.disclaimer}</p>}
    </div>
  );
}

const REFEREE_STANCE_TONE: Record<string, string> = {
  多头占优: 'border-rose-500/30 bg-rose-500/10 text-rose-100',
  偏多: 'border-rose-500/20 bg-rose-500/5 text-rose-200',
  中性: 'border-white/10 bg-white/5 text-neutral-200',
  偏空: 'border-emerald-500/20 bg-emerald-500/5 text-emerald-200',
  空头占优: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100',
  未知: 'border-white/10 bg-white/5 text-neutral-400',
};

function QuantRefereePanel({ referee }: { referee: QuantRefereeResult }) {
  const display = getQuantRefereeDisplayState(referee);
  const statusTone: Record<string, string> = {
    ok: REFEREE_STANCE_TONE[referee.stance] || REFEREE_STANCE_TONE['未知'],
    degraded: 'border-amber-500/25 bg-amber-500/[0.07] text-amber-100',
    skipped: 'border-white/10 bg-white/[0.03] text-neutral-300',
    error: 'border-red-500/25 bg-red-500/[0.07] text-red-100',
  };
  const tone = statusTone[display.tone];
  const alignTone =
    referee.llm_alignment === '冲突' || referee.llm_alignment === '背离'
      ? 'text-amber-300'
      : referee.llm_alignment === '一致' || referee.llm_alignment === '同向'
        ? 'text-emerald-300'
        : 'text-neutral-400';
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.035] p-5">
      <div className={cn('mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3', tone)}>
        <div className="flex items-center gap-2">
          <Gauge className="h-4 w-4" />
          <span className="text-sm font-semibold">规则立场：{referee.stance || '未知'}</span>
          <span className="rounded border border-current/20 px-1.5 py-0.5 text-[10px] opacity-80">
            {display.label}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] font-mono opacity-90">
          <span>净分 {Number(referee.net_score || 0).toFixed(1)}</span>
          <span>多 {referee.n_bull} · 空 {referee.n_bear} · 中 {referee.n_neutral}</span>
          <span className={alignTone}>vs LLM: {referee.llm_alignment || '未对比'}</span>
        </div>
      </div>
      <p className="mb-3 text-sm text-neutral-400">{referee.note || display.fallback}</p>
      {referee.signals?.length ? (
        <ul className="space-y-1.5">
          {referee.signals.map((s, i) => (
            <li key={`${s.rule_id}-${i}`} className="text-[12px] leading-relaxed text-neutral-300">
              <span className="mr-1 font-mono text-[10px] text-neutral-500">[{s.rule_id}]</span>
              {s.direction === 'bullish' ? '↑' : s.direction === 'bearish' ? '↓' : '·'} {s.claim}
              {s.value ? <span className="ml-1 text-neutral-500">({s.value})</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12px] text-neutral-600">
          {display.tone === 'ok' ? '未触发方向性规则信号。' : display.fallback}
        </p>
      )}
      {referee.disclaimer ? (
        <p className="mt-4 text-[11px] leading-relaxed text-neutral-500">{referee.disclaimer}</p>
      ) : null}
    </div>
  );
}

function CitationValidationPanel({ citation }: { citation: CitationValidationResult }) {
  const display = getCitationDisplayState(citation);
  const panelTone: Record<string, string> = {
    ok: 'border-emerald-500/15 bg-emerald-500/[0.035]',
    degraded: 'border-amber-500/20 bg-amber-500/[0.06]',
    skipped: 'border-white/8 bg-white/[0.035]',
    error: 'border-red-500/20 bg-red-500/[0.06]',
  };
  const grounding = Number.isFinite(citation.grounding_score) ? citation.grounding_score : 0;
  return (
    <div
      className={cn(
        'rounded-xl border p-5',
        panelTone[display.tone],
      )}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-neutral-100">
          <Link2 className="h-4 w-4" />
          数值与引用可追溯
          <span className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] font-normal text-neutral-400">
            {display.label}
          </span>
        </div>
        <div className="flex flex-wrap gap-3 text-[11px] font-mono text-neutral-400">
          <span>
            对齐 {citation.n_verified}/{citation.n_claims}
          </span>
          <span>grounding {(grounding * 100).toFixed(0)}%</span>
          <span>
            引用 OK {citation.n_citation_ok} / 异常 {citation.n_citation_bad}
          </span>
          {citation.suggest_confidence_cap != null ? (
            <span className="text-amber-300">建议置信上限 {citation.suggest_confidence_cap}</span>
          ) : null}
        </div>
      </div>
      {citation.note ? (
        <p className="mb-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-[12px] text-neutral-300">
          {citation.note}
        </p>
      ) : null}
      {citation.issues && citation.issues.length > 0 ? (
        <ul className="mb-3 space-y-1">
          {citation.issues.slice(0, 6).map((issue, i) => (
            <li key={i} className="text-[12px] text-amber-100/80">
              · {issue}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-[12px] text-neutral-500">{display.fallback}</p>
      )}
      {citation.disclaimer ? (
        <p className="text-[11px] leading-relaxed text-neutral-500">{citation.disclaimer}</p>
      ) : null}
    </div>
  );
}

function GeneratedResearchReport({
  result,
  symbol,
  stockName,
  onOpenModelSettings,
  view,
}: {
  result: AnalysisResult;
  symbol?: string;
  stockName?: string;
  onOpenModelSettings?: () => void;
  view: 'overview' | 'full' | 'sources';
}) {
  const hasBrief = Boolean(result.brief?.trim());
  const hasResearchReport = Boolean(result.research_report?.trim());
  const hasChairmanSummary = Boolean(result.chairman_summary?.trim());
  const hasCritic = Boolean(result.critic?.trim());

  return (
    <div className="space-y-1">
      {view === 'overview' && <ModelStatusNotice result={result} onOpenModelSettings={onOpenModelSettings} />}

      {view === 'full' && hasResearchReport && (
        <ReportSection icon={FileText} title="完整研报正文" eyebrow="Research Draft">
          <div className="py-2">
            <ReportTextBlock text={result.research_report} />
          </div>
        </ReportSection>
      )}

      {view === 'overview' && hasChairmanSummary && (
        <ReportSection icon={ClipboardCheck} title="投委会决策摘要" eyebrow={result.mode_name || 'AI Research Memo'}>
          <div className="py-2">
            <ReportTextBlock text={result.chairman_summary} />
          </div>
        </ReportSection>
      )}

      {view === 'full' && result.debate && result.debate.status === 'ok' && (
        <ReportSection icon={Scale} title="多空辩论与裁决" eyebrow="Bull vs Bear">
          <DebatePanel debate={result.debate} />
        </ReportSection>
      )}

      {view === 'full' && result.quant_referee && (
        <ReportSection icon={Gauge} title="量化裁判 (规则信号)" eyebrow="Quant Referee">
          <QuantRefereePanel referee={result.quant_referee} />
        </ReportSection>
      )}

      {view === 'sources' && result.citation_validation && (
        <ReportSection icon={Link2} title="引用与数值核验" eyebrow="Citation Validator">
          <CitationValidationPanel citation={result.citation_validation} />
        </ReportSection>
      )}

      {view === 'full' && symbol && (
        <ReportSection icon={BarChart3} title="多维图表分析" eyebrow="Charts · 9 图">
          <ReportCharts result={result} symbol={symbol} stockName={stockName} />
        </ReportSection>
      )}

      {view === 'sources' && hasBrief && (
        <ReportSection icon={LineChart} title="市场与数据快照" eyebrow="Market Snapshot">
          <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="py-2">
              <ReportTextBlock text={result.brief} />
            </div>
            <ModelQualityPanel result={result} />
          </div>
        </ReportSection>
      )}

      {view === 'overview' && result.summary && (
        <ReportSection icon={FileText} title="综合评级与投票" eyebrow="Decision Matrix">
          <div className="space-y-4">
            <RatingBadge
              score={result.score}
              rating={result.rating}
              breakdown={result.rating_breakdown}
            />
            <div className="py-2">
              <ReportTextBlock text={result.summary} />
            </div>
          </div>
        </ReportSection>
      )}

      {view === 'overview' && hasCritic && (
        <ReportSection icon={ShieldCheck} title="风控复核意见" eyebrow="Risk Review">
          <div className="border-l-2 border-amber-400/50 pl-4">
            <ReportTextBlock text={result.critic} />
          </div>
        </ReportSection>
      )}
    </div>
  );
}

export function ReportGenerator({ onOpenModelSettings }: ReportGeneratorProps) {
  const [selectedTarget, setSelectedTarget] = useState(() => getPersistedStock() ?? STOCK_UNIVERSE[0]);
  const selectedStock = formatStockLabel(selectedTarget);
  const [selectedTemplate, setSelectedTemplate] = useState('standard');
  const [researchQuestion, setResearchQuestion] = useState('');
  const [asOf, setAsOf] = useState('');
  const [workspaceId, setWorkspaceId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [materials, setMaterials] = useState<ResearchMaterial[]>([]);
  const [workspaceRefresh, setWorkspaceRefresh] = useState(0);
  const [reportView, setReportView] = useState<ReportView>('overview');
  const [parametersOpen, setParametersOpen] = useState(true);
  const [reportContext, setReportContext] = useState<(ResearchDraft & { number?: number }) | null>(null);
  const [reviewProgress, setReviewProgress] = useState<ReviewProgress | null>(null);
  const reviewDirty = useRef(false);
  function confirmLeaveReview() {
    return !reviewDirty.current || window.confirm('复核尚未保存，放弃修改并切换研究？');
  }
  const [isGenerating, setIsGenerating] = useState(false);
  const generatingRef = useRef(false);
  generatingRef.current = isGenerating;
  const [generationStep, setGenerationStep] = useState(0);
  const [progressPercent, setProgressPercent] = useState(0);
  const [generationStatus, setGenerationStatus] = useState('');
  // mock 进度 interval 的句柄;组件卸载时清理,避免 VITE_USE_MOCK_REPORT 模式下定时器泄漏
  const mockIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(
    () => () => {
      if (mockIntervalRef.current) clearInterval(mockIntervalRef.current);
    },
    [],
  );
  const [generationError, setGenerationError] = useState('');
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [currentTaskId, setCurrentTaskId] = useState('');
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [analysisRoutes, setAnalysisRoutes] = useState<AiModelRoutes>(() => loadLocalAiModelRoutes());
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [selectedReportModelKey, setSelectedReportModelKey] = useState('');
  
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  // 轮询活跃标志: stopTaskListeners 置 false 后, 进行中的 await 回调检查它即停,
  // 不对已卸载组件 setState、不递归重启已被清理的轮询链。
  const pollingActiveRef = useRef(false);
  const activeTaskRef = useRef('');
  const selectedReportModel = modelOptions.find((option) => option.key === selectedReportModelKey) ?? modelOptions[0];
  const selectableStocks = [selectedTarget, ...STOCK_UNIVERSE].filter(
    (stock, index, list) => list.findIndex((item) => item.symbol === stock.symbol) === index,
  );

  // Steps matching the general analysis pipeline
  const steps = [
    { label: '获取行情与概况', desc: '正在连接主数据源拉取实时行情快照...' },
    { label: '拉取资金与宏观数据', desc: '正在调取主力资金动向与板块轮动信息...' },
    { label: '风险与舆情过滤', desc: '正在扫描合规风险、违规处罚与负面舆情事件...' },
    { label: '领域专家圆桌会诊', desc: '基本面、量化、宏观Agent正在进行交叉研判...' },
    { label: '智能排版与生成', desc: '正在聚合证据链，排版最终投资建议报告...' }
  ];

  const stopTaskListeners = () => {
    pollingActiveRef.current = false;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  const finishWithError = (message: string) => {
    stopTaskListeners();
    setGenerationStatus('生成失败');
    setGenerationError(message);
    setIsGenerating(false);
    setWorkspaceRefresh(value => value + 1);
  };

  const completeTask = async (taskId: string) => {
    try {
      stopTaskListeners();
      setGenerationStep(steps.length);
      setProgressPercent(100);
      setGenerationStatus('报告生成完成，正在载入排版结果...');
      const result = await getTaskResult(taskId, false);
      if (activeTaskRef.current !== taskId) return;
      setAnalysisResult(result);
      setParametersOpen(false); setReportView('overview');
      if (result.research_version_id) setVersionId(result.research_version_id);
      if (result.workspace_id) rememberWorkspace(result.workspace_id);
      setWorkspaceRefresh(value => value + 1);
      setIsGenerating(false);
    } catch (error) {
      finishWithError(error instanceof Error ? error.message : '报告结果载入失败');
    }
  };

  const pollTaskStatus = (taskId: string) => {
    pollingActiveRef.current = true;
    pollTimerRef.current = window.setTimeout(async () => {
      try {
        const snapshot = await getTaskStatus(taskId);
        // 卸载/停止后不再 setState、不再递归(避免对已卸载组件 setState + 重启已清理轮询)
        if (!pollingActiveRef.current) return;
        if (activeTaskRef.current !== taskId) return;
        const p = Number(snapshot.progress) || 0;
        setProgressPercent((current) => Math.max(current, p));
        setGenerationStatus(snapshot.message || `任务状态：${snapshot.status}`);
        if (snapshot.status === 'success') {
          await completeTask(taskId);
          return;
        }
        if (snapshot.status === 'failed' || snapshot.status === 'cancelled') {
          finishWithError(snapshot.error || (snapshot.status === 'cancelled' ? '任务已取消' : '任务执行失败'));
          return;
        }
        pollTaskStatus(taskId);
      } catch (error) {
        if (!pollingActiveRef.current) return;
        console.warn('Failed to poll task status', error);
        pollTaskStatus(taskId);
      }
    }, 1500);
  };

  // Cleanup task listeners on unmount
  useEffect(() => {
    const unsubscribe = subscribeStockSelected(({ stock }) => {
      if (generatingRef.current) return;
      if (!confirmLeaveReview()) return;
      activeTaskRef.current = '';
      setSelectedTarget(findStockTarget(stock.symbol) ?? stock);
      setWorkspaceId(''); setVersionId(''); setAnalysisResult(null);
      setResearchQuestion(''); setMaterials([]); setAsOf('');
      setReportContext(null); setReviewProgress(null); setParametersOpen(true);
      localStorage.removeItem(LAST_WORKSPACE_KEY);
    });

    return () => {
      unsubscribe();
      activeTaskRef.current = '';
      stopTaskListeners();
    };
  }, []);

  const [reportModelsReloadKey, setReportModelsReloadKey] = useState(0);
  useEffect(() => subscribeSettingsChanged(() => setReportModelsReloadKey((k) => k + 1)), []);

  useEffect(() => {
    let cancelled = false;
    async function loadModels() {
      try {
        const result = await fetchApi<{ providers: ModelProvider[] }>('/api/settings/providers');
        if (cancelled) return;
        const nextProviders = result.providers || [];
        const routes = await loadAiModelRoutesFromApi().catch(() => loadLocalAiModelRoutes());
        if (cancelled) return;
        const options = buildModelOptions(nextProviders, 'chat');
        const routeKey = getModelKey(getRouteSelection(routes, nextProviders, 'report'));
        setProviders(nextProviders);
        setAnalysisRoutes(routes);
        setModelOptions(options);
        setSelectedReportModelKey((current) => (
          current && options.some((option) => option.key === current)
            ? current
            : routeKey && options.some((option) => option.key === routeKey)
              ? routeKey
              : options[0]?.key || ''
        ));
      } catch {
        if (!cancelled) {
          setProviders([]);
          setModelOptions([]);
          setSelectedReportModelKey('');
        }
      }
    }
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, [reportModelsReloadKey]);

  const [loadTaskId, setLoadTaskId] = useState('');
  const [loadError, setLoadError] = useState('');
  const [isLoadingTask, setIsLoadingTask] = useState(false);

  function rememberWorkspace(id: string) {
    setWorkspaceId(id);
    localStorage.setItem(LAST_WORKSPACE_KEY, id);
  }

  function restoreWorkspace(saved: Workspace, version?: ResearchVersion) {
    if (!confirmLeaveReview()) return;
    stopTaskListeners();
    activeTaskRef.current = '';
    rememberWorkspace(saved.id);
    // Draft edits remain separate from the frozen report's input parameters.
    const draft = saved.draft;
    const stock = findStockTarget(draft.stock_symbol);
    setSelectedTarget(stock || { ...STOCK_UNIVERSE[0], symbol: draft.stock_symbol, name: draft.stock_name });
    setResearchQuestion(draft.research_question);
    setAsOf(draft.as_of || ''); setSelectedTemplate(draft.report_template);
    setMaterials(draft.materials || []);
    setVersionId(version?.id || ''); setCurrentTaskId(version?.task_id || '');
    setGenerationError(''); setAnalysisResult(null); setIsGenerating(false);
    setReportContext(version ? { ...version.input, number: version.number } : null);
    setReviewProgress(null); setReportView('overview'); setParametersOpen(version?.status !== 'success');
    if (version?.status === 'success') {
      setAnalysisResult(normalizeAnalysisResult(version.result));
    } else if (version && ['pending', 'running'].includes(version.status) && version.task_id) {
      resumeTask(version.task_id, version.id);
    } else if (version) {
      setGenerationError(version.error || '任务未完成，可重试失败步骤');
    }
    setWorkspaceRefresh(value => value + 1);
  }

  function resumeTask(taskId: string, researchVersionId: string) {
    stopTaskListeners(); activeTaskRef.current = taskId;
    setCurrentTaskId(taskId); setVersionId(researchVersionId);
    setAnalysisResult(null); setGenerationError(''); setIsGenerating(true);
    setReviewProgress(null);
    setProgressPercent(0); setGenerationStatus('正在继续研究任务...');
    setWorkspaceRefresh(value => value + 1);
    pollTaskStatus(taskId);
  }

  function newWorkspace() {
    if (!confirmLeaveReview()) return;
    stopTaskListeners(); activeTaskRef.current = '';
    setWorkspaceId(''); setVersionId(''); setCurrentTaskId(''); setAnalysisResult(null);
    setResearchQuestion(''); setAsOf(''); setMaterials([]); setGenerationError('');
    setReportContext(null); setReviewProgress(null); setParametersOpen(true); setReportView('overview');
    localStorage.removeItem(LAST_WORKSPACE_KEY);
  }

  const researchDraft = {
    stock_symbol: selectedTarget.symbol, stock_name: selectedTarget.name,
    research_question: researchQuestion.trim(), as_of: asOf || null,
    report_template: selectedTemplate, materials,
  };

  // 从历史任务载入结果(修复圆桌分析结果不可达: 报告页可按 task_id 加载已完成任务)
  const loadExistingTask = async () => {
    const tid = loadTaskId.trim();
    if (!tid) return;
    if (!confirmLeaveReview()) return;
    setIsLoadingTask(true);
    setLoadError('');
    try {
      const task = await fetchApi<{ status: string; input_json: string }>(`/api/tasks/${tid}`);
      const input = JSON.parse(task.input_json || '{}');
      if (input.workspace_id && input.research_version_id) {
        const saved = await fetchApi<Workspace>(`/api/research-workspaces/${input.workspace_id}`);
        const version = await fetchApi<ResearchVersion>(`/api/research-workspaces/versions/${input.research_version_id}`);
        restoreWorkspace(saved, version);
        setLoadTaskId('');
        return;
      }
      if (task.status !== 'success') throw new Error('此历史任务尚未完成');
      const result = await getTaskResult(tid, false);
      activeTaskRef.current = '';
      setWorkspaceId(''); setVersionId('');
      if (input.stock_symbol) {
        setSelectedTarget(findStockTarget(input.stock_symbol) || { ...STOCK_UNIVERSE[0], symbol: input.stock_symbol, name: input.stock_name || input.stock_symbol });
        setResearchQuestion(input.research_question || ''); setAsOf(input.as_of || '');
      }
      setAnalysisResult(result);
      setReportContext({ stock_symbol: input.stock_symbol || '', stock_name: input.stock_name || '', research_question: input.research_question || '', as_of: input.as_of || null, report_template: input.report_template || '', materials: input.materials || [] });
      setReviewProgress(null); setReportView('overview'); setParametersOpen(false);
      setCurrentTaskId(tid);
      setGenerationStatus('已载入历史任务结果');
      setLoadTaskId('');
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '任务载入失败');
    } finally {
      setIsLoadingTask(false);
    }
  };

  const startGeneration = async () => {
    if (!confirmLeaveReview()) return;
    stopTaskListeners();
    setIsGenerating(true);
    setGenerationStep(0);
    setProgressPercent(0);
    setGenerationStatus('正在提交报告生成任务...');
    setGenerationError('');
    setAnalysisResult(null);
    setCurrentTaskId('');
    setReportContext({ ...researchDraft }); setReviewProgress(null); setReportView('overview');

    const symbol = selectedTarget.symbol;
    const name = selectedTarget.name;
    const forceMock = import.meta.env.VITE_USE_MOCK_REPORT === 'true';

    try {
      if (forceMock) {
        // Fallback mock flow
        let mockStep = 0;
        const interval = (mockIntervalRef.current = setInterval(() => {
          mockStep++;
          if (mockStep >= steps.length) {
            clearInterval(interval);
            setGenerationStep(steps.length);
            setProgressPercent(100);
            setGenerationStatus('报告生成完成');
            setAnalysisResult(mockAnalysisResult);
            setParametersOpen(false);
            setIsGenerating(false);
          } else {
            setGenerationStep(mockStep);
            setProgressPercent(mockStep * 20);
            setGenerationStatus(steps[mockStep]?.desc || 'AI 正在生成报告...');
          }
        }, 800));
        return;
      }

      const selectedReportRoute = selectedReportModel
        ? {
            providerId: selectedReportModel.providerId,
            providerName: selectedReportModel.providerName,
            modelId: selectedReportModel.modelId,
          }
        : undefined;
      const effectiveRoutes = applyReportModelOverride(analysisRoutes, selectedReportRoute);
      const globalAiSettings = selectedReportModel
        ? routesToGlobalAiSettings(effectiveRoutes, providers, 'report')
        : undefined;

      const saved = await saveResearchDraft(researchDraft, workspaceId);
      rememberWorkspace(saved.id);

      // Real API Flow with SSE
      const taskId = await startAsyncAnalysis(
        symbol,
        name,
        'deep',
        false,
        globalAiSettings,
        selectedTemplate,
        researchQuestion.trim(),
        asOf,
        { workspace_id: saved.id, materials },
      );
      activeTaskRef.current = taskId;
      setCurrentTaskId(taskId);
      const task = await fetchApi<{ input_json: string }>(`/api/tasks/${taskId}`);
      setVersionId(JSON.parse(task.input_json || '{}').research_version_id || '');
      setWorkspaceRefresh(value => value + 1);
      setProgressPercent(8);
      setGenerationStatus(`任务已启动：${taskId}`);
      pollTaskStatus(taskId);

      const sseUrl = getTaskEventsUrl(taskId);
      const eventSource = new EventSource(sseUrl);
      eventSourceRef.current = eventSource;

      eventSource.onmessage = async (e) => {
        if (e.data.trim() === ': heartbeat') return;
        try {
          const data = JSON.parse(e.data);
          if (data.task_id === taskId && activeTaskRef.current === taskId) {
            
            if (data.type === 'task_progress') {
              const p = Number(data.progress) || 0;
              setProgressPercent(p);
              const stepIndex = Math.min(steps.length - 1, Math.floor((p / 100) * steps.length));
              setGenerationStep(stepIndex);
              setGenerationStatus(data.message || steps[stepIndex]?.desc || 'AI 正在生成报告...');
            } 
            
            else if (data.type === 'task_completed') {
              await completeTask(taskId);
            }
            
            else if (data.type === 'task_failed' || data.type === 'task_cancelled') {
              console.error('Task failed or cancelled', data);
              finishWithError(data.error || data.message || '报告生成任务失败，请检查后端日志或模型配置。');
            }
          }
        } catch (err) {
          console.warn('Failed to parse task event payload', err, e.data);
        }
      };

      eventSource.onerror = (err) => {
        console.error('SSE Error', err);
        eventSource.close();
        eventSourceRef.current = null;
        setGenerationStatus('进度流连接中断，已切换为轮询任务状态...');
      };

    } catch (error) {
      console.error(error);
      finishWithError(error instanceof Error ? error.message : '报告生成任务启动失败');
    }
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="p-4 sm:p-6 lg:p-8 max-w-[1600px] mx-auto text-neutral-300 flex flex-col h-full overflow-y-auto lg:overflow-hidden tracking-normal"
    >
      
      {/* Title */}
      <div className="mb-4 flex shrink-0 items-center justify-between gap-3">
        <h2 className="text-xl font-medium text-white flex items-center gap-3">
          <FileText className="w-5 h-5 shrink-0 text-sky-400" />
          研究报告
        </h2>
        <button type="button" title={parametersOpen ? '收起研究参数' : '编辑研究参数'} aria-label={parametersOpen ? '收起研究参数' : '编辑研究参数'} aria-expanded={parametersOpen} aria-controls="research-parameters" onClick={() => setParametersOpen(v => !v)} className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md border border-white/15 px-3 text-sm text-neutral-300 hover:bg-white/5"><Settings2 className="h-4 w-4" /><span>研究参数</span></button>
      </div>

      <ResearchWorkspacePanel draft={researchDraft} workspaceId={workspaceId} versionId={versionId} busy={isGenerating || isLoadingTask} refreshKey={workspaceRefresh}
        onSaved={id => { rememberWorkspace(id); setWorkspaceRefresh(value => value + 1); }} onRestore={restoreWorkspace} onNew={newWorkspace} onMaterials={setMaterials} onStarted={resumeTask} beforeRetry={confirmLeaveReview} />
      <div className={cn('mt-4 flex-none lg:flex-1 grid grid-cols-1 gap-5 lg:min-h-0 lg:overflow-hidden', parametersOpen && 'lg:grid-cols-[minmax(260px,320px)_minmax(0,1fr)]')}>
        
        {/* Left configurations Column */}
        <div id="research-parameters" className={cn('lg:min-h-0 min-w-0 flex-col gap-5 lg:overflow-y-auto lg:border-r border-white/10 lg:pr-4 custom-scrollbar', parametersOpen ? 'flex' : 'hidden')}>
          <span className="text-sm text-neutral-200 font-semibold block mb-1">研究参数</span>
          
          <div className="space-y-2">
            <label className="text-xs font-medium text-neutral-400 select-none">研究对象</label>
            <ThemedSelect
              disabled={isGenerating || !!workspaceId}
              value={selectedStock}
              onChange={(value) => {
                const stock = selectableStocks.find((item) => formatStockLabel(item) === value);
                if (stock) {
                  setSelectedTarget(stock);
                  dispatchStockSelected(stock, 'report');
                }
              }}
              buttonClassName="h-10 bg-black/40 px-3 text-xs focus-visible:border-indigo-500/50"
              menuClassName="text-xs"
              options={selectableStocks.map((stock) => ({
                value: formatStockLabel(stock),
                label: formatStockLabel(stock),
              }))}
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-neutral-400 select-none">研究问题</label>
            <textarea
              value={researchQuestion}
              onChange={(event) => setResearchQuestion(event.target.value.slice(0, 2000))}
              placeholder="例如：未来两个季度的利润增长是否可持续？"
              rows={3}
              disabled={isGenerating}
              className="w-full resize-none rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs leading-relaxed text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-indigo-500/50 disabled:opacity-50"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-neutral-400 select-none">数据截止日</label>
            <input
              type="date"
              value={asOf}
              max={todayLocalDate()}
              onChange={(event) => setAsOf(event.target.value)}
              disabled={isGenerating}
              className="h-10 w-full rounded-lg border border-white/10 bg-black/40 px-3 text-xs text-neutral-200 outline-none [color-scheme:dark] focus:border-indigo-500/50 disabled:opacity-50"
            />
          </div>

          <div className="space-y-2.5">
            <label className="text-xs font-medium text-neutral-400 select-none">研报大纲范式 (Framework Templates)</label>
            <div className="space-y-2">
              {REPORT_TEMPLATES.map(tmp => (
                <button
                  key={tmp.id}
                  disabled={isGenerating}
                  onClick={() => setSelectedTemplate(tmp.id)}
                  className={cn(
                    "w-full p-3 rounded-xl border text-left cursor-pointer transition-all flex flex-col gap-1",
                    selectedTemplate === tmp.id 
                      ? "bg-indigo-500/10 border-indigo-500/40 shadow-sm"
                      : "bg-black/20 border-white/5 hover:border-white/10 hover:bg-black/40"
                  )}
                >
                  <span className={cn(
                    "text-xs font-semibold",
                    selectedTemplate === tmp.id ? "text-indigo-300" : "text-neutral-300"
                  )}>{tmp.name}</span>
                  <span className="text-[10px] text-neutral-500 leading-normal">{tmp.desc}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-white/5 bg-black/20 p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <label className="text-xs font-medium text-neutral-400 select-none">研报模型</label>
              <button
                type="button"
                onClick={onOpenModelSettings}
                className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-400 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
              >
                <Settings2 className="h-3.5 w-3.5" />
                设置
              </button>
            </div>
            <select
              data-testid="report-model-select"
              value={selectedReportModel?.key || ''}
              onChange={(event) => setSelectedReportModelKey(event.target.value)}
              disabled={!modelOptions.length || isGenerating}
              className="h-10 w-full rounded-xl border border-white/10 bg-black/40 px-3 text-xs text-neutral-200 outline-none focus:border-indigo-500/50 disabled:text-neutral-600"
            >
              {modelOptions.length ? modelOptions.map((option) => (
                <option key={option.key} value={option.key}>{formatModelOption(option)}</option>
              )) : (
                <option value="">请先在系统设置中添加模型</option>
              )}
            </select>
            <p className="mt-2 text-[10px] leading-relaxed text-neutral-500">
              该模型会作为研报生成、专家团默认推理和总结审稿的本次默认路由。
            </p>
          </div>

          <div className="mt-auto pt-4 border-t border-white/5 flex flex-col gap-4">
            {/* 载入历史任务: 从圆桌/任务中心跳转来的结果可在此按 task_id 打开 */}
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] font-medium text-neutral-500 select-none">
                载入历史任务
              </label>
              <div className="flex gap-1.5">
                <input
                  value={loadTaskId}
                  onChange={(e) => setLoadTaskId(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void loadExistingTask();
                  }}
                  placeholder="粘贴任务 ID"
                  className="h-8 min-w-0 flex-1 rounded-lg border border-white/10 bg-black/40 px-2 text-[11px] text-neutral-300 outline-none focus:border-indigo-500/50 placeholder:text-neutral-600"
                />
                <button
                  type="button"
                  onClick={loadExistingTask}
                  disabled={!loadTaskId.trim() || isLoadingTask || isGenerating}
                  className="h-8 shrink-0 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-[11px] text-neutral-300 hover:border-indigo-400/40 hover:text-indigo-200 disabled:opacity-40"
                >
                  {isLoadingTask ? '载入中' : '载入'}
                </button>
              </div>
              {loadError && (
                <p className="text-[10px] text-rose-400">{loadError}</p>
              )}
            </div>

            <button
              data-testid="report-generate-button"
              onClick={startGeneration}
              disabled={isGenerating}
              className={cn(
                "w-full py-3.5 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 cursor-pointer shadow-md tracking-wide grow-0 text-center",
                isGenerating 
                  ? "bg-indigo-950/40 border border-indigo-500/20 text-indigo-400 cursor-not-allowed" 
                  : "bg-indigo-600 hover:bg-indigo-500 text-white border border-indigo-500"
              )}
            >
              <Sparkles className="w-4 h-4 text-indigo-200 animate-pulse" />
              {isGenerating ? 'AI 正在生成报告...' : analysisResult ? '更新研究' : '开始研究'}
            </button>
          </div>
        </div>

        {/* Right Preview Panel - Takes 2 Columns */}
        <div className="flex flex-col min-h-[320px] min-w-0 lg:min-h-0 relative">
          
          <AnimatePresence mode="wait">
            
            {/* Loading/Generation Status State in layout */}
            {isGenerating && (
              <motion.div
                key="generating"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="absolute inset-0 flex flex-col items-center justify-center p-10 bg-black/60 backdrop-blur-sm z-30 font-sans"
              >
                <div className="relative w-20 h-20 flex items-center justify-center mb-8">
                  <motion.div 
                    animate={{ rotate: 360 }}
                    transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
                    className="absolute inset-0 border-2 border-dashed border-indigo-500/30 border-t-indigo-500 rounded-full"
                  />
                  <div className="absolute inset-2 bg-indigo-500/10 rounded-full flex items-center justify-center">
                    <FileText className="w-8 h-8 text-indigo-400 animate-bounce" />
                  </div>
                </div>

                <h3 className="text-lg font-semibold text-white mb-2">智能分析与排版中 ({Math.round(progressPercent)}%)</h3>
                {generationStatus && (
                  <p className="mb-4 max-w-md text-center text-[11px] leading-relaxed text-neutral-400">
                    {generationStatus}
                  </p>
                )}
                <div className="w-64 h-1 bg-white/10 rounded-full mb-8 overflow-hidden">
                  <motion.div 
                    className="h-full bg-indigo-500" 
                    initial={{ width: 0 }}
                    animate={{ width: `${progressPercent}%` }}
                    transition={{ ease: "linear" }}
                  />
                </div>

                <div className="w-full max-w-md space-y-4 font-mono text-[11px]">
                  {steps.map((st, index) => {
                    const isDone = generationStep > index;
                    const isActive = generationStep === index;
                    return (
                      <div 
                        key={index} 
                        className={cn(
                          "flex gap-3 p-3 rounded-lg border text-left transition-all",
                          isActive ? "bg-indigo-500/10 border-indigo-500/30 text-indigo-300" :
                          isDone ? "bg-black/30 border-emerald-500/20 text-emerald-400" :
                          "bg-black/10 border-white/5 text-neutral-600"
                        )}
                      >
                        <div className="h-5 w-5 rounded-full border border-current flex items-center justify-center shrink-0 text-xs font-bold font-mono">
                          {isDone ? '✓' : index + 1}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h4 className="font-bold flex items-center gap-1.5 leading-tight">
                            {st.label}
                            {isActive && <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-ping"></span>}
                          </h4>
                          <p className="text-[10px] text-neutral-500 leading-normal mt-0.5">{st.desc}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}

            {/* Generated Report State */}
            {analysisResult && !isGenerating ? (
              <motion.div
                key="generated"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                className="lg:flex-1 flex flex-col lg:min-h-0 bg-[#0c0c0c] lg:overflow-y-auto custom-scrollbar p-2 sm:p-4 lg:p-5"
              >
                <div className="mx-auto w-full max-w-5xl">

                  {/* 导出操作栏 */}
                  <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <h3 className="break-words text-lg font-semibold text-neutral-100">{reportContext?.stock_name || reportContext?.stock_symbol || '研究报告'}<span className="ml-2 text-sm font-normal text-neutral-400">{reportContext?.stock_symbol}</span></h3>
                      <p className="mt-2 break-words text-sm leading-relaxed text-neutral-300">{reportContext?.research_question || analysisResult.research_snapshot?.research_question || '研究问题未记录'}</p>
                      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500"><span>{reportContext?.number ? `V${reportContext.number}` : versionId ? `版本 ${versionId.slice(0, 8)}` : '历史任务'}</span><span>截止日 {analysisResult.research_snapshot?.effective_as_of || reportContext?.as_of || '未记录'}</span></p>
                    </div>
                    {currentTaskId && (
                      <a
                        href={getReportExportUrl(currentTaskId)}
                        target="_blank"
                        rel="noreferrer"
                        download
                        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-white/10 text-neutral-300 transition-colors hover:border-emerald-400/40 hover:text-emerald-200"
                        title="下载 Markdown 研报"
                        aria-label="下载 Markdown 研报"
                      >
                        <Download className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>

                  <ResearchStatusStrip result={analysisResult} progress={reviewProgress} />
                  <div role="tablist" aria-label="报告视图" className="sticky top-0 z-10 mb-5 flex border-b border-white/15 bg-[#0c0c0c]">
                    {REPORT_VIEWS.map(([key, label], index) => <button type="button" key={key} id={`report-tab-${key}`} role="tab" aria-selected={reportView === key} aria-controls={`report-panel-${key === 'compare' ? 'review' : key}`} tabIndex={reportView === key ? 0 : -1} onClick={() => setReportView(key)} onKeyDown={event => {
                      const next = event.key === 'ArrowRight' ? (index + 1) % REPORT_VIEWS.length : event.key === 'ArrowLeft' ? (index + REPORT_VIEWS.length - 1) % REPORT_VIEWS.length : event.key === 'Home' ? 0 : event.key === 'End' ? REPORT_VIEWS.length - 1 : -1;
                      if (next >= 0) { event.preventDefault(); setReportView(REPORT_VIEWS[next][0]); document.getElementById(`report-tab-${REPORT_VIEWS[next][0]}`)?.focus(); }
                    }} className={cn('min-h-12 flex-1 border-b-2 px-1 text-sm transition-colors', reportView === key ? 'border-sky-400 text-sky-300' : 'border-transparent text-neutral-400 hover:text-neutral-100')}>{label}</button>)}
                  </div>
                  <div role="tabpanel" id="report-panel-overview" aria-labelledby="report-tab-overview" hidden={reportView !== 'overview'}>
                  <DecisionSummary
                    stockSymbol={reportContext?.stock_symbol || ''}
                    stockName={reportContext?.stock_name || ''}
                    result={analysisResult}
                  />
                  <GeneratedResearchReport view="overview" result={analysisResult} onOpenModelSettings={onOpenModelSettings} />
                  </div>
                  <div role="tabpanel" id="report-panel-sources" aria-labelledby="report-tab-sources" hidden={reportView !== 'sources'}>
                  <ResearchSnapshotBar snapshot={analysisResult.research_snapshot} />
                  <ResearchTrustPanel trust={analysisResult.research_trust} />
                  <GeneratedResearchReport view="sources" result={analysisResult} />
                  <FieldSourceTable result={analysisResult} />
                  <SourceTracePanel traces={analysisResult.provider_traces} />
                  <EvidenceAppendix result={analysisResult} />
                  </div>
                  <div role="tabpanel" id="report-panel-review" aria-labelledby={`report-tab-${reportView === 'compare' ? 'compare' : 'review'}`} hidden={reportView !== 'review' && reportView !== 'compare'}>
                    {versionId ? <ResearchReviewPanel key={versionId} versionId={versionId} view={reportView === 'compare' ? 'compare' : 'review'} visible={reportView === 'review' || reportView === 'compare'} onDirtyChange={value => { reviewDirty.current = value; }} onProgress={setReviewProgress} onVersion={version => setReportContext({ ...version.input, number: version.number })} /> : <p className="py-5 text-sm text-neutral-400">此历史任务没有研究版本，无法进行逐条复核或版本对比。</p>}
                  </div>
                  <div role="tabpanel" id="report-panel-full" aria-labelledby="report-tab-full" hidden={reportView !== 'full'}>
                  {reportView === 'full' && <GeneratedResearchReport view="full" result={analysisResult} symbol={reportContext?.stock_symbol} stockName={reportContext?.stock_name} onOpenModelSettings={onOpenModelSettings} />}
                  {/* P0: Agent Opinions */}
                  <div className="my-7 border-t border-white/5 pt-7">
                    <h3 className="text-sm font-semibold text-white/80 mb-4 uppercase tracking-wider flex items-center gap-2">
                      <Award className="w-4 h-4 text-indigo-400" />
                      专家会签明细
                    </h3>
                    <AgentOpinionCards agents={analysisResult.agents} evidencePool={analysisResult.evidence_pool} />
                  </div>

                  </div>
                </div>
              </motion.div>
            ) : !isGenerating && generationError ? (
              <motion.div
                key="error"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex-1 flex flex-col justify-center items-center text-center p-12 text-neutral-500 font-sans gap-4 z-20"
              >
                <div className="w-16 h-16 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center shadow-md">
                  <AlertTriangle className="w-8 h-8 text-rose-300" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-neutral-100">报告生成没有完成</h3>
                  <p className="mt-2 max-w-lg text-xs leading-relaxed text-neutral-400">
                    {generationError}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={startGeneration}
                  className="mt-2 rounded-xl border border-indigo-500/40 bg-indigo-500/10 px-4 py-2 text-xs font-semibold text-indigo-200 transition-colors hover:border-indigo-400 hover:bg-indigo-500/20"
                >
                  重新开始研究
                </button>
              </motion.div>
            ) : !isGenerating ? (
              // Idle state
              <motion.div
                key="idle"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                className="flex-1 flex flex-col justify-center items-center text-center p-12 text-neutral-500 font-sans gap-3.5 z-20"
              >
                <div className="w-16 h-16 rounded-full bg-white/[0.02] border border-white/5 flex items-center justify-center animate-pulse shadow-md">
                  <FileCheck className="w-8 h-8 text-neutral-600" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-neutral-300">尚无研究报告</h3>
                </div>
              </motion.div>
            ) : null}

          </AnimatePresence>
        </div>

      </div>

    </motion.div>
  );
}
