#!/usr/bin/env python3
"""Position management: trailing-stop exits + correct hold/exit classification.

The screener is an ENTRY tool. A name leaving the entry screen (esp. to the
upside, because price rose) is NOT an exit — that's the thesis working. Exits
come from a trailing stop off the high-water mark, or a confirmed thesis break
(handled separately, out of band).

This module:
  1. migrate  — add high/low to daily_prices; add exit/peak fields to watchlist.
  2. backfill — pull daily OHLC since each name's first_seen_date (yfinance has
                full history, so the trailing stop can be replayed retroactively).
  3. replay   — walk each position forward: high-water = running max(High);
                stop triggers when Low <= peak*(1-trail); exit at the stop price.
                Classifies each name holding vs stopped and records the exit.

Trailing stop off the peak doubles as the initial stop: a name that never rises
trips ~trail% below entry; a name that runs up locks in most of the gain.

Usage:
  position_mgmt.py migrate
  position_mgmt.py backfill
  position_mgmt.py replay [--trail 0.15] [--apply]   # dry-run unless --apply
  position_mgmt.py report
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "pipeline.db"

try:
    from config import settings
    TRAIL_DEFAULT = getattr(settings, "TRAIL_STOP_PCT", 0.15)
except Exception:
    TRAIL_DEFAULT = 0.15


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def migrate(c: sqlite3.Connection) -> None:
    dp = {r["name"] for r in c.execute("PRAGMA table_info(daily_prices)")}
    if "high" not in dp:
        c.execute("ALTER TABLE daily_prices ADD COLUMN high REAL")
    if "low" not in dp:
        c.execute("ALTER TABLE daily_prices ADD COLUMN low REAL")
    wl = {r["name"] for r in c.execute("PRAGMA table_info(watchlist)")}
    for col, typ in [("exit_date", "DATE"), ("exit_price", "REAL"),
                     ("exit_reason", "TEXT"), ("peak_price", "REAL"), ("peak_date", "DATE")]:
        if col not in wl:
            c.execute(f"ALTER TABLE watchlist ADD COLUMN {col} {typ}")
    c.commit()
    print("migrate: schema up to date")


def _scalar(v):
    return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)


def _ohlc(ticker: str, start: str) -> list[tuple[str, float, float, float]]:
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return []
    out = []
    for idx, row in df.iterrows():
        try:
            out.append((idx.strftime("%Y-%m-%d"), _scalar(row["Close"]),
                        _scalar(row["High"]), _scalar(row["Low"])))
        except Exception:
            continue
    return out


def backfill(c: sqlite3.Connection) -> None:
    names = c.execute("SELECT ticker, first_seen_date FROM watchlist").fetchall()
    n = 0
    for r in names:
        series = _ohlc(r["ticker"], r["first_seen_date"])
        for d, close, high, low in series:
            c.execute(
                """INSERT INTO daily_prices (ticker, date, price, high, low)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(ticker, date) DO UPDATE SET
                     high=excluded.high, low=excluded.low,
                     price=COALESCE(daily_prices.price, excluded.price)""",
                (r["ticker"], d, round(close, 4), round(high, 4), round(low, 4)),
            )
        if series:
            n += 1
            print(f"  {r['ticker']}: {len(series)} days OHLC from {r['first_seen_date']}")
    c.commit()
    print(f"backfill: {n}/{len(names)} names")


def _replay_one(series: list[sqlite3.Row], entry: float, trail: float) -> dict:
    """series: rows with date, price(close), high, low (ascending). Returns outcome."""
    peak, peak_date = entry, (series[0]["date"] if series else None)
    for row in series:
        hi = row["high"] if row["high"] is not None else row["price"]
        lo = row["low"] if row["low"] is not None else row["price"]
        if hi > peak:
            peak, peak_date = hi, row["date"]
        stop = peak * (1 - trail)
        if lo <= stop:
            return {"status": "stopped", "exit_date": row["date"],
                    "exit_price": round(stop, 4), "peak_price": round(peak, 4),
                    "peak_date": peak_date, "reason": "trailing_stop"}
    last = series[-1] if series else None
    return {"status": "active", "exit_date": None, "exit_price": None,
            "peak_price": round(peak, 4), "peak_date": peak_date,
            "current": last["price"] if last else None}


def replay(c: sqlite3.Connection, trail: float, apply: bool) -> None:
    names = c.execute(
        "SELECT ticker, first_seen_date, first_seen_price, status FROM watchlist"
    ).fetchall()
    holds, stops = [], []
    for r in names:
        series = c.execute(
            "SELECT date, price, high, low FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date",
            (r["ticker"], r["first_seen_date"]),
        ).fetchall()
        if not series:
            continue
        out = _replay_one(series, r["first_seen_price"], trail)
        entry = r["first_seen_price"]
        if out["status"] == "stopped":
            ret = (out["exit_price"] - entry) / entry * 100
            stops.append((r["ticker"], out["exit_date"], out["exit_price"], ret, out["peak_price"]))
            if apply:
                c.execute(
                    "UPDATE watchlist SET status='stopped', status_updated=?, exit_date=?, "
                    "exit_price=?, exit_reason=?, peak_price=?, peak_date=? WHERE ticker=?",
                    (out["exit_date"], out["exit_date"], out["exit_price"], out["reason"],
                     out["peak_price"], out["peak_date"], r["ticker"]),
                )
        else:
            cur = out.get("current") or entry
            ret = (cur - entry) / entry * 100
            holds.append((r["ticker"], entry, cur, ret, out["peak_price"]))
            if apply:
                c.execute(
                    "UPDATE watchlist SET status='active', peak_price=?, peak_date=?, "
                    "exit_date=NULL, exit_price=NULL, exit_reason=NULL WHERE ticker=?",
                    (out["peak_price"], out["peak_date"], r["ticker"]),
                )
    if apply:
        c.commit()

    print(f"\n=== TRAILING STOP {trail*100:.0f}%  ({'APPLIED' if apply else 'DRY-RUN'}) ===")
    print(f"\nHOLDING ({len(holds)}):")
    for t, e, cur, ret, pk in sorted(holds, key=lambda x: -x[3]):
        print(f"  {t:6} entry ${e:8.2f}  now ${cur:8.2f}  {ret:+6.1f}%  peak ${pk:.2f}")
    print(f"\nSTOPPED OUT ({len(stops)}):")
    for t, xd, xp, ret, pk in sorted(stops, key=lambda x: x[3]):
        print(f"  {t:6} exit {xd} ${xp:8.2f}  {ret:+6.1f}%  (peak was ${pk:.2f})")
    if holds:
        avg = sum(h[3] for h in holds) / len(holds)
        win = sum(1 for h in holds if h[3] >= 0) / len(holds) * 100
        print(f"\nOpen book: avg {avg:+.1f}%, {win:.0f}% green")
    if stops:
        avgs = sum(s[3] for s in stops) / len(stops)
        print(f"Closed (stopped): avg {avgs:+.1f}% realized")


def report(c: sqlite3.Connection) -> None:
    rows = c.execute(
        "SELECT ticker, status, first_seen_date, first_seen_price, exit_date, exit_price, "
        "exit_reason, peak_price FROM watchlist ORDER BY status, ticker"
    ).fetchall()
    for r in rows:
        print(dict(r))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("backfill")
    rp = sub.add_parser("replay")
    rp.add_argument("--trail", type=float, default=TRAIL_DEFAULT)
    rp.add_argument("--apply", action="store_true")
    sub.add_parser("report")
    a = ap.parse_args()
    c = conn()
    if a.cmd == "migrate":
        migrate(c)
    elif a.cmd == "backfill":
        migrate(c); backfill(c)
    elif a.cmd == "replay":
        replay(c, a.trail, a.apply)
    elif a.cmd == "report":
        report(c)


if __name__ == "__main__":
    main()
