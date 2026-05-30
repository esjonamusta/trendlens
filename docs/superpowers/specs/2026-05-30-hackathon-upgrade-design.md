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
- **Time range selector:** 4 separate tabs — Yesterday | Today | This Week | Custom 📅
- **Top trends list:** ranked by average `weighted_evidence_score` over the selected period, with a sparkline per topic
- **Topic detail view:** click any topic → full evidence history with source list per run

### Agreed UI Design (locked in brainstorming session 2026-05-30)

**Time range tabs:**
- 4 separate pill tabs: `Yesterday` | `Today` | `This Week` | `Custom 📅`
- Contained in a single rounded pill container (dark background, subtle border)
- Active tab: purple fill (`#7c5cfc`), white text
- Inactive tabs: muted grey text, hover shows slight highlight

**Trend status labels — 3 labels only:**
- `⬆ Spiking` — green (`#22c55e`)
- `→ Stable` — amber (`#f59e0b`)
- `⬇ Declining` — red (`#ef4444`)
- These map to the codebase classifications: Spiking = `SPIKING VS LAST RUN`, Stable = `STABLE BUT IMPORTANT`, Declining = `DECLINING`
- No standalone label row — badges appear only on each trend row (right side)

**Trend row layout (horizontal):**
```
[ Trend title + meta ]  [ sparkline ]  [ shiny badge ]
```
- Background: `#16161f`, border-radius 12px, padding 14px 18px
- Title: 14px, medium weight, white
- Meta: 11px, muted (`#7878a0`) — shows source count, confidence, sources used
- Sparkline: 72×26px SVG inline, colored by status (green/amber/red), with subtle fill

**Shiny border badge (CSS technique — border-only shine):**
- Outer wrapper: `overflow: hidden`, `border-radius: 999px`, no padding except 1.5px gap
- `::before` pseudo-element: `conic-gradient` rotating spotlight — creates the shine on the border only
- `::after` pseudo-element: solid dark background (`inset: 1.5px`) — covers the interior so shine only shows on the border ring
- Label sits above both pseudo-elements via `z-index: 2`
- Each status has its own speed: Spiking 2.5s, Stable 3.5s, Declining 2.0s
- Inner background colors: Spiking `#0d1f14`, Stable `#1f1608`, Declining `#200d0d`
- Label padding: 5px 14px, 11px font, bold

**CSS for the shine (exact implementation):**
```css
.shine-btn::before {
  content: "";
  position: absolute;
  inset: -100%;
  background: conic-gradient(
    from 0deg,
    transparent 0%, transparent 35%,
    var(--shine) 48%, white 50%, var(--shine) 52%,
    transparent 65%, transparent 100%
  );
  animation: spin var(--speed) linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
.shine-btn::after {
  content: "";
  position: absolute;
  inset: 1.5px;
  border-radius: 999px;
  background: var(--bg);
}
```

**What was explicitly removed:**
- No standalone "Trend Status" section label above the badges
- No large badge row in the middle of the page — badges only on trend rows
- No 7d / 30d / 90d toggles — replaced with Yesterday / Today / This Week / Custom

**Trend row layout (final — with feedback):**
```
[ Rank ]  [ Title + meta ]  [ Sparkline ]  [ Badge + Feedback pill ]
```
- Right side is stacked vertically: shine badge on top, feedback pill below

**Feedback pill (Option B — agreed):**
- Style: pill toggle inside a dark rounded container
- Two options side by side: `👍 Relevant` and `👎 Not for me`
- Active state: green tint for relevant (`rgba(34,197,94,0.15)`, text `#22c55e`), red tint for not relevant
- Inactive: dark background, muted text
- CSS:
```css
.pill-feedback { display:flex; background:#16161f; border-radius:999px; padding:3px; gap:2px; border:1px solid rgba(255,255,255,0.06); }
.pf-btn { padding:4px 11px; border-radius:999px; font-size:11px; font-weight:700; cursor:pointer; color:#7878a0; }
.pf-btn.active-up   { background:rgba(34,197,94,0.15); color:#22c55e; }
.pf-btn.active-down { background:rgba(239,68,68,0.15); color:#ef4444; }
```

**Personalization logic:**
- Personalized tab shows trends matched to user's sign-up profile (keywords, product type, user type)
- Over time, 👍 / 👎 ratings improve the personalization — liked trends surface more, disliked trends are suppressed
- Personalized hint bar shows: "Matched to your profile — [keywords]. Your ratings improve this over time."
- General tab shows all trends unfiltered, no match tags, no hint bar

**Two mode tabs:**
- `✦ Personalized` with tag "For you" (purple tint when active)
- `🌐 General` with tag "All trends" (grey when active)
- Contained in a dark rounded card `#0f0f17`, border-radius 12px

