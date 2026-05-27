#!/usr/bin/env python3
"""Show the names that pass the deep-drawdown filter but fail the entry window.

These are the actual turnaround candidates the screen is finding — useful for
deciding how to loosen filters.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from config import settings
from src import screener


def main():
    cache = settings.DATA_DIR / "price_cache.pkl"
    if not cache.exists():
        print(f"No price cache at {cache}. Run scripts/diagnose_screen.py first.")
        return

    prices = pd.read_pickle(cache)
    rows = []
    for t in prices.columns:
        m = screener.compute_metrics(prices[t])
        if m is None:
            continue
        rows.append({"ticker": t, **m})
    df = pd.DataFrame(rows)

    # The names the screen cares about: deeply beat-down
    beaten = df[df["pct_of_200w_ma"] < 50].copy()
    beaten = beaten.sort_values("pct_above_200d_ma", ascending=False)

    print(f"{len(beaten)} names < 50% of 200w MA, sorted by % above 200d MA:\n")
    cols = ["ticker", "price", "pct_of_200w_ma", "pct_above_200d_ma",
            "pct_of_100d_ma", "pct_change_5d", "pct_change_1d"]
    print(beaten[cols].to_string(index=False, float_format=lambda x: f"{x:7.2f}"))

    # The interesting subset: above 200d MA (any amount)
    recovering = beaten[beaten["pct_above_200d_ma"] > 0]
    print(f"\n{len(recovering)} of these are above the 200d MA (showing recovery)\n")
    if len(recovering):
        print(recovering[cols].to_string(index=False, float_format=lambda x: f"{x:7.2f}"))


if __name__ == "__main__":
    main()
