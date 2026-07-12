import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { // Using as Logo
  LayoutGrid, 
  Newspaper, 
  BrainCircuit, 
  Bookmark, 
  Users,
  LineChart,
  Beaker,
  Settings,
  ChevronRight,
  ChevronLeft,
  Activity,
  ShieldAlert,
  FileText,
  Image as ImageIcon,
  Coins,
  Calculator,
  Swords,
  Sunrise,
  Gauge,
  History,
  Webhook,
  Database,
  Sigma,
  Boxes,
  Layers,
  Archive,
  Menu,
  X,
} from 'lucide-react';
import type { TabID } from '../types';
import { cn } from '../lib/utils';

interface SidebarProps {
  currentTab: TabID;
  setCurrentTab: (tab: TabID) => void;
}

type MenuItem = {
  id: TabID;
  label: string;
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
};

const MENU_GROUPS: Array<{ title: string; items: MenuItem[]; collapsible?: boolean }> = [
  {
    title: 'AI 投研体系',
    items: [
      { id: 'dashboard', label: '对话式研究', icon: LayoutGrid },
      { id: 'agents', label: '多Agent网络', icon: BrainCircuit },
      { id: 'market', label: '组合与风控', icon: ShieldAlert },
      { id: 'dragon_tiger', label: '龙虎榜/游资', icon: Swords },
      { id: 'investors', label: '投资人库', icon: Users },
      { id: 'brief', label: '自选晨报', icon: Sunrise },
      { id: 'news', label: '数据源终端聚合', icon: Newspaper },
      { id: 'chart', label: 'K线/多模态解析', icon: ImageIcon },
      { id: 'detailed', label: '研究报告生成', icon: FileText },
      { id: 'research_memory', label: '研究记忆', icon: History },
      { id: 'report_archive', label: '研究存档中心', icon: Archive },
      { id: 'saved', label: '投研逻辑证据链', icon: Bookmark },
    ],
  },
  {
    title: '量化研究引擎',
    items: [
      { id: 'tasks', label: '量化回测与执行', icon: Activity },
      { id: 'strategy_lab', label: '低代码策略编辑器', icon: Beaker },
      { id: 'fund_dca', label: '基金与定投研究室', icon: Coins },
      { id: 'valuation', label: '估值建模', icon: Calculator },
      { id: 'monitor', label: '系统监控中心', icon: Gauge },
    ],
  },
  {
    title: '高级工具',
    collapsible: true,
    items: [
      { id: 'evidence_aggregator', label: '多源证据聚合', icon: Layers },
      { id: 'tickflow', label: '自定义数据表', icon: Webhook },
      { id: 'datalake', label: '数据湖', icon: Database },
      { id: 'factor_registry', label: '因子注册中心', icon: Sigma },
      { id: 'integration_center', label: '集成中心', icon: Boxes },
    ],
  },
];

const MOBILE_PRIMARY_ITEMS: MenuItem[] = [
  MENU_GROUPS[0].items[0],
  MENU_GROUPS[0].items[1],
  MENU_GROUPS[0].items[8],
  MENU_GROUPS[1].items[0],
];

