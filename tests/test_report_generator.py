"""Report Generator 报告生成器单元测试"""

from backend.ai_assistant.report_generator import generate_report, generate_summary


class TestReportGenerator:
    def _make_conversation(self, **kwargs):
        """创建测试用对话数据"""
        defaults = {
            "id": "test_conv_001",
            "title": "贵州茅台分析",
            "stock_symbol": "600519",
            "stock_name": "贵州茅台",
            "mode": "deep",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "created_at": "2026-05-20 10:00:00",
            "message_count": 3,
        }
        defaults.update(kwargs)
        return defaults

    def _make_messages(self):
        """创建测试用消息数据"""
        return [
            {
                "role": "user",
                "content": "分析一下贵州茅台",
                "timestamp": "2026-05-20 10:00:00",
                "metadata": {},
            },
            {
                "role": "assistant",
                "content": "贵州茅台当前估值合理，建议买入。",
                "timestamp": "2026-05-20 10:01:00",
                "metadata": {
                    "mode": "deep",
                    "agents": {
                        "fundamental": {"signal": "buy", "confidence": 85},
                    },
                    "evidence": [
                        {
                            "type": "fundamental",
                            "claim": "ROE稳定在25%以上",
                            "source": "CNInfo",
                            "data_date": "2026-05-20",
                        }
                    ],
                    "summary": {"buy": 4, "hold": 1, "sell": 0},
                },
            },
        ]

    def test_generate_report_basic(self):
        """测试基本报告生成"""
        conv = self._make_conversation()
        messages = self._make_messages()
        report = generate_report(conv, messages)

        assert "贵州茅台分析" in report
        assert "600519" in report
        assert "深度分析" in report
        assert "deepseek" in report

    def test_generate_report_conversation_flow(self):
        """测试对话流程包含在报告中"""
        conv = self._make_conversation()
        messages = self._make_messages()
        report = generate_report(conv, messages)

        assert "分析一下贵州茅台" in report
        assert "贵州茅台当前估值合理" in report

    def test_generate_report_evidence_chain(self):
        """测试证据链包含在报告中"""
        conv = self._make_conversation()
        messages = self._make_messages()
        report = generate_report(conv, messages, include_evidence=True)

        assert "证据链" in report
        assert "ROE稳定在25%以上" in report
        assert "CNInfo" in report
        assert "研究可信度" in report
        assert "来源完整度" in report

    def test_generate_report_disclaimer(self):
        """测试深度分析报告包含免责声明"""
        conv = self._make_conversation(mode="deep")
        messages = self._make_messages()
        report = generate_report(conv, messages)

        assert "风险提示" in report

    def test_generate_report_no_disclaimer_free(self):
        """测试自由问答报告不包含免责声明"""
        conv = self._make_conversation(mode="free")
        messages = [
            {
                "role": "user",
                "content": "你好",
                "timestamp": "2026-05-20 10:00:00",
                "metadata": {},
            },
            {
                "role": "assistant",
                "content": "你好！有什么可以帮你的？",
                "timestamp": "2026-05-20 10:01:00",
                "metadata": {"mode": "free"},
            },
        ]
        report = generate_report(conv, messages)
        assert "风险提示" not in report

    def test_generate_report_no_stock(self):
        """测试无股票的对话报告"""
        conv = self._make_conversation(stock_symbol="", stock_name="")
        messages = self._make_messages()
        report = generate_report(conv, messages)

        assert "贵州茅台分析" in report
        assert "标的" not in report or "()" not in report

    def test_generate_summary_with_analysis(self):
        """测试从分析消息中提取摘要"""
        messages = self._make_messages()
        summary = generate_summary(messages)

        assert "贵州茅台当前估值合理" in summary

    def test_generate_summary_no_analysis(self):
        """测试无分析消息时返回默认摘要"""
        messages = [
            {
                "role": "user",
                "content": "你好",
                "timestamp": "2026-05-20 10:00:00",
                "metadata": {},
            },
            {
                "role": "assistant",
                "content": "你好！",
                "timestamp": "2026-05-20 10:01:00",
                "metadata": {"mode": "free"},
            },
        ]
        summary = generate_summary(messages)
        assert "暂无分析摘要" in summary
