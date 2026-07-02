import React, { useState } from 'react';
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
  Archive
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

export function Sidebar({ currentTab, setCurrentTab }: SidebarProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const menuGroups: Array<{ title: string; items: MenuItem[] }> = [
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
      ]
    },
    {
      title: '量化研究引擎',
      items: [
        { id: 'tasks', label: '量化回测与执行', icon: Activity },
        { id: 'strategy_lab', label: '低代码策略编辑器', icon: Beaker },
        { id: 'fund_dca', label: '基金与定投研究室', icon: Coins },
        { id: 'valuation', label: '估值建模', icon: Calculator },
        { id: 'tickflow', label: '自定义数据表', icon: Webhook },
        { id: 'datalake', label: '数据湖', icon: Database },
        { id: 'factor_registry', label: '因子注册中心', icon: Sigma },
        { id: 'integration_center', label: '集成中心', icon: Boxes },
        { id: 'monitor', label: '系统监控中心', icon: Gauge },
      ]
    }
  ];

  return (
    <motion.aside 
      animate={{ width: isExpanded ? 220 : 72 }}
      style={{
        width: isExpanded ? 220 : 72,
        minWidth: isExpanded ? 220 : 72,
        maxWidth: isExpanded ? 220 : 72,
      }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="bg-black/40 border-r border-white/[0.02] flex flex-col items-center py-6 h-full z-20 flex-shrink-0"
    >
      <div className="mb-6 relative group flex-shrink-0">
        <div className="absolute inset-0 bg-indigo-500/20 rounded-xl blur-md group-hover:bg-indigo-500/40 transition-all duration-300"></div>
        <div className="relative w-11 h-11 bg-gradient-to-tr from-indigo-600 to-indigo-400 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-600/30 border border-indigo-400/30">
          <LineChart className="w-6 h-6 text-white" strokeWidth={2.5} />
        </div>
      </div>

      <div className="flex-1 w-full overflow-y-auto custom-scrollbar overflow-x-hidden">
        {menuGroups.map((group, idx) => (
          <div key={idx} className="mb-6">
            <AnimatePresence>
              {isExpanded && (
                <motion.div 
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="px-6 mb-3 text-[11px] font-mono text-neutral-500 font-medium tracking-wider whitespace-nowrap overflow-hidden"
                >
                  {group.title}
                </motion.div>
              )}
            </AnimatePresence>
            {!isExpanded && idx !== 0 && (
              <div className="w-6 h-px bg-white/10 mx-auto mb-4"></div>
            )}
            
            <nav className="flex flex-col gap-2 w-full px-3">
              {group.items.map((tab) => {
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
                      title={!isExpanded ? tab.label : undefined}
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
          </div>
        ))}
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
