# External Strategy Corpus and ETF Rotation Research

AlphaScope can audit an externally supplied strategy article corpus without
executing its code, then optionally import prose into a separate low-trust RAG
collection. It also provides a clean-room ETF momentum + RSRS portfolio research
baseline. Both features are research-only and never submit broker orders.

## Corpus Audit

Run the audit from the repository root:

```powershell
python scripts/strategy_corpus.py audit C:\path\to\corpus `
  --out data\cache\corpus-audit `
  --repository-url https://github.com/owner/repository
```

The corpus must use `articles/*/content.md`. The output contains `audit.json`
and `audit.md`, with only hashes and metadata rather than copied article prose.
The audit performs static code parsing only; it does not import modules, run
scripts, follow unsafe symlinks, download attachments, or invoke corpus code.

It assigns topic families, exact prose duplicates, source/author/date gaps, and
risk tags such as platform-specific APIs, syntax errors, zero-slippage examples,
and live-trading references.

## Controlled Import

The audit is intentionally separate from import. Unknown licensing blocks import
until the caller acknowledges it explicitly:

```powershell
python scripts/strategy_corpus.py import data\cache\corpus-audit\audit.json `
  C:\path\to\corpus --confirm-unverified --article 038_ETF_rotation
```

Recognized copyleft or restricted licenses remain blocked; confirmation is only
for a local, explicitly unverified corpus whose license is unknown.

Before any write, AlphaScope re-checks the audited file hashes. It imports only
Markdown prose with fenced code removed into the `unverified_strategy_ideas`
vector collection and `external_strategy_corpus` document source type. Imported
documents carry a D-tier trust score, `citation_allowed=false`, repository/commit
metadata, and a batch id. They are not part of ordinary evidence and should not
be used as an authoritative source in research reports.

Remove a batch by id returned by the import command:

```powershell
python scripts/strategy_corpus.py remove corpus-<batch-id>
```

## ETF Momentum + RSRS

Two local APIs expose the multi-asset research baseline:

- `POST /api/quant/portfolio/backtest`
- `POST /api/quant/portfolio/walk-forward`

Example request:

```json
{
  "symbols": ["510300", "518880", "513100"],
  "start_date": "2020-01-01",
  "end_date": "2025-12-31",
  "initial_capital": 1000000,
  "params": {
    "momentum_window": 63,
    "rsrs_window": 18,
    "rsrs_history": 252,
    "rsrs_entry": 0.7,
    "rsrs_exit": -0.7,
    "rebalance_interval": 5,
    "top_k": 2
  }
}
```

The engine aligns common daily OHLCV dates across all supplied ETFs, ranks
annualized log-regression momentum multiplied by R-squared, filters with RSRS,
and sends equal-weight targets at the following open. It applies configurable
commission, slippage, and 100-share lots. No same-close execution is allowed.

For mainland ETF codes, AlphaScope classifies six-digit numeric symbols as CN
market data and, after the general stock-history endpoint is unavailable, falls
back to AkShare's ETF-history endpoint. Portfolio requests require enough
history for the selected indicators and check that cached bars cover the
requested date range before using them; a partial cache triggers a data-source
refresh instead of silently shortening the study.

The walk-forward endpoint uses date-based anchored or rolling IS/OOS windows and
does not fit parameters inside an IS window. Standard RSRS settings need several
years of aligned history; a short response is explicitly marked
`insufficient_data` rather than filled with preview results.

Current limitations are included in every response: the supplied ETF universe is
not point-in-time screened; the baseline does not model suspensions, ETF
premium/discount, corporate actions, price limits, settlement rules, or market
impact. Results describe historical behavior only and are not investment advice.
