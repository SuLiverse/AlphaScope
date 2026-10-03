// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MetricTile } from './MetricTile';

describe('MetricTile', () => {
  it('renders label, value and hint', () => {
    render(<MetricTile label="累计收益" value="+12.4%" hint="近 180 交易日" />);
    expect(screen.getByText('累计收益')).toHaveClass('text-neutral-500');
    expect(screen.getByText('+12.4%')).toHaveClass('text-neutral-100');
    expect(screen.getByText('近 180 交易日')).toBeInTheDocument();
  });

  it('renders quiet placeholder when value is empty', () => {
    const { rerender } = render(<MetricTile label="夏普比率" />);
    expect(screen.getByText('——')).toHaveClass('text-neutral-600');
    rerender(<MetricTile label="夏普比率" value="" />);
    expect(screen.getByText('——')).toBeInTheDocument();
  });

  it('applies tone classes for up/down semantics', () => {
    const { rerender } = render(<MetricTile label="今日浮动" value="+2.1%" tone="up" />);
    expect(screen.getByText('+2.1%')).toHaveClass('text-tint-up');
    rerender(<MetricTile label="今日浮动" value="-0.8%" tone="down" />);
    expect(screen.getByText('-0.8%')).toHaveClass('text-tint-down');
  });

  it('renders aside slot and merges className', () => {
    render(
      <MetricTile label="持仓" value="3" aside="只" className="mt-2" data-testid="tile">
        <span>extra</span>
      </MetricTile>,
    );
    expect(screen.getByTestId('tile')).toHaveClass('mt-2');
    expect(screen.getByText('只')).toBeInTheDocument();
  });
});
