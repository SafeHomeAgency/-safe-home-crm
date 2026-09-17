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
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads", "reports")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = Flask(__name__)


def _save_base64_photos(photos) -> list[str]:
    """Mini App-იდან მოსული base64 ფოტოების (data URI) დისკზე
    შენახვა — აბრუნებს შენახული ფაილების ფარდობით გზებს (`file_id`
    ველში ჩასაწერად, სხვა Telegram file_id-ების იგივე ფორმატით,
    მძიმით გამოყოფილი). დაცვა: მაქსიმუმ 5 ფოტო თითო ანგარიშზე, თითო
    ფოტო მაქს. 8MB. შენიშვნა: Railway-ის დისკი ჩვეულებრივ ეფემერულია —
    ხელახალ deploy-ზე შესაძლოა წაიშალოს, თუ Volume არაა მიმაგრებული."""
    import base64
    import uuid as _uuid
    saved = []
    for p in (photos or [])[:5]:
        try:
            if not isinstance(p, str) or "," not in p:
                continue
            header, b64data = p.split(",", 1)
            ext = "jpg"
            if "png" in header:
                ext = "png"
            elif "webp" in header:
                ext = "webp"
            raw = base64.b64decode(b64data)
            if len(raw) > 8 * 1024 * 1024:
                continue
            fname = f"{_uuid.uuid4().hex}.{ext}"
            with open(os.path.join(UPLOADS_DIR, fname), "wb") as f:
                f.write(raw)
            saved.append(f"uploads/reports/{fname}")
        except Exception:
            log.exception("ფოტოს შენახვა ვერ მოხერხდა")
    return saved


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


WARNING_TYPE_LABELS = {
    "late_report": "დაგვიანებული/გამოტოვებული ანგარიში",
    "late_arrival": "დაგვიანება სამუშაოზე",
    "no_show": "არ გამოცხადება",
    "quota_missed": "დღიური გეგმა ვერ შესრულდა",
}


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


@app.get("/api/regulations")
def api_regulations():
    """ინსტრუქცია/წესები ტაბისთვის — ცოცხალი, კონფიგურირებადი ლიმიტები
    (და არა ტექსტში ხელით ჩაწერილი რიცხვები), რომ თუ admin მომავალში
    environment-ცვლადს შეცვლის, Mini App-ის ინსტრუქციაც ავტომატურად
    განახლდეს."""
    _, _, err = _authed_agent()
    if err:
        return err
    return jsonify(limits={
        "online_daily_quota": config.ONLINE_DAILY_QUOTA,
        "office_daily_quota": config.OFFICE_DAILY_QUOTA,
        "dayoff_monthly_limit": config.DAYOFF_MONTHLY_LIMIT,
        "shift_swap_monthly_limit": config.SHIFT_SWAP_MONTHLY_LIMIT,
        "warning_limit": config.WARNING_LIMIT,
        "warning_window_days": config.WARNING_WINDOW_DAYS,
        "report_deadline_hour": config.REPORT_DEADLINE_HOUR,
        "attendance_grace_minutes": config.ATTENDANCE_GRACE_MINUTES,
    })


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
    """რეპორტების ისტორია დღე/კვირა/თვე ფილტრით (?period=), ან
    კონკრეტული თარიღით (?date=YYYY-MM-DD, უპირატესობა აქვს period-ზე) —
    პლიუს (ადმინისთვის) ?team= -> ?agent_id= დრილდაუნი, task-history-ის
    იგივე პრინციპით."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403

    team = request.args.get("team") or (None if admin else str(agent.get("team", "")).strip())
    agent_id = request.args.get("agent_id") or None
    date_filter = (request.args.get("date") or "").strip()

    if agent_id and not admin:
        target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(agent_id)), None)
        if not target or str(target.get("team", "")).strip() != team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტის რეპორტი"), 403

    rows = sheets.get_reports()
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    elif team:
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == team
        }
        rows = [r for r in rows if str(r.get("agent_id")) in team_ids]

    if date_filter:
        rows = [r for r in rows if str(r.get("created_at", "")).strip()[:10] == date_filter]
    else:
        days = _period_to_days(request.args.get("period"))
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)

        def _within(r):
            try:
                dt = datetime.datetime.fromisoformat(str(r.get("created_at", "")).strip())
            except Exception:
                return True
            return dt >= cutoff

        rows = [r for r in rows if _within(r)]

    rows = sorted(rows, key=lambda r: str(r.get("created_at", "")), reverse=True)
    teams = sheets.get_team_directory() if admin else []
    agents_out = sorted(
        [
            {"agent_id": a.get("agent_id"), "name": a.get("name")}
            for a in sheets.get_agents()
            if (team is None or str(a.get("team", "")).strip() == team)
        ],
        key=lambda r: r.get("name") or "",
    )
    return jsonify(rows=rows[:200], count=len(rows), teams=teams, agents=agents_out, team=team or "")


@app.get("/api/swaps")
def api_swaps():
    """მენეჯერისთვის დასადასტურებელი (`pending`) + სრული ისტორია
    (`history` — მოლოდინში კოლეგის პასუხის, დამტკიცებული, უარყოფილი),
    რომ ყოველთვის ჩანდეს ვინ მოითხოვა, ვისთან გაცვალა და კონკრეტულად
    რომელი სმენა/თარიღი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    rows = sheets.get_shift_swaps()
    if not admin and agent:
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == str(agent.get("team", "")).strip()
        }
        rows = [r for r in rows if str(r.get("agent_id")) in team_ids or str(r.get("target_agent_id")) in team_ids]
    pending = [r for r in rows if r.get("status") == "pending_manager"]
    history = [r for r in rows if r.get("status") != "pending_manager"]
    history.sort(key=lambda r: str(r.get("decided_at") or r.get("created_at", "")), reverse=True)
    return jsonify(pending=pending, history=history)


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


