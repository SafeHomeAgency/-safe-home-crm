"""
ერთიანი შეტყობინებების რიგი (Telegram): დუბლირების გასაღები, ასინქრონული გაგზავნა, კონტროლირებადი განმეორება, სტატისტიკა.

რატომ: ადრე თითო მოდული თავისი გზით აგზავნიდა (სინქრონულად, მოთხოვნის შიგნით, ჩავარდნისას — დაკარგვა). ახლა ახალი/მნიშვნელოვანი
შეტყობინებები აქ გადის: მოთხოვნა არ ელოდება Telegram-ს, ჩავარდნისას მეორდება (5/30/120 წმ), ერთი და იგივე გასაღები კი ორჯერ არ იგზავნება.

ზღვარი (პატიოსნად): რიგი **მეხსიერებაშია** — პროცესის გადატვირთვისას ჯერ არ გაგზავნილი/განსამეორებელი შეტყობინებები იკარგება
(ბიზნეს-ოპერაცია ამით არ ზიანდება: ის ცალკე ინახება ცხრილში). ძველი ბილიკები (ბოტის მიღწევადი `context.bot`, check_new_tasks)
უცვლელია — მათი დაცვები (`notified`, `reminded`, `add_warning_once`) რჩება.

პრიორიტეტი: critical (ატვირთვის სისტემა/უსაფრთხოება — მეტი ცდა) | operational | info.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections import deque

log = logging.getLogger("safehome-notify")

PRIORITIES = ("critical", "operational", "info")
DEFAULT_RETRY_DELAYS = {"critical": (5, 30, 120, 600, 1800), "operational": (5, 30, 120), "info": (30,)}


class Notifier:
    def __init__(self, sender, *, retry_delays=None, dedupe_ttl: float = 86400.0, max_queue: int = 2000,
                 clock=time.time, autostart: bool = True):
        """sender(chat_id, text, reply_markup) -> True (გაიგზავნა) | False (დროებითი ჩავარდნა: განმეორება) | "drop" (მუდმივი: განმეორება უშედეგოა)."""
        self._sender = sender
        self._delays = retry_delays or DEFAULT_RETRY_DELAYS
        self._ttl = dedupe_ttl
        self._max = max_queue
        self._clock = clock
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._heap: list = []            # (due_ts, seq, item)
        self._seq = itertools.count()
        self._seen: dict[str, float] = {}  # dedupe key -> expiry
        self._failed = deque(maxlen=50)
        self._stats = {"queued": 0, "sent": 0, "deduped": 0, "retried": 0, "failed": 0, "dropped_full": 0}
        self._last_error = ""
        self._stop = False
        self._thread = None
        if autostart:
            self.start()

    # ------------------------------------------------------------------ API
    def notify(self, chat_id, text: str, *, key: str | None = None, priority: str = "operational",
               reply_markup=None) -> str:
        """აბრუნებს: "queued" | "deduped" | "dropped" (რიგი სავსეა / chat_id ცარიელია)."""
        if chat_id in (None, "") or not str(text or "").strip():
            return "dropped"
        priority = priority if priority in PRIORITIES else "operational"
        now = self._clock()
        with self._cv:
            dk = None
            if key:
                dk = f"{chat_id}:{key}"
                self._purge(now)
                if self._seen.get(dk, 0) > now:
                    self._stats["deduped"] += 1
                    return "deduped"
            if len(self._heap) >= self._max:
                self._stats["dropped_full"] += 1
                return "dropped"
            if dk:
                self._seen[dk] = now + self._ttl
            item = {"chat_id": chat_id, "text": str(text), "key": dk, "priority": priority, "markup": reply_markup,
                    "attempt": 0, "created": now}
            heapq.heappush(self._heap, (now, next(self._seq), item))
            self._stats["queued"] += 1
            self._cv.notify()
        return "queued"

    def notify_many(self, chat_ids, text: str, *, key: str | None = None, priority: str = "operational") -> dict:
        out = {"queued": 0, "deduped": 0, "dropped": 0}
        for cid in chat_ids or []:
            out[self.notify(cid, text, key=key, priority=priority)] += 1
        return out

    def stats(self) -> dict:
        now = self._clock()
        with self._lock:
            oldest = min((it["created"] for _, _, it in self._heap), default=None)
            return {**self._stats, "pending": len(self._heap), "oldest_pending_s": None if oldest is None else int(now - oldest),
                    "last_error": self._last_error, "recent_failed": list(self._failed)[-5:]}

    # ------------------------------------------------------------------ worker
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="notify-outbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def _purge(self, now: float) -> None:
        """ვადაგასული დედუპლიკაციის გასაღებების გასუფთავება (მეხსიერების დასაცავად, მხოლოდ როცა ბევრია)."""
        if len(self._seen) > 2000:
            for k in [k for k, exp in self._seen.items() if exp <= now]:
                self._seen.pop(k, None)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._stop and (not self._heap or self._heap[0][0] > self._clock()):
                    wait = None if not self._heap else max(0.05, self._heap[0][0] - self._clock())
                    self._cv.wait(timeout=wait if wait is None else min(wait, 5.0))
                if self._stop:
                    return
                _, _, item = heapq.heappop(self._heap)
            self._deliver(item)

    def _deliver(self, item: dict) -> None:
        try:
            res = self._sender(item["chat_id"], item["text"], item["markup"])
        except Exception as e:  # noqa: BLE001 — გაგზავნის შეცდომამ ნართი არ უნდა გააჩეროს
            res = False
            self._last_error = f"{type(e).__name__}: {str(e)[:120]}"
        if res is True:
            with self._lock:
                self._stats["sent"] += 1
            return
        delays = self._delays.get(item["priority"], DEFAULT_RETRY_DELAYS["operational"])
        if res != "drop" and item["attempt"] < len(delays):
            delay = delays[item["attempt"]]
            item["attempt"] += 1
            with self._cv:
                self._stats["retried"] += 1
                heapq.heappush(self._heap, (self._clock() + delay, next(self._seq), item))
                self._cv.notify()
            return
        with self._lock:
            self._stats["failed"] += 1
            self._failed.append({"chat_id": str(item["chat_id"]), "key": item["key"], "priority": item["priority"],
                                 "attempts": item["attempt"] + 1, "reason": "drop" if res == "drop" else "retries_exhausted"})
            if item["key"]:
                self._seen.pop(item["key"], None)   # მომავალმა ახალმა მოვლენამ იგივე გასაღებით ხელახლა სცადოს

    # ტესტებისთვის: რიგის სინქრონული დაცლა (დაგეგმილი განმეორებების დროის გარეშე)
    def drain_now(self, max_rounds: int = 20) -> None:
        for _ in range(max_rounds):
            with self._cv:
                if not self._heap:
                    return
                _, _, item = heapq.heappop(self._heap)
            self._deliver(item)


# ------------------------------------------------------------------ პროცესის ერთადერთი ეგზემპლარი
_default: Notifier | None = None


def configure(sender, **kw) -> Notifier:
    global _default
    if _default is not None:
        _default.stop()
    _default = Notifier(sender, **kw)
    return _default


def default() -> Notifier | None:
    return _default
