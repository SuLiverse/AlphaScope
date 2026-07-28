// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorState } from './ErrorState';

describe('ErrorState', () => {
  it('renders message and default title, no retry button without onRetry', () => {
    render(<ErrorState message="网络异常" />);
    expect(screen.getByText('加载失败')).toBeInTheDocument();
    expect(screen.getByText('网络异常')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('calls onRetry when the retry button is clicked', async () => {
    const onRetry = vi.fn();
    render(<ErrorState message="网络异常" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
