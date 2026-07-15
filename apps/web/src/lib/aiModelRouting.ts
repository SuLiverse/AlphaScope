import { fetchApi } from './api';

export interface ProviderModelCapabilities {
  vision?: boolean;
  embedding?: boolean;
}

export interface ProviderModelInfo {
  id: string;
  owned_by?: string;
  capabilities?: ProviderModelCapabilities;
}

export type ProviderModel = string | {
  id?: string;
  owned_by?: string;
  capabilities?: ProviderModelCapabilities;
};

export interface ModelProvider {
  id: string;
  name: string;
  type?: string;
  base_url?: string;
  enabled: boolean;
  config_json?: string;
}

export interface AiModelSelection {
  providerId: string;
  providerName?: string;
  modelId: string;
}

export type AiRouteKey =
  | 'chat'
  | 'vision_extract'
  | 'vision_reasoning'
  | 'report'
  | 'news'
  | 'agent_default'
  | 'critic'
  | 'chairman';

export interface AiModelRoutes {
  useUnifiedModel: boolean;
  unified: AiModelSelection;
  routes: Partial<Record<AiRouteKey, AiModelSelection>>;
}

export interface AiRoutingPack {
  id: string;
  name: string;
  description?: string;
  routes?: Partial<Record<AiRouteKey, AiModelSelection>>;
}

export interface ModelOption extends AiModelSelection {
  key: string;
  vision: boolean;
  embedding: boolean;
}

export const AI_ROUTE_STORAGE_KEY = 'alphascope:ai-model-routes-v1';

export const AI_ROUTE_LABELS: Array<{ key: AiRouteKey; title: string; desc: string; requiresVision?: boolean }> = [
  { key: 'chat', title: '工作台对话', desc: '主界面 AI 对话和自由问答。' },
  { key: 'vision_extract', title: '图片解析模型', desc: 'K 线截图、图像内容识别，多模态模型优先。', requiresVision: true },
  { key: 'vision_reasoning', title: '多模态推理分析', desc: '接收视觉解析结果后，负责最终诊断和投资逻辑。' },
  { key: 'report', title: '研报生成', desc: '报告页专家团、审稿与主席总结的默认模型。' },
  { key: 'news', title: '新闻助手', desc: '新闻解读、链接解析后的投研问答。' },
  { key: 'agent_default', title: '专家团默认', desc: '新增 Agent 或一键配置时使用。' },
  { key: 'critic', title: 'Critic 审稿', desc: '审稿、反证、证据覆盖和分歧检查。' },
  { key: 'chairman', title: '主席总结', desc: '最终投资委员会摘要和操作建议。' },
];

const EMBEDDING_MODEL_HINTS = [
  'embedding',
  'embed',
  'bge-',
  'bge_',
  'gte-',
  'gte_',
  'jina-embeddings',
  'text-embedding',
  'text_embedding',
];

const VISION_MODEL_HINTS = [
  'vision',
  'visual',
  'multimodal',
  'multi-modal',
  'mimo',
  'omni',
  'vl',
  'llava',
  'qwen-vl',
  'qwen2-vl',
  'qwen2.5-vl',
  'gpt-4o',
  'gpt-4.1',
  'claude-3',
  'claude-sonnet',
  'claude-opus',
  'gemini',
];

const NON_CHAT_MODEL_HINTS = [
  ...EMBEDDING_MODEL_HINTS,
  'tts',
  'voice',
  'audio',
  'speech',
  'rerank',
  'moderation',
];

export function inferModelCapabilities(modelId: string): ProviderModelCapabilities {
  const model = modelId.toLowerCase();
  const embedding = EMBEDDING_MODEL_HINTS.some((token) => model.includes(token));
  const vision = VISION_MODEL_HINTS.some((token) => model.includes(token));
  return { vision: Boolean(vision && !embedding), embedding: Boolean(embedding) };
}

