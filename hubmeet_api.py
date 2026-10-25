"""
Safe Home Property Hub — შეხვედრები განცხადებიდან: HTTP API (`/api/hub/...`). ახალი endpoint-ებია; არსებულებს არ ცვლის.

ნაკადი: აგენტი კატალოგში ირჩევს ბინას -> POST /api/hub/meetings (კლიენტი, თარიღი/დრო, გაქირავების პერიოდი, თანამშრომლობის პირობები).
  * საკუთარ ბინაზე (ან თავისი გუნდის ბინაზე თიმლიდერი) — მაშინვე "planned" + ჩვეულებრივი ჩანაწერი `Meetings` ცხრილში (KPI/ისტორია/ხელშეკრულება/CRM);
  * სხვა აგენტის ბინაზე — "pending": მფლობელ აგენტს და მის თიმლიდერს Telegram-ში მიდის; ადასტურებს/უარყოფს Mini App-იდან.
უფლებები სერვერზეა: კლიენტის ტელეფონი მხოლოდ მომთხოვნ მხარეს; ბინის მფლობელის ნომერი არასდროს გადაეცემა სხვა აგენტს.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify, request

import hubmeet_model as m
import hubmeet_store as store
from hubmeet_model import HubMeetError
from listings_api import viewer_of

log = logging.getLogger("safehome-hubmeet-api")


def register(app, *, authed, audit, rate_limited, get_agents, team_lead_for, notify, admin_chat_ids,
             find_listing, create_base_meeting, crm_hook=None, contract_counts=None, get_tasks=None, find_listing_ref=None) -> None:
    """authed() -> (agent, admin, err); notify(chat_id, text); find_listing(listing_id) -> `Listings` სტრიქონი (შიდა ველებით);
    create_base_meeting(fields) -> meeting_id (ძველ `Meetings` ცხრილში); crm_hook(hub_row, meeting_id) — CRM კლიენტის გამდიდრება (არასავალდებულო)."""

    def _agent_by_id(aid):
        return next((a for a in get_agents() if str(a.get("agent_id")) == str(aid)), None)

    def _chat(aid):
        a = _agent_by_id(aid)
        try:
            return int(a.get("telegram_chat_id")) if a and a.get("telegram_chat_id") else None
        except (TypeError, ValueError):
            return None

    def _safe_notify(chat_id, text):
        if not chat_id:
            return
        try:
            notify(int(chat_id), text)
        except Exception:  # noqa: BLE001
            log.exception("Property Hub: შეტყობინება ვერ გაიგზავნა")

    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                return fn(agent, admin, *a, **kw)
            except HubMeetError as e:
                return jsonify(error=str(e)), e.status
            except Exception:  # noqa: BLE001
                log.exception("hub meetings API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    def _who(agent, admin):
        return str((agent or {}).get("name") or ("ადმინი" if admin else "აგენტი"))

    def _summary(h: dict, title: str, with_phone: bool = False) -> str:
        rent = "ქირ" in str(h.get("deal_type"))
        lines = [title,
                 f"🏠 {h.get('listing_title') or 'ბინა'} · {h.get('district') or ''} {h.get('address') or ''}".strip(),
                 f"💰 ${h.get('price_usd') or '—'}{'/თვე' if rent else ''}",
                 f"📅 {h.get('meeting_date')} {h.get('meeting_time')}",
                 f"👤 კლიენტი: {h.get('client_name')}" + (f" · {h.get('client_phone')}" if with_phone else ""),
                 f"🧑‍💼 აგენტი: {h.get('requester_name')}" + (f" → მფლობელი: {h.get('owner_agent_name')}" if h.get("coop") else "")]
        if h.get("rental_months"):
            lines.append(f"⏳ პერიოდი: {h.get('rental_months')} თვე" + (f" · შესვლა {h.get('move_in_date')}" if h.get("move_in_date") else ""))
        if h.get("coop_terms"):
            lines.append(f"🤝 პირობები: {h.get('coop_terms')}")
        if h.get("owner_availability"):
            lines.append(f"🕒 მეპატრონე თავისუფალია: {h.get('owner_availability')}")
        return "\n".join(lines)

    def _plan_base(h: dict, requester: dict | None, owner_phone_ok: bool) -> str:
        """ჩვეულებრივი ჩანაწერი `Meetings` ცხრილში (+ CRM) — KPI/ისტორია/ხელშეკრულებები უცვლელად მუშაობს. მეპატრონის ნომერი მხოლოდ თუ უფლება აქვს."""
        lst = find_listing(h.get("listing_id")) or {}
        req = requester or _agent_by_id(h.get("requester_agent_id")) or {}
        lead = team_lead_for(req.get("team")) if req.get("team") else None
        fields = {
            "owner_phone": (lst.get("owner_number") or "") if owner_phone_ok else "",
            "myhome_link": f"https://www.myhome.ge/pr/{h['myhome_id']}" if h.get("myhome_id") else "",
            "myhome_id": h.get("myhome_id") or "", "ssge_id": h.get("ssge_id") or "",
            "ssge_link": f"https://home.ss.ge/ka/udzravi-qoneba/{h['ssge_id']}" if h.get("ssge_id") else "",
            "condition": lst.get("condition") or "", "client_phone": h.get("client_phone") or "", "district": h.get("district") or "",
            "address": h.get("address") or "", "meeting_date": h.get("meeting_date") or "", "price": f"{h.get('price_usd') or ''}$",
            "percent": m.coop_percent(h.get("coop_terms")), "time": h.get("meeting_time") or "",
            "internal_number": req.get("internal_number") or "", "team_leader": (lead or {}).get("name", ""),
            "agent_id": h.get("requester_agent_id") or "", "agent_name": h.get("requester_name") or "", "agent_phone": req.get("phone") or "",
        }
        mid = create_base_meeting(fields)
        store.attach_meeting_id(h["hub_id"], mid)
        h["meeting_id"] = mid
        if crm_hook:
            try:
                crm_hook(h, mid)
            except Exception:  # noqa: BLE001
                log.exception("Property Hub: CRM კლიენტის განახლება ვერ მოხერხდა")
        return mid

    def _admins(text):
        for cid in admin_chat_ids():
            _safe_notify(cid, text)

    # ------------------------------------------------------------------ შექმნა
    @app.post("/api/hub/meetings")
    @rate_limited("hub_write")
    @_guard
    def hub_meeting_create(agent, admin):
        if not agent:
            raise HubMeetError("მხოლოდ დარეგისტრირებული აგენტისთვის", 403)
        data = request.get_json(silent=True) or {}
        listing = find_listing(data.get("listing_id"))
        viewer = viewer_of(agent, admin)
        # კლიენტის დავალებასთან (task) ბმა: მხოლოდ არსებული დავალება, რომელიც ამ აგენტზეა (ან მენეჯერი ქმნის); სხვა შემთხვევაში იგნორირდება
        tid = m.s(data.get("task_id"), 24)
        if tid and get_tasks:
            t = next((x for x in get_tasks() if str(x.get("task_id")) == tid), None)
            mgr = bool(admin) or str(agent.get("role") or "") == "team_lead"
            if not t or not (mgr or str(t.get("assigned_to")) == str(agent.get("agent_id"))):
                tid = ""
        data = dict(data, task_id=tid if get_tasks else "")
        h = store.create(listing, agent, viewer, data)
        if h["status"] == m.PLANNED:
            _plan_base(h, agent, owner_phone_ok=True)
            txt = _summary(h, f"📅 ახალი შეხვედრა — {h['requester_name']}")
            lead = team_lead_for(agent.get("team")) if agent.get("team") else None
            if lead and str(lead.get("agent_id")) != str(agent.get("agent_id")):
                _safe_notify(_chat(lead.get("agent_id")), txt)
            if h.get("coop") and h.get("owner_agent_id") and str(h["owner_agent_id"]) != str(agent.get("agent_id")):
                _safe_notify(_chat(h["owner_agent_id"]), _summary(h, "📅 თქვენს ბინაზე შეხვედრა დაიგეგმა (გუნდის ლიდერის მიერ)"))
            _admins(txt)
        else:
            txt = _summary(h, f"🤝 თანამშრომლობის მოთხოვნა შეხვედრაზე — {h['requester_name']}") + "\n\nდაადასტურეთ Mini App-ში: განცხადებები → შეხვედრები."
            _safe_notify(_chat(h["owner_agent_id"]), txt)
            ol = team_lead_for(h["owner_team"]) if h.get("owner_team") else None
            if ol and str(ol.get("agent_id")) != str(h["owner_agent_id"]):
                _safe_notify(_chat(ol.get("agent_id")), txt)
        audit(agent, admin, "hub_meeting_create", "hub_meeting", h["hub_id"], metadata={"listing": h["listing_id"], "status": h["status"], "coop": bool(h.get("coop"))})
        return jsonify(ok=True, meeting=store.project(h, viewer)), 201

    # ------------------------------------------------------------------ სია / სტატისტიკა
    @app.get("/api/hub/meetings")
    @rate_limited("hub_read")
    @_guard
    def hub_meetings_list(agent, admin):
        viewer = viewer_of(agent, admin)
        view = (request.args.get("view") or "upcoming").strip()
        try:
            days = int(request.args.get("days") or 30)
        except ValueError:
            days = 30
        rows = store.list_for(viewer, view if view in ("upcoming", "past", "pending", "all") else "upcoming", days, (request.args.get("listing_id") or "").strip())
        items = [store.project(h, viewer) for h in rows]
        vis = store.visible(viewer)
        meta = {"pending_for_me": sum(1 for h in vis if m.s(h.get("status")) == m.PENDING and store.sides(h, viewer)[0]),
                "my_pending": sum(1 for h in vis if m.s(h.get("status")) == m.PENDING and store.sides(h, viewer)[1])}
        return jsonify(items=items, total=len(items), meta=meta, status_labels=m.STATUS_LABELS, outcomes=m.OUTCOMES)

    # ------------------------------------------------------------------ კლიენტები (დავალებები): ერთიანი ინბოქსი — ბინასთან ერთად
    def _lead_listing(ref: str):
        """დავალებაში მითითებული ბინა (MyHome/ss.ge ID ან შიდა ID) -> კატალოგის ბინა (საჯარო ველები)."""
        if not ref or not find_listing_ref:
            return None
        L = find_listing_ref(ref)
        if not L:
            return None
        photos = [p for p in str(L.get("photos") or "").split("|") if p.startswith("http")]
        return {"listing_id": L.get("listing_id"), "address": L.get("address"), "district": L.get("district"), "price_usd": L.get("price_usd"),
                "deal_type": L.get("deal_type"), "rooms": L.get("rooms"), "area": L.get("area"), "photo": photos[0] if photos else "",
                "agent_name": L.get("agent_name"), "myhome_id": L.get("myhome_id"), "ssge_id": L.get("ssge_id")}

    @app.get("/api/hub/leads")
    @rate_limited("hub_read")
    @_guard
    def hub_leads(agent, admin):
        """კლიენტები/დავალებები ბინებთან ერთად: აგენტი — თავისი; თიმლიდერი — გუნდის; ადმინი — ყველა. ვინ რომელ ბინაზე შემოვიდა და რა შეხვედრაა დაგეგმილი."""
        viewer = viewer_of(agent, admin)
        view = (request.args.get("view") or "open").strip()
        agents_all = get_agents()
        mgr = bool(admin) or viewer["role"] == "team_lead"
        if admin:
            scope_ids = None
        elif viewer["role"] == "team_lead" and viewer["team"]:
            scope_ids = {str(a.get("agent_id")) for a in agents_all if str(a.get("team", "")).strip() == viewer["team"]}
        else:
            scope_ids = {viewer["agent_id"]} if viewer["agent_id"] else set()
        rows = [t for t in (get_tasks() if get_tasks else []) if scope_ids is None or str(t.get("assigned_to")) in scope_ids]
        done = lambda t: str(t.get("status")) == "Done"  # noqa: E731
        rows = [t for t in rows if (done(t) if view == "done" else not done(t))]
        rows.sort(key=lambda t: str(t.get("created_at", "")), reverse=True)
        by_task: dict[str, list] = {}
        for h in store.all_rows():
            if m.s(h.get("task_id")):
                by_task.setdefault(m.s(h.get("task_id")), []).append(h)
        items = []
        for t in rows[:120]:
            tid = str(t.get("task_id"))
            mts = sorted(by_task.get(tid, []), key=lambda h: (m.s(h.get("meeting_date")), m.s(h.get("meeting_time"))))
            items.append({
                "task_id": tid, "title": t.get("title", ""), "notes": t.get("description", ""), "assigned_to": str(t.get("assigned_to")),
                "assigned_to_name": t.get("assigned_to_name", ""), "status": t.get("status", ""), "priority": t.get("priority", ""),
                "created_at": t.get("created_at", ""), "lead_type": t.get("lead_type", ""), "client_phone": t.get("client_phone", ""),
                "deal_type": t.get("deal_type", ""), "viewing_time": t.get("viewing_time", ""), "listing_ref": t.get("listing_id", ""),
                "seen": str(t.get("seen", "")).strip().lower() in ("1", "yes", "true", "y") or bool(str(t.get("seen_at", "")).strip()),
                "is_mine": str(t.get("assigned_to")) == viewer["agent_id"],
                "listing": _lead_listing(str(t.get("listing_id") or "")) if t.get("lead_type") == "listing" or t.get("listing_id") else None,
                "meetings": [{"hub_id": h["hub_id"], "status": h.get("status"), "meeting_date": h.get("meeting_date"), "meeting_time": h.get("meeting_time"),
                              "status_label": m.STATUS_LABELS.get(m.s(h.get("status")), "")} for h in mts][:5],
            })
        agents_out = []
        if mgr:
            elig = [a for a in agents_all if str(a.get("active", "yes")).strip().lower() != "no" and (admin or str(a.get("team", "")).strip() == viewer["team"])]
            agents_out = sorted(({"agent_id": str(a.get("agent_id")), "name": a.get("name", ""), "team": a.get("team", "")} for a in elig), key=lambda r: r["name"] or "")
        unseen = sum(1 for i in items if i["is_mine"] and not i["seen"])
        return jsonify(items=items, total=len(items), unseen_mine=unseen, can_manage=mgr, agents=agents_out)

    @app.get("/api/hub/stats")
    @rate_limited("hub_read")
    @_guard
    def hub_stats(agent, admin):
        try:
            days = max(1, min(int(request.args.get("days") or 30), 365))
        except ValueError:
            days = 30
        cc = contract_counts() if contract_counts else {}
        return jsonify(store.stats(viewer_of(agent, admin), days, contract_counts=cc))

    # ------------------------------------------------------------------ გადაწყვეტილება / სტატუსი
    @app.post("/api/hub/meetings/<hub_id>/decide")
    @rate_limited("hub_write")
    @_guard
    def hub_meeting_decide(agent, admin, hub_id):
        body = request.get_json(silent=True) or {}
        viewer = viewer_of(agent, admin)
        action = str(body.get("action") or "").strip()
        h = store.decide(hub_id, viewer, _who(agent, admin), action, body.get("reason") or "", body.get("meeting_date") or "", body.get("meeting_time") or "")
        if action == "accept":
            _plan_base(h, None, owner_phone_ok=False)
            txt = _summary(h, "✅ თანამშრომლობა დადასტურდა — შეხვედრა დაგეგმილია")
            _safe_notify(_chat(h["requester_agent_id"]), txt)
            rl = team_lead_for(h["team"]) if h.get("team") else None
            if rl and str(rl.get("agent_id")) != str(h["requester_agent_id"]):
                _safe_notify(_chat(rl.get("agent_id")), txt)
            _admins(_summary(h, f"📅 ახალი შეხვედრა (თანამშრომლობა) — {h['requester_name']}"))
        else:
            _safe_notify(_chat(h["requester_agent_id"]), _summary(h, "❌ შეხვედრის მოთხოვნა უარყოფილია") + (f"\n💬 მიზეზი: {h.get('reject_reason')}" if h.get("reject_reason") else ""))
        audit(agent, admin, "hub_meeting_" + action, "hub_meeting", hub_id, metadata={"status": h["status"]})
        return jsonify(ok=True, meeting=store.project(h, viewer))

    @app.post("/api/hub/meetings/<hub_id>/status")
    @rate_limited("hub_write")
    @_guard
    def hub_meeting_status(agent, admin, hub_id):
        body = request.get_json(silent=True) or {}
        viewer = viewer_of(agent, admin)
        before = store.get(hub_id, fresh=True)
        h = store.set_status(hub_id, viewer, _who(agent, admin), str(body.get("status") or "").strip(), body.get("outcome") or "", body.get("note") or "")
        if h["status"] == m.CANCELLED and before:
            o, r = store.sides(before, viewer)
            target = h["owner_agent_id"] if (r and not o) else h["requester_agent_id"]
            if target and target != str((agent or {}).get("agent_id") or ""):
                _safe_notify(_chat(target), _summary(h, "🚫 შეხვედრა გაუქმდა"))
        audit(agent, admin, "hub_meeting_status", "hub_meeting", hub_id, metadata={"status": h["status"], "outcome": h.get("outcome", "")})
        return jsonify(ok=True, meeting=store.project(h, viewer))
