# 研策中枢 AlphaScope v1.8.1

发布日期：2026-06-24

v1.8.1 是一次**修复与开箱体验**版本：修正行情数据源失效导致的涨跌幅异常、让「自定义 API 接口 / 获取模型」开箱即用、并预置常用股行情种子数据。纯修复与增量，未删改既有功能。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.8.1.exe`（双击安装）
- Windows 便携版：`AlphaScope-portable.zip`（解压后运行 `AlphaScope.exe`）

## 修复

- **行情涨跌幅修正**：旧版日线在腾讯兜底源失效时拉不到最新交易日，导致「昨收」取到陈旧值、涨跌幅严重失真甚至恒为 0。新增 **东方财富 push2his 直连** 作为可靠兜底，取价链路变为 `akshare hist → 东财直连 → 腾讯`，保证开高低收 / 昨收 / 涨跌幅准确（`backend/providers/akshare_provider.py`）。
- **「自定义 API 接口」开箱即用**：
  - 发布版默认放行用户自定义 LLM Base URL（`ALLOW_LOCAL_LLM_BASE_URL=1`），自定义 Provider 不再被 SSRF 策略误拦。
  - 首次启动**自动生成持久主密钥**（`AI_FINANCE_MASTER_KEY` 写入 `.env`），每台安装独立且安全；保存自定义 Provider 的 API Key 不再需要手动配置主密钥，也不依赖不安全的开发回退密钥。
- **预置常用股行情**：打包内置常用蓝筹 / 港股近 1 年日线种子数据，开箱即有正确价格与涨跌幅；首次启动后行情源自动补到最新交易日。

## 升级说明

- 直接安装覆盖即可；本地 `data/` 与 `.env` 保留。
- 若此前手动改过 `.env`，其中的主密钥与 `ALLOW_LOCAL_LLM_BASE_URL` 会沿用你的设置。

## 验证

```bash
python scripts/build_seed_db.py        # 生成行情种子库(可选,网络正常时)
python build.py --installer --zip      # 产出 exe + 安装包 + 便携 zip
```

> 免责声明：本项目用于研究与辅助分析，不构成投资建议。所有输出请结合真实数据与个人判断独立核验。
