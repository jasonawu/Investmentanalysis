"""Valuation math. Pure functions only (no network, no UI) so they are easy to test.

Core idea of the tool:
    Price = Forward fundamental x Multiple
so a stock's return over a period decomposes into
    (1 + return) ~= (1 + growth in the fundamental) x (1 + change in the multiple).

Three lenses ("metrics") are supported, all on *forward* (next-12-month) numbers:
    pe         Price / forward EPS                       mature, profitable companies
    ev_ebitda  Enterprise value / forward EBITDA         capital-structure neutral; lower-margin or leveraged firms
    ps         Market cap / forward revenue (P/S)        fast growers that are not yet profitable

Forward EBITDA: free data has no EBITDA consensus, so it is estimated as
forward revenue consensus x the latest reported EBITDA margin.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .models import CompanyData

YEAR_DAYS = 365.25
FAIR_BAND = 0.10  # within +/-10% of fair value reads as "fairly priced"


# --------------------------------------------------------------------------- #
# Metric definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Metric:
    key: str
    label: str          # "Forward P/E"
    short: str          # "P/E"
    field: str          # fundamental it divides by
    field_label: str    # "EPS"
    enterprise: bool    # numerator is EV (True) or equity value (False)
    per_share: bool     # fundamental is already per share (EPS)
    growth_field: str   # which growth justifies the multiple
    cap: float          # multiples above this are treated as not meaningful


METRICS: dict[str, Metric] = {
    "pe": Metric("pe", "Forward P/E", "P/E", "eps", "EPS", False, True, "eps", 150),
    "ev_ebitda": Metric("ev_ebitda", "Forward EV/EBITDA", "EV/EBITDA", "ebitda", "EBITDA", True, False, "revenue", 100),
    "ps": Metric("ps", "Forward P/S", "P/S", "revenue", "Revenue", False, False, "revenue", 60),
}
GROWTH_COL = {"eps": "eps_growth", "revenue": "rev_growth"}


# --------------------------------------------------------------------------- #
# Fiscal-year tables and forward (NTM) values
# --------------------------------------------------------------------------- #
def ebitda_margin(c: CompanyData) -> float | None:
    a = c.annual.dropna(subset=["revenue", "ebitda"]).sort_index() if len(c.annual) else c.annual
    if len(a) and a["revenue"].iloc[-1]:
        return float(a["ebitda"].iloc[-1] / a["revenue"].iloc[-1])
    return None


def fiscal_table(c: CompanyData, field: str) -> pd.Series:
    """Values by fiscal-year end: reported actuals plus the current (FY0) and next (FY1) estimates."""
    act = c.annual[field].dropna().astype(float).sort_index() if field in c.annual else pd.Series(dtype=float)
    e = c.estimates
    if field == "eps":
        f0, f1 = e.eps_fy0, e.eps_fy1
    elif field == "revenue":
        f0, f1 = e.revenue_fy0, e.revenue_fy1
    elif field == "ebitda":
        m = ebitda_margin(c)
        f0 = e.revenue_fy0 * m if (m is not None and e.revenue_fy0) else None
        f1 = e.revenue_fy1 * m if (m is not None and e.revenue_fy1) else None
    else:
        f0 = f1 = None
    fy0_end = e.fy0_end
    if fy0_end is None and len(act):
        fy0_end = act.index.max() + pd.DateOffset(years=1)
    rows = dict(act)
    if fy0_end is not None:
        if f0 is not None and fy0_end not in rows:
            rows[fy0_end] = f0
        if f1 is not None:
            rows[fy0_end + pd.DateOffset(years=1)] = f1
    return pd.Series(rows, dtype=float).sort_index()


def ntm_value_at(date: pd.Timestamp, fy: pd.Series) -> float | None:
    """Next-twelve-months value at `date`, time-weighting the two fiscal years it spans.

    If FY_k (ending e_k) contains `date`, with f = remaining fraction of FY_k:
        NTM = f * FY_k + (1 - f) * FY_k+1
    This is the standard way sell-side "forward" multiples smooth the fiscal-year roll.
    """
    later = fy.index[fy.index >= date]
    if len(later) < 2:
        return None
    e_k, e_k1 = later[0], later[1]
    f = float(np.clip((e_k - date).days / YEAR_DAYS, 0.0, 1.0))
    return f * fy[e_k] + (1 - f) * fy[e_k1]


def forward_value(c: CompanyData, field: str, basis: str = "ntm",
                  today: pd.Timestamp | None = None) -> float | None:
    fy = fiscal_table(c, field)
    if basis == "fy1":
        e = c.estimates
        nxt = (e.fy0_end + pd.DateOffset(years=1)) if e.fy0_end is not None else None
        return float(fy[nxt]) if nxt is not None and nxt in fy.index else None
    return ntm_value_at(today or pd.Timestamp.today().normalize(), fy)


def forward_growth(c: CompanyData, field: str) -> float | None:
    """Consensus growth FY1 vs FY0 for 'eps' or 'revenue'."""
    e = c.estimates
    a, b = (e.eps_fy0, e.eps_fy1) if field == "eps" else (e.revenue_fy0, e.revenue_fy1)
    if a and b and a > 0:
        return b / a - 1
    return None


def shares_of(c: CompanyData) -> float | None:
    if c.shares:
        return c.shares
    return c.market_cap / c.price if (c.market_cap and c.price) else None


def net_debt_of(c: CompanyData) -> float:
    if c.net_debt is not None:
        return c.net_debt
    if c.enterprise_value and c.market_cap:
        return c.enterprise_value - c.market_cap
    return 0.0


# --------------------------------------------------------------------------- #
# Multiples: current, implied price, history
# --------------------------------------------------------------------------- #
def numerator(c: CompanyData, metric: str, price: float | None = None) -> float | None:
    """Value the multiple is computed on, at `price` (default: current price)."""
    m = METRICS[metric]
    price = c.price if price is None else price
    if price is None:
        return None
    if m.per_share:
        return price
    sh = shares_of(c)
    if not sh:
        return None
    equity = price * sh
    return equity + net_debt_of(c) if m.enterprise else equity


def multiple(c: CompanyData, metric: str, fwd: float | None, price: float | None = None) -> float | None:
    """Multiple at `price` given forward fundamental `fwd`. None when not meaningful (fwd <= 0)."""
    num = numerator(c, metric, price)
    if num is None or fwd is None or fwd <= 0:
        return None
    return num / fwd


def current_multiple(c: CompanyData, metric: str, basis: str = "ntm") -> float | None:
    return multiple(c, metric, forward_value(c, METRICS[metric].field, basis))


def implied_price(c: CompanyData, metric: str, mult: float | None, fwd: float | None) -> float | None:
    """Share price implied by applying `mult` to forward fundamental `fwd`."""
    m = METRICS[metric]
    if mult is None or fwd is None or fwd <= 0:
        return None
    value = mult * fwd
    if m.per_share:
        return value
    sh = shares_of(c)
    if not sh:
        return None
    if m.enterprise:
        value -= net_debt_of(c)
    return value / sh


def multiple_history(c: CompanyData, metric: str, freq: str = "W-FRI", basis: str = "ntm") -> pd.DataFrame:
    """Historical forward multiple.

    For past dates, "forward" fundamentals are what the company *actually went on
    to report* (free data doesn't keep historical consensus), blending into today's
    consensus for the most recent periods. EV and P/S history use today's share
    count and net debt, which is an approximation.
    """
    m = METRICS[metric]
    fy = fiscal_table(c, m.field)
    cols = ["price", "fwd", "multiple"]
    if c.prices.empty or len(fy) < 2:
        return pd.DataFrame(columns=cols)
    px = c.prices.resample(freq).last().dropna()
    out = []
    for d, p in px.items():
        if basis == "fy1":
            later = fy.index[fy.index >= d]
            v = fy[later[1]] if len(later) >= 2 else None
        else:
            v = ntm_value_at(d, fy)
        if v is None:
            continue
        mult = multiple(c, metric, v, price=p)
        out.append((d, p, v, mult if mult is not None else np.nan))
    return pd.DataFrame(out, columns=["date"] + cols).set_index("date")


# --------------------------------------------------------------------------- #
# Peer comparison and fair multiples
# --------------------------------------------------------------------------- #
def peer_row(c: CompanyData, basis: str = "ntm") -> dict:
    fwd = {f: forward_value(c, f, basis) for f in ("eps", "ebitda", "revenue")}
    annual = c.annual.sort_index()
    last = annual.iloc[-1] if len(annual) else pd.Series(dtype=float)
    rev = last.get("revenue")
    row = {
        "ticker": c.ticker, "name": c.name, "market_cap": c.market_cap, "price": c.price,
        "fwd_eps": fwd["eps"], "fwd_ebitda": fwd["ebitda"], "fwd_revenue": fwd["revenue"],
        "eps_growth": forward_growth(c, "eps"), "rev_growth": forward_growth(c, "revenue"),
        "op_margin": last.get("ebit") / rev if rev else np.nan,
        "ebitda_margin": last.get("ebitda") / rev if rev else np.nan,
    }
    for k, m in METRICS.items():
        v = multiple(c, k, fwd[m.field])
        row[k] = v if v is not None else np.nan
        g = row[GROWTH_COL[m.growth_field]]
        # Growth-adjusted multiple (PEG for P/E): multiple per point of growth.
        row[f"{k}_g"] = row[k] / (g * 100) if (g and g > 0 and v) else np.nan
    row["rule_of_40"] = ((row["rev_growth"] or 0) + (row["ebitda_margin"] or 0)) * 100 \
        if row["rev_growth"] is not None and row["ebitda_margin"] == row["ebitda_margin"] else np.nan
    return row


def peer_table(target: CompanyData, peers: list[CompanyData], basis: str = "ntm") -> pd.DataFrame:
    rows = [peer_row(target, basis)] + [peer_row(p, basis) for p in peers]
    df = pd.DataFrame(rows).drop_duplicates("ticker").set_index("ticker")
    df["is_target"] = df.index == target.ticker
    return df


@dataclass
class FairMultiple:
    method: str
    value: float | None
    note: str

    @property
    def key(self) -> str:
        return method_key(self.method)

    @property
    def pe(self) -> float | None:  # backwards-compatible alias
        return self.value


METHOD_KEYS = {"median": "Peer median", "growth": "Peer growth-adjusted",
               "regression": "Multiple vs growth regression", "own": "Own 5y average"}


def method_key(method: str) -> str:
    m = method.lower()
    if m.startswith("own"):
        return "own"
    if "regression" in m:
        return "regression"
    if "growth" in m or "peg" in m:
        return "growth"
    return "median"


def regression(peers: pd.DataFrame, metric: str):
    """OLS of multiple on growth across peers. Returns (slope, intercept, r2) or None."""
    gcol = GROWTH_COL[METRICS[metric].growth_field]
    d = peers[[gcol, metric]].dropna()
    if len(d) < 4:
        return None
    x, y = d[gcol].to_numpy(float), d[metric].to_numpy(float)
    if np.ptp(x) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    pred = intercept + slope * x
    ss_res, ss_tot = ((y - pred) ** 2).sum(), ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return float(slope), float(intercept), float(r2)


def valid_peers(table: pd.DataFrame, metric: str) -> pd.DataFrame:
    cap = METRICS[metric].cap
    p = table[~table["is_target"]]
    return p[(p[metric] > 0) & (p[metric] < cap)]


def fair_multiples(table: pd.DataFrame, history: pd.DataFrame, target: str, metric: str = "pe",
                   own_history_years: int = 5) -> list[FairMultiple]:
    """Four independent estimates of a fair multiple for `target`."""
    m = METRICS[metric]
    gname = "EPS" if m.growth_field == "eps" else "revenue"
    gcol = GROWTH_COL[m.growth_field]
    valid = valid_peers(table, metric)
    t = table.loc[target]
    g = t[gcol]
    g = None if g is None or g != g else float(g)
    out: list[FairMultiple] = []

    # 1) Peer median.
    if len(valid):
        out.append(FairMultiple(METHOD_KEYS["median"], float(valid[metric].median()),
                                f"Median {m.short} of {len(valid)} peers"))
    else:
        out.append(FairMultiple(METHOD_KEYS["median"], None, f"No peers with a meaningful {m.short}"))

    # 2) Growth-adjusted: peer median (multiple / growth) x target growth.
    ga = valid[f"{metric}_g"].dropna()
    ga = ga[(ga > 0) & (ga < 10)]
    if len(ga) and g and g > 0:
        out.append(FairMultiple(METHOD_KEYS["growth"], float(ga.median() * g * 100),
                                f"Peer median {m.short}/growth {ga.median():.2f} x {g*100:.1f}% {gname} growth"))
    else:
        out.append(FairMultiple(METHOD_KEYS["growth"], None, f"Needs positive {gname} growth"))

    # 3) Regression of the multiple on growth across peers.
    reg = regression(valid, metric)
    if reg and g is not None:
        slope, intercept, r2 = reg
        val = intercept + slope * g
        out.append(FairMultiple(METHOD_KEYS["regression"], float(val) if val > 0 else None,
                                f"{m.short} = {intercept:.1f} + {slope/100:.2f} x {gname} growth%  (R² {r2:.2f})"))
    else:
        out.append(FairMultiple(METHOD_KEYS["regression"], None, "Needs 4+ peers with growth data"))

    # 4) Own history.
    h = history["multiple"].dropna() if len(history) else pd.Series(dtype=float)
    h = h[(h > 0) & (h < m.cap)]
    if len(h):
        h = h[h.index >= h.index.max() - pd.DateOffset(years=own_history_years)]
        out.append(FairMultiple(METHOD_KEYS["own"], float(h.mean()), f"Range {h.min():.1f}x - {h.max():.1f}x"))
    else:
        out.append(FairMultiple(METHOD_KEYS["own"], None, "Not enough meaningful history"))
    return out


def blend(multiples: list[FairMultiple], weights: dict[str, float] | None = None) -> float | None:
    vals = [(m, (weights or {}).get(m.key, 1.0)) for m in multiples if m.value is not None]
    tot = sum(w for _, w in vals)
    if not vals or tot == 0:
        return None
    return sum(m.value * w for m, w in vals) / tot


# --------------------------------------------------------------------------- #
# Lens selection
# --------------------------------------------------------------------------- #
AUTO_RULE = ("P/E when forward EPS is positive and P/E is below 75x; otherwise EV/EBITDA when forward "
             "EBITDA is positive and below 50x; otherwise P/S.")


def auto_metric(c: CompanyData, basis: str = "ntm") -> str:
    pe = current_multiple(c, "pe", basis)
    if pe is not None and pe < 75:
        return "pe"
    ev = current_multiple(c, "ev_ebitda", basis)
    if ev is not None and ev < 50:
        return "ev_ebitda"
    return "ps"


# --------------------------------------------------------------------------- #
# Price target: fundamental growth x multiple change
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    name: str
    growth: float       # growth in the forward fundamental over the holding period
    exit_multiple: float


def decompose(c: CompanyData, metric: str, fwd: float, s: Scenario) -> dict:
    """Split the scenario's return into the two drivers of the philosophy."""
    price = c.price
    cur = multiple(c, metric, fwd)
    grown = fwd * (1 + s.growth)
    target = implied_price(c, metric, s.exit_multiple, grown)
    at_current_multiple = implied_price(c, metric, cur, grown)
    if target is None or at_current_multiple is None:
        return {}
    return {
        "current_multiple": cur, "exit_multiple": s.exit_multiple, "target": target,
        "total_return": target / price - 1,
        "from_fundamentals": at_current_multiple - price,
        "from_multiple": target - at_current_multiple,
        "multiple_change": s.exit_multiple / cur - 1,
    }


def sensitivity(c: CompanyData, metric: str, fwd: float, growths: list[float], mults: list[float]) -> pd.DataFrame:
    """Upside vs price (rows = growth, columns = exit multiple)."""
    data = [[(implied_price(c, metric, m, fwd * (1 + g)) or np.nan) / c.price - 1 for m in mults] for g in growths]
    return pd.DataFrame(data, index=growths, columns=mults)


# --------------------------------------------------------------------------- #
# Summary per metric and across metrics
# --------------------------------------------------------------------------- #
def verdict(upside: float | None, band: float = FAIR_BAND) -> str:
    if upside is None or not np.isfinite(upside):
        return "n/a"
    if upside > band:
        return "Undervalued"
    if upside < -band:
        return "Overvalued"
    return "Fair"


def evaluate_metric(c: CompanyData, metric: str, table: pd.DataFrame, basis: str = "ntm",
                    methods: set[str] | None = None, override: float | None = None) -> dict:
    hist = multiple_history(c, metric, basis=basis)
    fwd = forward_value(c, METRICS[metric].field, basis)
    ms = fair_multiples(table, hist, c.ticker, metric)
    used = [m for m in ms if methods is None or m.key in methods]
    model = blend(used)
    fair = override if override else model
    cur = multiple(c, metric, fwd)
    meaningful = cur is not None and cur < METRICS[metric].cap
    if not meaningful:  # e.g. losses, or near-zero earnings giving a 1000x P/E
        fwd_for_value = None
    else:
        fwd_for_value = fwd
    fv = implied_price(c, metric, fair, fwd_for_value)
    vals = [m.value for m in used if m.value is not None]
    lo = implied_price(c, metric, min(vals), fwd_for_value) if vals else None
    hi = implied_price(c, metric, max(vals), fwd_for_value) if vals else None
    up = fv / c.price - 1 if (fv is not None and c.price) else None
    own = next((m.value for m in ms if m.key == "own"), None)
    med = next((m.value for m in ms if m.key == "median"), None)
    return {
        "metric": metric, "fwd": fwd, "current": cur, "meaningful": meaningful, "model": model, "fair": fair,
        "fair_value": fv, "low": lo, "high": hi, "upside": up, "verdict": verdict(up),
        "custom": bool(override), "multiples": ms, "history": hist,
        "own_avg": own, "peer_median": med,
        "vs_own": (cur / own - 1) if (cur and own) else None,
        "vs_peers": (cur / med - 1) if (cur and med) else None,
    }


def summarize(c: CompanyData, peers: list[CompanyData], basis: str = "ntm", methods: set[str] | None = None,
              overrides: dict[str, float] | None = None, lens: str = "auto") -> dict:
    """Valuation on every metric, plus the headline result for the chosen lens."""
    overrides = overrides or {}
    table = peer_table(c, peers, basis)
    by_metric = {k: evaluate_metric(c, k, table, basis, methods, overrides.get(k)) for k in METRICS}
    chosen = auto_metric(c, basis) if lens == "auto" else lens
    h = by_metric[chosen]
    return {
        "ticker": c.ticker, "name": c.name, "industry": c.industry, "currency": c.currency,
        "price": c.price, "market_cap": c.market_cap, "lens": chosen, "lens_label": METRICS[chosen].short,
        "current": h["current"], "fair": h["fair"], "model": h["model"], "fair_value": h["fair_value"],
        "upside": h["upside"], "verdict": h["verdict"], "custom": h["custom"],
        "vs_own": h["vs_own"], "vs_peers": h["vs_peers"],
        "eps_growth": forward_growth(c, "eps"), "rev_growth": forward_growth(c, "revenue"),
        **{f"upside_{k}": v["upside"] for k, v in by_metric.items()},
        **{f"current_{k}": v["current"] for k, v in by_metric.items()},
        "n_peers": len(peers), "table": table, "by_metric": by_metric,
    }


# --------------------------------------------------------------------------- #
# Quarterly results with consensus fill-in
# --------------------------------------------------------------------------- #
def quarterly_view(c: CompanyData) -> pd.DataFrame:
    """Reported quarters plus consensus for the next unreported quarters, one row per quarter end.

    Columns:
      revenue, eps     reported values; for unreported quarters, the consensus estimate
      estimated        True for quarters not yet reported
      eps_consensus    consensus EPS for the quarter (recent reported quarters and unreported ones)
      eps_surprise     actual / consensus - 1 (beat > 0, miss < 0), where both are known
    """
    cols = ["revenue", "eps", "estimated", "eps_consensus", "eps_surprise"]
    q = c.quarterly.sort_index()
    out = pd.DataFrame({"revenue": q["revenue"], "eps": q["eps"], "estimated": False,
                        "eps_consensus": np.nan, "eps_surprise": np.nan}, index=q.index)[cols] \
        if len(q) else pd.DataFrame(columns=cols)
    s = c.estimates.eps_surprises
    if len(s) and len(q):
        # Match each consensus row to the reported quarter ending closest to it (within ~3 weeks).
        for d, r in s.iterrows():
            gaps = abs(q.index - d)
            k = gaps.argmin()
            if gaps[k] <= pd.Timedelta(days=21):
                qd = q.index[k]
                out.loc[qd, "eps_consensus"] = r.get("eps_estimate")
                if pd.notna(r.get("eps_actual")):
                    out.loc[qd, "eps"] = r.get("eps_actual")  # same basis as the consensus
    for e in c.estimates.quarters:
        if e["end"] in out.index:
            continue
        out.loc[e["end"]] = {"revenue": e.get("revenue"), "eps": e.get("eps"), "estimated": True,
                             "eps_consensus": e.get("eps"), "eps_surprise": np.nan}
    out = out.sort_index()
    for col in ["revenue", "eps", "eps_consensus", "eps_surprise"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["estimated"] = out["estimated"].fillna(False).astype(bool)
    rep = ~out["estimated"] & out["eps_consensus"].notna() & out["eps_consensus"].ne(0)
    out.loc[rep, "eps_surprise"] = (out.loc[rep, "eps"] - out.loc[rep, "eps_consensus"]) \
        / out.loc[rep, "eps_consensus"].abs()
    return out
