"""
Safe Home Property Hub — შეხვედრები განცხადებიდან: შენახვა (Google Sheets, ახალი ცხრილი `HubMeetings`) და ბიზნეს-წესები.

სტრუქტურა listings_store/contracts_store-ს იმეორებს: ცხრილი ზარმაცად იქმნება, ჩაწერა ერთ პროცესულ ბლოკირებაში და ახლად წაკითხული
მონაცემებით, წაშლა არ არსებობს (მხოლოდ სტატუსი). ბექენდი ტესტში იცვლება `MemoryBackend`-ით.
"""

from __future__ import annotations

import datetime
import logging
import threading

import contracts_store as _cs
import hubmeet_model as m
from hubmeet_model import HubMeetError

log = logging.getLogger("safehome-hubmeet")
_lock = threading.RLock()


class SheetsBackend(_cs.SheetsBackend):
    def ensure(self) -> None:
        if self._ready:
            return
        sg = self._sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in m.ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        self._ready = True


class MemoryBackend(_cs.MemoryBackend):
    def ensure(self) -> None:
        for name, _h, _r in m.ALL_TABS:
            self.tables.setdefault(name, [])


_backend = SheetsBackend()


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def now_dt() -> datetime.datetime:
    import crm_time
    return crm_time.local_now().replace(tzinfo=None)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")


def all_rows(fresh: bool = False) -> list[dict]:
    return _backend.read(m.HUB_MEETINGS_SHEET, fresh=fresh)


def get(hub_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in all_rows(fresh) if m.s(r.get("hub_id")) == m.s(hub_id)), None)


# ====================================================================== უფლებები
def sides(h: dict, viewer: dict) -> tuple[bool, bool]:
    """(owner_side, requester_side): ადმინი ორივე; აგენტი — თავისი როლი; თიმლიდერი — თავისი გუნდის ბინა/აგენტი."""
    if viewer.get("admin"):
        return True, True
    aid, team = m.s(viewer.get("agent_id")), m.s(viewer.get("team"))
    lead = viewer.get("role") == "team_lead" and bool(team)
    owner = bool(aid and aid == m.s(h.get("owner_agent_id"))) or (lead and team == m.s(h.get("owner_team")))
    req = bool(aid and aid == m.s(h.get("requester_agent_id"))) or (lead and team == m.s(h.get("team")))
    return owner, req


def _hist(h: dict, who: str, event: str) -> str:
    line = f"{now_str()}|{m.s(who, 60)}|{m.s(event, 160)}"
    prev = m.s(h.get("history"), 2000)
    return (prev + "\n" + line if prev else line)[-2000:]


