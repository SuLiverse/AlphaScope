import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Newspaper, 
  Search, 
  TrendingUp, 
  Flame, 
  Calendar, 
  Sparkles, 
  CheckCircle, 
  Clock, 
  ArrowUpRight, 
  ArrowDownRight, 
  Gauge, 
  Globe, 
  FileText,
  Link2,
  MessageCircle,
  Send,
  Settings2,
  RefreshCw,
  X,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { cn, isHttpUrl } from '../lib/utils';
import { STOCK_UNIVERSE, StockTarget, findStockTarget, formatStockLabel } from '../lib/stocks';
import { getPersistedStock, subscribeStockSelected, subscribeSettingsChanged } from '../lib/workspaceEvents';
import { fetchApi } from '../lib/api';
import {
  buildModelOptions,
  getModelKey,
  getRouteSelection,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
  ModelOption,
  ModelProvider,
} from '../lib/aiModelRouting';
import { ThemedSelect } from './ThemedSelect';
import { NewsFeedList, type NewsItem } from './NewsFeedList';

interface NewsAssistantMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

interface BackendNewsRecord {
  id?: string;
  title?: string;
  summary?: string;
  content?: string;
  source?: string;
  source_url?: string;
  published_at?: string;
  event_type?: string;
  sentiment?: number;
  importance?: number;
  confidence?: number;
}

interface BackendAnnouncementRecord {
  id?: string;
  title?: string;
  category?: string;
  source?: string;
  source_url?: string;
  published_at?: string;
  importance?: number;
  confidence?: number;
}

interface NewsApiPayload {
  news?: BackendNewsRecord[];
  total?: number;
  source_status?: string;
  degraded?: boolean;
  sources?: string[];
  source_count?: number;
  fallback_sources?: string[];
  error?: string;
}

interface AnnouncementApiPayload {
  announcements?: BackendAnnouncementRecord[];
  total?: number;
  source_status?: string;
  degraded?: boolean;
  source?: string;
  fallback_sources?: string[];
  error?: string;
}

interface NewsUrlParsePayload {
  title?: string;
  content?: string;
  summary?: string;
  source?: string;
  source_url?: string;
  published_at?: string;
  sentiment?: number;
  importance?: number;
  category?: string;
  degraded?: boolean;
  source_status?: string;
  error?: string;
}

interface ChatResponse {
  content?: string;
  provider?: string;
  model?: string;
}

const SOURCE_TIER_MAP: Record<string, NewsItem['sourceTier']> = {
  cninfo: '官方披露',
  巨潮资讯: '官方披露',
  交易所公告: '官方披露',
  上交所: '官方披露',
  深交所: '官方披露',
  公司公告: '官方披露',
  交易所互动易: '官方披露',
  sec: '官方披露',
  hkex: '官方披露',
  财联社: '主流媒体',
  东财: '主流媒体',
  东方财富: '主流媒体',
  新浪: '主流媒体',
  财新: '主流媒体',
  证券时报: '主流媒体',
  中国证券报: '主流媒体',
  上海证券报: '主流媒体',
  Wind: '数据终端',
  Choice: '数据终端',
  iFinD: '数据终端',
  Tushare: '数据终端',
  东财数据中心: '数据终端',
  两融数据: '数据终端',
  交易所逐笔与资金流: '数据终端',
  同花顺热榜: '舆情/另类',
  百度股市通: '舆情/另类',
  雪球: '舆情/另类',
  社媒监控: '舆情/另类',
};

const SOURCE_MATRIX: Array<{
  tier: NewsItem['sourceTier'];
  sources: string[];
  note: string;
}> = [
  {
    tier: '官方披露',
    sources: ['巨潮资讯', '上交所公告', '深交所公告', '交易所互动易', '公司官网'],
    note: '公告、问询函、监管函优先入证据链',
  },
  {
    tier: '主流媒体',
    sources: ['财联社', '东方财富资讯', '新浪财经', '财新', '证券时报'],
    note: '用于事件窗口和传播范围识别',
  },
  {
    tier: '数据终端',
    sources: ['东财搜索', '东财数据中心', 'Choice/Wind研报索引', '两融数据', '资金流'],
    note: '补充行业、研报、资金与风险事件',
  },
  {
    tier: '舆情/另类',
    sources: ['同花顺热榜', '百度股市通', '雪球', '社媒监控'],
    note: '只做召回扩展，需二次核验',
  },
];

const FALLBACK_SOURCE_LABELS: Record<string, string> = {
  eastmoney_stock_search: '东财个股搜索',
  eastmoney_topic_search: '东财主题搜索',
  cls_telegraph: '财联社快讯',
  eastmoney_telegraph: '东财快讯',
  sina_telegraph: '新浪快讯',
  caixin_summary: '财新摘要',
  cninfo_announcements: '巨潮公告',
  local_announcements: '本地公告库',
  provider_registry: 'Provider Registry',
  local_news: '本地新闻库',
};

const SOURCE_TIER_IDS: Record<NewsItem['sourceTier'], string> = {
  官方披露: 'official',
  主流媒体: 'media',
  数据终端: 'terminal',
  '舆情/另类': 'sentiment',
  研究兜底: 'fallback',
};

function sourceSlug(source: string): string {
  const normalized = source.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  if (normalized) return normalized.slice(0, 48);
  let hash = 0;
  for (let index = 0; index < source.length; index += 1) {
    hash = (hash * 31 + source.charCodeAt(index)) >>> 0;
  }
  return `src-${hash.toString(36)}`;
}

function sourceTier(source: string): NewsItem['sourceTier'] {
  const matched = Object.entries(SOURCE_TIER_MAP).find(([key]) => source.includes(key));
  return matched?.[1] ?? '研究兜底';
}

function displayFallbackSource(source: string): string {
  return FALLBACK_SOURCE_LABELS[source] ?? source;
}

function fallbackSourceTier(source: string): NewsItem['sourceTier'] {
  if (/公告|cninfo|announcements/i.test(source)) return '官方披露';
  if (/数据|两融|资金|registry|local_news/i.test(source)) return '数据终端';
  if (/热榜|社媒|topic|舆情/i.test(source)) return '舆情/另类';
  return sourceTier(source) === '研究兜底' ? '主流媒体' : sourceTier(source);
}

function formatBackendTime(value?: string): string {
  if (!value) return '--:--';
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  const match = value.match(/(\d{1,2}):(\d{2})/);
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : value.slice(0, 5);
}

function categoryFromEvent(value?: string): NewsItem['category'] {
  const text = String(value || '').toLowerCase();
  if (/ann|公告|report|披露|业绩|分红|减持|增持/.test(text)) return 'announcement';
  if (/risk|风险|问询|处罚|诉讼|解禁/.test(text)) return 'risk';
  if (/fund|flow|资金|两融|龙虎榜|大宗/.test(text)) return 'funds';
  return 'macro';
}

function sentimentFromScore(value?: number): NewsItem['sentiment'] {
  if (typeof value !== 'number') return 'neutral';
  if (value > 0.15) return 'bullish';
  if (value < -0.15) return 'bearish';
  return 'neutral';
}

function normalizeBackendNews(item: BackendNewsRecord, stock: StockTarget): NewsItem | undefined {
  const title = item.title?.trim();
  if (!title) return undefined;
  const source = item.source?.trim() || '后端新闻源';
  const content = item.content?.trim() || item.summary?.trim() || title;
  const importance = typeof item.importance === 'number' ? item.importance : 0.55;
  const impactScore = Math.max(35, Math.min(96, Math.round(importance * 100)));
  return {
    id: item.id || `${stock.symbol}-backend-news-${title}`,
    time: formatBackendTime(item.published_at),
    title,
    category: categoryFromEvent(item.event_type),
    source,
    sourceTier: sourceTier(source),
    sourceStatus: 'real',
    sourceUrl: item.source_url,
    severity: impactScore >= 80 ? 'high' : impactScore >= 65 ? 'medium' : 'info',
    sentiment: sentimentFromScore(item.sentiment),
    impactScore,
    content,
    aiSummary: `来自${source}的实时入库资讯，已关联到 ${stock.name}。请与公告、资金流和价格行为交叉验证后再进入结论。`,
  };
}

function normalizeBackendAnnouncement(item: BackendAnnouncementRecord, stock: StockTarget): NewsItem | undefined {
  const title = item.title?.trim();
  if (!title) return undefined;
  const source = item.source?.trim() || '公告源';
  const importance = typeof item.importance === 'number' ? item.importance : 0.75;
  const impactScore = Math.max(45, Math.min(98, Math.round(importance * 100)));
  return {
    id: item.id || `${stock.symbol}-backend-ann-${title}`,
    time: formatBackendTime(item.published_at),
    title: `${stock.name} 公告：${title}`,
    category: 'announcement',
    source,
    sourceTier: sourceTier(source),
    sourceStatus: 'real',
    sourceUrl: item.source_url,
    severity: impactScore >= 82 ? 'high' : impactScore >= 65 ? 'medium' : 'info',
    sentiment: 'neutral',
    impactScore,
    content: `${stock.symbol} 公告分类：${item.category || 'other'}。该条来自 ${source}，需优先作为证据链来源保存。`,
    aiSummary: '公告源优先级高于媒体快讯。若公告涉及业绩、减持、问询或重大合同，应同步推送至风险 Agent。',
  };
}

function mergeNewsItems(primary: NewsItem[], fallback: NewsItem[], limit = 32): NewsItem[] {
  const seen = new Set<string>();
  const merged: NewsItem[] = [];
  [...primary, ...fallback].forEach((item) => {
    const key = `${item.title}|${item.source}`;
    if (seen.has(key)) return;
    seen.add(key);
    merged.push(item);
  });
  return merged.slice(0, limit);
}

