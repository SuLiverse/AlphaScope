// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PageHeader } from './PageHeader';

describe('PageHeader', () => {
  it('renders title with badge and one-line description', () => {
    render(
      <PageHeader
        title="量化策略引擎"
        badge={<span>真实回测</span>}
        description="调用后端 BacktestEngine 运行策略、股票池真实因子筛选与决策后验。"
      />,
    );
    expect(screen.getByText('量化策略引擎')).toHaveClass('truncate');
    expect(screen.getByText('真实回测')).toBeInTheDocument();
    expect(screen.getByText(/调用后端 BacktestEngine/)).toHaveClass('line-clamp-1');
  });

  it('renders actions in a separated trailing slot', () => {
    render(
      <PageHeader
        title="组合与风控总览"
        actions={<button type="button">刷新价格</button>}
      />,
    );
    const btn = screen.getByText('刷新价格');
    expect(btn.closest('div')).toHaveClass('shrink-0');
  });

  it('omits description node when absent', () => {
    const { container } = render(<PageHeader title="研究记忆" />);
    expect(container.querySelector('p')).toBeNull();
  });
});
