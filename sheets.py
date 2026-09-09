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
import logging
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


# RLock (და არა უბრალო Lock) — რადგან ახლა ზოგიერთი ფუნქცია (მაგ.
# create_task) `with _lock:`-ის შიგნით იძახებს agent_name_by_id()-ს,
# რომელიც თავადაც `_lock`-ს ითხოვს (get_agents()-ის მეშვეობით) —
# ჩვეულებრივი Lock-ით ეს იმავე thread-ს "დაეჯახებოდა" (deadlock).
_lock = threading.RLock()
_client = None
_sheet = None

AGENTS_HEADERS = [
    "agent_id", "name", "phone", "telegram_username",
    "telegram_chat_id", "active", "registered_at", "team",
    "role", "internal_number",
]
# შენიშვნა: ყველა ახალი სვეტი (agent_name/assigned_to_name და ა.შ.)
# განზრახ ემატება სიის **ბოლოში**, არა შუაში — რომ არსებული ცხრილის
# ძველი (უკვე შევსებული) სტრიქონების სვეტები არ აირიოს/გადაინაცვლოს.
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
SCHEDULE_HEADERS = ["agent_id"] + WEEKDAY_KEYS + ["updated_at", "agent_name"]

# დღიური გამოცხადება/დასრულება (clock-in / clock-out)
ATTENDANCE_HEADERS = [
    "attendance_id", "agent_id", "date", "mode", "clock_in", "clock_out",
    "count_submitted", "agent_name", "site_count", "myhome_count", "ssge_count",
]

# გაფრთხილებები (დაგვიანებული/გამოტოვებული ანგარიში, დაგვიანება,
# არ-გამოცხადება). ტიპები: late_report / late_arrival / no_show / quota_missed
WARNINGS_HEADERS = ["warning_id", "agent_id", "type", "detail", "created_at", "agent_name"]

# სმენების/ცვლის გაცვლის მოთხოვნები. request_type: swap_agent (კონკრეტულ
# კოლეგასთან გაცვლა) / change_mode (საკუთარი ცვლის ტიპის შეცვლა, მაგ.
# ოფისი→ონლაინ) / open_swap (ვინმეს გაცვლის შეთავაზება, ყველასთვის).
# status: pending_peer -> pending_manager -> approved/rejected/cancelled
SHIFT_SWAPS_HEADERS = [
    "swap_id", "agent_id", "agent_name", "request_type", "from_mode", "to_mode",
    "target_agent_id", "target_agent_name", "swap_date", "note", "status",
    "accepted_by", "accepted_by_name", "created_at", "decided_at", "decided_by",
]

