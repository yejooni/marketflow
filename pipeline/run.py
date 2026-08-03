"""Daily orchestrator: collect -> analyse -> emit static JSON.

    python -m pipeline.run             full universe
    python -m pipeline.run --limit 150 quick local run
"""
from __future__ import annotations

import argparse
import sys
import time

from . import analyze, build_site, config, krx, prices, themes as themes_mod, universe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="analyse only the first N codes (development)")
    ap.add_argument("--skip-themes", action="store_true")
    args = ap.parse_args()

    t0 = time.time()

    print("[1/5] universe", flush=True)
    uni = universe.load_universe()
    if args.limit:
        uni = uni.head(args.limit)
    print(f"  {len(uni)} common shares "
          f"({uni['market'].value_counts().to_dict()})", flush=True)

    print("[2/5] themes", flush=True)
    if args.skip_themes:
        theme_dict, theme_map = {}, {}
    else:
        theme_dict, theme_map = themes_mod.fetch_themes()

    print("[3/5] prices", flush=True)
    codes = uni["code"].tolist()
    frames = prices.fetch_all(codes)

    coverage = len(frames) / max(1, len(codes))
    print(f"  coverage: {coverage:.1%}", flush=True)
    if coverage < config.MIN_COVERAGE:
        print(
            f"ERROR: only {len(frames)}/{len(codes)} stocks downloaded "
            f"({coverage:.1%} < {config.MIN_COVERAGE:.0%}). Aborting so the "
            f"previously published data stays live.",
            file=sys.stderr,
        )
        return 1

    # Real 거래대금, if a KRX key is configured. Silently skipped otherwise, in
    # which case every amount stays the volume x (O+H+L+C)/4 estimate.
    amount_source = "estimate"
    if krx.enabled():
        sessions = sorted({
            d.strftime("%Y%m%d")
            for df in frames.values()
            for d in df["date"].tail(config.KRX_DAYS)
        })[-config.KRX_DAYS:]
        real = krx.fetch_amounts(sessions)
        replaced, total = krx.apply_amounts(frames, real)
        if replaced:
            amount_source = "krx"
            print(f"  real 거래대금 applied to {replaced:,} candles", flush=True)
    else:
        print("  KRX key not set -- 거래대금 stays estimated", flush=True)

    indices = prices.fetch_indices()
    idx_ret = analyze.index_returns(indices)
    print(f"  index returns: "
          f"{ {m: {k: round(v, 1) for k, v in d.items()} for m, d in idx_ret.items()} }",
          flush=True)

    print("[4/5] analyse", flush=True)
    meta = uni.set_index("code").to_dict("index")
    results = []
    for code, df in frames.items():
        info = meta.get(code, {})
        r = analyze.analyze_stock(code, df, idx_ret, info.get("market", "KOSPI"))
        if r is None:
            continue
        r["name"] = info.get("name", code)
        marcap = info.get("marcap")
        r["marcap"] = marcap
        r["shares"] = info.get("shares")
        # Turnover ratio: recent daily turnover as a share of market cap. Needs
        # the listing's marcap, which is only joined here, so it is attached
        # before scoring rather than inside analyze_stock.
        r["turnover"] = (
            r["amount5"] / marcap
            if marcap and marcap > 0 and r["amount5"] and r["amount5"] > 0
            else None
        )
        results.append(r)

    if not results:
        print("ERROR: no analysable stocks", file=sys.stderr)
        return 1

    analyze.score(results)
    print(f"  analysed {len(results)} stocks", flush=True)

    print("[5/5] build site data", flush=True)
    trade_date = max(r["date"] for r in results)
    build_site.build(results, theme_dict, theme_map, trade_date,
                     amount_source=amount_source)

    print(f"done in {time.time() - t0:.0f}s (trade date {trade_date})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
