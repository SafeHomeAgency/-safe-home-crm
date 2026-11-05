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
    def __init__(self, msg: str, status: int = 400, code: str = ""):
        super().__init__(msg)
        self.status = status
        self.code = code


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
FILL_FIELDS = ["phone", "phone_raw", "age", "motivation", "experience", "pref_text", "pref_date", "pref_time", "interview_at", "call_status", "attended", "decision", "training_at",
               "training_ok", "attended_t1", "attended_t2", "inter_lasha", "inter_owner", "inter_client", "inter_lasha_at", "inter_owner_at", "inter_client_at", "inter_note",
               "test_score", "internship_at", "hire", "staffed_at", "left_at", "comment"]


def import_rows(parsed: list[dict], bootstrap: bool = False) -> dict:
    """parsed — map_row-ის შედეგები. ახალი src_key — ემატება; უკვე არსებულზე **მხოლოდ ცარიელ ველებს ვავსებთ** ცხრილის მონაცემით (ჩვენი რედაქტირება
    არასდროს იწერება თავზე; ცხრილში ხელით შევსებული ახალი მონაცემიც არ იკარგება). bootstrap=True: ძველი ისტორიის პირველადი ჩატვირთვა — `silent`,
    რომ ძველ კანდიდატებზე შეტყობინებები არ წავიდეს. დუბლიკატი ტელეფონით აქტიურ ჩანაწერთან — მიეთითება კომენტარში."""
    now = now_dt()
    with _lock:
        existing = all_rows(fresh=True)
        by_key = {_s(r.get("src_key")): r for r in existing if _s(r.get("src_key"))}
        phones = {_s(r.get("phone")): _s(r.get("name")) for r in existing if _s(r.get("phone")) and _s(r.get("closed")) != "yes"}
        added = skipped = dups = 0
        batch = []
        fills: dict[str, dict] = {}
        taken = {_s(r.get("recruit_id")) for r in existing}
        order = list(m.STAGES)
        for rec in parsed:
            old = by_key.get(rec["src_key"])
            if old is not None:
                ch = {k: _s(rec.get(k), 700) for k in FILL_FIELDS if _s(rec.get(k)) and not _s(old.get(k))}
                for k in ("inter_lasha", "inter_owner", "inter_client"):          # ძველი ვერსიის მნიშვნელობა „yes“ (გაიარა) -> ახალი სტატუსი
                    if _s(old.get(k)) == "yes":
                        ch[k] = "passed"
                if ch:
                    merged = dict(old, **ch)
                    cur = _s(old.get("stage")) or "new"
                    if _s(old.get("closed")) != "yes" and cur != "archive":
                        auto = m.infer_stage(merged)
                        if auto != cur and (order.index(auto) > order.index(cur) or auto in m.CLOSED_STAGES):
                            ch["stage"] = auto
                            ch["closed"] = "yes" if auto in m.CLOSED_STAGES else ""
                    ch["updated_at"], ch["updated_by"] = now_str(), "ცხრილიდან შევსება"
                    fills[_s(old.get("recruit_id"))] = ch
                skipped += 1
                continue
            rid = "R" + rec["src_key"].lstrip("A")
            if rec["src_key"].startswith("A"):
                rid = "A" + rec["src_key"][1:]
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
            by_key[rec["src_key"]] = rec
            added += 1
        # ჯგუფური ჩაწერა: ერთი მოთხოვნა 300 სტრიქონზე (სტრიქონ-სტრიქონ ჩაწერა Sheets-ის „Write requests per minute“ ლიმიტს ცდებოდა — 429)
        at = now_str()
        log_rows = []
        if batch:
            _backend.append_many(m.RECRUITS, m.HEADERS, batch)
            log_rows += [{"log_id": uuid.uuid4().hex[:10], "recruit_id": rec["recruit_id"], "at": at, "by_name": "სისტემა", "by_id": "", "kind": "import",
                          "text": ("არქივიდან გადმოტანილია" if rec.get("source") == "archive" else "ძველი ცხრილიდან გადმოტანილია") if rec.get("silent") else "ფორმიდან შემოვიდა"} for rec in batch]
        filled = 0
        if fills:
            filled = _backend.update_many(m.RECRUITS, m.HEADERS, fills)
            log_rows += [{"log_id": uuid.uuid4().hex[:10], "recruit_id": rid, "at": at, "by_name": "სისტემა", "by_id": "", "kind": "import",
                          "text": "ცხრილიდან შეივსო: " + ", ".join(k for k in ch if k not in ("updated_at", "updated_by", "closed"))[:200]} for rid, ch in fills.items()]
        if log_rows:
            _backend.append_many(m.RECRUIT_LOG, m.LOG_HEADERS, log_rows)
        return {"added": added, "skipped": skipped, "duplicates": dups, "bootstrap": bootstrap, "filled": filled}


