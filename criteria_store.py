"""
კლიენტის კრიტერიუმების შენახვა (ცხრილი `ClientCriteria`; იგივე ბექენდის ნიმუში, რაც listings_store/hubmeet_store). წაშლა არ არსებობს — მხოლოდ active=no.
"""

from __future__ import annotations

import datetime
import logging
import threading
import uuid

import contracts_store as _cs
import criteria_model as m
from criteria_model import CriteriaError

log = logging.getLogger("safehome-criteria")
_lock = threading.RLock()


class SheetsBackend(_cs.SheetsBackend):
    def ensure(self) -> None:
        if self._ready:
            return
        sg = self._sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in m.ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        self._ready = True


class MemoryBackend(_cs.MemoryBackend):
    def ensure(self) -> None:
        for name, _h, _r in m.ALL_TABS:
            self.tables.setdefault(name, [])


_backend = SheetsBackend()


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def now_str() -> str:
    import crm_time
    return crm_time.local_now().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")


def all_rows(fresh: bool = False) -> list[dict]:
    return _backend.read(m.CRITERIA_SHEET, fresh=fresh)


def get(criteria_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in all_rows(fresh) if m.s(r.get("criteria_id")) == m.s(criteria_id)), None)


def can_see(row: dict, viewer: dict) -> bool:
    """აგენტი — საკუთარი; თიმლიდერი — თავისი გუნდის; ადმინი — ყველა."""
    if viewer.get("admin"):
        return True
    if viewer.get("agent_id") and m.s(row.get("agent_id")) == m.s(viewer.get("agent_id")):
        return True
    return bool(viewer.get("role") == "team_lead" and m.s(viewer.get("team")) and m.s(row.get("team")) == m.s(viewer.get("team")))


def list_for(viewer: dict, phone: str = "", task_id: str = "", active_only: bool = False) -> list[dict]:
    pk = m.digits(phone)[-9:]
    rows = [r for r in all_rows() if can_see(r, viewer)]
    if pk:
        rows = [r for r in rows if m.digits(r.get("client_phone"))[-9:] == pk]
    if task_id:
        rows = [r for r in rows if m.s(r.get("task_id")) == task_id]
    if active_only:
        rows = [r for r in rows if m.s(r.get("active")).lower() != "no"]
    rows.sort(key=lambda r: m.s(r.get("created_at")), reverse=True)
    return rows


def create(agent: dict, viewer: dict, data: dict) -> dict:
    if not agent and not viewer.get("admin"):
        raise CriteriaError("მხოლოდ დარეგისტრირებული აგენტისთვის", 403)
    fields = m.parse_input(data)
    rec = dict(fields)
    with _lock:
        rows = _backend.read(m.CRITERIA_SHEET, fresh=True)
        # იგივე აგენტის იგივე კლიენტის იგივე კრიტერიუმის ზუსტი განმეორება -> არსებულს ვაბრუნებთ (ორმაგი ბარათი არ იქმნება)
        key = ("deal_type", "budget_min", "budget_max", "districts", "property_type", "area_min", "area_max", "rooms_min", "rooms_max", "bedrooms_min")
        for r in rows:
            if (m.s(r.get("agent_id")) == m.s((agent or {}).get("agent_id")) and m.digits(r.get("client_phone"))[-9:] == m.digits(fields["client_phone"])[-9:]
                    and m.s(r.get("active")).lower() != "no" and all(m.s(r.get(k)) == m.s(fields.get(k)) for k in key)):
                return dict(r, _existing=True)
        rec.update({
            "criteria_id": "C" + uuid.uuid4().hex[:8], "agent_id": m.s((agent or {}).get("agent_id"), 40),
            "agent_name": m.s((agent or {}).get("name"), 80) or ("ადმინი" if viewer.get("admin") else ""),
            "team": m.s((agent or {}).get("team"), 40), "active": "yes", "created_at": now_str(), "updated_at": now_str(), "notified": "",
        })
        _backend.append(m.CRITERIA_SHEET, m.HEADERS, rec)
        return rec


def update(criteria_id: str, viewer: dict, data: dict) -> dict:
    with _lock:
        row = get(criteria_id, fresh=True)
        if not row or not can_see(row, viewer):
            raise CriteriaError("კრიტერიუმი ვერ მოიძებნა", 404)
        if not (viewer.get("admin") or m.s(row.get("agent_id")) == m.s(viewer.get("agent_id")) or viewer.get("role") == "team_lead"):
            raise CriteriaError("შეცვლა მხოლოდ მფლობელ აგენტს/თიმლიდერს/ადმინს შეუძლია", 403)
        fields = m.parse_input(data, existing=row)
        fields["updated_at"] = now_str()
        fields["notified"] = ""          # შეცვლილ კრიტერიუმზე ძველი „უკვე შევატყობინეთ“ სია ბათილია
        _backend.update(m.CRITERIA_SHEET, m.HEADERS, m.s(criteria_id), fields)
        return dict(row, **fields)


def set_active(criteria_id: str, viewer: dict, active: bool) -> dict:
    with _lock:
        row = get(criteria_id, fresh=True)
        if not row or not can_see(row, viewer):
            raise CriteriaError("კრიტერიუმი ვერ მოიძებნა", 404)
        if not (viewer.get("admin") or m.s(row.get("agent_id")) == m.s(viewer.get("agent_id")) or viewer.get("role") == "team_lead"):
            raise CriteriaError("მხოლოდ მფლობელ აგენტს/თიმლიდერს/ადმინს შეუძლია", 403)
        _backend.update(m.CRITERIA_SHEET, m.HEADERS, m.s(criteria_id), {"active": "yes" if active else "no", "updated_at": now_str()})
        return {"criteria_id": m.s(criteria_id), "active": active}


def mark_notified(criteria_id: str, listing_id: str) -> bool:
    """მუდმივი დუბლირების დაცვა: ამ კრიტერიუმზე ამ ბინაზე შეტყობინება უკვე გაიგზავნა (სია გადატვირთვაშიც რჩება). True = ახალია, False = უკვე იყო."""
    with _lock:
        row = get(criteria_id, fresh=True)
        if not row:
            return False
        seen = [x for x in m.s(row.get("notified"), 2000).split(m.SEP) if x]
        if listing_id in seen:
            return False
        seen.append(listing_id)
        _backend.update(m.CRITERIA_SHEET, m.HEADERS, m.s(criteria_id), {"notified": m.SEP.join(seen[-m.MAX_NOTIFIED:])})
        return True
