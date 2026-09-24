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
    "viewing_time", "assigned_to_name", "seen", "seen_at",
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
WARNINGS_HEADERS = [
    "warning_id", "agent_id", "type", "detail", "created_at", "agent_name",
    "status", "dismiss_reason", "dismiss_requested_by", "dismiss_requested_by_name",
    "dismiss_requested_at", "dismiss_decided_by", "dismiss_decided_at",
]
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
AGENT_REQUESTS_HEADERS = [
    "request_id", "kind", "requested_by", "requested_by_name", "team",
    "target_agent_id", "name", "phone", "reason", "status",
    "created_at", "decided_at", "decided_by",
]
MYHOME_JOBS_HEADERS = [
    "job_id", "agent_id", "agent_name", "team", "manager_label",
    "myhome_listing_id", "cooperation_percent", "final_price", "notes",
    "status", "error_message", "retry_count",
    "created_at", "started_at", "completed_at",
]
MYHOME_ACCOUNTS_HEADERS = ["team", "manager_label", "manager_name", "updated_at"]


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


def delete_agent(agent_id: str) -> bool:
    """აგენტის ჩანაწერის სრული, შეუქცევადი წაშლა (არა უბრალო
    დეაქტივაცია) — აღარსად ჩანს, "აგენტების მართვა" ტაბშიც კი. მხოლოდ
    agents/schedule ცხრილებიდან შლის; ისტორიული ჩანაწერები (tasks/
    reports/meetings/warnings/attendance/shift_swaps) უცვლელად რჩება —
    მათში აგენტის სახელი ცალკეა შენახული (agent_name/assigned_to_name),
    ასე რომ KPI/ისტორია არ ზიანდება, თუმცა agent_id-ით ცოცხალ
    ჩანაწერზე მიბმა (მაგ. "მენეჯერის" ბმული) მას შემდეგ ვეღარ
    გაიმართება."""
    with _lock:
        row = db.query_one("SELECT * FROM agents WHERE agent_id = %s", (agent_id,))
        if not row:
            return False
        db.execute("DELETE FROM schedule WHERE agent_id = %s", (agent_id,))
        rc = db.execute("DELETE FROM agents WHERE agent_id = %s", (agent_id,))
    if rc:
        _audit("delete_agent", "agent", agent_id, old_value={"name": row.get("name")})
    return bool(rc)


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


def get_team_directory() -> list[dict]:
    """გუნდების საცნობარო სია — თითო აქტიურ თიმლიდერზე ერთი ჩანაწერი:
    {"team": <შიდა გუნდის კოდი>, "name": <თიმლიდერის სახელი>,
    "agent_id": <თიმლიდერის id>, "member_count": ...}. ეს არის
    ერთადერთი სწორი წყარო იმისთვის, თუ როგორ უნდა გამოჩნდეს "გუნდი"
    ნებისმიერ ჩამონათვალში/ფილტრში (რეპორტები, ისტორია, დღის ამბები) —
    ნედლი `team` ველის მაგივრად ყოველთვის თიმლიდერის სახელი (მაგ.
    "გაბოს გუნდი"), რომ ორი განსხვავებული თიმლიდერის შემთხვევითი
    ერთნაირი `team` მნიშვნელობა არასდროს აირიოს ერთმანეთში ჩუმად."""
    agents = get_agents()
    leads = [
        a for a in agents
        if str(a.get("role", "")).strip() == "team_lead"
        and str(a.get("active", "yes")).strip().lower() != "no"
        and str(a.get("team", "")).strip()
    ]
    out = []
    for lead in leads:
        team_key = str(lead.get("team", "")).strip()
        member_count = sum(
            1 for a in agents
            if str(a.get("team", "")).strip() == team_key
            and str(a.get("agent_id")) != str(lead.get("agent_id"))
            and str(a.get("active", "yes")).strip().lower() != "no"
        )
        out.append({
            "team": team_key,
            "name": lead.get("name", ""),
            "agent_id": lead.get("agent_id"),
            "member_count": member_count,
        })
    out.sort(key=lambda t: t["name"] or "")
    return out


