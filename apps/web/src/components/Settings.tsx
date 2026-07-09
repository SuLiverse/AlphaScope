import { useEffect, useMemo, useState } from 'react';
import type { ComponentType, ReactNode } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Bell,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleMinus,
  CirclePlus,
  Eye,
  EyeOff,
  Filter,
  Layers3,
  Monitor,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Server,
  Shield,
  Sparkles,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { API_BASE_URL } from '../lib/api';
import { ProviderHealthPanel } from './ProviderHealthPanel';
import { DataSourceConfigPanel } from './DataSourceConfigPanel';
import { NotifierSettings } from './NotifierSettings';
import {
  AI_ROUTE_LABELS,
  AiModelRoutes,
  AiRouteKey,
  buildModelOptions,
  ensureRoutesHaveDefaults,
  getModelKey,
  inferModelCapabilities,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
  normalizeAiModelRoutes,
  normalizeModelInfos,
  parseModelKey,
  parseProviderConfig,
  pickDefaultRoutes,
  saveAiModelRoutesToApi,
  saveLocalAiModelRoutes,
} from '../lib/aiModelRouting';
import type { ProviderModel, ProviderModelCapabilities, ProviderModelInfo } from '../lib/aiModelRouting';
import {
  AgentConfig,
  DEFAULT_AGENT_CONFIGS,
  createCustomAgentConfig,
  getEnabledAgentRuntimeConfigs,
  loadAgentConfigs,
  saveAgentConfigs,
} from '../lib/agentConfigs';
import { ThemedSelect, type ThemedSelectOption } from './ThemedSelect';
import { dispatchSettingsChanged } from '../lib/workspaceEvents';
import {
  type SettingTab,
  type SettingsState,
  type SettingsProps,
  type ProviderDraft,
  type SettingsModelProvider,
  type ProviderListItem,
  DEFAULT_SETTINGS,
  SETTING_TABS,
  SETTINGS_STORAGE_KEY,
  LEGACY_SETTINGS_STORAGE_KEY,
  DRAFT_PROVIDER_ID,
  AGENT_ICON_MAP,
  AGENT_ICON_OPTIONS,
  createEmptyProviderDraft,
  draftToProviderListItem,
  draftFromProvider,
  modelInfoToConfigModel,
  getModelCapabilityLabel,
  getModelCapabilityClass,
  modelOptionLabel,
  loadSettings,
  requestSettingsApi,
  SettingCard,
  ToggleRow,
  TextField,
  normalizeSettingTab,
  modelSelectOptions,
  ModelsTab,
  AgentsTab,
  SimplePrefsTabs,
  SettingsStatusBar,
} from './settings/index';

