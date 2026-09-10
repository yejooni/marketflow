"""Theme membership from Naver's mobile stock API.

Naver groups stocks into ~266 curated themes. A stock usually belongs to
several, and they are kept *most specific first* -- membership count is a good
proxy for specificity, since "HBM(고대역폭메모리)" identifies a stock far better
than a 90-member catch-all like "지주사".

Measured distribution: median 2 per stock, p90 5, p99 10, max 31 (삼성전자).
Keeping only two covered just 62.5% of memberships; the current cap of eight
covers 97.8% while dropping the tail where a stock belongs to so many themes
that none of them characterises it. Tables still show the first two; the detail
page shows all of them.

Source note: the old scrape of `finance.naver.com/sise/theme.naver` broke in
2026-09 when Naver rebuilt that page as a client-rendered React app with no
theme links in the HTML. `m.stock.naver.com/api/stocks/theme` is the JSON the
new page calls -- one request lists a page of themes, one lists a theme's
members. No key, `euc-kr` no longer in the picture (it is UTF-8 JSON).
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config

LIST_URL = "https://m.stock.naver.com/api/stocks/theme?page={page}&pageSize={size}"
DETAIL_URL = "https://m.stock.naver.com/api/stocks/theme/{no}?page={page}&pageSize={size}"

# Naver rejects pageSize above ~100 with a 400.
PAGE_SIZE = 100

CODE_RE = re.compile(r"^[0-9A-Z]{6}$")

MAX_THEMES_PER_STOCK = 8


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT})
    return s


def _get_json(session: requests.Session, url: str):
    for attempt in range(config.RETRIES):
        try:
            r = session.get(url, timeout=config.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.4 * (attempt + 1))
    return None


def fetch_themes() -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Return (themes_by_id, code -> ordered list of theme ids)."""
    session = _session()
    t0 = time.time()

    # 1. Enumerate themes, one page of PAGE_SIZE at a time.
    first = _get_json(session, LIST_URL.format(page=1, size=PAGE_SIZE))
    if not first or not first.get("groups"):
        print("  WARN: theme directory unreachable; themes will be empty", flush=True)
        return {}, {}

    total = int(first.get("totalCount") or len(first["groups"]))
    last_page = (total + PAGE_SIZE - 1) // PAGE_SIZE

    found: dict[str, str] = {}

    def add_groups(groups):
        for g in groups:
            no = str(g["no"])
            found[no] = (g.get("name") or "").strip()

    add_groups(first["groups"])

    def list_page(p: int):
        j = _get_json(session, LIST_URL.format(page=p, size=PAGE_SIZE))
        return j.get("groups", []) if j else []

    if last_page > 1:
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
            for groups in ex.map(list_page, range(2, last_page + 1)):
                add_groups(groups)

    # 2. Pull each theme's member list, paginating when it overflows one page.
    def detail(no: str):
        codes: list[str] = []
        seen: set[str] = set()
        page = 1
        while True:
            j = _get_json(session, DETAIL_URL.format(no=no, page=page, size=PAGE_SIZE))
            if not j:
                break
            stocks = j.get("stocks") or []
            for s in stocks:
                code = str(s.get("itemCode") or "")
                if CODE_RE.match(code) and code not in seen:
                    seen.add(code)
                    codes.append(code)
            tc = int(j.get("totalCount") or 0)
            if page * PAGE_SIZE >= tc or not stocks:
                break
            page += 1
        return no, codes

    themes: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
        for no, members in ex.map(detail, list(found)):
            if members:
                themes[no] = {"id": no, "name": found[no], "members": members}

    # 3. Invert to stock -> themes, most specific (smallest) theme first.
    by_code: dict[str, list[str]] = {}
    for no, t in themes.items():
        for code in t["members"]:
            by_code.setdefault(code, []).append(no)

    for code, ids in by_code.items():
        ids.sort(key=lambda i: (len(themes[i]["members"]), themes[i]["name"]))
        by_code[code] = ids[:MAX_THEMES_PER_STOCK]

    print(
        f"  themes: {len(themes)} themes, {len(by_code)} stocks mapped, "
        f"{time.time() - t0:.0f}s",
        flush=True,
    )
    return themes, by_code


if __name__ == "__main__":
    themes, by_code = fetch_themes()
    print("\nsample themes:")
    for no in list(themes)[:5]:
        t = themes[no]
        print(f"  {t['name']}  ({len(t['members'])} members)")
    print("\nsample mappings:")
    for code in ["005930", "000660", "042700"]:
        ids = by_code.get(code, [])
        print(f"  {code}: {[themes[i]['name'] for i in ids]}")
    sizes = sorted(len(t["members"]) for t in themes.values())
    print(f"\nmembers per theme: min={sizes[0]} median={sizes[len(sizes)//2]} max={sizes[-1]}")
    print("stocks with >=1 theme:", len(by_code))
