"""Shared configuration for the GodFlow pipeline."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = WEB_DIR / "data"
STOCK_DIR = DATA_DIR / "stocks"

# --- Collection -------------------------------------------------------------

# Naver returns a stock's entire range in one request, so pulling everything
# costs the same number of requests as pulling a year -- measured 3.9 min for
# the full universe vs 1.6 min for a year. There is nothing to cache or
# accumulate: a stateless full refetch also keeps splits and rights issues
# correct, which an append-only store would silently corrupt.
HISTORY_START = "19900101"

SERVE_TRADING_DAYS = 245  # ~1 year of daily candles sent to the browser

# Analysis deliberately ignores the deep history. The 12-month high needs 240
# sessions and MA120 needs warmup before that; 340 covers both. Widening this
# would silently change the sample the probability model was validated on.
ANALYSIS_BARS = 340

# Weekly candles carry the long view instead of daily ones. At 1000px a 36-year
# daily series is 0.1px per candle -- unrenderable -- which is why every HTS
# switches to 주봉 for long ranges. Weekly keeps the whole history at ~1/5 the
# payload.
WEEKLY_RULE = "W-FRI"

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

# Sessions of real 거래대금 to pull from KRX when a key is configured. Covers
# the served daily window, so both the rankings and the chart tooltip show real
# figures. Each session costs two calls (KOSPI + KOSDAQ).
KRX_DAYS = 250

# The KRX key expires a year after issue and the API gives no way to ask when.
# Recording it here lets the site show the remaining days and lets CI open an
# issue before it lapses -- otherwise the first sign would be turnover quietly
# reverting to estimates. Override with a KRX_KEY_EXPIRES repo variable on
# renewal so this needs no code change.
KRX_KEY_EXPIRES = os.getenv("KRX_KEY_EXPIRES", "2027-08-02")
KRX_KEY_WARN_DAYS = 30
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
