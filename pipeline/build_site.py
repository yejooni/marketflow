"""Serialise analysis results into the static JSON the web app reads.

Layout under web/data/:
    meta.json          run metadata and market summary
    leaders.json       per-period ranked leader lists (main page)
    index.json         compact [code, name, market] list for search
    themes.json        theme aggregates with member codes
    stocks/<code>.json full candle history + per-period analysis

Turnover is not stored per candle: the browser recomputes it as
volume x (o+h+l+c)/4, the same formula the pipeline uses, which keeps the
payload small and the two sides guaranteed consistent.
"""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone, timedelta

import numpy as np

from . import config

KST = timezone(timedelta(hours=9))


def _clean(v):
    """JSON has no NaN/Infinity; numpy types are not serialisable either."""
    # bool must precede int: Python's bool subclasses int, so the int branch
    # would otherwise turn True/False into 1/0.
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if not math.isfinite(f) else round(f, 4)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_clean(payload), f, ensure_ascii=False, separators=(",", ":"))


def _days_until(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        end = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (end - datetime.now(KST).date()).days


def _weekly(df):
    """Aggregate the full daily series into weekly candles.

    A 36-year daily series is ~9,400 candles; at typical chart width that is a
    tenth of a pixel each, so it cannot be drawn as candles at all. Weekly is
    what an HTS shows for long ranges and costs about a fifth of the payload.
    """
    tmp = df.copy()
    tmp["last_day"] = tmp["date"]
    w = tmp.set_index("date").resample(config.WEEKLY_RULE).agg({
        "last_day": "last", "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    # Label each bar with the last session it actually contains, not the bin's
    # period end -- otherwise the current, partial week is stamped with a Friday
    # that has not happened yet.
    return {
        "d": [d.strftime("%Y%m%d") for d in w["last_day"]],
        "o": [int(x) for x in w["open"]],
        "h": [int(x) for x in w["high"]],
        "l": [int(x) for x in w["low"]],
        "c": [int(x) for x in w["close"]],
        "v": [int(x) for x in w["volume"]],
    }


def _period_summary(p: dict) -> dict:
    keys = (
        "high", "low", "high_date", "days_since_high", "gap_pct", "at_high",
        "in_reach", "ret_pct", "slope", "r2", "rs", "range_pos", "prob",
        "prob_n", "score", "candidate", "components",
    )
    return {k: p[k] for k in keys if k in p}


def build(results: list[dict], themes: dict, theme_map: dict, trade_date: str,
          amount_source: str = "estimate") -> None:
    if config.DATA_DIR.exists():
        shutil.rmtree(config.DATA_DIR)
    config.STOCK_DIR.mkdir(parents=True, exist_ok=True)

    by_code = {r["code"]: r for r in results}

    def theme_objs(code):
        return [
            {"id": t, "name": themes[t]["name"]}
            for t in theme_map.get(code, [])
            if t in themes
        ]

    # ---- per-stock detail -------------------------------------------------
    for r in results:
        df = r["_full"].tail(config.SERVE_TRADING_DAYS)
        payload = {
            "code": r["code"],
            "name": r["name"],
            "market": r["market"],
            "themes": theme_objs(r["code"]),
            "date": r["date"],
            "close": r["close"],
            "change_pct": r["change_pct"],
            "volume": r["volume"],
            "amount": r["amount"],
            "amount5": r["amount5"],
            "amount20": r["amount20"],
            "turnover": r.get("turnover"),
            "vol_surge": r["vol_surge"],
            "volatility": r["volatility"],
            "ma_aligned": r["ma_aligned"],
            "uptrend": r["uptrend"],
            "liquid": r["liquid"],
            "bars": r["bars"],
            "first_date": r["first_date"],
            "marcap": r.get("marcap"),
            "shares": r.get("shares"),
            "ohlcv": {
                "d": [d.strftime("%Y%m%d") for d in df["date"]],
                "o": [int(x) for x in df["open"]],
                "h": [int(x) for x in df["high"]],
                "l": [int(x) for x in df["low"]],
                "c": [int(x) for x in df["close"]],
                "v": [int(x) for x in df["volume"]],
            },
            "weekly": _weekly(r["_full"]),
            "periods": {k: _period_summary(v) for k, v in r["periods"].items()},
        }
        _write(config.STOCK_DIR / f"{r['code']}.json", payload)

    # ---- leader lists -----------------------------------------------------
    leaders = {}
    for label in config.PERIODS:
        rows = [r for r in results if label in r["periods"]]
        cands = [r for r in rows if r["periods"][label].get("candidate")]
        cands.sort(key=lambda r: r["periods"][label]["score"], reverse=True)

        leaders[label] = [
            {
                "code": r["code"],
                "name": r["name"],
                "market": r["market"],
                "themes": theme_objs(r["code"]),
                "close": r["close"],
                "change_pct": r["change_pct"],
                "marcap": r.get("marcap"),
                "vol_surge": r["vol_surge"],
                "amount": r["amount"],
                "amount20": r["amount20"],
                "turnover": r.get("turnover"),
                "ma_aligned": r["ma_aligned"],
                **_period_summary(r["periods"][label]),
            }
            for r in cands[: config.TOP_N_LEADERS]
        ]

    _write(config.DATA_DIR / "leaders.json", leaders)

    # ---- compact row summaries -------------------------------------------
    # One row per stock, enough to render any table without opening the
    # per-stock files. Without this a 148-member theme page would fire 148
    # requests; instead every table view costs a single ~650KB fetch.
    def r2(v):
        """Percentages carry no meaning past two decimals; shorten the payload."""
        return None if v is None or not math.isfinite(v) else round(float(v), 2)

    rows = []
    for r in sorted(results, key=lambda x: x["code"]):
        per = {}
        for label, p in r["periods"].items():
            per[label] = {
                "gap": r2(p["gap_pct"]), "prob": round(p["prob"], 4) if math.isfinite(p["prob"]) else None,
                "ret": r2(p["ret_pct"]), "rs": r2(p["rs"]), "score": r2(p.get("score")),
                "cand": p.get("candidate", False), "at_high": p["at_high"],
            }
        rows.append({
            "code": r["code"], "name": r["name"], "market": r["market"],
            "close": r["close"], "change_pct": r2(r["change_pct"]),
            "marcap": r.get("marcap"), "vol_surge": r2(r["vol_surge"]),
            "amount": round(r["amount"]) if math.isfinite(r["amount"]) else None,
            "amount20": round(r["amount20"]) if math.isfinite(r["amount20"]) else None,
            "turnover": round(r["turnover"], 6) if r.get("turnover") else None,
            "ma_aligned": r["ma_aligned"], "themes": theme_objs(r["code"]),
            "periods": per,
        })
    _write(config.DATA_DIR / "rows.json", rows)

    # ---- search index -----------------------------------------------------
    index = [
        [r["code"], r["name"], r["market"], [t["name"] for t in theme_objs(r["code"])]]
        for r in sorted(results, key=lambda x: x["code"])
    ]
    _write(config.DATA_DIR / "index.json", index)

    # ---- themes -----------------------------------------------------------
    theme_rows = []
    for tid, t in themes.items():
        members = [c for c in t["members"] if c in by_code]
        if not members:
            continue
        entry = {"id": tid, "name": t["name"], "count": len(members), "members": members}
        for label in config.PERIODS:
            rets = [
                by_code[c]["periods"][label]["ret_pct"]
                for c in members
                if label in by_code[c]["periods"]
            ]
            scores = [
                by_code[c]["periods"][label]["score"]
                for c in members
                if label in by_code[c]["periods"]
                and by_code[c]["periods"][label].get("candidate")
            ]
            entry[f"ret_{label}"] = float(np.median(rets)) if rets else None
            entry[f"cands_{label}"] = len(scores)
            entry[f"best_{label}"] = float(max(scores)) if scores else None
        theme_rows.append(entry)

    theme_rows.sort(key=lambda e: (e.get("ret_1M") is None, -(e.get("ret_1M") or 0)))
    _write(config.DATA_DIR / "themes.json", theme_rows)

    # ---- meta -------------------------------------------------------------
    counts = {
        label: sum(
            1 for r in results
            if label in r["periods"] and r["periods"][label].get("candidate")
        )
        for label in config.PERIODS
    }
    advancing = sum(1 for r in results if r["change_pct"] > 0)
    meta = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "trade_date": trade_date,
        "universe": len(results),
        "themes": len(theme_rows),
        "candidates": counts,
        "periods": list(config.PERIODS),
        "reach_pct": config.REACH_PCT,
        # "krx" once real turnover is available; the UI drops the 추정 label.
        "amount_source": amount_source,
        "krx_key_expires": config.KRX_KEY_EXPIRES,
        "krx_key_days_left": _days_until(config.KRX_KEY_EXPIRES),
        "advancing": advancing,
        "declining": len(results) - advancing,
    }
    _write(config.DATA_DIR / "meta.json", meta)

    print(f"  wrote {len(results)} stock files, {len(theme_rows)} themes", flush=True)
    print(f"  candidates per period: {counts}", flush=True)
