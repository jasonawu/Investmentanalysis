"""Single-stock dashboard: price, fundamentals, valuation on P/E, EV/EBITDA and P/S, peers, price target."""
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
                          as_text, data_source_caption, fmt_money, get_company, get_peers, lens_label, load_watchlist, metric_value_fmt,
                          pct, save_watchlist, show_save_error)

# --------------------------------------------------------------------------- #
# Sidebar: stock, basis, peers
# --------------------------------------------------------------------------- #
wl = load_watchlist()
show_save_error()
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
table = V.peer_table(co, peers, basis)
auto = V.auto_metric(co, basis)

# --------------------------------------------------------------------------- #
# Sidebar: valuation lens and fair multiple
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Valuation lens")
    lens_opts = list(W.LENSES)
    saved_lens = wl.get_lens(co.ticker)
    lens_choice = st.radio("Value this stock on", lens_opts, index=lens_opts.index(saved_lens),
                           format_func=lambda k: f"Auto → {V.METRICS[auto].short}" if k == "auto" else lens_label(k),
                           key=f"lens_{co.ticker}", help=V.AUTO_RULE)
    metric = auto if lens_choice == "auto" else lens_choice
    M = V.METRICS[metric]

    st.header("Fair multiple")
    st.session_state.setdefault("methods", list(V.METHOD_KEYS))
    methods = {k for k, name in V.METHOD_KEYS.items()
               if st.checkbox(name, value=k in st.session_state["methods"], key=f"m_{k}")}
    st.session_state["methods"] = sorted(methods)

    # Evaluate every lens once; the chosen lens can carry the user's own multiple.
    base_eval = {k: V.evaluate_metric(co, k, table, basis, methods) for k in V.METRICS}
    saved = wl.get_fair(co.ticker, metric)
    override = st.checkbox(f"Use my own fair {M.short}", value=saved is not None, key=f"ovr_{co.ticker}_{metric}")
    my_mult = None
    if override:
        my_mult = st.number_input(f"My fair {M.label}", min_value=0.1,
                                  value=float(round(saved or base_eval[metric]["model"] or 10.0, 1)),
                                  step=0.5, key=f"my_{co.ticker}_{metric}")
    ev = dict(base_eval)
    if my_mult:
        ev[metric] = V.evaluate_metric(co, metric, table, basis, methods, my_mult)

    st.header("Watchlist")
    if co.ticker in wl.tickers:
        st.caption(f"✓ {co.ticker} is on your watchlist")
        b1, b2 = st.columns(2)
        if b1.button("Save", help="The watchlist will rank this stock with this lens "
                                                  "(and your fair multiple, if set)"):
            wl.set_lens(co.ticker, lens_choice)
            wl.set_fair(co.ticker, metric, my_mult if override else None)
            save_watchlist(wl); st.rerun()
        if b2.button("Remove"):
            wl.remove(co.ticker); save_watchlist(wl); st.rerun()
    elif st.button(f"☆ Add {co.ticker} to watchlist", width="stretch"):
        wl.add(co.ticker)
        wl.set_lens(co.ticker, lens_choice)
        if override:
            wl.set_fair(co.ticker, metric, my_mult)
        save_watchlist(wl); st.rerun()

h = ev[metric]
fwd, cur_mult, fair, fair_value, upside = h["fwd"], h["current"], h["fair"], h["fair_value"], h["upside"]

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title(f"{co.name} ({co.ticker})")
st.caption(" · ".join(x for x in [co.sector, co.industry, f"Market cap {fmt_money(co.market_cap, cur)}",
                                   (f"Net debt {fmt_money(V.net_debt_of(co), cur)}" if V.net_debt_of(co) >= 0
                                    else f"Net cash {fmt_money(-V.net_debt_of(co), cur)}"),
                                   f"{co.estimates.analysts} analysts" if co.estimates.analysts else ""] if x))
if co.is_demo:
    st.info("Showing **synthetic demo data** (fictional companies). Enter a real ticker to pull live data.")
elif data_source_caption(co):
    st.caption(data_source_caption(co))

