# Catalyst-Proximity Screener (v1)

A weekly screener that surfaces US stocks with a **confirmed upcoming earnings
date** and **historically elevated volatility**, ranked with a transparent,
traceable score. It is a research shortlist generator, not a prediction tool.

## What it actually does

For each stock reporting earnings in the next 21 days (configurable):
1. Filters out companies below a market-cap floor (avoids illiquid junk)
2. Pulls ~90 days of price history and computes **realized volatility**
   (how much the stock has actually moved historically) — used as a proxy
   for "how big a move might this earnings print cause," since real
   options-implied volatility isn't reliably free anywhere
3. Pulls analyst EPS estimate trend where available
4. Scores and ranks candidates: closer earnings date + higher historical
   volatility + positive estimate revisions = higher score

## What it does NOT do

- **It does not predict direction.** A high score means "this stock tends to
  move a lot around earnings," not "this stock will go up."
- **It is not backtested for profitability.** This is a filter for what to
  research next, not a trading signal validated against historical returns.
- **It excludes options data and short interest** (v1) because reliable free
  access to those doesn't exist. Don't add a paid data source that claims to
  provide these without verifying it actually does — see the conversation
  that produced this tool for why that verification step matters.

## Setup

1. Get a free API key at https://site.financialmodelingprep.com/developer/docs
   (you already have this)
2. Locally:
   ```bash
   export FMP_API_KEY="your_fmp_key_here"
   export FINNHUB_API_KEY="your_finnhub_key_here"   # optional but recommended -- enables headlines
   python3 screener.py
   python3 track_outcomes.py
   ```
3. Check `results.csv` for the full ranked list, `digest.txt` for the
   human-readable weekly summary (with best-effort headlines), and
   `history.csv` for the cumulative track record that builds up over time.

## Automating it completely (runs by itself, notifies you, no manual step)

This repo is fully wired for hands-off weekly operation via GitHub Actions.

**1. Create the GitHub repo and push (run these from inside this folder):**
```bash
git init
git add .
git commit -m "Initial commit: catalyst screener"
gh repo create catalyst-screener --private --source=. --push
```
(No `gh` CLI installed? Create an empty repo manually at github.com/new,
then instead of the last line run:
`git remote add origin https://github.com/YOUR_USERNAME/catalyst-screener.git`
followed by `git branch -M main` and `git push -u origin main`.)

**2. Add your secrets** (repo → Settings → Secrets and variables → Actions
→ "New repository secret"):
- `FMP_API_KEY` — your FMP key
- `FINNHUB_API_KEY` — free key from https://finnhub.io/register (used for
  headlines — FMP's news endpoint turned out to require a paid plan)
- `NTFY_TOPIC` — optional, a random hard-to-guess string (e.g.
  `elvin-catalyst-8f2x`) — this becomes your private notification channel

**3. Subscribe to notifications on your phone:**
- Install the free **ntfy** app (iOS/Android)
- Add the same topic name you set as `NTFY_TOPIC`
- That's it — you'll get a push notification every Sunday night with the
  week's top picks, scores, and headlines, straight from `digest.txt`

**4. Confirm it's live:** go to the repo's Actions tab and click
"Run workflow" once manually to test end-to-end before waiting for Sunday.

From here it runs itself: every week it re-screens, checks outcomes on
picks from ~a month ago, commits the updated `history.csv` back to the
repo (so the track record persists and grows), and pushes you a
notification. You never have to open the code again unless you want to
tune something.

## What's inside

- `screener.py` — weekly candidate scoring, logs top picks + headlines
- `track_outcomes.py` — checks back on month-old picks, builds the real track record in `history.csv`
- `backtest.py` — one-time-ish evidence check for whether the volatility factor is real (volatility clustering test, free-tier data only)
- `fmp_common.py` — shared API helpers used by all three scripts
- `.github/workflows/weekly-screener.yml` — runs screener + outcome-check every Sunday, commits history.csv back, sends ntfy notification

## Tuning it

Open `screener.py` and adjust the constants near the top:
- `LOOKAHEAD_DAYS` — how far ahead to look for earnings (default 21)
- `MIN_MARKET_CAP` / `MAX_MARKET_CAP` — filter by company size
- `TOP_N` — how many results to keep

## Does any of this actually work? Run the backtest before trusting it.

`backtest.py` tests the score's core claim -- that elevated historical
volatility predicts a BIGGER near-term move (never direction) -- using only
free historical price data. It does NOT use earnings dates (FMP's free tier
paywalls historical earnings-calendar queries, confirmed via a live 402
response), so instead it tests the more general, well-documented phenomenon
called **volatility clustering**: periods of high volatility tend to be
followed by more high volatility. This is exactly what the screener's
volatility factor is betting on, tested generally instead of earnings-specific.

```bash
export FMP_API_KEY="your_key_here"
python3 backtest.py
```

It samples ~30 large/mid-cap tickers at regular checkpoints (not
move-triggered, to avoid circular bias), computes realized volatility going
into each checkpoint, and compares it against the actual move over the next
1 and 5 trading days -- bucketed into quartiles. Read it honestly: if Q4
doesn't clearly beat Q1, the volatility factor isn't earning its weight in
the score and should be reduced or removed.

**What this version can't tell you:** whether volatility behaves
differently specifically around earnings days versus normal trading days --
that requires FMP's paid tier (historical earnings-calendar, ~$22/mo) or a
different free data source. If you want that more precise test later, say
so and we can revisit it.

## What changed since v1 (fixed after reviewing real runs)

- **Negative estimate revisions now hurt the score.** A stock with EPS
  estimates falling 29% used to score the same as a stock with no estimate
  data at all -- both just skipped the bonus. Now revisions cut both ways,
  symmetrically, so a real warning sign shows up as a real point deduction.
- **Shared API logic moved to `fmp_common.py`** so the screener and the
  backtest use identical request/error handling -- one place to fix if FMP
  changes an endpoint.
- **Backtest rebuilt around free data only** after a live 402 confirmed
  FMP's free tier paywalls historical earnings-calendar queries entirely
  (both symbol-filtered and general date-range queries). v2 tests
  volatility clustering from price history instead, which needs no
  earnings-calendar access at all.

## Extending it later

Reasonable next steps once this base is working and you trust the pipeline:
- Add a real options-data source (paid) for actual implied volatility
  instead of the realized-volatility proxy
- Add short interest from a source that genuinely provides it
- Backtest the scoring weights against actual post-earnings returns before
  trusting the score more than the raw numbers underneath it

## The one rule worth keeping regardless of how this evolves

Every number this script outputs should be traceable to a real API response.
If a future version of this adds a "score" you can't explain by pointing at
underlying data, that's the same failure mode as the pump-and-dump post that
started this — confident-looking output without a verifiable basis.
