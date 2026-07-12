/**
 * Settings API keys / providers tab + model library dialog.
 */
import type { Dispatch, SetStateAction } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  CheckCircle2,
  CircleMinus,
  CirclePlus,
  Eye,
  EyeOff,
  Filter,
  Layers3,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { cn } from "../../lib/utils";
import type { ProviderModelCapabilities, ProviderModelInfo } from "../../lib/aiModelRouting";
import { ThemedSelect, type ThemedSelectOption } from "../ThemedSelect";
import {
  type ProviderDraft,
  type ProviderListItem,
  type SettingsModelProvider,
  type SettingsState,
} from "./types";
import { getModelCapabilityClass, getModelCapabilityLabel } from "./helpers";
import { TextField, ToggleRow } from "./fields";

export interface ApiKeysTabProps {
  settings: SettingsState;
  updateSetting: <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => void;
  providerSearch: string;
  setProviderSearch: Dispatch<SetStateAction<string>>;
  filteredProviders: ProviderListItem[];
  isProviderDraft: boolean;
  selectedProviderId: string;
  selectProvider: (provider: ProviderListItem) => void;
  addProvider: () => void;
  providerDraft: ProviderDraft;
  setProviderDraft: Dispatch<SetStateAction<ProviderDraft>>;
  providerStatus: string;
  deleteProvider: () => void | Promise<void>;
  saveProvider: () => void | Promise<unknown>;
  providerLoading: boolean;
  showProviderKey: boolean;
  setShowProviderKey: Dispatch<SetStateAction<boolean>>;
  selectedProvider: SettingsModelProvider | undefined;
  testProvider: () => void | Promise<void>;
  providerTesting: boolean;
  fetchProviderModels: () => void | Promise<void>;
  providerFetchingModels: boolean;
  setModelDialogOpen: Dispatch<SetStateAction<boolean>>;
  visibleProviderModels: ProviderModelInfo[];
  updateProviderModelCapabilities: (modelId: string, patch: Partial<ProviderModelCapabilities>) => void;
  selectEmbeddingModel: (modelId: string) => void;
  removeModelFromProvider: (modelId: string) => void;
  embeddingSelectOptions: ThemedSelectOption[];
  embeddingModelOptions: ProviderModelInfo[];
  modelDialogOpen: boolean;
  modelSearch: string;
  setModelSearch: Dispatch<SetStateAction<string>>;
  modelCapabilityFilter: 'all' | 'vision' | 'text' | 'embedding';
  setModelCapabilityFilter: Dispatch<SetStateAction<'all' | 'vision' | 'text' | 'embedding'>>;
  filteredDiscoveredModels: ProviderModelInfo[];
  visibleModelIds: Set<string>;
  addModelToProvider: (model: ProviderModelInfo) => void;
  discoveredModels: ProviderModelInfo[];
}

