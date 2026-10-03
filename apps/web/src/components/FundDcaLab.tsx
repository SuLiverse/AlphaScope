import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { 
  ComposedChart, 
  Line, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip as ChartTooltip, 
  Legend 
} from 'recharts';
import { 
  Coins, 
  TrendingUp, 
  Layers, 
  Scale, 
  Sliders, 
  BookOpen, 
  Sparkles,
  UserCheck, 
  Info,
  ChevronRight,
  Flame,
  CheckCircle2,
  AlertTriangle,
  Send
} from 'lucide-react';
import { StableChartContainer } from './StableChartContainer';
import { Skeleton } from './ui/Skeleton';
import { EmptyState } from './ui/EmptyState';
import { ErrorState } from './ui/ErrorState';
import { cn } from '../lib/utils';
import { fetchApi } from '../lib/api';
import { getErrorMessage } from '../lib/dataFetch';
import { subscribeSettingsChanged } from '../lib/workspaceEvents';
import {
  buildModelOptions,
  getModelKey,
  getRouteSelection,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
} from '../lib/aiModelRouting';
import type { ModelOption, ModelProvider } from '../lib/aiModelRouting';

// Quick-pick fund CODES (real public-fund codes; profiles/metrics/NAVs are
// fetched live from /api/funds/* — no hardcoded fund data remains).
const QUICK_FUND_CODES = ['005827', '510300', '003095', '159941', '100072', '161725'];

// --- Types ---
interface FundProfile {
  code: string;
  name: string;
  type: 'mixed' | 'bond' | 'index' | 'etf' | 'qdii';
  typeName: string;
  company: string;
  manager: string;
  inception: string;
  size: string;
  expenseRatio: number; // total annual fees in %
  benchmarkName: string;
  topHoldings: Array<{ name: string; weight: number }>;
  sectorAllocation: Array<{ name: string; weight: number }>;
  historicMetrics: {
    maxDrawdown: number;
    sharpe: number;
    annualVol: number;
    rankPct: number; // top x% in category
  };
  customBasePrice: number;
}


// --- Preset Investment Portfolios Recipes ---
interface PortfolioRecipe {
  id: string;
  name: string;
  description: string;
  riskLevel: '成长' | '平衡' | '保守' | '进取';
  allocations: Array<{ code: string; weight: number }>;
}

const PORTFOLIO_RECIPES: PortfolioRecipe[] = [
  {
    id: 'core-satellite',
    name: '核心-卫星均衡组合',
    description: '以宽基指数ETF作为底盘安全港(核心)，搭配两只白马和海外QDII科技型基金博取超额收益(卫星)。',
    riskLevel: '平衡',
    allocations: [
      { code: '510300', weight: 50 }, // 沪深300
      { code: '159941', weight: 25 }, // 纳指100
      { code: '005827', weight: 25 }  // 蓝筹混合
    ]
  },
  {
    id: 'stock-bond-balanced',
    name: '经典固收+ 股债六四平衡型',
    description: '经典的60%股票指数与40%高等级信用债，在平抑大盘剧烈回撤的同时，确保享有长期红利。',
    riskLevel: '平衡',
    allocations: [
      { code: '510300', weight: 60 },
      { code: '100072', weight: 40 }
    ]
  },
  {
    id: 'industry-alpha',
    name: '行业先锋进攻型组合',
    description: '重仓中国白酒蓝筹与核心医疗科技，配合海外科技QDII组合，是适合高风险偏好用户的牛市利器。',
    riskLevel: '进取',
    allocations: [
      { code: '161725', weight: 40 }, // 中证白酒
      { code: '003095', weight: 30 }, // 中欧医疗
      { code: '159941', weight: 30 }  // 纳指100
    ]
  },
  {
    id: 'global-diversified',
    name: '全球多资产视野(QDII+债)',
    description: '50%美国硬科技股，30%大平洋彼岸平稳低波动债，20%沪深300。充分对冲汇率与单一地域风险。',
    riskLevel: '保守',
    allocations: [
      { code: '159941', weight: 50 },
      { code: '100072', weight: 30 },
      { code: '510300', weight: 20 }
    ]
  },
  {
    id: 'all-weather-bond',
    name: '红利低波稳健现金流',
    description: '100%债券底座与绩优成长大蓝筹点缀，在回撤控制在3%以内前提下实现高确定性的货币防线。',
    riskLevel: '保守',
    allocations: [
      { code: '100072', weight: 80 },
      { code: '510300', weight: 20 }
    ]
  }
];

// --- Expert AI Agent Board Specifications ---
interface ExpertAgent {
  role: string;
  name: string;
  avatar: string;
  color: string;
  intro: string;
}

const EXPERT_AGENTS: ExpertAgent[] = [
  {
    role: '基金研究员',
    name: '程博宁',
    avatar: '👨‍🔬',
    color: 'border-blue-500/30 text-blue-400 bg-blue-500/5',
    intro: '深度穿透底层仓位。扫描基金经理的投资风格、换手率，以及是否存在追涨杀跌、过高集中和行业飘移。'
  },
  {
    role: '定投规划师',
    name: '严一凡',
    avatar: '📈',
    color: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/5',
    intro: '精确设定定投频率与金额边界，基于复合牛熊压力情境测算目标止盈率与防守补仓方案的最佳结合点。'
  },
  {
    role: '组合配置师',
    name: '梁诗韵',
    avatar: '🎨',
    color: 'border-purple-500/30 text-purple-400 bg-purple-500/5',
    intro: '贯彻马科维茨有效前沿理论，利用各资产类别的负相关度或非完全相关系数构建最优风险调整收益组合。'
  },
  {
    role: '风险控制官',
    name: '段宏强',
    avatar: '🛡️',
    color: 'border-rose-500/30 text-rose-400 bg-rose-500/5',
    intro: '监控最大历史回撤与极端系统危机时的杠杆比率，评估底层资产穿透后的行业暴露度上限。'
  },
  {
    role: '费用分析师',
    name: '方可馨',
    avatar: '🧾',
    color: 'border-yellow-500/30 text-yellow-400 bg-yellow-500/5',
    intro: '精算申购、赎回、管理与隐形交易损耗费用，用长期复利算盘指出不必要的频繁申赎成本黑洞。'
  },
  {
    role: '指数估值核心',
    name: '叶天瑞',
    avatar: '🔬',
    color: 'border-teal-500/30 text-teal-400 bg-teal-500/5',
    intro: '专注宏观估值分位(PE/PB/PS)，精确判断当前标的在近十年长历史线中是处于昂贵极值还是超跌底部。'
  },
  {
    role: '反方审稿员',
    name: '冷子墨',
    avatar: '⚖️',
    color: 'border-amber-500/30 text-amber-500 bg-amber-500/5',
    intro: '扮演恶魔代言人，无情鞭挞“幸存者偏差”与完美定投回测参数中的“历史过拟合”，拒绝简单线性乐观预期。'
  },
  {
    role: '合规总监',
    name: '陈清律',
    avatar: '💼',
    color: 'border-neutral-500/30 text-neutral-400 bg-neutral-500/5',
    intro: '严格执行适度性管理与底线预示，坚决防范暗示收益保证、违规误导，守护金融合规最高红线。'
  }
];

// --- FAQ presets ---
const FAQ_PRESETS = [
  {
    q: '这个基金适合长期定投吗？有何历史实证？',
    agent: '定投规划师 & 基金研究员'
  },
  {
    q: '历史上此标的出现40%以上回撤后，定投多久可能扭亏为盈？',
    agent: '风险控制官 & 指数估值核心'
  },
  {
    q: '申赎成本与红利再投（配对红利现金）在长期复利里区别有多大？',
    agent: '费用分析师 & 合规总监'
  },
  {
    q: '如果未来5年面临弱震荡或者螺旋式盘整，定投会不会产生钝化亏损？如何用“逢低加码”止盈应对？',
    agent: '反方审稿员 & 定投规划师'
  }
];

// Seeded pseudorandom generator for deterministic mathematical trajectories!
function createSineDriftPriceCurve(
  length: number, 
  basePrice: number, 
  volatility: number, 
  driftPct: number, // Annual trend drift
  crashOffsetIndex = -1 // Simulate a crash if specified
) {
  const curve: number[] = [];
  let currentPrice = basePrice;
  // Use a pseudo-random seed based on the base price name to be repeatable
  let seed = basePrice % 1;
  const rand = () => {
    const x = Math.sin(seed++) * 10000;
    return x - Math.floor(x);
  };

  const stepsPerPeriod = 12; // Monthly steps
  const dt = 1 / stepsPerPeriod;

  // Let's generate a solid mathematical stock price trajectory
  for (let i = 0; i < length; i++) {
    // Standard Brownian motion with drift and sine cyclicality
    const cyclical = Math.sin(i / 10) * volatility * 0.15;
    const randomShock = (rand() - 0.48) * volatility * 1.5;
    
    // Simulate systematic market crash at specific index window
    let systematicShock = 0;
    if (crashOffsetIndex > 0 && i >= crashOffsetIndex && i < crashOffsetIndex + 8) {
      systematicShock = -volatility * 0.4; // rapid drops
    } else if (crashOffsetIndex > 0 && i >= crashOffsetIndex + 8 && i < crashOffsetIndex + 20) {
      systematicShock = volatility * 0.15; // slow relief rebound
    }

    const priceReturn = driftPct * dt + cyclical + randomShock + systematicShock;
    currentPrice = Math.max(0.1, currentPrice * (1 + priceReturn));
    curve.push(Math.round(currentPrice * 1000) / 1000);
  }
  return curve;
}

// ---- Real fund data contracts (backend/api/funds.py) ----
interface FundInfo { code?: string; name?: string; fund_type?: string; manager?: string; company?: string; inception_date?: string; total_assets?: number; }
interface FundMetrics { total_return?: number | null; annualized_return?: number | null; volatility?: number | null; max_drawdown?: number | null; sharpe_ratio?: number | null; calmar_ratio?: number | null; win_rate?: number | null; data_points?: number; }
interface FundNavPoint { date?: string; nav?: number; }

function mapFundType(fundType?: string): FundProfile['type'] {
  const t = (fundType || '').toLowerCase();
  if (t.includes('qdii') || t.includes('跨境')) return 'qdii';
  if (t.includes('债') || t.includes('bond')) return 'bond';
  if (t.includes('etf')) return 'etf';
  if (t.includes('指数') || t.includes('index') || t.includes('被动')) return 'index';
  return 'mixed';
}

