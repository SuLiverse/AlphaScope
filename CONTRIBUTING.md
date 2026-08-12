# Contributing

Thanks for your interest in contributing to 研策中枢 AlphaScope.

## Getting Started

```bash
git clone https://github.com/TIANWEN-cpu/AlphaScope.git
cd AlphaScope
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Development Workflow

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Run lint and tests before submitting:

```bash
ruff check backend/ frontend/ tests/
ruff format --check backend/ frontend/ tests/
python -m pytest tests/ -v -m "not network" --ignore=tests/probes
```

可选：安装 pre-commit，提交前自动跑与 CI 相同的 ruff check/format（避免再因 format 门禁整段 CI 变红）：

```bash
pip install pre-commit
pre-commit install
```

4. Submit a pull request with a clear description of what changed and why

## Code Style

- Python 3.11+
- Ruff for linting and formatting (config in `pyproject.toml` / pre-commit)
- Type hints encouraged but not required
- No comments unless the "why" is non-obvious

## Adding a Data Provider

The provider system uses dynamic discovery -- no need to edit registry.py.

**Quick start:**

```bash
python scripts/create_provider.py --name your_source --markets CN --types news,reports --custom
```

**Manual steps:**

1. Create `custom_providers/your_provider.py` (or `backend/providers/your_provider.py` for built-in)
2. Extend `BaseProvider`, set class attributes (`name`, `markets`, `data_types`, `priority`)
3. Implement `get_news()`, `get_reports()`, `get_announcements()` as applicable
4. Add config entry in `config/data_sources.yaml` under the relevant `{data_type}_providers` section
5. Add tests in `tests/test_your_provider.py`
6. Restart the application -- your provider is auto-discovered

## Adding an Agent

1. Add agent function in `backend/llm_agents.py`
2. Register in the agent mode config (`config/models.yaml`)
3. Update the market brief builder if the agent needs custom data

## Reporting Issues

Open a GitHub issue with:
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS

## Security

See [SECURITY.md](SECURITY.md) for reporting security vulnerabilities.
