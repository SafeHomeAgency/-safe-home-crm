"""
Google Sheets-თან მუშაობის ფენა (gspread-ის დახმარებით).

ცხრილის სტრუქტურა (2 tab):

  Agents:
    agent_id | name | phone | telegram_username | telegram_chat_id | active | registered_at

  Tasks:
    task_id | title | description | assigned_to | status | priority |
    due_date | created_by | created_at | updated_at | notified

  status: New / InProgress / Done
  notified: yes / no  (bot ავსებს ავტომატურად, როცა აგენტს შეატყობინებს)
"""

from __future__ import annotations

import datetime
import json
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
    "notified",
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
                 priority: str, due_date: str, created_by: str) -> str:
    with _lock:
        task_id = uuid.uuid4().hex[:8]
        now = _now()
        _tasks_ws().append_row([
            task_id, title, description, assigned_to, "New",
            priority, due_date, created_by, now, now, "no",
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
