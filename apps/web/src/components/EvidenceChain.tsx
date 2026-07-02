import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Bookmark,
  Sparkles,
  CheckCircle,
  Cpu,
  FileText,
  FolderLock,
  Plus,
  Coins,
  Newspaper,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { STOCK_UNIVERSE, StockTarget, findStockTarget, formatStockLabel } from '../lib/stocks';
import { dispatchStockSelected, getPersistedStock, subscribeStockSelected } from '../lib/workspaceEvents';
import { fetchApi } from '../lib/api';
import { getErrorMessage, stripSymbolSuffix } from '../lib/dataFetch';

type PillarId = 'fundamental' | 'quant' | 'sentiment' | 'liquidity';

// ---- Backend evidence item contract (backend/api/evidence.py + evidence_store.py) ----
interface EvidenceItem {
  id: string;
  evidence_type?: string;
  title: string;
  source?: string;
  source_url?: string;
  content_summary?: string;
  symbols?: string[];
  confidence?: number; // 0-1
  relevance?: number;  // 0-1
  claim?: string;
  data_date?: string;
  created_at?: number; // unix epoch
}

interface EvidenceNode extends EvidenceItem {
  pillar: PillarId;
  weight: number; // 1-10 derived from confidence
}

interface EvidenceCreateBody {
  evidence_type: string;
  title: string;
  source: string;
  claim: string;
  content_summary: string;
  symbols: string[];
  confidence: number;
  source_url?: string;
  data_date?: string;
  relevance?: number;
}

function classifyPillar(evidenceType?: string): PillarId {
  const t = (evidenceType || '').toLowerCase();
  if (t.includes('quant') || t.includes('factor') || t.includes('technical')) return 'quant';
  if (t.includes('sent') || t.includes('event') || t.includes('news') || t.includes('risk')) return 'sentiment';
  if (t.includes('liquid') || t.includes('flow') || t.includes('money')) return 'liquidity';
  return 'fundamental';
}

function toNode(item: EvidenceItem): EvidenceNode {
  const confidence = Number.isFinite(item.confidence) ? Math.max(0, Math.min(1, item.confidence as number)) : 0.5;
  return {
    ...item,
    pillar: classifyPillar(item.evidence_type),
    weight: Math.max(1, Math.round(confidence * 10)),
  };
}

function formatStamp(value?: number): string {
  if (!value || !Number.isFinite(value)) return '--';
  const d = new Date(value * 1000);
  if (Number.isNaN(d.getTime())) return '--';
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}

function todayDate(): string {
  const d = new Date();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}

const PILLARS: Array<{ id: PillarId; label: string; icon: React.ElementType }> = [
  { id: 'fundamental', label: '基本面支撑 (Fundamental)', icon: FileText },
  { id: 'quant', label: '量化信号阀 (Quant Factor)', icon: Cpu },
  { id: 'sentiment', label: '舆情与合规 (Sentiment & Event)', icon: Newspaper },
  { id: 'liquidity', label: '主力资金流 (Liquidity Flow)', icon: Coins },
];

