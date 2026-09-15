"""
Mini App (ვიზუალური დაშბორდი) — მცირე Flask სერვერი, რომელიც ბოტის იმავე
პროცესში, ფონურ thread-ში ეშვება (bot.py-ის main()-იდან).

გვერდი (index.html/style.css/app.js) იტვირთება პირდაპირ ტელეგრამშივე,
როგორც Telegram Mini App — ავტორიზაცია ხდება Telegram-ის `initData`-ს
ვალიდაციით (HMAC-SHA256 ბოტის ტოკენით, დამატებით ტოკენი არასდროს
ეგზავნება frontend-ს).

შენიშვნა: frontend-ის ფაილები (index.html/style.css/app.js) აქ
იტვირთება **repo-ს იმავე ძირი საქაღალდიდან**, სადაც bot.py/webserver.py
დევს — არა ცალკე "webapp/" ქვესაქაღალდედან — რომ GitHub-ის ვებ
ატვირთვისას (Add file → Upload files, ქვესაქაღალდეების გარეშე)
ავტომატურად, ხელით საქაღალდის შექმნის გარეშე იმუშაოს.

დოკუმენტაცია: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request, send_from_directory

import config
import sheets

log = logging.getLogger("safehome-crm-webapp")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)


def _send_telegram_message(chat_id, text: str) -> None:
    """პირდაპირი, სინქრონული HTTP მოთხოვნა Telegram-ის Bot API-სთან —
    Flask-ის (სინქრონული) მოთხოვნის დამმუშავებლიდან ბოტის (async)
    obj-ის გამოძახება პირდაპირ არ ხერხდება, ამიტომ აქ იგივეს ვაკეთებთ
    "ხელით", python-telegram-bot-ის გვერდის ავლით."""
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        log.exception("Telegram შეტყობინების გაგზავნა Mini App-იდან ვერ მოხერხდა")


# ---------------------------------------------------------------- auth

def _validate_init_data(init_data: str) -> dict | None:
    """ამოწმებს Telegram-ის Mini App `initData`-ს ხელმოწერას. წარმატების
    შემთხვევაში აბრუნებს {"user": {...}} dict-ს, წინააღმდეგ შემთხვევაში
    None-ს."""
    if not init_data or not config.TELEGRAM_BOT_TOKEN:
        return None
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(b"WebAppData", config.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        user = json.loads(data.get("user", "{}"))
        return {"user": user}
    except Exception:
        log.exception("initData ვალიდაცია ჩავარდა")
        return None


def _authed_agent():
    """მოთხოვნიდან ამოწმებს initData-ს და აბრუნებს
    (agent_or_None, is_admin, error_response_or_None)."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = _validate_init_data(init_data)
    if not parsed:
        return None, False, (jsonify(error="ავტორიზაცია ვერ დადასტურდა"), 401)
    chat_id = parsed["user"].get("id")
    if chat_id is None:
        return None, False, (jsonify(error="მომხმარებელი ვერ მოიძებნა"), 401)
    admin = chat_id in config.ADMIN_CHAT_IDS
    agent = sheets.find_agent_by_chat_id(chat_id)
    if not agent and not admin:
        return None, False, (jsonify(error="ჯერ დარეგისტრირდით ბოტში /start-ით"), 403)
    return agent, admin, None


# ---------------------------------------------------------------- API

def _is_team_lead(agent) -> bool:
    return bool(agent) and str(agent.get("role", "")).strip() == "team_lead"


_PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}


def _period_to_days(period: str | None) -> int:
    """Mini App-ის შედეგების/მონაცემების პერიოდის ფილტრი (დღე/კვირა/
    თვე) -> `days` პარამეტრი performance-გამოთვლებისთვის. უცნობი/ცარიელი
    მნიშვნელობისას ნაგულისხმევად თვე (30) რჩება — ძველი ქცევა უცვლელია."""
    return _PERIOD_DAYS.get((period or "").strip().lower(), 30)


@app.get("/api/me")
def api_me():
    agent, admin, err = _authed_agent()
    if err:
        return err
    return jsonify(
        is_admin=admin,
        is_team_lead=_is_team_lead(agent),
        agent=({
            "agent_id": agent.get("agent_id"),
            "name": agent.get("name"),
            "team": agent.get("team", ""),
            "active": agent.get("active", "yes"),
            "role": agent.get("role", "agent"),
        } if agent else None),
    )


