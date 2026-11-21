"""Watchlist: rank every stock you follow by upside to its fair forward-P/E value."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import valuation as V
from analysis import watchlist as W
from views.common import (BLUE, FAIR_BAND, GRAY, ORANGE, RED, basis_control, chart, get_company,
                          get_peers, open_in_dashboard, pct)


@st.cache_data(ttl=3600, show_spinner=False)
def rank_one(ticker: str, basis: str, methods: tuple[str, ...], n_peers: int,
             override: float | None) -> dict:
    co = get_company(ticker)
    peers, _ = get_peers(tuple(co.peers[:n_peers]))
    s = V.summarize(co, peers, basis, set(methods), override)
    s.pop("multiples", None)
    return s


wl = W.load()

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Watchlist")
    with st.form("add", clear_on_submit=True, border=False):
        new = st.text_input("Add tickers", placeholder="e.g. MSFT, GOOGL, AMZN")
        if st.form_submit_button("Add", width="stretch") and new:
            added = [t for t in (x.strip().upper() for x in new.split(",")) if t and wl.add(t)]
            if added:
                W.save(wl)
                st.rerun()
    basis_label, basis = basis_control()
    st.header("Fair P/E methods")
    st.session_state.setdefault("wl_methods", list(V.METHOD_KEYS))
    methods = st.multiselect("Blend these", options=list(V.METHOD_KEYS), format_func=V.METHOD_KEYS.get,
                             default=st.session_state["wl_methods"],
                             help="Applied to every stock without its own saved fair P/E.")
    st.session_state["wl_methods"] = methods
    n_peers = st.slider("Peers per stock", 3, 10, 6,
                        help="Peers come from each company's industry. Fewer loads faster.")
    if st.button("↻ Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

st.title("Watchlist")
st.caption("Every stock you follow, ranked by upside to fair value. "
           "Fair value = fair forward P/E × forward EPS. A stock uses **your** fair P/E if you saved one, "
           "otherwise the blend of the methods in the sidebar.")

if not wl.tickers:
    st.info("Your watchlist is empty. Add tickers in the sidebar or from the stock dashboard.")
    st.stop()
if not methods:
    st.warning("Pick at least one fair P/E method in the sidebar.")
    st.stop()

# --------------------------------------------------------------------------- #
# Load and rank (parallel, cached)
# --------------------------------------------------------------------------- #
rows, errors = [], {}
bar = st.progress(0.0, text="Valuing watchlist…")
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(rank_one, t, basis, tuple(sorted(methods)), n_peers, wl.fair_pe.get(t)): t
            for t in wl.tickers}
    for i, f in enumerate(as_completed(futs), 1):
        t = futs[f]
        try:
            rows.append(f.result())
        except Exception as e:
            errors[t] = str(e)
        bar.progress(i / len(futs), text=f"Valuing watchlist… {i}/{len(futs)}")
bar.empty()
if errors:
    st.warning("Could not value: " + ", ".join(f"**{t}** ({e[:60]})" for t, e in errors.items()))
if not rows:
    st.stop()

df = pd.DataFrame(rows).set_index("ticker")
df["note"] = [wl.notes.get(t, "") for t in df.index]
ranked = df.sort_values("upside", ascending=False, na_position="last")

# --------------------------------------------------------------------------- #
# Summary tiles
# --------------------------------------------------------------------------- #
valid = ranked["upside"].dropna()
k = st.columns(4)
k[0].metric("Stocks", len(ranked))
k[1].metric("▲ Undervalued", int((valid > FAIR_BAND).sum()), help=f"Upside above +{FAIR_BAND:.0%}")
k[2].metric("▼ Overvalued", int((valid < -FAIR_BAND).sum()), help=f"Downside beyond −{FAIR_BAND:.0%}")
k[3].metric("Median upside", pct(valid.median()) if len(valid) else "—")

c1, c2 = st.columns([3, 2])
sort_by = c1.selectbox("Rank by", ["Upside to fair value", "Discount to peers", "Discount to own history",
                                   "Expected EPS growth"])
verdicts = c2.multiselect("Show", ["Undervalued", "Fair", "Overvalued", "n/a"],
                          default=["Undervalued", "Fair", "Overvalued", "n/a"])
key, asc = {"Upside to fair value": ("upside", False), "Discount to peers": ("vs_peers", True),
            "Discount to own history": ("vs_own_avg", True), "Expected EPS growth": ("eps_growth", False)}[sort_by]
view = df[df["verdict"].isin(verdicts)].sort_values(key, ascending=asc, na_position="last")

# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
tab_up, tab_pe = st.tabs(["Upside ranking", "Current vs fair P/E"])
plot = view.dropna(subset=["upside"]).iloc[::-1]  # reversed so the top rank is drawn at the top

with tab_up:
    if plot.empty:
        st.write("Nothing to chart.")
    else:
        fig = go.Figure()
        fig.add_vrect(x0=-FAIR_BAND * 100, x1=FAIR_BAND * 100, fillcolor=GRAY, opacity=0.12, line_width=0,
                      annotation_text=f"fair ±{FAIR_BAND:.0%}", annotation_position="bottom")
        fig.add_bar(y=plot.index, x=plot["upside"] * 100, orientation="h",
                    marker_color=[BLUE if u > 0 else RED for u in plot["upside"]],
                    text=[f"{u*100:+.0f}%" + (" ★" if c else "") for u, c in zip(plot["upside"], plot["custom_pe"])],
                    textposition="outside", cliponaxis=False,
                    customdata=np.c_[plot["fwd_pe"], plot["fair_pe"], plot["price"], plot["fair_value"]],
                    hovertemplate="<b>%{y}</b>: %{x:+.1f}%<br>P/E %{customdata[0]:.1f}x → fair %{customdata[1]:.1f}x"
                                  "<br>Price %{customdata[2]:,.2f} → fair %{customdata[3]:,.2f}<extra></extra>")
        fig.add_vline(x=0, line=dict(color=GRAY, width=1))
        fig.update_layout(title="Upside to fair value (★ = your own fair P/E)", xaxis_title="Upside (%)",
                          showlegend=False, hovermode="closest")
        chart(fig, max(320, 34 * len(plot) + 120))

with tab_pe:
    st.caption("The gap is the multiple change needed for the stock to reach fair value "
               "(assuming forward EPS holds). Arrow right = room for multiple expansion.")
    d = plot.dropna(subset=["fwd_pe", "fair_pe"])
    if d.empty:
        st.write("Nothing to chart.")
    else:
        fig = go.Figure()
        for t, r in d.iterrows():
            fig.add_scatter(x=[r["fwd_pe"], r["fair_pe"]], y=[t, t], mode="lines", showlegend=False,
                            line=dict(color=BLUE if r["fair_pe"] > r["fwd_pe"] else RED, width=2),
                            hoverinfo="skip")
        fig.add_scatter(x=d["fwd_pe"], y=d.index, mode="markers", name="Current forward P/E",
                        marker=dict(size=11, color=GRAY, line=dict(color="white", width=2)),
                        hovertemplate="%{y}: now %{x:.1f}x<extra></extra>")
        fig.add_scatter(x=d["fair_pe"], y=d.index, mode="markers", name="Fair P/E",
                        marker=dict(size=11, color=ORANGE, line=dict(color="white", width=2)),
                        hovertemplate="%{y}: fair %{x:.1f}x<extra></extra>")
        fig.update_layout(xaxis_title="Forward P/E (x)", hovermode="closest")
        chart(fig, max(320, 34 * len(d) + 120))

# --------------------------------------------------------------------------- #
# Ranking table
# --------------------------------------------------------------------------- #
st.subheader("Ranking")
show = pd.DataFrame({
    "Name": view["name"],
    "Verdict": view["verdict"].map({"Undervalued": "▲ Undervalued", "Overvalued": "▼ Overvalued",
                                    "Fair": "● Fair", "n/a": "n/a"}),
    "Upside %": view["upside"] * 100,
    "Price": view["price"],
    "Fair value": view["fair_value"],
    "Fwd P/E": view["fwd_pe"],
    "Fair P/E": view["fair_pe"],
    "P/E source": np.where(view["custom_pe"], "Mine", "Model"),
    "vs peers %": view["vs_peers"] * 100,
    "vs own 5y %": view["vs_own_avg"] * 100,
    "EPS growth %": view["eps_growth"] * 100,
    "Rev growth %": view["rev_growth"] * 100,
    "Note": view["note"],
})
num = lambda f: st.column_config.NumberColumn(format=f)
event = st.dataframe(
    show, width="stretch", on_select="rerun", selection_mode="single-row", key="wl_table",
    column_config={"Upside %": num("%+.1f%%"), "Price": num("%.2f"), "Fair value": num("%.2f"),
                   "Fwd P/E": num("%.1fx"), "Fair P/E": num("%.1fx"), "vs peers %": num("%+.0f%%"),
                   "vs own 5y %": num("%+.0f%%"), "EPS growth %": num("%+.1f%%"), "Rev growth %": num("%+.1f%%")})
st.caption("vs peers / vs own 5y = how far today's forward P/E sits above (+) or below (−) the peer median "
           "and the stock's own average. Select a row to open it.")
sel = event.selection.rows if event and event.selection else []
if sel:
    t = show.index[sel[0]]
    if st.button(f"Open {t} in the dashboard →", type="primary"):
        open_in_dashboard(t)

# --------------------------------------------------------------------------- #
# Edit watchlist
# --------------------------------------------------------------------------- #
with st.expander("Edit watchlist: your fair P/E, notes, remove"):
    st.caption("Leave **My fair P/E** blank to use the model blend.")
    ed = pd.DataFrame({"Ticker": wl.tickers,
                       "My fair P/E": [wl.fair_pe.get(t) for t in wl.tickers],
                       "Model P/E": [df["model_pe"].get(t) if t in df.index else None for t in wl.tickers],
                       "Note": [wl.notes.get(t, "") for t in wl.tickers],
                       "Remove": False})
    out = st.data_editor(ed, hide_index=True, width="stretch", key="wl_edit",
                         column_config={"Ticker": st.column_config.TextColumn(disabled=True),
                                        "Model P/E": st.column_config.NumberColumn(format="%.1fx", disabled=True),
                                        "My fair P/E": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1fx"),
                                        "Remove": st.column_config.CheckboxColumn()})
    if st.button("Save changes"):
        for _, r in out.iterrows():
            if r["Remove"]:
                wl.remove(r["Ticker"])
                continue
            pe = r["My fair P/E"]
            wl.set_fair_pe(r["Ticker"], None if pd.isna(pe) else float(pe))
            wl.set_note(r["Ticker"], r["Note"] if isinstance(r["Note"], str) else "")
        W.save(wl)
        st.rerun()
