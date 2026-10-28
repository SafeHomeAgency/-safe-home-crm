"""
კლიენტის კრიტერიუმები (Property Hub): ცხრილი `ClientCriteria`, ვალიდაცია. ბინების შესატყვისობა — `matching.py`.

ერთი ჩანაწერი = ერთი აქტიური ძიება კონკრეტული კლიენტისთვის კონკრეტული აგენტის მიერ. კლიენტი ტელეფონით ერთიანდება (როგორც CRM-ში), მაგრამ
ტელეფონი **არ არის** შიდა იდენტიფიკატორი — `criteria_id` არის. ავტომატური გაერთიანება/წაშლა არ არსებობს (მხოლოდ active=no).
"""

from __future__ import annotations

import datetime
import re

CRITERIA_SHEET = "ClientCriteria"

HEADERS = [
    "criteria_id", "client_phone", "client_name", "agent_id", "agent_name", "team", "task_id",
    "deal_type", "budget_min", "budget_max", "districts", "property_type", "area_min", "area_max",
    "rooms_min", "rooms_max", "bedrooms_min", "floor_min", "not_first", "not_last", "pets_needed",
    "min_rent_months", "move_in_date", "notes", "active", "created_at", "updated_at", "notified",
]
ALL_TABS = [(CRITERIA_SHEET, HEADERS, 1000)]

SEP = "|"
MAX_NOTIFIED = 40


class CriteriaError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


def digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _num(v, label: str, lo: float, hi: float) -> str:
    t = s(v, 20).replace(",", ".")
    if not t:
        return ""
    try:
        n = float(t)
    except ValueError:
        raise CriteriaError(f"{label}: არასწორი რიცხვი") from None
    if not lo <= n <= hi:
        raise CriteriaError(f"{label}: {lo:g}–{hi:g}")
    return f"{n:g}"


def _flag(v) -> str:
    return "yes" if str(v).strip().lower() in ("1", "yes", "true", "on") else ""


def parse_input(data: dict, existing: dict | None = None) -> dict:
    """ვალიდირებული ველები (მხოლოდ კრიტერიუმის ველები; მფლობელი/გუნდი/დრო სერვერზე ივსება)."""
    data = data or {}
    out: dict = {}
    phone = s(data.get("client_phone"), 30)
    if existing is None or "client_phone" in data:
        if len(digits(phone)) < 9:
            raise CriteriaError("კლიენტის ტელეფონი სავალდებულოა (მინიმუმ 9 ციფრი)")
        out["client_phone"] = phone
    if existing is None or "client_name" in data:
        out["client_name"] = s(data.get("client_name"), 80)
    out["task_id"] = s(data.get("task_id"), 24) if "task_id" in data or existing is None else s((existing or {}).get("task_id"), 24)
    out["deal_type"] = s(data.get("deal_type"), 40)
    out["budget_min"] = _num(data.get("budget_min"), "ბიუჯეტი (მინ.)", 0, 100_000_000)
    out["budget_max"] = _num(data.get("budget_max"), "ბიუჯეტი (მაქს.)", 0, 100_000_000)
    if out["budget_min"] and out["budget_max"] and float(out["budget_min"]) > float(out["budget_max"]):
        raise CriteriaError("მინიმალური ბიუჯეტი მაქსიმალურზე დიდია")
    raw_d = data.get("districts") or []
    if isinstance(raw_d, str):
        raw_d = [x for x in re.split(r"[|,;]", raw_d)]
    out["districts"] = SEP.join(s(x, 80) for x in list(raw_d)[:12] if s(x, 80) and SEP not in str(x))
    out["property_type"] = s(data.get("property_type"), 40)
    out["area_min"] = _num(data.get("area_min"), "ფართი (მინ.)", 0, 100000)
    out["area_max"] = _num(data.get("area_max"), "ფართი (მაქს.)", 0, 100000)
    if out["area_min"] and out["area_max"] and float(out["area_min"]) > float(out["area_max"]):
        raise CriteriaError("მინიმალური ფართი მაქსიმალურზე დიდია")
    out["rooms_min"] = _num(data.get("rooms_min"), "ოთახები (მინ.)", 0, 30)
    out["rooms_max"] = _num(data.get("rooms_max"), "ოთახები (მაქს.)", 0, 30)
    if out["rooms_min"] and out["rooms_max"] and float(out["rooms_min"]) > float(out["rooms_max"]):
        raise CriteriaError("მინიმალური ოთახობა მაქსიმალურზე დიდია")
    out["bedrooms_min"] = _num(data.get("bedrooms_min"), "საძინებლები (მინ.)", 0, 20)
    out["floor_min"] = _num(data.get("floor_min"), "სართული (მინ.)", 0, 100)
    out["not_first"], out["not_last"] = _flag(data.get("not_first")), _flag(data.get("not_last"))
    out["pets_needed"] = _flag(data.get("pets_needed"))
    out["min_rent_months"] = _num(data.get("min_rent_months"), "ქირავნობის პერიოდი (თვე)", 0, 120)
    mv = s(data.get("move_in_date"), 12)
    if mv:
        try:
            mv = datetime.datetime.strptime(mv[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise CriteriaError("სასურველი თარიღი: ფორმატი წწწწ-თთ-დდ") from None
    out["move_in_date"] = mv
    out["notes"] = s(data.get("notes"), 300)
    meaningful = [out[k] for k in ("deal_type", "budget_max", "budget_min", "districts", "property_type", "area_min", "area_max", "rooms_min", "rooms_max", "bedrooms_min")]
    if not any(meaningful):
        raise CriteriaError("მიუთითეთ მინიმუმ ერთი კრიტერიუმი (გარიგება, ბიუჯეტი, რაიონი, ტიპი, ფართი, ოთახები...)")
    return out


def to_match_dict(row: dict) -> dict:
    """ცხრილის სტრიქონი -> matching.match()-ის კრიტერიუმი (districts — სია)."""
    d = dict(row)
    d["districts"] = [x for x in str(row.get("districts") or "").split(SEP) if x.strip()]
    return d


def project(row: dict) -> dict:
    out = {k: row.get(k, "") for k in HEADERS if k != "notified"}
    out["districts"] = [x for x in str(row.get("districts") or "").split(SEP) if x.strip()]
    out["active"] = str(row.get("active") or "").strip().lower() != "no"
    return out
