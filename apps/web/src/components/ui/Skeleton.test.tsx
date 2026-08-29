// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { Skeleton } from './Skeleton';

describe('Skeleton', () => {
  it('renders card variant by default with reduced-motion-safe pulse', () => {
    const { container } = render(<Skeleton />);
    const root = container.firstElementChild;
    expect(root).toHaveAttribute('data-variant', 'card');
    expect(root).toHaveClass('animate-pulse', 'motion-reduce:animate-none');
  });

  it('switches list/chart variants', () => {
    const { container, rerender } = render(<Skeleton variant="list" />);
    expect(container.firstElementChild).toHaveAttribute('data-variant', 'list');
    rerender(<Skeleton variant="chart" />);
    expect(container.firstElementChild).toHaveAttribute('data-variant', 'chart');
  });
});