def find_duplicate_team_keys() -> list[dict]:
    """უსაფრთხოების საკონტროლო შემოწმება: თუ ორ სხვადასხვა (აქტიურ)
    თიმლიდერს ერთი და იგივე `team` კოდი ერგო (ძველი მონაცემებიდან ან
    ხელით /setteam-ით) — ისინი Mini App-ში ერთმანეთში აირევა (ერთის
    გუნდის წევრი მეორის გუნდში გამოჩნდება). აბრუნებს ასეთ კოლიზიებს,
    რომ ადმინმა "აგენტების მართვა" ტაბიდან ერთი ღილაკით გაასწოროს."""
    agents = get_agents()
    leads = [
        a for a in agents
        if str(a.get("role", "")).strip() == "team_lead"
        and str(a.get("active", "yes")).strip().lower() != "no"
    ]
    by_key: dict[str, list[dict]] = {}
    for lead in leads:
        key = str(lead.get("team", "")).strip()
        if not key:
            continue
        by_key.setdefault(key, []).append(lead)
    return [
        {"team": key, "leads": [{"agent_id": l.get("agent_id"), "name": l.get("name")} for l in ls]}
        for key, ls in by_key.items() if len(ls) > 1
    ]


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


def get_task_history(days: int | None = None, agent_id: str | None = None,
                      team: str | None = None) -> list[dict]:
    """დავალებების ისტორია (ღიაც და დახურულიც) — Mini App-ის
    დღე/კვირა/თვე ფილტრისთვის + გუნდის/აგენტის სქოუფინგისთვის."""
    rows = get_tasks()
    if agent_id:
        rows = [r for r in rows if str(r.get("assigned_to")) == str(agent_id)]
    if team:
        team_ids = {
            str(a.get("agent_id")) for a in get_agents()
            if str(a.get("team", "")).strip() == team.strip()
        }
        rows = [r for r in rows if str(r.get("assigned_to")) in team_ids]
    if days:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        rows = [r for r in rows if (_parse_dt(r.get("created_at", "")) or cutoff) >= cutoff]
    return sorted(rows, key=lambda r: str(r.get("created_at", "")), reverse=True)


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
            agent_name_by_id(assigned_to), "no", "",
        ])
        return task_id