export function Sidebar({ currentTab, setCurrentTab }: SidebarProps) {
  const [isExpanded, setIsExpanded] = useState(() => {
    if (typeof window === 'undefined') return false;
    const saved = window.localStorage.getItem('alphascope.sidebar.expanded');
    return saved === null ? window.innerWidth >= 1366 : saved === 'true';
  });
  // 高级模块默认折叠图标栏；展开侧栏时若当前 tab 在高级组则自动展开该组
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const advancedIds = MENU_GROUPS.find((g) => g.collapsible)?.items.map((i) => i.id) ?? [];
  const showAdvanced = advancedOpen || advancedIds.includes(currentTab);

  useEffect(() => {
    window.localStorage.setItem('alphascope.sidebar.expanded', String(isExpanded));
  }, [isExpanded]);

  return (
    <motion.aside 
      animate={{ width: isExpanded ? 220 : 72 }}
      style={{
        width: isExpanded ? 220 : 72,
        minWidth: isExpanded ? 220 : 72,
        maxWidth: isExpanded ? 220 : 72,
      }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="hidden h-full flex-shrink-0 flex-col items-center border-r border-white/[0.04] bg-[#07080b]/95 py-6 md:flex"
    >
      <div className={cn('mb-6 flex h-11 w-full flex-shrink-0 items-center', isExpanded ? 'gap-3 px-4' : 'justify-center')}>
        <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-indigo-400/30 bg-indigo-500 text-white shadow-[0_8px_24px_rgba(79,70,229,0.3)]">
          <LineChart className="h-5 w-5" strokeWidth={2.5} />
        </div>
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -6 }}
              className="min-w-0 overflow-hidden whitespace-nowrap"
            >
              <div className="font-display text-sm font-semibold text-white">AlphaScope</div>
              <div className="mt-0.5 text-[10px] text-neutral-500">RESEARCH OS</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex-1 w-full overflow-y-auto custom-scrollbar overflow-x-hidden">
        {MENU_GROUPS.map((group, idx) => {
          const isAdvancedGroup = Boolean(group.collapsible);
          // 折叠侧栏：高级图标始终可点；展开侧栏：仅 showAdvanced 时列出高级项
          const itemsToShow =
            isAdvancedGroup && isExpanded && !showAdvanced ? [] : group.items;

          return (
          <div key={idx} className="mb-6">
            <AnimatePresence>
              {isExpanded && (
                <motion.div 
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="px-6 mb-3 text-[11px] font-mono text-neutral-500 font-medium tracking-wider whitespace-nowrap overflow-hidden"
                >
                  {isAdvancedGroup ? (
                    <button
                      type="button"
                      data-testid="nav-advanced-toggle"
                      onClick={() => setAdvancedOpen((v) => !v)}
                      className="flex w-full items-center justify-between gap-2 text-left text-neutral-500 hover:text-neutral-300"
                      title="高级工具（功能完整保留）"
                    >
                      <span>{group.title}</span>
                      <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', showAdvanced && 'rotate-90')} />
                    </button>
                  ) : (
                    group.title
                  )}
                </motion.div>
              )}
            </AnimatePresence>
            {!isExpanded && idx !== 0 && (
              <div className="w-6 h-px bg-white/10 mx-auto mb-4"></div>
            )}
            
            <nav className="flex flex-col gap-2 w-full px-3">
              {itemsToShow.map((tab) => {
                const Icon = tab.icon;
                const isActive = currentTab === tab.id || (currentTab === 'workbench' && tab.id === 'dashboard');
                return (
                    <button
                      key={tab.id}
                      data-testid={`nav-${tab.id}`}
                      onClick={() => setCurrentTab(tab.id)}
                      style={{ width: '100%' }}
                      className={cn(
                        'h-11 w-full flex items-center rounded-xl transition-all duration-300 relative group flex-shrink-0',
                        isExpanded ? 'px-3 justify-start' : 'justify-center',
                        isActive 
                          ? 'text-indigo-400' 
                          : 'text-neutral-500 hover:text-neutral-300 hover:bg-white/5'
                      )}
                      title={!isExpanded ? `${tab.label}${isAdvancedGroup ? '（高级）' : ''}` : undefined}
                    >
                      <div className="w-[22px] flex items-center justify-center flex-shrink-0 relative z-10">
                        <Icon className={cn("w-[22px] h-[22px] transition-transform duration-300", isActive ? "scale-110" : "group-hover:scale-110")} strokeWidth={isActive ? 2.5 : 2} />
                      </div>
                      
                      <AnimatePresence>
                        {isExpanded && (
                          <motion.span
                            initial={{ opacity: 0, width: 0, marginLeft: 0 }}
                            animate={{ opacity: 1, width: 'auto', marginLeft: 12 }}
                            exit={{ opacity: 0, width: 0, marginLeft: 0 }}
                            className="text-sm font-medium whitespace-nowrap overflow-hidden relative z-10"
                          >
                            {tab.label}
                          </motion.span>
                        )}
                      </AnimatePresence>

                      {isActive && (
                        <motion.div 
                          layoutId="sidebar-active"
                          className="absolute inset-0 bg-indigo-500/10 rounded-xl border border-indigo-500/20 shadow-[inset_0_1px_1px_rgba(255,255,255,0.1)]"
                          initial={false}
                          transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        />
                      )}
                      {isActive && (
                        <motion.div 
                          layoutId="sidebar-indicator"
                          className={cn(
                            "absolute top-1/2 -translate-y-1/2 w-1.5 h-6 bg-indigo-500 rounded-r-full shadow-[0_0_10px_rgba(99,102,241,0.5)]",
                            isExpanded ? "left-[-12px]" : "left-[-13px]"
                          )}
                          initial={false}
                          transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        />
                      )}
                    </button>
                );
              })}
            </nav>
            {isAdvancedGroup && isExpanded && !showAdvanced && (
              <button
                type="button"
                data-testid="nav-advanced-expand"
                onClick={() => setAdvancedOpen(true)}
                className="mx-3 mt-1 w-[calc(100%-1.5rem)] rounded-lg border border-dashed border-white/10 px-3 py-2 text-left text-[11px] text-neutral-500 hover:border-indigo-500/30 hover:text-neutral-300"
              >
                展开高级工具（{group.items.length}）
              </button>
            )}
          </div>
          );
        })}
      </div>

      <div className="mt-auto pt-4 flex flex-col gap-2 w-full px-3 flex-shrink-0">
        <button 
          data-testid="nav-settings"
          onClick={() => setCurrentTab('settings')}
          style={{ width: '100%' }}
          className={cn(
            'h-11 w-full flex items-center rounded-xl transition-all duration-300 relative group flex-shrink-0',
            isExpanded ? 'px-3 justify-start' : 'justify-center',
            currentTab === 'settings'
              ? 'text-indigo-400' 
              : 'text-neutral-500 hover:text-neutral-300 hover:bg-white/5'
          )}
          title={!isExpanded ? '属性设置' : undefined}
        >
          <div className="w-[22px] flex items-center justify-center flex-shrink-0 relative z-10">
             <Settings className={cn("w-[22px] h-[22px] transition-transform duration-300", currentTab === 'settings' ? "scale-110" : "group-hover:scale-110")} strokeWidth={currentTab === 'settings' ? 2.5 : 2} />
          </div>

          <AnimatePresence>
            {isExpanded && (
              <motion.span
                initial={{ opacity: 0, width: 0, marginLeft: 0 }}
                animate={{ opacity: 1, width: 'auto', marginLeft: 12 }}
                exit={{ opacity: 0, width: 0, marginLeft: 0 }}
                className="text-sm font-medium whitespace-nowrap overflow-hidden relative z-10"
              >
                属性设置
              </motion.span>
            )}
          </AnimatePresence>

          {currentTab === 'settings' && (
            <motion.div 
              layoutId="sidebar-active"
              className="absolute inset-0 bg-indigo-500/10 rounded-xl border border-indigo-500/20 shadow-[inset_0_1px_1px_rgba(255,255,255,0.1)]"
              initial={false}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
            />
          )}
          {currentTab === 'settings' && (
            <motion.div 
              layoutId="sidebar-indicator"
              className={cn(
                "absolute top-1/2 -translate-y-1/2 w-1.5 h-6 bg-indigo-500 rounded-r-full shadow-[0_0_10px_rgba(99,102,241,0.5)]",
                isExpanded ? "left-[-12px]" : "left-[-13px]"
              )}
              initial={false}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
            />
          )}
        </button>

        <button 
          onClick={() => setIsExpanded(!isExpanded)}
          className={cn(
            'h-11 flex items-center rounded-xl transition-all duration-300 relative group flex-shrink-0 text-neutral-500 hover:text-neutral-300 hover:bg-white/5',
            isExpanded ? 'px-3 justify-end' : 'justify-center'
          )}
          aria-label={isExpanded ? '收起导航栏' : '展开导航栏'}
          title={isExpanded ? '收起导航栏' : '展开导航栏'}
        >
          {isExpanded ? (
            <ChevronLeft className="w-5 h-5 group-hover:-translate-x-0.5 transition-transform" />
          ) : (
            <ChevronRight className="w-5 h-5 group-hover:translate-x-0.5 transition-transform" />
          )}
        </button>
      </div>
    </motion.aside>
  );
}

