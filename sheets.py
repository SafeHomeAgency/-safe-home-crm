"""
Google Sheets-თან მუშაობის ფენა (gspread-ის დახმარებით).

ცხრილის სტრუქტურა (2 tab):

  Agents:
    agent_id | name | phone | telegram_username | telegram_chat_id | active | registered_at

  Tasks:
    task_id | title | description | assigned_to | status | priority |
    due_date | created_by | created_at | updated_at | notified |
    lead_type | client_phone | deal_type | listing_id | viewing_time

  status: New / InProgress / Done
  notified: yes / no  (bot ავსებს ავტომატურად, როცა აგენტს შეატყობინებს)
  lead_type: general (ზოგადი კლიენტი) / listing (კონკრეტული ბინის ნახვა)
  deal_type: ქირა / ყიდვა  (მხოლოდ lead_type=general-ისთვის)
"""

from __future__ import annotations

import datetime
import json
import random
import threading
import uuid

import gspread
from google.oauth2.service_account import Credentials

import config

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_lock = threading.Lock()
_client = None
_sheet = None

AGENTS_HEADERS = [
    "agent_id", "name", "phone", "telegram_username",
    "telegram_chat_id", "active", "registered_at",
]
TASKS_HEADERS = [
    "task_id", "title", "description", "assigned_to", "status",
    "priority", "due_date", "created_by", "created_at", "updated_at",
    "notified", "lead_type", "client_phone", "deal_type", "listing_id",
    "viewing_time",
]
REPORTS_HEADERS = [
    "report_id", "agent_id", "client_phone", "actions", "notes",
    "file_id", "created_at",
]
DAYOFF_HEADERS = [
    "request_id", "agent_id", "date", "reason", "status",
    "created_at", "decided_at",
]
# ყოფილი Slack "შეხვედრები" (meetings/viewings) ფორმის სვეტები
MEETINGS_HEADERS = [
    "meeting_id", "timestamp", "owner_phone", "myhome_link", "myhome_id",
    "ssge_link", "ssge_id", "condition", "client_phone", "district",
    "address", "meeting_date", "agent_id", "agent_name", "price",
    "percent", "time", "internal_number", "agent_phone", "team_leader",
]

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# ერთი სტრიქონი ერთ აგენტზე — კვირის განმეორებადი გრაფიკი (ყოფილი
# "პირბადული ცხრილი"). მნიშვნელობები: off / office_morning /
# office_evening / online.
SCHEDULE_HEADERS = ["agent_id"] + WEEKDAY_KEYS + ["updated_at"]

# დღიური გამოცხადება/დასრულება (clock-in / clock-out)
ATTENDANCE_HEADERS = [
    "attendance_id", "agent_id", "date", "mode", "clock_in", "clock_out",
]

# გაფრთხილებები (დაგვიანებული/გამოტოვებული ანგარიში, დაგვიანება,
# არ-გამოცხადება). ტიპები: late_report / late_arrival / no_show
WARNINGS_HEADERS = ["warning_id", "agent_id", "type", "detail", "created_at"]


def _get_client():
    """
    GOOGLE_SERVICE_ACCOUNT_JSON შეიძლება იყოს:
      - JSON ფაილის გზა (მაგ. service_account.json), ან
      - თავად JSON-ის შიგთავსი პირდაპირ environment variable-ში
        (მოსახერხებელია Railway-ის მსგავს პლატფორმებზე, სადაც ფაილის
        ატვირთვა არ არის საჭირო — მთელი JSON შეგიძლიათ ჩასვათ env
        ცვლადის მნიშვნელობად).
    """
    global _client
    if _client is None:
        raw = config.GOOGLE_SERVICE_ACCOUNT_JSON.strip()
        if raw.startswith("{"):
            info = json.loads(raw)
            creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        else:
            creds = Credentials.from_service_account_file(raw, scopes=_SCOPES)
        _client = gspread.authorize(creds)
    return _client


def _get_spreadsheet():
    global _sheet
    if _sheet is None:
        _sheet = _get_client().open_by_key(config.GOOGLE_SHEET_ID)
    return _sheet


