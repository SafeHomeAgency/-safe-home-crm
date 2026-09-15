"""
იგივე საჯარო API, რაც sheets_gspread.py-ს აქვს (ყველა ფუნქციის სახელი,
არგუმენტები და დაბრუნების მნიშვნელობა ზუსტად იგივეა) — მაგრამ მონაცემები
ინახება PostgreSQL-ში, Google Sheets-ის ნაცვლად.

აქტიურდება მხოლოდ მაშინ, როცა config.DATA_BACKEND == "postgres" (იხ.
sheets.py). სანამ ეს არ დაყენდება, ეს ფაილი საერთოდ არ იტვირთება და
bot.py/webserver.py ძველებურად, Google Sheets-ზე მუშაობენ.

დიზაინის პრინციპი: სადაც ლოგიკა Sheets-სპეციფიკური არ იყო (rate-scoring,
დაშბორდის აწყობა, quota გამოთვლა, გრაფიკის შემოწმება) — კოდი სიტყვასიტყვით
აქედანაა აღებული sheets_gspread.py-დან, უცვლელად. იცვლება მხოლოდ
წაკითხვა/ჩაწერის ის ნაწილი, რომელიც აქამდე gspread-ს მიმართავდა.
"""

from __future__ import annotations

import datetime
import logging
import random
import threading
import uuid

import config
import db

log = logging.getLogger("safehome-crm-sheets-pg")

_lock = threading.RLock()

AGENTS_HEADERS = [
    "agent_id", "name", "phone", "telegram_username",
    "telegram_chat_id", "active", "registered_at", "team",
    "role", "internal_number",
]
TASKS_HEADERS = [
    "task_id", "title", "description", "assigned_to", "status",
    "priority", "due_date", "created_by", "created_at", "updated_at",
    "notified", "lead_type", "client_phone", "deal_type", "listing_id",
    "viewing_time", "assigned_to_name",
]
REPORTS_HEADERS = [
    "report_id", "agent_id", "client_phone", "actions", "notes",
    "file_id", "created_at", "agent_name", "quality_auto", "quality_manual", "rated_by",
]
DAYOFF_HEADERS = [
    "request_id", "agent_id", "date", "reason", "status",
    "created_at", "decided_at", "agent_name",
]
MEETINGS_HEADERS = [
    "meeting_id", "timestamp", "owner_phone", "myhome_link", "myhome_id",
    "ssge_link", "ssge_id", "condition", "client_phone", "district",
    "address", "meeting_date", "agent_id", "agent_name", "price",
    "percent", "time", "internal_number", "agent_phone", "team_leader",
]
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SCHEDULE_HEADERS = ["agent_id"] + WEEKDAY_KEYS + ["updated_at", "agent_name"]
ATTENDANCE_HEADERS = [
    "attendance_id", "agent_id", "date", "mode", "clock_in", "clock_out",
    "count_submitted", "agent_name", "site_count", "myhome_count", "ssge_count",
]
WARNINGS_HEADERS = ["warning_id", "agent_id", "type", "detail", "created_at", "agent_name"]
SHIFT_SWAPS_HEADERS = [
    "swap_id", "agent_id", "agent_name", "request_type", "from_mode", "to_mode",
    "target_agent_id", "target_agent_name", "swap_date", "note", "status",
    "accepted_by", "accepted_by_name", "created_at", "decided_at", "decided_by",
]
EXCLUSIVES_HEADERS = [
    "exclusive_id", "agent_id", "agent_name", "contact_internal", "owner_phone",
    "property_type", "deal_type", "building_status", "condition", "location",
    "cadastral_code", "area", "rooms", "bedrooms", "floors_total", "floor_number",
    "project_type", "bathrooms", "balcony", "price", "percent", "notes",
    "photos", "status", "created_at",
]
QUESTIONS_HEADERS = [
    "question_id", "agent_id", "agent_name", "team", "text", "status",
    "answer", "answered_by", "created_at", "answered_at",
]
EXCLUSIVE_SHARES_HEADERS = [
    "share_id", "exclusive_id", "from_agent_id", "from_agent_name",
    "to_agent_id", "to_agent_name", "note", "created_at",
]


# --------------------------------------------------------------- helpers

def ensure_sheets() -> None:
    """იმავე დანიშნულებით, რაც Sheets-ვერსიაში — გამოიძახება ბოტის
    გაშვებისას. Postgres-ში ეს ცხრილების (idempotent) შექმნაა."""
    try:
        db.init_schema()
    except Exception:
        log.exception("Postgres სქემის მომზადება ვერ მოხერხდა")


def _insert(table: str, headers: list[str], values: list) -> None:
    cols = ", ".join(headers)
    placeholders = ", ".join(["%s"] * len(headers))
    db.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", tuple(values))


