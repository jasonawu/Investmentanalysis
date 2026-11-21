"""Data providers.

`load_company(ticker)` returns a CompanyData. Two providers:
  * yfinance (free Yahoo Finance data, no API key)  -> real tickers
  * demo (synthetic, offline)                         -> tickers starting with "DEMO"
Swap in a paid provider (FMP, Polygon, etc.) by adding another loader that
returns the same CompanyData shape.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models import FUNDAMENTALS, CompanyData, Estimates

# Yahoo income-statement row names -> our column names (first match wins).
_ROWS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "ebit": ["EBIT", "Operating Income"],
    "eps": ["Diluted EPS", "Basic EPS"],
}


def _statement(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=pd.DatetimeIndex([]), columns=FUNDAMENTALS, dtype=float)
    if df is None or df.empty:
        return out
    cols = {}
    for key, names in _ROWS.items():
        for n in names:
            if n in df.index:
                cols[key] = pd.to_numeric(df.loc[n], errors="coerce")
                break
    out = pd.DataFrame(cols).reindex(columns=FUNDAMENTALS)
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.sort_index().dropna(how="all")


def _est(df: pd.DataFrame, period: str, col: str = "avg") -> float | None:
    try:
        v = float(df.loc[period, col])
        return v if np.isfinite(v) else None
    except Exception:
        return None


def load_yfinance(ticker: str, with_peers: bool = True, max_peers: int = 8) -> CompanyData:
    import yfinance as yf

    t = yf.Ticker(ticker)
    info = t.info or {}
    hist = t.history(period="max", auto_adjust=True)
    prices = hist["Close"].copy() if not hist.empty else pd.Series(dtype=float)
    if len(prices):
        prices.index = pd.to_datetime(prices.index).tz_localize(None)

    annual = _statement(t.income_stmt)
    quarterly = _statement(t.quarterly_income_stmt)

    ee = getattr(t, "earnings_estimate", None)
    re_ = getattr(t, "revenue_estimate", None)
    trend = getattr(t, "eps_trend", None)
    fy0_end = annual.index.max() + pd.DateOffset(years=1) if len(annual) else None
    est = Estimates(
        eps_fy0=_est(ee, "0y"), eps_fy1=_est(ee, "+1y"),
        revenue_fy0=_est(re_, "0y"), revenue_fy1=_est(re_, "+1y"),
        fy0_end=fy0_end,
        analysts=int(_est(ee, "+1y", "numberOfAnalysts") or 0) or None,
    )
    if trend is not None and not getattr(trend, "empty", True) and "+1y" in trend.index:
        est.eps_fy1_trend = {k: float(v) for k, v in trend.loc["+1y"].items() if pd.notna(v)}

    peers: list[str] = []
    if with_peers and info.get("industryKey"):
        try:
            top = yf.Industry(info["industryKey"]).top_companies
            if top is not None and not top.empty:
                peers = [s for s in top.index.tolist() if s.upper() != ticker.upper()][:max_peers]
        except Exception:
            peers = []

    price = info.get("currentPrice") or info.get("regularMarketPrice") or (float(prices.iloc[-1]) if len(prices) else None)
    mcap, ev = info.get("marketCap"), info.get("enterpriseValue")
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or (mcap / price if mcap and price else None)
    if info.get("totalDebt") is not None or info.get("totalCash") is not None:
        net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
    else:
        net_debt = ev - mcap if (ev and mcap) else None
    return CompanyData(
        ticker=ticker.upper(), name=info.get("longName") or info.get("shortName") or ticker.upper(),
        sector=info.get("sector", ""), industry=info.get("industry", ""),
        currency=info.get("currency", "USD"), price=price,
        market_cap=mcap, enterprise_value=ev, shares=shares, net_debt=net_debt,
        prices=prices, annual=annual, quarterly=quarterly, estimates=est, peers=peers,
    )


# --------------------------------------------------------------------------- #
# Demo provider: synthetic, internally consistent companies for offline use.
# --------------------------------------------------------------------------- #
_DEMO_UNIVERSE = {
    # ticker: (name, revenue_bn, rev_growth, op_margin, shares_bn, base_multiple, multiple_drift,
    #          net_debt_bn, priced_on)   priced_on = "pe" or "ps" (how the market values it)
    "DEMO":  ("Demo Software Corp",   40.0, 0.12,  0.30, 2.0, 24,  0.0,  -10.0, "pe"),
    "DEMOA": ("Alpha Cloud Systems",  25.0, 0.18,  0.25, 1.5, 32,  0.6,    5.0, "pe"),
    "DEMOB": ("Beta Enterprise Apps", 60.0, 0.06,  0.33, 3.0, 18, -0.4,   40.0, "pe"),
    "DEMOC": ("Gamma Data Inc",       12.0, 0.22,  0.18, 0.8, 38,  0.3,   -4.0, "pe"),
    "DEMOD": ("Delta Security Ltd",   18.0, 0.14,  0.27, 1.1, 27,  0.2,    2.0, "pe"),
    "DEMOE": ("Epsilon Networks",     35.0, 0.04,  0.22, 2.4, 15, -0.5,   25.0, "pe"),
    "DEMOF": ("Zeta Analytics",        9.0, 0.10,  0.20, 0.6, 22,  0.0,    0.0, "pe"),
    "DEMOG": ("Eta Hypergrowth AI",    4.0, 0.45, -0.12, 0.9, 14,  0.3,   -3.0, "ps"),
    "DEMOH": ("Theta Robotics",        6.0, 0.35, -0.04, 1.2,  9, -0.2,   -1.0, "ps"),
}


def demo_tickers() -> list[str]:
    return list(_DEMO_UNIVERSE)


def load_demo(ticker: str, with_peers: bool = True) -> CompanyData:
    key = ticker.upper()
    if key not in _DEMO_UNIVERSE:
        key = "DEMO"
    name, rev0, g, m, shares, pe0, drift, nd, priced_on = _DEMO_UNIVERSE[key]
    rng = np.random.default_rng(sum(ord(ch) * 31**i for i, ch in enumerate(key)) % (2**32))
    today = pd.Timestamp.today().normalize()
    fy_month = 12
    last_fy = pd.Timestamp(year=today.year - 1, month=fy_month, day=31)

    # 10 fiscal years of history + 2 estimate years.
    years = [last_fy - pd.DateOffset(years=k) for k in range(9, -1, -1)]
    growth = g + rng.normal(0, 0.04, len(years) + 2)
    if priced_on == "ps":  # young company: growth decelerating from very high levels
        growth = np.linspace(g * 1.8, g, len(years) + 2) + rng.normal(0, 0.03, len(years) + 2)
    growth[3] -= 0.12  # a down-cycle year so the charts are interesting
    rev = rev0 / np.prod(1 + growth[:len(years)]) * np.cumprod(1 + growth)
    lo = -0.8 if priced_on == "ps" else 0.05
    ramp = np.linspace(-0.25, 0.04, len(rev)) if priced_on == "ps" else np.linspace(-0.03, 0.02, len(rev))
    margin = np.clip(m + rng.normal(0, 0.02, len(rev)) + ramp, lo, 0.6)
    margin[3] -= 0.05
    ebit = rev * margin
    ebitda = ebit + rev * 0.06
    eps = np.where(ebit > 0, ebit * 0.80, ebit) / shares  # taxed only when profitable
    annual = pd.DataFrame({"revenue": rev[:10] * 1e9, "ebitda": ebitda[:10] * 1e9,
                           "ebit": ebit[:10] * 1e9, "eps": eps[:10]}, index=pd.DatetimeIndex(years))

    # Quarterly: split each year in 4 with mild seasonality.
    season = np.array([0.23, 0.245, 0.25, 0.275])
    q_rows, q_idx = [], []
    for d, row in annual.iterrows():
        for i in range(4):
            q_idx.append(d - pd.DateOffset(months=9 - 3 * i))
            q_rows.append(row * season[i])
    quarterly = pd.DataFrame(q_rows, index=pd.DatetimeIndex(q_idx)).sort_index()

    est = Estimates(eps_fy0=float(eps[10]), eps_fy1=float(eps[11]),
                    revenue_fy0=float(rev[10] * 1e9), revenue_fy1=float(rev[11] * 1e9),
                    fy0_end=last_fy + pd.DateOffset(years=1), analysts=int(rng.integers(12, 40)),
                    eps_fy1_trend={"current": float(eps[11]), "7daysAgo": float(eps[11] * 0.998),
                                   "30daysAgo": float(eps[11] * 0.99), "60daysAgo": float(eps[11] * 0.985),
                                   "90daysAgo": float(eps[11] * 0.97)})

    # Price = forward EPS x forward P/E (or forward sales/share x P/S); the multiple mean-reverts with noise.
    cdata = CompanyData(ticker=key, name=name, annual=annual, estimates=est)
    from .valuation import fiscal_table, ntm_value_at

    driver = "eps" if priced_on == "pe" else "revenue"
    fy_val = fiscal_table(cdata, driver)
    per_share = 1.0 if driver == "eps" else 1.0 / (shares * 1e9)
    days = pd.bdate_range(years[0] - pd.DateOffset(years=1) + pd.Timedelta(days=1), today)
    pe = np.empty(len(days))
    pe[0] = pe0
    shocks = rng.normal(0, 0.012, len(days))
    trend_target = pe0 * (1 + drift * np.linspace(-0.5, 0.5, len(days)) * 0.4)
    for i in range(1, len(days)):
        pe[i] = pe[i - 1] * np.exp(shocks[i]) + 0.004 * (trend_target[i] - pe[i - 1])
    ntm = np.array([ntm_value_at(d, fy_val) or np.nan for d in days]) * per_share
    prices = pd.Series(pe * ntm, index=days).dropna()

    price = float(prices.iloc[-1])
    peers = [t for t in _DEMO_UNIVERSE if t != key] if with_peers else []
    sector, industry = "Technology", "Software (demo)"
    return CompanyData(
        ticker=key, name=name, sector=sector, industry=industry,
        price=price, market_cap=price * shares * 1e9, enterprise_value=price * shares * 1e9 + nd * 1e9,
        shares=shares * 1e9, net_debt=nd * 1e9,
        prices=prices, annual=annual, quarterly=quarterly, estimates=est, peers=peers, is_demo=True,
    )


def load_company(ticker: str, with_peers: bool = True) -> CompanyData:
    if ticker.upper().startswith("DEMO"):
        return load_demo(ticker, with_peers)
    return load_yfinance(ticker, with_peers)
