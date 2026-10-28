"""
სისტემის ჯანმრთელობის დაფის წმინდა ლოგიკა (Flask/Sheets-ისგან დამოუკიდებელი, ტესტირებადი).

პრინციპი: „მწვანე“ მხოლოდ მაშინ, როცა კომპონენტი **რეალურად მუშაობს** (job ბოლოს გაეშვა, worker job-ს ითხოვს, რიგი არ დგას), და არა იმიტომ, რომ
სერვერი პასუხობს. ყველა მაჩვენებელს აქვს წყარო და ზღვარი; რაც არ ვიცით — `unknown` (არა მწვანე).
"""

from __future__ import annotations

import re
import threading
import time

_lock = threading.Lock()
_jobs: dict[str, dict] = {}           # bot job name -> {last_ok, last_run, last_error, runs, errors, interval}
_api = {"last_ok": None, "last_5xx": None, "count": 0, "errors_5xx": 0}


# ------------------------------------------------------------------ ბოტის ფონური job-ები
def record_job(name: str, ok: bool, error: str = "", interval: float | None = None, now: float | None = None) -> None:
    t = time.time() if now is None else now
    with _lock:
        d = _jobs.setdefault(name, {"last_ok": None, "last_run": None, "last_error": "", "runs": 0, "errors": 0, "interval": interval})
        d["last_run"] = t
        d["runs"] += 1
        if interval:
            d["interval"] = interval
        if ok:
            d["last_ok"] = t
        else:
            d["errors"] += 1
            d["last_error"] = str(error)[:160]


def jobs_snapshot(now: float | None = None) -> list[dict]:
    """ყოველი job: ok | late (ინტერვალზე 2.5-ჯერ დიდხანს არ გაშვებულა) | failing (ბოლო გაშვება ჩავარდა) | never (ჯერ არ გაშვებულა)."""
    t = time.time() if now is None else now
    out = []
    with _lock:
        for name, d in sorted(_jobs.items()):
            age = None if d["last_run"] is None else int(t - d["last_run"])
            if d["last_run"] is None:
                status = "never"
            elif d["last_ok"] != d["last_run"]:
                status = "failing"
            elif d["interval"] and age is not None and age > d["interval"] * 2.5 + 30:
                status = "late"
            else:
                status = "ok"
            out.append({"name": name, "status": status, "age_seconds": age, "runs": d["runs"], "errors": d["errors"],
                        "last_error": d["last_error"], "interval": d["interval"]})
    return out


# ------------------------------------------------------------------ API
def note_request(status_code: int, now: float | None = None) -> None:
    t = time.time() if now is None else now
    with _lock:
        _api["count"] += 1
        if status_code >= 500:
            _api["errors_5xx"] += 1
            _api["last_5xx"] = t
        else:
            _api["last_ok"] = t


def api_snapshot(now: float | None = None) -> dict:
    t = time.time() if now is None else now
    with _lock:
        return {"requests": _api["count"], "errors_5xx": _api["errors_5xx"],
                "last_ok_age_s": None if _api["last_ok"] is None else int(t - _api["last_ok"]),
                "last_5xx_age_s": None if _api["last_5xx"] is None else int(t - _api["last_5xx"])}


def reset_for_tests() -> None:
    with _lock:
        _jobs.clear()
        _api.update(last_ok=None, last_5xx=None, count=0, errors_5xx=0)


# ------------------------------------------------------------------ ატვირთვის სტატისტიკა
_ERROR_CLASSES = [
    ("payment", r"MYHOME_PAYMENT_ERROR|გადახდ|ბალანს"),
    ("login", r"NOT_LOGGED_IN|SSGE_NOT_LOGGED_IN|შესულ"),
    ("cloudflare", r"MYHOME_CHALLENGE|Cloudflare"),
    ("listing_gone", r"LISTING_UNAVAILABLE|წაშლილ|არ არსებობს"),
    ("owner_phone", r"PHONE_MISSING|ნომერი არ არის"),
    ("photos", r"ფოტო"),
    ("ssge_form", r"SSGE_"),
    ("worker_lost", r"stale|გაითიშა|worker"),
]


def classify_error(msg: str) -> str:
    m = str(msg or "")
    if not m.strip():
        return "unknown"
    for name, pat in _ERROR_CLASSES:
        if re.search(pat, m, re.I):
            return name
    return "other"


def portal_of(job: dict) -> str:
    tgt = str(job.get("publish_target") or "myhome").strip().lower() or "myhome"
    return {"myhome": "MyHome", "ssge": "ss.ge", "both": "MyHome+ss.ge"}.get(tgt, tgt)


def upload_stats(jobs: list[dict], now_server_naive, parse_dt, hours: float = 24.0) -> dict:
    """ბოლო `hours` საათის job-ები: რაოდენობები, წარმატების %, შეცდომების ჯგუფები (პორტალისა და ტიპის მიხედვით), განმეორებადი შეცდომები (≥3)."""
    window = []
    for j in jobs:
        c = parse_dt(j.get("created_at"))
        if c and 0 <= (now_server_naive - c).total_seconds() <= hours * 3600:
            window.append(j)
    by_status: dict[str, int] = {}
    for j in window:
        by_status[str(j.get("status"))] = by_status.get(str(j.get("status")), 0) + 1
    done = by_status.get("COMPLETED", 0)
    failed = by_status.get("FAILED", 0)
    finished = done + failed
    groups: dict[tuple, int] = {}
    for j in window:
        if str(j.get("status")) == "FAILED":
            k = (portal_of(j), classify_error(j.get("error_message")))
            groups[k] = groups.get(k, 0) + 1
    failures = [{"portal": p, "class": c, "count": n, "repeating": n >= 3}
                for (p, c), n in sorted(groups.items(), key=lambda kv: -kv[1])]
    return {"hours": hours, "total": len(window), "by_status": by_status, "completed": done, "failed": failed,
            "success_pct": None if not finished else round(100 * done / finished, 1), "failures": failures,
            "repeating": [f for f in failures if f["repeating"]]}


def queue_snapshot(jobs: list[dict], now_server_naive, parse_dt) -> dict:
    q = [j for j in jobs if str(j.get("status")) == "QUEUED"]
    p = [j for j in jobs if str(j.get("status")) == "PROCESSING"]
    oldest = None
    for j in q:
        c = parse_dt(j.get("created_at"))
        if c:
            age = (now_server_naive - c).total_seconds()
            oldest = age if oldest is None else max(oldest, age)
    oldest_p = None
    for j in p:
        c = parse_dt(j.get("started_at")) or parse_dt(j.get("created_at"))
        if c:
            age = (now_server_naive - c).total_seconds()
            oldest_p = age if oldest_p is None else max(oldest_p, age)
    return {"queued": len(q), "processing": len(p),
            "oldest_queued_min": None if oldest is None else int(oldest // 60),
            "oldest_processing_min": None if oldest_p is None else int(oldest_p // 60)}


def overall(components: dict) -> str:
    """ok | warn | bad — ყველაზე ცუდი კომპონენტის მიხედვით; unknown არ ითვლება „ok“-დ."""
    rank = {"ok": 0, "unknown": 1, "warn": 1, "bad": 2}
    worst = max((rank.get(str(c.get("level")), 1) for c in components.values()), default=1)
    return {0: "ok", 1: "warn", 2: "bad"}[worst]
