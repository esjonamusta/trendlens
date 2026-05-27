# TrendLens

Get the **top trending signals for any domain** — sourced from podcasts, Reddit, and the web — ranked by what matters for product managers.

Run the same domain again tomorrow and see what changed: what spiked, what's new, what's fading.

> **How it works:** TrendLens searches the live web, clusters the results by topic, and uses an LLM to write a short summary of each cluster. Headlines are AI-synthesised from real sources — they are not verbatim article titles. Each result links to the underlying search results so you can verify the claim yourself.

---

## What it does

You enter a domain (e.g. *"developer experience"*, *"fintech compliance"*). TrendLens:

1. Discovers the most relevant podcasts and subreddits for that domain
2. Searches across podcast mentions, Reddit, and the web in parallel — focused on the last 90 days
3. Clusters the results by topic and ranks them by evidence quality (weighted by source credibility, recency, and domain diversity)
4. Passes the ranked clusters to an LLM which writes a short summary of each — headlines, what happened, why it matters, PM action
5. Verifies each summary against real search result URLs (flags unverified claims)
6. Compares against the previous run and surfaces what changed

**What the LLM does and does not do:**
- ✅ Writes the headline, summary, and PM action from the evidence provided
- ✅ Chooses which clusters to highlight
- ❌ Cannot fabricate URLs — all source links come from real search results
- ❌ Cannot change confidence scores or evidence counts — those are computed deterministically

---

## Architecture

```
User Input (domain + optional context)
            │
            ▼
    ┌───────────────┐
    │ Source        │  LLM identifies the most relevant podcasts
    │ Discovery     │  and subreddits for this domain (Claude Haiku)
    └──────┬────────┘
           │
     ┌─────┴──────┬──────────────┐
     ▼            ▼              ▼
  Podcasts     Reddit          Web/News
  (web search) (site:reddit)   (Brave/Tavily)
     │            │              │
     └─────┬──────┴──────────────┘
           │  parallel fetch + deduplication
           ▼
    ┌───────────────┐
    │ Cluster &     │  Jaccard keyword clustering + weighted evidence scoring.
    │ Rank          │  No LLM — fast, deterministic, auditable.
    └──────┬────────┘
           │
           ▼
    ┌───────────────┐
    │ Summarise     │  LLM writes text only — headline, summary, PM action.
    │               │  URLs and confidence labels are set before this step
    │               │  and cannot be changed by the LLM.
    └──────┬────────┘
           │
           ▼
    ┌───────────────┐
    │ Delta Engine  │  Compares against previous run (≥24h gap).
    │               │  Scores using real matched URL counts.
    │               │  Lifecycle: NOT_DETECTED → COOLING → DORMANT → DISAPPEARED
    └──────┘
```

### Tech stack

