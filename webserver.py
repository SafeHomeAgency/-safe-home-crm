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

import functools

import config
import crm_extras
import crm_security
import crm_time
import sheets

log = logging.getLogger("safehome-crm-webapp")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# UPLOADS_DIR env (Railway Volume mount path) — ცარიელი = ძველი ადგილი
UPLOADS_DIR = config.UPLOADS_DIR_OVERRIDE or os.path.join(BASE_DIR, "uploads", "reports")
os.makedirs(UPLOADS_DIR, exist_ok=True)

_rate_limiter = crm_security.RateLimiter()


def _client_ip() -> str:
    """Railway proxy-ს უკან რეალური IP — X-Forwarded-For-ის პირველი მისამართი."""
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else (request.remote_addr or "")) or "unknown"


def _rate_check(bucket: str, identity) -> tuple | None:
    """None = დაშვებულია; სხვა შემთხვევაში (jsonify-response, 429)."""
    if not config.RATE_LIMIT_ENABLED:
        return None
    limit, window = config.RATE_LIMITS[bucket]
    ok, retry_after = _rate_limiter.check((bucket, str(identity)), limit, window)
    if ok:
        return None
    resp = jsonify(error="ძალიან ბევრი მოთხოვნა — სცადეთ ცოტა ხანში", code="rate_limited")
    resp.headers["Retry-After"] = str(retry_after)
    return resp, 429


def rate_limited(bucket: str):
    """decorator: მომხმარებელზე (Telegram ID, თუ initData ვალიდურია; სხვა
    შემთხვევაში IP) ითვლის მოთხოვნებს `config.RATE_LIMITS[bucket]`-ით.
    პროცესის შიდა limiter-ია (იხ. crm_security.RateLimiter)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            parsed = _validate_init_data(request.headers.get("X-Telegram-Init-Data", ""), quiet=True)
            identity = (parsed or {}).get("user", {}).get("id") or _client_ip()
            blocked = _rate_check(bucket, identity)
            if blocked:
                return blocked
            return fn(*args, **kwargs)
        return wrapper
    return deco

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


def _send_telegram_message(chat_id, text: str, reply_markup: dict | None = None) -> bool:
    """პირდაპირი, სინქრონული HTTP მოთხოვნა Telegram-ის Bot API-სთან —
    Flask-ის (სინქრონული) მოთხოვნის დამმუშავებლიდან ბოტის (async)
    obj-ის გამოძახება პირდაპირ არ ხერხდება, ამიტომ აქ იგივეს ვაკეთებთ
    "ხელით", python-telegram-bot-ის გვერდის ავლით.

    აბრუნებს True/False-ს — მნიშვნელოვანია იქ, სადაც ამ შედეგზეა
    დამოკიდებული შემდგომი ლოგიკა (მაგ. task-ის "notified"-ად მონიშვნა):
    თუ გაგზავნა ჩავარდა და მაინც "notified"-ად აღინიშნა, სარეზერვო
    ფონური job (check_new_tasks) აღარასდროს გაიმეორებს მცდელობას და
    შეტყობინება სამუდამოდ იკარგება."""
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        body = {"chat_id": chat_id, "text": text}
        if reply_markup:
            body["reply_markup"] = reply_markup
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        log.exception("Telegram შეტყობინების გაგზავნა Mini App-იდან ვერ მოხერხდა")
        return False


def _send_telegram_document(chat_id, filename: str, content: bytes, caption: str = "") -> bool:
    """ფაილის (მაგ. CSV ექსპორტის) გაგზავნა Telegram-ში — Mini App-ის
    WebView-ში პირდაპირი ჩამოტვირთვა არასანდოა, ამიტომ ფაილს ბოტი
    აგზავნის მომთხოვნის ჩატში. multipart/form-data ხელით აიგება (გარე
    ბიბლიოთეკის გარეშე)."""
    try:
        import uuid as _uuid
        boundary = "----sh" + _uuid.uuid4().hex
        parts = []

        def field(name, value):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
            )

        field("chat_id", str(chat_id))
        if caption:
            field("caption", caption)
        parts.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
                f"filename=\"{filename}\"\r\nContent-Type: text/csv; charset=utf-8\r\n\r\n"
            ).encode()
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception:
        log.exception("Telegram ფაილის გაგზავნა ვერ მოხერხდა")
        return False


def _team_lead_for_team(team: str):
    team = str(team or "").strip()
    if not team:
        return None
    return next(
        (x for x in sheets.get_agents()
         if str(x.get("role", "")).strip() == "team_lead"
         and str(x.get("team", "")).strip() == team),
        None,
    )


def _notify_managers_of_agent(agent: dict, text: str, include_admins: bool = True) -> None:
    """აგენტის თიმლიდერს (თუ ჰყავს და არ არის თავად თიმლიდერი) და
    ადმინებს უგზავნის შეტყობინებას."""
    lead = None
    if str(agent.get("role", "")).strip() != "team_lead":
        lead = _team_lead_for_team(agent.get("team"))
    if lead and lead.get("telegram_chat_id"):
        _send_telegram_message(int(lead["telegram_chat_id"]), text)
    if include_admins:
        for admin_id in config.ADMIN_CHAT_IDS:
            _send_telegram_message(admin_id, text)


# ---------------------------------------------------------------- auth

def _validate_init_data(init_data: str, quiet: bool = False) -> dict | None:
    """ამოწმებს Telegram-ის Mini App `initData`-ს ხელმოწერას. წარმატების
    შემთხვევაში აბრუნებს {"user": {...}} dict-ს, წინააღმდეგ შემთხვევაში
    None-ს."""
    # PHASE 1.5: HMAC + auth_date ვადა (crm_security.validate_init_data).
    # ლოგში მხოლოდ მოკლე მიზეზი იწერება — initData/hash არასდროს.
    user, reason = crm_security.validate_init_data(
        init_data, config.TELEGRAM_BOT_TOKEN,
        config.INITDATA_MAX_AGE_SECONDS, config.INITDATA_FUTURE_SKEW_SECONDS,
    )
    if user is None:
        if not quiet and reason not in ("missing",):
            log.warning("initData უარყოფილია: %s", reason)
        return None
    return {"user": user["user"], "auth_date": user["auth_date"]}


def _authed_agent():
    """მოთხოვნიდან ამოწმებს initData-ს და აბრუნებს
    (agent_or_None, is_admin, error_response_or_None). წარუმატებელი
    ავტორიზაციები IP-ზე რიცხვდება (rate limit `auth_fail`)."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = _validate_init_data(init_data)
    if not parsed:
        blocked = _rate_check("auth_fail", _client_ip())
        if blocked:
            return None, False, blocked
        return None, False, (jsonify(error="ავტორიზაცია ვერ დადასტურდა", code="auth_failed"), 401)
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


def _audit(agent, admin: bool, action: str, entity_type: str = "", entity_id: str = "",
           job_id: str = "", metadata: dict | None = None, result: str = "ok") -> None:
    """PHASE 1.5: ქმედების ჩაწერა AuditLog-ში **რეალური Telegram ID-ით**
    (არა ლიტერალური "admin"-ით). ბიზნეს-ველები (`created_by`/`decided_by`...)
    უცვლელია — მათზე ლოგიკა დამოკიდებულია. audit-ის ჩავარდნა ძირითად
    ოპერაციას არასდროს აჩერებს."""
    try:
        role = "admin" if admin else (str((agent or {}).get("role") or "agent"))
        sheets.add_audit_event(
            _requester_chat_id(), role, action, entity_type, str(entity_id or ""),
            str(job_id or ""), metadata or {}, result,
        )
    except Exception:
        log.exception("audit ჩაწერა ვერ მოხერხდა (%s)", action)


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
        # მენეჯერს აგენტის დეტალებში უჩანს, რომელ რაიონზე მუშაობს ამ კვირაში
        try:
            ws_now = crm_time.week_start().strftime(crm_time.DATE_FMT)
            amap = {
                str(r.get("agent_id")): crm_extras.split_districts(r.get("districts", ""))
                for r in sheets.get_district_assignments(week_start=ws_now)
            }
            for t in payload["admin"].get("team", []):
                t["districts"] = ", ".join(amap.get(str(t.get("agent_id")), []))
        except Exception:
            log.exception("districts team overlay ჩავარდა")
    if agent:
        try:
            payload["agent"] = sheets.get_agent_dashboard(agent["agent_id"], days=days)
        except Exception:
            log.exception("agent dashboard ჩავარდა")
            return jsonify(error="მონაცემების ჩატვირთვა ვერ მოხერხდა"), 500
        # ახალი ბარათები (Attendance + კვირის რაიონები) — თუ რომელიმე
        # ვერ ჩაიტვირთა, მთავარი დაშბორდი მაინც სრულად იტვირთება.
        try:
            payload["attendance"] = crm_extras.attendance_card(agent)
        except Exception:
            log.exception("attendance card ჩავარდა")
        try:
            payload["districts"] = _district_week_payload(agent)
        except Exception:
            log.exception("districts card ჩავარდა")
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
@rate_limited("bulk_notify")
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


