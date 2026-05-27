from __future__ import annotations

from datetime import datetime, timezone

from app.core.schemas import (
    DeltaInsight,
    DeltaReport,
    ScoreBreakdown,
    TopicLifecycle,
    TopicSnapshot,
)
from app.services.embeddings import EMBED_MATCH_THRESHOLD
from app.services.normalizer import extract_keywords, topic_similarity

# Jaccard threshold below which two topics are considered different.
# 0.15 lets paraphrased headlines of the same event match (e.g. different
# sub-angles of the same conference) while keeping unrelated topics apart.
_MATCH_THRESHOLD = 0.15

# trend_delta_score thresholds for classification
_SPIKE_THRESHOLD = 0.40
_DECLINE_THRESHOLD = -0.30

_CONF_RANK = {"High": 3, "Medium": 2, "Low": 1}


def _score_components(current: TopicSnapshot, previous: TopicSnapshot) -> ScoreBreakdown:
    # Use real matched URL counts when available; fall back to LLM-reported source_count
    cur_count = current.matched_url_count or current.source_count
    prev_count = previous.matched_url_count or previous.source_count
    src_pct = (cur_count - prev_count) / max(prev_count, 1)

    rank_delta = previous.rank - current.rank
    conf_delta = _CONF_RANK.get(current.confidence, 2) - _CONF_RANK.get(previous.confidence, 2)

    # Use real matched domains when available; fall back to source type tags
    cur_domains = set(current.matched_domains) if current.matched_domains else set(current.sources)
    prev_domains = set(previous.matched_domains) if previous.matched_domains else set(previous.sources)
    diversity_delta = len(cur_domains) - len(prev_domains)

    return ScoreBreakdown(
        source_count_contribution=round(src_pct * 0.40, 4),
        rank_contribution=round(rank_delta * 0.25, 4),
        confidence_contribution=round(conf_delta * 0.20, 4),
        diversity_contribution=round(diversity_delta * 0.15, 4),
    )


def compute_trend_delta_score(current: TopicSnapshot, previous: TopicSnapshot) -> float:
    """
    Weighted composite score.
      > 0  = growing / improving
      < 0  = shrinking / declining

    Weights:
      40%  source-count percentage growth
      25%  rank improvement (prev_rank - cur_rank)
      20%  confidence change
      15%  source-diversity change
    """
    b = _score_components(current, previous)
    return round(
        b.source_count_contribution
        + b.rank_contribution
        + b.confidence_contribution
        + b.diversity_contribution,
        4,
    )


_FRESHNESS_REQUIRED = 0.3  # minimum freshness_score for NEW or SPIKING

# ── Lifecycle thresholds ───────────────────────────────────────────────────────
COOLING_AFTER_MISSING_RUNS = 2    # 2+ consecutive misses → COOLING
DORMANT_AFTER_MISSING_RUNS = 5    # 5+ consecutive misses → DORMANT
DORMANT_AFTER_DAYS = 7            # 7+ days since last seen → DORMANT
DISAPPEARED_AFTER_DAYS = 14       # 14+ days since last seen → DISAPPEARED


def _classify(delta_score: float, confidence: str, freshness: float = 0.5) -> str:
    if delta_score >= _SPIKE_THRESHOLD:
        # Block SPIKING when all evidence is stale — growth is repeated old content, not a real spike
        if freshness >= _FRESHNESS_REQUIRED:
            return "SPIKING VS LAST RUN"
        return "STABLE BUT IMPORTANT"
    if delta_score <= _DECLINE_THRESHOLD:
        return "DECLINING"
    if confidence == "Low":
        return "WEAK SIGNAL TO WATCH"
    return "STABLE BUT IMPORTANT"


