import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ElementType } from 'react';
import {
  BarChart3,
  Bot,
  ChevronDown,
  Database,
  Globe,
  Network,
  Play,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Square,
  TrendingUp,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { cn } from '../lib/utils';
import {
  AgentConfig,
  AgentIconKey,
  AGENT_CONFIG_STORAGE_KEY,
  LEGACY_AGENT_CONFIG_STORAGE_KEY,
  getEnabledAgentRuntimeConfigs,
  loadAgentConfigs,
  saveAgentConfigs,
} from '../lib/agentConfigs';
import { fetchApi } from '../lib/api';
import { getPersistedStock, subscribeStockSelected } from '../lib/workspaceEvents';
import { STOCK_UNIVERSE, formatStockLabel } from '../lib/stocks';
import { stripSymbolSuffix, useTaskStream } from '../lib/dataFetch';

const ICON_MAP: Record<AgentIconKey, ElementType> = {
  macro: Globe,
  fundamental: BarChart3,
  quant: TrendingUp,
  risk: ShieldCheck,
  data: Database,
  execution: Play,
  custom: Bot,
};

interface AgentsSystemProps {
  onOpenAgentSettings?: () => void;
}

export function AgentsSystem({ onOpenAgentSettings }: AgentsSystemProps) {
  const [agents, setAgents] = useState<AgentConfig[]>(() => loadAgentConfigs());
  const [topologyOpen, setTopologyOpen] = useState(false);
  const [stock, setStock] = useState(() => getPersistedStock() ?? STOCK_UNIVERSE[0]);
  const [runningTaskCount, setRunningTaskCount] = useState<number>(0);
  const [analysisMode, setAnalysisMode] = useState<'auto' | 'standard' | 'deep'>('deep');
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const task = useTaskStream();

  useEffect(() => {
    saveAgentConfigs(agents);
  }, [agents]);

  useEffect(() => {
    const handleAgentConfigChange = (event: Event) => {
      const configs = (event as CustomEvent<AgentConfig[]>).detail;
      setAgents(Array.isArray(configs) ? configs : loadAgentConfigs());
    };
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === AGENT_CONFIG_STORAGE_KEY || event.key === LEGACY_AGENT_CONFIG_STORAGE_KEY) {
        setAgents(loadAgentConfigs());
      }
    };
    const unsubscribe = subscribeStockSelected(({ stock: nextStock }) => {
      setStock(nextStock);
    });
    window.addEventListener('agent-configs-changed', handleAgentConfigChange);
    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('agent-configs-changed', handleAgentConfigChange);
      window.removeEventListener('storage', handleStorageChange);
      unsubscribe();
    };
  }, []);

  const enabledAgents = useMemo(() => agents.filter((agent) => agent.enabled), [agents]);
  const enabledCount = enabledAgents.length;
  const runtimeConfigs = useMemo(() => getEnabledAgentRuntimeConfigs(agents), [agents]);

  const refreshRunningCount = useCallback(async () => {
    try {
      const res = await fetchApi<{ tasks?: unknown[]; total?: number }>('/api/tasks?status=running&limit=50');
      setRunningTaskCount(res.total ?? res.tasks?.length ?? 0);
    } catch {
      setRunningTaskCount(task.isRunning ? 1 : 0);
    }
  }, [task.isRunning]);

  useEffect(() => {
    void refreshRunningCount();
  }, [refreshRunningCount]);

  const handleRun = () => {
    if (!stock || task.isRunning) return;
    void task.run(stripSymbolSuffix(stock.symbol), stock.name, analysisMode);
  };
  const handleStop = () => {
    void task.cancel().then(() => void refreshRunningCount());
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="h-full flex flex-col p-4 text-neutral-300"
    >
      <div className="flex flex-col gap-4 px-2 mb-6 relative z-30 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-3xl font-display font-medium tracking-tight text-white mb-2 flex flex-wrap items-center gap-3">
            专家圆桌
            <span className="px-2 py-0.5 rounded text-[10px] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-mono tracking-wider align-middle">
              多Agent协同
            </span>
          </h2>
          <p className="text-sm text-neutral-400 font-mono">
            查看启用 Agent 与真实分析任务运行态；角色、提示词和数量请在系统设置中维护。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-lg border border-white/5 bg-black/40 px-3 py-2 text-xs font-mono text-neutral-400">
            标的：{formatStockLabel(stock)}
          </span>
          <div className="relative">
            <button
              type="button"
              data-testid="agents-mode-selector"
              onClick={() => setModeMenuOpen((open) => !open)}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs font-medium text-neutral-300 transition-colors hover:bg-white/[0.06]"
            >
              <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 shadow-[0_0_5px_rgba(99,102,241,0.5)]"></div>
              {analysisMode === 'auto' ? '自动模式' : analysisMode === 'standard' ? '标准分析' : '深度分析'}
              <ChevronDown className="h-3 w-3" />
            </button>
            <AnimatePresence>
              {modeMenuOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.98 }}
                  className="absolute right-0 top-10 z-50 w-64 overflow-hidden rounded-xl border border-white/10 bg-[#101010] shadow-2xl"
                >
                  {([
                    { id: 'auto', label: '自动模式', desc: '快速预筛, 信号强直接给结论, 分歧时升级深度' },
                    { id: 'standard', label: '标准分析', desc: '基本面/资金/技术面多 Agent 综合研判' },
                    { id: 'deep', label: '深度分析', desc: '买方深度调研 + 全专家团 + Critic 反证 + 主席 (最完整)' },
                  ] as const).map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      data-testid={`agents-mode-${m.id}`}
                      onClick={() => { setAnalysisMode(m.id); setModeMenuOpen(false); }}
                      className={cn(
                        'w-full px-3 py-3 text-left transition-colors',
                        analysisMode === m.id ? 'bg-indigo-500/10' : 'hover:bg-white/[0.04]'
                      )}
                    >
                      <span className="block text-xs font-medium text-neutral-100">{m.label}</span>
                      <span className="mt-1 block text-[10px] leading-relaxed text-neutral-500">{m.desc}</span>
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <button
            type="button"
            onClick={refreshRunningCount}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-medium text-neutral-300 transition-colors hover:bg-white/[0.06]"
          >
            <RefreshCw className={cn('h-4 w-4', task.isRunning && 'animate-spin')} />
            刷新
          </button>
          <button
            type="button"
            data-testid="agents-open-settings"
            onClick={onOpenAgentSettings}
            className="flex items-center gap-2 rounded-lg border border-indigo-500/25 bg-indigo-500/10 px-3 py-2 text-xs font-medium text-indigo-300 transition-colors hover:bg-indigo-500/15"
          >
            <Settings2 className="h-4 w-4" />
            到系统设置配置
          </button>
          <button
            type="button"
            onClick={() => setTopologyOpen((open) => !open)}
            className="flex items-center gap-2 rounded-lg border border-indigo-500/20 bg-indigo-500/10 px-3 py-2 text-xs font-medium text-indigo-400 shadow-[0_0_15px_rgba(99,102,241,0.1)] transition-colors hover:bg-indigo-500/20"
          >
            <Network className="h-4 w-4" />
            全网拓扑
          </button>
          {task.isRunning ? (
            <button
              type="button"
              onClick={handleStop}
              className="flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/15 px-4 py-2 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-500/25"
            >
              <Square className="h-4 w-4 fill-current" />
              停止分析
            </button>
          ) : (
            <button
              type="button"
              data-testid="agents-run-analysis"
              onClick={handleRun}
              disabled={enabledCount === 0}
              title={enabledCount === 0 ? '请先在系统设置启用至少一个 Agent' : '对当前标的运行启用的专家圆桌分析'}
              className="flex items-center gap-2 rounded-lg border border-indigo-500/50 bg-indigo-600 px-4 py-2 text-xs font-medium text-white shadow-[0_0_20px_rgba(99,102,241,0.2)] transition-all hover:bg-indigo-500 disabled:opacity-40"
            >
              <Play className="h-4 w-4 fill-current" />
              启动圆桌分析
            </button>
          )}
        </div>
      </div>

      {/* Real task progress / result banner */}
      <AnimatePresence>
        {(task.isRunning || task.message || task.error || task.result) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="relative z-10 mx-2 mb-5 overflow-hidden rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-4"
          >
            {task.isRunning && (
              <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-black/40">
                <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${task.progress}%` }} />
              </div>
            )}
            <div className="flex items-center gap-2 text-xs">
              {task.isRunning && <RefreshCw className="h-3.5 w-3.5 animate-spin text-indigo-400" />}
              <span className={cn('font-medium', task.error ? 'text-rose-300' : task.result ? 'text-emerald-300' : 'text-indigo-200')}>
                {task.error ? `分析失败：${task.error}` : task.result ? '圆桌分析完成，可在「研究报告」查看结果。' : task.message || '任务调度中...'}
              </span>
            </div>
            {task.status === 'pending' && task.taskId && (
              <p className="mt-1 font-mono text-[10px] text-neutral-500">任务 ID：{task.taskId}</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mx-2 mb-5 grid grid-cols-1 gap-3 md:grid-cols-3">
        {[
          ['已启用席位', `${enabledCount}/${agents.length}`, '进入分析请求的 Agent 数量。'],
          ['运行中任务', `${runningTaskCount}`, '后端 /api/tasks 实时运行态。'],
          ['请求配置', `${runtimeConfigs.length}`, '将写入 agent_configs 的配置项。'],
        ].map(([label, value, desc]) => (
          <div key={label} className="rounded-xl border border-white/5 bg-white/[0.02] px-4 py-3">
            <p className="text-[10px] font-mono tracking-wider text-neutral-500">{label}</p>
            <p className="mt-1 text-xl font-semibold text-white">{value}</p>
            <p className="mt-1 text-[11px] text-neutral-500">{desc}</p>
          </div>
        ))}
      </div>

      <AnimatePresence>
        {topologyOpen && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="relative z-10 mx-2 mb-6 rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-5"
          >
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-neutral-100">协作拓扑概览</h3>
                <p className="mt-1 text-xs text-neutral-500">
                  当前启用 {enabledCount} 个 Agent，后端运行态 {runningTaskCount} 个；设置页保存后会同步到本页和分析请求。
                </p>
              </div>
              <span className={cn('rounded-full border px-3 py-1 text-xs', task.isRunning ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-white/10 bg-black/30 text-neutral-400')}>
                {task.isRunning ? '调度器运行中' : '调度器待命'}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {[
                ['输入层', '行情、公告、新闻、研报与用户上传材料形成上下文。'],
                ['研判层', '启用的 Agent 按各自提示词、模型和温度参数参与圆桌。'],
                ['输出层', '结论汇入证据链、报告生成与工作台对话，并保留人工复核。'],
              ].map(([title, desc]) => (
                <div key={title} className="rounded-xl border border-white/5 bg-black/25 p-4">
                  <p className="text-xs font-semibold text-neutral-200">{title}</p>
                  <p className="mt-2 text-xs leading-relaxed text-neutral-500">{desc}</p>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-8 relative z-10 custom-scrollbar">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent, index) => {
            const Icon = ICON_MAP[agent.iconKey] ?? Bot;
            const participating = agent.enabled && task.isRunning;
            return (
              <motion.div
                key={agent.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: agent.enabled ? 1 : 0.55, scale: 1 }}
                transition={{ delay: index * 0.04, type: 'spring', stiffness: 300, damping: 24 }}
                className={cn(
                  'group relative flex min-h-[260px] flex-col overflow-hidden rounded-2xl border bg-white/[0.04] p-5 shadow-xl transition-all duration-300 hover:-translate-y-1 hover:bg-white/[0.06]',
                  participating ? 'border-indigo-500/35' : 'border-white/5 hover:border-indigo-500/25',
                  !agent.enabled && 'bg-black/20',
                )}
              >
                {participating && (
                  <motion.div
                    animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.6, 0.3] }}
                    transition={{ repeat: Infinity, duration: 2 }}
                    className="absolute top-0 right-0 w-40 h-40 bg-indigo-500/10 blur-[40px] rounded-full translate-x-1/3 -translate-y-1/3 pointer-events-none"
                  />
                )}

                <div className="relative z-10 mb-5 flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-4">
                    <div className={cn(
                      'flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border shadow-inner transition-colors',
                      participating
                        ? 'border-indigo-500/30 bg-gradient-to-tr from-indigo-600/20 to-indigo-400/10 text-indigo-400 shadow-[0_0_15px_rgba(99,102,241,0.2)]'
                        : 'border-white/5 bg-black/40 text-neutral-500 group-hover:text-neutral-400',
                    )}>
                      <Icon className="h-6 w-6" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate text-base font-semibold tracking-wide text-neutral-100">{agent.name}</h3>
                      <p className="truncate text-[10px] font-mono uppercase tracking-wider text-neutral-500">{agent.role}</p>
                    </div>
                  </div>

                  <div className={cn(
                    'shrink-0 rounded-md border px-2.5 py-1 text-[10px] font-mono',
                    participating
                      ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300'
                      : agent.enabled
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
                        : 'border-white/10 bg-black/30 text-neutral-500',
                  )}>
                    {participating ? '分析中' : agent.enabled ? '已就绪' : '停用'}
                  </div>
                </div>

                <div className="relative z-10 flex-1">
                  <p className="text-sm leading-relaxed text-neutral-400 transition-colors group-hover:text-neutral-300">
                    {agent.description}
                  </p>
                  <div className="mt-4 flex flex-wrap items-center gap-2 text-[10px] font-mono">
                    <span className="rounded border border-white/5 bg-white/[0.03] px-2 py-1 text-neutral-500">
                      {agent.provider ? `${agent.provider} / ${agent.model}` : agent.model}
                    </span>
                    <span className="rounded border border-white/5 bg-white/[0.03] px-2 py-1 text-neutral-500">
                      温度 {agent.temperature.toFixed(2)}
                    </span>
                  </div>
                </div>

                <div className="relative z-10 mt-5 flex items-center justify-between border-t border-white/5 pt-4">
                  <div className="flex min-w-0 max-w-[68%] flex-col gap-1">
                    <span className="text-[10px] font-mono tracking-wide text-neutral-500">运行态</span>
                    <span className={cn('truncate text-xs font-medium', participating ? 'text-indigo-300' : 'text-neutral-400')}>
                      {participating ? '跟随圆桌调度参与分析' : agent.enabled ? '待命，点击右上角启动圆桌分析' : '已在系统设置中停用'}
                    </span>
                  </div>
                  <div className={cn('flex h-10 w-10 items-center justify-center rounded-xl border', participating ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-400' : 'border-white/10 bg-black/40 text-neutral-500')}>
                    <Icon className="h-4 w-4" />
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
