"""事件抽取器 - 从新闻/公告中提取结构化事件

v0.12 核心模块。使用规则引擎 + 关键词匹配抽取事件,
后续可接入 LLM 做更精细的抽取。

事件类型:
- earnings: 业绩 (盈利预增/预减/快报/年报/季报)
- dividend: 分红/送转/派息
- mna: 收购/合并/要约/重组
- financing: 融资/配股/增发/发债/可转债
- litigation: 诉讼/仲裁/处罚/立案
- policy: 政策/监管/法规
- supply_chain: 供应链/合同/中标/订单
- insider: 股东增减持/回购/管理层变动
- macro: 宏观/利率/汇率/通胀
- other: 其他
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """结构化事件"""

    id: str = ""
    event_type: str = "other"
    title: str = ""
    summary: str = ""
    source: str = ""
    source_url: str = ""
    symbols: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    sentiment: float = 0.0  # -1.0 ~ 1.0
    importance: float = 0.5  # 0.0 ~ 1.0
    published_at: Optional[datetime] = None
    evidence_id: str = ""  # 关联的原始数据 ID

    def __post_init__(self):
        if not self.id:
            raw = f"{self.event_type}_{self.source}_{self.title}"
            self.id = f"evt_{hashlib.md5(raw.encode()).hexdigest()[:12]}"


# ---- 事件类型关键词规则 ----

_EVENT_RULES: list[dict] = [
    {
        "type": "earnings",
        "keywords": [
            "业绩预告",
            "业绩快报",
            "盈利预增",
            "盈利预减",
            "净利润增长",
            "净利润下降",
            "扭亏为盈",
            "由盈转亏",
            "年报",
            "季报",
            "中报",
            "营业收入增长",
            "营收增长",
            "每股收益",
            "ROE",
            "净资产收益率",
            "业绩大幅增长",
            "业绩大幅下降",
            "超预期",
            "低于预期",
        ],
        "title_patterns": [
            r"20\d{2}年.*年度报告",
            r"20\d{2}年.*季度报告",
            r"半年度报告",
            r"业绩.*预告",
            r"业绩.*快报",
        ],
        "importance": 0.8,
        "sentiment_keywords": {
            "positive": ["增长", "预增", "扭亏", "超预期", "大幅增长", "创新高"],
            "negative": ["下降", "预减", "亏损", "低于预期", "大幅下降", "暴跌"],
        },
    },
    {
        "type": "dividend",
        "keywords": [
            "分红",
            "派息",
            "送股",
            "转增",
            "权益分派",
            "利润分配",
            "每10股派",
            "每10股送",
            "每10股转",
        ],
        "title_patterns": [
            r"权益分派",
            r"利润分配方案",
            r"分红.*公告",
        ],
        "importance": 0.6,
        "sentiment_keywords": {
            "positive": ["高送转", "高分红", "派息", "送股"],
            "negative": ["不分红", "不分配", "取消分红"],
        },
    },
    {
        "type": "mna",
        "keywords": [
            "收购",
            "合并",
            "重组",
            "要约收购",
            "资产注入",
            "借壳",
            "私有化",
            "吸收合并",
            "换股",
            "标的资产",
            "交易对方",
        ],
        "title_patterns": [
            r"重大资产.*重组",
            r"收购.*股权",
            r"合并.*公告",
        ],
        "importance": 0.9,
        "sentiment_keywords": {
            "positive": ["收购完成", "重组获批", "资产注入"],
            "negative": ["收购终止", "重组失败", "审批被否"],
        },
    },
    {
        "type": "financing",
        "keywords": [
            "配股",
            "增发",
            "定向增发",
            "非公开发行",
            "可转债",
            "公司债",
            "中期票据",
            "短期融资券",
            "融资",
            "募集资金",
            "IPO",
            "发行",
            "申购",
        ],
        "title_patterns": [
            r"非公开发行",
            r"配股.*公告",
            r"增发.*方案",
            r"可转换公司债",
        ],
        "importance": 0.7,
        "sentiment_keywords": {
            "positive": ["融资获批", "定增完成", "募资到位"],
            "negative": ["融资终止", "定增被否", "发行失败"],
        },
    },
    {
        "type": "litigation",
        "keywords": [
            "诉讼",
            "仲裁",
            "处罚",
            "立案",
            "调查",
            "违规",
            "行政处罚",
            "监管措施",
            "警示函",
            "通报批评",
            "退市风险",
            "ST",
            "*ST",
        ],
        "title_patterns": [
            r"收到.*处罚",
            r"立案.*调查",
            r"诉讼.*公告",
        ],
        "importance": 0.85,
        "sentiment_keywords": {
            "positive": ["诉讼和解", "处罚撤销", "解除风险"],
            "negative": ["立案", "处罚", "退市", "违规", "ST"],
        },
    },
    {
        "type": "policy",
        "keywords": [
            "政策",
            "监管",
            "法规",
            "条例",
            "指导意见",
            "国务院",
            "证监会",
            "央行",
            "银保监",
            "发改委",
            "降准",
            "降息",
            "加息",
            "MLF",
            "LPR",
        ],
        "title_patterns": [
            r"关于.*意见",
            r"关于.*通知",
            r"关于.*办法",
        ],
        "importance": 0.7,
        "sentiment_keywords": {
            "positive": ["降准", "降息", "利好", "扶持", "鼓励"],
            "negative": ["加息", "收紧", "限制", "处罚", "整顿"],
        },
    },
    {
        "type": "supply_chain",
        "keywords": [
            "中标",
            "合同",
            "订单",
            "供货",
            "采购",
            "战略合作",
            "框架协议",
            "项目中标",
        ],
        "title_patterns": [
            r"中标.*公告",
            r"签订.*合同",
            r"重大.*订单",
        ],
        "importance": 0.65,
        "sentiment_keywords": {
            "positive": ["中标", "大额订单", "战略合作", "合同签订"],
            "negative": ["合同终止", "订单取消", "供应中断"],
        },
    },
    {
        "type": "insider",
        "keywords": [
            "增持",
            "减持",
            "回购",
            "管理层变动",
            "董事辞职",
            "高管变更",
            "控股股东",
            "实际控制人",
            "举牌",
            "股份回购",
            "员工持股",
        ],
        "title_patterns": [
            r"增持.*公告",
            r"减持.*公告",
            r"回购.*方案",
            r"董事.*辞职",
        ],
        "importance": 0.6,
        "sentiment_keywords": {
            "positive": ["增持", "回购", "举牌", "员工持股"],
            "negative": ["减持", "清仓", "董事辞职", "高管离职"],
        },
    },
]

# 宏观事件关键词 (不关联个股)
_MACRO_KEYWORDS = [
    "GDP",
    "CPI",
    "PPI",
    "PMI",
    "社融",
    "M2",
    "美联储",
    "非农",
    "通胀",
    "利率决议",
    "贸易战",
    "关税",
    "地缘政治",
]


class EventExtractor:
    """事件抽取器"""

    def __init__(self) -> None:
        self._rules = _EVENT_RULES
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """预编译正则"""
        for rule in self._rules:
            rule["_compiled"] = [re.compile(p, re.IGNORECASE) for p in rule.get("title_patterns", [])]

    def extract_from_text(
        self,
        text: str,
        source: str = "",
        source_url: str = "",
        symbols: list[str] = None,
        published_at: Optional[datetime] = None,
    ) -> list[Event]:
        """从文本中抽取事件"""
        if not text:
            return []

        events = []
        text_lower = text.lower()

        for rule in self._rules:
            matched, sentiment = self._match_rule(rule, text, text_lower)
            if not matched:
                continue

            events.append(
                Event(
                    event_type=rule["type"],
                    title=self._extract_title(text),
                    summary=self._extract_summary(text),
                    source=source,
                    source_url=source_url,
                    symbols=symbols or [],
                    sentiment=sentiment,
                    importance=rule.get("importance", 0.5),
                    published_at=published_at,
                )
            )

        # 如果没匹配到任何规则, 归类为 other
        if not events:
            events.append(
                Event(
                    event_type="other",
                    title=self._extract_title(text),
                    summary=self._extract_summary(text)[:200],
                    source=source,
                    source_url=source_url,
                    symbols=symbols or [],
                    importance=0.3,
                    published_at=published_at,
                )
            )

        return events

    def extract_from_news_item(self, item: dict) -> list[Event]:
        """从新闻条目抽取事件"""
        text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('content', '')}"
        return self.extract_from_text(
            text=text,
            source=item.get("source", ""),
            source_url=item.get("source_url", item.get("url", "")),
            symbols=item.get("symbols", []),
            published_at=item.get("datetime") or item.get("published_at"),
        )

    def extract_from_announcement(self, item: dict) -> list[Event]:
        """从公告条目抽取事件"""
        text = f"{item.get('title', '')} {item.get('content', '')}"
        symbols = [item.get("symbol", "")] if item.get("symbol") else []
        return self.extract_from_text(
            text=text,
            source=item.get("source", ""),
            source_url=item.get("source_url", item.get("url", "")),
            symbols=symbols,
            published_at=item.get("datetime") or item.get("published_at"),
        )

    def _match_rule(self, rule: dict, text: str, text_lower: str) -> tuple[bool, float]:
        """检查文本是否匹配规则, 返回 (是否匹配, 情绪分)"""
        # 关键词匹配
        keyword_hits = 0
        for kw in rule.get("keywords", []):
            if kw.lower() in text_lower:
                keyword_hits += 1

        # 正则匹配
        pattern_hits = 0
        for pat in rule.get("_compiled", []):
            if pat.search(text):
                pattern_hits += 1

        # 至少命中 1 个关键词或 1 个正则
        if keyword_hits == 0 and pattern_hits == 0:
            return False, 0.0

        # 计算情绪分
        sentiment = self._calc_sentiment(rule, text_lower)
        return True, sentiment

    def _calc_sentiment(self, rule: dict, text_lower: str) -> float:
        """基于关键词计算情绪分"""
        sent_kw = rule.get("sentiment_keywords", {})
        pos_hits = sum(1 for kw in sent_kw.get("positive", []) if kw.lower() in text_lower)
        neg_hits = sum(1 for kw in sent_kw.get("negative", []) if kw.lower() in text_lower)

        total = pos_hits + neg_hits
        if total == 0:
            return 0.0
        return (pos_hits - neg_hits) / total

    @staticmethod
    def _extract_title(text: str) -> str:
        """提取标题 (取第一行或前80字)"""
        first_line = text.strip().split("\n")[0].strip()
        return first_line[:80] if first_line else text[:80]

    @staticmethod
    def _extract_summary(text: str) -> str:
        """提取摘要 (取前200字)"""
        clean = re.sub(r"\s+", " ", text).strip()
        return clean[:200]


# ---- 便捷函数 ----

_extractor: Optional[EventExtractor] = None


def _get_extractor() -> EventExtractor:
    global _extractor
    if _extractor is None:
        _extractor = EventExtractor()
    return _extractor


def extract_events_from_news(items: list[dict]) -> list[Event]:
    """批量从新闻条目抽取事件"""
    extractor = _get_extractor()
    events = []
    for item in items:
        events.extend(extractor.extract_from_news_item(item))
    return events


def extract_events_from_announcements(items: list[dict]) -> list[Event]:
    """批量从公告条目抽取事件"""
    extractor = _get_extractor()
    events = []
    for item in items:
        events.extend(extractor.extract_from_announcement(item))
    return events
