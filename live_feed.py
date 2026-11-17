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


# ტექნიკური ჩანაწერები (ჟურნალები, worker-ის სიგნალი, სესიები) — მომხმარებლის ეკრანზე არაფერს ცვლის; ადრე ამაზე ყველა გახსნილი ეკრანი რამდენიმე წამში თავიდან იტვირთებოდა.
QUIET = {"AuditLog", "WorkerHeartbeat", "TgLog", "AiActions", "AiUsage", "AiLog", "AiConversations", "AiMessages", "LeadGuardLog", "NotificationLog", "Sessions", "RateLimit", "SystemHealth"}


def bump(name: str = "") -> None:
    global _seq, _at
    if name in QUIET or str(name).startswith(("Ai", "Log", "/internal/worker", "/api/ai/")):
        return
    with _lock:
        _seq += 1
        _at = time.time()
        if name:
            _names[str(name)[:60]] = _seq


def snapshot() -> dict:
    with _lock:
        return {"seq": _seq, "epoch": _epoch, "at": int(_at)}


def snapshot_since(since) -> dict:
    """snapshot + რა შეიცვალა `since`-ის მერე (ცხრილის სახელები / API გზები) — კლიენტი მხოლოდ საჭირო ეკრანს აახლებს."""
    out = snapshot()
    try:
        out["changed"] = changed_since(int(since))[:40] if since not in (None, "") else []
    except (TypeError, ValueError):
        out["changed"] = []
    return out


def changed_since(since: int) -> list[str]:
    with _lock:
        return [n for n, s in _names.items() if s > since]