def _build_reason(
    classification: str,
    current: TopicSnapshot,
    previous: TopicSnapshot,
) -> str:
    cur_count = current.matched_url_count or current.source_count
    prev_count = previous.matched_url_count or previous.source_count
    src_delta = cur_count - prev_count
    src_pct = round(src_delta / max(prev_count, 1) * 100)
    rank_str = f"rank {previous.rank} → {current.rank}"
    src_str = f"{prev_count} → {cur_count} sources"

    if classification == "SPIKING VS LAST RUN":
        return (
            f"Source count grew {src_pct:+d}% ({src_str}), moved from {rank_str}. "
            f"Confidence: {previous.confidence} → {current.confidence}."
        )
    if classification == "DECLINING":
        return (
            f"Source count changed {src_pct:+d}% ({src_str}), moved from {rank_str}. "
            f"Confidence: {previous.confidence} → {current.confidence}."
        )
    if classification == "STABLE BUT IMPORTANT":
        return f"Consistently present — {rank_str}, {src_str}."
    if classification == "WEAK SIGNAL TO WATCH":
        return f"Low confidence but tracked — {rank_str}, {src_str}."
    return f"Delta: {rank_str}, {src_str}."


def _build_reason_new(current: TopicSnapshot) -> str:
    return (
        f"First seen in this run — not present in the previous snapshot. "
        f"Confidence: {current.confidence}, {current.source_count} source(s)."
    )


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _days_apart(ts_a: str, ts_b: str) -> float:
    return abs((_parse_dt(ts_a) - _parse_dt(ts_b)).total_seconds()) / 86400


# ── Lifecycle helpers ─────────────────────────────────────────────────────────

def _topic_in_snap(canonical_id: str, headline_kws: frozenset[str], snap_topics: list[dict]) -> bool:
    """Return True if the topic appears in a snapshot's topic list."""
    for t in snap_topics:
        cid = t.get("canonical_topic_id", "")
        if cid and cid == canonical_id:
            return True
    # Fallback for snapshots predating canonical_topic_id
    if headline_kws:
        for t in snap_topics:
            t_kws = frozenset(t.get("keywords", []))
            if t_kws and topic_similarity(headline_kws, t_kws) >= 0.15:
                return True
    return False


def _rolling_7d_score(
    canonical_id: str,
    headline_kws: frozenset[str],
    snapshot_history: list[dict],
    current_created_at: str,
) -> float:
    """Average weighted_evidence_score across snapshots from the last 7 days."""
    now_dt = _parse_dt(current_created_at)
    scores = []
    for snap in snapshot_history:
        snap_dt = _parse_dt(snap["created_at"])
        if (now_dt - snap_dt).total_seconds() > DORMANT_AFTER_DAYS * 86400:
            break  # history is newest-first; no point scanning beyond 7 days
        for t in snap["topics"]:
            cid = t.get("canonical_topic_id", "")
            matched = (cid and cid == canonical_id) or (
                not cid and headline_kws
                and topic_similarity(headline_kws, frozenset(t.get("keywords", []))) >= 0.15
            )
            if matched:
                scores.append(t.get("weighted_evidence_score", 0.0))
                break
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def _topic_lifecycle(
    prev: TopicSnapshot,
    snapshot_history: list[dict],
    raw_cluster_ids: set[str],
    current_created_at: str,
) -> TopicLifecycle:
    canonical_id = prev.canonical_topic_id
    headline_kws = frozenset(prev.keywords) if prev.keywords else extract_keywords(prev.headline)

    # Detected in current run but below the display cutoff — not truly absent.
    if canonical_id and canonical_id in raw_cluster_ids:
        return TopicLifecycle(
            canonical_topic_id=canonical_id,
            status="NOT_DETECTED_THIS_RUN",
            topic_headline=prev.headline,
            days_since_last_seen=0.0,
            consecutive_missing_runs=0,
            last_seen_at=prev.last_seen_at,
            last_weighted_evidence_score=prev.weighted_evidence_score,
            rolling_7d_weighted_evidence_score=0.0,
        )

    # Walk snapshot_history (newest-first) to count consecutive missing runs.
    consecutive = 1  # current run is the first miss
    last_seen_at = prev.last_seen_at  # may be set from TopicSnapshot tracking
    last_ws = prev.weighted_evidence_score

    for snap in snapshot_history:
        if _topic_in_snap(canonical_id, headline_kws, snap["topics"]):
            if not last_seen_at:
                last_seen_at = snap["created_at"]
            break
        consecutive += 1

    # Compute days since last confirmed sighting.
    if last_seen_at:
        now_dt = _parse_dt(current_created_at)
        ls_dt = _parse_dt(last_seen_at)
        days_since = abs((now_dt - ls_dt).total_seconds()) / 86400
    else:
        days_since = 0.0

    rolling = _rolling_7d_score(canonical_id, headline_kws, snapshot_history, current_created_at)

    if days_since >= DISAPPEARED_AFTER_DAYS:
        status = "DISAPPEARED"
    elif consecutive >= DORMANT_AFTER_MISSING_RUNS or days_since >= DORMANT_AFTER_DAYS:
        status = "DORMANT"
    elif consecutive >= COOLING_AFTER_MISSING_RUNS:
        status = "COOLING"
    else:
        status = "NOT_DETECTED_THIS_RUN"

    return TopicLifecycle(
        canonical_topic_id=canonical_id,
        status=status,
        topic_headline=prev.headline,
        days_since_last_seen=round(days_since, 1),
        consecutive_missing_runs=consecutive,
        last_seen_at=last_seen_at,
        last_weighted_evidence_score=last_ws,
        rolling_7d_weighted_evidence_score=rolling,
    )