def _active_warning_count(agent_id: str) -> int:
    return len([
        w for w in sheets.get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS)
        if str(w.get("status") or "active") != "dismissed"
    ])


@app.get("/api/warnings")
def api_warnings():
    """გაფრთხილებების სრული სია (არა მხოლოდ ბოლო 10, დაშბორდის
    ხედვისგან განსხვავებით) — დეტალურ ჩაშლას/გაუქმების მოთხოვნას
    რომ დაექვემდებაროს. ადმინს ყველა ჩანს, თიმლიდერს — საკუთარი
    გუნდის."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    rows = sheets.get_warnings()
    if not admin:
        my_team = str(agent.get("team", "")).strip()
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == my_team
        }
        rows = [r for r in rows if str(r.get("agent_id")) in team_ids]
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return jsonify(rows=rows[:300])


@app.post("/api/warnings/request-dismiss")
def api_warnings_request_dismiss():
    """მენეჯერი ითხოვს კონკრეტული გაფრთხილების გაუქმებას — მაგ. თუ
    გაფრთხილება (ხშირად "quota_missed"/"late_report") იმიტომ დაეწერა,
    რომ აგენტი ამ დროს შეხვედრაზე იყო. მოთხოვნა თავად არაფერს
    აუქმებს, მხოლოდ დირექტორის დამტკიცებამდე ითვლება "pending"-ად."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    warning_id = body.get("warning_id")
    reason = (body.get("reason") or "").strip()
    if not warning_id or not reason:
        return jsonify(error="მიზეზის მითითება სავალდებულოა"), 400

    target = next((w for w in sheets.get_warnings() if str(w.get("warning_id")) == str(warning_id)), None)
    if not target:
        return jsonify(error="ვერ მოიძებნა"), 404
    if not admin:
        my_team = str(agent.get("team", "")).strip()
        target_agent = next(
            (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(target.get("agent_id"))), None,
        )
        if not target_agent or str(target_agent.get("team", "")).strip() != my_team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის გაფრთხილებაზე შეგიძლიათ მოთხოვნა"), 403

    requested_by = "admin" if admin else agent.get("agent_id")
    row = sheets.request_warning_dismissal(warning_id, requested_by, reason)
    if not row:
        return jsonify(error="ეს გაფრთხილება უკვე მოთხოვნილი/გაუქმებულია"), 400

    # ხაზგასმა: ბოტმა "სმენის დამთხვევის" კონტექსტი დირექტორის
    # თვალწინ რომ დადოს — თუ ამ თარიღზე ამ აგენტს შეხვედრა
    # ჩაწერილი ჰქონდა, ეს ინფორმაცია ერთვის შეტყობინებას.
    meeting_hint = ""
    warn_date = str(target.get("created_at", "")).split(" ")[0]
    if warn_date:
        same_day_meetings = [
            m for m in sheets.get_meetings(agent_id=target.get("agent_id"))
            if str(m.get("meeting_date", "")).strip() == warn_date
            or str(m.get("timestamp", "")).startswith(warn_date)
        ]
        if same_day_meetings:
            meeting_hint = f"\n📅 ამ დღეს ({warn_date}) ჩაწერილია {len(same_day_meetings)} შეხვედრა ამ აგენტთან."

    requester_name = "ადმინი" if admin else agent.get("name")
    text = (
        f"📝 გაფრთხილების გაუქმების მოთხოვნა — {requester_name}\n"
        f"აგენტი: {row.get('agent_name')}\n"
        f"გაფრთხილება: {WARNING_TYPE_LABELS.get(row.get('type'), row.get('type'))} ({warn_date})\n"
        f"მიზეზი: {reason}"
        f"{meeting_hint}"
    )
    for admin_id in config.ADMIN_CHAT_IDS:
        _send_telegram_message(admin_id, text)
    return jsonify(ok=True, row=row)


