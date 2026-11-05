"""
კადრების აყვანის (Recruitment) შენახვა და ლოგიკა: ცხრილები `Recruits` / `RecruitLog` / `RecruitSettings` / `RecruitAlerts` (tab_backend-ის ნიმუში),
Google Form-ის ცხრილიდან იმპორტი (მხოლოდ ახალი სტრიქონები; ჩვენი ცვლილებები ცხრილით არასდროს იწერება თავზე), ჩანაწერის განახლება ისტორიით,
სამუშაო სიები („დღეს დასარეკი“, „ხვალინდელი გასაუბრებები“), ვორონკა/სტატისტიკა, დროის სლოტები, შეტყობინებების დედუპლიკაცია (RecruitAlerts).
"""

from __future__ import annotations

import datetime
import logging
import threading
import uuid

import config
import crm_time
import recruit_model as m
import tab_backend

log = logging.getLogger("safehome-recruit")
_lock = threading.RLock()
SheetsBackend, MemoryBackend = tab_backend.make(m.ALL_TABS)
_backend = SheetsBackend()


class RecruitError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def now_dt() -> datetime.datetime:
    """ადგილობრივი (თბილისის) დრო **tzinfo-ს გარეშე** — ჩვენი თარიღები ცხრილში ასეთია; aware/naive შედარება 500-ს იძლეოდა."""
    return crm_time.local_now().replace(tzinfo=None)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")


def _s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


# ---------------------------------------------------------------------------------------------- პარამეტრები
def get_settings() -> dict:
    rows = {r.get("key"): r.get("value", "") for r in _backend.read(m.RECRUIT_SETTINGS)}
    resp = [x.strip() for x in (rows.get("responsible_ids") or ",".join(sorted(config.RECRUIT_RESPONSIBLE_IDS))).split(",") if x.strip()]
    try:
        hour = int(rows.get("remind_hour") or config.RECRUIT_REMIND_HOUR)
    except ValueError:
        hour = config.RECRUIT_REMIND_HOUR
    return {"responsible_ids": resp, "remind_hour": min(20, max(8, hour)), "templates": {k: rows.get("tpl_" + k, "") for k in ("confirm", "reminder", "noshow", "training")}}


def set_setting(key: str, value: str) -> None:
    with _lock:
        rows = _backend.read(m.RECRUIT_SETTINGS, fresh=True)
        if any(r.get("key") == key for r in rows):
            _backend.update(m.RECRUIT_SETTINGS, m.SETTINGS_HEADERS, key, {"value": value})
        else:
            _backend.append(m.RECRUIT_SETTINGS, m.SETTINGS_HEADERS, {"key": key, "value": value})


# ---------------------------------------------------------------------------------------------- წაკითხვა
def all_rows(fresh: bool = False) -> list[dict]:
    return _backend.read(m.RECRUITS, fresh=fresh)


def get(recruit_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in all_rows(fresh) if _s(r.get("recruit_id")) == _s(recruit_id)), None)


def log_for(recruit_id: str, limit: int = 60) -> list[dict]:
    rows = [r for r in _backend.read(m.RECRUIT_LOG) if _s(r.get("recruit_id")) == _s(recruit_id)]
    rows.reverse()                                          # ახალი ჩანაწერი პირველია; ერთი წუთის შიგნით — დამატების თანმიმდევრობით (სტაბილური სორტი)
    rows.sort(key=lambda r: _s(r.get("at")), reverse=True)
    return rows[:limit]


def _log(recruit_id: str, kind: str, text: str, by: dict | None) -> None:
    _backend.append(m.RECRUIT_LOG, m.LOG_HEADERS, {
        "log_id": uuid.uuid4().hex[:10], "recruit_id": recruit_id, "at": now_str(), "by_name": _s((by or {}).get("name") or "სისტემა", 80),
        "by_id": _s((by or {}).get("agent_id") or "", 40), "kind": kind, "text": _s(text, 500)})