export function isChatModel(modelId: string): boolean {
  const model = modelId.toLowerCase();
  return !NON_CHAT_MODEL_HINTS.some((token) => model.includes(token));
}

export function normalizeModelInfo(model: ProviderModel): ProviderModelInfo | null {
  const id = (typeof model === 'string' ? model : model.id ?? '').trim();
  if (!id) return null;
  const ownedBy = typeof model === 'string' ? '' : model.owned_by ?? '';
  const inferred = inferModelCapabilities(id);
  return {
    id,
    owned_by: ownedBy,
    capabilities: typeof model === 'string'
      ? inferred
      : {
          vision: model.capabilities?.vision ?? inferred.vision,
          embedding: model.capabilities?.embedding ?? inferred.embedding,
        },
  };
}

export function normalizeModelInfos(models?: ProviderModel[]): ProviderModelInfo[] {
  if (!models) return [];
  const seen = new Set<string>();
  return models
    .map(normalizeModelInfo)
    .filter((model): model is ProviderModelInfo => Boolean(model))
    .filter((model) => {
      if (seen.has(model.id)) return false;
      seen.add(model.id);
      return true;
    });
}

export function parseProviderConfig(provider?: Pick<ModelProvider, 'config_json'>): {
  models: ProviderModelInfo[];
  default_model?: string;
  embedding_model?: string;
} {
  if (!provider?.config_json) return { models: [] };
  try {
    const parsed = JSON.parse(provider.config_json) as {
      models?: unknown;
      default_model?: unknown;
      embedding_model?: unknown;
    };
    const rawModels = parsed.models;
    const models = Array.isArray(rawModels)
      ? normalizeModelInfos(rawModels as ProviderModel[])
      : rawModels && typeof rawModels === 'object'
        ? normalizeModelInfos(Object.keys(rawModels))
        : [];

    return {
      models,
      default_model: typeof parsed.default_model === 'string' ? parsed.default_model : undefined,
      embedding_model: typeof parsed.embedding_model === 'string' ? parsed.embedding_model : undefined,
    };
  } catch {
    return { models: [] };
  }
}

export function buildModelOptions(
  providers: ModelProvider[],
  filter: 'chat' | 'vision' | 'embedding' | 'all' = 'chat',
): ModelOption[] {
  return providers
    .filter((provider) => provider.enabled)
    .flatMap((provider) => {
      const config = parseProviderConfig(provider);
      const models = [...config.models];
      if (config.default_model && !models.some((model) => model.id === config.default_model)) {
        models.unshift({ id: config.default_model, capabilities: inferModelCapabilities(config.default_model) });
      }
      return models
        .filter((model) => {
          const vision = Boolean(model.capabilities?.vision);
          const embedding = Boolean(model.capabilities?.embedding);
          if (filter === 'vision') return vision;
          if (filter === 'embedding') return embedding;
          if (filter === 'chat') return isChatModel(model.id);
          return true;
        })
        .map((model) => ({
          providerId: provider.id,
          providerName: provider.name || provider.id,
          modelId: model.id,
          key: getModelKey({ providerId: provider.id, modelId: model.id }),
          vision: Boolean(model.capabilities?.vision),
          embedding: Boolean(model.capabilities?.embedding),
        }));
    });
}

export function getModelKey(selection?: Pick<AiModelSelection, 'providerId' | 'modelId'> | null): string {
  return selection?.providerId && selection.modelId ? `${selection.providerId}::${selection.modelId}` : '';
}

export function parseModelKey(key: string, options: ModelOption[] = []): AiModelSelection {
  const [providerId = '', modelId = ''] = key.split('::');
  const matched = options.find((option) => option.providerId === providerId && option.modelId === modelId);
  return {
    providerId,
    providerName: matched?.providerName,
    modelId,
  };
}

function isValidSelection(value: unknown): value is AiModelSelection {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<AiModelSelection>;
  return typeof item.providerId === 'string' && typeof item.modelId === 'string';
}

