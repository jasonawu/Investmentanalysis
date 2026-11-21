"""Helpers shared by the dashboard and watchlist pages: cached loaders, formatting, controls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from analysis import valuation as V
from analysis.data import load_company
from analysis.models import CompanyData

# Palette (validated reference categorical slots + neutral gray).
BLUE, ORANGE, AQUA, GRAY, RED = "#2a78d6", "#eb6834", "#1baf7a", "#8c8b87", "#e34948"
FAIR_BAND = V.FAIR_BAND


@st.cache_data(ttl=3600, show_spinner=False)
def get_company(ticker: str, with_peers: bool = True) -> CompanyData:
    return load_company(ticker, with_peers)


def _try_company(t: str) -> CompanyData | None:
    try:
        return get_company(t, with_peers=False)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_peers(tickers: tuple[str, ...]) -> tuple[list[CompanyData], list[str]]:
    ok, failed = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, c in zip(tickers, ex.map(_try_company, tickers)):
            (ok if c is not None else failed).append(c if c is not None else t)
    return ok, failed


def fmt_money(x: float | None, cur: str = "$") -> str:
    if x is None or not np.isfinite(x):
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(x) >= div:
            return f"{cur}{x/div:,.1f}{suf}"
    return f"{cur}{x:,.2f}"


def pct(x) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x*100:+.1f}%"


def currency_symbol(code: str) -> str:
    return "$" if code == "USD" else f"{code} "


def chart(fig: go.Figure, height: int = 380, **kwargs):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return st.plotly_chart(fig, width="stretch", theme="streamlit", **kwargs)


BASIS_OPTIONS = ["Next 12 months (blended)", "Next fiscal year"]


def basis_control() -> tuple[str, str]:
    """Forward-earnings basis radio, shared across pages via session state."""
    st.session_state.setdefault("basis_label", BASIS_OPTIONS[0])
    label = st.radio("Forward earnings basis", BASIS_OPTIONS,
                     index=BASIS_OPTIONS.index(st.session_state["basis_label"]),
                     help="NTM blends current and next fiscal year by time remaining; "
                          "it avoids jumps when the fiscal year rolls over.")
    st.session_state["basis_label"] = label
    return label, ("ntm" if label.startswith("Next 12") else "fy1")


def open_in_dashboard(ticker: str):
    st.session_state["selected_ticker"] = ticker
    st.switch_page("views/dashboard.py")