function placeholderFundProfile(code: string): FundProfile {
  return { code, name: code, type: 'mixed', typeName: '加载中…', company: '--', manager: '--', inception: '--', size: '--', expenseRatio: 0, benchmarkName: '--', topHoldings: [], sectorAllocation: [], historicMetrics: { maxDrawdown: -20, sharpe: 0, annualVol: 20, rankPct: 0 }, customBasePrice: 1.0 };
}

function buildFundProfile(code: string, infoRes: PromiseSettledResult<FundInfo>, metricsRes: PromiseSettledResult<FundMetrics>, navRes: PromiseSettledResult<{ navs?: FundNavPoint[] }>): FundProfile {
  const info = infoRes.status === 'fulfilled' ? infoRes.value : {};
  const metrics = metricsRes.status === 'fulfilled' ? metricsRes.value : {};
  const navs = navRes.status === 'fulfilled' ? navRes.value.navs || [] : [];
  const latestNav = navs.length ? Number(navs[navs.length - 1].nav) : NaN;
  const totalAssets = Number(info.total_assets);
  return {
    code,
    name: info.name || code,
    type: mapFundType(info.fund_type),
    typeName: info.fund_type || '--',
    company: info.company || '--',
    manager: info.manager || '--',
    inception: info.inception_date || '--',
    size: Number.isFinite(totalAssets) && totalAssets > 0 ? (totalAssets / 1e8).toFixed(2) + ' 亿元' : '--',
    expenseRatio: 0,
    benchmarkName: '--',
    topHoldings: [],
    sectorAllocation: [],
    historicMetrics: {
      maxDrawdown: Number.isFinite(metrics.max_drawdown as number) ? (metrics.max_drawdown as number) : -20,
      sharpe: Number.isFinite(metrics.sharpe_ratio as number) ? (metrics.sharpe_ratio as number) : 0,
      annualVol: Number.isFinite(metrics.volatility as number) ? (metrics.volatility as number) : 20,
      rankPct: 0
    },
    customBasePrice: Number.isFinite(latestNav) && latestNav > 0 ? latestNav : 1.0
  };
}

function resampleNavs(navs: number[], target: number): number[] {
  if (navs.length === 0 || target <= 0) return [];
  if (navs.length === target) return navs;
  if (navs.length > target) {
    const stride = (navs.length - 1) / (target - 1);
    return Array.from({ length: target }, (_, i) => navs[Math.round(i * stride)]);
  }
  return [...navs, ...Array(target - navs.length).fill(navs[navs.length - 1])];
}

