"""
CRM 2.0 (P2) — მონაცემთა შენახვა Google Sheets-ზე (production backend).

განზრახ **ცალკე მოდულია** და არსებულ `sheets_gspread.py`-ს არ ცვლის:
  * ამ მოდულის შემოტანა production-ზე თავისთავად არაფერს ცვლის — ცხრილები იქმნება
    მხოლოდ პირველი გამოყენებისას (`ensure_tabs()`), ძველი ცხრილები უცვლელია;
  * Postgres-ის ბექენდი P2-ში არ გამოიყენება (გადაწყვეტილება: ყველაფერი Sheets-ზე).

შეზღუდვა (იგივე რაც დანარჩენ Sheets-ზე): ჩაწერის "ერთჯერადობა" პროცესის შიგნით RLock-ით
და ახალი (უკეშო) წაკითხვით იცავს დუბლიკატებს; ორ სხვადასხვა პროცესს შორის — best-effort
(Railway-ზე 1 replica). კვოტა: ერთი ჩაწერა = 1 API-ზარი, ამიტომ ბევრი ჩანაწერი
`append_rows`-ით იწერება ერთიანად.
"""

from __future__ import annotations

import datetime
import threading

import crm2_model as m

_lock = threading.RLock()
_ready = False


class Crm2Error(ValueError):
    """მოსალოდნელი ვალიდაციის შეცდომა (არასწორი სტატუსი/ტიპი/თარიღი)."""


def _sg():
    import sheets_gspread  # ზარმაცი იმპორტი: Postgres-ის გარემოს არ ეხება
    return sheets_gspread


def ensure_tabs() -> None:
    """ქმნის CRM 2.0 ცხრილებს, თუ არ არსებობს (ძველებს არ ეხება). იდემპოტენტურია."""
    global _ready
    with _lock:
        sg = _sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in m.ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        _ready = True


def _ws(name: str):
    if not _ready:
        ensure_tabs()
    return _sg()._worksheet(name)


def _read(name: str, fresh: bool = False) -> list[dict]:
    if not _ready:
        ensure_tabs()
    sg = _sg()
    if fresh:
        return sg._worksheet(name).get_all_records(numericise_ignore=["all"])
    return sg._cached_records(name)


def _row(headers: list[str], d: dict) -> list[str]:
    return [str(d.get(h, "")) for h in headers]


def _append(name: str, headers: list[str], d: dict) -> None:
    _ws(name).append_row(_row(headers, d), value_input_option="RAW")
    _sg()._invalidate(name)


def _update_by_id(name: str, headers: list[str], id_value: str, changes: dict) -> dict | None:
    """იმავე ID-ის სტრიქონს ანახლებს (მთლიან სტრიქონს ერთი ზარით). None — ვერ მოიძებნა."""
    ws = _ws(name)
    cell = ws.find(str(id_value), in_column=1)
    if cell is None:
        return None
    current = dict(zip(headers, (ws.row_values(cell.row) + [""] * len(headers))[: len(headers)]))
    current.update({k: str(v) for k, v in changes.items() if k in headers})
    ws.update(f"A{cell.row}", [_row(headers, current)])
    _sg()._invalidate(name)
    return current


# ====================================================================== კლიენტები

def get_client(client_id: str) -> dict | None:
    return next((c for c in _read(m.CLIENTS_SHEET) if c.get("client_id") == client_id), None)


def get_client_by_phone(phone) -> dict | None:
    key = m.normalize_phone(phone)
    if not key:
        return None
    return next(
        (c for c in _read(m.CLIENTS_SHEET) if c.get("phone_norm") == key and c.get("archived") != "yes"),
        None,
    )