# ექსკლუზივი ლისტინგები ("ბინების ბაზა") — ყოფილი "ექსკლუზივების ბაზა"
# Google Form-ის ველების ზუსტი ასლი.
EXCLUSIVES_HEADERS = [
    "exclusive_id", "agent_id", "agent_name", "contact_internal", "owner_phone",
    "property_type", "deal_type", "building_status", "condition", "location",
    "cadastral_code", "area", "rooms", "bedrooms", "floors_total", "floor_number",
    "project_type", "bathrooms", "balcony", "price", "percent", "notes",
    "photos", "status", "created_at",
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


def _ensure_one_sheet(ss, existing: dict, name: str, headers: list[str], rows: int):
    """
    ერთი tab-ის შექმნა/სათაურების განახლება. განზრახ არაფერს არ
    ისვამს try/except-ში აქ — მთლიანი ensure_sheets() თითო sheet-ს
    ცალკე იცავს, რომ ერთი წყვეტადი sheet-ი (მაგ. დაცული სვეტი) მთელ
    ბოტს არ აჩერებდეს გაშვებაზე.
    """
    if name not in existing:
        ws = ss.add_worksheet(name, rows=rows, cols=len(headers))
        ws.append_row(headers)
        return
    ws = existing[name]
    if ws.row_values(1) != headers:
        if ws.col_count < len(headers):
            ws.resize(cols=len(headers))
        ws.update("A1", [headers])


def ensure_sheets():
    """ქმნის/ანახლებს ყველა საჭირო tab-ს. თითო tab ცალკეა დაცული
    შეცდომისგან — ერთის გაფუჭება არ უშლის ხელს დანარჩენებს და ბოტის
    გაშვებას."""
    ss = _get_spreadsheet()
    existing = {ws.title: ws for ws in ss.worksheets()}

    sheets_to_ensure = [
        (config.AGENTS_SHEET_NAME, AGENTS_HEADERS, 200),
        (config.TASKS_SHEET_NAME, TASKS_HEADERS, 500),
        (config.REPORTS_SHEET_NAME, REPORTS_HEADERS, 1000),
        (config.DAYOFF_SHEET_NAME, DAYOFF_HEADERS, 300),
        (config.MEETINGS_SHEET_NAME, MEETINGS_HEADERS, 1000),
        (config.SCHEDULE_SHEET_NAME, SCHEDULE_HEADERS, 200),
        (config.ATTENDANCE_SHEET_NAME, ATTENDANCE_HEADERS, 2000),
        (config.WARNINGS_SHEET_NAME, WARNINGS_HEADERS, 500),
        (config.SHIFT_SWAPS_SHEET_NAME, SHIFT_SWAPS_HEADERS, 500),
        (config.EXCLUSIVES_SHEET_NAME, EXCLUSIVES_HEADERS, 1000),
    ]
    for name, headers, rows in sheets_to_ensure:
        try:
            _ensure_one_sheet(ss, existing, name, headers, rows)
        except Exception:
            logging.getLogger("safehome-crm-sheets").exception(
                "'%s' tab-ის მომზადება ვერ მოხერხდა — ბოტი მაინც განაგრძობს გაშვებას", name
            )


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


def _shift_swaps_ws():
    return _get_spreadsheet().worksheet(config.SHIFT_SWAPS_SHEET_NAME)


def _exclusives_ws():
    return _get_spreadsheet().worksheet(config.EXCLUSIVES_SHEET_NAME)


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


def agent_name_by_id(agent_id: str) -> str:
    """აგენტის სახელი agent_id-ით — რომ ცხრილებში (Tasks/Reports/DayOff/
    Attendance/Warnings/Schedule) id-ის გვერდით ყოველთვის სახელიც ეწეროს
    და ცხრილის ხელით დათვალიერებისას ცხადი იყოს ვისზეა საუბარი."""
    if not agent_id:
        return ""
    for a in get_agents():
        if str(a.get("agent_id")) == str(agent_id):
            return a.get("name", "")
    return ""


def register_agent_chat_id(agent_id: str, chat_id: int, username: str):
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("telegram_chat_id") + 1, str(chat_id))
        ws.update_cell(cell.row, AGENTS_HEADERS.index("telegram_username") + 1, username or "")
        return True


def add_agent(name: str, phone: str, team: str = "") -> str:
    """ადმინი ამატებს ახალ აგენტს (ტელეფონით). აბრუნებს agent_id-ს."""
    with _lock:
        agent_id = uuid.uuid4().hex[:8]
        _agents_ws().append_row([
            agent_id, name, phone, "", "", "yes", _now(), team, "agent", "",
        ])
        return agent_id


def set_agent_team(agent_id: str, team: str) -> bool:
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("team") + 1, team)
        return True


def set_agent_active(agent_id: str, value: str) -> bool:
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("active") + 1, value)
        return True


def set_agent_role(agent_id: str, role: str) -> bool:
    """role: 'agent' / 'team_lead' — თიმლიდერს Mini App-ში ემატება
    საკუთარი გუნდის ფილტრირებული მენეჯერული ხედვაც."""
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("role") + 1, role)
        return True


def set_agent_internal_number(agent_id: str, number: str) -> bool:
    with _lock:
        ws = _agents_ws()
        cell = ws.find(agent_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, AGENTS_HEADERS.index("internal_number") + 1, number)
        return True


