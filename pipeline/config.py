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

MAX_WORKERS = 6  # gentler than the 8 that ran into throttling from CI runners
# Per attempt. Kept short deliberately: with thousands of codes a long timeout
# turns a throttled source into an hours-long hang instead of a fast failure.
REQUEST_TIMEOUT = 12
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

# Minimum candles for a stock to appear on the site at all. Deliberately tiny:
# a listing only days old still has a readable chart, and someone searching for
# it should find it rather than conclude the site does not know about it.
# Whether any *period* can be analysed is decided separately, per period, by
# that period's own window length.
MIN_HISTORY = 5

# Abort rather than publish if this share of the universe failed to download.
# A half-fetched day would quietly replace a good dataset with a worse one and
# drop real leaders off the board; failing keeps the previous deploy live.
MIN_COVERAGE = 0.90

# Per period, written to the main page payload. High enough to carry every
# candidate: the browser filters this list (거래대금, 시장, 확률), so trimming
# by score first would hide qualifying stocks that happen to rank lower. At a
# few hundred rows the payload is still trivial, so this is only a safety cap.
TOP_N_LEADERS = 500