@app.post("/api/warnings/decide-dismiss")
def api_warnings_decide_dismiss():
    """დირექტორის საბოლოო გადაწყვეტილება — დამტკიცებისას აგენტისა და
    მომთხოვნი მენეჯერისთვის ეცნობება ახალი (განახლებული)
    გაფრთხილებების რაოდენობა, რომ არსად არაფერი არ აირიოს."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    warning_id = body.get("warning_id")
    approve = bool(body.get("approve"))
    if not warning_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    row = sheets.decide_warning_dismissal(warning_id, approve, decided_by="admin")
    if not row:
        return jsonify(error="ვერ მოიძებნა ან უკვე გადაწყვეტილია"), 404

    agent_id = str(row.get("agent_id"))
    new_count = _active_warning_count(agent_id)
    label = "✅ გაუქმდა" if approve else "❌ უარყოფილია, ძალაშია"
    agents_by_id = {str(a.get("agent_id")): a for a in sheets.get_agents()}

    target_agent = agents_by_id.get(agent_id)
    if target_agent and target_agent.get("telegram_chat_id"):
        _send_telegram_message(
            int(target_agent["telegram_chat_id"]),
            f"თქვენი გაფრთხილება ({WARNING_TYPE_LABELS.get(row.get('type'), row.get('type'))}) — {label}.\n"
            f"მიმდინარე გაფრთხილებების რაოდენობა: {new_count}/{config.WARNING_LIMIT}.",
        )

    requester = agents_by_id.get(str(row.get("dismiss_requested_by")))
    if requester and requester.get("telegram_chat_id"):
        _send_telegram_message(
            int(requester["telegram_chat_id"]),
            f"თქვენი მოთხოვნა ({row.get('agent_name')}-ის გაფრთხილების გაუქმებაზე) — {label}.\n"
            f"{row.get('agent_name')}-ის მიმდინარე გაფრთხილებების რაოდენობა: {new_count}/{config.WARNING_LIMIT}.",
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
    # თუ ორ სხვადასხვა თიმლიდერს ერთი და იგივე გუნდის კოდი ერგო (ძველი
    # მონაცემებიდან ან ხელით /setteam-ით) — ცხადად ვაფრთხილებთ ადმინს,
    # რომ არ მოხდეს გუნდების ჩუმად არევა.
    duplicate_teams = sheets.find_duplicate_team_keys()
    return jsonify(rows=rows, managers=managers_out, duplicate_teams=duplicate_teams)


@app.post("/api/agents/rekey_team")
def api_agents_rekey_team():
    """კონკრეტული თიმლიდერის გუნდის კოდის განახლება მისივე agent_id-ზე
    (გარანტირებულად უნიკალური) — გამოსასწორებლად, თუ ორ თიმლიდერს
    ერთი და იგივე გუნდის კოდი ერგო შემთხვევით. მხოლოდ თვითონ
    თიმლიდერის საკუთარ ჩანაწერს ცვლის — მისი გუნდის წევრები არ
    იცვლება ავტომატურად (ისინი admin-მა ხელახლა უნდა შეარჩიოს
    "აგენტების მართვა" ტაბიდან, რომ სწორად მიებას ახალ კოდს)."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    if not agent_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(agent_id)), None)
    if not target or str(target.get("role", "")).strip() != "team_lead":
        return jsonify(error="მხოლოდ თიმლიდერისთვის"), 400
    sheets.set_agent_team(agent_id, agent_id)
    return jsonify(ok=True)