function categoryLabel(category: NewsItem['category']): string {
  if (category === 'announcement') return '个股公告';
  if (category === 'risk') return '风控与舆情';
  if (category === 'funds') return '主力异动';
  return '宏观大势';
}

function sentimentLabel(sentiment: NewsItem['sentiment']): string {
  if (sentiment === 'bullish') return '利好';
  if (sentiment === 'bearish') return '偏空';
  return '中性';
}

function domainFromUrl(value: string): string {
  try {
    return new URL(value).hostname.replace(/^www\./, '');
  } catch {
    return '外部链接';
  }
}

function sourceUrlForArticle(article: NewsItem, stock: StockTarget): string {
  if (isHttpUrl(article.sourceUrl)) return article.sourceUrl as string;
  const query = [article.title, stock.name, article.source].filter(Boolean).join(' ');
  return `https://www.baidu.com/s?wd=${encodeURIComponent(query)}`;
}

function sourceActionLabel(article: NewsItem): string {
  return isHttpUrl(article.sourceUrl) ? '打开原文' : '检索原文';
}

function buildNewsAssistantAnswer(article: NewsItem | null, question: string, stock: StockTarget): string {
  if (!article) {
    return '请先在左侧选择一条新闻，或粘贴新闻链接生成待核验卡片后再提问。';
  }
  const normalized = question.trim();
  const isRiskQuestion = /风险|利空|负面|担心|雷|减持|问询|处罚|诉讼/.test(normalized);
  const isImpactQuestion = /影响|怎么看|解读|利好|利空|股价|估值|催化/.test(normalized);
  const isEvidenceQuestion = /证据|来源|原文|核验|可信|真假|出处/.test(normalized);
  const action = article.sourceTier === '官方披露'
    ? '可优先进入证据链，但仍要核对披露日期、主体和关键数字。'
    : '暂按线索处理，需要与公告、行情、资金流或权威媒体交叉核验。';
  const riskLine = isRiskQuestion
    ? `风险侧重点：${article.category === 'funds' ? '资金异动容易短期反转，需要看连续性。' : article.category === 'risk' ? '需要优先找公告或监管披露确认。' : '不要把单条媒体信息直接外推为公司基本面变化。'}`
    : `风险提示：当前影响分 ${article.impactScore}%，情绪为${sentimentLabel(article.sentiment)}，仍需二次核验。`;
  const impactLine = isImpactQuestion
    ? `对 ${stock.name} 的影响：这条更适合作为${categoryLabel(article.category)}线索，短期看事件窗口，中期要落到业绩、现金流或估值假设。`
    : `投研定位：这条属于${categoryLabel(article.category)}，适合和同主题新闻一起做多源对照。`;
  const evidenceLine = isEvidenceQuestion
    ? `来源核验：来源为「${article.source}」，层级为「${article.sourceTier}」${article.sourceUrl ? `，可通过原文链接回看：${article.sourceUrl}` : '，当前没有后端原文链接，需要保留标题和抓取时间作为线索。'}`
    : `核验动作：${action}`;

  return [
    `已基于选中新闻「${article.title}」做快速回答。`,
    '',
    impactLine,
    riskLine,
    evidenceLine,
    '',
    `原文摘要：${article.content}`,
  ].join('\n');
}

function buildLinkAnalysis(url: string, stock: StockTarget): string {
  const host = domainFromUrl(url);
  return [
    `已接收新闻链接：${url}`,
    '',
    `站点识别：${host}`,
    `当前绑定标的：${formatStockLabel(stock)}`,
    '',
    '链接解析状态：前端已生成待核验卡片。若后端抓取服务开启，可在下一步接入正文抽取；当前不会把链接内容当作已验证事实。',
    '',
    '建议核验顺序：',
    '1. 打开原文确认标题、发布时间和作者/来源。',
    '2. 抽取涉及公司、金额、时间、政策或监管主体的关键句。',
    '3. 与公告、交易所披露、行情和资金流做交叉验证。',
  ].join('\n');
}

function buildNewsFeed(stock: StockTarget): NewsItem[] {
  const isChip = /半导体|存储|芯片|光模块/i.test(stock.sector) || stock.symbol.startsWith('301666');
  const isConsumption = /白酒|消费/i.test(stock.sector);
  const label = formatStockLabel(stock);
  const sector = stock.sector || '所属行业';

  return [
    {
      id: `${stock.symbol}-announcement-1`,
      time: '14:12',
      title: `${label} 发布经营与风险提示更新：重点核验收入确认、存货周转与客户结构变化。`,
      category: 'announcement',
      source: '巨潮资讯/公司公告',
      sourceTier: '官方披露',
      sourceStatus: 'fallback',
      severity: 'medium',
      sentiment: 'neutral',
      impactScore: 76,
      content: `${stock.name} 当前公告解读聚焦 ${sector} 景气度、订单兑现、费用投放和现金流变化。系统已将该公告同步到全局标的，后续研报和证据链应以 ${stock.symbol} 为主键。`,
      aiSummary: `公告本身不直接构成买卖结论，需把 ${stock.name} 的经营数据与同行、资金流和风险事件交叉核验。`
    },
    {
      id: `${stock.symbol}-announcement-2`,
      time: '13:58',
      title: `${stock.name} 投资者关系活动记录披露：管理层回应 ${sector} 需求、价格与产能节奏。`,
      category: 'announcement',
      source: '交易所互动易',
      sourceTier: '官方披露',
      sourceStatus: 'fallback',
      severity: 'info',
      sentiment: isChip ? 'bullish' : 'neutral',
      impactScore: isChip ? 82 : 68,
      content: isChip
        ? '管理层重点提及企业级存储、国产替代和客户认证进展，但对价格竞争、库存跌价和毛利率波动仍保持谨慎表述。'
        : '管理层重点回应渠道、产品结构和成本控制，短期仍需观察终端动销和行业需求恢复。',
      aiSummary: isChip
        ? '若后续公告验证客户导入与收入确认，成长弹性可上调；若仅停留在主题预期，需降低置信度。'
        : '适合作为基本面补充证据，不宜单独进入最终摘要。'
    },
    {
      id: `${stock.symbol}-risk-1`,
      time: '13:21',
      title: `${stock.name} 风险扫描：减持、解禁、问询与商誉/存货项目进入复核清单。`,
      category: 'risk',
      source: '东财数据中心/风控雷达',
      sourceTier: '数据终端',
      sourceStatus: 'fallback',
      severity: 'high',
      sentiment: 'bearish',
      impactScore: 79,
      content: `系统对 ${stock.symbol} 建立风险检查表：限售解禁、董监高减持、交易所问询、异常大宗交易、融资余额突变均需在最终研报中标注来源。`,
      aiSummary: '风险项当前作为“待核验观察”处理；若出现公告确认或交易所披露，应同步下调风险评分。'
    },
    {
      id: `${stock.symbol}-funds-1`,
      time: '11:36',
      title: `${stock.name} 主力资金异动：盘中换手与大单净额偏离近 20 日均值。`,
      category: 'funds',
      source: '交易所逐笔与资金流',
      sourceTier: '数据终端',
      sourceStatus: 'fallback',
      severity: 'medium',
      sentiment: 'bullish',
      impactScore: 74,
      content: `${stock.symbol} 的大单、融资余额和行业 ETF 联动需要一起观察。若放量伴随价格回落，则资金项改判为分歧而非吸筹。`,
      aiSummary: '资金信号只能提高短期关注度，不能替代公告、业绩和估值证据。'
    },
    {
      id: `${stock.symbol}-macro-1`,
      time: '10:42',
      title: isChip ? `大基金三期与 AI 数据中心资本开支升温，${sector} 板块关注度抬升。` : `${sector} 行业景气跟踪：政策预期与消费/需求修复影响估值中枢。`,
      category: 'macro',
      source: isChip ? '产业政策与主题库' : '宏观行业跟踪',
      sourceTier: isChip ? '舆情/另类' : '主流媒体',
      sourceStatus: 'fallback',
      severity: 'high',
      sentiment: isChip || isConsumption ? 'bullish' : 'neutral',
      impactScore: isChip ? 92 : 72,
      content: isChip
        ? `半导体存储链条受国产替代、AI 服务器和数据中心资本开支影响较大，${stock.name} 需要重点验证产品落地和客户认证。`
        : `${stock.name} 的行业贝塔来自政策、需求和价格预期，需避免把宏观利好直接等同于公司业绩改善。`,
      aiSummary: isChip
        ? '主题强度较高，但最终权重取决于订单、毛利率和库存周转证据。'
        : '宏观信号作为估值背景，不直接进入个股结论。'
    },
    {
      id: `${stock.symbol}-announcement-3`,
      time: '09:48',
      title: `${stock.name} 近期公告索引：定期报告、股东户数、分红派息与异常波动说明已归档。`,
      category: 'announcement',
      source: '公告索引',
      sourceTier: '官方披露',
      sourceStatus: 'fallback',
      severity: 'info',
      sentiment: 'neutral',
      impactScore: 61,
      content: `已为 ${stock.symbol} 建立公告索引入口，后续可接入东财数据中心、交易所公告和公司官网披露，形成可追踪证据链。`,
      aiSummary: '该条是索引型情报，适合作为证据附录，不应单独影响评级。'
    },
    {
      id: `${stock.symbol}-risk-2`,
      time: '09:20',
      title: `${stock.name} 舆情监控：社媒热度升高但有效信源不足，暂不进入最终摘要。`,
      category: 'risk',
      source: '同花顺热榜/社媒监控',
      sourceTier: '舆情/另类',
      sourceStatus: 'fallback',
      severity: 'medium',
      sentiment: 'neutral',
      impactScore: 58,
      content: '热榜与社媒讨论可提示关注方向，但需要公告、交易数据或权威媒体确认后，才能进入正式研报结论。',
      aiSummary: '按证据链规则，该类信息保留在“待核验观察”。'
    },
    {
      id: `${stock.symbol}-funds-2`,
      time: '09:12',
      title: `${stock.name} 融资融券观察：余额变化与价格方向需要继续匹配。`,
      category: 'funds',
      source: '两融数据',
      sourceTier: '数据终端',
      sourceStatus: 'fallback',
      severity: 'info',
      sentiment: 'neutral',
      impactScore: 55,
      content: `融资余额若连续扩张但股价走弱，可能代表交易拥挤；若余额温和提升且公告证据改善，可作为流动性补充因子。`,
      aiSummary: '两融数据只作为资金结构补充，不单独给出方向判断。'
    },
    {
      id: `${stock.symbol}-media-cls`,
      time: '08:58',
      title: `${stock.name} 进入财联社快讯关键词池：产业链订单、政策催化与估值修复被同步跟踪。`,
      category: 'macro',
      source: '财联社',
      sourceTier: '主流媒体',
      sourceStatus: 'fallback',
      severity: 'medium',
      sentiment: isChip ? 'bullish' : 'neutral',
      impactScore: isChip ? 78 : 63,
      content: `财联社快讯池用于捕捉 ${stock.name} 所属 ${sector} 的实时催化，但需要与公告和行情数据交叉验证。`,
      aiSummary: '主流媒体快讯适合提示事件窗口，不能替代公司披露。'
    },
    {
      id: `${stock.symbol}-media-eastmoney`,
      time: '08:46',
      title: `${stock.name} 东方财富资讯池更新：机构关注度、行业热度与相关研报标题同步入库。`,
      category: 'macro',
      source: '东方财富资讯',
      sourceTier: '主流媒体',
      sourceStatus: 'fallback',
      severity: 'info',
      sentiment: 'neutral',
      impactScore: 60,
      content: '东财资讯用于补充新闻广度，重点看是否出现多源重复确认，而不是单条标题本身。',
      aiSummary: '若同一事件在公告、媒体、资金数据中同时出现，置信度才会上调。'
    },
    {
      id: `${stock.symbol}-research-choice`,
      time: '08:31',
      title: `${stock.name} 券商研报摘要：盈利预测分歧与目标价调整进入观察列表。`,
      category: 'macro',
      source: 'Choice/Wind 研报索引',
      sourceTier: '数据终端',
      sourceStatus: 'fallback',
      severity: 'info',
      sentiment: 'neutral',
      impactScore: 57,
      content: `研报源关注 ${stock.name} 的盈利预测、估值假设和评级变化。受版权限制，终端仅展示元数据和摘要级归因。`,
      aiSummary: '研报源适合做估值假设对照，需保留机构、日期和关键假设。'
    },
    {
      id: `${stock.symbol}-alt-baidu`,
      time: '08:19',
      title: `${stock.name} 百度股市通概念映射：${sector}、地域与相邻主题已加入检索扩展词。`,
      category: 'risk',
      source: '百度股市通',
      sourceTier: '舆情/另类',
      sourceStatus: 'fallback',
      severity: 'info',
      sentiment: 'neutral',
      impactScore: 52,
      content: '概念映射用于扩大检索召回，可能存在标签噪声，最终结论仍以公告和交易数据为准。',
      aiSummary: '另类源提升召回，不提升单条证据权重。'
    },
    {
      id: `${stock.symbol}-official-exchange`,
      time: '08:05',
      title: `${stock.name} 交易所公告快照：异常波动、问询函、监管函将优先推送。`,
      category: 'announcement',
      source: stock.exchange === 'SH' ? '上交所公告' : stock.exchange === 'SZ' ? '深交所公告' : '交易所公告',
      sourceTier: '官方披露',
      sourceStatus: 'fallback',
      severity: 'high',
      sentiment: 'neutral',
      impactScore: 84,
      content: '交易所披露是公告类最高优先级来源；若与媒体报道冲突，以交易所公告为准。',
      aiSummary: '官方披露优先进入证据链，并要求保留来源链接与检索时间。'
    },
  ];
}

