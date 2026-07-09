import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Bot, Maximize2, RefreshCw, Send, Settings2, Sparkles, ChevronDown, ImagePlus } from 'lucide-react';
import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Cell, Tooltip } from 'recharts';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { ChatMessage } from '../types';
import { STOCK_UNIVERSE, StockTarget, findStockTarget, formatStockLabel, resolveStockTarget } from '../lib/stocks';
import { getPersistedStock, subscribeStockSelected, subscribeSettingsChanged } from '../lib/workspaceEvents';
import { fetchApi, API_BASE_URL, API_KEY, LOCAL_API_TOKEN } from '../lib/api';
import {
  buildModelOptions,
  getModelKey,
  getRouteSelection,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
  ModelProvider,
} from '../lib/aiModelRouting';
import { ThemedSelect } from './ThemedSelect';
import { StableChartContainer } from './StableChartContainer';
import { SyntheticDataBanner } from './SyntheticDataBanner';
import {
  isLivePriceFeed,
  isSyntheticPriceFeed,
  resolvePriceFeed,
  type PriceFeed,
} from '../lib/priceFeed';
import {
  type WorkbenchChartPoint,
  type PriceBar,
  type PriceSeriesResponse,
  type KlinePeriod,
  type CustomKlineFrequency,
  type MetricCard,
  type PanelNewsItem,
  type FundamentalsResponse,
  type FundFlowResponse,
  type FactorResponse,
  type NewsListResponse,
  type AnalysisModeId,
  type PanelTabId,
  type ChatResponse,
  PERIOD_BUTTONS,
  CUSTOM_FREQUENCY_OPTIONS,
  LOADING_FINANCE_CARDS,
  LOADING_FUND_CARDS,
  LOADING_QUANT_CARDS,
  ANALYSIS_MODES,
  PANEL_TABS,
  getCustomLimitOptions,
  generateKlineData,
  getErrorMessage,
  formatMessageHtml,
  stripSymbolSuffix,
  formatAxisDate,
  getMinimumPeriodBars,
  shouldShowMovingAverage,
  formatPricePayloadMessage,
  formatPrice,
  formatVolume,
  metricToneClass,
  sourceStatusLabel,
  emptyCards,
  buildFinanceCards,
  buildFundFlowCards,
  buildQuantCards,
  buildNewsItems,
  getWorkbenchPriceDomain,
  enrichWorkbenchData,
  getPeriodConfig,
  getPeriodTestId,
  type WorkbenchProps,
} from './workbench/support';
import {
  WorkbenchChartTooltip,
  CompactWorkbenchTooltip,
  WorkbenchCandlestick,
} from './workbench/chartParts';
import { WorkbenchAiPanel } from './workbench/WorkbenchAiPanel';

// 专业 K 线懒加载, 把 lightweight-charts 拆出主包(Workbench 是默认页, 仍是首屏并行加载的独立分块)。
const LightweightKLine = lazy(() => import('./LightweightKLine').then((m) => ({ default: m.LightweightKLine })));