@app.get("/api/dashboard")
def api_dashboard():
    """`?period=day|week|month` — შედეგების/რეიტინგის ფანჯარა (ნაგულის-
    ხმევად "month" = ძველი 30-დღიანი ქცევა, უცვლელი)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    days = _period_to_days(request.args.get("period"))
    team_lead = _is_team_lead(agent)
    payload = {"is_admin": admin or team_lead, "is_team_lead": team_lead, "period": request.args.get("period") or "month"}
    if admin or team_lead:
        try:
            team_filter = None if admin else agent.get("team", "")
            payload["admin"] = sheets.get_admin_dashboard(team=team_filter, days=days)
        except Exception:
            log.exception("admin dashboard ჩავარდა")
            return jsonify(error="მონაცემების ჩატვირთვა ვერ მოხერხდა"), 500
    if agent:
        try:
            payload["agent"] = sheets.get_agent_dashboard(agent["agent_id"], days=days)
        except Exception:
            log.exception("agent dashboard ჩავარდა")
            return jsonify(error="მონაცემების ჩატვირთვა ვერ მოხერხდა"), 500
    return jsonify(payload)


@app.get("/api/exclusives")
def api_exclusives():
    agent, admin, err = _authed_agent()
    if err:
        return err
    rows = sheets.get_exclusives(status="active")
    for r in rows:
        try:
            r["collaboration_count"] = len(sheets.get_exclusive_shares(exclusive_id=r.get("exclusive_id")))
        except Exception:
            r["collaboration_count"] = 0
    return jsonify(rows=rows[::-1])


@app.get("/api/colleagues")
def api_colleagues():
    """კოლეგების სია (გაზიარების მისამართებისთვის) — საკუთარი თავის
    გარეშე, მხოლოდ აქტიური აგენტები."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    rows = [
        {"agent_id": a.get("agent_id"), "name": a.get("name"), "team": a.get("team", "")}
        for a in sheets.get_agents()
        if str(a.get("agent_id")) != str(agent.get("agent_id"))
        and str(a.get("active", "yes")).strip().lower() not in ("no", "false", "0")
    ]
    rows.sort(key=lambda r: r.get("name") or "")
    return jsonify(rows=rows)