export function normalizeAiModelRoutes(value: unknown): AiModelRoutes {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const routesRaw = raw.routes && typeof raw.routes === 'object'
    ? raw.routes as Record<string, unknown>
    : {};
  const routes: Partial<Record<AiRouteKey, AiModelSelection>> = {};
  AI_ROUTE_LABELS.forEach(({ key }) => {
    const route = routesRaw[key];
    if (isValidSelection(route)) {
      routes[key] = {
        providerId: route.providerId,
        providerName: typeof route.providerName === 'string' ? route.providerName : undefined,
        modelId: route.modelId,
      };
    }
  });
  const unified = isValidSelection(raw.unified)
    ? {
        providerId: raw.unified.providerId,
        providerName: typeof raw.unified.providerName === 'string' ? raw.unified.providerName : undefined,
        modelId: raw.unified.modelId,
      }
    : { providerId: '', modelId: '' };
  return {
    useUnifiedModel: typeof raw.useUnifiedModel === 'boolean'
      ? raw.useUnifiedModel
      : Boolean(raw.use_unified_model ?? true),
    unified,
    routes,
  };
}

export function loadLocalAiModelRoutes(): AiModelRoutes {
  if (typeof window === 'undefined') {
    return normalizeAiModelRoutes(undefined);
  }
  try {
    return normalizeAiModelRoutes(JSON.parse(window.localStorage.getItem(AI_ROUTE_STORAGE_KEY) || '{}'));
  } catch {
    return normalizeAiModelRoutes(undefined);
  }
}

export function saveLocalAiModelRoutes(routes: AiModelRoutes) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(AI_ROUTE_STORAGE_KEY, JSON.stringify(routes));
  window.dispatchEvent(new CustomEvent('ai-model-routes-changed', { detail: routes }));
}

export function mergeAiModelRouteSources(localValue: unknown, serverValue: unknown): AiModelRoutes {
  const localRoutes = normalizeAiModelRoutes(localValue);
  if (serverValue == null) return localRoutes;
  const serverRoutes = normalizeAiModelRoutes(serverValue);
  return normalizeAiModelRoutes({
    ...localRoutes,
    ...serverRoutes,
    routes: {
      ...localRoutes.routes,
      ...serverRoutes.routes,
    },
  });
}

export function applyAiRoutingPack(current: AiModelRoutes, pack: AiRoutingPack): AiModelRoutes {
  return normalizeAiModelRoutes({
    ...current,
    useUnifiedModel: false,
    routes: {
      ...current.routes,
      ...(pack.routes || {}),
    },
  });
}

export async function loadAiModelRoutesFromApi(): Promise<AiModelRoutes> {
  const result = await fetchApi<{ preferences?: { ai_models?: unknown } }>('/api/settings/preferences');
  const localRoutes = loadLocalAiModelRoutes();
  const merged = mergeAiModelRouteSources(localRoutes, result.preferences?.ai_models);
  saveLocalAiModelRoutes(merged);
  return merged;
}

export async function saveAiModelRoutesToApi(routes: AiModelRoutes): Promise<AiModelRoutes> {
  const payload = {
    use_unified_model: routes.useUnifiedModel,
    unified: routes.unified,
    routes: routes.routes,
  };
  const result = await fetchApi<{ preferences?: { ai_models?: unknown } }>('/api/settings/preferences', {
    method: 'PUT',
    body: JSON.stringify({ preferences: { ai_models: payload } }),
  });
  const saved = normalizeAiModelRoutes(result.preferences?.ai_models ?? payload);
  saveLocalAiModelRoutes(saved);
  return saved;
}

