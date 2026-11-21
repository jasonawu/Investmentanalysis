"""FMP provider tests with a fake HTTP client (no network, no API calls)."""
import pandas as pd
import pytest

from analysis import fmp
from analysis import valuation as V


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def _fake_fmp(premium=()):
    q_ends = ["2025-09-27", "2025-12-27", "2026-03-28", "2026-06-27", "2026-09-26"]
    data = {
        "profile": [{"price": 100.0, "marketCap": 1_000e9, "companyName": "Test Corp", "sector": "Technology",
                     "industry": "Software", "currency": "USD"}],
        "income-statement:annual": [
            {"date": f"{y}-09-26", "revenue": r * 1e9, "ebitda": r * 0.4e9, "ebit": r * 0.3e9, "epsDiluted": e}
            for y, r, e in [(2022, 300, 3.0), (2023, 330, 3.3), (2024, 360, 3.6), (2025, 400, 4.0), (2026, 440, 4.4)]],
        "income-statement:quarter": [
            {"date": d, "revenue": 110e9, "ebitda": 44e9, "ebit": 33e9, "epsDiluted": 1.1} for d in q_ends],
        "balance-sheet-statement": [{"netDebt": 50e9}],
        "analyst-estimates": [
            {"date": f"{y}-09-26", "epsAvg": e, "revenueAvg": r * 1e9, "ebitdaAvg": r * 0.42e9, "ebitAvg": r * 0.32e9,
             "numAnalystsEps": 20} for y, e, r in [(2025, 4.0, 400), (2026, 4.4, 440), (2027, 5.0, 480), (2028, 5.5, 520)]],
        "earnings": [
            {"date": "2027-01-29", "epsActual": None, "epsEstimated": 1.30, "revenueActual": None, "revenueEstimated": 125e9},
            {"date": "2026-10-30", "epsActual": 1.15, "epsEstimated": 1.10, "revenueActual": 110e9, "revenueEstimated": 108e9},
            {"date": "2026-07-30", "epsActual": 1.05, "epsEstimated": 1.08, "revenueActual": 110e9, "revenueEstimated": 111e9},
        ],
        "historical-price-eod/light": [{"date": d.strftime("%Y-%m-%d"), "price": 100.0}
                                       for d in pd.bdate_range("2021-01-04", "2026-11-20")][::-1],
        "stock-peers": [{"symbol": "PEER1"}, {"symbol": "0001.HK"}, {"symbol": "ABCDF"}, {"symbol": "PEER2"}],
    }

    class Http:
        calls = []

        def get(self, url, headers=None, timeout=None):
            assert headers == {"apikey": "test-key"} and "apikey=" not in url  # key only in the header
            path = url[len(fmp.API):].split("?")[0]
            key = path
            if path == "income-statement":
                key += ":quarter" if "period=quarter" in url else ":annual"
            self.calls.append(url)
            if path in premium:
                return _Resp(402, {"Error Message": "premium"})
            return _Resp(200, data[key])
    return Http()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.delenv("FMP_PLAN", raising=False)
    fmp._cache.clear()


def test_load_builds_company_with_multi_year_consensus():
    http = _fake_fmp()
    c = fmp.load("test", http=http)
    assert c.name == "Test Corp" and c.shares == pytest.approx(10e9) and c.net_debt == 50e9
    assert c.sources == {"financials": "FMP", "estimates": "FMP", "prices": "FMP"}
    # Only future years count as estimates; FY0/FY1 follow the last reported year.
    assert list(c.estimates.annual.index.year) == [2027, 2028]
    assert c.estimates.eps_fy0 == 5.0 and c.estimates.eps_fy1 == 5.5
    # Real EBITDA consensus is used instead of revenue x margin.
    fy = V.fiscal_table(c, "ebitda")
    assert fy[pd.Timestamp("2027-09-26")] == pytest.approx(480 * 0.42e9)
    assert V.forward_value(c, "eps", "fy1") == 5.5
    assert c.peers == ["PEER1", "PEER2"]  # foreign listings filtered out


def test_quarterly_consensus_vs_actual_and_next_quarter():
    c = fmp.load("test", http=_fake_fmp())
    qv = V.quarterly_view(c)
    sept = qv.loc[pd.Timestamp("2026-09-26")]
    assert sept["eps_consensus"] == 1.10 and sept["eps"] == 1.15 and sept["eps_surprise"] > 0
    assert sept["revenue_consensus"] == 108e9 and sept["revenue_surprise"] == pytest.approx(110 / 108 - 1)
    june = qv.loc[pd.Timestamp("2026-06-27")]
    assert june["eps_surprise"] < 0
    nxt = qv[qv["estimated"]]
    assert len(nxt) == 1 and nxt.index[0] == pd.Timestamp("2026-12-31") and nxt["revenue"].iloc[0] == 125e9


def test_free_plan_limits_and_caching():
    http = _fake_fmp()
    fmp.load("test", http=http)
    n = len(http.calls)
    # Free plan: statements and earnings history capped at 5 periods (annual estimates allow 10).
    capped = [u for u in http.calls if "income-statement" in u or "/earnings" in u]
    assert capped and all("limit=5" in u for u in capped)
    fmp.load("test", http=http)
    assert len(http.calls) == n  # second load served from cache


def test_premium_only_pieces_are_skipped_not_fatal():
    c = fmp.load("test", http=_fake_fmp(premium=("earnings", "analyst-estimates")))
    assert "estimates" not in c.sources and c.estimates.annual.empty and len(c.annual) == 5


def test_daily_limit_raises_so_loader_falls_back():
    class Http:
        def get(self, *a, **k):
            return _Resp(429, {})
    with pytest.raises(fmp.FMPDailyLimit):
        fmp.load("test", http=Http())
