"""
CRM 2.0 (P2.3) — HTTP API (`/api/crm2/...`).

ახალი endpoint-ებია; არსებულ endpoint-ებს არ ცვლის. webserver.py მხოლოდ ერთ ხაზს უმატებს:
`crm2_api.register(app, ...)` — საჭირო დამხმარეები (ავტორიზაცია, audit, rate limit) აქედან
გადაეცემა, რომ მოდულებს შორის წრიული იმპორტი არ გაჩნდეს.

ხილვადობა (სერვერზე, არა frontend-ზე):
  * ადმინი — ყველა კლიენტი;
  * თიმლიდერი — იმ აგენტების კლიენტები, რომლებიც მის გუნდშია;
  * აგენტი — მხოლოდ საკუთარზე მიმაგრებული კლიენტები.
უხილავი კლიენტის id-ზე პასუხი 404 (არსებობას არ ვამხელთ).

ჩაწერები (follow-up / შენიშვნა) AuditLog-ში იწერება ნამდვილი Telegram ID-ით.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

import crm2_model as m
import crm2_store as store

log = logging.getLogger("safehome-crm2-api")

MAX_ACTION_LEN = 500
MAX_NOTE_LEN = 2000


def _scope_checker(agent, admin: bool, is_team_lead, get_agents):
    """აბრუნებს ფუნქციას `visible(client_row) -> bool` მიმდინარე მომხმარებლისთვის."""
    if admin:
        return lambda c: True
    my_id = str((agent or {}).get("agent_id", ""))
    if is_team_lead(agent):
        team = str(agent.get("team", "")).strip()
        team_ids = {str(a.get("agent_id")) for a in get_agents() if str(a.get("team", "")).strip() == team}
        return lambda c: str(c.get("assigned_agent_id", "")) in team_ids or (
            not c.get("assigned_agent_id") and str(c.get("team", "")).strip() == team)
    return lambda c: bool(my_id) and str(c.get("assigned_agent_id", "")) == my_id


def _public_client(c: dict) -> dict:
    keys = ("client_id", "phone_raw", "phone_norm", "name", "status", "source", "assigned_agent_id",
            "assigned_agent_name", "team", "deal_type", "budget", "notes", "created_at", "updated_at",
            "last_activity_at")
    return {k: c.get(k, "") for k in keys}


def register(app, *, authed, is_team_lead, audit, rate_limited, get_agents) -> None:
    """Flask app-ზე ამატებს CRM 2.0 endpoint-ებს.
    authed() -> (agent, admin, err_response); audit(agent, admin, action, entity_type, entity_id, metadata=...)."""

    def _ctx():
        agent, admin, err = authed()
        if err:
            return None, None, None, err
        return agent, admin, _scope_checker(agent, admin, is_team_lead, get_agents), None

    def _client_or_404(client_id, visible):
        c = store.get_client(client_id)
        if c is None or c.get("archived") == "yes" or not visible(c):
            return None
        return c

    # ---------------------------------------------------------------- წაკითხვა
    @app.get("/api/crm2/clients")
    @rate_limited("crm2_read")
    def crm2_clients():
        agent, admin, visible, err = _ctx()
        if err:
            return err
        status = (request.args.get("status") or "").strip() or None
        q = (request.args.get("q") or "").strip().lower()
        qd = m.normalize_phone(q)
        rows = [c for c in store.list_clients(status=status) if visible(c)]
        if q:
            rows = [c for c in rows
                    if q in str(c.get("name", "")).lower() or (qd and qd in str(c.get("phone_norm", "")))]
        fu = {}
        now = m.utc_now()
        for f in store.list_followups(status="open"):
            d = fu.setdefault(f.get("client_id"), {"open": 0, "overdue": 0})
            d["open"] += 1
            if f.get("due_at", "") < now:
                d["overdue"] += 1
        out = []
        for c in sorted(rows, key=lambda r: r.get("last_activity_at") or r.get("created_at", ""), reverse=True)[:500]:
            d = _public_client(c)
            d["open_followups"] = fu.get(c["client_id"], {}).get("open", 0)
            d["overdue_followups"] = fu.get(c["client_id"], {}).get("overdue", 0)
            out.append(d)
        return jsonify(rows=out, count=len(rows))

    @app.get("/api/crm2/clients/<client_id>")
    @rate_limited("crm2_read")
    def crm2_client_card(client_id):
        agent, admin, visible, err = _ctx()
        if err:
            return err
        c = _client_or_404(client_id, visible)
        if c is None:
            return jsonify(error="კლიენტი ვერ მოიძებნა"), 404
        return jsonify(
            client=_public_client(c),
            timeline=store.list_activities("client", client_id, limit=200),
            followups=[f for f in store.list_followups(status=None) if f.get("client_id") == client_id],
        )

    @app.get("/api/crm2/followups")
    @rate_limited("crm2_read")
    def crm2_followups():
        agent, admin, visible, err = _ctx()
        if err:
            return err
        overdue = request.args.get("overdue") in ("1", "true", "yes")
        visible_ids = {c["client_id"] for c in store.list_clients() if visible(c)}
        rows = [f for f in store.list_followups(status="open", overdue_only=overdue)
                if f.get("client_id") in visible_ids]
        if not admin and not is_team_lead(agent):
            rows = [f for f in rows if str(f.get("agent_id")) == str((agent or {}).get("agent_id", ""))]
        return jsonify(rows=rows[:500], count=len(rows))

    # ---------------------------------------------------------------- ჩაწერა
    @app.post("/api/crm2/clients/<client_id>/followups")
    @rate_limited("crm2_write")
    def crm2_followup_create(client_id):
        agent, admin, visible, err = _ctx()
        if err:
            return err
        c = _client_or_404(client_id, visible)
        if c is None:
            return jsonify(error="კლიენტი ვერ მოიძებნა"), 404
        data = request.get_json(silent=True) or {}
        action = str(data.get("next_action", "")).strip()
        if len(action) > MAX_ACTION_LEN:
            return jsonify(error=f"ტექსტი ძალიან გრძელია (მაქს. {MAX_ACTION_LEN})"), 400
        owner_id = str((agent or {}).get("agent_id") or c.get("assigned_agent_id") or "")
        owner_name = str((agent or {}).get("name") or c.get("assigned_agent_name") or "")
        try:
            fid = store.create_followup(client_id, owner_id, str(data.get("due_at", "")), action,
                                        agent_name=owner_name, by=str((agent or {}).get("agent_id") or "admin"))
            store.add_activity("client", client_id, "system", f"Follow-up დაგეგმილია: {action}",
                               agent_id=owner_id, agent_name=owner_name, source_ref=f"followup:{fid}")
        except store.Crm2Error as e:
            return jsonify(error=str(e)), 400
        audit(agent, admin, "crm2.followup_create", "followup", fid, metadata={"client_id": client_id})
        return jsonify(ok=True, followup_id=fid)

    @app.post("/api/crm2/followups/<followup_id>/close")
    @rate_limited("crm2_write")
    def crm2_followup_close(followup_id):
        agent, admin, visible, err = _ctx()
        if err:
            return err
        f = next((x for x in store.list_followups(status=None) if x.get("followup_id") == followup_id), None)
        c = _client_or_404(f.get("client_id"), visible) if f else None
        if f is None or c is None:
            return jsonify(error="follow-up ვერ მოიძებნა"), 404
        if not admin and not is_team_lead(agent) and str(f.get("agent_id")) != str((agent or {}).get("agent_id", "")):
            return jsonify(error="ეს follow-up სხვა აგენტისაა"), 403
        status = str((request.get_json(silent=True) or {}).get("status", "done"))
        try:
            closed = store.close_followup(followup_id, status)
        except store.Crm2Error as e:
            return jsonify(error=str(e)), 400
        if closed is None:
            return jsonify(ok=True, already_closed=True)  # განმეორება უვნებელია
        store.add_activity("client", c["client_id"], "system", f"Follow-up დაიხურა ({status}): {f.get('next_action', '')}",
                           agent_id=str((agent or {}).get("agent_id", "")), agent_name=str((agent or {}).get("name", "")),
                           source_ref=f"followup-close:{followup_id}")
        audit(agent, admin, "crm2.followup_close", "followup", followup_id, metadata={"status": status})
        return jsonify(ok=True)

    @app.post("/api/crm2/clients/<client_id>/notes")
    @rate_limited("crm2_write")
    def crm2_note_add(client_id):
        agent, admin, visible, err = _ctx()
        if err:
            return err
        c = _client_or_404(client_id, visible)
        if c is None:
            return jsonify(error="კლიენტი ვერ მოიძებნა"), 404
        text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
        if not text:
            return jsonify(error="ტექსტი აუცილებელია"), 400
        if len(text) > MAX_NOTE_LEN:
            return jsonify(error=f"ტექსტი ძალიან გრძელია (მაქს. {MAX_NOTE_LEN})"), 400
        aid = store.add_activity("client", client_id, "note", text,
                                 agent_id=str((agent or {}).get("agent_id", "")),
                                 agent_name=str((agent or {}).get("name", "")))
        audit(agent, admin, "crm2.note_add", "client", client_id, metadata={"length": len(text)})
        return jsonify(ok=True, activity_id=aid)
