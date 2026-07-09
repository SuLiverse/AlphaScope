/**
 * Settings types, helpers, and small UI primitives (extracted from Settings.tsx).
 */
import type { ComponentType, ReactNode } from "react";
import {
  Activity,
  BarChart3,
  Bell,
  Bot,
  BrainCircuit,
  Database,
  Globe,
  Key,
  Settings2,
  Shield,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { API_BASE_URL, API_KEY, LOCAL_API_TOKEN, type ApiResponse } from "../../lib/api";
import {
  type ModelOption,
  type ModelProvider,
  type ProviderModelInfo,
} from "../../lib/aiModelRouting";
import {
  type AgentIconKey,
} from "../../lib/agentConfigs";
import { type ThemedSelectOption } from "../ThemedSelect";

export type SettingTab = 'general' | 'models' | 'agents' | 'api' | 'network' | 'security' | 'data' | 'notifiers';
export const DEFAULT_API_BASE_URL = 'http://localhost:8000';

export const SETTING_TABS: Array<{ id: SettingTab; label: string; icon: ComponentType<{ className?: string }> }> = [
  { id: 'general', label: '基础设置', icon: Settings2 },
  { id: 'models', label: '模型路由', icon: Bot },
  { id: 'agents', label: 'Agent 编排', icon: BrainCircuit },
  { id: 'api', label: 'API 密钥', icon: Key },
  { id: 'network', label: '网络节点', icon: Globe },
  { id: 'security', label: '安全策略', icon: Shield },
  { id: 'data', label: '数据源健康', icon: Database },
  { id: 'notifiers', label: '通知推送', icon: Bell },
];

export const AGENT_ICON_MAP: Record<AgentIconKey, ComponentType<{ className?: string }>> = {
  macro: Globe,
  fundamental: BarChart3,
  quant: TrendingUp,
  risk: ShieldCheck,
  data: Database,
  execution: Activity,
  custom: Bot,
};

export const AGENT_ICON_OPTIONS: Array<{ key: AgentIconKey; label: string }> = [
  { key: 'macro', label: '宏观' },
  { key: 'fundamental', label: '基本面' },
  { key: 'quant', label: '量化' },
  { key: 'risk', label: '风控' },
  { key: 'data', label: '数据' },
  { key: 'execution', label: '执行' },
  { key: 'custom', label: '自定义' },
];

export const DEFAULT_SETTINGS = {
  defaultStock: '贵州茅台 (600519.SH)',
  language: '简体中文',
  density: '紧凑',
  autoRefresh: true,
  pushNotice: true,
  apiBaseUrl: API_BASE_URL,
  timeoutSeconds: 12,
  retryCount: 2,
  sseEnabled: true,
  maskKeys: true,
  confirmDangerousActions: true,
  auditLog: true,
  windKey: 'wind-demo-token-configured',
  llmKey: '',
  knowledgeEnabled: true,
  sharedKnowledge: true,
  agentMemory: true,
  autoWriteAgentMemory: true,
  embeddingProviderId: '',
  embeddingModel: '',
  memoryRetentionDays: 90,
  activeProvider: '腾讯行情 + 东财数据中心',
};

export type SettingsState = typeof DEFAULT_SETTINGS;
export const SETTINGS_STORAGE_KEY = 'alphascope:ui-settings';
export const LEGACY_SETTINGS_STORAGE_KEY = `${['ai', 'finance'].join('-')}:ui-settings`;
export const DRAFT_PROVIDER_ID = '__draft_provider__';

export type SettingsModelProvider = ModelProvider & { base_url: string; api_key_masked?: string };

export interface ProviderDraft {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  enabled: boolean;
}

export type ProviderListItem = SettingsModelProvider & { isDraft?: boolean };

export function createEmptyProviderDraft(index = 1, existingIds: string[] = []): ProviderDraft {
  let nextIndex = Math.max(1, index);
  let id = `custom-provider-${nextIndex}`;
  while (existingIds.includes(id)) {
    nextIndex += 1;
    id = `custom-provider-${nextIndex}`;
  }

  return {
    id,
    name: nextIndex > 1 ? `自定义 Provider ${nextIndex}` : '自定义 Provider',
    base_url: '',
    api_key: '',
    enabled: true,
  };
}

export function draftToProviderListItem(draft: ProviderDraft): ProviderListItem {
  return {
    id: draft.id,
    name: draft.name,
    type: 'openai_compatible',
    base_url: draft.base_url,
    enabled: draft.enabled,
    config_json: '{}',
    isDraft: true,
  };
}

export function draftFromProvider(provider: SettingsModelProvider): ProviderDraft {
  return {
    id: provider.id,
    name: provider.name,
    base_url: provider.base_url,
    api_key: '',
    enabled: provider.enabled,
  };
}

export function modelInfoToConfigModel(model: ProviderModelInfo) {
  return {
    id: model.id,
    owned_by: model.owned_by ?? '',
    capabilities: {
      vision: Boolean(model.capabilities?.vision),
      embedding: Boolean(model.capabilities?.embedding),
    },
  };
}

export function getModelCapability(model: ProviderModelInfo): 'embedding' | 'vision' | 'text' {
  if (model.capabilities?.embedding) return 'embedding';
  if (model.capabilities?.vision) return 'vision';
  return 'text';
}

export function getModelCapabilityLabel(model: ProviderModelInfo): string {
  const capability = getModelCapability(model);
  if (capability === 'embedding') return '嵌入';
  if (capability === 'vision') return '视觉';
  return '文本';
}

export function getModelCapabilityClass(model: ProviderModelInfo): string {
  const capability = getModelCapability(model);
  if (capability === 'embedding') return 'border-amber-400/30 bg-amber-400/10 text-amber-200';
  if (capability === 'vision') return 'border-indigo-400/30 bg-indigo-400/10 text-indigo-200';
  return 'border-white/10 bg-white/[0.04] text-neutral-300';
}

export function modelOptionLabel(option?: ModelOption) {
  if (!option) return '未选择';
  const tags = [
    option.vision ? '视觉' : '',
    option.embedding ? '嵌入' : '',
  ].filter(Boolean);
  return `${option.providerName} / ${option.modelId}${tags.length ? ` · ${tags.join('/')}` : ''}`;
}

export async function requestSettingsApi<T>(endpoint: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const headers = new Headers(options?.headers);
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (API_KEY && !headers.has('X-API-Key') && !headers.has('Authorization')) {
    headers.set('X-API-Key', API_KEY);
  }
  if (LOCAL_API_TOKEN && !headers.has('X-AlphaScope-Local-Token')) {
    headers.set('X-AlphaScope-Local-Token', LOCAL_API_TOKEN);
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    return { success: false, error: `HTTP ${response.status} ${response.statusText}` };
  }

  return response.json() as Promise<ApiResponse<T>>;
}

export function loadSettings(): SettingsState {
  if (typeof window === 'undefined') return DEFAULT_SETTINGS;

  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY)
      ?? window.localStorage.getItem(LEGACY_SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;

    const parsed = JSON.parse(raw) as Partial<SettingsState>;
    const settings = { ...DEFAULT_SETTINGS, ...parsed };
    if (!parsed.apiBaseUrl || (parsed.apiBaseUrl === DEFAULT_API_BASE_URL && API_BASE_URL !== DEFAULT_API_BASE_URL)) {
      settings.apiBaseUrl = API_BASE_URL;
    }
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    return settings;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function SettingCard({
  title,
  desc,
  icon: Icon,
  children,
}: {
  title: string;
  desc: string;
  icon: ComponentType<{ className?: string }>;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-white/5 bg-black/20 p-5">
      <div className="mb-5 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-indigo-500/20 bg-indigo-500/10">
          <Icon className="h-4 w-4 text-indigo-300" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-neutral-100">{title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-neutral-500">{desc}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-white/5 bg-white/[0.025] px-4 py-3">
      <span>
        <span className="block text-sm text-neutral-200">{label}</span>
        <span className="mt-1 block text-xs text-neutral-500">{hint}</span>
      </span>
      <input type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 accent-indigo-500" />
    </label>
  );
}

export function TextField({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  disabled = false,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-neutral-400">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-neutral-100 outline-none transition-all placeholder:text-neutral-700 focus:border-indigo-500/50 focus:bg-white/[0.05] disabled:cursor-not-allowed disabled:text-neutral-500"
      />
    </label>
  );
}

export interface SettingsProps {
  initialTab?: string;
}

export function normalizeSettingTab(value?: string): SettingTab {
  return SETTING_TABS.some((tab) => tab.id === value) ? value as SettingTab : 'api';
}

export function modelSelectOptions(options: ModelOption[], emptyLabel: string): ThemedSelectOption[] {
  return options.length
    ? options.map((option) => ({
      value: option.key,
      label: modelOptionLabel(option),
      badge: option.vision ? <span className="rounded-full bg-indigo-400/10 px-1.5 py-0.5 text-[9px] text-indigo-200">视觉</span> : undefined,
    }))
    : [{ value: '', label: emptyLabel, disabled: true }];
}


