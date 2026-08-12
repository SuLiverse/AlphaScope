import React, { lazy, Suspense, useEffect, useState } from 'react';
import { Onboarding } from './components/Onboarding';
import { GoldenPathTour } from './components/GoldenPathTour';
import { subscribeTabChange } from './lib/workspaceEvents';
import { ApiRequestError, fetchApi, LOCAL_API_TOKEN, storeLocalToken } from './lib/api';
import type { ErrorInfo, FormEvent, ReactNode } from 'react';
import { KeepAlive } from './components/KeepAlive';
import { MobileNav, Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { Workbench } from './components/Workbench';
import type { TabID } from './types';

const AgentsSystem = lazy(() => import('./components/AgentsSystem').then((module) => ({ default: module.AgentsSystem })));
const Portfolio = lazy(() => import('./components/Portfolio').then((module) => ({ default: module.Portfolio })));
const Backtesting = lazy(() => import('./components/Backtesting').then((module) => ({ default: module.Backtesting })));
const StrategyLab = lazy(() => import('./components/StrategyLab').then((module) => ({ default: module.StrategyLab })));
const FundDcaLab = lazy(() => import('./components/FundDcaLab').then((module) => ({ default: module.FundDcaLab })));
const NewsAggregator = lazy(() => import('./components/NewsAggregator').then((module) => ({ default: module.NewsAggregator })));
const MultimodalChart = lazy(() => import('./components/MultimodalChart').then((module) => ({ default: module.MultimodalChart })));
const ReportGenerator = lazy(() => import('./components/ReportGenerator').then((module) => ({ default: module.ReportGenerator })));
const EvidenceChain = lazy(() => import('./components/EvidenceChain').then((module) => ({ default: module.EvidenceChain })));
const Settings = lazy(() => import('./components/Settings').then((module) => ({ default: module.Settings })));
const PlaceholderModule = lazy(() => import('./components/PlaceholderModule').then((module) => ({ default: module.PlaceholderModule })));
const Valuation = lazy(() => import('./components/Valuation').then((module) => ({ default: module.Valuation })));
const DragonTiger = lazy(() => import('./components/DragonTiger').then((module) => ({ default: module.DragonTiger })));
const ExpertPanel = lazy(() => import('./components/ExpertPanel').then((module) => ({ default: module.ExpertPanel })));
const MorningBrief = lazy(() => import('./components/MorningBrief').then((module) => ({ default: module.MorningBrief })));
const MonitoringCenter = lazy(() => import('./components/MonitoringCenter').then((module) => ({ default: module.MonitoringCenter })));
const ResearchMemory = lazy(() => import('./components/ResearchMemory').then((module) => ({ default: module.ResearchMemory })));
const ReportArchive = lazy(() => import('./components/ReportArchive').then((module) => ({ default: module.ReportArchive })));
const TickFlowManager = lazy(() => import('./components/TickFlowManager').then((module) => ({ default: module.TickFlowManager })));
const DataLakeManager = lazy(() => import('./components/DataLakeManager').then((module) => ({ default: module.DataLakeManager })));
const FactorRegistry = lazy(() => import('./components/FactorRegistry').then((module) => ({ default: module.FactorRegistry })));
const IntegrationCenter = lazy(() => import('./components/IntegrationCenter').then((module) => ({ default: module.IntegrationCenter })));
const EvidenceAggregator = lazy(() => import('./components/EvidenceAggregator').then((module) => ({ default: module.EvidenceAggregator })));

const VISIBLE_TABS: TabID[] = ['dashboard', 'workbench', 'agents', 'experts', 'market', 'tasks', 'strategy_lab', 'fund_dca', 'news', 'chart', 'detailed', 'saved', 'valuation', 'dragon_tiger', 'investors', 'brief', 'monitor', 'research_memory', 'report_archive', 'tickflow', 'datalake', 'factor_registry', 'integration_center', 'evidence_aggregator', 'settings'];

function initialTabFromUrl(): TabID {
  if (typeof window === 'undefined') return 'dashboard';
  const tab = new URLSearchParams(window.location.search).get('tab') as TabID | null;
  return tab && VISIBLE_TABS.includes(tab) ? tab : 'dashboard';
}

function ModuleLoading() {
  return (
    <div className="flex h-full min-h-[420px] items-center justify-center px-6">
      <div className="flex items-center gap-3 text-sm text-neutral-500">
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80 animate-pulse" />
        <span>模块加载中...</span>
      </div>
    </div>
  );
}

function ModuleLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex h-full min-h-[420px] items-center justify-center px-6">
      <div className="max-w-sm rounded-lg border border-red-500/20 bg-red-500/10 p-5 text-center">
        <div className="text-sm font-medium text-red-100">模块加载失败</div>
        <p className="mt-2 text-sm text-red-100/70">网络或缓存异常，请重试。</p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-lg border border-red-300/20 bg-red-400/10 px-3 py-2 text-sm text-red-50 transition-colors hover:bg-red-400/20"
          >
            重试
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-neutral-200 transition-colors hover:bg-white/10"
          >
            刷新页面
          </button>
        </div>
      </div>
    </div>
  );
}

