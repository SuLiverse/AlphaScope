import { describe, expect, it } from 'vitest';
import {
  applyAiRoutingPack,
  applyReportModelOverride,
  mergeAiModelRouteSources,
  normalizeAiModelRoutes,
  routesToGlobalAiSettings,
} from './aiModelRouting';

describe('AI model route persistence', () => {
  it('applies a routing pack to React state without dropping existing routes', () => {
    const current = normalizeAiModelRoutes({
      useUnifiedModel: true,
      unified: { providerId: 'base', modelId: 'base-model' },
      routes: {
        chat: { providerId: 'base', modelId: 'chat-model' },
        report: { providerId: 'base', modelId: 'report-model' },
      },
    });
    const next = applyAiRoutingPack(current, {
      id: 'research',
      name: 'Research',
      routes: {
        report: { providerId: 'strong', modelId: 'reasoner' },
        critic: { providerId: 'strong', modelId: 'critic' },
      },
    });

    expect(next.useUnifiedModel).toBe(false);
    expect(next.routes.chat?.modelId).toBe('chat-model');
    expect(next.routes.report?.modelId).toBe('reasoner');
    expect(next.routes.critic?.modelId).toBe('critic');
  });

  it('uses local routes only as fallback and lets server routes win', () => {
    const local = {
      useUnifiedModel: false,
      unified: { providerId: 'local', modelId: 'local-model' },
      routes: { chat: { providerId: 'local', modelId: 'local-chat' } },
    };
    const server = {
      use_unified_model: false,
      unified: { providerId: 'server', modelId: 'server-model' },
      routes: { chat: { providerId: 'server', modelId: 'server-chat' } },
    };

    expect(mergeAiModelRouteSources(local, undefined).routes.chat?.providerId).toBe('local');
    const merged = mergeAiModelRouteSources(local, server);
    expect(merged.unified.providerId).toBe('server');
    expect(merged.routes.chat?.providerId).toBe('server');
  });

  it('sends the complete routing pack to the backend task router', () => {
    const providers = [
      {
        id: 'cheap',
        name: 'Cheap',
        enabled: true,
        config_json: JSON.stringify({ models: [{ id: 'chat-model' }] }),
      },
      {
        id: 'strong',
        name: 'Strong',
        enabled: true,
        config_json: JSON.stringify({
          models: [{ id: 'critic-model' }, { id: 'chair-model' }, { id: 'report-model' }],
        }),
      },
    ];
    const routes = normalizeAiModelRoutes({
      useUnifiedModel: false,
      unified: { providerId: 'cheap', modelId: 'chat-model' },
      routes: {
        agent_default: { providerId: 'cheap', modelId: 'chat-model' },
        critic: { providerId: 'strong', modelId: 'critic-model' },
        chairman: { providerId: 'strong', modelId: 'chair-model' },
        report: { providerId: 'strong', modelId: 'report-model' },
      },
    });

    const settings = routesToGlobalAiSettings(routes, providers, 'report');

    expect(settings?.routes.agent_default).toEqual({ provider: 'cheap', model: 'chat-model' });
    expect(settings?.routes.critic).toEqual({ provider: 'strong', model: 'critic-model' });
    expect(settings?.routes.chairman).toEqual({ provider: 'strong', model: 'chair-model' });
    expect(settings?.provider).toBe('strong');
    expect(settings?.model).toBe('report-model');
  });

  it('applies the report-page model to every task used by report generation', () => {
    const providers = [
      {
        id: 'configured',
        name: 'Configured',
        enabled: true,
        config_json: JSON.stringify({ models: [{ id: 'old-model' }] }),
      },
      {
        id: 'selected',
        name: 'Selected',
        enabled: true,
        config_json: JSON.stringify({ models: [{ id: 'report-model' }] }),
      },
    ];
    const routes = normalizeAiModelRoutes({
      useUnifiedModel: false,
      unified: { providerId: 'configured', modelId: 'old-model' },
      routes: {
        chat: { providerId: 'configured', modelId: 'old-model' },
        report: { providerId: 'configured', modelId: 'old-model' },
        agent_default: { providerId: 'configured', modelId: 'old-model' },
        critic: { providerId: 'configured', modelId: 'old-model' },
        chairman: { providerId: 'configured', modelId: 'old-model' },
      },
    });

    const effectiveRoutes = applyReportModelOverride(routes, {
      providerId: 'selected',
      providerName: 'Selected',
      modelId: 'report-model',
    });
    const settings = routesToGlobalAiSettings(effectiveRoutes, providers, 'report');

    expect(routes.routes.agent_default?.providerId).toBe('configured');
    expect(effectiveRoutes.routes.chat?.providerId).toBe('configured');
    expect(settings?.routes.report).toEqual({ provider: 'selected', model: 'report-model' });
    expect(settings?.routes.agent_default).toEqual({ provider: 'selected', model: 'report-model' });
    expect(settings?.routes.critic).toEqual({ provider: 'selected', model: 'report-model' });
    expect(settings?.routes.chairman).toEqual({ provider: 'selected', model: 'report-model' });
    expect(settings?.critic).toEqual({
      provider: 'selected',
      model: 'report-model',
      inherit_global_key: false,
    });
    expect(settings?.chairman).toEqual({
      provider: 'selected',
      model: 'report-model',
      inherit_global_key: false,
    });
  });

  it('updates the unified route without rewriting saved task routes', () => {
    const routes = normalizeAiModelRoutes({
      useUnifiedModel: true,
      unified: { providerId: 'old', modelId: 'old-model' },
      routes: {
        agent_default: { providerId: 'task', modelId: 'task-model' },
      },
    });

    const effectiveRoutes = applyReportModelOverride(routes, {
      providerId: 'selected',
      modelId: 'report-model',
    });

    expect(effectiveRoutes.unified).toEqual({ providerId: 'selected', modelId: 'report-model' });
    expect(effectiveRoutes.routes.agent_default).toEqual({ providerId: 'task', modelId: 'task-model' });
  });
});
