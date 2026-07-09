/**
 * 行情展示状态机：区分「真实行情(含降级)」与「本地合成预览」。
 * 勿用单一 degraded 同时表示两种语义。
 */
export type PriceFeed = 'loading' | 'live' | 'live_degraded' | 'synthetic';

export function isSyntheticPriceFeed(feed: PriceFeed): boolean {
  return feed === 'synthetic';
}

export function isLivePriceFeed(feed: PriceFeed): boolean {
  return feed === 'live' || feed === 'live_degraded';
}

/** 有真实 bars 时按后端 degraded 标记分流；无 bars / 失败 → synthetic */
export function resolvePriceFeed(opts: {
  hasBars: boolean;
  backendDegraded?: boolean;
  failed?: boolean;
}): PriceFeed {
  if (opts.failed || !opts.hasBars) return 'synthetic';
  return opts.backendDegraded ? 'live_degraded' : 'live';
}
