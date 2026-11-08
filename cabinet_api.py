"""
👤 პირადი კაბინეტი — ერთი მოთხოვნით (`GET /api/cabinet`) ყველაფერი, რაც აგენტს/მენეჯერს „ახლა“ სჭირდება: კლიენტები (დავალებები + Telegram ლიდები),
დასადასტურებელი, ვადაგადაცილებული follow-up-ები, შეხვედრები, ყურადღების საჭირო საკითხები, ჩემი ბინები, ექსკლუზივები, კრიტერიუმები, გაფრთხილებები.
მენეჯერს (თიმლიდერი — თავისი გუნდი; დირექტორი — ყველა/არჩეული გუნდი) დამატებით: გუნდის ცხრილი აგენტების მიხედვით (ფილტრი: გუნდი, აგენტი, პერიოდი, „მხოლოდ პრობლემური“).

მხოლოდ კითხულობს (უკვე კეშირებულ ცხრილებს); არაფერს ცვლის. კლიენტის ტელეფონები აქ არ ბრუნდება (მხოლოდ რაოდენობები) — დეტალები თავის ეკრანზეა უფლებებით.
"""

from __future__ import annotations

import datetime
import functools
import logging

from flask import jsonify, request

log = logging.getLogger("safehome-cabinet")

TG_OPEN = ("assigned", "acknowledged", "contacted", "waiting")


def _s(v, cap: int = 200) -> str:
    return str(v if v is not None else "").strip()[:cap]


def _seen(t: dict) -> bool:
    return _s(t.get("seen")).lower() in ("1", "yes", "true", "y") or bool(_s(t.get("seen_at")))


