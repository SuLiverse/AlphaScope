import { memo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ArrowUpRight, FileText, Filter, MessageCircle } from 'lucide-react';
import { cn, isHttpUrl } from '../lib/utils';

export interface NewsItem {
  id: string;
  time: string;
  title: string;
  category: 'macro' | 'announcement' | 'risk' | 'funds';
  source: string;
  sourceTier: '官方披露' | '主流媒体' | '数据终端' | '舆情/另类' | '研究兜底';
  sourceStatus?: 'real' | 'fallback' | 'degraded';
  sourceUrl?: string;
  severity: 'high' | 'medium' | 'info';
  sentiment: 'bullish' | 'bearish' | 'neutral';
  impactScore: number;
  content: string;
  aiSummary: string;
}

export interface NewsFeedListProps {
  items: NewsItem[];
  searchQuery: string;
  selectedId?: string;
  onActivate: (item: NewsItem) => void;
  onOpenDetail: (item: NewsItem) => void;
  onOpenSource: (item: NewsItem) => void;
  onAsk: (item: NewsItem) => void;
  onClearFilters: () => void;
}

/**
 * 新闻 feed 列表（纯渲染）：数据与回调均由父组件备好并保证引用稳定，
 * memo 后右侧面板（聊天输入等）的按键级重渲不会波及整棵 feed 树。
 */
export const NewsFeedList = memo(function NewsFeedList({
  items,
  searchQuery,
  selectedId,
  onActivate,
  onOpenDetail,
  onOpenSource,
  onAsk,
  onClearFilters,
}: NewsFeedListProps) {
  return (
    <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar bg-black/10 rounded-2xl border border-white/5 p-4 relative min-h-0">
      <AnimatePresence mode="popLayout">
        {items.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="h-full flex flex-col justify-center items-center text-center p-8 text-neutral-500 font-mono text-xs gap-3"
          >
            <Filter className="w-10 h-10 text-neutral-600 animate-pulse" />
            <p>未能检索到包含关键字 "{searchQuery}" 的核心公告或数据</p>
            <button
              type="button"
              data-testid="news-empty-reset"
              onClick={onClearFilters}
              className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-1.5 text-[11px] text-indigo-100 transition-colors hover:bg-indigo-500/20"
            >
              重置并显示全部资讯
            </button>
          </motion.div>
        ) : (
          items.map((item, idx) => {
            const isCurSelected = selectedId === item.id;
            return (
              <motion.div
                role="button"
                tabIndex={0}
                data-testid={`news-feed-item-${idx}`}
                key={item.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.04 }}
                onClick={() => onActivate(item)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onActivate(item);
                  }
                }}
                className={cn(
                  "p-4 mb-4 rounded-xl border transition-all cursor-pointer flex gap-4 relative group focus:outline-none focus:ring-2 focus:ring-indigo-500/40",
                  isCurSelected
                    ? "bg-indigo-500/10 border-indigo-500/40 shadow-[inset_0_1px_1px_rgba(255,255,255,0.05)]"
                    : "bg-white/[0.01] border-white/5 hover:border-white/15 hover:bg-white/[0.03]"
                )}
              >
                {/* Left Badge Indicator Column */}
                <div className="flex flex-col gap-2 items-center flex-shrink-0 w-12 text-center border-r border-white/5 pr-3">
                  <span className="text-xs font-mono font-medium text-neutral-400 group-hover:text-neutral-300">{item.time}</span>
                  <span className={cn(
                    "w-2 h-2 rounded-full",
                    item.severity === 'high' ? "bg-rose-500 animate-[pulse_1.5s_infinite] shadow-[0_0_8px_rgb(244,63,94)]" : "bg-neutral-500"
                  )} />

                  <div className={cn(
                    "text-[9px] font-mono uppercase px-1 py-0.5 rounded-sm shrink-0 border mt-1",
                    item.sentiment === 'bullish' ? 'bg-rose-950/20 border-rose-500/20 text-rose-400' :
                    item.sentiment === 'bearish' ? 'bg-emerald-950/20 border-emerald-500/20 text-emerald-400' :
                    'bg-neutral-900 border-white/5 text-neutral-500'
                  )}>
                    {item.sentiment === 'bullish' ? '利好' : item.sentiment === 'bearish' ? '偏空' : '中性'}
                  </div>
                </div>

                {/* Title / Description */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <span className="text-[10px] uppercase font-mono font-bold tracking-wider rounded px-1.5 py-0.5 bg-white/5 border border-white/10 text-indigo-400">
                      {item.source}
                    </span>
                    <span className={cn(
                      "text-[9px] rounded px-1.5 py-0.5 border font-mono",
                      item.sourceTier === '官方披露' ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" :
                      item.sourceTier === '数据终端' ? "border-indigo-500/20 bg-indigo-500/10 text-indigo-300" :
                      item.sourceTier === '主流媒体' ? "border-sky-500/20 bg-sky-500/10 text-sky-300" :
                      item.sourceTier === '舆情/另类' ? "border-amber-500/20 bg-amber-500/10 text-amber-300" :
                      "border-white/10 bg-white/5 text-neutral-400"
                    )}>
                      {item.sourceTier}
                    </span>
                    {item.sourceStatus === 'real' && (
                      <span className="rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-mono text-emerald-300">实时</span>
                    )}
                    <span className="text-[10px] font-mono text-neutral-500 flex items-center gap-1">
                      影响因子: <span className={cn(
                        "font-bold",
                        item.impactScore >= 80 ? "text-rose-400" : "text-indigo-400"
                      )}>{item.impactScore}%</span>
                    </span>
                  </div>
                  <h3 className="text-sm text-neutral-100 font-medium leading-relaxed group-hover:text-indigo-300 transition-colors mb-1.5">
                    {item.title}
                  </h3>
                  <p className="text-xs text-neutral-400 leading-relaxed max-w-3xl line-clamp-2">
                    {item.content}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      data-testid={`news-detail-button-${idx}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenDetail(item);
                      }}
                      className="inline-flex items-center gap-1 rounded-md border border-indigo-500/25 bg-indigo-500/10 px-2 py-1 text-[10px] text-indigo-100 transition-colors hover:bg-indigo-500/20"
                    >
                      <FileText className="h-3 w-3" />
                      详情
                    </button>
                    <button
                      type="button"
                      data-testid={`news-source-button-${idx}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenSource(item);
                      }}
                      className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-neutral-300 transition-colors hover:border-emerald-400/40 hover:text-emerald-200"
                    >
                      <ArrowUpRight className="h-3 w-3" />
                      {isHttpUrl(item.sourceUrl) ? '原文' : '检索'}
                    </button>
                    <button
                      type="button"
                      data-testid={`news-ask-button-${idx}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onAsk(item);
                      }}
                      className="inline-flex items-center gap-1 rounded-md border border-violet-500/25 bg-violet-500/10 px-2 py-1 text-[10px] text-violet-100 transition-colors hover:bg-violet-500/20"
                    >
                      <MessageCircle className="h-3 w-3" />
                      咨询
                    </button>
                  </div>
                </div>

                {/* Right subtle arrow */}
                <div className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-600 group-hover:text-indigo-400 transition-colors opacity-0 group-hover:opacity-100 transition-opacity">
                  <ArrowUpRight className="w-4 h-4" />
                </div>
              </motion.div>
            );
          })
        )}
      </AnimatePresence>
    </div>
  );
});
