#!/usr/bin/env python3
"""Diagnose the screen — for each filter, count how many of the universe pass.

Useful when the screen returns 0 hits and you want to know which criterion is
actually eliminating things. Reuses the cached price download from a recent
run if available (data/price_cache.parquet); otherwise re-downloads.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from config import settings
from src import screener


def main():
    universe = screener.load_universe()
    print(f"Universe: {len(universe)} tickers")

    cache = settings.DATA_DIR / "price_cache.pkl"
    if cache.exists():
        print(f"Using cached prices from {cache}")
        prices = pd.read_pickle(cache)
    else:
        print("Downloading prices (this takes ~2 min)...")
        prices = screener.download_prices(universe)
        prices.to_pickle(cache)
        print(f"Cached to {cache}")

    print(f"Got prices for {prices.shape[1]} tickers\n")

    # Compute metrics for everyone
    rows = []
    for t in prices.columns:
        m = screener.compute_metrics(prices[t])
        if m is None:
            continue
        rows.append({"ticker": t, **m})
    df = pd.DataFrame(rows)
    print(f"{len(df)} tickers with enough history\n")

    # Distribution of the two main metrics
    print("=" * 60)
    print("Distribution of % of 200w MA (lower = more beat-down)")
    print("=" * 60)
    print(df["pct_of_200w_ma"].describe(percentiles=[.01, .05, .1, .25, .5]).to_string())
    print(f"\n  < 50% of 200w MA:  {(df['pct_of_200w_ma'] < 50).sum()}")
    print(f"  < 60% of 200w MA:  {(df['pct_of_200w_ma'] < 60).sum()}")
    print(f"  < 75% of 200w MA:  {(df['pct_of_200w_ma'] < 75).sum()}")
    print(f"  < 100% of 200w MA: {(df['pct_of_200w_ma'] < 100).sum()}")

    print("\n" + "=" * 60)
    print("Distribution of % above 200d MA")
    print("=" * 60)
    print(df["pct_above_200d_ma"].describe(percentiles=[.05, .25, .5, .75, .95]).to_string())

    # Apply the actual screen functions to every ticker
    print("\n" + "=" * 60)
    print("Screen results by mode (pre-metadata)")
    print("=" * 60)
    recovering = []
    basing = []
    for _, row in df.iterrows():
        m = row.to_dict()
        rec_pass, _ = screener.passes_recovering(m)
        if rec_pass:
            recovering.append({"ticker": row["ticker"], **m})
            continue
        if settings.ENABLE_BASING_MODE:
            bas_pass, _ = screener.passes_basing(m)
            if bas_pass:
                basing.append({"ticker": row["ticker"], **m})

    print(f"Recovering candidates: {len(recovering)}")
    print(f"Basing candidates:     {len(basing)}")
    print(f"Total:                 {len(recovering) + len(basing)}")
    print("\nNote: metadata filters (mkt cap >= $250M, $5M/day volume) "
          "will further narrow these.")

    cols = ["ticker", "price", "pct_of_200w_ma", "pct_above_200d_ma",
            "pct_of_100d_ma", "pct_change_5d", "pct_change_30d"]
    if recovering:
        print("\n--- Recovering (top 15) ---")
        rdf = pd.DataFrame(recovering).sort_values("pct_of_200w_ma").head(15)
        print(rdf[cols].to_string(index=False, float_format=lambda x: f"{x:7.2f}"))
    if basing:
        print("\n--- Basing (top 15) ---")
        bdf = pd.DataFrame(basing).sort_values("pct_of_200w_ma").head(15)
        print(bdf[cols].to_string(index=False, float_format=lambda x: f"{x:7.2f}"))


if __name__ == "__main__":
    main()
