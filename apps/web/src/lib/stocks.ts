import { fetchApi } from './api';

export interface StockTarget {
  name: string;
  symbol: string;
  exchange: 'SH' | 'SZ' | 'BJ' | 'HK';
  market: 'A股' | '北交所' | '港股';
  startPrice: number;
  sector: string;
  tags: string[];
  source?: 'local' | 'backend' | 'symbol-fallback';
  resolved?: boolean;
}

export const STOCK_UNIVERSE: StockTarget[] = [
  { name: '贵州茅台', symbol: '600519.SH', exchange: 'SH', market: 'A股', startPrice: 1720, sector: '白酒', tags: ['茅台', 'maotai', '600519'] },
  { name: '宁德时代', symbol: '300750.SZ', exchange: 'SZ', market: 'A股', startPrice: 205, sector: '新能源电池', tags: ['宁德', 'catl', '300750'] },
  { name: '招商银行', symbol: '600036.SH', exchange: 'SH', market: 'A股', startPrice: 34.6, sector: '银行', tags: ['招行', 'cmb', '600036'] },
  { name: '海通证券', symbol: '600837.SH', exchange: 'SH', market: 'A股', startPrice: 8.2, sector: '证券', tags: ['海通', 'haitong', '600837'] },
  { name: '中国平安', symbol: '601318.SH', exchange: 'SH', market: 'A股', startPrice: 48.4, sector: '保险', tags: ['平安', 'pingan', '601318'] },
  { name: '比亚迪', symbol: '002594.SZ', exchange: 'SZ', market: 'A股', startPrice: 252, sector: '新能源汽车', tags: ['byd', '比亚迪', '002594'] },
  { name: '东方财富', symbol: '300059.SZ', exchange: 'SZ', market: 'A股', startPrice: 15.9, sector: '互联网券商', tags: ['东财', 'eastmoney', '300059'] },
  { name: '中际旭创', symbol: '300308.SZ', exchange: 'SZ', market: 'A股', startPrice: 178, sector: '光模块', tags: ['cpo', '光模块', '300308'] },
  { name: '大普微-UW', symbol: '301666.SZ', exchange: 'SZ', market: 'A股', startPrice: 79.6, sector: '半导体存储', tags: ['大普微', '大微普', 'dapuwei', '301666'] },
  { name: '腾讯控股', symbol: '00700.HK', exchange: 'HK', market: '港股', startPrice: 392, sector: '互联网平台', tags: ['腾讯', 'tencent', '00700', '700'] },
];

interface BackendStockIdentity {
  symbol?: string;
  name?: string;
  exchange?: string;
  market?: string;
  resolved?: boolean;
  source?: string;
}

interface BackendStockSearchResponse {
  query: string;
  results: BackendStockIdentity[];
  total: number;
}

const STOCK_CACHE_KEY = 'alphascope:resolved-stock-cache';
const LEGACY_STOCK_CACHE_KEY = `${['ai', 'finance'].join('-')}:resolved-stock-cache`;
const stockMemoryCache = new Map<string, StockTarget>();

const stockAliases: Record<string, string> = {
  大微普: '大普微',
  大普微uw: '大普微',
  大普微u: '大普微',
};

export function formatStockLabel(stock: StockTarget): string {
  return `${stock.name} (${stock.symbol})`;
}

export function normalizeStockKeyword(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, '');
}

function normalizeAlias(value: string) {
  const normalized = normalizeStockKeyword(value);
  return stockAliases[normalized] || normalized;
}

function codeOnly(value: string): string {
  const match = String(value || '').match(/\d{5,6}/);
  return match ? match[0].padStart(match[0].length === 5 ? 5 : 6, '0') : '';
}

function inferExchange(code: string): StockTarget['exchange'] {
  if (code.length === 5) return 'HK';
  if (/^(60|68|90)/.test(code)) return 'SH';
  if (/^(00|30|20)/.test(code)) return 'SZ';
  if (/^[48]/.test(code)) return 'BJ';
  return 'SZ';
}

function exchangeSuffix(exchange: StockTarget['exchange']) {
  return exchange === 'HK' ? 'HK' : exchange;
}

function inferMarket(exchange: StockTarget['exchange']): StockTarget['market'] {
  if (exchange === 'HK') return '港股';
  if (exchange === 'BJ') return '北交所';
  return 'A股';
}

function pseudoPrice(code: string) {
  const seed = code.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return Number((8 + (seed % 180) + (seed % 37) / 100).toFixed(2));
}

export function buildFallbackStockTarget(value: string, name?: string): StockTarget | undefined {
  const code = codeOnly(value);
  if (!code || !/^\d{5,6}$/.test(code)) return undefined;
  const exchange = inferExchange(code);
  const symbol = `${code}.${exchangeSuffix(exchange)}`;
  return {
    name: name?.trim() || `待解析标的 ${code}`,
    symbol,
    exchange,
    market: inferMarket(exchange),
    startPrice: pseudoPrice(code),
    sector: '待解析',
    tags: [code, symbol, value],
    source: 'symbol-fallback',
    resolved: false,
  };
}

function stockMatches(stock: StockTarget, normalizedKeyword: string): boolean {
  const normalized = normalizeAlias(normalizedKeyword);
  const haystack = [
    stock.name,
    stock.symbol,
    stock.symbol.replace('.', ''),
    stock.symbol.split('.')[0],
    stock.sector,
    stock.market,
    ...stock.tags,
  ].map(normalizeAlias);

  return haystack.some((item) => item.includes(normalized) || normalized.includes(item));
}

