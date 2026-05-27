#!/usr/bin/env python3
"""Retrospective — review how the watchlist has performed.

Asks Claude to find patterns: which conviction scores actually correlated with
returns? Which sectors panned out? What signals did we miss?

This is the feedback loop. Run weekly or monthly. Findings should inform the
analyst.py prompt and screener.py filters.

Usage:
    python scripts/retrospective.py                 # last 30 days
    python scripts/retrospective.py --since 90d
    python scripts/retrospective.py --since 6m
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import Anthropic

from config import settings
from src import db, tracker


def parse_since(s: str) -> int:
    """Parse '30d', '6m', '1y' into days."""
    s = s.lower().strip()
    if s.endswith("d"):
        return int(s[:-1])
    if s.endswith("w"):
        return int(s[:-1]) * 7
    if s.endswith("m"):
        return int(s[:-1]) * 30
    if s.endswith("y"):
        return int(s[:-1]) * 365
    return int(s)


def gather_watchlist_performance(since_days: int) -> list[dict]:
    """For every watchlist name added within the window, compute performance."""
    cutoff = (date.today() - timedelta(days=since_days)).isoformat()
    watchlist = db.get_active_watchlist()

    results = []
    for w in watchlist:
        if w["first_seen_date"] < cutoff:
            continue
        perf = tracker.performance_since_added(w["ticker"])
        analysis = json.loads(w["analysis_json"]) if w["analysis_json"] else {}

        results.append({
            "ticker": w["ticker"],
            "added": w["first_seen_date"],
            "status": w["status"],
            "first_seen_price": w["first_seen_price"],
            "current_price": perf.get("current_price"),
            "pct_change": perf.get("pct_change"),
            "days_held": perf.get("days_held"),
            "conviction_score": w["conviction_score"],
            "sector": w["sector"],
            "suggested_trade": w["suggested_trade"],
            "catalyst": analysis.get("catalyst"),
            "key_risk": analysis.get("key_risk"),
            "estimated_upside_pct": analysis.get("estimated_upside_pct"),
            "estimated_downside_pct": analysis.get("estimated_downside_pct"),
        })
    return results


RETRO_PROMPT = """You are reviewing a turnaround stock watchlist that has been
running for a while. Look at the performance data and find honest, actionable
patterns.

Specifically address:

1. **Conviction calibration.** Do high-conviction (8+) names actually outperform
   low-conviction (4-5) names? If not, the analyst prompt is mis-calibrated and
   needs adjustment. Be specific about by how much.

2. **Sector patterns.** Which sectors have been winners? Which have been traps?
   Is there a pattern in the catalyst types that paid off vs didn't?

3. **Timing patterns.** How long after being added did winners actually start
   working? Are we adding too early (still falling) or too late (move already
   happened)? Suggest specific filter adjustments if so.

4. **Signal that should be added.** What additional data point, had we tracked
   it from the start, would have separated winners from losers?

5. **Signal that should be removed.** Is any criterion in the current screen
   actually negative — i.e., names failing that criterion did better than names
   passing it?

6. **Top 3 actionable changes to the system.** Concrete edits to the prompt or
   filters that would have improved hit rate.

Be brutally honest. If the data shows the system isn't working, say so. If it
shows specific traps (e.g. "biotechs without partner deals always failed"),
state them explicitly.

Output in markdown."""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="30d",
                        help="Window to analyze (e.g. 30d, 90d, 6m, 1y)")
    parser.add_argument("--save", action="store_true",
                        help="Save report to data/reports/retro-YYYY-MM-DD.md")
    args = parser.parse_args()

    since_days = parse_since(args.since)
    print(f"Gathering watchlist performance for the last {since_days} days...")

    perf_data = gather_watchlist_performance(since_days)
    if not perf_data:
        print("No watchlist entries in window. Run the daily pipeline first.")
        return

    print(f"  → {len(perf_data)} entries to review")

    # Also pull aggregate stats for context
    aggregate_stats = {
        "total_entries": len(perf_data),
        "avg_pct_change": sum(p["pct_change"] or 0 for p in perf_data) / len(perf_data),
        "win_rate": sum(1 for p in perf_data if (p["pct_change"] or 0) > 0) / len(perf_data),
        "best_performer": max(perf_data, key=lambda p: p["pct_change"] or -999)["ticker"],
        "worst_performer": min(perf_data, key=lambda p: p["pct_change"] or 999)["ticker"],
    }

    print(f"  Avg return: {aggregate_stats['avg_pct_change']:+.1f}%")
    print(f"  Win rate: {aggregate_stats['win_rate']:.0%}")
    print()
    print("Asking Claude for retrospective analysis...")

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.RETROSPECTIVE_MODEL,
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": f"{RETRO_PROMPT}\n\nAggregate stats:\n"
                       f"{json.dumps(aggregate_stats, indent=2)}\n\n"
                       f"Per-ticker data:\n"
                       f"{json.dumps(perf_data, indent=2, default=str)}"
        }]
    )

    report = response.content[0].text
    print("\n" + "=" * 70)
    print(report)
    print("=" * 70)

    if args.save:
        reports_dir = settings.DATA_DIR / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"retro-{date.today().isoformat()}.md"
        path.write_text(report)
        print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