def find_agent_by_internal_number(number: str) -> dict | None:
    number = str(number).strip()
    for a in get_agents():
        if str(a.get("internal_number", "")).strip() == number and number:
            return a
    return None


def swap_internal_numbers(agent_id_a: str, agent_id_b: str) -> bool:
    """ორი აგენტის შიდა ნომრების ერთმანეთში გაცვლა."""
    with _lock:
        ws = _agents_ws()
        cell_a = ws.find(agent_id_a, in_column=1)
        cell_b = ws.find(agent_id_b, in_column=1)
        if not cell_a or not cell_b:
            return False
        col = AGENTS_HEADERS.index("internal_number") + 1
        num_a = ws.cell(cell_a.row, col).value or ""
        num_b = ws.cell(cell_b.row, col).value or ""
        ws.update_cell(cell_a.row, col, num_b)
        ws.update_cell(cell_b.row, col, num_a)
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
            agent_name_by_id(assigned_to),
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

def _auto_quality(client_phone: str, actions: str, notes: str, file_id: str) -> int:
    """მარტივი ავტომატური „სისრულის" შეფასება 1-5 — რამდენად სრულადაა
    შევსებული რეპორტი (ტელეფონი/მოქმედება/შენიშვნა/მტკიცებულება).
    ეს არ ცვლის/ანაცვლებს მენეჯერის ხელით შეფასებას (quality_manual)."""
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
        _reports_ws().append_row([
            report_id, agent_id, client_phone, actions, notes,
            file_id, _now(), agent_name_by_id(agent_id), auto_q, "", "",
        ])
        return report_id


def set_report_quality(report_id: str, score: int, rated_by: str) -> bool:
    """მენეჯერის/თიმლიდერის ხელით შეფასება (1-5) — Mini App-იდან."""
    with _lock:
        ws = _reports_ws()
        cell = ws.find(report_id, in_column=1)
        if not cell:
            return False
        ws.update_cell(cell.row, REPORTS_HEADERS.index("quality_manual") + 1, score)
        ws.update_cell(cell.row, REPORTS_HEADERS.index("rated_by") + 1, rated_by)
        return True


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
            agent_name_by_id(agent_id),
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
        row = ([agent_id] + [pattern.get(k, "off") for k in WEEKDAY_KEYS]
               + [_now(), agent_name_by_id(agent_id)])
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
        ws.append_row([
            attendance_id, agent_id, today, mode, _now(), "", "",
            agent_name_by_id(agent_id), "", "", "",
        ])
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


def set_daily_count(agent_id: str, count: int, site: int | None = None,
                     myhome: int | None = None, ssge: int | None = None) -> bool:
    """ინახავს დღეს შეყვანილი განცხადებების რაოდენობას (ყოფილი
    "ანგარიშფაქტურა" ფორმის "შეყვანილი რაოდენობა"). `count` ყოველთვის
    ჯამია; ოფისის ცვლაზე დამატებით ინახება პლატფორმების მიხედვითაც
    (site/myhome/ssge) — ონლაინ დღეზე ეს სამივე ცარიელი რჩება.
    აგენტს უნდა ჰქონდეს დღეს უკვე დაწყებული (/clockin) — მისი სტრიქონი
    Attendance-ში."""
    today = _today_str()
    with _lock:
        ws = _attendance_ws()
        records = ws.get_all_records()
        for idx, r in enumerate(records, start=2):
            if str(r.get("agent_id")) == str(agent_id) and str(r.get("date")) == today:
                ws.update_cell(idx, ATTENDANCE_HEADERS.index("count_submitted") + 1, count)
                if site is not None:
                    ws.update_cell(idx, ATTENDANCE_HEADERS.index("site_count") + 1, site)
                if myhome is not None:
                    ws.update_cell(idx, ATTENDANCE_HEADERS.index("myhome_count") + 1, myhome)
                if ssge is not None:
                    ws.update_cell(idx, ATTENDANCE_HEADERS.index("ssge_count") + 1, ssge)
                return True
        return False


