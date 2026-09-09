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
    agent, admin, err = _authed_agent()
    if err:
        return err
    team_lead = _is_team_lead(agent)
    payload = {"is_admin": admin or team_lead, "is_team_lead": team_lead}
    if admin or team_lead:
        try:
            team_filter = None if admin else agent.get("team", "")
            payload["admin"] = sheets.get_admin_dashboard(team=team_filter)
        except Exception:
            log.exception("admin dashboard ჩავარდა")
            return jsonify(error="მონაცემების ჩატვირთვა ვერ მოხერხდა"), 500
    if agent:
        try:
            payload["agent"] = sheets.get_agent_dashboard(agent["agent_id"])
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
    return jsonify(rows=rows[::-1])


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