const CALENDAR_EVENTS = [
  {
    time: '16:00',
    title: '欧元区 4月 核心物价调和指数（HICP）',
    importance: '★★★☆☆',
    status: '已公布',
    preview: '预期 2.7% | 实际 2.6%',
    impact: '中性偏好',
    scope: '欧元、欧洲股指、外需链',
    readthrough: '实际值低于预期，短线偏向缓和通胀压力，对全球风险偏好形成温和支撑。',
    watch: ['欧元兑美元', '欧洲消费与奢侈品链', '全球利率预期']
  },
  {
    time: '20:30',
    title: '美国 4月 PCE 物价指数核心指标（年率）',
    importance: '★★★★★',
    status: '未公布',
    preview: '前值 2.8% | 预测值 2.7%',
    impact: '高瞻性催化',
    scope: '美债、美元、成长股估值',
    readthrough: '若低于预测，降息交易可能升温；若高于预测，长端利率上行会压制高估值资产。',
    watch: ['10年期美债收益率', '美元指数', '半导体与港股科技']
  },
  {
    time: '21:00',
    title: '美联储沃勒、雷曼等委员对货币政策答疑',
    importance: '★★★★☆',
    status: '未公布',
    preview: '政策口径寻踪，寻找下半年降息坐标',
    impact: '流动性突变',
    scope: '全球流动性、北向风险偏好',
    readthrough: '讲话重点看通胀韧性和就业降温的权重，偏鹰会推升风险溢价，偏鸽会改善资金面预期。',
    watch: ['联邦基金期货', '离岸人民币', '外资重仓板块']
  }
];

interface NewsAggregatorProps {
  onOpenModelSettings?: () => void;
}

function formatModelOption(option?: ModelOption) {
  if (!option) return '未配置';
  return `${option.providerName} / ${option.modelId}`;
}

interface NewsAssistantComposerProps {
  disabled: boolean;
  placeholder: string;
  prefill: { nonce: number; text: string };
  onSend: (text: string) => void;
}

/**
 * 聊天输入框：输入 state 下放于此，打字只重渲本组件，
 * 不再触发 NewsAggregator 整树（尤其是 feed 列表）重渲。
 * 外部（咨询按钮 / 链接解析 / 详情弹窗）通过 prefill（nonce 递增）注入预设问题。
 */
function NewsAssistantComposer({ disabled, placeholder, prefill, onSend }: NewsAssistantComposerProps) {
  const [value, setValue] = useState('');
  const appliedPrefillNonceRef = useRef(prefill.nonce);

  useEffect(() => {
    if (prefill.nonce === appliedPrefillNonceRef.current) return;
    appliedPrefillNonceRef.current = prefill.nonce;
    if (prefill.text) setValue(prefill.text);
  }, [prefill]);

  const send = () => {
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue('');
  };

  return (
    <div className="flex gap-2">
      <textarea
        data-testid="news-assistant-input"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            send();
          }
        }}
        placeholder={placeholder}
        disabled={disabled}
        className="min-h-[42px] min-w-0 flex-1 resize-none rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] text-neutral-200 outline-none transition-colors placeholder:text-neutral-600 focus:border-violet-400/50"
      />
      <button
        type="button"
        data-testid="news-assistant-send"
        onClick={send}
        disabled={disabled || !value.trim()}
        className="inline-flex h-[42px] w-[42px] flex-shrink-0 items-center justify-center rounded-lg border border-violet-500/30 bg-violet-500/10 text-violet-100 transition-colors hover:bg-violet-500/20"
        title="发送"
      >
        {disabled ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
      </button>
    </div>
  );
}

interface NewsLinkParserBoxProps {
  onParse: (url: string) => Promise<void>;
}

/** 链接解析输入框：输入 state 同样下放，解析完成后清空输入。 */
function NewsLinkParserBox({ onParse }: NewsLinkParserBoxProps) {
  const [value, setValue] = useState('');

  const submit = async () => {
    const url = value.trim();
    if (!url) return;
    await onParse(url);
    setValue('');
  };

  return (
    <div className="rounded-xl border border-white/5 bg-black/20 p-3">
      <div className="mb-2 flex items-center gap-2 text-[11px] font-medium text-neutral-300">
        <Link2 className="h-3.5 w-3.5 text-indigo-300" />
        解析新闻链接
      </div>
      <div className="flex gap-2">
        <input
          type="url"
          data-testid="news-link-input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit();
          }}
          placeholder="粘贴新闻原文链接..."
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] text-neutral-200 outline-none transition-colors placeholder:text-neutral-600 focus:border-indigo-400/50"
        />
        <button
          type="button"
          data-testid="news-link-parse"
          onClick={submit}
          className="inline-flex items-center gap-1 rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-[11px] text-indigo-100 transition-colors hover:bg-indigo-500/20"
        >
          <Sparkles className="h-3.5 w-3.5" />
          解析
        </button>
      </div>
    </div>
  );
}


/** 后端信源状态枚举 → 用户可读标签（idle/loading/ok/failed/其他 source_status）。 */
function backendStateLabel(status: string): string {
  switch (status) {
    case 'ok':
      return '正常';
    case 'failed':
      return '未连接';
    case 'loading':
      return '连接中';
    case 'idle':
      return '待连接';
    case 'empty':
      return '无数据';
    case 'cache':
      return '缓存数据';
    case 'timeout':
      return '响应超时';
    default:
      return status;
  }
}

/** 状态 → 颜色点：正常绿、进行中琥珀呼吸、异常中性灰（错误细节不在概览层裸奔）。 */
function backendStateDotClass(status: string): string {
  if (status === 'ok') return 'bg-emerald-400';
  if (status === 'loading') return 'bg-amber-400 animate-pulse';
  return 'bg-neutral-500';
}

