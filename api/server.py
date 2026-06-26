#!/usr/bin/env python3
"""
Turnaround Screener REST API
Lightweight read-only API over the pipeline.db for trading agent systems.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import sqlite3
import json
from datetime import date, datetime
from pathlib import Path

# Reuse the project's settings
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "config"))
from settings import DB_PATH

app = FastAPI(
    title="Turnaround Screener API",
    description="Read-only API for the turnaround screener pipeline DB",
    version="0.1.0",
)

# Allow any origin for now (trading agents are internal)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- Pydantic models ----------------

class WatchlistItem(BaseModel):
    ticker: str
    first_seen_date: str
    first_seen_price: float
    sector: Optional[str]
    market_cap: Optional[float]
    has_options: bool
    screen_mode: Optional[str]
    status: str
    status_updated: Optional[str]
    conviction_score: Optional[int]
    suggested_trade: Optional[str]
    notes: Optional[str]


class PricePoint(BaseModel):
    date: str
    price: float
    volume: Optional[int]
    pct_of_200w_ma: Optional[float]
    pct_above_200d_ma: Optional[float]


class ScreenHistoryPoint(BaseModel):
    date: str
    passed: bool


class PipelineRun(BaseModel):
    id: int
    run_date: str
    started_at: Optional[str]
    completed_at: Optional[str]
    tickers_screened: Optional[int]
    tickers_passed: Optional[int]
    new_tickers: Optional[int]
    dropped_tickers: Optional[int]
    claude_api_cost_est: Optional[float]


# ---------------- Endpoints ----------------

@app.get("/")
def root():
    return {
        "name": "Turnaround Screener API",
        "version": "0.1.0",
        "db": str(DB_PATH),
        "endpoints": [
            "/watchlist",
            "/watchlist/{ticker}",
            "/prices/{ticker}",
            "/screen-history/{ticker}",
            "/pipeline-runs",
        ],
    }


@app.get("/health")
def health():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM watchlist")
    wl_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM daily_prices")
    price_count = cur.fetchone()[0]
    conn.close()
    return {"status": "ok", "watchlist_rows": wl_count, "price_rows": price_count}


@app.get("/watchlist", response_model=List[WatchlistItem])
def get_watchlist(
    status: Optional[str] = Query(None, description="Filter by status: active, dropped, etc."),
    min_conviction: Optional[int] = Query(None, ge=1, le=10),
    limit: int = Query(100, le=500),
):
    conn = get_db()
    cur = conn.cursor()

    query = "SELECT * FROM watchlist"
    params = []
    where = []

    if status:
        where.append("status = ?")
        params.append(status)
    if min_conviction is not None:
        where.append("conviction_score >= ?")
        params.append(min_conviction)

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY first_seen_date DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@app.get("/watchlist/{ticker}", response_model=Dict[str, Any])
def get_watchlist_ticker(ticker: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM watchlist WHERE ticker = ?", (ticker.upper(),))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")

    data = dict(row)
    if data.get("analysis_json"):
        try:
            data["analysis"] = json.loads(data["analysis_json"])
        except Exception:
            data["analysis"] = None
    return data


@app.get("/prices/{ticker}", response_model=List[PricePoint])
def get_prices(
    ticker: str,
    limit: int = Query(60, le=500),
    since: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    conn = get_db()
    cur = conn.cursor()

    query = "SELECT date, price, volume, pct_of_200w_ma, pct_above_200d_ma FROM daily_prices WHERE ticker = ?"
    params = [ticker.upper()]

    if since:
        query += " AND date >= ?"
        params.append(since)

    query += " ORDER BY date DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@app.get("/screen-history/{ticker}", response_model=List[ScreenHistoryPoint])
def get_screen_history(
    ticker: str,
    days: int = Query(90, le=365),
):
    conn = get_db()
    cur = conn.cursor()

    # Get recent N days of screen history
    cur.execute(
        """
        SELECT date, passed 
        FROM screen_history 
        WHERE ticker = ? 
        ORDER BY date DESC 
        LIMIT ?
        """,
        (ticker.upper(), days),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@app.get("/pipeline-runs", response_model=List[PipelineRun])
def get_pipeline_runs(limit: int = Query(20, le=100)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM pipeline_runs ORDER BY run_date DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@app.get("/trades")
def get_trades():
    """Placeholder — trades table is currently empty."""
    return {"message": "trades endpoint ready — table is empty", "rows": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8780, log_level="info")