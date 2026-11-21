import pandas as pd
import pytest

from analysis import valuation as V
from analysis.data import load_company
from analysis.models import CompanyData, Estimates


def _co():
    annual = pd.DataFrame({"revenue": [100.0, 110.0], "ebitda": [30.0, 33.0],
                           "ebit": [25.0, 28.0], "eps": [2.0, 2.2]},
                          index=pd.to_datetime(["2023-12-31", "2024-12-31"]))
    est = Estimates(eps_fy0=2.5, eps_fy1=3.0, revenue_fy0=120.0, revenue_fy1=132.0,
                    fy0_end=pd.Timestamp("2025-12-31"))
    prices = pd.Series(50.0, index=pd.bdate_range("2023-01-02", "2025-06-30"))
    return CompanyData("TST", "Test Co", price=50.0, prices=prices, annual=annual, estimates=est)


def test_ntm_eps_blends_fiscal_years():
    fy = V.fiscal_eps_table(_co())
    # Halfway through FY2025 -> about half FY25 (2.5) and half FY26 (3.0).
    assert V.ntm_eps_at(pd.Timestamp("2025-07-01"), fy) == pytest.approx(2.75, abs=0.01)
    # At fiscal year end, NTM is the next year.
    assert V.ntm_eps_at(pd.Timestamp("2024-12-31"), fy) == pytest.approx(2.5)


def test_forward_pe_history_uses_realized_then_consensus():
    h = V.forward_pe_history(_co())
    assert not h.empty
    assert (h["fwd_pe"] == h["price"] / h["fwd_eps"]).all()


def test_growth_and_decomposition_identity():
    c = _co()
    assert V.forward_eps_growth(c) == pytest.approx(0.2)
    d = V.decompose(price=100.0, fwd_eps=5.0, s=V.Scenario("base", 0.10, 22.0))
    assert d["target"] == pytest.approx(5.0 * 1.1 * 22.0)
    assert 100 + d["from_earnings"] + d["from_multiple"] == pytest.approx(d["target"])
    assert (1 + d["total_return"]) == pytest.approx(1.1 * (1 + d["multiple_change"]))


def test_fair_multiples_on_demo_universe():
    c = load_company("DEMO")
    peers = [load_company(p, with_peers=False) for p in c.peers]
    table = V.peer_table(c, peers)
    ms = V.fair_multiples(table, V.forward_pe_history(c), c.ticker)
    assert all(m.pe is None or 0 < m.pe < 200 for m in ms)
    assert V.blend(ms) is not None


def test_summarize_and_override():
    c = load_company("DEMO")
    peers = [load_company(p, with_peers=False) for p in c.peers]
    s = V.summarize(c, peers)
    assert s["fair_value"] == pytest.approx(s["fair_pe"] * s["fwd_eps"])
    assert s["upside"] == pytest.approx(s["fair_value"] / s["price"] - 1)
    only_peers = V.summarize(c, peers, methods={"median"})
    assert only_peers["fair_pe"] == pytest.approx(only_peers["peer_median_pe"])
    mine = V.summarize(c, peers, fair_pe_override=40.0)
    assert mine["fair_pe"] == 40.0 and mine["custom_pe"]
    assert V.verdict(0.2) == "Undervalued" and V.verdict(-0.2) == "Overvalued" and V.verdict(0.05) == "Fair"