@app.post("/api/agents/delete")
def api_agents_delete():
    """აგენტის ჩანაწერის სრული, შეუქცევადი წაშლა — "აგენტების მართვა"
    ტაბიდან, დეაქტივაციისგან განსხვავებით საერთოდ აღარსად ჩანს.
    ისტორიული მონაცემები (დავალებები/რეპორტები/შეხვედრები/
    გაფრთხილებები) უცვლელად რჩება — მათში სახელი ცალკეა შენახული."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    if not agent_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    ok = sheets.delete_agent(agent_id)
    if not ok:
        return jsonify(error="ვერ მოიძებნა"), 404
    return jsonify(ok=True)


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
        was_already_lead = str(target.get("role", "")).strip() == "team_lead"
        sheets.set_agent_role(agent_id, "team_lead")
        # მნიშვნელოვანი: ახლად დანიშნულ თიმლიდერს ყოველთვის ეძლევა
        # ახალი, გარანტირებულად უნიკალური გუნდის კოდი (თავისივე
        # agent_id) — და არა მხოლოდ მაშინ, როცა `team` ველი ცარიელია.
        # თუ ეს პირი ადრე სხვის გუნდში იყო წევრი, მისი ძველი `team`
        # მნიშვნელობა კვლავ იმ ყოფილი მენეჯერისას ემთხვევა და, თუ
        # უცვლელი დარჩება, ორივე ("ძველი" და "ახალი" თიმლიდერი) ერთსა
        # და იმავე გუნდის კოდს გაინაწილებენ — რაც სწორედ არასწორი
        # მენეჯერის ჩვენების მიზეზი იყო. უკვე არსებულ თიმლიდერს კი (თუ
        # ეს ღილაკი უბრალოდ ხელახლა დაეჭირა) მისი უკვე სწორი გუნდის
        # კოდი უცვლელი რჩება.
        if not was_already_lead:
            sheets.set_agent_team(agent_id, agent_id)
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


# --------------------------------------------------- agent add/remove
# მოთხოვნები (მენეჯერი ითხოვს, ადმინი ამტკიცებს/უარყოფს)

@app.post("/api/agent-requests")
def api_agent_requests_create():
    """მენეჯერის (თიმლიდერის) მოთხოვნა ახალი აგენტის დამატებაზე ან
    არსებულის გათავისუფლებაზე — მხოლოდ "pending" ჩანაწერი იქმნება,
    რეალურად არაფერი იცვლება ადმინის დამტკიცებამდე (იხ.
    /api/agent-requests/decide)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in ("add", "remove"):
        return jsonify(error="არასწორი მოთხოვნა"), 400

    team = (body.get("team") or "").strip() if admin else str(agent.get("team", "")).strip()
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()
    target_agent_id = body.get("target_agent_id") or ""
    reason = (body.get("reason") or "").strip()
    target = None

    if kind == "add" and not name:
        return jsonify(error="შეიყვანეთ აგენტის სახელი"), 400
    if kind == "remove":
        if not target_agent_id:
            return jsonify(error="აირჩიეთ აგენტი"), 400
        target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(target_agent_id)), None)
        if not target:
            return jsonify(error="აგენტი ვერ მოიძებნა"), 404
        if not admin and str(target.get("team", "")).strip() != team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტზე"), 403

    requested_by = agent.get("agent_id") if agent else ""
    request_id = sheets.create_agent_request(
        kind, requested_by, team=team, name=name, phone=phone,
        target_agent_id=target_agent_id, reason=reason,
    )

    label = "➕ ახალი აგენტის მოთხოვნა" if kind == "add" else "➖ აგენტის გათავისუფლების მოთხოვნა"
    who = agent.get("name") if agent else "ადმინი"
    detail = name or (target.get("name") if kind == "remove" and target else "")
    notify_text = f"📋 {label}\nმენეჯერი: {who}\n{detail}"
    if reason:
        notify_text += f"\nმიზეზი: {reason}"
    for admin_id in config.ADMIN_CHAT_IDS:
        _send_telegram_message(admin_id, notify_text)
    return jsonify(ok=True, request_id=request_id)


