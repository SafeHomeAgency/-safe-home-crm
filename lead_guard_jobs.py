"""
SAIRO — Lead Protection Engine-ის ფონური ციკლი (ბოტის JobQueue-დან; ლოგიკა აქ, რომ ტესტირებადი იყოს — იგივე ნიმუში, რაც hubmeet_jobs).

  * `prepare_cycle()` — აღმოაჩენს რისკებს, განაახლებს `LeadGuardLog`-ს, დაგეგმავს შეხსენებებს/ესკალაციებს და **გაგზავნამდე** იკავებს (claim) მათ;
    აბრუნებს გასაგზავნ შეტყობინებებს. `finish(msg, ok)` — ჩავარდნისას დაკავებას აუქმებს (შემდეგ ციკლზე ისევ ეცდება).
  * `prepare_digests()` — დღიური ანგარიში: თიმლიდერს — თავისი გუნდის, ადმინს — სრული; დღეში ერთხელ ადამიანზე (გასაღები ცხრილში — რესტარტი არ აორმაგებს).
  * `run_cycle_sync(send)` — იგივე სინქრონულად (ტესტი/დემო/ხელით გაშვება).
კლიენტებს/ჯგუფებს ეს ძრავა **არასდროს** წერს — მხოლოდ აგენტებს (მათ საკუთარ საქმეებზე) და მენეჯერებს/ადმინებს.
"""

from __future__ import annotations

import datetime
import logging

import config
import lead_guard as lg

log = logging.getLogger("safehome-leadguard-jobs")


def prepare_cycle(now: datetime.datetime | None = None, data: dict | None = None) -> list[dict]:
    now = now or lg._now()
    data = data if data is not None else lg.collect(now)
    if "agents" in data.get("errors", []):
        return []                                                   # აგენტების გარეშე ვერც რისკს ვადგენთ, ვერც მიმღებს
    risks, _gaps = lg.detect(now, data)
    lg.ensure_tabs()
    by_key = lg.sync_log(risks, lg.covered_kinds(data), now)
    msgs = []
    for act in lg.plan(now, risks, by_key, data["agents"]):
        claimed = lg.claim(act, now)
        if claimed:
            msgs.append(claimed)
    return msgs


def finish(msg: dict, ok: bool) -> None:
    if not ok:
        lg.release(msg)


def run_cycle_sync(send, now: datetime.datetime | None = None, data: dict | None = None) -> dict:
    """send(chat_id, text) -> bool. აბრუნებს სტატისტიკას."""
    stats = {"remind": 0, "escalate": 0, "failed": 0, "messages": []}
    for m in prepare_cycle(now, data):
        delivered = 0
        for cid in m["chat_ids"]:
            try:
                if send(cid, m["text"]):
                    delivered += 1
                    stats["messages"].append({"type": m["type"], "chat_id": cid, "keys": m["keys"], "text": m["text"]})
            except Exception:  # noqa: BLE001
                log.warning("LeadGuard: გაგზავნა ვერ მოხერხდა (%s)", cid, exc_info=True)
        finish(m, delivered > 0)                                           # ერთი მიმღებიც საკმარისია: დაკავება რჩება; ყველა ჩავარდა -> უკან
        if delivered:
            stats[m["type"]] += 1
        else:
            stats["failed"] += 1
    return stats


# ---------------------------------------------------------------- დღიური ანგარიში
def _digest_claim(key: str, chat_id: int, ts: str) -> bool:
    with lg._lock:  # noqa: SLF001
        rows = lg.log_rows(fresh=True)
        L = rows.get(key)
        if L is not None and str(L.get("status")) == "sent":
            return False
        if L is None:
            row = {h: "" for h in lg.HEADERS}
            row.update({"guard_key": key, "kind": "digest", "entity_id": str(chat_id), "first_seen": ts, "status": "sent"})
            lg._backend.append_many(lg.SHEET, lg.HEADERS, [row])  # noqa: SLF001
        else:
            lg._backend.update_many(lg.SHEET, lg.HEADERS, {key: {"status": "sent"}})  # noqa: SLF001
        return True


def prepare_digests(now: datetime.datetime | None = None, data: dict | None = None) -> list[dict]:
    now = now or lg._now()
    data = data if data is not None else lg.collect(now)
    if "agents" in data.get("errors", []) or lg.in_quiet_hours(now):
        return []
    lg.ensure_tabs()
    day, ts, out = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S"), []
    recipients: list[tuple[int, dict, str]] = []
    pilot = config.LEAD_GUARD_PILOT_TEAMS
    for cid in sorted(config.ADMIN_CHAT_IDS):
        recipients.append((cid, {"admin": True, "role": "admin"}, "📊 SAIRO — კლიენტების რისკები (" + ("პილოტი: " + ", ".join(sorted(pilot)) if pilot else "ყველა გუნდი") + ")"))
    for a in data["agents"]:
        if pilot and str(a.get("team", "")).strip() not in pilot:
            continue
        if str(a.get("role", "")).strip() == "team_lead" and lg._active(a) and lg._chat(a) and lg._chat(a) not in config.ADMIN_CHAT_IDS:  # noqa: SLF001
            recipients.append((lg._chat(a), {"role": "team_lead", "team": str(a.get("team", "")).strip(), "agent_id": str(a.get("agent_id"))},  # noqa: SLF001
                               f"📊 SAIRO — თქვენი გუნდის კლიენტების რისკები ({str(a.get('team', '')).strip() or '—'})"))
    for cid, viewer, heading in recipients:
        rep = lg.report(viewer, now, data, only_teams=pilot or None)
        if not rep["counts"]["total"] and not rep["data_errors"]:
            continue                                                # ცარიელ ანგარიშს არავის ვუგზავნით
        key = f"digest:{day}:{cid}"
        if _digest_claim(key, cid, ts):
            out.append({"type": "digest", "chat_id": cid, "text": lg.digest_text(rep, heading), "keys": [key], "digest_key": key})
    return out


def finish_digest(msg: dict, ok: bool) -> None:
    if not ok:
        with lg._lock:  # noqa: SLF001
            lg._backend.update_many(lg.SHEET, lg.HEADERS, {msg["digest_key"]: {"status": "failed"}})  # noqa: SLF001


def run_digests_sync(send, now: datetime.datetime | None = None, data: dict | None = None) -> list[dict]:
    sent = []
    for m in prepare_digests(now, data):
        try:
            ok = bool(send(m["chat_id"], m["text"]))
        except Exception:  # noqa: BLE001
            ok = False
        finish_digest(m, ok)
        if ok:
            sent.append(m)
    return sent
