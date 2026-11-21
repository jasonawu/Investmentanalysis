"""Single-stock dashboard: price, fundamentals, forward P/E history, peers, price target."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from analysis import valuation as V
from analysis import watchlist as W
from analysis.data import demo_tickers
from analysis.models import FUNDAMENTALS, LABELS
from views.common import (AQUA, BLUE, FAIR_BAND, GRAY, ORANGE, RED, basis_control, chart,
                          fmt_money, get_company, get_peers, pct)

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
wl = W.load()
with st.sidebar:
    st.header("Stock")
    ticker = st.text_input("Ticker", value=st.session_state.get("selected_ticker", "DEMO"),
                           help="Any Yahoo Finance ticker (e.g. MSFT). "
                                "Tickers starting with DEMO use offline sample data.").strip().upper()
    st.session_state["selected_ticker"] = ticker
    basis_label, basis = basis_control()
    st.caption("Demo tickers: " + ", ".join(demo_tickers()))

if not ticker:
    st.stop()

with st.spinner(f"Loading {ticker}…"):
    try:
        co = get_company(ticker)
    except Exception as e:  # network or bad ticker
        st.error(f"Could not load **{ticker}**: {e}")
        st.stop()

with st.sidebar:
    st.header("Peers")
    peer_text = st.text_area("Comparable companies (comma-separated)", value=", ".join(co.peers),
                             help="Auto-filled from the company's industry. Edit to refine the peer set.")
    peer_list = tuple(dict.fromkeys(p.strip().upper() for p in peer_text.split(",") if p.strip()))

with st.spinner("Loading peers…"):
    peers, failed = get_peers(peer_list)
if failed:
    st.sidebar.warning("Could not load: " + ", ".join(failed))

cur = "$" if co.currency == "USD" else f"{co.currency} "
hist = V.forward_pe_history(co, basis=basis)
fwd_eps = V.current_forward_eps(co, basis)
table = V.peer_table(co, peers, basis)
multiples = V.fair_multiples(table, hist, co.ticker)

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title(f"{co.name} ({co.ticker})")
st.caption(" · ".join(x for x in [co.sector, co.industry, f"Market cap {fmt_money(co.market_cap, cur)}",
                                   f"{co.estimates.analysts} analysts" if co.estimates.analysts else ""] if x))
if co.is_demo:
    st.info("Showing **synthetic demo data** (fictional companies). Enter a real ticker to pull live data.")

# Fair-multiple controls live in the sidebar so the headline reflects them.
with st.sidebar:
    st.header("Fair multiple")
    use = {m.method: st.checkbox(f"{m.method}" + (f" ({m.pe:.1f}x)" if m.pe else " (n/a)"),
                                 value=m.pe is not None, disabled=m.pe is None) for m in multiples}
    blended = V.blend([m for m in multiples if use.get(m.method)])
    saved_pe = wl.fair_pe.get(co.ticker)
    override = st.checkbox("Override with my own P/E", value=saved_pe is not None, key=f"ovr_{co.ticker}")
    fair_pe = st.number_input("My fair forward P/E", value=float(round(saved_pe or blended or 20.0, 1)),
                              step=0.5, key=f"mype_{co.ticker}") if override else blended

    st.header("Watchlist")
    if co.ticker in wl.tickers:
        st.caption(f"✓ {co.ticker} is on your watchlist"
                   + (f" (your fair P/E {saved_pe:.1f}x)" if saved_pe else ""))
        b1, b2 = st.columns(2)
        if b1.button("Save my P/E", disabled=not override, help="The watchlist will rank this stock using your P/E"):
            wl.set_fair_pe(co.ticker, fair_pe); W.save(wl); st.rerun()
        if b2.button("Remove"):
            wl.remove(co.ticker); W.save(wl); st.rerun()
    elif st.button(f"☆ Add {co.ticker} to watchlist", width="stretch"):
        wl.add(co.ticker)
        if override:
            wl.set_fair_pe(co.ticker, fair_pe)
        W.save(wl); st.rerun()

cur_pe = co.price / fwd_eps if (co.price and fwd_eps and fwd_eps > 0) else None
fair_value = fair_pe * fwd_eps if (fair_pe and fwd_eps) else None
upside = fair_value / co.price - 1 if (fair_value and co.price) else None

k = st.columns(6)
k[0].metric("Price", f"{cur}{co.price:,.2f}" if co.price else "—")
k[1].metric("Forward EPS", f"{cur}{fwd_eps:,.2f}" if fwd_eps else "—", help=basis_label)
k[2].metric("Forward P/E", f"{cur_pe:.1f}x" if cur_pe else "—")
k[3].metric("Fair P/E", f"{fair_pe:.1f}x" if fair_pe else "—",
            delta=f"{(fair_pe/cur_pe-1)*100:+.0f}% vs current" if (fair_pe and cur_pe) else None)
k[4].metric("Fair value today", f"{cur}{fair_value:,.2f}" if fair_value else "—")
k[5].metric("Upside / downside", pct(upside))

if upside is not None:
    if upside > FAIR_BAND:
        st.success(f"▲ **Looks undervalued** — trades at {cur_pe:.1f}x vs a fair {fair_pe:.1f}x forward earnings.")
    elif upside < -FAIR_BAND:
        st.error(f"▼ **Looks overvalued** — trades at {cur_pe:.1f}x vs a fair {fair_pe:.1f}x forward earnings.")
    else:
        st.warning(f"● **Roughly fairly priced** — within ±{FAIR_BAND:.0%} of fair value at {fair_pe:.1f}x.")

tabs = st.tabs(["① Price", "② Fundamentals vs price", "③ Forward P/E history",
                "④ Peer valuation", "⑤ Price target"])

# --------------------------------------------------------------------------- #
# 1. Price chart
# --------------------------------------------------------------------------- #
with tabs[0]:
    tf = st.radio("Timeframe", ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "Max"],
                  index=4, horizontal=True, label_visibility="collapsed")
    px = co.prices
    if len(px):
        end = px.index.max()
        start = {"1M": end - pd.DateOffset(months=1), "3M": end - pd.DateOffset(months=3),
                 "6M": end - pd.DateOffset(months=6), "YTD": pd.Timestamp(year=end.year, month=1, day=1),
                 "1Y": end - pd.DateOffset(years=1), "3Y": end - pd.DateOffset(years=3),
                 "5Y": end - pd.DateOffset(years=5), "10Y": end - pd.DateOffset(years=10),
                 "Max": px.index.min()}[tf]
        s = px[px.index >= start]
        chg = s.iloc[-1] / s.iloc[0] - 1
        fig = go.Figure(go.Scatter(x=s.index, y=s, mode="lines", line=dict(color=BLUE, width=2),
                                   name="Close", hovertemplate=f"{cur}%{{y:,.2f}}<extra></extra>"))
        if len(s) > 50:
            ma = px.rolling(50).mean().reindex(s.index)
            fig.add_scatter(x=ma.index, y=ma, mode="lines", name="50-day avg",
                            line=dict(color=GRAY, width=1.5, dash="dot"))
        fig.update_layout(title=f"{co.ticker} share price · {tf} {chg*100:+.1f}%", yaxis_title=co.currency)
        chart(fig, 420)
    else:
        st.write("No price history available.")

# --------------------------------------------------------------------------- #
# 2. Fundamentals vs price
# --------------------------------------------------------------------------- #
with tabs[1]:
    c1, c2 = st.columns([1, 1])
    freq = c1.radio("Period", ["Annual", "Quarterly (TTM)"], horizontal=True)
    show_est = c2.checkbox("Include consensus estimates", value=True)
    if freq == "Annual":
        f = co.annual.copy()
    else:
        q = co.quarterly.sort_index()
        f = q.rolling(4).sum().dropna(how="all") if len(q) >= 4 else q
    est_rows = {}
    if show_est and freq == "Annual" and co.estimates.fy0_end is not None:
        e = co.estimates
        est_rows = {e.fy0_end: {"revenue": e.revenue_fy0, "eps": e.eps_fy0},
                    e.fy0_end + pd.DateOffset(years=1): {"revenue": e.revenue_fy1, "eps": e.eps_fy1}}

    if f.empty:
        st.write("No financial statements available.")
    else:
        st.caption("Each panel shares the time axis with the share price above it, so you can see "
                   "whether the stock followed the fundamentals. Orange bars are analyst estimates.")
        fig = make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                            row_heights=[0.28, 0.18, 0.18, 0.18, 0.18],
                            subplot_titles=["Share price"] + [LABELS[m] for m in FUNDAMENTALS])
        lo = f.index.min() - pd.DateOffset(months=12)
        p = co.prices[co.prices.index >= lo]
        fig.add_scatter(x=p.index, y=p, row=1, col=1, line=dict(color=BLUE, width=2), name="Price",
                        hovertemplate=f"{cur}%{{y:,.2f}}")
        width = 1000 * 3600 * 24 * (250 if freq == "Annual" else 70)
        for i, m in enumerate(FUNDAMENTALS, start=2):
            scale = 1 if m == "eps" else 1e9
            unit = cur if m == "eps" else f"{cur}B "
            fig.add_bar(x=f.index, y=f[m] / scale, row=i, col=1, marker_color=BLUE, width=width,
                        name="Reported", showlegend=(i == 2), legendgroup="rep",
                        hovertemplate=f"{LABELS[m]}: {unit}%{{y:,.2f}}")
            ex = [(d, v[m]) for d, v in est_rows.items() if v.get(m) is not None]
            if ex:
                fig.add_bar(x=[d for d, _ in ex], y=[v / scale for _, v in ex], row=i, col=1,
                            marker_color=ORANGE, width=width, name="Consensus estimate",
                            showlegend=(i == 2), legendgroup="est",
                            hovertemplate=f"{LABELS[m]} est: {unit}%{{y:,.2f}}")
        fig.update_layout(bargap=0.15)
        chart(fig, 900)

        st.subheader("Indexed growth (start = 100)")
        st.caption("Price vs. EPS and revenue on one scale. When price outruns EPS the multiple expanded; "
                   "when it lags, the multiple contracted.")
        base = f.dropna(subset=["eps"])
        if len(base) >= 2 and base["eps"].iloc[0] > 0:
            ix = go.Figure()
            p_at = co.prices.reindex(base.index, method="ffill")
            for name, ser, col in [("Price", p_at, BLUE), ("EPS", base["eps"], ORANGE),
                                   ("Revenue", base["revenue"], AQUA)]:
                ser = ser.dropna()
                if len(ser) and ser.iloc[0] > 0:
                    ix.add_scatter(x=ser.index, y=ser / ser.iloc[0] * 100, name=name, mode="lines+markers",
                                   line=dict(color=col, width=2), marker=dict(size=8))
            ix.add_hline(y=100, line=dict(color=GRAY, width=1, dash="dot"))
            chart(ix, 360)

        g = f.pct_change().iloc[1:] * 100
        tbl = pd.concat({"Value": f.assign(revenue=f.revenue / 1e9, ebitda=f.ebitda / 1e9, ebit=f.ebit / 1e9),
                         "YoY %": g}, axis=1)
        tbl.index = tbl.index.strftime("%Y-%m")
        st.dataframe(tbl.T.round(2), width="stretch")
        st.caption("Revenue / EBITDA / EBIT in billions.")

# --------------------------------------------------------------------------- #
# 3. Forward P/E history
# --------------------------------------------------------------------------- #
with tabs[2]:
    st.caption("Forward P/E = price ÷ forward EPS. For past dates we use the earnings the company *actually "
               "reported* for the following 12 months (historical consensus isn't available free); the most "
               "recent points use today's consensus.")
    h = hist.dropna()
    if h.empty:
        st.write("Not enough earnings history to build a forward P/E series.")
    else:
        mu, sd = h["fwd_pe"].mean(), h["fwd_pe"].std()
        fig = go.Figure()
        fig.add_hrect(y0=mu - sd, y1=mu + sd, fillcolor=GRAY, opacity=0.12, line_width=0)
        fig.add_hline(y=mu, line=dict(color=GRAY, dash="dash", width=1.5),
                      annotation_text=f"avg {mu:.1f}x", annotation_position="top left")
        fig.add_scatter(x=h.index, y=h["fwd_pe"], mode="lines", line=dict(color=BLUE, width=2),
                        name="Forward P/E", hovertemplate="%{y:.1f}x")
        if fair_pe:
            fig.add_hline(y=fair_pe, line=dict(color=ORANGE, width=2),
                          annotation_text=f"fair {fair_pe:.1f}x", annotation_position="bottom right")
        fig.update_layout(title=f"Forward P/E · now {h['fwd_pe'].iloc[-1]:.1f}x · band = ±1σ ({mu-sd:.1f}x–{mu+sd:.1f}x)",
                          yaxis_title="x forward EPS")
        chart(fig, 400)

        st.subheader("What drove the stock: earnings vs. multiple")
        yrs = st.select_slider("Look-back", options=[1, 2, 3, 5, 10], value=3, format_func=lambda y: f"{y}y")
        a = h[h.index >= h.index.max() - pd.DateOffset(years=yrs)]
        if len(a) >= 2:
            r_tot = a["price"].iloc[-1] / a["price"].iloc[0] - 1
            r_eps = a["fwd_eps"].iloc[-1] / a["fwd_eps"].iloc[0] - 1
            r_pe = a["fwd_pe"].iloc[-1] / a["fwd_pe"].iloc[0] - 1
            m = st.columns(3)
            m[0].metric("Price change", pct(r_tot))
            m[1].metric("Forward EPS growth", pct(r_eps))
            m[2].metric("Multiple change", pct(r_pe),
                        help=f"{a['fwd_pe'].iloc[0]:.1f}x → {a['fwd_pe'].iloc[-1]:.1f}x")
            st.caption("(1 + price change) = (1 + EPS growth) × (1 + multiple change)")

# --------------------------------------------------------------------------- #
# 4. Peer valuation
# --------------------------------------------------------------------------- #
with tabs[3]:
    if len(table) <= 1:
        st.write("No peers loaded. Add tickers in the sidebar.")
    else:
        t = table.sort_values("fwd_pe")
        med = t.loc[~t["is_target"], "fwd_pe"].median()
        fig = go.Figure(go.Bar(
            y=t.index, x=t["fwd_pe"], orientation="h",
            marker_color=[BLUE if x else GRAY for x in t["is_target"]],
            text=[f"{v:.1f}x" if v == v else "n/m" for v in t["fwd_pe"]], textposition="outside",
            hovertemplate="%{y}: %{x:.1f}x<extra></extra>"))
        fig.add_vline(x=med, line=dict(color=ORANGE, dash="dash", width=2),
                      annotation_text=f"peer median {med:.1f}x", annotation_position="bottom right")
        fig.update_layout(title="Forward P/E vs peers", xaxis_title="x forward EPS", showlegend=False,
                          hovermode="closest")
        chart(fig, max(300, 40 * len(t)))

        st.subheader("Is the premium justified by growth?")
        d = table.dropna(subset=["fwd_pe", "eps_growth"])
        sc = go.Figure()
        for is_t, col, nm in [(False, GRAY, "Peers"), (True, BLUE, co.ticker)]:
            dd = d[d["is_target"] == is_t]
            sc.add_scatter(x=dd["eps_growth"] * 100, y=dd["fwd_pe"], mode="markers+text", name=nm,
                           text=dd.index, textposition="top center",
                           marker=dict(size=14 if is_t else 11, color=col, line=dict(color="white", width=2)),
                           hovertemplate="%{text}: growth %{x:.1f}%, P/E %{y:.1f}x<extra></extra>")
        reg = V.pe_growth_regression(d[~d["is_target"]])
        if reg:
            slope, icpt, r2 = reg
            xs = np.linspace(d["eps_growth"].min(), d["eps_growth"].max(), 20)
            sc.add_scatter(x=xs * 100, y=icpt + slope * xs, mode="lines", name=f"Peer fit (R² {r2:.2f})",
                           line=dict(color=ORANGE, width=2, dash="dash"))
        sc.update_layout(xaxis_title="Consensus EPS growth, next FY (%)", yaxis_title="Forward P/E",
                         hovermode="closest")
        chart(sc, 420)
        st.caption("Above the line = priced richer than its growth implies; below = cheaper.")

        show = table.drop(columns=["is_target"]).copy()
        show["market_cap"] = show["market_cap"] / 1e9
        for c in ["eps_growth", "rev_growth", "op_margin"]:
            show[c] = show[c] * 100
        st.dataframe(
            show.rename(columns={"name": "Name", "market_cap": "Mkt cap ($B)", "price": "Price",
                                 "fwd_eps": "Fwd EPS", "fwd_pe": "Fwd P/E", "eps_growth": "EPS growth %",
                                 "rev_growth": "Rev growth %", "op_margin": "Op margin %",
                                 "ev_ebitda": "EV/EBITDA", "peg": "PEG"}).round(2),
            width="stretch")

    st.subheader("Fair multiple estimates")
    st.dataframe(pd.DataFrame([{"Method": m.method, "Fair P/E": round(m.pe, 1) if m.pe else None,
                                "Basis": m.note, "Used": use.get(m.method, False)} for m in multiples]),
                 width="stretch", hide_index=True)
    st.caption("Toggle methods or override the fair P/E in the sidebar.")

# --------------------------------------------------------------------------- #
# 5. Price target
# --------------------------------------------------------------------------- #
with tabs[4]:
    if not (fwd_eps and co.price and cur_pe):
        st.write("Needs positive forward EPS to build a price target.")
    else:
        g0 = V.forward_eps_growth(co) or 0.08
        st.caption("12-month target = forward EPS × (1 + EPS growth) × exit P/E. Edit the scenarios.")
        default = pd.DataFrame([
            {"Scenario": "Bear", "EPS growth %": round(g0 * 100 - 10, 1), "Exit P/E": round(min(cur_pe, fair_pe or cur_pe) * 0.85, 1)},
            {"Scenario": "Base", "EPS growth %": round(g0 * 100, 1), "Exit P/E": round(fair_pe or cur_pe, 1)},
            {"Scenario": "Bull", "EPS growth %": round(g0 * 100 + 8, 1), "Exit P/E": round(max(cur_pe, fair_pe or cur_pe) * 1.1, 1)},
        ])
        sc_df = st.data_editor(default, hide_index=True, width="stretch", key=f"sc_{co.ticker}",
                               column_config={"Scenario": st.column_config.TextColumn(disabled=True)})
        rows = []
        for _, r in sc_df.iterrows():
            s = V.Scenario(r["Scenario"], r["EPS growth %"] / 100, r["Exit P/E"])
            d = V.decompose(co.price, fwd_eps, s)
            rows.append({**d, "Scenario": s.name})
        res = pd.DataFrame(rows).set_index("Scenario")

        cols = st.columns(len(res))
        for c, (nm, r) in zip(cols, res.iterrows()):
            c.metric(f"{nm} target", f"{cur}{r['target']:,.2f}", pct(r["total_return"]))

        base = res.loc["Base"] if "Base" in res.index else res.iloc[0]
        wf = go.Figure(go.Waterfall(
            orientation="v", measure=["absolute", "relative", "relative", "total"],
            x=["Price today", "Earnings growth", "Multiple change", "Base target"],
            y=[co.price, base["from_earnings"], base["from_multiple"], 0],
            text=[f"{cur}{co.price:,.0f}", f"{base['from_earnings']:+,.0f}".replace("+", "+" + cur).replace("-", "−" + cur),
                  f"{base['from_multiple']:+,.0f}".replace("+", "+" + cur).replace("-", "−" + cur), f"{cur}{base['target']:,.0f}"],
            textposition="outside",
            increasing=dict(marker=dict(color=BLUE)), decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=GRAY)), connector=dict(line=dict(color=GRAY, width=1))))
        base_pe = base["current_pe"] * (1 + base["multiple_change"])
        wf.update_layout(title=f"Base case: where the return comes from ({cur_pe:.1f}x → {base_pe:.1f}x)",
                         showlegend=False, hovermode="closest")
        chart(wf, 400)

        st.subheader("Sensitivity: upside vs. EPS growth and exit multiple")
        growths = [round(g0 + d, 3) for d in (-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15)]
        centre = fair_pe or cur_pe
        pes = [round(centre * f, 1) for f in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3)]
        grid = V.sensitivity(fwd_eps, co.price, growths, pes)
        lim = float(np.nanmax(np.abs(grid.values)))
        hm = go.Figure(go.Heatmap(
            z=grid.values * 100, x=[f"{p:.1f}x" for p in pes], y=[f"{g*100:+.0f}%" for g in growths],
            colorscale=[[0, RED], [0.5, "#f0efec"], [1, BLUE]], zmin=-lim * 100, zmax=lim * 100,
            text=[[f"{v*100:+.0f}%" for v in row] for row in grid.values], texttemplate="%{text}",
            hovertemplate="EPS growth %{y}, exit P/E %{x}: %{text}<extra></extra>",
            colorbar=dict(title="Upside %"), xgap=2, ygap=2))
        hm.update_layout(xaxis_title="Exit forward P/E", yaxis_title="Forward EPS growth", hovermode="closest",
                         xaxis_type="category", yaxis_type="category")
        chart(hm, 420)

        tr = co.estimates.eps_fy1_trend
        if tr:
            st.subheader("Estimate momentum (next-FY EPS consensus)")
            order = [k for k in ["90daysAgo", "60daysAgo", "30daysAgo", "7daysAgo", "current"] if k in tr]
            vals = [tr[k] for k in order]
            st.caption(f"Change over 90 days: {pct(vals[-1] / vals[0] - 1) if vals[0] else '—'} — "
                       "rising estimates tend to support the multiple; falling ones pressure it.")
            em = go.Figure(go.Scatter(x=[k.replace("daysAgo", "d ago") for k in order], y=vals,
                                      mode="lines+markers", line=dict(color=BLUE, width=2), marker=dict(size=9),
                                      hovertemplate=f"{cur}%{{y:.2f}}<extra></extra>"))
            em.update_layout(yaxis_title="EPS estimate", hovermode="closest")
            chart(em, 280)

st.divider()
st.caption("Data: Yahoo Finance via yfinance (free, may be delayed or incomplete). For research only — not investment advice.")
