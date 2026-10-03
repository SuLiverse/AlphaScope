// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fetchApi } from '../../lib/api';
import { LAST_WORKSPACE_KEY, type ResearchDraft } from '../../lib/researchWorkspace';
import { ResearchWorkspacePanel } from './ResearchWorkspacePanel';

vi.mock('../../lib/api', () => ({ fetchApi: vi.fn() }));
const draft: ResearchDraft = { stock_symbol: '600519', stock_name: 'Test', research_question: 'Cash flow?', as_of: '2026-06-30', report_template: 'standard', materials: [] };
const failed = { id: 'v1', number: 1, task_id: 't1', status: 'failed', stage: 'analysis', error: 'model unavailable', created_at: '2026-06-30T00:00:00Z', input: draft };
const workspace = { id: 'ws', draft, versions: [failed] };
function props() { return { draft, workspaceId: '', versionId: '', busy: false, refreshKey: 0, onSaved: vi.fn(), onRestore: vi.fn(), onNew: vi.fn(), onMaterials: vi.fn(), onStarted: vi.fn() }; }

beforeEach(() => {
  localStorage.clear();
  vi.mocked(fetchApi).mockImplementation(async path => {
    if (path.endsWith('/versions/v1')) return failed;
    if (path.endsWith('/ws')) return workspace;
    return { workspaces: [workspace] };
  });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('continues the last saved workspace after remount', async () => {
  localStorage.setItem(LAST_WORKSPACE_KEY, 'ws');
  const callbacks = props();
  render(<ResearchWorkspacePanel {...callbacks} />);
  await waitFor(() => expect(callbacks.onRestore).toHaveBeenCalledWith(workspace, failed));
});

it('retries the selected failed version rather than silently starting a fresh study', async () => {
  const callbacks = { ...props(), workspaceId: 'ws', versionId: 'v1' };
  render(<ResearchWorkspacePanel {...callbacks} />);
  const retry = await screen.findByRole('button', { name: '重试失败步骤' });
  vi.mocked(fetchApi).mockResolvedValueOnce({ task_id: 't2', version_id: 'v2' });
  fireEvent.click(retry);
  await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledWith('t2', 'v2'));
  const request = vi.mocked(fetchApi).mock.calls.find(([path]) => path === '/api/analysis/async');
  expect(JSON.parse(String(request?.[1]?.body))).toEqual({ stock_symbol: '600519', workspace_id: 'ws', retry_from: 'v1' });
});

it('does not report a failed draft save as persisted', async () => {
  const callbacks = props();
  render(<ResearchWorkspacePanel {...callbacks} />);
  await screen.findByRole('option', { name: /Cash flow/ });
  vi.mocked(fetchApi).mockRejectedValueOnce(new Error('Storage unavailable'));
  fireEvent.click(screen.getByRole('button', { name: '保存研究草稿' }));
  await screen.findByRole('alert');
  expect(callbacks.onSaved).not.toHaveBeenCalled();
  expect(screen.queryByText('草稿已保存')).toBeNull();
});
