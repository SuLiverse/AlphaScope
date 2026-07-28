// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Card } from './Card';

describe('Card', () => {
  it('renders children with default glass classes', () => {
    render(<Card>内容</Card>);
    const el = screen.getByText('内容');
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass('border', 'border-border-card', 'bg-surface', 'rounded-xl', 'p-5');
  });

  it('applies padding/rounded options and merges className', () => {
    render(
      <Card padding="sm" rounded="2xl" className="mt-4" data-testid="card">
        x
      </Card>,
    );
    expect(screen.getByTestId('card')).toHaveClass('p-3', 'rounded-2xl', 'mt-4');
  });
});
