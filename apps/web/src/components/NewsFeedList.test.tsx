// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { NewsFeedList, type NewsItem } from './NewsFeedList';

function makeItem(id: string, title: string): NewsItem {
  return {
    id,
    time: '10:00',
    title,
    category: 'macro',
    source: '财联社',
    sourceTier: '主流媒体',
    severity: 'info',
    sentiment: 'neutral',
    impactScore: 60,
    content: `${title} 正文`,
    aiSummary: '摘要',
  };
}

const noop = () => {};

function renderList(overrides: Partial<Parameters<typeof NewsFeedList>[0]> = {}) {
  const props = {
    items: [makeItem('a', '第一条新闻'), makeItem('b', '第二条新闻')],
    searchQuery: '',
    selectedId: undefined,
    onActivate: noop,
    onOpenDetail: noop,
    onOpenSource: noop,
    onAsk: noop,
    onClearFilters: noop,
    ...overrides,
  };
  return render(<NewsFeedList {...props} />);
}

describe('NewsFeedList', () => {
  it('renders all feed items', () => {
    renderList();
    expect(screen.getByText('第一条新闻')).toBeInTheDocument();
    expect(screen.getByText('第二条新闻')).toBeInTheDocument();
    expect(screen.getByTestId('news-feed-item-0')).toBeInTheDocument();
    expect(screen.getByTestId('news-feed-item-1')).toBeInTheDocument();
  });

  it('shows empty state and reset button triggers onClearFilters', () => {
    const onClearFilters = vi.fn();
    renderList({ items: [], searchQuery: '不存在的关键词', onClearFilters });
    expect(screen.getByText(/未能检索到包含关键字/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('news-empty-reset'));
    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });
});