export function NewsAggregator({ onOpenModelSettings }: NewsAggregatorProps) {
  const [currentStock, setCurrentStock] = useState<StockTarget>(() => getPersistedStock() ?? STOCK_UNIVERSE[0]);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedSourceTier, setSelectedSourceTier] = useState<NewsItem['sourceTier'] | 'all'>('all');
  const [selectedSource, setSelectedSource] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedArticle, setSelectedArticle] = useState<NewsItem | null>(null);
  const [detailArticle, setDetailArticle] = useState<NewsItem | null>(null);
  const [selectedCalendarIndex, setSelectedCalendarIndex] = useState<number>(1);
  const [isAiExpanded, setIsAiExpanded] = useState<boolean>(true);
  const [isCalendarExpanded, setIsCalendarExpanded] = useState<boolean>(true);
  const [isSourceOverviewExpanded, setIsSourceOverviewExpanded] = useState<boolean>(true);
  const [isSourceMatrixExpanded, setIsSourceMatrixExpanded] = useState<boolean>(false);
  const [assistantPrefill, setAssistantPrefill] = useState<{ nonce: number; text: string }>({ nonce: 0, text: '' });
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [newsModels, setNewsModels] = useState<ModelOption[]>([]);
  const [selectedNewsModelKey, setSelectedNewsModelKey] = useState('');
  const [assistantMessages, setAssistantMessages] = useState<NewsAssistantMessage[]>([
    {
      id: 'news-assistant-welcome',
      role: 'assistant',
      content: '请选择左侧新闻后提问，或粘贴新闻链接做待核验解析。我会优先按来源、影响分、情绪方向和当前标的做投研拆解。',
      timestamp: new Date().toISOString(),
    },
  ]);
  const [remoteNews, setRemoteNews] = useState<NewsItem[]>([]);
  const [sourceStatus, setSourceStatus] = useState<'loading' | 'real' | 'fallback'>('fallback');
  const [backendSourceState, setBackendSourceState] = useState<{
    sources: string[];
    fallbackSources: string[];
    newsStatus: string;
    announcementStatus: string;
    degraded: boolean;
  }>({
    sources: [],
    fallbackSources: [],
    newsStatus: 'idle',
    announcementStatus: 'idle',
    degraded: false,
  });
  const fallbackNews = useMemo(() => buildNewsFeed(currentStock), [currentStock]);
  const news = useMemo(() => mergeNewsItems(remoteNews, fallbackNews), [remoteNews, fallbackNews]);
  const selectedNewsModel = newsModels.find((model) => model.key === selectedNewsModelKey) ?? newsModels[0];

  useEffect(() => subscribeStockSelected(({ stock }) => {
    setCurrentStock(findStockTarget(stock.symbol) ?? stock);
    setSelectedArticle(null);
    setDetailArticle(null);
    setSearchQuery('');
    setSelectedCategory('all');
    setSelectedSourceTier('all');
    setSelectedSource('');
  }), []);

  const [modelsReloadKey, setModelsReloadKey] = useState(0);
  useEffect(() => subscribeSettingsChanged(() => setModelsReloadKey((k) => k + 1)), []);

  useEffect(() => {
    let cancelled = false;
    async function loadModels() {
      try {
        const result = await fetchApi<{ providers: ModelProvider[] }>('/api/settings/providers');
        if (cancelled) return;
        const providers = result.providers || [];
        const routes = await loadAiModelRoutesFromApi().catch(() => loadLocalAiModelRoutes());
        if (cancelled) return;
        const models = buildModelOptions(providers, 'chat');
        const routeKey = getModelKey(getRouteSelection(routes, providers, 'news'));
        setNewsModels(models);
        setSelectedNewsModelKey((current) => (
          current && models.some((model) => model.key === current)
            ? current
            : routeKey && models.some((model) => model.key === routeKey)
              ? routeKey
              : models[0]?.key || ''
        ));
      } catch {
        if (!cancelled) {
          setNewsModels([]);
          setSelectedNewsModelKey('');
        }
      }
    }
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, [modelsReloadKey]);

  useEffect(() => {
    let cancelled = false;
    const symbol = currentStock.symbol.split('.')[0];
    setSourceStatus('loading');
    setBackendSourceState((prev) => ({ ...prev, newsStatus: 'loading', announcementStatus: 'loading' }));

    Promise.allSettled([
      fetchApi<NewsApiPayload>(
        `/api/news?symbol=${encodeURIComponent(symbol)}&limit=24`,
      ),
      fetchApi<AnnouncementApiPayload>(
        `/api/news/announcements?symbol=${encodeURIComponent(symbol)}&limit=12`,
      ),
    ]).then((results) => {
      if (cancelled) return;
      const [newsResult, annResult] = results;
      const backendItems: NewsItem[] = [];
      if (newsResult.status === 'fulfilled') {
        (newsResult.value.news || [])
          .map((item) => normalizeBackendNews(item, currentStock))
          .filter((item): item is NewsItem => Boolean(item))
          .forEach((item) => backendItems.push(item));
      }
      if (annResult.status === 'fulfilled') {
        (annResult.value.announcements || [])
          .map((item) => normalizeBackendAnnouncement(item, currentStock))
          .filter((item): item is NewsItem => Boolean(item))
          .forEach((item) => backendItems.push(item));
      }
      const newsPayload = newsResult.status === 'fulfilled' ? newsResult.value : undefined;
      const annPayload = annResult.status === 'fulfilled' ? annResult.value : undefined;
      const backendSources = [
        ...(newsPayload?.sources || []),
        ...(annPayload?.source ? [annPayload.source] : []),
      ].filter(Boolean);
      const fallbackSources = [
        ...(newsPayload?.fallback_sources || []),
        ...(annPayload?.fallback_sources || []),
      ].map(displayFallbackSource);

      setRemoteNews(backendItems);
      setSourceStatus(backendItems.length > 0 ? 'real' : 'fallback');
      setBackendSourceState({
        sources: Array.from(new Set(backendSources)),
        fallbackSources: Array.from(new Set(fallbackSources)),
        newsStatus: newsPayload?.source_status || (newsResult.status === 'fulfilled' ? 'ok' : 'failed'),
        announcementStatus: annPayload?.source_status || (annResult.status === 'fulfilled' ? 'ok' : 'failed'),
        degraded: Boolean(newsPayload?.degraded || annPayload?.degraded || backendItems.length === 0),
      });
    }).catch(() => {
      if (!cancelled) {
        setRemoteNews([]);
        setSourceStatus('fallback');
        setBackendSourceState({
          sources: [],
          fallbackSources: [],
          newsStatus: 'failed',
          announcementStatus: 'failed',
          degraded: true,
        });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [currentStock]);

  const filterCategories = [
    { id: 'all', label: '全部资讯', count: news.length },
    { id: 'macro', label: '宏观大势', count: news.filter(n => n.category === 'macro').length },
    { id: 'announcement', label: '个股公告', count: news.filter(n => n.category === 'announcement').length },
    { id: 'risk', label: '风控与舆情', count: news.filter(n => n.category === 'risk').length },
    { id: 'funds', label: '主力异动', count: news.filter(n => n.category === 'funds').length }
  ];

  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const filteredNews = useMemo(() => news.filter(item => {
    const matchesCategory = selectedCategory === 'all' || item.category === selectedCategory;
    const matchesTier = selectedSourceTier === 'all' || item.sourceTier === selectedSourceTier;
    const matchesSource = !selectedSource || item.source === selectedSource || item.source.includes(selectedSource) || selectedSource.includes(item.source);
    const searchableText = [
      item.title,
      item.content,
      item.source,
      item.sourceTier,
      currentStock.symbol,
      currentStock.name,
      currentStock.sector,
    ].join(' ').toLowerCase();
    const matchesSearch = !normalizedSearchQuery || searchableText.includes(normalizedSearchQuery);
    return matchesCategory && matchesTier && matchesSource && matchesSearch;
  }), [news, selectedCategory, selectedSourceTier, selectedSource, normalizedSearchQuery, currentStock]);

  useEffect(() => {
    if (filteredNews.length === 0) {
      if (selectedArticle) setSelectedArticle(null);
      return;
    }
    const stillVisible = selectedArticle ? filteredNews.some((item) => item.id === selectedArticle.id) : false;
    if (!stillVisible) {
      setSelectedArticle(filteredNews[0]);
    }
  }, [filteredNews, selectedArticle]);

  const sourceSummary = useMemo(() => {
    const sources: string[] = Array.from(new Set(news.map((item) => item.source)));
    const tiers: NewsItem['sourceTier'][] = Array.from(new Set(news.map((item) => item.sourceTier)));
    const sourceTierBySource = new Map<string, NewsItem['sourceTier']>();
    news.forEach((item) => {
      if (!sourceTierBySource.has(item.source)) {
        sourceTierBySource.set(item.source, item.sourceTier);
      }
    });
    const tierCounts = SOURCE_MATRIX.map((entry) => ({
      ...entry,
      count: news.filter((item) => item.sourceTier === entry.tier).length,
      activeSources: sources.filter((source) => sourceTierBySource.get(source) === entry.tier),
    }));
    return {
      sources,
      tiers,
      tierCounts,
      sourceTierBySource,
      officialCount: news.filter((item) => item.sourceTier === '官方披露').length,
      mediaCount: news.filter((item) => item.sourceTier === '主流媒体').length,
      terminalCount: news.filter((item) => item.sourceTier === '数据终端').length,
      sentimentCount: news.filter((item) => item.sourceTier === '舆情/另类').length,
      realCount: news.filter((item) => item.sourceStatus === 'real').length,
    };
  }, [news]);
  const visibleSourceButtons = sourceSummary.sources.slice(0, 14);
  const activeFilters = [
    selectedCategory !== 'all' ? `分类：${filterCategories.find((cat) => cat.id === selectedCategory)?.label ?? selectedCategory}` : '',
    selectedSourceTier !== 'all' ? `来源层级：${selectedSourceTier}` : '',
    selectedSource ? `来源：${selectedSource}` : '',
    searchQuery ? `关键词：${searchQuery}` : '',
  ].filter(Boolean);
  const clearNewsFilters = useCallback(() => {
    setSelectedCategory('all');
    setSelectedSourceTier('all');
    setSelectedSource('');
    setSearchQuery('');
    setSelectedArticle(news[0] ?? null);
  }, [news]);
  const activateArticle = useCallback((item: NewsItem) => {
    setSelectedArticle(item);
    setIsAiExpanded(true);
  }, []);
  const openArticleDetail = useCallback((item: NewsItem) => {
    setSelectedArticle(item);
    setDetailArticle(item);
    setIsAiExpanded(true);
  }, []);
  const openArticleSource = useCallback((item: NewsItem) => {
    const url = sourceUrlForArticle(item, currentStock);
    window.open(url, '_blank', 'noopener,noreferrer');
  }, [currentStock]);
  const prefillAssistantInput = useCallback((text: string) => {
    setAssistantPrefill((prev) => ({ nonce: prev.nonce + 1, text }));
  }, []);
  const askFromFeed = useCallback((item: NewsItem) => {
    activateArticle(item);
    prefillAssistantInput(`请解析这条新闻对 ${currentStock.name} 的影响`);
  }, [activateArticle, currentStock.name, prefillAssistantInput]);
  const askAboutArticle = useCallback(async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || assistantLoading) return;
    const userMessage: NewsAssistantMessage = {
      id: `news-user-${Date.now()}`,
      role: 'user',
      content: trimmed,
      timestamp: new Date().toISOString(),
    };
    const pendingId = `news-assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const assistantMessage: NewsAssistantMessage = {
      id: pendingId,
      role: 'assistant',
      content: selectedNewsModel
        ? `正在调用新闻助手模型：${formatModelOption(selectedNewsModel)}`
        : '当前没有可用新闻助手模型。请到系统设置 > 模型路由中配置新闻助手模型。',
      timestamp: new Date().toISOString(),
    };
    setAssistantMessages((prev) => [...prev, userMessage, assistantMessage]);
    if (!selectedNewsModel) return;
    setAssistantLoading(true);
    try {
      const article = selectedArticle;
      const result = await fetchApi<ChatResponse>('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: [
            '你是证券新闻投研助手。请基于选中新闻和当前标的回答用户问题，必须区分已验证事实、待核验线索和推断。',
            '不要编造原文没有的信息；如果证据不足，明确说明需要打开原文或公告核验。',
            '',
            `用户问题：${trimmed}`,
            `当前标的：${formatStockLabel(currentStock)}`,
            article ? [
              `新闻标题：${article.title}`,
              `来源：${article.source} / ${article.sourceTier}`,
              `情绪：${sentimentLabel(article.sentiment)}，影响分：${article.impactScore}%`,
              `原文链接：${article.sourceUrl || '无'}`,
              `新闻正文/摘要：${article.content}`,
              `系统初筛：${article.aiSummary}`,
            ].join('\n') : '未选中新闻。',
          ].join('\n'),
          mode: 'free',
          stock_symbol: currentStock.symbol,
          stock_name: currentStock.name,
          provider: selectedNewsModel.providerId,
          model: selectedNewsModel.modelId,
          context: {
            news_title: article?.title,
            news_source: article?.source,
            news_tier: article?.sourceTier,
          },
        }),
      });
      const content = result.content?.trim() || '模型没有返回内容，请检查 Provider 权限、余额或 Base URL。';
      setAssistantMessages((prev) => prev.map((message) => (
        message.id === pendingId
          ? {
              ...message,
              content: `模型调用：${result.provider || selectedNewsModel.providerId} / ${result.model || selectedNewsModel.modelId}\n\n${content}`,
              timestamp: new Date().toISOString(),
            }
          : message
      )));
    } catch (error) {
      const fallback = buildNewsAssistantAnswer(selectedArticle, trimmed, currentStock);
      setAssistantMessages((prev) => prev.map((message) => (
        message.id === pendingId
          ? {
              ...message,
              content: [
                `新闻助手模型调用失败：${error instanceof Error ? error.message : String(error || '未知错误')}`,
                '',
                '本地规则兜底如下，未冒充真实 AI：',
                fallback,
              ].join('\n'),
              timestamp: new Date().toISOString(),
            }
          : message
      )));
    } finally {
      setAssistantLoading(false);
    }
  }, [assistantLoading, selectedNewsModel, selectedArticle, currentStock]);
  const parseNewsLink = useCallback(async (url: string) => {
    const trimmed = url.trim();
    if (!trimmed) return;
    const fallbackArticle: NewsItem = {
      id: `link-${Date.now()}`,
      time: formatBackendTime(new Date().toISOString()),
      title: `外部新闻链接解析：${domainFromUrl(trimmed)}`,
      category: 'macro',
      source: domainFromUrl(trimmed),
      sourceTier: '研究兜底',
      sourceStatus: 'fallback',
      sourceUrl: trimmed,
      severity: 'info',
      sentiment: 'neutral',
      impactScore: 50,
      content: `用户提交外部新闻链接：${trimmed}。当前前端已生成待核验条目，正文抽取需后端抓取服务接入后补全。`,
      aiSummary: buildLinkAnalysis(trimmed, currentStock),
    };
    let parsedArticle = fallbackArticle;
    try {
      const parsed = await fetchApi<NewsUrlParsePayload>('/api/news/parse-url', {
        method: 'POST',
        body: JSON.stringify({ url: trimmed, symbol: currentStock.symbol, stock_name: currentStock.name }),
      });
      const normalized = normalizeBackendNews({
        id: `parsed-url-${Date.now()}`,
        title: parsed.title || fallbackArticle.title,
        content: parsed.content || parsed.summary || fallbackArticle.content,
        summary: parsed.summary,
        source: parsed.source || domainFromUrl(trimmed),
        source_url: parsed.source_url || trimmed,
        published_at: parsed.published_at,
        sentiment: parsed.sentiment,
        importance: parsed.importance,
        event_type: parsed.category,
      }, currentStock);
      if (normalized) {
        parsedArticle = {
          ...normalized,
          sourceStatus: parsed.degraded ? 'degraded' : normalized.sourceStatus,
          sourceUrl: normalized.sourceUrl || trimmed,
          aiSummary: parsed.degraded
            ? `${normalized.aiSummary}\n\n后端链接解析已降级：${parsed.source_status || parsed.error || '来源暂不可用'}。请打开原文核对发布时间、来源和关键数字。`
            : `${normalized.aiSummary}\n\n后端已返回正文/摘要字段，仍建议打开原文核对发布时间、来源和关键数字。`,
        };
      }
    } catch {
      parsedArticle = fallbackArticle;
    }
    setSelectedArticle(parsedArticle);
    setDetailArticle(parsedArticle);
    setIsAiExpanded(true);
    setAssistantMessages((prev) => [
      ...prev,
      {
        id: `news-link-user-${Date.now()}`,
        role: 'user',
        content: `解析新闻链接：${trimmed}`,
        timestamp: new Date().toISOString(),
      },
      {
        id: `news-link-assistant-${Date.now()}`,
        role: 'assistant',
        content: parsedArticle === fallbackArticle ? buildLinkAnalysis(trimmed, currentStock) : `已解析新闻链接并生成详情卡片：${parsedArticle.title}\n\n${parsedArticle.aiSummary}`,
        timestamp: new Date().toISOString(),
      },
    ]);
    if (selectedNewsModel) {
      prefillAssistantInput(`请分析这条新闻链接对 ${currentStock.name} 的影响，并列出需要核验的关键事实`);
    }
  }, [currentStock, selectedNewsModel, prefillAssistantInput]);
  const selectFirstVisibleArticle = () => {
    if (filteredNews[0]) activateArticle(filteredNews[0]);
  };
  const selectedCalendarEvent = CALENDAR_EVENTS[selectedCalendarIndex] ?? CALENDAR_EVENTS[0];

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="p-6 lg:p-8 max-w-[1600px] mx-auto text-neutral-300 flex flex-col h-full overflow-hidden"
    >
      {/* Real-time Ticker */}
      <div className="w-full bg-indigo-500/5 min-h-[38px] border border-indigo-500/10 rounded-xl px-4 flex items-center justify-between mb-6 overflow-hidden relative group">
        <div className="absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-[#050505] to-transparent pointer-events-none z-10" />
        <div className="absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-[#050505] to-transparent pointer-events-none z-10" />
        <div className="flex gap-1.5 items-center bg-indigo-600/20 px-2.5 py-0.5 rounded text-[10px] font-mono tracking-widest text-indigo-400 border border-indigo-500/20 relative z-20 flex-shrink-0 animate-pulse">
          <Flame className="w-3.5 h-3.5" /> HOT
        </div>
        
        <div className="flex-1 overflow-hidden relative mx-6 flex items-center">
          <div className="animate-[marquee_25s_linear_infinite] whitespace-nowrap flex gap-12 text-[11px] font-mono font-medium text-neutral-400">
            <span className="flex items-center gap-2">恒生指数 19,252.12 <span className="text-emerald-500 flex items-center"><ArrowDownRight className="w-3 h-3" /> -0.34%</span></span>
            <span className="flex items-center gap-2">沪深300 3,654.40 <span className="text-rose-500 flex items-center"><ArrowUpRight className="w-3 h-3" /> +0.48%</span></span>
            <span className="flex items-center gap-2">美债10年期 4.425% <span className="text-rose-500 flex items-center"><ArrowUpRight className="w-3 h-3" /> +0.035</span></span>
            <span className="flex items-center gap-2">{currentStock.name} {currentStock.symbol} <span className="text-rose-500 flex items-center"><ArrowUpRight className="w-3 h-3" /> 关注中</span></span>
            <span className="flex items-center gap-2">{currentStock.sector} 主题热度抬升 <span className="text-yellow-400 px-1 rounded bg-yellow-400/10 border border-yellow-400/20 font-sans font-normal text-[9px]">当前标的</span></span>
            <span className="flex items-center gap-2">黄金（盎司） 2,425.80 <span className="text-emerald-500 flex items-center"><ArrowDownRight className="w-3 h-3" /> -0.15%</span></span>
          </div>
        </div>

        <div className="text-[10px] font-mono text-neutral-500 flex-shrink-0 flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" /> 终端已同步
        </div>
      </div>

      {/* Main Grid Layout */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-8 min-h-0 overflow-hidden">
        {/* News Feed - Takes 2 Columns */}
        <div className="lg:col-span-2 flex flex-col min-h-0">
          
          {/* Header Actions */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
            <div>
              <h2 className="text-2xl font-display font-medium text-white flex items-center gap-3">
                <Newspaper className="w-6 h-6 text-indigo-400" />
                数据源终端聚合
              </h2>
              <p className="text-xs text-neutral-500 mt-1.5 font-mono">
                当前标的：{formatStockLabel(currentStock)} · 覆盖 {sourceSummary.sources.length} 个来源 / {sourceSummary.tiers.length} 类源
              </p>
            </div>

            {/* Simple Search */}
            <div className="relative w-full md:w-64 max-w-sm">
              <input
                type="text"
                data-testid="news-search-input"
                placeholder="搜索重要标题或要素..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    selectFirstVisibleArticle();
                  }
                }}
                className="w-full bg-white/[0.02] border border-white/5 focus:border-indigo-500/50 focus:outline-none rounded-xl py-2 pl-9 pr-4 text-xs text-neutral-200 placeholder:text-neutral-500 transition-all font-sans"
              />
              <Search className="absolute left-3 top-2.5 w-4 h-4 text-neutral-500" />
            </div>
          </div>

          <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.015] p-3 flex-shrink-0">
            <div className="mb-2 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-2 text-xs font-medium text-neutral-200">
                <Globe className="h-4 w-4 text-indigo-400" />
                信源概览
                <span className="flex items-center gap-2 text-[10px] text-neutral-500">
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', backendStateDotClass(backendSourceState.newsStatus))} />
                    资讯源 {backendStateLabel(backendSourceState.newsStatus)}
                  </span>
                  <span className="text-neutral-700">·</span>
                  <span className="inline-flex items-center gap-1">
                    <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', backendStateDotClass(backendSourceState.announcementStatus))} />
                    公告源 {backendStateLabel(backendSourceState.announcementStatus)}
                  </span>
                </span>
              </div>
              <div className="flex items-center gap-2">
                <p className="hidden text-[10px] text-neutral-500 sm:block">
                  {sourceStatus === 'loading' ? '同步中' : sourceStatus === 'real' ? `真实源 ${sourceSummary.realCount} 条` : '内置多源聚合'} · 官方 {sourceSummary.officialCount} 条 · 主流/终端 {sourceSummary.mediaCount}/{sourceSummary.terminalCount} 条
                </p>
                <button
                  type="button"
                  data-testid="news-source-overview-toggle"
                  onClick={() => setIsSourceOverviewExpanded((prev) => !prev)}
                  className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-300 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
                >
                  {isSourceOverviewExpanded ? '收起概览' : '展开概览'}
                  {isSourceOverviewExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>
              </div>
            </div>

            {!isSourceOverviewExpanded && (
              <button
                type="button"
                data-testid="news-source-overview-summary"
                onClick={() => setIsSourceOverviewExpanded(true)}
                className="mt-2 flex w-full items-center justify-between rounded-xl border border-white/5 bg-black/20 px-3 py-2 text-left transition-colors hover:border-indigo-400/30 hover:bg-indigo-500/[0.04]"
              >
                <span className="truncate text-[11px] text-neutral-300">
                  {sourceStatus === 'loading' ? '同步中' : sourceStatus === 'real' ? `真实源 ${sourceSummary.realCount} 条` : '内置多源聚合'} · 官方披露 {sourceSummary.officialCount} 条 · 主流/终端 {sourceSummary.mediaCount}/{sourceSummary.terminalCount} 条 · {backendSourceState.degraded ? '部分数据源暂不可用，已自动切换备用源' : '数据源正常'}
                </span>
                <ChevronDown className="ml-2 h-3.5 w-3.5 flex-shrink-0 text-neutral-500" />
              </button>
            )}

            {isSourceOverviewExpanded && (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
                  {[
                    ['源状态', sourceStatus === 'loading' ? '同步中' : sourceStatus === 'real' ? `真实源 ${sourceSummary.realCount} 条` : '内置多源聚合'],
                    ['官方披露', `${sourceSummary.officialCount} 条`],
                    ['主流/终端', `${sourceSummary.mediaCount} / ${sourceSummary.terminalCount} 条`],
                    ['数据源', backendSourceState.degraded ? '部分源暂不可用，已切换备用源' : '全部正常'],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2">
                      <p className="text-[9px] font-mono uppercase tracking-widest text-neutral-600">{label}</p>
                      <p className="mt-1 truncate text-[11px] font-medium text-neutral-300">{value}</p>
                    </div>
                  ))}
                </div>

                <div className="rounded-xl border border-white/5 bg-black/10 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-neutral-300">新闻来源矩阵</span>
                    <div className="flex items-center gap-2">
                      <p className="text-[10px] text-neutral-500">
                        后端接入 {backendSourceState.sources.length || 0} 个源 · 内置备用 {backendSourceState.fallbackSources.length || SOURCE_MATRIX.length} 组
                      </p>
                      <button
                        type="button"
                        data-testid="news-source-matrix-toggle"
                        onClick={() => setIsSourceMatrixExpanded((prev) => !prev)}
                        className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-300 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
                      >
                        {isSourceMatrixExpanded ? '收起来源' : '展开来源'}
                        {isSourceMatrixExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      </button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
                    {sourceSummary.tierCounts.map((entry) => {
                      const isTierSelected = selectedSourceTier === entry.tier && !selectedSource;
                      return (
                      <button
                        key={entry.tier}
                        type="button"
                        data-testid={`news-tier-${SOURCE_TIER_IDS[entry.tier]}`}
                        onClick={() => {
                          setSelectedSourceTier((prev) => (prev === entry.tier && !selectedSource ? 'all' : entry.tier));
                          setSelectedSource('');
                          setSelectedCategory('all');
                          setSelectedArticle(null);
                        }}
                        className={cn(
                          "rounded-xl border bg-black/20 text-left transition-all hover:border-indigo-400/40 hover:bg-indigo-500/[0.04] focus:outline-none focus:ring-2 focus:ring-indigo-500/40",
                          isSourceMatrixExpanded ? "p-3" : "px-3 py-2",
                          isTierSelected ? "border-indigo-400/50 bg-indigo-500/[0.07]" : "border-white/5"
                        )}
                        aria-pressed={isTierSelected}
                      >
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <span className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] font-mono",
                            entry.tier === '官方披露' ? "bg-emerald-500/10 text-emerald-300" :
                            entry.tier === '数据终端' ? "bg-indigo-500/10 text-indigo-300" :
                            entry.tier === '主流媒体' ? "bg-sky-500/10 text-sky-300" :
                            "bg-amber-500/10 text-amber-300"
                          )}>
                            {entry.tier}
                          </span>
                          <span className="text-[10px] font-mono text-neutral-500">{entry.count} 条</span>
                        </div>
                        {isSourceMatrixExpanded && (
                          <>
                            <p className="mb-2 line-clamp-2 text-[10px] leading-relaxed text-neutral-500">{entry.note}</p>
                            <div className="flex flex-wrap gap-1">
                              {(entry.activeSources.length ? entry.activeSources : entry.sources).slice(0, 4).map((source) => (
                                <span key={source} className={cn(
                                  "rounded border px-1.5 py-0.5 text-[9px] transition-colors",
                                  entry.activeSources.includes(source)
                                    ? "border-white/15 bg-white/5 text-neutral-300"
                                    : "border-white/5 bg-white/[0.02] text-neutral-600"
                                )}>
                                  {source}
                                </span>
                              ))}
                            </div>
                          </>
                        )}
                      </button>
                    );
                    })}
                  </div>

                  {isSourceMatrixExpanded && (
                    <div className="mt-3 flex max-h-24 flex-wrap gap-1.5 overflow-y-auto border-t border-white/5 pt-3 custom-scrollbar">
                      {visibleSourceButtons.map((source) => (
                        <button
                          key={source}
                          type="button"
                          data-testid={`news-source-primary-${sourceSlug(source)}`}
                          data-source-name={source}
                          onClick={() => {
                            const nextSource = selectedSource === source ? '' : source;
                            setSelectedSource(nextSource);
                            setSelectedSourceTier(nextSource ? (sourceSummary.sourceTierBySource.get(source) ?? sourceTier(source)) : 'all');
                            setSelectedCategory('all');
                            setSelectedArticle(null);
                          }}
                          className={cn(
                            "rounded-md border px-2 py-1 text-[10px] transition-all hover:border-emerald-300/50 hover:bg-emerald-500/10 focus:outline-none focus:ring-2 focus:ring-emerald-500/30",
                            selectedSource === source
                              ? "border-emerald-300/60 bg-emerald-500/15 text-emerald-100"
                              : "border-emerald-500/15 bg-emerald-500/5 text-emerald-300"
                          )}
                          aria-pressed={selectedSource === source}
                        >
                          {source}
                        </button>
                      ))}
                      {backendSourceState.fallbackSources.filter((source) => !visibleSourceButtons.includes(source)).slice(0, 8).map((source) => (
                        <button
                          key={source}
                          type="button"
                          data-testid={`news-source-fallback-${sourceSlug(source)}`}
                          data-source-name={source}
                          onClick={() => {
                            const matchedTier = sourceSummary.sourceTierBySource.get(source);
                            const nextSource = matchedTier && selectedSource !== source ? source : '';
                            setSelectedSource(nextSource);
                            setSelectedSourceTier(nextSource && matchedTier ? matchedTier : fallbackSourceTier(source));
                            setSelectedCategory('all');
                            setSelectedArticle(null);
                          }}
                          className={cn(
                            "rounded-md border px-2 py-1 text-[10px] transition-all hover:border-white/25 hover:bg-white/[0.06] focus:outline-none focus:ring-2 focus:ring-white/20",
                            selectedSource === source
                              ? "border-white/35 bg-white/[0.08] text-neutral-100"
                              : "border-white/10 bg-white/[0.03] text-neutral-400"
                          )}
                          aria-pressed={selectedSource === source}
                        >
                          {source}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
            {activeFilters.length > 0 && (
              <div
                data-testid="news-active-filters"
                className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/5 pt-3"
              >
                <span className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">当前过滤</span>
                {activeFilters.map((filter) => (
                  <span key={filter} className="rounded-md border border-indigo-500/20 bg-indigo-500/10 px-2 py-1 text-[10px] text-indigo-200">
                    {filter}
                  </span>
                ))}
                <button
                  type="button"
                  data-testid="news-clear-filters"
                  onClick={clearNewsFilters}
                  className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-300 transition-colors hover:border-white/25 hover:bg-white/[0.06]"
                >
                  清除过滤
                </button>
              </div>
            )}
          </div>

          {/* Categories Pill Scroller */}
          <div className="flex gap-2 overflow-x-auto pb-4 custom-scrollbar flex-shrink-0">
            {filterCategories.map(cat => (
              <button
                key={cat.id}
                type="button"
                data-testid={`news-category-${cat.id}`}
                onClick={() => {
                  setSelectedCategory((prev) => (prev === cat.id && cat.id !== 'all' ? 'all' : cat.id));
                  setSelectedSourceTier('all');
                  setSelectedSource('');
                  setSelectedArticle(null);
                }}
                className={cn(
                  "px-4 py-1.5 rounded-xl text-xs font-medium border transition-all flex items-center gap-2 whitespace-nowrap cursor-pointer",
                  selectedCategory === cat.id 
                    ? "bg-indigo-600 border-indigo-500 text-white shadow-[0_0_15px_rgba(99,102,241,0.3)]" 
                    : "bg-white/[0.02] border-white/5 text-neutral-400 hover:text-neutral-200 hover:bg-white/5"
                )}
              >
                {cat.label}
                <span className={cn(
                  "px-1.5 py-0.5 rounded-md font-mono text-[9px] font-bold",
                  selectedCategory === cat.id ? "bg-indigo-700 text-indigo-100" : "bg-white/5 text-neutral-500"
                )}>
                  {cat.count}
                </span>
              </button>
            ))}
          </div>

          {/* Main Feed Container */}
          <NewsFeedList
            items={filteredNews}
            searchQuery={searchQuery}
            selectedId={selectedArticle?.id}
            onActivate={activateArticle}
            onOpenDetail={openArticleDetail}
            onOpenSource={openArticleSource}
            onAsk={askFromFeed}
            onClearFilters={clearNewsFilters}
          />
        </div>

        {/* Dynamic Detail Panel / Calendar Right Column */}
        <div className="flex flex-col gap-6 h-full min-h-0 overflow-hidden">
          
          {/* Main Top Drawer: AI News Smart Analyzer */}
          <div className={cn(
            "bg-white/[0.02] border border-white/10 rounded-2xl p-5 flex flex-col relative overflow-hidden transition-all duration-300 shadow-lg",
            isAiExpanded ? "flex-[3] min-h-[220px]" : "h-[64px] flex-shrink-0"
          )}>
            <div className="absolute top-0 left-0 right-0 h-32 bg-indigo-500/10 blur-[40px] pointer-events-none" />
            
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-white/5 select-none relative z-10 flex-shrink-0">
              <div 
                className="flex gap-2.5 items-center cursor-pointer group" 
                onClick={() => {
                  setIsAiExpanded(!isAiExpanded);
                  if (!isAiExpanded) setIsCalendarExpanded(true);
                }}
              >
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center flex-shrink-0 group-hover:bg-indigo-500/20 transition-all">
                  <Sparkles className="w-4.5 h-4.5 text-indigo-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-neutral-200 group-hover:text-white transition-colors">新闻 AI 助手</h3>
                  <p className="text-[9px] font-mono uppercase text-neutral-500 tracking-wider">NEWS COPILOT · LINK PARSER</p>
                </div>
              </div>
              <button 
                onClick={() => {
                  setIsAiExpanded(!isAiExpanded);
                  if (!isAiExpanded) setIsCalendarExpanded(true);
                }}
                className="w-7 h-7 rounded-lg hover:bg-white/5 border border-transparent hover:border-white/10 flex items-center justify-center text-neutral-400 hover:text-neutral-200 transition-all"
                title={isAiExpanded ? "折叠面板" : "展开面板"}
              >
                {isAiExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            </div>

            <div className={cn(
              "flex-1 overflow-y-auto custom-scrollbar relative z-10 text-xs text-neutral-400 leading-relaxed pr-1 transition-all duration-300 min-h-0",
              !isAiExpanded && "opacity-0 pointer-events-none scale-95"
            )}>
              <div className="space-y-4">
                <NewsLinkParserBox onParse={parseNewsLink} />

                <AnimatePresence mode="wait">
                  {selectedArticle ? (
                    <motion.div 
                      key={selectedArticle.id}
                      initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}
                      className="space-y-4"
                    >
                    <div className="bg-black/30 border border-white/5 rounded-xl p-3">
                      <span className="text-[10px] uppercase font-mono text-neutral-500 block mb-1">选定信源</span>
                      <p data-testid="news-detail-title" className="text-xs text-neutral-200 font-medium">{selectedArticle.title}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-mono text-neutral-500">
                        <span>{selectedArticle.time} · {selectedArticle.source}</span>
                        <button
                          type="button"
                          data-testid="news-detail-open-selected"
                          onClick={() => openArticleDetail(selectedArticle)}
                          className="inline-flex items-center gap-1 rounded border border-indigo-500/20 bg-indigo-500/10 px-2 py-1 text-indigo-100 transition-colors hover:bg-indigo-500/20"
                        >
                          查看详情 <FileText className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          data-testid="news-source-open-selected"
                          onClick={() => openArticleSource(selectedArticle)}
                          className="inline-flex items-center gap-1 rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-neutral-300 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
                        >
                          {sourceActionLabel(selectedArticle)} <ArrowUpRight className="h-3 w-3" />
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                      {[
                        ['来源层级', selectedArticle.sourceTier],
                        ['影响分', `${selectedArticle.impactScore}%`],
                        ['情绪方向', selectedArticle.sentiment === 'bullish' ? '利好' : selectedArticle.sentiment === 'bearish' ? '偏空' : '中性'],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-lg border border-white/5 bg-black/20 p-2">
                          <span className="block text-[9px] font-mono text-neutral-500">{label}</span>
                          <span className="mt-1 block truncate text-[11px] font-medium text-neutral-200">{value}</span>
                        </div>
                      ))}
                    </div>

                    <div className="space-y-2">
                      <h4 className="font-medium text-neutral-300 flex items-center gap-1.5">
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> 信能评估与关联变量
                      </h4>
                      <p className="text-xs text-neutral-400">
                        当前按来源层级、后端字段和影响分进行投研预筛。{selectedArticle.sourceTier === '官方披露' ? '官方披露优先进入证据链。' : '非公告信源需要与公告、行情和资金数据交叉核验。'}
                      </p>
                    </div>

                    <div className="space-y-2 bg-indigo-500/5 border border-indigo-500/10 rounded-xl p-4">
                      <h4 className="font-semibold text-neutral-200 flex items-center gap-1.5 text-xs text-indigo-300">
                        <Sparkles className="w-3.5 h-3.5" /> AI 量化结论与逻辑归因
                      </h4>
                      <p className="text-xs leading-relaxed text-indigo-100 italic">
                        "{selectedArticle.aiSummary}"
                      </p>
                    </div>

                    <div className="border-t border-white/5 pt-3 grid grid-cols-2 gap-3 text-center">
                      <div className="p-2 bg-black/20 rounded-lg">
                        <span className="text-[10px] font-mono text-neutral-500 block">建议动作</span>
                        <span className="text-xs font-mono font-medium text-rose-400">加入证据链</span>
                      </div>
                      <div className="p-2 bg-black/20 rounded-lg">
                        <span className="text-[10px] font-mono text-neutral-500 block">复核重点</span>
                        <span className="text-xs font-mono font-medium text-indigo-400">{selectedArticle.category === 'funds' ? '资金持续性' : selectedArticle.category === 'risk' ? '公告确认' : '多源一致性'}</span>
                      </div>
                    </div>
                    </motion.div>
                  ) : (
                    <motion.div 
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                      className="flex flex-col items-center justify-center rounded-xl border border-white/5 bg-black/20 p-6 text-center text-neutral-500 font-sans gap-2"
                    >
                      <Gauge className="w-8 h-8 text-neutral-600 animate-pulse" />
                      <p className="text-[11px]">请在左侧选择新闻，或粘贴新闻链接生成待核验卡片。</p>
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="rounded-xl border border-violet-500/10 bg-violet-500/[0.04] p-3">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-[11px] font-medium text-violet-200">
                      <MessageCircle className="h-3.5 w-3.5" />
                      咨询这条新闻
                    </div>
                    <button
                      type="button"
                      onClick={onOpenModelSettings}
                      className="inline-flex items-center gap-1 rounded border border-white/10 bg-white/[0.03] px-2 py-1 text-[9px] text-neutral-400 transition-colors hover:border-violet-400/40 hover:text-violet-100"
                    >
                      <Settings2 className="h-3 w-3" />
                      模型设置
                    </button>
                  </div>
                  <div className="mb-3 flex items-center gap-2">
                    <ThemedSelect
                      data-testid="news-assistant-model-select"
                      value={selectedNewsModel?.key || ''}
                      onChange={setSelectedNewsModelKey}
                      disabled={!newsModels.length || assistantLoading}
                      className="min-w-0 flex-1"
                      buttonClassName="h-8 rounded-lg bg-black/35 px-2 text-[10px] focus-visible:border-violet-400/50"
                      menuClassName="text-xs"
                      options={newsModels.length ? newsModels.map((model) => ({
                        value: model.key,
                        label: formatModelOption(model),
                      })) : [{ value: '', label: '请先在系统设置中添加模型', disabled: true }]}
                    />
                  </div>
                  <div className="mb-3 max-h-44 space-y-2 overflow-y-auto pr-1 custom-scrollbar">
                    {assistantMessages.map((message) => (
                      <div
                        key={message.id}
                        className={cn(
                          "rounded-lg border px-3 py-2 text-[11px] leading-relaxed whitespace-pre-line",
                          message.role === 'user'
                            ? "ml-6 border-indigo-500/20 bg-indigo-500/10 text-indigo-50"
                            : "mr-6 border-white/5 bg-black/25 text-neutral-300"
                        )}
                      >
                        {message.content}
                      </div>
                    ))}
                  </div>
                  <NewsAssistantComposer
                    disabled={assistantLoading}
                    placeholder={selectedArticle ? "问：这条新闻是利好还是风险？" : "先选一条新闻再提问..."}
                    prefill={assistantPrefill}
                    onSend={askAboutArticle}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Card: Economic Calendar (财经日历) */}
          <div className={cn(
            "bg-white/[0.02] border border-white/10 rounded-2xl p-5 flex flex-col shadow-lg transition-all duration-300 overflow-hidden relative",
            isCalendarExpanded ? "flex-[2] min-h-[180px]" : "h-[64px] flex-shrink-0"
          )}>
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-white/5 select-none relative z-10 flex-shrink-0">
              <div 
                className="flex gap-2.5 items-center cursor-pointer group" 
                onClick={() => {
                  setIsCalendarExpanded(!isCalendarExpanded);
                  if (!isCalendarExpanded) setIsAiExpanded(true);
                }}
              >
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0 group-hover:bg-emerald-500/20 transition-all">
                  <Calendar className="w-4.5 h-4.5 text-emerald-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-neutral-200 group-hover:text-white transition-colors">海外财经及指标前瞻</h3>
                  <p className="text-[9px] font-mono uppercase text-neutral-500 tracking-wider">Macro Indicator Calendar</p>
                </div>
              </div>
              <button 
                onClick={() => {
                  setIsCalendarExpanded(!isCalendarExpanded);
                  if (!isCalendarExpanded) setIsAiExpanded(true);
                }}
                className="w-7 h-7 rounded-lg hover:bg-white/5 border border-transparent hover:border-white/10 flex items-center justify-center text-neutral-400 hover:text-neutral-200 transition-all"
                title={isCalendarExpanded ? "折叠面板" : "展开面板"}
              >
                {isCalendarExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            </div>
            
            <div className={cn(
              "flex-1 overflow-y-auto custom-scrollbar space-y-3 pr-1 transition-all duration-300 min-h-0",
              !isCalendarExpanded && "opacity-0 pointer-events-none scale-95"
            )}>
              {CALENDAR_EVENTS.map((evt, i) => {
                const isSelected = selectedCalendarIndex === i;
                return (
                <button
                  key={evt.title}
                  type="button"
                  data-testid={`macro-calendar-event-${i}`}
                  onClick={() => setSelectedCalendarIndex(i)}
                  className={cn(
                    "bg-black/20 border p-2 px-3 rounded-lg flex flex-col text-left transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500/30",
                    isSelected ? "border-emerald-400/40 bg-emerald-500/[0.06]" : "border-white/5 hover:bg-neutral-900/40"
                  )}
                  aria-pressed={isSelected}
                >
                  <div className="flex justify-between items-center mb-1 flex-wrap gap-2 text-[10px]">
                    <span className="font-mono text-neutral-500 font-medium">{evt.time}</span>
                    <span className="text-indigo-400 tracking-wider font-mono">{evt.importance}</span>
                    <span className={cn(
                      "px-1 py-0.5 rounded text-[8px] font-sans font-medium uppercase border",
                      evt.status === '已公布' 
                        ? 'bg-neutral-800 border-white/5 text-neutral-400' 
                        : 'bg-emerald-950/20 border-emerald-500/20 text-emerald-450'
                    )}>{evt.status}</span>
                  </div>
                  <h4 className="text-xs text-neutral-200 font-medium line-clamp-1">{evt.title}</h4>
                  <div className="flex justify-between items-center text-[10px] mt-1 text-neutral-500 leading-none">
                    <span className="text-neutral-500">{evt.preview}</span>
                    <span className="text-indigo-400 font-medium text-[9px]">{evt.impact}</span>
                  </div>
                </button>
              );
              })}
              <div
                data-testid="macro-calendar-detail"
                className="rounded-xl border border-emerald-500/10 bg-emerald-500/[0.04] p-3 text-xs"
              >
                <div className="mb-2 flex items-center gap-2 text-emerald-300">
                  <TrendingUp className="h-3.5 w-3.5" />
                  <span className="font-medium">{selectedCalendarEvent.scope}</span>
                </div>
                <p className="leading-relaxed text-neutral-300">{selectedCalendarEvent.readthrough}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selectedCalendarEvent.watch.map((item) => (
                    <span key={item} className="rounded-md border border-white/10 bg-black/20 px-2 py-1 text-[10px] text-neutral-400">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <AnimatePresence>
        {detailArticle && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setDetailArticle(null)}
          >
            <motion.div
              role="dialog"
              aria-modal="true"
              data-testid="news-detail-modal"
              className="flex max-h-[86vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#08090f] shadow-2xl"
              initial={{ opacity: 0, y: 18, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 18, scale: 0.98 }}
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-4 border-b border-white/10 p-5">
                <div className="min-w-0">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className="rounded-md border border-indigo-500/20 bg-indigo-500/10 px-2 py-1 text-[10px] font-mono text-indigo-200">
                      {categoryLabel(detailArticle.category)}
                    </span>
                    <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] font-mono text-neutral-400">
                      {detailArticle.time} · {detailArticle.source}
                    </span>
                    <span className={cn(
                      "rounded-md border px-2 py-1 text-[10px] font-mono",
                      detailArticle.sourceTier === '官方披露' ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" :
                      detailArticle.sourceTier === '数据终端' ? "border-indigo-500/20 bg-indigo-500/10 text-indigo-300" :
                      detailArticle.sourceTier === '主流媒体' ? "border-sky-500/20 bg-sky-500/10 text-sky-300" :
                      detailArticle.sourceTier === '舆情/另类' ? "border-amber-500/20 bg-amber-500/10 text-amber-300" :
                      "border-white/10 bg-white/5 text-neutral-400"
                    )}>
                      {detailArticle.sourceTier}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold leading-relaxed text-neutral-100">
                    {detailArticle.title}
                  </h3>
                </div>
                <button
                  type="button"
                  data-testid="news-detail-close"
                  onClick={() => setDetailArticle(null)}
                  className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-neutral-400 transition-colors hover:bg-white/[0.08] hover:text-white"
                  title="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-5 custom-scrollbar">
                <div className="mb-4 grid grid-cols-3 gap-2">
                  {[
                    ['影响分', `${detailArticle.impactScore}%`],
                    ['情绪方向', sentimentLabel(detailArticle.sentiment)],
                    ['状态', detailArticle.sourceStatus === 'real' ? '实时入库' : detailArticle.sourceStatus === 'degraded' ? '降级源' : '兜底/待核验'],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                      <p className="text-[9px] font-mono uppercase tracking-widest text-neutral-600">{label}</p>
                      <p className="mt-1 truncate text-[12px] font-medium text-neutral-200">{value}</p>
                    </div>
                  ))}
                </div>

                <section className="mb-4 rounded-xl border border-white/5 bg-black/20 p-4">
                  <h4 className="mb-2 flex items-center gap-2 text-sm font-medium text-neutral-200">
                    <FileText className="h-4 w-4 text-indigo-300" />
                    新闻正文 / 摘要
                  </h4>
                  <p className="whitespace-pre-line text-sm leading-7 text-neutral-300">
                    {detailArticle.content}
                  </p>
                </section>

                <section className="rounded-xl border border-indigo-500/10 bg-indigo-500/[0.04] p-4">
                  <h4 className="mb-2 flex items-center gap-2 text-sm font-medium text-indigo-200">
                    <Sparkles className="h-4 w-4" />
                    AI 归因提示
                  </h4>
                  <p className="whitespace-pre-line text-sm leading-7 text-indigo-50">
                    {detailArticle.aiSummary}
                  </p>
                </section>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 p-4">
                <p className="text-[11px] text-neutral-500">
                  详情内容来自当前聚合结果；用于投研辅助，关键结论需回到原文和公告核验。
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedArticle(detailArticle);
                      prefillAssistantInput(`请结合原文详情分析这条新闻对 ${currentStock.name} 的影响`);
                      setDetailArticle(null);
                      setIsAiExpanded(true);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-[12px] text-violet-100 transition-colors hover:bg-violet-500/20"
                  >
                    <MessageCircle className="h-3.5 w-3.5" />
                    咨询这条
                  </button>
                  <button
                    type="button"
                    data-testid="news-detail-source-open"
                    onClick={() => openArticleSource(detailArticle)}
                    className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[12px] text-emerald-100 transition-colors hover:bg-emerald-500/20"
                  >
                    {sourceActionLabel(detailArticle)} <ArrowUpRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