# ====================================================================== შექმნა
def create(listing: dict, requester: dict, viewer: dict, data: dict) -> dict:
    """listing — `Listings` ცხრილის სტრიქონი; requester — აგენტის ჩანაწერი (agent_id, name, team); viewer — უფლებებისთვის."""
    if not listing or str(listing.get("active", "yes")).lower() == "no" or str(listing.get("archived", "")).lower() in ("yes", "true", "1"):
        raise HubMeetError("განცხადება აქტიური არ არის ან ვერ მოიძებნა", 404)
    name = m.s(data.get("client_name"), 80)
    phone = m.s(data.get("client_phone"), 30)
    if not name:
        raise HubMeetError("კლიენტის სახელი სავალდებულოა")
    if len(m.norm_phone(phone)) < 9:
        raise HubMeetError("კლიენტის ტელეფონი სავალდებულოა (მინ. 9 ციფრი)")
    date = m.parse_date(data.get("meeting_date"), "შეხვედრის თარიღი")
    today = now_dt().date()
    d = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    if d < today - datetime.timedelta(days=1):
        raise HubMeetError("შეხვედრის თარიღი წარსულშია")
    if d > today + datetime.timedelta(days=366):
        raise HubMeetError("შეხვედრის თარიღი ძალიან შორსაა")
    time = m.parse_time(data.get("meeting_time"))
    rental = m.parse_int(data.get("rental_months"), "გაქირავების პერიოდი (თვე)", 1, 120)
    move_in = m.parse_date(data.get("move_in_date"), "შესვლის თარიღი", required=False)
    budget = m.parse_int(data.get("budget_usd"), "ბიუჯეტი", 0, 100000000)
    owner_id = m.s(listing.get("agent_id"), 40)
    req_id = m.s(requester.get("agent_id"), 40)
    coop = bool(owner_id and owner_id != req_id)
    row = {
        "hub_id": "HM" + __import__("uuid").uuid4().hex[:8], "meeting_id": "", "listing_id": m.s(listing.get("listing_id"), 40),
        "coop": "yes" if coop else "", "owner_agent_id": owner_id, "owner_agent_name": m.s(listing.get("agent_name"), 80),
        "owner_team": m.s(listing.get("team"), 40), "requester_agent_id": req_id, "requester_name": m.s(requester.get("name"), 80),
        "team": m.s(requester.get("team"), 40),
        "listing_title": " · ".join(x for x in (m.s(listing.get("property_type"), 30), m.s(listing.get("rooms"), 6) and (m.s(listing.get("rooms"), 6) + " ოთახი")) if x),
        "address": m.s(listing.get("address"), 160), "district": m.s(listing.get("district"), 80), "city": m.s(listing.get("city"), 60),
        "deal_type": m.s(listing.get("deal_type"), 40), "price_usd": m.s(listing.get("price_usd"), 20),
        "photo": next(iter(str(listing.get("photos") or "").split("|")), "") if str(listing.get("photos") or "").startswith("http") else "",
        "myhome_id": m.digits(listing.get("myhome_id")), "ssge_id": m.digits(listing.get("ssge_id")),
        "client_name": name, "client_phone": phone, "meeting_date": date, "meeting_time": time, "rental_months": rental,
        "move_in_date": move_in, "budget_usd": budget, "tenants": m.s(data.get("tenants"), 200), "coop_terms": m.s(data.get("coop_terms"), 300),
        "owner_availability": m.s(data.get("owner_availability"), 200), "notes": m.s(data.get("notes"), 500),
        "outcome": "", "reject_reason": "", "history": "", "created_at": now_str(), "updated_at": now_str(), "reminded": "", "nudged": "", "task_id": m.s(data.get("task_id"), 24),
    }
    owner_side, _req = sides(row, viewer)
    row["status"] = m.PLANNED if (not coop or owner_side) else m.PENDING
    row["history"] = _hist(row, requester.get("name"), "მოთხოვნა გაიგზავნა" if row["status"] == m.PENDING else "დაგეგმილია")
    with _lock:
        rows = _backend.read(m.HUB_MEETINGS_SHEET, fresh=True)
        key = (req_id, row["listing_id"], m.norm_phone(phone), date)
        if any((m.s(r.get("requester_agent_id")), m.s(r.get("listing_id")), m.norm_phone(r.get("client_phone")), m.s(r.get("meeting_date"))) == key
               and m.s(r.get("status")) in m.ACTIVE_STATUSES for r in rows):
            raise HubMeetError("ასეთი შეხვედრა უკვე არსებობს (იგივე ბინა, კლიენტი და თარიღი)", 409)
        _backend.append(m.HUB_MEETINGS_SHEET, m.HM_HEADERS, row)
    return row


def attach_meeting_id(hub_id: str, meeting_id: str) -> None:
    with _lock:
        _backend.update(m.HUB_MEETINGS_SHEET, m.HM_HEADERS, hub_id, {"meeting_id": m.s(meeting_id, 20), "updated_at": now_str()})