@app.post("/api/exclusives/share")
def api_exclusives_share():
    """ექსკლუზივის გაზიარება კოლეგასთან — თანამშრომლობის კვალის
    ჩაწერით (v3.10): თუ კლიენტი დაინტერესდა კოლეგის ბინით, აგენტს
    შეუძლია პირდაპირ Mini App-იდან გაუზიაროს და ეს აისახოს ორივეს
    დაშბორდზე და მენეჯერთანაც."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    body = request.get_json(silent=True) or {}
    exclusive_id = body.get("exclusive_id")
    to_agent_id = body.get("to_agent_id")
    note = (body.get("note") or "").strip()
    if not exclusive_id or not to_agent_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    if str(to_agent_id) == str(agent.get("agent_id")):
        return jsonify(error="საკუთარ თავზე გაზიარება არ შეიძლება"), 400
    result = sheets.share_exclusive(exclusive_id, agent["agent_id"], to_agent_id, note)
    if not result:
        return jsonify(error="ეს ექსკლუზივი ვერ მოიძებნა"), 404

    to_agent = next(
        (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(to_agent_id)), None
    )
    exclusive = result.get("exclusive", {})
    loc = exclusive.get("location") or exclusive.get("property_type") or ""
    notify_text = (
        f"🤝 {agent.get('name')}-მ გაგიზიარათ ექსკლუზივი ({loc}) — "
        f"კლიენტი დაინტერესებულია."
    )
    if note:
        notify_text += f"\nშენიშვნა: {note}"
    if to_agent and to_agent.get("telegram_chat_id"):
        _send_telegram_message(int(to_agent["telegram_chat_id"]), notify_text)
    for admin_id in config.ADMIN_CHAT_IDS:
        _send_telegram_message(
            admin_id,
            f"🤝 თანამშრომლობა: {agent.get('name')} ↔ {to_agent.get('name') if to_agent else to_agent_id} "
            f"ბინაზე ({loc}).",
        )
    return jsonify(ok=True, share=result)


@app.post("/api/reports/rate")
def api_reports_rate():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    report_id = body.get("report_id")
    try:
        score = int(body.get("score"))
    except (TypeError, ValueError):
        return jsonify(error="არასწორი შეფასება"), 400
    if not report_id or not (1 <= score <= 5):
        return jsonify(error="არასწორი მოთხოვნა"), 400
    rated_by = "admin" if admin else (agent.get("name") if agent else "")
    ok = sheets.set_report_quality(report_id, score, rated_by)
    if not ok:
        return jsonify(error="ვერ მოიძებნა"), 404
    return jsonify(ok=True)


@app.get("/api/reports")
def api_reports():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    rows = sheets.get_reports()
    if not admin and agent:
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == str(agent.get("team", "")).strip()
        }
        rows = [r for r in rows if str(r.get("agent_id")) in team_ids]
    rows = sorted(rows, key=lambda r: str(r.get("created_at", "")), reverse=True)[:30]
    return jsonify(rows=rows)


@app.get("/api/swaps")
def api_swaps():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    rows = sheets.get_shift_swaps(status="pending_manager")
    if not admin and agent:
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == str(agent.get("team", "")).strip()
        }
        rows = [r for r in rows if str(r.get("agent_id")) in team_ids or str(r.get("target_agent_id")) in team_ids]
    return jsonify(rows=rows)


@app.post("/api/swaps/decide")
def api_swaps_decide():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    swap_id = body.get("swap_id")
    status = body.get("status")
    if status not in ("approved", "rejected") or not swap_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    decided_by = "admin" if admin else (agent.get("name") if agent else "")
    row = sheets.decide_shift_swap(swap_id, status, decided_by=decided_by)
    if not row:
        return jsonify(error="ვერ მოიძებნა"), 404

    label = "✅ დამტკიცებულია" if status == "approved" else "❌ უარყოფილია"
    for aid_key in ("agent_id", "target_agent_id"):
        aid = row.get(aid_key)
        if not aid:
            continue
        a = next((x for x in sheets.get_agents() if str(x.get("agent_id")) == str(aid)), None)
        if a and a.get("telegram_chat_id"):
            _send_telegram_message(
                int(a["telegram_chat_id"]),
                f"სმენის გაცვლის მოთხოვნა ({row.get('swap_date')}) — {label}",
            )
    return jsonify(ok=True, row=row)


@app.get("/api/agents")
def api_agents():
    """აგენტების/მენეჯერების მართვის ცხრილი (მხოლოდ ადმინისთვის —
    "დირექტორის" დონის მოქმედება, არა თიმლიდერისთვის). თითოეულ აგენტთან
    აბრუნებს მის მიმდინარე "მენეჯერს" (თუ არის), და `managers` — ყველა
    არსებული თიმლიდერის სია, ახალი დანიშვნის dropdown-ისთვის."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403

    all_agents = sheets.get_agents()
    leads_by_team = {}
    for a in all_agents:
        if str(a.get("role", "")).strip() == "team_lead":
            key = str(a.get("team", "")).strip()
            if key:
                leads_by_team[key] = a

    rows = []
    for a in all_agents:
        team_val = str(a.get("team", "")).strip()
        is_lead = str(a.get("role", "")).strip() == "team_lead"
        manager = None
        if not is_lead and team_val and team_val in leads_by_team:
            lead = leads_by_team[team_val]
            manager = {"agent_id": lead.get("agent_id"), "name": lead.get("name")}
        rows.append({
            "agent_id": a.get("agent_id"),
            "name": a.get("name"),
            "phone": a.get("phone"),
            "active": a.get("active", "yes"),
            "role": a.get("role", "agent"),
            "team": team_val,
            "registered": bool(a.get("telegram_chat_id")),
            "manager": manager,
        })
    rows.sort(key=lambda r: r.get("name") or "")
    managers_out = [
        {"agent_id": a.get("agent_id"), "name": a.get("name"), "team": str(a.get("team", "")).strip()}
        for a in all_agents if str(a.get("role", "")).strip() == "team_lead"
    ]
    return jsonify(rows=rows, managers=managers_out)