# Sorting priority for insight classifications
_CLASS_ORDER = {
    "NEW THIS RUN": 0,
    "SPIKING VS LAST RUN": 1,
    "DECLINING": 2,
    "STABLE BUT IMPORTANT": 3,
    "WEAK SIGNAL TO WATCH": 4,
    "DISAPPEARED": 5,
}


def compute_delta(
    current_topics: list[TopicSnapshot],
    previous_topics: list[TopicSnapshot],
    previous_run_id: str,
    previous_created_at: str,
    current_created_at: str,
    similarity_matrix: list[list[float]] | None = None,
    snapshot_history: list[dict] | None = None,
    raw_cluster_ids: set[str] | None = None,
) -> DeltaReport:
    """
    Match topics across two runs and produce ranked delta insights.

    Matching uses greedy bipartite assignment. When similarity_matrix is provided
    (pre-computed cosine similarities from embeddings), it is used instead of Jaccard.
    Unmatched current topics → NEW. Unmatched previous topics → DISAPPEARED.
    """
    use_embeddings = similarity_matrix is not None
    threshold = EMBED_MATCH_THRESHOLD if use_embeddings else _MATCH_THRESHOLD

    # Pre-compute Jaccard keyword sets (only used as fallback)
    cur_kws = (
        None if use_embeddings
        else [extract_keywords(f"{t.headline} {' '.join(t.keywords)}") for t in current_topics]
    )
    prev_kws = (
        None if use_embeddings
        else [extract_keywords(f"{t.headline} {' '.join(t.keywords)}") for t in previous_topics]
    )

    matched_prev_indices: set[int] = set()
    matches: list[tuple[int, int | None, float]] = []

    for ci in range(len(current_topics)):
        best_sim, best_pi = 0.0, None
        for pi in range(len(previous_topics)):
            if pi in matched_prev_indices:
                continue
            if use_embeddings:
                sim = similarity_matrix[ci][pi]  # type: ignore[index]
            else:
                sim = topic_similarity(cur_kws[ci], prev_kws[pi])  # type: ignore[index]
            if sim > best_sim:
                best_sim, best_pi = sim, pi
        if best_sim >= threshold and best_pi is not None:
            matched_prev_indices.add(best_pi)
            matches.append((ci, best_pi, best_sim))
        else:
            matches.append((ci, None, 0.0))

    insights: list[DeltaInsight] = []

    for cur_idx, prev_idx, _sim in matches:
        cur = current_topics[cur_idx]
        prev = previous_topics[prev_idx] if prev_idx is not None else None

        if prev is None:
            # Topic not seen in previous run.
            # Require some fresh evidence — stale-only content reappearing is not a true new trend.
            if cur.freshness_score >= _FRESHNESS_REQUIRED:
                new_classification = "NEW THIS RUN"
            else:
                new_classification = "WEAK SIGNAL TO WATCH"
            evidence: list[str] = []
            if cur.sources:
                evidence.append(f"Sources: {', '.join(cur.sources)}")
            insights.append(DeltaInsight(
                classification=new_classification,
                topic=cur.headline,
                previous_rank=None,
                current_rank=cur.rank,
                previous_source_count=None,
                current_source_count=cur.source_count,
                rank_delta=None,
                source_count_delta=None,
                previous_confidence=None,
                current_confidence=cur.confidence,
                reason=_build_reason_new(cur),
                evidence=evidence,
                trend_delta_score=0.0,
            ))
        else:
            breakdown = _score_components(cur, prev)
            score = round(
                breakdown.source_count_contribution
                + breakdown.rank_contribution
                + breakdown.confidence_contribution
                + breakdown.diversity_contribution,
                4,
            )
            classification = _classify(score, cur.confidence, cur.freshness_score)
            # A high-novelty topic that matched an old topic by keywords but introduces
            # genuinely new subtopics/angles should surface as NEW, not just STABLE.
            if classification == "STABLE BUT IMPORTANT" and cur.novelty_score >= 0.7:
                classification = "NEW THIS RUN"
            reason = _build_reason(classification, cur, prev)
            cur_count = cur.matched_url_count or cur.source_count
            prev_count = prev.matched_url_count or prev.source_count
            src_delta = cur_count - prev_count
            evidence = [
                f"Sources: {', '.join(cur.sources) if cur.sources else 'none'}",
                f"Source count: {prev_count} → {cur_count} ({src_delta:+d})",
            ]
            insights.append(DeltaInsight(
                classification=classification,
                topic=cur.headline,
                previous_rank=prev.rank,
                current_rank=cur.rank,
                previous_source_count=prev.source_count,
                current_source_count=cur.source_count,
                rank_delta=prev.rank - cur.rank,
                source_count_delta=src_delta,
                previous_confidence=prev.confidence,
                current_confidence=cur.confidence,
                reason=reason,
                evidence=evidence,
                trend_delta_score=score,
                score_breakdown=breakdown,
            ))

    # Classify unmatched previous topics using lifecycle logic.
    _history = snapshot_history or []
    _raw_ids = raw_cluster_ids or set()

    lifecycle: list[TopicLifecycle] = []
    disappeared: list[str] = []

    for pi in range(len(previous_topics)):
        if pi not in matched_prev_indices:
            lc = _topic_lifecycle(previous_topics[pi], _history, _raw_ids, current_created_at)
            lifecycle.append(lc)
            if lc.status == "DISAPPEARED":
                disappeared.append(lc.topic_headline)

    # Sort: by classification priority, then by absolute delta score descending
    insights.sort(
        key=lambda x: (_CLASS_ORDER.get(x.classification, 9), -abs(x.trend_delta_score))
    )

    days = _days_apart(current_created_at, previous_created_at)
    comparison_type = "7_day" if 5.0 <= days <= 9.0 else "most_recent"

    return DeltaReport(
        compared_to_run_id=previous_run_id,
        compared_to_date=previous_created_at,
        days_apart=round(days, 1),
        comparison_type=comparison_type,
        insights=insights,
        disappeared=disappeared,
        lifecycle=lifecycle,
    )