export function pickDefaultRoutes(providers: ModelProvider[]): AiModelRoutes {
  const chat = buildModelOptions(providers, 'chat');
  const vision = buildModelOptions(providers, 'vision');
  const defaultChat = chat[0];
  const defaultVision = vision[0] ?? defaultChat;
  const unified: AiModelSelection = defaultChat
    ? { providerId: defaultChat.providerId, providerName: defaultChat.providerName, modelId: defaultChat.modelId }
    : { providerId: '', modelId: '' };
  const routes: Partial<Record<AiRouteKey, AiModelSelection>> = {};
  AI_ROUTE_LABELS.forEach(({ key }) => {
    const source = key === 'vision_extract' ? defaultVision : defaultChat;
    if (source) {
      routes[key] = {
        providerId: source.providerId,
        providerName: source.providerName,
        modelId: source.modelId,
      };
    }
  });
  return { useUnifiedModel: true, unified, routes };
}

export function ensureRoutesHaveDefaults(routes: AiModelRoutes, providers: ModelProvider[]): AiModelRoutes {
  const defaults = pickDefaultRoutes(providers);
  const nextRoutes = { ...defaults.routes, ...routes.routes };
  const unified = routes.unified.providerId && routes.unified.modelId ? routes.unified : defaults.unified;
  return {
    useUnifiedModel: routes.useUnifiedModel,
    unified,
    routes: nextRoutes,
  };
}

export function getRouteSelection(
  routes: AiModelRoutes,
  providers: ModelProvider[],
  routeKey: AiRouteKey,
): AiModelSelection {
  const options = buildModelOptions(providers, routeKey === 'vision_extract' ? 'vision' : 'chat');
  const unified = routes.unified.providerId && routes.unified.modelId ? routes.unified : undefined;
  const route = routes.routes[routeKey];
  const candidate = routes.useUnifiedModel && routeKey !== 'vision_extract' ? unified : route;
  const candidateKey = getModelKey(candidate);
  const matched = options.find((option) => option.key === candidateKey);
  if (matched) {
    return { providerId: matched.providerId, providerName: matched.providerName, modelId: matched.modelId };
  }
  const fallback = options[0];
  return fallback
    ? { providerId: fallback.providerId, providerName: fallback.providerName, modelId: fallback.modelId }
    : { providerId: '', modelId: '' };
}

export function selectionToGlobalAiSettings(selection: AiModelSelection) {
  if (!selection.providerId || !selection.modelId) return undefined;
  return {
    use_unified_key: true,
    provider: selection.providerId,
    model: selection.modelId,
  };
}

export function applyReportModelOverride(
  routes: AiModelRoutes,
  selection?: AiModelSelection,
): AiModelRoutes {
  if (!selection?.providerId || !selection.modelId) return routes;

  const selectedRoute = { ...selection };
  if (routes.useUnifiedModel) {
    return { ...routes, unified: selectedRoute };
  }

  return {
    ...routes,
    routes: {
      ...routes.routes,
      // The report pipeline invokes the agent, critic, and chairman tasks.
      report: selectedRoute,
      agent_default: selectedRoute,
      critic: selectedRoute,
      chairman: selectedRoute,
    },
  };
}

export function routesToGlobalAiSettings(routes: AiModelRoutes, providers: ModelProvider[], routeKey: AiRouteKey) {
  const selection = getRouteSelection(routes, providers, routeKey);
  const base = selectionToGlobalAiSettings(selection);
  if (!base) return undefined;
  const critic = getRouteSelection(routes, providers, 'critic');
  const chairman = getRouteSelection(routes, providers, 'chairman');
  const taskRoutes: Partial<Record<AiRouteKey, { provider: string; model: string }>> = {};
  AI_ROUTE_LABELS.forEach(({ key }) => {
    const route = getRouteSelection(routes, providers, key);
    if (route.providerId && route.modelId) {
      taskRoutes[key] = { provider: route.providerId, model: route.modelId };
    }
  });
  return {
    ...base,
    routes: taskRoutes,
    critic: critic.providerId && critic.modelId
      ? { provider: critic.providerId, model: critic.modelId, inherit_global_key: false }
      : undefined,
    chairman: chairman.providerId && chairman.modelId
      ? { provider: chairman.providerId, model: chairman.modelId, inherit_global_key: false }
      : undefined,
  };
}
