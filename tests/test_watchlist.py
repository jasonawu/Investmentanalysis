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


class _FakeResp:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data
        self.content = b"x" if data is not None else b""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeGitHub:
    """Minimal stand-in for the GitHub gists API."""

    def __init__(self, fail=None):
        self.gists, self.calls, self.fail = {}, [], fail

    def request(self, method, url, params=None, json=None, **kw):
        self.calls.append((method, url))
        if self.fail:
            return _FakeResp(self.fail, {})
        if method == "GET" and url.endswith("/gists"):
            return _FakeResp(200, [{"id": k, "files": {n: {} for n in v}} for k, v in self.gists.items()])
        if method == "POST":
            gid = f"g{len(self.gists) + 1}"
            self.gists[gid] = {n: f["content"] for n, f in json["files"].items()}
            assert json["public"] is False
            return _FakeResp(201, {"id": gid})
        gid = url.rsplit("/", 1)[-1]
        if method == "PATCH":
            self.gists[gid].update({n: f["content"] for n, f in json["files"].items()})
            return _FakeResp(200, {"id": gid})
        return _FakeResp(200, {"files": {n: {"content": c} for n, c in self.gists[gid].items()}})


def _store(gh, token):
    W.GistStore._gist_ids.clear()
    W.GistStore._cache.clear()
    return W.GistStore(token, http=gh)


def test_gist_store_creates_then_updates_one_secret_gist():
    gh = _FakeGitHub()
    st = _store(gh, "t1")
    assert W.load(store=st).tickers == W.STARTER          # nothing saved yet
    w = W.Watchlist(tickers=["MSFT"])
    W.save(w, store=st)
    w.add("SNOW"); w.set_fair("SNOW", "ps", 12)
    W.save(w, store=st)
    assert len(gh.gists) == 1                             # updated in place, not duplicated
    fresh = _store(gh, "t1")                              # e.g. after the website restarts
    r = W.load(store=fresh)
    assert r.tickers == ["MSFT", "SNOW"] and r.get_fair("SNOW", "ps") == 12.0


def test_unreachable_storage_never_overwrites_saved_list():
    gh = _FakeGitHub()
    W.save(W.Watchlist(tickers=["AAPL"]), store=_store(gh, "t2"))
    gh.fail = 500
    w = W.load(store=_store(gh, "t2"))
    assert w.load_error
    w.add("XYZ")
    try:
        W.save(w, store=_store(gh, "t2"))
        raise AssertionError("save should have been refused")
    except W.WatchlistSaveError:
        pass
    gh.fail = None
    assert W.load(store=_store(gh, "t2")).tickers == ["AAPL"]


def test_bad_token_gives_plain_message():
    w = W.load(store=_store(_FakeGitHub(fail=401), "bad"))
    assert "token" in w.load_error.lower()


def test_storage_picks_gist_when_token_set(monkeypatch):
    monkeypatch.setenv("WATCHLIST_GITHUB_TOKEN", "abc")
    assert isinstance(W.storage(), W.GistStore)
    monkeypatch.delenv("WATCHLIST_GITHUB_TOKEN")
    assert isinstance(W.storage(), W.FileStore)
