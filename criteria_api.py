"""
კლიენტის კრიტერიუმები და ავტომატური შესატყვისობა — HTTP API (`/api/hub/criteria...`). ახალი endpoint-ებია; არსებულს არ ცვლის.

წვდომა სერვერზე: აგენტი — საკუთარი კრიტერიუმები; თიმლიდერი — გუნდის; ადმინი — ყველა. ბინების პროექცია იგივეა, რაც კატალოგში: მესაკუთრის ნომერი/შენიშვნა
სხვის ბინაზე არ გადადის. ახალი ბინის დამატებისას შესაბამის აგენტს ეგზავნება შეტყობინება (დუბლირებისგან დაცვა: ცხრილში მუდმივი სია + შეტყობინების გასაღები).
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify, request

import criteria_model as m
import criteria_store as store
import listings_model as lm
import listings_store as lst
import matching
from criteria_model import CriteriaError

log = logging.getLogger("safehome-criteria-api")


def viewer_of(agent, admin: bool) -> dict:
    agent = agent or {}
    return {"agent_id": str(agent.get("agent_id") or ""), "role": str(agent.get("role") or "").strip(),
            "team": str(agent.get("team") or "").strip(), "admin": bool(admin)}


def _live_listings() -> list[dict]:
    return [r for r in lst.all_rows() if str(r.get("active") or "").strip().lower() != "no"
            and str(r.get("archived") or "").strip().lower() not in ("yes", "true", "1")]


def matches_for(row: dict, viewer: dict, limit: int = 25, now=None) -> list[dict]:
    now = now or lst.now_dt()
    th = lm.thresholds()
    crit = m.to_match_dict(row)
    out = []
    for hit in matching.rank(crit, _live_listings(), limit=limit):
        L = hit["listing"]
        proj = lm.project(L, now, lst.is_privileged(L, viewer), th)
        out.append({"listing": proj, "match": hit["match"]})
    return out


def _fmt_notice(row: dict, listing: dict, res: dict) -> str:
    price = lm.num(listing.get("price_usd"))
    lines = [f"🎯 ახალი ბინა კლიენტისთვის — {row.get('client_name') or row.get('client_phone')} (შესაბამისობა {res['score']}%)",
             f"🏠 {listing.get('district') or ''} {listing.get('address') or ''}".strip(),
             f"💰 {('$%g' % price) if price is not None else '—'} · {listing.get('area') or '—'} მ² · {listing.get('rooms') or '—'} ოთ."]
    lines += res["matched"][:4] + res["mismatched"][:3] + res["unknown"][:2]
    lines.append("გახსენით Mini App → განცხადებები → სამუშაო → კრიტერიუმები.")
    return "\n".join(lines)


def notify_new_listing(listing: dict, notify, agent_chat) -> int:
    """ახალი განცხადების დამატებისას: ყველა აქტიურ კრიტერიუმს ვადარებთ; ≥ MIN_NOTIFY_SCORE და არ არის მკაცრად შეუსაბამო -> აგენტს შეტყობინება.
    notify(chat_id, text, key) ; agent_chat(agent_id) -> chat_id. აბრუნებს გაგზავნილ შეტყობინებათა რაოდენობას. ორჯერ არასდროს (mark_notified + key)."""
    sent = 0
    if str(listing.get("active") or "").strip().lower() == "no":
        return 0
    for row in store.all_rows(fresh=True):
        if str(row.get("active") or "").strip().lower() == "no":
            continue
        if str(row.get("agent_id")) == str(listing.get("agent_id")):
            continue                                   # საკუთარი ახალი განცხადება აგენტმა თავად იცის
        crit = m.to_match_dict(row)
        if not (crit.get("budget_max") or crit.get("budget_min") or crit.get("districts")):
            continue                                   # ძალიან ზოგადი კრიტერიუმი — შეტყობინებებით არ დავამძიმებთ
        res = matching.match(crit, listing)
        if res["hard_fail"] or res["score"] < matching.MIN_NOTIFY_SCORE:
            continue
        if any(x.startswith("❌") for x in res["mismatched"]):
            continue                                   # შეტყობინება მხოლოდ მაშინ, როცა არცერთი მოთხოვნა ცალსახად არ ირღვევა (ახლოს მყოფი „⚠️“ ჩვენდება)
        chat = agent_chat(row.get("agent_id"))
        if not chat:
            continue
        if not store.mark_notified(row.get("criteria_id"), str(listing.get("listing_id"))):
            continue
        notify(chat, _fmt_notice(row, listing, res), f"match:{row.get('criteria_id')}:{listing.get('listing_id')}")
        sent += 1
    return sent


def register(app, *, authed, audit, rate_limited) -> None:
    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                return fn(agent, admin, *a, **kw)
            except CriteriaError as e:
                return jsonify(error=str(e)), e.status
            except Exception:  # noqa: BLE001
                log.exception("criteria API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    @app.get("/api/hub/criteria")
    @rate_limited("hub_read")
    @_guard
    def criteria_list(agent, admin):
        v = viewer_of(agent, admin)
        rows = store.list_for(v, phone=request.args.get("phone", ""), task_id=request.args.get("task_id", ""),
                              active_only=request.args.get("active") in ("1", "true"))
        return jsonify(items=[m.project(r) for r in rows[:100]], total=len(rows))

    @app.post("/api/hub/criteria")
    @rate_limited("hub_write")
    @_guard
    def criteria_save(agent, admin):
        v = viewer_of(agent, admin)
        data = request.get_json(silent=True) or {}
        cid = str(data.get("criteria_id") or "").strip()
        if cid:
            row = store.update(cid, v, data)
            audit(agent, admin, "criteria_update", "criteria", cid)
            return jsonify(ok=True, criteria=m.project(row))
        row = store.create(agent, v, data)
        existing = bool(row.pop("_existing", False))
        if not existing:
            audit(agent, admin, "criteria_create", "criteria", row["criteria_id"])
        return jsonify(ok=True, existing=existing, criteria=m.project(row)), (200 if existing else 201)

    @app.post("/api/hub/criteria/<criteria_id>/status")
    @rate_limited("hub_write")
    @_guard
    def criteria_status(agent, admin, criteria_id):
        body = request.get_json(silent=True) or {}
        if "active" not in body:
            raise CriteriaError("active საჭიროა")
        res = store.set_active(criteria_id, viewer_of(agent, admin), bool(body.get("active")))
        audit(agent, admin, "criteria_status", "criteria", criteria_id, metadata={"active": res["active"]})
        return jsonify(ok=True, **res)

    @app.get("/api/hub/criteria/<criteria_id>/matches")
    @rate_limited("hub_read")
    @_guard
    def criteria_matches(agent, admin, criteria_id):
        v = viewer_of(agent, admin)
        row = store.get(criteria_id)
        if not row or not store.can_see(row, v):
            raise CriteriaError("კრიტერიუმი ვერ მოიძებნა", 404)
        items = matches_for(row, v)
        return jsonify(criteria=m.project(row), items=items, total=len(items))