def ensure_sheets():
    """თუ Agents/Tasks tab-ები არ არსებობს, ქმნის სათაურებით."""
    ss = _get_spreadsheet()
    existing = {ws.title: ws for ws in ss.worksheets()}

    if config.AGENTS_SHEET_NAME not in existing:
        ws = ss.add_worksheet(config.AGENTS_SHEET_NAME, rows=200, cols=len(AGENTS_HEADERS))
        ws.append_row(AGENTS_HEADERS)
    else:
        ws = existing[config.AGENTS_SHEET_NAME]
        if ws.row_values(1) != AGENTS_HEADERS:
            ws.update("A1", [AGENTS_HEADERS])

    if config.TASKS_SHEET_NAME not in existing:
        ws2 = ss.add_worksheet(config.TASKS_SHEET_NAME, rows=500, cols=len(TASKS_HEADERS))
        ws2.append_row(TASKS_HEADERS)
    else:
        ws2 = existing[config.TASKS_SHEET_NAME]
        if ws2.row_values(1) != TASKS_HEADERS:
            if ws2.col_count < len(TASKS_HEADERS):
                ws2.resize(cols=len(TASKS_HEADERS))
            ws2.update("A1", [TASKS_HEADERS])

    if config.REPORTS_SHEET_NAME not in existing:
        ws3 = ss.add_worksheet(config.REPORTS_SHEET_NAME, rows=1000, cols=len(REPORTS_HEADERS))
        ws3.append_row(REPORTS_HEADERS)
    else:
        ws3 = existing[config.REPORTS_SHEET_NAME]
        if ws3.row_values(1) != REPORTS_HEADERS:
            if ws3.col_count < len(REPORTS_HEADERS):
                ws3.resize(cols=len(REPORTS_HEADERS))
            ws3.update("A1", [REPORTS_HEADERS])

    if config.DAYOFF_SHEET_NAME not in existing:
        ws4 = ss.add_worksheet(config.DAYOFF_SHEET_NAME, rows=300, cols=len(DAYOFF_HEADERS))
        ws4.append_row(DAYOFF_HEADERS)
    else:
        ws4 = existing[config.DAYOFF_SHEET_NAME]
        if ws4.row_values(1) != DAYOFF_HEADERS:
            if ws4.col_count < len(DAYOFF_HEADERS):
                ws4.resize(cols=len(DAYOFF_HEADERS))
            ws4.update("A1", [DAYOFF_HEADERS])

    if config.MEETINGS_SHEET_NAME not in existing:
        ws5 = ss.add_worksheet(config.MEETINGS_SHEET_NAME, rows=1000, cols=len(MEETINGS_HEADERS))
        ws5.append_row(MEETINGS_HEADERS)
    else:
        ws5 = existing[config.MEETINGS_SHEET_NAME]
        if ws5.row_values(1) != MEETINGS_HEADERS:
            if ws5.col_count < len(MEETINGS_HEADERS):
                ws5.resize(cols=len(MEETINGS_HEADERS))
            ws5.update("A1", [MEETINGS_HEADERS])

    if config.SCHEDULE_SHEET_NAME not in existing:
        ws6 = ss.add_worksheet(config.SCHEDULE_SHEET_NAME, rows=200, cols=len(SCHEDULE_HEADERS))
        ws6.append_row(SCHEDULE_HEADERS)
    else:
        ws6 = existing[config.SCHEDULE_SHEET_NAME]
        if ws6.row_values(1) != SCHEDULE_HEADERS:
            if ws6.col_count < len(SCHEDULE_HEADERS):
                ws6.resize(cols=len(SCHEDULE_HEADERS))
            ws6.update("A1", [SCHEDULE_HEADERS])

    if config.ATTENDANCE_SHEET_NAME not in existing:
        ws7 = ss.add_worksheet(config.ATTENDANCE_SHEET_NAME, rows=2000, cols=len(ATTENDANCE_HEADERS))
        ws7.append_row(ATTENDANCE_HEADERS)
    else:
        ws7 = existing[config.ATTENDANCE_SHEET_NAME]
        if ws7.row_values(1) != ATTENDANCE_HEADERS:
            if ws7.col_count < len(ATTENDANCE_HEADERS):
                ws7.resize(cols=len(ATTENDANCE_HEADERS))
            ws7.update("A1", [ATTENDANCE_HEADERS])

    if config.WARNINGS_SHEET_NAME not in existing:
        ws8 = ss.add_worksheet(config.WARNINGS_SHEET_NAME, rows=500, cols=len(WARNINGS_HEADERS))
        ws8.append_row(WARNINGS_HEADERS)
    else:
        ws8 = existing[config.WARNINGS_SHEET_NAME]
        if ws8.row_values(1) != WARNINGS_HEADERS:
            if ws8.col_count < len(WARNINGS_HEADERS):
                ws8.resize(cols=len(WARNINGS_HEADERS))
            ws8.update("A1", [WARNINGS_HEADERS])


