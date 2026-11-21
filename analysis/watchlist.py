"""Watchlist persistence: a small JSON file next to the app (path overridable by WATCHLIST_PATH).

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


def load(path: Path = DEFAULT_PATH) -> Watchlist:
    try:
        d = json.loads(Path(path).read_text())
        fair = {k.upper(): {m: float(x) for m, x in v.items()} for k, v in d.get("fair", {}).items()}
        for k, v in d.get("fair_pe", {}).items():  # legacy format
            fair.setdefault(k.upper(), {}).setdefault("pe", float(v))
        return Watchlist(tickers=[t.upper() for t in d.get("tickers", [])], fair=fair,
                         lens={k.upper(): v for k, v in d.get("lens", {}).items() if v in LENSES},
                         notes={k.upper(): str(v) for k, v in d.get("notes", {}).items()})
    except FileNotFoundError:
        return Watchlist(tickers=list(STARTER))
    except (ValueError, TypeError, AttributeError):
        return Watchlist(tickers=list(STARTER))


def save(w: Watchlist, path: Path = DEFAULT_PATH) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps({"tickers": w.tickers, "fair": w.fair, "lens": w.lens, "notes": w.notes}, indent=2))
    tmp.replace(path)