@app.get("/api/myhome-jobs")
def api_myhome_jobs():
    """აგენტს — საკუთარი job-ები; თიმლიდერს — თავისი თიმის; ადმინს —
    ყველა (იგივე თიმის-ფილტრის პრინციპი, რაც `/api/reports`-ს აქვს)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if admin:
        rows = sheets.get_myhome_jobs()
    elif _is_team_lead(agent):
        rows = sheets.get_myhome_jobs(team=agent.get("team", ""))
    elif agent:
        rows = sheets.get_myhome_jobs(agent_id=agent["agent_id"])
    else:
        return jsonify(error="ავტორიზაცია საჭიროა"), 403
    payload = {"rows": rows}
    if admin:
        try:
            payload["workers"] = worker_status_list()
        except Exception:
            log.exception("worker status ვერ ჩაიტვირთა")
    return jsonify(payload)


@app.post("/api/myhome-jobs")
@rate_limited("job_create")
def api_myhome_jobs_create():
    """აგენტი Mini App-იდან შეაქვს MyHome ID (+ %, ფასი, შენიშვნა) —
    queue-ში ემატება "QUEUED" job. worker.py (ცალკე კომპიუტერზე)
    შემდეგ თავად პოულობს, რომელ მენეჯერის ანგარიშზე უნდა გამოქვეყნდეს
    (agent -> team -> myhome_accounts) — აგენტს არაფრის არჩევა არ
    სჭირდება და MyHome ანგარიშის შესახებ არაფერს ხედავს."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403

    body = request.get_json(silent=True) or {}
    listing_id = str(body.get("myhome_listing_id") or "").strip()
    if not listing_id or not listing_id.isdigit():
        return jsonify(error="MyHome ID არასწორია — მხოლოდ ციფრები"), 400

    # მესაკუთრის ნომერი სავალდებულოდ აგენტისგანვე ვიღებთ — myhome.ge-ს
    # საკუთარი "ნომრის ნახვა" ხშირად დროებით იბლოკება (ანგარიშის/IP-ის
    # დონეზე, ავტომატურადაც და ხელითაც), ამიტომ worker.py აღარ ცდილობს
    # საიტიდან ამოღებას — პირდაპირ ამ ველს იყენებს.
    owner_number = str(body.get("owner_number") or "").strip()
    if not owner_number:
        return jsonify(error="მესაკუთრის ნომრის მითითება სავალდებულოა"), 400

    team = str(agent.get("team", "")).strip()
    account = sheets.get_myhome_account_for_team(team)
    if not account or not str(account.get("manager_label", "")).strip():
        return jsonify(
            error="თქვენი გუნდისთვის MyHome ანგარიში ჯერ არაა მიბმული — მიმართეთ ადმინს"
        ), 409

    # ბიზნეს-წესი (PHASE 1.5): უნიკალურია `agent_id + myhome_id + ბიზნეს-დღე
    # (Asia/Tbilisi)`. გლობალური დუბლიკატის აკრძალვა **არ არის**: იგივე ID
    # შეუძლია სხვა აგენტსაც (სხვა ფასზე შეთანხმებით), ან იგივე აგენტს —
    # ხვალ. ფასი გასაღების ნაწილი არ არის. შემოწმება+შექმნა ერთად (სერვერზე).
    job_id, existing = sheets.create_myhome_job_once_per_day(agent["agent_id"], {
        "team": team,
        "manager_label": account.get("manager_label", ""),
        "myhome_listing_id": listing_id,
        "cooperation_percent": str(body.get("cooperation_percent") or "").strip(),
        "final_price": str(body.get("final_price") or "").strip(),
        "notes": str(body.get("notes") or "").strip(),
        "owner_number": owner_number,
    })
    if job_id is None:
        hint = " (ჩავარდნილის გასაშვებად გამოიყენეთ „ხელახლა ცდა“)" if (existing or {}).get("status") == "FAILED" else ""
        return jsonify(error="ამ MyHome ID-ს დღეს უკვე შეიყვანეთ — ერთსა და იმავე ID-ს ერთი აგენტი "
                             "დღეში ერთხელ შეიყვანს" + hint,
                       code="duplicate_today", row=existing), 409
    row = sheets.find_myhome_job(job_id)
    _audit(agent, admin, "myhome_job_create", "myhome_job", job_id, job_id,
           {"myhome_listing_id": listing_id, "team": team})
    if agent.get("telegram_chat_id"):
        _send_telegram_message(
            int(agent["telegram_chat_id"]),
            f"🏠 MyHome ID {listing_id} დაემატა რიგში (QUEUED) — შეგატყობინებთ დამუშავებისას.",
        )
    return jsonify(ok=True, row=row)


@app.get("/api/myhome-jobs/search")
def api_myhome_jobs_search():
    """ყველა აგენტის MyHome job-ების ძებნა — `?q=`(ტექსტი: ID/მისამართი/
    რაიონი/ქალაქი/აგენტი/შენიშვნა), `?deal_type=`, `?status=`,
    `?date_from=`/`?date_to=` (YYYY-MM-DD). განზრახ ღიაა ნებისმიერი
    დარეგისტრირებული აგენტისთვის ყველა კოლეგის მონაცემებზე — იგივე,
    რაც ძველი Google Sheets "ბაზა" იძლეოდა (კლიენტის გადაბარებისას
    კოლეგის დადებული ბინის საპოვნელად)."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (agent or admin):
        return jsonify(error="ავტორიზაცია საჭიროა"), 403
    rows = sheets.search_myhome_jobs(
        query=request.args.get("q", ""),
        deal_type=request.args.get("deal_type", ""),
        status=request.args.get("status", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
    )
    return jsonify(rows=rows)


@app.get("/api/myhome-jobs/stats")
def api_myhome_jobs_stats():
    """თითო აგენტზე შეჯამებული სტატისტიკა, თარიღის ფილტრით
    (`?date_from=`/`?date_to=`, YYYY-MM-DD). თიმლიდერს — მხოლოდ
    საკუთარი გუნდი (query-ს `team` პარამეტრი, თუ არაა ადმინი,
    იგნორირდება — იგივე დაცვა, რაც `/api/reports`-ს აქვს); ადმინს —
    ყველა, ან კონკრეტული `?team=` მითითებით."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/ადმინისთვის"), 403
    team = request.args.get("team") if admin else str(agent.get("team", "")).strip()
    rows = sheets.get_myhome_job_stats(
        team=team or None,
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
    )
    return jsonify(rows=rows)


