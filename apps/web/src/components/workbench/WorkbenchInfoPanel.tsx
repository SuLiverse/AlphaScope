/**
 * Workbench bottom info panel: news / finance / funds / quant tabs.
 */
import { motion, AnimatePresence } from "motion/react";
import { cn } from "../../lib/utils";
import { formatStockLabel, type StockTarget } from "../../lib/stocks";
import {
  PANEL_TABS,
  metricToneClass,
  type MetricCard,
  type PanelNewsItem,
  type PanelTabId,
} from "./support";

export interface WorkbenchInfoPanelProps {
  activePanelTab: PanelTabId;
  handlePanelTabChange: (tab: PanelTabId) => void;
  infoStatus: Record<PanelTabId, string>;
  stockNews: PanelNewsItem[];
  financeCards: MetricCard[];
  fundFlowCards: MetricCard[];
  quantCards: MetricCard[];
  currentStock: StockTarget;
  handlePanelItemSelect: (title: string, detail: string) => void;
}

export function WorkbenchInfoPanel({
  activePanelTab,
  handlePanelTabChange,
  infoStatus,
  stockNews,
  financeCards,
  fundFlowCards,
  quantCards,
  currentStock,
  handlePanelItemSelect,
}: WorkbenchInfoPanelProps) {
  return (
    <div className="bg-white/[0.04] border border-white/5 rounded-2xl overflow-hidden shadow-2xl flex flex-col h-[380px]">
      <div className="flex items-center gap-8 px-6 border-b border-white/5 bg-white/[0.01] pt-1">
        {PANEL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            data-testid={`workbench-info-tab-${tab.id}`}
            onClick={() => handlePanelTabChange(tab.id)}
            className={cn(
              "flex items-center gap-2 py-4 text-xs font-medium border-b-2 transition-colors relative focus:outline-none focus:ring-2 focus:ring-indigo-500/40",
              activePanelTab === tab.id
                ? "border-indigo-400 text-indigo-400"
                : "border-transparent text-neutral-500 hover:text-neutral-300",
            )}
          >
            <tab.icon
              className={cn(
                "w-4 h-4",
                activePanelTab === tab.id
                  ? "text-indigo-400 drop-shadow-[0_0_5px_rgba(129,140,248,0.5)]"
                  : "text-neutral-600",
              )}
            />
            {tab.label}
            {activePanelTab === tab.id && (
              <motion.div
                layoutId="activeTabIndicator"
                className="absolute bottom-[-2px] left-0 right-0 h-[2px] bg-indigo-400 shadow-[0_0_10px_rgba(129,140,248,0.8)]"
              />
            )}
          </button>
        ))}
      </div>
      <div className="border-b border-white/5 bg-black/30 px-5 py-2 text-[10px] font-mono text-neutral-500">
        {infoStatus[activePanelTab]}
      </div>
      <div className="flex-1 overflow-y-auto p-4 bg-black/40 custom-scrollbar">
        <AnimatePresence mode="wait">
          {activePanelTab === "news" && (
            <motion.div
              key="news"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              {stockNews.length === 0 && (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-100/80">
                  当前标的暂无可用资讯。可在新闻聚合页按股票名称或代码拉取外部新闻；本面板不会再用模板新闻替代真实结果。
                </div>
              )}
              {stockNews.map((news, i) => (
                <button
                  key={`${news.time}-${news.title}`}
                  type="button"
                  data-testid={`workbench-news-item-${i}`}
                  onClick={() =>
                    handlePanelItemSelect(
                      news.title,
                      `${news.detail}。该资讯已关联 ${formatStockLabel(currentStock)}。`,
                    )
                  }
                  className="w-full px-4 py-3 text-left border-b border-white/5 hover:bg-white/[0.02] transition-colors cursor-pointer group focus:outline-none focus:bg-indigo-500/[0.04]"
                >
                  <div className="flex gap-4">
                    <div className="text-[10px] font-mono text-neutral-500 group-hover:text-neutral-400 mt-1 flex items-center gap-2">
                      {news.time}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20 text-[9px] font-mono uppercase">
                          {news.source}
                        </span>
                        <div className="w-1.5 h-1.5 rounded-full bg-white/10"></div>
                      </div>
                      <h4 className="text-sm text-neutral-200 font-medium leading-relaxed group-hover:text-indigo-300 transition-colors">
                        {news.title}
                      </h4>
                      {news.desc && <p className="text-xs text-neutral-500 mt-1.5 leading-relaxed">{news.desc}</p>}
                    </div>
                  </div>
                </button>
              ))}
            </motion.div>
          )}

          {activePanelTab === "finance" && (
            <motion.div
              key="finance"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-4"
            >
              {financeCards.map((item, i) => (
                <button
                  key={item.label}
                  type="button"
                  data-testid={`workbench-finance-card-${i}`}
                  onClick={() =>
                    handlePanelItemSelect(
                      item.label,
                      `当前值 ${item.value}。${item.detail}。请结合 ${currentStock.name} 最新财报、行业均值和估值假设复核。`,
                    )
                  }
                  className="bg-white/[0.03] border border-white/5 p-4 rounded-xl flex flex-col justify-center hover:bg-white/[0.05] transition-colors text-left focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                >
                  <span className="text-xs text-neutral-500 mb-2">{item.label}</span>
                  <span className={cn("text-2xl font-mono font-medium", metricToneClass(item.tone))}>{item.value}</span>
                  <span className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-neutral-500">{item.detail}</span>
                </button>
              ))}
            </motion.div>
          )}

          {activePanelTab === "funds" && (
            <motion.div
              key="funds"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-4"
            >
              {fundFlowCards.map((item, i) => (
                <button
                  key={item.label}
                  type="button"
                  data-testid={`workbench-funds-card-${i}`}
                  onClick={() =>
                    handlePanelItemSelect(
                      item.label,
                      `${item.label} 当前为 ${item.value}。${item.detail}。资金项需要和换手率、价格方向、龙虎榜/两融数据交叉验证。`,
                    )
                  }
                  className="bg-white/[0.03] border border-white/5 p-4 rounded-xl flex flex-col justify-center hover:bg-white/[0.05] transition-colors text-left focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                >
                  <span className="text-xs text-neutral-500 mb-2">{item.label}</span>
                  <span className={cn("text-2xl font-mono font-medium", metricToneClass(item.tone))}>{item.value}</span>
                  <span className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-neutral-500">{item.detail}</span>
                </button>
              ))}
            </motion.div>
          )}

          {activePanelTab === "quant" && (
            <motion.div
              key="quant"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="grid h-full grid-cols-2 gap-4 p-4"
            >
              {quantCards.map((factor, i) => (
                <button
                  key={factor.label}
                  type="button"
                  data-testid={`workbench-quant-card-${i}`}
                  onClick={() =>
                    handlePanelItemSelect(factor.label, `${factor.detail}。该因子当前只作为研究辅助，不构成投资建议。`)
                  }
                  className="rounded-xl border border-indigo-500/20 bg-indigo-500/10 p-4 text-left text-indigo-200 transition-colors hover:bg-indigo-500/15 focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                >
                  <span className="block text-[10px] font-mono uppercase tracking-widest text-indigo-300/70">
                    {factor.label}
                  </span>
                  <span className={cn("mt-2 block text-2xl font-mono font-semibold", metricToneClass(factor.tone))}>
                    {factor.value}
                  </span>
                  <span className="mt-2 block text-[11px] leading-relaxed text-indigo-100/65">{factor.detail}</span>
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