def get_today_attendance_all() -> list[dict]:
    today = _today_str()
    with _lock:
        rows = _attendance_ws().get_all_records()
    return [r for r in rows if str(r.get("date")) == today]


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
        _warnings_ws().append_row([warning_id, agent_id, type_, detail, _now(), agent_name_by_id(agent_id)])

    count = len(get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS))
    deactivated = False
    if count >= config.WARNING_LIMIT:
        set_agent_active(agent_id, "no")
        deactivated = True
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
    """request_type: 'swap_agent' (კონკრეტულ კოლეგასთან) / 'open_swap'
    (ყველასთვის გაგზავნა, ვინც დათანხმდება) / 'change_mode' (საკუთარი
    ცვლის ტიპის შეცვლა — პირს არ სჭირდება)."""
    with _lock:
        swap_id = uuid.uuid4().hex[:8]
        status = "pending_manager" if request_type == "change_mode" else "pending_peer"
        target_name = agent_name_by_id(target_agent_id) if target_agent_id else ""
        _shift_swaps_ws().append_row([
            swap_id, agent_id, agent_name_by_id(agent_id), request_type, from_mode, to_mode,
            target_agent_id, target_name, swap_date, note, status,
            "", "", _now(), "", "",
        ])
        return swap_id


def get_shift_swaps(agent_id: str | None = None, status: str | None = None) -> list[dict]:
    with _lock:
        rows = _shift_swaps_ws().get_all_records()
    if agent_id:
        rows = [
            r for r in rows
            if str(r.get("agent_id")) == str(agent_id) or str(r.get("target_agent_id")) == str(agent_id)
        ]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


def accept_shift_swap(swap_id: str, accepting_agent_id: str) -> dict | None:
    """კოლეგა ეთანხმება ღია/მიმართულ მოთხოვნას — შემდეგ სტატუსი
    გადადის 'pending_manager'-ზე და მენეჯერის დადასტურებას ელოდება."""
    with _lock:
        ws = _shift_swaps_ws()
        cell = ws.find(swap_id, in_column=1)
        if not cell:
            return None
        row = dict(zip(SHIFT_SWAPS_HEADERS, ws.row_values(cell.row)))
        if row.get("status") != "pending_peer":
            return None
        name = agent_name_by_id(accepting_agent_id)
        if row.get("request_type") == "open_swap" and not row.get("target_agent_id"):
            ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("target_agent_id") + 1, accepting_agent_id)
            ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("target_agent_name") + 1, name)
        ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("accepted_by") + 1, accepting_agent_id)
        ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("accepted_by_name") + 1, name)
        ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("status") + 1, "pending_manager")
        return dict(zip(SHIFT_SWAPS_HEADERS, ws.row_values(cell.row)))


def decide_shift_swap(swap_id: str, status: str, decided_by: str) -> dict | None:
    """მენეჯერის საბოლოო გადაწყვეტილება. დამტკიცებისას რეალურად
    იცვლება Schedule-ში შესაბამისი კვირის დღის რეჟიმი(ები) —
    წინააღმდეგ შემთხვევაში (უარყოფა) არაფერი იცვლება."""
    with _lock:
        ws = _shift_swaps_ws()
        cell = ws.find(swap_id, in_column=1)
        if not cell:
            return None
        ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("status") + 1, status)
        ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("decided_at") + 1, _now())
        ws.update_cell(cell.row, SHIFT_SWAPS_HEADERS.index("decided_by") + 1, decided_by)
        row = dict(zip(SHIFT_SWAPS_HEADERS, ws.row_values(cell.row)))

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


# ---------- ექსკლუზივები ("ბინების ბაზა") ----------

