/**
 * Settings pure helpers and storage/API loaders.
 */
import { API_BASE_URL, API_KEY, LOCAL_API_TOKEN, type ApiResponse } from "../../lib/api";
import type { ModelOption, ProviderModelInfo } from "../../lib/aiModelRouting";
import {
  DEFAULT_API_BASE_URL,
  DEFAULT_SETTINGS,
  LEGACY_SETTINGS_STORAGE_KEY,
  SETTING_TABS,
  SETTINGS_STORAGE_KEY,
  type ProviderDraft,
  type ProviderListItem,
  type SettingTab,
  type SettingsModelProvider,
  type SettingsState,
} from "./types";

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


export function normalizeSettingTab(value?: string): SettingTab {
  return SETTING_TABS.some((tab) => tab.id === value) ? (value as SettingTab) : "api";
}