# ====================================================================== გადაწყვეტილებები
def decide(hub_id: str, viewer: dict, actor_name: str, action: str, reason: str = "", date: str = "", time: str = "") -> dict:
    """მფლობელი აგენტი/მისი თიმლიდერი/ადმინი: accept (შეიძლება ახალი თარიღით/დროით) ან reject."""
    with _lock:
        h = get(hub_id, fresh=True)
        if not h:
            raise HubMeetError("შეხვედრა ვერ მოიძებნა", 404)
        owner_side, _ = sides(h, viewer)
        if not owner_side:
            raise HubMeetError("მხოლოდ ბინის მფლობელ აგენტს, მის თიმლიდერს ან ადმინს შეუძლია", 403)
        if m.s(h.get("status")) != m.PENDING:
            raise HubMeetError("ეს მოთხოვნა უკვე დამუშავებულია", 409)
        if action == "accept":
            ch = {"status": m.PLANNED}
            if date:
                ch["meeting_date"] = m.parse_date(date, "შეხვედრის თარიღი")
            if time:
                ch["meeting_time"] = m.parse_time(time)
            ev = "დადასტურდა" + (f" (ახალი დრო: {ch.get('meeting_date', h['meeting_date'])} {ch.get('meeting_time', h['meeting_time'])})" if date or time else "")
        elif action == "reject":
            ch = {"status": m.REJECTED, "reject_reason": m.s(reason, 200)}
            ev = "უარყოფილია" + (f": {m.s(reason, 100)}" if reason else "")
        else:
            raise HubMeetError("action: accept ან reject")
        ch["history"] = _hist(h, actor_name, ev)
        ch["updated_at"] = now_str()
        _backend.update(m.HUB_MEETINGS_SHEET, m.HM_HEADERS, hub_id, ch)
        return dict(h, **ch)


def set_status(hub_id: str, viewer: dict, actor_name: str, status: str, outcome: str = "", note: str = "") -> dict:
    """planned -> done / no_show / cancelled; pending -> cancelled. ორივე მხარეს (და ადმინს) შეუძლია."""
    if status not in (m.DONE, m.NO_SHOW, m.CANCELLED):
        raise HubMeetError("სტატუსი: done, no_show ან cancelled")
    with _lock:
        h = get(hub_id, fresh=True)
        if not h:
            raise HubMeetError("შეხვედრა ვერ მოიძებნა", 404)
        owner_side, req_side = sides(h, viewer)
        if not (owner_side or req_side):
            raise HubMeetError("ამ შეხვედრაზე წვდომა არ გაქვთ", 403)
        cur = m.s(h.get("status"))
        if cur not in m.ACTIVE_STATUSES:
            raise HubMeetError("ეს შეხვედრა უკვე დახურულია", 409)
        if status in (m.DONE, m.NO_SHOW) and cur != m.PLANNED:
            raise HubMeetError("დასადასტურებელი შეხვედრის ჩატარებულად მონიშვნა შეუძლებელია", 409)
        oc = m.s(outcome, 20)
        if oc and oc not in m.OUTCOMES:
            raise HubMeetError("შედეგი არასწორია")
        ch = {"status": status, "outcome": oc if status == m.DONE else "", "updated_at": now_str()}
        ev = m.STATUS_LABELS[status] + (f" · {m.OUTCOMES[oc]}" if oc and status == m.DONE else "") + (f" · {m.s(note, 100)}" if note else "")
        ch["history"] = _hist(h, actor_name, ev)
        _backend.update(m.HUB_MEETINGS_SHEET, m.HM_HEADERS, hub_id, ch)
        return dict(h, **ch)


