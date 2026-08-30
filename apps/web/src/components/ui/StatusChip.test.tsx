// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusChip } from './StatusChip';

/** getByText 命中的是内层文本 span；色值与圆点都在外层 chip 根元素上。 */
function chipRoot(label: string): HTMLElement {
  return screen.getByText(label).parentElement!;
}

describe('StatusChip', () => {
  it('renders label with neutral dot by default', () => {
    render(<StatusChip>已同步</StatusChip>);
    const el = chipRoot('已同步');
    expect(el).toHaveClass('text-neutral-400', 'border-border-strong');
    expect(el.querySelector('span[aria-hidden]')).not.toBeNull();
  });

  it('up/down tones render bare semantic text without shell border', () => {
    render(<StatusChip tone="up">+1.2%</StatusChip>);
    expect(chipRoot('+1.2%')).toHaveClass('text-tint-up', 'border-transparent');
  });

  it('warn tone exposes pulse dot when loading', () => {
    render(
      <StatusChip tone="warn" pulse>
        连接中
      </StatusChip>,
    );
    const el = chipRoot('连接中');
    expect(el).toHaveClass('border-amber-500/20');
    expect(el.querySelector('span[aria-hidden]')).toHaveClass('animate-pulse');
  });

  it('can hide the dot', () => {
    render(
      <StatusChip dot={false} tone="info">
        演示数据
      </StatusChip>,
    );
    expect(chipRoot('演示数据').querySelector('span[aria-hidden]')).toBeNull();
  });
});
