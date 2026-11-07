"""
Live-განახლება (ეკონომიური): სერვერზე ერთი მრიცხველი `seq`, რომელიც იზრდება ყოველ ცვლილებაზე (ნებისმიერი წარმატებული POST/PUT/PATCH/DELETE API-ზე + ბოტის/ფონური ჩაწერები კეშის გაუქმებისას).
კლიენტი ყოველ ~7 წამში ეკითხება `/api/live` — ეს **ცხრილს არ კითხულობს** (Google Sheets-ის ლიმიტს არ ჭამს); მრიცხველი შეიცვალა -> ეკრანი თავისით განახლდება (თუ მომხმარებელი არაფერს წერს).
ერთი რეპლიკა (Railway-ზე ახლა 1) — მრიცხველი პროცესის მეხსიერებაშია; რესტარტზე ახალი ეპოქა (epoch) -> კლიენტი ერთხელ განახლდება.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_seq = 0
_epoch = int(time.time())
_at = 0.0
_names: dict[str, int] = {}


def bump(name: str = "") -> None:
    global _seq, _at
    with _lock:
        _seq += 1
        _at = time.time()
        if name:
            _names[str(name)[:60]] = _seq


def snapshot() -> dict:
    with _lock:
        return {"seq": _seq, "epoch": _epoch, "at": int(_at)}


def changed_since(since: int) -> list[str]:
    with _lock:
        return [n for n, s in _names.items() if s > since]