@app.post("/api/myhome-jobs/retry")
def api_myhome_jobs_retry():
    """FAILED (ან გაჭედილი PROCESSING) job-ის ხელახლა "QUEUED"-ში
    დაბრუნება პირდაპირ Mini App-იდან — აღარაა საჭირო Railway Console-ში
    ხელით სკრიპტის გაშვება. აგენტს — მხოლოდ საკუთარი job, თიმლიდერს —
    საკუთარი გუნდის, ადმინს — ნებისმიერი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        return jsonify(error="job_id საჭიროა"), 400
    row = sheets.find_myhome_job(job_id)
    if not row:
        return jsonify(error="job ვერ მოიძებნა"), 404
    if not admin:
        if _is_team_lead(agent):
            if str(row.get("team", "")).strip() != str(agent.get("team", "")).strip():
                return jsonify(error="მხოლოდ საკუთარი გუნდის job-ისთვის"), 403
        elif agent:
            if str(row.get("agent_id", "")) != str(agent.get("agent_id", "")):
                return jsonify(error="მხოლოდ საკუთარი job-ისთვის"), 403
        else:
            return jsonify(error="ავტორიზაცია საჭიროა"), 403
    if row.get("status") not in ("FAILED", "PROCESSING"):
        return jsonify(error="მხოლოდ ჩავარდნილი/გაჭედილი job-ის ხელახლა გაშვება შეიძლება"), 400
    if row.get("status") == "PROCESSING":
        # PHASE 1.5: ახლა მიმდინარე (ცოცხალი) job ხელით არ უნდა დაბრუნდეს
        # queue-ში — worker მას ამუშავებს და მეორე დაკავება განცხადებას
        # გააორმაგებდა. "გაჭედილია" მხოლოდ STALE ვადის შემდეგ.
        started = crm_time.parse_server_dt(row.get("started_at") or row.get("created_at"))
        age_min = (datetime.datetime.now() - started).total_seconds() / 60 if started else 10**6
        if age_min < config.MYHOME_JOB_STALE_MINUTES:
            return jsonify(error="job ახლა მუშავდება — დაელოდეთ დასრულებას (გაჭედილად "
                                 f"{config.MYHOME_JOB_STALE_MINUTES} წუთის შემდეგ ითვლება)"), 409
    updated = sheets.retry_myhome_job(job_id)
    if not updated:
        return jsonify(error="ვერ განახლდა"), 409
    _audit(agent, admin, "myhome_job_retry_manual", "myhome_job", job_id, job_id,
           {"previous_status": row.get("status"), "retry_count": row.get("retry_count")})
    return jsonify(ok=True, row=updated)


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

    if not admin:
        my_team = str(agent.get("team", "")).strip()
        target = next((r for r in sheets.get_reports() if str(r.get("report_id")) == str(report_id)), None)
        target_agent = next(
            (a for a in sheets.get_agents() if str(a.get("agent_id")) == str((target or {}).get("agent_id"))), None,
        )
        if not target or not target_agent or str(target_agent.get("team", "")).strip() != my_team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის რეპორტის შეფასება შეიძლება"), 403

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

    team = request.args.get("team") if admin else str(agent.get("team", "")).strip()
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

    if not admin:
        my_team = str(agent.get("team", "")).strip()
        target = next((s for s in sheets.get_shift_swaps() if str(s.get("swap_id")) == str(swap_id)), None)
        target_agent = next(
            (a for a in sheets.get_agents() if str(a.get("agent_id")) == str((target or {}).get("agent_id"))), None,
        )
        if not target or not target_agent or str(target_agent.get("team", "")).strip() != my_team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის მოთხოვნის გადაწყვეტა შეიძლება"), 403

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
@rate_limited("bulk_notify")
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
    _audit(agent, admin, "warning_dismiss_request", "warning", warning_id,
           metadata={"reason": reason[:200]})

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
@rate_limited("bulk_notify")
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
    _audit(None, admin, "warning_dismiss_decide", "warning", warning_id,
           metadata={"approve": approve, "agent_id": row.get("agent_id")})

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


def _clean_id_list(value, limit: int = 300) -> list[str]:
    seen, out = set(), []
    for v in (value if isinstance(value, list) else []):
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:limit]


@app.post("/api/warnings/request-dismiss-bulk")
@rate_limited("bulk_notify")
def api_warnings_request_dismiss_bulk():
    """მულტი-მონიშვნა: რამდენიმე გაფრთხილების გაუქმების მოთხოვნა ერთად,
    ერთი მიზეზით. უფლებები/შეზღუდვები იგივეა, რაც ერთეულ
    `/api/warnings/request-dismiss`-ში (თიმლიდერი — მხოლოდ საკუთარი
    გუნდის გაფრთხილებებზე; სხვისი გუნდის ID-ები ჩუმად გამოიტოვება და
    `skipped`-ში ჩაითვლება). ადმინს ერთი შეჯამებული შეტყობინება
    მიდის და არა N ცალკე."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/თიმლიდერისთვის"), 403
    body = request.get_json(silent=True) or {}
    ids = _clean_id_list(body.get("warning_ids"))
    reason = (body.get("reason") or "").strip()
    if not ids or not reason:
        return jsonify(error="მონიშნეთ გაფრთხილებები და მიუთითეთ მიზეზი"), 400

    allowed = set(ids)
    if not admin:
        my_team = str(agent.get("team", "")).strip()
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == my_team
        }
        allowed = {
            str(w.get("warning_id")) for w in sheets.get_warnings()
            if str(w.get("warning_id")) in set(ids) and str(w.get("agent_id")) in team_ids
        }
    requested_by = "admin" if admin else agent.get("agent_id")
    rows = sheets.request_warning_dismissals_bulk(sorted(allowed), requested_by, reason) if allowed else []
    _audit(agent, admin, "warning_dismiss_request_bulk", "warning", ",".join(sorted(allowed)[:20]),
           metadata={"reason": reason[:200], "requested": len(rows)})

    if rows:
        by_agent: dict[str, list[dict]] = {}
        for r in rows:
            by_agent.setdefault(str(r.get("agent_name") or r.get("agent_id")), []).append(r)
        requester_name = "ადმინი" if admin else agent.get("name")
        lines = [f"📝 გაფრთხილებების გაუქმების მოთხოვნა — {requester_name}", f"სულ: {len(rows)}"]
        for name, items in by_agent.items():
            kinds = ", ".join(
                f"{WARNING_TYPE_LABELS.get(i.get('type'), i.get('type'))} ({str(i.get('created_at', '')).split(' ')[0]})"
                for i in items[:5]
            )
            more = f" +{len(items) - 5}" if len(items) > 5 else ""
            lines.append(f"• {name}: {len(items)} — {kinds}{more}")
        lines.append(f"მიზეზი: {reason}")
        text = "\n".join(lines)
        for admin_id in config.ADMIN_CHAT_IDS:
            _send_telegram_message(admin_id, text)
    return jsonify(ok=True, requested=len(rows), skipped=len(ids) - len(rows))


