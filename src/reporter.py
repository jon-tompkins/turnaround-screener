"""Reporter — generates daily output.

Outputs in order of importance:
  1. Console — always, so you can see what happened
  2. Markdown report — saved to data/reports/YYYY-MM-DD.md
  3. Slack — optional, requires SLACK_WEBHOOK_URL
"""
import json
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from tabulate import tabulate

from config import settings
from src import tracker


def _format_pct(val: Optional[float], digits: int = 1) -> str:
    if val is None:
        return "-"
    return f"{val:+.{digits}f}%"


def build_markdown_report(new_tickers: list[dict], dropped_tickers: list[str],
                          top_candidates: list[dict]) -> str:
    """Build a markdown report for the day's run."""
    today = date.today().isoformat()
    lines = [f"# Turnaround Pipeline — {today}", ""]

    # Summary stats
    lines += [
        f"**New names today:** {len(new_tickers)}  ",
        f"**Dropped from screen:** {len(dropped_tickers)}  ",
        f"**Active watchlist size:** {len(tracker.db.get_active_watchlist())}",
        "",
    ]

    # NEW NAMES — full analysis
    if new_tickers:
        lines += ["## New Names", ""]
        for entry in new_tickers:
            ticker = entry["ticker"]
            analysis = entry.get("analysis", {})

            mode = entry.get("screen_mode") or "?"
            lines += [f"### {ticker} — {analysis.get('company_name', '')} `[{mode}]`",
                      "", f"*{analysis.get('sector', '')} / "
                          f"{analysis.get('industry', '')}*", ""]

            if analysis.get("turnaround_reason"):
                lines += [f"**Setup:** {analysis['turnaround_reason']}", ""]
            if analysis.get("catalyst"):
                lines += [f"**Catalyst:** {analysis['catalyst']} "
                          f"({analysis.get('catalyst_timing', 'TBD')})", ""]
            if analysis.get("suggested_trade"):
                lines += [f"**Suggested trade:** {analysis['suggested_trade']}", ""]
            if analysis.get("conviction_score") is not None:
                lines += [
                    f"**Conviction:** {analysis['conviction_score']}/10 | "
                    f"Upside est: {analysis.get('estimated_upside_pct', '?')}% | "
                    f"Downside est: {analysis.get('estimated_downside_pct', '?')}%",
                    "",
                ]

            if analysis.get("bullish_points"):
                lines += ["**Bullish:**"]
                lines += [f"- {p}" for p in analysis["bullish_points"]]
                lines += [""]
            if analysis.get("bearish_points"):
                lines += ["**Bearish:**"]
                lines += [f"- {p}" for p in analysis["bearish_points"]]
                lines += [""]
            if analysis.get("key_risk"):
                lines += [f"**Key risk:** {analysis['key_risk']}", ""]
            lines += ["---", ""]

    # DROPPED — just list them
    if dropped_tickers:
        lines += ["## Dropped From Screen Today", "",
                  ", ".join(sorted(dropped_tickers)), ""]

    # TOP CANDIDATES — current best of the watchlist
    if top_candidates:
        lines += [f"## Top {len(top_candidates)} Candidates Right Now", ""]
        table_data = []
        for c in top_candidates:
            perf = tracker.performance_since_added(c["ticker"])
            table_data.append([
                c["ticker"],
                (c.get("sector") or "-")[:15],
                c.get("conviction_score") or "-",
                f"${perf.get('current_price') or c.get('first_seen_price') or 0:.2f}",
                _format_pct(perf.get("pct_change")),
                perf.get("days_held", 0),
                (c.get("suggested_trade") or "")[:40],
            ])
        lines += [tabulate(
            table_data,
            headers=["Ticker", "Sector", "Conv", "Price", "Δ Since", "Days", "Trade"],
            tablefmt="pipe",
        ), ""]

    return "\n".join(lines)


def write_markdown_report(content: str) -> Path:
    """Save the markdown report to disk."""
    reports_dir = settings.DATA_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{date.today().isoformat()}.md"
    path.write_text(content)
    return path


def print_console_summary(new_tickers: list[dict], dropped_tickers: list[str],
                          top_candidates: list[dict]):
    """Print a tight summary to stdout."""
    print()
    print("=" * 70)
    print(f"  TURNAROUND PIPELINE — {date.today().isoformat()}")
    print("=" * 70)
    print(f"  New names:    {len(new_tickers)}")
    print(f"  Dropped:      {len(dropped_tickers)}")
    print(f"  Watchlist:    {len(tracker.db.get_active_watchlist())} active")
    print()

    if new_tickers:
        print("  NEW NAMES:")
        for entry in new_tickers:
            a = entry.get("analysis", {})
            mode = entry.get("screen_mode") or "?"
            print(f"    {entry['ticker']:6s}  [{mode:10s}]  "
                  f"conv={a.get('conviction_score', '?')}/10  "
                  f"{(a.get('company_name') or '')[:30]:30s}  "
                  f"{(a.get('suggested_trade') or '')[:40]}")
        print()

    if dropped_tickers:
        print(f"  DROPPED: {', '.join(sorted(dropped_tickers))}")
        print()

    if top_candidates:
        print(f"  TOP {len(top_candidates)} CANDIDATES (current watchlist):")
        for c in top_candidates:
            perf = tracker.performance_since_added(c["ticker"])
            print(f"    {c['ticker']:6s}  conv={c.get('conviction_score', '?')}/10  "
                  f"{_format_pct(perf.get('pct_change')):>8s} since added  "
                  f"{(c.get('suggested_trade') or '')[:50]}")
    print()


