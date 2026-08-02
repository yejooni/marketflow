"""Theme membership scraped from Naver Finance's theme directory.

Naver groups stocks into ~280 curated themes. A stock often belongs to several;
we keep at most two and prefer the *most specific* one -- membership count is a
good proxy for specificity, since "HBM(고대역폭메모리)" identifies a stock far
better than a 90-member catch-all like "지주사".
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config

LIST_URL = "https://finance.naver.com/sise/theme.naver?page={page}"
DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"

THEME_LINK_RE = re.compile(r'type=theme&no=(\d+)"[^>]*>([^<]+)<')
MEMBER_RE = re.compile(r'/item/main\.naver\?code=([0-9A-Z]{6})"[^>]*>([^<]+)<')
PAGE_RE = re.compile(r"theme\.naver\?&?page=(\d+)")

MAX_THEMES_PER_STOCK = 2


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT})
    return s


def _get(session: requests.Session, url: str) -> str | None:
    for attempt in range(config.RETRIES):
        try:
            r = session.get(url, timeout=config.REQUEST_TIMEOUT)
            if r.status_code == 200:
                r.encoding = "euc-kr"
                return r.text
        except requests.RequestException:
            pass
        time.sleep(0.4 * (attempt + 1))
    return None


def fetch_themes() -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Return (themes_by_id, code -> ordered list of theme ids)."""
    session = _session()
    t0 = time.time()

    # 1. Enumerate theme pages.
    first = _get(session, LIST_URL.format(page=1))
    if not first:
        print("  WARN: theme directory unreachable; themes will be empty", flush=True)
        return {}, {}

    pages = [int(p) for p in PAGE_RE.findall(first)]
    last_page = max(pages) if pages else 1

    found: dict[str, str] = {}
    for no, name in THEME_LINK_RE.findall(first):
        found[no] = name.strip()

    def list_page(p: int):
        html = _get(session, LIST_URL.format(page=p))
        return THEME_LINK_RE.findall(html) if html else []

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
        for res in ex.map(list_page, range(2, last_page + 1)):
            for no, name in res:
                found[no] = name.strip()

    # 2. Pull each theme's member list.
    def detail(no: str):
        html = _get(session, DETAIL_URL.format(no=no))
        if not html:
            return no, []
        seen, members = set(), []
        for code, nm in MEMBER_RE.findall(html):
            if code not in seen:
                seen.add(code)
                members.append(code)
        return no, members

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
