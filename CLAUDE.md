# TrendLens — Claude Code context

## What this project does

TrendLens is a FastAPI app that researches a domain (e.g. "developer experience") and returns the top 3 trending topics pulled from podcasts, Reddit, and the web. It compares each run against a saved history to surface deltas (new, spiking, declining, disappeared topics).

## Key commands

```bash
make install   # set up venv
make run       # start dev server (localhost:8000)
make test      # run pytest
make lint      # ruff check
```

## Architecture

The request flow is:

1. `POST /research` → `app/api/routes.py`
2. → `app/core/pipeline.py:run_research()` — cache check, orchestration, history save
3. → `app/agents/research_agent.py:ResearchAgent.run()` — two LLM calls:
   - `_discover_sources()` uses **Haiku** (fast/cheap) to pick podcasts + subreddits
   - parallel fetch via `app/sources/{podcasts,reddit,web}.py`
   - `_rank_and_summarize()` uses **Sonnet** to produce 3 ranked items
4. → `app/services/delta.py:compute_delta()` — Jaccard keyword matching + trend_delta_score
5. → `app/db/history.py:save_snapshot()` — persists to SQLite

## Important constraints

- **Do not add LLM calls for delta computation.** The delta engine (`app/services/delta.py`) is intentionally LLM-free — keyword matching + weighted scoring only. Keep it fast, cheap, and deterministic.
- **Schemas in `app/core/schemas.py` are the source of truth.** The LLM is instructed via `instructor` to return these exact shapes. Changing field names or types will break structured outputs.
- **The delta match threshold is 0.20 Jaccard** (`_MATCH_THRESHOLD` in `delta.py`). Don't lower it without running the normalizer tests — false matches will silently corrupt delta output.
- **SQLite WAL files (`history.db-shm`, `history.db-wal`) are gitignored.** Never commit them.

## File ownership map

| What you want to change | Where to look |
|------------------------|---------------|
| LLM prompts | `app/core/prompts.py` |
| Data shapes / models | `app/core/schemas.py` |
| API endpoints | `app/api/routes.py` |
| Pipeline orchestration | `app/core/pipeline.py` |
| Delta scoring logic | `app/services/delta.py` |
| Keyword normalisation | `app/services/normalizer.py` |
| History DB operations | `app/db/history.py` |
| Search queries per source | `app/sources/{podcasts,reddit,web}.py` |
| Web search client | `app/services/web_search.py` |
| Web UI | `app/static/index.html` |
| Config / env vars | `app/core/config.py` + `.env.example` |

## Environment

Needs at minimum:
- `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` with `LLM_PROVIDER=openai`)
- `TAVILY_API_KEY` for live web search (falls back to LLM knowledge if missing)

## Tests

```bash
make test
# or: pytest tests/ -v
```

Tests are in `tests/` and cover the delta engine, history DB, and normalizer. They do not make real LLM or search API calls. New features should have tests before merging.