def upsert_client(phone, fields: dict | None = None, by: str = "") -> tuple[str, bool]:
    """კლიენტი ტელეფონით: თუ არსებობს (ნორმალიზებული ნომრით) — არაცარიელი ველებით ავსებს
    და აბრუნებს (id, False); თუ არა — ქმნის (id, True). არსებულ არაცარიელ მნიშვნელობას
    **ცარიელით არ ვშლით**."""
    key = m.normalize_phone(phone)
    if not key:
        raise Crm2Error("ტელეფონი აუცილებელია")
    fields = {k: v for k, v in (fields or {}).items() if k in m.CLIENTS_HEADERS}
    if fields.get("status") and fields["status"] not in m.CLIENT_STATUSES:
        raise Crm2Error(f"უცნობი სტატუსი: {fields['status']}")
    with _lock:
        existing = next(
            (c for c in _read(m.CLIENTS_SHEET, fresh=True)
             if c.get("phone_norm") == key and c.get("archived") != "yes"),
            None,
        )
        now = m.utc_now()
        if existing:
            changes = {k: v for k, v in fields.items() if str(v).strip() != ""
                       and k not in ("client_id", "phone_norm", "created_at", "created_by")}
            if changes:
                changes["updated_at"] = now
                _update_by_id(m.CLIENTS_SHEET, m.CLIENTS_HEADERS, existing["client_id"], changes)
            return existing["client_id"], False
        rec = {h: "" for h in m.CLIENTS_HEADERS}
        rec.update(fields)
        rec.update({
            "client_id": m.new_id("cl"), "phone_norm": key, "phone_raw": str(phone).strip(),
            "status": fields.get("status") or "new", "created_at": now, "updated_at": now,
            "created_by": by,
        })
        _append(m.CLIENTS_SHEET, m.CLIENTS_HEADERS, rec)
        return rec["client_id"], True


def update_client(client_id: str, fields: dict) -> dict | None:
    allowed = {k: v for k, v in fields.items()
               if k in m.CLIENTS_HEADERS and k not in ("client_id", "phone_norm", "phone_raw", "created_at", "created_by")}
    if allowed.get("status") and allowed["status"] not in m.CLIENT_STATUSES:
        raise Crm2Error(f"უცნობი სტატუსი: {allowed['status']}")
    allowed["updated_at"] = m.utc_now()
    with _lock:
        return _update_by_id(m.CLIENTS_SHEET, m.CLIENTS_HEADERS, client_id, allowed)


def archive_client(client_id: str) -> bool:
    """რბილი წაშლა (`archived=yes`) — მონაცემი არ იკარგება."""
    return update_client(client_id, {"archived": "yes"}) is not None


def list_clients(agent_id: str | None = None, status: str | None = None,
                 include_archived: bool = False) -> list[dict]:
    rows = _read(m.CLIENTS_SHEET)
    if not include_archived:
        rows = [c for c in rows if c.get("archived") != "yes"]
    if agent_id:
        rows = [c for c in rows if c.get("assigned_agent_id") == str(agent_id)]
    if status:
        rows = [c for c in rows if c.get("status") == status]
    return rows


# ====================================================================== აქტივობები

def add_activity(entity_type: str, entity_id: str, type_: str, summary: str,
                 agent_id: str = "", agent_name: str = "", source_ref: str = "") -> str:
    if entity_type not in m.ACTIVITY_ENTITY_TYPES:
        raise Crm2Error(f"უცნობი entity_type: {entity_type}")
    if type_ not in m.ACTIVITY_TYPES:
        raise Crm2Error(f"უცნობი აქტივობის ტიპი: {type_}")
    if not entity_id:
        raise Crm2Error("entity_id აუცილებელია")
    now = m.utc_now()
    rec = {
        "activity_id": m.new_id("ac"), "entity_type": entity_type, "entity_id": entity_id,
        "type": type_, "summary": summary, "agent_id": agent_id, "agent_name": agent_name,
        "source_ref": source_ref, "created_at": now,
    }
    with _lock:
        _append(m.ACTIVITIES_SHEET, m.ACTIVITIES_HEADERS, rec)
        if entity_type == "client":
            _update_by_id(m.CLIENTS_SHEET, m.CLIENTS_HEADERS, entity_id, {"last_activity_at": now})
    return rec["activity_id"]


def list_activities(entity_type: str, entity_id: str, limit: int = 100) -> list[dict]:
    """ერთი ობიექტის timeline, ახალი პირველი."""
    rows = [a for a in _read(m.ACTIVITIES_SHEET)
            if a.get("entity_type") == entity_type and a.get("entity_id") == entity_id]
    rows.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return rows[:limit]


# ====================================================================== Follow-up-ები

def _norm_due(value: str) -> str:
    """`YYYY-MM-DD` -> იმ დღის ბოლო წუთი თბილისის დროით (19:59:59Z); სრული ISO UTC — ისე რჩება."""
    v = str(value or "").strip()
    try:
        if len(v) == 10:
            datetime.datetime.strptime(v, "%Y-%m-%d")
            return v + "T19:59:59Z"
        datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
        return v
    except ValueError:
        raise Crm2Error("due_at ფორმატი: YYYY-MM-DD ან YYYY-MM-DDTHH:MM:SSZ (UTC)") from None


