/**
 * Settings · model routing tab.
 */
import { Bot, RefreshCw, Save, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { AI_ROUTE_LABELS, getModelKey, type AiModelRoutes, type AiRouteKey, type ModelOption, type ModelProvider } from "../../lib/aiModelRouting";
import { ThemedSelect } from "../ThemedSelect";
import { SettingCard } from "./fields";
import { modelOptionLabel } from "./helpers";
import { modelSelectOptions } from "./modelOptions";

export interface ModelsTabProps {
  providers: ModelProvider[];
  chatModelOptions: ModelOption[];
  visionModelOptions: ModelOption[];
  normalizedAiRoutes: AiModelRoutes;
  routeSaving: boolean;
  applyRouteDefaults: () => void;
  applyUnifiedModel: (modelKey: string) => void;
  patchAiRoutes: (patch: Partial<AiModelRoutes>) => void;
  updateRouteSelection: (routeKey: AiRouteKey, modelKey: string) => void;
  saveAiRoutes: () => void | Promise<void>;
}

export function ModelsTab({
  providers,
  chatModelOptions,
  visionModelOptions,
  normalizedAiRoutes,
  routeSaving,
  applyRouteDefaults,
  applyUnifiedModel,
  patchAiRoutes,
  updateRouteSelection,
  saveAiRoutes,
}: ModelsTabProps) {
  return (
    <motion.div key="models" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="max-w-6xl space-y-5">
      <SettingCard title="全局模型路由" desc="所有 AI 功能都从这里读取默认模型；功能页也可以直接跳回本页修改。" icon={Bot}>
        <div className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-white/5 bg-white/[0.025] px-4 py-3">
            <p className="text-[10px] font-mono tracking-wider text-neutral-500">Provider</p>
            <p className="mt-1 text-lg font-semibold text-white">{providers.filter((provider) => provider.enabled).length}</p>
            <p className="mt-1 text-[11px] text-neutral-500">已启用模型平台。</p>
          </div>
          <div className="rounded-xl border border-white/5 bg-white/[0.025] px-4 py-3">
            <p className="text-[10px] font-mono tracking-wider text-neutral-500">聊天模型</p>
            <p className="mt-1 text-lg font-semibold text-white">{chatModelOptions.length}</p>
            <p className="mt-1 text-[11px] text-neutral-500">可用于推理、研报、新闻和 Agent。</p>
          </div>
          <div className="rounded-xl border border-white/5 bg-white/[0.025] px-4 py-3">
            <p className="text-[10px] font-mono tracking-wider text-neutral-500">视觉模型</p>
            <p className="mt-1 text-lg font-semibold text-white">{visionModelOptions.length}</p>
            <p className="mt-1 text-[11px] text-neutral-500">可用于图片解析和多模态入口。</p>
          </div>
        </div>

        <div className="rounded-2xl border border-indigo-500/15 bg-indigo-500/[0.04] p-4">
          <div className="mb-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h4 className="text-sm font-semibold text-neutral-100">一键统一模型</h4>
              <p className="mt-1 text-xs text-neutral-500">默认所有文本推理功能使用同一模型，图片解析仍优先使用带视觉能力的模型。</p>
            </div>
            <button
              type="button"
              onClick={applyRouteDefaults}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-neutral-200 transition-colors hover:bg-white/[0.08]"
            >
              <Sparkles className="h-4 w-4 text-indigo-300" />
              智能填充
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <ThemedSelect
              value={getModelKey(normalizedAiRoutes.unified)}
              options={modelSelectOptions(chatModelOptions, "请先在 API 密钥页添加 Provider 并获取模型列表")}
              onChange={applyUnifiedModel}
              disabled={!chatModelOptions.length}
              buttonClassName="h-11 bg-black/30 focus-visible:border-indigo-400/60"
            />
            <label className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-neutral-300">
              <span>统一文本模型</span>
              <input
                type="checkbox"
                checked={normalizedAiRoutes.useUnifiedModel}
                onChange={() => patchAiRoutes({ useUnifiedModel: !normalizedAiRoutes.useUnifiedModel })}
                className="h-4 w-4 accent-indigo-500"
              />
            </label>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 xl:grid-cols-2">
          {AI_ROUTE_LABELS.map((route) => {
            const selection = normalizedAiRoutes.routes[route.key];
            const options = route.requiresVision ? visionModelOptions : chatModelOptions;
            const selectedKey = getModelKey(selection);
            return (
              <div key={route.key} className="rounded-2xl border border-white/5 bg-black/20 p-4">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h4 className="text-sm font-semibold text-neutral-100">{route.title}</h4>
                    <p className="mt-1 text-xs leading-relaxed text-neutral-500">{route.desc}</p>
                  </div>
                  {route.requiresVision && (
                    <span className="shrink-0 rounded-full border border-indigo-400/25 bg-indigo-400/10 px-2.5 py-1 text-[10px] text-indigo-200">
                      视觉
                    </span>
                  )}
                </div>
                <ThemedSelect
                  value={selectedKey}
                  options={modelSelectOptions(
                    options,
                    route.requiresVision ? "暂无视觉模型，请在 API 页手动标记模型能力" : "暂无聊天模型",
                  )}
                  onChange={(nextValue) => updateRouteSelection(route.key, nextValue)}
                  disabled={!options.length || (normalizedAiRoutes.useUnifiedModel && route.key !== "vision_extract")}
                  buttonClassName="h-11 bg-white/[0.03] focus-visible:border-indigo-400/60"
                />
                {normalizedAiRoutes.useUnifiedModel && route.key !== "vision_extract" && (
                  <p className="mt-2 text-[11px] text-neutral-500">当前跟随统一文本模型；关闭统一开关后可单独指定。</p>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-4">
          <p className="text-xs text-neutral-500">
            当前统一模型：
            {modelOptionLabel(chatModelOptions.find((option) => option.key === getModelKey(normalizedAiRoutes.unified)))}
          </p>
          <button
            type="button"
            onClick={() => {
              void saveAiRoutes();
            }}
            disabled={routeSaving}
            className="inline-flex items-center gap-2 rounded-xl border border-indigo-500 bg-indigo-600 px-4 py-2 text-sm text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {routeSaving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存模型路由
          </button>
        </div>
      </SettingCard>
    </motion.div>
  );
}
