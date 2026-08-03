"""Daily OHLCV collection from Naver's siseJson endpoint.

One request returns a stock's whole history for the requested window, so a
full-universe pull is ~2,500 requests rather than one per stock-day. Trading
value (거래대금) is not published by this endpoint, so it is reconstructed as
volume x average candle price; validated against KRX's real figures at 0.70%
median error, which is well inside what a liquidity filter needs.
"""
from __future__ import annotations

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from . import config

SISE_URL = (
    "https://api.finance.naver.com/siseJson.naver"
    "?symbol={code}&requestType=1&startTime={start}&endTime={end}&timeframe=day"
)

COLUMNS = ["date", "open", "high", "low", "close", "volume"]

# Circuit-breaker thresholds: once this many codes have been attempted, a
# failure rate above the limit means the source is refusing us rather than a
# few codes being individually broken.
BREAKER_MIN_SAMPLE = 200
BREAKER_FAILURE_RATE = 0.35

# ", ]" left behind when the trailing field of an old row is empty.
EMPTY_TRAILING = re.compile(r",\s*\]")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT})
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=config.MAX_WORKERS * 2,
        pool_maxsize=config.MAX_WORKERS * 2,
    )
    s.mount("https://", adapter)
    return s


def _parse(text: str) -> pd.DataFrame | None:
    """Parse Naver's JS-array response into a DataFrame."""
    text = text.strip()
    if not text or "[" not in text:
        return None
    # Rows older than the foreign-ownership series carry an empty trailing
    # field -- ["19900103", 44000, 45000, 43200, 44800, 26240, ] -- which is not
    # valid JSON. Dropping the dangling comma is what makes pre-2000 history
    # parseable at all; without it those stocks silently returned nothing.
    text = EMPTY_TRAILING.sub("]", text.replace("'", '"'))
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not rows or len(rows) < 2:
        return None

    body = [r for r in rows[1:] if isinstance(r, list) and len(r) >= 6]
    if not body:
        return None

    df = pd.DataFrame([r[:6] for r in body], columns=COLUMNS)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    # Naver pads non-trading days with open=high=low=0 but carries the previous
    # close, so testing close alone lets those rows through as candles spanning
    # zero. That wrecked the price scale (series minimum 0) and, because the low
    # was no longer positive, silently disabled the log axis. Every price must
    # be positive for the row to be a real session.
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    if df.empty:
        return None

    df = _drop_unadjusted_prefix(df)
    if df.empty:
        return None

    df["volume"] = df["volume"].fillna(0)
    # Estimated turnover. (O+H+L+C)/4 approximates the session VWAP far better
    # than the close alone (0.70% vs 1.71% median error against KRX actuals).
    df["amount"] = df["volume"] * (
        df["open"] + df["high"] + df["low"] + df["close"]
    ) / 4.0

    return df.sort_values("date").reset_index(drop=True)


def _drop_unadjusted_prefix(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the tail of the series that shares one price basis.

    Naver's back-adjustment does not reach the whole archive. 삼성전자 closes at
    43,500 on 1990-02-28 and 423 the next session -- a raw 100:1 step with no
    adjustment -- and about one in six stocks with pre-2000 data has a similar
    cliff. Splits from 2018 and 2021 *are* adjusted correctly, so the problem is
    confined to old history.

    Korean price limits cap a session at ±30% today and were tighter before
    2015, so a close-to-close step outside -32%/+35% cannot be a price move; it
    is an unadjusted corporate action. The band sits just outside the limit so a
    genuine 하한가 (0.70) or 상한가 (1.30) is never mistaken for one. Everything
    before the most recent such step is on a different price basis and is
    discarded.
    """
    if len(df) < 2:
        return df
    ratio = df["close"].to_numpy()[1:] / df["close"].to_numpy()[:-1]
    breaks = np.nonzero((ratio <= 0.68) | (ratio >= 1.35))[0]
    if breaks.size == 0:
        return df
    return df.iloc[breaks[-1] + 1:].reset_index(drop=True)


def fetch_one(code: str, start: str, end: str, session: requests.Session) -> pd.DataFrame | None:
    for attempt in range(config.RETRIES):
        try:
            r = session.get(
                SISE_URL.format(code=code, start=start, end=end),
                timeout=config.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                df = _parse(r.text)
                if df is not None:
                    return df
            elif r.status_code in (429, 503):
                # Explicit throttling: wait longer than for a generic error.
                time.sleep(2.0 * (attempt + 1) + random.random())
                continue
        except requests.RequestException:
            pass
        time.sleep(0.4 * (attempt + 1) + random.random() * 0.3)
    return None


def fetch_all(codes: list[str], end_date: datetime | None = None) -> dict[str, pd.DataFrame]:
    """Fetch daily candles for every code. Returns {code: DataFrame}."""
    end_date = end_date or datetime.now()
    end = end_date.strftime("%Y%m%d")
    start = config.HISTORY_START

    out: dict[str, pd.DataFrame] = {}
    failures: list[str] = []
    done = 0
    t0 = time.time()
    tripped = False

    session = _session()

    def work(code: str):
        if tripped:  # stop issuing requests once the breaker has opened
            return code, None
        return code, fetch_one(code, start, end, session)

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
        for code, df in ex.map(work, codes):
            done += 1
            if df is None or len(df) < 2:
                failures.append(code)
            else:
                out[code] = df

            # Circuit breaker. If the source starts refusing us, retrying every
            # remaining code wastes the timeout budget for hours and still ends
            # in an unusable dataset -- better to stop and report immediately.
            if not tripped and done >= BREAKER_MIN_SAMPLE:
                if len(failures) / done > BREAKER_FAILURE_RATE:
                    tripped = True
                    print(
                        f"  ABORT: {len(failures)}/{done} requests failing "
                        f"(>{BREAKER_FAILURE_RATE:.0%}); the source is likely "
                        f"throttling us. Stopping early.",
                        flush=True,
                    )

            if done % 250 == 0:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(codes) - done) / rate if rate else 0
                print(f"  prices {done}/{len(codes)}  {el:.0f}s  ok={len(out)}  "
                      f"eta={eta:.0f}s", flush=True)

    print(f"  prices done: {len(out)} ok, {len(failures)} failed, {time.time() - t0:.0f}s",
          flush=True)
    if failures:
        print(f"  failed codes (first 20): {failures[:20]}", flush=True)
    return out


def fetch_indices(end_date: datetime | None = None) -> dict[str, pd.DataFrame]:
    """KOSPI / KOSDAQ index history, used for relative-strength scoring."""
    import FinanceDataReader as fdr

    end_date = end_date or datetime.now()
    start = (end_date - timedelta(days=500)).strftime("%Y-%m-%d")
    out = {}
    for key, sym in (("KOSPI", "KS11"), ("KOSDAQ", "KQ11")):
        try:
            d = fdr.DataReader(sym, start)
            d = d.reset_index().rename(columns={"Date": "date", "Close": "close"})
            out[key] = d[["date", "close"]]
        except Exception as e:  # index is a nice-to-have, not a hard dependency
            print(f"  WARN: index {key} unavailable ({e})", flush=True)
    return out


if __name__ == "__main__":
    s = _session()
    df = fetch_one("005930", "20250801", "20260731", s)
    print(df.tail(5).to_string())
    print("\nrows:", len(df))
