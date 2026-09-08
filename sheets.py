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


def _agents_ws():
    return _get_spreadsheet().worksheet(config.AGENTS_SHEET_NAME)


def _tasks_ws():
    return _get_spreadsheet().worksheet(config.TASKS_SHEET_NAME)


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
