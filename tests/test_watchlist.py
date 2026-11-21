from analysis import watchlist as W


def test_roundtrip_and_edits(tmp_path):
    p = tmp_path / "wl.json"
    w = W.load(p)
    assert w.tickers == W.STARTER  # missing file -> starter list
    w = W.Watchlist()
    assert w.add("msft") and not w.add("MSFT")
    w.set_fair_pe("MSFT", 30)
    w.set_note("MSFT", " Azure ")
    W.save(w, p)
    r = W.load(p)
    assert r.tickers == ["MSFT"] and r.fair_pe == {"MSFT": 30.0} and r.notes == {"MSFT": "Azure"}
    r.set_fair_pe("MSFT", None)
    r.remove("MSFT")
    assert r.tickers == [] and not r.fair_pe and not r.notes


def test_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "wl.json"
    p.write_text("not json")
    assert W.load(p).tickers == W.STARTER