# ---------------------------------------------------------------------------------------------- იმპორტი
def import_rows(parsed: list[dict], bootstrap: bool = False) -> dict:
    """parsed — map_row-ის შედეგები. უკვე არსებულ src_key-ს არ ვეხებთ (ჩვენი რედაქტირება არ იკარგება). bootstrap=True: ძველი ისტორიის
    პირველადი ჩატვირთვა — `silent`, რომ ძველ კანდიდატებზე შეტყობინებები არ წავიდეს. დუბლიკატი ტელეფონით აქტიურ ჩანაწერთან — მიეთითება კომენტარში."""
    now = now_dt()
    with _lock:
        existing = all_rows(fresh=True)
        have = {_s(r.get("src_key")) for r in existing if _s(r.get("src_key"))}
        phones = {_s(r.get("phone")): _s(r.get("name")) for r in existing if _s(r.get("phone")) and _s(r.get("closed")) != "yes"}
        added = skipped = dups = 0
        batch = []
        taken = {_s(r.get("recruit_id")) for r in existing}
        for rec in parsed:
            if rec["src_key"] in have:
                skipped += 1
                continue
            rid = "R" + rec["src_key"]
            if rid in taken:
                skipped += 1
                continue
            taken.add(rid)
            created = m.parse_dt(rec.get("created_at"))
            historic = bootstrap or created is None or now - created > datetime.timedelta(days=3)       # ძველი განაცხადი: შეტყობინება/„ახალი“ სია არ ეხება (ჩავარდნილი იმპორტის გაგრძელებისასაც)
            rec = dict(rec, recruit_id=rid, updated_at=now_str(), updated_by="import", silent="yes" if historic else "")
            if not historic and rec.get("stage") == "invited" and not rec.get("call_status"):
                rec["stage"] = "new"                                # ახალი განაცხადი = „ახალი, დასარეკი“, სანამ ვინმე არ დაუკავშირდება (სლოტი კანდიდატმა თავად აირჩია)
            if rec.get("phone") and rec["phone"] in phones and not historic:
                rec["comment"] = (f"⚠️ იგივე ნომერი აქვს: {phones[rec['phone']]}. " + _s(rec.get("comment"), 500)).strip()
                dups += 1
            if rec.get("phone"):
                phones[rec["phone"]] = rec["name"]
            batch.append(rec)
            have.add(rec["src_key"])
            added += 1
        # ჯგუფური ჩაწერა: ერთი მოთხოვნა 300 სტრიქონზე (სტრიქონ-სტრიქონ ჩაწერა Sheets-ის „Write requests per minute“ ლიმიტს ცდებოდა — 429)
        if batch:
            _backend.append_many(m.RECRUITS, m.HEADERS, batch)
            at, by = now_str(), "სისტემა"
            _backend.append_many(m.RECRUIT_LOG, m.LOG_HEADERS, [{
                "log_id": uuid.uuid4().hex[:10], "recruit_id": rec["recruit_id"], "at": at, "by_name": by, "by_id": "", "kind": "import",
                "text": "ძველი ცხრილიდან გადმოტანილია" if rec.get("silent") else "ფორმიდან შემოვიდა"} for rec in batch])
        return {"added": added, "skipped": skipped, "duplicates": dups, "bootstrap": bootstrap}


def sync(fetch=None, sheet_id: str = "", tab: str = "") -> dict:
    """Google Form-ის ცხრილიდან ახალი სტრიქონების გადმოტანა. ჩვენი ცხრილი ცარიელია => ბოოტსტრაპი (ძველი ისტორია, უხმოდ)."""
    fetch = fetch or m.fetch_sheet_rows
    header, rows = fetch(sheet_id or config.RECRUIT_SHEET_ID, tab or config.RECRUIT_SHEET_TAB)
    parsed = [p for p in (m.map_row(header, r) for r in rows) if p]
    with _lock:
        bootstrap = not all_rows(fresh=True)
    out = import_rows(parsed, bootstrap=bootstrap)
    out["source_rows"] = len(rows)
    return out


# ---------------------------------------------------------------------------------------------- განახლება
def _label(field: str, val: str) -> str:
    if field == "stage":
        return m.STAGES.get(val, val)
    if field == "call_status":
        return m.CALL_STATUS.get(val, val)
    return val or "—"