def mark_task_seen(task_id: str, agent_id: str) -> dict | None:
    """აგენტი ადასტურებს კონკრეტული კლიენტის/დავალების მიღებას —
    მენეჯერს/ადმინს რომ სჩანდეს, ნახა თუ არა აგენტმა უკვე. მხოლოდ
    თავად მინიჭებულ აგენტს შეუძლია საკუთარი დავალების დადასტურება."""
    with _lock:
        row = db.query_one("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
        if not row or str(row.get("assigned_to")) != str(agent_id):
            return None
        db.execute(
            "UPDATE tasks SET seen = %s, seen_at = %s WHERE task_id = %s",
            ("yes", _now(), task_id),
        )
        return db.query_one("SELECT * FROM tasks WHERE task_id = %s", (task_id,))


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
            "notified = %s, seen = %s, seen_at = %s WHERE task_id = %s",
            (new_agent_id, agent_name_by_id(new_agent_id), _now(), "no", "no", "", task_id),
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


def get_all_clients(team: str | None = None) -> list[dict]:
    """ერთი სტრიქონი თითო უნიკალურ კლიენტის ტელეფონზე (ყველა
    დავალების/ლიდის მიხედვით, ოდესმე შექმნილი) — მიმოხილვისთვის
    "კლიენტები" ტაბში. `team` მითითებისას რჩება მხოლოდ ის კლიენტები,
    რომელთა რომელიმე დავალება ოდესმე ამ გუნდის (მიმდინარე წევრობით)
    აგენტზე ყოფილა მინიჭებული — მენეჯერს რომ არც ის კლიენტი წაერთვას
    ხედვიდან, რომელიც შემდეგ სხვა გუნდზე გადაბარდა."""
    tasks = get_tasks()
    agents_by_id = {str(a.get("agent_id")): a for a in get_agents()}
    by_phone: dict[str, list[dict]] = {}
    for t in tasks:
        phone = str(t.get("client_phone", "")).strip()
        if not phone:
            continue
        by_phone.setdefault(phone, []).append(t)

    out = []
    for phone, trows in by_phone.items():
        trows_sorted = sorted(trows, key=lambda t: str(t.get("created_at", "")))
        latest = trows_sorted[-1]
        if team is not None:
            team_keys = {
                str(agents_by_id.get(str(t.get("assigned_to")), {}).get("team", "")).strip()
                for t in trows
            }
            if team not in team_keys:
                continue
        out.append({
            "client_phone": phone,
            "current_agent_id": latest.get("assigned_to"),
            "current_agent_name": latest.get("assigned_to_name") or agent_name_by_id(latest.get("assigned_to")),
            "status": latest.get("status"),
            "deal_type": latest.get("deal_type") or latest.get("lead_type"),
            "task_count": len(trows),
            "first_seen": trows_sorted[0].get("created_at", ""),
            "last_activity": latest.get("updated_at") or latest.get("created_at", ""),
        })
    out.sort(key=lambda c: str(c.get("last_activity") or ""), reverse=True)
    return out


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


def get_dayoff_request(request_id: str) -> dict | None:
    with _lock:
        return db.query_one("SELECT * FROM dayoff WHERE request_id = %s", (request_id,))


def approved_dayoffs_count_this_month(agent_id: str, date: str) -> int:
    """რამდენი "approved" Day off აქვს ამ აგენტს იმავე კალენდარულ თვეში,
    რასაც `date` (YYYY-MM-DD) ეკუთვნის — თვის ჭერის (DAYOFF_MONTHLY_LIMIT)
    შემოწმებისთვის დამტკიცების წინ."""
    month_key = str(date or "").strip()[:7]
    if not month_key:
        return 0
    rows = get_dayoff_requests(status="approved")
    return sum(
        1 for r in rows
        if str(r.get("agent_id")) == str(agent_id)
        and str(r.get("date", "")).strip()[:7] == month_key
    )


# ---------- აგენტის დამატების/გათავისუფლების მოთხოვნები (მენეჯერი
# ითხოვს, ადმინი ამტკიცებს/უარყოფს) ----------

def create_agent_request(kind: str, requested_by: str, team: str = "",
                          name: str = "", phone: str = "",
                          target_agent_id: str = "", reason: str = "") -> str:
    with _lock:
        request_id = uuid.uuid4().hex[:8]
        _insert("agent_requests", AGENT_REQUESTS_HEADERS, [
            request_id, kind, requested_by, agent_name_by_id(requested_by), team,
            target_agent_id, name, phone, reason, "pending", _now(), "", "",
        ])
        return request_id


def get_agent_requests(status: str | None = None, team: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM agent_requests")
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    if team:
        rows = [r for r in rows if str(r.get("team", "")).strip() == team.strip()]
    return sorted(rows, key=lambda r: str(r.get("created_at", "")), reverse=True)


def decide_agent_request(request_id: str, status: str, decided_by: str = "") -> dict | None:
    """დამტკიცებისას ("approved") რეალურადაც ასრულებს მოქმედებას:
    kind="add" -> add_agent(...), kind="remove" -> დეაქტივაცია
    (set_agent_active "no") — არასდროს ნამდვილი წაშლა, არსებული
    "გათავისუფლების" პრინციპის მსგავსად, რომ ისტორია არ დაიკარგოს."""
    with _lock:
        req = db.query_one("SELECT * FROM agent_requests WHERE request_id = %s", (request_id,))
    if not req or str(req.get("status")) != "pending":
        return None

    new_agent_id = ""
    if status == "approved":
        if req.get("kind") == "add":
            new_agent_id = add_agent(req.get("name", ""), req.get("phone", ""), team=req.get("team", ""))
        elif req.get("kind") == "remove" and req.get("target_agent_id"):
            set_agent_active(req.get("target_agent_id"), "no")

    with _lock:
        db.execute(
            "UPDATE agent_requests SET status = %s, decided_at = %s, decided_by = %s, "
            "target_agent_id = %s WHERE request_id = %s",
            (status, _now(), decided_by, new_agent_id or req.get("target_agent_id", ""), request_id),
        )
        row = db.query_one("SELECT * FROM agent_requests WHERE request_id = %s", (request_id,))
    _audit("decide_agent_request", "agent_request", request_id, actor_agent_id=decided_by,
           new_value={"status": status, "kind": req.get("kind")})
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


def get_meetings(agent_id: str | None = None, client_phone: str | None = None,
                  days: int | None = None) -> list[dict]:
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
    if days:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        rows = [r for r in rows if (_parse_dt(r.get("timestamp", "")) or cutoff) >= cutoff]
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
                [warning_id, agent_id, type_, detail, _now(), agent_name_by_id(agent_id),
                 "active", "", "", "", "", "", ""])

    count = len([
        w for w in get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS)
        if str(w.get("status") or "active") != "dismissed"
    ])
    deactivated = False
    if count >= config.WARNING_LIMIT:
        set_agent_active(agent_id, "no")
        deactivated = True
        _audit("auto_deactivate_on_warnings", "agent", agent_id,
               new_value={"warning_count": count, "type": type_})
    return {"warning_id": warning_id, "count": count, "deactivated": deactivated}


