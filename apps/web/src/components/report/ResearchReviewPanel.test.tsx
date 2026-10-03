// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchApi } from '../../lib/api';
import { ResearchReviewPanel } from './ResearchReviewPanel';
import type { ResearchVersion, Workspace } from '../../lib/researchWorkspace';

vi.mock('../../lib/api', () => ({ fetchApi: vi.fn() }));

const version: ResearchVersion = {
  id: 'v2', number: 2, task_id: 'task2', workspace_id: 'ws', status: 'success', stage: 'complete', error: '', created_at: '2026-06-30T12:00:00Z',
  input: { stock_symbol: '600519', stock_name: 'Test', research_question: 'Cash flow?', as_of: '2026-06-30', report_template: 'standard', materials: [] },
  result: { evidence_pool: [{ evidence_id: 'e1', number: 1, source: '公告', published_at: '2026-06-29', source_url: 'https://example.com/report', excerpt: '报告原文摘录' },
    { evidence_id: 'e2', number: 2, source: '不安全链接', source_url: 'javascript:alert(1)', preview: '待核实' }] },
  claims: [{ id: 'c1', agent_id: 'a', agent_name: '基本面', text: '现金流改善。', evidence_ids: ['e1'], agent_evidence_ids: ['e1'] }], reviews: {},
};
const workspace: Workspace = { id: 'ws', draft: version.input, versions: [version, { ...version, id: 'v1', number: 1 }] };

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  vi.mocked(fetchApi).mockImplementation(async (path) => {
    if (path.endsWith('/versions/v2')) return structuredClone(version);
    if (path.endsWith('/ws')) return structuredClone(workspace);
    if (path.includes('/compare?')) return { summary: '证据变化 1 条', warnings: ['差异不代表因果关系'], conclusion: { before: 'HOLD', after: 'SELL', changed: true }, context: [], evidence: [], metrics: [], agents: [], models: [] };
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

describe('Research review workflow', () => {
  it('opens original evidence and saves an evidence-bound revision without rewriting the original', async () => {
    render(<ResearchReviewPanel versionId="v2" />);
    fireEvent.click(await screen.findByRole('button', { name: /现金流改善/ }));
    expect(screen.getByText('报告原文摘录')).toBeTruthy();
    expect(screen.getByRole('link', { name: '原文' }).getAttribute('href')).toBe('https://example.com/report');
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect((screen.getByRole('button', { name: '保存复核' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('复核结论'), { target: { value: 'partial' } });
    fireEvent.change(screen.getByLabelText('复核理由'), { target: { value: '季度波动尚未排除' } });
    fireEvent.change(screen.getByLabelText('修订后的结论'), { target: { value: '现金流改善有待持续验证。' } });
    fireEvent.change(screen.getByLabelText('证据 e1 与论断的关系'), { target: { value: 'opposes' } });
    vi.mocked(fetchApi).mockImplementationOnce(async (_path, options) => ({ ...JSON.parse(String(options?.body)), revision: 1, created_at: '2026-07-01T00:00:00Z' }));
    fireEvent.click(screen.getByRole('button', { name: '保存复核' }));
    await screen.findByText('复核已保存');
    expect(screen.getByText('现金流改善。')).toBeTruthy();
    expect(screen.getByRole('button', { name: /现金流改善有待持续验证/ })).toBeTruthy();
    const call = vi.mocked(fetchApi).mock.calls.find(([path]) => path.endsWith('/claims/c1'));
    const payload = JSON.parse(String(call?.[1]?.body));
    expect(payload.expected_revision).toBe(0);
    expect(payload.evidence_relations).toEqual({ e1: 'opposes' });
  });

  it('compares an earlier version and shows the causal caveat', async () => {
    render(<ResearchReviewPanel versionId="v2" />);
    await screen.findByRole('button', { name: /现金流改善/ });
    fireEvent.click(screen.getByRole('tab', { name: '报告差异' }));
    await screen.findByText('证据变化 1 条');
    expect(screen.getByText('差异不代表因果关系')).toBeTruthy();
    expect(screen.getByText('HOLD')).toBeTruthy();
    expect(screen.getByText('SELL')).toBeTruthy();
    expect((screen.getByLabelText('基准版本') as HTMLSelectElement).value).toBe('v1');
  });

  it('surfaces a save conflict without claiming success', async () => {
    render(<ResearchReviewPanel versionId="v2" />);
    fireEvent.click(await screen.findByRole('button', { name: /现金流改善/ }));
    fireEvent.change(screen.getByLabelText('复核理由'), { target: { value: 'Checked' } });
    vi.mocked(fetchApi).mockRejectedValueOnce(new Error('Review changed; reload before saving'));
    fireEvent.click(screen.getByRole('button', { name: '保存复核' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('复核已保存')).toBeNull();
    await waitFor(() => expect((screen.getByRole('button', { name: '保存复核' }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('retains a draft across views and guards claim changes', async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce({ ...version, claims: [...version.claims, { ...version.claims[0], id: 'c2', text: '第二条论断' }] });
    const { rerender } = render(<ResearchReviewPanel versionId="v2" view="review" />);
    fireEvent.click(await screen.findByRole('button', { name: /现金流改善/ }));
    fireEvent.change(screen.getByLabelText('复核理由'), { target: { value: '未保存的理由' } });
    rerender(<ResearchReviewPanel versionId="v2" view="compare" />);
    await screen.findByText('证据变化 1 条');
    rerender(<ResearchReviewPanel versionId="v2" view="review" />);
    expect((screen.getByLabelText('复核理由') as HTMLTextAreaElement).value).toBe('未保存的理由');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByRole('button', { name: /第二条论断/ }));
    expect(confirm).toHaveBeenCalled();
    expect((screen.getByLabelText('复核理由') as HTMLTextAreaElement).value).toBe('未保存的理由');
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: /第二条论断/ }));
    expect((screen.getByLabelText('复核理由') as HTMLTextAreaElement).value).toBe('');
    confirm.mockRestore();
  });

  it('saves and advances through unreviewed claims, then filters counterevidence', async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce({ ...version, claims: [...version.claims, { ...version.claims[0], id: 'c2', text: '第二条论断' }] });
    const onProgress = vi.fn();
    render(<ResearchReviewPanel versionId="v2" onProgress={onProgress} />);
    await screen.findByRole('button', { name: /现金流改善/ });
    fireEvent.click(screen.getByRole('button', { name: '未复核' }));
    fireEvent.click(screen.getByRole('button', { name: /现金流改善/ }));
    fireEvent.change(screen.getByLabelText('复核理由'), { target: { value: '发现反证' } });
    fireEvent.change(screen.getByLabelText('证据 e1 与论断的关系'), { target: { value: 'opposes' } });
    vi.mocked(fetchApi).mockImplementationOnce(async (_path, options) => ({ ...JSON.parse(String(options?.body)), revision: 1, created_at: '2026-07-01T00:00:00Z' }));
    fireEvent.click(screen.getByRole('button', { name: '保存并下一条' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /第二条论断/ }).getAttribute('aria-pressed')).toBe('true'));
    expect(screen.queryByRole('button', { name: /现金流改善/ })).toBeNull();
    expect(onProgress).toHaveBeenLastCalledWith({ reviewed: 1, total: 2 });
    fireEvent.click(screen.getByRole('button', { name: '存在反证' }));
    expect(screen.getByRole('button', { name: /现金流改善/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /第二条论断/ })).toBeNull();
  });

  it('ignores a late save response after a version switch', async () => {
    const { rerender } = render(<ResearchReviewPanel key="v2" versionId="v2" />);
    fireEvent.click(await screen.findByRole('button', { name: /现金流改善/ }));
    fireEvent.change(screen.getByLabelText('复核理由'), { target: { value: '旧版本理由' } });
    let finish!: (value: unknown) => void;
    vi.mocked(fetchApi).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: '保存复核' }));
    vi.mocked(fetchApi).mockResolvedValueOnce({ ...version, id: 'v3', claims: [{ ...version.claims[0], text: '新版本论断' }] });
    rerender(<ResearchReviewPanel key="v3" versionId="v3" />);
    await screen.findByRole('button', { name: /新版本论断/ });
    await act(async () => { finish({ reason: '旧版本理由', status: 'supported', evidence_relations: {}, revised_text: '污染新版本', revision: 1, created_at: '' }); });
    expect(screen.queryByText('污染新版本')).toBeNull();
    expect(screen.queryByText('复核已保存')).toBeNull();
  });

  it('ignores stale version reads and their progress callbacks', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(fetchApi).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const onVersion = vi.fn();
    const { rerender } = render(<ResearchReviewPanel versionId="v2" onVersion={onVersion} />);
    vi.mocked(fetchApi).mockResolvedValueOnce({ ...version, id: 'v3', claims: [{ ...version.claims[0], text: '新版本论断' }] });
    rerender(<ResearchReviewPanel versionId="v3" onVersion={onVersion} />);
    await screen.findByRole('button', { name: /新版本论断/ });
    await act(async () => { finish(structuredClone(version)); });
    expect(onVersion).toHaveBeenCalledTimes(1);
    expect(onVersion.mock.calls[0][0].id).toBe('v3');
    expect(screen.queryByRole('button', { name: /现金流改善/ })).toBeNull();
  });

  it('discards a delayed comparison after switching back to review', async () => {
    render(<ResearchReviewPanel versionId="v2" />);
    await screen.findByRole('button', { name: /现金流改善/ });
    let finish!: (value: unknown) => void;
    vi.mocked(fetchApi).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    fireEvent.click(screen.getByRole('tab', { name: '报告差异' }));
    fireEvent.click(screen.getByRole('tab', { name: /逐条复核/ }));
    await act(async () => { finish({ summary: '旧的比较响应', warnings: [], conclusion: { before: null, after: null, changed: false }, context: [], evidence: [], agents: [], metrics: [], models: [] }); });
    expect(screen.queryByText('旧的比较响应')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: '报告差异' }));
    await screen.findByText('证据变化 1 条');
    expect(screen.queryByText('旧的比较响应')).toBeNull();
  });

  it('closes the mobile detail before returning keyboard focus', async () => {
    vi.mocked(window.matchMedia).mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
    render(<ResearchReviewPanel versionId="v2" />);
    const trigger = await screen.findByRole('button', { name: /现金流改善/ });
    trigger.focus(); fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: '论断复核' });
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
