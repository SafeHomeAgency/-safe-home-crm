"""
ხელშეკრულებების აღრიცხვა — მონაცემთა შენახვა და ბიზნეს-წესები (Google Sheets).

სტრუქტურა crm2_store.py-ს იმეორებს: ცხრილები იქმნება ზარმაცად (`ensure_tabs`), არსებულ ცხრილებს არაფერი ეხება.
ყველა ჩაწერა ხდება **ერთ პროცესულ ბლოკირებაში** (`_lock`) და **ახლად წაკითხული** (არა კეშირებული) მონაცემებით —
ორი ერთდროული მოთხოვნა ვერ გასცემს ერთსა და იმავე ეგზემპლარს და ვერ მიიღებს ერთსა და იმავე ID-ს.
შენიშვნა: Sheets-ს ტრანზაქცია არა აქვს; ბლოკირება მხოლოდ ერთი სერვერის პროცესს იცავს (Railway-ზე ბოტი+ვებ ერთი პროცესია).

შენახვის ფენა (`_backend`) შეიცვლება ტესტში მეხსიერების ვერსიით (`MemoryBackend`).
"""

from __future__ import annotations

import datetime
import json
import logging
import threading

import config
import contracts_model as m
from contracts_model import ContractError

log = logging.getLogger("safehome-contracts")

_lock = threading.RLock()


# ====================================================================== შენახვის ფენები
class SheetsBackend:
    """Google Sheets (sheets_gspread-ის არსებული კლიენტი/კეში/ხელახალი ცდები)."""

    def __init__(self):
        self._ready = False

    @staticmethod
    def _sg():
        import sheets_gspread  # ზარმაცი იმპორტი: Postgres-ის გარემოს არ ეხება
        return sheets_gspread

    def ensure(self) -> None:
        if self._ready:
            return
        sg = self._sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in m.ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        self._ready = True

    def read(self, name: str, fresh: bool = False) -> list[dict]:
        self.ensure()
        sg = self._sg()
        if fresh:
            return sg._worksheet(name).get_all_records(numericise_ignore=["all"])
        return sg._cached_records(name)

    def append(self, name: str, headers: list[str], d: dict) -> None:
        self.ensure()
        sg = self._sg()
        # RAW: Sheets-მა ტექსტი არ "გააგოს" (თარიღი/ტელეფონი/კოდი ზუსტად ისე რჩება, როგორც ჩაიწერა)
        sg._worksheet(name).append_row([str(d.get(h, "")) for h in headers], value_input_option="RAW")
        sg._invalidate(name)

    def update(self, name: str, headers: list[str], id_value: str, changes: dict) -> dict | None:
        self.ensure()
        sg = self._sg()
        ws = sg._worksheet(name)
        cell = ws.find(str(id_value), in_column=1)
        if cell is None:
            return None
        current = dict(zip(headers, (ws.row_values(cell.row) + [""] * len(headers))[: len(headers)]))
        current.update({k: str(v) for k, v in changes.items() if k in headers})
        ws.update(f"A{cell.row}", [[str(current.get(h, "")) for h in headers]], value_input_option="RAW")
        sg._invalidate(name)
        return current