def request_warning_dismissal(warning_id: str, requested_by: str, reason: str) -> dict | None:
    """მენეჯერი ითხოვს კონკრეტული გაფრთხილების გაუქმებას (მაგ. აგენტი
    შეხვედრაზე იყო სმენის დროს) — მიზეზის მითითებით. მოთხოვნა
    "pending"-ია სანამ დირექტორი არ გადაწყვეტს (decide_warning_dismissal);
    თავად აღარ აქვეითებს გაფრთხილებას/მის ჩათვლას ჭერში."""
    with _lock:
        row = db.query_one("SELECT * FROM warnings WHERE warning_id = %s", (warning_id,))
        if not row or str(row.get("status") or "active") not in ("active",):
            return None
        db.execute(
            "UPDATE warnings SET status = %s, dismiss_reason = %s, dismiss_requested_by = %s, "
            "dismiss_requested_by_name = %s, dismiss_requested_at = %s WHERE warning_id = %s",
            ("dismiss_pending", reason, requested_by, agent_name_by_id(requested_by), _now(), warning_id),
        )
        return db.query_one("SELECT * FROM warnings WHERE warning_id = %s", (warning_id,))


def decide_warning_dismissal(warning_id: str, approve: bool, decided_by: str) -> dict | None:
    """დირექტორის საბოლოო გადაწყვეტილება მენეჯერის მოთხოვნაზე.
    დამტკიცებისას (approve=True) გაფრთხილება status='dismissed'-ზე
    გადადის და აღარ ითვლება WARNING_LIMIT-ის ჭერში; უარყოფისას
    ისევ 'active'-ზე ბრუნდება (განგრძობით ითვლება)."""
    with _lock:
        row = db.query_one("SELECT * FROM warnings WHERE warning_id = %s", (warning_id,))
        if not row or str(row.get("status") or "active") != "dismiss_pending":
            return None
        new_status = "dismissed" if approve else "active"
        db.execute(
            "UPDATE warnings SET status = %s, dismiss_decided_by = %s, dismiss_decided_at = %s "
            "WHERE warning_id = %s",
            (new_status, decided_by, _now(), warning_id),
        )
        row = db.query_one("SELECT * FROM warnings WHERE warning_id = %s", (warning_id,))
    _audit("decide_warning_dismissal", "warning", warning_id,
           new_value={"status": new_status, "decided_by": decided_by})
    return row


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


