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

@app.get("/api/me")
def api_me():
    agent, admin, err = _authed_agent()
    if err:
        return err
    return jsonify(
        is_admin=admin,
        agent=({
            "agent_id": agent.get("agent_id"),
            "name": agent.get("name"),
            "team": agent.get("team", ""),
            "active": agent.get("active", "yes"),
        } if agent else None),
    )


@app.get("/api/dashboard")
def api_dashboard():
    agent, admin, err = _authed_agent()
    if err:
        return err
    payload = {"is_admin": admin}
    if admin:
        try:
            payload["admin"] = sheets.get_admin_dashboard()
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
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    body = request.get_json(silent=True) or {}
    result = sheets.clock_out(agent["agent_id"])
    if result == "ok":
        count = body.get("count")
        if count is not None:
            try:
                sheets.set_daily_count(agent["agent_id"], int(count))
            except (TypeError, ValueError):
                pass
    return jsonify(result=result)


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
