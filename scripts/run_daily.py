#!/usr/bin/env python3
"""Daily run — main orchestration script.

The full pipeline:
  1. Load universe
  2. Run screener
  3. Diff against watchlist (new vs dropped vs unchanged)
  4. Update prices for all tracked tickers
  5. For NEW tickers only: enrich, then either
       (a) analyze via Claude API (default), or
       (b) --skip-analysis: dump dossier to data/pending/<date>/<TICKER>.json
           for later analysis (e.g. by Claude Code via /morning), or
       (c) --dry-run: skip enrichment and Claude entirely
  6. Rank current watchlist
  7. Generate report (console + markdown + optional Slack)
  8. Log the run

Usage:
    python scripts/run_daily.py                   # full run (uses paid API)
    python scripts/run_daily.py --skip-analysis   # dump pending dossiers, no Claude
    python scripts/run_daily.py --dry-run         # screen only, no enrichment
    python scripts/run_daily.py --force-reanalyze TICKER
"""
import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Path setup so we can import from src/ and config/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import screener, tracker, enrichment, analyst, reporter, db
from config import settings


def main():
    parser = argparse.ArgumentParser(description="Run the daily turnaround pipeline.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run screener only, skip enrichment + Claude")
    parser.add_argument("--skip-analysis", action="store_true",
                        help="Enrich + dump dossiers to data/pending/ but skip Claude")
    parser.add_argument("--force-reanalyze", metavar="TICKER",
                        help="Re-run Claude analysis on a specific ticker")
    parser.add_argument("--no-slack", action="store_true",
                        help="Skip Slack notification even if webhook configured")
    args = parser.parse_args()

    started_at = datetime.now()
    print(f"\n[{started_at.strftime('%Y-%m-%d %H:%M:%S')}] Pipeline start.")

    # Ensure DB exists
    db.init_db()

    # Handle force-reanalyze short-circuit
    if args.force_reanalyze:
        ticker = args.force_reanalyze.upper()
        print(f"\nForce re-analyzing {ticker}...")
        enriched = enrichment.enrich_ticker(ticker)
        analysis = analyst.analyze_ticker(enriched)
        db.add_to_watchlist(
            ticker,
            price=enriched.get("overview", {}).get("current_price", 0),
            sector=enriched.get("overview", {}).get("sector"),
            market_cap=enriched.get("overview", {}).get("market_cap"),
            has_options=enriched.get("options", {}).get("has_options", False),
            analysis=analysis,
        )
        print(f"\nAnalysis for {ticker}:")
        print(json.dumps(analysis, indent=2))
        return

    # === STAGE 1: Screen ===
    print("\n[1/5] Running screener...")
    universe = screener.load_universe()
    screen_results = screener.run_screener(universe)
    print(f"      → {len(screen_results)} tickers passed all filters")

    # === STAGE 2: Diff + record ===
    print("\n[2/5] Diffing against watchlist...")
    new_tickers_data, dropped_tickers = tracker.diff_against_watchlist(screen_results)
    print(f"      → {len(new_tickers_data)} new, {len(dropped_tickers)} dropped")

    tracker.record_screen_results(screen_results, universe)
    for ticker in dropped_tickers:
        db.mark_dropped(ticker)

    # === STAGE 3: Update prices for entire watchlist ===
    print("\n[3/5] Updating prices for tracked tickers...")
    updated_count = tracker.update_watchlist_prices()
    print(f"      → {updated_count} prices updated")

    # Also record prices for new tickers
    for entry in new_tickers_data:
        db.record_daily_price(
            entry["ticker"],
            price=entry["price"],
            pct_of_200w_ma=entry["pct_of_200w_ma"],
            pct_above_200d_ma=entry["pct_above_200d_ma"],
        )

    # === STAGE 4: Enrich + (optionally) analyze NEW tickers ===
    print(f"\n[4/5] Enriching {len(new_tickers_data)} new tickers...")
    total_cost = 0.0
    new_with_analysis = []
    pending_dir = settings.DATA_DIR / "pending" / date.today().isoformat()
    if args.skip_analysis and new_tickers_data:
        pending_dir.mkdir(parents=True, exist_ok=True)

    for entry in new_tickers_data:
        ticker = entry["ticker"]
        try:
            if args.dry_run:
                # Dry-run is read-only: no DB writes, no enrichment, no Claude.
                print(f"  (dry-run) {ticker}: skipping enrichment + Claude")
                entry["analysis"] = {
                    "ticker": ticker,
                    "conviction_score": None,
                    "suggested_trade": "(dry-run — no analysis)",
                }
                new_with_analysis.append(entry)
                continue

            enriched = enrichment.enrich_ticker(ticker)
            enriched["screen_mode"] = entry.get("screen_mode")
            enriched["screen_metrics"] = {
                k: entry[k] for k in (
                    "pct_of_200w_ma", "pct_above_200d_ma", "pct_of_100d_ma",
                    "pct_change_1d", "pct_change_5d", "pct_change_30d",
                ) if k in entry
            }

            if args.skip_analysis:
                # Dump dossier for later analysis (e.g. by Claude Code /morning)
                dossier_path = pending_dir / f"{ticker}.json"
                dossier_path.write_text(json.dumps(enriched, indent=2, default=str))
                print(f"    {ticker}: dossier → {dossier_path.relative_to(settings.ROOT_DIR)}")
                analysis = None
            else:
                analysis = analyst.analyze_ticker(enriched)
                cost = analysis.get("_meta", {}).get("cost_estimate_usd", 0)
                total_cost += cost
                print(f"    {ticker}: conviction {analysis.get('conviction_score', '?')}/10  "
                      f"(${cost:.3f})")

            db.add_to_watchlist(
                ticker=ticker,
                price=entry["price"],
                sector=enriched.get("overview", {}).get("sector"),
                market_cap=enriched.get("overview", {}).get("market_cap"),
                has_options=enriched.get("options", {}).get("has_options", False),
                screen_mode=entry.get("screen_mode"),
                analysis=analysis,
            )
            entry["analysis"] = analysis or {
                "ticker": ticker,
                "company_name": enriched.get("overview", {}).get("name"),
                "sector": enriched.get("overview", {}).get("sector"),
                "suggested_trade": "(pending analysis)",
            }
            new_with_analysis.append(entry)
            time.sleep(0.5)  # gentle on the APIs

        except Exception as e:
            print(f"    {ticker}: enrichment/analysis failed — {e}")
            continue

    if not (args.dry_run or args.skip_analysis):
        print(f"      → Estimated Claude API spend: ${total_cost:.3f}")

    # === STAGE 5: Rank + report ===
    print("\n[5/5] Generating report...")
    top_candidates = tracker.rank_active_watchlist()

    if args.no_slack:
        settings_module = sys.modules["config.settings"]
        settings_module.SLACK_WEBHOOK_URL = None

    reporter.report_daily(new_with_analysis, dropped_tickers, top_candidates)

    # Log the run
    completed_at = datetime.now()
    notes = None
    if args.dry_run:
        notes = "dry-run"
    elif args.skip_analysis:
        notes = "skip-analysis"
    db.log_run({
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "tickers_screened": len(universe),
        "tickers_passed": len(screen_results),
        "new_tickers": len(new_tickers_data),
        "dropped_tickers": len(dropped_tickers),
        "claude_api_cost_est": total_cost,
        "notes": notes,
    })

    duration = (completed_at - started_at).total_seconds()
    print(f"\n[{completed_at.strftime('%Y-%m-%d %H:%M:%S')}] "
          f"Pipeline complete in {duration:.1f}s.\n")


if __name__ == "__main__":
    main()