def _update_field(table: str, pk_col: str, pk_value: str, field: str, value) -> bool:
    rc = db.execute(f"UPDATE {table} SET {field} = %s WHERE {pk_col} = %s", (value, pk_value))
    return rc > 0


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _today_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _parse_dt(value: str):
    try:
        return datetime.datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return None


def _audit(action: str, entity_type: str, entity_id: str, actor_agent_id: str = "",
           old_value: dict | None = None, new_value: dict | None = None,
           source: str = "bot") -> None:
    """მსუბუქი, best-effort ჩანაწერი audit_log-ში — მაღალი რისკის
    მოქმედებებზე (აგენტის (დე)აქტივაცია, როლის შეცვლა, დამტკიცება/
    უარყოფა). არასდროს წყვეტს მთავარ ოპერაციას, თუ ჩაწერა ვერ
    მოხერხდა — მხოლოდ ლოგში ჩაიწერება."""
    import json
    try:
        db.execute(
            "INSERT INTO audit_log (actor_agent_id, action, entity_type, entity_id, "
            "old_value, new_value, source) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                actor_agent_id or "", action, entity_type, str(entity_id),
                json.dumps(old_value) if old_value is not None else None,
                json.dumps(new_value) if new_value is not None else None,
                source,
            ),
        )
    except Exception:
        log.exception("audit_log ჩანაწერი ვერ შეიქმნა (%s %s/%s)", action, entity_type, entity_id)


# ---------- Agents ----------

def get_agents() -> list[dict]:
    with _lock:
        return db.query_all("SELECT * FROM agents")


def find_agent_by_phone(phone: str) -> dict | None:
    phone = phone.strip().lstrip("+")
    for row in get_agents():
        if str(row.get("phone", "")).strip().lstrip("+") == phone:
            return row
    return None


def find_agent_by_chat_id(chat_id: int) -> dict | None:
    for row in get_agents():
        if str(row.get("telegram_chat_id", "")).strip() == str(chat_id):
            return row
    return None


def agent_name_by_id(agent_id: str) -> str:
    if not agent_id:
        return ""
    row = db.query_one("SELECT name FROM agents WHERE agent_id = %s", (str(agent_id),))
    return row["name"] if row else ""


def register_agent_chat_id(agent_id: str, chat_id: int, username: str):
    with _lock:
        rc = db.execute(
            "UPDATE agents SET telegram_chat_id = %s, telegram_username = %s WHERE agent_id = %s",
            (str(chat_id), username or "", agent_id),
        )
        return rc > 0


def add_agent(name: str, phone: str, team: str = "") -> str:
    with _lock:
        agent_id = uuid.uuid4().hex[:8]
        _insert("agents", AGENTS_HEADERS, [
            agent_id, name, phone, "", "", "yes", _now(), team, "agent", "",
        ])
        return agent_id


def set_agent_team(agent_id: str, team: str) -> bool:
    with _lock:
        ok = _update_field("agents", "agent_id", agent_id, "team", team)
    if ok:
        _audit("set_agent_team", "agent", agent_id, new_value={"team": team})
    return ok


def set_agent_active(agent_id: str, value: str) -> bool:
    with _lock:
        ok = _update_field("agents", "agent_id", agent_id, "active", value)
    if ok:
        _audit("set_agent_active", "agent", agent_id, new_value={"active": value})
    return ok


def set_agent_role(agent_id: str, role: str) -> bool:
    with _lock:
        ok = _update_field("agents", "agent_id", agent_id, "role", role)
    if ok:
        _audit("set_agent_role", "agent", agent_id, new_value={"role": role})
    return ok


def set_agent_internal_number(agent_id: str, number: str) -> bool:
    with _lock:
        return _update_field("agents", "agent_id", agent_id, "internal_number", number)


def find_agent_by_internal_number(number: str) -> dict | None:
    number = str(number).strip()
    for a in get_agents():
        if str(a.get("internal_number", "")).strip() == number and number:
            return a
    return None


def swap_internal_numbers(agent_id_a: str, agent_id_b: str) -> bool:
    with _lock:
        a = db.query_one("SELECT internal_number FROM agents WHERE agent_id = %s", (agent_id_a,))
        b = db.query_one("SELECT internal_number FROM agents WHERE agent_id = %s", (agent_id_b,))
        if a is None or b is None:
            return False
        db.execute("UPDATE agents SET internal_number = %s WHERE agent_id = %s",
                   (b["internal_number"], agent_id_a))
        db.execute("UPDATE agents SET internal_number = %s WHERE agent_id = %s",
                   (a["internal_number"], agent_id_b))
        return True


# ---------- Tasks ----------

def get_tasks() -> list[dict]:
    with _lock:
        return db.query_all("SELECT * FROM tasks")


