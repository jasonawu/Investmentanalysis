import json

from analysis import watchlist as W


def test_roundtrip_and_edits(tmp_path):
    p = tmp_path / "wl.json"
    assert W.load(p).tickers == W.STARTER  # missing file -> starter list
    w = W.Watchlist()
    assert w.add("snow") and not w.add("SNOW")
    w.set_fair("SNOW", "ps", 12)
    w.set_lens("SNOW", "ps")
    w.set_note("SNOW", " data cloud ")
    W.save(w, p)
    r = W.load(p)
    assert r.tickers == ["SNOW"] and r.get_fair("SNOW", "ps") == 12.0
    assert r.get_lens("SNOW") == "ps" and r.notes == {"SNOW": "data cloud"}
    r.set_fair("SNOW", "ps", None)
    r.set_lens("SNOW", "auto")
    assert r.fair == {} and r.get_lens("SNOW") == "auto"
    r.remove("SNOW")
    assert r.tickers == []


def test_reads_legacy_fair_pe(tmp_path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": ["MSFT"], "fair_pe": {"MSFT": 30}}))
    assert W.load(p).get_fair("MSFT", "pe") == 30.0


def test_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "wl.json"
    p.write_text("not json")
    assert W.load(p).tickers == W.STARTER
