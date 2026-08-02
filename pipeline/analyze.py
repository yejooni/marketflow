"""Breakout analysis and the empirical breakout-probability model.

The pipeline runs before the open, so "today" means the next trading session
and every input is drawn from sessions that have already closed.

Probability model
-----------------
For a period high H and last close C, a breakout needs today's intraday high to
clear a return of r = H/C - 1. Rather than assuming a distribution, we ask how
often this stock has actually made a move that large:

    h_t = High_t / Close_{t-1} - 1          (daily upside extension)

Raw frequencies of h_t >= r would misprice a stock whose volatility regime has
shifted, so each extension is standardised by the volatility prevailing *before*
that session, and the requirement is standardised by today's volatility:

    z_t = h_t / sigma_{t-1}      z_req = r / sigma_now

The estimate is the share of past sessions whose z_t cleared z_req.

A variant that further conditioned on trend state (above/below MA20) with a
Beta prior was backtested against this one over 9,340 stock-days and proved
indistinguishable -- AUC 0.9027 vs 0.9038, ECE 0.73pp vs 0.67pp, the two
estimates correlating at 0.996 -- so the simpler form is used. Trend still
influences ranking, as its own component of the leader score.

Measured behaviour of the model in use (see docs/model-validation.md):
predicted 14.1% -> observed 13.4%, predicted 73.0% -> observed 76.5%,
expected calibration error 0.67pp, AUC 0.904.

This is a historical frequency, not a forecast: it says how often moves of this
size have happened from this kind of setup, which is the honest question a
static daily screen can answer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

MA_WINDOWS = (5, 20, 60, 120)

PROB_FLOOR, PROB_CEIL = 0.005, 0.98

# Leader-score weights. Components are cross-sectional percentiles (0-1).
SCORE_WEIGHTS = {
    "prob": 0.30,          # how reachable the breakout is
    "trend": 0.25,         # how cleanly the stock is trending up
    "rs": 0.20,            # outperformance vs its own index
    "volume": 0.15,        # money rotating in
    "proximity": 0.10,     # nearness to the high
}


# --------------------------------------------------------------------------
# indicators
# --------------------------------------------------------------------------

def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    for w in MA_WINDOWS:
        df[f"ma{w}"] = c.rolling(w, min_periods=max(2, w // 2)).mean()

    df["logret"] = np.log(c).diff()
    df["vol20"] = df["logret"].rolling(20, min_periods=10).std()
    # Upside extension of the session relative to the prior close.
    df["hi_ext"] = df["high"] / c.shift(1) - 1.0
    df["amount20"] = df["amount"].rolling(20, min_periods=5).mean()
    df["amount5"] = df["amount"].rolling(5, min_periods=2).mean()
    df["amount60"] = df["amount"].rolling(60, min_periods=10).mean()
    return df


def _trend(logclose: np.ndarray) -> tuple[float, float]:
    """OLS on log price. Returns (annualised slope in %, R^2)."""
    n = len(logclose)
    if n < 5:
        return 0.0, 0.0
    x = np.arange(n, dtype=float)
    x -= x.mean()
    y = logclose - logclose.mean()
    denom = float((x * x).sum())
    if denom <= 0:
        return 0.0, 0.0
    slope = float((x * y).sum() / denom)
    fitted = slope * x
    ss_res = float(((y - fitted) ** 2).sum())
    ss_tot = float((y * y).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope * 240.0 * 100.0, max(0.0, r2)


def breakout_probability(
    df: pd.DataFrame, required: float, sigma_now: float
) -> tuple[float, int]:
    """Return (probability, number of historical sessions in the sample)."""
    hi = df["hi_ext"]
    sig = df["vol20"].shift(1)  # only volatility knowable before the session

    mask = hi.notna() & sig.notna() & (sig > 0)
    n = int(mask.sum())
    if n < 30 or not np.isfinite(sigma_now) or sigma_now <= 0:
        return float("nan"), 0

    z = (hi[mask] / sig[mask]).to_numpy()
    z_req = required / sigma_now
    p = float((z >= z_req).mean())

    return float(np.clip(p, PROB_FLOOR, PROB_CEIL)), n


# --------------------------------------------------------------------------
# per-stock analysis
# --------------------------------------------------------------------------

def analyze_stock(
    code: str, df: pd.DataFrame, index_ret: dict[str, dict[str, float]], market: str
) -> dict | None:
    if df is None or len(df) < config.MIN_HISTORY:
        return None

    df = prepare(df)
    last = df.iloc[-1]
    close = float(last["close"])
    if close <= 0:
        return None

    sigma_now = float(last["vol20"]) if np.isfinite(last["vol20"]) else float("nan")
    uptrend_now = bool(np.isfinite(last["ma20"]) and close > last["ma20"])

    amount20 = float(last["amount20"]) if np.isfinite(last["amount20"]) else 0.0
    amount5 = float(last["amount5"]) if np.isfinite(last["amount5"]) else 0.0
    amount60 = float(last["amount60"]) if np.isfinite(last["amount60"]) else 0.0
    vol_surge = amount5 / amount60 if amount60 > 0 else float("nan")

    ma_stack = [last.get(f"ma{w}") for w in MA_WINDOWS]
    aligned = bool(
        all(np.isfinite(v) for v in ma_stack[1:])
        and close > ma_stack[1] > ma_stack[2] > ma_stack[3]
    )

    periods: dict[str, dict] = {}
    for label, win in config.PERIODS.items():
        # The window must actually be there. Gating on min(win, MIN_HISTORY)
        # used to let a 63-bar stock report its 63-day high as a "12개월
        # 신고가" -- and since a fresh listing near its all-time high then
        # showed a near-zero gap on every period at once, it climbed the
        # leader board on highs that did not exist.
        if len(df) < win:
            continue
        seg = df.tail(win)
        high = float(seg["high"].max())
        low = float(seg["low"].min())
        hi_idx = seg["high"].idxmax()
        high_date = seg.loc[hi_idx, "date"]
        days_since_high = int(len(seg) - seg.index.get_loc(hi_idx) - 1)

        required = high / close - 1.0
        gap_pct = required * 100.0

        slope, r2 = _trend(np.log(seg["close"].to_numpy()))
        period_ret = (close / float(seg["close"].iloc[0]) - 1.0) * 100.0
        idx_ret = index_ret.get(market, {}).get(label, float("nan"))
        rs = period_ret - idx_ret if np.isfinite(idx_ret) else float("nan")

        prob, prob_n = breakout_probability(df, required, sigma_now)

        # Position within the period's range: 1.0 means sitting at the high.
        rng = high - low
        pos = (close - low) / rng if rng > 0 else float("nan")

        periods[label] = {
            "high": high,
            "low": low,
            "high_date": high_date.strftime("%Y-%m-%d"),
            "days_since_high": days_since_high,
            "gap_pct": gap_pct,
            "at_high": bool(close >= high),
            "in_reach": bool(0 <= gap_pct <= config.REACH_PCT) or bool(close >= high),
            "ret_pct": period_ret,
            "slope": slope,
            "r2": r2,
            "trend_quality": slope * r2,
            "rs": rs,
            "range_pos": pos,
            "prob": prob,
            "prob_n": prob_n,
        }

    # A stock with no complete period is still kept: it gets a page, a chart
    # and search visibility, just no rankings. Dropping it outright is how
    # recent listings silently vanished from the site.
    return {
        "code": code,
        "market": market,
        "close": close,
        "change_pct": float(close / df["close"].iloc[-2] - 1.0) * 100.0 if len(df) > 1 else 0.0,
        "date": last["date"].strftime("%Y-%m-%d"),
        "volume": int(last["volume"]),
        "amount": float(last["amount"]),
        "amount20": amount20,
        "vol_surge": vol_surge,
        "volatility": sigma_now * 100.0 if np.isfinite(sigma_now) else float("nan"),
        "ma_aligned": aligned,
        "uptrend": uptrend_now,
        "liquid": bool(amount20 >= config.MIN_AVG_AMOUNT and close >= config.MIN_PRICE),
        "bars": int(len(df)),
        "periods": periods,
        "_df": df,
    }


def index_returns(indices: dict[str, pd.DataFrame]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for market, d in indices.items():
        c = d["close"].to_numpy(dtype=float)
        per = {}
        for label, win in config.PERIODS.items():
            if len(c) > win:
                per[label] = (c[-1] / c[-win] - 1.0) * 100.0
            elif len(c) > 1:
                per[label] = (c[-1] / c[0] - 1.0) * 100.0
        out[market] = per
    return out


# --------------------------------------------------------------------------
# cross-sectional scoring
# --------------------------------------------------------------------------

def _pct_rank(values: pd.Series) -> pd.Series:
    return values.rank(pct=True, na_option="keep")


def score(results: list[dict]) -> None:
    """Attach a 0-100 leader score per period, in place.

    Components are ranked cross-sectionally so that a score always answers
    "how does this stock compare with everything else trading today".
    """
    for label in config.PERIODS:
        rows = [r for r in results if label in r["periods"]]
        if not rows:
            continue

        frame = pd.DataFrame(
            {
                "prob": [r["periods"][label]["prob"] for r in rows],
                "trend": [r["periods"][label]["trend_quality"] for r in rows],
                "rs": [r["periods"][label]["rs"] for r in rows],
                "volume": [r["vol_surge"] for r in rows],
                "proximity": [-r["periods"][label]["gap_pct"] for r in rows],
            }
        )

        ranked = pd.DataFrame({c: _pct_rank(frame[c]) for c in frame})
        # A missing component should neither reward nor punish.
        ranked = ranked.fillna(0.5)

        total = sum(SCORE_WEIGHTS.values())
        composite = sum(ranked[c] * w for c, w in SCORE_WEIGHTS.items()) / total

        for r, s, comp in zip(rows, composite, ranked.to_dict("records")):
            p = r["periods"][label]
            p["score"] = float(s * 100.0)
            p["components"] = {k: float(v * 100.0) for k, v in comp.items()}
            p["candidate"] = bool(
                r["liquid"]
                and r["uptrend"]
                and p["in_reach"]
                and p["slope"] > 0
            )
