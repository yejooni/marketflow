"""Real daily 거래대금 from KRX's official OpenAPI.

Everything else in this project reconstructs turnover as
`volume x (O+H+L+C)/4` because no free source publishes it per day. KRX does,
through openapi.krx.co.kr, behind an API key.

Why this API and not pykrx: pykrx authenticates by POSTing a member ID and
password to data.krx.co.kr's login form and riding the JSESSIONID. That means
handling a real account password and depending on a login page that can change
at any time. The OpenAPI needs only an issued key, is documented, and is the
sanctioned route. Without a key nothing here runs and the pipeline keeps using
the estimate, so this module is inert until `KRX_AUTH_KEY` is set.

Setup
-----
1. Register at https://openapi.krx.co.kr and apply for an 인증키 (API 인증키 신청).
2. Add it to the repo as a secret named `KRX_AUTH_KEY`
   (Settings -> Secrets and variables -> Actions -> New repository secret).
   Never paste the key into source or chat.
3. Verify:  KRX_AUTH_KEY=... python -m pipeline.krx --check
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config

BASE = "https://data-dbg.krx.co.kr/svc/apis/sto"
ENDPOINTS = {"KOSPI": "stk_bydd_trd", "KOSDAQ": "ksq_bydd_trd"}

ENV_KEY = "KRX_AUTH_KEY"

# Per the published 개발 명세서 for stk_bydd_trd the columns are BAS_DD, ISU_CD,
# ISU_NM, MKT_NM, SECT_TP_NM, TDD_CLSPRC, CMPPREVDD_PRC, FLUC_RT, TDD_OPNPRC,
# TDD_HGPRC, TDD_LWPRC, ACC_TRDVOL, ACC_TRDVAL, MKTCAP, LIST_SHRS. Alternatives
# are still accepted so a rename degrades to the estimate instead of crashing.
CODE_FIELDS = ("ISU_SRT_CD", "ISU_CD", "SRT_CD")
VALUE_FIELDS = ("ACC_TRDVAL", "TRDVAL", "ACC_TRD_VAL")

# This API only publishes from 2010-01-04, so older sessions simply return
# nothing and keep their estimate.
EARLIEST = "20100104"

MAX_WORKERS = 4
TIMEOUT = 20
RETRIES = 3


def enabled() -> bool:
    return bool(os.getenv(ENV_KEY))


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "AUTH_KEY": os.getenv(ENV_KEY, ""),
        "User-Agent": config.USER_AGENT,
        "Accept": "application/json",
    })
    return s


def _norm_code(code: str) -> str:
    """KRX sometimes identifies an issue by ISIN; our codes are the short form.

    KR7005930003 -> 005930. Anything already six characters passes through.
    """
    code = str(code).strip()
    if len(code) == 12 and code[:2].isalpha():
        return code[3:9]
    return code


def _pick(row: dict, names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in row and row[n] not in ("", None):
            return row[n]
    return None


# Populated during a run and copied into meta.json. Statuses and field names
# only -- never anything derived from the key itself. Without CI log access this
# is the only way to see why a run fell back to estimates.
DIAG: dict = {}


def _note(key, value=None):
    if value is None:
        DIAG[key] = DIAG.get(key, 0) + 1
    else:
        DIAG.setdefault(key, value)


def _fetch_day(session: requests.Session, market: str, day: str) -> list[dict]:
    url = f"{BASE}/{ENDPOINTS[market]}"
    for attempt in range(RETRIES):
        try:
            r = session.get(url, params={"basDd": day}, timeout=TIMEOUT)
            _note(f"http_{r.status_code}")
            if r.status_code == 200:
                body = r.json()
                _note("top_keys", sorted(body)[:6])
                for key in ("OutBlock_1", "output", "OutBlock1", "data"):
                    if isinstance(body.get(key), list):
                        rows = body[key]
                        if rows:
                            _note("row_fields", sorted(rows[0])[:24])
                            _note("sample_code", str(_pick(rows[0], CODE_FIELDS)))
                            _note("sample_value", str(_pick(rows[0], VALUE_FIELDS)))
                        return rows
                _note("no_known_block")
                return []
            if r.status_code in (401, 403):
                raise PermissionError(
                    f"KRX rejected the key ({r.status_code}). Check {ENV_KEY}."
                )
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
        except PermissionError:
            raise
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.5 * (attempt + 1))
    return []


def fetch_amounts(days: list[str]) -> dict[str, dict[str, float]]:
    """Return {YYYYMMDD: {code: 거래대금}} for the requested sessions.

    Non-trading days simply come back empty. Any day we cannot retrieve is
    omitted, and the caller keeps its estimate for that day.
    """
    DIAG.clear()
    DIAG["enabled"] = enabled()
    DIAG["sessions_requested"] = len(days)
    if not enabled():
        return {}

    session = _session()
    days = [d for d in days if d >= EARLIEST]
    jobs = [(m, d) for d in days for m in ENDPOINTS]
    out: dict[str, dict[str, float]] = {}
    t0 = time.time()

    def work(job):
        market, day = job
        return day, _fetch_day(session, market, day)

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for day, rows in ex.map(work, jobs):
                if not rows:
                    continue
                bucket = out.setdefault(day, {})
                for row in rows:
                    code = _pick(row, CODE_FIELDS)
                    val = _pick(row, VALUE_FIELDS)
                    if not code or val is None:
                        continue
                    try:
                        bucket[_norm_code(code)] = float(str(val).replace(",", ""))
                    except ValueError:
                        continue
    except PermissionError as e:
        _note("rejected", str(e))
        print(f"  WARN: {e} Falling back to estimated 거래대금.", flush=True)
        return {}

    filled = sum(len(v) for v in out.values())
    DIAG["sessions_ok"] = len(out)
    DIAG["values"] = filled
    print(f"  KRX 거래대금: {len(out)}/{len(days)} sessions, {filled:,} values, "
          f"{time.time() - t0:.0f}s", flush=True)
    return out


def apply_amounts(frames: dict, amounts: dict[str, dict[str, float]]) -> tuple[int, int]:
    """Overwrite estimated turnover with the real figure where we have it.

    Returns (replaced, total) candle counts so the run can report coverage.
    """
    if not amounts:
        return 0, 0
    replaced = total = 0
    for code, df in frames.items():
        if df is None or df.empty:
            continue
        keys = df["date"].dt.strftime("%Y%m%d")
        real = [amounts.get(k, {}).get(code) for k in keys]
        total += len(df)
        got = [i for i, v in enumerate(real) if v is not None]
        if not got:
            continue
        col = df["amount"].to_numpy(dtype=float).copy()
        for i in got:
            col[i] = real[i]
        df["amount"] = col
        replaced += len(got)
    return replaced, total


def _check() -> int:
    """Smoke test: prove the key works and show what the API actually returns."""
    if not enabled():
        print(f"{ENV_KEY} is not set. Export it and re-run.")
        return 1
    session = _session()
    for market in ENDPOINTS:
        rows = _fetch_day(session, market, sys.argv[2] if len(sys.argv) > 2 else "20260731")
        print(f"\n=== {market} ({ENDPOINTS[market]}) -> {len(rows)} rows ===")
        if rows:
            print("fields:", sorted(rows[0]))
            sample = rows[0]
            print("code  :", _pick(sample, CODE_FIELDS))
            print("value :", _pick(sample, VALUE_FIELDS))
            print("sample:", {k: sample[k] for k in list(sample)[:10]})
        else:
            print("no rows -- wrong date (non-trading day) or the key lacks access")
    return 0


if __name__ == "__main__":
    raise SystemExit(_check() if "--check" in sys.argv else _check())