def _agents_ws():
    return _get_spreadsheet().worksheet(config.AGENTS_SHEET_NAME)


def _tasks_ws():
    return _get_spreadsheet().worksheet(config.TASKS_SHEET_NAME)


def _reports_ws():
    return _get_spreadsheet().worksheet(config.REPORTS_SHEET_NAME)


def _dayoff_ws():
    return _get_spreadsheet().worksheet(config.DAYOFF_SHEET_NAME)


def _meetings_ws():
    return _get_spreadsheet().worksheet(config.MEETINGS_SHEET_NAME)


def _schedule_ws():
    return _get_spreadsheet().worksheet(config.SCHEDULE_SHEET_NAME)


def _attendance_ws():
    return _get_spreadsheet().worksheet(config.ATTENDANCE_SHEET_NAME)


def _warnings_ws():
    return _get_spreadsheet().worksheet(config.WARNINGS_SHEET_NAME)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------- Agents ----------

def get_agents() -> list[dict]:
    with _lock:
        return _agents_ws().get_all_records()


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


def register_agent_chat_id(agent_id: str, chat_id: int, username: str):
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("telegram_chat_id") + 1, str(chat_id))
        ws.update_cell(cell.row, AGENTS_HEADERS.index("telegram_username") + 1, username or "")
        return True


def add_agent(name: str, phone: str) -> str:
    """ადმინი ამატებს ახალ აგენტს (ტელეფონით). აბრუნებს agent_id-ს."""
    with _lock:
        agent_id = uuid.uuid4().hex[:8]
        _agents_ws().append_row([
            agent_id, name, phone, "", "", "yes", _now(),
        ])
        return agent_id


def set_agent_active(agent_id: str, value: str) -> bool:
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("active") + 1, value)
        return True


# ---------- Tasks ----------

def get_tasks() -> list[dict]:
    with _lock:
        return _tasks_ws().get_all_records()


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
        _tasks_ws().append_row([
            task_id, title, description, assigned_to, "New",
            priority, due_date, created_by, now, now, "no",
            lead_type, client_phone, deal_type, listing_id, viewing_time,
        ])
        return task_id


def _find_task_row(task_id: str):
    ws = _tasks_ws()
    cell = ws.find(task_id, in_column=1)
    return ws, cell


def mark_task_done(task_id: str) -> bool:
    with _lock:
        ws, cell = _find_task_row(task_id)
        if not cell:
            return False
        ws.update_cell(cell.row, TASKS_HEADERS.index("status") + 1, "Done")
        ws.update_cell(cell.row, TASKS_HEADERS.index("updated_at") + 1, _now())
        return True


def mark_task_notified(task_id: str):
    with _lock:
        ws, cell = _find_task_row(task_id)
        if cell:
            ws.update_cell(cell.row, TASKS_HEADERS.index("notified") + 1, "yes")


def get_unnotified_tasks() -> list[dict]:
    return [
        t for t in get_tasks()
        if str(t.get("notified", "")).strip().lower() != "yes"
        and t.get("assigned_to")
    ]


# ---------- Performance / assignment ----------

def _parse_dt(value: str):
    try:
        return datetime.datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return None


def get_agent_performance(days: int = 30) -> dict:
    """
    თითო აგენტისთვის ბოლო `days` დღეში დაწყებული დავალებების მიხედვით:
      assigned   - სულ რამდენი დავალება მიენიჭა
      on_time    - რამდენი დაასრულა (Done) 24 საათის განმავლობაში
      rate       - on_time / assigned (0.0 - 1.0), None თუ assigned=0

    "დროულობა" აქ იზომება არა due_date-თან შედარებით (რადგან ზოგად
    კლიენტებს ხშირად ვადა საერთოდ არა აქვთ), არამედ შექმნიდან 24 საათში
    დახურვით — ეს პირდაპირ ზომავს, რამდენად სწრაფად რეაგირებს აგენტი
    ახალ ლიდზე.
    """
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