export function Settings({ initialTab }: SettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingTab>(() => normalizeSettingTab(initialTab));
  const [settings, setSettings] = useState<SettingsState>(() => loadSettings());
  const [savedMessage, setSavedMessage] = useState('配置仅保存在当前浏览器预览环境');
  const [agentConfigs, setAgentConfigs] = useState<AgentConfig[]>(() => loadAgentConfigs());
  const [selectedAgentId, setSelectedAgentId] = useState(() => loadAgentConfigs()[0]?.id ?? DEFAULT_AGENT_CONFIGS[0].id);
  const [providers, setProviders] = useState<SettingsModelProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [providerDraft, setProviderDraft] = useState<ProviderDraft>(() => createEmptyProviderDraft());
  const [providerModels, setProviderModels] = useState<ProviderModelInfo[]>([]);
  const [discoveredModels, setDiscoveredModels] = useState<ProviderModelInfo[]>([]);
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [modelSearch, setModelSearch] = useState('');
  const [modelCapabilityFilter, setModelCapabilityFilter] = useState<'all' | 'vision' | 'text' | 'embedding'>('all');
  const [providerStatus, setProviderStatus] = useState('正在载入 Provider 配置...');
  const [providerLoading, setProviderLoading] = useState(false);
  const [providerTesting, setProviderTesting] = useState(false);
  const [providerFetchingModels, setProviderFetchingModels] = useState(false);
  const [providerSearch, setProviderSearch] = useState('');
  const [showProviderKey, setShowProviderKey] = useState(false);
  const [aiModelRoutes, setAiModelRoutes] = useState<AiModelRoutes>(() => loadLocalAiModelRoutes());
  const [routeSaving, setRouteSaving] = useState(false);

  useEffect(() => {
    setActiveTab(normalizeSettingTab(initialTab));
  }, [initialTab]);

  useEffect(() => {
    if (agentConfigs.length && !agentConfigs.some((agent) => agent.id === selectedAgentId)) {
      setSelectedAgentId(agentConfigs[0].id);
    }
  }, [agentConfigs, selectedAgentId]);

  const activeTitle = useMemo(
    () => SETTING_TABS.find((tab) => tab.id === activeTab)?.label ?? '系统设置',
    [activeTab],
  );
  const selectedAgent = useMemo(
    () => agentConfigs.find((agent) => agent.id === selectedAgentId) ?? agentConfigs[0],
    [agentConfigs, selectedAgentId],
  );
  const enabledAgentCount = useMemo(() => agentConfigs.filter((agent) => agent.enabled).length, [agentConfigs]);
  const runtimeAgentCount = useMemo(() => getEnabledAgentRuntimeConfigs(agentConfigs).length, [agentConfigs]);
  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId),
    [providers, selectedProviderId],
  );
  const chatModelOptions = useMemo(() => buildModelOptions(providers, 'chat'), [providers]);
  const visionModelOptions = useMemo(() => buildModelOptions(providers, 'vision'), [providers]);
  const normalizedAiRoutes = useMemo(
    () => ensureRoutesHaveDefaults(aiModelRoutes, providers),
    [aiModelRoutes, providers],
  );
  const isProviderDraft = selectedProviderId === DRAFT_PROVIDER_ID;
  const storedProviderConfig = useMemo(() => parseProviderConfig(selectedProvider), [selectedProvider]);
  const visibleProviderModels = providerModels.length ? providerModels : storedProviderConfig.models;
  const visibleModelIds = useMemo(() => new Set(visibleProviderModels.map((model) => model.id)), [visibleProviderModels]);
  const embeddingModelOptions = useMemo(
    () => {
      const options = visibleProviderModels.filter((model) => model.capabilities?.embedding);
      if (
        settings.embeddingModel
        && settings.embeddingProviderId === providerDraft.id
        && !options.some((model) => model.id === settings.embeddingModel)
      ) {
        const selected = visibleProviderModels.find((model) => model.id === settings.embeddingModel);
        if (selected) return [selected, ...options];
      }
      return options;
    },
    [providerDraft.id, settings.embeddingModel, settings.embeddingProviderId, visibleProviderModels],
  );
  const filteredDiscoveredModels = useMemo(() => {
    const keyword = modelSearch.trim().toLowerCase();
    return discoveredModels.filter((model) => {
      const matchesKeyword = !keyword || [model.id, model.owned_by ?? ''].some((value) => value.toLowerCase().includes(keyword));
      const isEmbedding = Boolean(model.capabilities?.embedding);
      const isVision = Boolean(model.capabilities?.vision);
      const matchesCapability =
        modelCapabilityFilter === 'all'
        || (modelCapabilityFilter === 'vision' && isVision)
        || (modelCapabilityFilter === 'embedding' && isEmbedding)
        || (modelCapabilityFilter === 'text' && !isVision && !isEmbedding);
      return matchesKeyword && matchesCapability;
    });
  }, [discoveredModels, modelCapabilityFilter, modelSearch]);
  const providerListItems = useMemo<ProviderListItem[]>(() => {
    if (!isProviderDraft || !providerDraft.id.trim()) return providers;
    const draftItem = draftToProviderListItem(providerDraft);
    return [draftItem, ...providers.filter((provider) => provider.id !== draftItem.id)];
  }, [isProviderDraft, providerDraft, providers]);
  const filteredProviders = useMemo(() => {
    const keyword = providerSearch.trim().toLowerCase();
    if (!keyword) return providerListItems;
    return providerListItems.filter((provider) =>
      [provider.name, provider.id, provider.base_url].some((value) => value.toLowerCase().includes(keyword)),
    );
  }, [providerListItems, providerSearch]);
  const agentProviderOptions = useMemo<ThemedSelectOption[]>(
    () => [
      { value: '', label: '跟随后端默认' },
      ...providers
        .filter((provider) => provider.enabled)
        .map((provider) => ({ value: provider.id, label: provider.name || provider.id })),
    ],
    [providers],
  );
  const agentModelOptions = useMemo<ThemedSelectOption[]>(() => {
    const filtered = chatModelOptions.filter((option) => !selectedAgent?.provider || option.providerId === selectedAgent.provider);
    const options = modelSelectOptions(filtered, '请先在 API 密钥页获取模型列表');
    if (
      selectedAgent?.model
      && !chatModelOptions.some((option) => option.providerId === selectedAgent.provider && option.modelId === selectedAgent.model)
    ) {
      return [
        ...options.filter((option) => option.value !== ''),
        {
          value: getModelKey({ providerId: selectedAgent.provider, modelId: selectedAgent.model }),
          label: `${selectedAgent.provider || '默认'} / ${selectedAgent.model}`,
        },
      ];
    }
    return options;
  }, [chatModelOptions, selectedAgent]);
  const embeddingSelectOptions = useMemo<ThemedSelectOption[]>(
    () => [
      { value: '', label: '未选择' },
      ...embeddingModelOptions.map((model) => ({ value: model.id, label: model.id })),
    ],
    [embeddingModelOptions],
  );

  const updateSetting = <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const patchAiRoutes = (patch: Partial<AiModelRoutes>) => {
    setAiModelRoutes((prev) => {
      const next = { ...prev, ...patch, routes: patch.routes ?? prev.routes };
      saveLocalAiModelRoutes(next);
      return next;
    });
  };

  const updateRouteSelection = (routeKey: AiRouteKey, modelKey: string) => {
    const options = routeKey === 'vision_extract' ? visionModelOptions : chatModelOptions;
    const selection = parseModelKey(modelKey, options);
    patchAiRoutes({
      useUnifiedModel: false,
      routes: {
        ...normalizedAiRoutes.routes,
        [routeKey]: selection,
      },
    });
  };

  const applyUnifiedModel = (modelKey: string) => {
    const selection = parseModelKey(modelKey, chatModelOptions);
    const nextRoutes = { ...normalizedAiRoutes.routes };
    AI_ROUTE_LABELS.forEach(({ key }) => {
      if (key !== 'vision_extract') {
        nextRoutes[key] = selection;
      }
    });
    patchAiRoutes({ useUnifiedModel: true, unified: selection, routes: nextRoutes });
  };

  const applyRouteDefaults = () => {
    const next = pickDefaultRoutes(providers);
    patchAiRoutes(next);
    setSavedMessage('已按当前 Provider 一键生成默认模型路由');
  };

  const saveAiRoutes = async (routes: AiModelRoutes = normalizedAiRoutes) => {
    setRouteSaving(true);
    try {
      const saved = await saveAiModelRoutesToApi(routes);
      setAiModelRoutes(saved);
      setSavedMessage(`已保存模型路由，${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`);
      dispatchSettingsChanged('ai-routes');
    } catch (error) {
      setSavedMessage(error instanceof Error ? `模型路由保存失败：${error.message}` : '模型路由保存失败');
    } finally {
      setRouteSaving(false);
    }
  };

  const updateProviderModelCapabilities = (modelId: string, patch: Partial<ProviderModelCapabilities>) => {
    const applyPatch = (model: ProviderModelInfo) => (
      model.id === modelId
        ? { ...model, capabilities: { ...inferModelCapabilities(model.id), ...model.capabilities, ...patch } }
        : model
    );
    setDiscoveredModels((prev) => prev.map(applyPatch));
    setProviderModels((prev) => {
      const current = prev.length ? prev : visibleProviderModels;
      return current.map(applyPatch);
    });
  };

  const loadKnowledgePreferences = async () => {
    const result = await requestSettingsApi<{ preferences: { knowledge?: Record<string, unknown>; ai_models?: unknown } }>('/api/settings/preferences');
    if (!result.success || !result.data?.preferences?.knowledge) {
      if (result.data?.preferences?.ai_models) {
        setAiModelRoutes(ensureRoutesHaveDefaults(normalizeAiModelRoutes(result.data.preferences.ai_models), providers));
      }
      return;
    }

    const knowledge = result.data.preferences.knowledge;
    setSettings((prev) => ({
      ...prev,
      knowledgeEnabled: Boolean(knowledge.enabled ?? prev.knowledgeEnabled),
      sharedKnowledge: Boolean(knowledge.shared_knowledge ?? prev.sharedKnowledge),
      agentMemory: Boolean(knowledge.agent_memory ?? prev.agentMemory),
      autoWriteAgentMemory: Boolean(knowledge.auto_write_agent_memory ?? prev.autoWriteAgentMemory),
      embeddingProviderId: typeof knowledge.embedding_provider_id === 'string' ? knowledge.embedding_provider_id : prev.embeddingProviderId,
      embeddingModel: typeof knowledge.embedding_model === 'string' ? knowledge.embedding_model : prev.embeddingModel,
      memoryRetentionDays: Number(knowledge.memory_retention_days ?? prev.memoryRetentionDays) || prev.memoryRetentionDays,
    }));
    if (result.data.preferences.ai_models) {
      const routes = ensureRoutesHaveDefaults(normalizeAiModelRoutes(result.data.preferences.ai_models), providers);
      setAiModelRoutes(routes);
      saveLocalAiModelRoutes(routes);
    }
  };

  const saveKnowledgePreferences = async (nextSettings: SettingsState = settings) => {
    await requestSettingsApi<{ preferences: unknown }>('/api/settings/preferences', {
      method: 'PUT',
      body: JSON.stringify({
        preferences: {
          knowledge: {
            enabled: nextSettings.knowledgeEnabled,
            shared_knowledge: nextSettings.sharedKnowledge,
            agent_memory: nextSettings.agentMemory,
            auto_write_agent_memory: nextSettings.autoWriteAgentMemory,
            embedding_provider_id: nextSettings.embeddingProviderId,
            embedding_model: nextSettings.embeddingModel,
            memory_retention_days: nextSettings.memoryRetentionDays,
          },
        },
      }),
    });
  };

  const buildProviderConfigJson = () => {
    const modelIds = visibleProviderModels.map((model) => model.id);
    const config = {
      ...storedProviderConfig,
      models: visibleProviderModels.map(modelInfoToConfigModel),
      default_model: storedProviderConfig.default_model && modelIds.includes(storedProviderConfig.default_model)
        ? storedProviderConfig.default_model
        : modelIds[0] ?? '',
      embedding_model: settings.embeddingProviderId === providerDraft.id ? settings.embeddingModel : '',
    };
    return JSON.stringify(config);
  };

  const loadProviders = async (preferredProviderId?: string) => {
    setProviderLoading(true);
    const result = await requestSettingsApi<{ providers: SettingsModelProvider[] }>('/api/settings/providers');
    setProviderLoading(false);

    if (!result.success || !result.data) {
      setProviderStatus(result.error || 'Provider 配置读取失败，请确认后端服务已启动');
      return;
    }

    const nextProviders = result.data.providers || [];
    setProviders(nextProviders);
    setAiModelRoutes((current) => {
      const nextRoutes = ensureRoutesHaveDefaults(current, nextProviders);
      saveLocalAiModelRoutes(nextRoutes);
      return nextRoutes;
    });

    const nextSelected =
      preferredProviderId && nextProviders.some((provider) => provider.id === preferredProviderId)
        ? preferredProviderId
        : nextProviders[0]?.id || '';
    setSelectedProviderId(nextSelected);

    if (nextSelected) {
      const provider = nextProviders.find((item) => item.id === nextSelected);
      if (provider) {
        setProviderDraft(draftFromProvider(provider));
        setProviderModels(parseProviderConfig(provider).models);
      }
      setProviderStatus(`已载入 ${nextProviders.length} 个 Provider`);
    } else {
      const draft = createEmptyProviderDraft(1, nextProviders.map((provider) => provider.id));
      setProviderDraft(draft);
      setSelectedProviderId(DRAFT_PROVIDER_ID);
      setProviderModels([]);
      setProviderStatus('还没有 Provider，新增后填写 Base URL 和 API Key');
    }
  };

  const saveProvider = async (): Promise<SettingsModelProvider | null> => {
    if (!providerDraft.id.trim() || !providerDraft.name.trim() || !providerDraft.base_url.trim()) {
      setProviderStatus('Provider ID、名称和 Base URL 都不能为空');
      return null;
    }

    setProviderLoading(true);
    const result = await requestSettingsApi<SettingsModelProvider>('/api/settings/providers', {
      method: 'POST',
      body: JSON.stringify({
        id: providerDraft.id.trim(),
        name: providerDraft.name.trim(),
        base_url: providerDraft.base_url.trim(),
        api_key: providerDraft.api_key.trim(),
        enabled: providerDraft.enabled,
        config_json: buildProviderConfigJson(),
      }),
    });
    setProviderLoading(false);

    if (!result.success || !result.data) {
      setProviderStatus(result.error || 'Provider 保存失败');
      return null;
    }

    setProviderDraft(draftFromProvider(result.data));
    setProviderModels(parseProviderConfig(result.data).models);
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    await saveKnowledgePreferences();
    await loadProviders(result.data.id);
    setProviderStatus(`已保存 Provider：${result.data.name}`);
    dispatchSettingsChanged('providers');
    return result.data;
  };

  const addProvider = () => {
    const draft = createEmptyProviderDraft(providers.length + 1, providers.map((provider) => provider.id));
    setSelectedProviderId(DRAFT_PROVIDER_ID);
    setProviderDraft(draft);
    setProviderModels([]);
    setDiscoveredModels([]);
    setProviderSearch('');
    setModelSearch('');
    setShowProviderKey(false);
    setProviderStatus('正在新增 Provider，保存后会写入后端配置');
  };

  const deleteProvider = async () => {
    if (!selectedProvider) {
      setProviderStatus('当前 Provider 还未保存，无需删除');
      const draft = createEmptyProviderDraft(providers.length + 1, providers.map((provider) => provider.id));
      setSelectedProviderId(DRAFT_PROVIDER_ID);
      setProviderDraft(draft);
      setProviderModels([]);
      setDiscoveredModels([]);
      return;
    }
    if (
      settings.confirmDangerousActions
      && !window.confirm(`确认删除 Provider "${selectedProvider.name}"？此操作会写入本地配置。`)
    ) {
      setProviderStatus('已取消删除 Provider');
      return;
    }

    setProviderLoading(true);
    const result = await requestSettingsApi<{ deleted: string }>(`/api/settings/providers/${encodeURIComponent(selectedProviderId)}`, {
      method: 'DELETE',
    });
    setProviderLoading(false);

    if (!result.success) {
      setProviderStatus(result.error || 'Provider 删除失败');
      return;
    }

    await loadProviders();
    setProviderStatus('已删除 Provider');
    dispatchSettingsChanged('providers');
  };

  const testProvider = async () => {
    const provider = await saveProvider();
    if (!provider) {
      return;
    }

    setProviderTesting(true);
    const result = await requestSettingsApi<{ success: boolean; models?: ProviderModel[]; message?: string; error?: string }>(
      `/api/settings/providers/${encodeURIComponent(provider.id)}/test`,
      { method: 'POST' },
    );
    setProviderTesting(false);

    if (!result.success || !result.data?.success) {
      setProviderStatus(result.data?.error || result.error || '连接测试失败');
      return;
    }

    const modelInfos = normalizeModelInfos(result.data.models);
    setProviderModels(modelInfos);
    setDiscoveredModels(modelInfos);
    await loadProviders(provider.id);
    setProviderStatus(result.data.message || `连接成功，发现 ${modelInfos.length} 个模型`);
  };

  const fetchProviderModels = async () => {
    const provider = await saveProvider();
    if (!provider) {
      return;
    }

    setProviderFetchingModels(true);
    const result = await requestSettingsApi<{ models: ProviderModel[] }>(
      `/api/settings/providers/${encodeURIComponent(provider.id)}/models`,
    );
    setProviderFetchingModels(false);

    if (!result.success || !result.data) {
      setProviderStatus(result.error || '模型列表获取失败');
      return;
    }

    const modelInfos = normalizeModelInfos(result.data.models);
    setDiscoveredModels(modelInfos);
    setProviderModels((prev) => prev.length ? prev : modelInfos);
    setModelDialogOpen(true);
    setProviderStatus(`已获取 ${modelInfos.length} 个模型`);
  };

  const selectProvider = (provider: ProviderListItem) => {
    if (provider.isDraft) {
      setSelectedProviderId(DRAFT_PROVIDER_ID);
      setProviderStatus('正在新增 Provider，保存后会写入后端配置');
      return;
    }

    setSelectedProviderId(provider.id);
    setProviderDraft(draftFromProvider(provider));
    setProviderModels(parseProviderConfig(provider).models);
    setDiscoveredModels([]);
    setShowProviderKey(false);
    setProviderStatus(`正在编辑 ${provider.name}`);
  };

  const addModelToProvider = (model: ProviderModelInfo) => {
    setProviderModels((prev) => {
      const current = prev.length ? prev : visibleProviderModels;
      if (current.some((item) => item.id === model.id)) return current;
      return [...current, model];
    });
    if (model.capabilities?.embedding) {
      setSettings((prev) => ({
        ...prev,
        embeddingProviderId: providerDraft.id,
        embeddingModel: model.id,
        knowledgeEnabled: true,
      }));
    }
  };

  const removeModelFromProvider = (modelId: string) => {
    if (
      settings.confirmDangerousActions
      && !window.confirm(`确认从当前 Provider 移除模型 "${modelId}"？`)
    ) {
      setProviderStatus('已取消移除模型');
      return;
    }
    setProviderModels((prev) => {
      const current = prev.length ? prev : visibleProviderModels;
      return current.filter((model) => model.id !== modelId);
    });
    if (settings.embeddingModel === modelId && settings.embeddingProviderId === providerDraft.id) {
      setSettings((prev) => ({ ...prev, embeddingModel: '', embeddingProviderId: '' }));
    }
  };

  const selectEmbeddingModel = (modelId: string) => {
    setSettings((prev) => ({
      ...prev,
      knowledgeEnabled: Boolean(modelId) || prev.knowledgeEnabled,
      embeddingProviderId: modelId ? providerDraft.id : '',
      embeddingModel: modelId,
    }));
  };

  useEffect(() => {
    void loadProviders();
    void loadKnowledgePreferences();
    void loadAiModelRoutesFromApi()
      .then((routes) => setAiModelRoutes((current) => ensureRoutesHaveDefaults({ ...current, ...routes, routes: { ...current.routes, ...routes.routes } }, providers)))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载时初始化;providers 到位后由 normalizedAiRoutes(memo)与 loadProviders 重算修正
  }, []);

  const saveSettings = () => {
    if (activeTab === 'api') {
      void saveProvider();
      return;
    }
    if (activeTab === 'models') {
      void saveAiRoutes();
      return;
    }

    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    saveAgentConfigs(agentConfigs);
    setSavedMessage(`已保存 ${activeTitle}，${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`);
  };

  const resetSettings = () => {
    if (activeTab === 'api') {
      void loadProviders(selectedProviderId);
      setProviderStatus('已重新载入 Provider 配置');
      return;
    }

    if (activeTab === 'agents') {
      const resetAgents = DEFAULT_AGENT_CONFIGS.map((agent) => ({ ...agent }));
      setAgentConfigs(resetAgents);
      setSelectedAgentId(resetAgents[0].id);
      saveAgentConfigs(resetAgents);
      setSavedMessage('已恢复默认 Agent 编排');
      return;
    }
    if (activeTab === 'models') {
      const defaults = pickDefaultRoutes(providers);
      setAiModelRoutes(defaults);
      saveLocalAiModelRoutes(defaults);
      void saveAiRoutes(defaults);
      return;
    }

    setSettings(DEFAULT_SETTINGS);
    window.localStorage.removeItem(SETTINGS_STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_SETTINGS_STORAGE_KEY);
    setSavedMessage('已恢复默认配置');
  };

  const updateAgent = (id: string, patch: Partial<AgentConfig>) => {
    setAgentConfigs((prev) => {
      const next = prev.map((agent) => (agent.id === id ? { ...agent, ...patch } : agent));
      saveAgentConfigs(next);
      return next;
    });
  };

  const applyAgentDefaultModel = () => {
    const selection = normalizedAiRoutes.routes.agent_default || normalizedAiRoutes.unified;
    if (!selection.providerId || !selection.modelId) {
      setSavedMessage('当前没有可用的专家团默认模型，请先添加 Provider 并获取模型列表');
      return;
    }
    setAgentConfigs((prev) => {
      const next = prev.map((agent) => ({
        ...agent,
        provider: selection.providerId,
        model: selection.modelId,
      }));
      saveAgentConfigs(next);
      return next;
    });
    setSavedMessage(`已将 ${selection.providerName || selection.providerId} / ${selection.modelId} 应用到全部 Agent`);
  };

  const addAgent = () => {
    setAgentConfigs((prev) => {
      const nextAgent = createCustomAgentConfig(prev.length + 1);
      const next = [...prev, nextAgent];
      setSelectedAgentId(nextAgent.id);
      saveAgentConfigs(next);
      setSavedMessage('已新增自定义 Agent');
      return next;
    });
  };

  const deleteAgent = (id: string) => {
    const agent = agentConfigs.find((item) => item.id === id);
    if (
      settings.confirmDangerousActions
      && !window.confirm(`确认删除 Agent "${agent?.name || id}"？`)
    ) {
      setSavedMessage('已取消删除 Agent');
      return;
    }
    setAgentConfigs((prev) => {
      const remaining = prev.filter((agent) => agent.id !== id);
      const next = remaining.length ? remaining : [createCustomAgentConfig(1)];
      setSelectedAgentId((current) => (current === id ? next[0].id : current));
      saveAgentConfigs(next);
      setSavedMessage('已删除 Agent 配置');
      return next;
    });
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="settings-ui mx-auto flex h-full w-full max-w-[1360px] gap-6 p-5 text-neutral-300 lg:p-6"
      >
        <div className="relative z-10 flex w-56 shrink-0 flex-col gap-7">
          <div>
            <h2 className="mb-2 text-[1.7rem] font-medium leading-tight text-white">系统设置</h2>
            <p className="text-sm text-neutral-500">本地预览配置中心</p>
          </div>

        <nav className="flex flex-col gap-1">
          {SETTING_TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;

            return (
              <button
                key={tab.id}
                data-testid={`settings-tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'group relative flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-all duration-300',
                  isActive ? 'text-indigo-400' : 'text-neutral-500 hover:bg-white/[0.02] hover:text-neutral-300',
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="settings-active"
                    className="absolute inset-0 rounded-xl border border-indigo-500/20 bg-indigo-500/10 shadow-[0_0_15px_rgba(99,102,241,0.05)]"
                    initial={false}
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                  />
                )}
                <Icon className="relative z-10 h-5 w-5" />
                <span className="relative z-10">{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="relative z-10 flex flex-1 flex-col overflow-hidden rounded-3xl border border-white/5 bg-white/[0.04] shadow-xl">
        <div className="h-2 bg-gradient-to-r from-indigo-500/40 via-emerald-500/40 to-transparent" />

        <div className="flex items-center justify-between border-b border-white/5 px-6 py-5">
          <div>
            <h3 className="text-lg font-medium text-neutral-100">{activeTitle}</h3>
            <p className="mt-1 text-xs text-neutral-500">{savedMessage}</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              data-testid="settings-reset"
              onClick={resetSettings}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-neutral-300 transition-colors hover:bg-white/10"
            >
              <RotateCcw className="h-4 w-4" />
              恢复默认
            </button>
            <button
              data-testid="settings-save"
              onClick={saveSettings}
              className="inline-flex items-center gap-2 rounded-xl border border-indigo-500 bg-indigo-600 px-4 py-2 text-sm text-white shadow-[0_0_15px_rgba(99,102,241,0.25)] transition-colors hover:bg-indigo-500"
            >
              <Save className="h-4 w-4" />
              保存配置
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
          <div key={activeTab}>
            {activeTab === 'general' && (
              <SimplePrefsTabs activeTab="general" settings={settings} updateSetting={updateSetting} />
            )}

            {activeTab === 'models' && (
              <ModelsTab
                providers={providers}
                chatModelOptions={chatModelOptions}
                visionModelOptions={visionModelOptions}
                normalizedAiRoutes={normalizedAiRoutes}
                routeSaving={routeSaving}
                applyRouteDefaults={applyRouteDefaults}
                applyUnifiedModel={applyUnifiedModel}
                patchAiRoutes={patchAiRoutes}
                updateRouteSelection={updateRouteSelection}
                saveAiRoutes={saveAiRoutes}
              />
            )}

            {activeTab === 'agents' && selectedAgent && (
              <AgentsTab
                agentConfigs={agentConfigs}
                selectedAgent={selectedAgent}
                selectedAgentId={selectedAgentId}
                setSelectedAgentId={setSelectedAgentId}
                enabledAgentCount={enabledAgentCount}
                runtimeAgentCount={runtimeAgentCount}
                agentProviderOptions={agentProviderOptions}
                agentModelOptions={agentModelOptions}
                chatModelOptions={chatModelOptions}
                providers={providers}
                applyAgentDefaultModel={applyAgentDefaultModel}
                addAgent={addAgent}
                deleteAgent={deleteAgent}
                updateAgent={updateAgent}
              />
            )}

            {activeTab === 'api' && (
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
            )}

            {activeTab === 'network' && (
              <SimplePrefsTabs activeTab="network" settings={settings} updateSetting={updateSetting} />
            )}

            {activeTab === 'security' && (
              <SimplePrefsTabs activeTab="security" settings={settings} updateSetting={updateSetting} />
            )}

            {activeTab === 'data' && (
              <SimplePrefsTabs activeTab="data" settings={settings} updateSetting={updateSetting} />
            )}

            {activeTab === 'notifiers' && (
              <SimplePrefsTabs activeTab="notifiers" settings={settings} updateSetting={updateSetting} />
            )}
          </div>

          <SettingsStatusBar settings={settings} />

        </div>
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