def get_tasks_for_agent(agent_id: str, only_open: bool = True) -> list[dict]:
    tasks = [t for t in get_tasks() if str(t.get("assigned_to")) == str(agent_id)]
    if only_open:
        tasks = [t for t in tasks if t.get("status") != "Done"]
    return tasks


def create_task(title: str, description: str, assigned_to: str,
                 priority: str, due_date: str, created_by: str,
                 lead_type: str = "", client_phone: str = "",
                 deal_type: str = "", listing_id: str = "",
                 viewing_time: str = "") -> str:
    with _lock:
        task_id = uuid.uuid4().hex[:8]
        now = _now()
        _insert("tasks", TASKS_HEADERS, [
            task_id, title, description, assigned_to, "New",
            priority, due_date, created_by, now, now, "no",
            lead_type, client_phone, deal_type, listing_id, viewing_time,
            agent_name_by_id(assigned_to),
        ])
        return task_id


def mark_task_done(task_id: str) -> bool:
    with _lock:
        rc = db.execute(
            "UPDATE tasks SET status = %s, updated_at = %s WHERE task_id = %s",
            ("Done", _now(), task_id),
        )
        return rc > 0


def mark_task_notified(task_id: str):
    with _lock:
        db.execute("UPDATE tasks SET notified = %s WHERE task_id = %s", ("yes", task_id))