NAMES = {"name": "სახელი", "phone": "ტელეფონი", "age": "ასაკი", "interview_at": "გასაუბრება", "stage": "ეტაპი", "call_status": "ზარი", "attended": "გასაუბრებაზე იყო",
         "decision": "გადაწყვეტილება", "training_at": "ტრენინგი", "training_ok": "ტრენინგზე მოდის", "test_score": "ტესტი", "internship_at": "სტაჟირება",
         "hire": "აგვყავს", "staffed_at": "ჩაშტატება", "left_at": "წასვლა", "left_reason": "წასვლის მიზეზი", "comment": "კომენტარი", "responsible_id": "პასუხისმგებელი"}


def update(recruit_id: str, changes: dict, by: dict, comment: str = "") -> dict:
    """ველების განახლება + ისტორიაში ჩაწერა + ავტომატური ეტაპი (თუ ეტაპი პირდაპირ არ არის მითითებული) + დახურვის დროშა."""
    ch = m.clean_update(changes)
    with _lock:
        r = get(recruit_id, fresh=True)
        if not r:
            raise RecruitError("კანდიდატი ვერ მოიძებნა", 404)
        merged = dict(r, **ch)
        if "stage" not in ch:
            auto = m.infer_stage(merged)
            order = list(m.STAGES)
            cur = _s(r.get("stage")) or "new"
            if auto != cur and (order.index(auto) > order.index(cur) or auto in m.CLOSED_STAGES):
                ch["stage"] = auto                                  # ავტომატურად მხოლოდ წინ (ან დახურვა); უკან — მხოლოდ ხელით
        stage = ch.get("stage", _s(r.get("stage")))
        ch["closed"] = "yes" if stage in m.CLOSED_STAGES else ""
        ch["updated_at"], ch["updated_by"] = now_str(), _s((by or {}).get("name"), 80)
        ch["last_contact_at"] = now_str() if any(k in ch for k in ("call_status", "attended", "decision", "comment", "stage", "interview_at")) else _s(r.get("last_contact_at"))
        diffs = [f"{NAMES.get(k, k)}: {_label(k, _s(r.get(k)))} → {_label(k, v)}" for k, v in ch.items()
                 if k in NAMES and _s(r.get(k)) != _s(v) and k != "comment"]
        _backend.update(m.RECRUITS, m.HEADERS, _s(recruit_id), ch)
        if diffs:
            _log(recruit_id, "change", "; ".join(diffs), by)
        if "comment" in ch and _s(ch["comment"]) != _s(r.get("comment")):
            _log(recruit_id, "comment", ch["comment"], by)
        if comment:
            _log(recruit_id, "comment", comment, by)
        return get(recruit_id, fresh=True)


def create(data: dict, by: dict) -> dict:
    ch = m.clean_update(data)
    if not ch.get("name"):
        raise RecruitError("სახელი სავალდებულოა")
    with _lock:
        rec = {h: "" for h in m.HEADERS}
        rid = "R" + uuid.uuid4().hex[:11]
        rec.update(ch, recruit_id=rid, created_at=now_str(), source="manual", src_key="m" + rid, updated_at=now_str(), updated_by=_s((by or {}).get("name"), 80))
        rec["stage"] = ch.get("stage") or m.infer_stage(rec)
        rec["closed"] = "yes" if rec["stage"] in m.CLOSED_STAGES else ""
        _backend.append(m.RECRUITS, m.HEADERS, rec)
        _log(rid, "create", "დაემატა ხელით", by)
        return rec


# ---------------------------------------------------------------------------------------------- სიები / სტატისტიკა
def _dt(r: dict, key: str) -> datetime.datetime | None:
    return m.parse_dt(r.get(key))


def public(r: dict, now: datetime.datetime | None = None) -> dict:
    now = now or now_dt()
    out = {k: _s(r.get(k), 700) for k in m.HEADERS if k not in ("src_key", "silent")}
    out["phone_pretty"] = m.phone_pretty(out.get("phone", ""))
    out["stage_label"] = m.STAGES.get(out.get("stage") or "new", out.get("stage", ""))
    out["call_label"] = m.CALL_STATUS.get(out.get("call_status") or "", "")
    iv = _dt(r, "interview_at")
    if iv:
        days = (iv.date() - now.date()).days
        out["interview_in_days"] = days
        out["interview_day"] = "დღეს" if days == 0 else "ხვალ" if days == 1 else "გუშინ" if days == -1 else iv.strftime("%d.%m")
        out["interview_time"] = iv.strftime("%H:%M") if iv.strftime("%H:%M") != "00:00" else ""
    fc = _dt(r, "created_at")
    out["age_hours"] = round((now - fc).total_seconds() / 3600, 1) if fc else None
    return out


