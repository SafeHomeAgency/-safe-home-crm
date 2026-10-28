"""
ატვირთვის ძრავის რეალური ჯანმრთელობა — „heartbeat მოდის“ არ ნიშნავს „job-ებს იღებს“.

სიგნალები:
  * heartbeat (ცალკე ტაიმერი ექსთენშენში) — ცოცხალია თუ არა პროცესი;
  * `/next` გამოძახებების დრო (სერვერზე, მეხსიერებაში) — **ციკლი რეალურად იღებს თუ არა job-ს**. გამორთული/დაპაუზებული/შესვლის მომლოდინე
    ექსთენშენი heartbeat-ს აგზავნის, მაგრამ `/next`-ს არა; ეს მუშაობს ძველ ექსთენშენზეც (ვერსიის განახლების გარეშე);
  * status-ის სტრიქონი (ახალი ექსთენშენი): `online-v11|st=paused|rs=<მიზეზი>|ca=<წმ>` — ზუსტი მდგომარეობა და მიზეზი.
    ძველი ფორმატი (`online-v10`) ასევე იკითხება.

მხოლოდ ხელშეკრულებისა და ლოგიკის ფუნქციებია — Sheets/Flask-ზე დამოკიდებულება არ აქვს, ამიტომ ტესტირებადია.
"""

from __future__ import annotations

import threading
import time

STATES = ("idle", "busy", "disabled", "paused", "login", "unknown")
STATE_LABELS = {
    "idle": "ველოდება job-ს", "busy": "მუშაობს job-ზე", "disabled": "გამორთულია (▶ ჩართვა)",
    "paused": "დაპაუზებულია", "login": "ელოდება MyHome-ში შესვლას", "unknown": "მდგომარეობა უცნობია",
}

_polls: dict[str, float] = {}
_lock = threading.Lock()
_started = time.time()


def note_poll(label: str, now: float | None = None) -> None:
    """`/next` გამოძახება ამ იარლიყიდან (ციკლი ცოცხალია და job-ს ითხოვს)."""
    label = str(label or "").strip()
    if label:
        with _lock:
            _polls[label] = time.time() if now is None else now


def last_poll_age(label: str, now: float | None = None) -> float | None:
    with _lock:
        t = _polls.get(str(label or "").strip())
    if t is None:
        return None
    return (time.time() if now is None else now) - t


def reset_for_tests() -> None:
    with _lock:
        _polls.clear()


def process_uptime(now: float | None = None) -> float:
    return (time.time() if now is None else now) - _started


def parse_status(status: str) -> dict:
    """`online-v11|st=paused|rs=balance|ca=12` -> {version, base, state, reason, claim_age_s}. ძველი `online-v10`/`busy-v10` — state None."""
    parts = str(status or "").split("|")
    base = parts[0].strip()
    out = {"base": base, "version": base.split("-", 1)[1] if "-" in base else "", "state": None, "reason": "", "claim_age_s": None}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        if k == "st" and v in STATES:
            out["state"] = v
        elif k == "rs":
            out["reason"] = v[:60]
        elif k == "ca":
            try:
                out["claim_age_s"] = int(v)
            except ValueError:
                pass
    if out["state"] is None and base.startswith("busy"):
        out["state"] = "busy"
    return out


