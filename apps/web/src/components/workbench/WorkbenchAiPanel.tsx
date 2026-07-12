/**
 * Workbench right-rail AI analysis engine panel.
 */
import type React from "react";
import { Bot, Maximize2, RefreshCw, Send, Sparkles, ChevronDown, ImagePlus, Settings2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "../../lib/utils";
import type { ChatMessage } from "../../types";
import type { StockTarget } from "../../lib/stocks";
import type { ModelOption } from "../../lib/aiModelRouting";
import { formatStockLabel } from "../../lib/stocks";
import { ThemedSelect } from "../ThemedSelect";
import {
  ANALYSIS_MODES,
  formatMessageHtml,
  type AnalysisModeId,
} from "./support";

export interface WorkbenchAiPanelProps {
  analysisMode: AnalysisModeId;
  autoEvidence: boolean;
  canSendChat: boolean;
  chatLoading: boolean;
  chatModelOptions: ModelOption[];
  chatStatus: string;
  currentStock: StockTarget;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleFullscreen: () => void;
  handleModeChange: (id: AnalysisModeId) => void;
  handleRefreshChart: () => void;
  handleSend: () => void | Promise<void>;
  handleUploadContext: (e: React.ChangeEvent<HTMLInputElement>) => void | Promise<void>;
  input: string;
  lastUploadedFile: string;
  messages: ChatMessage[];
  modeMenuOpen: boolean;
  onOpenModelSettings: (() => void) | undefined;
  selectedChatModel: ModelOption | undefined;
  selectedMode: { id: string; label: string; desc: string };
  setAutoEvidence: React.Dispatch<React.SetStateAction<boolean>>;
  setInput: React.Dispatch<React.SetStateAction<string>>;
  setModeMenuOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedChatModelKey: React.Dispatch<React.SetStateAction<string>>;
  setSettingsOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setStrictRisk: React.Dispatch<React.SetStateAction<boolean>>;
  settingsOpen: boolean;
  strictRisk: boolean;
}

export function WorkbenchAiPanel({
  analysisMode,
  autoEvidence,
  canSendChat,
  chatLoading,
  chatModelOptions,
  chatStatus,
  currentStock,
  fileInputRef,
  handleFullscreen,
  handleModeChange,
  handleRefreshChart,
  handleSend,
  handleUploadContext,
  input,
  lastUploadedFile,
  messages,
  modeMenuOpen,
  onOpenModelSettings,
  selectedChatModel,
  selectedMode,
  setAutoEvidence,
  setInput,
  setModeMenuOpen,
  setSelectedChatModelKey,
  setSettingsOpen,
  setStrictRisk,
  settingsOpen,
  strictRisk,
}: WorkbenchAiPanelProps) {
  return (
    <>
      {/* Right AI Engine Panel */}
      {/* 注意: 此面板不能用 overflow-hidden — 模式选择菜单 (absolute top-8) 会向下弹出
          被 overflow-hidden 裁切, 导致主页「切换不了分析模式」。glow 的 blur 轻微外溢可接受。 */}
      <div className="relative mt-6 flex h-[720px] flex-col rounded-lg border border-white/[0.08] bg-[#0b0c11] shadow-[0_20px_65px_rgba(0,0,0,0.3)] sm:mt-8">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-indigo-400/60" />

        <div className="px-5 py-4 border-b border-white/5 flex justify-between items-center bg-white/[0.01] relative z-30">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-indigo-400/20 bg-indigo-500/10">
              <Sparkles className="w-4 h-4 text-indigo-400" />
            </div>
            <h2 className="font-semibold text-neutral-200 tracking-wide">AI 分析引擎</h2>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                data-testid="workbench-analysis-mode"
                onClick={() => setModeMenuOpen((open) => !open)}
                className="flex items-center gap-1.5 px-2 py-1 text-[11px] rounded border border-white/10 bg-black/40 text-neutral-400 hover:text-white transition-colors"
              >
                <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full shadow-[0_0_5px_rgba(99,102,241,0.5)]"></div>
                {selectedMode.label}
                <ChevronDown className="w-3 h-3 ml-1" />
              </button>
              <AnimatePresence>
                {modeMenuOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: -4, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -4, scale: 0.98 }}
                    className="absolute right-0 top-8 z-50 w-64 overflow-hidden rounded-xl border border-white/10 bg-[#101010] shadow-2xl"
                  >
                    {ANALYSIS_MODES.map((mode) => (
                      <button
                        key={mode.id}
                        type="button"
                        data-testid={`workbench-mode-${mode.id}`}
                        onClick={() => handleModeChange(mode.id)}
                        className={cn(
                          "w-full px-3 py-3 text-left transition-colors",
                          analysisMode === mode.id ? "bg-indigo-500/10" : "hover:bg-white/[0.04]"
                        )}
                      >
                        <span className="block text-xs font-medium text-neutral-100">{mode.label}</span>
                        <span className="mt-1 block text-[10px] leading-relaxed text-neutral-500">{mode.desc}</span>
                      </button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            <button data-testid="workbench-refresh-chart" onClick={handleRefreshChart} className="p-1.5 hover:bg-white/5 rounded-md text-neutral-500 transition-colors" title="刷新行情沙盘">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
            <button data-testid="workbench-fullscreen" onClick={handleFullscreen} className="p-1.5 hover:bg-white/5 rounded-md text-neutral-500 transition-colors" title="切换全屏">
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
            <button
              data-testid="workbench-open-model-settings"
              onClick={onOpenModelSettings}
              className="p-1.5 hover:bg-white/5 rounded-md text-neutral-500 transition-colors"
              title="模型路由设置"
            >
              <Bot className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar z-10">
          <AnimatePresence>
            {messages.map(msg => (
              <motion.div 
                key={msg.id} 
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
                className="flex gap-3"
              >
                {msg.role !== 'user' ? (
                  <div className="min-w-0 flex-1 mr-4">
                     <div className="bg-white/[0.06] border border-white/[0.05] rounded-xl rounded-tl-sm p-4 text-sm text-neutral-300 leading-relaxed shadow-[0_4px_15px_rgba(0,0,0,0.1)]">
                       <p dangerouslySetInnerHTML={{ __html: formatMessageHtml(msg.content) }} />
                     </div>
                  </div>
                ) : (
                  <div className="min-w-0 flex-1 ml-12">
                     <div className="bg-gradient-to-br from-indigo-500/25 to-indigo-600/15 border border-indigo-500/30 text-indigo-50 rounded-xl rounded-tr-sm p-4 text-sm leading-relaxed shadow-[0_4px_15px_rgba(99,102,241,0.05)]">
                       {msg.content}
                     </div>
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            transition={{ delay: 1 }} 
            className="flex justify-center my-4 relative z-10"
          >
             <span className="text-[10px] font-mono text-neutral-500 bg-black/60 px-3 py-1 rounded-full border border-white/5">
               [系统] 已切换至 {formatStockLabel(currentStock)}
             </span>
          </motion.div>
        </div>
        
        <div className="p-4 border-t border-white/5 bg-black/40 relative z-10">
          <div className="mb-3 rounded-xl border border-white/10 bg-white/[0.025] px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2 text-xs text-neutral-300">
                <Bot className="h-4 w-4 shrink-0 text-indigo-300" />
                <span className="shrink-0 font-medium text-neutral-100">真实模型</span>
                <span className="truncate font-mono text-[11px] text-neutral-500">{chatStatus}</span>
              </div>
              <button
                type="button"
                onClick={onOpenModelSettings}
                className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-[10px] text-neutral-400 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
              >
                设置
              </button>
              <ThemedSelect
                data-testid="workbench-chat-model-select"
                value={selectedChatModel?.key || ''}
                onChange={setSelectedChatModelKey}
                disabled={!chatModelOptions.length || chatLoading}
                className="min-w-[220px]"
                buttonClassName="h-8 rounded-lg bg-black/50 px-2 text-xs"
                menuClassName="text-xs"
                options={chatModelOptions.length ? chatModelOptions.map((option) => ({
                  value: option.key,
                  label: `${option.providerName} / ${option.modelId}${option.vision ? ' · 视觉' : ''}`,
                  badge: option.vision ? <span className="rounded-full bg-indigo-400/10 px-1.5 py-0.5 text-[9px] text-indigo-200">视觉</span> : undefined,
                })) : [{ value: '', label: '请先在系统设置获取模型列表', disabled: true }]}
              />
            </div>
          </div>
          <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden shadow-inner focus-within:border-indigo-500/50 focus-within:ring-1 focus-within:ring-indigo-500/50 transition-all">
            <textarea 
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={`对 ${currentStock.name} 提出分析需求...`} 
              className="w-full bg-transparent p-4 text-sm focus:outline-none text-neutral-200 placeholder:text-neutral-500 resize-none h-24 custom-scrollbar"
            />
            <div className="flex justify-between items-center px-3 pb-3">
              <div className="flex gap-1.5">
                <input ref={fileInputRef} type="file" accept="image/*,.pdf,.txt,.md,.csv" onChange={handleUploadContext} className="hidden" />
                <button
                  data-testid="workbench-upload-context"
                  onClick={() => fileInputRef.current?.click()}
                  title="多模态分析 (上传 K 线截图或本地研报)"
                  className="p-1.5 text-neutral-500 hover:text-indigo-400 hover:bg-indigo-500/10 rounded-md transition-colors"
                >
                  <ImagePlus className="w-4.5 h-4.5" />
                </button>
                <button
                  data-testid="workbench-analysis-settings"
                  onClick={() => setSettingsOpen((open) => !open)}
                  title="分析配置"
                  className="p-1.5 text-neutral-500 hover:text-neutral-300 rounded-md hover:bg-white/5 transition-colors"
                >
                  <Settings2 className="w-4.5 h-4.5" />
                </button>
              </div>
              <div className="flex items-center gap-4 text-[10px] font-mono text-neutral-500">
                <span>ENTER 发送 • SHIFT+ENTER 换行</span>
                <button 
                  onClick={handleSend}
                  disabled={!canSendChat}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 text-white rounded-lg border border-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.4)] transition-all",
                    canSendChat ? "bg-indigo-600 hover:bg-indigo-500" : "cursor-not-allowed bg-neutral-800 text-neutral-500 border-white/10 shadow-none"
                  )}
                >
                  {chatLoading ? '调用中' : '发送'}
                  {chatLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>
          <AnimatePresence>
            {settingsOpen && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                className="mt-3 rounded-xl border border-white/10 bg-black/35 p-3 text-xs text-neutral-400"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="font-medium text-neutral-200">本次分析配置</span>
                  <span className="font-mono text-[10px] text-indigo-300">{selectedMode.label}</span>
                </div>
                <label className="mb-2 flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-white/[0.03] px-3 py-2">
                  <span>自动附带证据链引用</span>
                  <input type="checkbox" checked={autoEvidence} onChange={() => setAutoEvidence((value) => !value)} />
                </label>
                <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-white/[0.03] px-3 py-2">
                  <span>风险事件优先进入摘要</span>
                  <input type="checkbox" checked={strictRisk} onChange={() => setStrictRisk((value) => !value)} />
                </label>
                {lastUploadedFile && (
                  <p className="mt-3 rounded-lg border border-indigo-500/20 bg-indigo-500/5 px-3 py-2 text-[11px] text-indigo-100/80">
                    已加载材料：{lastUploadedFile}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </>
  );
}