# ====================================================================== პროექცია / სიები
def project(h: dict, viewer: dict) -> dict:
    owner_side, req_side = sides(h, viewer)
    out = {k: h.get(k, "") for k in m.HM_HEADERS if k not in ("client_phone", "meeting_id", "history")}
    out["coop"] = bool(m.s(h.get("coop")))
    out["status_label"] = m.STATUS_LABELS.get(m.s(h.get("status")), "")
    out["outcome_label"] = m.OUTCOMES.get(m.s(h.get("outcome")), "")
    out["price_usd"] = h.get("price_usd", "")
    # კლიენტის ტელეფონი და ძველი ცხრილის ID — მხოლოდ მომთხოვნ მხარეს; ისტორია — ორივე მხარეს
    if req_side:
        out["client_phone"] = h.get("client_phone", "")
        out["meeting_id"] = h.get("meeting_id", "")
    out["history"] = [dict(zip(("at", "who", "event"), ln.split("|", 2))) for ln in m.s(h.get("history"), 2000).split("\n") if ln.count("|") >= 2]
    status = m.s(h.get("status"))
    out["side"] = "both" if owner_side and req_side else ("owner" if owner_side else "requester")
    out["can_decide"] = bool(owner_side and status == m.PENDING)
    out["can_close"] = bool((owner_side or req_side) and status == m.PLANNED)
    out["can_cancel"] = bool((owner_side or req_side) and status in m.ACTIVE_STATUSES)
    out["can_contract"] = bool(req_side and m.s(h.get("meeting_id")) and status in (m.PLANNED, m.DONE))
    return out


def visible(viewer: dict) -> list[dict]:
    res = []
    for h in all_rows():
        o, r = sides(h, viewer)
        if o or r:
            res.append(h)
    return res


def list_for(viewer: dict, view: str = "upcoming", days: int = 30, listing_id: str = "", today: datetime.date | None = None) -> list[dict]:
    today = today or now_dt().date()
    t = today.strftime("%Y-%m-%d")
    rows = visible(viewer)
    if listing_id:
        rows = [h for h in rows if m.s(h.get("listing_id")) == m.s(listing_id)]
    if view == "pending":
        rows = [h for h in rows if m.s(h.get("status")) == m.PENDING]
        rows.sort(key=lambda h: (m.s(h.get("meeting_date")), m.s(h.get("meeting_time"))))
    elif view == "upcoming":
        rows = [h for h in rows if m.s(h.get("status")) in m.ACTIVE_STATUSES and m.s(h.get("meeting_date")) >= t]
        rows.sort(key=lambda h: (m.s(h.get("meeting_date")), m.s(h.get("meeting_time"))))
    elif view == "past":
        cutoff = (today - datetime.timedelta(days=max(1, days))).strftime("%Y-%m-%d")
        rows = [h for h in rows if m.s(h.get("meeting_date")) >= cutoff
                and (m.s(h.get("status")) not in m.ACTIVE_STATUSES or m.s(h.get("meeting_date")) < t)]
        rows.sort(key=lambda h: (m.s(h.get("meeting_date")), m.s(h.get("meeting_time"))), reverse=True)
    else:
        rows.sort(key=lambda h: (m.s(h.get("meeting_date")), m.s(h.get("meeting_time"))), reverse=True)
    return rows[:300]


# ====================================================================== „ყურადღება“: დაგვიანებული Follow-up-ები
ATTENTION_PRIORITY = {"outcome_missing": 0, "pending_undecided": 1, "lead_unseen": 2, "lead_no_meeting": 3}


