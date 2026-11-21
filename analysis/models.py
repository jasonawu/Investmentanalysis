"""Plain data containers shared by the data providers, the valuation math and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Column names used for fundamentals everywhere in the app.
FUNDAMENTALS = ["revenue", "ebitda", "ebit", "eps"]
LABELS = {"revenue": "Revenue", "ebitda": "EBITDA", "ebit": "EBIT", "eps": "EPS (diluted)"}


@dataclass
class Estimates:
    """Consensus analyst estimates for the current (unreported) and next fiscal year."""

    eps_fy0: float | None = None        # current fiscal year (not yet reported)
    eps_fy1: float | None = None        # next fiscal year
    revenue_fy0: float | None = None
    revenue_fy1: float | None = None
    fy0_end: pd.Timestamp | None = None  # period-end date of the current fiscal year
    analysts: int | None = None
    # EPS estimate for next FY as it stood N days ago -> shows estimate revisions.
    eps_fy1_trend: dict[str, float] = field(default_factory=dict)
    # Next unreported quarters: [{"end": Timestamp, "revenue": float|None, "eps": float|None}, ...]
    quarters: list[dict] = field(default_factory=list)
    # Recent reported quarters, consensus EPS vs actual: index = quarter end, columns eps_estimate, eps_actual.
    eps_surprises: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["eps_estimate", "eps_actual"]))


@dataclass
class CompanyData:
    ticker: str
    name: str
    sector: str = ""
    industry: str = ""
    currency: str = "USD"
    price: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    shares: float | None = None          # diluted shares outstanding
    net_debt: float | None = None        # debt - cash (negative = net cash)
    # Daily close prices, DatetimeIndex -> float.
    prices: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    # Annual reported fundamentals: index = fiscal period end, columns = FUNDAMENTALS.
    annual: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=FUNDAMENTALS))
    # Quarterly reported fundamentals (same columns).
    quarterly: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=FUNDAMENTALS))
    estimates: Estimates = field(default_factory=Estimates)
    peers: list[str] = field(default_factory=list)
    is_demo: bool = False