**Post-login flow:**
- After login → straight to Trend Explorer page
- Domains pre-populated from sign-up keywords
- Welcome banner at top: "Welcome to TrendLens, [name] 👋 — We've already run your first report based on your product profile."
- Dismiss button on banner

**Domain selector (top of Trend Explorer):**
- Horizontal pill chips for each tracked domain
- Active domain: purple tint (`rgba(124,92,252,0.12)`), purple border, purple text
- Inactive: dark background, muted text
- `+ Add domain` chip at the end

**Nav (post-login):**
- Left: Logo
- Center: `Trend Explorer` | `Run Research` tabs
- Right: Avatar circle with user initials (purple gradient)

### Chart.js Usage
- Sparklines: inline SVG (not Chart.js) — `polyline` with colored stroke and subtle fill
- Topic detail (on click): `type: 'line'` Chart.js with hover tooltips showing source count

### Backend — Feedback Storage
- New SQLite table: `user_feedback (id, user_id, domain, trend_headline, feedback, created_at)`
- `POST /feedback` already exists — extend to store `relevant` / `not_relevant` instead of just `incorrect`
- Personalized tab filters trends by: keyword match from profile + positive feedback history

### Day 1 Target
Full explorer UI with seeded `history.db` data (3–5 fake runs). All charts rendering and interactive.

### Day 2 Target
Live `GET /history/{domain}/timeline` endpoint wired in. Feedback wired to backend.

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

## Home Page & Login (agreed 2026-05-30)

### Layout
- Two-column grid: `1fr 400px`, max-width 1100px, centered, 60px padding from nav
- Left column: hero copy + feature list
- Right column: login card
- Vertically centered on the page

### Nav
- Logo only (icon + "TrendLens" text) — **no login button in nav**
- Logo icon: 30×30px rounded square, purple gradient (`#7c5cfc → #4f46e5`)
- Subtle bottom border (`rgba(255,255,255,0.06)`)

### Left — Hero Copy
- Eyebrow pill: `✦ Built for Product Managers` — purple tint bg, purple border, `width: fit-content`
- H1: `"Stay ahead of what's trending in your domain"` — gradient text (white fading to 55% white), 800 weight, -1.5px letter spacing
- Subtext: 15px, muted (`#b8b8cc`), max-width 420px
- 3 feature rows below, each with:
  - Purple-tinted icon box (32×32px, rounded 8px)
  - Bold 13px title + 12px muted description

**Feature copy:**
1. 📡 Real signals, not noise — "Sourced from HN, Reddit, GitHub, and the web. Ranked by engagement, not recency."
2. 📈 Track what changes — "Run it again tomorrow and see what spiked, what's new, and what's fading."
3. 📬 Daily digest — "Get a morning email summarising your domains — no manual searching required."

### Right — Login Card
- Background: `#0f0f17`, border `rgba(255,255,255,0.08)`, border-radius 20px, padding 36px 32px
- Title: `Welcome back 👋` (20px, 700 weight)
- Subtitle: `Sign in to your workspace` (13px, muted)
- Email field + Password field — dark input (`#16161f`), focus ring purple
- Primary CTA: `Sign in →` — full-width, purple gradient button
- Divider: `or`
- Secondary CTA: `Continue with Google` — outline button with Google logo SVG
- Footer: `Don't have an account? Sign up free` (purple link)
- **No login button in the nav** — the card is the only login entry point

### What was removed
- Nav "Log in" button — redundant since card is always visible
- Extra vertical space above the eyebrow pill

---

## Sign-Up & Personalisation Page (agreed 2026-05-30, details TBD)

### Layout
- Single page (not multi-step) — all fields on one scroll
- Centered card, max-width 580px, same dark card style as login (`#0f0f17`, border-radius 20px)
- Same nav as home page (logo only)

### Sections & Fields

**Account**
- First name + Last name (two columns)
- Work email
- Password

**Your Product**
- Type of product (dropdown): SaaS/Software, Marketplace, Developer Tool, Fintech, Healthcare, E-commerce, EdTech, Hardware, Other
- Who are your users? (free text — e.g. "students, enterprise engineers, small business owners")
- Business model (pill toggles): B2B | B2C | Both | B2B2C
- Goal of your product (textarea — e.g. "Help finance teams automate expense reporting")

**Trend Interests**
- Keywords (tag input — type and press Enter to add, ✕ to remove)
- Hint text: "These shape which signals TrendLens surfaces for you."

### CTA
- `Create account & start tracking →` — full width purple gradient button
- Footer: `Already have an account? Sign in`

### Notes
- Exact field copy and dropdown options to be refined later
- Pill toggles: clicking activates purple tint style, others go inactive
- Keyword tags: purple tint pill with ✕ remove button

---

## Out of Scope

- Personalization / per-user trend filtering — separate spec to be written
- Authentication / multi-user
- Mobile UI
- Podcast API (Listen Notes/Spotify — paid or restricted)
- Twitter/X API (paid)