def _parse_local(s):
    try:
        return datetime.datetime.strptime(_s(s).replace("T", " ")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _role(agent: dict | None, admin: bool) -> str:
    if admin:
        return "admin"
    return "team_lead" if _s((agent or {}).get("role")) == "team_lead" else "agent"


def build(viewer: dict, *, agents: list, tasks: list, tg_leads: list, hub_rows: list, attention: list, listings: list, exclusives: list,
          criteria: list, followups_open: list, warnings: list, now_local: datetime.datetime, now_utc_iso: str, days: int = 30,
          team: str = "", agent_filter: str = "", problems_only: bool = False) -> dict:
    """წმინდა ფუნქცია (ტესტირებადი): ყველა წყარო გადმოეცემა. viewer = {agent_id, role, team, admin, name}."""
    me = _s(viewer.get("agent_id"))
    admin = bool(viewer.get("admin"))
    mgr = admin or viewer.get("role") == "team_lead"
    active = [a for a in agents if _s(a.get("active") or "yes").lower() not in ("no", "false", "0")]
    teams = sorted({_s(a.get("team")) for a in active if _s(a.get("team"))})
    if admin:
        scope = [a for a in active if not team or _s(a.get("team")) == team]
    elif viewer.get("role") == "team_lead" and _s(viewer.get("team")):
        scope = [a for a in active if _s(a.get("team")) == _s(viewer.get("team"))]
    else:
        scope = [a for a in active if _s(a.get("agent_id")) == me]
    selectable = list(scope)
    if agent_filter and mgr:
        scope = [a for a in scope if _s(a.get("agent_id")) == agent_filter]
    ids = {_s(a.get("agent_id")) for a in scope}
    names = {_s(a.get("agent_id")): _s(a.get("name")) for a in agents}
    listing_team = {_s(r.get("listing_id")): _s(r.get("team")) for r in listings}
    today = now_local.date().strftime("%Y-%m-%d")
    tomorrow = (now_local.date() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff = (now_local - datetime.timedelta(days=max(1, days))).strftime("%Y-%m-%d")

    def row0(aid):
        return {"agent_id": aid, "name": names.get(aid, aid), "team": next((_s(a.get("team")) for a in scope if _s(a.get("agent_id")) == aid), ""),
                "clients_open": 0, "clients_unseen": 0, "tg_unconfirmed": 0, "tg_open": 0, "tg_overdue": 0, "followups_overdue": 0, "followups_open": 0,
                "meetings": 0, "meetings_done": 0, "no_show": 0, "meetings_upcoming": 0, "attention": 0, "listings": 0, "exclusives": 0, "warnings": 0}

    per = {aid: row0(aid) for aid in ids}
    for t in tasks:
        aid = _s(t.get("assigned_to"))
        if aid in per and _s(t.get("status")) != "Done":
            per[aid]["clients_open"] += 1
            per[aid]["clients_unseen"] += 0 if _seen(t) else 1
    tg_new = 0
    for r in tg_leads:
        if _s(r.get("kind")) != "lead":
            continue
        st = _s(r.get("status")) or "new"
        aid = _s(r.get("assigned_agent_id"))
        if st == "new":
            lt = listing_team.get(_s(r.get("listing_key")), "")
            if admin and (not team or lt == team or not lt):
                tg_new += 1
            elif mgr and not admin and lt == _s(viewer.get("team")):
                tg_new += 1
            continue
        if aid not in per or st not in TG_OPEN:
            continue
        per[aid]["tg_open"] += 1
        per[aid]["tg_unconfirmed"] += 1 if st == "assigned" else 0
        due = _parse_local(r.get("follow_up_at"))
        if st in ("contacted", "waiting") and due and due < now_local:
            per[aid]["tg_overdue"] += 1
    for f in followups_open:
        aid = _s(f.get("agent_id"))
        if aid in per and _s(f.get("status") or "open") == "open":
            per[aid]["followups_open"] += 1
            per[aid]["followups_overdue"] += 1 if _s(f.get("due_at")) and _s(f.get("due_at")) < now_utc_iso else 0
    upcoming_me = {"today": 0, "tomorrow": 0, "pending_for_me": 0}
    for h in hub_rows:
        aid = _s(h.get("requester_agent_id"))
        st = _s(h.get("status"))
        md = _s(h.get("meeting_date"))
        if aid in per and (_s(h.get("created_at"))[:10] >= cutoff or md >= today):
            p = per[aid]
            p["meetings"] += 1 if st not in ("cancelled", "rejected") else 0
            p["meetings_done"] += 1 if st == "done" else 0
            p["no_show"] += 1 if st == "no_show" else 0
            p["meetings_upcoming"] += 1 if st in ("pending", "planned") and md >= today else 0
        if st in ("pending", "planned") and (aid in ids or _s(h.get("owner_agent_id")) in ids):
            upcoming_me["today"] += 1 if md == today else 0
            upcoming_me["tomorrow"] += 1 if md == tomorrow else 0
        if st == "pending" and _s(h.get("owner_agent_id")) in ids:
            upcoming_me["pending_for_me"] += 1
    by_name = {v: k for k, v in names.items() if k in ids}
    for it in attention:
        aid = by_name.get(_s(it.get("agent_name")))
        if aid in per:
            per[aid]["attention"] += 1
    for r in listings:
        aid = _s(r.get("agent_id"))
        if aid in per and _s(r.get("active") or "yes").lower() != "no" and _s(r.get("archived")).lower() not in ("yes", "true", "1"):
            per[aid]["listings"] += 1
    for e in exclusives:
        aid = _s(e.get("agent_id"))
        if aid in per:
            per[aid]["exclusives"] += 1
    for w in warnings:
        aid = _s(w.get("agent_id"))
        if aid in per and _s(w.get("status") or "active") not in ("dismissed", "deleted"):
            per[aid]["warnings"] += 1

    def flags(p):
        out = []
        if p["tg_unconfirmed"]:
            out.append("tg_unconfirmed")
        if p["clients_unseen"]:
            out.append("clients_unseen")
        if p["followups_overdue"] or p["tg_overdue"]:
            out.append("followup_overdue")
        if p["attention"]:
            out.append("attention")
        return out

    rows = []
    for p in per.values():
        p["flags"] = flags(p)
        p["level"] = "red" if (p["tg_unconfirmed"] or p["followups_overdue"] or p["tg_overdue"]) else ("orange" if p["flags"] else "green")
        rows.append(p)
    rows.sort(key=lambda p: ({"red": 0, "orange": 1, "green": 2}[p["level"]], -(p["tg_unconfirmed"] + p["followups_overdue"] + p["tg_overdue"] + p["attention"]), p["name"]))
    total = {k: sum(p[k] for p in rows) for k in ("clients_open", "clients_unseen", "tg_unconfirmed", "tg_open", "tg_overdue", "followups_overdue", "followups_open",
                                                 "meetings", "meetings_done", "no_show", "meetings_upcoming", "attention", "listings", "exclusives", "warnings")}
    total.update(upcoming_me)
    total["tg_new"] = tg_new if mgr else 0
    total["criteria"] = sum(1 for c in criteria if _s(c.get("active")).lower() != "no")
    out = {"role": "admin" if admin else ("team_lead" if mgr else "agent"), "manager": mgr, "days": days, "totals": total, "teams": teams if admin else [],
           "agents": [{"agent_id": _s(a.get("agent_id")), "name": _s(a.get("name")), "team": _s(a.get("team"))} for a in sorted(selectable, key=lambda a: _s(a.get("name")))] if mgr else [],
           "generated_at": now_local.strftime("%Y-%m-%d %H:%M")}
    if mgr:
        out["team"] = [p for p in rows if not problems_only or p["level"] != "green"]
    else:
        out["me"] = rows[0] if rows else row0(me)
    return out


def register(app, *, authed, rate_limited, get_agents, get_tasks, get_warnings, get_exclusives) -> None:
    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                return fn(agent, admin, *a, **kw)
            except Exception:  # noqa: BLE001
                log.exception("cabinet API შეცდომა")
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    def _safe(fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — ერთი წყაროს ხარვეზმა მთელი კაბინეტი არ უნდა გააჩეროს
            log.warning("cabinet: წყარო ვერ ჩაიტვირთა", exc_info=True)
            return default

    @app.get("/api/cabinet")
    @rate_limited("hub_read")
    @_guard
    def cabinet(agent, admin):
        import config
        import crm2_store
        import criteria_store
        import hubmeet_store
        import listings_store
        import tgnet_store
        from listings_api import viewer_of
        viewer = viewer_of(agent, admin)
        viewer["name"] = _s((agent or {}).get("name"))
        a = request.args
        try:
            days = max(1, min(int(a.get("days") or 30), 365))
        except ValueError:
            days = 30
        agents = get_agents()
        tasks = _safe(get_tasks, [])
        mgr = bool(admin) or viewer["role"] == "team_lead"
        if admin:
            scope_ids = None
        elif viewer["role"] == "team_lead" and viewer["team"]:
            scope_ids = {_s(x.get("agent_id")) for x in agents if _s(x.get("team")) == viewer["team"]}
        else:
            scope_ids = {viewer["agent_id"]}
        now_local = hubmeet_store.now_dt()
        res = build(viewer, agents=agents, tasks=tasks, tg_leads=_safe(tgnet_store.list_lead_rows, []), hub_rows=_safe(hubmeet_store.all_rows, []),
                    attention=_safe(lambda: hubmeet_store.attention_items(viewer, tasks, scope_ids), []), listings=_safe(listings_store.all_rows, []),
                    exclusives=_safe(lambda: get_exclusives(status="active"), []), criteria=_safe(lambda: criteria_store.list_for(viewer, active_only=True), []),
                    followups_open=_safe(lambda: crm2_store.list_followups(status="open"), []), warnings=_safe(lambda: get_warnings(days=config.WARNING_WINDOW_DAYS), []),
                    now_local=now_local, now_utc_iso=(now_local - datetime.timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"), days=days,
                    team=_s(a.get("team"), 60) if admin else "", agent_filter=_s(a.get("agent"), 40) if mgr else "", problems_only=a.get("problems") == "1")
        res["me_name"] = viewer["name"] or ("დირექტორი" if admin else "")
        res["me_team"] = viewer["team"]
        return jsonify(res)
