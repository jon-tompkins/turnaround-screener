#!/usr/bin/env python3
"""Merge completed analyses back into the DB and regenerate the daily report.

The /morning slash command writes analyses to data/analyzed/<YYYY-MM-DD>/<TICKER>.json.
This script reads them, updates each ticker's row in the watchlist, and rebuilds
the markdown report so it includes the full analyses.

Usage:
    python scripts/merge_analyses.py                # use today's date
    python scripts/merge_analyses.py --date 2026-05-27
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from src import db, tracker, reporter


def load_analyses(target_date: str) -> dict:
    """Return {ticker: analysis_dict} from data/analyzed/<date>/."""
    analyzed_dir = settings.DATA_DIR / "analyzed" / target_date
    if not analyzed_dir.exists():
        return {}

    results = {}
    for path in sorted(analyzed_dir.glob("*.json")):
        ticker = path.stem.upper()
        try:
            results[ticker] = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"  ! {ticker}: failed to parse — {e}")
    return results


def merge_into_watchlist(analyses: dict) -> int:
    """Write each analysis back to the watchlist row. Returns count updated."""
    updated = 0
    with db.get_conn() as conn:
        for ticker, analysis in analyses.items():
            existing = conn.execute(
                "SELECT ticker FROM watchlist WHERE ticker = ?", (ticker,)
            ).fetchone()
            if not existing:
                print(f"  ! {ticker}: not in watchlist, skipping")
                continue

            conn.execute(
                "UPDATE watchlist SET "
                "analysis_json = ?, "
                "conviction_score = ?, "
                "suggested_trade = ? "
                "WHERE ticker = ?",
                (
                    json.dumps(analysis),
                    analysis.get("conviction_score"),
                    analysis.get("suggested_trade"),
                    ticker,
                ),
            )
            updated += 1
    return updated


def rebuild_report_for_date(target_date: str, analyses: dict):
    """Regenerate the daily markdown report including the new analyses."""
    pending_dir = settings.DATA_DIR / "pending" / target_date
    new_tickers = []
    if pending_dir.exists():
        for dossier_path in sorted(pending_dir.glob("*.json")):
            ticker = dossier_path.stem.upper()
            dossier = json.loads(dossier_path.read_text())
            analysis = analyses.get(ticker, {
                "ticker": ticker,
                "company_name": dossier.get("overview", {}).get("name"),
                "suggested_trade": "(pending analysis)",
            })
            new_tickers.append({
                "ticker": ticker,
                "screen_mode": dossier.get("screen_mode"),
                "price": dossier.get("overview", {}).get("current_price", 0),
                "analysis": analysis,
            })

    top_candidates = tracker.rank_active_watchlist()
    reporter.report_daily(new_tickers, [], top_candidates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Target date (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    print(f"Merging analyses for {args.date}...")
    analyses = load_analyses(args.date)
    print(f"  Loaded {len(analyses)} analyses")

    if not analyses:
        print("  Nothing to merge.")
        return

    updated = merge_into_watchlist(analyses)
    print(f"  Updated {updated} watchlist rows")

    print("Rebuilding report...")
    rebuild_report_for_date(args.date, analyses)
    print("Done.")


if __name__ == "__main__":
    main()