def pick_agent_for_priority(priority: str, days: int = 30) -> str | None:
    """
    ირჩევს agent_id-ს პრიორიტეტის მიხედვით:
      მაღალი   -> საუკეთესო შესრულების მაჩვენებლის მქონე აქტიური აგენტი
      საშუალო  -> ყველაზე სუსტი მაჩვენებლის მქონე აქტიური აგენტი
      სხვა     -> შემთხვევითი აქტიური აგენტი

    გასათვალისწინებელია მხოლოდ აქტიური და უკვე Telegram-ში
    დარეგისტრირებული აგენტები (წინააღმდეგ შემთხვევაში შეტყობინებას ვერ
    მიიღებდნენ), და — თუ მათთვის გრაფიკი (/setschedule) დაყენებულია —
    მხოლოდ ისინი, ვინც დღეს გრაფიკითაა გათვალისწინებული და უკვე
    დააჭირა /clockin-ს (წინააღმდეგ შემთხვევაში კლიენტი არ ერგებათ).
    """
    agents = [
        a for a in get_agents()
        if str(a.get("active", "")).strip().lower() != "no"
        and str(a.get("telegram_chat_id", "")).strip()
        and agent_available_now(a["agent_id"])
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


# ---------- Client reports (ყოფილი "AgentReports" ფორმის შემცვლელი) ----------

def create_report(agent_id: str, client_phone: str, actions: str,
                   notes: str = "", file_id: str = "") -> str:
    with _lock:
        report_id = uuid.uuid4().hex[:8]
        _reports_ws().append_row([
            report_id, agent_id, client_phone, actions, notes,
            file_id, _now(),
        ])
        return report_id


def get_reports(agent_id: str | None = None, client_phone: str | None = None) -> list[dict]:
    with _lock:
        rows = _reports_ws().get_all_records()
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
    """ერთი კლიენტის მთელი ისტორია — დავალებები + აგენტის რეპორტები + შეხვედრები."""
    needle = client_phone.strip().lstrip("+")
    tasks = [
        t for t in get_tasks()
        if str(t.get("client_phone", "")).strip().lstrip("+") == needle
    ]
    reports = get_reports(client_phone=client_phone)
    meetings = get_meetings(client_phone=client_phone)
    return {"tasks": tasks, "reports": reports, "meetings": meetings}


# ---------- Day off მოთხოვნები ----------

def create_dayoff_request(agent_id: str, date: str, reason: str) -> str:
    with _lock:
        request_id = uuid.uuid4().hex[:8]
        _dayoff_ws().append_row([
            request_id, agent_id, date, reason, "pending", _now(), "",
        ])
        return request_id


def get_dayoff_requests(status: str | None = None) -> list[dict]:
    with _lock:
        rows = _dayoff_ws().get_all_records()
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


def decide_dayoff(request_id: str, status: str) -> dict | None:
    with _lock:
        ws = _dayoff_ws()
        cell = ws.find(request_id, in_column=1)
        if not cell:
            return None
        ws.update_cell(cell.row, DAYOFF_HEADERS.index("status") + 1, status)
        ws.update_cell(cell.row, DAYOFF_HEADERS.index("decided_at") + 1, _now())
        row = ws.row_values(cell.row)
        return dict(zip(DAYOFF_HEADERS, row))


# ---------- შეხვედრები (ყოფილი "შეხვედრები" Google Form) ----------

def create_meeting(fields: dict) -> str:
    """
    fields უნდა შეიცავდეს MEETINGS_HEADERS-ის ყველა სვეტს, გარდა
    meeting_id და timestamp-ისა (ეს ავტომატურად ივსება).
    """
    with _lock:
        meeting_id = uuid.uuid4().hex[:8]
        row = []
        for h in MEETINGS_HEADERS:
            if h == "meeting_id":
                row.append(meeting_id)
            elif h == "timestamp":
                row.append(_now())
            else:
                row.append(fields.get(h, ""))
        _meetings_ws().append_row(row)
        return meeting_id


def get_meetings(agent_id: str | None = None, client_phone: str | None = None) -> list[dict]:
    with _lock:
        rows = _meetings_ws().get_all_records()
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if client_phone:
        needle = client_phone.strip().lstrip("+")
        rows = [
            r for r in rows
            if str(r.get("client_phone", "")).strip().lstrip("+") == needle
        ]
    return rows


# ---------- გრაფიკი (ყოფილი "პირბადული ცხრილი") + გამოცხადება ----------

def _today_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def set_agent_schedule(agent_id: str, pattern: dict) -> None:
    """pattern: {"mon": "office_morning", ...}. გამოტოვებული დღე = 'off'."""
    with _lock:
        ws = _schedule_ws()
        cell = ws.find(agent_id, in_column=1)
        row = [agent_id] + [pattern.get(k, "off") for k in WEEKDAY_KEYS] + [_now()]
        if cell:
            ws.update(f"A{cell.row}", [row])
        else:
            ws.append_row(row)


def get_agent_schedule(agent_id: str) -> dict | None:
    with _lock:
        rows = _schedule_ws().get_all_records()
    for r in rows:
        if str(r.get("agent_id")) == str(agent_id):
            return r
    return None


def get_today_mode(agent_id: str) -> str:
    """თუ გრაფიკი საერთოდ არ არის დაყენებული, ითვლება 'off'-ად."""
    sched = get_agent_schedule(agent_id)
    if not sched:
        return "off"
    key = WEEKDAY_KEYS[datetime.datetime.now().weekday()]
    return str(sched.get(key) or "off")


def clock_in(agent_id: str) -> str:
    """აბრუნებს 'ok' / 'already'."""
    with _lock:
        ws = _attendance_ws()
        today = _today_str()
        records = ws.get_all_records()
        for idx, r in enumerate(records, start=2):
            if str(r.get("agent_id")) == str(agent_id) and str(r.get("date")) == today:
                if r.get("clock_in"):
                    return "already"
                ws.update_cell(idx, ATTENDANCE_HEADERS.index("clock_in") + 1, _now())
                return "ok"
        mode = get_today_mode(agent_id)
        attendance_id = uuid.uuid4().hex[:8]
        ws.append_row([attendance_id, agent_id, today, mode, _now(), ""])
        return "ok"


def clock_out(agent_id: str) -> str:
    """აბრუნებს 'ok' / 'not_in' (ჯერ არ დაწყებულა)."""
    with _lock:
        ws = _attendance_ws()
        today = _today_str()
        records = ws.get_all_records()
        for idx, r in enumerate(records, start=2):
            if str(r.get("agent_id")) == str(agent_id) and str(r.get("date")) == today:
                if not r.get("clock_in"):
                    return "not_in"
                ws.update_cell(idx, ATTENDANCE_HEADERS.index("clock_out") + 1, _now())
                return "ok"
        return "not_in"


def get_today_attendance(agent_id: str) -> dict | None:
    today = _today_str()
    with _lock:
        rows = _attendance_ws().get_all_records()
    for r in rows:
        if str(r.get("agent_id")) == str(agent_id) and str(r.get("date")) == today:
            return r
    return None


def is_clocked_in_today(agent_id: str) -> bool:
    r = get_today_attendance(agent_id)
    return bool(r and r.get("clock_in") and not r.get("clock_out"))


def agent_available_now(agent_id: str) -> bool:
    """
    გრაფიკის მიხედვით, ხელმისაწვდომია თუ არა აგენტი ახალი კლიენტის
    მისაღებად ახლავე. თუ გრაფიკი საერთოდ არ არის დაყენებული ამ
    აგენტისთვის — ძველებურად ხელმისაწვდომია (უკან-თავსებადობისთვის,
    სანამ ადმინი /setschedule-ს არ გაუშვებს).
    """
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
        rows = _warnings_ws().get_all_records()
    return any(
        str(r.get("agent_id")) == str(agent_id)
        and r.get("type") == type_
        and str(r.get("created_at", "")).startswith(today)
        for r in rows
    )


def get_warnings(agent_id: str | None = None, days: int | None = None) -> list[dict]:
    with _lock:
        rows = _warnings_ws().get_all_records()
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if days:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        rows = [r for r in rows if (_parse_dt(r.get("created_at", "")) or cutoff) >= cutoff]
    return rows


def add_warning(agent_id: str, type_: str, detail: str = "") -> dict:
    """
    სვამს ახალ გაფრთხილებას და ამოწმებს ბოლო WARNING_WINDOW_DAYS დღეში
    ჯამურ რაოდენობას — თუ WARNING_LIMIT-ს მიაღწია, აგენტი ავტომატურად
    გამოირთვება (active=no).
    აბრუნებს: {"warning_id", "count", "deactivated": bool}
    """
    with _lock:
        warning_id = uuid.uuid4().hex[:8]
        _warnings_ws().append_row([warning_id, agent_id, type_, detail, _now()])

    count = len(get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS))
    deactivated = False
    if count >= config.WARNING_LIMIT:
        set_agent_active(agent_id, "no")
        deactivated = True
    return {"warning_id": warning_id, "count": count, "deactivated": deactivated}