| Layer | Technology |
|-------|-----------|
| LLM provider | Anthropic Claude (default) or OpenAI |
| Structured outputs | [instructor](https://github.com/jxnl/instructor) + Pydantic v2 |
| Web search | Brave Search (recommended) or Tavily |
| API | FastAPI + uvicorn |
| History | SQLite (WAL mode, auto-purge) |
| UI | Vanilla HTML/CSS/JS (no framework) |

---

## Quick start

### Option A — Local (Python)

**Prerequisites:** Python 3.12+, an Anthropic or OpenAI API key, a Brave Search or Tavily API key.

```bash
git clone https://github.com/your-org/trendlens.git
cd trendlens
make install
cp .env.example .env   # add your API keys
make run
```

Open [http://localhost:8000](http://localhost:8000).

### Option B — Docker

```bash
git clone https://github.com/your-org/trendlens.git
cd trendlens
cp .env.example .env   # add your API keys
make docker-up
```

Open [http://localhost:8000](http://localhost:8000). History is persisted in a named Docker volume (`trendlens-data`).

```bash
make docker-down   # stop
```

### Minimum `.env`

```env
ANTHROPIC_API_KEY=sk-ant-...
BRAVE_API_KEY=BSA...
```

Brave Search has a **free tier of 2,000 queries/month** — enough for roughly 150 runs. Tavily also works (set `TAVILY_API_KEY`) and auto-falls back to Brave when its credits run out if both keys are set.

### CLI

```bash
python cli.py "developer experience"
python cli.py "fintech compliance" --competitors Stripe Plaid --days 14 --output report.md
```

---

## Known limitations

- **Headlines are AI-generated, not real article titles.** The LLM synthesises a headline from a cluster of search results. Searching for it verbatim may return no results. Source links point to the underlying evidence.
- **"Podcast mentions" are web search results** that reference podcast episodes — not transcripts or RSS feeds.
- **Delta tracking can miss topic continuity** when the same story is phrased differently across runs. Jaccard keyword matching degrades on paraphrased headlines; enable `SIMILARITY_METHOD=embeddings` for better matching.
- **Single-user, single-machine.** SQLite is not suitable for shared multi-user deployments.

---

## API reference

### `POST /research`

Run a full research pipeline and return a structured report.

**Request body** (`domain` is the only required field):

```json
{
  "domain": "developer experience",
  "competitors": ["GitHub Copilot", "Cursor"],
  "target_users": "platform engineers",
  "geographic_market": "US",
  "time_window_days": 7,
  "max_items": 3
}
```

**Response:** `ResearchReportWithDelta`

```json
{
  "config": { "domain": "developer experience", "max_items": 3 },
  "items": [
    {
      "headline": "AI coding tools shift from autocomplete to autonomous agents",
      "what_happened": "...",
      "why_it_matters": "...",
      "podcast_evidence": [{ "text": "The Changelog ep 600 — AI agents in dev tools", "url": "https://changelog.com/podcast/600" }],
      "reddit_evidence":  [{ "text": "r/programming — thread on agent reliability", "url": "https://reddit.com/r/programming/..." }],
      "source_links": ["https://techcrunch.com/..."],
      "confidence": "High",
      "pm_action": "Audit your onboarding flow for agent-first workflows.",
      "grounded": true
    }
  ],
  "generated_at": "2026-05-24T10:00:00+00:00",
  "run_id": "uuid",
  "is_baseline": false,
  "delta": {
    "compared_to_date": "2026-05-17T10:00:00+00:00",
    "days_apart": 7.0,
    "comparison_type": "7_day",
    "insights": [
      {
        "classification": "SPIKING VS LAST RUN",
        "topic": "AI coding tools shift from autocomplete to autonomous agents",
        "trend_delta_score": 0.82,
        "reason": "Source count grew +240% (5 → 17), moved from rank 3 → 1."
      }
    ],
    "disappeared": [],
    "lifecycle": [
      {
        "status": "COOLING",
        "topic_headline": "Topic that dropped off",
        "consecutive_missing_runs": 2,
        "days_since_last_seen": 3.1
      }
    ]
  }
}
```

- First run for a domain: `is_baseline: true`, `delta: null`
- Re-run within 24h: `delta: null`, `delta_unavailable_reason` explains why
- `grounded: false` on an item means none of its cited URLs matched any real search result domain

### `POST /research/markdown`

Same as `/research` but returns a Markdown document.

```bash
curl -s -X POST http://localhost:8000/research/markdown \
  -H "Content-Type: application/json" \
  -d '{"domain": "B2B SaaS analytics"}' > report.md
```

### `POST /feedback`

Mark an item as incorrect. TrendLens excludes flagged headlines from future runs for that domain.

```json
{ "run_id": "uuid", "domain": "developer experience", "item_headline": "...", "feedback_type": "incorrect" }
```

### `GET /history/{domain}?limit=10`

Returns recent snapshot summaries for a domain (most recent first).

### `GET /health`

Returns `{"status": "ok"}`.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | — | Required for Anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Main model (ranking + synthesis) |
| `ANTHROPIC_FAST_MODEL` | `claude-haiku-4-5-20251001` | Fast model (source discovery) |
| `OPENAI_API_KEY` | — | Required for OpenAI provider or embedding matching |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `BRAVE_API_KEY` | — | Brave Search (recommended — 2,000 free queries/month) |
| `TAVILY_API_KEY` | — | Tavily search (1,000 free credits/month; auto-fallback to Brave if both set) |
| `ENABLE_CACHE` | `true` | In-memory TTL cache |
| `CACHE_TTL_SECONDS` | `3600` | Cache lifetime (1 hour) |
| `HISTORY_RETENTION_DAYS` | `90` | Auto-purge snapshots older than N days (`0` = keep forever) |
| `HISTORY_DB_PATH` | `history.db` | SQLite file path — set to `/data/history.db` in Docker |
| `DELTA_MIN_GAP_HOURS` | `24` | Minimum hours between runs before delta is computed |
| `SIMILARITY_METHOD` | `jaccard` | Topic matching: `jaccard` (fast, no cost) or `embeddings` (semantic, requires `OPENAI_API_KEY`) |
| `DEBUG` | `false` | Verbose logging |

---

## History + Delta

TrendLens saves every run to `history.db` and computes a delta after a 24-hour gap. Same-day comparisons reflect LLM output variance, not real trend movement.

**Topic lifecycle:**

| Status | Meaning |
|--------|---------|
| `NEW THIS RUN` | Not seen in the previous snapshot |
| `SPIKING VS LAST RUN` | Evidence count and/or rank improved significantly |
| `DECLINING` | Evidence count and/or rank dropped significantly |
| `STABLE BUT IMPORTANT` | Consistently present, no major movement |
| `WEAK SIGNAL TO WATCH` | Low confidence but tracked across runs |
| `NOT_DETECTED_THIS_RUN` | Absent from display but still detected in clustering |
| `COOLING` | Missing from 2–4 consecutive runs |
| `DORMANT` | Missing 5+ runs or 7+ days since last seen |
| `DISAPPEARED` | Absent for 14+ days with no cluster evidence |

For more accurate matching of paraphrased headlines, enable embedding-based matching:

```env
SIMILARITY_METHOD=embeddings
OPENAI_API_KEY=sk-...
```

See [HISTORY.md](HISTORY.md) for full technical details.

---

## Project structure

```
trendlens/
├── app/
│   ├── agents/
│   │   └── research_agent.py      # Source discovery + signal collection + ranking
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings + .env)
│   │   ├── llm.py                 # Provider-agnostic LLM client
│   │   ├── pipeline.py            # Orchestration, cache, history integration
│   │   ├── prompts.py             # LLM prompts
│   │   └── schemas.py             # Pydantic models
│   ├── db/
│   │   └── history.py             # SQLite snapshot persistence
│   ├── services/
│   │   ├── delta.py               # Topic matching, scoring, lifecycle classification
│   │   ├── embeddings.py          # OpenAI embedding-based topic matching
│   │   ├── normalizer.py          # Keyword extraction, Jaccard similarity, source matching
│   │   ├── report.py              # Markdown export
│   │   └── web_search.py          # Brave + Tavily search client with automatic fallback
│   ├── sources/
│   │   ├── podcasts.py            # Podcast mention queries
│   │   ├── reddit.py              # Reddit signal queries
│   │   └── web.py                 # Web/news signal queries
│   ├── api/
│   │   └── routes.py              # FastAPI endpoints
│   └── static/
│       └── index.html             # Web UI
├── tests/
│   ├── conftest.py
│   ├── test_delta.py
│   ├── test_history.py
│   └── test_normalizer.py
├── cli.py                         # Command-line interface
├── main.py                        # App entry point
├── Dockerfile
├── docker-compose.yml
├── Makefile                       # Developer shortcuts
├── requirements.txt
├── .env.example
├── CONTRIBUTING.md
└── HISTORY.md
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT
