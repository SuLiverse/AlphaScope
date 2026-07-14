# WAYLON A-share Strategy Corpus Audit

Audit snapshot: 2026-07-14

- Repository: https://github.com/WAYLON/ashare-quant-strategies
- Audited commit: `6abf8eb427ba30c45f57f218511d83cf89964d08`
- Audit manifest SHA-256: `28a5302a41905e864b001a47e448099e01457f567ad372d1199b4589dce35184`
- Corpus articles: 119
- Import performed: no

The snapshot was produced by `scripts/strategy_corpus.py`. It records metadata
and static-analysis findings only; no source article prose or executable snippet
was copied into this repository.

## Result

- Declared license: absent. All 119 entries remain blocked from import until an
  operator explicitly confirms the unknown license.
- Provenance: all 119 entries lack the author, source URL, and publication date
  required for evidence-grade use.
- Platform coupling: 114 entries reference a platform-specific quant API.
- Static code quality: 33 entries contain one or more invalid Python snippets.
- Validation gaps: 95 entries do not describe a backtest method; none describes
  an out-of-sample method.
- Friction risk: 35 entries contain a zero-slippage example.

## Candidate Families

The audit ranks 15 entries as A-tier *research ideas*, not code candidates.
The first implementation target is the ETF momentum/RSRS family represented by
entries 38, 43, 84, 98, 101, and 105. AlphaScope implements this family in a
separate clean-room engine; see [the feature guide](../strategy-corpus-etf-rotation.md).

Multi-asset allocation/rebalancing entries are useful follow-up research
candidates. Multi-factor, dividend/value, and generic momentum entries remain
B-tier until point-in-time universe and fundamentals data are available.

Limit-up/intraday and machine-learning entries remain C-tier: they require data
and validation capabilities that this corpus does not supply.

## Reproduce

```powershell
python scripts/strategy_corpus.py audit C:\path\to\ashare-quant-strategies `
  --out data\cache\ashare-quant-strategies-audit `
  --repository-url https://github.com/WAYLON/ashare-quant-strategies
```

The generated `audit.json` contains file hashes and drift checks. Its import
command stays opt-in and body-only by design.
