"""Valuation math. Pure functions only (no network, no UI) so they are easy to test.

Core idea of the tool:
    Price = Forward EPS x Forward P/E
so a stock's return over a period decomposes into
    (1 + return) = (1 + EPS growth) x (1 + change in forward P/E).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .models import CompanyData

YEAR_DAYS = 365.25


# --------------------------------------------------------------------------- #
# Forward (NTM) EPS
# --------------------------------------------------------------------------- #
def fiscal_eps_table(c: CompanyData) -> pd.Series:
    """EPS by fiscal-year end: reported actuals plus the two consensus years.

    Index = fiscal period end date, value = EPS. Estimates overwrite nothing
    reported; they are appended for FY0 (current, unreported) and FY1.
    """
    eps = c.annual["eps"].dropna().astype(float).sort_index() if "eps" in c.annual else pd.Series(dtype=float)
    e = c.estimates
    fy0_end = e.fy0_end
    if fy0_end is None and len(eps):
        fy0_end = eps.index.max() + pd.DateOffset(years=1)
    rows = dict(eps)
    if fy0_end is not None:
        if e.eps_fy0 is not None and fy0_end not in rows:
            rows[fy0_end] = e.eps_fy0
        if e.eps_fy1 is not None:
            rows[fy0_end + pd.DateOffset(years=1)] = e.eps_fy1
    return pd.Series(rows, dtype=float).sort_index()


def ntm_eps_at(date: pd.Timestamp, fy_eps: pd.Series) -> float | None:
    """Next-twelve-months EPS at `date`, time-weighting the two fiscal years it spans.

    If FY_k (ending e_k) contains `date`, with f = remaining fraction of FY_k:
        NTM = f * EPS(FY_k) + (1 - f) * EPS(FY_k+1)
    This is the standard way sell-side "forward P/E" smooths the fiscal-year roll.
    """
    ends = fy_eps.index
    later = ends[ends >= date]
    if len(later) < 2:
        return None
    e_k, e_k1 = later[0], later[1]
    f = float(np.clip((e_k - date).days / YEAR_DAYS, 0.0, 1.0))
    return f * fy_eps[e_k] + (1 - f) * fy_eps[e_k1]


def forward_pe_history(c: CompanyData, freq: str = "W-FRI", basis: str = "ntm") -> pd.DataFrame:
    """Historical forward P/E series.

    For past dates, "forward" earnings are the earnings the company *actually went
    on to report* (free data sources don't keep historical consensus), blended
    into the current consensus for the most recent periods.

    basis = "ntm": time-weighted next 12 months.  basis = "fy1": next full fiscal year.
    """
    fy_eps = fiscal_eps_table(c)
    if c.prices.empty or len(fy_eps) < 2:
        return pd.DataFrame(columns=["price", "fwd_eps", "fwd_pe"])
    px = c.prices.resample(freq).last().dropna()
    out = []
    for d, p in px.items():
        if basis == "fy1":
            later = fy_eps.index[fy_eps.index >= d]
            eps = fy_eps[later[1]] if len(later) >= 2 else None
        else:
            eps = ntm_eps_at(d, fy_eps)
        if eps is None:
            continue
        out.append((d, p, eps, p / eps if eps > 0 else np.nan))
    df = pd.DataFrame(out, columns=["date", "price", "fwd_eps", "fwd_pe"]).set_index("date")
    return df


def current_forward_eps(c: CompanyData, basis: str = "ntm", today: pd.Timestamp | None = None) -> float | None:
    today = today or pd.Timestamp.today().normalize()
    if basis == "fy1":
        return c.estimates.eps_fy1
    return ntm_eps_at(today, fiscal_eps_table(c))


def forward_eps_growth(c: CompanyData) -> float | None:
    """Consensus EPS growth FY1 vs FY0 (the market's 'next year' growth expectation)."""
    e = c.estimates
    if e.eps_fy0 and e.eps_fy1 and e.eps_fy0 > 0:
        return e.eps_fy1 / e.eps_fy0 - 1
    return None


def forward_revenue_growth(c: CompanyData) -> float | None:
    e = c.estimates
    if e.revenue_fy0 and e.revenue_fy1:
        return e.revenue_fy1 / e.revenue_fy0 - 1
    return None


# --------------------------------------------------------------------------- #
# Peer comparison and fair multiple
# --------------------------------------------------------------------------- #
def peer_row(c: CompanyData, basis: str = "ntm") -> dict:
    fwd_eps = current_forward_eps(c, basis)
    fwd_pe = c.price / fwd_eps if (c.price and fwd_eps and fwd_eps > 0) else np.nan
    g = forward_eps_growth(c)
    annual = c.annual.sort_index()
    last = annual.iloc[-1] if len(annual) else pd.Series(dtype=float)
    op_margin = last.get("ebit") / last.get("revenue") if last.get("revenue") else np.nan
    ev_ebitda = (c.enterprise_value / last.get("ebitda")) if (c.enterprise_value and last.get("ebitda")) else np.nan
    return {
        "ticker": c.ticker,
        "name": c.name,
        "market_cap": c.market_cap,
        "price": c.price,
        "fwd_eps": fwd_eps,
        "fwd_pe": fwd_pe,
        "eps_growth": g,
        "rev_growth": forward_revenue_growth(c),
        "op_margin": op_margin,
        "ev_ebitda": ev_ebitda,
        "peg": fwd_pe / (g * 100) if (g and g > 0 and fwd_pe == fwd_pe) else np.nan,
    }


def peer_table(target: CompanyData, peers: list[CompanyData], basis: str = "ntm") -> pd.DataFrame:
    rows = [peer_row(target, basis)] + [peer_row(p, basis) for p in peers]
    df = pd.DataFrame(rows).set_index("ticker")
    df["is_target"] = df.index == target.ticker
    return df


@dataclass
class FairMultiple:
    method: str
    pe: float | None
    note: str


def fair_multiples(table: pd.DataFrame, history: pd.DataFrame, target: str,
                   own_history_years: int = 5) -> list[FairMultiple]:
    """Several independent estimates of a fair forward P/E for `target`."""
    peers = table[~table["is_target"]]
    valid = peers[(peers["fwd_pe"] > 0) & (peers["fwd_pe"] < 200)]
    t = table.loc[target]
    out: list[FairMultiple] = []

    # 1) Peer median.
    if len(valid):
        out.append(FairMultiple("Peer median P/E", float(valid["fwd_pe"].median()),
                                f"Median forward P/E of {len(valid)} peers"))
    else:
        out.append(FairMultiple("Peer median P/E", None, "No peers with positive earnings"))

    # 2) Growth-adjusted: apply peer median PEG to target's growth.
    pegs = valid["peg"].dropna()
    pegs = pegs[(pegs > 0) & (pegs < 10)]
    g = t["eps_growth"]
    if len(pegs) and g and g > 0:
        out.append(FairMultiple("Peer PEG x growth", float(pegs.median() * g * 100),
                                f"Peer median PEG {pegs.median():.2f} x {g*100:.1f}% EPS growth"))
    else:
        out.append(FairMultiple("Peer PEG x growth", None, "Needs positive growth for target and peers"))

    # 3) Regression of P/E on EPS growth across peers.
    reg = pe_growth_regression(valid)
    if reg and g == g and g is not None:
        slope, intercept, r2 = reg
        out.append(FairMultiple("P/E vs growth regression", float(intercept + slope * g),
                                f"P/E = {intercept:.1f} + {slope/100:.2f} x growth%  (R² {r2:.2f})"))
    else:
        out.append(FairMultiple("P/E vs growth regression", None, "Needs 4+ peers with growth data"))

    # 4) Own history.
    h = history["fwd_pe"].dropna() if len(history) else pd.Series(dtype=float)
    if len(h):
        h = h[h.index >= h.index.max() - pd.DateOffset(years=own_history_years)]
        out.append(FairMultiple(f"Own {own_history_years}y average", float(h.mean()),
                                f"Range {h.min():.1f}x - {h.max():.1f}x"))
    else:
        out.append(FairMultiple(f"Own {own_history_years}y average", None, "Not enough history"))
    return out


def pe_growth_regression(peers: pd.DataFrame):
    d = peers[["eps_growth", "fwd_pe"]].dropna()
    if len(d) < 4:
        return None
    x, y = d["eps_growth"].to_numpy(float), d["fwd_pe"].to_numpy(float)
    if np.ptp(x) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    pred = intercept + slope * x
    ss_res, ss_tot = ((y - pred) ** 2).sum(), ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return float(slope), float(intercept), float(r2)


def blend(multiples: list[FairMultiple], weights: dict[str, float] | None = None) -> float | None:
    vals = [(m, (weights or {}).get(m.method, 1.0)) for m in multiples if m.pe is not None]
    tot = sum(w for _, w in vals)
    if not vals or tot == 0:
        return None
    return sum(m.pe * w for m, w in vals) / tot


# --------------------------------------------------------------------------- #
# Price target: earnings growth x multiple change
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    name: str
    eps_growth: float   # growth in forward EPS over the holding period
    exit_pe: float      # forward P/E at the end of the period


def scenario_price(fwd_eps: float, s: Scenario) -> float:
    return fwd_eps * (1 + s.eps_growth) * s.exit_pe


def decompose(price: float, fwd_eps: float, s: Scenario) -> dict:
    """Split expected return into the two drivers of the philosophy."""
    cur_pe = price / fwd_eps
    target = scenario_price(fwd_eps, s)
    earnings_part = price * s.eps_growth                       # EPS growth at today's multiple
    multiple_part = target - price - earnings_part             # re-rating (incl. cross term)
    return {
        "current_pe": cur_pe,
        "target": target,
        "total_return": target / price - 1,
        "from_earnings": earnings_part,
        "from_multiple": multiple_part,
        "multiple_change": s.exit_pe / cur_pe - 1,
    }


def sensitivity(fwd_eps: float, price: float, growths: list[float], pes: list[float]) -> pd.DataFrame:
    """Return grid (rows = EPS growth, columns = exit P/E) of implied upside vs price."""
    data = [[fwd_eps * (1 + g) * pe / price - 1 for pe in pes] for g in growths]
    return pd.DataFrame(data, index=growths, columns=pes)
