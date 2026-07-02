# 专家团角色 Prompt (prompts/experts/)

每个 `.md` 文件是一个专家团成员的 system_prompt,由 `backend/expert_panel.py` 的
`load_prompt_file(promptFile)` 加载,在 `config/experts.yaml` v2.0 teams 块引用。

## 文件清单

| 文件 | 角色 | 关注维度 |
|---|---|---|
| `buffett.md` | 巴菲特派 · 价值投资 | 护城河/ROE/FCF/估值 |
| `lynch.md` | 彼得·林奇 · 十倍股 | 日常生活观察/PEG/成长 |
| `chanlun.md` | 缠论派 · 走势结构 | 中枢/背驰/级别 |
| `macro.md` | 宏观对冲 | 周期/流动性/政策 |
| `risk_officer.md` | 风控官 | 仓位/止损/集中度 |
| `sentiment.md` | 消息面分析师 | 新闻情绪/公告/政策/传闻 |
| `fund_flow.md` | 资金面分析师 | 主力/北向/融资融券/大宗 |
| `devil.md` | 反方分析师 | 反面论证/逻辑漏洞/风险盲点 |
| `compliance.md` | 合规官 | 合规声明/风险提示/禁用词/适当性 |
| `summarizer.md` | 总结官 | 结论提炼/置信度/证据汇总/行动建议 |

## 维护规范

1. **结构对齐**: 每个 prompt 含「角色定位 + 核心原则 + 关注维度 + 输出要求」四段
   (对标 `buffett.md`)。末尾固定「根据 system 指令返回 JSON 格式分析结果」。
2. **合规红线**: 所有 prompt 仅研究语义, 不得输出确定性买卖指令; compliance.md 是
   合规审查的最终防线。
3. **路径引用**: `experts.yaml` 的 `promptFile` 字段是相对仓库根的路径
   (如 `prompts/experts/sentiment.md`)。文件缺失时 `load_prompt_file` 静默返回空
   → 空白人设, 由 `tests/test_experts_yaml.py::test_v2_member_prompt_files_all_load_nonempty`
   锁住防回归。
4. **A 股视角**: 角色 prompt 应含「A 股视角」段(适用 A 股的标的/逻辑), 因为
   AlphaScope 主要服务 A 股研究。