interface ModuleErrorBoundaryProps {
  children: ReactNode;
  resetKey: TabID;
}

interface ModuleErrorBoundaryState {
  error: Error | null;
}

class ModuleErrorBoundary extends React.Component<ModuleErrorBoundaryProps, ModuleErrorBoundaryState> {
  override state: ModuleErrorBoundaryState = { error: null };

  constructor(props: ModuleErrorBoundaryProps) {
    super(props);
  }

  static getDerivedStateFromError(error: Error): ModuleErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Module failed to load', error, info.componentStack);
  }

  override componentDidUpdate(prevProps: ModuleErrorBoundaryProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  retry = () => {
    this.setState({ error: null });
  };

  override render() {
    if (this.state.error) {
      return <ModuleLoadError onRetry={this.retry} />;
    }

    return this.props.children;
  }
}

type GateState = 'checking' | 'locked' | 'ready';

function TokenGate({ rejected, onSubmit }: { rejected: boolean; onSubmit: (token: string) => void }) {
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const value = token.trim();
    if (!value || submitting) return;
    setSubmitting(true);
    onSubmit(value);
  };

  return (
    <div className="flex h-screen w-full items-center justify-center bg-[#07080b] px-6 font-sans">
      <div className="w-full max-w-sm rounded-lg border border-indigo-500/20 bg-white/5 p-6">
        <h1 className="text-base font-medium text-neutral-100">需要本地访问令牌</h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral-400">
          本地令牌不会随静态页面分发。请查看部署目录
          <code className="mx-1 rounded bg-white/10 px-1 py-0.5 text-xs text-neutral-300">data/runtime/local_api_token.txt</code>
          ，或根目录
          <code className="mx-1 rounded bg-white/10 px-1 py-0.5 text-xs text-neutral-300">.env</code>
          中的
          <code className="mx-1 rounded bg-white/10 px-1 py-0.5 text-xs text-neutral-300">ALPHASCOPE_LOCAL_API_TOKEN</code>
          中查看，粘贴后仅存于当前页面会话（关页即清）。
        </p>
        {rejected && <p className="mt-3 text-sm text-red-300">令牌无效，请重新输入。</p>}
        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="粘贴本地访问令牌"
            autoFocus
            className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-neutral-100 placeholder-neutral-500 outline-none transition-colors focus:border-indigo-400/50"
          />
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-indigo-500/90 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:opacity-50"
          >
            {submitting ? '验证中…' : '连接'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function App() {
  const [currentTab, setCurrentTab] = useState<TabID>(() => initialTabFromUrl());
  const [settingsInitialTab, setSettingsInitialTab] = useState<string>('api');

  // 轻量鉴权引导门：仅当需鉴权探测返回 401/403 时要求用户输入一次 token
  // （docker 远程部署下共享卷副本不再携带 token）。探测端点必须是读路径。
  const [gateState, setGateState] = useState<GateState>('checking');
  const [gateAttempt, setGateAttempt] = useState(0);
  const [gateRejected, setGateRejected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setGateRejected(false);
      try {
        await fetchApi('/api/settings/preferences');
        if (!cancelled) setGateState('ready');
      } catch (error) {
        if (cancelled) return;
        const unauthorized =
          error instanceof ApiRequestError && (error.status === 401 || error.status === 403);
        if (unauthorized) {
          setGateState('locked');
          setGateRejected(Boolean(LOCAL_API_TOKEN));
        } else {
          setGateState('ready');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [gateAttempt]);

  useEffect(() => subscribeTabChange((tab) => setCurrentTab(tab as TabID)), []);

  const handleTokenSubmit = (token: string) => {
    storeLocalToken(token);
    setGateState('checking');
    setGateAttempt((n) => n + 1);
  };

  if (gateState !== 'ready') {
    return (
      <div className="relative flex h-screen w-full overflow-hidden bg-[#07080b] font-sans text-neutral-300">
        {gateState === 'locked' ? (
          <TokenGate rejected={gateRejected} onSubmit={handleTokenSubmit} />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-neutral-500">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80 animate-pulse" />
              <span>正在连接服务…</span>
            </div>
          </div>
        )}
      </div>
    );
  }

  const openAgentSettings = () => {
    setSettingsInitialTab('agents');
    setCurrentTab('settings');
  };

  const openModelSettings = () => {
    setSettingsInitialTab('models');
    setCurrentTab('settings');
  };

  return (
    <div className="relative flex h-screen w-full overflow-hidden bg-[#07080b] font-sans text-neutral-300 selection:bg-indigo-500/30">
      <div className="pointer-events-none absolute inset-0 z-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.08)_0.7px,transparent_0.7px)] bg-[length:7px_7px] opacity-[0.018]" />
      
      <div className="relative z-10 flex w-full h-full">
        <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} />
        
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar />
          
          <main className="flex-1 overflow-hidden relative">
            <div className="custom-scrollbar h-full overflow-y-auto pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-0">
              <ModuleErrorBoundary resetKey={currentTab}>
                <Suspense fallback={<ModuleLoading />}>
                  {/* 切页优化：
                      1) 不再用 AnimatePresence mode="wait"（旧版会强制等退场动画 0.4s 才挂新页）；
                      2) 用 KeepAlive 缓存"无强布局副作用"的重型 tab（Workbench / Portfolio /
                         NewsAggregator / AgentsSystem / FundDcaLab / Valuation / DragonTiger /
                         ExpertPanel / MorningBrief / EvidenceChain），切回时秒显、不重新拉数据；
                      3) 有 canvas/强布局依赖或带 interval 的 tab（chart / detailed / tasks /
                         settings）仍按需挂载卸载，避免隐藏时尺寸为 0 或空转轮询。 */}
                  <KeepAlive
                    active={currentTab}
                    tabs={{
                      dashboard: () => <Workbench onOpenModelSettings={openModelSettings} />,
                      workbench: () => <Workbench onOpenModelSettings={openModelSettings} />,
                      agents: () => <AgentsSystem onOpenAgentSettings={openAgentSettings} />,
                      experts: () => <AgentsSystem onOpenAgentSettings={openAgentSettings} />,
                      market: () => <Portfolio />,
                      fund_dca: () => <FundDcaLab />,
                      news: () => <NewsAggregator onOpenModelSettings={openModelSettings} />,
                      valuation: () => <Valuation />,
                      dragon_tiger: () => <DragonTiger />,
                      investors: () => <ExpertPanel />,
                      brief: () => <MorningBrief />,
                      saved: () => <EvidenceChain />,
                    }}
                  />
                  {/* 非缓存类：按需挂载 */}
                  {currentTab === 'tasks' && (
                    <Backtesting key="backtesting" />
                  )}
                  {currentTab === 'strategy_lab' && (
                    <StrategyLab key="strategy_lab" />
                  )}
                  {currentTab === 'chart' && (
                    <MultimodalChart key="chart" onOpenModelSettings={openModelSettings} />
                  )}
                  {currentTab === 'detailed' && (
                    <ReportGenerator key="report" onOpenModelSettings={openModelSettings} />
                  )}
                  {currentTab === 'monitor' && (
                    <MonitoringCenter key="monitor" />
                  )}
                  {currentTab === 'research_memory' && (
                    <ResearchMemory key="research_memory" />
                  )}
                  {currentTab === 'report_archive' && (
                    <ReportArchive key="report_archive" />
                  )}
                  {currentTab === 'tickflow' && (
                    <TickFlowManager key="tickflow" />
                  )}
                  {currentTab === 'datalake' && (
                    <DataLakeManager key="datalake" />
                  )}
                  {currentTab === 'factor_registry' && (
                    <FactorRegistry key="factor_registry" />
                  )}
                  {currentTab === 'integration_center' && (
                    <IntegrationCenter key="integration_center" />
                  )}
                  {currentTab === 'evidence_aggregator' && (
                    <EvidenceAggregator key="evidence_aggregator" />
                  )}
                  {currentTab === 'settings' && (
                    <Settings key="settings" initialTab={settingsInitialTab} />
                  )}
                  {!VISIBLE_TABS.includes(currentTab) &&
                    !['dashboard', 'workbench', 'agents', 'experts', 'market', 'fund_dca', 'news', 'valuation', 'dragon_tiger', 'investors', 'brief', 'saved'].includes(currentTab) && (
                    <PlaceholderModule key="placeholder" tab={currentTab} />
                  )}
                </Suspense>
              </ModuleErrorBoundary>
          </div>
        </main>
      </div>
      <MobileNav currentTab={currentTab} setCurrentTab={setCurrentTab} />
    </div>
    <Onboarding />
    <GoldenPathTour onNavigate={(tab) => setCurrentTab(tab as TabID)} />
  </div>
);
}