def _active(r: dict) -> bool:
    return _s(r.get("closed")) != "yes"


def lists(now: datetime.datetime | None = None) -> dict:
    """სამუშაო სიები მენეჯერისთვის: რას უნდა გაუკეთოს დღეს."""
    now = now or now_dt()
    today, tomorrow = now.date(), now.date() + datetime.timedelta(days=1)
    act = [r for r in all_rows() if _active(r)]
    new = [r for r in act if _s(r.get("stage")) == "new" and not _s(r.get("last_contact_at")) and not _s(r.get("silent"))]
    tomorrow_iv = [r for r in act if (d := _dt(r, "interview_at")) and d.date() == tomorrow and _s(r.get("stage")) in ("new", "invited", "confirmed")]
    today_iv = [r for r in act if (d := _dt(r, "interview_at")) and d.date() == today and _s(r.get("stage")) in ("new", "invited", "confirmed")]
    to_confirm = [r for r in tomorrow_iv if _s(r.get("call_status")) in ("", "repeat", "no_contact")]
    need_result = [r for r in act if (d := _dt(r, "interview_at")) and d < now - datetime.timedelta(minutes=60) and _s(r.get("stage")) in ("new", "invited", "confirmed") and not _s(r.get("attended"))]
    decisions = [r for r in act if _s(r.get("stage")) == "interviewed" and not _s(r.get("decision"))]
    training_tm = [r for r in act if (d := _dt(r, "training_at")) and d.date() == tomorrow and _s(r.get("training_ok")) != "yes"]
    key = lambda r: (_s(r.get("interview_at")) or "9", _s(r.get("created_at")))  # noqa: E731
    pack = lambda arr: [public(x, now) for x in sorted(arr, key=key)]  # noqa: E731
    return {"new": pack(new), "tomorrow": pack(tomorrow_iv), "today": pack(today_iv), "to_confirm": pack(to_confirm), "need_result": pack(need_result),
            "decisions": pack(decisions), "training_tomorrow": pack(training_tm)}