@app.get("/api/agent-requests")
def api_agent_requests_list():
    """მოთხოვნების სია — ადმინს ყველა ჩანს (?status= ფილტრით),
    თიმლიდერს მხოლოდ საკუთარი გუნდიდან გაგზავნილები."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    status = request.args.get("status") or None
    team = None if admin else str(agent.get("team", "")).strip()
    rows = sheets.get_agent_requests(status=status, team=team)
    teams = sheets.get_team_directory() if admin else []
    return jsonify(rows=rows, teams=teams)


@app.post("/api/agent-requests/decide")
def api_agent_requests_decide():
    """მოთხოვნის დამტკიცება/უარყოფა — მხოლოდ ადმინისთვის. დამტკიცებისას
    რეალურადაც სრულდება მოქმედება (ახალი აგენტის დამატება ან არსებულის
    გათიშვა) — იხ. sheets.decide_agent_request."""
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
    row = sheets.decide_agent_request(request_id, status, decided_by="admin")
    if not row:
        return jsonify(error="ვერ მოიძებნა ან უკვე გადაწყვეტილია"), 404

    label = "✅ დამტკიცებულია" if status == "approved" else "❌ უარყოფილია"
    kind_label = "ახალი აგენტის დამატება" if row.get("kind") == "add" else "აგენტის გათავისუფლება"
    requester = next(
        (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("requested_by"))), None
    )
    if requester and requester.get("telegram_chat_id"):
        _send_telegram_message(
            int(requester["telegram_chat_id"]),
            f"თქვენი მოთხოვნა ({kind_label}: {row.get('name') or row.get('target_agent_id')}) — {label}",
        )
    return jsonify(ok=True, row=row)


@app.post("/api/tasks/new")
def api_tasks_new():
    """ახალი კლიენტის/ლიდის დამატება Mini App-იდან — იგივე ორი
    სცენარი, რაც აქამდე მხოლოდ ბოტის /newtask ბრძანებით შეეძლო
    ადმინს: "ზოგადი" კლიენტი (ავტომატურად ერგება საუკეთესო/სუსტესი
    შემსრულებელს, პრიორიტეტის მიხედვით) და "კონკრეტული ბინა" (პირდაპირ
    არჩეულ აგენტზე). ადმინისთვის — მთელ კომპანიაზე; თიმლიდერისთვის —
    მხოლოდ საკუთარ გუნდში (იგივე კურატორის პრინციპი, რაც უკვე აქვს
    დავალების გადაბარებაზე)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in ("general", "listing"):
        return jsonify(error="არასწორი მოთხოვნა"), 400

    my_team = None if admin else str(agent.get("team", "")).strip()
    created_by = "admin" if admin else str(agent.get("agent_id") or "")

    if kind == "general":
        phone = (body.get("phone") or "").strip()
        deal_type = (body.get("deal_type") or "").strip()
        priority = (body.get("priority") or "").strip()
        if not phone or deal_type not in ("ქირა", "ყიდვა") or priority not in ("მაღალი", "საშუალო", "დაბალი"):
            return jsonify(error="არასწორი მოთხოვნა"), 400
        if not admin and not my_team:
            return jsonify(error="ჯერ არ გაქვთ საკუთარი გუნდი მინიჭებული"), 400
        # მენეჯერს/თიმლიდერს შეუძლია კლიენტი პირდაპირ საკუთარ თავზეც
        # დაირეგისტრიროს (ავტომატური არჩევანის ალგორითმის გვერდის
        # ავლით) — რომ დირექტორსაც სჩანდეს, თავად რას აკეთებს.
        if body.get("assign_to_self") and agent:
            target_agent_id = agent.get("agent_id")
        else:
            target_agent_id = sheets.pick_agent_for_priority(priority, team=my_team)
        if not target_agent_id:
            return jsonify(error="შესაფერისი აქტიური აგენტი ვერ მოიძებნა"), 400
        title = f"კლიენტი {phone} ({deal_type})"
        task_id = sheets.create_task(
            title=title, description="", assigned_to=target_agent_id, priority=priority,
            due_date="", created_by=created_by, lead_type="general",
            client_phone=phone, deal_type=deal_type,
        )
    else:  # kind == "listing"
        target_agent_id = body.get("agent_id")
        listing_id = (body.get("listing_id") or "").strip()
        phone = (body.get("phone") or "").strip()
        viewing_time = (body.get("viewing_time") or "").strip()
        if not target_agent_id or not listing_id or not phone:
            return jsonify(error="არასწორი მოთხოვნა"), 400
        target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(target_agent_id)), None)
        if not target or str(target.get("active", "yes")).strip().lower() == "no":
            return jsonify(error="ეს აგენტი აღარაა აქტიური"), 400
        if not admin and (not my_team or str(target.get("team", "")).strip() != my_team):
            return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტზე შეგიძლიათ დამატება"), 403
        title = f"ნახვა: {listing_id}"
        description = f"ნახვის დრო: {viewing_time}" if viewing_time else ""
        task_id = sheets.create_task(
            title=title, description=description, assigned_to=target_agent_id,
            priority="მაღალი", due_date=viewing_time, created_by=created_by,
            lead_type="listing", client_phone=phone, listing_id=listing_id, viewing_time=viewing_time,
        )

    return jsonify(ok=True, task_id=task_id)


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