def worker_view(hb: dict, hb_age: float | None, stale_after: float, poll_age: float | None, poll_stale: float,
                server_uptime: float | None = None) -> dict:
    """ერთი worker-ის ერთიანი სურათი. `loop_alive`: busy -> True; სხვა შემთხვევაში `/next` ახლახან იყო. სერვერის ახლად ჩართვისას
    (poll_stale-ზე ნაკლები uptime) `/next`-ის უქონლობა ჯერ არაფერს ნიშნავს -> loop_alive None."""
    p = parse_status(hb.get("status"))
    online = hb_age is not None and hb_age <= stale_after
    state = p["state"]
    if state is None:
        state = "busy" if str(hb.get("current_job_id") or "").strip() else "unknown"
    if not online:
        loop_alive = False
    elif state == "busy":
        loop_alive = True
    elif poll_age is not None:
        loop_alive = poll_age <= poll_stale
    elif server_uptime is not None and server_uptime < poll_stale:
        loop_alive = None
    else:
        loop_alive = False
    healthy = bool(online and loop_alive is not False and state in ("idle", "busy", "unknown"))
    return {"worker_id": hb.get("worker_id"), "online": online, "age_seconds": None if hb_age is None else int(hb_age),
            "version": p["version"], "state": state, "state_label": STATE_LABELS.get(state, state), "reason": p["reason"],
            "poll_age_seconds": None if poll_age is None else int(poll_age), "loop_alive": loop_alive,
            "healthy": healthy}


def diagnose_queued(jobs: list[dict], views_by_label: dict, label_teams: dict, agents_team: dict,
                    now_server_naive, parse_dt, wait_minutes: float) -> list[dict]:
    """QUEUED job-ები, რომლებიც `wait_minutes`-ზე დიდხანს დგას, + სავარაუდო მიზეზი.

    views_by_label: label -> worker_view (ან არარსებობა); label_teams: label -> {team ids}; agents_team: agent_id -> team.
    მიზეზები: no_worker | offline | disabled | paused | login | not_polling | team_mismatch | busy | queue_backlog."""
    out = []
    busy_count: dict[str, int] = {}
    for j in jobs:
        if str(j.get("status")) == "PROCESSING":
            busy_count[str(j.get("manager_label") or "")] = busy_count.get(str(j.get("manager_label") or ""), 0) + 1
    for j in jobs:
        if str(j.get("status")) != "QUEUED":
            continue
        created = parse_dt(j.get("created_at"))
        if not created:
            continue
        due = parse_dt(j.get("next_retry_at")) if str(j.get("next_retry_at") or "").strip() else None
        if due and due > now_server_naive:
            continue                      # დაგეგმილი ავტო-retry — ჯერ არ ელოდება
        age_min = (now_server_naive - created).total_seconds() / 60
        if age_min < wait_minutes:
            continue
        label = str(j.get("manager_label") or "").strip()
        allowed = label_teams.get(label.lower()) or set()
        if allowed and (str(j.get("team") or "").strip() not in allowed
                        or str(agents_team.get(str(j.get("agent_id")), "")).strip() not in allowed):
            cause, detail = "team_mismatch", f"აგენტი/გუნდი არ ეკუთვნის ანგარიშს „{label}“ (გუნდები: {', '.join(sorted(allowed))})"
        else:
            v = views_by_label.get(label)
            if v is None:
                cause, detail = "no_worker", f"ანგარიშ „{label}“-ს worker საერთოდ არ გამოუჩენია"
            elif not v["online"]:
                cause, detail = "offline", f"worker ოფლაინია ({v['age_seconds']} წმ-ია signal არ მოსულა)" if v["age_seconds"] is not None else "worker ოფლაინია"
            elif v["state"] in ("disabled", "paused", "login"):
                cause, detail = v["state"], v["state_label"] + (f": {v['reason']}" if v["reason"] else "")
            elif v["loop_alive"] is False:
                cause, detail = "not_polling", "heartbeat ცოცხალია, მაგრამ job-ს არ ითხოვს (გამორთული/დაპაუზებული/შესვლის მომლოდინე ან გაჭედილი)"
            elif v["state"] == "busy" or busy_count.get(label):
                cause, detail = "busy", "worker სხვა job-ზე მუშაობს — რიგი მიდის"
            else:
                cause, detail = "queue_backlog", "worker ჯანმრთელია; დაელოდეთ რიგს"
        out.append({"job_id": str(j.get("job_id")), "label": label, "age_min": int(age_min), "cause": cause, "detail": detail,
                    "agent_name": j.get("agent_name", ""), "source_id": j.get("myhome_listing_id", "")})
    out.sort(key=lambda r: -r["age_min"])
    return out