@app.post("/api/warnings/decide-dismiss-bulk")
@rate_limited("bulk_notify")
def api_warnings_decide_dismiss_bulk():
    """მულტი-მონიშვნა: დირექტორის გადაწყვეტილება (დამტკიცება/უარყოფა)
    რამდენიმე "dismiss_pending" გაფრთხილებაზე ერთად. თითო აგენტს
    და თითო მომთხოვნ მენეჯერს ერთი შეჯამებული შეტყობინება მიდის
    განახლებული მრიცხველით."""
    _, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    ids = _clean_id_list(body.get("warning_ids"))
    approve = bool(body.get("approve"))
    if not ids:
        return jsonify(error="მონიშნეთ გაფრთხილებები"), 400
    rows = sheets.decide_warning_dismissals_bulk(ids, approve, decided_by="admin")
    _audit(None, admin, "warning_dismiss_decide_bulk", "warning", ",".join(ids[:20]),
           metadata={"approve": approve, "requested": len(ids), "decided": len(rows)})
    label = "✅ გაუქმდა" if approve else "❌ უარყოფილია, ძალაშია"
    agents_by_id = {str(a.get("agent_id")): a for a in sheets.get_agents()}

    per_agent: dict[str, int] = {}
    per_requester: dict[str, dict[str, int]] = {}
    for r in rows:
        aid = str(r.get("agent_id"))
        per_agent[aid] = per_agent.get(aid, 0) + 1
        req = str(r.get("dismiss_requested_by") or "")
        if req:
            per_requester.setdefault(req, {})
            per_requester[req][aid] = per_requester[req].get(aid, 0) + 1

    for aid, n in per_agent.items():
        a = agents_by_id.get(aid)
        if a and a.get("telegram_chat_id"):
            _send_telegram_message(
                int(a["telegram_chat_id"]),
                f"თქვენი {n} გაფრთხილების გაუქმების მოთხოვნა — {label}.\n"
                f"მიმდინარე გაფრთხილებების რაოდენობა: {_active_warning_count(aid)}/{config.WARNING_LIMIT}.",
            )
    for req_id, agent_counts in per_requester.items():
        requester = agents_by_id.get(req_id)
        if requester and requester.get("telegram_chat_id"):
            lines = [f"თქვენი მოთხოვნა ({sum(agent_counts.values())} გაფრთხილება) — {label}."]
            for aid, n in agent_counts.items():
                lines.append(
                    f"• {(agents_by_id.get(aid) or {}).get('name', aid)}: {n} — "
                    f"ახლა {_active_warning_count(aid)}/{config.WARNING_LIMIT}"
                )
            _send_telegram_message(int(requester["telegram_chat_id"]), "\n".join(lines))
    return jsonify(ok=True, decided=len(rows), skipped=len(ids) - len(rows))


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
    _audit(None, admin, "agent_rekey_team", "agent", agent_id)
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
    _audit(None, admin, "agent_delete", "agent", agent_id)
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

    _audit(None, admin, "agent_assign", "agent", agent_id,
           metadata={"mode": mode, "manager_id": body.get("manager_id")})

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
    _audit(None, admin, "agent_set_active", "agent", agent_id, metadata={"active": active})
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
    _audit(None, admin, "agent_request_decide", "agent_request", request_id,
           metadata={"status": status, "ok": bool(row)})
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
@rate_limited("bulk_notify")
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
        # "დამატებითი დეტალი" (არასავალდებულო) — მენეჯერის შენიშვნა, რომელსაც
        # აგენტი ამ კლიენტზე კითხულობს (ინახება დავალების description-ში).
        notes = (body.get("notes") or "").strip()[:1000]
        task_id = sheets.create_task(
            title=title, description=notes, assigned_to=target_agent_id, priority=priority,
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
        # ძველად აქ description-ში "ნახვის დრო: ..." იწერებოდა და იმავე
        # დროს ცალკე viewing_time ველშიც — აგენტის შეტყობინებაში ორჯერ
        # ჩანდა. ახლა description = მენეჯერის არასავალდებულო
        # "დამატებითი დეტალი"; ნახვის დრო მხოლოდ viewing_time-შია.
        description = (body.get("notes") or "").strip()[:1000]
        owner_phone = (body.get("owner_phone") or "").strip()
        task_id = sheets.create_task(
            title=title, description=description, assigned_to=target_agent_id,
            priority="მაღალი", due_date=viewing_time, created_by=created_by,
            lead_type="listing", client_phone=phone, listing_id=listing_id, viewing_time=viewing_time,
            owner_phone=owner_phone,
        )

    _audit(agent, admin, "task_create", "task", task_id, metadata={"kind": kind})
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
    _audit(agent, admin, "task_reassign", "task", task_id, metadata={"to_agent_id": to_agent_id})

    if to_agent.get("telegram_chat_id"):
        title = str(row.get("title") or "")
        phone = str(row.get("client_phone") or "").strip()
        msg = f"📋 გადმოგეცით დავალება: {title}"
        if phone and phone not in title:
            msg += f"\nკლიენტი: {phone}"
        if str(row.get("owner_phone") or "").strip():
            msg += f"\nმესაკუთრე: {row.get('owner_phone')}"
        if str(row.get("description") or "").strip():
            msg += f"\n📝 დეტალი: {row.get('description')}"
        sent_ok = _send_telegram_message(int(to_agent["telegram_chat_id"]), msg)
        # მნიშვნელოვანია: "notified"-ად მხოლოდ მაშინ ვნიშნავთ, თუ
        # გაგზავნა ნამდვილად წარმატებული იყო. თუ ეს ერთხელ (ქსელის
        # ხანმოკლე ჩავარდნით, ან Telegram API-ის დროებითი შეცდომით)
        # წარუმატებელი აღმოჩნდა, მაგრამ მაინც "notified=yes"-ად
        # მონიშნული დარჩებოდა — სარეზერვო ფონური job (check_new_tasks,
        # რომელიც ზუსტად ასეთი შემთხვევებისთვისაა) აღარასდროს
        # შეამჩნევდა და მეორედ ვეღარასდროს სცდიდა გაგზავნას, თანაც
        # მენეჯერს "✅ გადაბარდა" ეჩვენებოდა მიუხედავად რეალური
        # წარუმატებლობისა — სწორედ ეს იყო აგენტამდე კლიენტის
        # "არმისვლის" ნამდვილი მიზეზი.
        if sent_ok:
            try:
                sheets.mark_task_notified(task_id)
            except Exception:
                log.exception("mark_task_notified ჩავარდა reassign-ის შემდეგ")
        else:
            log.warning(
                f"reassign: Telegram შეტყობინება ვერ გაეგზავნა agent_id={to_agent_id} "
                f"task_id={task_id} — check_new_tasks ფონურმა job-მა უნდა გაიმეოროს."
            )
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
        team = request.args.get("team") if admin else str(agent.get("team", "")).strip()
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
    # crm_extras.client_directory — ერთ ნომერს სხვადასხვა ფორმატით
    # ჩაწერილს (+995/0599/ინტერვალებით) ერთ კლიენტად აერთიანებს და
    # დავალებების გარდა რეპორტებსა და შეხვედრებსაც ითვალისწინებს.
    rows = crm_extras.client_directory(team=team)
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
    hist = crm_extras.client_history(phone)
    if not admin:
        my_team = str(agent.get("team", "")).strip()
        team_ids = {
            str(a.get("agent_id")) for a in sheets.get_agents()
            if str(a.get("team", "")).strip() == my_team
        }
        if not (hist["agent_ids"] & team_ids):
            return jsonify(error="ეს კლიენტი თქვენს გუნდს არასდროს ჰყოლია"), 403
    timeline = []
    for t in hist["tasks"]:
        timeline.append({"kind": "task", "at": t.get("updated_at") or t.get("created_at", ""), "data": t})
    for r in hist["reports"]:
        timeline.append({"kind": "report", "at": r.get("created_at", ""), "data": r})
    for m in hist["meetings"]:
        timeline.append({"kind": "meeting", "at": m.get("timestamp") or m.get("meeting_date", ""), "data": m})
    for e in hist["exclusives"]:
        timeline.append({"kind": "exclusive", "at": e.get("created_at", ""), "data": e})
    for j in hist["myhome_jobs"]:
        timeline.append({"kind": "myhome", "at": j.get("completed_at") or j.get("created_at", ""), "data": j})
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
    team = request.args.get("team") if admin else str(agent.get("team", "")).strip()
    days = _period_to_days(request.args.get("period"))
    try:
        return jsonify(sheets.get_daily_digest(team=team, days=days))
    except Exception:
        log.exception("დღის ამბების აწყობა ჩავარდა")
        return jsonify(error="მონაცემების ჩატვირთვა ვერ მოხერხდა"), 500


@app.post("/api/clockin")
def api_clockin():
    """სამუშაოს დაწყება. თუ ოფისის GPS ვერიფიკაცია ჩართულია (ადმინმა
    ოფისის კოორდინატი დააყენა), body-ში {lat, lng, accuracy} სავალდებულოა
    — მანძილი/სტატუსი სერვერზე ითვლება. ძველებურად (GPS-ის გარეშე)
    მუშაობს მანამ, სანამ ოფისის კოორდინატი არ არის დაყენებული. ეს
    ერთადერთი რეალიზაციაა — `/api/attendance/check-in` იგივე
    ფუნქციის ალიასია."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    if str(agent.get("active", "yes")).lower() == "no":
        return jsonify(error="თქვენი ანგარიში გამორთულია"), 403
    body = request.get_json(silent=True) or {}
    geo, geo_err = crm_extras.parse_geo_input(body)
    if geo_err:
        return jsonify(error="⚠️ მდებარეობის განსაზღვრა ვერ მოხერხდა. სცადეთ ხელახლა.", code="invalid_location"), 400
    try:
        res = crm_extras.check_in(agent, geo)
    except Exception:
        log.exception("check-in ჩავარდა agent_id=%s", agent.get("agent_id"))
        return jsonify(error="⚠️ მონაცემის გაგზავნა ვერ მოხერხდა. სცადეთ ხელახლა.", code="server_error"), 500
    if not res.get("ok"):
        status = 403 if res.get("code") == "outside_office" else 400
        return jsonify(error=res.get("message", "შეცდომა"), code=res.get("code"),
                       distance_m=res.get("distance_m")), status
    if res.get("result") == "ok":
        try:
            alert = crm_extras.checkin_alert_text(agent, res)
            if alert:
                _notify_managers_of_agent(agent, alert)
        except Exception:
            log.exception("check-in შეტყობინება ვერ გაიგზავნა")
    return jsonify(
        result=res.get("result"), geo_status=res.get("geo_status", ""),
        distance_m=res.get("distance_m"), late=res.get("late", False),
        attendance=crm_extras.attendance_card(agent),
    )


app.add_url_rule("/api/attendance/check-in", endpoint="api_attendance_check_in",
                 view_func=api_clockin, methods=["POST"])


def _notify_quota_warning(agent: dict, warn_result: dict, detail: str) -> None:
    """"quota_missed" გაფრთხილების შეტყობინებები: ადმინებს, აგენტს და
    აგენტის თიმლიდერს (ადრე ეს კოდი api_clockout-ის შიგნით იყო —
    უცვლელად გადმოტანილია, რომ Day off-ით გამოტოვების ლოგიკა
    მარტივად დაემატოს)."""
    label = "დღიური გეგმა (განცხადებები) ვერ შესრულდა"
    text_admin = (
        f"⚠️ გაფრთხილება — {agent['name']}: {label}\n{detail}\n"
        f"მიმდინარე თვეში: {warn_result['count']}/{config.WARNING_LIMIT}"
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
        lead = _team_lead_for_team(team_val)
        if lead and lead.get("telegram_chat_id"):
            _send_telegram_message(
                int(lead["telegram_chat_id"]),
                f"⚠️ თქვენი გუნდიდან — {agent['name']}: {label}\n{detail}",
            )


@app.post("/api/clockout")
@rate_limited("clockout")
def api_clockout():
    """სამუშაო დღის დასრულება. ოფისის ცვლაზე body-ში მოდის {site, ssge}
    (საიტი და ss.ge — აგენტის თვითდეკლარაცია); MyHome-ის რაოდენობა და
    ონლაინ დღის საერთო რიცხვი **აღარ მოდის აგენტისგან** — სერვერი
    ავტომატურად, რეალურად დადებული (COMPLETED) განცხადებებიდან ითვლის.
    თუ GPS ვერიფიკაცია ჩართულია — body-ში {lat, lng, accuracy}
    სავალდებულოა. თუ ჯამი დღიურ გეგმაზე ნაკლებია — ავტომატურად ემატება
    "quota_missed" გაფრთხილება (Day off-ზე — არა), ისევე როგორც
    ბოტის /clockout-ში."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    body = request.get_json(silent=True) or {}
    agent_id = agent["agent_id"]

    # Attendance + GPS: დღის დახურვამდე (არაფრის ჩაწერამდე) ვამოწმებთ
    # ლოკაციას — თუ GPS ჩართულია და არ გამოუგზავნია, დღე არ იხურება.
    geo, geo_err = crm_extras.parse_geo_input(body)
    if geo_err:
        return jsonify(error="⚠️ მდებარეობის განსაზღვრა ვერ მოხერხდა. სცადეთ ხელახლა.", code="invalid_location"), 400
    pre = crm_extras.check_out_precheck(agent, geo)
    if pre:
        return jsonify(error=pre["message"], code=pre["code"]), 400

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

        # MyHome-ის რაოდენობა აღარ არის აგენტის ხელით შეყვანილი (შეეძლო
        # რეალურზე მეტის მითითება) — ავტომატურად, ნამდვილად დადებული
        # (worker.py-ს მიერ COMPLETED) განცხადებებიდან ითვლება.
        myhome = crm_extras.count_myhome_completed_today(agent_id)
        if mode in ("office_morning", "office_evening"):
            site, ssge = _as_int(body.get("site")), _as_int(body.get("ssge"))
            # იხ. bot.py-ის იგივე ლოგიკის კომენტარი: ერთი და იგივე
            # განცხადება ერთდროულად იტვირთება საიტზე და myhome-ზე,
            # ამიტომ ჯამი = max(site, myhome), ss.ge ჯერჯერობით მხოლოდ
            # საინფორმაციოდ ინახება.
            total = max(site, myhome)
            sheets.set_daily_count(agent_id, total, site=site, myhome=myhome, ssge=ssge)
        else:
            total = myhome
            sheets.set_daily_count(agent_id, total)

        # დასრულების ლოკაციის ივენთი (თუ გამოგზავნა) — clock_out უკვე
        # წარმატებულია, ამიტომ მხოლოდ ახლა ვწერთ.
        try:
            crm_extras.record_check_out(agent, geo)
        except Exception:
            log.exception("check-out ივენთი ვერ ჩაიწერა agent_id=%s", agent_id)

        quota = sheets.quota_for_mode(mode)
        if quota and total < quota:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            detail = f"{today}: {total}/{quota} (Mini App-იდან)"
            warn_result = sheets.add_warning(agent_id, "quota_missed", detail)
            # დამტკიცებული Day off დღეს -> გაფრთხილება არ იწერება
            # (skipped) და არავის ეგზავნება შეტყობინება.
            if not warn_result.get("skipped"):
                _notify_quota_warning(agent, warn_result, detail)

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
    return jsonify(result=result, attendance=crm_extras.attendance_card(agent))


app.add_url_rule("/api/attendance/check-out", endpoint="api_attendance_check_out",
                 view_func=api_clockout, methods=["POST"])


# ------------------------------------------------ Attendance + GPS (v4.0)
# უფლებები (ყველა შემოწმება სერვერზეა, frontend-ის დამალვა უფლებას არ
# ცვლის): აგენტი — მხოლოდ საკუთარი; თიმლიდერი — მხოლოდ საკუთარი გუნდი
# (query-ის `team` იგნორირდება); ადმინი — ყველა (`?team=` ფილტრით).

def _requester_chat_id():
    parsed = _validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    return (parsed or {}).get("user", {}).get("id")


def _attendance_manager_scope(agent, admin):
    """(team_filter, error_response). ადმინი: None ან ?team=; თიმლიდერი:
    საკუთარი გუნდი."""
    if admin:
        return (request.args.get("team") or None), None
    if _is_team_lead(agent):
        team = str(agent.get("team", "")).strip()
        if not team:
            return None, (jsonify(error="ჯერ არ გაქვთ საკუთარი გუნდი მინიჭებული"), 400)
        return team, None
    return None, (jsonify(error="მხოლოდ მენეჯერისთვის/ადმინისთვის"), 403)


@app.get("/api/attendance/me/today")
def api_attendance_me_today():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    return jsonify(attendance=crm_extras.attendance_card(agent))


@app.get("/api/attendance/me/history")
def api_attendance_me_history():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    return jsonify(rows=crm_extras.attendance_history(agent, request.args.get("month", "")))


@app.get("/api/attendance/overview")
def api_attendance_overview():
    """დღის დასწრება (ცხრილი + შეჯამება) ფილტრებით: date, team (მხოლოდ
    ადმინი), agent_id, state, geo, late=1."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    team, scope_err = _attendance_manager_scope(agent, admin)
    if scope_err:
        return scope_err
    agent_id = request.args.get("agent_id") or None
    if agent_id and not admin:
        target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(agent_id)), None)
        if not target or str(target.get("team", "")).strip() != team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტი"), 403
    data = crm_extras.attendance_overview(
        request.args.get("date", ""), team=team, agent_id=agent_id,
        state=request.args.get("state", ""), geo=request.args.get("geo", ""),
        late_only=request.args.get("late") in ("1", "true", "yes"),
    )
    teams = []
    if admin:
        seen = {}
        for a in sheets.get_agents():
            t = str(a.get("team", "")).strip()
            if t and t not in seen:
                lead = _team_lead_for_team(t)
                seen[t] = (lead or {}).get("name") or t
        teams = [{"team": k, "label": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1])]
    return jsonify(
        summary=data["summary"], rows=data["rows"], teams=teams,
        settings=_attendance_settings_public(admin),
    )


app.add_url_rule("/api/attendance/team/today", endpoint="api_attendance_team_today",
                 view_func=api_attendance_overview, methods=["GET"])
app.add_url_rule("/api/attendance/admin/today", endpoint="api_attendance_admin_today",
                 view_func=api_attendance_overview, methods=["GET"])


@app.get("/api/attendance/history")
def api_attendance_history():
    """ერთი აგენტის თვის დასწრების ისტორია მენეჯერისთვის/ადმინისთვის."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    team, scope_err = _attendance_manager_scope(agent, admin)
    if scope_err:
        return scope_err
    target_id = request.args.get("agent_id")
    target = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(target_id)), None)
    if not target:
        return jsonify(error="აგენტი ვერ მოიძებნა"), 404
    if not admin and str(target.get("team", "")).strip() != team:
        return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტი"), 403
    return jsonify(rows=crm_extras.attendance_history(target, request.args.get("month", "")),
                   agent_name=target.get("name"))