@app.post("/api/agents/assign")
def api_agents_assign():
    """აგენტის დანიშვნა: დამოუკიდებელი / თიმლიდერი (საკუთარი გუნდი) /
    კონკრეტული თიმლიდერის გუნდის წევრი — "პირამიდის" სტრუქტურის
    აწყობა Mini App-იდანვე, ცხრილის ხელით რედაქტირების ან agent_id-ის
    ზეპირად აკრეფის გარეშე. მხოლოდ ადმინისთვის."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    mode = body.get("mode")
    if not agent_id or mode not in ("independent", "lead", "member"):
        return jsonify(error="არასწორი მოთხოვნა"), 400

    all_agents = sheets.get_agents()
    target = next((a for a in all_agents if str(a.get("agent_id")) == str(agent_id)), None)
    if not target:
        return jsonify(error="აგენტი ვერ მოიძებნა"), 404

    if mode == "independent":
        sheets.set_agent_role(agent_id, "agent")
        sheets.set_agent_team(agent_id, "")
        return jsonify(ok=True)

    if mode == "lead":
        sheets.set_agent_role(agent_id, "team_lead")
        if not str(target.get("team", "")).strip():
            sheets.set_agent_team(agent_id, target.get("name") or agent_id)
        return jsonify(ok=True)

    # mode == "member" — კონკრეტული თიმლიდერის გუნდში ჩართვა
    manager_id = body.get("manager_id")
    manager = next((a for a in all_agents if str(a.get("agent_id")) == str(manager_id)), None)
    if not manager or str(manager.get("role", "")).strip() != "team_lead":
        return jsonify(error="მენეჯერი ვერ მოიძებნა"), 400
    if str(agent_id) == str(manager_id):
        return jsonify(error="საკუთარ თავზე ვერ დანიშნავთ"), 400

    team_key = str(manager.get("team", "")).strip()
    if not team_key:
        team_key = manager.get("name") or manager_id
        sheets.set_agent_team(manager_id, team_key)

    is_new_member = str(target.get("team", "")).strip() != team_key or str(target.get("role", "")).strip() == "team_lead"
    sheets.set_agent_role(agent_id, "agent")
    sheets.set_agent_team(agent_id, team_key)

    if is_new_member and manager.get("telegram_chat_id"):
        _send_telegram_message(
            int(manager["telegram_chat_id"]),
            f"👥 თქვენს გუნდს დაემატა ახალი წევრი: {target.get('name')}",
        )
    if target.get("telegram_chat_id"):
        _send_telegram_message(
            int(target["telegram_chat_id"]),
            f"ℹ️ თქვენი მენეჯერია: {manager.get('name')}",
        )
    return jsonify(ok=True)


@app.post("/api/agents/active")
def api_agents_active():
    """აგენტის გააქტიურება/გამორთვა Mini App-იდან (იგივე, რაც ბოტის
    /reactivate-ს შეეძლო — ახლა ცხრილიდანვე, agent_id-ის ძებნის
    გარეშე). მხოლოდ ადმინისთვის."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    active = body.get("active")
    if not agent_id or active not in ("yes", "no"):
        return jsonify(error="არასწორი მოთხოვნა"), 400
    ok = sheets.set_agent_active(agent_id, active)
    if not ok:
        return jsonify(error="აგენტი ვერ მოიძებნა"), 404
    return jsonify(ok=True)