def attention_items(viewer: dict, tasks: list[dict], scope_ids, now: datetime.datetime | None = None,
                    unseen_hours: float = 2.0, no_meeting_hours: float = 24.0, pending_hours: float = 12.0, outcome_hours: float = 3.0) -> list[dict]:
    """რა მოითხოვს ახლა ყურადღებას (სპამის გარეშე — მხოლოდ რეალურად დაგვიანებული):
      * შეხვედრის დრო გავიდა >outcome_hours და შედეგი არ ჩაწერილა (planned);
      * თანამშრომლობის მოთხოვნა >pending_hours-ია მფლობელის გადაწყვეტილების გარეშე;
      * მინიჭებული კლიენტი >unseen_hours-ია „მივიღე“-ს გარეშე;
      * კლიენტი მიღებულია, მაგრამ >no_meeting_hours-ია შეხვედრა არ დაუგეგმავთ და დავალება არ დახურულა.
    scope_ids — აგენტების id-ების სიმრავლე, რომელთა კლიენტებიც ჩანს (None = ყველა — ადმინი). აბრუნებს პრიორიტეტით დალაგებულ სიას."""
    import crm_time
    now = now or now_dt()
    items: list[dict] = []
    owner_hubs = visible(viewer)
    for h in owner_hubs:
        o, r = sides(h, viewer)
        st = m.s(h.get("status"))
        when = None
        try:
            when = datetime.datetime.strptime(f"{m.s(h.get('meeting_date'))} {m.s(h.get('meeting_time'))}", "%Y-%m-%d %H:%M")
        except ValueError:
            pass
        if st == m.PLANNED and r and when and (now - when).total_seconds() > outcome_hours * 3600:
            items.append({"kind": "outcome_missing", "hub_id": m.s(h.get("hub_id")), "age_hours": int((now - when).total_seconds() // 3600),
                          "text": f"შეხვედრის შედეგი არ ჩაწერილა — {m.s(h.get('client_name'))} · {m.s(h.get('address'))}",
                          "agent_name": m.s(h.get("requester_name"))})
        if st == m.PENDING and o:
            created = None
            try:
                created = datetime.datetime.strptime(m.s(h.get("created_at"))[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                pass
            if created and (now - created).total_seconds() > pending_hours * 3600:
                items.append({"kind": "pending_undecided", "hub_id": m.s(h.get("hub_id")), "age_hours": int((now - created).total_seconds() // 3600),
                              "text": f"თანამშრომლობის მოთხოვნას პასუხი არ გაეცა — {m.s(h.get('requester_name'))} · {m.s(h.get('address'))}",
                              "agent_name": m.s(h.get("owner_agent_name"))})
    linked = {m.s(h.get("task_id")) for h in all_rows() if m.s(h.get("task_id")) and m.s(h.get("status")) not in (m.CANCELLED, m.REJECTED)}
    for t in tasks:
        if str(t.get("status")) == "Done" or not t.get("assigned_to"):
            continue
        if scope_ids is not None and str(t.get("assigned_to")) not in scope_ids:
            continue
        created = crm_time.parse_server_dt(t.get("created_at"))
        if not created:
            continue
        age_h = (now - crm_time.server_naive_to_local(created)).total_seconds() / 3600
        seen = str(t.get("seen", "")).strip().lower() in ("1", "yes", "true", "y") or bool(str(t.get("seen_at", "")).strip())
        label = f"{m.s(t.get('title'), 60)} · {m.s(t.get('client_phone'), 20)}".strip(" ·")
        if not seen and age_h > unseen_hours:
            items.append({"kind": "lead_unseen", "task_id": str(t.get("task_id")), "age_hours": int(age_h),
                          "text": f"კლიენტს ჯერ არ დაუდასტურებია „მივიღე“ — {label}", "agent_name": m.s(t.get("assigned_to_name"))})
        elif seen and age_h > no_meeting_hours and str(t.get("task_id")) not in linked:
            items.append({"kind": "lead_no_meeting", "task_id": str(t.get("task_id")), "age_hours": int(age_h),
                          "text": f"კლიენტს შეხვედრა არ დაუგეგმეს — {label}", "agent_name": m.s(t.get("assigned_to_name"))})
    items.sort(key=lambda x: (ATTENTION_PRIORITY.get(x["kind"], 9), -x["age_hours"]))
    return items


# ====================================================================== ანალიტიკა
def interest_counts(days: int = 30, now: datetime.datetime | None = None) -> dict:
    """ბინაზე შეხვედრების რაოდენობა ბოლო N დღეში (უარყოფილი/გაუქმებული არ ითვლება) — 'ცხელი ბინის' ნიშნისთვის."""
    now = now or now_dt()
    cutoff = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    out: dict[str, int] = {}
    for h in all_rows():
        if m.s(h.get("status")) in (m.CANCELLED, m.REJECTED) or m.s(h.get("created_at"))[:10] < cutoff:
            continue
        lid = m.s(h.get("listing_id"))
        if lid:
            out[lid] = out.get(lid, 0) + 1
    return out


def stats(viewer: dict, days: int = 30, now: datetime.datetime | None = None, contract_counts: dict | None = None) -> dict:
    """ადმინი — ყველაფერი; თიმლიდერი — თავისი გუნდი (ორივე მხარე); აგენტი — მხოლოდ საკუთარი. კლიენტის მონაცემი არ გადადის."""
    now = now or now_dt()
    today = now.date().strftime("%Y-%m-%d")
    tomorrow = (now.date() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff = (now - datetime.timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    rows = [h for h in visible(viewer) if m.s(h.get("created_at"))[:10] >= cutoff or m.s(h.get("meeting_date")) >= today]
    cc = contract_counts or {}
    scope = "all" if viewer.get("admin") else ("team" if viewer.get("role") == "team_lead" else "mine")
    tot = {"meetings": len(rows), "pending": 0, "planned": 0, "done": 0, "cancelled": 0, "no_show": 0, "today": 0, "tomorrow": 0, "contracts": 0}
    lst: dict[str, dict] = {}
    owners: dict[str, dict] = {}
    reqs: dict[str, dict] = {}
    for h in rows:
        st = m.s(h.get("status"))
        key = "cancelled" if st in (m.CANCELLED, m.REJECTED) else st
        tot[key] = tot.get(key, 0) + 1
        if st in m.ACTIVE_STATUSES:
            tot["today"] += 1 if m.s(h.get("meeting_date")) == today else 0
            tot["tomorrow"] += 1 if m.s(h.get("meeting_date")) == tomorrow else 0
        nc = int(cc.get(m.s(h.get("meeting_id")), 0)) if m.s(h.get("meeting_id")) else 0
        tot["contracts"] += nc
        if st in (m.CANCELLED, m.REJECTED):
            continue
        L = lst.setdefault(m.s(h.get("listing_id")), {"listing_id": m.s(h.get("listing_id")), "title": m.s(h.get("listing_title")), "address": m.s(h.get("address")),
                           "district": m.s(h.get("district")), "price_usd": m.s(h.get("price_usd")), "deal_type": m.s(h.get("deal_type")), "photo": m.s(h.get("photo")),
                           "owner_agent_name": m.s(h.get("owner_agent_name")), "meetings": 0, "done": 0, "contracts": 0})
        L["meetings"] += 1
        L["done"] += 1 if st == m.DONE else 0
        L["contracts"] += nc
        o = owners.setdefault(m.s(h.get("owner_agent_id")) or "-", {"agent_id": m.s(h.get("owner_agent_id")), "name": m.s(h.get("owner_agent_name")) or "—", "team": m.s(h.get("owner_team")),
                                                                  "meetings": 0, "done": 0, "listings": set()})
        o["meetings"] += 1
        o["done"] += 1 if st == m.DONE else 0
        o["listings"].add(m.s(h.get("listing_id")))
        r = reqs.setdefault(m.s(h.get("requester_agent_id")) or "-", {"agent_id": m.s(h.get("requester_agent_id")), "name": m.s(h.get("requester_name")) or "—", "team": m.s(h.get("team")),
                                                                    "meetings": 0, "done": 0, "no_show": 0, "contracts": 0})
        r["meetings"] += 1
        r["done"] += 1 if st == m.DONE else 0
        r["no_show"] += 1 if st == m.NO_SHOW else 0
        r["contracts"] += nc
    top_listings = sorted(lst.values(), key=lambda x: (-x["meetings"], -x["done"], x["address"]))[:8]
    owners_l = sorted(({**o, "listings": len(o["listings"])} for o in owners.values()), key=lambda x: (-x["meetings"], x["name"]))[:15]
    reqs_l = sorted(reqs.values(), key=lambda x: (-x["done"], -x["meetings"], x["name"]))[:15]
    if scope == "mine":
        aid = m.s(viewer.get("agent_id"))
        owners_l = [o for o in owners_l if o["agent_id"] == aid]
        reqs_l = [r for r in reqs_l if r["agent_id"] == aid]
    return {"scope": scope, "days": days, "totals": tot, "top_listings": top_listings, "owners": owners_l, "requesters": reqs_l}