@app.post("/api/tasks/ack")
def api_tasks_ack():
    """აგენტი ადასტურებს, რომ კონკრეტული მისთვის მინიჭებული
    კლიენტი/დავალება უკვე ნახა — მენეჯერს/ადმინს რომ სჩანდეს, ვინ
    ჯერ არ გახსნია/მიუღია."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    body = request.get_json(silent=True) or {}
    task_id = body.get("task_id")
    if not task_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400
    row = sheets.mark_task_seen(task_id, agent["agent_id"])
    if not row:
        return jsonify(error="ვერ მოიძებნა ან სხვა აგენტზეა მინიჭებული"), 404

    # შემქმნელს (მენეჯერს/ადმინს) ეცნობება, რომ აგენტმა დაადასტურა.
    created_by = str(row.get("created_by") or "")
    text = f"✅ {agent.get('name')} დაადასტურა კლიენტის მიღება: {row.get('title')}"
    if created_by and created_by != "admin":
        creator = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == created_by), None)
        if creator and creator.get("telegram_chat_id"):
            _send_telegram_message(int(creator["telegram_chat_id"]), text)
    else:
        for admin_id in config.ADMIN_CHAT_IDS:
            _send_telegram_message(admin_id, text)
    return jsonify(ok=True, row=row)


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


@app.get("/api/task-history")
def api_task_history():
    """დავალებების ისტორია (ღიაც და დახურულიც), დღე/კვირა/თვე ფილტრით
    (?period=). ადმინს შეუძლია ?team= და შემდეგ ?agent_id= დრილდაუნი
    (ჯერ ირჩევს გუნდის მენეჯერს, მერე კონკრეტულ აგენტს); თიმლიდერს
    ავტომატურად საკუთარი გუნდი უფილტრდება, აგენტს კი — მხოლოდ თავისი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    days = _period_to_days(request.args.get("period"))
    team_lead = _is_team_lead(agent)

    if admin or team_lead:
        team = request.args.get("team") or (None if admin else str(agent.get("team", "")).strip())
        agent_id = request.args.get("agent_id") or None
        # თუ კონკრეტული agent_id მოთხოვნილია, ვამოწმებთ, რომ ის
        # მართლა ამ სქოუფის (გუნდის) წევრია — თიმლიდერს არ შეუძლია სხვა
        # გუნდის აგენტის ისტორიის ნახვა agent_id-ის პირდაპირ გადაცემით.
        if agent_id and not admin:
            target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(agent_id)), None)
            if not target or str(target.get("team", "")).strip() != team:
                return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტის ისტორია"), 403
        rows = sheets.get_task_history(days=days, agent_id=agent_id, team=None if agent_id else team)
        teams = sheets.get_team_directory() if admin else []
        agents_out = sorted(
            [
                {"agent_id": a.get("agent_id"), "name": a.get("name")}
                for a in sheets.get_agents()
                if (team is None or str(a.get("team", "")).strip() == team)
            ],
            key=lambda r: r.get("name") or "",
        )
        return jsonify(rows=rows[:200], count=len(rows), teams=teams, agents=agents_out, team=team or "")

    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    rows = sheets.get_task_history(days=days, agent_id=agent["agent_id"])
    return jsonify(rows=rows[:200], count=len(rows))


@app.get("/api/meetings")
def api_meetings_history():
    """შეხვედრების ისტორია დღე/კვირა/თვე ფილტრით — ადმინს ყველა
    შეხვედრა ჩანს, თიმლიდერს საკუთარი გუნდისა, აგენტს კი მხოლოდ
    საკუთარი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    days = _period_to_days(request.args.get("period"))
    team_lead = _is_team_lead(agent)

    # თიმლიდერიც ჩვეულებრივი აგენტივით მუშაობს და შეიძლება პირადი
    # შეხვედრებიც ჰქონდეს — "own" მოთხოვნისას მხოლოდ საკუთარი ეჩვენება
    # (ჯამურ გუნდში აღარ ერევა), ნაგულისხმევად კი გუნდის ჯამური.
    if team_lead and request.args.get("scope") == "own":
        rows = sheets.get_meetings(agent_id=agent["agent_id"], days=days)
        rows.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
        return jsonify(rows=rows[:200], count=len(rows), scope="own")

    if admin or team_lead:
        team_filter = None if admin else str(agent.get("team", "")).strip()
        rows = sheets.get_meetings(days=days)
        if team_filter:
            team_ids = {
                str(a.get("agent_id")) for a in sheets.get_agents()
                if str(a.get("team", "")).strip() == team_filter
            }
            rows = [r for r in rows if str(r.get("agent_id")) in team_ids]
        rows.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
        return jsonify(rows=rows[:200], count=len(rows), scope="all" if admin else "team")

    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    rows = sheets.get_meetings(agent_id=agent["agent_id"], days=days)
    rows.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
    return jsonify(rows=rows[:200], count=len(rows), scope="own")


@app.get("/api/clients")
def api_clients():
    """კლიენტების ჯამური სია (თითო უნიკალურ ტელეფონზე ერთი
    სტრიქონი) — ადმინს ყველა კლიენტი ეჩვენება, თიმლიდერს მხოლოდ
    საკუთარი გუნდის (ოდესმე). ძებნა ტელეფონის/სახელის მიხედვით
    frontend-ის მხარეს სრულდება (სია ჯერჯერობით პატარაა)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    team = None if admin else str(agent.get("team", "")).strip()
    rows = sheets.get_all_clients(team=team)
    return jsonify(rows=rows[:500])


