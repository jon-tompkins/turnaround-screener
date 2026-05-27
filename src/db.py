"""SQLite database layer.

Schema is intentionally simple: 4 tables, no foreign keys, append-mostly.
The history IS the dataset — don't delete things, just mark status changes.
"""
import sqlite3
import json
from datetime import date, datetime
from contextlib import contextmanager
from typing import Optional
from config.settings import DB_PATH


SCHEMA = """
-- Every name that has ever passed the screen
CREATE TABLE IF NOT EXISTS watchlist (
    ticker              TEXT PRIMARY KEY,
    first_seen_date     DATE NOT NULL,
    first_seen_price    REAL NOT NULL,
    sector              TEXT,
    market_cap          REAL,
    has_options         BOOLEAN DEFAULT 0,
    screen_mode         TEXT,   -- 'recovering' or 'basing'
    status              TEXT DEFAULT 'active',  -- active, dropped, traded, closed, removed
    status_updated      DATE,
    analysis_json       TEXT,   -- Claude's structured output
    conviction_score    INTEGER,
    suggested_trade     TEXT,
    notes               TEXT
);

-- Daily price snapshot for everything on the watchlist
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker              TEXT NOT NULL,
    date                DATE NOT NULL,
    price               REAL NOT NULL,
    volume              INTEGER,
    pct_of_200w_ma      REAL,   -- snapshot of the screen metric
    pct_above_200d_ma   REAL,
    PRIMARY KEY (ticker, date)
);

-- Every screen run, whether or not the ticker passed
CREATE TABLE IF NOT EXISTS screen_history (
    ticker              TEXT NOT NULL,
    date                DATE NOT NULL,
    passed              BOOLEAN NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- Trades you actually took (manual entry or via a separate CLI)
CREATE TABLE IF NOT EXISTS trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    entry_date          DATE NOT NULL,
    entry_price         REAL NOT NULL,
    exit_date           DATE,
    exit_price          REAL,
    instrument          TEXT,   -- 'spot', 'call', 'put', 'spread'
    strike              REAL,
    expiry              DATE,
    contracts           INTEGER,
    cost_basis          REAL,
    proceeds            REAL,
    notes               TEXT
);

-- Run log for retrospectives
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date            DATE NOT NULL,
    started_at          TIMESTAMP,
    completed_at        TIMESTAMP,
    tickers_screened    INTEGER,
    tickers_passed      INTEGER,
    new_tickers         INTEGER,
    dropped_tickers     INTEGER,
    claude_api_cost_est REAL,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_prices_ticker ON daily_prices(ticker);
CREATE INDEX IF NOT EXISTS idx_prices_date ON daily_prices(date);
CREATE INDEX IF NOT EXISTS idx_screen_date ON screen_history(date);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
"""


def init_db():
    """Create the database and schema if they don't exist. Idempotent."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Add columns that were introduced after the initial schema
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(watchlist)").fetchall()}
        if "screen_mode" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN screen_mode TEXT")
    print(f"Initialized database at {DB_PATH}")


@contextmanager
def get_conn():
    """Context manager for DB connections. Always commits on success."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- watchlist operations ----------

def get_active_watchlist() -> list[dict]:
    """All tickers currently in 'active' or 'dropped' status (i.e. still tracked)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE status IN ('active', 'dropped') "
            "ORDER BY conviction_score DESC NULLS LAST, first_seen_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_tickers() -> set[str]:
    """Set of tickers currently in 'active' status (passing the screen now)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE status = 'active'"
        ).fetchall()
    return {r["ticker"] for r in rows}


def add_to_watchlist(ticker: str, price: float, sector: str = None,
                     market_cap: float = None, has_options: bool = False,
                     screen_mode: str = None, analysis: dict = None):
    """Add a new ticker. Idempotent — if ticker exists, just updates status to active."""
    today = date.today().isoformat()
    analysis_json = json.dumps(analysis) if analysis else None
    conviction = analysis.get("conviction_score") if analysis else None
    suggested_trade = analysis.get("suggested_trade") if analysis else None

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT ticker FROM watchlist WHERE ticker = ?", (ticker,)
        ).fetchone()

        if existing:
            # Reactivate if it dropped off then came back, refresh mode either way
            conn.execute(
                "UPDATE watchlist SET status = 'active', status_updated = ?, "
                "screen_mode = COALESCE(?, screen_mode) "
                "WHERE ticker = ? AND status IN ('active', 'dropped')",
                (today, screen_mode, ticker)
            )
        else:
            conn.execute(
                "INSERT INTO watchlist (ticker, first_seen_date, first_seen_price, "
                "sector, market_cap, has_options, screen_mode, status, status_updated, "
                "analysis_json, conviction_score, suggested_trade) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
                (ticker, today, price, sector, market_cap, has_options, screen_mode,
                 today, analysis_json, conviction, suggested_trade)
            )


def mark_dropped(ticker: str):
    """Mark a ticker as no longer passing the screen. Keep tracking it."""
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET status = 'dropped', status_updated = ? "
            "WHERE ticker = ? AND status = 'active'",
            (today, ticker)
        )


def mark_traded(ticker: str, notes: str = None):
    """Mark a ticker as one you've taken a position in."""
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET status = 'traded', status_updated = ?, notes = ? "
            "WHERE ticker = ?",
            (today, notes, ticker)
        )


# ---------- price tracking ----------

def record_daily_price(ticker: str, price: float, volume: int = None,
                       pct_of_200w_ma: float = None, pct_above_200d_ma: float = None):
    """Insert today's price for a ticker. Idempotent via UPSERT."""
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_prices "
            "(ticker, date, price, volume, pct_of_200w_ma, pct_above_200d_ma) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, today, price, volume, pct_of_200w_ma, pct_above_200d_ma)
        )


def get_price_history(ticker: str, days: int = 90) -> list[dict]:
    """Get the last N days of price data for a ticker."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_prices WHERE ticker = ? "
            "ORDER BY date DESC LIMIT ?",
            (ticker, days)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- screen history ----------

def record_screen_result(ticker: str, passed: bool):
    """Log whether a ticker passed today's screen."""
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO screen_history (ticker, date, passed) "
            "VALUES (?, ?, ?)",
            (ticker, today, passed)
        )


# ---------- run log ----------

def log_run(stats: dict):
    """Log a pipeline run for retrospectives."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_date, started_at, completed_at, tickers_screened, "
            "tickers_passed, new_tickers, dropped_tickers, claude_api_cost_est, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date.today().isoformat(),
             stats.get("started_at"), stats.get("completed_at"),
             stats.get("tickers_screened"), stats.get("tickers_passed"),
             stats.get("new_tickers"), stats.get("dropped_tickers"),
             stats.get("claude_api_cost_est"), stats.get("notes"))
        )
