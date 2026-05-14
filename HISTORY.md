# History + Delta System

TrendLens persists every research run and compares new runs against previous ones to surface what actually changed — not just what is trending now.

---

## How it works

### 1. Persistence

Every successful research run is saved to `history.db` (SQLite, WAL mode) in the `snapshots` table:

| Column | Description |
|--------|-------------|
| `run_id` | UUID for this run |
| `domain` | Lowercased domain key |
| `config_json` | Full `ResearchConfig` |
| `report_json` | Full `ResearchReport` |
| `topics_json` | Extracted `TopicSnapshot` list (see below) |
| `created_at` | UTC ISO8601 timestamp |

Each run extracts a `TopicSnapshot` from every `ResearchItem` — a normalised representation storing rank, headline, keywords, confidence, source count, and source types. These snapshots are what the delta engine compares.

### 2. Previous run selection

When a new run completes, the system finds the best previous snapshot for the same domain:

- **Preferred**: the snapshot whose age is closest to **7 days ago**
- **Fallback**: the most recent prior snapshot if no 7-day one exists
- **Baseline**: if no previous snapshot exists at all, the run is marked `is_baseline: true` and no delta is computed

### 3. Topic matching

Topics are matched across runs using **Jaccard similarity on keyword sets**:

1. Extract keywords from `headline + what_happened` — strip stopwords, normalise hyphens, require ≥ 3 chars.
2. For each current topic, find the best-matching previous topic (greedy bipartite assignment).
3. Pairs with Jaccard ≥ 0.20 are matched as the "same story". Below the threshold = treated as different.

This handles near-duplicate headlines ("agent infrastructure grows" ↔ "agent infrastructure open source adoption") without false positives on unrelated topics.

### 4. Delta scoring (`trend_delta_score`)

Each matched topic pair gets a composite score:

| Factor | Weight | Direction |
|--------|--------|-----------|
| Source count % change | 40% | Higher = better |
| Rank improvement (`prev_rank − cur_rank`) | 25% | Higher = better |
| Confidence change (High=3, Med=2, Low=1) | 20% | Higher = better |
| Source diversity change (# unique source types) | 15% | Higher = better |

Score > 0 = growing. Score < 0 = declining.

### 5. Classification

| Classification | Condition |
|----------------|-----------|
| `NEW THIS RUN` | No matching previous topic |
| `SPIKING VS LAST RUN` | `trend_delta_score ≥ 0.40` |
| `DECLINING` | `trend_delta_score ≤ −0.30` |
| `STABLE BUT IMPORTANT` | Matched, High confidence, score in (−0.30, 0.40) |
| `WEAK SIGNAL TO WATCH` | Matched, Low confidence, not declining |
| `DISAPPEARED` | In previous run but no match in current |

Insights are ranked: NEW → SPIKING → DECLINING → STABLE → WEAK, then by `|trend_delta_score|` descending within each bucket.

---

## API

### `POST /research`

Returns `ResearchReportWithDelta` — the existing report format plus:

```json
{
  "run_id": "uuid",
  "is_baseline": false,
  "delta": {
    "compared_to_run_id": "...",
    "compared_to_date": "2026-05-15T10:00:00+00:00",
    "days_apart": 7.0,
    "comparison_type": "7_day",
    "insights": [
      {
        "classification": "SPIKING VS LAST RUN",
        "topic": "Open-source agent infrastructure grows rapidly",
        "previous_rank": 3,
        "current_rank": 1,
        "previous_source_count": 5,
        "current_source_count": 17,
        "rank_delta": 2,
        "source_count_delta": 12,
        "previous_confidence": "Medium",
        "current_confidence": "High",
        "reason": "Source count grew +240% (5 → 17 sources), moved from rank 3 → 1. Confidence: Medium → High.",
        "evidence": ["Sources: podcast, reddit, web", "Source count: 5 → 17 (+12)"],
        "trend_delta_score": 1.05
      }
    ],
    "disappeared": ["Blockchain payments regulation news"]
  }
}
```

On the first run for a domain: `is_baseline: true`, `delta: null`.

### `GET /history/{domain}?limit=10`

Returns recent snapshot summaries for a domain (most recent first), including topics extracted from each run.

---

## Edge cases

| Scenario | Behaviour |
|----------|-----------|
| No prior history | `is_baseline: true`, delta is `null`, UI shows baseline message |
| Incomplete previous data | Delta still computed; low-confidence insights marked as `WEAK SIGNAL TO WATCH` |
| Duplicate sources | URL deduplication happens in the research agent before topics are extracted |
| Near-duplicate topic names | Keyword Jaccard matching handles rewording within the same story |
| Renamed topics | Treated as DISAPPEARED + NEW (correct: the narrative genuinely changed) |

---

## Running tests

```bash
pytest tests/ -v
```

Tests cover: baseline behaviour, 7-day snapshot selection, most-recent fallback, new topic detection, disappeared topic detection, spike detection, decline detection, ranking by significance, and near-duplicate normalisation.