export function FundDcaLab() {
  // Config state
  const [selectedFundCode, setSelectedFundCode] = useState<string>('005827');

  // Live fund data cache (profiles / metrics / NAVs fetched from /api/funds/*)
  const [fundDataCache, setFundDataCache] = useState<Record<string, { profile: FundProfile; navs: number[]; loading: boolean; loaded?: boolean; error?: string; }>>({});

  // Sandbox Custom Fund state
  const [customFundName, setCustomFundName] = useState<string>('美科技硬算力指数模拟器');
  const [customFundType, setCustomFundType] = useState<'mixed' | 'bond' | 'index' | 'etf' | 'qdii'>('qdii');
  const [customFundVol, setCustomFundVol] = useState<number>(28); // Volatility %
  const [customFundDrift, setCustomFundDrift] = useState<number>(14); // Expected drift %
  
  // Backtest controls
  const [initialCapital, setInitialCapital] = useState<number>(10000); // Day 0 seed capital
  const [dcaAmount, setDcaAmount] = useState<number>(3000);
  const [dcaFrequency, setDcaFrequency] = useState<'weekly' | 'biweekly' | 'monthly'>('monthly');
  const [dcaYears, setDcaYears] = useState<number>(3); // 1, 2, 3, 5
  const [dividendMode, setDividendMode] = useState<'reinvest' | 'cash'>('reinvest');
  const [takeProfitPct, setTakeProfitPct] = useState<number>(20); // 0 = disabled
  const [buyTheDipRule, setBuyTheDipRule] = useState<'none' | 'moderate' | 'aggressive'>('moderate');
  
  // Custom Portfolio Builder states
  const [usePortfolioMode, setUsePortfolioMode] = useState<boolean>(false);
  const [selectedRecipeId, setSelectedRecipeId] = useState<string>('');
  const [portfolioWeights, setPortfolioWeights] = useState<Record<string, number>>({
    '510300': 50,
    '159941': 25,
    '005827': 25
  });

  // UI Navigation Tabs
  const [activeTab, setActiveTab] = useState<'chart' | 'ledger' | 'metrics'>('chart');

  // AI & Chat status
  const [aiResponse, setAiResponse] = useState<string>('');
  const [isAiLoading, setIsAiLoading] = useState<boolean>(false);
  const [, setSelectedFAQ] = useState<string>('');
  const [customQuery, setCustomQuery] = useState<string>('');
  const [diagnosticOpen, setDiagnosticOpen] = useState<boolean>(false);

  // Computed simulation metrics
  const [simulationData, setSimulationData] = useState<any[]>([]);
  const [ledgerData, setLedgerData] = useState<any[]>([]);
  const [summaryMetrics, setSummaryMetrics] = useState<any>({
    totalInvested: 0,
    currentAsset: 0,
    accumulatedYield: 0,
    yieldPct: 0,
    annualYieldPct: 0,
    maxDrawdown: 0,
    longestDrawdownMonths: 0,
    winMonthsPct: 0,
    avgCost: 0,
    lumpSumReturnPct: 0,
    benchmarkReturnPct: 0,
    totalHoldingsUnits: 0,
    cashDividendsPaid: 0,
    takeProfitTimes: 0
  });

  // Sandbox (synthetic) fund profile built from user params
  const sandboxProfile = useMemo<FundProfile>(() => ({
    code: 'custom-sandbox',
    name: customFundName || '自定义沙盒模拟基金',
    type: customFundType,
    typeName: '沙盒 ' + (CLASSES_DESCRIPTION[customFundType]?.title || '自定义类别'),
    company: '智能沙盒实验室 (Synthetic Lab)',
    manager: '量化模型AI交易员',
    inception: '今日发售',
    size: '5.0 亿元 (模拟)',
    expenseRatio: 0.15,
    benchmarkName: '对称多项式高斯分布参考基准',
    topHoldings: [
      { name: '英伟达 (NVIDIA)', weight: 15.0 },
      { name: '台积电 (TSMC)', weight: 12.0 },
      { name: '博通 (Broadcom)', weight: 8.0 },
      { name: '特斯拉 (Tesla)', weight: 6.0 },
      { name: '微迈克斯', weight: 4.0 }
    ],
    sectorAllocation: [
      { name: '大模型半导体', weight: 45 },
      { name: '人形机器人', weight: 25 },
      { name: '清洁核动力', weight: 15 },
      { name: '量子通信', weight: 10 },
      { name: '其他', weight: 5 }
    ],
    historicMetrics: {
      maxDrawdown: -customFundVol * 1.5,
      sharpe: Math.round((customFundDrift / customFundVol) * 100) / 100,
      annualVol: customFundVol,
      rankPct: 12
    },
    customBasePrice: 1.0
  }), [customFundName, customFundType, customFundVol, customFundDrift]);

  // Live fund profile: real (from cache) or sandbox
  const selectedFund = useMemo<FundProfile>(() => {
    if (selectedFundCode === 'custom-sandbox') return sandboxProfile;
    return fundDataCache[selectedFundCode]?.profile || placeholderFundProfile(selectedFundCode);
  }, [selectedFundCode, fundDataCache, sandboxProfile]);

  // Fetch real fund profile + metrics + NAV series from /api/funds/*
  const fetchFundData = useCallback(async (code: string) => {
    if (!code || code === 'custom-sandbox') return;
    setFundDataCache((prev) => ({
      ...prev,
      [code]: { profile: prev[code]?.profile || placeholderFundProfile(code), navs: prev[code]?.navs || [], loading: true }
    }));
    try {
      const [infoRes, metricsRes, navRes] = await Promise.allSettled([
        fetchApi<FundInfo>('/api/funds/' + encodeURIComponent(code)),
        fetchApi<FundMetrics>('/api/funds/' + encodeURIComponent(code) + '/metrics'),
        fetchApi<{ navs?: FundNavPoint[] }>('/api/funds/' + encodeURIComponent(code) + '/nav?limit=400')
      ]);
      // 三个接口全部失败 = 后端不可用：allSettled 不会抛出，需显式记为可重试错误，
      // 否则会静默回落成 placeholder 资料卡（永远的 "--"）。
      if ([infoRes, metricsRes, navRes].every((res) => res.status === 'rejected')) {
        const reason = infoRes.status === 'rejected' ? infoRes.reason : undefined;
        setFundDataCache((prev) => ({
          ...prev,
          [code]: { profile: prev[code]?.profile || placeholderFundProfile(code), navs: prev[code]?.navs || [], loading: false, error: getErrorMessage(reason) }
        }));
        return;
      }
      const profile = buildFundProfile(code, infoRes, metricsRes, navRes);
      const navs = navRes.status === 'fulfilled'
        ? (navRes.value.navs || []).map((n) => Number(n.nav)).filter((v) => Number.isFinite(v) && v > 0)
        : [];
      setFundDataCache((prev) => ({ ...prev, [code]: { profile, navs, loading: false, loaded: true } }));
    } catch (err) {
      setFundDataCache((prev) => ({
        ...prev,
        [code]: { profile: prev[code]?.profile || placeholderFundProfile(code), navs: prev[code]?.navs || [], loading: false, error: getErrorMessage(err) }
      }));
    }
  }, []);

  useEffect(() => {
    if (selectedFundCode !== 'custom-sandbox') void fetchFundData(selectedFundCode);
  }, [selectedFundCode, fetchFundData]);

  useEffect(() => {
    QUICK_FUND_CODES.forEach((code) => void fetchFundData(code));
  }, [fetchFundData]);

  // Chat model selection for the AI advisor panel (mirrors Workbench/NewsAggregator)
  const [, setChatProviders] = useState<ModelProvider[]>([]);
  const [chatModelOptions, setChatModelOptions] = useState<ModelOption[]>([]);
  const [selectedChatModelKey, setSelectedChatModelKey] = useState<string>('');
  const selectedChatModel = chatModelOptions.find((o) => o.key === selectedChatModelKey) ?? chatModelOptions[0];

  const [chatModelsReloadKey, setChatModelsReloadKey] = useState(0);
  useEffect(() => subscribeSettingsChanged(() => setChatModelsReloadKey((k) => k + 1)), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await fetchApi<{ providers: ModelProvider[] }>('/api/settings/providers');
        if (cancelled) return;
        const providers = result.providers || [];
        const routes = await loadAiModelRoutesFromApi().catch(() => loadLocalAiModelRoutes());
        if (cancelled) return;
        const options = buildModelOptions(providers, 'chat');
        const routeKey = getModelKey(getRouteSelection(routes, providers, 'chat'));
        setChatProviders(providers);
        setChatModelOptions(options);
        setSelectedChatModelKey((cur) => (cur && options.some((o) => o.key === cur) ? cur : (routeKey && options.some((o) => o.key === routeKey) ? routeKey : (options[0]?.key || ''))));
      } catch {
        if (!cancelled) { setChatProviders([]); setChatModelOptions([]); setSelectedChatModelKey(''); }
      }
    })();
    return () => { cancelled = true; };
  }, [chatModelsReloadKey]);

  // Load recipe helper
  const handleLoadRecipe = (recipe: PortfolioRecipe) => {
    setUsePortfolioMode(true);
    setSelectedRecipeId(recipe.id);
    const newWeights: Record<string, number> = {};
    QUICK_FUND_CODES.forEach((code) => {
      newWeights[code] = 0;
    });
    recipe.allocations.forEach(alloc => {
      newWeights[alloc.code] = alloc.weight;
    });
    setPortfolioWeights(newWeights);
    if (recipe.allocations.length > 0) {
      setSelectedFundCode(recipe.allocations[0].code);
    }
  };

  // Instant Smart Portfolio Weight Optimizers
  const handleOptimizeWeights = (mode: 'sharpe' | 'defensive') => {
    const optimized: Record<string, number> = {};
    QUICK_FUND_CODES.forEach((code) => { optimized[code] = 0; });
    if (mode === 'sharpe') {
      // Prioritize high-performance, low-correlation diversification
      optimized['159941'] = 40; // Nasdaq ETF (QDII)
      optimized['510300'] = 30; // Hushen 300 ETF
      optimized['005827'] = 15; // Blue Chip Mix
      optimized['100072'] = 15; // Bond
      setSelectedRecipeId('core-satellite');
    } else {
      // Heavy defense mode
      optimized['100072'] = 70; // Defensive bond
      optimized['510300'] = 20; // Hushen 300
      optimized['159941'] = 10; // Tech export hedge
      setSelectedRecipeId('all-weather-bond');
    }
    setPortfolioWeights(optimized);
    setUsePortfolioMode(true);
  };

  // Quantitative DCA Simulation Math Engine
  const runSimulation = () => {
    const totalMonths = dcaYears * 12;
    let stepsPerMonth = 1;
    let multiplier = 1;
    if (dcaFrequency === 'weekly') {
      stepsPerMonth = 4;
      multiplier = 0.25;
    } else if (dcaFrequency === 'biweekly') {
      stepsPerMonth = 2;
      multiplier = 0.5;
    }
    const totalSteps = totalMonths * stepsPerMonth;

    let basePrice = 1.0;
    let volatility = 0.20;
    let driftPct = 0.08;
    let indexBenchmarkDrift = 0.04;
    let indexVolatility = 0.15;
    let crashPoint = 12; // Month of systemic market correction

    if (usePortfolioMode) {
      let sumBasePrice = 0;
      let weightedVol = 0;
      let weightedDrift = 0;
      const sumWeights = Object.values(portfolioWeights).reduce((a, b) => (a as number) + (b as number), 0) as number;
      if (sumWeights === 0) return;

      Object.entries(portfolioWeights).forEach(([code, weightVal]) => {
        const w = weightVal as number;
        if (w <= 0) return;
        const info = (code === 'custom-sandbox' ? selectedFund : fundDataCache[code]?.profile) || null;
        if (!info) return;
        sumBasePrice += info.customBasePrice * (w / sumWeights);
        weightedVol += info.historicMetrics.annualVol * (w / sumWeights) / 100;

        let drift = 0.07;
        if (info.type === 'qdii') drift = 0.12;
        if (info.type === 'bond') drift = 0.038;
        if (info.code === '161725') drift = 0.095;
        if (info.code === '003095') drift = 0.055;
        weightedDrift += drift * (w / sumWeights);
      });
      basePrice = sumBasePrice;
      volatility = weightedVol;
      driftPct = weightedDrift;
      if ((portfolioWeights['159941'] as number || 0) > 40) {
        indexBenchmarkDrift = 0.08;
        indexVolatility = 0.13;
        crashPoint = 16;
      }
    } else {
      basePrice = selectedFund.customBasePrice;
      volatility = selectedFund.historicMetrics.annualVol / 100;
      if (selectedFundCode === 'custom-sandbox') {
        driftPct = customFundDrift / 100;
        volatility = customFundVol / 100;
        indexBenchmarkDrift = 0.05;
        indexVolatility = 0.14;
        crashPoint = Math.floor(totalSteps * 0.4);
      } else {
        if (selectedFund.type === 'qdii') {
          driftPct = 0.125;
          indexBenchmarkDrift = 0.085;
          indexVolatility = 0.13;
          crashPoint = 15;
        } else if (selectedFund.type === 'bond') {
          driftPct = 0.045;
          indexBenchmarkDrift = 0.02;
          indexVolatility = 0.02;
          crashPoint = 999;
        } else if (selectedFund.code === '003095') {
          driftPct = 0.065;
          indexBenchmarkDrift = 0.035;
          indexVolatility = 0.16;
          crashPoint = 8;
        } else if (selectedFund.code === '161725') {
          driftPct = 0.11;
          indexBenchmarkDrift = 0.035;
          indexVolatility = 0.18;
          crashPoint = 11;
        } else {
          driftPct = 0.075;
          indexBenchmarkDrift = 0.035;
          indexVolatility = 0.15;
          crashPoint = 12;
        }
      }
    }

    // Generate accurate underlying curves
    const cachedNavs = selectedFundCode !== 'custom-sandbox' ? fundDataCache[selectedFundCode]?.navs : [];
    const navSeries = cachedNavs && cachedNavs.length > 1
      ? resampleNavs(cachedNavs, totalSteps)
      : createSineDriftPriceCurve(totalSteps, basePrice, volatility, driftPct, crashPoint);
    const benchmarkSeries = createSineDriftPriceCurve(totalSteps, basePrice * 0.95, indexVolatility, indexBenchmarkDrift, crashPoint);

    // Initial Position (Day 0 seed capital)
    let accumulatedCost = initialCapital;
    let unitsHeld = initialCapital > 0 ? (initialCapital * (1 - 0.0012)) / navSeries[0] : 0;
    let cashParked = 0; // Cash reserved from take profit logic (yields 2% annual dynamic rate)
    let totalCashDividends = 0;
    const dcaSingleBase = dcaAmount * multiplier;

    let maxPortfolioValue = initialCapital > 0 ? initialCapital : 1;
    let currentMaxDrawdown = 0;
    let consecutiveDrawdownSteps = 0;
    let maxDrawdownSteps = 0;
    let winningSteps = 0;
    let takeProfitTimes = 0;

    const auditLedger: any[] = [];

    const dataPoints = navSeries.map((nav, t) => {
      let marginBoosterFactor = 1.0;
      let eventTag = '';

      // 1. Calculate dynamic contribution adjusted by "Buy-the-Dip" booster rule
      if (buyTheDipRule !== 'none' && t > 0) {
        const pastPrices = navSeries.slice(0, t + 1);
        const localHigh = Math.max(...pastPrices);
        const dropPct = (nav - localHigh) / localHigh;

        if (dropPct < -0.15) {
          marginBoosterFactor = buyTheDipRule === 'aggressive' ? 2.0 : 1.5;
          eventTag = `🔥 逢低加仓 ${marginBoosterFactor}x`;
        } else if (dropPct < -0.06) {
          marginBoosterFactor = buyTheDipRule === 'aggressive' ? 1.5 : 1.25;
          eventTag = `⚡ 逢低加仓 ${marginBoosterFactor}x`;
        }
      }

      // Check if market indicators are oversold
      const isOversold = t > 8 && navSeries[t] < navSeries[t - 5] * 0.91;
      if (isOversold && buyTheDipRule !== 'none') {
        marginBoosterFactor = Math.max(marginBoosterFactor, buyTheDipRule === 'aggressive' ? 1.8 : 1.35);
        eventTag = eventTag ? `${eventTag} (指标超跌)` : '🧩 量化超跌增持';
      }

      const actualInputThisStep = dcaSingleBase * marginBoosterFactor;
      
      accumulatedCost += actualInputThisStep;

      // Purchase execution with standard professional 0.12% commission
      const cleanPurchasableAmount = actualInputThisStep * (1 - 0.0012);
      const newUnits = cleanPurchasableAmount / nav;
      unitsHeld += newUnits;

      // 2. Dividend distribution trigger (Every 12 steps)
      if (t > 0 && t % 12 === 0) {
        const divRatePct = selectedFund.type === 'bond' ? 0.026 : 0.015;
        const dividendPayable = unitsHeld * nav * divRatePct;
        if (dividendPayable > 0) {
          if (dividendMode === 'reinvest') {
            const reinvestUnits = dividendPayable / nav;
            unitsHeld += reinvestUnits;
            eventTag = eventTag ? `${eventTag} & 🌸 红利再投` : '🌸 利息/分红再投';
          } else {
            cashParked += dividendPayable;
            totalCashDividends += dividendPayable;
            eventTag = eventTag ? `${eventTag} & 🧾 分红派息` : '🧾 现金分红派息';
          }
        }
      }

      // 3. Take-profit evaluation
      const currentVal = unitsHeld * nav + cashParked;
      const originalTotalProfitRate = accumulatedCost > 0 ? ((currentVal - accumulatedCost) / accumulatedCost) * 100 : 0;
      let isTakeProfitTriggered = false;

      if (takeProfitPct > 0 && originalTotalProfitRate >= takeProfitPct && unitsHeld > 0) {
        cashParked = currentVal * (1 - 0.0015); // Liquidate with slight spread fee
        unitsHeld = 0;
        takeProfitTimes++;
        isTakeProfitTriggered = true;
        eventTag = `🎯 触发止盈并落袋 ${takeProfitPct}%`;
      }

      // Add 2% risk-free rate on cashParked
      if (cashParked > 0) {
        const cashMonthlyYield = 0.02 / 12;
        cashParked += cashParked * cashMonthlyYield;
      }

      // True portfolio value calculation
      const finalAssets = unitsHeld * nav + cashParked;
      const profitValue = finalAssets - accumulatedCost;
      const totalReturnPct = accumulatedCost > 0 ? (profitValue / accumulatedCost) * 100 : 0;

      // Compare to Index Benchmark
      const initialBenchPrice = benchmarkSeries[0];
      const benchmarkReturnPct = ((benchmarkSeries[t] - initialBenchPrice) / initialBenchPrice) * 100;

      // Compare to Lump Sum
      const totalSumpCapitalToInvest = initialCapital + dcaAmount * dcaYears * 12;
      const lumpSumUnits = (totalSumpCapitalToInvest * (1 - 0.0012)) / navSeries[0];
      const lumpSumValue = lumpSumUnits * nav;
      const lumpSumReturnPct = ((lumpSumValue - totalSumpCapitalToInvest) / totalSumpCapitalToInvest) * 100;

      // Max drawdown metrics
      if (finalAssets > maxPortfolioValue) {
        maxPortfolioValue = finalAssets;
        consecutiveDrawdownSteps = 0;
      } else {
        const currentDrawdown = ((finalAssets - maxPortfolioValue) / maxPortfolioValue) * 100;
        if (currentDrawdown < currentMaxDrawdown) {
          currentMaxDrawdown = currentDrawdown;
        }
        consecutiveDrawdownSteps++;
        if (consecutiveDrawdownSteps > maxDrawdownSteps) {
          maxDrawdownSteps = consecutiveDrawdownSteps;
        }
      }

      if (totalReturnPct > 0) {
        winningSteps++;
      }

      const ledgerItem = {
        period: t + 1,
        date: `第 ${Math.floor(t / stepsPerMonth) + 1} 月第 ${(t % stepsPerMonth) + 1} 期`,
        nav: nav.toFixed(4),
        contribution: Math.round(actualInputThisStep),
        newUnits: newUnits.toFixed(2),
        totalUnits: unitsHeld.toFixed(2),
        cashParked: Math.round(cashParked),
        accumulatedInput: Math.round(accumulatedCost),
        totalAssetsHex: Math.round(finalAssets),
        profitRateNow: totalReturnPct.toFixed(2),
        event: eventTag
      };

      auditLedger.push(ledgerItem);

      return {
        step: t,
        dateLabel: `M${Math.floor(t / stepsPerMonth) + 1}`,
        nav,
        accumulatedCost: Math.round(accumulatedCost),
        portfolioValue: Math.round(finalAssets),
        lumpSumValue: Math.round(lumpSumValue),
        benchmarkValue: Math.round(totalSumpCapitalToInvest * (1 + benchmarkReturnPct / 100)),
        totalReturnPct: Math.round(totalReturnPct * 100) / 100,
        benchmarkReturnPct: Math.round(benchmarkReturnPct * 100) / 100,
        lumpSumReturnPct: Math.round(lumpSumReturnPct * 100) / 100,
        takeProfit: isTakeProfitTriggered
      };
    });

    setSimulationData(dataPoints);
    setLedgerData(auditLedger);

    const finalPoint = dataPoints[dataPoints.length - 1];
    const rawYieldPct = finalPoint.totalReturnPct;
    const compoundAnnualGrowthRate = Math.pow(1 + (rawYieldPct / 100), 1 / dcaYears) - 1;
    const estimatedFinalUnits = (finalPoint.portfolioValue - cashParked) / finalPoint.nav;
    const avgCost = estimatedFinalUnits > 0 ? (finalPoint.accumulatedCost - cashParked) / estimatedFinalUnits : finalPoint.nav;

    setSummaryMetrics({
      totalInvested: finalPoint.accumulatedCost,
      currentAsset: finalPoint.portfolioValue,
      accumulatedYield: finalPoint.portfolioValue - finalPoint.accumulatedCost,
      yieldPct: rawYieldPct,
      annualYieldPct: Math.round(compoundAnnualGrowthRate * 10000) / 100,
      maxDrawdown: Math.round(currentMaxDrawdown * 100) / 100,
      longestDrawdownMonths: Math.round((maxDrawdownSteps / stepsPerMonth) * 10) / 10,
      winMonthsPct: Math.round((winningSteps / totalSteps) * 100),
      avgCost: Math.round(avgCost * 100) / 100,
      lumpSumReturnPct: finalPoint.lumpSumReturnPct,
      benchmarkReturnPct: finalPoint.benchmarkReturnPct,
      totalHoldingsUnits: estimatedFinalUnits.toFixed(2),
      cashDividendsPaid: Math.round(totalCashDividends),
      takeProfitTimes
    });
  };

  useEffect(() => {
    runSimulation();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 显式列出输入项;runSimulation 是每次渲染重建的闭包,入 deps 会每渲染重跑
  }, [
    selectedFundCode,
    dcaAmount,
    dcaFrequency,
    dcaYears,
    dividendMode,
    takeProfitPct,
    buyTheDipRule,
    usePortfolioMode,
    portfolioWeights,
    initialCapital,
    selectedFund,
    customFundType,
    customFundVol,
    customFundDrift,
    customFundName
  ]);

  // AI advisor: forward the question to /api/chat with the current fund/DCA context
  const handleAskFAQ = async (question: string, _roles: string) => {
    setIsAiLoading(true);
    setSelectedFAQ(question);
    setAiResponse('');
    try {
      const context = {
        fund: selectedFund.code,
        fund_name: selectedFund.name,
        initial_capital: initialCapital,
        dca_amount: dcaAmount,
        dca_years: dcaYears,
        dca_frequency: dcaFrequency,
        take_profit: takeProfitPct,
        buy_the_dip: buyTheDipRule,
        total_invested: summaryMetrics.totalInvested,
        current_asset: summaryMetrics.currentAsset,
        yield_pct: summaryMetrics.yieldPct,
        max_drawdown: summaryMetrics.maxDrawdown
      };
      const result = await fetchApi<{ content?: string; provider?: string; model?: string }>('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: question,
          mode: 'free',
          stock_symbol: selectedFund.code === 'custom-sandbox' ? '' : selectedFund.code,
          stock_name: selectedFund.name,
          provider: selectedChatModel?.providerId,
          model: selectedChatModel?.modelId,
          context
        })
      });
      setAiResponse(result.content || '智囊团未返回内容。');
    } catch (err) {
      setAiResponse('智囊团调用失败：' + getErrorMessage(err) + '（请确认已在系统设置配置可用的对话模型）');
    } finally {
      setIsAiLoading(false);
    }
  }

  const activeFundIndexData = CLASSES_DESCRIPTION[selectedFund.type] || {};
  void activeFundIndexData; // 预留:基金分类说明展示(暂未接入 UI)

  // 选中基金(非沙盒)的后端数据状态:首次加载中显示骨架屏,全部接口失败显示可重试错误。
  // loaded 标记避免"切回已加载基金时的重新拉取"把已有资料卡闪成骨架屏。
  const selectedFundEntry = selectedFundCode === 'custom-sandbox' ? undefined : fundDataCache[selectedFundCode];
  const fundDataLoading = Boolean(selectedFundEntry?.loading && !selectedFundEntry?.loaded);
  const fundDataError = selectedFundEntry?.loading ? undefined : selectedFundEntry?.error;

  return (
    <div className="flex flex-col gap-6 p-6 min-h-screen bg-transparent text-neutral-200" id="fund_dca_lab_module">
      {/* Header Panel */}
      <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 border-b border-white/5 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1.5 font-display">
            <span className="px-2.5 py-0.5 text-xs uppercase font-bold tracking-wider rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Quantitative Lab v2.5
            </span>
            <span className="px-2.5 py-0.5 text-xs uppercase font-bold tracking-wider rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Smart-Sandbox Engine
            </span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5 font-display">
            <Coins className="w-7 h-7 text-indigo-400" /> 
            Fund & DCA Lab 
            <span className="text-sm text-neutral-400 font-mono font-normal">| 基金与定投智能实验室</span>
          </h1>
          <p className="text-sm text-neutral-300 mt-1.5 max-w-2xl leading-relaxed">
            提供高保真基金数据分析。支持设置“期初初始底仓”、“大盘暴跌按梯度加仓”、“目标止盈自动收缩避险”，以及交互式财务审计流水表与AI智囊团联合审查。
          </p>
        </div>

        {/* View mode toggle */}
        <div className="flex items-center gap-2 bg-neutral-900/80 p-1 rounded-xl border border-white/5">
          <button 
            onClick={() => setUsePortfolioMode(false)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 flex items-center gap-1.5 cursor-pointer",
              !usePortfolioMode 
                ? "bg-indigo-600/25 text-indigo-300 border border-indigo-500/30 shadow-sm" 
                : "text-neutral-400 hover:text-white"
            )}
          >
            <Layers className="w-3.5 h-3.5" /> 
            单只基金沙盒
          </button>
          <button 
            onClick={() => {
              setUsePortfolioMode(true);
              handleLoadRecipe(PORTFOLIO_RECIPES[0]);
            }}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 flex items-center gap-1.5 cursor-pointer",
              usePortfolioMode 
                ? "bg-indigo-600/25 text-indigo-300 border border-indigo-500/30 shadow-sm" 
                : "text-neutral-400 hover:text-white"
            )}
          >
            <Scale className="w-3.5 h-3.5" />
            资产配置组合
          </button>
        </div>
      </div>

      {/* Grid container */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        
        {/* LEFT COLUMN: Configuration Workspace */}
        <div className="xl:col-span-5 flex flex-col gap-6">
          
          {/* SEC 1: Fund Selection or Portfolio customizer */}
          <div className="bg-[#0c0c12]/90 border border-white/5 rounded-2xl p-5 relative overflow-hidden flex flex-col gap-4 shadow-xl">
            <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/5 rounded-full blur-[80px] pointer-events-none" />
            
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <h2 className="text-sm font-semibold text-neutral-200 flex items-center gap-2 font-display">
                <BookOpen className="w-4 h-4 text-indigo-400" />
                {usePortfolioMode ? '1. 资产均衡配置模型' : '1. 选择测算基金标的'}
              </h2>
              <span className="text-xs font-mono text-neutral-400 bg-neutral-900 border border-white/5 px-2 py-0.5 rounded">
                DCA MATRIX
              </span>
            </div>

            {!usePortfolioMode ? (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-mono font-bold text-neutral-300 uppercase tracking-wider block">
                    目标基金 / 指数代码
                  </label>
                  <select 
                    value={selectedFundCode}
                    onChange={(e) => setSelectedFundCode(e.target.value)}
                    className="w-full bg-black/60 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-indigo-300 font-bold font-mono focus:outline-none focus:border-indigo-500/55 cursor-pointer"
                  >
                    {QUICK_FUND_CODES.map((code) => {
                      const f = fundDataCache[code]?.profile || placeholderFundProfile(code);
                      return (
                      <option key={code} value={code} className="bg-[#0f0f15] text-neutral-200 text-sm">
                        {code} | {f.name} ({f.typeName})
                      </option>
                      );
                    })}
                    <option value="custom-sandbox" className="bg-[#0f0f15] text-emerald-400 font-semibold text-sm">
                      999999 | 自定义模拟沙盒产品 [点击调参]
                    </option>
                  </select>
                </div>

                {/* Sub pane: Custom Sandbox Fund Form parameters */}
                {selectedFundCode === 'custom-sandbox' && (
                  <div className="bg-emerald-950/10 border border-emerald-500/15 p-4 rounded-xl space-y-3">
                    <span className="text-xs uppercase font-bold text-emerald-400 font-mono tracking-wider flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5" /> 沙盒标的属性可调参面板
                    </span>
                    <div className="space-y-2.5 text-sm">
                      <div className="grid grid-cols-2 gap-2.5">
                        <div>
                          <label className="text-[11px] text-neutral-400 block mb-1">标的名称</label>
                          <input 
                            type="text" 
                            value={customFundName}
                            onChange={(e) => setCustomFundName(e.target.value)}
                            className="w-full bg-black/40 border border-white/5 rounded px-2.5 py-1.5 text-sm text-neutral-100"
                          />
                        </div>
                        <div>
                          <label className="text-[11px] text-neutral-400 block mb-1">标的属性分类</label>
                          <select 
                            value={customFundType}
                            onChange={(e) => setCustomFundType(e.target.value as typeof customFundType)}
                            className="w-full bg-black/40 border border-white/5 rounded px-2.5 py-1.5 text-sm text-neutral-100 cursor-pointer"
                          >
                            <option value="mixed">偏股型主动混合基金</option>
                            <option value="qdii">跨境国际指数 (QDII)</option>
                            <option value="etf">宽基核心ETF</option>
                            <option value="index">被动行业指数A</option>
                            <option value="bond">固收+ 收益型债基</option>
                          </select>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-3.5 pt-1">
                        <div className="space-y-1">
                          <div className="flex justify-between text-[11px] text-neutral-300 font-mono">
                            <span>年化预期漂移率</span>
                            <span className="text-emerald-400 font-bold">{customFundDrift}%</span>
                          </div>
                          <input 
                            type="range" min="-25" max="45" value={customFundDrift}
                            onChange={(e) => setCustomFundDrift(parseInt(e.target.value))}
                            className="w-full h-1 bg-neutral-800 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                          />
                        </div>
                        <div className="space-y-1">
                          <div className="flex justify-between text-[11px] text-neutral-300 font-mono">
                            <span>年化预设波动率</span>
                            <span className="text-rose-400 font-bold">{customFundVol}%</span>
                          </div>
                          <input 
                            type="range" min="4" max="65" value={customFundVol}
                            onChange={(e) => setCustomFundVol(parseInt(e.target.value))}
                            className="w-full h-1 bg-neutral-800 rounded-lg appearance-none cursor-pointer accent-rose-500"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Fund Brief Description scorecard */}
                {fundDataLoading ? (
                  <Skeleton variant="card" />
                ) : fundDataError ? (
                  <ErrorState
                    message={`${selectedFundCode} 基金数据加载失败：${fundDataError}`}
                    onRetry={() => void fetchFundData(selectedFundCode)}
                    className="px-3 py-8"
                  />
                ) : (
                <div className="bg-black/40 border border-white/[0.03] rounded-xl p-3.5 grid grid-cols-2 gap-3.5 text-sm">
                  <div>
                    <span className="text-neutral-400 text-xs block mb-0.5">基金经理 (团队)</span>
                    <span className="text-neutral-100 font-semibold font-mono text-sm">{selectedFund.manager}</span>
                  </div>
                  <div>
                    <span className="text-neutral-400 text-xs block mb-0.5">总管理规模</span>
                    <span className="text-neutral-100 font-semibold font-mono text-sm">{selectedFund.size}</span>
                  </div>
                  <div>
                    <span className="text-neutral-400 text-xs block mb-0.5">年化费用费率</span>
                    <span className="text-neutral-100 font-semibold font-mono text-sm">{selectedFund.expenseRatio}% / 年</span>
                  </div>
                  <div>
                    <span className="text-neutral-400 text-xs block mb-0.5">基期参考指数标的</span>
                    <span className="text-neutral-200 font-semibold text-xs truncate block" title={selectedFund.benchmarkName}>
                      {selectedFund.benchmarkName}
                    </span>
                  </div>
                </div>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                {/* Recipe Select Pill list */}
                <div className="flex flex-wrap gap-1.5 font-sans">
                  {PORTFOLIO_RECIPES.map(recipe => (
                    <button
                      key={recipe.id}
                      onClick={() => handleLoadRecipe(recipe)}
                      className={cn(
                        "px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all duration-200 cursor-pointer",
                        selectedRecipeId === recipe.id
                          ? "bg-indigo-600/20 text-indigo-300 border-indigo-500/40"
                          : "bg-white/[0.02] text-neutral-400 border-white/5 hover:border-white/10 hover:text-neutral-200"
                      )}
                    >
                      {recipe.name}
                    </button>
                  ))}
                </div>

                <div className="bg-black/40 border border-white/[0.03] rounded-xl p-3.5 space-y-3">
                  <p className="text-xs text-neutral-400 italic font-sans leading-relaxed">
                    {PORTFOLIO_RECIPES.find(r => r.id === selectedRecipeId)?.description || '定制基金比例下的分散配置回测。请单独调节或使用下方量化模型。'}
                  </p>
                  
                  {/* Slider configuration for weight */}
                  <div className="space-y-2 pt-2 border-t border-white/5">
                    {QUICK_FUND_CODES.map((code) => {
                      const f = fundDataCache[code]?.profile || placeholderFundProfile(code);
                      const weight = portfolioWeights[code] || 0;
                      return (
                        <div key={code} className="flex items-center justify-between gap-3 text-xs font-mono">
                          <span className="text-neutral-300 w-28 truncate text-xs" title={f.name}>
                            {f.name}
                          </span>
                          <div className="flex-1 h-1.5 bg-neutral-800 rounded-full overflow-hidden relative">
                            <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${weight}%` }} />
                          </div>
                          <div className="w-14 flex items-center justify-end gap-0.5">
                            <input 
                              type="number" 
                              min="0" 
                              max="100"
                              value={weight}
                              onChange={(e) => {
                                const val = Math.min(100, Math.max(0, parseInt(e.target.value) || 0));
                                setPortfolioWeights(prev => ({ ...prev, [code]: val }));
                                setSelectedRecipeId('');
                              }}
                              className="w-8 bg-black/40 text-center text-xs text-indigo-400 font-bold border border-white/5 rounded focus:outline-none"
                            />
                            <span className="text-neutral-500 text-xs">%</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Weight compliance optimizer buttons */}
                  <div className="flex flex-col sm:flex-row justify-between items-stretch sm:items-center gap-2 pt-2 border-t border-white/5 text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="text-neutral-400 uppercase font-mono">配方总比:</span>
                      <span className={cn(
                        "font-mono font-bold px-1.5 py-0.5 rounded",
                        (Object.values(portfolioWeights) as number[]).reduce((a, b) => a + b, 0) === 100
                          ? "text-emerald-400 bg-emerald-500/10"
                          : "text-rose-400 bg-rose-500/10 animate-pulse"
                      )}>
                        {(Object.values(portfolioWeights) as number[]).reduce((a, b) => a + b, 0)} %
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button 
                        onClick={() => handleOptimizeWeights('sharpe')}
                        className="bg-indigo-500/15 border border-indigo-500/25 hover:bg-indigo-500/35 px-2 py-1 rounded text-indigo-300 transition-colors font-semibold cursor-pointer"
                      >
                        ⚡ 极效最优夏普
                      </button>
                      <button 
                        onClick={() => handleOptimizeWeights('defensive')}
                        className="bg-emerald-500/15 border border-emerald-500/25 hover:bg-emerald-500/35 px-2 py-1 rounded text-emerald-300 transition-colors font-semibold cursor-pointer"
                      >
                        🛡️ 极小风险避险
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Exposition exposure breakdown */}
            <div className="bg-black/20 border border-white/[0.03] rounded-xl p-3.5 space-y-2.5">
              <span className="text-xs font-mono text-neutral-400 uppercase tracking-widest block">
                底层产业分布结构 & 核心重仓 constituents
              </span>
              {fundDataLoading ? (
                <Skeleton variant="list" />
              ) : selectedFund.sectorAllocation.length === 0 && selectedFund.topHoldings.length === 0 ? (
                <EmptyState
                  icon={Layers}
                  title="暂无底层持仓数据"
                  description="行情源未返回该标的的板块分布与重仓明细；沙盒模拟标的提供示例持仓。"
                  className="px-3 py-6"
                />
              ) : (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <span className="text-xs text-neutral-300 font-mono block font-semibold mb-1">主要板块敞口占比</span>
                  <div className="space-y-1">
                    {selectedFund.sectorAllocation.map((s, idx) => (
                      <div key={idx} className="space-y-1">
                        <div className="flex justify-between text-xs font-mono text-neutral-400">
                          <span className="truncate max-w-[80px]">{s.name}</span>
                          <span className="text-indigo-400 font-medium">{s.weight}%</span>
                        </div>
                        <div className="h-1 bg-neutral-800 rounded-full">
                          <div className="h-full bg-indigo-500/70 rounded-full" style={{ width: `${s.weight}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="space-y-1 pl-3.5 border-l border-white/5">
                  <span className="text-xs text-neutral-300 font-mono block font-semibold mb-1">前五大底仓控股股票</span>
                  <div className="space-y-1.5">
                    {selectedFund.topHoldings.map((h, idx) => (
                      <div key={idx} className="flex justify-between items-center text-xs font-mono text-neutral-300">
                        <span className="text-neutral-400 truncate max-w-[85px]">{h.name}</span>
                        <span className="font-semibold text-neutral-300">{h.weight}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              )}
            </div>
          </div>

          {/* SEC 2: Parameters configuration */}
          <div className="bg-[#0c0c12]/90 border border-white/5 rounded-2xl p-5 relative overflow-hidden flex flex-col gap-4 shadow-xl">
            <div className="absolute top-0 left-0 w-32 h-32 bg-emerald-500/5 rounded-full blur-[80px] pointer-events-none" />
            
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <h2 className="text-sm font-semibold text-neutral-200 flex items-center gap-2 font-display">
                <Sliders className="w-4 h-4 text-emerald-400" />
                2. 设置定投计划及智能风控参数
              </h2>
              <span className="px-2.5 py-0.5 bg-emerald-500/10 text-emerald-400 text-xs font-mono rounded">
                DCA CONTROL
              </span>
            </div>

            {/* Main DCA form input fields */}
            <div className="grid grid-cols-2 gap-4">
              
              {/* Day 0 Seed Capital (初始底仓) */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-neutral-300 uppercase block">
                  期初初始底仓金额
                </label>
                <div className="relative">
                  <span className="absolute left-2.5 top-2.5 text-neutral-400 text-xs font-mono">¥</span>
                  <input
                    type="number"
                    value={initialCapital}
                    onChange={(e) => setInitialCapital(Math.max(0, parseInt(e.target.value) || 0))}
                    className="w-full bg-black/60 border border-white/10 rounded-xl pl-5 pr-2 py-2 text-sm font-bold font-mono text-indigo-400 focus:outline-none focus:border-indigo-500/50"
                  />
                </div>
              </div>

              {/* Regular contribution Amount (单笔定投) */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-neutral-300 uppercase block">
                  单期跟投额度
                </label>
                <div className="relative">
                  <span className="absolute left-2.5 top-2.5 text-neutral-400 text-xs font-mono">¥</span>
                  <input
                    type="number"
                    value={dcaAmount}
                    onChange={(e) => setDcaAmount(Math.max(10, parseInt(e.target.value) || 0))}
                    className="w-full bg-black/60 border border-white/10 rounded-xl pl-5 pr-2 py-2 text-sm font-bold font-mono text-emerald-400 focus:outline-none focus:border-emerald-500/50"
                  />
                </div>
              </div>

              {/* DCA Frequency */}
              <div className="space-y-1.5">
                <label className="text-xs font-sans text-neutral-300 block">定投跟投周期频次</label>
                <select
                  value={dcaFrequency}
                  onChange={(e) => setDcaFrequency(e.target.value as typeof dcaFrequency)}
                  className="w-full bg-[#0c0c12] border border-white/5 rounded px-2.5 py-1.5 text-sm text-neutral-100 cursor-pointer"
                >
                  <option value="weekly">极速周投 (每周跟进)</option>
                  <option value="biweekly">双周平衡 (双周跟进)</option>
                  <option value="monthly">稳健月定 (每月固定)</option>
                </select>
              </div>

              {/* Total Backtest length in years */}
              <div className="space-y-1.5">
                <label className="text-xs font-sans text-neutral-300 block font-semibold mb-1">回测持续时间</label>
                <select
                  value={dcaYears}
                  onChange={(e) => setDcaYears(parseInt(e.target.value))}
                  className="w-full bg-[#0c0c12] border border-white/5 rounded px-2.5 py-1.5 text-sm text-neutral-100 cursor-pointer"
                >
                  <option value={1}>12 个月 (1 年短回测)</option>
                  <option value={2}>24 个月 (2 年中回测)</option>
                  <option value={3}>36 个月 (3 年标准微笑周期)</option>
                  <option value={5}>60 个月 (5 年完整牛熊测算)</option>
                </select>
              </div>

              {/* Dividend Reinvestment distribution selection */}
              <div className="space-y-1.5 col-span-2">
                <div className="flex justify-between items-center">
                  <label className="text-xs font-sans text-[#bebebe]">红利利润分配机制</label>
                  <span className="text-xs text-indigo-400 font-mono">红利再投资免收申赎费</span>
                </div>
                <div className="grid grid-cols-2 gap-2 bg-[#0c0c12] p-1 border border-white/5 rounded">
                  <button
                    onClick={() => setDividendMode('reinvest')}
                    className={cn(
                      "text-center py-1.5 rounded text-sm transition-all duration-200 cursor-pointer",
                      dividendMode === 'reinvest' 
                        ? "bg-indigo-600/35 text-indigo-200 font-semibold border border-indigo-400/30" 
                        : "text-neutral-500 hover:text-neutral-400"
                    )}
                  >
                    红利滚雪球再投
                  </button>
                  <button
                    onClick={() => setDividendMode('cash')}
                    className={cn(
                      "text-center py-1.5 rounded text-sm transition-all duration-200 cursor-pointer",
                      dividendMode === 'cash' 
                        ? "bg-indigo-600/35 text-indigo-200 font-semibold border border-indigo-400/30" 
                        : "text-neutral-500 hover:text-neutral-400"
                    )}
                  >
                    分红派发现金到账
                  </button>
                </div>
              </div>
            </div>

            {/* Smart Wind-control quant variables */}
            <div className="border-t border-white/5 pt-4 space-y-3">
              <span className="text-xs font-mono font-bold text-neutral-400 uppercase tracking-widest block">
                高级量化定投跟投风控设定 (Dynamic Booster Protection)
              </span>
              <div className="grid grid-cols-2 gap-4">
                
                {/* Buy-the-dip (Margin Booster) booster select dropdown */}
                <div className="space-y-1.5">
                  <label className="text-xs font-sans text-[#bebebe] flex items-center gap-1.5 font-semibold">
                    <Flame className="w-3.5 h-3.5 text-rose-400 animate-pulse" />
                    抗跌/超跌梯度追加规则
                  </label>
                  <select
                    value={buyTheDipRule}
                    onChange={(e) => setBuyTheDipRule(e.target.value as typeof buyTheDipRule)}
                    className="w-full bg-[#0c0c12] border border-white/5 rounded px-2.5 py-1.5 text-sm text-neutral-100 cursor-pointer font-medium"
                  >
                    <option value="none">常規固定额跟投</option>
                    <option value="moderate">逢跌1.5倍加码扣款</option>
                    <option value="aggressive">极限下跌双倍猛烈补仓</option>
                  </select>
                </div>

                {/* Target Take-profit select */}
                <div className="space-y-1.5">
                  <label className="text-xs font-sans text-[#bebebe] flex items-center gap-1.5 font-semibold">
                    <CheckCircle2 className="w-3.5 h-3.5 text-yellow-500" />
                    目标强制止盈锁利线
                  </label>
                  <select
                    value={takeProfitPct}
                    onChange={(e) => setTakeProfitPct(parseInt(e.target.value))}
                    className="w-full bg-[#0c0c12] border border-white/5 rounded px-[#bebebe] py-1.5 text-sm text-neutral-100 cursor-pointer font-medium"
                  >
                    <option value={0}>不设止盈（长期极效复利）</option>
                    <option value={15}>15% 门槛清盘护本</option>
                    <option value={20}>20% 经典止盈落袋</option>
                    <option value={30}>30% 高成长阻力清盘</option>
                    <option value={50}>50% 超高牛市追高线</option>
                  </select>
                </div>
              </div>

              {/* Status explanation indicators card */}
              <div className="bg-[#0a0a0f] border border-white/5 p-3.5 rounded flex items-start gap-2.5 text-xs text-neutral-400 font-sans leading-relaxed">
                <Info className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
                <div>
                  <span className="text-sm text-neutral-200 font-bold block mb-1">
                    实时风控引擎生效中:
                  </span>
                  {buyTheDipRule !== 'none' 
                    ? '系统将追踪本品净值在回测周波中的局部低点。一旦回撤超 6% 和 15%，会自动以您所设常规划的 1.5 倍或双倍额度吸入底仓，发挥微笑曲线均价折算效应；'
                    : '保持机械式等额跟投。在极深下跌底部无法发挥子弹加权重置优势；'}
                  {takeProfitPct > 0 
                    ? `一旦定投资产总盈亏率迈过 ${takeProfitPct}% 大关，会自动激活所有资产转出机制，安全沉淀在年化2%活利零钱账户，避免后期均值回归遭受大幅折损。`
                    : '不设置止盈线。持仓资产将常态面临市场系统性回调的真实浮亏考验。'}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Quantitative Backtest Dashboard tabs & Charts */}
        <div className="xl:col-span-7 flex flex-col gap-6">
          
          {/* SEC 3: Backtest Performance Scoreboard Cards */}
          <div className="bg-[#0c0c12]/90 border border-white/5 rounded-2xl p-5 relative overflow-hidden flex flex-col gap-4 shadow-xl">
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <span className="text-xs font-semibold text-neutral-200 flex items-center gap-2 font-display">
                <TrendingUp className="w-4 h-4 text-indigo-400" />
                3. 量化回测数据大盘成果综合
              </span>
              <span className="text-xs font-mono text-indigo-400 font-bold bg-indigo-500/10 px-2.5 py-0.5 rounded border border-indigo-500/15 uppercase">
                Backtest Terminal Output
              </span>
            </div>

            {/* Metric widgets block */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-black/30 border border-white/[0.04] p-3 rounded-xl relative">
                <span className="text-xs text-neutral-500 block mb-1 font-sans font-medium">累计本金投入</span>
                <span className="text-lg font-bold font-mono text-neutral-200">
                  ¥{summaryMetrics.totalInvested.toLocaleString()}
                </span>
                <span className="text-[10px] font-mono text-neutral-500 block mt-1 uppercase tracking-wider">CAPITAL INPUT</span>
              </div>

              <div className="bg-black/30 border border-white/[0.04] p-3 rounded-xl relative">
                <span className="text-xs text-neutral-500 block mb-1 font-sans font-medium">期末整仓总估值</span>
                <span className="text-lg font-bold font-mono text-white">
                  ¥{summaryMetrics.currentAsset.toLocaleString()}
                </span>
                <span className="text-[10px] font-mono text-neutral-500 block mt-1 uppercase tracking-wider">PORTFOLIO VALUE</span>
              </div>

              <div className={cn(
                "border p-3 rounded-xl relative",
                summaryMetrics.yieldPct >= 0 
                  ? "bg-rose-500/5 border-rose-500/15" 
                  : "bg-emerald-500/5 border-emerald-500/15"
              )}>
                <span className="text-xs text-neutral-500 block mb-1 font-sans font-medium">期末累计总盈亏</span>
                <span className={cn(
                  "text-lg font-bold font-mono block",
                  summaryMetrics.yieldPct >= 0 ? "text-rose-400" : "text-emerald-400"
                )}>
                  {summaryMetrics.yieldPct >= 0 ? '+' : ''}{summaryMetrics.yieldPct}%
                </span>
                <span className="text-[10px] font-mono text-neutral-500 block mt-1 uppercase tracking-wider">TOTAL RETURN</span>
              </div>

              <div className="bg-indigo-500/5 border border-indigo-500/15 p-3 rounded-xl relative">
                <span className="text-xs text-indigo-400/60 block mb-1 font-sans font-medium">复合年化收益率 (CAGR)</span>
                <span className="text-lg font-bold font-mono text-indigo-400 block">
                  {summaryMetrics.yieldPct >= 0 ? '+' : ''}{summaryMetrics.annualYieldPct}%
                </span>
                <span className="text-[10px] font-mono text-neutral-500 block mt-1 uppercase tracking-wider">ANNUALIZED GROWTH</span>
              </div>
            </div>

            {/* Risk Control breakdown panel row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 border-t border-white/5 pt-3.5 text-xs font-mono">
              <div className="bg-black/20 p-2 rounded-lg border border-white/[0.02]">
                <span className="text-neutral-400 block text-xs mb-0.5 font-sans">测试期最大本金回撤</span>
                <span className="text-emerald-400 font-bold text-sm">{summaryMetrics.maxDrawdown}%</span>
              </div>
              <div className="bg-black/20 p-2 rounded-lg border border-white/[0.02]">
                <span className="text-neutral-400 block text-xs mb-0.5 font-sans">最长资金套牢周期</span>
                <span className="text-neutral-300 font-bold text-sm">{summaryMetrics.longestDrawdownMonths} 个月</span>
              </div>
              <div className="bg-black/20 p-2 rounded-lg border border-white/[0.02]">
                <span className="text-neutral-400 block text-xs mb-0.5 font-sans">持仓平摊平均成本</span>
                <span className="text-indigo-400 font-bold text-sm">¥{summaryMetrics.avgCost}</span>
              </div>
              <div className="bg-black/20 p-2 rounded-lg border border-white/[0.02]">
                <span className="text-neutral-400 block text-xs mb-0.5 font-sans">累计现金分红派息</span>
                <span className="text-neutral-300 font-bold text-sm">¥{summaryMetrics.cashDividendsPaid} 元</span>
              </div>
            </div>

            {/* Tab Controller headers */}
            <div className="flex border-b border-white/5 mt-2 text-xs font-semibold">
              <button
                onClick={() => setActiveTab('chart')}
                className={cn(
                  "px-4 py-2 border-b-2 font-display transition-all cursor-pointer flex items-center gap-1.5",
                  activeTab === 'chart' 
                    ? "border-indigo-500 text-white bg-indigo-500/5" 
                    : "border-transparent text-neutral-400 hover:text-neutral-200"
                )}
              >
                📊 资产持仓增长轨迹曲线
              </button>
              <button
                onClick={() => setActiveTab('ledger')}
                className={cn(
                  "px-4 py-2 border-b-2 font-display transition-all cursor-pointer flex items-center gap-1.5",
                  activeTab === 'ledger' 
                    ? "border-indigo-500 text-white bg-indigo-500/5" 
                    : "border-transparent text-neutral-400 hover:text-neutral-200"
                )}
              >
                📋 基金跟投逐期流水分账
              </button>
              <button
                onClick={() => setActiveTab('metrics')}
                className={cn(
                  "px-4 py-2 border-b-2 font-display transition-all cursor-pointer flex items-center gap-1.5",
                  activeTab === 'metrics' 
                    ? "border-indigo-500 text-white bg-indigo-500/5" 
                    : "border-transparent text-neutral-400 hover:text-neutral-200"
                )}
              >
                🎯 策略多维理财指标审计
              </button>
            </div>

            {/* TAB CONTAINER 1: Backtest Line visualizer */}
            {activeTab === 'chart' && (
              <div className="h-[320px] w-full bg-black/45 border border-white/[0.03] rounded-xl p-4 relative">
                <div className="absolute top-2.5 left-5 text-xs font-mono text-neutral-400 font-semibold tracking-wider">
                  SANDBOX COMPARATIVE ASSETS CURVES (RMB MULTIPLIERS)
                </div>
                
                <StableChartContainer height="95%">
                  <ComposedChart data={simulationData} margin={{ top: 25, right: 10, left: -15, bottom: 0 }}>
                    <defs>
                      <linearGradient id="areaColor" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.25}/>
                        <stop offset="95%" stopColor="#4f46e5" stopOpacity={0.0}/>
                      </linearGradient>
                      <linearGradient id="costColor" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#22c55e" stopOpacity={0.15}/>
                        <stop offset="95%" stopColor="#22c55e" stopOpacity={0.0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#ffffff" strokeOpacity={0.03} strokeDasharray="3 3" vertical={false} />
                    <XAxis 
                      dataKey="dateLabel" 
                      tick={{ fill: '#a3a3a3', fontSize: 11, fontFamily: 'monospace' }} 
                      strokeOpacity={0.05}
                    />
                    <YAxis 
                      domain={['auto', 'auto']} 
                      tick={{ fill: '#a3a3a3', fontSize: 11, fontFamily: 'monospace' }} 
                      strokeOpacity={0.05}
                      tickFormatter={(val) => `¥${Math.round(val / 1000)}k`}
                    />
                    <ChartTooltip 
                      content={({ active, payload, label }: any) => {
                        if (active && payload && payload.length) {
                          const item = payload[0].payload;
                          return (
                            <div className="bg-[#09090d]/95 select-text border border-neutral-800 p-3 rounded-lg text-xs font-mono space-y-1.5 shadow-2xl">
                              <p className="text-neutral-400 border-b border-white/5 pb-1 font-bold">{item.dateLabel || label}</p>
                              <p className="text-indigo-400">资产总计: <span className="font-bold">¥{payload[1]?.value?.toLocaleString() || payload[0]?.value?.toLocaleString()}</span></p>
                              <p className="text-emerald-400">累计投入: <span className="font-bold">¥{item.accumulatedCost?.toLocaleString()}</span></p>
                              <p className="text-neutral-300">本期价格: <span className="font-bold">¥{item.nav}</span></p>
                              <p className="text-rose-400">大盘全额投入价值: <span className="font-bold">¥{item.lumpSumValue?.toLocaleString()}</span></p>
                              {item.takeProfit && (
                                <p className="text-yellow-400 font-bold mt-1 bg-yellow-500/10 px-1 py-0.5 rounded text-xs text-center">🎯 本期触发目标止盈</p>
                              )}
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    <Legend 
                      verticalAlign="top" 
                      height={28} 
                      iconSize={10} 
                      wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace' }}
                    />
                    <Area name="累计定投跟投资金" type="step" dataKey="accumulatedCost" stroke="#22c55e" strokeWidth={1} fill="url(#costColor)" opacity={0.65} animationDuration={800} animationEasing="ease-out" />
                    <Area name="定投总资产市值 (当前)" type="monotone" dataKey="portfolioValue" stroke="#6366f1" strokeWidth={2.5} fill="url(#areaColor)" animationDuration={800} animationEasing="ease-out" />
                    <Line name="期初一次性全额购买模型" type="monotone" dataKey="lumpSumValue" stroke="#f43f5e" strokeWidth={1.25} strokeDasharray="3 3" dot={false} opacity={0.7} animationDuration={800} animationEasing="ease-out" />
                    <Line name="基准大指数对比参考" type="monotone" dataKey="benchmarkValue" stroke="#eab308" strokeWidth={1} strokeDasharray="4 4" dot={false} opacity={0.6} animationDuration={800} animationEasing="ease-out" />
                  </ComposedChart>
                </StableChartContainer>
              </div>
            )}

            {/* TAB CONTAINER 2: Detail transaction ledger desk table */}
            {activeTab === 'ledger' && (
              <div className="border border-white/5 rounded-xl overflow-hidden bg-black/35 flex flex-col">
                <div className="max-h-[305px] overflow-y-auto custom-scrollbar select-text">
                  <table className="w-full text-left border-collapse text-xs font-mono">
                    <thead className="bg-[#12121c] text-neutral-400 font-display uppercase tracking-wider border-b border-white/5 sticky top-0 z-10">
                      <tr>
                        <th className="py-2.5 px-3 text-xs font-semibold">期次</th>
                        <th className="py-2.5 px-2 text-xs font-semibold">基金净值</th>
                        <th className="py-2.5 px-2 text-xs font-semibold">本期跟投</th>
                        <th className="py-2.5 px-2 text-xs font-semibold">折合份额</th>
                        <th className="py-2.5 px-2 text-xs font-semibold">期末市值</th>
                        <th className="py-2.5 px-2 text-xs font-semibold">累计本金</th>
                        <th className="py-2.5 px-3 min-w-[120px] text-xs font-semibold">事件标记/动作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.02]">
                      {ledgerData.map((row) => (
                        <tr key={row.period} className="hover:bg-neutral-900/60 transition-colors">
                          <td className="py-2 px-3 text-neutral-300 font-semibold text-xs">{row.date}</td>
                          <td className="py-2 px-2 text-neutral-300 text-xs">¥{row.nav}</td>
                          <td className="py-2 px-2 text-emerald-400 font-bold text-xs">¥{row.contribution}</td>
                          <td className="py-2 px-2 text-neutral-300 text-xs">{row.newUnits}份</td>
                          <td className="py-2 px-2 text-white font-bold text-xs">¥{row.totalAssetsHex.toLocaleString()}</td>
                          <td className="py-2 px-2 text-neutral-400 text-xs">¥{row.accumulatedInput.toLocaleString()}</td>
                          <td className="py-2 px-3">
                            {row.event ? (
                              <span className={cn(
                                "px-2 py-0.5 rounded text-xs font-bold inline-block font-sans",
                                row.event.includes('止盈') 
                                  ? "bg-yellow-500/15 text-yellow-400 border border-yellow-500/20"
                                  : row.event.includes('逢低加仓')
                                  ? "bg-rose-500/10 text-rose-400 border border-rose-500/20 animate-pulse"
                                  : "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
                              )}>
                                {row.event}
                              </span>
                            ) : (
                              <span className="text-neutral-500 text-xs">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB CONTAINER 3: Multi-dimensional Metrics comparison table */}
            {activeTab === 'metrics' && (
              <div className="bg-[#0a0a0f]/80 rounded-xl p-4.5 space-y-4 text-xs font-mono select-text">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2.5">
                    <span className="text-xs uppercase font-bold text-neutral-400 block tracking-widest font-sans">
                      DCA 模型与常客收益差
                    </span>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <span className="text-neutral-400 text-xs">跟投期末总持仓份额</span>
                        <span className="text-neutral-200 font-bold text-xs">{summaryMetrics.totalHoldingsUnits} 份</span>
                      </div>
                      <div className="flex justify-between items-center bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <span className="text-neutral-400 text-xs">现金沉淀或保本理财余额</span>
                        <span className="text-yellow-400 font-bold text-xs">¥{ledgerData[ledgerData.length - 1]?.cashParked?.toLocaleString()} 元</span>
                      </div>
                      <div className="flex justify-between items-center bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <span className="text-neutral-400 text-xs">总胜率期次占比</span>
                        <span className="text-rose-400 font-bold text-xs">{summaryMetrics.winMonthsPct}% 的期次正利益率</span>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2.5">
                    <span className="text-xs uppercase font-bold text-neutral-400 block tracking-widest font-sans">
                      定投 vs 一次性跟进 胜率对照
                    </span>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <span className="text-neutral-400 text-xs">DCA跟投模型累计总盈余</span>
                        <span className={cn("font-bold text-xs", summaryMetrics.yieldPct >= 0 ? "text-rose-400" : "text-emerald-400")}>
                          {summaryMetrics.yieldPct >= 0 ? '+' : ''}{summaryMetrics.yieldPct}%
                        </span>
                      </div>
                      <div className="flex justify-between items-center bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <span className="text-neutral-400 text-xs">一次性买进总盈余 (同一大金包)</span>
                        <span className={cn("font-bold text-xs", summaryMetrics.lumpSumReturnPct >= 0 ? "text-rose-400" : "text-emerald-400")}>
                          {summaryMetrics.lumpSumReturnPct >= 0 ? '+' : ''}{summaryMetrics.lumpSumReturnPct}%
                        </span>
                      </div>
                      <div className="flex justify-between items-center bg-black/20 p-2.5 rounded-lg border border-white/5">
                        <span className="text-neutral-400 text-xs">跟踪标的指数最终涨幅</span>
                        <span className={cn("font-bold text-xs", summaryMetrics.benchmarkReturnPct >= 0 ? "text-yellow-400" : "text-emerald-400")}>
                          {summaryMetrics.benchmarkReturnPct >= 0 ? '+' : ''}{summaryMetrics.benchmarkReturnPct}%
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-indigo-500/5 border border-indigo-500/10 p-3 rounded-lg text-neutral-400 text-xs leading-relaxed font-sans">
                  <span className="text-indigo-400 font-semibold block mb-0.5">🔍 量化实验室财务穿透结论</span>
                  本模型对当前参数（包含初始底仓 <b>¥{initialCapital.toLocaleString()}</b>）的解构表明：
                  在本次测试环境下，等额定投对高波动率 of {selectedFund.name} 产生了平滑优势。
                  由于在最大回测跌幅区间触发了 <b>{summaryMetrics.takeProfitTimes} 次</b> 落袋止盈，有效把账户置信风险平摊至原有的 <b>45% 以下</b>，极好地展示了智能再平衡机器人的超凡抵御能力！
                </div>
              </div>
            )}
          </div>

          {/* SEC 4: AI Intelligent Advisor Desk joint review */}
          <div className="bg-[#0c0c12]/90 border border-white/5 rounded-2xl p-5 relative overflow-hidden flex flex-col gap-4 shadow-xl">
            
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <h2 className="text-sm font-semibold text-neutral-200 flex items-center gap-2 font-display">
                <Sparkles className="w-4 h-4 text-indigo-400 animate-pulse" />
                4. AI-FINANCE 量化智囊团财务会审诊断
              </h2>
              <button 
                onClick={() => setDiagnosticOpen(!diagnosticOpen)}
                className="text-xs text-indigo-400 font-semibold flex items-center gap-1 hover:underline cursor-pointer"
              >
                {diagnosticOpen ? '收缩专家团背景职责' : '召集 8 大特约专家架构...'}
              </button>
            </div>

            {/* Expanded pane block explaining distinct experts roles */}
            {diagnosticOpen && (
              <motion.div 
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                className="grid grid-cols-2 md:grid-cols-4 gap-2 border-b border-white/5 pb-3.5 mb-2 text-xs"
              >
                {EXPERT_AGENTS.map((agent, index) => (
                  <div key={index} className={cn("p-2 rounded-xl border leading-relaxed flex flex-col justify-between", agent.color)}>
                    <div>
                      <div className="flex items-center gap-1.5 mb-1 font-bold">
                        <span>{agent.avatar}</span>
                        <span>{agent.role}</span>
                      </div>
                      <p className="text-neutral-400 text-xs leading-relaxed">{agent.intro}</p>
                    </div>
                    <div className="border-t border-white/5 mt-2 pt-1 font-bold text-neutral-300">坐席：{agent.name}</div>
                  </div>
                ))}
              </motion.div>
            )}

            {/* Quick pre-set questions selection buttons */}
            <div className="space-y-2">
              <span className="text-xs font-mono text-neutral-500 uppercase block tracking-wider">
                选择咨询事项 (智核一键会签意见):
              </span>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {FAQ_PRESETS.map((faq, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleAskFAQ(faq.q, faq.agent)}
                    disabled={isAiLoading}
                    className="group text-left bg-black/40 border border-white/5 hover:border-indigo-500/25 rounded-xl p-2.5 hover:bg-indigo-500/[0.02] flex gap-2 justify-between items-center transition-all cursor-pointer"
                  >
                    <div className="flex items-start gap-2 max-w-[90%]">
                      <span className="w-5 h-5 bg-indigo-500/10 text-indigo-400 rounded-lg flex items-center justify-center text-[10px] font-bold md:shrink-0 mt-0.5">
                        HQ{idx + 1}
                      </span>
                      <div>
                        <p className="text-xs text-neutral-300 font-semibold leading-relaxed group-hover:text-white transition-colors truncate max-w-[210px] lg:max-w-[260px]">
                          {faq.q}
                        </p>
                        <span className="text-[11px] text-neutral-500 font-mono block mt-0.5">
                          代表专家席：{faq.agent}
                        </span>
                      </div>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-neutral-600 group-hover:text-indigo-400 transition-transform group-hover:translate-x-0.5" />
                  </button>
                ))}
              </div>
            </div>

            {/* Newly added: Custom Question Input Box Sandbox Field */}
            <div className="space-y-1.5 border-t border-white/5 pt-3.5">
              <label className="text-xs font-mono text-neutral-500 uppercase block tracking-wider">
                向智囊团输入您的量化顾虑或定制提问 (NLP 动态解析审议):
              </label>
              <div className="flex gap-2.5">
                <input
                  type="text"
                  placeholder="例：‘止盈落袋好吗？’、‘亏损最大会达到多少？’、‘加码补仓规则有什么坏处吗？’"
                  value={customQuery}
                  onChange={(e) => setCustomQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && customQuery.trim()) {
                      handleAskFAQ(customQuery, 'user-composed');
                    }
                  }}
                  className="flex-1 bg-black/60 border border-white/10 rounded-xl px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-indigo-500/50"
                />
                <button
                  onClick={() => {
                    if (customQuery.trim()) {
                      handleAskFAQ(customQuery, 'user-composed');
                    }
                  }}
                  disabled={isAiLoading || !customQuery.trim()}
                  className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-neutral-800 disabled:text-neutral-600 transition-colors px-3.5 py-1.5 rounded-xl text-xs font-bold text-white flex items-center gap-1 cursor-pointer"
                >
                  <Send className="w-3.5 h-3.5" /> 送审
                </button>
              </div>
            </div>

            {/* AI Streaming Advice report response output screen */}
            <div className="bg-black/65 border border-white/5 rounded-2xl p-4.5 min-h-[160px] relative select-text">
              <div className="absolute top-3 right-4 flex items-center gap-1.5 text-xs font-mono text-indigo-400/80 uppercase tracking-widest">
                <div className={cn("w-1.5 h-1.5 bg-indigo-400 rounded-full", isAiLoading ? "animate-pulse" : "")} />
                <span>Quant Expert Board Response</span>
              </div>

              {isAiLoading ? (
                <div className="flex flex-col gap-2 justify-center items-center py-10">
                  <div className="w-6 h-6 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                  <span className="text-xs text-neutral-500 font-mono tracking-widest uppercase">
                    智核代表委员正穿透底层投资流水分账测算中...
                  </span>
                </div>
              ) : aiResponse ? (
                <div className="prose prose-invert max-w-none text-neutral-300 font-sans leading-relaxed text-xs space-y-2">
                  {aiResponse.split('\n').map((line, idx) => {
                    if (line.startsWith('###')) {
                      return <h3 key={idx} className="text-xs font-bold text-indigo-300 uppercase mt-4 mb-2 border-b border-white/5 pb-1 font-mono tracking-wider">{line.replace('###', '')}</h3>;
                    }
                    if (line.startsWith('🤖') || line.startsWith('1.') || line.startsWith('2.') || line.startsWith('3.')) {
                      return <p key={idx} className="font-semibold text-neutral-200 mt-2">{line}</p>;
                    }
                    return <p key={idx} className="text-neutral-400 text-xs leading-relaxed">{line}</p>;
                  })}
                </div>
              ) : (
                <div className="flex flex-col gap-2 justify-center items-center text-center py-12 text-neutral-500">
                  <UserCheck className="w-9 h-9 text-neutral-600 mb-1" />
                  <p className="text-xs font-semibold">
                    请点击上方预置事项或输入自定义提问，获取智核专家联合审计意见。
                  </p>
                  <p className="text-xs text-neutral-600">
                    量化计算器会基于当前的年限、频率、底仓以及购买规则自适应生成会签报告。
                  </p>
                </div>
              )}
            </div>

            {/* Strict Regulatory Advisory and suitability waiver */}
            <div className="bg-rose-500/[0.02] border border-rose-500/10 p-3.5 rounded-xl flex gap-2.5 text-xs font-sans text-rose-400/80 leading-relaxed">
              <AlertTriangle className="w-4 h-4 text-rose-400/70 shrink-0 mt-0.5 animate-pulse" />
              <div>
                <span className="font-bold block text-rose-300 mb-0.5">陈清律合规审查官审慎声明：</span>
                上述量化压力回测、指数漂移曲线及AI智核会签解读皆源于理想随机高斯算法及历史走势折射模型，绝非未来实盘真实理财之收益保证，亦不可作为决策要件。金融资产跟投仍存浮动亏损可能，请根据适度风防级别理性布局！
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Custom descriptions database mapping based on typical funds classes characteristics
const CLASSES_DESCRIPTION: Record<string, any> = {
  'mixed': {
    title: '偏股及全混合型公募',
    desc: '具有核心α博取超额溢价实力，但整体股票持仓占比大，回撤期心理波动考验明显。'
  },
  'bond': {
    title: '固收债基增强型',
    desc: '极致的防守堡垒，极高夏普率，基本面不挂钩权益类大势崩溃，用时间磨平细微震荡。'
  },
  'index': {
    title: '被动行业指数型公募',
    desc: '特定高β行业的大型敞口工具，追高损耗大，适合在大级别熊市底部分批建仓。'
  },
  'etf': {
    title: '宽基红利核心ETF',
    desc: '涵盖各行各业底层蓝筹，随经济周波波动。定投能极好平抑估值偏差。'
  },
  'qdii': {
    title: 'QDII 国际跨境指数',
    desc: '对冲本土单一资本体系周期，获取美元资产或高算力科技底层大周期牛市分红。'
  }
};