def sync(fetch=None, sheet_id: str = "", tab: str = "", archive_tabs=None) -> dict:
    """Google Form-ის ცხრილიდან ახალი სტრიქონების გადმოტანა + ცარიელი ველების შევსება. ჩვენი ცხრილი ცარიელია => ბოოტსტრაპი (ძველი ისტორია, უხმოდ).
    ძველი ფორმის გვერდები (RECRUIT_ARCHIVE_TABS, მაგ. Sheet3) — ეტაპით „არქივი“ (შედეგი უცნობია), რომ არავინ დაიკარგოს."""
    fetch = fetch or m.fetch_sheet_rows
    sid = sheet_id or config.RECRUIT_SHEET_ID
    header, rows = fetch(sid, tab or config.RECRUIT_SHEET_TAB)
    parsed = [p for p in (m.map_row(header, r) for r in rows) if p]
    with _lock:
        bootstrap = not [r for r in all_rows(fresh=True) if _s(r.get("source")) != "archive"]
    out = import_rows(parsed, bootstrap=bootstrap)
    out["source_rows"] = len(rows)
    tabs = config.RECRUIT_ARCHIVE_TABS if archive_tabs is None else archive_tabs
    arch = {"added": 0, "tabs": 0}
    for t in tabs:
        try:
            ah, ar = fetch(sid, t)
            res = import_rows([p for p in (m.map_archive_row(ah, r) for r in ar) if p], bootstrap=True)
            arch["added"] += res["added"]
            arch["tabs"] += 1
        except Exception as e:  # noqa: BLE001
            log.warning("Recruit: არქივის გვერდი ვერ ჩაიტვირთა (%s): %s", t, e)
            arch["error"] = f"{t}: {e}"
    out["archive"] = arch
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
        if ch["closed"] == "yes" and _s(r.get("closed")) != "yes" and stage != "archive" and not _s(merged.get("left_reason")):
            # დახურვა მიზეზის გარეშე არ შეიძლება: „ყველას მიზეზი უნდა ვიცოდეთ“
            raise RecruitError("მიუთითეთ მიზეზი — რატომ იხურება კანდიდატი (მაგ. ანაზღაურება, გრაფიკი, გადაიფიქრა…)", 400, "reason_required")
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
    out["flags"] = flags_of(r, now)
    out["train"] = m.train_info(r)
    if not _active(r):
        out["reason"], explicit = m.reason_of(r)
        out["reason_auto"] = not explicit and bool(out["reason"])
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
    # ტრენინგი: რამდენი მოდის, ქირის / ყიდვის ტრენინგი რამდენს ჩაუტარდა, რამდენი გადავიდა ყიდვაზე (ორივე)
    ti = [(r, m.train_info(r)) for r in rows]
    by_day: dict[str, dict] = {}
    for r, t_ in ti:
        td = _dt(r, "training_at")
        if td:
            d = by_day.setdefault(td.strftime("%Y-%m-%d"), {"date": td.strftime("%Y-%m-%d"), "scheduled": 0, "coming": 0, "rent": 0, "sale": 0, "both": 0})
            d["scheduled"] += 1
            d["coming"] += 1 if _s(r.get("training_ok")) == "yes" else 0
            d["rent"] += 1 if t_["rent"] else 0
            d["sale"] += 1 if t_["sale"] else 0
            d["both"] += 1 if t_["both"] else 0
    training = {
        "scheduled": sum(1 for r in rows if _s(r.get("training_at"))), "coming": sum(1 for r in rows if _s(r.get("training_ok")) == "yes"),
        "declined": sum(1 for r in rows if _s(r.get("training_ok")) in ("no", "changed")), "no_answer": sum(1 for r in rows if _s(r.get("training_ok")) == "no_answer"),
        "rent": sum(1 for _r, t_ in ti if t_["rent"]), "sale": sum(1 for _r, t_ in ti if t_["sale"]), "rent_then_sale": sum(1 for _r, t_ in ti if t_["both"]),
        "rent_only": sum(1 for _r, t_ in ti if t_["rent"] and not t_["sale"]), "sale_only": sum(1 for _r, t_ in ti if t_["sale"] and not t_["rent"]),
        "absent": sum(1 for _r, t_ in ti if t_["absent"]), "by_day": [by_day[k] for k in sorted(by_day, reverse=True)][:14],
    }
    inter = {}
    for key, label in (("inter_lasha", "ლაშასთან"), ("inter_owner", "მეპატრონესთან"), ("inter_client", "კლიენტთან")):
        c = {k: sum(1 for r in rows if _s(r.get(key)) == k) for k in ("scheduled", "held", "passed", "failed", "changed")}
        c["label"] = label
        c["conducted"] = c["held"] + c["passed"] + c["failed"]
        inter[key] = c
    outcome = {"internship": sum(1 for r in rows if _s(r.get("internship_at"))), "hire_yes": sum(1 for r in rows if _s(r.get("hire")) == "yes"),
               "hire_changed": sum(1 for r in rows if _s(r.get("hire")) in ("changed", "no")), "staffed": staffed, "left": sum(1 for r in rows if _s(r.get("left_at"))),
               "tested": len(scores)}
    reasons: dict[str, int] = {}
    unknown = 0
    for r in rows:
        if not _active(r) and _s(r.get("stage")) != "archive":
            txt = m.reason_of(r)[0]
            if txt:
                k = txt.split(":")[0].strip()                  # „ანაზღაურება: დეტალი“ -> „ანაზღაურება“
                reasons[k] = reasons.get(k, 0) + 1
            else:
                unknown += 1
    return {"days": days, "reasons": sorted(({"reason": k, "count": v} for k, v in reasons.items()), key=lambda x: -x["count"])[:14], "reason_unknown": unknown,
            "training": training, "interactions": inter, "outcome": outcome, "total": total, "by_stage": cnt, "booked": booked, "interviewed": interviewed, "trained": trained, "staffed": staffed, "no_show": noshow,
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


FLAG_LABELS = {"no_reason": "❓ დახურულია, მიზეზი არ არის მითითებული", "uncontacted": "🆕 დაუკავშირებელი (3 სთ+)", "result_missing": "✍️ გასაუბრების შედეგი ჩაუწერელია", "postponed": "⏭ გადაიდო — ახალი დრო დაუნიშნეთ",
               "stalled": "🧊 3 დღეზე მეტია უმოქმედოა", "no_phone": "📵 ტელეფონი არ არის", "duplicate": "👯 დუბლიკატი"}
_IN_PROGRESS = ("new", "invited", "confirmed", "interviewed", "considering", "training", "internship")


def flags_of(r: dict, now: datetime.datetime) -> list[str]:
    """„ყურადღების“ ნიშნები (აქტიურ ჩანაწერზე): რომ არცერთი კანდიდატი არ დაიკარგოს. ძველი (silent) ისტორია ხმაურს არ ქმნის."""
    if not _active(r):
        if _s(r.get("stage")) != "archive" and not m.reason_of(r)[0]:
            return ["no_reason"]                                # დახურულია, მაგრამ რატომ — უცნობია: შესავსებად ჩანს „ყურადღებაში“
        return []
    out = []
    stage = _s(r.get("stage")) or "new"
    silent = bool(_s(r.get("silent")))
    created = _dt(r, "created_at")
    last = _dt(r, "last_contact_at") or created
    if stage == "new" and not _s(r.get("last_contact_at")) and not silent and created and now - created >= datetime.timedelta(hours=3):
        out.append("uncontacted")
    iv = _dt(r, "interview_at")
    if iv and datetime.timedelta(minutes=60) <= now - iv < datetime.timedelta(days=14) and stage in ("new", "invited", "confirmed") and not _s(r.get("attended")):
        out.append("result_missing")
    if not silent and stage in _IN_PROGRESS and last and now - last >= datetime.timedelta(days=3):
        out.append("stalled")
    if _s(r.get("attended")) == "postponed" and stage in ("new", "invited", "confirmed"):
        out.append("postponed")
    if not _s(r.get("phone")):
        out.append("no_phone")
    if "იგივე ნომერი" in _s(r.get("comment")):
        out.append("duplicate")
    return out


def _passes(r: dict, f: dict, now: datetime.datetime, skip: tuple = ()) -> bool:
    q = _s(f.get("q"), 60).lower()
    if q and "q" not in skip:
        qd = "".join(ch for ch in q if ch.isdigit())
        digits = "".join(ch for ch in _s(r.get("phone_raw")) + _s(r.get("phone")) if ch.isdigit())
        if q not in _s(r.get("name")).lower() and q not in _s(r.get("comment")).lower() and not (len(qd) >= 3 and qd in digits):
            return False
    stage = _s(f.get("stage"))
    state = _s(f.get("state")) or "active"
    if stage in m.CLOSED_STAGES and state == "active":
        state = "all"                                           # დახურული ეტაპი არჩეულია — აქტიურებზე შეზღუდვა აზრს კარგავს
    if "state" not in skip:
        if state == "active" and not _active(r):
            return False
        if state == "closed" and _active(r):
            return False
    if stage and "stage" not in skip and _s(r.get("stage")) != stage:
        return False
    call = _s(f.get("call"))
    if call and "call" not in skip:
        cs = _s(r.get("call_status"))
        if (call == "todo" and cs) or (call != "todo" and cs != call):
            return False
    iv = _dt(r, "interview_at")
    p = _s(f.get("iv"))
    if p and "iv" not in skip:
        today = now.date()
        if p == "none":
            ok = iv is None
        elif iv is None:
            ok = False
        elif p == "today":
            ok = iv.date() == today
        elif p == "tomorrow":
            ok = iv.date() == today + datetime.timedelta(days=1)
        elif p == "week":
            ok = today <= iv.date() <= today + datetime.timedelta(days=7)
        elif p == "past":
            ok = iv.date() < today
        elif p == "date":
            d = m.parse_dt(_s(f.get("iv_date")))
            ok = bool(d) and iv.date() == d.date()
        else:
            ok = True
        if not ok:
            return False
    added = _s(f.get("added"))
    if added and "added" not in skip:
        c = _dt(r, "created_at")
        if not c:
            return False
        if added == "today" and c.date() != now.date():
            return False
        if added in ("7", "30") and now - c > datetime.timedelta(days=int(added)):
            return False
    age = _s(r.get("age"))
    for key, cmp in (("age_min", lambda a, v: a >= v), ("age_max", lambda a, v: a <= v)):
        if _s(f.get(key)) and "age" not in skip:
            try:
                if not age or not cmp(int(age), int(f[key])):
                    return False
            except ValueError:
                return False
    exp = _s(f.get("exp"))
    if exp and "exp" not in skip:
        e = _s(r.get("experience")).lower()
        has = e.startswith(("დიახ", "კი", "yes"))
        if (exp == "yes" and not has) or (exp == "no" and (has or not e)):
            return False
    if _s(f.get("source")) and "source" not in skip and _s(r.get("source")) != _s(f.get("source")):
        return False
    tr = _s(f.get("train"))
    if tr and "train" not in skip:
        ti = m.train_info(r)
        ok = {"coming": _s(r.get("training_ok")) == "yes", "rent": ti["rent"], "sale": ti["sale"], "both": ti["both"], "absent": ti["absent"] or _s(r.get("training_ok")) in ("no", "changed", "no_answer"),
              "none": bool(_s(r.get("training_at"))) and not ti["any"]}.get(tr, True)
        if not ok:
            return False
    ia = _s(f.get("inter"))
    if ia and "inter" not in skip:
        if ia == "none":
            if any(_s(r.get(k)) for k in ("inter_lasha", "inter_owner", "inter_client")):
                return False
        elif not any(_s(r.get(k)) == ia for k in ("inter_lasha", "inter_owner", "inter_client")):
            return False
    if f.get("responsible") and _s(r.get("responsible_id")) != _s(f["responsible"]):
        return False
    flag = _s(f.get("flag"))
    if flag and "flag" not in skip and flag not in flags_of(r, now):
        return False
    return True


def query(f: dict, now: datetime.datetime | None = None) -> dict:
    """ძიება + ფილტრები + დახარისხება. პასუხში `facets` — რამდენი ჩანაწერი ერგება თითოეულ ვარიანტს (დანარჩენი ფილტრების გათვალისწინებით),
    რომ ეკრანზე ყოველი ღილაკის გვერდით რიცხვი ჩანდეს და „ცარიელ“ ფილტრში არავინ მოხვდეს."""
    now = now or now_dt()
    rows_all = all_rows()
    rows = [r for r in rows_all if _passes(r, f, now)]
    sort = _s(f.get("sort")) or "new"
    if sort == "interview":
        rows.sort(key=lambda r: (not _s(r.get("interview_at")), _s(r.get("interview_at"))))
    elif sort == "name":
        rows.sort(key=lambda r: _s(r.get("name")).lower())
    elif sort == "activity":
        rows.sort(key=lambda r: _s(r.get("last_contact_at")) or _s(r.get("created_at")), reverse=True)
    else:
        rows.sort(key=lambda r: _s(r.get("created_at")), reverse=True)
    per = max(1, min(int(f.get("per_page") or 30), 100))
    page = max(1, int(f.get("page") or 1))

    def cnt(skip, key_fn):
        out: dict[str, int] = {}
        for r in rows_all:
            if _passes(r, f, now, skip):
                for k in key_fn(r):
                    out[k] = out.get(k, 0) + 1
        return out

    facets = {
        "stage": cnt(("stage",), lambda r: [_s(r.get("stage")) or "new"]),
        "state": cnt(("state", "stage"), lambda r: ["active" if _active(r) else "closed"]),
        "flag": cnt(("flag",), lambda r: flags_of(r, now)),
        "call": cnt(("call",), lambda r: [_s(r.get("call_status")) or "todo"]),
    }
    facets["state"]["all"] = sum(facets["state"].values())
    return {"items": [public(x, now) for x in rows[(page - 1) * per: page * per]], "total": len(rows), "page": page, "per_page": per, "facets": facets,
            "flag_labels": FLAG_LABELS}


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


# ---------------------------------------------------------------------------------------------- კალენდარი
WEEKDAYS = ["ორშ", "სამ", "ოთხ", "ხუთ", "პარ", "შაბ", "კვი"]


def calendar(start: str = "", days: int = 14, now: datetime.datetime | None = None) -> dict:
    """დღეების ზოლი კალენდრისთვის: ყოველ დღეს — გასაუბრებები (სულ/დადასტურებული/დასადასტურებელი), ტრენინგები, სტაჟირების დაწყება, ჩაშტატება, წასვლა."""
    now = now or now_dt()
    d0 = m.parse_dt(start)
    d0 = d0.date() if d0 else now.date()
    days = max(1, min(int(days or 14), 62))
    out = {}
    for i in range(days):
        d = d0 + datetime.timedelta(days=i)
        out[d.strftime("%Y-%m-%d")] = {"date": d.strftime("%Y-%m-%d"), "weekday": WEEKDAYS[d.weekday()], "day": d.day, "today": d == now.date(),
                                       "interviews": {"total": 0, "confirmed": 0, "declined": 0, "pending": 0}, "trainings": {"total": 0, "coming": 0}, "internship": 0, "staffed": 0, "left": 0}
    for r in all_rows():
        iv = _dt(r, "interview_at")
        if iv and iv.strftime("%Y-%m-%d") in out and _s(r.get("stage")) != "archive":
            b = out[iv.strftime("%Y-%m-%d")]["interviews"]
            b["total"] += 1
            cs = _s(r.get("call_status"))
            b["confirmed" if cs == "confirmed" else "declined" if cs == "declined" else "pending"] += 1
        tr = _dt(r, "training_at")
        if tr and tr.strftime("%Y-%m-%d") in out:
            b = out[tr.strftime("%Y-%m-%d")]["trainings"]
            b["total"] += 1
            b["coming"] += 1 if _s(r.get("training_ok")) == "yes" else 0
        for key, field in (("internship", "internship_at"), ("staffed", "staffed_at"), ("left", "left_at")):
            dd = m.parse_dt(r.get(field))
            if dd and dd.strftime("%Y-%m-%d") in out:
                out[dd.strftime("%Y-%m-%d")][key] += 1
    return {"from": d0.strftime("%Y-%m-%d"), "days": list(out.values())}


def day_view(day: str, now: datetime.datetime | None = None) -> dict:
    """ერთი დღის სრული სია: გასაუბრებები დროის მიხედვით, ტრენინგები, სტაჟირების დაწყება, ჩაშტატება, წასვლა."""
    now = now or now_dt()
    d0 = m.parse_dt(day)
    if not d0:
        raise RecruitError("თარიღი არასწორია")
    key = d0.strftime("%Y-%m-%d")
    pick = lambda field, time_key: sorted([r for r in all_rows() if (d := m.parse_dt(r.get(field))) and d.strftime("%Y-%m-%d") == key and _s(r.get("stage")) != "archive"],  # noqa: E731
                                          key=lambda r: _s(r.get(time_key or field)))
    return {"day": key, "interviews": [public(x, now) for x in pick("interview_at", "interview_at")], "trainings": [public(x, now) for x in pick("training_at", "training_at")],
            "internship": [public(x, now) for x in pick("internship_at", "name")], "staffed": [public(x, now) for x in pick("staffed_at", "name")], "left": [public(x, now) for x in pick("left_at", "name")]}
