/**
 * Settings · Agent roundtable orchestration tab.
 */
import { Bot, BrainCircuit, Plus, Sparkles, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import { cn } from "../../lib/utils";
import {
  buildModelOptions,
  getModelKey,
  parseModelKey,
  type ModelOption,
  type ModelProvider,
} from "../../lib/aiModelRouting";
import type { AgentConfig, AgentIconKey } from "../../lib/agentConfigs";
import { ThemedSelect, type ThemedSelectOption } from "../ThemedSelect";
import { AGENT_ICON_MAP, AGENT_ICON_OPTIONS } from "./types";
import { SettingCard, TextField } from "./fields";

export interface AgentsTabProps {
  agentConfigs: AgentConfig[];
  selectedAgent: AgentConfig;
  selectedAgentId: string;
  setSelectedAgentId: (id: string) => void;
  enabledAgentCount: number;
  runtimeAgentCount: number;
  agentProviderOptions: ThemedSelectOption[];
  agentModelOptions: ThemedSelectOption[];
  chatModelOptions: ModelOption[];
  providers: ModelProvider[];
  applyAgentDefaultModel: () => void;
  addAgent: () => void;
  deleteAgent: (id: string) => void;
  updateAgent: (id: string, patch: Partial<AgentConfig>) => void;
}

export function AgentsTab({
  agentConfigs,
  selectedAgent,
  selectedAgentId,
  setSelectedAgentId,
  enabledAgentCount,
  runtimeAgentCount,
  agentProviderOptions,
  agentModelOptions,
  chatModelOptions,
  providers,
  applyAgentDefaultModel,
  addAgent,
  deleteAgent,
  updateAgent,
}: AgentsTabProps) {
  return (
    <motion.div
      key="agents"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="max-w-5xl space-y-5"
    >
      <SettingCard title="Agent 圆桌编排" desc="统一维护专家团数量、启用状态、模型参数和系统提示词。" icon={BrainCircuit}>
        <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-3">
            {(
              [
                ["总席位", agentConfigs.length, "当前圆桌中的 Agent 数量。"],
                ["已启用", enabledAgentCount, "会传入分析请求的 Agent。"],
                ["请求配置", runtimeAgentCount, "agent_configs 输出项。"],
              ] as const
            ).map(([label, value, hint]) => (
              <div key={label} className="rounded-xl border border-white/5 bg-white/[0.025] px-4 py-3">
                <p className="text-[10px] font-mono tracking-wider text-neutral-500">{label}</p>
                <p className="mt-1 text-lg font-semibold text-white">{value}</p>
                <p className="mt-1 text-[11px] text-neutral-500">{hint}</p>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={applyAgentDefaultModel}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-indigo-500/25 bg-indigo-500/10 px-3 py-2 text-xs font-medium text-indigo-200 transition-colors hover:bg-indigo-500/15"
          >
            <Sparkles className="h-4 w-4" />
            应用默认模型到全部 Agent
          </button>
        </div>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
          <div className="rounded-2xl border border-white/5 bg-black/20 p-3">
            <div className="mb-3 flex items-center justify-between gap-3 px-1">
              <span className="text-xs font-medium text-neutral-300">专家席位</span>
              <button
                type="button"
                data-testid="settings-agent-add"
                onClick={addAgent}
                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1.5 text-xs text-emerald-300 transition-colors hover:bg-emerald-500/15"
              >
                <Plus className="h-3.5 w-3.5" />
                新增
              </button>
            </div>

            <div className="max-h-[34rem] space-y-2 overflow-y-auto pr-1 custom-scrollbar">
              {agentConfigs.map((agent) => {
                const Icon = AGENT_ICON_MAP[agent.iconKey as AgentIconKey] ?? Bot;
                const isActive = selectedAgentId === agent.id;
                return (
                  <button
                    key={agent.id}
                    type="button"
                    data-testid={`settings-agent-${agent.id}`}
                    onClick={() => setSelectedAgentId(agent.id)}
                    className={cn(
                      "w-full rounded-xl border px-3 py-3 text-left transition-colors",
                      isActive
                        ? "border-indigo-500/35 bg-indigo-500/10"
                        : "border-white/5 bg-white/[0.02] hover:bg-white/[0.04]",
                    )}
                  >
                    <span className="flex items-center gap-3">
                      <span
                        className={cn(
                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border",
                          agent.enabled
                            ? "border-indigo-500/25 bg-indigo-500/10 text-indigo-300"
                            : "border-white/10 bg-black/25 text-neutral-600",
                        )}
                      >
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-neutral-100">{agent.name}</span>
                        <span className="mt-0.5 block truncate font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                          {agent.role}
                        </span>
                      </span>
                      <span
                        className={cn(
                          "shrink-0 rounded-md border px-2 py-0.5 text-[10px]",
                          agent.enabled
                            ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                            : "border-white/10 bg-black/25 text-neutral-500",
                        )}
                      >
                        {agent.enabled ? "启用" : "停用"}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="rounded-2xl border border-white/5 bg-black/20 p-5">
            <div className="mb-5 flex flex-col gap-3 border-b border-white/5 pb-4 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-indigo-300">Selected Agent</p>
                <h4 className="mt-1 truncate text-lg font-semibold text-white">{selectedAgent.name}</h4>
                <p className="mt-1 text-xs text-neutral-500">保存后会同步到专家圆桌页和分析请求。</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300">
                  <input
                    type="checkbox"
                    checked={selectedAgent.enabled}
                    onChange={() =>
                      updateAgent(selectedAgent.id, {
                        enabled: !selectedAgent.enabled,
                        status: selectedAgent.enabled ? "idle" : selectedAgent.status,
                      })
                    }
                    className="accent-indigo-500"
                  />
                  参与分析
                </label>
                <button
                  type="button"
                  data-testid="settings-agent-delete"
                  onClick={() => deleteAgent(selectedAgent.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300 transition-colors hover:bg-rose-500/15"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  删除
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <TextField
                label="名称"
                value={selectedAgent.name}
                onChange={(value) => updateAgent(selectedAgent.id, { name: value })}
              />
              <TextField
                label="角色标签"
                value={selectedAgent.role}
                onChange={(value) => updateAgent(selectedAgent.id, { role: value })}
              />
              <label className="block md:col-span-2">
                <span className="mb-2 block text-xs font-medium text-neutral-400">职责说明</span>
                <textarea
                  value={selectedAgent.description}
                  onChange={(event) => updateAgent(selectedAgent.id, { description: event.target.value })}
                  rows={3}
                  className="w-full resize-none rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm leading-relaxed text-neutral-100 outline-none transition-all custom-scrollbar placeholder:text-neutral-700 focus:border-indigo-500/50 focus:bg-white/[0.05]"
                />
              </label>

              <label className="block">
                <span className="mb-2 block text-xs font-medium text-neutral-400">Provider</span>
                <ThemedSelect
                  value={selectedAgent.provider}
                  options={agentProviderOptions}
                  onChange={(providerId) => {
                    const firstModel = buildModelOptions(
                      providers.filter((provider) => provider.id === providerId),
                      "chat",
                    )[0];
                    updateAgent(selectedAgent.id, {
                      provider: providerId,
                      model: firstModel?.modelId || selectedAgent.model,
                    });
                  }}
                  buttonClassName="h-[42px] bg-white/[0.03] focus-visible:border-indigo-500/50"
                />
              </label>

              <label className="block">
                <span className="mb-2 block text-xs font-medium text-neutral-400">模型</span>
                <ThemedSelect
                  value={getModelKey({ providerId: selectedAgent.provider, modelId: selectedAgent.model })}
                  options={agentModelOptions}
                  onChange={(nextValue) => {
                    const selection = parseModelKey(nextValue, chatModelOptions);
                    updateAgent(selectedAgent.id, { provider: selection.providerId, model: selection.modelId });
                  }}
                  disabled={!chatModelOptions.length && !selectedAgent.model}
                  buttonClassName="h-[42px] bg-white/[0.03] focus-visible:border-indigo-500/50"
                />
              </label>

              <label className="block">
                <span className="mb-2 flex items-center justify-between gap-3 text-xs font-medium text-neutral-400">
                  温度
                  <span className="font-mono text-indigo-300">{selectedAgent.temperature.toFixed(2)}</span>
                </span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={selectedAgent.temperature}
                  onChange={(event) => updateAgent(selectedAgent.id, { temperature: Number(event.target.value) })}
                  className="h-10 w-full accent-indigo-500"
                />
              </label>

              <div className="md:col-span-2">
                <span className="mb-2 block text-xs font-medium text-neutral-400">图标</span>
                <div className="grid grid-cols-4 gap-2 md:grid-cols-7">
                  {AGENT_ICON_OPTIONS.map((option) => {
                    const Icon = AGENT_ICON_MAP[option.key];
                    return (
                      <button
                        key={option.key}
                        type="button"
                        title={option.label}
                        onClick={() => updateAgent(selectedAgent.id, { iconKey: option.key })}
                        className={cn(
                          "flex h-10 items-center justify-center rounded-xl border transition-colors",
                          selectedAgent.iconKey === option.key
                            ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-300"
                            : "border-white/10 bg-white/[0.02] text-neutral-500 hover:text-neutral-300",
                        )}
                      >
                        <Icon className="h-4 w-4" />
                      </button>
                    );
                  })}
                </div>
              </div>

              <label className="block md:col-span-2">
                <span className="mb-2 block text-xs font-medium text-neutral-400">系统提示词</span>
                <textarea
                  value={selectedAgent.prompt}
                  onChange={(event) => updateAgent(selectedAgent.id, { prompt: event.target.value })}
                  rows={9}
                  className="w-full resize-none rounded-xl border border-white/10 bg-white/[0.03] px-3 py-3 text-sm leading-relaxed text-neutral-100 outline-none transition-all custom-scrollbar placeholder:text-neutral-700 focus:border-indigo-500/50 focus:bg-white/[0.05]"
                />
              </label>
            </div>
          </div>
        </div>
      </SettingCard>
    </motion.div>
  );
}