@app.get("/api/clients/<path:phone>")
def api_client_history(phone):
    """ერთი კონკრეტული კლიენტის სრული ისტორია — ვისაც კი ოდესმე
    ჰყოლია გადაბარებული (ყველა დავალება/რეპორტი/შეხვედრა ამ
    ტელეფონზე), ერთად, დროის მიხედვით დალაგებული."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    hist = sheets.get_client_history(phone)
    if not admin:
        my_team = str(agent.get("team", "")).strip()
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == my_team
        }
        if not any(str(t.get("assigned_to")) in team_ids for t in hist["tasks"]):
            return jsonify(error="ეს კლიენტი თქვენს გუნდს არასდროს ჰყოლია"), 403
    timeline = []
    for t in hist["tasks"]:
        timeline.append({"kind": "task", "at": t.get("updated_at") or t.get("created_at", ""), "data": t})
    for r in hist["reports"]:
        timeline.append({"kind": "report", "at": r.get("created_at", ""), "data": r})
    for m in hist["meetings"]:
        timeline.append({"kind": "meeting", "at": m.get("timestamp") or m.get("meeting_date", ""), "data": m})
    timeline.sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    return jsonify(phone=phone, timeline=timeline)


@app.get("/api/digest")
def api_digest():
    """დღის შეჯამება (6 პუნქტიანი) — მხოლოდ ადმინი/თიმლიდერი. ადმინს
    შეუძლია ?team= აირჩიოს კონკრეტული გუნდი, სხვა შემთხვევაში მთელი
    კომპანია ეჩვენება. თიმლიდერს ავტომატურად საკუთარი გუნდი უჩანს."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    team = request.args.get("team") or (None if admin else str(agent.get("team", "")).strip())
    try:
        return jsonify(sheets.get_daily_digest(team=team))
    except Exception:
        log.exception("დღის ამბების აწყობა ჩავარდა")
        return jsonify(error="მონაცემების ჩატვირთვა ვერ მოხერხდა"), 500


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

    # მკაცრი წესი: თუ დღეს ამ აგენტს ჰქონდა მინიჭებული/გადაბარებული
    # კლიენტი (ნებისმიერი დავალება, შექმნილი დღეს), დღის დახურვამდე
    # კლიენტის ანგარიშის შევსება სავალდებულოა — "გამოტოვება" აღარ
    # შეიძლება მხოლოდ თვითონ აგენტის სიტყვის მიხედვით. სერვერი თავად
    # ამოწმებს (client_counts), აგენტის თვითდეკლარაციას აღარ ენდობა.
    had_client_today = sheets.client_counts(agent_id).get("today", 0) > 0
    cr = body.get("client_report")
    cr_valid = (
        isinstance(cr, dict)
        and str(cr.get("phone", "")).strip()
        and str(cr.get("actions", "")).strip()
    )
    if had_client_today and not cr_valid:
        return jsonify(
            error="დღეს კლიენტი გქონდათ მინიჭებული — დღის დასახურად კლიენტის ანგარიშის შევსება სავალდებულოა",
            code="client_report_required",
        ), 400

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
            # იხ. bot.py-ის იგივე ლოგიკის კომენტარი: ერთი და იგივე
            # განცხადება ერთდროულად იტვირთება საიტზე და myhome-ზე,
            # ამიტომ ჯამი = max(site, myhome), ss.ge ჯერჯერობით მხოლოდ
            # საინფორმაციოდ ინახება.
            total = max(site, myhome)
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
            team_val = str(agent.get("team", "")).strip()
            if team_val and str(agent.get("role", "")).strip() != "team_lead":
                lead = next(
                    (x for x in sheets.get_agents()
                     if str(x.get("role", "")).strip() == "team_lead"
                     and str(x.get("team", "")).strip() == team_val),
                    None,
                )
                if lead and lead.get("telegram_chat_id"):
                    _send_telegram_message(
                        int(lead["telegram_chat_id"]),
                        f"⚠️ თქვენი გუნდიდან — {agent['name']}: {label}\n{detail}",
                    )

        # "კლიენტი გყავდათ დღეს?" კითხვის პასუხი Mini App-იდან — თუ
        # agent-მა ტელეფონი/მოქმედებები შეავსო, ავტომატურად იქმნება
        # client report, ისევე როგორც /clientreport-ით (ბოტის მხარეს).
        # ფოტოებიც (base64) ინახება დისკზე და file_id-ში ერთვის.
        if result == "ok" and cr_valid:
            try:
                photo_paths = _save_base64_photos(cr.get("photos"))
                sheets.create_report(
                    agent_id=agent_id,
                    client_phone=str(cr.get("phone", "")).strip(),
                    actions=str(cr.get("actions", "")).strip(),
                    notes=str(cr.get("notes", "")).strip(),
                    file_id=",".join(photo_paths),
                )
            except Exception:
                log.exception("Mini App clockout client report ვერ შეიქმნა agent_id=%s", agent_id)
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


