"""Screener — finds turnaround candidates.

The core ask: stocks where current price is < 50% of 200-week MA but recovering
above the 200-day MA (by less than 10%). With sanity filters added so we don't
catch falling knives or unusable micro-caps.

The screener is intentionally side-effect free — it reads tickers, returns
results. Tracking + watchlist updates happen in tracker.py.

Usage:
    from src.screener import run_screener
    hits = run_screener()  # returns list[dict] of passing tickers with metrics
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config import settings


def load_universe(path: Optional[Path] = None) -> list[str]:
    """Load ticker universe from CSV. First column = ticker symbol."""
    path = path or settings.UNIVERSE_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Universe file not found at {path}. "
            "Run scripts/seed_universe.py first."
        )
    df = pd.read_csv(path)
    # Normalize: take first column, uppercase, strip, replace dots with dashes
    # (yfinance uses BRK-B not BRK.B)
    col = df.columns[0]
    tickers = (
        df[col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(".", "-", regex=False)
        .unique()
        .tolist()
    )
    return tickers


def download_prices(tickers: list[str], years: int = None) -> pd.DataFrame:
    """Batch download daily close prices for many tickers.

    Returns a DataFrame indexed by date with one column per ticker. Missing
    tickers are simply excluded (yfinance returns NaN columns we drop).
    """
    years = years or settings.LOOKBACK_YEARS
    period = f"{years}y"
    batch_size = settings.BATCH_SIZE

    all_closes = []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        print(f"  Downloading batch {i//batch_size + 1}/"
              f"{(len(tickers)-1)//batch_size + 1} ({len(batch)} tickers)...")
        try:
            data = yf.download(
                batch,
                period=period,
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            print(f"    Batch failed: {e}, continuing.")
            continue

        # Extract just 'Close' for each ticker. yfinance returns different
        # shapes depending on batch size (1 vs many), normalize here.
        if len(batch) == 1:
            t = batch[0]
            if "Close" in data.columns:
                closes = data[["Close"]].rename(columns={"Close": t})
                all_closes.append(closes)
        else:
            for t in batch:
                try:
                    closes = data[t]["Close"].rename(t)
                    if closes.notna().sum() > 0:
                        all_closes.append(closes.to_frame())
                except (KeyError, TypeError):
                    continue

        time.sleep(settings.BATCH_SLEEP_SECONDS)

    if not all_closes:
        return pd.DataFrame()

    combined = pd.concat(all_closes, axis=1)
    # Drop columns that are entirely NaN
    combined = combined.dropna(axis=1, how="all")
    return combined


def compute_metrics(price_series: pd.Series) -> Optional[dict]:
    """Given a price series for one ticker, compute screen metrics.

    Returns None if there's not enough history.
    """
    s = price_series.dropna()
    if len(s) < settings.MIN_HISTORY_DAYS:
        return None

    current = float(s.iloc[-1])

    # 200-day MA — straightforward last 200 trading days
    ma_200d = float(s.tail(200).mean())

    # 100-day MA — additional filter we discussed
    ma_100d = float(s.tail(100).mean())

    # 200-week MA — resample daily to weekly (Friday close), take last 200
    weekly = s.resample("W-FRI").last().dropna()
    if len(weekly) < 200:
        return None
    ma_200w = float(weekly.tail(200).mean())

    def _pct_change(lookback: int) -> float:
        if len(s) >= lookback + 1:
            return (float(s.iloc[-1]) / float(s.iloc[-lookback - 1]) - 1) * 100
        return 0.0

    pct_change_1d = _pct_change(1)
    pct_change_5d = _pct_change(5)
    pct_change_30d = _pct_change(30)

    return {
        "price": current,
        "ma_200d": ma_200d,
        "ma_100d": ma_100d,
        "ma_200w": ma_200w,
        "pct_of_200w_ma": current / ma_200w * 100,
        "pct_above_200d_ma": (current / ma_200d - 1) * 100,
        "pct_of_100d_ma": current / ma_100d * 100,
        "pct_change_1d": pct_change_1d,
        "pct_change_5d": pct_change_5d,
        "pct_change_30d": pct_change_30d,
    }


def _common_sanity_checks(metrics: dict) -> list[str]:
    """Filters that apply to both modes."""
    reasons = []
    if metrics["price"] >= settings.PCT_OF_200W_MA_MAX * metrics["ma_200w"]:
        reasons.append("not_below_half_200w")
    if metrics["pct_change_1d"] < settings.MAX_DAILY_DROP_PCT:
        reasons.append("big_drop_today")
    if metrics["price"] < settings.MIN_PRICE:
        reasons.append("price_too_low")
    return reasons


def passes_recovering(metrics: dict) -> tuple[bool, list[str]]:
    """Original mode: deeply beat-down AND already above 200d MA, recovering."""
    reasons = _common_sanity_checks(metrics)

    if settings.ABOVE_200D_MA and metrics["price"] <= metrics["ma_200d"]:
        reasons.append("not_above_200d")
    if metrics["price"] >= settings.PCT_ABOVE_200D_MA_MAX * metrics["ma_200d"]:
        reasons.append("too_far_above_200d")

    if settings.USE_100D_MA_FILTER:
        ratio_100d = metrics["pct_of_100d_ma"] / 100
        if ratio_100d < settings.PCT_OF_100D_MA_MIN:
            reasons.append("too_far_below_100d")
        elif ratio_100d > settings.PCT_OF_100D_MA_MAX:
            reasons.append("too_far_above_100d")

    if settings.REQUIRE_POSITIVE_5D_CHANGE and metrics["pct_change_5d"] <= 0:
        reasons.append("negative_5d_momentum")

    return (len(reasons) == 0, reasons)


def passes_basing(metrics: dict) -> tuple[bool, list[str]]:
    """Basing mode: deeply beat-down, still below 200d but close to crossing, stable."""
    reasons = _common_sanity_checks(metrics)

    # Must still be BELOW the 200d MA (else it's a recovering candidate)
    if metrics["price"] >= metrics["ma_200d"]:
        reasons.append("already_above_200d")
    # …but close to crossing
    if metrics["pct_above_200d_ma"] < settings.BASING_MIN_PCT_ABOVE_200D:
        reasons.append("too_far_below_200d")

    # Flat-to-mildly-positive 30d momentum (avoid falling knives AND mid-breakouts)
    if metrics["pct_change_30d"] < settings.BASING_MIN_30D_MOMENTUM:
        reasons.append("30d_momentum_too_negative")
    if metrics["pct_change_30d"] > settings.BASING_MAX_30D_MOMENTUM:
        reasons.append("30d_momentum_too_hot")

    # Must be holding above the 100d MA (basing = no fresh downtrend)
    if metrics["pct_of_100d_ma"] / 100 < settings.BASING_MIN_PCT_OF_100D_MA:
        reasons.append("below_100d_floor")

    return (len(reasons) == 0, reasons)


def fetch_metadata(ticker: str) -> dict:
    """Pull market cap, sector, options availability via yfinance Ticker.

    Note: this is one API call per ticker so we only call it for screen passes.
    yf.Ticker(t).info is slow + sometimes flaky; wrap in try/except.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        return {
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "avg_volume": info.get("averageVolume"),
            "shares_outstanding": info.get("sharesOutstanding"),
            # Check options availability — fastest signal is whether options chain has entries
            "has_options": bool(t.options),
        }
    except Exception:
        return {
            "market_cap": None,
            "sector": None,
            "industry": None,
            "avg_volume": None,
            "shares_outstanding": None,
            "has_options": False,
        }