def create_followup(client_id: str, agent_id: str, due_at: str, next_action: str,
                    agent_name: str = "", by: str = "") -> str:
    if not next_action.strip():
        raise Crm2Error("შემდეგი ქმედება (next_action) აუცილებელია")
    if get_client(client_id) is None:
        raise Crm2Error("კლიენტი ვერ მოიძებნა")
    rec = {
        "followup_id": m.new_id("fu"), "client_id": client_id, "agent_id": str(agent_id),
        "agent_name": agent_name, "due_at": _norm_due(due_at), "next_action": next_action.strip(),
        "status": "open", "done_at": "", "created_at": m.utc_now(), "created_by": by,
    }
    with _lock:
        _append(m.FOLLOWUPS_SHEET, m.FOLLOWUPS_HEADERS, rec)
    return rec["followup_id"]


def close_followup(followup_id: str, status: str = "done") -> dict | None:
    if status not in ("done", "cancelled"):
        raise Crm2Error("status: done / cancelled")
    with _lock:
        cur = next((f for f in _read(m.FOLLOWUPS_SHEET, fresh=True)
                    if f.get("followup_id") == followup_id), None)
        if cur is None or cur.get("status") != "open":
            return None  # უკვე დახურულია / არ არსებობს — განმეორება უვნებელია
        return _update_by_id(m.FOLLOWUPS_SHEET, m.FOLLOWUPS_HEADERS, followup_id,
                             {"status": status, "done_at": m.utc_now()})


def list_followups(agent_id: str | None = None, status: str | None = "open",
                   overdue_only: bool = False, now: str | None = None) -> list[dict]:
    rows = _read(m.FOLLOWUPS_SHEET)
    if agent_id:
        rows = [f for f in rows if f.get("agent_id") == str(agent_id)]
    if status:
        rows = [f for f in rows if f.get("status") == status]
    if overdue_only:
        cutoff = now or m.utc_now()
        rows = [f for f in rows if f.get("status") == "open" and f.get("due_at", "") < cutoff]
    return sorted(rows, key=lambda f: f.get("due_at", ""))


# ====================================================================== მფლობელები / ობიექტები

def upsert_owner(phone, name: str = "", by: str = "", notes: str = "") -> tuple[str, bool]:
    key = m.normalize_phone(phone)
    if not key:
        raise Crm2Error("ტელეფონი აუცილებელია")
    with _lock:
        existing = next((o for o in _read(m.OWNERS_SHEET, fresh=True)
                         if o.get("phone_norm") == key and o.get("archived") != "yes"), None)
        now = m.utc_now()
        if existing:
            ch = {k: v for k, v in (("name", name), ("notes", notes)) if v.strip()}
            if ch:
                ch["updated_at"] = now
                _update_by_id(m.OWNERS_SHEET, m.OWNERS_HEADERS, existing["owner_id"], ch)
            return existing["owner_id"], False
        rec = {h: "" for h in m.OWNERS_HEADERS}
        rec.update({"owner_id": m.new_id("ow"), "phone_norm": key, "phone_raw": str(phone).strip(),
                    "name": name, "notes": notes, "created_at": now, "updated_at": now, "created_by": by})
        _append(m.OWNERS_SHEET, m.OWNERS_HEADERS, rec)
        return rec["owner_id"], True


def create_property(owner_id: str, fields: dict | None = None) -> str:
    fields = {k: v for k, v in (fields or {}).items() if k in m.PROPERTIES_HEADERS}
    if fields.get("status") and fields["status"] not in m.PROPERTY_STATUSES:
        raise Crm2Error(f"უცნობი სტატუსი: {fields['status']}")
    now = m.utc_now()
    rec = {h: "" for h in m.PROPERTIES_HEADERS}
    rec.update(fields)
    rec.update({"property_id": m.new_id("pr"), "owner_id": owner_id,
                "status": fields.get("status") or "active", "created_at": now, "updated_at": now})
    with _lock:
        _append(m.PROPERTIES_SHEET, m.PROPERTIES_HEADERS, rec)
    return rec["property_id"]