def reassign_task(task_id: str, new_agent_id: str, actor_agent_id: str = "") -> dict | None:
    """დავალების/კლიენტის სხვა აგენტზე გადაბარება (ადმინი — ნებისმიერ
    აგენტზე; თიმლიდერი — მხოლოდ საკუთარ გუნდში, კურატორის პრინციპით).
    `notified`-ს ისევ "no"-ზე აბრუნებს, რომ არსებული ფონური
    შეტყობინების job-მა ახალ აგენტს ავტომატურად აცნობოს."""
    with _lock:
        old = db.query_one("SELECT assigned_to, assigned_to_name FROM tasks WHERE task_id = %s", (task_id,))
        if old is None:
            return None
        db.execute(
            "UPDATE tasks SET assigned_to = %s, assigned_to_name = %s, updated_at = %s, "
            "notified = %s WHERE task_id = %s",
            (new_agent_id, agent_name_by_id(new_agent_id), _now(), "no", task_id),
        )
        row = db.query_one("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
    _audit(
        "reassign_task", "task", task_id, actor_agent_id=actor_agent_id,
        old_value={"assigned_to": old.get("assigned_to"), "assigned_to_name": old.get("assigned_to_name")},
        new_value={"assigned_to": new_agent_id, "assigned_to_name": agent_name_by_id(new_agent_id)},
    )
    return row


def get_unnotified_tasks() -> list[dict]:
    return [
        t for t in get_tasks()
        if str(t.get("notified", "")).strip().lower() != "yes"
        and t.get("assigned_to")
    ]


# ---------- Performance / assignment (სიტყვასიტყვით იგივეა, რაც Sheets-ვერსიაში) ----------

def get_agent_performance(days: int = 30) -> dict:
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    stats: dict[str, dict] = {}

    for t in get_tasks():
        created = _parse_dt(t.get("created_at", ""))
        if not created or created < cutoff:
            continue
        agent_id = str(t.get("assigned_to") or "").strip()
        if not agent_id:
            continue
        s = stats.setdefault(agent_id, {"assigned": 0, "on_time": 0})
        s["assigned"] += 1
        if str(t.get("status")) == "Done":
            updated = _parse_dt(t.get("updated_at", ""))
            if updated and (updated - created) <= datetime.timedelta(hours=24):
                s["on_time"] += 1

    for s in stats.values():
        s["rate"] = (s["on_time"] / s["assigned"]) if s["assigned"] else None

    return stats


def pick_agent_for_priority(priority: str, days: int = 30, team: str | None = None) -> str | None:
    """იხ. sheets_gspread.py-ის იგივე ფუნქციის დოკუმენტაცია — `team`
    პარამეტრი კანდიდატებს ზღუდავს ერთ გუნდზე (თიმლიდერისთვის)."""
    agents = [
        a for a in get_agents()
        if str(a.get("active", "")).strip().lower() != "no"
        and str(a.get("telegram_chat_id", "")).strip()
        and agent_available_now(a["agent_id"])
        and (team is None or str(a.get("team", "")).strip() == team.strip())
    ]
    if not agents:
        return None

    perf = get_agent_performance(days)

    def rate(agent_id: str) -> float:
        s = perf.get(agent_id)
        if not s or not s["assigned"] or s["rate"] is None:
            return 0.0
        return s["rate"]

    scored = [(a["agent_id"], rate(a["agent_id"])) for a in agents]

    if priority == "მაღალი":
        scored.sort(key=lambda x: x[1], reverse=True)
    elif priority == "საშუალო":
        scored.sort(key=lambda x: x[1])
    else:
        random.shuffle(scored)

    return scored[0][0]


# ---------- Client reports ----------

def _auto_quality(client_phone: str, actions: str, notes: str, file_id: str) -> int:
    score = 1
    if client_phone.strip():
        score += 1
    if actions.strip():
        score += 1
    if notes.strip() and len(notes.strip()) >= 5:
        score += 1
    if file_id.strip():
        score += 1
    return min(score, 5)


def create_report(agent_id: str, client_phone: str, actions: str,
                   notes: str = "", file_id: str = "") -> str:
    with _lock:
        report_id = uuid.uuid4().hex[:8]
        auto_q = _auto_quality(client_phone, actions, notes, file_id)
        _insert("reports", REPORTS_HEADERS, [
            report_id, agent_id, client_phone, actions, notes,
            file_id, _now(), agent_name_by_id(agent_id), auto_q, "", "",
        ])
        return report_id


def set_report_quality(report_id: str, score: int, rated_by: str) -> bool:
    with _lock:
        rc = db.execute(
            "UPDATE reports SET quality_manual = %s, rated_by = %s WHERE report_id = %s",
            (score, rated_by, report_id),
        )
        return rc > 0


def get_reports(agent_id: str | None = None, client_phone: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM reports")
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if client_phone:
        needle = client_phone.strip().lstrip("+")
        rows = [
            r for r in rows
            if str(r.get("client_phone", "")).strip().lstrip("+") == needle
        ]
    return rows


def get_client_history(client_phone: str) -> dict:
    needle = client_phone.strip().lstrip("+")
    tasks = [
        t for t in get_tasks()
        if str(t.get("client_phone", "")).strip().lstrip("+") == needle
    ]
    reports = get_reports(client_phone=client_phone)
    meetings = get_meetings(client_phone=client_phone)
    return {"tasks": tasks, "reports": reports, "meetings": meetings}


# ---------- Day off ----------

def create_dayoff_request(agent_id: str, date: str, reason: str) -> str:
    with _lock:
        request_id = uuid.uuid4().hex[:8]
        _insert("dayoff", DAYOFF_HEADERS, [
            request_id, agent_id, date, reason, "pending", _now(), "",
            agent_name_by_id(agent_id),
        ])
        return request_id


def get_dayoff_requests(status: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM dayoff")
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


def decide_dayoff(request_id: str, status: str) -> dict | None:
    with _lock:
        rc = db.execute(
            "UPDATE dayoff SET status = %s, decided_at = %s WHERE request_id = %s",
            (status, _now(), request_id),
        )
        if not rc:
            return None
        row = db.query_one("SELECT * FROM dayoff WHERE request_id = %s", (request_id,))
    _audit("decide_dayoff", "dayoff", request_id, new_value={"status": status})
    return row


# ---------- შეხვედრები ----------

def create_meeting(fields: dict) -> str:
    with _lock:
        meeting_id = uuid.uuid4().hex[:8]
        values = []
        for h in MEETINGS_HEADERS:
            if h == "meeting_id":
                values.append(meeting_id)
            elif h == "timestamp":
                values.append(_now())
            else:
                values.append(fields.get(h, ""))
        _insert("meetings", MEETINGS_HEADERS, values)
        return meeting_id


def get_meetings(agent_id: str | None = None, client_phone: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM meetings")
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if client_phone:
        needle = client_phone.strip().lstrip("+")
        rows = [
            r for r in rows
            if str(r.get("client_phone", "")).strip().lstrip("+") == needle
        ]
    return rows


# ---------- გრაფიკი + გამოცხადება ----------

def set_agent_schedule(agent_id: str, pattern: dict) -> None:
    with _lock:
        existing = db.query_one("SELECT agent_id FROM schedule WHERE agent_id = %s", (agent_id,))
        values = [pattern.get(k, "off") for k in WEEKDAY_KEYS]
        if existing:
            sets = ", ".join(f"{k} = %s" for k in WEEKDAY_KEYS)
            db.execute(
                f"UPDATE schedule SET {sets}, updated_at = %s, agent_name = %s WHERE agent_id = %s",
                (*values, _now(), agent_name_by_id(agent_id), agent_id),
            )
        else:
            _insert("schedule", SCHEDULE_HEADERS,
                    [agent_id] + values + [_now(), agent_name_by_id(agent_id)])


def get_agent_schedule(agent_id: str) -> dict | None:
    with _lock:
        return db.query_one("SELECT * FROM schedule WHERE agent_id = %s", (str(agent_id),))


def get_today_mode(agent_id: str) -> str:
    sched = get_agent_schedule(agent_id)
    if not sched:
        return "off"
    key = WEEKDAY_KEYS[datetime.datetime.now().weekday()]
    return str(sched.get(key) or "off")


def clock_in(agent_id: str) -> str:
    with _lock:
        today = _today_str()
        row = db.query_one(
            "SELECT * FROM attendance WHERE agent_id = %s AND date = %s", (agent_id, today),
        )
        if row:
            if row.get("clock_in"):
                return "already"
            db.execute(
                "UPDATE attendance SET clock_in = %s WHERE attendance_id = %s",
                (_now(), row["attendance_id"]),
            )
            return "ok"
        mode = get_today_mode(agent_id)
        attendance_id = uuid.uuid4().hex[:8]
        _insert("attendance", ATTENDANCE_HEADERS, [
            attendance_id, agent_id, today, mode, _now(), "", "",
            agent_name_by_id(agent_id), "", "", "",
        ])
        return "ok"


def clock_out(agent_id: str) -> str:
    with _lock:
        today = _today_str()
        row = db.query_one(
            "SELECT * FROM attendance WHERE agent_id = %s AND date = %s", (agent_id, today),
        )
        if not row or not row.get("clock_in"):
            return "not_in"
        db.execute(
            "UPDATE attendance SET clock_out = %s WHERE attendance_id = %s",
            (_now(), row["attendance_id"]),
        )
        return "ok"


def get_today_attendance(agent_id: str) -> dict | None:
    today = _today_str()
    with _lock:
        return db.query_one(
            "SELECT * FROM attendance WHERE agent_id = %s AND date = %s", (str(agent_id), today),
        )


def set_daily_count(agent_id: str, count: int, site: int | None = None,
                     myhome: int | None = None, ssge: int | None = None) -> bool:
    today = _today_str()
    with _lock:
        row = db.query_one(
            "SELECT attendance_id FROM attendance WHERE agent_id = %s AND date = %s",
            (agent_id, today),
        )
        if not row:
            return False
        db.execute(
            "UPDATE attendance SET count_submitted = %s WHERE attendance_id = %s",
            (count, row["attendance_id"]),
        )
        if site is not None:
            db.execute("UPDATE attendance SET site_count = %s WHERE attendance_id = %s",
                       (site, row["attendance_id"]))
        if myhome is not None:
            db.execute("UPDATE attendance SET myhome_count = %s WHERE attendance_id = %s",
                       (myhome, row["attendance_id"]))
        if ssge is not None:
            db.execute("UPDATE attendance SET ssge_count = %s WHERE attendance_id = %s",
                       (ssge, row["attendance_id"]))
        return True


def get_today_attendance_all() -> list[dict]:
    today = _today_str()
    with _lock:
        return db.query_all("SELECT * FROM attendance WHERE date = %s", (today,))


def is_clocked_in_today(agent_id: str) -> bool:
    r = get_today_attendance(agent_id)
    return bool(r and r.get("clock_in") and not r.get("clock_out"))


def agent_available_now(agent_id: str) -> bool:
    sched = get_agent_schedule(agent_id)
    if not sched:
        return True
    mode = str(sched.get(WEEKDAY_KEYS[datetime.datetime.now().weekday()]) or "off")
    if mode == "off":
        return False
    return is_clocked_in_today(agent_id)


# ---------- გაფრთხილებები ----------

def has_warning_today(agent_id: str, type_: str) -> bool:
    today = _today_str()
    with _lock:
        rows = db.query_all(
            "SELECT * FROM warnings WHERE agent_id = %s AND type = %s", (agent_id, type_),
        )
    return any(str(r.get("created_at", "")).startswith(today) for r in rows)


def get_warnings(agent_id: str | None = None, days: int | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM warnings")
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if days:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        rows = [r for r in rows if (_parse_dt(r.get("created_at", "")) or cutoff) >= cutoff]
    return rows


def add_warning(agent_id: str, type_: str, detail: str = "") -> dict:
    with _lock:
        warning_id = uuid.uuid4().hex[:8]
        _insert("warnings", WARNINGS_HEADERS,
                [warning_id, agent_id, type_, detail, _now(), agent_name_by_id(agent_id)])

    count = len(get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS))
    deactivated = False
    if count >= config.WARNING_LIMIT:
        set_agent_active(agent_id, "no")
        deactivated = True
        _audit("auto_deactivate_on_warnings", "agent", agent_id,
               new_value={"warning_count": count, "type": type_})
    return {"warning_id": warning_id, "count": count, "deactivated": deactivated}


# ---------- სმენების/ნომრის გაცვლა ----------

def _weekday_key_for_date(date_str: str) -> str | None:
    try:
        d = datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return WEEKDAY_KEYS[d.weekday()]
    except (ValueError, AttributeError):
        return None


def count_swap_requests_this_month(agent_id: str) -> int:
    month_str = datetime.datetime.now().strftime("%Y-%m")
    return sum(
        1 for r in get_shift_swaps(agent_id=agent_id)
        if str(r.get("created_at", "")).startswith(month_str) and str(r.get("agent_id")) == str(agent_id)
    )


def create_shift_swap_request(agent_id: str, request_type: str, swap_date: str,
                               from_mode: str = "", to_mode: str = "",
                               target_agent_id: str = "", note: str = "") -> str:
    with _lock:
        swap_id = uuid.uuid4().hex[:8]
        status = "pending_manager" if request_type == "change_mode" else "pending_peer"
        target_name = agent_name_by_id(target_agent_id) if target_agent_id else ""
        _insert("shift_swaps", SHIFT_SWAPS_HEADERS, [
            swap_id, agent_id, agent_name_by_id(agent_id), request_type, from_mode, to_mode,
            target_agent_id, target_name, swap_date, note, status,
            "", "", _now(), "", "",
        ])
        return swap_id


def get_shift_swaps(agent_id: str | None = None, status: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM shift_swaps")
    if agent_id:
        rows = [
            r for r in rows
            if str(r.get("agent_id")) == str(agent_id) or str(r.get("target_agent_id")) == str(agent_id)
        ]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


def accept_shift_swap(swap_id: str, accepting_agent_id: str) -> dict | None:
    with _lock:
        row = db.query_one("SELECT * FROM shift_swaps WHERE swap_id = %s", (swap_id,))
        if not row or row.get("status") != "pending_peer":
            return None
        name = agent_name_by_id(accepting_agent_id)
        if row.get("request_type") == "open_swap" and not row.get("target_agent_id"):
            db.execute(
                "UPDATE shift_swaps SET target_agent_id = %s, target_agent_name = %s WHERE swap_id = %s",
                (accepting_agent_id, name, swap_id),
            )
        db.execute(
            "UPDATE shift_swaps SET accepted_by = %s, accepted_by_name = %s, status = %s "
            "WHERE swap_id = %s",
            (accepting_agent_id, name, "pending_manager", swap_id),
        )
        return db.query_one("SELECT * FROM shift_swaps WHERE swap_id = %s", (swap_id,))


def decide_shift_swap(swap_id: str, status: str, decided_by: str) -> dict | None:
    with _lock:
        rc = db.execute(
            "UPDATE shift_swaps SET status = %s, decided_at = %s, decided_by = %s WHERE swap_id = %s",
            (status, _now(), decided_by, swap_id),
        )
        if not rc:
            return None
        row = db.query_one("SELECT * FROM shift_swaps WHERE swap_id = %s", (swap_id,))

    _audit("decide_shift_swap", "shift_swap", swap_id, new_value={"status": status})

    if status == "approved":
        wk = _weekday_key_for_date(row.get("swap_date", ""))
        if wk:
            if row.get("request_type") == "change_mode":
                sched = get_agent_schedule(row["agent_id"]) or {}
                pattern = {k: str(sched.get(k) or "off") for k in WEEKDAY_KEYS}
                pattern[wk] = row.get("to_mode") or "off"
                set_agent_schedule(row["agent_id"], pattern)
            elif row.get("target_agent_id"):
                sched_a = get_agent_schedule(row["agent_id"]) or {}
                sched_b = get_agent_schedule(row["target_agent_id"]) or {}
                mode_a = str(sched_a.get(wk) or "off")
                mode_b = str(sched_b.get(wk) or "off")
                pat_a = {k: str(sched_a.get(k) or "off") for k in WEEKDAY_KEYS}
                pat_b = {k: str(sched_b.get(k) or "off") for k in WEEKDAY_KEYS}
                pat_a[wk] = mode_b
                pat_b[wk] = mode_a
                set_agent_schedule(row["agent_id"], pat_a)
                set_agent_schedule(row["target_agent_id"], pat_b)
    return row


# ---------- ექსკლუზივები ----------

def create_exclusive(agent_id: str, fields: dict) -> str:
    with _lock:
        exclusive_id = uuid.uuid4().hex[:8]
        values = []
        for h in EXCLUSIVES_HEADERS:
            if h == "exclusive_id":
                values.append(exclusive_id)
            elif h == "agent_id":
                values.append(agent_id)
            elif h == "agent_name":
                values.append(agent_name_by_id(agent_id))
            elif h == "created_at":
                values.append(_now())
            elif h == "status":
                values.append(fields.get("status") or "active")
            else:
                values.append(fields.get(h, ""))
        _insert("exclusives", EXCLUSIVES_HEADERS, values)
        return exclusive_id


def get_exclusives(agent_id: str | None = None, status: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM exclusives")
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


def find_exclusive(exclusive_id: str) -> dict | None:
    with _lock:
        return db.query_one("SELECT * FROM exclusives WHERE exclusive_id = %s", (str(exclusive_id),))


# ---------- ექსკლუზივის გაზიარება ----------

def share_exclusive(exclusive_id: str, from_agent_id: str, to_agent_id: str, note: str = "") -> dict | None:
    exclusive = find_exclusive(exclusive_id)
    if not exclusive:
        return None
    with _lock:
        share_id = uuid.uuid4().hex[:8]
        _insert("exclusive_shares", EXCLUSIVE_SHARES_HEADERS, [
            share_id, exclusive_id, from_agent_id, agent_name_by_id(from_agent_id),
            to_agent_id, agent_name_by_id(to_agent_id), note, _now(),
        ])
    return {
        "share_id": share_id, "exclusive_id": exclusive_id,
        "from_agent_id": from_agent_id, "to_agent_id": to_agent_id,
        "exclusive": exclusive,
    }


def get_exclusive_shares(exclusive_id: str | None = None, agent_id: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM exclusive_shares")
    if exclusive_id:
        rows = [r for r in rows if str(r.get("exclusive_id")) == str(exclusive_id)]
    if agent_id:
        rows = [
            r for r in rows
            if str(r.get("from_agent_id")) == str(agent_id) or str(r.get("to_agent_id")) == str(agent_id)
        ]
    return rows


def collaboration_count(agent_id: str) -> int:
    return len(get_exclusive_shares(agent_id=agent_id))


# ---------- კითხვა მენეჯერს ----------

def create_question(agent_id: str, text: str) -> str:
    with _lock:
        question_id = uuid.uuid4().hex[:8]
        agent = next((a for a in get_agents() if str(a.get("agent_id")) == str(agent_id)), None)
        team = agent.get("team", "") if agent else ""
        _insert("questions", QUESTIONS_HEADERS, [
            question_id, agent_id, agent_name_by_id(agent_id), team, text,
            "open", "", "", _now(), "",
        ])
        return question_id


def get_questions(agent_id: str | None = None, team: str | None = None,
                   status: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM questions")
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if team:
        rows = [r for r in rows if str(r.get("team", "")).strip() == team.strip()]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


def answer_question(question_id: str, answer: str, answered_by: str) -> dict | None:
    with _lock:
        rc = db.execute(
            "UPDATE questions SET status = %s, answer = %s, answered_by = %s, answered_at = %s "
            "WHERE question_id = %s",
            ("answered", answer, answered_by, _now(), question_id),
        )
        if not rc:
            return None
        return db.query_one("SELECT * FROM questions WHERE question_id = %s", (question_id,))


# ---------- Mini App დაშბორდის მონაცემები (სიტყვასიტყვით იგივეა) ----------

def quota_for_mode(mode: str) -> int | None:
    if mode == "online":
        return config.ONLINE_DAILY_QUOTA
    if mode in ("office_morning", "office_evening"):
        return config.OFFICE_DAILY_QUOTA
    return None


def client_counts(agent_id: str) -> dict:
    today_str = _today_str()
    agent_tasks = [t for t in get_tasks() if str(t.get("assigned_to")) == str(agent_id)]
    today_count = sum(1 for t in agent_tasks if str(t.get("created_at", "")).startswith(today_str))
    return {"today": today_count, "total": len(agent_tasks)}


def get_agent_dashboard(agent_id: str, days: int = 30) -> dict | None:
    all_agents = get_agents()
    agent = next((a for a in all_agents if str(a.get("agent_id")) == str(agent_id)), None)
    if not agent:
        return None
    att = get_today_attendance(agent_id) or {}
    mode = get_today_mode(agent_id)
    perf = get_agent_performance(days).get(str(agent_id), {"assigned": 0, "on_time": 0, "rate": None})
    warns = get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS)
    sched = get_agent_schedule(agent_id) or {}
    tasks = get_tasks_for_agent(agent_id, only_open=True)
    meetings = get_meetings(agent_id=agent_id)[-5:][::-1]
    clients = client_counts(agent_id)

    # "პირამიდის" სტრუქტურა: ჩვეულებრივმა აგენტმა (არა-თიმლიდერმა) Mini
    # App-ში უნდა იცოდეს, ვინაა მისი მენეჯერი — ვეძებთ იმავე `team`
    # მნიშვნელობის მქონე თიმლიდერს.
    manager_name = None
    if str(agent.get("role", "")).strip() != "team_lead":
        team_val = str(agent.get("team", "")).strip()
        if team_val:
            lead = next(
                (a for a in all_agents
                 if str(a.get("role", "")).strip() == "team_lead"
                 and str(a.get("team", "")).strip() == team_val),
                None,
            )
            if lead:
                manager_name = lead.get("name")

    return {
        "agent": {
            "agent_id": agent.get("agent_id", ""),
            "name": agent.get("name", ""),
            "phone": agent.get("phone", ""),
            "team": agent.get("team", ""),
            "active": agent.get("active", "yes"),
            "manager_name": manager_name,
        },
        "today": {
            "mode": mode,
            "clock_in": att.get("clock_in", ""),
            "clock_out": att.get("clock_out", ""),
            "count_submitted": att.get("count_submitted", ""),
            "site_count": att.get("site_count", ""),
            "myhome_count": att.get("myhome_count", ""),
            "ssge_count": att.get("ssge_count", ""),
            "quota": quota_for_mode(mode),
        },
        "clients": clients,
        "schedule": {k: str(sched.get(k) or "off") for k in WEEKDAY_KEYS},
        "performance": {
            "assigned": perf.get("assigned", 0),
            "on_time": perf.get("on_time", 0),
            "rate": perf.get("rate"),
        },
        "warnings": {
            "count": len(warns),
            "limit": config.WARNING_LIMIT,
            "recent": warns[-5:][::-1],
        },
        "tasks": tasks[:20],
        "meetings": meetings,
    }


def get_admin_dashboard(team: str | None = None, days: int = 30) -> dict:
    """იხ. sheets_gspread.py-ის იგივე ფუნქციის დოკუმენტაცია — ლოგიკა
    ორივე backend-ში იდენტურია (გათავისუფლებული აგენტები გამორიცხულია
    გუნდის/რეიტინგის ხედვიდან, `days` — პერიოდის ფილტრისთვის)."""
    all_agents = get_agents()
    if team:
        all_agents = [a for a in all_agents if str(a.get("team", "")).strip() == team.strip()]
    agents = [a for a in all_agents if str(a.get("active", "yes")).strip().lower() != "no"]
    perf = get_agent_performance(days)
    today_att = {str(r.get("agent_id")): r for r in get_today_attendance_all()}

    team_rows = []
    total_submitted = 0
    total_quota_target = 0
    clocked_in_count = 0
    quota_missed_count = 0
    clients_today_total = 0
    clients_all_total = 0
    for a in agents:
        aid = a.get("agent_id")
        mode = get_today_mode(aid)
        quota = quota_for_mode(mode)
        att = today_att.get(str(aid), {})
        clocked = bool(att.get("clock_in")) and not att.get("clock_out")
        if clocked:
            clocked_in_count += 1
        try:
            count_submitted = int(att.get("count_submitted") or 0)
        except (TypeError, ValueError):
            count_submitted = 0
        if quota:
            total_quota_target += quota
            total_submitted += count_submitted
            if att.get("clock_out") and count_submitted < quota:
                quota_missed_count += 1
        w = len(get_warnings(agent_id=aid, days=config.WARNING_WINDOW_DAYS))
        p = perf.get(str(aid), {})
        c = client_counts(aid)
        clients_today_total += c["today"]
        clients_all_total += c["total"]
        team_rows.append({
            "agent_id": aid,
            "name": a.get("name", ""),
            "team": a.get("team", ""),
            "role": a.get("role", "agent"),
            "active": a.get("active", "yes"),
            "mode": mode,
            "clocked_in": clocked,
            "count_submitted": att.get("count_submitted", ""),
            "site_count": att.get("site_count", ""),
            "myhome_count": att.get("myhome_count", ""),
            "ssge_count": att.get("ssge_count", ""),
            "quota": quota,
            "warnings": w,
            "assigned": p.get("assigned", 0),
            "rate": p.get("rate"),
            "clients_today": c["today"],
            "clients_total": c["total"],
            "collaboration": collaboration_count(aid),
        })

    ranking = sorted(
        [t for t in team_rows if t["rate"] is not None and t["assigned"]],
        key=lambda t: t["rate"], reverse=True,
    )[:10]
    team_agent_ids = {str(a.get("agent_id")) for a in agents}
    pending_dayoffs = [
        r for r in get_dayoff_requests(status="pending")
        if not team or str(r.get("agent_id")) in team_agent_ids
    ]
    recent_warnings = [
        w for w in sorted(get_warnings(), key=lambda w: str(w.get("created_at", "")), reverse=True)
        if not team or str(w.get("agent_id")) in team_agent_ids
    ][:10]

    return {
        "team": team_rows,
        "ranking": ranking,
        "pending_dayoffs": pending_dayoffs,
        "recent_warnings": recent_warnings,
        "summary": {
            "agents_total": len(all_agents),
            "active_total": len(agents),
            "inactive_total": len(all_agents) - len(agents),
            "clocked_in": clocked_in_count,
            "total_submitted": total_submitted,
            "total_quota_target": total_quota_target,
            "quota_missed": quota_missed_count,
            "pending_dayoffs": len(pending_dayoffs),
            "clients_today": clients_today_total,
            "clients_total": clients_all_total,
        },
    }
