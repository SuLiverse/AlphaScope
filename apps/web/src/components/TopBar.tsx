import { useEffect, useMemo, useState } from 'react';
import { Bell, CheckCircle2, Loader2, Search, Wallet, X } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { dispatchStockSelected, subscribeStockSelected } from '../lib/workspaceEvents';
import { findStockTarget, formatStockLabel, resolveStockTarget, searchStockTargets, searchStockTargetsRemote } from '../lib/stocks';
import type { StockTarget } from '../lib/stocks';
import { cn } from '../lib/utils';
import { fetchApi } from '../lib/api';

interface CostWindow {
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

interface CostSummary {
  windows: { today: CostWindow; last_7d: CostWindow; last_30d: CostWindow; total: CostWindow };
  by_model: { model: string; vendor: string; calls: number; cost_usd: number }[];
  as_of: number;
}

const fmtUsd = (n: number) => `$${(n ?? 0).toFixed((n ?? 0) < 1 ? 4 : 2)}`;

interface AlertItem {
  alert_id: string;
  symbol: string;
  name: string;
  type: string;
  message: string;
  severity: string;
  timestamp: number;
  acknowledged: boolean;
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'border-rose-500/30 bg-rose-500/10',
  warning: 'border-amber-500/30 bg-amber-500/10',
  info: 'border-sky-500/30 bg-sky-500/10',
};

const fmtAlertTime = (ts: number) => {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return d.toLocaleDateString('zh-CN');
};

export function TopBar() {
  const [searchValue, setSearchValue] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [lastSelected, setLastSelected] = useState('贵州茅台 (600519.SH)');
  const [activeIndex, setActiveIndex] = useState(0);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [remoteSuggestions, setRemoteSuggestions] = useState<StockTarget[]>([]);
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [costOpen, setCostOpen] = useState(false);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [unackCount, setUnackCount] = useState(0);

  const localSuggestions = useMemo(() => searchStockTargets(searchValue, 6), [searchValue]);
  const suggestions = remoteSuggestions.length ? remoteSuggestions : localSuggestions;

  useEffect(() => {
    return subscribeStockSelected(({ stock }) => {
      const resolved = findStockTarget(stock.symbol) ?? stock;
      setLastSelected(formatStockLabel(resolved));
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      void fetchApi<CostSummary>('/api/diagnostics/cost-summary')
        .then((data) => {
          if (!cancelled) setCost(data);
        })
        .catch(() => {
          /* 成本展示为非关键信息，取数失败静默处理 */
        });
    };
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // 自选股监控告警:拉取数量(红点)+列表;每 30 秒刷新一次
  useEffect(() => {
    let cancelled = false;
    const loadCount = () => {
      void fetchApi<{ unacknowledged: number }>('/api/alerts/count')
        .then((data) => {
          if (!cancelled) setUnackCount(data?.unacknowledged ?? 0);
        })
        .catch(() => {
          /* 通知为非关键功能,静默 */
        });
    };
    const loadList = () => {
      void fetchApi<{ items: AlertItem[] }>('/api/alerts?limit=20')
        .then((data) => {
          if (!cancelled) setAlerts(data?.items ?? []);
        })
        .catch(() => {
          /* 静默 */
        });
    };
    loadCount();
    loadList();
    const timer = window.setInterval(() => {
      loadCount();
      if (noticeOpen) loadList();
    }, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [noticeOpen]);

  const ackAlert = (alertId: string) => {
    void fetchApi(`/api/alerts/${alertId}/ack`, { method: 'POST' }).then(() => {
      setAlerts((prev) =>
        prev.map((a) => (a.alert_id === alertId ? { ...a, acknowledged: true } : a)),
      );
      setUnackCount((c) => Math.max(0, c - 1));
    });
  };
  const ackAll = () => {
    void fetchApi('/api/alerts/ack-all', { method: 'POST' }).then(() => {
      setAlerts((prev) => prev.map((a) => ({ ...a, acknowledged: true })));
      setUnackCount(0);
    });
  };

  useEffect(() => {
    setActiveIndex(0);
  }, [searchValue]);

  useEffect(() => {
    let cancelled = false;
    const keyword = searchValue.trim();
    setRemoteSuggestions([]);
    if (!keyword) return undefined;

    const timer = window.setTimeout(() => {
      setIsResolving(true);
      void searchStockTargetsRemote(keyword, 8)
        .then((items) => {
          if (!cancelled) {
            setRemoteSuggestions(items);
          }
        })
        .finally(() => {
          if (!cancelled) {
            setIsResolving(false);
          }
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchValue]);

  const selectStock = async (value: string | StockTarget) => {
    setIsResolving(true);
    const stock = typeof value === 'string' ? await resolveStockTarget(value) : value;
    setIsResolving(false);
    if (!stock) return;

    const label = formatStockLabel(stock);
    setSearchValue(label);
    setLastSelected(label);
    setIsOpen(false);
    dispatchStockSelected(stock, 'topbar');
  };

  const clearSearch = () => {
    setSearchValue('');
    setIsOpen(true);
  };

  return (
    <header className="relative z-[80] h-[60px] flex-shrink-0 overflow-visible border-b border-white/[0.04] bg-[#06070c] px-6 text-neutral-400 shadow-[0_18px_60px_rgba(0,0,0,0.32)]">
      <div className="flex h-full items-center justify-between gap-6">
        <div className="flex min-w-0 flex-1 items-center gap-4">
          <div className="group relative z-[90] flex w-[min(42vw,36rem)] min-w-[20rem] max-w-[36rem] items-center">
            <Search className="w-4 h-4 absolute left-3.5 text-neutral-500 group-focus-within:text-indigo-400 transition-colors" />
            <input 
              data-testid="global-stock-search"
              type="text" 
              value={searchValue}
              onFocus={() => setIsOpen(true)}
              onBlur={() => window.setTimeout(() => setIsOpen(false), 120)}
              onChange={(e) => {
                setSearchValue(e.target.value);
                setIsOpen(true);
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  setIsOpen(true);
                  setActiveIndex((index) => Math.min(index + 1, Math.max(0, suggestions.length - 1)));
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setActiveIndex((index) => Math.max(0, index - 1));
                }
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void selectStock(searchValue);
                }
                if (e.key === 'Escape') {
                  setIsOpen(false);
                }
              }}
              placeholder="搜索标的 / 贵州茅台 (600519)" 
              className="w-full bg-white/[0.03] border border-white/[0.05] rounded-lg pl-10 pr-10 py-2 text-sm focus:outline-none focus:border-indigo-500/50 focus:bg-white/[0.05] transition-all text-neutral-200 placeholder:text-neutral-500 shadow-inner"
            />
            {searchValue && (
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={clearSearch}
                className="absolute right-2 rounded-md p-1 text-neutral-500 transition-colors hover:bg-white/5 hover:text-neutral-300"
                title="清空搜索"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
            {isResolving && (
              <Loader2 className="absolute right-9 h-3.5 w-3.5 animate-spin text-indigo-300" />
            )}
            {isOpen && suggestions.length > 0 && (
              <div className="custom-scrollbar absolute left-0 top-[calc(100%+0.75rem)] z-[120] max-h-[min(68vh,28rem)] w-full overflow-y-auto rounded-xl border border-indigo-500/25 bg-[#0b0c12] shadow-[0_24px_80px_rgba(0,0,0,0.72)] ring-1 ring-black/70">
                <div className="px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-neutral-500 border-b border-white/5">
                  选择后同步到 K线、多模态与研报模块
                </div>
                {suggestions.map((stock, index) => (
                  <button
                    key={stock.symbol}
                    data-testid={`stock-suggestion-${stock.symbol}`}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => void selectStock(stock)}
                    className={cn(
                      "w-full px-3 py-2.5 flex items-center justify-between gap-3 text-left transition-colors",
                      activeIndex === index ? "bg-indigo-500/10" : "hover:bg-white/[0.05]"
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block text-sm text-neutral-200 font-medium">{stock.name}</span>
                      <span className="block text-[10px] text-neutral-500 font-mono">{stock.sector} · {stock.market}</span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <span className="font-mono text-xs text-indigo-300">{stock.symbol}</span>
                      {stock.source === 'symbol-fallback' && (
                        <span className="rounded border border-amber-500/20 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-200">
                          待解析
                        </span>
                      )}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {isOpen && searchValue && !isResolving && suggestions.length === 0 && (
              <div className="absolute left-0 top-[calc(100%+0.75rem)] z-[120] w-full rounded-xl border border-amber-500/25 bg-[#0b0c12] px-3 py-3 text-xs text-amber-100 shadow-[0_24px_80px_rgba(0,0,0,0.72)] ring-1 ring-black/70">
                未找到匹配标的。可直接输入 6 位 A 股代码继续解析，也可以输入简称、行业或别名，例如 600519、301666、大微普、银行。
              </div>
            )}
          </div>
          <div className="h-5 w-px bg-white/10 mx-1"></div>
          <span className="hidden shrink-0 items-center gap-2 text-sm font-medium tracking-wide text-neutral-400 md:flex">
            A股 研究工作台
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-mono">PRO</span>
          </span>
          <span className="hidden xl:flex items-center gap-1.5 text-[11px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-1 rounded-full">
            <CheckCircle2 className="w-3.5 h-3.5" />
            已同步 {lastSelected}
          </span>
        </div>
        <div className="relative flex shrink-0 items-center gap-5">
          <div className="relative">
            <button
              type="button"
              onClick={() => setCostOpen((open) => !open)}
              title="LLM 调用成本(估算)"
              className="flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-[11px] font-medium text-amber-300 transition-colors hover:bg-amber-500/15"
            >
              <Wallet className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">LLM 今日</span>
              <span className="font-mono">{fmtUsd(cost?.windows?.today?.cost_usd ?? 0)}</span>
            </button>
            <AnimatePresence>
              {costOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98 }}
                  className="absolute right-0 top-11 z-[120] w-72 rounded-2xl border border-white/10 bg-[#0b0c12] p-4 shadow-2xl ring-1 ring-black/70"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-neutral-100">LLM 调用成本</h3>
                    <button
                      type="button"
                      onClick={() => setCostOpen(false)}
                      className="rounded-md p-1 text-neutral-500 hover:bg-white/5 hover:text-neutral-300"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    {([['今日', 'today'], ['近7天', 'last_7d'], ['近30天', 'last_30d'], ['累计', 'total']] as const).map(
                      ([label, key]) => (
                        <div key={key} className="rounded-lg border border-white/5 bg-white/[0.03] px-2.5 py-2">
                          <div className="text-neutral-500">{label}</div>
                          <div className="mt-0.5 font-mono text-amber-300">{fmtUsd(cost?.windows?.[key]?.cost_usd ?? 0)}</div>
                          <div className="text-[10px] text-neutral-600">{cost?.windows?.[key]?.calls ?? 0} 次调用</div>
                        </div>
                      ),
                    )}
                  </div>
                  {cost?.by_model?.length ? (
                    <div className="mt-3 border-t border-white/5 pt-2">
                      <div className="mb-1 text-[10px] uppercase tracking-widest text-neutral-500">按模型(累计)</div>
                      {cost.by_model.slice(0, 4).map((m) => (
                        <div key={`${m.vendor}/${m.model}`} className="flex items-center justify-between py-0.5 text-[11px]">
                          <span className="truncate text-neutral-300">{m.model}</span>
                          <span className="ml-2 shrink-0 font-mono text-amber-300/90">{fmtUsd(m.cost_usd)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3 border-t border-white/5 pt-2 text-[11px] text-neutral-500">暂无调用记录</div>
                  )}
                  <div className="mt-2 text-[10px] leading-relaxed text-neutral-600">估算值,基于各模型公开单价</div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <motion.button
            whileTap={{ scale: 0.95 }}
            onClick={() => setNoticeOpen((open) => !open)}
            className="relative p-2 hover:bg-white/5 rounded-lg transition-colors text-neutral-500 hover:text-neutral-300"
            title="查看自选股监控告警"
          >
            <Bell className="w-[18px] h-[18px]" />
            {unackCount > 0 && (
              <span className="absolute top-1 right-1 min-w-[16px] h-[16px] px-1 flex items-center justify-center rounded-full bg-rose-500 border-2 border-[#050505] text-[10px] font-semibold text-white">
                {unackCount > 99 ? '99+' : unackCount}
              </span>
            )}
          </motion.button>
          <AnimatePresence>
            {noticeOpen && (
              <motion.div
                initial={{ opacity: 0, y: -6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.98 }}
                className="absolute right-24 top-11 z-[120] w-[22rem] max-h-[28rem] flex flex-col rounded-2xl border border-white/10 bg-[#0b0c12] shadow-2xl ring-1 ring-black/70"
              >
                <div className="flex items-center justify-between p-4 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-100">
                    自选股监控
                    {unackCount > 0 && (
                      <span className="ml-2 text-[11px] font-normal text-rose-400">
                        {unackCount} 条未确认
                      </span>
                    )}
                  </h3>
                  <div className="flex items-center gap-1">
                    {unackCount > 0 && (
                      <button
                        type="button"
                        onClick={ackAll}
                        className="rounded-md px-2 py-1 text-[11px] text-neutral-400 hover:bg-white/5 hover:text-neutral-200"
                      >
                        全部已读
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setNoticeOpen(false)}
                      className="rounded-md p-1 text-neutral-500 hover:bg-white/5 hover:text-neutral-300"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
                  {alerts.length === 0 ? (
                    <div className="py-10 text-center">
                      <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-neutral-700" />
                      <p className="text-xs text-neutral-500">暂无告警</p>
                      <p className="mt-1 text-[10px] text-neutral-600">
                        把股票加入「自选晨报」后,系统会自动监控涨跌幅与量能异动
                      </p>
                    </div>
                  ) : (
                    alerts.map((a) => (
                      <div
                        key={a.alert_id}
                        className={cn(
                          'rounded-xl border p-3 transition-opacity',
                          SEVERITY_COLOR[a.severity] ?? 'border-white/5 bg-white/[0.03]',
                          a.acknowledged && 'opacity-40',
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium text-neutral-200">
                                {a.name || a.symbol}
                              </span>
                              <span className="text-[10px] text-neutral-600">
                                {a.type === 'price_change' ? '价格异动' : a.type === 'volume_spike' ? '量能异动' : a.type}
                              </span>
                            </div>
                            <p className="mt-1 text-[11px] leading-relaxed text-neutral-400">
                              {a.message}
                            </p>
                            <p className="mt-1 text-[10px] text-neutral-600">{fmtAlertTime(a.timestamp)}</p>
                          </div>
                          {!a.acknowledged && (
                            <button
                              type="button"
                              onClick={() => ackAlert(a.alert_id)}
                              className="shrink-0 rounded-md px-2 py-1 text-[10px] text-sky-400 hover:bg-sky-500/10"
                            >
                              已读
                            </button>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.1)]">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-[pulse_2s_ease-in-out_infinite] shadow-[0_0_5px_rgba(16,185,129,0.5)]"></div>
            <span className="text-[11px] font-medium tracking-wider">系统在线</span>
          </div>
        </div>
      </div>
    </header>
  );
}
