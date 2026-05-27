"""Configuration for the turnaround pipeline.

All tunable knobs live here. The screener criteria are explicit and easy to
adjust as you learn what works.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
DB_PATH = DATA_DIR / "pipeline.db"
UNIVERSE_PATH = CONFIG_DIR / "universe.csv"
PRICE_CACHE_PATH = DATA_DIR / "price_cache.parquet"

# Ensure dirs exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# API keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Models
ANALYST_MODEL = os.getenv("CLAUDE_ANALYST_MODEL", "claude-sonnet-4-6")
RETROSPECTIVE_MODEL = os.getenv("CLAUDE_RETROSPECTIVE_MODEL", "claude-opus-4-7")

# ============================================================================
# SCREENER CRITERIA — adjust these as you refine the system
# ============================================================================

# Core thesis: deep drawdown + recovering above near-term MA
PCT_OF_200W_MA_MAX = 0.50      # price must be < 50% of 200-week MA
PCT_ABOVE_200D_MA_MAX = 1.30   # price must be < 130% of 200-day MA (within 30% above)
ABOVE_200D_MA = True            # price must be ABOVE the 200-day MA (recovering mode)

# Optional second-leg: closeness to 100-day MA
USE_100D_MA_FILTER = True
PCT_OF_100D_MA_MIN = 0.80      # price within 20% below the 100d MA
PCT_OF_100D_MA_MAX = 1.40      # or 40% above (recoveries often extend here first)

# Basing mode — beat-down names still below 200d but close to crossing
ENABLE_BASING_MODE = True
BASING_MIN_PCT_ABOVE_200D = -30.0   # within 30% below 200d MA
BASING_MIN_30D_MOMENTUM = -2.0      # 30d return must be roughly flat-to-up
BASING_MAX_30D_MOMENTUM = 25.0      # avoid mid-breakout names
BASING_MIN_PCT_OF_100D_MA = 0.85    # above 85% of 100d MA (not still falling)

# Momentum confirmation (avoid catching falling knives like NXXT)
REQUIRE_POSITIVE_5D_CHANGE = True   # 5-day price change > 0
MAX_DAILY_DROP_PCT = -10.0          # exclude if down >10% today

# Sanity filters (avoid penny stocks, micro caps, illiquid names)
MIN_PRICE = 2.00                # avoid sub-$2 stocks (no usable options)
MIN_MARKET_CAP = 250_000_000    # $250M minimum for option liquidity
MIN_AVG_DOLLAR_VOLUME = 5_000_000  # $5M/day liquidity

# Data requirements
MIN_HISTORY_DAYS = 1000         # need ~4 years for 200w MA
LOOKBACK_YEARS = 5

# Universe / yfinance batching
BATCH_SIZE = 100                # tickers per yfinance call
BATCH_SLEEP_SECONDS = 1.5       # rate limit cushion

# ============================================================================
# PIPELINE BEHAVIOR
# ============================================================================

# How long to keep a "dropped" name on the watchlist (still tracked, not re-analyzed)
DROPPED_RETENTION_DAYS = 180

# Re-analyze a watchlist name if it's been on the list this many days AND new news
RE_ANALYZE_AFTER_DAYS = 30

# Daily report
TOP_N_CANDIDATES = 5            # show top N in daily summary