@app.post("/api/attendance/export")
@rate_limited("export")
def api_attendance_export():
    """დასწრების CSV ექსპორტი — ფაილს ბოტი აგზავნის მომთხოვნის
    Telegram ჩატში (Mini App-ის WebView-ში პირდაპირი ჩამოტვირთვა
    არასანდოა). body: {date_from, date_to, team?}."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    team, scope_err = _attendance_manager_scope(agent, admin)
    if scope_err:
        return scope_err
    body = request.get_json(silent=True) or {}
    d_to = crm_time.parse_user_date(body.get("date_to", "")) or crm_time.local_today()
    d_from = crm_time.parse_user_date(body.get("date_from", "")) or d_to.replace(day=1)
    if admin and body.get("team"):
        team = str(body.get("team"))
    chat_id = _requester_chat_id()
    if not chat_id:
        return jsonify(error="ჩატი ვერ განისაზღვრა"), 400
    csv_text = crm_extras.attendance_csv(
        d_from.strftime(crm_time.DATE_FMT), d_to.strftime(crm_time.DATE_FMT), team=team,
    )
    fname = f"attendance_{d_from.strftime(crm_time.DATE_FMT)}_{d_to.strftime(crm_time.DATE_FMT)}.csv"
    ok = _send_telegram_document(
        chat_id, fname, csv_text.encode("utf-8-sig"),
        caption=f"📤 დასწრება {d_from.strftime(crm_time.DATE_FMT)} → {d_to.strftime(crm_time.DATE_FMT)}",
    )
    if not ok:
        return jsonify(error="ფაილის გაგზავნა ვერ მოხერხდა"), 502
    return jsonify(ok=True)


def _attendance_settings_public(admin: bool) -> dict:
    """ადმინს ეძლევა სრული პარამეტრები (ოფისის კოორდინატი რედაქტირებისთვის),
    სხვას — მხოლოდ ის, რაც ინტერფეისს სჭირდება (კოორდინატი არა)."""
    s = crm_extras.attendance_settings()
    out = {
        "configured": s["configured"],
        "office_radius_meters": s["office_radius_meters"],
        "max_accuracy_meters": s["max_accuracy_meters"],
        "allow_outside_checkin": s["allow_outside_checkin"],
    }
    if admin:
        out.update({
            "office_name": s["office_name"],
            "office_latitude": s["office_latitude"],
            "office_longitude": s["office_longitude"],
        })
    return out


@app.get("/api/attendance/settings")
def api_attendance_settings_get():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    return jsonify(settings=_attendance_settings_public(True))


@app.post("/api/attendance/settings")
def api_attendance_settings_set():
    """ოფისის/ვერიფიკაციის პარამეტრები (მხოლოდ ადმინი). ინახება
    AppSettings-ში და მაშინვე მოქმედებს, restart არ სჭირდება."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    cleaned, bad = crm_extras.validate_settings_input(body)
    if bad:
        return jsonify(error=bad), 400
    who = "admin"
    for key, value in cleaned.items():
        sheets.set_app_setting(key, value, updated_by=who)
    _audit(agent, admin, "attendance_settings_update", "app_settings", "attendance",
           metadata={"keys": sorted(cleaned.keys())})
    return jsonify(ok=True, settings=_attendance_settings_public(True))


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

    if not admin:
        my_team = str(agent.get("team", "")).strip()
        target = next((q for q in sheets.get_questions() if str(q.get("question_id")) == str(question_id)), None)
        if not target or str(target.get("team", "")).strip() != my_team:
            return jsonify(error="მხოლოდ საკუთარი გუნდის კითხვაზე პასუხის გაცემა შეიძლება"), 403

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
    _audit(agent, admin, "dayoff_decide", "dayoff", request_id,
           metadata={"status": status, "agent_id": row.get("agent_id"), "date": row.get("date")})

    label = "✅ დამტკიცებულია" if status == "approved" else "❌ უარყოფილია"
    a2 = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("agent_id"))), None)
    if a2 and a2.get("telegram_chat_id"):
        _send_telegram_message(
            int(a2["telegram_chat_id"]),
            f"თქვენი Day off მოთხოვნა ({row.get('date')}) — {label}",
        )
    return jsonify(ok=True, row=row)


