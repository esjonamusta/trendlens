# Contributing to TrendLens

Thanks for your interest in contributing. This document covers everything you need to get started.

---

## Getting started

### 1. Fork and clone

```bash
git clone https://github.com/your-org/trendlens.git
cd trendlens
```

### 2. Install dependencies

```bash
make install
# or manually:
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and TAVILY_API_KEY at minimum
```

### 4. Run the app

```bash
make run
```

### 5. Run the tests

```bash
make test
```

---

## Development workflow

### Branching

Use the following prefixes:

| Prefix | Use for |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `chore/` | Tooling, CI, dependency updates |
| `docs/` | Documentation only |

Example: `feat/slack-digest`, `fix/delta-match-threshold`

### Before opening a PR

```bash
make lint   # ruff check
make test   # pytest
```

Both must pass. CI will enforce the same checks.

### Commit style

Use short imperative messages:

```
add history retention setting to config
fix jaccard threshold for near-duplicate topics
update README architecture diagram
```

No ticket numbers, no emoji, no trailing punctuation.

---

## Project structure

```
app/
├── agents/         # Research orchestration (source discovery + ranking)
├── core/           # Config, LLM client, pipeline, schemas, prompts
├── db/             # SQLite history layer
├── services/       # Delta engine, normalizer, web search, report export
├── sources/        # Podcast / Reddit / web search query builders
├── api/            # FastAPI routes
└── static/         # Web UI (vanilla HTML/CSS/JS)
tests/              # pytest — run with `make test`
```

The key flows:

- **Research pipeline**: `app/core/pipeline.py` → `app/agents/research_agent.py` → sources → LLM ranking
- **Delta**: `app/services/delta.py` reads from `app/db/history.py` after every run
- **API**: `app/api/routes.py` — three endpoints (`/research`, `/research/markdown`, `/history/{domain}`)

---

## Where to contribute

Good areas for contribution:

- **New source types** — add a file under `app/sources/` following the pattern of `podcasts.py`
- **Delta scoring** — improve `compute_trend_delta_score` in `app/services/delta.py`
- **Export formats** — add Notion, Slack, or email output to `app/services/`
- **Tests** — coverage is thin outside the delta engine; any new test is welcome
- **UI improvements** — `app/static/index.html` is self-contained vanilla JS

If you're adding a new feature, open an issue first so we can discuss scope before you build.

---

## Adding a new source

1. Create `app/sources/your_source.py`:

```python
from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, web_search_service

def build_your_queries(config: ResearchConfig) -> list[str]:
    return [f"{config.domain} site:your-source.com"]

async def fetch_your_signals(config: ResearchConfig) -> list[QueryResults]:
    queries = build_your_queries(config)
    return await web_search_service.search_many(queries, max_results_per_query=5)
```

2. Import and call it in `app/agents/research_agent.py` alongside the existing sources.

3. Pass the results into `_format_results()` with a label.

---

## Running with OpenAI instead of Anthropic

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

No code changes required — the `LLMClient` in `app/core/llm.py` handles the switch.

---

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). Include:

- What you ran
- What you expected
- What actually happened
- Relevant log output

---

## Questions

Open a discussion or file an issue with the `question` label.
