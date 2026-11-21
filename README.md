# Forward P/E Investment Dashboard

A quick first-pass research tool built on one idea:

> **Price = Forward fundamental × Multiple**
>
> A stock moves because (1) its expected earnings (or revenue) change and (2) the multiple the market pays for them expands or contracts. Forecast both and you have a view on the price.

Enter a ticker and the dashboard answers: *what multiple is the market paying, what multiple is fair compared with peers and history, and what does that imply for the price?*

## Three valuation lenses
| Lens | Formula (all forward, next 12 months) | Best for |
|---|---|---|
| **P/E** | Price ÷ forward EPS | Profitable, mature companies |
| **EV/EBITDA** | (Market cap + net debt) ÷ forward EBITDA | Comparing companies with different debt levels; capital-heavy or lower-margin businesses |
| **P/S** | Market cap ÷ forward revenue | Fast growers that aren't profitable yet |

- **Auto lens** (the default): P/E when forward EPS is positive and P/E is below 75x; otherwise EV/EBITDA when forward EBITDA is positive and below 50x; otherwise P/S. You can override it per stock in the sidebar, and the watchlist remembers your choice.
- **Forward EBITDA**: Yahoo has no EBITDA consensus, so it is estimated as revenue consensus × the latest reported EBITDA margin. A paid source would supply real EBITDA estimates.
- A lens is marked **not meaningful** when its forward fundamental is negative or the multiple is extreme (P/E > 150x, EV/EBITDA > 100x, P/S > 60x).
- Every fair-multiple method (peer median, growth-adjusted, regression, own history) runs on each lens. P/E is judged against EPS growth; EV/EBITDA and P/S against revenue growth.

## How to run it (no technical knowledge needed)

**One-time setup**
1. **Install Python** from https://www.python.org/downloads/ (click the big yellow Download button).
   - **Windows:** on the first installer screen, tick **"Add python.exe to PATH"** before clicking Install.
   - **Mac:** open the downloaded file and click through the installer.
2. **Download this tool**: on the GitHub page, switch to the branch `claude/investment-analysis-dashboard-acktlb`, click the green **Code** button, then **Download ZIP**. Unzip it (double-click the ZIP file) and move the folder somewhere easy to find, such as Documents.

**Every time you want to use it**
- **Windows:** open the folder and double-click **`run_windows.bat`**. If Windows shows "Windows protected your PC", click **More info → Run anyway**.
- **Mac:** open the folder, **right-click `run_mac.command` → Open**, then click **Open** again. (Right-clicking is only needed the first time; after that a double-click works.)

A black window opens. The first time, it spends a few minutes installing things. Then the dashboard opens in your web browser. **Keep the black window open** while you use the dashboard; close it when you're done.

**For people comfortable with a terminal:** `pip install -r requirements.txt`, then `streamlit run app.py`.

## Real data from Financial Modeling Prep (FMP)

Without any setup, the app uses free Yahoo Finance data. Adding an FMP key makes FMP the main source, with Yahoo filling any gaps.

**What FMP adds, even on the free plan**
- Analyst forecasts up to 5 years ahead, including **real EBITDA and EBIT forecasts** (instead of revenue × latest margin)
- **Revenue and EPS forecast vs actual** for recent quarters, plus next quarter's forecast
- An official service, so it's more reliable on the website than Yahoo

**What still needs a paid FMP plan:** more than 5 years of annual / 5 quarters of quarterly history, quarterly forecasts beyond next quarter, and longer forecast-vs-actual history.

**Setup on the website**
1. At share.streamlit.io, open your app's **⋮** menu → **Settings** → **Secrets**.
2. Add this line under the GitHub line that's already there, with your key between the quotes, then **Save**:
   ```
   FMP_API_KEY = "your_fmp_key"
   ```
3. If you upgrade to a paid FMP plan, add `FMP_PLAN = "paid"` as well so the app uses FMP for peers too.

**Setup on your own computer:** in the app folder, create a folder called `.streamlit` and in it a text file called `secrets.toml` containing the same line(s). It is never uploaded to GitHub.

**The free plan's 250 requests a day:** each stock you open uses about 8, so the app uses FMP for the stocks you open and your watchlist, loads peers from Yahoo, and remembers results for 12 hours. The line under the company name shows where each number came from and how many FMP requests have been used. If the daily limit is reached, the app switches to Yahoo automatically and says so.

## Saving the watchlist on the website

The website version (Streamlit Community Cloud) wipes files whenever the app restarts, so the watchlist needs somewhere permanent to live. The app can save it to **your own GitHub account** as a *secret gist* (a small private note). It isn't listed or searchable; only someone with its exact web address could see it, and it contains only your tickers, multiples and notes.