def create_exclusive(agent_id: str, fields: dict) -> str:
    with _lock:
        exclusive_id = uuid.uuid4().hex[:8]
        row = []
        for h in EXCLUSIVES_HEADERS:
            if h == "exclusive_id":
                row.append(exclusive_id)
            elif h == "agent_id":
                row.append(agent_id)
            elif h == "agent_name":
                row.append(agent_name_by_id(agent_id))
            elif h == "created_at":
                row.append(_now())
            elif h == "status":
                row.append(fields.get("status") or "active")
            else:
                row.append(fields.get(h, ""))
        _exclusives_ws().append_row(row)
        return exclusive_id


def get_exclusives(agent_id: str | None = None, status: str | None = None) -> list[dict]:
    with _lock:
        rows = _exclusives_ws().get_all_records()
    if agent_id:
        rows = [r for r in rows if str(r.get("agent_id")) == str(agent_id)]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    return rows


# ---------- Mini App დაშბორდის მონაცემები ----------

def quota_for_mode(mode: str) -> int | None:
    """დღიური გეგმა (რაოდენობა) რეჟიმის მიხედვით — ონლაინ და ოფისის
    ცვლას ცალ-ცალკე ლიმიტი აქვს; დასვენების დღეს (off) ლიმიტი არ არის."""
    if mode == "online":
        return config.ONLINE_DAILY_QUOTA
    if mode in ("office_morning", "office_evening"):
        return config.OFFICE_DAILY_QUOTA
    return None


def client_counts(agent_id: str) -> dict:
    """კლიენტების რაოდენობა (დღეს/ჯამურად) — "კლიენტი" აქ ნიშნავს
    აგენტზე მინიჭებულ დავალებას/ლიდს (Tasks), მომხმარებლის
    განმარტებით (და არა /clientreport-ის რეპორტს)."""
    today_str = _today_str()
    agent_tasks = [t for t in get_tasks() if str(t.get("assigned_to")) == str(agent_id)]
    today_count = sum(1 for t in agent_tasks if str(t.get("created_at", "")).startswith(today_str))
    return {"today": today_count, "total": len(agent_tasks)}


def get_agent_dashboard(agent_id: str) -> dict | None:
    """ერთი აგენტის სრული დღევანდელი სურათი — Mini App-ის "ჩემი დღე"
    გვერდისთვის."""
    agent = next((a for a in get_agents() if str(a.get("agent_id")) == str(agent_id)), None)
    if not agent:
        return None
    att = get_today_attendance(agent_id) or {}
    mode = get_today_mode(agent_id)
    perf = get_agent_performance(30).get(str(agent_id), {"assigned": 0, "on_time": 0, "rate": None})
    warns = get_warnings(agent_id=agent_id, days=config.WARNING_WINDOW_DAYS)
    sched = get_agent_schedule(agent_id) or {}
    tasks = get_tasks_for_agent(agent_id, only_open=True)
    meetings = get_meetings(agent_id=agent_id)[-5:][::-1]
    clients = client_counts(agent_id)
    return {
        "agent": {
            "agent_id": agent.get("agent_id", ""),
            "name": agent.get("name", ""),
            "phone": agent.get("phone", ""),
            "team": agent.get("team", ""),
            "active": agent.get("active", "yes"),
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


def get_admin_dashboard(team: str | None = None) -> dict:
    """მთელი გუნდის (ან, თუ `team` მითითებულია — მხოლოდ ერთი გუნდის,
    თიმლიდერის ფილტრირებული ხედვისთვის) დღევანდელი სურათი — Mini
    App-ის მენეჯერის დაშბორდისთვის."""
    agents = get_agents()
    if team:
        agents = [a for a in agents if str(a.get("team", "")).strip() == team.strip()]
    perf = get_agent_performance(30)
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
            "agents_total": len(agents),
            "active_total": sum(1 for a in agents if str(a.get("active", "yes")).lower() != "no"),
            "clocked_in": clocked_in_count,
            "total_submitted": total_submitted,
            "total_quota_target": total_quota_target,
            "quota_missed": quota_missed_count,
            "pending_dayoffs": len(pending_dayoffs),
            "clients_today": clients_today_total,
            "clients_total": clients_all_total,
        },
    }