export function MobileNav({ currentTab, setCurrentTab }: SidebarProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [currentTab]);

  const navigate = (tab: TabID) => {
    setCurrentTab(tab);
    setMenuOpen(false);
  };

  const isActive = (tab: TabID) => currentTab === tab || (tab === 'dashboard' && currentTab === 'workbench');

  return (
    <>
      <AnimatePresence>
        {menuOpen && (
          <div className="fixed inset-0 z-[140] md:hidden">
            <motion.button
              type="button"
              aria-label="关闭全部功能"
              className="absolute inset-0 bg-black/70 backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMenuOpen(false)}
            />
            <motion.section
              role="dialog"
              aria-modal="true"
              aria-label="全部功能"
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', stiffness: 340, damping: 34 }}
              className="absolute inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] max-h-[72vh] overflow-y-auto rounded-t-lg border-t border-white/10 bg-[#0b0c10] px-4 pb-5 pt-4 shadow-[0_-24px_70px_rgba(0,0,0,0.65)]"
            >
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-white">全部功能</h2>
                  <p className="mt-0.5 text-xs text-neutral-500">研究、量化与数据工具</p>
                </div>
                <button
                  type="button"
                  onClick={() => setMenuOpen(false)}
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-neutral-400 hover:bg-white/5 hover:text-white"
                  aria-label="关闭"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {MENU_GROUPS.map((group) => (
                <div key={group.title} className="mb-5 last:mb-0">
                  <h3 className="mb-2 text-[11px] font-medium text-neutral-500">{group.title}</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => navigate(item.id)}
                          className={cn(
                            'flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-xs transition-colors',
                            isActive(item.id)
                              ? 'border-indigo-400/30 bg-indigo-500/12 text-indigo-200'
                              : 'border-white/[0.06] bg-white/[0.025] text-neutral-300 hover:bg-white/5',
                          )}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          <span className="min-w-0 leading-tight">{item.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}

              <button
                type="button"
                onClick={() => navigate('settings')}
                className={cn(
                  'mt-1 flex w-full items-center gap-2 rounded-lg border px-3 py-3 text-sm',
                  currentTab === 'settings'
                    ? 'border-indigo-400/30 bg-indigo-500/12 text-indigo-200'
                    : 'border-white/[0.06] bg-white/[0.025] text-neutral-300',
                )}
              >
                <Settings className="h-4 w-4" />
                系统设置
              </button>
            </motion.section>
          </div>
        )}
      </AnimatePresence>

      <nav className="fixed inset-x-0 bottom-0 z-[150] grid h-[calc(4rem+env(safe-area-inset-bottom))] grid-cols-5 border-t border-white/[0.07] bg-[#08090d]/95 px-1 pb-[env(safe-area-inset-bottom)] shadow-[0_-12px_40px_rgba(0,0,0,0.42)] backdrop-blur-xl md:hidden">
        {MOBILE_PRIMARY_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.id);
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => navigate(item.id)}
              className={cn(
                'relative flex min-w-0 flex-col items-center justify-center gap-1 text-[10px] transition-colors',
                active ? 'text-indigo-300' : 'text-neutral-500',
              )}
            >
              {active && <span className="absolute top-0 h-0.5 w-7 rounded-full bg-indigo-400" />}
              <Icon className="h-5 w-5" strokeWidth={active ? 2.4 : 2} />
              <span className="w-full truncate px-1">{item.label.replace('生成', '')}</span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          className={cn(
            'flex min-w-0 flex-col items-center justify-center gap-1 text-[10px] transition-colors',
            menuOpen ? 'text-indigo-300' : 'text-neutral-500',
          )}
          aria-expanded={menuOpen}
          aria-label="全部功能"
        >
          {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          <span>全部</span>
        </button>
      </nav>
    </>
  );
}