def get_today_client_phones(agent_id: str) -> list[str]:
    """დღეს ამ აგენტზე მინიჭებული კლიენტების ტელეფონები (უნიკალური,
    გამეორების გარეშე) — რომ დღის დახურვისას აგენტს არ მოეთხოვოს იმ
    ნომრის ხელახლა ხელით აკრეფა, რაც სისტემას უკვე აქვს (მენეჯერმა
    კლიენტის გადაბარებისას უკვე შეიყვანა)."""
    today_str = _today_str()
    tasks = [
        t for t in get_tasks()
        if str(t.get("assigned_to")) == str(agent_id)
        and str(t.get("created_at", "")).startswith(today_str)
        and str(t.get("client_phone", "")).strip()
    ]
    out = []
    for t in tasks:
        phone = str(t.get("client_phone")).strip()
        if phone not in out:
            out.append(phone)
    return out


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
            "client_phones": get_today_client_phones(agent_id),
        },
        "clients": clients,
        "schedule": {k: str(sched.get(k) or "off") for k in WEEKDAY_KEYS},
        "performance": {
            "assigned": perf.get("assigned", 0),
            "on_time": perf.get("on_time", 0),
            "rate": perf.get("rate"),
        },
        "warnings": {
            "count": len([w for w in warns if str(w.get("status") or "active") != "dismissed"]),
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
    late_count = 0
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
        # "დღეს ვინ დაგვიანდა/არ დაუწყია" — Mini App-ის ცოცხალი სურათისთვის
        # (item 6): ოფისის ცვლაზეა, ჯერ არ დაუწყია, და საათი უკვე
        # grace-ის მიღმაა.
        late = False
        if mode in ("office_morning", "office_evening") and not att.get("clock_in"):
            start_hour = 10 if mode == "office_morning" else 16
            _now_dt = datetime.datetime.now()
            _deadline = _now_dt.replace(hour=start_hour, minute=config.ATTENDANCE_GRACE_MINUTES, second=0, microsecond=0)
            if _now_dt >= _deadline:
                late = True
                late_count += 1
        w = len([
            x for x in get_warnings(agent_id=aid, days=config.WARNING_WINDOW_DAYS)
            if str(x.get("status") or "active") != "dismissed"
        ])
        p = perf.get(str(aid), {})
        c = client_counts(aid)
        clients_today_total += c["today"]
        clients_all_total += c["total"]
        team_rows.append({
            "agent_id": aid,
            "name": a.get("name", ""),
            "team": a.get("team", ""),
            "late": late,
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
            "schedule": get_agent_schedule(aid) or {},
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
            "late_count": late_count,
        },
    }


_DIGEST_MODE_LABELS = {
    "office_morning": "ოფისი, დილის ცვლა",
    "office_evening": "ოფისი, საღამოს ცვლა",
    "online": "ონლაინ (სახლიდან)",
}
_DIGEST_WARNING_LABELS = {
    "late_report": "დაგვიანებული/გამოტოვებული ანგარიში",
    "late_arrival": "დაგვიანება სამუშაოზე",
    "no_show": "არ გამოცხადება",
    "quota_missed": "დღიური გეგმა ვერ შესრულდა",
}


def get_daily_digest(team: str | None = None, days: int = 1) -> dict:
    """დღის შეჯამება (6 პუნქტი) — ერთი საერთო წყარო, რომელსაც იყენებს
    ორივე: ბოტის ყოველდღიური ტექსტური შეტყობინება ადმინისთვის/
    თიმლიდერისთვის და Mini App-ის „დღის ამბები“ ტაბი. `team=None` —
    მთელი კომპანია (ადმინი), კონკრეტული `team` — მხოლოდ ის გუნდი.
    `days` — 1 (დღეს, ნაგულისხმევი, ძველი ქცევა უცვლელია), 7 (კვირა)
    ან 30 (თვე): პუნქტები 2-3-5 (კლიენტები/შეხვედრები/გაფრთხილებები)
    ამ ფანჯარაში ჯამდება. პუნქტი 1 (გამოცხადება) და 4 (განცხადებების
    დღიური რაოდენობა) მუდამ მხოლოდ დღევანდელს აჩვენებს — დასწრება
    დღიური სნეპშოტია, კვირაში/თვეში „ჯამურად გამოცხადებული“ არაფერს
    ნიშნავს ისე, როგორც დღეს."""
    today = _today_str()
    days = max(1, int(days or 1))
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days - 1)).strftime("%Y-%m-%d")
    all_agents = get_agents()
    agents = [
        a for a in all_agents
        if str(a.get("active", "yes")).strip().lower() != "no"
        and (team is None or str(a.get("team", "")).strip() == team.strip())
    ]
    agent_ids = {str(a.get("agent_id")) for a in agents}
    names = {str(a.get("agent_id")): a.get("name", "") for a in agents}
    att_all = {str(r.get("agent_id")): r for r in get_today_attendance_all()}

    came, not_started = [], []
    for a in agents:
        aid = str(a.get("agent_id"))
        mode = get_today_mode(aid)
        if mode == "off":
            continue
        mode_label = _DIGEST_MODE_LABELS.get(mode, mode)
        att = att_all.get(aid)
        if att and att.get("clock_in"):
            status = "დასრულებულია" if att.get("clock_out") else "ჯერ მუშაობს"
            came.append(f"{a.get('name')} — {mode_label} ({status})")
        else:
            not_started.append(f"{a.get('name')} — {mode_label}")

    tasks_period = [
        t for t in get_tasks()
        if str(t.get("assigned_to")) in agent_ids and str(t.get("created_at", ""))[:10] >= cutoff
    ]
    clients_assigned = [
        f"{names.get(str(t.get('assigned_to')), t.get('assigned_to'))} — {t.get('title', '')}"
        for t in tasks_period
    ]

    meetings_period = [
        m for m in get_meetings()
        if str(m.get("agent_id")) in agent_ids and str(m.get("timestamp", ""))[:10] >= cutoff
    ]
    meetings_list = [
        f"{m.get('agent_name') or names.get(str(m.get('agent_id')), '')} — {m.get('address') or m.get('district') or ''}"
        for m in meetings_period
    ]

    listing_counts = [
        f"{a.get('name')}: {att_all[str(a.get('agent_id'))].get('count_submitted')}"
        for a in agents
        if str(a.get("agent_id")) in att_all
        and att_all[str(a.get("agent_id"))].get("count_submitted") not in (None, "")
    ]

    warns_period = [
        w for w in get_warnings()
        if str(w.get("agent_id")) in agent_ids and str(w.get("created_at", ""))[:10] >= cutoff
    ]
    warnings_today = [
        f"{names.get(str(w.get('agent_id')), w.get('agent_id'))} — "
        f"{_DIGEST_WARNING_LABELS.get(w.get('type'), w.get('type'))}"
        for w in warns_period
    ]

    attention = []
    for a in agents:
        aid = str(a.get("agent_id"))
        w_count = len([
            x for x in get_warnings(agent_id=aid, days=config.WARNING_WINDOW_DAYS)
            if str(x.get("status") or "active") != "dismissed"
        ])
        if w_count >= max(1, config.WARNING_LIMIT - 1):
            attention.append(
                f"{a.get('name')} — {w_count}/{config.WARNING_LIMIT} გაფრთხილება "
                f"({config.WARNING_WINDOW_DAYS} დღეში)"
            )

    teams = get_team_directory() if team is None else []

    return {
        "date": today,
        "days": days,
        "came": came,
        "not_started": not_started,
        "clients_assigned": clients_assigned,
        "meetings": meetings_list,
        "listing_counts": listing_counts,
        "warnings_today": warnings_today,
        "attention": attention,
        "teams": teams,
    }


