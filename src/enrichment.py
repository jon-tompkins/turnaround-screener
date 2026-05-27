"""Enrichment — pulls per-ticker context for Claude analysis.

Free sources work fine for v1. Premium APIs (FMP, NewsAPI) improve quality
significantly but cost a bit. All sources gracefully degrade — if an API key
isn't configured, that section is just skipped.

Add new data sources by writing a `fetch_X(ticker)` function and calling it
from `enrich_ticker`.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
import yfinance as yf

from config import settings


def fetch_yfinance_overview(ticker: str) -> dict:
    """Pull all the basic info yfinance has on a ticker. Free."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # Recent earnings
        try:
            earnings_dates = t.earnings_dates.head(4).reset_index().to_dict("records") \
                if t.earnings_dates is not None else []
        except Exception:
            earnings_dates = []

        # Recent news from yfinance
        try:
            news = [
                {
                    "title": n.get("title"),
                    "publisher": n.get("publisher"),
                    "link": n.get("link"),
                    "published": n.get("providerPublishTime"),
                }
                for n in (t.news or [])[:10]
            ]
        except Exception:
            news = []

        return {
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "short_ratio": info.get("shortRatio"),
            "short_percent_of_float": info.get("shortPercentOfFloat"),
            "held_by_insiders": info.get("heldPercentInsiders"),
            "held_by_institutions": info.get("heldPercentInstitutions"),
            "revenue_ttm": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "profit_margins": info.get("profitMargins"),
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            "total_cash": info.get("totalCash"),
            "total_debt": info.get("totalDebt"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "analyst_target_mean": info.get("targetMeanPrice"),
            "analyst_target_high": info.get("targetHighPrice"),
            "analyst_target_low": info.get("targetLowPrice"),
            "recommendation": info.get("recommendationKey"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
            "earnings_dates": earnings_dates,
            "news": news,
        }
    except Exception as e:
        return {"error": f"yfinance fetch failed: {e}"}


def fetch_options_summary(ticker: str) -> dict:
    """Summarize the options chain — IV, OI, available expiries.

    Just enough for Claude to know what's available; not the full chain.
    """
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if not expiries:
            return {"has_options": False}

        # Sample one near-ish expiry for IV context (~3 months out)
        target_date = datetime.now() + timedelta(days=90)
        sample_expiry = min(
            expiries,
            key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d") - target_date).days)
        )

        chain = t.option_chain(sample_expiry)
        atm_iv = None
        try:
            mid_price = chain.calls.iloc[len(chain.calls) // 2]
            atm_iv = float(mid_price.get("impliedVolatility", 0)) * 100
        except (IndexError, KeyError, ValueError):
            pass

        return {
            "has_options": True,
            "num_expiries": len(expiries),
            "nearest_expiry": expiries[0] if expiries else None,
            "farthest_expiry": expiries[-1] if expiries else None,
            "sampled_expiry": sample_expiry,
            "sampled_atm_iv_pct": atm_iv,
            "total_call_oi": int(chain.calls["openInterest"].sum())
                if not chain.calls.empty else 0,
            "total_put_oi": int(chain.puts["openInterest"].sum())
                if not chain.puts.empty else 0,
        }
    except Exception:
        return {"has_options": False}


def fetch_fmp_fundamentals(ticker: str) -> Optional[dict]:
    """Pull richer fundamentals from Financial Modeling Prep. Requires FMP_API_KEY."""
    if not settings.FMP_API_KEY:
        return None
    try:
        base = "https://financialmodelingprep.com/api/v3"
        key = settings.FMP_API_KEY

        # Income statement (last 4 quarters)
        income_r = requests.get(
            f"{base}/income-statement/{ticker}?period=quarter&limit=4&apikey={key}",
            timeout=10,
        )
        # Cash flow
        cashflow_r = requests.get(
            f"{base}/cash-flow-statement/{ticker}?period=quarter&limit=4&apikey={key}",
            timeout=10,
        )
        # Key metrics TTM
        metrics_r = requests.get(
            f"{base}/key-metrics-ttm/{ticker}?apikey={key}",
            timeout=10,
        )

        return {
            "income_statement_quarters": income_r.json() if income_r.ok else [],
            "cash_flow_quarters": cashflow_r.json() if cashflow_r.ok else [],
            "key_metrics_ttm": metrics_r.json() if metrics_r.ok else [],
        }
    except Exception:
        return None


def fetch_insider_activity(ticker: str) -> dict:
    """Pull recent insider transactions. Free via yfinance.

    For richer data, replace with OpenInsider scrape or QuiverQuant API.
    """
    try:
        t = yf.Ticker(ticker)
        insider_purchases = t.insider_purchases
        insider_transactions = t.insider_transactions

        return {
            "insider_purchases_summary": insider_purchases.to_dict("records")
                if insider_purchases is not None and not insider_purchases.empty else [],
            "recent_transactions": (
                insider_transactions.head(10).to_dict("records")
                if insider_transactions is not None and not insider_transactions.empty
                else []
            ),
        }
    except Exception:
        return {"insider_purchases_summary": [], "recent_transactions": []}


def enrich_ticker(ticker: str) -> dict:
    """Pull all the per-ticker data Claude needs for analysis.

    Returns a single dict that can be JSON-serialized and sent to Claude.
    """
    enriched = {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
    }

    print(f"  Enriching {ticker}...")

    enriched["overview"] = fetch_yfinance_overview(ticker)
    enriched["options"] = fetch_options_summary(ticker)
    enriched["insider"] = fetch_insider_activity(ticker)

    fmp = fetch_fmp_fundamentals(ticker)
    if fmp:
        enriched["fmp_fundamentals"] = fmp

    return enriched
