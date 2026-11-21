"""Watchlist persistence.

Where it is stored:
  * WATCHLIST_GITHUB_TOKEN set (environment variable or a Streamlit secret): a secret gist in that
    GitHub account, so the watchlist survives restarts of the hosted website version.
  * otherwise: a JSON file next to the app (path overridable by WATCHLIST_PATH).

Format:
{
  "tickers": ["MSFT", "SNOW"],
  "fair":  {"MSFT": {"pe": 30.0}, "SNOW": {"ps": 12.0}},   # optional: your own fair multiples
  "lens":  {"SNOW": "ps"},                                  # optional: valuation lens per stock (default auto)
  "notes": {"MSFT": "Azure growth"}                         # optional: one-line thesis
}
Files written by earlier versions ("fair_pe": {"MSFT": 30}) are read as {"pe": 30}.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("WATCHLIST_PATH", Path(__file__).resolve().parent.parent / "watchlist.json"))
STARTER = ["DEMO", "DEMOA", "DEMOB", "DEMOC", "DEMOD", "DEMOE", "DEMOF", "DEMOG", "DEMOH"]
LENSES = ("auto", "pe", "ev_ebitda", "ps")


@dataclass
class Watchlist:
    tickers: list[str] = field(default_factory=list)
    fair: dict[str, dict[str, float]] = field(default_factory=dict)
    lens: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    # Not saved: set when the stored copy could not be read, so a save can't overwrite it with a blank list.
    load_error: str | None = field(default=None, compare=False)

    def add(self, ticker: str) -> bool:
        t = ticker.strip().upper()
        if t and t not in self.tickers:
            self.tickers.append(t)
            return True
        return False

    def remove(self, ticker: str) -> None:
        t = ticker.upper()
        self.tickers = [x for x in self.tickers if x != t]
        for d in (self.fair, self.lens, self.notes):
            d.pop(t, None)

    def set_fair(self, ticker: str, metric: str, value: float | None) -> None:
        t = ticker.upper()
        d = self.fair.setdefault(t, {})
        if value and value > 0:
            d[metric] = float(value)
        else:
            d.pop(metric, None)
        if not d:
            self.fair.pop(t, None)

    def get_fair(self, ticker: str, metric: str) -> float | None:
        return self.fair.get(ticker.upper(), {}).get(metric)

    def set_lens(self, ticker: str, lens: str | None) -> None:
        t = ticker.upper()
        if lens and lens != "auto" and lens in LENSES:
            self.lens[t] = lens
        else:
            self.lens.pop(t, None)

    def get_lens(self, ticker: str) -> str:
        return self.lens.get(ticker.upper(), "auto")

    def set_note(self, ticker: str, note: str | None) -> None:
        t = ticker.upper()
        if note and note.strip():
            self.notes[t] = note.strip()
        else:
            self.notes.pop(t, None)


class WatchlistSaveError(RuntimeError):
    pass


def from_dict(d: dict) -> Watchlist:
    fair = {k.upper(): {m: float(x) for m, x in v.items()} for k, v in d.get("fair", {}).items()}
    for k, v in d.get("fair_pe", {}).items():  # legacy format
        fair.setdefault(k.upper(), {}).setdefault("pe", float(v))
    return Watchlist(tickers=[t.upper() for t in d.get("tickers", [])], fair=fair,
                     lens={k.upper(): v for k, v in d.get("lens", {}).items() if v in LENSES},
                     notes={k.upper(): str(v) for k, v in d.get("notes", {}).items()})


def to_dict(w: Watchlist) -> dict:
    return {"tickers": w.tickers, "fair": w.fair, "lens": w.lens, "notes": w.notes}


# --------------------------------------------------------------------------- #
# Storage backends
# --------------------------------------------------------------------------- #
class FileStore:
    where = "a file on the computer running the app"
    persistent_on_web = False

    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)

    def read(self) -> dict | None:
        """Stored data, or None when nothing has been saved yet."""
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except ValueError:
            return None  # unreadable local file: start fresh (it is overwritten on the next save)

    def write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)


class GistStore:
    """Watchlist kept in a secret gist of the GitHub account that owns the token (needs the 'gist' scope)."""

    FILENAME = "investment-dashboard-watchlist.json"
    API = "https://api.github.com"
    where = "your GitHub account (a secret gist)"
    persistent_on_web = True
    _gist_ids: dict[str, str] = {}             # token -> gist id, found once per process
    _cache: dict[str, tuple[float, dict]] = {}  # token -> (time read, data)
    CACHE_SECONDS = 20

    def __init__(self, token: str, http=None):
        self.token = token
        if http is None:
            import requests
            http = requests.Session()
        self.http = http

    def _call(self, method: str, url: str, **kw):
        r = self.http.request(method, url, timeout=15, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}, **kw)
        if r.status_code == 401:
            raise RuntimeError("GitHub rejected the token (expired or mistyped). Create a new one; see README.")
        if r.status_code == 403 or r.status_code == 404 and method != "GET":
            raise RuntimeError("GitHub refused the request. Check that the token has the 'gist' permission "
                               "(see README).")
        r.raise_for_status()
        return r.json() if r.content else {}

    def _find_gist(self) -> str | None:
        if self.token in self._gist_ids:
            return self._gist_ids[self.token]
        page = 1
        while page <= 10:
            gists = self._call("GET", f"{self.API}/gists", params={"per_page": 100, "page": page})
            for g in gists:
                if self.FILENAME in (g.get("files") or {}):
                    self._gist_ids[self.token] = g["id"]
                    return g["id"]
            if len(gists) < 100:
                break
            page += 1
        return None

    def read(self) -> dict | None:
        hit = self._cache.get(self.token)
        if hit and time.time() - hit[0] < self.CACHE_SECONDS:
            return json.loads(json.dumps(hit[1]))  # copy
        gid = self._find_gist()
        if gid is None:
            return None
        g = self._call("GET", f"{self.API}/gists/{gid}")
        f = (g.get("files") or {}).get(self.FILENAME) or {}
        content = f.get("content")
        if f.get("truncated") and f.get("raw_url"):
            content = self.http.get(f["raw_url"], timeout=15).text
        data = json.loads(content) if content else None
        if data is not None:
            self._cache[self.token] = (time.time(), data)
        return data

    def write(self, data: dict) -> None:
        body = {"files": {self.FILENAME: {"content": json.dumps(data, indent=2)}}}
        gid = self._find_gist()
        if gid is None:
            g = self._call("POST", f"{self.API}/gists", json={
                **body, "public": False, "description": "Investment dashboard watchlist (saved by the app)"})
            self._gist_ids[self.token] = g["id"]
        else:
            self._call("PATCH", f"{self.API}/gists/{gid}", json=body)
        self._cache[self.token] = (time.time(), data)


def storage():
    token = os.environ.get("WATCHLIST_GITHUB_TOKEN", "").strip()
    return GistStore(token) if token else FileStore(DEFAULT_PATH)


def load(path: Path | None = None, store=None) -> Watchlist:
    store = store or (FileStore(path) if path is not None else storage())
    try:
        data = store.read()
    except Exception as e:  # network or permission problem: keep the stored copy safe
        w = Watchlist(tickers=list(STARTER))
        w.load_error = str(e) or e.__class__.__name__
        return w
    if data is None:
        return Watchlist(tickers=list(STARTER))
    try:
        return from_dict(data)
    except (ValueError, TypeError, AttributeError):
        return Watchlist(tickers=list(STARTER))


def save(w: Watchlist, path: Path | None = None, store=None) -> None:
    if w.load_error:
        raise WatchlistSaveError("Not saved: the stored watchlist couldn't be read, and saving now could "
                                 f"overwrite it. ({w.load_error})")
    store = store or (FileStore(path) if path is not None else storage())
    try:
        store.write(to_dict(w))
    except Exception as e:
        raise WatchlistSaveError(f"Not saved: {e}") from e