def send_slack(content: str, max_chars: int = 4000):
    """Post a summary to Slack via webhook. Truncates if needed."""
    if not settings.SLACK_WEBHOOK_URL:
        return

    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n_[truncated — see full markdown report]_"

    try:
        requests.post(
            settings.SLACK_WEBHOOK_URL,
            json={"text": content, "mrkdwn": True},
            timeout=10,
        )
    except Exception as e:
        print(f"  Slack post failed: {e}")


def _conviction_10_to_5(score) -> int:
    """Map our 1-10 conviction scale to the trading system's 1-5 scale."""
    if score is None:
        return 3
    s = int(score)
    if s >= 9: return 5
    if s >= 7: return 4
    if s >= 5: return 3
    if s >= 3: return 2
    return 1


def _build_idea(ticker: str, direction: str, conviction_raw, thesis: str,
                metadata: dict) -> dict:
    """Build one idea in the trading system's webhook format."""
    return {
        "ticker": ticker,
        "direction": direction,
        "conviction": _conviction_10_to_5(conviction_raw),
        "thesis": thesis[:500] if thesis else "",
        "external_id": f"{date.today().isoformat()}:{ticker}",
        "metadata": metadata,
    }


def send_webhook(new_tickers: list[dict], dropped_tickers: list[str],
                  top_candidates: list[dict]):
    """Push structured JSON to the trading system webhook.

    Format: POST {ideas: [...]} with Bearer auth.
    Sends:
      - 'long' ideas for new high-conviction names (conv >= 4)
      - 'long' ideas for existing top candidates (conv >= 6)
      - 'exit' ideas for names dropped from the screen
    """
    webhook_url = settings.TRADING_WEBHOOK_URL
    if not webhook_url:
        return

    webhook_token = settings.TRADING_WEBHOOK_TOKEN
    ideas = []

    # New names with conviction >= 4 → long signals
    for entry in new_tickers:
        a = entry.get("analysis") or {}
        conv = a.get("conviction_score")
        if conv is None or conv < 4:
            continue

        thesis_parts = []
        if a.get("turnaround_reason"):
            thesis_parts.append(a["turnaround_reason"])
        if a.get("catalyst"):
            thesis_parts.append(f"Catalyst: {a['catalyst']} ({a.get('catalyst_timing', 'TBD')})")
        if a.get("suggested_trade"):
            thesis_parts.append(f"Trade: {a['suggested_trade']}")
        if a.get("key_risk"):
            thesis_parts.append(f"Risk: {a['key_risk']}")

        metadata = {
            "sector": a.get("sector"),
            "screen_mode": entry.get("screen_mode"),
            "price": entry.get("price"),
            "conviction_10": conv,
            "upside_pct": a.get("estimated_upside_pct"),
            "downside_pct": a.get("estimated_downside_pct"),
            "has_options": entry.get("has_options"),
            "source": "turnaround-screener",
            "api": f"http://3.19.242.142:8780/watchlist/{entry['ticker']}",
        }

        ideas.append(_build_idea(
            ticker=entry["ticker"],
            direction="long",
            conviction_raw=conv,
            thesis=" | ".join(thesis_parts),
            metadata=metadata,
        ))

    # Existing top candidates with conviction >= 6 → long signals (reaffirm)
    for c in top_candidates:
        conv = c.get("conviction_score")
        if conv is None or conv < 6:
            continue
        perf = tracker.performance_since_added(c["ticker"])

        metadata = {
            "sector": c.get("sector"),
            "screen_mode": c.get("screen_mode"),
            "first_seen_date": c.get("first_seen_date"),
            "price": perf.get("current_price"),
            "pct_change": perf.get("pct_change"),
            "days_held": perf.get("days_held"),
            "conviction_10": conv,
            "source": "turnaround-screener",
            "api": f"http://3.19.242.142:8780/watchlist/{c['ticker']}",
        }

        thesis = (c.get("suggested_trade") or "")[:500]
        # Skip if this ticker is already in new_names (avoid dup same day)
        if any(i["ticker"] == c["ticker"] for i in ideas):
            continue

        ideas.append(_build_idea(
            ticker=c["ticker"],
            direction="long",
            conviction_raw=conv,
            thesis=thesis,
            metadata=metadata,
        ))

    # Dropped names → exit signals
    for ticker in dropped_tickers:
        metadata = {
            "source": "turnaround-screener",
            "reason": "dropped_from_screen",
            "api": f"http://3.19.242.142:8780/watchlist/{ticker}",
        }
        ideas.append(_build_idea(
            ticker=ticker,
            direction="exit",
            conviction_raw=3,
            thesis="Dropped from turnaround screen — no longer meets criteria.",
            metadata=metadata,
        ))

    if not ideas:
        print("  Webhook: no qualifying ideas to push (need conv >= 4 new or >= 6 existing)")
        return

    headers = {"Content-Type": "application/json"}
    if webhook_token:
        headers["Authorization"] = f"Bearer {webhook_token}"

    try:
        resp = requests.post(webhook_url, json={"ideas": ideas},
                             headers=headers, timeout=30)
        print(f"  Webhook push: {len(ideas)} ideas → {resp.status_code}")
        if resp.status_code >= 400:
            print(f"  Response: {resp.text[:200]}")
    except Exception as e:
        print(f"  Webhook push failed: {e}")


def report_daily(new_tickers: list[dict], dropped_tickers: list[str],
                 top_candidates: list[dict]) -> Path:
    """Generate all outputs. Returns path to markdown report."""
    print_console_summary(new_tickers, dropped_tickers, top_candidates)
    md = build_markdown_report(new_tickers, dropped_tickers, top_candidates)
    path = write_markdown_report(md)
    print(f"  Report saved: {path}")
    send_slack(md)
    send_webhook(new_tickers, dropped_tickers, top_candidates)
    return path