@app.get("/api/tasks")
def api_tasks():
    """ღია დავალებების/კლიენტების სია გადაბარებისთვის — ადმინს ყველა
    ეჩვენება, თიმლიდერს მხოლოდ საკუთარი გუნდის აგენტებზე მინიჭებული
    (კურატორის პრინციპი). აბრუნებს ასევე `agents` — აქტიური აგენტების
    სიას, ვისზეც დასაშვებია გადაბარება (frontend-ის dropdown-ისთვის)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403

    all_agents = sheets.get_agents()
    active_agents = [a for a in all_agents if str(a.get("active", "yes")).strip().lower() != "no"]

    if admin:
        eligible = active_agents
        team_ids = None
    else:
        my_team = str(agent.get("team", "")).strip()
        eligible = [a for a in active_agents if str(a.get("team", "")).strip() == my_team]
        team_ids = {str(a.get("agent_id")) for a in eligible}

    rows = [t for t in sheets.get_tasks() if str(t.get("status")) != "Done"]
    if team_ids is not None:
        rows = [t for t in rows if str(t.get("assigned_to")) in team_ids]
    rows.sort(key=lambda t: str(t.get("created_at", "")), reverse=True)

    agents_out = sorted(
        [{"agent_id": a.get("agent_id"), "name": a.get("name"), "team": a.get("team", "")} for a in eligible],
        key=lambda r: r.get("name") or "",
    )
    return jsonify(rows=rows[:100], agents=agents_out)


@app.post("/api/tasks/reassign")
def api_tasks_reassign():
    """დავალების/კლიენტის სხვა აგენტზე გადაბარება — ადმინისთვის
    ნებისმიერ აქტიურ აგენტზე, თიმლიდერისთვის მხოლოდ საკუთარ გუნდში
    (კურატორის პრინციპი — ადმინის იგივე ფუნქცია, ახლა თიმლიდერსაც
    აქვს)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    task_id = body.get("task_id")
    to_agent_id = body.get("to_agent_id")
    if not task_id or not to_agent_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400

    to_agent = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(to_agent_id)), None)
    if not to_agent or str(to_agent.get("active", "yes")).strip().lower() == "no":
        return jsonify(error="ეს აგენტი აღარაა აქტიური"), 400
    if not admin:
        my_team = str(agent.get("team", "")).strip()
        if str(to_agent.get("team", "")).strip() != my_team or not my_team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტზე შეგიძლიათ გადაბარება"), 403

    actor = "admin" if admin else str(agent.get("agent_id") or "")
    row = sheets.reassign_task(task_id, to_agent_id, actor_agent_id=actor)
    if not row:
        return jsonify(error="დავალება ვერ მოიძებნა"), 404

    if to_agent.get("telegram_chat_id"):
        _send_telegram_message(
            int(to_agent["telegram_chat_id"]),
            f"📋 გადმოგეცით დავალება: {row.get('title')}"
            + (f"\nკლიენტი: {row.get('client_phone')}" if row.get("client_phone") else ""),
        )
        # უკვე გავაგზავნეთ საკუთარი (უფრო ინფორმატიული) შეტყობინება
        # პირდაპირ აქედან — ვნიშნავთ, რომ არ გავაორმაგოთ ფონური
        # check_new_tasks job-ის ზოგადი შეტყობინებით.
        try:
            sheets.mark_task_notified(task_id)
        except Exception:
            log.exception("mark_task_notified ჩავარდა reassign-ის შემდეგ")
    return jsonify(ok=True, row=row)


@app.post("/api/clockin")
def api_clockin():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    if str(agent.get("active", "yes")).lower() == "no":
        return jsonify(error="თქვენი ანგარიში გამორთულია"), 403
    result = sheets.clock_in(agent["agent_id"])
    return jsonify(result=result)


@app.post("/api/clockout")
def api_clockout():
    """ოფისის ცვლაზე body-ში მოდის {site, myhome, ssge} (თითოეული
    ცალკე რიცხვი — ჯამი ავტომატურად ითვლება), ონლაინზე კი უბრალოდ
    {count}. თუ ჯამი დღიურ გეგმაზე ნაკლებია — ავტომატურად ემატება
    "quota_missed" გაფრთხილება, ისევე როგორც ბოტის /clockout-ში."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    body = request.get_json(silent=True) or {}
    agent_id = agent["agent_id"]
    result = sheets.clock_out(agent_id)
    if result == "ok":
        mode = sheets.get_today_mode(agent_id)

        def _as_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        if mode in ("office_morning", "office_evening"):
            site, myhome, ssge = _as_int(body.get("site")), _as_int(body.get("myhome")), _as_int(body.get("ssge"))
            total = site + myhome + ssge
            sheets.set_daily_count(agent_id, total, site=site, myhome=myhome, ssge=ssge)
        else:
            total = _as_int(body.get("count"))
            sheets.set_daily_count(agent_id, total)

        quota = sheets.quota_for_mode(mode)
        if quota and total < quota:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            detail = f"{today}: {total}/{quota} (Mini App-იდან)"
            warn_result = sheets.add_warning(agent_id, "quota_missed", detail)
            label = "დღიური გეგმა (განცხადებები) ვერ შესრულდა"
            text_admin = (
                f"⚠️ გაფრთხილება — {agent['name']}: {label}\n{detail}\n"
                f"ბოლო {config.WARNING_WINDOW_DAYS} დღეში: "
                f"{warn_result['count']}/{config.WARNING_LIMIT}"
            )
            if warn_result["deactivated"]:
                text_admin += (
                    f"\n\n🚫 აგენტი ავტომატურად გამოირთო (მიაღწია "
                    f"{config.WARNING_LIMIT} გაფრთხილებას)."
                )
            for admin_id in config.ADMIN_CHAT_IDS:
                _send_telegram_message(admin_id, text_admin)
            if agent.get("telegram_chat_id"):
                agent_text = f"⚠️ მიიღეთ გაფრთხილება: {label}."
                if warn_result["deactivated"]:
                    agent_text += (
                        "\n\nსამწუხაროდ, გაფრთხილებების ლიმიტს მიაღწიეთ და თქვენი "
                        "ანგარიში დროებით გამოირთო. დაუკავშირდით მენეჯერს."
                    )
                _send_telegram_message(int(agent["telegram_chat_id"]), agent_text)
    return jsonify(result=result)


@app.get("/api/questions")
def api_questions():
    """აგენტს — მხოლოდ საკუთარი კითხვები (სრული დიალოგი); ადმინს/
    თიმლიდერს — ღია კითხვები პირველ რიგში + ბოლო პასუხგაცემულებიც
    (თიმლიდერს — მხოლოდ საკუთარი გუნდისა)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if admin or _is_team_lead(agent):
        team = None if admin else agent.get("team", "")
        rows = sheets.get_questions(team=team)
        rows = sorted(
            rows,
            key=lambda r: (r.get("status") != "open", str(r.get("created_at", ""))),
            reverse=False,
        )
        open_rows = [r for r in rows if r.get("status") == "open"]
        answered_rows = [r for r in rows if r.get("status") != "open"]
        answered_rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        rows = open_rows + answered_rows[:20]
        return jsonify(rows=rows)
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    rows = sheets.get_questions(agent_id=agent["agent_id"])
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return jsonify(rows=rows)