export function EvidenceChain() {
  const initialStock = getPersistedStock() ?? STOCK_UNIVERSE[0];
  const [selectedTarget, setSelectedTarget] = useState<StockTarget>(initialStock);
  const [evidence, setEvidence] = useState<EvidenceNode[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<EvidenceNode | null>(null);
  const [sourceLabel, setSourceLabel] = useState<string>('');

  // Add-evidence form
  const [isAdding, setIsAdding] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newPillar, setNewPillar] = useState<PillarId>('fundamental');
  const [newWeight, setNewWeight] = useState(7);
  const [newSource, setNewSource] = useState('财联社/Wind 精梳');
  const [newContent, setNewContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const selectedStock = formatStockLabel(selectedTarget);
  const stockOptions = useMemo(
    () => [selectedTarget, ...STOCK_UNIVERSE].filter((stock, index, list) => (
      list.findIndex((item) => item.symbol === stock.symbol) === index
    )),
    [selectedTarget],
  );

  // 轮次序号: loadEvidence 自增, fetch 返回后若非最新则丢弃(防切标的 stale 覆盖)。
  const evidenceSeqRef = useRef(0);

  const loadEvidence = useCallback(async (stock: StockTarget) => {
    const seq = ++evidenceSeqRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const payload = await fetchApi<{ evidence?: EvidenceItem[]; total?: number }>(
        `/api/evidence?symbol=${encodeURIComponent(stripSymbolSuffix(stock.symbol))}&limit=50`,
      );
      if (seq !== evidenceSeqRef.current) return; // 已有更新的请求, 丢弃 stale 结果
      const items = (payload.evidence || []).map(toNode);
      setEvidence(items);
      setSourceLabel(`真实证据库 · ${items.length} 条 · 共 ${payload.total ?? items.length} 条`);
    } catch (err) {
      if (seq !== evidenceSeqRef.current) return;
      setEvidence([]);
      setLoadError(getErrorMessage(err));
      setSourceLabel('证据库不可用');
    } finally {
      if (seq === evidenceSeqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEvidence(selectedTarget);
  }, [selectedTarget, loadEvidence]);

  useEffect(() => {
    setSelectedNode((current) => {
      if (current && evidence.some((node) => node.id === current.id)) return current;
      return evidence[0] ?? null;
    });
  }, [evidence]);

  useEffect(() => subscribeStockSelected(({ stock }) => {
    const next = findStockTarget(stock.symbol) ?? stock;
    setSelectedTarget(next);
  }), []);

  const handleAddEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    const body: EvidenceCreateBody = {
      evidence_type: newPillar,
      title: newTitle.trim(),
      source: newSource.trim() || '人工录入',
      claim: newContent.trim(),
      content_summary: newContent.trim(),
      symbols: [stripSymbolSuffix(selectedTarget.symbol)],
      confidence: Math.max(1, Math.min(10, newWeight)) / 10,
      source_url: '',
      data_date: todayDate(),
      relevance: Math.max(1, Math.min(10, newWeight)) / 10,
    };
    try {
      await fetchApi('/api/evidence', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setNewTitle('');
      setNewContent('');
      setIsAdding(false);
      await loadEvidence(selectedTarget);
    } catch (err) {
      setSubmitError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteEvidence = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await fetchApi(`/api/evidence/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await loadEvidence(selectedTarget);
      if (selectedNode?.id === id) setSelectedNode(null);
    } catch (err) {
      setSubmitError(getErrorMessage(err));
    }
  };

  const handleStockChange = (symbol: string) => {
    const stock = stockOptions.find((item) => item.symbol === symbol);
    if (stock) {
      setSelectedTarget(stock);
      dispatchStockSelected(stock, 'system');
    }
  };

  // Composite confidence from real evidence (avg confidence * 100)
  const compositeScore = useMemo(() => {
    if (!evidence.length) return 0;
    const total = evidence.reduce((sum, node) => sum + (node.confidence ?? 0.5), 0);
    return Math.round((total / evidence.length) * 100);
  }, [evidence]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="p-6 lg:p-8 max-w-[1600px] mx-auto text-neutral-300 flex flex-col h-full overflow-hidden"
    >
      {/* Title */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 flex-shrink-0">
        <div>
          <h2 className="text-2xl font-display font-medium text-white flex items-center gap-3">
            <Bookmark className="w-6 h-6 text-indigo-400" />
            投研决策证据链终端 (Evidence Chain Vault)
          </h2>
          <p className="text-xs text-neutral-500 mt-1.5 font-mono">
            基于后端证据库的实时证据采集、归档与置信度审计面板，支持按标的筛选与人工追加。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => loadEvidence(selectedTarget)}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 hover:bg-white/[0.06]"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
            刷新
          </button>
          <select
            value={selectedTarget.symbol}
            onChange={(e) => handleStockChange(e.target.value)}
            className="bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500/50"
          >
            {stockOptions.map((stock) => (
              <option key={stock.symbol} value={stock.symbol}>{formatStockLabel(stock)}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Composite Score + Add action */}
      <div className="bg-indigo-500/5 border border-indigo-500/10 rounded-2xl p-5 mb-6 flex-shrink-0 flex flex-col md:flex-row items-center justify-between gap-6 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-96 h-96 bg-indigo-500/10 blur-[50px] pointer-events-none -translate-x-12 -translate-y-12" />
        <div className="flex items-center gap-5 relative z-10">
          <div className="relative w-16 h-16 rounded-full bg-black/40 border border-[#6366f1]/20 flex items-center justify-center flex-shrink-0">
            <svg className="absolute inset-0 w-full h-full transform -rotate-90">
              <circle cx="32" cy="32" r="28" stroke="rgba(99,102,241,0.06)" strokeWidth="4" fill="transparent" />
              <circle
                cx="32" cy="32" r="28" stroke="#6366f1" strokeWidth="4" fill="transparent"
                strokeDasharray={`${2 * Math.PI * 28}`}
                strokeDashoffset={`${2 * Math.PI * 28 * (1 - compositeScore / 100)}`}
                className="transition-all duration-1000 ease-out"
              />
            </svg>
            <span className="text-sm font-mono font-bold text-white">{compositeScore}%</span>
          </div>
          <div>
            <h3 className="text-neutral-100 text-sm font-semibold tracking-wide">
              {selectedStock} 证据综合置信度
            </h3>
            <p className="text-xs text-neutral-400 mt-1 max-w-xl">
              结合后端证据库已归档的 <strong className="text-white font-medium">{evidence.length} 件证据</strong>，按平均置信度计算的综合看多置信度。{sourceLabel}
            </p>
          </div>
        </div>
        <button
          onClick={() => setIsAdding(!isAdding)}
          className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white border border-indigo-500 shadow-lg shadow-indigo-600/30 transition-all flex items-center gap-2 flex-shrink-0 cursor-pointer"
        >
          <Plus className="w-4 h-4" /> 追加核心决策论据
        </button>
      </div>

      {loadError && (
        <div className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
          证据库读取失败：{loadError}（请确认后端 /api/evidence 可用）
        </div>
      )}

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-8 min-h-0 overflow-hidden">
        {/* Left: pillars + add form */}
        <div className="lg:col-span-2 flex flex-col min-h-0 relative">
          <AnimatePresence mode="popLayout">
            {isAdding && (
              <motion.form
                key="add_form"
                initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }}
                onSubmit={handleAddEvidence}
                className="bg-[#0b0b0b] border border-indigo-500/20 rounded-2xl p-6 h-full flex flex-col justify-between absolute inset-0 z-20 overflow-y-auto"
              >
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2 pb-2 border-b border-white/5">
                    <Sparkles className="w-4 h-4 text-indigo-400 animate-pulse" /> 追加决策论据到证据库
                  </h3>
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-medium text-neutral-400">论据关键标题 (Title)</label>
                    <input type="text" required placeholder="例：Q1净利润同增19%超出全同业中枢" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500/50" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-[11px] font-medium text-neutral-400">研究评估分类 (Pillar)</label>
                      <select value={newPillar} onChange={(e) => setNewPillar(e.target.value as PillarId)} className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500/50">
                        {PILLARS.map((p) => (<option key={p.id} value={p.id}>{p.label.split(' (')[0]}</option>))}
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-[11px] font-medium text-neutral-400">决策置信比重 (Weight 1-10)</label>
                      <input type="number" min="1" max="10" required value={newWeight} onChange={(e) => setNewWeight(Number(e.target.value))} className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500/50" />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-medium text-neutral-400">信源出处支撑 (Source)</label>
                    <input type="text" required placeholder="例：公司2026年Q1财报合并报表部分" value={newSource} onChange={(e) => setNewSource(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500/50" />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-medium text-neutral-400">论据佐证内容 (Claim)</label>
                    <textarea required rows={3} placeholder="请详细披露核心论据事实、归因变量以及验证过程日志..." value={newContent} onChange={(e) => setNewContent(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500/50 resize-none h-24 custom-scrollbar" />
                  </div>
                  {submitError && <p className="text-xs text-rose-300">提交失败：{submitError}</p>}
                </div>
                <div className="flex gap-4 border-t border-white/5 pt-4 mt-4">
                  <button type="button" onClick={() => setIsAdding(false)} className="flex-1 py-3 text-xs rounded-xl bg-white/5 border border-white/5 text-neutral-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer">取消</button>
                  <button type="submit" disabled={submitting} className="flex-1 py-3 text-xs rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white border border-indigo-500 font-semibold shadow-md cursor-pointer disabled:opacity-50">
                    {submitting ? '提交中...' : '保存到证据库'}
                  </button>
                </div>
              </motion.form>
            )}
          </AnimatePresence>

          <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-6 overflow-y-auto pr-1 pb-4 custom-scrollbar min-h-0">
            {PILLARS.map((pil) => {
              const nodesInPillar = evidence.filter((n) => n.pillar === pil.id);
              const ActiveIcon = pil.icon;
              return (
                <div key={pil.id} className={cn("rounded-2xl border p-4.5 bg-black/20 flex flex-col min-h-[180px] transition-all duration-200", selectedNode?.pillar === pil.id ? "border-indigo-500/30 bg-indigo-500/[0.02] shadow-inner" : "border-white/5")}>
                  <div className="flex justify-between items-center mb-4 pb-2.5 border-b border-white/5">
                    <span className="text-[10px] uppercase font-mono font-bold tracking-wider text-neutral-500 flex items-center gap-1.5">
                      <ActiveIcon className="w-4 h-4 text-neutral-400" />
                      {pil.label.split(' (')[0]}
                    </span>
                    <span className="px-1.5 py-0.5 rounded-md font-mono text-[9px] bg-white/5 border border-white/10 text-neutral-400">{nodesInPillar.length} 论据</span>
                  </div>
                  <div className="flex-grow space-y-2">
                    {loading ? (
                      <div className="text-[10px] font-mono text-neutral-600 italic py-4">[同步] 正在从证据库加载...</div>
                    ) : nodesInPillar.length === 0 ? (
                      <div className="text-[10px] font-mono text-neutral-600 italic py-4">[缺省] 暂无该类证据，可追加</div>
                    ) : (
                      nodesInPillar.map((node) => {
                        const isNodeSelected = selectedNode?.id === node.id;
                        return (
                          <div
                            key={node.id}
                            onClick={() => setSelectedNode(node)}
                            className={cn("p-2.5 rounded-xl border text-xs leading-relaxed text-left cursor-pointer transition-all flex justify-between items-start group relative overflow-hidden", isNodeSelected ? "bg-indigo-500/10 border-indigo-500/40 text-neutral-100 font-medium" : "bg-black/40 border-white/5 hover:border-white/15 text-neutral-400 hover:text-neutral-300")}
                          >
                            <span className="line-clamp-1 flex-1 pr-4">{node.title}</span>
                            <div className="flex items-center gap-2 flex-shrink-0 shrink-0">
                              <span className="text-[9px] font-mono font-bold px-1 rounded bg-[#6366f1]/15 text-indigo-400 border border-[#6366f1]/10">W {node.weight}</span>
                              <button onClick={(e) => handleDeleteEvidence(node.id, e)} className="opacity-0 group-hover:opacity-100 text-neutral-500 hover:text-rose-400 p-0.5 transition-opacity">
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: audit detail pane */}
        <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-5 flex flex-col relative overflow-hidden h-full min-h-[400px]">
          <div className="absolute top-0 right-0 p-3 opacity-20 text-indigo-400 pointer-events-none">
            <FolderLock className="w-24 h-24 stroke-[0.3]" />
          </div>
          <div className="flex gap-2.5 items-center mb-5 relative z-10">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
              <CheckCircle className="w-4.5 h-4.5 text-indigo-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-neutral-200">投研信能佐证审计官</h3>
              <p className="text-[10px] font-mono uppercase text-neutral-500 tracking-wider">Proof Audit Interface</p>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar relative z-10 text-xs text-neutral-400 leading-relaxed pr-1 flex flex-col">
            <AnimatePresence mode="wait">
              {selectedNode ? (
                <motion.div key={selectedNode.id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} className="space-y-4">
                  <div className="bg-black/30 border border-white/5 rounded-xl p-3.5">
                    <span className="text-[9px] font-mono uppercase tracking-widest text-neutral-500 block mb-1">选论论断</span>
                    <h4 className="text-sm text-neutral-200 font-semibold leading-relaxed text-left">{selectedNode.title}</h4>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-center text-[10px] font-mono">
                    <div className="p-2.5 bg-black/20 rounded-lg border border-white/5">
                      <span className="text-neutral-500 block">置信度</span>
                      <span className="text-xs font-bold text-white">权重 {selectedNode.weight} / 10</span>
                    </div>
                    <div className="p-2.5 bg-black/20 rounded-lg border border-white/5">
                      <span className="text-neutral-500 block">数据日期</span>
                      <span className="text-xs text-neutral-300 font-medium">{selectedNode.data_date || formatStamp(selectedNode.created_at)}</span>
                    </div>
                  </div>
                  <div className="p-3 bg-indigo-500/5 border border-indigo-500/10 rounded-xl space-y-1">
                    <span className="text-[9px] font-mono uppercase tracking-widest text-indigo-400 block">信源</span>
                    <div className="flex items-center gap-1.5 text-xs text-neutral-300 font-medium">
                      <FileText className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                      {selectedNode.source || '未标注信源'}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <span className="text-[9px] font-mono uppercase tracking-widest text-neutral-500 block">论据佐证</span>
                    <p className="text-xs text-neutral-300 leading-relaxed bg-black/20 border border-white/5 p-3.5 rounded-xl text-left">
                      "{selectedNode.claim || selectedNode.content_summary || '无内容'}"
                    </p>
                  </div>
                  <div className="border-t border-white/5 pt-4 space-y-2">
                    <span className="text-[9px] font-mono uppercase tracking-widest text-neutral-500 block">分类与归档</span>
                    <div className="flex gap-2 items-center text-[11px] bg-indigo-950/20 border border-indigo-500/20 p-2.5 rounded-xl text-indigo-300">
                      <Cpu className="w-4 h-4 text-indigo-400 shrink-0" />
                      <span>类型 {selectedNode.evidence_type || 'default'} · 置信度 {Math.round((selectedNode.confidence ?? 0.5) * 100)}%</span>
                    </div>
                  </div>
                </motion.div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center text-neutral-500 py-12 gap-2">
                  <Bookmark className="w-8 h-8 text-neutral-600 animate-pulse" />
                  <p className="text-[11px]">{loading ? '正在加载证据库...' : '请在左侧选择证据条目，或追加新论据以启动溯源跟踪。'}</p>
                </div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