k = st.columns(6)
k[0].metric("Price", f"{cur}{co.price:,.2f}" if co.price else "—")
k[1].metric(f"Forward {M.field_label}", metric_value_fmt(fwd, M, cur), help=basis_label)
k[2].metric(M.label, f"{cur_mult:.1f}x" if (cur_mult and h["meaningful"]) else "n/m")
k[3].metric(f"Fair {M.short}", f"{fair:.1f}x" if fair else "—",
            delta=f"{(fair/cur_mult-1)*100:+.0f}% vs current" if (fair and cur_mult and h["meaningful"]) else None,
            help="Your own multiple" if h["custom"] else "Blend of the methods ticked in the sidebar")
k[4].metric("Fair value today", f"{cur}{fair_value:,.2f}" if fair_value else "—")
k[5].metric("Upside / downside", pct(upside))

if not h["meaningful"]:
    st.warning(f"⚠ **{M.short} isn't meaningful for {co.ticker}** (forward {M.field_label} is negative or too "
               f"small). Try the {'P/S' if metric != 'ps' else 'EV/EBITDA'} lens in the sidebar.")
elif upside is not None:
    what = f"{cur_mult:.1f}x vs a fair {fair:.1f}x forward {M.field_label.lower() if M.field != 'eps' else 'earnings'} ({M.short})"
    if upside > FAIR_BAND:
        st.success(f"▲ **Looks undervalued** on {M.short}: trades at {what}.")
    elif upside < -FAIR_BAND:
        st.error(f"▼ **Looks overvalued** on {M.short}: trades at {what}.")
    else:
        st.warning(f"● **Roughly fairly priced** on {M.short}: within ±{FAIR_BAND:.0%} of fair value at {fair:.1f}x.")

