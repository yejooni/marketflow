# CLAUDE.md — GodFlow

Read this first. It carries the decisions and traps that are **not** recoverable
from the code, so a fresh session (or a different model) can continue safely.

- **Live:** https://yejooni.github.io/marketflow
- **Repo:** `yejooni/marketflow`, default branch **`master`** (not `main`)
- **Brand is `GodFlow`; the repo and URL stay `marketflow`.** Renaming the repo
  would break the published URL. Do not "fix" this inconsistency.
- Working dir: `C:\Workspaces-cc\marketflow`
- UI language is Korean. Write user-facing strings in Korean.

## Keeping this file current — do this without being asked

Claude Code loads this file automatically, so it is the only thing guaranteed to
survive a new session or a model switch. Nothing updates it on its own. **Update
it in the same commit as the change**, whenever you:

- change a threshold, weight, schedule or data source (and say *why*);
- hit a bug that the code alone would not warn the next person about — add it to
  *Traps already hit*, with the symptom, not just the fix;
- add or reject an approach after measuring — record the numbers so nobody
  re-litigates it;
- discover an environment quirk (a tool that is missing, a shell that misbehaves).

Keep it short and specific. Facts recoverable by reading the code do not belong
here; the reasoning behind them does. If something in here turns out to be wrong,
correct it rather than appending a contradiction.

## What it does

Every trading morning it collects ~2,530 KOSPI/KOSDAQ common shares, measures how
close each sits to its 1/3/6/12-month high, estimates the probability of clearing
that high today, ranks leader candidates, and publishes a static site.

## Environment

```
python   C:\anaconda3\envs\py64\python.exe      (3.10; CI uses 3.11)
gh CLI   NOT installed -- use the GitHub REST API via curl/Invoke-RestMethod
git      credentials already cached (push works unattended)
```
Unauthenticated GitHub API is **60 req/hr** — polling loops burn it fast. Prefer
checking the live site over polling the Actions API.

Shell: PowerShell is primary. **Heredocs do not work there** — use the Bash tool
for `git commit -F -`. `python` in Git Bash is a broken Windows stub; always use
the full conda path above.

## Commands

```bash
python -m pipeline.run                 # full run, ~6 min local
python -m pipeline.run --limit 300 --skip-themes   # fast dev loop
python -m pipeline.backtest            # revalidate the probability model
python -m pipeline.krx --check         # prove a KRX key works
cd web && python -m http.server 8765   # local preview (run the pipeline first)
```

`web/data/` is gitignored and starts empty on a fresh clone, so local preview
needs a run first. **A `--limit` run leaves a partial dataset behind** that looks
like a real one — if the site shows an implausibly small 분석 종목 count, that is
why. Delete `web/data` or do a full run.

`requirements.txt` lists `lxml` and `beautifulsoup4` even though nothing here
imports them: FinanceDataReader imports bs4 at module load and fails without it.
Verified by installing the file into a clean venv and removing them.
Browser-cache the CSS aggressively — **hard-reload (ctrl+shift+r)** when checking
style changes locally, or you will debug a stale stylesheet.

## Architecture

```
pipeline/
  config.py      periods, thresholds, worker counts  <- tune here first
  universe.py    KRX listing -> KOSPI/KOSDAQ common shares
  prices.py      Naver siseJson candles + circuit breaker
  themes.py      Naver theme scrape (~266 themes)
  analyze.py     indicators, breakout probability, leader score
  backtest.py    calibration harness for the probability model
  build_site.py  emits web/data/*.json
  run.py         orchestrator (attaches marcap + turnover, coverage guard)
web/             dependency-free static site (vanilla JS + canvas chart)
docs/model-validation.md   measured model numbers
```

Generated data lives in `web/data/` and is **gitignored on purpose** — see
Deployment.

## Data sources — and why

- **Candles: Naver `siseJson`.** One request returns a stock's entire date range,
  so a full pull is ~2,530 requests, not one per stock-day.
- **KRX's own API is unusable.** It now requires an account; `pykrx` and direct
  `data.krx.co.kr` calls return `LOGOUT`. Do not reintroduce them.
- **Listing: FinanceDataReader `StockListing("KRX")`.** ETFs/ETNs are already
  absent from it. Retried 4x — it is one request and a hard dependency.