def run_screener(universe: Optional[list[str]] = None,
                 verbose: bool = True) -> list[dict]:
    """Run the full screen and return all passing tickers with metrics.

    Returns list of dicts, sorted by % of 200w MA ascending (most beat-down first).
    """
    if universe is None:
        universe = load_universe()

    if verbose:
        print(f"Screening {len(universe)} tickers...")

    # Phase 1: bulk price download + MA computation
    prices = download_prices(universe)

    if prices.empty:
        if verbose:
            print("No price data returned. Check network / yfinance.")
        return []

    if verbose:
        print(f"  Got price data for {prices.shape[1]} tickers, "
              f"computing metrics + filtering...")

    # Phase 2: compute metrics + apply core filters (no API calls).
    # A ticker can pass via either mode; recovering wins if both.
    candidates = []
    n_recovering = n_basing = 0
    for ticker in prices.columns:
        metrics = compute_metrics(prices[ticker])
        if metrics is None:
            continue
        rec_passed, _ = passes_recovering(metrics)
        bas_passed, _ = passes_basing(metrics) if settings.ENABLE_BASING_MODE else (False, [])
        if rec_passed:
            candidates.append({"ticker": ticker, "screen_mode": "recovering", **metrics})
            n_recovering += 1
        elif bas_passed:
            candidates.append({"ticker": ticker, "screen_mode": "basing", **metrics})
            n_basing += 1

    if verbose:
        print(f"  {len(candidates)} candidates passed MA filters "
              f"({n_recovering} recovering, {n_basing} basing).")

    # Phase 3: enrich with metadata (slower per-ticker calls) + apply liquidity/cap filters
    final = []
    for c in candidates:
        meta = fetch_metadata(c["ticker"])
        c.update(meta)

        # Market cap filter
        if meta["market_cap"] and meta["market_cap"] < settings.MIN_MARKET_CAP:
            continue

        # Dollar volume filter (approximate — use last close * avg volume)
        if meta["avg_volume"]:
            dollar_vol = c["price"] * meta["avg_volume"]
            if dollar_vol < settings.MIN_AVG_DOLLAR_VOLUME:
                continue

        final.append(c)

    if verbose:
        print(f"  {len(final)} candidates passed all filters.")

    # Sort by most beat-down first (lowest % of 200w MA)
    final.sort(key=lambda x: x["pct_of_200w_ma"])
    return final


if __name__ == "__main__":
    # Allow running directly: python -m src.screener
    results = run_screener()
    print(f"\n{len(results)} tickers passed:\n")
    for r in results:
        print(f"  {r['ticker']:6s}  [{r['screen_mode']:10s}]  ${r['price']:7.2f}  "
              f"{r['pct_of_200w_ma']:5.1f}% of 200wMA  "
              f"{r['pct_above_200d_ma']:+6.1f}% vs 200dMA  "
              f"5d {r['pct_change_5d']:+5.1f}%  "
              f"{r.get('sector', '-') or '-':20s}  "
              f"opts={r.get('has_options', False)}")
