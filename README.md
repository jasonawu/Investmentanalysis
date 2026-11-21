# Forward P/E Investment Dashboard

A quick first-pass research tool built on one idea:

> **Price = Forward EPS × Forward P/E**
>
> A stock moves because (1) its expected earnings change and (2) the multiple the market pays for them expands or contracts. Forecast both and you have a view on the price.

Enter a ticker and the dashboard answers: *what multiple is the market paying, what multiple is fair compared with peers and history, and what does that imply for the price?*

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Type any Yahoo Finance ticker (e.g. `MSFT`, `NVDA`). Tickers starting with `DEMO` load offline sample data made up for testing.

## What's on the dashboard

| Section | What it shows | Why it matters for the thesis |
|---|---|---|
| **Headline** | Price, forward EPS, forward P/E, fair P/E, fair value, upside, and an under/fair/overvalued call (±10% band) | The answer in one line |
| **① Price** | Price chart with 1M → Max timeframes and a 50-day average | Context |
| **② Fundamentals vs price** | Revenue, EBITDA, EBIT, EPS bars lined up under the price chart (annual or quarterly TTM, with consensus estimates in orange); an indexed chart of price vs EPS vs revenue; YoY growth table | Did the stock follow earnings? |
| **③ Forward P/E history** | Forward P/E over time with average and ±1σ band; split of the past N years' return into *EPS growth* and *multiple change* | Is today's multiple stretched or cheap against its own history? |
| **④ Peer valuation** | Forward P/E vs peers; P/E vs EPS growth scatter with a peer regression line; comps table (growth, margins, EV/EBITDA, PEG) | Is the premium or discount earned by growth? |
| **⑤ Price target** | Editable bear/base/bull scenarios (EPS growth × exit P/E); waterfall of earnings vs multiple contribution; sensitivity heatmap; trend in the EPS consensus | Where the stock could go, and why |

## Watchlist (⭐ page)
Ranks every stock you follow by **upside to fair value** (fair forward P/E × forward EPS ÷ price − 1).
- **Add stocks** from the sidebar (comma-separated) or with **☆ Add to watchlist** on the stock dashboard.
- **Your judgment wins**: save your own fair P/E for a stock (dashboard → *Override with my own P/E* → *Save my P/E*, or the *Edit watchlist* table). Those stocks are ranked on your P/E and marked ★; the rest use the model blend chosen in the sidebar.
- **Two charts**: an upside ranking with the ±10% "fair" band, and current-vs-fair P/E showing how much the multiple would have to expand or contract.
- **Ranking table** also shows the P/E premium/discount to peers and to the stock's own 5-year average, plus expected EPS and revenue growth. You can re-rank by any of these or filter by verdict. Select a row to open that stock in the dashboard.
- Saved to `watchlist.json` next to the app (git-ignored; set `WATCHLIST_PATH` to keep it elsewhere). Starts with the demo tickers.

### How the fair P/E is estimated (sidebar toggles)
1. **Peer median** forward P/E
2. **Peer PEG × growth**: the peer median PEG applied to this company's expected EPS growth
3. **P/E vs growth regression** across peers, read off at this company's growth rate
4. **Own 5-year average** forward P/E

The ones you tick are averaged equally, or you can enter your own fair P/E.

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
analysis/data.py       Data providers: yfinance (live) and demo (offline)
analysis/valuation.py  Pure valuation math: NTM EPS, forward P/E history, peers, fair multiple, scenarios
tests/                 pytest unit tests (`python -m pytest`)
```

## Known limitations and next steps
- **Data depth**: Yahoo gives about 4 years of annual and 5 quarters of quarterly statements, and consensus only for the current and next fiscal year. A paid source (e.g. Financial Modeling Prep, FactSet, Koyfin) would add 10+ years of history, **true historical consensus estimates** and FY+2 estimates. Plug one in by adding a loader to `analysis/data.py` that returns `CompanyData`.
- **Peers**: filled in automatically from Yahoo's list of the industry's largest companies; check and edit the list in the sidebar.
- Possible additions: saved theses, EV/EBITDA as a second valuation lens, earnings-revision alerts.

*For research only. Not investment advice.*
