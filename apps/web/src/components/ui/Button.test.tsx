// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';

describe('Button', () => {
  it('renders primary/md by default and fires onClick', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>提交</Button>);
    const btn = screen.getByRole('button', { name: '提交' });
    expect(btn).toHaveAttribute('type', 'button');
    expect(btn).toHaveClass('bg-brand/15', 'border-brand/50', 'px-3', 'py-2');
    await userEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('applies variant/size and does not fire when disabled', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="danger" size="sm" disabled onClick={onClick}>
        删除
      </Button>,
    );
    const btn = screen.getByRole('button', { name: '删除' });
    expect(btn).toHaveClass('bg-red-500/10', 'text-xs');
    expect(btn).toBeDisabled();
    await userEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });
});