function readCachedStocks(): StockTarget[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STOCK_CACHE_KEY) ?? window.localStorage.getItem(LEGACY_STOCK_CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as StockTarget[];
    if (!Array.isArray(parsed)) return [];
    const stocks = parsed.filter((stock) => stock?.symbol && stock?.name);
    if (stocks.length) {
      window.localStorage.setItem(STOCK_CACHE_KEY, JSON.stringify(stocks.slice(0, 80)));
    }
    return stocks;
  } catch {
    return [];
  }
}

function rememberStock(stock: StockTarget) {
  stockMemoryCache.set(stock.symbol, stock);
  stockMemoryCache.set(stock.symbol.split('.')[0], stock);
  stockMemoryCache.set(normalizeAlias(stock.name), stock);
  if (typeof window === 'undefined') return;
  const merged = [stock, ...readCachedStocks()].reduce<StockTarget[]>((acc, item) => {
    if (!acc.some((existing) => existing.symbol === item.symbol)) {
      acc.push(item);
    }
    return acc;
  }, []);
  window.localStorage.setItem(STOCK_CACHE_KEY, JSON.stringify(merged.slice(0, 80)));
}

function uniqueStocks(stocks: StockTarget[]) {
  return stocks.reduce<StockTarget[]>((acc, stock) => {
    if (!acc.some((item) => item.symbol === stock.symbol)) {
      acc.push(stock);
    }
    return acc;
  }, []);
}

function backendIdentityToStock(identity: BackendStockIdentity, query: string): StockTarget | undefined {
  const rawSymbol = identity.symbol || codeOnly(query);
  if (!rawSymbol) return undefined;
  const code = codeOnly(rawSymbol);
  if (!code) return undefined;
  const exchange = inferExchange(code);
  const symbol = rawSymbol.includes('.') ? rawSymbol.toUpperCase() : `${code}.${exchangeSuffix(exchange)}`;
  return {
    name: identity.name?.trim() || `待解析标的 ${code}`,
    symbol,
    exchange,
    market: identity.market === 'HK' ? '港股' : exchange === 'BJ' ? '北交所' : 'A股',
    startPrice: pseudoPrice(code),
    sector: identity.resolved ? '后端解析' : '待解析',
    tags: [code, symbol, query, identity.source || 'backend'],
    source: identity.source ? 'backend' : 'symbol-fallback',
    resolved: Boolean(identity.resolved),
  };
}

export async function resolveStockTarget(query: string): Promise<StockTarget | undefined> {
  const local = findStockTarget(query);
  if (local && local.source !== 'symbol-fallback') return local;

  const cached = stockMemoryCache.get(query)
    || stockMemoryCache.get(codeOnly(query))
    || stockMemoryCache.get(normalizeAlias(query))
    || readCachedStocks().find((stock) => stockMatches(stock, query));
  if (cached && cached.source !== 'symbol-fallback') return cached;

  try {
    const identity = await fetchApi<BackendStockIdentity>(`/api/stocks/resolve?q=${encodeURIComponent(query)}`);
    const resolved = backendIdentityToStock(identity, query);
    if (resolved) {
      rememberStock(resolved);
      return resolved;
    }
  } catch {
    // Keep search usable when the backend resolver is unavailable.
  }

  const fallback = buildFallbackStockTarget(query);
  if (fallback) {
    rememberStock(fallback);
  }
  return local ?? cached ?? fallback;
}

export async function searchStockTargetsRemote(query: string, limit = 8): Promise<StockTarget[]> {
  const local = searchStockTargets(query, limit);
  if (!query.trim()) return local;

  try {
    const payload = await fetchApi<BackendStockSearchResponse>(
      `/api/stocks/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    );
    const remote = (payload.results || [])
      .map((item) => backendIdentityToStock(item, query))
      .filter((stock): stock is StockTarget => Boolean(stock));
    remote.forEach(rememberStock);
    return uniqueStocks([...remote, ...local]).slice(0, limit);
  } catch {
    return local;
  }
}

export function searchStockTargets(keyword: string, limit = 6): StockTarget[] {
  const normalized = normalizeAlias(keyword);
  if (!normalized) {
    return STOCK_UNIVERSE.slice(0, limit);
  }

  const candidates = [...STOCK_UNIVERSE, ...readCachedStocks()];
  const matched = candidates.filter((stock, index) => {
    return candidates.findIndex((item) => item.symbol === stock.symbol) === index
      && stockMatches(stock, normalized);
  });

  const fallback = buildFallbackStockTarget(keyword);
  if (fallback && !matched.some((stock) => stock.symbol === fallback.symbol)) {
    matched.push(fallback);
  }

  return matched.slice(0, limit);
}

export function findStockTarget(value: string): StockTarget | undefined {
  const normalized = normalizeAlias(value);
  const candidates = [...STOCK_UNIVERSE, ...readCachedStocks(), ...stockMemoryCache.values()];
  return candidates.find((stock, index) => {
    if (candidates.findIndex((item) => item.symbol === stock.symbol) !== index) return false;
    const aliases = [
      stock.name,
      stock.symbol,
      stock.symbol.replace('.', ''),
      stock.symbol.split('.')[0],
      formatStockLabel(stock),
      ...stock.tags,
    ].map(normalizeAlias);

    return aliases.some((candidate) => candidate === normalized);
  }) ?? searchStockTargets(value, 1)[0] ?? buildFallbackStockTarget(value);
}