tabs = st.tabs(["① Price", "② Fundamentals vs price", "③ Valuation summary", "④ Multiple history",
                "⑤ Peer valuation", "⑥ Price target"])

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
        show_q = st.checkbox("Show quarterly revenue & EPS", value=True,
                             help="Reported results per quarter, lined up under the price on the same dates, "
                                  "with analyst consensus for EPS and for quarters not yet reported.")
        qv = V.quarterly_view(co) if show_q else pd.DataFrame()
        qw = qv[qv.index >= start] if len(qv) else qv
        panels = show_q and len(qw) > 0 and qw["revenue"].notna().any()

        # Price, revenue and EPS stacked tightly on ONE shared date axis (so the hover guide line and
        # tooltip cover all three); each panel has its own y scale so quarter-to-quarter changes are as
        # visible as moves in the stock.
        fig = go.Figure()
        fig.add_scatter(x=s.index, y=s, mode="lines", line=dict(color=BLUE, width=2), name="Close",
                        hovertemplate=f"{cur}%{{y:,.2f}}")
        if len(s) > 50:
            ma = px.rolling(50).mean().reindex(s.index)
            fig.add_scatter(x=ma.index, y=ma, mode="lines", name="50-day avg",
                            line=dict(color=GRAY, width=1.5, dash="dot"), hovertemplate=f"{cur}%{{y:,.2f}}")
        axes = dict(yaxis=dict(title=f"Price ({co.currency})", domain=[0, 1]))
        x_end = s.index.max()
        if panels:
            yoy = qv["revenue"].pct_change(4, fill_method=None).reindex(qw.index) * 100
            act, fut = qw[~qw["estimated"]], qw[qw["estimated"]]
            hollow = dict(size=8, symbol="circle-open", line=dict(width=2))

            # Revenue: reported (solid) then consensus for unreported quarters (dashed).
            def beat_text(series):
                return [("" if pd.isna(x) else (f" · beat {x*100:+.1f}%" if x >= 0 else f" · miss {x*100:+.1f}%"))
                        for x in series]

            yoy_txt = [("" if pd.isna(v) else f" (YoY {v:+.1f}%)") for v in yoy.reindex(act.index)]
            fig.add_scatter(x=act.index, y=act["revenue"] / 1e9, name="Revenue", mode="lines+markers", yaxis="y2",
                            line=dict(color=AQUA, width=2), marker=dict(size=8),
                            customdata=[a + b for a, b in zip(yoy_txt, beat_text(act["revenue_surprise"]))],
                            hovertemplate=f"{cur}%{{y:,.2f}}B%{{customdata}}")
            # Revenue consensus: what analysts expected for recent quarters (when the source has it) and
            # the forecast for unreported quarters.
            rc = qw.dropna(subset=["revenue_consensus"])
            if len(rc) and not (~rc["estimated"]).any() and len(act):
                rc = pd.concat([act.tail(1).assign(revenue_consensus=act["revenue"].iloc[-1]), rc])
            if len(rc):
                fig.add_scatter(x=rc.index, y=rc["revenue_consensus"] / 1e9, name="Revenue consensus", yaxis="y2",
                                mode="lines+markers", line=dict(color=AQUA, width=2, dash="dash"), marker=hollow,
                                hovertemplate=f"{cur}%{{y:,.2f}}B")

            # EPS: reported (solid) vs consensus (dashed) for the same quarters, then consensus ahead.
            beat = beat_text(act["eps_surprise"])
            fig.add_scatter(x=act.index, y=act["eps"], name="EPS (diluted)", mode="lines+markers", yaxis="y3",
                            line=dict(color=ORANGE, width=2), marker=dict(size=8), customdata=beat,
                            hovertemplate=f"{cur}%{{y:,.2f}}%{{customdata}}")
            cons = qw.dropna(subset=["eps_consensus"])
            if len(cons):
                fig.add_scatter(x=cons.index, y=cons["eps_consensus"], name="EPS consensus", yaxis="y3",
                                mode="lines+markers", line=dict(color=ORANGE, width=2, dash="dash"), marker=hollow,
                                hovertemplate=f"{cur}%{{y:,.2f}}")
            axes = dict(yaxis=dict(title=f"Price ({co.currency})", domain=[0.47, 1]),
                        yaxis2=dict(title=f"Revenue ({cur.strip()}B)", domain=[0.245, 0.455]),
                        yaxis3=dict(title=f"EPS ({cur.strip()})", domain=[0, 0.21]),
                        xaxis=dict(anchor="y3"))  # dates along the bottom of the stack
            if (qw["eps"] < 0).any() or (qw["eps_consensus"] < 0).any():
                fig.add_hline(y=0, line=dict(color=GRAY, width=1), yref="y3")
            x_end = max(x_end, qw.index.max())
        fig.update_layout(**axes)
        fig.update_xaxes(range=[s.index.min() - pd.Timedelta(days=5), x_end + pd.Timedelta(days=12) + (s.index.max() - s.index.min()) * 0.015],
                         showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1,
                         spikedash="dot", spikecolor=GRAY)
        fig.update_layout(title=f"{co.ticker} share price · {tf} {chg*100:+.1f}%", hoversubplots="axis")
        chart(fig, 640 if panels else 420)
        if show_q:
            if not len(qv):
                st.caption("No quarterly results available for this company.")
            elif not panels:
                st.caption("No quarterly results inside this timeframe. Pick 6M or longer.")
            else:
                earliest = co.quarterly.index.min() if len(co.quarterly) else None
                note = (f" Yahoo only provides quarterly results back to {earliest:%b %Y}, so the lines start there."
                        if earliest is not None and earliest > start + pd.DateOffset(months=3) else "")
                st.caption("Solid lines are reported results; dashed lines are analyst consensus. Where the "
                           "dashed line runs alongside the solid one, it shows what analysts expected that quarter, "
                           "so the gap is the beat or miss (recent quarters only; revenue needs FMP data). Points "
                           "sit at each quarter's end date." + note)
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
        em = V.ebitda_margin(co)
        est_rows = {d: {"revenue": r, "eps": p, "ebitda": r * em if (r and em is not None) else None}
                    for d, r, p in [(e.fy0_end, e.revenue_fy0, e.eps_fy0),
                                    (e.fy0_end + pd.DateOffset(years=1), e.revenue_fy1, e.eps_fy1)]}

    if f.empty:
        st.write("No financial statements available.")
    else:
        st.caption("Price, revenue and diluted EPS stacked on one shared date axis, each with its own scale. "
                   "Hover anywhere to line up the price with the results; dashed lines are analyst consensus.")
        # One shared x axis (so the hover guide line and tooltip span every panel) and five stacked y axes.
        chart_fields = ["revenue", "eps"]
        colors = {"revenue": AQUA, "eps": ORANGE}
        heights, gap = [0.5, 0.25, 0.25], 0.022
        usable = 1 - gap * (len(heights) - 1)
        domains, top = [], 1.0
        for h_ in heights:
            bottom = max(0.0, top - h_ * usable)
            domains.append([round(bottom, 4), round(top, 4)])
            top = bottom - gap
        fig = go.Figure()
        lo = f.index.min() - pd.DateOffset(months=12)
        p = co.prices[co.prices.index >= lo]
        fig.add_scatter(x=p.index, y=p, line=dict(color=BLUE, width=2), name="Price",
                        hovertemplate=f"{cur}%{{y:,.2f}}")
        axes = {"yaxis": dict(title=f"Price ({co.currency})", domain=domains[0])}
        for i, m in enumerate(chart_fields, start=2):
            ya = f"y{i}"
            scale = 1 if m == "eps" else 1e9
            fmt = f"{cur}%{{y:,.2f}}" + ("" if m == "eps" else "B")
            short = {"revenue": "Revenue", "eps": "EPS (diluted)"}[m]
            axes[f"yaxis{i}"] = dict(title=f"{short.split(' ')[0]} ({cur.strip()}{'' if m == 'eps' else 'B'})", domain=domains[i - 1])
            rep_s = f[m].dropna() / scale
            fig.add_scatter(x=rep_s.index, y=rep_s, yaxis=ya, mode="lines+markers",
                            line=dict(color=colors[m], width=2), marker=dict(size=8), name=short,
                            hovertemplate=fmt)
            ex = [(d, v[m] / scale) for d, v in est_rows.items() if v.get(m) is not None]
            if ex and len(rep_s):
                # Dashed line continues from the last reported year into the estimates.
                xs = [rep_s.index[-1]] + [d for d, _ in ex]
                ys = [rep_s.iloc[-1]] + [v for _, v in ex]
                fig.add_scatter(x=xs, y=ys, yaxis=ya, mode="lines+markers",
                                line=dict(color=colors[m], width=2, dash="dash"),
                                marker=dict(size=8, symbol="circle-open", line=dict(width=2)),
                                name=f"{short.split(' ')[0]} consensus", hovertemplate=fmt)
            if (rep_s < 0).any() or any(v < 0 for _, v in ex):
                fig.add_hline(y=0, line=dict(color=GRAY, width=1), yref=ya)
        fig.update_layout(**axes, xaxis=dict(anchor=f"y{len(heights)}"), hoversubplots="axis")
        fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1,
                         spikedash="dot", spikecolor=GRAY)
        chart(fig, 620)

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
# 3. Valuation summary (football field)
# --------------------------------------------------------------------------- #
with tabs[2]:
    st.caption("Fair value from each multiple. Bars span the range of the fair-multiple methods you ticked; "
               "◆ is the blended (or your own) fair value. Lenses that don't apply to this company are greyed out.")
    rows = []
    for key, r in ev.items():
        mm = V.METRICS[key]
        rows.append({"key": key, "Lens": mm.short + (" ◀ selected" if key == metric else ""),
                     "Forward base": metric_value_fmt(r["fwd"], mm, cur),
                     "Current": r["current"] if r["meaningful"] else None, "Fair": r["fair"] if r["meaningful"] else None,
                     "Fair value": r["fair_value"], "Low": r["low"], "High": r["high"],
                     "Upside %": r["upside"] * 100 if r["upside"] is not None else None,
                     "Verdict": r["verdict"] if r["meaningful"] else "not meaningful",
                     "Source": "Mine" if r["custom"] else "Model"})
    ff = pd.DataFrame(rows)
    for c in ["Current", "Fair", "Fair value", "Low", "High", "Upside %"]:
        ff[c] = pd.to_numeric(ff[c], errors="coerce")
    one_year = co.prices[co.prices.index >= co.prices.index.max() - pd.DateOffset(years=1)] if len(co.prices) else None

    fig = go.Figure()
    labels = list(ff["Lens"])[::-1]
    if one_year is not None and len(one_year):
        labels = labels + ["52-week range"]
    for _, r in ff.iloc[::-1].iterrows():
        if r["Low"] is not None and r["High"] is not None and pd.notna(r["Low"]):
            lo, hi = r["Low"], r["High"]
            if hi - lo < co.price * 0.01:  # single method: draw a small visible bar
                lo, hi = lo - co.price * 0.005, hi + co.price * 0.005
            fig.add_bar(y=[r["Lens"]], x=[hi - lo], base=[lo], orientation="h", showlegend=False,
                        marker=dict(color=BLUE if r["key"] == metric else "#86b6ef"),
                        hovertemplate=f"{r['Lens']}: {cur}{r['Low']:,.2f} – {cur}{r['High']:,.2f}<extra></extra>")
        if r["Fair value"] is not None and pd.notna(r["Fair value"]):
            fig.add_scatter(y=[r["Lens"]], x=[r["Fair value"]], mode="markers", showlegend=False,
                            marker=dict(symbol="diamond", size=14, color=ORANGE, line=dict(color="white", width=2)),
                            hovertemplate=f"Fair value {cur}%{{x:,.2f}}<extra></extra>")
    if one_year is not None and len(one_year):
        fig.add_bar(y=["52-week range"], x=[one_year.max() - one_year.min()], base=[one_year.min()],
                    orientation="h", marker=dict(color=GRAY), showlegend=False,
                    hovertemplate=f"52w: {cur}{one_year.min():,.2f} – {cur}{one_year.max():,.2f}<extra></extra>")
    for _, r in ff[ff["Verdict"] == "not meaningful"].iterrows():
        fig.add_annotation(y=r["Lens"], x=co.price, text=f"not meaningful (negative forward "
                           f"{V.METRICS[r['key']].field_label})", showarrow=False, xanchor="left", xshift=8,
                           font=dict(color=GRAY))
    fig.add_vline(x=co.price, line=dict(color=GRAY, width=2, dash="dash"),
                  annotation_text=f"price {cur}{co.price:,.2f}", annotation_position="top")
    fig.update_layout(title="Fair value by valuation lens", xaxis_title=f"Implied share price ({co.currency})",
                      hovermode="closest", barmode="overlay", bargap=0.45,
                      yaxis=dict(categoryorder="array", categoryarray=labels))
    chart(fig, 340)

    votes = ff[ff["Verdict"].isin(["Undervalued", "Fair", "Overvalued"])]
    if len(votes):
        tally = ", ".join(f"{(votes['Verdict'] == v).sum()} {v.lower()}" for v in ["Undervalued", "Fair", "Overvalued"]
                          if (votes["Verdict"] == v).sum())
        st.markdown(f"**Cross-check:** of {len(votes)} applicable lenses: {tally}.")
    num = lambda f: st.column_config.NumberColumn(format=f)
    st.dataframe(as_text(ff.drop(columns=["key"]),
                     {"Current": "{:.1f}x", "Fair": "{:.1f}x", "Fair value": "{:,.2f}", "Low": "{:,.2f}",
                      "High": "{:,.2f}", "Upside %": "{:+.1f}%"}),
                 hide_index=True, width="stretch")
    st.caption(f"**Which lens?** P/E suits profitable, mature companies. EV/EBITDA is neutral to debt and "
               f"useful for leveraged or capital-heavy businesses. P/S is for fast growers without meaningful "
               f"earnings yet; judge it next to revenue growth and margins. Auto rule: {V.AUTO_RULE}")