**One-time setup (about 5 minutes)**
1. **Create a key on GitHub.** Sign in at github.com, click your profile picture (top right) → **Settings** → **Developer settings** (bottom of the left menu) → **Personal access tokens** → **Tokens (classic)** → **Generate new token** → **Generate new token (classic)**.
   - **Note:** type `Investment dashboard watchlist`
   - **Expiration:** choose **No expiration** (or a date; when it expires the app will warn you and you'll make a new one)
   - **Scopes:** tick **only `gist`**. Nothing else is needed, so the key can't touch your code or settings.
   - Click **Generate token** and **copy** the key (it starts with `ghp_`). GitHub only shows it once.
2. **Give the key to the app.** At share.streamlit.io, open your app's **⋮** menu → **Settings** → **Secrets**, paste this line (with your key between the quotes), and click **Save**:
   ```
   WATCHLIST_GITHUB_TOKEN = "ghp_your_key_here"
   ```
3. The app restarts by itself. Open **Watchlist → Saving & backup** in the sidebar: it should say *saved to your GitHub account*. The first time you add or change a stock, the app creates the gist.

**Good to know**
- Your existing watchlist doesn't move over automatically. If you built one before, use **Download a backup** first, then **Restore from a backup file** after setup.
- If GitHub can't be reached or the key stops working, the app shows a warning and **won't save** until it's fixed, so it can never overwrite your saved list with a blank one.
- Running on your own computer, no setup is needed: the watchlist is saved in `watchlist.json` in the app folder. (You can also use the key there by setting the same `WATCHLIST_GITHUB_TOKEN` environment variable, so both share one watchlist.)
- **Download a backup** (Watchlist → Saving & backup) any time for an extra copy.

## What's on the dashboard

| Section | What it shows | Why it matters for the thesis |
|---|---|---|
| **Headline** | Price, forward fundamental, current and fair multiple on the chosen lens, fair value, upside, and an undervalued/fair/overvalued call (±10% band) | The answer in one line |
| **① Price** | Price chart with 1M → Max timeframes and a 50-day average, with quarterly revenue and diluted EPS stacked tightly underneath on the same timeline. Dashed lines show analyst consensus: for the next two unreported quarters, and for EPS also what analysts expected in each of the last 4 quarters (so you can see beats and misses) | Price and results in one place |
| **② Fundamentals vs price** | Revenue and diluted EPS lines stacked under the price (annual or quarterly TTM, consensus estimates dashed); price vs EPS vs revenue indexed to 100; YoY growth table | Did the stock follow the fundamentals? |
| **③ Valuation summary** | Football-field chart of fair value on P/E, EV/EBITDA and P/S (range across methods, blended value, current price, 52-week range); a count of how many lenses agree | Do the lenses agree? |
| **④ Multiple history** | Any of the three multiples over time with average and ±1σ band; the past N years' return split into fundamental growth and multiple change | Is today's multiple stretched or cheap against its own history? |
| **⑤ Peer valuation** | The chosen multiple vs peers; multiple vs growth scatter with a peer regression line; comps table with all three multiples, growth, margins and Rule of 40 | Is the premium or discount earned by growth? |
| **⑥ Price target** | Editable bear/base/bull scenarios on the chosen lens (growth × exit multiple); waterfall of growth vs multiple contribution; sensitivity heatmap; trend in the EPS consensus | Where the stock could go, and why |

### How the fair multiple is estimated (sidebar toggles, applied to each lens)
1. **Peer median** multiple
2. **Peer growth-adjusted**: the peers' median multiple per point of growth (PEG for P/E) applied to this company's growth
3. **Multiple vs growth regression** across peers, read off at this company's growth rate
4. **Own 5-year average** multiple

The ones you tick are averaged equally, or you can enter your own fair multiple for the chosen lens.

### Definitions
- **Forward EPS (NTM)**: the next 12 months' EPS, mixing the current and next fiscal-year consensus by how much of the current year is left. You can switch to "Next fiscal year".
- **Historical forward P/E**: for past dates, the EPS the company *actually reported* over the following year is used, because free data doesn't keep old consensus estimates. Recent points use today's consensus.

## Project layout
```
app.py                 Entry point: page navigation
views/dashboard.py     Single-stock dashboard
views/watchlist.py     Watchlist ranking page
views/common.py        Shared cached loaders, formatting, controls
analysis/watchlist.py  Watchlist JSON storage
analysis/models.py     CompanyData / Estimates containers
analysis/data.py       Data providers: picks FMP, Yahoo or demo data
analysis/fmp.py        Financial Modeling Prep provider
analysis/valuation.py  Pure valuation math: NTM EPS, forward P/E history, peers, fair multiple, scenarios
tests/                 pytest unit tests (`python -m pytest`)
```

## Known limitations and next steps
- **Data depth**: free data (Yahoo, or FMP's free plan) gives about 5 years of annual and 5 quarters of quarterly statements. A paid FMP plan adds decades of history and quarterly forecasts. **Historical consensus** (what analysts expected on each past date, for a truly point-in-time forward P/E history) needs a professional source such as FactSet or LSEG I/B/E/S.
- **Peers**: filled in automatically from Yahoo's list of the industry's largest companies; check and edit the list in the sidebar.
- Possible additions: saved theses, earnings-revision alerts, sector-specific lenses (e.g. P/B for banks).

*For research only. Not investment advice.*
