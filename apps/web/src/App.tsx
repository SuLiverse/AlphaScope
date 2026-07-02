import React, { lazy, Suspense, useEffect, useState } from 'react';
import { Onboarding } from './components/Onboarding';
import { GoldenPathTour } from './components/GoldenPathTour';
import { subscribeTabChange } from './lib/workspaceEvents';
import type { ErrorInfo, ReactNode } from 'react';
import { KeepAlive } from './components/KeepAlive';
import { Sidebar } from './components/Sidebar';
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

const VISIBLE_TABS: TabID[] = ['dashboard', 'workbench', 'agents', 'experts', 'market', 'tasks', 'strategy_lab', 'fund_dca', 'news', 'chart', 'detailed', 'saved', 'valuation', 'dragon_tiger', 'investors', 'brief', 'monitor', 'research_memory', 'report_archive', 'tickflow', 'datalake', 'factor_registry', 'integration_center', 'settings'];

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

export default function App() {
  const [currentTab, setCurrentTab] = useState<TabID>('dashboard');
  const [settingsInitialTab, setSettingsInitialTab] = useState<string>('api');

  const openAgentSettings = () => {
    setSettingsInitialTab('agents');
    setCurrentTab('settings');
  };

  const openModelSettings = () => {
    setSettingsInitialTab('models');
    setCurrentTab('settings');
  };

  useEffect(() => subscribeTabChange((tab) => setCurrentTab(tab as TabID)), []);

  return (
    <div className="flex h-screen w-full bg-[#050505] text-neutral-300 font-sans selection:bg-indigo-500/30 overflow-hidden relative">
      {/* Absolute background effects */}
      <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[120px] mix-blend-screen mix-blend-lighten" />
        <div className="absolute bottom-0 right-1/4 w-[600px] h-[600px] bg-emerald-500/5 rounded-full blur-[150px] mix-blend-screen mix-blend-lighten" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.08)_0.7px,transparent_0.7px)] bg-[length:6px_6px] opacity-[0.025] mix-blend-overlay"></div>
      </div>
      
      <div className="relative z-10 flex w-full h-full">
        <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} />
        
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar />
          
          <main className="flex-1 overflow-hidden relative">
            <div className="h-full overflow-y-auto custom-scrollbar">
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
    </div>
    <Onboarding />
    <GoldenPathTour onNavigate={(tab) => setCurrentTab(tab as TabID)} />
  </div>
);
}