# --------------------------------------------------------------------------- #
# 4. Multiple history
# --------------------------------------------------------------------------- #
with tabs[3]:
    hm_key = st.radio("Multiple", list(V.METRICS), index=list(V.METRICS).index(metric), horizontal=True,
                      format_func=lens_label, key="hist_metric")
    HM = V.METRICS[hm_key]
    he = ev[hm_key]
    hh = he["history"].dropna()
    hh = hh[(hh["multiple"] > 0) & (hh["multiple"] < HM.cap)]
    st.caption(f"{HM.label} = {'price' if HM.per_share else ('enterprise value' if HM.enterprise else 'market cap')} "
               f"÷ forward {HM.field_label}. For past dates the {HM.field_label} the company *actually reported* "
               "over the next 12 months is used (old consensus isn't available free); recent points use today's "
               "consensus." + ("" if HM.per_share else " Uses today's share count and net debt throughout."))
    if hh.empty:
        st.write(f"No meaningful {HM.short} history (forward {HM.field_label} was negative or too small).")
    else:
        mu, sd = hh["multiple"].mean(), hh["multiple"].std()
        fig = go.Figure()
        fig.add_hrect(y0=mu - sd, y1=mu + sd, fillcolor=GRAY, opacity=0.12, line_width=0)
        fig.add_hline(y=mu, line=dict(color=GRAY, dash="dash", width=1.5),
                      annotation_text=f"avg {mu:.1f}x", annotation_position="top left")
        fig.add_scatter(x=hh.index, y=hh["multiple"], mode="lines", line=dict(color=BLUE, width=2),
                        name=HM.label, hovertemplate="%{y:.1f}x")
        if he["fair"]:
            fig.add_hline(y=he["fair"], line=dict(color=ORANGE, width=2),
                          annotation_text=f"fair {he['fair']:.1f}x", annotation_position="bottom right")
        fig.update_layout(title=f"{HM.label} · now {hh['multiple'].iloc[-1]:.1f}x · band = ±1σ ({mu-sd:.1f}x–{mu+sd:.1f}x)",
                          yaxis_title=f"x forward {HM.field_label}")
        chart(fig, 400)

        st.subheader(f"What drove the stock: {HM.field_label} growth vs. multiple")
        yrs = st.select_slider("Look-back", options=[1, 2, 3, 5, 10], value=3, format_func=lambda y: f"{y}y")
        a = hh[hh.index >= hh.index.max() - pd.DateOffset(years=yrs)]
        if len(a) >= 2:
            r_mult = a["multiple"].iloc[-1] / a["multiple"].iloc[0] - 1
            r_fund = a["fwd"].iloc[-1] / a["fwd"].iloc[0] - 1
            r_px = a["price"].iloc[-1] / a["price"].iloc[0] - 1
            m3 = st.columns(3)
            m3[0].metric("Price change", pct(r_px))
            m3[1].metric(f"Forward {HM.field_label} growth", pct(r_fund))
            m3[2].metric("Multiple change", pct(r_mult), help=f"{a['multiple'].iloc[0]:.1f}x → {a['multiple'].iloc[-1]:.1f}x")
            ident = "price" if not HM.enterprise else "enterprise value"
            st.caption(f"(1 + {ident} change) = (1 + {HM.field_label} growth) × (1 + multiple change)"
                       + (". With debt, the share price moves more than EV." if HM.enterprise else ""))

