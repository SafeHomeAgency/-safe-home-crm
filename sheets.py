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
    მიიღებდნენ).
    """
    agents = [
        a for a in get_agents()
        if str(a.get("active", "")).strip().lower() != "no"
        and str(a.get("telegram_chat_id", "")).strip()
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