@app.get("/api/dayoff/mine")
def api_dayoff_mine():
    """აგენტის საკუთარი Day off მოთხოვნები (ისტორია) + თვის ჭერი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    rows = [r for r in sheets.get_dayoff_requests() if str(r.get("agent_id")) == str(agent["agent_id"])]
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    month_key = crm_time.local_today().strftime("%Y-%m")
    approved_now = sheets.approved_dayoffs_count_this_month(agent["agent_id"], month_key + "-01")
    return jsonify(rows=rows[:60], monthly_limit=config.DAYOFF_MONTHLY_LIMIT, approved_this_month=approved_now)


@app.post("/api/dayoff/request")
@rate_limited("bulk_notify")
def api_dayoff_request():
    """Day off მოთხოვნა Mini App-იდან — თარიღის არჩევით (<input type=date>).
    ძველი ბოტის /dayoff თავისუფალ ტექსტს იღებდა ("ხვალ", "15/09") და
    ასეთი ჩანაწერი ვერც ერთ ავტომატურ შემოწმებაში ვერ მონაწილეობდა —
    აქ თარიღი სერვერზე მკაცრად მოწმდება და ISO (YYYY-MM-DD) ფორმატით
    ინახება."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    if str(agent.get("active", "yes")).lower() == "no":
        return jsonify(error="თქვენი ანგარიში გამორთულია"), 403
    body = request.get_json(silent=True) or {}
    day = crm_time.parse_user_date(body.get("date", ""))
    reason = (body.get("reason") or "").strip()[:500]
    if not day:
        return jsonify(error="აირჩიეთ სწორი თარიღი"), 400
    today = crm_time.local_today()
    if day < today:
        return jsonify(error="გასული თარიღის დასვენება ვერ მოითხოვება"), 400
    if (day - today).days > 120:
        return jsonify(error="ძალიან შორეული თარიღია (მაქს. 120 დღე)"), 400
    day_str = day.strftime(crm_time.DATE_FMT)
    for r in sheets.get_dayoff_requests():
        if str(r.get("agent_id")) == str(agent["agent_id"]) \
                and str(r.get("status")) in ("pending", "approved") \
                and crm_time.parse_user_date(r.get("date", "")) == day:
            return jsonify(error="ამ თარიღზე მოთხოვნა უკვე არსებობს"), 409

    request_id = sheets.create_dayoff_request(agent["agent_id"], day_str, reason or "-")
    text = (
        f"🏖 Day off მოთხოვნა: {agent.get('name')}\n"
        f"თარიღი: {day_str}\nმიზეზი: {reason or '-'}"
    )
    buttons = {"inline_keyboard": [[
        {"text": "✅ დამტკიცება", "callback_data": f"do_ok:{request_id}"},
        {"text": "❌ უარყოფა", "callback_data": f"do_no:{request_id}"},
    ]]}
    for admin_id in config.ADMIN_CHAT_IDS:
        _send_telegram_message(admin_id, text, reply_markup=buttons)
    lead = _team_lead_for_team(agent.get("team")) if str(agent.get("role", "")).strip() != "team_lead" else None
    if lead and lead.get("telegram_chat_id") and int(lead["telegram_chat_id"]) not in config.ADMIN_CHAT_IDS:
        _send_telegram_message(
            int(lead["telegram_chat_id"]),
            text + "\n\nდასამტკიცებლად გახსენით Mini App → შვებულებები.",
        )
    return jsonify(ok=True, request_id=request_id, date=day_str)


# ------------------------------------------- კვირის რაიონების განაწილება
# მენეჯერი (თიმლიდერი — საკუთარი გუნდი; ადმინი — ყველა) ყოველ კვირას
# ანაწილებს რაიონებს აგენტებზე (მულტი-არჩევით), აგენტი კი თავის
# დაშბორდზე იმ კვირის განმავლობაში ხედავს და Telegram-ში იღებს
# შეტყობინებას. კვირა = ორშაბათიდან კვირამდე (თბილისის კალენდრით).

def _agent_districts_for(agent_id, week_start_str) -> list[str]:
    rows = sheets.get_district_assignments(week_start=week_start_str, agent_id=agent_id)
    return crm_extras.split_districts(rows[0].get("districts", "")) if rows else []


def _district_week_payload(agent: dict) -> dict:
    """აგენტის დაშბორდისთვის: ამ კვირის (და, თუ უკვე განაწილებულია,
    მომავალი კვირის) რაიონები."""
    this_week = crm_time.week_start()
    next_week = this_week + datetime.timedelta(days=7)
    ws_now = this_week.strftime(crm_time.DATE_FMT)
    ws_next = next_week.strftime(crm_time.DATE_FMT)
    return {
        "week_start": ws_now,
        "week_label": crm_extras.week_label(this_week),
        "districts": _agent_districts_for(agent["agent_id"], ws_now),
        "next_week_label": crm_extras.week_label(next_week),
        "next_districts": _agent_districts_for(agent["agent_id"], ws_next),
    }


