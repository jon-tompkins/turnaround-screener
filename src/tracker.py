"""Tracker — manages the persistent watchlist.

This is what makes the system stateful. The screener returns a flat list; the
tracker compares that to what's already on the watchlist, identifies what's
new vs dropped, and updates persistent state.
"""
from datetime import date, timedelta
import pandas as pd
import yfinance as yf

from src import db
from config import settings


def diff_against_watchlist(screen_results: list[dict]) -> tuple[list[dict], list[str]]:
    """Compare today's screen hits to the active watchlist.

    Returns:
        (new_tickers, dropped_tickers)
        new_tickers: list of full screen result dicts for names not yet on watchlist
        dropped_tickers: list of tickers that were active but didn't pass today
    """
    today_tickers = {r["ticker"] for r in screen_results}
    active_tickers = db.get_active_tickers()

    truly_new = [r for r in screen_results if r["ticker"] not in active_tickers]
    dropped = list(active_tickers - today_tickers)

    return truly_new, dropped


def record_screen_results(screen_results: list[dict], full_universe: list[str]):
    """Log who passed and who didn't for today's run."""
    passed = {r["ticker"] for r in screen_results}
    for ticker in full_universe:
        db.record_screen_result(ticker, ticker in passed)


def update_watchlist_prices() -> int:
    """Pull today's price for everything still being tracked (active + dropped).

    Returns count of tickers updated. Uses a single batched yfinance call.
    """
    tracked = db.get_active_watchlist()
    if not tracked:
        return 0

    tickers = [t["ticker"] for t in tracked]

    # Just need today's close + 200d and 200w context, so pull 5y like the screener
    try:
        data = yf.download(
            tickers,
            period="5y",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        print(f"  Price update failed: {e}")
        return 0

    updated = 0
    for t in tickers:
        try:
            if len(tickers) == 1:
                closes = data["Close"]
            else:
                closes = data[t]["Close"]
            closes = closes.dropna()
            if len(closes) < 200:
                continue

            price = float(closes.iloc[-1])
            volume = None
            try:
                volume = int(data[t]["Volume"].iloc[-1]) if len(tickers) > 1 \
                    else int(data["Volume"].iloc[-1])
            except (KeyError, ValueError):
                pass

            ma_200d = float(closes.tail(200).mean())
            weekly = closes.resample("W-FRI").last().dropna()
            ma_200w = float(weekly.tail(200).mean()) if len(weekly) >= 200 else None

            pct_of_200w = (price / ma_200w * 100) if ma_200w else None
            pct_above_200d = (price / ma_200d - 1) * 100

            db.record_daily_price(t, price, volume, pct_of_200w, pct_above_200d)
            updated += 1
        except (KeyError, TypeError, IndexError):
            continue

    return updated


def rank_active_watchlist(top_n: int = None) -> list[dict]:
    """Return the most interesting watchlist names, sorted by conviction score.

    Ranking factors (in order):
      1. Conviction score (from Claude analysis)
      2. How recently added (newer = fresher thesis)
      3. % of 200w MA (more beat down = more upside potential)
    """
    top_n = top_n or settings.TOP_N_CANDIDATES
    watchlist = db.get_active_watchlist()

    # Filter to active only for "best candidates today" ranking
    active = [w for w in watchlist if w["status"] == "active"]

    # Augment with latest price snapshot
    for w in active:
        history = db.get_price_history(w["ticker"], days=1)
        if history:
            w["current_pct_of_200w_ma"] = history[0].get("pct_of_200w_ma")
            w["current_price"] = history[0].get("price")

    # Sort by conviction desc, then by pct_of_200w_ma asc (most beat down)
    active.sort(
        key=lambda w: (
            -(w.get("conviction_score") or 0),
            w.get("current_pct_of_200w_ma") or 100,
        )
    )
    return active[:top_n]


def days_on_watchlist(ticker: str) -> int:
    """How many days has this ticker been on the watchlist?"""
    watchlist = db.get_active_watchlist()
    for w in watchlist:
        if w["ticker"] == ticker:
            first_seen = date.fromisoformat(w["first_seen_date"])
            return (date.today() - first_seen).days
    return 0


def performance_since_added(ticker: str) -> dict:
    """Calculate price change since this ticker was first seen.

    Useful for the daily report — see how added names have actually performed.
    """
    watchlist = db.get_active_watchlist()
    entry = next((w for w in watchlist if w["ticker"] == ticker), None)
    if not entry:
        return {}

    initial_price = entry["first_seen_price"]
    history = db.get_price_history(ticker, days=1)
    if not history:
        return {"initial_price": initial_price}

    current = history[0]["price"]
    return {
        "initial_price": initial_price,
        "current_price": current,
        "pct_change": (current / initial_price - 1) * 100,
        "days_held": days_on_watchlist(ticker),
    }
