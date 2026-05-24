"""
TrendLens CLI

Usage:
    python cli.py "developer experience"
    python cli.py "fintech compliance" --competitors Plaid Stripe --users "compliance teams"
    python cli.py "AI coding tools" --market "Europe" --days 14 --output report.md
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.pipeline import run_research
from app.core.schemas import ResearchConfig
from app.services.report import to_json, to_markdown


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TrendLens — top 3 news items for your domain")
    p.add_argument("domain", help="Domain to research, e.g. 'developer experience'")
    p.add_argument("--competitors", nargs="*", default=[], metavar="NAME", help="Competitor names")
    p.add_argument("--users", default="", metavar="TEXT", help="Target user description")
    p.add_argument("--market", default="", metavar="TEXT", help="Geographic market")
    p.add_argument("--days", type=int, default=7, metavar="N", help="Time window in days (default: 7)")
    p.add_argument("--output", default="", metavar="FILE", help="Save report to file (.md or .json)")
    p.add_argument("--no-cache", action="store_true", help="Force fresh run, bypass cache")
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    config = ResearchConfig(
        domain=args.domain,
        competitors=args.competitors,
        target_users=args.users,
        geographic_market=args.market,
        time_window_days=args.days,
    )

    print(f"\n🔍 Researching: {config.domain}")
    if config.competitors:
        print(f"   Competitors: {', '.join(config.competitors)}")
    if config.target_users:
        print(f"   Users: {config.target_users}")
    if config.geographic_market:
        print(f"   Market: {config.geographic_market}")
    print(f"   Time window: last {config.time_window_days} days\n")

    report = await run_research(config=config, use_cache=not args.no_cache)

    conf_colors = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}

    for i, item in enumerate(report.items, 1):
        conf = conf_colors.get(item.confidence, "⚪")
        print(f"{'─' * 60}")
        print(f"{i}. {item.headline}  {conf} {item.confidence}")
        print(f"\n   {item.what_happened}")
        print(f"\n   → Why it matters: {item.why_it_matters}")
        print(f"\n   → PM action: {item.pm_action}")
        if item.source_links:
            print(f"\n   Sources: {item.source_links[0]}")
        print()

    print(f"{'─' * 60}\n")

    if args.output:
        path = Path(args.output)
        if path.suffix == ".json":
            path.write_text(to_json(report))
        else:
            path.write_text(to_markdown(report))
        print(f"✓ Report saved to {path}")
    else:
        print("Tip: use --output report.md to save the full report\n")


if __name__ == "__main__":
    asyncio.run(main())