@app.get("/api/districts")
def api_districts():
    """მენეჯერის ხედვა: არჩეული კვირის (`?week=` — ნებისმიერი თარიღი იმ
    კვირიდან) აგენტები და მათი უკვე მინიჭებული რაიონები + რაიონების
    კატალოგი (ჯგუფებად). ადმინს შეუძლია `?team=` ფილტრი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/ადმინისთვის"), 403
    day = crm_time.parse_user_date(request.args.get("week", "")) or crm_time.local_today()
    ws = crm_time.week_start(day)
    ws_str = ws.strftime(crm_time.DATE_FMT)
    all_agents = [a for a in sheets.get_agents() if crm_extras._is_active_agent(a)]
    if admin:
        team_filter = request.args.get("team") or None
    else:
        team_filter = str(agent.get("team", "")).strip()
        if not team_filter:
            return jsonify(error="ჯერ არ გაქვთ საკუთარი გუნდი მინიჭებული"), 400
    members = [a for a in all_agents if team_filter is None or str(a.get("team", "")).strip() == team_filter]
    assignments = {str(r.get("agent_id")): r for r in sheets.get_district_assignments(week_start=ws_str)}
    leads = {
        str(a.get("team", "")).strip(): a.get("name", "")
        for a in all_agents if str(a.get("role", "")).strip() == "team_lead"
    }
    rows = []
    for a in members:
        aid = str(a.get("agent_id"))
        t = str(a.get("team", "")).strip()
        rows.append({
            "agent_id": aid, "name": a.get("name"), "team": t,
            "team_label": f"{leads.get(t)}-ის გუნდი" if leads.get(t) else (t or "დაუნაწილებელი"),
            "role": a.get("role", "agent"),
            "districts": crm_extras.split_districts((assignments.get(aid) or {}).get("districts", "")),
            "assigned_by_name": (assignments.get(aid) or {}).get("assigned_by_name", ""),
            "updated_at": (assignments.get(aid) or {}).get("updated_at", ""),
        })
    rows.sort(key=lambda r: (r["team_label"], r["name"] or ""))
    teams = []
    if admin:
        seen = {}
        for a in all_agents:
            t = str(a.get("team", "")).strip()
            if t and t not in seen:
                seen[t] = f"{leads.get(t)}-ის გუნდი" if leads.get(t) else t
        teams = [{"team": k, "label": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1])]
    this_week = crm_time.week_start()
    return jsonify(
        week_start=ws_str, week_label=crm_extras.week_label(ws),
        is_current=(ws == this_week), is_past=(ws < this_week),
        catalog=crm_extras.districts_catalog(), agents=rows, teams=teams,
    )


@app.post("/api/districts/assign")
@rate_limited("bulk_notify")
def api_districts_assign():
    """body: {week, agent_ids:[...], districts:[...]} — ერთი ან რამდენიმე
    აგენტისთვის (მულტი-არჩევით) კვირის რაიონების ჩაწერა/გადაწერა
    (ცარიელი districts = გასუფთავება). თიმლიდერი მხოლოდ საკუთარი
    გუნდის აგენტებზე ანაწილებს (სერვერი ამოწმებს); წარსული კვირის
    შეცვლა არ შეიძლება. შეცვლილი აგენტი იღებს Telegram შეტყობინებას."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not (admin or _is_team_lead(agent)):
        return jsonify(error="მხოლოდ მენეჯერისთვის/ადმინისთვის"), 403
    body = request.get_json(silent=True) or {}
    day = crm_time.parse_user_date(body.get("week", "")) or crm_time.local_today()
    ws = crm_time.week_start(day)
    if ws < crm_time.week_start():
        return jsonify(error="გასული კვირის რაიონების შეცვლა არ შეიძლება"), 400
    agent_ids = _clean_id_list(body.get("agent_ids"), 100)
    raw = body.get("districts") if isinstance(body.get("districts"), list) else []
    districts = crm_extras.clean_districts(raw)
    if len(districts) != len({str(x).strip() for x in raw if str(x).strip()}):
        return jsonify(error="უცნობი რაიონი სიაში"), 400
    if not agent_ids:
        return jsonify(error="აირჩიეთ აგენტი"), 400

    agents_by_id = {str(a.get("agent_id")): a for a in sheets.get_agents()}
    my_team = str(agent.get("team", "")).strip() if not admin else None
    for aid in agent_ids:
        target = agents_by_id.get(aid)
        if not target or not crm_extras._is_active_agent(target):
            return jsonify(error="აგენტი ვერ მოიძებნა ან აღარაა აქტიური"), 400
        if not admin and (not my_team or str(target.get("team", "")).strip() != my_team):
            return jsonify(error="მხოლოდ საკუთარი გუნდის აგენტებზე შეგიძლიათ განაწილება"), 403

    ws_str = ws.strftime(crm_time.DATE_FMT)
    assigned_by = "admin" if admin else str(agent.get("agent_id"))
    assigned_by_name = "ადმინი" if admin else str(agent.get("name") or "")
    label = crm_extras.week_label(ws)
    changed = 0
    for aid in agent_ids:
        before = _agent_districts_for(aid, ws_str)
        sheets.set_district_assignment(ws_str, aid, districts, assigned_by, assigned_by_name)
        if before == districts:
            continue
        changed += 1
        chat = agents_by_id[aid].get("telegram_chat_id")
        if chat:
            if districts:
                msg = (
                    f"📍 ამ კვირის ({label}) განმავლობაში ხართ შემდეგი რაიონების "
                    f"მიმართულებით:\n{', '.join(districts)}\n\nგისურვებთ წარმატებას! 🍀"
                )
            else:
                msg = f"📍 ამ კვირის ({label}) რაიონების განაწილება გაუქმდა — დაგაზუსტებთ მენეჯერი."
            _send_telegram_message(int(chat), msg)
    _audit(agent, admin, "districts_assign", "district_assignment", ws_str,
           metadata={"agents": len(agent_ids), "changed": changed, "districts": districts})
    return jsonify(ok=True, changed=changed, total=len(agent_ids), week_start=ws_str)


@app.get("/api/districts/mine")
def api_districts_mine():
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not agent:
        return jsonify(error="მხოლოდ დარეგისტრირებული აგენტისთვის"), 403
    return jsonify(_district_week_payload(agent))


# --------------------------------------------------- internal (worker.py)
# MyHome სქრეპერის queue worker (home-automation რეპო, ცალკე, Windows
# კომპიუტერზე მომუშავე პროცესი) იძახებს ამ ორ endpoint-ს. ეს
# machine-to-machine გამოძახებაა (არა Mini App-იდან) — ამიტომ Telegram
# initData-ს მაგივრად საერთო გასაღები (Authorization: Bearer <key>).
# ცარიელი MYHOME_WORKER_API_KEY ნიშნავს, რომ ეს გამორთულია (404).

def _authed_worker():
    if not config.MYHOME_WORKER_API_KEY:
        return jsonify(error="ეს endpoint გამორთულია"), 404
    expected = f"Bearer {config.MYHOME_WORKER_API_KEY}"
    if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
        return jsonify(error="ავტორიზაცია ვერ დადასტურდა"), 401
    return None


@app.get("/internal/myhome-jobs/next")
@rate_limited("worker")
def internal_myhome_jobs_next():
    """worker.py ყოველ SCRAPER_POLL_INTERVAL წამში — ამ მენეჯერის
    (`?manager_label=`) უძველესი "QUEUED" job-ის დაკავება
    ("PROCESSING"-ში გადაყვანით, `?worker_id=`-ის ჩაწერით). job არაა →
    `row: null`. (Sheets-ზე დაკავება საუკეთესო ძალისხმევაა, იხ.
    sheets_gspread.claim_next_myhome_job.)"""
    err = _authed_worker()
    if err:
        return err
    manager_label = str(request.args.get("manager_label") or "").strip()
    if not manager_label:
        return jsonify(error="manager_label საჭიროა"), 400
    worker_id = str(request.args.get("worker_id") or "").strip()[:80]
    row = sheets.claim_next_myhome_job(manager_label, worker_id)
    if not row:
        return jsonify(row=None)
    sheets.add_audit_event("", "worker", "myhome_job_claimed", "myhome_job", row.get("job_id"),
                           row.get("job_id"), {"worker_id": worker_id, "manager_label": manager_label})
    agent = next(
        (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("agent_id"))),
        None,
    )
    if agent and agent.get("telegram_chat_id"):
        _send_telegram_message(
            int(agent["telegram_chat_id"]),
            f"⏳ MyHome ID {row.get('myhome_listing_id')} — მუშავდება...",
        )
    return jsonify(row=row)


_FINISH_HTTP = {"not_found": 404, "not_processing": 409, "wrong_worker": 409, "bad_status": 400}