@app.get("/api/dayoffs")
def api_dayoffs():
    """Day off ისტორია, სამ ცალკე კატეგორიად გაყოფილი: მომლოდინე /
    დადასტურებული / უარყოფილი — ადმინს ყველა (ან ?team=), თიმლიდერს
    მხოლოდ საკუთარი გუნდისა."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    team = request.args.get("team") if admin else str(agent.get("team", "")).strip()
    rows = sheets.get_dayoff_requests()
    if team:
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == team
        }
        rows = [r for r in rows if str(r.get("agent_id")) in team_ids]
    by_status = {"pending": [], "approved": [], "rejected": []}
    for r in rows:
        by_status.setdefault(str(r.get("status", "")), []).append(r)
    for k in by_status:
        by_status[k].sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return jsonify(
        pending=by_status["pending"],
        approved=by_status["approved"],
        rejected=by_status["rejected"],
        monthly_limit=config.DAYOFF_MONTHLY_LIMIT,
    )


@app.post("/api/dayoff/decide")
def api_dayoff_decide():
    """დღეს ეს ხელმისაწვდომია ადმინისთვისაც და თიმლიდერისთვისაც
    (საკუთარი გუნდის მოთხოვნებზე) — role_permissions-ში ეს უფლება
    თავიდანვე იყო გათვალისწინებული (decide_dayoff), უბრალოდ ეს
    endpoint აქამდე მხოლოდ ადმინზე იყო შეზღუდული. დამტკიცებამდე
    მოწმდება თვის ჭერიც (DAYOFF_MONTHLY_LIMIT)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ ადმინისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    request_id = body.get("request_id")
    status = body.get("status")
    if status not in ("approved", "rejected") or not request_id:
        return jsonify(error="არასწორი მოთხოვნა"), 400

    pending = sheets.get_dayoff_request(request_id)
    if not pending:
        return jsonify(error="ვერ მოიძებნა"), 404
    if str(pending.get("status")) != "pending":
        return jsonify(error="ეს მოთხოვნა უკვე გადაწყვეტილია"), 400

    if not admin:
        team = str(agent.get("team", "")).strip()
        target = next(
            (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(pending.get("agent_id"))), None
        )
        if not target or str(target.get("team", "")).strip() != team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის მოთხოვნის გადაწყვეტა შეიძლება"), 403

    if status == "approved":
        already = sheets.approved_dayoffs_count_this_month(pending.get("agent_id"), pending.get("date", ""))
        if already >= config.DAYOFF_MONTHLY_LIMIT:
            return jsonify(
                error=f"ამ აგენტს ამ თვეში უკვე დამტკიცებული აქვს {config.DAYOFF_MONTHLY_LIMIT} დღეოფი — მეტის დამტკიცება არ შეიძლება"
            ), 400

    row = sheets.decide_dayoff(request_id, status)
    if not row:
        return jsonify(error="ვერ მოიძებნა"), 404

    label = "✅ დამტკიცებულია" if status == "approved" else "❌ უარყოფილია"
    a2 = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("agent_id"))), None)
    if a2 and a2.get("telegram_chat_id"):
        _send_telegram_message(
            int(a2["telegram_chat_id"]),
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


@app.get("/uploads/reports/<path:filename>")
def uploaded_report_photo(filename):
    """კლიენტის რეპორტთან ატვირთული ფოტოს გაცემა — ფაილის სახელი
    შემთხვევითი (UUID) წარმოქმნილია, პირდაპირ ვერავინ გამოიცნობს;
    ცალკე ავტორიზაცია არ სჭირდება, რადგან <img src>-ს Mini App-ის
    custom header-ის დამატება არ შეუძლია."""
    return send_from_directory(UPLOADS_DIR, filename)


def run():
    """ბლოკავს — bot.py იძახებს ცალკე thread-ში."""
    log.info("Mini App ვებ-სერვერი ეშვება პორტზე %s", config.PORT)
    app.run(host="0.0.0.0", port=config.PORT, threaded=True, use_reloader=False)