- **Themes: Naver theme directory**, up to **8** per stock (`MAX_THEMES_PER_STOCK`),
  most *specific* first (fewest members = most identifying). Measured spread:
  median 2, p90 5, max 31 (삼성전자). A cap of 2 carried only 62.5% of
  memberships; 8 carries 97.8% and drops the tail where a stock belongs to so
  many themes that none of them describes it. Tables render the first two
  (`themeChips(themes, 2)`); the detail page renders all.
- **거래대금 is REAL where KRX covers it, estimated elsewhere.** `pipeline/krx.py`
  is live and supplies ~97.5% of the served year; the rest (pre-2010, or days
  the API skipped) falls back to `volume x (O+H+L+C)/4`. Per-candle flags drive
  the labelling, so never assume a series is wholly one or the other.
  - The estimate was measured against 93,854 real candles: **median 0.50%**
    error, p90 1.75%, p99 4.87%, +0.15% bias. It is *better* than the 0.70%
    figure first published off a 58-sample check — if a doc still says 0.70%,
    it is stale.
  - **pykrx does not solve this.** `get_market_ohlcv_by_date` works without
    credentials but falls back to a source with no 거래대금 column (시가·고가·
    저가·종가·거래량·등락률 only), and the KRX-backed calls print
    `KRX 로그인 실패` and return nothing. It authenticates by POSTing a member
    ID and password to data.krx.co.kr's login form (`website/comm/auth.py`),
    which means handling an account password and depending on a login page.
  - **`pipeline/krx.py` is the route instead**: KRX's official OpenAPI
    (`data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd` + `ksq_bydd_trd`), keyed by
    an `AUTH_KEY` header — a key, not a password. It is **inert unless the
    `KRX_AUTH_KEY` secret exists**; without it every amount stays estimated and
    `meta.amount_source` is `"estimate"`, which is what makes the UI say 추정.
    One call per market per session, `config.KRX_DAYS` sessions.
    Verify a key with `python -m pipeline.krx --check [YYYYMMDD]`, which prints
    the actual field names — the parser accepts several spellings so a rename
    degrades to the estimate rather than crashing.
  - **An issued key is not enough.** KRX's own 이용방법 has four steps, and the
    key is only step 1. Step 3 is **API 이용신청 per service, with admin
    approval** (the button sits on each API's detail page). Until that is
    approved every call returns **401** and the run falls back — this happened,
    with 이용현황 listing zero applications while the key was perfectly valid.
    **If turnover is unexpectedly estimated, check entitlements before the key.**
    Working shape once approved: 500 calls all HTTP 200, 249/250 sessions,
    ~689k values, ~4 min added to the run.
  - Published spec: `ISU_CD`, `ACC_TRDVAL` (거래대금), plus `MKTCAP` and
    `LIST_SHRS`. Data starts **2010-01-04**; earlier sessions keep the estimate.
  - `meta.krx_diag` carries statuses and field names (never key material) so a
    fallback is diagnosable from the published site without CI log access.

### The daily job refetches ALL history — keep it that way
It pulls every session back to 1990 per stock, every run. **One request returns
any range**, so a full pull costs the same ~2,530 requests as a one-year pull —
measured 3.9 min vs 1.6 min. Incremental accumulation would therefore buy
nothing while adding a cache to corrupt, and a stateless refetch keeps splits
correct: Naver back-adjusts, so an append-only store would freeze pre-split
prices and quietly break the series at every 액면분할.

### Deep history is dirty — two filters keep it usable
Both live in `prices._parse` and matter more than they look:

1. **Non-trading days are padded with `open=high=low=0` and a carried close.**
   Testing `close > 0` alone let them through as candles spanning zero, which
   put the series minimum at 0 and — because `lo > 0` was then false — silently
   disabled the log axis. All four prices must be positive.
2. **Naver's back-adjustment does not reach the whole archive.**
   삼성전자 closes 43,500 then 423 the next session (raw 100:1, unadjusted);
   ~1 in 6 stocks with pre-2000 data has such a cliff, while the 2018 and 2021
   splits *are* adjusted. `_drop_unadjusted_prefix` keeps only the tail sharing
   one price basis, cutting at any close-to-close step outside -32%/+35% —
   impossible under Korean price limits (±30%), so such a step is always a
   corporate action, never a price. Verified: 0/298 sampled stocks retain an
   impossible move, down from 5/149.

## Probability model

`P = share of past sessions whose volatility-standardised intraday high
extension cleared what today needs.`

```
h_t = High_t/Close_{t-1} - 1        z_t = h_t / sigma_{t-1}
z_req = (H/C - 1) / sigma_now       P = mean(z_t >= z_req)
```

**Measured** (9,336 stock-days, `pipeline/backtest.py`): predicted 9.47% vs
observed 9.45%, **ECE 0.70pp, AUC 0.913**. Slightly conservative at the top end.

A trend-conditioned variant (MA20 state + Beta shrinkage) was **built, tested and
rejected**: AUC 0.9027 vs 0.9038, estimates correlated 0.996. Do not re-add it
without new evidence. Trend already enters the leader score separately.

It is a **historical frequency, not a forecast** — keep the UI honest about that.

## Leader score

Cross-sectional percentiles, weighted (`analyze.SCORE_WEIGHTS`):
prob .28 / trend .22 / rs .18 / volume .12 / turnover .12 / proximity .08.

`volume` = 5d vs 60d turnover (busier than its own norm). `turnover` = 5d
turnover ÷ market cap (big money relative to company size). They answer different
questions — a sleepy small cap clears `volume` on any mild day, which is why
`turnover` exists. `turnover` is attached in `run.py`, not `analyze.py`, because
market cap only joins there.

A stock is a **candidate** if: liquid, above MA20, positive slope, and the high is
within 20%.

## Traps already hit — do not regress these

1. **Share class is the LAST character.** Common = ends `0`. Preferred = ends
   5/7/9 or a letter (K/L/M). Codes may contain letters: `0126Z0` (삼성에피스홀딩스)
   is a normal common share in KRX's newer format. An all-digit regex wrongly
   dropped 26 real companies.
2. **A period requires its FULL window** (`len(df) >= win`). Gating on
   `min(win, MIN_HISTORY)` once made 50 stocks report a 63-day high as a
   "12개월 신고가", and fresh listings near all-time highs swept the leader board
   on highs that did not exist.
3. **`MIN_HISTORY = 5`, deliberately tiny.** It only controls site visibility.
   A 60-bar floor made recent listings vanish; a user searched 레몬헬스케어
   (365660) and found nothing. Short-history stocks get a page/chart/search but
   no periods and no ranking.
4. **`TOP_N_LEADERS` must exceed the candidate count.** The browser filters
   `leaders.json`, so trimming by score first hides qualifying stocks. Trimming to
   60 hid 12 of the 32 stocks passing the default 100억 filter.
5. **`bool` is a subclass of `int`** — check bool before int in `build_site._clean`
   or every `true` serialises as `1`.
6. **Bind table sort listeners once.** `makeSortable` is re-invoked on every
   filter change; re-binding stacks handlers so one click toggles repeatedly.
   State lives on the table element; `theme.js` clears it when rebuilding headers.
7. **Never fetch per-member on theme pages.** Use `web/data/rows.json` (one
   compact row per stock) — a 148-member theme was firing 148 requests.
8. **A table column sizes to its widest row, including conditional content.**
   One row's 신고가 badge widened 종목 by 49px for all 31 rows and pushed the last
   column off-screen. The badge was also redundant with the 신고가까지 cell. Names
   are now capped at 132px for the same reason. When adding a column, check the
   table with a row that has every optional element present.

## Deployment

`.github/workflows/daily.yml` — cron `13 12 * * 1-5` UTC = **21:00 KST Mon–Fri**,
after the close. UTC and KST land on the same calendar day at that hour, so the
site carries the **current** session's close and the breakout estimate refers to
the **next** trading day. Say 다음 거래일 in the UI, never 오늘 — that wording was
correct only under the old pre-open schedule.

- **Observed runs start ~23:30 KST, not 21:00.** GitHub defers scheduled
  workflows under load; measured delay has been 2–3 hours, every run still
  succeeding. Data is unaffected (the session closed hours earlier), so this is
  a presentation issue only — never state a precise update hour in the UI, point
  at `generated_at` instead. Moving the cron earlier would pull the landing time
  in, but nothing before ~10:00 UTC (19:00 KST) is safe: the 시간외단일가 session
  runs to 18:00 KST and its trades count toward the day's 거래량/거래대금.
- **Do not push twice inside ~8 minutes.** `cancel-in-progress: true` means the
  second push kills the first run, and a full run takes 6–7 minutes with KRX.
  This has already caused a "why isn't it deploying" moment — the first change
  was simply never built. Batch edits into one push, or wait for the run.
- After a deploy, a browser holding the previous page keeps it for up to 10
  minutes (`max-age=600`). That is the cache-busting working: old HTML pairs
  with old JS and stays consistent instead of breaking. Ctrl+Shift+R to check
  immediately.

- Output ships as a **Pages artifact, never committed** → repo stays ~0.12MB.
- Pages source must be **"GitHub Actions"** in repo settings. `configure-pages`
  with `enablement: true` does **not** work — the default `GITHUB_TOKEN` lacks
  Pages admin scope. This is a manual one-time setting.
- **`keepalive.yml` is load-bearing.** GitHub disables scheduled workflows after
  60 days of repo inactivity, and this project never commits. Without the monthly
  heartbeat the daily job dies silently. Do not delete it.
- The artifact is `_site/`, produced by `pipeline/stage_site.py`, **not `web/`
  directly.** Pages pins `Cache-Control: max-age=600` and cannot be configured,
  so a visitor could revalidate the HTML while still holding the previous JS and
  get a table whose rows do not match its headers. Staging stamps `?v=<build>`
  onto asset URLs *and* module import specifiers. Tracked sources stay clean.
- Collection **aborts below 90% coverage** (`MIN_COVERAGE`) so a partial day
  cannot replace good published data; the previous deploy stays live.
- **Circuit breaker** in `prices.fetch_all`: >35% failures after 200 attempts
  aborts. Naver throttles bulk scraping from runner IPs — a run once ground for
  30+ minutes before this existed.

## UI conventions

- **Korean market colours: 상승 = red, 하락 = blue.** This is deliberate and
  inverts the Western convention. Never "correct" it.
- Chart mimics 키움 HTS: filled red/blue candles, MA 5/20/60/120, volume pane,
  crosshair, right-hand price axis. Pure canvas, no library, so the conventions
  are exact.
- **The hover tooltip is a DOM node, not canvas** (`.chart-tip`), so text layout
  and theme colours come free. Its contents depend on the pane: the price pane
  reports O/H/L/C with each value's % against the previous close; the volume
  pane reports 상장주식수, 거래량, turnover of shares outstanding, and 거래대금.
  The volume figures need `shares`, passed in via chart options from `stock.js`.
  Keep `pointer-events: none` on it or it swallows the mousemove that moves it.
- MA palette is validated for colour-vision deficiency in both themes. Light uses
  Kiwoom defaults `#FF0000/#CC00CC/#009900/#0000FF`; dark is re-stepped to
  `#F04A4A/#D45BD4/#2FA050/#4A86E8` (pure blue fails the dark lightness band).
  Revalidate with the `dataviz` skill's `validate_palette.js` if changed.
- Probability shows `–`, never `0.0%`, when the sample is too small — 0% would
  read as "cannot break out".
- **Daily candles up to 1 year, weekly beyond.** A 36-year daily series is
  ~9,400 candles — a tenth of a pixel each — so it cannot be drawn; every HTS
  switches to 주봉 for the same reason. `build_site._weekly` labels each bar with
  the last session it contains, not the resample bin edge, or the current
  partial week gets stamped with a Friday that has not happened yet.
- **Log axis auto-engages** once the visible range spans ≥5x, and the user's
  manual toggle wins after that. Without it a stock that rose 40x renders as a
  flat line then a spike.

## Verify after changes

```bash
python -m pipeline.run
# no period may be reported without its full window (must print 0):
python -c "import json,os;W={'1M':20,'3M':60,'6M':120,'12M':240};print(sum(1 for f in os.listdir('web/data/stocks') for k in json.load(open('web/data/stocks/'+f,encoding='utf-8'))['periods'] if json.load(open('web/data/stocks/'+f,encoding='utf-8'))['bars']<W[k]))"
```
Then load the site and actually look at it — main table, a stock detail chart, a
large theme, and search.
