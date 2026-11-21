"""Financial Modeling Prep (FMP) data provider.

Turned on by setting FMP_API_KEY (environment variable, or a Streamlit secret on the website).
FMP_PLAN = "free" (default) or "paid":
  * free: the 250-requests-a-day plan. FMP is used for the stocks you open and your watchlist;
          peers are loaded from Yahoo to stay inside the daily limit.
  * paid: FMP for everything, including peers.

What FMP adds over Yahoo, even on the free plan: analyst consensus several years ahead,
including real EBITDA and EBIT consensus, and consensus vs actual for both EPS and revenue.
Anything FMP can't provide (plan limits, errors, daily limit reached) falls back to Yahoo.
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np
import pandas as pd

from .models import FUNDAMENTALS, CompanyData, Estimates

API = "https://financialmodelingprep.com/stable/"
FREE_LIMIT = 5                  # free plan: at most 5 periods per request
FUNDAMENTALS_TTL = 12 * 3600    # statements and estimates change rarely
MARKET_TTL = 15 * 60            # prices and quotes


class FMPError(RuntimeError):
    pass


class FMPPlanLimit(FMPError):
    """The endpoint or parameter needs a higher FMP plan (HTTP 402)."""


class FMPDailyLimit(FMPError):
    """Too many requests (HTTP 429): the daily or per-minute allowance is used up."""


_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()
_calls = {"count": 0, "day": time.strftime("%Y-%m-%d")}


def api_key() -> str:
    return os.environ.get("FMP_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def plan() -> str:
    return "paid" if os.environ.get("FMP_PLAN", "free").strip().lower() == "paid" else "free"


def calls_today() -> int:
    today = time.strftime("%Y-%m-%d")
    if _calls["day"] != today:
        _calls.update(count=0, day=today)
    return _calls["count"]


def _get(path: str, ttl: int, http=None, **params):
    """GET an FMP endpoint (cached). The key is sent in the 'apikey' header, never in the URL."""
    url = API + path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.time()
    with _lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < ttl:
            return hit[1]
    if http is None:
        import requests
        http = requests
    r = http.get(url, headers={"apikey": api_key()}, timeout=20)
    with _lock:
        calls_today()
        _calls["count"] += 1
    if r.status_code == 402:
        raise FMPPlanLimit(f"{path} needs a higher FMP plan")
    if r.status_code == 429:
        raise FMPDailyLimit("FMP request limit reached for now")
    if r.status_code in (401, 403):
        raise FMPError("FMP rejected the API key (check FMP_API_KEY)")
    if r.status_code >= 400:
        raise FMPError(f"FMP error {r.status_code} on {path}")
    data = r.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise FMPError(data["Error Message"])
    with _lock:
        _cache[url] = (now, data)
    return data


def _limit(n: int) -> int:
    return n if plan() == "paid" else min(n, FREE_LIMIT)


def _num(v):
    try:
        v = float(v)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _statement(rows: list[dict]) -> pd.DataFrame:
    cols = {"revenue": "revenue", "ebitda": "ebitda", "ebit": "ebit", "eps": "epsDiluted"}
    if not rows:
        return pd.DataFrame(columns=FUNDAMENTALS, index=pd.DatetimeIndex([]), dtype=float)
    df = pd.DataFrame([{k: _num(r.get(src)) for k, src in cols.items()} for r in rows],
                      index=pd.to_datetime([r["date"] for r in rows]))
    if df["ebit"].isna().all():
        df["ebit"] = [_num(r.get("operatingIncome")) for r in rows]
    return df.sort_index().reindex(columns=FUNDAMENTALS)


def _us_like(symbol: str) -> bool:
    """FMP peer lists mix in foreign listings; keep US-traded tickers (no exchange suffix, not OTC '...F')."""
    return "." not in symbol and not (len(symbol) == 5 and symbol.endswith("F"))


def load(ticker: str, with_peers: bool = True, http=None) -> CompanyData:
    """Build CompanyData from FMP. Raises FMPError if the core data can't be loaded."""
    t = ticker.upper()
    g = lambda path, ttl=FUNDAMENTALS_TTL, **p: _get(path, ttl, http=http, symbol=t, **p)
    sources: dict[str, str] = {}

    prof = g("profile", MARKET_TTL)
    if not prof:
        raise FMPError(f"FMP has no data for {t}")
    prof = prof[0]
    price, mcap = _num(prof.get("price")), _num(prof.get("marketCap"))

    annual = _statement(g("income-statement", period="annual", limit=_limit(10)))
    quarterly = _statement(g("income-statement", period="quarter", limit=_limit(12)))
    sources["financials"] = "FMP"

    # Net debt from the latest balance sheet.
    net_debt = None
    try:
        bs = g("balance-sheet-statement", period="quarter", limit=1)
        if bs:
            net_debt = _num(bs[0].get("netDebt"))
            if net_debt is None:
                net_debt = (_num(bs[0].get("totalDebt")) or 0) - (_num(bs[0].get("cashAndCashEquivalents")) or 0)
    except FMPPlanLimit:
        pass

    # Annual consensus: every future fiscal year FMP has (revenue, EBITDA, EBIT, EPS).
    est = Estimates()
    try:
        rows = g("analyst-estimates", period="annual", limit=10)
        ea = pd.DataFrame([{"eps": _num(r.get("epsAvg")), "revenue": _num(r.get("revenueAvg")),
                            "ebitda": _num(r.get("ebitdaAvg")), "ebit": _num(r.get("ebitAvg")),
                            "analysts": _num(r.get("numAnalystsEps"))} for r in rows],
                          index=pd.to_datetime([r["date"] for r in rows])).sort_index() if rows else pd.DataFrame()
        last_actual = annual.index.max() if len(annual) else None
        future = ea[ea.index > last_actual] if (len(ea) and last_actual is not None) else ea
        if len(future):
            est.annual = future[["eps", "revenue", "ebitda", "ebit"]]
            est.fy0_end = future.index[0]
            est.eps_fy0, est.revenue_fy0 = future["eps"].iloc[0], future["revenue"].iloc[0]
            if len(future) > 1:
                est.eps_fy1, est.revenue_fy1 = future["eps"].iloc[1], future["revenue"].iloc[1]
            n = future["analysts"].iloc[min(1, len(future) - 1)]
            est.analysts = int(n) if n else None
            sources["estimates"] = "FMP"
    except FMPPlanLimit:
        pass

    # Quarterly consensus vs actual (EPS and revenue) and the next quarter's consensus.
    try:
        rows = g("earnings", limit=_limit(12))
        q_ends = list(quarterly.index.sort_values())
        surprises, future_q = [], []
        for r in sorted(rows, key=lambda r: r["date"]):
            report = pd.Timestamp(r["date"])
            if r.get("epsActual") is None and r.get("revenueActual") is None:
                future_q.append(r)
                continue
            # The quarter this report covers: the latest quarter ending before the report date.
            ended = [d for d in q_ends if d < report]
            if ended and (report - ended[-1]).days <= 120:
                surprises.append({"date": ended[-1], "eps_estimate": _num(r.get("epsEstimated")),
                                  "eps_actual": _num(r.get("epsActual")),
                                  "revenue_estimate": _num(r.get("revenueEstimated")),
                                  "revenue_actual": _num(r.get("revenueActual"))})
        if surprises:
            est.eps_surprises = pd.DataFrame(surprises).drop_duplicates("date", keep="last").set_index("date")
        if q_ends:
            for i, r in enumerate(future_q[:2], start=1):
                end = q_ends[-1] + pd.DateOffset(months=3 * i) + pd.offsets.MonthEnd(0)
                est.quarters.append({"end": end, "revenue": _num(r.get("revenueEstimated")),
                                     "eps": _num(r.get("epsEstimated"))})
    except FMPPlanLimit:
        pass

    # Daily prices (split-adjusted).
    prices = pd.Series(dtype=float)
    try:
        rows = g("historical-price-eod/light", MARKET_TTL, **{"from": "2000-01-01"})
        if rows:
            prices = pd.Series([_num(r.get("price")) for r in rows],
                               index=pd.to_datetime([r["date"] for r in rows])).dropna().sort_index()
            sources["prices"] = "FMP"
    except FMPPlanLimit:
        pass

    peers: list[str] = []
    if with_peers:
        try:
            peers = [p["symbol"] for p in g("stock-peers") if _us_like(p.get("symbol", ""))]
        except FMPPlanLimit:
            pass

    shares = mcap / price if (mcap and price) else None
    return CompanyData(
        ticker=t, name=prof.get("companyName") or t, sector=prof.get("sector") or "",
        industry=prof.get("industry") or "", currency=prof.get("currency") or "USD", price=price,
        market_cap=mcap, enterprise_value=(mcap + net_debt) if (mcap and net_debt is not None) else None,
        shares=shares, net_debt=net_debt, prices=prices, annual=annual, quarterly=quarterly,
        estimates=est, peers=peers, sources=sources,
    )
