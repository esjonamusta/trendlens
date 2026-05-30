# TrendLens Hackathon Upgrade — Design Spec

**Date:** 2026-05-30
**Team:** 5 people
**Duration:** 2 days

---

## Overview

Upgrade TrendLens from a single-user, manually-triggered research tool into a proactive PM intelligence platform. The upgraded app surfaces real engagement signals, tracks multiple domains automatically, and delivers daily email digests — while remaining usable on-demand.

---

## Goals

- Replace web-search-only sources with real API calls that include engagement data (upvotes, stars, comments)
- Allow PMs to track multiple domains and have them run automatically every 24 hours
- Provide a dashboard showing all tracked domains and their trend status at a glance
- Give PMs an interactive trend explorer to understand how signals change over time
- Send a daily email digest summarizing what changed across all tracked domains

---

## Non-Goals (for this hackathon)

- Personalization / per-user filtering within a domain (separate future spec)
- Multi-user accounts or authentication
- Mobile-optimized UI
- Email unsubscribe management (stub only)
- Tavily/Brave replacement — existing web search stays as-is for general web signals

---

## Architecture Overview

```
Tracked Domains (SQLite)
        │
        ▼
APScheduler (daily)
        │
        ├──► run_research() [existing pipeline]
        │         │
        │         └──► Sources: HN API + GitHub API + Reddit API + existing web/podcast/reddit search
        │
        └──► Email Digest (SendGrid)

FastAPI
  ├── GET  /domains              → list tracked domains
  ├── POST /domains              → add domain to watch list
  ├── GET  /history/{domain}/timeline  → per-topic scores over time
  └── POST /digest/send          → manually trigger email digest

Frontend (vanilla HTML + Alpine.js + Chart.js)
  ├── Dashboard panel (domain list + latest trends)
  ├── Trend explorer (time range selector, sparklines, week comparison)
  └── Existing on-demand search (unchanged)
```

---

## Person 1 — Real Source APIs

### Goal
Replace the implicit web search for HN and add real API calls for HN, GitHub, and Reddit that return engagement metadata alongside content.

### New Files
- `app/sources/hn.py` — HN Algolia API client
- `app/sources/github.py` — GitHub Search API client

### Modified Files
- `app/sources/reddit.py` — add Reddit OAuth client alongside existing web search fallback
- `app/core/schemas.py` — add `engagement_score: float | None = None` to `SearchSource`
- `app/services/trend_engine.py` — update `source_quality_weight()` to boost sources with real engagement data

### API Details

**HN Algolia** (no key required)
```
GET https://hn.algolia.com/api/v1/search?query={domain}&tags=story&numericFilters=points>10
```
Returns: `title`, `url`, `points`, `num_comments`, `created_at`

**GitHub** (free key, 5000 req/hour)
```
GET https://api.github.com/search/repositories?q={domain}&sort=stars
GET https://api.github.com/search/issues?q={domain}&sort=reactions
```
Returns: `full_name`, `html_url`, `description`, `stargazers_count`, `open_issues_count`

**Reddit OAuth** (free tier, 100 req/min)
```
POST https://www.reddit.com/api/v1/access_token
GET  https://oauth.reddit.com/r/{subreddit}/search?q={domain}&sort=top&t=month
```
Returns: `title`, `url`, `score`, `num_comments`, `subreddit`

### Engagement Score Mapping
Each API result gets an `engagement_score` (0.0–1.0) before being passed to the existing pipeline:
- HN: `min(points / 500, 1.0)`
- GitHub repos: `min(stargazers_count / 10000, 1.0)`
- Reddit: `min(score / 1000, 1.0)`

`source_quality_weight()` applies a 1.0–1.5x multiplier when `engagement_score` is present, proportional to the score.

### Day 1 Target
HN Algolia integration working end-to-end with engagement scores flowing into ranking.

### Day 2 Target
GitHub and Reddit integrations complete and wired in.

### Error Handling
- All three clients fall back gracefully to empty results on API error or missing credentials
- Existing web search results are unaffected — new sources are additive

---

## Person 2 — Scheduler

