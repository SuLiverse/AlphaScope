// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  it('renders title and optional description', () => {
    render(<EmptyState title="暂无数据" description="调整筛选条件后重试" />);
    expect(screen.getByText('暂无数据')).toBeInTheDocument();
    expect(screen.getByText('调整筛选条件后重试')).toBeInTheDocument();
  });

  it('renders action slot when provided, omits description otherwise', () => {
    const { container } = render(<EmptyState title="空" action={<button>新建</button>} />);
    expect(screen.getByRole('button', { name: '新建' })).toBeInTheDocument();
    expect(screen.queryByText('调整筛选条件后重试')).toBeNull();
    expect(container.querySelector('p')).toBeNull();
  });
});
