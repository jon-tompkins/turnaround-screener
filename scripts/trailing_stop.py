#!/usr/bin/env python3
"""Trailing-stop evaluator for the turnaround screener.

Implements a 20% trailing stop with status differentiation:
  - active: still passing the screen
  - appreciated: no longer passing screen BUT price > entry (graduated, winner)
  - stopped: trailing stop hit (price fell 20% from peak)
  - dropped: legacy status for names that fell off screen before stop logic existed

Run after price updates in the daily pipeline, or standalone:
    python scripts/trailing_stop.py          # evaluate + write to DB
    python scripts/trailing_stop.py --dry    # report only, no writes
"""
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings

TRAIL_STOP_PCT = 0.20  # 20% trailing stop


def get_conn():
    return sqlite3.connect(settings.DB_PATH)


def backfill_peaks(conn):
    """Compute and store peak_price + peak_date for every watchlist entry that doesn't have one.

    Peak = highest daily close between first_seen_date and today (or status_updated
    for dropped names, since we stop tracking those).
    """
    rows = conn.execute(
        "SELECT ticker, first_seen_date, status, status_updated, peak_price "
        "FROM watchlist WHERE peak_price IS NULL"
    ).fetchall()

    updated = 0
    for ticker, first_seen, status, status_updated, _ in rows:
        end_date = status_updated if status in ("dropped", "stopped") else date.today().isoformat()
        peak_row = conn.execute(
            "SELECT date, price FROM daily_prices "
            "WHERE ticker = ? AND date >= ? AND date <= ? "
            "ORDER BY price DESC LIMIT 1",
            (ticker, first_seen, end_date),
        ).fetchone()

        if peak_row:
            conn.execute(
                "UPDATE watchlist SET peak_price = ?, peak_date = ? WHERE ticker = ?",
                (peak_row[1], peak_row[0], ticker),
            )
            updated += 1

    return updated


def evaluate_trailing_stop(conn, dry_run=False):
    """Check every active + appreciated name against the 20% trailing stop.

    If current price <= peak * (1 - TRAIL_STOP_PCT), mark as 'stopped' with exit info.
    Also reclassify 'dropped' names that actually appreciated (price > entry) as 'appreciated'.
    """
    today = date.today().isoformat()
    updates = []

    # Get latest price for each ticker we care about
    tracked = conn.execute(
        "SELECT ticker, first_seen_price, peak_price, peak_date, status, "
        "first_seen_date, status_updated "
        "FROM watchlist WHERE status IN ('active', 'dropped', 'appreciated')"
    ).fetchall()

    for row in tracked:
        ticker, entry_price, peak, peak_dt, status, first_seen, status_updated = row

        # Get latest price
        latest = conn.execute(
            "SELECT price, date FROM daily_prices WHERE ticker = ? "
            "ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if not latest:
            continue

        current_price, latest_date = latest[0], latest[1]
        entry = entry_price

        # Reclassify 'dropped' names: if price > entry, they appreciated, didn't drop
        if status == "dropped":
            if current_price > entry * 1.01:
                # Appreciated out of the screen zone — winner
                # Check if trailing stop would have fired first
                if peak and current_price <= peak * (1 - TRAIL_STOP_PCT):
                    updates.append((ticker, "stopped", current_price, latest_date,
                                    f"trailing_stop_20 (peak {peak:.2f} → {current_price:.2f})"))
                else:
                    updates.append((ticker, "appreciated", None, None, None))
                continue
            else:
                # Genuinely dropped — check if trailing stop would fire
                if peak and current_price <= peak * (1 - TRAIL_STOP_PCT):
                    updates.append((ticker, "stopped", current_price, latest_date,
                                    f"trailing_stop_20 (peak {peak:.2f} → {current_price:.2f})"))
                # else: leave as 'dropped' — fell off screen but didn't hit stop
                continue

        # For active/appreciated: check trailing stop
        if peak and current_price <= peak * (1 - TRAIL_STOP_PCT):
            updates.append((ticker, "stopped", current_price, latest_date,
                            f"trailing_stop_20 (peak {peak:.2f} → {current_price:.2f})"))

    if not dry_run:
        for ticker, new_status, exit_price, exit_date, reason in updates:
            if new_status == "stopped":
                conn.execute(
                    "UPDATE watchlist SET status = ?, status_updated = ?, "
                    "exit_date = ?, exit_price = ?, exit_reason = ? "
                    "WHERE ticker = ?",
                    (new_status, today, exit_date, exit_price, reason, ticker),
                )
            elif new_status == "appreciated":
                conn.execute(
                    "UPDATE watchlist SET status = ?, status_updated = ? "
                    "WHERE ticker = ?",
                    (new_status, today, ticker),
                )

    return updates


def update_appreciated(conn, dry_run=False):
    """Mark active names that no longer pass the screen but are above entry as 'appreciated'.

    This needs to be called with knowledge of which tickers passed today's screen.
    For standalone runs, we just flag names whose status is 'active' but haven't had a
    screen_history pass in the last 5 trading days.
    """
    today = date.today().isoformat()
    updates = []

    active = conn.execute(
        "SELECT ticker, first_seen_price FROM watchlist WHERE status = 'active'"
    ).fetchall()

    for ticker, entry_price in active:
        # Check if passed screen recently
        recent_pass = conn.execute(
            "SELECT 1 FROM screen_history WHERE ticker = ? AND passed = 1 "
            "AND date >= date(?, '-7 days') ORDER BY date DESC LIMIT 1",
            (ticker, today),
        ).fetchone()

        if not recent_pass:
            # Not passing screen — check if above entry
            latest = conn.execute(
                "SELECT price FROM daily_prices WHERE ticker = ? "
                "ORDER BY date DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if latest and latest[0] > entry_price * 1.01:
                updates.append((ticker, "appreciated"))

    if not dry_run:
        for ticker, new_status in updates:
            conn.execute(
                "UPDATE watchlist SET status = ?, status_updated = ? "
                "WHERE ticker = ? AND status = 'active'",
                (new_status, today, ticker),
            )

    return updates


def main():
    parser = argparse.ArgumentParser(description="Run trailing-stop evaluation.")
    parser.add_argument("--dry", action="store_true", help="Report only, no DB writes")
    args = parser.parse_args()

    conn = get_conn()
    conn.row_factory = sqlite3.Row

    print("\n[trailing-stop] Backfilling peaks...")
    n = backfill_peaks(conn)
    print(f"  → {n} peaks backfilled")

    print("\n[trailing-stop] Evaluating 20% trailing stop...")
    updates = evaluate_trailing_stop(conn, dry_run=args.dry)
    for u in updates:
        ticker, new_status, exit_price, exit_date, reason = u
        if new_status == "stopped":
            print(f"  STOPPED: {ticker:6s} exit=${exit_price:.2f} {reason}")
        elif new_status == "appreciated":
            print(f"  APPRECIATED: {ticker:6s} (graduated above entry)")

    print(f"\n  → {len(updates)} status updates ({'dry run' if args.dry else 'applied'})")

    print("\n[trailing-stop] Reclassifying appreciated names...")
    recats = update_appreciated(conn, dry_run=args.dry)
    for ticker, _ in recats:
        print(f"  → {ticker:6s} active → appreciated (above entry, not passing screen)")
    print(f"  → {len(recats)} reclassifications")

    if not args.dry:
        conn.commit()

    # Summary
    print("\n[trailing-stop] Status summary:")
    for r in conn.execute("SELECT status, COUNT(*) as n FROM watchlist GROUP BY status"):
        print(f"  {r['status']:14s}: {r['n']}")

    conn.close()


if __name__ == "__main__":
    main()