# ---------- MyHome სქრეპერის queue (worker.py, home-automation რეპო) ----------

def get_myhome_accounts() -> list[dict]:
    with _lock:
        return db.query_all("SELECT * FROM myhome_accounts")


def get_myhome_account_for_team(team: str) -> dict | None:
    with _lock:
        return db.query_one(
            "SELECT * FROM myhome_accounts WHERE team = %s", (str(team or "").strip(),)
        )


def set_myhome_account(team: str, manager_label: str, manager_name: str = "") -> None:
    team = str(team or "").strip()
    with _lock:
        rc = db.execute(
            "UPDATE myhome_accounts SET manager_label = %s, manager_name = %s, "
            "updated_at = %s WHERE team = %s",
            (manager_label, manager_name, _now(), team),
        )
        if not rc:
            _insert(
                "myhome_accounts", MYHOME_ACCOUNTS_HEADERS,
                [team, manager_label, manager_name, _now()],
            )


def create_myhome_job(agent_id: str, fields: dict) -> str:
    with _lock:
        job_id = uuid.uuid4().hex[:8]
        values = []
        for h in MYHOME_JOBS_HEADERS:
            if h == "job_id":
                values.append(job_id)
            elif h == "agent_id":
                values.append(agent_id)
            elif h == "agent_name":
                values.append(agent_name_by_id(agent_id))
            elif h == "status":
                values.append("QUEUED")
            elif h == "retry_count":
                values.append("0")
            elif h == "created_at":
                values.append(_now())
            elif h in ("started_at", "completed_at", "error_message"):
                values.append("")
            else:
                values.append(fields.get(h, ""))
        _insert("myhome_jobs", MYHOME_JOBS_HEADERS, values)
        return job_id


def get_myhome_jobs(agent_id: str | None = None, team: str | None = None,
                     status: str | None = None) -> list[dict]:
    with _lock:
        rows = db.query_all("SELECT * FROM myhome_jobs")
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if team:
        rows = [r for r in rows if str(r.get("team", "")).strip() == str(team).strip()]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return sorted(rows, key=lambda r: str(r.get("created_at", "")), reverse=True)


