"""Watchlist: rank every stock you follow by upside to fair value on its valuation lens."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import valuation as V
from analysis import watchlist as W
from views.common import (BLUE, FAIR_BAND, GRAY, ORANGE, RED, basis_control, chart, get_company,
                          get_peers, lens_label, load_watchlist, open_in_dashboard, pct, save_watchlist,
                          show_save_error, storage_status)


@st.cache_data(ttl=3600, show_spinner=False)
def rank_one(ticker: str, basis: str, methods: tuple[str, ...], n_peers: int,
             overrides: tuple[tuple[str, float], ...], lens: str) -> dict:
    co = get_company(ticker)
    peers, _ = get_peers(tuple(co.peers[:n_peers]))
    s = V.summarize(co, peers, basis, set(methods), dict(overrides), lens)
    for k in ("table", "by_metric"):
        s.pop(k, None)
    return s


wl = load_watchlist()
show_save_error()

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Watchlist")
    with st.form("add", clear_on_submit=True, border=False):
        new = st.text_input("Add tickers", placeholder="e.g. MSFT, GOOGL, SNOW")
        if st.form_submit_button("Add", width="stretch") and new:
            added = [t for t in (x.strip().upper() for x in new.split(",")) if t and wl.add(t)]
            if added:
                save_watchlist(wl)
                st.rerun()
    basis_label, basis = basis_control()
    st.header("Valuation lens")
    force = st.radio("Rank on", ["each", "pe", "ev_ebitda", "ps"],
                     format_func=lambda k: "Each stock's own lens" if k == "each" else f"{lens_label(k)} for all",
                     help="Each stock's own lens = the lens you saved for it, else Auto. " + V.AUTO_RULE)
    st.header("Fair multiple methods")
    st.session_state.setdefault("methods", list(V.METHOD_KEYS))
    methods = st.multiselect("Blend these", options=list(V.METHOD_KEYS), format_func=V.METHOD_KEYS.get,
                             default=st.session_state["methods"],
                             help="Applied wherever you haven't saved your own fair multiple.")
    st.session_state["methods"] = sorted(methods)
    n_peers = st.slider("Peers per stock", 3, 10, 8,
                        help="Peers come from each company's industry (up to 8 are auto-filled, the same set "
                             "the dashboard uses by default). Fewer loads faster but can shift fair values.")
    if st.button("↻ Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    with st.expander("Saving & backup"):
        where, durable = storage_status()
        st.markdown(f"Your watchlist is saved to **{where}**.")
        if not durable:
            st.info("On the **website version** a file is wiped whenever the app restarts. To keep your "
                    "watchlist there, add a GitHub token to the app's secrets (see *Saving the watchlist on the "
                    "website* in the README). Running on your own computer, the file is kept.")
        import json as _json
        st.download_button("⬇ Download a backup", data=_json.dumps(W.to_dict(wl), indent=2),
                           file_name="watchlist-backup.json", mime="application/json")
        up = st.file_uploader("Restore from a backup file", type=["json"], key="wl_restore")
        if up is not None and st.button("Replace my watchlist with this backup"):
            try:
                restored = W.from_dict(_json.loads(up.getvalue().decode("utf-8")))
            except Exception:
                st.error("That file isn't a watchlist backup.")
            else:
                restored.load_error = wl.load_error
                if save_watchlist(restored):
                    st.success(f"Restored {len(restored.tickers)} stocks.")
                st.rerun()

st.title("Watchlist")
st.caption("Every stock you follow, ranked by upside to fair value on its valuation lens "
           "(P/E, EV/EBITDA or P/S). Fair value = fair multiple × forward fundamental. "
           "Stocks use **your** fair multiple where you saved one, otherwise the blend of methods in the sidebar.")

if not wl.tickers:
    st.info("Your watchlist is empty. Add tickers in the sidebar or from the stock dashboard.")
    st.stop()
if not methods:
    st.warning("Pick at least one fair multiple method in the sidebar.")
    st.stop()

# --------------------------------------------------------------------------- #
# Load and rank (parallel, cached)
# --------------------------------------------------------------------------- #
rows, errors = [], {}
bar = st.progress(0.0, text="Valuing watchlist…")
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(rank_one, t, basis, tuple(sorted(methods)), n_peers,
                      tuple(sorted(wl.fair.get(t, {}).items())),
                      wl.get_lens(t) if force == "each" else force): t
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

# --------------------------------------------------------------------------- #
# Summary tiles and controls
# --------------------------------------------------------------------------- #
valid = df["upside"].dropna()
k = st.columns(5)
k[0].metric("Stocks", len(df))
k[1].metric("▲ Undervalued", int((valid > FAIR_BAND).sum()), help=f"Upside above +{FAIR_BAND:.0%}")
k[2].metric("▼ Overvalued", int((valid < -FAIR_BAND).sum()), help=f"Downside beyond −{FAIR_BAND:.0%}")
k[3].metric("Median upside", pct(valid.median()) if len(valid) else "—")
k[4].metric("Lens mix", " · ".join(f"{n} {l}" for l, n in df["lens_label"].value_counts().items()))

c1, c2 = st.columns([3, 2])
sort_by = c1.selectbox("Rank by", ["Upside to fair value", "Discount to peers", "Discount to own history",
                                   "Expected revenue growth", "Expected EPS growth"])
verdicts = c2.multiselect("Show", ["Undervalued", "Fair", "Overvalued", "n/a"],
                          default=["Undervalued", "Fair", "Overvalued", "n/a"])
key, asc = {"Upside to fair value": ("upside", False), "Discount to peers": ("vs_peers", True),
            "Discount to own history": ("vs_own", True), "Expected revenue growth": ("rev_growth", False),
            "Expected EPS growth": ("eps_growth", False)}[sort_by]
view = df[df["verdict"].isin(verdicts)].sort_values(key, ascending=asc, na_position="last")

# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
tab_up, tab_mult, tab_cross = st.tabs(["Upside ranking", "Current vs fair multiple", "Upside on every lens"])
plot = view.dropna(subset=["upside"]).iloc[::-1]  # reversed so the top rank is drawn at the top
ylab = [f"{t} · {l}" for t, l in zip(plot.index, plot["lens_label"])]

with tab_up:
    if plot.empty:
        st.write("Nothing to chart.")
    else:
        fig = go.Figure()
        fig.add_vrect(x0=-FAIR_BAND * 100, x1=FAIR_BAND * 100, fillcolor=GRAY, opacity=0.12, line_width=0,
                      annotation_text=f"fair ±{FAIR_BAND:.0%}", annotation_position="bottom")
        fig.add_bar(y=ylab, x=plot["upside"] * 100, orientation="h",
                    marker_color=[BLUE if u > 0 else RED for u in plot["upside"]],
                    text=[f"{u*100:+.0f}%" + (" ★" if c else "") for u, c in zip(plot["upside"], plot["custom"])],
                    textposition="outside", cliponaxis=False,
                    customdata=np.c_[plot["current"], plot["fair"], plot["price"], plot["fair_value"]],
                    hovertemplate="<b>%{y}</b>: %{x:+.1f}%<br>Multiple %{customdata[0]:.1f}x → fair %{customdata[1]:.1f}x"
                                  "<br>Price %{customdata[2]:,.2f} → fair %{customdata[3]:,.2f}<extra></extra>")
        fig.add_vline(x=0, line=dict(color=GRAY, width=1))
        fig.update_layout(title="Upside to fair value (label shows the lens; ★ = your own multiple)",
                          xaxis_title="Upside (%)", showlegend=False, hovermode="closest")
        chart(fig, max(320, 34 * len(plot) + 120))

with tab_mult:
    st.caption("The gap is the change in the multiple needed for the stock to reach fair value, assuming "
               "forward fundamentals hold. Arrow right = room for the multiple to expand. Multiples differ by lens, "
               "so compare each stock's own two dots, not across rows.")
    d = plot.dropna(subset=["current", "fair"])
    dl = [f"{t} · {l}" for t, l in zip(d.index, d["lens_label"])]
    if d.empty:
        st.write("Nothing to chart.")
    else:
        fig = go.Figure()
        for y, (_, r) in zip(dl, d.iterrows()):
            fig.add_scatter(x=[r["current"], r["fair"]], y=[y, y], mode="lines", showlegend=False,
                            line=dict(color=BLUE if r["fair"] > r["current"] else RED, width=2), hoverinfo="skip")
        fig.add_scatter(x=d["current"], y=dl, mode="markers", name="Current multiple",
                        marker=dict(size=11, color=GRAY, line=dict(color="white", width=2)),
                        hovertemplate="%{y}: now %{x:.1f}x<extra></extra>")
        fig.add_scatter(x=d["fair"], y=dl, mode="markers", name="Fair multiple",
                        marker=dict(size=11, color=ORANGE, line=dict(color="white", width=2)),
                        hovertemplate="%{y}: fair %{x:.1f}x<extra></extra>")
        fig.update_layout(xaxis_title="Forward multiple (x)", hovermode="closest")
        chart(fig, max(320, 34 * len(d) + 120))

with tab_cross:
    st.caption("Upside on each lens side by side. When P/E, EV/EBITDA and P/S agree, the signal is stronger; "
               "blank = that lens isn't meaningful for the company.")
    cross = view[[f"upside_{m}" for m in V.METRICS]] * 100
    cross.columns = [V.METRICS[m].short for m in V.METRICS]
    lim = float(np.nanmax(np.abs(cross.values))) if cross.notna().any().any() else 1.0
    hm = go.Figure(go.Heatmap(
        z=cross.values, x=list(cross.columns), y=list(cross.index), zmin=-lim, zmax=lim,
        colorscale=[[0, RED], [0.5, "#f0efec"], [1, BLUE]], xgap=2, ygap=2,
        text=[[("" if v != v else f"{v:+.0f}%") for v in row] for row in cross.values], texttemplate="%{text}",
        hovertemplate="%{y} on %{x}: %{text}<extra></extra>", colorbar=dict(title="Upside %")))
    hm.update_layout(yaxis=dict(autorange="reversed", type="category"), xaxis_type="category",
                     hovermode="closest")
    chart(hm, max(300, 32 * len(cross) + 100))

# --------------------------------------------------------------------------- #
# Ranking table
# --------------------------------------------------------------------------- #
st.subheader("Ranking")
show = pd.DataFrame({
    "Name": view["name"],
    "Lens": view["lens_label"],
    "Verdict": view["verdict"].map({"Undervalued": "▲ Undervalued", "Overvalued": "▼ Overvalued",
                                    "Fair": "● Fair", "n/a": "n/a"}),
    "Upside %": view["upside"] * 100,
    "Price": view["price"],
    "Fair value": view["fair_value"],
    "Multiple": view["current"],
    "Fair multiple": view["fair"],
    "Source": np.where(view["custom"], "Mine", "Model"),
    "vs peers %": view["vs_peers"] * 100,
    "vs own 5y %": view["vs_own"] * 100,
    "Rev growth %": view["rev_growth"] * 100,
    "EPS growth %": view["eps_growth"] * 100,
    "Note": view["note"],
})
num = lambda f: st.column_config.NumberColumn(format=f)
event = st.dataframe(
    show, width="stretch", on_select="rerun", selection_mode="single-row", key="wl_table",
    column_config={"Upside %": num("%+.1f%%"), "Price": num("%.2f"), "Fair value": num("%.2f"),
                   "Multiple": num("%.1fx"), "Fair multiple": num("%.1fx"), "vs peers %": num("%+.0f%%"),
                   "vs own 5y %": num("%+.0f%%"), "EPS growth %": num("%+.1f%%"), "Rev growth %": num("%+.1f%%")})
st.caption("Multiple = the stock's forward multiple on its lens. vs peers / vs own 5y = how far it sits above (+) "
           "or below (−) the peer median and its own average. Select a row to open it.")
sel = event.selection.rows if event and event.selection else []
if sel:
    t = show.index[sel[0]]
    if st.button(f"Open {t} in the dashboard →", type="primary"):
        open_in_dashboard(t)

# --------------------------------------------------------------------------- #
# Edit watchlist
# --------------------------------------------------------------------------- #
with st.expander("Edit watchlist: lens, your fair multiples, notes, remove"):
    st.caption("Leave a multiple blank to use the model blend. Lens 'auto' follows the rule: " + V.AUTO_RULE)
    ed = pd.DataFrame({"Ticker": wl.tickers,
                       "Lens": [wl.get_lens(t) for t in wl.tickers],
                       **{f"My {V.METRICS[m].short}": [wl.get_fair(t, m) for t in wl.tickers] for m in V.METRICS},
                       "Note": [wl.notes.get(t, "") for t in wl.tickers],
                       "Remove": False})
    mcol = lambda: st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1fx")
    out = st.data_editor(ed, hide_index=True, width="stretch", key="wl_edit",
                         column_config={"Ticker": st.column_config.TextColumn(disabled=True),
                                        "Lens": st.column_config.SelectboxColumn(options=list(W.LENSES), required=True),
                                        **{f"My {V.METRICS[m].short}": mcol() for m in V.METRICS},
                                        "Remove": st.column_config.CheckboxColumn()})
    if st.button("Save changes"):
        for _, r in out.iterrows():
            t = r["Ticker"]
            if r["Remove"]:
                wl.remove(t)
                continue
            wl.set_lens(t, r["Lens"])
            for m in V.METRICS:
                v = r[f"My {V.METRICS[m].short}"]
                wl.set_fair(t, m, None if pd.isna(v) else float(v))
            wl.set_note(t, r["Note"] if isinstance(r["Note"], str) else "")
        save_watchlist(wl)
        st.rerun()