def stats(now: datetime.datetime | None = None, days: int = 90) -> dict:
    """ვორონკა, გადასვლის %, პასუხის სიჩქარე, გასაუბრებაზე გამოუცხადებლობა, რეკლამიდან ჩაშტატებამდე ბოლო N დღეში."""
    now = now or now_dt()
    since = now - datetime.timedelta(days=days)
    rows = [r for r in all_rows() if (d := _dt(r, "created_at")) and d >= since]
    order = list(m.STAGES)
    reached = lambda r, stg: (order.index(_s(r.get("stage")) or "new") >= order.index(stg) and _s(r.get("stage")) not in ("rejected", "dropped")) or _s(r.get("stage")) == "left"  # noqa: E731
    total = len(rows)
    cnt = {s: sum(1 for r in rows if _s(r.get("stage")) == s) for s in m.STAGES}
    interviewed = sum(1 for r in rows if _s(r.get("attended")) == "yes")
    booked = sum(1 for r in rows if _s(r.get("interview_at")))
    trained = sum(1 for r in rows if _s(r.get("training_at")) and _s(r.get("training_ok")) != "changed")
    staffed = sum(1 for r in rows if _s(r.get("staffed_at")) or _s(r.get("stage")) in ("staffed", "left"))
    noshow = sum(1 for r in rows if _s(r.get("attended")) == "changed" or (_s(r.get("call_status")) == "confirmed" and _s(r.get("attended")) in ("no", "changed")))
    pct = lambda a, b: round(100 * a / b) if b else 0  # noqa: E731
    first = []
    for r in rows:
        c, lc = _dt(r, "created_at"), _dt(r, "last_contact_at")
        if c and lc and lc >= c:
            first.append((lc - c).total_seconds() / 3600)
    first.sort()
    scores = [int(_s(r.get("test_score"))) for r in rows if _s(r.get("test_score")).isdigit()]
    reasons: dict[str, int] = {}
    for r in rows:
        if _s(r.get("left_reason")):
            reasons[_s(r.get("left_reason"))] = reasons.get(_s(r.get("left_reason")), 0) + 1
    return {"days": days, "total": total, "by_stage": cnt, "booked": booked, "interviewed": interviewed, "trained": trained, "staffed": staffed, "no_show": noshow,
            "conv": {"booked": pct(booked, total), "interviewed": pct(interviewed, booked), "trained": pct(trained, interviewed), "staffed": pct(staffed, total)},
            "median_first_contact_h": round(first[len(first) // 2], 1) if first else None, "avg_test": round(sum(scores) / len(scores), 1) if scores else None,
            "left_reasons": sorted(({"reason": k, "count": v} for k, v in reasons.items()), key=lambda x: -x["count"])[:8],
            "active": sum(1 for r in all_rows() if _active(r))}


def slots(day: str) -> dict:
    """დღის გასაუბრებების სლოტები საათების მიხედვით (როგორც ძველი INTERVIEW DASHBOARD): მოდის/არ მოდის/განმეორებითი/ვერ დაუკავშირდნენ/დასადასტურებელი."""
    d0 = m.parse_dt(day)
    if not d0:
        raise RecruitError("თარიღი არასწორია")
    by: dict[str, dict] = {}
    for r in all_rows():
        iv = _dt(r, "interview_at")
        if not iv or iv.date() != d0.date():
            continue
        t = iv.strftime("%H:%M")
        b = by.setdefault(t, {"time": t, "total": 0, "confirmed": 0, "declined": 0, "repeat": 0, "no_contact": 0, "pending": 0, "names": []})
        b["total"] += 1
        cs = _s(r.get("call_status"))
        b[cs if cs in ("confirmed", "declined", "repeat", "no_contact") else "pending"] += 1
        b["names"].append({"id": _s(r.get("recruit_id")), "name": _s(r.get("name"), 60), "call": cs})
    return {"day": m.fmt_date(d0), "slots": [by[k] for k in sorted(by)], "total": sum(b["total"] for b in by.values())}


def query(f: dict, now: datetime.datetime | None = None) -> dict:
    now = now or now_dt()
    q = _s(f.get("q"), 60).lower()
    qd = "".join(ch for ch in q if ch.isdigit())
    rows = []
    for r in all_rows():
        if f.get("stage") and _s(r.get("stage")) != f["stage"]:
            continue
        if f.get("active") and not _active(r):
            continue
        if f.get("responsible") and _s(r.get("responsible_id")) != f["responsible"]:
            continue
        if q and q not in _s(r.get("name")).lower() and not (len(qd) >= 3 and qd in "".join(ch for ch in _s(r.get("phone_raw")) + _s(r.get("phone")) if ch.isdigit())):
            continue
        rows.append(r)
    rows.sort(key=lambda r: _s(r.get("created_at")), reverse=True)
    per = max(1, min(int(f.get("per_page") or 30), 100))
    page = max(1, int(f.get("page") or 1))
    return {"items": [public(x, now) for x in rows[(page - 1) * per: page * per]], "total": len(rows), "page": page, "per_page": per}


# ---------------------------------------------------------------------------------------------- შეტყობინებების დედუპლიკაცია
def claim_alert(key: str, kind: str, recruit_id: str, to: str) -> bool:
    with _lock:
        if any(_s(r.get("alert_key")) == key for r in _backend.read(m.RECRUIT_ALERTS, fresh=True)):
            return False
        _backend.append(m.RECRUIT_ALERTS, m.ALERT_HEADERS, {"alert_key": key, "kind": kind, "recruit_id": recruit_id, "to": to, "at": now_str()})
        return True


def release_alert(key: str) -> None:
    with _lock:
        # გაგზავნა ჩავარდა => გასაღებს ვანთავისუფლებთ (შემდეგ ციკლზე ისევ ეცდება): ჩანაწერს ვარქმევთ სხვა გასაღებს
        _backend.update(m.RECRUIT_ALERTS, m.ALERT_HEADERS, key, {"alert_key": f"{key}#released#{uuid.uuid4().hex[:6]}", "kind": "released", "to": "released"})


def alert_keys() -> set:
    return {_s(r.get("alert_key")) for r in _backend.read(m.RECRUIT_ALERTS) if _s(r.get("kind")) != "released"}