def find_myhome_job(job_id: str) -> dict | None:
    with _lock:
        return db.query_one("SELECT * FROM myhome_jobs WHERE job_id = %s", (str(job_id),))


def find_active_myhome_job(myhome_listing_id: str) -> dict | None:
    """დუბლიკატის დაცვა: იგივე MyHome ID-ზე უკვე მიმდინარე (QUEUED ან
    PROCESSING) job არსებობს თუ არა. დასრულებულ/ჩავარდნილ job-ებს არ
    ეხება — იმავე ID-ის ხელახლა გაგზავნა მოგვიანებით დაშვებულია."""
    listing_id = str(myhome_listing_id or "").strip()
    if not listing_id:
        return None
    with _lock:
        return db.query_one(
            "SELECT * FROM myhome_jobs WHERE myhome_listing_id = %s "
            "AND status IN ('QUEUED', 'PROCESSING') LIMIT 1",
            (listing_id,),
        )


def claim_next_myhome_job(manager_label: str) -> dict | None:
    """worker.py გამოძახებით: ამ მენეჯერის ანგარიშზე უძველესი "QUEUED"
    job-ის დაკავება — მაშინვე "PROCESSING"-ში გადაყვანა. ერთდროულად
    მხოლოდ ერთი worker-ის დაშვებით (რეკომენდებული) ეს საკმარისად
    უსაფრთხოა; მკაცრი, ბევრ worker-ზე გათვლილი атомურობა (SELECT ...
    FOR UPDATE SKIP LOCKED) ჯერჯერობით საჭირო არაა."""
    manager_label = str(manager_label or "").strip()
    with _lock:
        row = db.query_one(
            "SELECT * FROM myhome_jobs WHERE status = 'QUEUED' AND manager_label = %s "
            "ORDER BY created_at ASC LIMIT 1",
            (manager_label,),
        )
        if not row:
            return None
        rc = db.execute(
            "UPDATE myhome_jobs SET status = 'PROCESSING', started_at = %s WHERE job_id = %s",
            (_now(), row["job_id"]),
        )
        if not rc:
            return None
        return db.query_one("SELECT * FROM myhome_jobs WHERE job_id = %s", (row["job_id"],))


def complete_myhome_job(job_id: str, status: str, error_message: str = "") -> dict | None:
    """status: "COMPLETED" ან "FAILED"."""
    with _lock:
        rc = db.execute(
            "UPDATE myhome_jobs SET status = %s, error_message = %s, completed_at = %s "
            "WHERE job_id = %s",
            (status, error_message, _now(), str(job_id)),
        )
        if not rc:
            return None
        return db.query_one("SELECT * FROM myhome_jobs WHERE job_id = %s", (str(job_id),))


def reset_stale_myhome_jobs(older_than_minutes: int, max_retries: int) -> list[dict]:
    """worker.py-ს crash-ის/restart-ის დაცვა: "PROCESSING"-ში
    `older_than_minutes`-ზე მეტხანს გაჭედილი job-ები ბრუნდება
    "QUEUED"-ში ხელახლა (retry_count იზრდება), ან თუ უკვე `max_retries`
    მიაღწია — საბოლოოდ "FAILED"."""
    cutoff = datetime.datetime.now() - datetime.timedelta(minutes=older_than_minutes)
    changed = []
    for r in get_myhome_jobs(status="PROCESSING"):
        started = r.get("started_at") or r.get("created_at")
        try:
            started_dt = datetime.datetime.strptime(str(started).strip(), "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        if started_dt > cutoff:
            continue
        retry_count = int(str(r.get("retry_count") or "0").strip() or "0")
        if retry_count >= max_retries:
            updated = complete_myhome_job(
                r["job_id"], "FAILED",
                error_message="worker-ი გაითიშა დამუშავებისას, ცდების ლიმიტი ამოიწურა",
            )
        else:
            with _lock:
                db.execute(
                    "UPDATE myhome_jobs SET status = 'QUEUED', retry_count = %s, "
                    "started_at = '' WHERE job_id = %s",
                    (str(retry_count + 1), r["job_id"]),
                )
                updated = db.query_one(
                    "SELECT * FROM myhome_jobs WHERE job_id = %s", (r["job_id"],)
                )
        if updated:
            changed.append(updated)
    return changed