class MemoryBackend:
    """ტესტებისთვის: იგივე ინტერფეისი, ცხრილები — Python სიები."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def ensure(self) -> None:
        for name, _h, _r in m.ALL_TABS:
            self.tables.setdefault(name, [])

    def read(self, name: str, fresh: bool = False) -> list[dict]:
        self.ensure()
        return [dict(r) for r in self.tables[name]]

    def append(self, name: str, headers: list[str], d: dict) -> None:
        self.ensure()
        self.tables[name].append({h: str(d.get(h, "")) for h in headers})

    def update(self, name: str, headers: list[str], id_value: str, changes: dict) -> dict | None:
        self.ensure()
        for r in self.tables[name]:
            if str(r.get(headers[0])) == str(id_value):
                r.update({k: str(v) for k, v in changes.items() if k in headers})
                return dict(r)
        return None


_backend = SheetsBackend()


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


# ====================================================================== დამხმარეები
def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _int(v, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def audit(actor_id, action: str, entity_type: str, entity_id: str, old="", new="") -> None:
    """აუდიტი — მხოლოდ ემატება; წაშლის/შეცვლის ფუნქცია არ არსებობს. ჩავარდნა ძირითად ოპერაციას არ აჩერებს."""
    try:
        def j(x):
            return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, sort_keys=True)
        _backend.append(m.AUDIT_SHEET, m.AUDIT_HEADERS, {
            "event_id": m.new_event_id(), "timestamp": m.now_str(), "actor_id": _s(actor_id),
            "action": action, "entity_type": entity_type, "entity_id": entity_id,
            "old_value": j(old)[:900], "new_value": j(new)[:900],
        })
    except Exception:  # noqa: BLE001
        log.exception("ხელშეკრულებების აუდიტი ვერ ჩაიწერა (%s %s)", action, entity_id)


def get_request(request_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in _backend.read(m.REQUESTS_SHEET, fresh=fresh)
                 if _s(r.get("request_id")) == _s(request_id)), None)


def get_copy(copy_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in _backend.read(m.COPIES_SHEET, fresh=fresh)
                 if _s(r.get("copy_id")) == _s(copy_id)), None)


def get_issue(issue_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in _backend.read(m.ISSUES_SHEET, fresh=fresh)
                 if _s(r.get("issue_id")) == _s(issue_id)), None)


def list_requests() -> list[dict]:
    return _backend.read(m.REQUESTS_SHEET)


def list_copies() -> list[dict]:
    return _backend.read(m.COPIES_SHEET)


def list_issues() -> list[dict]:
    return _backend.read(m.ISSUES_SHEET)


def list_audit(entity_id: str = "", limit: int = 300) -> list[dict]:
    rows = _backend.read(m.AUDIT_SHEET)
    if entity_id:
        rows = [r for r in rows if _s(r.get("entity_id")) == _s(entity_id)]
    return rows[-limit:][::-1]


def is_open_issue(i: dict) -> bool:
    return not _s(i.get("returned_at"))


def stock_by_type() -> dict:
    """{contract_type: {"available": n, "reserved": n, "issued": n, "total": n}}"""
    out = {t: {"available": 0, "reserved": 0, "issued": 0, "total": 0} for t in m.CONTRACT_TYPES}
    for c in list_copies():
        t = _s(c.get("contract_type"))
        if t not in out:
            continue
        out[t]["total"] += 1
        st = _s(c.get("physical_status"))
        if st == m.PH_AVAILABLE:
            out[t]["available"] += 1
        elif st == m.PH_RESERVED:
            out[t]["reserved"] += 1
        elif st == m.PH_ISSUED:
            out[t]["issued"] += 1
    return out


# ====================================================================== ეგზემპლარების რეგისტრაცია (მარაგი)
def register_copies(contract_type: str, quantity: int, actor_id, storage_location: str = "", condition: str = "ახალი") -> list[dict]:
    """ახალი ფიზიკური ეგზემპლარების დამატება მარაგში: თითოეულს ენიჭება უნიკალური Control Code (სერვერზე)."""
    if contract_type not in m.CONTRACT_TYPES:
        raise ContractError("ხელშეკრულების ტიპი არასწორია")
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        raise ContractError("რაოდენობა უნდა იყოს მთელი რიცხვი")
    if qty < 1 or qty > m.MAX_COPIES_PER_BATCH:
        raise ContractError(f"რაოდენობა უნდა იყოს 1–{m.MAX_COPIES_PER_BATCH}")
    with _lock:
        existing_codes = {_s(c.get("control_code")) for c in _backend.read(m.COPIES_SHEET, fresh=True)}
        created = []
        for _ in range(qty):
            code = ""
            for _attempt in range(30):               # collision-ის შემთხვევაში ხელახალი გენერაცია
                cand = m.new_control_code()
                if cand not in existing_codes:
                    code = cand
                    break
            if not code:
                raise ContractError("უნიკალური კოდი ვერ დაგენერირდა — სცადეთ ხელახლა", 500)
            existing_codes.add(code)
            now = m.now_str()
            row = {
                "copy_id": m.new_copy_id(), "control_code": code, "contract_type": contract_type,
                "language_pair": m.CONTRACT_TYPES[contract_type]["language_pair"],
                "physical_status": m.PH_AVAILABLE, "storage_location": _s(storage_location)[:120],
                "condition": _s(condition)[:120], "created_at": now, "created_by": _s(actor_id),
                "active_issue_id": "", "reserved_request_id": "", "updated_at": now, "last_outcome": "",
            }
            _backend.append(m.COPIES_SHEET, m.COPIES_HEADERS, row)
            created.append(row)
            audit(actor_id, "copy_registered", "copy", row["copy_id"], "", {"code": code, "type": contract_type})
        return created


# ====================================================================== მოთხოვნები
def create_request(*, meeting: dict, agent: dict | None, actor_id, contract_type: str, copy_count,
                   notes: str = "", idempotency_key: str = "", client_id: str = "") -> tuple[dict, bool]:
    """ქმნის მოთხოვნას შეხვედრიდან. აბრუნებს (მოთხოვნა, ახალია?).
    განმეორებითი გაგზავნა იგივე idempotency_key-ით (ან იგივე შეხვედრა+ტიპი+რაოდენობა 2 წუთში) — ახალს არ ქმნის."""
    if contract_type not in m.CONTRACT_TYPES:
        raise ContractError("აირჩიეთ ხელშეკრულების ტიპი")
    try:
        n = int(copy_count)
    except (TypeError, ValueError):
        raise ContractError("ეგზემპლარების რაოდენობა უნდა იყოს მთელი რიცხვი")
    if n < 1 or n > m.MAX_COPIES_PER_REQUEST:
        raise ContractError(f"ეგზემპლარების რაოდენობა უნდა იყოს 1–{m.MAX_COPIES_PER_REQUEST}")
    notes = _s(notes)
    if len(notes) > m.MAX_NOTE_LEN:
        raise ContractError(f"კომენტარი ძალიან გრძელია (მაქს. {m.MAX_NOTE_LEN})")
    key = _s(idempotency_key)[:64]
    meeting_id = _s(meeting.get("meeting_id"))
    agent_id = _s(meeting.get("agent_id"))
    with _lock:
        rows = _backend.read(m.REQUESTS_SHEET, fresh=True)
        if key:
            hit = next((r for r in rows if _s(r.get("idempotency_key")) == key), None)
            if hit:
                return hit, False
        cutoff = m.now_local() - datetime.timedelta(minutes=2)
        for r in rows:
            if (_s(r.get("meeting_id")) == meeting_id and _s(r.get("agent_id")) == agent_id
                    and _s(r.get("contract_type")) == contract_type and _int(r.get("copy_count")) == n
                    and _s(r.get("request_status")) == m.REQ_REQUESTED
                    and (m.parse_dt(r.get("request_created_at")) or datetime.datetime.min) >= cutoff):
                return r, False
        used = {_s(r.get("request_id")) for r in rows}
        rid = ""
        for _attempt in range(30):
            cand = m.new_request_id()
            if cand not in used:
                rid = cand
                break
        if not rid:
            raise ContractError("მოთხოვნის ნომერი ვერ დაგენერირდა — სცადეთ ხელახლა", 500)
        prop_id = _s(meeting.get("myhome_id")) or _s(meeting.get("ssge_id"))
        mdt = (_s(meeting.get("meeting_date")) + " " + _s(meeting.get("time"))).strip()
        now = m.now_str()
        row = {
            "request_id": rid, "meeting_id": meeting_id, "client_id": _s(client_id),
            "client_phone": _s(meeting.get("client_phone")), "property_id": prop_id,
            "property_address": _s(meeting.get("address")),
            "agent_id": agent_id, "agent_name": _s((agent or {}).get("name")) or _s(meeting.get("agent_name")),
            "contract_type": contract_type, "copy_count": str(n), "request_created_at": now,
            "requested_return_due_at": "", "request_status": m.REQ_REQUESTED, "approved_by": "", "notes": notes,
            "language_pair": m.CONTRACT_TYPES[contract_type]["language_pair"],
            "team": _s((agent or {}).get("team")), "meeting_datetime": mdt,
            "myhome_id": _s(meeting.get("myhome_id")), "ssge_id": _s(meeting.get("ssge_id")),
            "issued_count": "0", "approved_at": "", "idempotency_key": key, "updated_at": now, "cancelled_reason": "",
        }
        _backend.append(m.REQUESTS_SHEET, m.REQUESTS_HEADERS, row)
        audit(actor_id, "request_created", "request", rid, "", {
            "meeting_id": meeting_id, "type": contract_type, "copies": n, "agent_id": agent_id})
        return row, True


def _set_request(request_id: str, changes: dict) -> dict | None:
    changes = dict(changes)
    changes["updated_at"] = m.now_str()
    return _backend.update(m.REQUESTS_SHEET, m.REQUESTS_HEADERS, request_id, changes)


def _set_copy(copy_id: str, changes: dict) -> dict | None:
    changes = dict(changes)
    changes["updated_at"] = m.now_str()
    return _backend.update(m.COPIES_SHEET, m.COPIES_HEADERS, copy_id, changes)


def approve_request(request_id: str, actor_id, actor_name: str) -> dict:
    """REQUESTED -> APPROVED. ამავდროულად ცდილობს ხელმისაწვდომი ეგზემპლარების დაჯავშნას (RESERVED) — არსებული მარაგის ფარგლებში."""
    with _lock:
        req = get_request(request_id, fresh=True)
        if not req:
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        if _s(req.get("request_status")) != m.REQ_REQUESTED:
            raise ContractError("მოთხოვნა უკვე დამუშავებულია (სტატუსი: %s)" % m.REQUEST_STATUSES.get(_s(req.get("request_status")), ""), 409)
        need = _int(req.get("copy_count"))
        reserved = 0
        for c in _backend.read(m.COPIES_SHEET, fresh=True):
            if reserved >= need:
                break
            if (_s(c.get("contract_type")) == _s(req.get("contract_type")) and _s(c.get("physical_status")) == m.PH_AVAILABLE
                    and not _s(c.get("active_issue_id"))):
                _set_copy(c["copy_id"], {"physical_status": m.PH_RESERVED, "reserved_request_id": request_id})
                audit(actor_id, "copy_reserved", "copy", c["copy_id"], m.PH_AVAILABLE, {"request": request_id, "status": m.PH_RESERVED})
                reserved += 1
        new = _set_request(request_id, {"request_status": m.REQ_APPROVED, "approved_by": _s(actor_name) or _s(actor_id),
                                        "approved_at": m.now_str()})
        audit(actor_id, "request_approved", "request", request_id, m.REQ_REQUESTED, {"status": m.REQ_APPROVED, "reserved": reserved})
        new["_reserved"] = reserved
        return new


def cancel_request(request_id: str, actor_id, reason: str = "") -> dict:
    """გაუქმება: მხოლოდ გაუცემელ მოთხოვნას (REQUESTED/APPROVED). დაჯავშნილი ეგზემპლარები თავისუფლდება."""
    with _lock:
        req = get_request(request_id, fresh=True)
        if not req:
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        old = _s(req.get("request_status"))
        if old not in m.CANCELLABLE_REQUEST:
            raise ContractError("გაცემულ ან დასრულებულ მოთხოვნას ვერ გააუქმებთ", 409)
        released = 0
        for c in _backend.read(m.COPIES_SHEET, fresh=True):
            if _s(c.get("physical_status")) == m.PH_RESERVED and _s(c.get("reserved_request_id")) == request_id:
                _set_copy(c["copy_id"], {"physical_status": m.PH_AVAILABLE, "reserved_request_id": ""})
                audit(actor_id, "copy_released", "copy", c["copy_id"], m.PH_RESERVED, m.PH_AVAILABLE)
                released += 1
        new = _set_request(request_id, {"request_status": m.REQ_CANCELLED, "cancelled_reason": _s(reason)[:300]})
        audit(actor_id, "request_cancelled", "request", request_id, old, {"status": m.REQ_CANCELLED, "released": released})
        return new


def _recompute_request(request_id: str, actor_id) -> dict | None:
    """მოთხოვნის სტატუსის გადათვლა აქტიური/დახურული Issue ჩანაწერებიდან (არა ხელით)."""
    req = get_request(request_id, fresh=True)
    if not req or _s(req.get("request_status")) in (m.REQ_CANCELLED, m.REQ_REQUESTED):
        return req
    issues = [i for i in _backend.read(m.ISSUES_SHEET, fresh=True) if _s(i.get("request_id")) == request_id]
    issued_n = len(issues)
    open_n = sum(1 for i in issues if is_open_issue(i))
    need = _int(req.get("copy_count"))
    if issued_n == 0:
        status = m.REQ_APPROVED
    elif issued_n >= need and open_n == 0:
        status = m.REQ_COMPLETED
    elif issued_n >= need:
        status = m.REQ_ISSUED
    else:
        status = m.REQ_PARTIAL
    old = _s(req.get("request_status"))
    if status != old or _int(req.get("issued_count")) != issued_n:
        req = _set_request(request_id, {"request_status": status, "issued_count": str(issued_n)})
        if status != old:
            audit(actor_id, "request_status_changed", "request", request_id, old, status)
    return req


def close_remaining(request_id: str, actor_id) -> dict:
    """ნაწილობრივ გაცემულ მოთხოვნაზე დარჩენილის გაუქმება: copy_count = უკვე გაცემული; დაბრუნების შემდეგ — COMPLETED."""
    with _lock:
        req = get_request(request_id, fresh=True)
        if not req:
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        if _s(req.get("request_status")) != m.REQ_PARTIAL:
            raise ContractError("ეს მოქმედება მხოლოდ ნაწილობრივ გაცემულ მოთხოვნაზეა", 409)
        issued_n = _int(req.get("issued_count"))
        for c in _backend.read(m.COPIES_SHEET, fresh=True):
            if _s(c.get("physical_status")) == m.PH_RESERVED and _s(c.get("reserved_request_id")) == request_id:
                _set_copy(c["copy_id"], {"physical_status": m.PH_AVAILABLE, "reserved_request_id": ""})
        _set_request(request_id, {"copy_count": str(issued_n)})
        audit(actor_id, "request_remaining_closed", "request", request_id, req.get("copy_count"), str(issued_n))
        return _recompute_request(request_id, actor_id)


# ====================================================================== გაცემა
def issue_copies(request_id: str, copy_ids: list, actor_id, actor_name: str = "", due_at: str = "", notes: str = "") -> list[dict]:
    """ფიზიკური გაცემის დადასტურება (მხოლოდ უფლებამოსილი თანამშრომელი — API-ზე მოწმდება).
    ყოველი ეგზემპლარისთვის იქმნება ცალკე Issue ჩანაწერი. ორმაგი გაცემა დაბლოკილია."""
    ids = []
    for x in (copy_ids or []):
        if _s(x) and _s(x) not in ids:
            ids.append(_s(x))
    if not ids:
        raise ContractError("აირჩიეთ გასაცემი ეგზემპლარი")
    due = None
    if _s(due_at):
        due = m.parse_dt(due_at)
        if not due:
            raise ContractError("დაბრუნების ვადა არასწორია")
        if due <= m.now_local():
            raise ContractError("დაბრუნების ვადა უნდა იყოს მომავალში")
    else:
        due = m.now_local() + datetime.timedelta(hours=config.CONTRACT_DEFAULT_RETURN_HOURS)
    with _lock:
        req = get_request(request_id, fresh=True)
        if not req:
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        if _s(req.get("request_status")) not in m.ISSUABLE_REQUEST:
            raise ContractError("გაცემა შეიძლება მხოლოდ დამტკიცებულ მოთხოვნაზე", 409)
        remaining = _int(req.get("copy_count")) - _int(req.get("issued_count"))
        if len(ids) > remaining:
            raise ContractError(f"ამ მოთხოვნაზე კიდევ მხოლოდ {remaining} ეგზემპლარის გაცემაა შესაძლებელი", 409)
        copies = {_s(c.get("copy_id")): c for c in _backend.read(m.COPIES_SHEET, fresh=True)}
        checked = []
        for cid in ids:
            c = copies.get(cid)
            if not c:
                raise ContractError("ეგზემპლარი ვერ მოიძებნა", 404)
            if _s(c.get("contract_type")) != _s(req.get("contract_type")):
                raise ContractError(f"ეგზემპლარი {c.get('control_code')} სხვა ტიპისაა", 409)
            st = _s(c.get("physical_status"))
            ok = st == m.PH_AVAILABLE or (st == m.PH_RESERVED and _s(c.get("reserved_request_id")) == request_id)
            if not ok or _s(c.get("active_issue_id")):
                raise ContractError(f"ეგზემპლარი {c.get('control_code')} გასაცემად მიუწვდომელია (სტატუსი: {m.PHYSICAL_STATUSES.get(st, st)})", 409)
            checked.append(c)
        out = []
        for c in checked:
            now = m.now_str()
            issue = {
                "issue_id": m.new_issue_id(), "copy_id": c["copy_id"], "request_id": request_id,
                "meeting_id": _s(req.get("meeting_id")), "agent_id": _s(req.get("agent_id")),
                "issued_by": _s(actor_name) or _s(actor_id), "issued_at": now, "due_at": m.fmt(due),
                "returned_at": "", "received_by": "", "return_condition": "", "return_reason": "", "outcome": "",
                "notes": _s(notes)[:m.MAX_NOTE_LEN], "control_code": _s(c.get("control_code")),
                "agent_name": _s(req.get("agent_name")), "signed_contract_number": "", "reminder_sent_at": "",
                "overdue_notified_at": "", "contract_type": _s(req.get("contract_type")),
                "client_phone": _s(req.get("client_phone")), "property_address": _s(req.get("property_address")),
            }
            # თანმიმდევრობა: ჯერ ისტორია, მერე ეგზემპლარი, მერე მოთხოვნა — ჩავარდნისას აუდიტში ჩანს რა დარჩა შუაში
            _backend.append(m.ISSUES_SHEET, m.ISSUES_HEADERS, issue)
            try:
                _set_copy(c["copy_id"], {"physical_status": m.PH_ISSUED, "active_issue_id": issue["issue_id"],
                                         "reserved_request_id": ""})
            except Exception:
                audit(actor_id, "issue_copy_update_failed", "issue", issue["issue_id"], "", c["copy_id"])
                raise
            audit(actor_id, "copy_issued", "copy", c["copy_id"], _s(c.get("physical_status")),
                  {"issue": issue["issue_id"], "request": request_id, "agent_id": issue["agent_id"], "due": issue["due_at"]})
            out.append(issue)
        _recompute_request(request_id, actor_id)
        return out


# ====================================================================== დაბრუნება
def return_issue(issue_id: str, actor_id, actor_name: str, *, outcome: str, reusable: bool = False,
                 condition: str = "", reason: str = "", notes: str = "", signed_number: str = "") -> dict:
    """დაბრუნების რეგისტრაცია (მხოლოდ უფლებამოსილი თანამშრომელი). ხურავს **კონკრეტულ** Issue ჩანაწერს.
    გამოუყენებელი + სუფთა + ხელახლა გამოსაყენებელი -> AVAILABLE; სხვა შემთხვევაში UNDER_REVIEW / საბოლოო სტატუსი."""
    if outcome not in (m.OUT_UNUSED, m.OUT_SIGNED, m.OUT_DAMAGED, m.OUT_LOST):
        raise ContractError("დაბრუნების შედეგი არასწორია")
    with _lock:
        issue = get_issue(issue_id, fresh=True)
        if not issue:
            raise ContractError("გაცემის ჩანაწერი ვერ მოიძებნა", 404)
        if not is_open_issue(issue):
            raise ContractError("ეს ეგზემპლარი უკვე დაბრუნებულია", 409)
        copy = get_copy(issue["copy_id"], fresh=True)
        if not copy:
            raise ContractError("ეგზემპლარი ვერ მოიძებნა", 404)
        now = m.now_str()
        old_status = _s(copy.get("physical_status"))
        final_outcome = outcome
        changes = {"active_issue_id": "", "reserved_request_id": "", "last_outcome": outcome}
        if outcome == m.OUT_UNUSED:
            if reusable and _s(condition).lower() not in ("damaged", "dirty"):
                # დაბრუნდა გამოუყენებელი და შემოწმებულია -> RETURNED_UNUSED (მოვლენა), მერე AVAILABLE
                audit(actor_id, "copy_status_changed", "copy", copy["copy_id"], old_status, m.PH_RETURNED_UNUSED)
                changes["physical_status"] = m.PH_AVAILABLE
                audit(actor_id, "copy_status_changed", "copy", copy["copy_id"], m.PH_RETURNED_UNUSED, m.PH_AVAILABLE)
            else:
                # კლიენტის მონაცემი/ხელმოწერა/დაზიანება/გაურკვეველი — ხელახლა გაცემა შემოწმებამდე აკრძალულია
                changes["physical_status"] = m.PH_UNDER_REVIEW
                final_outcome = m.OUT_UNDER_REVIEW
        elif outcome == m.OUT_SIGNED:
            changes["physical_status"] = m.PH_USED_SIGNED
        elif outcome == m.OUT_DAMAGED:
            changes["physical_status"] = m.PH_DAMAGED
        else:
            changes["physical_status"] = m.PH_LOST
        if _s(condition):
            changes["condition"] = _s(condition)[:120]
        new_copy = _set_copy(copy["copy_id"], changes)
        new_issue = _backend.update(m.ISSUES_SHEET, m.ISSUES_HEADERS, issue_id, {
            "returned_at": now, "received_by": _s(actor_name) or _s(actor_id), "return_condition": _s(condition)[:120],
            "return_reason": _s(reason)[:300], "outcome": final_outcome, "notes": _s(notes)[:m.MAX_NOTE_LEN] or _s(issue.get("notes")),
            "signed_contract_number": _s(signed_number)[:80],
        })
        audit(actor_id, "copy_returned", "issue", issue_id, {"status": old_status},
              {"outcome": final_outcome, "copy_status": new_copy.get("physical_status") if new_copy else "", "condition": _s(condition)})
        _recompute_request(_s(issue.get("request_id")), actor_id)
        return new_issue


def review_copy(copy_id: str, decision: str, actor_id, note: str = "") -> dict:
    """UNDER_REVIEW ეგზემპლარის გადაწყვეტილება: available / damaged / lost / signed."""
    target = {"available": m.PH_AVAILABLE, "damaged": m.PH_DAMAGED, "lost": m.PH_LOST, "signed": m.PH_USED_SIGNED}.get(decision)
    if not target:
        raise ContractError("გადაწყვეტილება არასწორია")
    with _lock:
        c = get_copy(copy_id, fresh=True)
        if not c:
            raise ContractError("ეგზემპლარი ვერ მოიძებნა", 404)
        if _s(c.get("physical_status")) != m.PH_UNDER_REVIEW:
            raise ContractError("ეგზემპლარი შემოწმების სტატუსში არ არის", 409)
        new = _set_copy(copy_id, {"physical_status": target, "active_issue_id": "", "reserved_request_id": ""})
        audit(actor_id, "copy_reviewed", "copy", copy_id, m.PH_UNDER_REVIEW, {"status": target, "note": _s(note)[:200]})
        return new


# ====================================================================== ვადები / შეხსენებები
def overdue_issues(now: datetime.datetime | None = None) -> list[dict]:
    now = now or m.now_local()
    out = []
    for i in list_issues():
        if is_open_issue(i):
            due = m.parse_dt(i.get("due_at"))
            if due and due < now:
                out.append(i)
    return out


def due_today_issues(now: datetime.datetime | None = None) -> list[dict]:
    now = now or m.now_local()
    out = []
    for i in list_issues():
        if is_open_issue(i):
            due = m.parse_dt(i.get("due_at"))
            if due and due.date() == now.date():
                out.append(i)
    return out


def mark_issue_flag(issue_id: str, field: str) -> None:
    if field in ("reminder_sent_at", "overdue_notified_at"):
        with _lock:
            _backend.update(m.ISSUES_SHEET, m.ISSUES_HEADERS, issue_id, {field: m.now_str()})


def dashboard(issues=None, requests=None, copies=None) -> dict:
    """სარეზერვო/ადმინის მთავარი რიცხვები."""
    copies = copies if copies is not None else list_copies()
    issues = issues if issues is not None else list_issues()
    requests = requests if requests is not None else list_requests()
    now = m.now_local()
    cnt = {k: 0 for k in ("total", "available", "reserved", "issued", "due_today", "overdue", "returned_unused",
                          "signed", "damaged", "lost", "under_review", "in_process")}
    cnt["total"] = len(copies)
    for c in copies:
        st = _s(c.get("physical_status"))
        key = {m.PH_AVAILABLE: "available", m.PH_RESERVED: "reserved", m.PH_ISSUED: "issued", m.PH_USED_SIGNED: "signed",
               m.PH_DAMAGED: "damaged", m.PH_LOST: "lost", m.PH_UNDER_REVIEW: "under_review"}.get(st)
        if key:
            cnt[key] += 1
    for i in issues:
        if is_open_issue(i):
            due = m.parse_dt(i.get("due_at"))
            if due and due < now:
                cnt["overdue"] += 1
            elif due and due.date() == now.date():
                cnt["due_today"] += 1
        elif _s(i.get("outcome")) == m.OUT_UNUSED:
            cnt["returned_unused"] += 1
    cnt["in_process"] = sum(1 for r in requests if _s(r.get("request_status")) in (m.REQ_REQUESTED, m.REQ_APPROVED, m.REQ_PARTIAL))
    return cnt