### Goal
Automatically run research for each tracked domain every 24 hours, so PMs get fresh data without manual triggering.

### New Files
- `app/scheduler.py` — APScheduler setup and job definitions
- `app/db/tracked_domains.py` — SQLite CRUD for tracked domains

### Modified Files
- `app/api/routes.py` — add `POST /domains` and `GET /domains`
- `main.py` — start scheduler on app boot

### Data Model

```sql
CREATE TABLE tracked_domains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL UNIQUE,
    added_at    TEXT NOT NULL,
    last_run_at TEXT,
    status      TEXT DEFAULT 'pending'   -- pending | running | done | error
);
```

### API Endpoints

`POST /domains`
```json
{ "domain": "developer experience" }
```
Response: `{ "id": 1, "domain": "developer experience", "status": "pending" }`

`GET /domains`
```json
[
  {
    "id": 1,
    "domain": "developer experience",
    "added_at": "2026-05-30T08:00:00Z",
    "last_run_at": "2026-05-30T09:00:00Z",
    "status": "done"
  }
]
```

### Scheduler Behaviour
- APScheduler runs an `IntervalTrigger` every 24 hours
- On each tick: fetch all tracked domains, call `run_research()` for each sequentially
- Updates `last_run_at` and `status` after each run
- Respects existing `DELTA_MIN_GAP_HOURS` setting — won't produce a delta if run too soon

### Day 1 Target
`POST /domains` and `GET /domains` working. Manual job trigger via `POST /domains/run-now` for testing.

### Day 2 Target
APScheduler auto-runs on boot. Status field updating correctly.

---

## Person 3 — Dashboard

### Goal
Replace the single-domain hero with a two-panel dashboard showing all tracked domains and their latest trend status at a glance.

### Modified Files
- `app/static/index.html` — new two-panel layout with Alpine.js

### Layout

```
┌─────────────────────┬────────────────────────────────────┐
│  Tracked Domains    │  Developer Experience               │
│                     │  Last run: 2 hours ago              │
│  ● Dev Experience ↑ │                                     │
│  ● Fintech Comply → │  ⚡ Don't Miss                      │
│  ● AI Coding Tools↑ │  AI coding tools shift to agents   │
│                     │  SPIKING · High confidence          │
│  + Track domain     │                                     │
│                     │  1. AI coding tools...  SPIKING     │
│                     │  2. Pricing pressure... STABLE      │
│                     │  3. OSS alternatives... NEW         │
└─────────────────────┴────────────────────────────────────┘
```

### Status Badges
Derived from the delta `classification` field already returned by the API:
- 🟢 NEW THIS RUN
- 🔴 SPIKING VS LAST RUN
- 🟡 STABLE BUT IMPORTANT
- ⚪ COOLING / DECLINING

### "Don't Miss This" Card
Surfaces the single highest `weighted_evidence_score` item from the latest run, shown at the top of the domain detail panel regardless of rank.

### Data Sources
- `GET /domains` → domain list (Person 2)
- `GET /history/{domain}?limit=1` → latest run results per domain (existing endpoint)

### Day 1 Target
Full UI with mocked domain list and hardcoded trend data. Alpine.js reactive panel switching.

### Day 2 Target
Wired to live `GET /domains` and `GET /history/{domain}` endpoints.

---

## Person 4 — Trend Explorer

### Goal
An interactive visualization layer that lets PMs explore how trends have moved over time within a domain.

### New Files
- `app/api/routes.py` — add `GET /history/{domain}/timeline`

### Modified Files
- `app/static/index.html` — add trend explorer tab with Chart.js charts

### New Endpoint

`GET /history/{domain}/timeline?days=30`

```json
{
  "domain": "developer experience",
  "snapshots": [
    {
      "run_id": "uuid",
      "created_at": "2026-05-23T09:00:00Z",
      "topics": [
        {
          "headline": "AI coding tools shift to agents",
          "weighted_evidence_score": 3.2,
          "rank": 1,
          "classification": "SPIKING VS LAST RUN"
        }
      ]
    }
  ]
}
```