export function Workbench({ onOpenModelSettings }: WorkbenchProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const previousChartPeriodKeyRef = useRef<string | undefined>(undefined);
  const [currentStock, setCurrentStock] = useState<StockTarget>(() => getPersistedStock() ?? STOCK_UNIVERSE[0]);
  const [activePeriod, setActivePeriod] = useState<KlinePeriod>('日K');
  const [customFrequency, setCustomFrequency] = useState<CustomKlineFrequency>('1d');
  const [customLimit, setCustomLimit] = useState('120');
  const [activePanelTab, setActivePanelTab] = useState<PanelTabId>('news');
  const [chartData, setChartData] = useState(() => generateKlineData(40, currentStock.startPrice));
  // K 线渲染模式:专业(Lightweight Charts)↔ 经典(recharts 自绘)。只增不替。
  const [klineRenderer, setKlineRenderer] = useState<'pro' | 'classic'>('pro');
  const [analysisMode, setAnalysisMode] = useState<AnalysisModeId>('standard');
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [autoEvidence, setAutoEvidence] = useState(true);
  const [strictRisk, setStrictRisk] = useState(true);
  const [lastUploadedFile, setLastUploadedFile] = useState('');
  const [chatProviders, setChatProviders] = useState<ModelProvider[]>([]);
  const [selectedChatModelKey, setSelectedChatModelKey] = useState('');
  const [conversationId, setConversationId] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatStatus, setChatStatus] = useState('正在读取系统设置中的模型配置...');
  const [latestQuote, setLatestQuote] = useState<WorkbenchChartPoint | undefined>();
  const [hoveredChartPoint, setHoveredChartPoint] = useState<WorkbenchChartPoint | undefined>();
  const [priceFeed, setPriceFeed] = useState<PriceFeed>('loading');
  const [priceMessage, setPriceMessage] = useState('正在同步行情...');
  const [priceRefreshKey, setPriceRefreshKey] = useState(0);
  const [financeCards, setFinanceCards] = useState<MetricCard[]>(LOADING_FINANCE_CARDS);
  const [fundFlowCards, setFundFlowCards] = useState<MetricCard[]>(LOADING_FUND_CARDS);
  const [quantCards, setQuantCards] = useState<MetricCard[]>(LOADING_QUANT_CARDS);
  const [stockNews, setStockNews] = useState<PanelNewsItem[]>([]);
  const [infoStatus, setInfoStatus] = useState<Record<PanelTabId, string>>({
    news: '正在同步当前标的资讯...',
    finance: '正在同步基本面数据...',
    funds: '正在同步主力资金...',
    quant: '正在计算量化因子...',
  });
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'agent',
      agentName: 'System',
      content: `欢迎使用研策中枢 AlphaScope 多 Agent 分析工作台。当前标的：**${currentStock.name}** (${currentStock.symbol})。请选择分析模式并输入问题。`,
      timestamp: new Date().toISOString(),
    }
  ]);
  const [input, setInput] = useState('');
  const fallbackPrice = currentStock.startPrice;
  const selectedMode = ANALYSIS_MODES.find((mode) => mode.id === analysisMode) ?? ANALYSIS_MODES[0];
  const chatModelOptions = useMemo(() => buildModelOptions(chatProviders, 'chat'), [chatProviders]);
  const selectedChatModel = useMemo(
    () => chatModelOptions.find((option) => option.key === selectedChatModelKey) ?? chatModelOptions[0],
    [chatModelOptions, selectedChatModelKey],
  );
  const customLimitOptions = useMemo(() => getCustomLimitOptions(customFrequency), [customFrequency]);
  const activePeriodConfig = useMemo(
    () => getPeriodConfig(activePeriod, customFrequency, customLimit),
    [activePeriod, customFrequency, customLimit],
  );
  const activePeriodLabel = activePeriodConfig.label;
  const axisPeriod = activePeriodConfig.axisPeriod;
  const canSendChat = Boolean(input.trim() && selectedChatModel && !chatLoading);
  const chartLastPoint = chartData[chartData.length - 1];
  const lastChartPoint = activePeriodConfig.frequency === 'intraday' ? (latestQuote ?? chartLastPoint) : chartLastPoint;
  const displayPrice = lastChartPoint?.close ?? fallbackPrice;
  const displayChange = lastChartPoint?.changePct ?? 0;
  const displayIsUp = displayChange >= 0;
  const isPeriodDataTooShort = chartData.length > 0 && chartData.length < getMinimumPeriodBars(activePeriodConfig.frequency);
  const chartStats = useMemo(() => {
    const lastPoint = chartData[chartData.length - 1];
    const ma5 = lastPoint?.ma5 ?? fallbackPrice;
    const ma10 = lastPoint?.ma10 ?? fallbackPrice;
    const ma20 = lastPoint?.ma20 ?? fallbackPrice;
    const values = chartData.flatMap((point) => [point.high, point.low, point.ma5, point.ma10, point.ma20]);
    const validValues = values.filter((value) => Number.isFinite(value));
    const max = validValues.length ? Math.max(...validValues) : fallbackPrice;
    const min = validValues.length ? Math.min(...validValues) : fallbackPrice;
    const volume = lastPoint?.volume ?? 0;
    return {
      ma5,
      ma10,
      ma20,
      high: max,
      low: min,
      volume,
    };
  }, [chartData, fallbackPrice]);
  const priceDomain = useMemo(
    () => getWorkbenchPriceDomain(chartData, fallbackPrice),
    [chartData, fallbackPrice],
  );
  const isSyntheticPreview = isSyntheticPriceFeed(priceFeed);
  const priceSourceLabel =
    priceFeed === 'live'
      ? `${lastChartPoint?.source || 'provider'} · ${lastChartPoint?.date || ''}`
      : priceFeed === 'live_degraded'
        ? `真实行情(源降级) · ${priceMessage}`
        : priceMessage;
  const chartSourceLabel = isPeriodDataTooShort
    ? `${activePeriodLabel}样本不足，仅显示上市以来可用K线`
    : isSyntheticPreview
      ? `演示/预览数据（非真实行情）· ${priceMessage}`
      : priceSourceLabel;
  const displayChartPoint = hoveredChartPoint ?? lastChartPoint;
  const displayChartPointUp = (displayChartPoint?.change ?? 0) >= 0;
  const showMa5Line = shouldShowMovingAverage(activePeriodConfig.frequency, chartData.length, 5);
  const showMa10Line = shouldShowMovingAverage(activePeriodConfig.frequency, chartData.length, 10);
  const showMa20Line = shouldShowMovingAverage(activePeriodConfig.frequency, chartData.length, 20);

  const handleChartMouseMove = (state: any) => {
    const point = state?.activePayload?.find((item: any) => item?.payload)?.payload as WorkbenchChartPoint | undefined;
    if (point) setHoveredChartPoint(point);
  };
  const handlePanelTabChange = (tabId: PanelTabId) => {
    setActivePanelTab(tabId);
  };

  const handlePanelItemSelect = (title: string, detail: string) => {
    appendSystemMessage(`已选中 **${currentStock.name}** 的信息卡片：**${title}**。\n${detail}\n\n下一步建议：把该信息与公告、价格行为、资金流和证据链进行交叉核验。`);
  };

  const appendSystemMessage = (content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `system-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: 'agent',
        agentName: 'System',
        content,
        timestamp: new Date().toISOString(),
      },
    ]);
  };

  const [providersReloadKey, setProvidersReloadKey] = useState(0);
  useEffect(() => {
    const unsub = subscribeSettingsChanged(() => setProvidersReloadKey((k) => k + 1));
    return unsub;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadChatProviders() {
      try {
        const result = await fetchApi<{ providers: ModelProvider[] }>('/api/settings/providers');
        if (cancelled) return;
        const providers = result.providers || [];
        const options = buildModelOptions(providers, 'chat');
        const routes = await loadAiModelRoutesFromApi().catch(() => loadLocalAiModelRoutes());
        const chatRoute = getRouteSelection(routes, providers, 'chat');
        const routeKey = getModelKey(chatRoute);
        setChatProviders(providers);
        setSelectedChatModelKey((current) => (
          current && options.some((option) => option.key === current)
            ? current
            : routeKey && options.some((option) => option.key === routeKey)
              ? routeKey
              : options[0]
                ? options[0].key
              : ''
        ));
        setChatStatus(
          options.length
            ? `已连接系统设置 Provider，共 ${options.length} 个可用聊天模型`
            : '没有可用聊天模型，请先到系统设置添加 Provider 并获取模型列表',
        );
      } catch (error) {
        if (cancelled) return;
        setChatProviders([]);
        setSelectedChatModelKey('');
        setChatStatus(`模型配置读取失败：${getErrorMessage(error)}`);
      }
    }

    loadChatProviders();
    return () => {
      cancelled = true;
    };
  }, [providersReloadKey]);

  useEffect(() => {
    return subscribeStockSelected(({ stock }) => {
      const resolved = stock.resolved || stock.source === 'backend'
        ? stock
        : findStockTarget(stock.symbol) ?? stock;
      setCurrentStock(resolved);
      setMessages((prev) => [
        ...prev.map((msg) => msg.id === 'welcome'
          ? {
              ...msg,
              content: `欢迎使用研策中枢 AlphaScope 多 Agent 分析工作台。当前标的：**${resolved.name}** (${resolved.symbol})。请选择分析模式并输入问题。`,
            }
          : msg),
        {
          id: `stock-${Date.now()}`,
          role: 'agent',
          agentName: 'System',
          content: `已切换研究标的：**${resolved.name}** (${resolved.symbol})。行情、资金与多 Agent 分析上下文已同步。`,
          timestamp: new Date().toISOString(),
        },
      ]);
    });
  }, []);

  useEffect(() => {
    if (currentStock.resolved || currentStock.source === 'backend') return;
    let cancelled = false;
    const code = stripSymbolSuffix(currentStock.symbol);
    void resolveStockTarget(code).then((resolved) => {
      if (cancelled || !resolved) return;
      if (resolved.symbol !== currentStock.symbol || resolved.name !== currentStock.name || resolved.source !== currentStock.source || resolved.resolved !== currentStock.resolved) {
        setCurrentStock(resolved);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [currentStock]);

  useEffect(() => {
    if (customLimitOptions.some((option) => option.value === customLimit)) return;
    setCustomLimit(customLimitOptions[1]?.value ?? customLimitOptions[0]?.value ?? '120');
  }, [customLimit, customLimitOptions]);

  useEffect(() => {
    let cancelled = false;
    const period = activePeriodConfig;
    const fallback = generateKlineData(period.points, currentStock.startPrice, period.stepDays, period.stepMinutes ?? 0);
    const chartPeriodKey = [
      currentStock.symbol,
      period.frequency,
      period.limit,
      period.points,
      period.stepDays,
      period.stepMinutes ?? 0,
    ].join('|');
    if (previousChartPeriodKeyRef.current !== chartPeriodKey) {
      previousChartPeriodKeyRef.current = chartPeriodKey;
      setChartData(fallback);
      setHoveredChartPoint(undefined);
      if (period.frequency !== 'intraday') {
        setLatestQuote(undefined);
      }
    }

    async function loadPrices() {
      setPriceFeed('loading');
      setPriceMessage('正在同步真实行情...');
      try {
        const symbol = encodeURIComponent(stripSymbolSuffix(currentStock.symbol));
        const payload = await fetchApi<PriceSeriesResponse>(
          `/api/prices/${symbol}?frequency=${period.frequency}&limit=${period.limit}`,
        );
        if (cancelled) return;
        const hasBars = Boolean(payload.bars?.length);
        const nextData = hasBars ? enrichWorkbenchData(payload.bars!) : fallback;
        let nextQuote = nextData[nextData.length - 1];
        if (period.frequency === 'intraday') {
          try {
            const latest = await fetchApi<PriceBar>(`/api/prices/${symbol}/latest`);
            if (!cancelled && latest?.close) {
              nextQuote = enrichWorkbenchData([latest])[0];
              nextQuote.changePct = Number((latest.change_pct || nextQuote.changePct || 0).toFixed(2));
              setLatestQuote(nextQuote);
            }
          } catch {
            if (!cancelled) setLatestQuote(nextQuote);
          }
        } else {
          setLatestQuote(undefined);
        }
        if (cancelled) return;
        setChartData(nextData);
        setPriceFeed(resolvePriceFeed({ hasBars, backendDegraded: payload.degraded }));
        if (hasBars) {
          setPriceMessage(formatPricePayloadMessage(payload, activePeriodLabel));
        } else {
          setPriceMessage('行情源暂无数据，已切换本地预览');
          setLatestQuote(undefined);
        }
      } catch (error) {
        if (cancelled) return;
        setChartData(fallback);
        setLatestQuote(undefined);
        setPriceFeed('synthetic');
        setPriceMessage(error instanceof Error ? error.message : '行情获取失败，已切换本地预览');
      }
    }

    void loadPrices();
    return () => {
      cancelled = true;
    };
  }, [activePeriodConfig, activePeriodLabel, currentStock, priceRefreshKey]);

  useEffect(() => {
    let cancelled = false;
    const symbol = encodeURIComponent(stripSymbolSuffix(currentStock.symbol));
    const stockName = encodeURIComponent(currentStock.name);

    setFinanceCards(LOADING_FINANCE_CARDS);
    setFundFlowCards(LOADING_FUND_CARDS);
    setQuantCards(LOADING_QUANT_CARDS);
    setStockNews([]);
    setInfoStatus({
      news: `正在同步 ${currentStock.name} 的资讯...`,
      finance: `正在同步 ${currentStock.name} 的基本面...`,
      funds: `正在同步 ${currentStock.name} 的主力资金...`,
      quant: `正在计算 ${currentStock.name} 的量化因子...`,
    });

    async function loadInformationPanels() {
      const [newsResult, fundamentalsResult, fundFlowResult, factorResult] = await Promise.allSettled([
        fetchApi<NewsListResponse>(`/api/news?symbol=${symbol}&limit=6`),
        fetchApi<FundamentalsResponse>(`/api/fundamentals/${symbol}`),
        fetchApi<FundFlowResponse>(`/api/fund-flow/${symbol}?days=30`),
        fetchApi<FactorResponse>(`/api/factors/${symbol}?stock_name=${stockName}&days=30`),
      ]);

      if (cancelled) return;

      if (newsResult.status === 'fulfilled') {
        const items = buildNewsItems(newsResult.value);
        setStockNews(items);
        setInfoStatus((prev) => ({
          ...prev,
          news: items.length
            ? `${sourceStatusLabel(newsResult.value.source_status, newsResult.value.degraded)} · ${items.length} 条资讯`
            : `${sourceStatusLabel(newsResult.value.source_status || 'empty', true)} · 当前标的暂无可用资讯`,
        }));
      } else {
        setStockNews([]);
        setInfoStatus((prev) => ({
          ...prev,
          news: `资讯源不可用：${getErrorMessage(newsResult.reason)}`,
        }));
      }

      if (fundamentalsResult.status === 'fulfilled') {
        const payload = fundamentalsResult.value;
        setFinanceCards(buildFinanceCards(payload));
        const period = payload.financial_periods?.[0]?.period;
        setInfoStatus((prev) => ({
          ...prev,
          finance: `${sourceStatusLabel(payload.source_status, payload.degraded)}${period ? ` · 报告期 ${period}` : ''}`,
        }));
      } else {
        setFinanceCards(emptyCards(getErrorMessage(fundamentalsResult.reason)));
        setInfoStatus((prev) => ({
          ...prev,
          finance: `基本面源不可用：${getErrorMessage(fundamentalsResult.reason)}`,
        }));
      }

      if (fundFlowResult.status === 'fulfilled') {
        const payload = fundFlowResult.value;
        setFundFlowCards(buildFundFlowCards(payload));
        const lastDate = payload.summary?.last_date;
        setInfoStatus((prev) => ({
          ...prev,
          funds: `${sourceStatusLabel(payload.source_status, payload.degraded)} · ${payload.source || 'eastmoney'}${lastDate ? ` · ${lastDate}` : ''}`,
        }));
      } else {
        setFundFlowCards(emptyCards(getErrorMessage(fundFlowResult.reason)));
        setInfoStatus((prev) => ({
          ...prev,
          funds: `资金源不可用：${getErrorMessage(fundFlowResult.reason)}`,
        }));
      }

      if (factorResult.status === 'fulfilled') {
        const payload = factorResult.value;
        setQuantCards(buildQuantCards(payload));
        const degradedText = payload.degraded_inputs?.length
          ? ` · 降级输入 ${payload.degraded_inputs.join(', ')}`
          : '';
        setInfoStatus((prev) => ({
          ...prev,
          quant: `近30日因子 · ${payload.computed_at?.slice(0, 19).replace('T', ' ') || '已计算'}${degradedText}`,
        }));
      } else {
        setQuantCards(emptyCards(getErrorMessage(factorResult.reason)));
        setInfoStatus((prev) => ({
          ...prev,
          quant: `因子计算失败：${getErrorMessage(factorResult.reason)}`,
        }));
      }
    }

    void loadInformationPanels();
    return () => {
      cancelled = true;
    };
  }, [currentStock, priceRefreshKey]);

  const handlePeriodChange = (period: KlinePeriod) => {
    setActivePeriod(period);
  };

  const handleModeChange = (mode: AnalysisModeId) => {
    const nextMode = ANALYSIS_MODES.find((item) => item.id === mode) ?? ANALYSIS_MODES[0];
    setAnalysisMode(mode);
    setModeMenuOpen(false);
    appendSystemMessage(`分析模式已切换为 **${nextMode.label}**。\n${nextMode.desc}。`);
  };

  const handleRefreshChart = () => {
    setPriceRefreshKey((value) => value + 1);
    appendSystemMessage(`已刷新 **${currentStock.name}** (${currentStock.symbol}) 的${activePeriodLabel}行情，并同步更新均线、成交量与资金标签。`);
  };

  const handleFullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        appendSystemMessage('已退出全屏研究模式。');
      } else {
        await document.documentElement.requestFullscreen();
        appendSystemMessage('已进入全屏研究模式，适合进行盘中盯盘或投研展示。');
      }
    } catch {
      appendSystemMessage('当前浏览器未允许全屏切换，请检查浏览器权限或手动使用 F11。');
    }
  };

  const handleUploadContext = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      appendSystemMessage(`正在上传 **${file.name}** 到知识库，请稍候...`);
      const formData = new FormData();
      formData.append('file', file);
      const headers = new Headers();
      if (API_KEY) {
        headers.set('X-API-Key', API_KEY);
      }
      if (LOCAL_API_TOKEN) {
        headers.set('X-AlphaScope-Local-Token', LOCAL_API_TOKEN);
      }

      const response = await fetch(`${API_BASE_URL}/api/knowledge/upload`, {
        method: 'POST',
        headers,
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));

      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error || `HTTP ${response.status} ${response.statusText}`);
      }

      const uploadedName = payload?.data?.filename || file.name;
      setLastUploadedFile(uploadedName);
      appendSystemMessage(`已上传并索引：**${uploadedName}**。\n${payload?.message || '文件上传并处理成功'}`);
    } catch (error) {
      appendSystemMessage(`知识库上传失败：**${file.name}**\n${getErrorMessage(error)}`);
    } finally {
      event.target.value = '';
    }
  };

  const handleSend = async () => {
    const prompt = input.trim();
    if (!prompt || chatLoading) return;

    if (!selectedChatModel) {
      appendSystemMessage('当前没有可用聊天模型。请先到系统设置中添加 Provider、检查连通性并获取模型列表。');
      return;
    }

    const now = Date.now();
    const userMsg: ChatMessage = {
      id: `user-${now}`,
      role: 'user',
      content: prompt,
      timestamp: new Date().toISOString(),
    };
    const pendingId = `assistant-pending-${now}`;
    const pendingMsg: ChatMessage = {
      id: pendingId,
      role: 'agent',
      agentName: `${selectedChatModel.providerName}/${selectedChatModel.modelId}`,
      content: `正在调用真实模型：**${selectedChatModel.providerName} / ${selectedChatModel.modelId}**\n\n已注入当前标的、行情沙盘、资金和分析模式上下文。`,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setInput('');
    setChatLoading(true);
    setChatStatus(`正在调用 ${selectedChatModel.providerName} / ${selectedChatModel.modelId}...`);

    try {
      const result = await fetchApi<ChatResponse>('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          conversation_id: conversationId || undefined,
          message: prompt,
          mode: 'free',
          stock_symbol: currentStock.symbol,
          stock_name: currentStock.name,
          provider: selectedChatModel.providerId,
          model: selectedChatModel.modelId,
          context: {
            close: displayPrice,
            day_change: displayChange,
            period_change: displayChange,
            ma5: Number(chartStats.ma5.toFixed(2)),
            ma20: Number(chartStats.ma20.toFixed(2)),
            ma60: Number(chartStats.ma20.toFixed(2)),
            fund_dir: fundFlowCards.map((item) => `${item.label}: ${item.value}`).join('；'),
            fundamentals: financeCards.map((item) => `${item.label}: ${item.value} (${item.detail})`).join('；'),
            factor_context: quantCards.map((item) => `${item.label}: ${item.value} (${item.detail})`).join('；'),
            data_date: new Date().toLocaleDateString('zh-CN'),
            analysis_mode: selectedMode.label,
            auto_evidence: autoEvidence,
            strict_risk: strictRisk,
          },
        }),
      });

      if (result.conversation_id) {
        setConversationId(result.conversation_id);
      }

      const responseProvider = result.provider || selectedChatModel.providerId;
      const responseModel = result.model || selectedChatModel.modelId;
      const modelLine = `模型调用：**${responseProvider} / ${responseModel}**`;
      const content = result.content?.trim()
        ? `${modelLine}\n\n${result.content.trim()}`
        : `${modelLine}\n\n模型没有返回内容。请检查该 Provider 的模型权限、余额或 Base URL。`;

      setMessages((prev) => prev.map((msg) => (
        msg.id === pendingId
          ? {
              ...msg,
              agentName: `${responseProvider}/${responseModel}`,
              content,
              timestamp: new Date().toISOString(),
            }
          : msg
      )));
      setChatStatus(`上次调用成功：${responseProvider} / ${responseModel}`);
    } catch (error) {
      const message = getErrorMessage(error);
      setMessages((prev) => prev.map((msg) => (
        msg.id === pendingId
          ? {
              ...msg,
              agentName: '模型调用失败',
              content: `模型调用失败：${message}\n\n这不是模拟回复。请检查系统设置中的 Provider、Base URL、API Key、模型名称和网络连通性。`,
              timestamp: new Date().toISOString(),
            }
          : msg
      )));
      setChatStatus(`模型调用失败：${message}`);
    } finally {
      setChatLoading(false);
    }
  };
  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="mx-auto max-w-[1600px] p-6 text-neutral-300 lg:p-8"
    >
      {/* Top Header */}
      <div className="relative z-10 mb-8 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="mb-3 flex min-w-0 flex-wrap items-center gap-3 text-2xl font-medium tracking-tight text-white sm:text-3xl">
            {currentStock.name}
            <span className="shrink-0 rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 font-mono text-xs font-medium tracking-wider text-neutral-300">{currentStock.symbol}</span>
          </h1>
          <div className={cn('flex min-w-0 flex-wrap items-baseline gap-3', displayIsUp ? 'text-rose-500' : 'text-emerald-500')}>
            <span className={cn('font-mono text-3xl font-medium tracking-tight sm:text-4xl', displayIsUp ? 'drop-shadow-[0_0_15px_rgba(244,63,94,0.3)]' : 'drop-shadow-[0_0_15px_rgba(16,185,129,0.25)]')}>
              {formatPrice(displayPrice)}
            </span>
            <span className={cn('flex items-center rounded border px-2 py-0.5 font-mono text-sm font-medium', displayIsUp ? 'border-rose-500/20 bg-rose-500/10 text-rose-500' : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500')}>
              <span className="rotate-45 mr-1 text-lg leading-none">{displayIsUp ? '↗' : '↘'}</span>{displayIsUp ? '+' : ''}{displayChange.toFixed(2)}%
            </span>
            <span className={cn('max-w-[22rem] truncate rounded border px-2 py-0.5 align-middle font-mono text-[10px]', isLivePriceFeed(priceFeed) ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/20 bg-amber-500/10 text-amber-300')}>
              {priceFeed === 'loading' ? '同步中' : priceSourceLabel}
            </span>
          </div>
        </div>

        <div className="grid w-full grid-cols-2 gap-3 sm:grid-cols-4 md:w-auto md:max-w-[48rem]">
          {financeCards.slice(0, 4).map((item, i) => (
            <div key={`${item.label}-${i}`} title={item.detail} className="flex min-w-0 flex-col rounded-xl border border-white/5 bg-white/[0.03] px-4 py-3 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:bg-white/[0.05]">
              <span className="mb-1.5 truncate text-xs text-neutral-500">{item.label}</span>
              <span className={cn("truncate text-sm font-mono font-medium tracking-wide", metricToneClass(item.tone))}>
                {item.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8 relative z-10">
        {/* Left Column: Chart & Info */}
        <div className="xl:col-span-2 flex flex-col gap-8">
          {/* Chart Panel */}
          <div className="flex h-[500px] min-h-0 flex-col overflow-hidden rounded-2xl border border-white/5 bg-white/[0.04] shadow-2xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 bg-white/[0.01] px-5 py-4">
              <div className="flex items-center gap-3">
                 <h2 className="font-semibold text-neutral-200">行情走势</h2>
                 <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-[pulse_2s_ease-in-out_infinite] shadow-[0_0_5px_rgba(16,185,129,0.5)]"></span>
                 <span className="hidden max-w-[18rem] truncate rounded border border-white/10 bg-black/30 px-2 py-0.5 font-mono text-[10px] text-neutral-500 sm:inline">
                   {priceFeed === 'loading' ? '正在同步行情' : chartSourceLabel}
                 </span>
              </div>
              <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleRefreshChart}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/40 text-neutral-400 transition-colors hover:bg-white/[0.05] hover:text-neutral-200"
                title="刷新行情"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', priceFeed === 'loading' && 'animate-spin')} />
              </button>
              <div className="flex flex-wrap rounded-lg border border-white/5 bg-black/40 p-1 shadow-inner">
                {PERIOD_BUTTONS.map((period) => (
                  <button 
                    key={period}
                    data-testid={getPeriodTestId(period)}
                    onClick={() => handlePeriodChange(period)}
                    className={cn(
                      "px-3 py-1.5 text-xs rounded-md font-medium transition-all cursor-pointer sm:px-5",
                      activePeriod === period ? "bg-white/10 text-white shadow-sm border border-white/10" : "text-neutral-500 hover:text-neutral-300 border border-transparent"
                    )}
                  >
                    {period}
                  </button>
                ))}
              </div>
              {activePeriod === '自定义' && (
                <div className="flex items-center gap-2 rounded-lg border border-white/5 bg-black/40 p-1 shadow-inner">
                  <ThemedSelect
                    value={customFrequency}
                    options={CUSTOM_FREQUENCY_OPTIONS}
                    onChange={(value) => setCustomFrequency(value as CustomKlineFrequency)}
                    ariaLabel="自定义K线粒度"
                    testId="workbench-custom-frequency"
                    className="w-[86px]"
                    buttonClassName="h-8 rounded-md border-transparent bg-transparent px-2 text-xs"
                    menuClassName="text-xs"
                    align="right"
                  />
                  <ThemedSelect
                    value={customLimit}
                    options={customLimitOptions}
                    onChange={setCustomLimit}
                    ariaLabel="自定义K线窗口"
                    testId="workbench-custom-limit"
                    className="w-[86px]"
                    buttonClassName="h-8 rounded-md border-transparent bg-transparent px-2 text-xs"
                    menuClassName="text-xs"
                    align="right"
                  />
                </div>
              )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/5 bg-black/20 px-5 py-3 font-mono text-[11px]">
               <span className={cn('flex items-center gap-2', showMa5Line ? 'text-yellow-500/90' : 'text-neutral-600')}><div className={cn('h-0.5 w-2', showMa5Line ? 'bg-yellow-500/90' : 'bg-neutral-700')}></div>MA5: {showMa5Line ? formatPrice(chartStats.ma5) : '--'}</span>
               <span className={cn('flex items-center gap-2', showMa10Line ? 'text-indigo-400/90' : 'text-neutral-600')}><div className={cn('h-0.5 w-2', showMa10Line ? 'bg-indigo-400/90' : 'bg-neutral-700')}></div>MA10: {showMa10Line ? formatPrice(chartStats.ma10) : '--'}</span>
               <span className={cn('flex items-center gap-2', showMa20Line ? 'text-emerald-400/90' : 'text-neutral-600')}><div className={cn('h-0.5 w-2', showMa20Line ? 'bg-emerald-400/90' : 'bg-neutral-700')}></div>MA20: {showMa20Line ? formatPrice(chartStats.ma20) : '--'}</span>
               <div className="flex rounded-md border border-white/5 bg-black/30 p-0.5" title="K线渲染模式">
                 {([['pro', '专业'], ['classic', '经典']] as Array<['pro' | 'classic', string]>).map(([mode, label]) => (
                   <button
                     key={mode}
                     onClick={() => setKlineRenderer(mode)}
                     className={cn('rounded px-2 py-0.5 text-[10px]', klineRenderer === mode ? 'bg-white/10 text-white' : 'text-neutral-500 hover:text-neutral-300')}
                   >
                     {label}
                   </button>
                 ))}
               </div>
               {displayChartPoint && (
                 <span className="min-w-0 truncate rounded border border-white/10 bg-white/[0.03] px-2 py-1 text-neutral-400">
                   {displayChartPoint.date} · 收 {formatPrice(displayChartPoint.close)} · <span className={displayChartPointUp ? 'text-rose-400' : 'text-emerald-400'}>{displayChartPointUp ? '+' : ''}{displayChartPoint.changePct.toFixed(2)}%</span>
                 </span>
               )}
               {isPeriodDataTooShort && (
                 <span className="min-w-0 truncate rounded border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-amber-300">
                   {activePeriodLabel}样本不足：仅 {chartData.length} 根，可能是新股或行情源历史较短
                 </span>
               )}
               <span className="text-neutral-500 sm:ml-auto">VOL: {formatVolume(chartStats.volume)}</span>
            </div>

            {/* Chart Area */}
            <motion.div
              key={`kline-${currentStock.symbol}-${activePeriodConfig?.label}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, ease: 'easeOut' }}
              className="relative h-[360px] min-h-[320px] bg-black/40 p-5"
            >
               {isSyntheticPreview && <SyntheticDataBanner testId="workbench-synthetic-banner" />}
               <div className="pointer-events-none absolute right-6 top-6 text-[10px] font-mono text-neutral-600">{formatPrice(chartStats.high)}</div>
               <div className="pointer-events-none absolute right-6 bottom-24 text-[10px] font-mono text-neutral-600">{formatPrice(chartStats.low)}</div>

             <div className="h-[calc(100%-72px)] min-h-[240px]">
               {klineRenderer === 'pro' ? (
                 <Suspense fallback={<div className="flex h-full items-center justify-center text-xs text-neutral-600">专业K线加载中…</div>}>
                   <LightweightKLine data={chartData} showMa5={showMa5Line} showMa10={showMa10Line} showMa20={showMa20Line} />
                 </Suspense>
               ) : (
               <StableChartContainer>
                 <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }} onMouseMove={handleChartMouseMove}>
                   <CartesianGrid stroke="#ffffff" strokeOpacity={0.03} strokeDasharray="4 4" vertical={false} />
                   <XAxis dataKey="date" tickFormatter={(value) => formatAxisDate(String(value), axisPeriod)} hide />
                   <YAxis domain={priceDomain} hide />
                   <Tooltip
                     content={<CompactWorkbenchTooltip />}
                     offset={0}
                     allowEscapeViewBox={{ x: true, y: true }}
                     wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                     cursor={{ stroke: '#818cf8', strokeOpacity: 0.32, strokeWidth: 1 }}
                   />
                   {/* K线蜡烛点数多、逐点 rAF 重排最贵 -> 关闭逐点动画，
                       整图由外层 motion.div 的 GPU opacity/transform 一次性淡入 */}
                   <Bar dataKey="wickRange" barSize={9} shape={<WorkbenchCandlestick />} isAnimationActive={false}>
                      {chartData.map((entry, index) => (
                        <Cell key={`candle-${index}`} fill={entry.up ? '#f43f5e' : '#10b981'} />
                      ))}
                   </Bar>
                   {showMa5Line && <Line type="monotone" dataKey="ma5" stroke="#eab308" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                   {showMa10Line && <Line type="monotone" dataKey="ma10" stroke="#818cf8" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                   {showMa20Line && <Line type="monotone" dataKey="ma20" stroke="#34d399" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                 </ComposedChart>
               </StableChartContainer>
               )}
             </div>

             <div className="h-[72px]">
               <StableChartContainer>
                 <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                   <XAxis dataKey="date" tickFormatter={(value) => formatAxisDate(String(value), axisPeriod)} tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" minTickGap={22} />
                   <Tooltip
                     content={<WorkbenchChartTooltip />}
                     offset={0}
                     allowEscapeViewBox={{ x: true, y: true }}
                     wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                     cursor={{ fill: 'rgba(129,140,248,0.08)' }}
                   />
                   {/* 成交量柱：点数中等，用 recharts 默认 400ms 动画即可，够快也够顺 */}
                   <Bar dataKey="volume" barSize={4} radius={[2, 2, 0, 0]}>
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-vol-${index}`} fill={entry.up ? '#f43f5e' : '#10b981'} fillOpacity={0.4} />
                      ))}
                   </Bar>
                 </ComposedChart>
               </StableChartContainer>
             </div>
            </motion.div>
          </div>
        </div>

        {/* Bottom News/Facts Panel */}
        <div className="bg-white/[0.04] border border-white/5 rounded-2xl overflow-hidden shadow-2xl flex flex-col h-[380px]">
           <div className="flex items-center gap-8 px-6 border-b border-white/5 bg-white/[0.01] pt-1">
             {PANEL_TABS.map((tab) => (
               <button 
                 key={tab.id} 
                 type="button"
                 data-testid={`workbench-info-tab-${tab.id}`}
                 onClick={() => handlePanelTabChange(tab.id)}
                 className={cn(
                 "flex items-center gap-2 py-4 text-xs font-medium border-b-2 transition-colors relative focus:outline-none focus:ring-2 focus:ring-indigo-500/40",
                 activePanelTab === tab.id ? "border-indigo-400 text-indigo-400" : "border-transparent text-neutral-500 hover:text-neutral-300"
               )}>
                 <tab.icon className={cn("w-4 h-4", activePanelTab === tab.id ? "text-indigo-400 drop-shadow-[0_0_5px_rgba(129,140,248,0.5)]" : "text-neutral-600")} />
                 {tab.label}
                 {activePanelTab === tab.id && (
                    <motion.div 
                      layoutId="activeTabIndicator"
                      className="absolute bottom-[-2px] left-0 right-0 h-[2px] bg-indigo-400 shadow-[0_0_10px_rgba(129,140,248,0.8)]"
                    />
                 )}
               </button>
             ))}
           </div>
           <div className="border-b border-white/5 bg-black/30 px-5 py-2 text-[10px] font-mono text-neutral-500">
             {infoStatus[activePanelTab]}
           </div>
           <div className="flex-1 overflow-y-auto p-4 bg-black/40 custom-scrollbar">
             <AnimatePresence mode="wait">
               {activePanelTab === 'news' && (
                 <motion.div 
                   key="news"
                   initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
                 >
                   {stockNews.length === 0 && (
                     <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-100/80">
                       当前标的暂无可用资讯。可在新闻聚合页按股票名称或代码拉取外部新闻；本面板不会再用模板新闻替代真实结果。
                     </div>
                   )}
                   {stockNews.map((news, i) => (
                     <button
                       key={`${news.time}-${news.title}`}
                       type="button"
                       data-testid={`workbench-news-item-${i}`}
                       onClick={() => handlePanelItemSelect(news.title, `${news.detail}。该资讯已关联 ${formatStockLabel(currentStock)}。`)}
                       className="w-full px-4 py-3 text-left border-b border-white/5 hover:bg-white/[0.02] transition-colors cursor-pointer group focus:outline-none focus:bg-indigo-500/[0.04]"
                     >
                       <div className="flex gap-4">
                         <div className="text-[10px] font-mono text-neutral-500 group-hover:text-neutral-400 mt-1 flex items-center gap-2">
                            {news.time}
                         </div>
                         <div className="flex-1">
                           <div className="flex items-center gap-2 mb-1.5">
                             <span className="px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20 text-[9px] font-mono uppercase">
                               {news.source}
                             </span>
                             <div className="w-1.5 h-1.5 rounded-full bg-white/10"></div>
                           </div>
                           <h4 className="text-sm text-neutral-200 font-medium leading-relaxed group-hover:text-indigo-300 transition-colors">{news.title}</h4>
                           {news.desc && <p className="text-xs text-neutral-500 mt-1.5 leading-relaxed">{news.desc}</p>}
                         </div>
                       </div>
                     </button>
                   ))}
                 </motion.div>
               )}

               {activePanelTab === 'finance' && (
                 <motion.div key="finance" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-4">
              {financeCards.map((item, i) => (
                     <button
                       key={item.label}
                       type="button"
                       data-testid={`workbench-finance-card-${i}`}
                       onClick={() => handlePanelItemSelect(item.label, `当前值 ${item.value}。${item.detail}。请结合 ${currentStock.name} 最新财报、行业均值和估值假设复核。`)}
                       className="bg-white/[0.03] border border-white/5 p-4 rounded-xl flex flex-col justify-center hover:bg-white/[0.05] transition-colors text-left focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                     >
                       <span className="text-xs text-neutral-500 mb-2">{item.label}</span>
                       <span className={cn("text-2xl font-mono font-medium", metricToneClass(item.tone))}>
                         {item.value}
                       </span>
                       <span className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-neutral-500">{item.detail}</span>
                     </button>
                   ))}
                 </motion.div>
               )}

               {activePanelTab === 'funds' && (
                 <motion.div key="funds" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-4">
                   {fundFlowCards.map((item, i) => (
                     <button
                       key={item.label}
                       type="button"
                       data-testid={`workbench-funds-card-${i}`}
                       onClick={() => handlePanelItemSelect(item.label, `${item.label} 当前为 ${item.value}。${item.detail}。资金项需要和换手率、价格方向、龙虎榜/两融数据交叉验证。`)}
                       className="bg-white/[0.03] border border-white/5 p-4 rounded-xl flex flex-col justify-center hover:bg-white/[0.05] transition-colors text-left focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                     >
                       <span className="text-xs text-neutral-500 mb-2">{item.label}</span>
                       <span className={cn("text-2xl font-mono font-medium", metricToneClass(item.tone))}>
                         {item.value}
                       </span>
                       <span className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-neutral-500">{item.detail}</span>
                     </button>
                   ))}
                 </motion.div>
               )}

               {activePanelTab === 'quant' && (
                 <motion.div key="quant" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="grid h-full grid-cols-2 gap-4 p-4">
                   {quantCards.map((factor, i) => (
                     <button
                       key={factor.label}
                       type="button"
                       data-testid={`workbench-quant-card-${i}`}
                       onClick={() => handlePanelItemSelect(factor.label, `${factor.detail}。该因子当前只作为研究辅助，不构成投资建议。`)}
                       className="rounded-xl border border-indigo-500/20 bg-indigo-500/10 p-4 text-left text-indigo-200 transition-colors hover:bg-indigo-500/15 focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                     >
                       <span className="block text-[10px] font-mono uppercase tracking-widest text-indigo-300/70">{factor.label}</span>
                       <span className={cn("mt-2 block text-2xl font-mono font-semibold", metricToneClass(factor.tone))}>{factor.value}</span>
                       <span className="mt-2 block text-[11px] leading-relaxed text-indigo-100/65">{factor.detail}</span>
                     </button>
                   ))}
                 </motion.div>
               )}
             </AnimatePresence>
           </div>
        </div>
      </div>

      <WorkbenchAiPanel
        analysisMode={analysisMode}
        autoEvidence={autoEvidence}
        canSendChat={canSendChat}
        chatLoading={chatLoading}
        chatModelOptions={chatModelOptions}
        chatStatus={chatStatus}
        currentStock={currentStock}
        fileInputRef={fileInputRef}
        handleFullscreen={handleFullscreen}
        handleModeChange={handleModeChange}
        handleRefreshChart={handleRefreshChart}
        handleSend={handleSend}
        handleUploadContext={handleUploadContext}
        input={input}
        lastUploadedFile={lastUploadedFile}
        messages={messages}
        modeMenuOpen={modeMenuOpen}
        onOpenModelSettings={onOpenModelSettings}
        selectedChatModel={selectedChatModel}
        selectedChatModelKey={selectedChatModelKey}
        selectedMode={selectedMode}
        setAutoEvidence={setAutoEvidence}
        setInput={setInput}
        setModeMenuOpen={setModeMenuOpen}
        setSelectedChatModelKey={setSelectedChatModelKey}
        setSettingsOpen={setSettingsOpen}
        setStrictRisk={setStrictRisk}
        settingsOpen={settingsOpen}
        strictRisk={strictRisk}
      />
    </motion.div>
  );
}
