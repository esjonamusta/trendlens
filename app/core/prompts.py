from __future__ import annotations


# ── Source Discovery ────────────────────────────────────────────────────────────

DISCOVERY_SYSTEM = """\
You are a media researcher who knows the podcast and Reddit landscape deeply.
Given a domain, identify the most relevant sources where practitioners actually talk.

Be specific. Name real shows and real subreddits, not generic ones.
"""

DISCOVERY_USER = """\
Domain: {domain}
Competitors: {competitors}
Target users: {target_users}
{product_context}
Identify:
- podcasts: 3-5 podcast show names that practitioners in this domain actually listen to.
  Name real shows. Focus on product, industry, and practitioner podcasts — not generic tech news.
- subreddits: 3-5 subreddits in r/name format where real users and builders discuss this domain.

Examples of good podcast answers: "Lenny's Podcast", "The Product Podcast", "acquired"
Examples of good subreddit answers: "r/SaaS", "r/devops", "r/fintech"
"""


# ── Trend Summarization ────────────────────────────────────────────────────────

SUMMARIZE_SYSTEM = """\
You are a senior product researcher. Your job is to write clear, actionable summaries \
of trend signals for product managers.

You will receive pre-ranked trend clusters — groups of related search results that have \
already been scored and grounded. Each cluster's confidence label is computed from real \
evidence counts. Do not modify it.

RULES:
- Summarize only what the evidence in each cluster actually shows. Do not invent facts.
- DO NOT generate URLs or links. All source links are already attached from search data.
- DO NOT change or override the confidence label. It is computed from real data.
- Plain English. No jargon. No hedging.
- pm_action must start with a verb and be something a PM can do this week.
- Every item must relate to roadmap decisions, user behaviour, competitive moves, or GTM.
- When product context is provided, frame why_it_matters and pm_action specifically \
  for that product and PM — not generically "a PM in this space".

GOOD pm_action: "Talk to 5 users who switched to [competitor] and ask what tipped them."
BAD pm_action: "Consider monitoring competitive developments in this space."
"""

SUMMARIZE_USER = """\
Domain: {domain}
Competitors: {competitors}
Target users: {target_users}
Geographic market: {geographic_market}
{product_context}{excluded_section}\
Write exactly {count} summaries — one per cluster, in the order given. \
Clusters are pre-ranked by evidence strength (most evidence first).

{cluster_text}
"""

_EXCLUDED_SECTION_TEMPLATE = """\
PREVIOUSLY MARKED AS INCORRECT — do not include these topics:
{headlines}

"""


def format_product_context(profile: dict) -> str:
    """Build a product context block for prompt injection from a stored profile.

    Only non-empty fields are included. Returns an empty string when the profile
    has no useful content, so prompts degrade gracefully without a profile.
    """
    lines: list[str] = []

    if profile.get("product_description"):
        lines.append(f"What it does: {profile['product_description']}")
    if profile.get("product_stage"):
        lines.append(f"Stage: {profile['product_stage']}")
    if profile.get("tech_stack"):
        lines.append(f"Tech stack: {', '.join(profile['tech_stack'])}")
    if profile.get("customer_segment"):
        lines.append(f"Selling to: {profile['customer_segment']}")
    if profile.get("user_pain_points"):
        lines.append(f"User pain points: {'; '.join(profile['user_pain_points'])}")
    pm_parts = [profile.get("pm_role", ""), profile.get("pm_focus", "")]
    pm_str = " — ".join(p for p in pm_parts if p)
    if pm_str:
        lines.append(f"PM context: {pm_str}")

    if not lines:
        return ""

    return "Product context:\n" + "\n".join(f"- {line}" for line in lines) + "\n\n"
