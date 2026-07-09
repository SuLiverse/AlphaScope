/**
 * Settings domain types and constants.
 */
import type { ComponentType } from "react";
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
import { API_BASE_URL } from "../../lib/api";
import type { ModelProvider } from "../../lib/aiModelRouting";
import type { AgentIconKey } from "../../lib/agentConfigs";

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

export interface SettingsProps {
  initialTab?: string;
}
