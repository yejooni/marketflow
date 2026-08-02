"""Shared configuration for the MarketFlow pipeline."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = WEB_DIR / "data"
STOCK_DIR = DATA_DIR / "stocks"

# --- Collection -------------------------------------------------------------

# We serve one year of candles, but analysis needs a little more history than
# it displays: the 12-month high must look back a full 240 trading days *and*
# MA120 has to be defined at the left edge of that window. 500 calendar days
# (~340 trading days) covers both with room for holidays.
FETCH_CALENDAR_DAYS = 500
SERVE_TRADING_DAYS = 245  # ~1 year of candles sent to the browser

MAX_WORKERS = 8  # Naver tolerates this comfortably; verified on the runner
REQUEST_TIMEOUT = 30
RETRIES = 3

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# --- Universe ---------------------------------------------------------------

MARKETS = ("KOSPI", "KOSDAQ")

# Liquidity floor. Names below this are not tradeable in size and produce
# meaningless breakout signals, so they are scored but flagged illiquid.
MIN_AVG_AMOUNT = 500_000_000  # 5억원, 20-day average turnover
MIN_PRICE = 1_000

# --- Analysis ---------------------------------------------------------------

# label -> trading-day lookback
PERIODS = {
    "1M": 20,
    "3M": 60,
    "6M": 120,
    "12M": 240,
}

# A breakout is "in reach today" if the high sits within this much upside.
REACH_PCT = 20.0

# Minimum candles before a stock is analysed at all (recent IPOs).
MIN_HISTORY = 60

# Abort rather than publish if this share of the universe failed to download.
# A half-fetched day would quietly replace a good dataset with a worse one and
# drop real leaders off the board; failing keeps the previous deploy live.
MIN_COVERAGE = 0.90

TOP_N_LEADERS = 60  # per period, written to the main page payload
