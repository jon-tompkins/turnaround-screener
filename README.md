# Turnaround Pipeline

Daily-running screener + watchlist + Claude analyst for finding turnaround stock
candidates. Built around the screen we developed: price < 50% of 200-week MA,
price within 10% above 200-day MA (recovering from deep drawdown).

## Philosophy

This isn't just "run screener, get list." It's a **persistent research system**:

1. **Screen daily** for names matching the criteria
2. **Maintain a watchlist** of every name that's ever passed
3. **Only deep-research new names** (saves API costs, builds knowledge over time)
4. **Track price + screen status** for everything on the watchlist
5. **Retrospect periodically** — which conviction scores correlated with returns?

The differential pattern is the key: a name passes the screen once → gets full
Claude analysis once → then stays on the watchlist being monitored cheaply until
either you trade it, it drops off the screen, or you manually remove it.

## Architecture

```
┌──────────────────┐
│ Daily cron 6am   │
└────────┬─────────┘
         ▼
┌────────────────────────────────┐
│ screener.py                    │
│ • Loads ticker universe        │
│ • Batches yfinance downloads   │
│ • Computes 200d + 200w MAs     │
│ • Applies screen + filters     │
└────────┬───────────────────────┘
         ▼
┌────────────────────────────────┐
│ tracker.py                     │
│ • Diff vs current watchlist    │
│ • truly_new = new this run     │
│ • dropped = no longer passing  │
│ • Update prices for ALL active │
└────────┬───────────────────────┘
         ▼
┌────────────────────────────────┐  ← only for NEW names
│ enrichment.py + analyst.py     │     (keeps cost low)
│ • Pull fundamentals, news,     │
│   insider, options, filings    │
│ • Run Claude analysis          │
└────────┬───────────────────────┘
         ▼
┌────────────────────────────────┐
│ reporter.py                    │
│ • Console summary              │
│ • Optional Slack/email push    │
│ • Generates daily.md           │
└────────────────────────────────┘
```

State lives in `data/pipeline.db` (SQLite). Every run is idempotent — re-running
won't double-analyze, double-charge, or corrupt history.

## Setup

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Copy and fill in env
cp .env.example .env
# Add ANTHROPIC_API_KEY (required) and optional FMP_API_KEY, SLACK_WEBHOOK_URL

# 3. Seed the ticker universe (one-time)
python scripts/seed_universe.py
# Pulls S&P 1500 by default. To use Russell 3000:
#   Download IWV holdings CSV from iShares, drop to config/universe.csv

# 4. Initialize the database
python -c "from src.db import init_db; init_db()"

# 5. Do a dry run (screener only, no Claude calls)
python scripts/run_daily.py --dry-run

# 6. If output looks right, do a real run
python scripts/run_daily.py
```

## Daily run cost

For a ~1500 ticker universe with the screen criteria we set up:

| Component | Typical Cost |
|---|---|
| Screener (yfinance) | $0 |
| Price tracking for watchlist | $0 |
| Enrichment for new names (FMP optional) | $0.03/ticker if using FMP |
| Claude analysis for new names | $0.50-2.00 per new ticker (Sonnet 4.6) |
| Avg new names per day | 0-3 |
| **Avg cost per run** | **$0-6** |
| **Avg monthly cost** | **~$30-60** |

Most days will be $0 (no new names). Busy days after market moves cost more.

## Watchlist lifecycle

A ticker can be in these states:
- **active** — currently passing the screen
- **dropped** — was passing, no longer passes (kept for monitoring)
- **traded** — you took a position (set manually)
- **closed** — position closed (set manually, with outcome notes)
- **removed** — you manually killed it

Tickers never get deleted automatically. The history is the dataset.

## Retrospectives

Run `python scripts/retrospective.py --since 30d` for a Claude-generated review of:
- Which conviction scores correlated with actual returns
- Which sectors panned out
- Average days from "added to watchlist" to "best entry"
- What signals you missed

This is where the system gets smarter over time — feed retrospectives back into
the analyst prompt as context for future runs.

## Extending

The architecture isolates concerns so each piece can evolve independently:

- **Add filters** → edit `src/screener.py`, the criteria are explicit at the top
- **Better enrichment** → swap stubs in `src/enrichment.py` for real APIs
- **Different output** → add to `src/reporter.py`
- **TradingView integration** → write a webhook receiver that calls
  `tracker.add_from_pine_alert()` instead of running the screener locally
- **Auto-execution** (advanced) → add `src/executor.py` that watches the
  watchlist and fires broker orders on rules. **Don't build this until you've
  tracked 6+ months of manual results.**

## What's NOT in here (intentionally)

- Trade execution (do this manually until the research arm is proven)
- Position sizing logic (depends on your portfolio context, do manually)
- Tax tracking (use your broker's reports)
- Backtesting framework (different problem, build separately if needed)
