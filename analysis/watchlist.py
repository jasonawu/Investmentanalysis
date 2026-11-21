"""Watchlist persistence: a small JSON file next to the app (path overridable by WATCHLIST_PATH).

Format:
{
  "tickers": ["MSFT", "GOOGL"],
  "fair_pe": {"MSFT": 30.0},          # optional: your own fair forward P/E per stock
  "notes":   {"MSFT": "Azure growth"} # optional: one-line thesis
}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("WATCHLIST_PATH", Path(__file__).resolve().parent.parent / "watchlist.json"))
STARTER = ["DEMO", "DEMOA", "DEMOB", "DEMOC", "DEMOD", "DEMOE", "DEMOF"]


@dataclass
class Watchlist:
    tickers: list[str] = field(default_factory=list)
    fair_pe: dict[str, float] = field(default_factory=dict)
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
        self.fair_pe.pop(t, None)
        self.notes.pop(t, None)

    def set_fair_pe(self, ticker: str, pe: float | None) -> None:
        t = ticker.upper()
        if pe and pe > 0:
            self.fair_pe[t] = float(pe)
        else:
            self.fair_pe.pop(t, None)

    def set_note(self, ticker: str, note: str | None) -> None:
        t = ticker.upper()
        if note and note.strip():
            self.notes[t] = note.strip()
        else:
            self.notes.pop(t, None)


def load(path: Path = DEFAULT_PATH) -> Watchlist:
    try:
        d = json.loads(Path(path).read_text())
        return Watchlist(tickers=[t.upper() for t in d.get("tickers", [])],
                         fair_pe={k.upper(): float(v) for k, v in d.get("fair_pe", {}).items()},
                         notes={k.upper(): str(v) for k, v in d.get("notes", {}).items()})
    except FileNotFoundError:
        return Watchlist(tickers=list(STARTER))
    except (ValueError, TypeError, AttributeError):
        return Watchlist(tickers=list(STARTER))


def save(w: Watchlist, path: Path = DEFAULT_PATH) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps({"tickers": w.tickers, "fair_pe": w.fair_pe, "notes": w.notes}, indent=2))
    tmp.replace(path)