@app.post("/internal/myhome-jobs/<job_id>/complete")
@rate_limited("worker")
def internal_myhome_jobs_complete(job_id):
    """worker.py-ს job-ის დამუშავების შედეგის ანგარიში
    (`{"status": "COMPLETED"|"FAILED", "worker_id": "...", "error_message": "...",
    "failure_stage": "preparing|payment|paid", "deal_type"/"address"/
    "district"/"city": "..." (წარმატებისას)}`).

    PHASE 1.5: მხოლოდ PROCESSING -> COMPLETED/FAILED, მხოლოდ დამკავებელი
    worker-იდან; განმეორებითი იგივე შედეგი idempotent-ია (200, `duplicate:
    true`, **Telegram-შეტყობინების გარეშე**). FAILED გადახდამდე ეტაპზე
    ავტომატურად იგეგმება ხელახლა (მაქს. MYHOME_JOB_MAX_RETRIES, backoff)."""
    err = _authed_worker()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    status = str(body.get("status") or "").strip().upper()
    if status not in ("COMPLETED", "FAILED"):
        return jsonify(error="status უნდა იყოს COMPLETED ან FAILED"), 400
    worker_id = str(body.get("worker_id") or "").strip()[:80]
    error_message = str(body.get("error_message") or "").strip()[:2000]
    res = sheets.finish_myhome_job(
        job_id, worker_id, status, error_message,
        deal_type=str(body.get("deal_type") or "").strip(),
        address=str(body.get("address") or "").strip(),
        district=str(body.get("district") or "").strip(),
        city=str(body.get("city") or "").strip(),
        failure_stage=str(body.get("failure_stage") or "").strip(),
    )
    if not res["ok"]:
        sheets.add_audit_event("", "worker", "myhome_job_finish_rejected", "myhome_job", job_id, job_id,
                               {"worker_id": worker_id, "status": status, "code": res["code"]}, "rejected")
        return jsonify(error="ოპერაცია უარყოფილია", code=res["code"]), _FINISH_HTTP.get(res["code"], 409)
    row = res["row"]
    if res["code"] == "duplicate":
        return jsonify(ok=True, duplicate=True, row=row)

    sheets.add_audit_event(
        "", "worker",
        "myhome_job_retry_scheduled" if res["retry_scheduled"] else f"myhome_job_{status.lower()}",
        "myhome_job", job_id, job_id,
        {"worker_id": worker_id, "retry_count": row.get("retry_count"),
         "failure_stage": row.get("failure_stage"), "next_retry_at": row.get("next_retry_at")},
        "ok" if status == "COMPLETED" else "failed",
    )
    agent = next(
        (a for a in sheets.get_agents() if str(a.get("agent_id")) == str(row.get("agent_id"))),
        None,
    )
    if agent and agent.get("telegram_chat_id"):
        listing = row.get("myhome_listing_id")
        if status == "COMPLETED":
            text = f"✅ MyHome ID {listing} — წარმატებით აიტვირთა."
        elif res["retry_scheduled"]:
            text = (f"⚠️ MyHome ID {listing} — დროებით ვერ აიტვირთა ({error_message or 'უცნობი მიზეზი'}). "
                    f"ავტომატურად გავიმეორებთ ({row.get('retry_count')}/{config.MYHOME_JOB_MAX_RETRIES}).")
        else:
            text = f"❌ MyHome ID {listing} — ვერ აიტვირთა. მიზეზი: {error_message or 'უცნობი'}"
        _send_telegram_message(int(agent["telegram_chat_id"]), text)
    return jsonify(ok=True, row=row, retry_scheduled=res["retry_scheduled"])


@app.post("/internal/myhome-jobs/<job_id>/stage")
@rate_limited("worker")
def internal_myhome_jobs_stage(job_id):
    """"გადახდის კარიბჭე": worker-ი გადახდამდე (`stage: "payment"`) და მის
    შემდეგ (`"paid"`) იძახებს. 200 = გადახდის დაწყება/გაგრძელება დაშვებულია;
    409 = job ამ worker-ს აღარ ეკუთვნის -> worker-მა გადახდა **არ უნდა დაიწყოს**
    (ორმაგი გადახდის დაცვა). ეტაპი job-ზე ინახება და stale-recovery-ს
    აჩერებს (გადახდილი job queue-ში არ ბრუნდება)."""
    err = _authed_worker()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    res = sheets.set_myhome_job_stage(job_id, str(body.get("worker_id") or "").strip()[:80],
                                      str(body.get("stage") or "").strip())
    if not res["ok"]:
        sheets.add_audit_event("", "worker", "myhome_job_stage_rejected", "myhome_job", job_id, job_id,
                               {"stage": body.get("stage"), "code": res["code"]}, "rejected")
        code = {"not_found": 404, "bad_stage": 400}.get(res["code"], 409)
        return jsonify(error="ოპერაცია უარყოფილია", code=res["code"]), code
    sheets.add_audit_event("", "worker", f"myhome_job_stage_{body.get('stage')}", "myhome_job", job_id, job_id,
                           {"worker_id": body.get("worker_id")})
    return jsonify(ok=True)


@app.post("/internal/worker/heartbeat")
@rate_limited("worker")
def internal_worker_heartbeat():
    """worker-ის სიცოცხლის ნიშანი: {worker_id, status, current_job_id, stage}."""
    err = _authed_worker()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    worker_id = str(body.get("worker_id") or "").strip()[:80]
    if not worker_id:
        return jsonify(error="worker_id საჭიროა"), 400
    row = sheets.record_worker_heartbeat(
        worker_id, str(body.get("status") or "online")[:20],
        str(body.get("current_job_id") or "")[:40], str(body.get("stage") or "")[:20],
    )
    return jsonify(ok=True, last_heartbeat=row["last_heartbeat"])


def worker_status_list() -> list[dict]:
    """heartbeat-ები + გამოთვლილი `online` (WORKER_HEARTBEAT_STALE_SECONDS)."""
    out = []
    for hb in sheets.get_worker_heartbeats():
        age = crm_time.seconds_since_utc_iso(hb.get("last_heartbeat"))
        online = age is not None and age <= config.WORKER_HEARTBEAT_STALE_SECONDS
        out.append({**hb, "online": online, "age_seconds": None if age is None else int(age)})
    return out


@app.get("/api/worker/status")
def api_worker_status():
    """worker-ების მდგომარეობა — მხოლოდ ადმინი."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not admin:
        return jsonify(error="მხოლოდ ადმინისთვის"), 403
    return jsonify(workers=worker_status_list(), stale_after_seconds=config.WORKER_HEARTBEAT_STALE_SECONDS)


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


def _photo_owner_report(filename: str) -> dict | None:
    """იმ რეპორტის პოვნა, რომლის file_id-შიც ეს ფოტოა მითითებული."""
    needle = f"uploads/reports/{filename}"
    for r in sheets.get_reports():
        if needle in str(r.get("file_id") or ""):
            return r
    return None


@app.get("/uploads/reports/<path:filename>")
@rate_limited("photo")
def uploaded_report_photo(filename):
    """კლიენტის რეპორტთან ატვირთული ფოტოს გაცემა — PHASE 1.5: **ავტორიზაცია
    სავალდებულოა** (initData სათაური; ფრონტენდი სურათს fetch-ით კითხულობს და
    blob URL-ით აჩვენებს). ფაილის სახელის ცოდნა აღარ კმარა.
    წვდომა: ადმინი — ყველა; თიმლიდერი — თავისი გუნდის რეპორტების;
    აგენტი — საკუთარი რეპორტის; რეპორტთან დაუკავშირებელი (ობოლი) ფაილი —
    მხოლოდ ადმინი. წაშლის endpoint არ არსებობს."""
    agent, admin, err = _authed_agent()
    if err:
        return err
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return jsonify(error="არასწორი ფაილი"), 400
    if not admin:
        report = _photo_owner_report(filename)
        allowed = False
        if report and agent:
            if _is_team_lead(agent):
                owner = next((a for a in sheets.get_agents()
                              if str(a.get("agent_id")) == str(report.get("agent_id"))), None)
                allowed = bool(owner) and str(owner.get("team", "")).strip() == str(agent.get("team", "")).strip() \
                    and bool(str(agent.get("team", "")).strip())
            else:
                allowed = str(report.get("agent_id")) == str(agent.get("agent_id"))
        if not allowed:
            return jsonify(error="ამ ფაილზე წვდომა არ გაქვთ"), 403
    resp = send_from_directory(UPLOADS_DIR, filename)
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def run():
    """ბლოკავს — bot.py იძახებს ცალკე thread-ში."""
    log.info("Mini App ვებ-სერვერი ეშვება პორტზე %s", config.PORT)
    app.run(host="0.0.0.0", port=config.PORT, threaded=True, use_reloader=False)