export function ApiKeysTab({
  settings,
  updateSetting,
  providerSearch,
  setProviderSearch,
  filteredProviders,
  isProviderDraft,
  selectedProviderId,
  selectProvider,
  addProvider,
  providerDraft,
  setProviderDraft,
  providerStatus,
  deleteProvider,
  saveProvider,
  providerLoading,
  showProviderKey,
  setShowProviderKey,
  selectedProvider,
  testProvider,
  providerTesting,
  fetchProviderModels,
  providerFetchingModels,
  setModelDialogOpen,
  visibleProviderModels,
  updateProviderModelCapabilities,
  selectEmbeddingModel,
  removeModelFromProvider,
  embeddingSelectOptions,
  embeddingModelOptions,
  modelDialogOpen,
  modelSearch,
  setModelSearch,
  modelCapabilityFilter,
  setModelCapabilityFilter,
  filteredDiscoveredModels,
  visibleModelIds,
  addModelToProvider,
  discoveredModels,
}: ApiKeysTabProps) {
  return (
    <>
      {/* api panel — rendered when parent selects api tab */}
              <motion.div key="api" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="overflow-hidden rounded-3xl border border-white/5 bg-black/20">
                <div className="grid min-h-[38rem] grid-cols-1 lg:grid-cols-[clamp(18rem,32%,22rem)_minmax(0,1fr)]">
                  <aside className="flex min-h-[32rem] flex-col border-b border-white/5 bg-white/[0.02] p-4 lg:border-b-0 lg:border-r">
                    <label className="relative block">
                      <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-neutral-500" />
                      <input
                        type="search"
                        value={providerSearch}
                        onChange={(event) => setProviderSearch(event.target.value)}
                        placeholder="搜索模型平台..."
                        className="h-12 w-full rounded-2xl border border-emerald-500/35 bg-black/20 pl-11 pr-4 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-emerald-400/70"
                      />
                    </label>

                    <div className="mt-4 flex-1 space-y-1 overflow-y-auto pr-1 custom-scrollbar">
                      {filteredProviders.map((provider) => {
                        const isActive = provider.isDraft ? isProviderDraft : provider.id === selectedProviderId;
                        const initial = (provider.name || provider.id || '?').trim().slice(0, 1).toUpperCase();
                        return (
                          <button
                            key={provider.id}
                            type="button"
                            onClick={() => selectProvider(provider)}
                            className={cn(
                              'flex w-full items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-colors',
                              isActive
                                ? 'border-white/10 bg-white/[0.07]'
                                : 'border-transparent hover:bg-white/[0.04]',
                            )}
                          >
                            <span className={cn(
                              'flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-medium',
                              provider.enabled ? 'bg-emerald-500/85 text-black' : 'bg-neutral-700 text-neutral-300',
                            )}>
                              {initial}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium text-neutral-100">{provider.name}</span>
                              <span className="mt-1 block truncate text-xs text-neutral-500">{provider.id}</span>
                            </span>
                            <span className={cn(
                              'rounded-full border px-2.5 py-1 text-[11px] font-medium',
                              provider.isDraft
                                ? 'border-indigo-400/40 bg-indigo-400/10 text-indigo-300'
                                : provider.enabled
                                ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300'
                                : 'border-white/10 bg-white/[0.03] text-neutral-500',
                            )}>
                              {provider.isDraft ? '新建' : provider.enabled ? '启用' : '停用'}
                            </span>
                          </button>
                        );
                      })}

                      {!filteredProviders.length && (
                        <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-8 text-center text-sm text-neutral-500">
                          {providerSearch.trim() ? '没有匹配的平台。' : '暂无 Provider，点击添加后配置。'}
                        </div>
                      )}
                    </div>

                    <button
                      type="button"
                      onClick={addProvider}
                      className="mt-4 inline-flex h-12 items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/[0.03] text-sm font-medium text-neutral-200 transition-colors hover:bg-white/[0.06]"
                    >
                      <Plus className="h-5 w-5" />
                      添加
                    </button>
                  </aside>

                  <section className="p-5 lg:px-7 lg:py-6">
                    <div className="flex items-center justify-between gap-4 border-b border-white/10 pb-5">
                      <div className="min-w-0">
                        <div className="flex items-center gap-3">
                          <h3 className="truncate text-xl font-medium leading-snug text-white">{providerDraft.name || '自定义 Provider'}</h3>
                          <Server className="h-5 w-5 shrink-0 text-neutral-500" />
                        </div>
                        <p className="mt-2 max-w-xl text-sm leading-6 text-neutral-500">{providerStatus}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setProviderDraft((prev) => ({ ...prev, enabled: !prev.enabled }))}
                        className={cn(
                          'relative h-11 w-20 shrink-0 rounded-full border transition-colors',
                          providerDraft.enabled
                            ? 'border-emerald-400/50 bg-emerald-500'
                            : 'border-white/10 bg-white/[0.06]',
                        )}
                        aria-label="切换 Provider 启用状态"
                      >
                        <span className={cn(
                          'absolute left-1 top-1 h-9 w-9 rounded-full bg-white shadow transition-transform',
                          providerDraft.enabled ? 'translate-x-9' : 'translate-x-0',
                        )} />
                      </button>
                    </div>

                    <div className="mt-6 space-y-6">
                      <div>
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <h4 className="text-lg font-medium text-white">平台信息</h4>
                          <button
                            type="button"
                            onClick={deleteProvider}
                            className="inline-flex items-center gap-1.5 rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300 transition-colors hover:bg-rose-500/15"
                          >
                            <Trash2 className="h-4 w-4" />
                            删除
                          </button>
                        </div>
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <TextField
                            label="名称"
                            value={providerDraft.name}
                            onChange={(value) => setProviderDraft((prev) => ({ ...prev, name: value }))}
                            placeholder="DeepSeek"
                          />
                          <TextField
                            label="Provider ID"
                            value={providerDraft.id}
                            onChange={(value) => {
                              setProviderDraft((prev) => ({ ...prev, id: value }));
                            }}
                            placeholder="deepseek"
                            disabled={!isProviderDraft}
                          />
                        </div>
                      </div>

                      <div>
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <h4 className="text-lg font-medium text-white">API 密钥</h4>
                          <button
                            type="button"
                            onClick={saveProvider}
                            disabled={providerLoading}
                            className="inline-flex items-center gap-2 rounded-xl border border-indigo-500 bg-indigo-600 px-3 py-2 text-xs text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <Save className="h-4 w-4" />
                            保存
                          </button>
                        </div>
                        <div className="flex overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] focus-within:border-emerald-400/60">
                          <input
                            type={showProviderKey ? 'text' : 'password'}
                            value={providerDraft.api_key}
                            onChange={(event) => setProviderDraft((prev) => ({ ...prev, api_key: event.target.value }))}
                            placeholder={selectedProvider?.api_key_masked ? `已保存：${selectedProvider.api_key_masked}` : 'sk-...'}
                            className="min-w-0 flex-1 bg-transparent px-4 py-3 text-sm text-neutral-100 outline-none placeholder:text-neutral-600"
                          />
                          <button
                            type="button"
                            onClick={() => setShowProviderKey((prev) => !prev)}
                            className="flex w-12 items-center justify-center border-l border-white/10 text-neutral-500 transition-colors hover:text-neutral-200"
                            aria-label="显示或隐藏 API Key"
                          >
                            {showProviderKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                          <button
                            type="button"
                            onClick={testProvider}
                            disabled={providerTesting || !selectedProviderId}
                            className="inline-flex items-center gap-2 border-l border-white/10 px-5 text-sm font-medium text-neutral-100 transition-colors hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {providerTesting ? <RefreshCw className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                            检测
                          </button>
                        </div>
                        <p className="mt-2 text-right text-xs text-neutral-500">多个密钥使用逗号分隔</p>
                      </div>

                      <div>
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <h4 className="text-lg font-medium text-white">API 地址</h4>
                          <Server className="h-5 w-5 text-neutral-500" />
                        </div>
                        <input
                          value={providerDraft.base_url}
                          onChange={(event) => setProviderDraft((prev) => ({ ...prev, base_url: event.target.value }))}
                          placeholder="https://api.example.com/v1"
                          className="w-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-emerald-400/60"
                        />
                        <p className="mt-2 text-sm text-neutral-500">
                          预览：{providerDraft.base_url ? `${providerDraft.base_url.replace(/\/$/, '')}/chat/completions` : '填写 Base URL 后生成预览'}
                        </p>
                      </div>

                      <div>
                        <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                          <div className="flex items-center gap-2">
                            <h4 className="text-lg font-medium text-white">模型</h4>
                            <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-neutral-400">{visibleProviderModels.length}</span>
                          </div>
                          <div className="flex overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03]">
                            <button
                              type="button"
                              onClick={fetchProviderModels}
                              disabled={providerFetchingModels || !selectedProviderId}
                              className="inline-flex min-w-0 items-center gap-2 px-4 py-2 text-sm text-neutral-100 transition-colors hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              <RefreshCw className={cn('h-4 w-4 shrink-0', providerFetchingModels && 'animate-spin')} />
                              <span className="whitespace-nowrap">获取模型列表</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => setModelDialogOpen(true)}
                              className="flex w-12 shrink-0 items-center justify-center border-l border-white/10 text-neutral-200 transition-colors hover:bg-white/[0.05]"
                              aria-label="打开模型库"
                            >
                              <Layers3 className="h-5 w-5" />
                            </button>
                          </div>
                        </div>

                        <div className="min-h-28 max-h-72 overflow-y-auto rounded-2xl border border-white/5 bg-white/[0.02] p-2 custom-scrollbar">
                          <div className="space-y-2">
                            {visibleProviderModels.map((model) => {
                              const isEmbeddingSelected =
                                settings.embeddingProviderId === providerDraft.id && settings.embeddingModel === model.id;
                              return (
                                <div
                                  key={model.id}
                                  className="grid grid-cols-[2.25rem_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2.5"
                                >
                                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[0.06] text-xs font-semibold text-neutral-200">
                                    {model.id.slice(0, 1).toUpperCase()}
                                  </span>
                                  <span className="min-w-0">
                                    <span className="block truncate text-sm font-medium text-neutral-100">{model.id}</span>
                                    <span className="mt-1 block truncate text-xs text-neutral-500">{model.owned_by || providerDraft.name || providerDraft.id}</span>
                                  </span>
                                  <span className="flex shrink-0 items-center gap-2">
                                    <button
                                      type="button"
                                      onClick={() => updateProviderModelCapabilities(model.id, { vision: !model.capabilities?.vision })}
                                      className={cn(
                                        'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                                        model.capabilities?.vision
                                          ? 'border-indigo-400/40 bg-indigo-400/15 text-indigo-200'
                                          : 'border-white/10 bg-white/[0.03] text-neutral-500 hover:text-neutral-300',
                                      )}
                                      title="标记或取消视觉能力"
                                    >
                                      视觉
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        updateProviderModelCapabilities(model.id, { embedding: !model.capabilities?.embedding });
                                        if (!model.capabilities?.embedding) selectEmbeddingModel(model.id);
                                      }}
                                      className={cn(
                                        'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                                        model.capabilities?.embedding
                                          ? 'border-amber-400/40 bg-amber-400/15 text-amber-200'
                                          : 'border-white/10 bg-white/[0.03] text-neutral-500 hover:text-neutral-300',
                                        isEmbeddingSelected && 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200',
                                      )}
                                      title="标记嵌入能力，可用于本地知识库"
                                    >
                                      {isEmbeddingSelected ? '知识库' : '嵌入'}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => removeModelFromProvider(model.id)}
                                      className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-neutral-500 transition-colors hover:border-rose-400/30 hover:bg-rose-400/10 hover:text-rose-300"
                                      aria-label={`移除 ${model.id}`}
                                    >
                                      <CircleMinus className="h-4 w-4" />
                                    </button>
                                  </span>
                                </div>
                              );
                            })}
                            {!visibleProviderModels.length && (
                              <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-8 text-center text-sm text-neutral-500">
                                暂无模型，保存 Provider 后点击获取模型列表。
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="rounded-2xl border border-white/5 bg-white/[0.025] p-4">
                        <div className="mb-4 flex items-start justify-between gap-3">
                          <div>
                            <h4 className="text-lg font-medium text-white">本地知识库与记忆</h4>
                            <p className="mt-1 text-xs leading-relaxed text-neutral-500">嵌入模型用于本地知识库检索；共享知识库和 Agent 记忆会进入专家团上下文。</p>
                          </div>
                          <Sparkles className="h-5 w-5 shrink-0 text-amber-300" />
                        </div>

                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          <ToggleRow label="启用本地知识库" hint="允许用户文档和系统证据进入统一检索。" checked={settings.knowledgeEnabled} onChange={() => updateSetting('knowledgeEnabled', !settings.knowledgeEnabled)} />
                          <ToggleRow label="共享知识库" hint="分析任务可读取已上传资料与证据库。" checked={settings.sharedKnowledge} onChange={() => updateSetting('sharedKnowledge', !settings.sharedKnowledge)} />
                          <ToggleRow label="Agent 记忆" hint="同一标的的历史 Agent 观点会作为参考上下文。" checked={settings.agentMemory} onChange={() => updateSetting('agentMemory', !settings.agentMemory)} />
                          <ToggleRow label="自动写入记忆" hint="专家团成功运行后自动沉淀关键观点。" checked={settings.autoWriteAgentMemory} onChange={() => updateSetting('autoWriteAgentMemory', !settings.autoWriteAgentMemory)} />
                        </div>

                        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_10rem]">
                          <label className="block">
                            <span className="mb-2 block text-xs font-medium text-neutral-400">嵌入模型</span>
                            <ThemedSelect
                              value={settings.embeddingProviderId === providerDraft.id ? settings.embeddingModel : ''}
                              options={embeddingSelectOptions}
                              onChange={selectEmbeddingModel}
                              buttonClassName="h-11 bg-black/30 focus-visible:border-emerald-400/60"
                            />
                            <p className="mt-2 text-xs text-neutral-500">
                              {embeddingModelOptions.length ? '只显示当前 Provider 中识别为嵌入能力的模型。' : '获取模型列表后，包含 embedding/embed/bge/gte 等名称的模型会出现在这里。'}
                            </p>
                          </label>
                          <TextField
                            label="记忆保留天数"
                            type="number"
                            value={settings.memoryRetentionDays}
                            onChange={(value) => updateSetting('memoryRetentionDays', Number(value) || 1)}
                          />
                        </div>
                      </div>
                    </div>
                  </section>
                </div>
              </motion.div>

            <AnimatePresence>
        {modelDialogOpen && (
          <motion.div
            className="settings-ui fixed inset-0 z-[200] flex items-center justify-center bg-black/70 p-4 text-neutral-300 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-label="模型库"
              className="flex max-h-[82vh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#090b10] shadow-2xl"
              initial={{ opacity: 0, y: 18, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.98 }}
              transition={{ duration: 0.18 }}
            >
              <div className="flex items-center justify-between gap-4 border-b border-white/10 px-5 py-4">
                <div className="min-w-0">
                  <h3 className="text-lg font-medium text-white">模型库</h3>
                  <p className="mt-1 text-xs text-neutral-500">选择当前 Provider 要启用的模型，能力只按视觉、嵌入和文本区分。</p>
                </div>
                <button
                  type="button"
                  onClick={() => setModelDialogOpen(false)}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 text-neutral-400 transition-colors hover:bg-white/[0.06] hover:text-white"
                  aria-label="关闭模型库"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="border-b border-white/10 p-4">
                <label className="relative block">
                  <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-500" />
                  <input
                    type="search"
                    value={modelSearch}
                    onChange={(event) => setModelSearch(event.target.value)}
                    placeholder="搜索模型 ID 或归属方..."
                    className="h-11 w-full rounded-2xl border border-white/10 bg-white/[0.03] pl-11 pr-4 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-indigo-400/60"
                  />
                </label>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {[
                    ['all', '全部'],
                    ['vision', '视觉'],
                    ['text', '文本'],
                    ['embedding', '嵌入'],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setModelCapabilityFilter(value as 'all' | 'vision' | 'text' | 'embedding')}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs transition-colors',
                        modelCapabilityFilter === value
                          ? 'border-indigo-400/40 bg-indigo-400/15 text-indigo-200'
                          : 'border-white/10 bg-white/[0.03] text-neutral-400 hover:bg-white/[0.06] hover:text-neutral-200',
                      )}
                    >
                      <Filter className="h-3.5 w-3.5" />
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-3 custom-scrollbar">
                <div className="space-y-2">
                  {filteredDiscoveredModels.map((model) => {
                    const added = visibleModelIds.has(model.id);
                    const isEmbeddingSelected =
                      settings.embeddingProviderId === providerDraft.id && settings.embeddingModel === model.id;
                    return (
                      <div
                        key={model.id}
                        className="grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border border-white/5 bg-white/[0.025] px-3 py-3"
                      >
                        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/[0.06] text-xs font-semibold text-neutral-200">
                          {model.id.slice(0, 1).toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="truncate text-sm font-medium text-neutral-100">{model.id}</span>
                            <span className={cn('shrink-0 rounded-full border px-2 py-0.5 text-[10px]', getModelCapabilityClass(model))}>
                              {isEmbeddingSelected ? '知识库' : getModelCapabilityLabel(model)}
                            </span>
                          </div>
                          <p className="mt-1 truncate text-xs text-neutral-500">{model.owned_by || providerDraft.name || providerDraft.id}</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => updateProviderModelCapabilities(model.id, { vision: !model.capabilities?.vision })}
                              className={cn(
                                'rounded-lg border px-2 py-1 text-[10px] transition-colors',
                                model.capabilities?.vision
                                  ? 'border-indigo-400/40 bg-indigo-400/15 text-indigo-200'
                                  : 'border-white/10 bg-white/[0.03] text-neutral-500 hover:text-neutral-300',
                              )}
                            >
                              视觉
                            </button>
                            <button
                              type="button"
                              onClick={() => updateProviderModelCapabilities(model.id, { embedding: !model.capabilities?.embedding })}
                              className={cn(
                                'rounded-lg border px-2 py-1 text-[10px] transition-colors',
                                model.capabilities?.embedding
                                  ? 'border-amber-400/40 bg-amber-400/15 text-amber-200'
                                  : 'border-white/10 bg-white/[0.03] text-neutral-500 hover:text-neutral-300',
                              )}
                            >
                              嵌入
                            </button>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => (added ? removeModelFromProvider(model.id) : addModelToProvider(model))}
                          className={cn(
                            'flex h-9 w-9 items-center justify-center rounded-xl border transition-colors',
                            added
                              ? 'border-rose-400/25 bg-rose-400/10 text-rose-300 hover:bg-rose-400/15'
                              : 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300 hover:bg-emerald-400/15',
                          )}
                          aria-label={added ? `移除 ${model.id}` : `加入 ${model.id}`}
                        >
                          {added ? <CircleMinus className="h-4 w-4" /> : <CirclePlus className="h-4 w-4" />}
                        </button>
                      </div>
                    );
                  })}

                  {!filteredDiscoveredModels.length && (
                    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-5 py-10 text-center">
                      <Layers3 className="mx-auto mb-3 h-8 w-8 text-neutral-600" />
                      <p className="text-sm text-neutral-400">{discoveredModels.length ? '没有匹配的模型。' : '还没有获取到模型列表。'}</p>
                      <button
                        type="button"
                        onClick={fetchProviderModels}
                        disabled={providerFetchingModels || !selectedProviderId}
                        className="mt-4 inline-flex items-center gap-2 rounded-xl border border-indigo-400/30 bg-indigo-400/10 px-3 py-2 text-xs text-indigo-200 transition-colors hover:bg-indigo-400/15 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <RefreshCw className={cn('h-4 w-4', providerFetchingModels && 'animate-spin')} />
                        获取模型列表
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </>
  );
}
