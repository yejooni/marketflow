"""Calibration backtest for the breakout-probability model.

Run:  python -m pipeline.backtest

At each sampled (stock, day t) it computes the model's probability of clearing
the 1-month high on day t+1 using only data through t, then checks what actually
happened. A calibrated model puts ~15% of its 10-20% predictions into breakouts.

Reported numbers live in docs/model-validation.md; rerun this after any change
to the model and update that file.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import analyze, config, prices, universe

SAMPLE_STOCKS = 250
DAYS_PER_STOCK = 40
MIN_BARS = 300
WARMUP = 260  # bars of history the model needs before its first prediction
BUCKETS = (0, .02, .05, .10, .20, .35, .55, 1.01)


def auc(p: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUC with tie handling."""
    order = np.argsort(p)
    y = np.asarray(y)[order]
    p = np.asarray(p)[order]
    n1 = y.sum()
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = np.empty(len(y), float)
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and p[j + 1] == p[i]:
            j += 1
        ranks[i:j + 1] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def calibration_table(p: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    d = pd.DataFrame({"p": p, "y": y})
    d["bucket"] = pd.cut(d["p"], BUCKETS, right=False)
    t = d.groupby("bucket", observed=True).agg(
        n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean")
    )
    t["predicted"] *= 100
    t["actual"] *= 100
    t["err_pp"] = t["actual"] - t["predicted"]
    return t.round(2)


def expected_calibration_error(table: pd.DataFrame) -> float:
    w = table["n"] / table["n"].sum()
    return float((w * table["err_pp"].abs()).sum())


def run(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    codes = universe.load_universe()["code"].sample(
        SAMPLE_STOCKS, random_state=seed
    ).tolist()

    session = prices._session()

    def get(code):
        return code, prices.fetch_one(code, "20240101", "20260731", session)

    data = {}
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
        for code, df in ex.map(get, codes):
            if df is not None and len(df) > MIN_BARS:
                data[code] = analyze.prepare(df)
    print(f"stocks with usable history: {len(data)}")

    win = config.PERIODS["1M"]
    rows = []
    for code, df in data.items():
        lo, hi = WARMUP, len(df) - 2
        if hi <= lo:
            continue
        days = rng.choice(range(lo, hi + 1), size=min(DAYS_PER_STOCK, hi - lo + 1),
                          replace=False)
        for t in days:
            hist = df.iloc[: t + 1]
            close = float(hist["close"].iloc[-1])
            sigma = float(hist["vol20"].iloc[-1])
            if not np.isfinite(sigma) or sigma <= 0 or close <= 0:
                continue
            period_high = float(hist["high"].tail(win).max())
            p, _ = analyze.breakout_probability(hist, period_high / close - 1.0, sigma)
            if not np.isfinite(p):
                continue
            rows.append({"p": p, "hit": float(df["high"].iloc[t + 1] >= period_high)})

    r = pd.DataFrame(rows)
    table = calibration_table(r["p"].to_numpy(), r["hit"].to_numpy())

    print(f"\nevaluations: {len(r):,}")
    print(f"mean predicted {r['p'].mean() * 100:.2f}%  vs  observed {r['hit'].mean() * 100:.2f}%")
    print("\n--- calibration ---")
    print(table.to_string())
    print(f"\nexpected calibration error: {expected_calibration_error(table):.2f} pp")
    print(f"AUC: {auc(r['p'].to_numpy(), r['hit'].to_numpy()):.4f}")
    return r


if __name__ == "__main__":
    run()