# --------------------------------------------------------------------------- #
# 5. Peer valuation
# --------------------------------------------------------------------------- #
with tabs[4]:
    pm_key = st.radio("Multiple", list(V.METRICS), index=list(V.METRICS).index(metric), horizontal=True,
                      format_func=lens_label, key="peer_metric")
    PM = V.METRICS[pm_key]
    gcol = V.GROWTH_COL[PM.growth_field]
    gname = "EPS" if PM.growth_field == "eps" else "revenue"
    if len(table) <= 1:
        st.write("No peers loaded. Add tickers in the sidebar.")
    else:
        t = table.copy()
        t["plot"] = t[pm_key].where((t[pm_key] > 0) & (t[pm_key] < PM.cap))
        t = t.sort_values("plot", na_position="first")
        med = V.valid_peers(table, pm_key)[pm_key].median()
        fig = go.Figure(go.Bar(
            y=t.index, x=t["plot"].fillna(0), orientation="h",
            marker_color=[BLUE if x else GRAY for x in t["is_target"]],
            text=[f"{v:.1f}x" if v == v else "n/m" for v in t["plot"]], textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: %{x:.1f}x<extra></extra>"))
        if med == med:
            fig.add_vline(x=med, line=dict(color=ORANGE, dash="dash", width=2),
                          annotation_text=f"peer median {med:.1f}x", annotation_position="bottom right")
        fig.update_layout(title=f"{PM.label} vs peers (n/m = negative or not meaningful)",
                          xaxis_title=f"x forward {PM.field_label}", showlegend=False, hovermode="closest")
        chart(fig, max(300, 40 * len(t)))

        st.subheader(f"Is the premium justified by {gname} growth?")
        d = t.dropna(subset=["plot", gcol])
        sc = go.Figure()
        for is_t, col, nm in [(False, GRAY, "Peers"), (True, BLUE, co.ticker)]:
            dd = d[d["is_target"] == is_t]
            sc.add_scatter(x=dd[gcol] * 100, y=dd["plot"], mode="markers+text", name=nm,
                           text=dd.index, textposition="top center",
                           marker=dict(size=14 if is_t else 11, color=col, line=dict(color="white", width=2)),
                           hovertemplate="%{text}: growth %{x:.1f}%, %{y:.1f}x<extra></extra>")
        reg = V.regression(V.valid_peers(table, pm_key), pm_key)
        if reg and len(d):
            slope, icpt, r2 = reg
            xs = np.linspace(d[gcol].min(), d[gcol].max(), 20)
            sc.add_scatter(x=xs * 100, y=icpt + slope * xs, mode="lines", name=f"Peer fit (R² {r2:.2f})",
                           line=dict(color=ORANGE, width=2, dash="dash"))
        sc.update_layout(xaxis_title=f"Consensus {gname} growth, next FY (%)", yaxis_title=PM.label,
                         hovermode="closest")
        chart(sc, 420)
        st.caption("Above the line = priced richer than its growth implies; below = cheaper."
                   + (" For P/S, also weigh margins: a 30% grower at break-even deserves less than one at 20% "
                      "EBITDA margin (see Rule of 40 below)." if pm_key == "ps" else ""))

        show = table.drop(columns=["is_target"] + [c for c in table.columns if c.endswith("_g")]).copy()
        show = show.apply(lambda col: pd.to_numeric(col, errors="coerce") if col.name != "name" else col)
        show["market_cap"] = show["market_cap"] / 1e9
        for c in ["eps_growth", "rev_growth", "op_margin", "ebitda_margin"]:
            show[c] = show[c] * 100
        for c in V.METRICS:
            show[c] = show[c].where((show[c] > 0) & (show[c] < V.METRICS[c].cap))
        show = show.drop(columns=["fwd_ebitda", "fwd_revenue"]).rename(columns={
            "name": "Name", "market_cap": "Mkt cap ($B)", "price": "Price", "fwd_eps": "Fwd EPS",
            "pe": "P/E", "ev_ebitda": "EV/EBITDA", "ps": "P/S", "eps_growth": "EPS growth %",
            "rev_growth": "Rev growth %", "op_margin": "Op margin %", "ebitda_margin": "EBITDA margin %",
            "rule_of_40": "Rule of 40"})
        num = lambda f: st.column_config.NumberColumn(format=f)
        st.dataframe(as_text(show,
                         {"Mkt cap ($B)": "{:,.1f}", "Price": "{:,.2f}", "Fwd EPS": "{:.2f}", "P/E": "{:.1f}x",
                          "EV/EBITDA": "{:.1f}x", "P/S": "{:.1f}x", "EPS growth %": "{:+.1f}",
                          "Rev growth %": "{:+.1f}", "Op margin %": "{:.1f}", "EBITDA margin %": "{:.1f}",
                          "Rule of 40": "{:.0f}"}), width="stretch")
        st.caption("— multiple = not meaningful (negative or extreme). Rule of 40 = revenue growth % + "
                   "EBITDA margin %; above 40 is the usual bar for a healthy growth company.")

    st.subheader(f"Fair {PM.short} estimates")
    st.dataframe(as_text(pd.DataFrame([{"Method": m.method, f"Fair {PM.short}": round(m.value, 1) if m.value else np.nan,
                                "Basis": m.note, "Used": m.key in methods} for m in ev[pm_key]["multiples"]]),
                         {f"Fair {PM.short}": "{:.1f}x"}), width="stretch", hide_index=True)
    st.caption("Toggle methods or set your own multiple in the sidebar.")

# --------------------------------------------------------------------------- #
# 6. Price target
# --------------------------------------------------------------------------- #
with tabs[5]:
    if not (h["meaningful"] and fwd and co.price):
        st.write(f"Needs a meaningful {M.short} to build a price target. Pick another lens in the sidebar.")
    else:
        fname = M.field_label
        g0 = V.forward_growth(co, "eps" if M.field == "eps" else "revenue") or 0.08
        st.caption(f"12-month target on {M.short}: forward {fname} × (1 + {fname} growth) × exit {M.short}"
                   + (", minus net debt, ÷ shares." if M.enterprise else (" ÷ shares." if not M.per_share else ".")))
        f0 = fair or cur_mult
        default = pd.DataFrame([
            {"Scenario": "Bear", "Growth %": round(g0 * 100 - 10, 1), "Exit multiple": round(min(cur_mult, f0) * 0.85, 1)},
            {"Scenario": "Base", "Growth %": round(g0 * 100, 1), "Exit multiple": round(f0, 1)},
            {"Scenario": "Bull", "Growth %": round(g0 * 100 + 8, 1), "Exit multiple": round(max(cur_mult, f0) * 1.1, 1)},
        ])
        sc_df = st.data_editor(default, hide_index=True, width="stretch", key=f"sc_{co.ticker}_{metric}",
                               column_config={"Scenario": st.column_config.TextColumn(disabled=True),
                                              "Growth %": st.column_config.NumberColumn(f"{fname} growth %"),
                                              "Exit multiple": st.column_config.NumberColumn(f"Exit {M.short}")})
        rows = []
        for _, r in sc_df.iterrows():
            dd = V.decompose(co, metric, fwd, V.Scenario(r["Scenario"], r["Growth %"] / 100, r["Exit multiple"]))
            if dd:
                rows.append({**dd, "Scenario": r["Scenario"]})
        if rows:
            res = pd.DataFrame(rows).set_index("Scenario")
            cols = st.columns(len(res))
            for c, (nm, r) in zip(cols, res.iterrows()):
                c.metric(f"{nm} target", f"{cur}{r['target']:,.2f}", pct(r["total_return"]))

            base = res.loc["Base"] if "Base" in res.index else res.iloc[0]
            money = lambda v: f"{v:+,.0f}".replace("+", "+" + cur).replace("-", "−" + cur)
            wf = go.Figure(go.Waterfall(
                orientation="v", measure=["absolute", "relative", "relative", "total"],
                x=["Price today", f"{fname} growth", "Multiple change", "Base target"],
                y=[co.price, base["from_fundamentals"], base["from_multiple"], 0],
                text=[f"{cur}{co.price:,.0f}", money(base["from_fundamentals"]), money(base["from_multiple"]),
                      f"{cur}{base['target']:,.0f}"],
                textposition="outside",
                increasing=dict(marker=dict(color=BLUE)), decreasing=dict(marker=dict(color=RED)),
                totals=dict(marker=dict(color=GRAY)), connector=dict(line=dict(color=GRAY, width=1))))
            wf.update_layout(title=f"Base case: where the return comes from ({M.short} {cur_mult:.1f}x → "
                                   f"{base['exit_multiple']:.1f}x)", showlegend=False, hovermode="closest")
            chart(wf, 400)

        st.subheader(f"Sensitivity: upside vs. {fname} growth and exit {M.short}")
        growths = [round(g0 + d, 3) for d in (-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15)]
        centre = fair or cur_mult
        mults = [round(centre * f, 1) for f in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3)]
        grid = V.sensitivity(co, metric, fwd, growths, mults)
        lim = float(np.nanmax(np.abs(grid.values))) or 1.0
        hmp = go.Figure(go.Heatmap(
            z=grid.values * 100, x=[f"{p:.1f}x" for p in mults], y=[f"{g*100:+.0f}%" for g in growths],
            colorscale=[[0, RED], [0.5, "#f0efec"], [1, BLUE]], zmin=-lim * 100, zmax=lim * 100,
            text=[[f"{v*100:+.0f}%" for v in row] for row in grid.values], texttemplate="%{text}",
            hovertemplate=f"{fname} growth %{{y}}, exit %{{x}}: %{{text}}<extra></extra>",
            colorbar=dict(title="Upside %"), xgap=2, ygap=2))
        hmp.update_layout(xaxis_title=f"Exit {M.label}", yaxis_title=f"Forward {fname} growth", hovermode="closest",
                          xaxis_type="category", yaxis_type="category")
        chart(hmp, 420)

    tr = co.estimates.eps_fy1_trend
    if tr:
        st.subheader("Estimate momentum (next-FY EPS consensus)")
        order = [k for k in ["90daysAgo", "60daysAgo", "30daysAgo", "7daysAgo", "current"] if k in tr]
        vals = [tr[k] for k in order]
        chg = (vals[-1] - vals[0]) / abs(vals[0]) if vals[0] else None
        st.caption(f"Change over 90 days: {pct(chg)}. Rising estimates tend to support the multiple; "
                   "falling ones pressure it.")
        em = go.Figure(go.Scatter(x=[k.replace("daysAgo", "d ago") for k in order], y=vals,
                                  mode="lines+markers", line=dict(color=BLUE, width=2), marker=dict(size=9),
                                  hovertemplate=f"{cur}%{{y:.2f}}<extra></extra>"))
        em.update_layout(yaxis_title="EPS estimate", hovermode="closest")
        chart(em, 280)

st.divider()
st.caption("Data: Yahoo Finance via yfinance (free, may be delayed or incomplete). For research only, not investment advice.")
