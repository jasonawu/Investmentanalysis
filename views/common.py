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
    sign, x = ("−" if x < 0 else ""), abs(x)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if x >= div:
            return f"{sign}{cur}{x/div:,.1f}{suf}"
    return f"{sign}{cur}{x:,.2f}"


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


def lens_label(key: str) -> str:
    return "Auto" if key == "auto" else V.METRICS[key].short


def metric_value_fmt(v: float | None, m: "V.Metric", cur: str = "$") -> str:
    """Format a forward fundamental: EPS per share, EBITDA/revenue as totals."""
    if v is None or not np.isfinite(v):
        return "—"
    return (f"−{cur}{-v:,.2f}" if v < 0 else f"{cur}{v:,.2f}") if m.per_share else fmt_money(v, cur)


def as_text(df, fmts: dict[str, str], na: str = "—"):
    """Format numeric columns as text so empty values show as a dash (Streamlit renders NaN as 'None')."""
    out = df.copy()
    for col, f in fmts.items():
        if col in out:
            out[col] = [na if (v is None or (isinstance(v, float) and not np.isfinite(v))) else f.format(v)
                        for v in out[col]]
    return out


# --------------------------------------------------------------------------- #
# Watchlist storage (file locally; GitHub gist when a token is configured)
# --------------------------------------------------------------------------- #
SECRET_NAMES = ("WATCHLIST_GITHUB_TOKEN", "FMP_API_KEY", "FMP_PLAN")


def bootstrap_secrets() -> None:
    """Copy keys from Streamlit secrets (website version) into the environment, where the data code reads them."""
    import os
    for name in SECRET_NAMES:
        if os.environ.get(name):
            continue
        try:
            val = st.secrets.get(name)
        except Exception:  # no secrets configured
            val = None
        if val:
            os.environ[name] = str(val)


_bootstrap_secrets = bootstrap_secrets


def data_source_caption(co) -> str:
    """One line saying where the numbers came from."""
    from analysis import fmp
    if co.is_demo:
        return ""
    by_src: dict[str, list[str]] = {}
    for kind in ("financials", "estimates", "prices", "peers"):
        if kind in co.sources:
            by_src.setdefault(co.sources[kind], []).append(kind)
    parts = [f"{src} ({', '.join(kinds)})" for src, kinds in by_src.items()]
    line = "Data: " + " · ".join(parts) if parts else ""
    if fmp.enabled():
        line += f" · FMP requests since the app started today: {fmp.calls_today()}"
        if fmp.plan() == "free":
            line += " of 250/day (repeat views are cached)"
    if co.sources.get("note"):
        line += f" · ⚠ {co.sources['note']}"
    return line


def load_watchlist():
    from analysis import watchlist as W
    _bootstrap_secrets()
    wl = W.load()
    if wl.load_error:
        st.error(f"⚠ Couldn't load your saved watchlist, so changes won't be saved for now. {wl.load_error}")
    return wl


def save_watchlist(wl) -> bool:
    from analysis import watchlist as W
    try:
        W.save(wl)
        return True
    except W.WatchlistSaveError as e:
        st.session_state["wl_save_error"] = str(e)
        return False


def show_save_error() -> None:
    err = st.session_state.pop("wl_save_error", None)
    if err:
        st.error(f"⚠ {err}")


def storage_status() -> tuple[str, bool]:
    from analysis import watchlist as W
    _bootstrap_secrets()
    s = W.storage()
    return s.where, s.persistent_on_web
