import pandas as pd
import pytest

from analysis import valuation as V
from analysis.data import load_company
from analysis.models import CompanyData, Estimates


def _co(net_debt=20.0):
    annual = pd.DataFrame({"revenue": [100.0, 110.0], "ebitda": [30.0, 33.0],
                           "ebit": [25.0, 28.0], "eps": [2.0, 2.2]},
                          index=pd.to_datetime(["2023-12-31", "2024-12-31"]))
    est = Estimates(eps_fy0=2.5, eps_fy1=3.0, revenue_fy0=120.0, revenue_fy1=132.0,
                    fy0_end=pd.Timestamp("2025-12-31"))
    prices = pd.Series(50.0, index=pd.bdate_range("2023-01-02", "2025-06-30"))
    return CompanyData("TST", "Test Co", price=50.0, market_cap=500.0, shares=10.0, net_debt=net_debt,
                       prices=prices, annual=annual, estimates=est)


def _demo_universe(t="DEMO"):
    c = load_company(t)
    return c, [load_company(p, with_peers=False) for p in c.peers]


def test_ntm_blends_fiscal_years():
    fy = V.fiscal_table(_co(), "eps")
    assert V.ntm_value_at(pd.Timestamp("2025-07-01"), fy) == pytest.approx(2.75, abs=0.01)
    assert V.ntm_value_at(pd.Timestamp("2024-12-31"), fy) == pytest.approx(2.5)


def test_ebitda_estimates_use_latest_margin():
    fy = V.fiscal_table(_co(), "ebitda")
    assert fy[pd.Timestamp("2025-12-31")] == pytest.approx(120.0 * 0.30)
    assert fy[pd.Timestamp("2026-12-31")] == pytest.approx(132.0 * 0.30)


def test_multiples_and_implied_price_roundtrip():
    c = _co()
    fwd_rev, fwd_ebitda = 126.0, 37.8
    assert V.multiple(c, "ps", fwd_rev) == pytest.approx(500 / 126)
    assert V.multiple(c, "ev_ebitda", fwd_ebitda) == pytest.approx(520 / 37.8)
    for metric, fwd in [("pe", 2.75), ("ps", fwd_rev), ("ev_ebitda", fwd_ebitda)]:
        m = V.multiple(c, metric, fwd)
        assert V.implied_price(c, metric, m, fwd) == pytest.approx(50.0)  # current multiple -> current price
    assert V.multiple(c, "pe", -1.0) is None


def test_net_debt_lowers_ev_based_value():
    assert V.implied_price(_co(100.0), "ev_ebitda", 10, 50) < V.implied_price(_co(0.0), "ev_ebitda", 10, 50)


def test_history_for_each_metric():
    for m in V.METRICS:
        h = V.multiple_history(_co(), m)
        assert not h.empty and (h["multiple"] > 0).all()


def test_decomposition_identity():
    c = _co()
    for metric, fwd in [("pe", 2.75), ("ps", 126.0), ("ev_ebitda", 37.8)]:
        d = V.decompose(c, metric, fwd, V.Scenario("base", 0.10, V.multiple(c, metric, fwd) * 1.2))
        assert c.price + d["from_fundamentals"] + d["from_multiple"] == pytest.approx(d["target"])
    d = V.decompose(c, "pe", 2.75, V.Scenario("base", 0.10, 22.0))
    assert d["target"] == pytest.approx(2.75 * 1.1 * 22.0)


def test_fair_multiples_on_demo_universe():
    c, peers = _demo_universe()
    table = V.peer_table(c, peers)
    for metric in V.METRICS:
        ms = V.fair_multiples(table, V.multiple_history(c, metric), c.ticker, metric)
        assert all(m.value is None or 0 < m.value < V.METRICS[metric].cap for m in ms)
        assert V.blend(ms) is not None


def test_auto_lens_picks_ps_for_unprofitable_grower():
    c, peers = _demo_universe("DEMOG")
    assert V.forward_value(c, "eps") < 0
    assert V.auto_metric(c) == "ps"
    s = V.summarize(c, peers)
    assert s["lens"] == "ps" and s["fair_value"] is not None
    assert s["by_metric"]["pe"]["meaningful"] is False and s["upside_pe"] is None


def test_summarize_and_overrides():
    c, peers = _demo_universe()
    s = V.summarize(c, peers)
    assert s["lens"] == "pe"
    assert s["upside"] == pytest.approx(s["fair_value"] / s["price"] - 1)
    only_peers = V.summarize(c, peers, methods={"median"})
    assert only_peers["fair"] == pytest.approx(only_peers["by_metric"]["pe"]["peer_median"])
    mine = V.summarize(c, peers, overrides={"ps": 9.0}, lens="ps")
    assert mine["fair"] == 9.0 and mine["custom"] and mine["lens"] == "ps"
    assert V.verdict(0.2) == "Undervalued" and V.verdict(-0.2) == "Overvalued" and V.verdict(0.05) == "Fair"
