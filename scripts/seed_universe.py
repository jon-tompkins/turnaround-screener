#!/usr/bin/env python3
"""Seed the ticker universe.

Sources:
  --source broad   (default) SEC EDGAR company_tickers.json — ~10k US-listed
                   names, superset of Russell 3000. The screen's $250M market
                   cap floor filters the long tail.
  --source sp1500  S&P 1500 (S&P 500 + 400 + 600) from Wikipedia — fastest,
                   curated, but skews mega/large cap and misses real
                   turnaround candidates living in small caps.

Usage:
    python scripts/seed_universe.py
    python scripts/seed_universe.py --source sp1500
"""
import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from config import settings


WIKI_LISTS = [
    ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol"),
    ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "Symbol"),
]

WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# SEC requires a real contact in the UA. The address can be anything reachable.
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_HEADERS = {"User-Agent": "TurnaroundScreener research@example.com"}


def seed_from_wikipedia() -> list[str]:
    """Scrape S&P 1500 tickers from Wikipedia."""
    all_tickers = set()
    for url, col in WIKI_LISTS:
        print(f"  Fetching {url}...")
        try:
            resp = requests.get(url, headers=WIKI_HEADERS, timeout=15)
            resp.raise_for_status()
            tables = pd.read_html(io.StringIO(resp.text))
            df = next((t for t in tables if col in t.columns), tables[0])
            tickers = df[col].dropna().astype(str).str.strip().str.upper()
            tickers = tickers.str.replace(".", "-", regex=False)  # yfinance format
            all_tickers.update(tickers.tolist())
            print(f"    → {len(tickers)} tickers")
        except Exception as e:
            print(f"    Failed: {e}")
            continue
    return sorted(all_tickers)


def _looks_like_common_stock(ticker: str) -> bool:
    """Drop tickers that aren't common stock (warrants, units, rights, preferreds)."""
    if not ticker or len(ticker) > 5:
        # Most preferreds and weird share classes have long tickers
        return False
    # Suffixes commonly used for non-common-stock instruments
    if any(ticker.endswith(s) for s in ("W", "U", "R", "P")):
        # Rough but cheap. We tolerate false positives (a few real tickers end in
        # P/R/U/W) because yfinance will simply fail to find them and we skip.
        # Cleaner option later: pull the SEC submissions feed for exact share class.
        pass  # leave alone — too aggressive to drop all of these
    return True


def seed_from_sec() -> list[str]:
    """Pull the SEC EDGAR company tickers (~10k US-listed names)."""
    print(f"  Fetching {SEC_TICKERS_URL}...")
    resp = requests.get(SEC_TICKERS_URL, headers=SEC_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    tickers = set()
    for entry in data.values():
        t = str(entry.get("ticker", "")).strip().upper()
        if not t:
            continue
        t = t.replace(".", "-")  # yfinance format
        if _looks_like_common_stock(t):
            tickers.add(t)
    print(f"    → {len(tickers)} tickers")
    return sorted(tickers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["broad", "sp1500"], default="broad",
                        help="broad = SEC ~10k tickers (default); sp1500 = S&P 1500")
    args = parser.parse_args()

    print(f"Seeding ticker universe (source={args.source})...")
    if args.source == "sp1500":
        tickers = seed_from_wikipedia()
    else:
        tickers = seed_from_sec()

    print(f"\nTotal unique tickers: {len(tickers)}")

    if not tickers:
        print("No tickers fetched; not overwriting universe.csv.")
        return

    df = pd.DataFrame({"ticker": tickers})
    df.to_csv(settings.UNIVERSE_PATH, index=False)
    print(f"Saved to {settings.UNIVERSE_PATH}")


if __name__ == "__main__":
    main()