@app.post("/api/questions")
def api_questions_ask():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify(error="დაწერეთ კითხვის ტექსტი"), 400
    question_id = sheets.create_question(agent["agent_id"], text)

    notify_text = f"❓ ახალი კითხვა — {agent.get('name')}:\n{text}"
    team = str(agent.get("team", "")).strip()
    notified_ids = set()
    for admin_id in config.ADMIN_CHAT_IDS:
        _send_telegram_message(admin_id, notify_text)
        notified_ids.add(admin_id)
    if team:
        for a in sheets.get_agents():
            if str(a.get("role", "")).strip() != "team_lead":
                continue
            if str(a.get("team", "")).strip() != team:
                continue
            chat_id = a.get("telegram_chat_id")
            if chat_id and int(chat_id) not in notified_ids:
                _send_telegram_message(int(chat_id), notify_text)
                notified_ids.add(int(chat_id))
    return jsonify(ok=True, question_id=question_id)


@app.post("/api/questions/answer")
def api_questions_answer():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    question_id = body.get("question_id")
    answer = (body.get("answer") or "").strip()
    if not question_id or not answer:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    answered_by = "მენეჯერი" if admin else (agent.get("name") if agent else "თიმლიდერი")
    row = sheets.answer_question(question_id, answer, answered_by)
    if not row:
        return jsonify(error="ვერ მოიძებნა"), 404

    asking_agent = next(
        (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("agent_id"))), None
    )
    if asking_agent and asking_agent.get("telegram_chat_id"):
        _send_telegram_message(
            int(asking_agent["telegram_chat_id"]),
            f"💬 პასუხი თქვენს კითხვაზე „{row.get('text')}“:\n{answer}",
        )
    return jsonify(ok=True, row=row)


@app.post("/api/dayoff/decide")
def api_dayoff_decide():
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    request_id = body.get("request_id")
    status = body.get("status")
    if status not in ("approved", "rejected") or not request_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    row = sheets.decide_dayoff(request_id, status)
    if not row:
        return jsonify(error="ვერ მოიძებნა"), 404

    label = "✅ დამტკიცებულია" if status == "approved" else "❌ უარყოფილია"
    agent = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("agent_id"))), None)
    if agent and agent.get("telegram_chat_id"):
        _send_telegram_message(
            int(agent["telegram_chat_id"]),
            f"თქვენი Day off მოთხოვნა ({row.get('date')}) — {label}",
        )
    return jsonify(ok=True, row=row)


# ---------------------------------------------------------- static app
# (index.html/style.css/app.js — repo-ს ძირიდან, არა ცალკე ქვესაქაღალდიდან)

@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/style.css")
def style_css():
    return send_from_directory(BASE_DIR, "style.css")


@app.get("/app.js")
def app_js():
    return send_from_directory(BASE_DIR, "app.js")


def run():
    """ბლოკავს — bot.py იძახებს ცალკე thread-ში."""
    log.info("Mini App ვებ-სერვერი ეშვება პორტზე %s", config.PORT)
    app.run(host="0.0.0.0", port=config.PORT, threaded=True, use_reloader=False)