### Explorer Features
- **Time range selector:** 7d / 30d / 90d toggle
- **Top trends list:** ranked by average `weighted_evidence_score` over the selected period, with a sparkline per topic
- **Week comparison panel:** side-by-side view of this week vs last week — what moved up, down, or disappeared
- **Topic detail view:** click any topic → full evidence history with source list per run

### Chart.js Usage
- Sparklines: `type: 'line'`, no axes, `tension: 0.4`, minimal styling
- Week comparison: `type: 'bar'`, grouped bars per topic
- Topic detail: `type: 'line'` with hover tooltips showing source count

### Day 1 Target
Full explorer UI with seeded `history.db` data (3–5 fake runs). All charts rendering and interactive.

### Day 2 Target
Live `GET /history/{domain}/timeline` endpoint wired in.

---

## Person 5 — Email Digest

### Goal
Send a daily email to PMs summarizing what changed across all their tracked domains overnight.

### New Files
- `app/services/digest.py` — builds the digest content from latest run deltas
- `app/services/email.py` — SendGrid client

### Modified Files
- `app/api/routes.py` — add `POST /digest/send`
- `app/scheduler.py` — trigger digest after nightly runs complete (Person 2)

### SendGrid Setup
- Free tier: 100 emails/day, no credit card required
- Env var: `SENDGRID_API_KEY`
- Add to `.env.example`

### Email Format

**Subject:** `TrendLens Daily · May 30 · 3 domains tracked`

**Body (per domain):**
```
── Developer Experience ──────────────────
⚡ NEW: AI coding tools shift to agents       [High]
↑ SPIKING: Pricing pressure from OSS tools   [Medium]
↓ COOLING: Low-code platform adoption        [Low]

View full report → http://localhost:8000

── Fintech Compliance ────────────────────
...
```

### API Endpoint

`POST /digest/send`
```json
{ "email": "pm@company.com" }
```
Sends immediately using latest run data for all tracked domains.

### Digest Logic (digest.py)
1. Fetch all tracked domains from `tracked_domains` table
2. For each domain, fetch latest snapshot from `history.db`
3. Extract top 3 items with their delta classification
4. Render email body
5. Send via SendGrid

### Day 1 Target
Email rendering working. `POST /digest/send` sends a real email manually.

### Day 2 Target
Auto-triggered by scheduler after nightly runs.

---

## UI Stack

| Library | Version | Purpose | CDN |
|---------|---------|---------|-----|
| Alpine.js | 3.x | Reactive UI, panel switching, state | jsDelivr |
| Chart.js | 4.x | Sparklines, bar charts, line charts | jsDelivr |

No build step. Both added as `<script>` tags to `index.html`. Existing vanilla JS stays.

---

## New Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | No | GitHub API token (5000 req/hr vs 60 unauth) |
| `REDDIT_CLIENT_ID` | No | Reddit OAuth app client ID |
| `REDDIT_CLIENT_SECRET` | No | Reddit OAuth app secret |
| `SENDGRID_API_KEY` | Yes (Person 5) | SendGrid email sending |
| `DIGEST_EMAIL` | No | Default recipient for daily digest |

---

## Day-by-Day Plan

### Day 1 — Build independently
| Person | Target |
|--------|--------|
| 1 | HN Algolia end-to-end with engagement scores |
| 2 | `POST/GET /domains` endpoints + manual job trigger |
| 3 | Dashboard UI with mocked data, Alpine.js panel switching |
| 4 | Trend explorer UI with seeded data, all Chart.js charts |
| 5 | Email rendering + `POST /digest/send` sending real email |

### Day 2 — Integrate and polish
| Person | Target |
|--------|--------|
| 1 | GitHub + Reddit APIs wired in |
| 2 | APScheduler auto-runs on boot |
| 3 | Dashboard wired to live `/domains` and `/history` |
| 4 | Timeline endpoint live, explorer fully wired |
| 5 | Digest auto-triggered by scheduler |

---

## Out of Scope

- Personalization / per-user trend filtering — separate spec to be written
- Authentication / multi-user
- Mobile UI
- Podcast API (Listen Notes/Spotify — paid or restricted)
- Twitter/X API (paid)
