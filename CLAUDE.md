# CLAUDE.md — GodFlow

Read this first. It carries the decisions and traps that are **not** recoverable
from the code, so a fresh session (or a different model) can continue safely.

- **Live:** https://yejooni.github.io/marketflow
- **Repo:** `yejooni/marketflow`, default branch **`master`** (not `main`)
- **Brand is `GodFlow`; the repo and URL stay `marketflow`.** Renaming the repo
  would break the published URL. Do not "fix" this inconsistency.
- Working dir: `C:\Workspaces-cc\marketflow`
- UI language is Korean. Write user-facing strings in Korean.

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
python -m pipeline.run                 # full run, ~3 min local
python -m pipeline.run --limit 300 --skip-themes   # fast dev loop
python -m pipeline.backtest            # revalidate the probability model
cd web && python -m http.server 8765   # local preview
```
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
- **Themes: Naver theme directory**, up to 2 per stock, most *specific* first
  (fewest members = most identifying).
- **거래대금 is ESTIMATED**: `volume x (O+H+L+C)/4`. No source publishes it
  historically. Validated at **0.70% median error** vs KRX actuals (close-only
  was 1.71%). Always label it 추정 in the UI.

### The daily job refetches everything — keep it that way
It pulls ~500 calendar days per stock every run, not one day. Reasons:
the 12-month high needs 240 sessions plus MA120 warmup anyway; **one request
returns any range**, so incremental fetching saves zero requests; and a full
rebuild absorbs splits/rights issues automatically, whereas appending one day at
a time would silently corrupt a series after a 액면분할. Runners are ephemeral
and data is never committed, so there is nothing to append to.

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

## Deployment

`.github/workflows/daily.yml` — cron `17 20 * * 0-4` UTC = **05:17 KST Mon–Fri**.
At 05:17 KST on day D the runner's UTC date is D-1, exactly the last closed
Korean session, so no timezone juggling is needed. Measured end-to-end: **~2.5
min** (collect+analyse 110s).

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
- MA palette is validated for colour-vision deficiency in both themes. Light uses
  Kiwoom defaults `#FF0000/#CC00CC/#009900/#0000FF`; dark is re-stepped to
  `#F04A4A/#D45BD4/#2FA050/#4A86E8` (pure blue fails the dark lightness band).
  Revalidate with the `dataviz` skill's `validate_palette.js` if changed.
- Probability shows `–`, never `0.0%`, when the sample is too small — 0% would
  read as "cannot break out".

## Verify after changes

```bash
python -m pipeline.run
# no period may be reported without its full window (must print 0):
python -c "import json,os;W={'1M':20,'3M':60,'6M':120,'12M':240};print(sum(1 for f in os.listdir('web/data/stocks') for k in json.load(open('web/data/stocks/'+f,encoding='utf-8'))['periods'] if json.load(open('web/data/stocks/'+f,encoding='utf-8'))['bars']<W[k]))"
```
Then load the site and actually look at it — main table, a stock detail chart, a
large theme, and search.
