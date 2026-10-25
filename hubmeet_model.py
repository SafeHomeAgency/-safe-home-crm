"""
Safe Home Property Hub — შეხვედრები განცხადებიდან (ერთი ორგანიზმი): მოდელი.

აგენტი კატალოგში ირჩევს ბინას და ნიშნავს შეხვედრას: კლიენტი, გაქირავების პერიოდი, თანამშრომლობის პირობები, მეპატრონის თავისუფალი დრო.
საკუთარ ბინაზე შეხვედრა მაშინვე "planned"-ია; სხვა აგენტის ბინაზე — "pending" (მფლობელი აგენტი/თიმლიდერი ადასტურებს).
დადასტურებისას იქმნება ჩვეულებრივი ჩანაწერი არსებულ `Meetings` ცხრილში (KPI, შეხვედრების ისტორია, ხელშეკრულებები, CRM კლიენტი — უცვლელად
მუშაობს), ხოლო ეს ცხრილი (`HubMeetings`) ინახავს დამატებით დეტალებს და ბმას ბინასთან.

კონფიდენციალურობა: კლიენტის ტელეფონი ჩანს მხოლოდ მომთხოვნ აგენტს, მის თიმლიდერს და ადმინს; მფლობელი აგენტი ხედავს კლიენტის სახელს, პირობებს და დროს.
"""

from __future__ import annotations

import datetime
import re

HUB_MEETINGS_SHEET = "HubMeetings"

HM_HEADERS = [
    "hub_id", "meeting_id", "listing_id", "status", "coop",
    "owner_agent_id", "owner_agent_name", "owner_team", "requester_agent_id", "requester_name", "team",
    "listing_title", "address", "district", "city", "deal_type", "price_usd", "photo", "myhome_id", "ssge_id",
    "client_name", "client_phone", "meeting_date", "meeting_time", "rental_months", "move_in_date", "budget_usd",
    "tenants", "coop_terms", "owner_availability", "notes",
    "outcome", "reject_reason", "history", "created_at", "updated_at", "reminded", "nudged", "task_id",
]
ALL_TABS = [(HUB_MEETINGS_SHEET, HM_HEADERS, 2000)]

PENDING, PLANNED, DONE, CANCELLED, REJECTED, NO_SHOW = "pending", "planned", "done", "cancelled", "rejected", "no_show"
ACTIVE_STATUSES = (PENDING, PLANNED)
STATUS_LABELS = {PENDING: "დასადასტურებელი", PLANNED: "დაგეგმილი", DONE: "ჩატარდა", CANCELLED: "გაუქმდა", REJECTED: "უარყოფილია", NO_SHOW: "არ გამოცხადდა"}
OUTCOMES = {"interested": "დაინტერესდა", "thinking": "ფიქრობს", "refused": "უარი თქვა", "deal": "გარიგება", "other": "სხვა"}

PRIVATE_CLIENT_FIELDS = ("client_phone",)


class HubMeetError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


def digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def norm_phone(v) -> str:
    """ქართული ნომრის ერთიანი ფორმა დუბლიკატის შესამოწმებლად: +995 5xx.. / 0 5xx.. -> 9 ციფრი; სხვა — ციფრები."""
    d = digits(v)
    if d.startswith("995") and len(d) == 12:
        d = d[3:]
    if d.startswith("0") and len(d) == 10:
        d = d[1:]
    return d


def parse_date(v, label: str, required: bool = True) -> str:
    t = s(v, 20)
    if not t:
        if required:
            raise HubMeetError(f"{label} სავალდებულოა")
        return ""
    try:
        return datetime.datetime.strptime(t[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise HubMeetError(f"{label}: ფორმატი უნდა იყოს წწწწ-თთ-დდ") from None


def parse_time(v) -> str:
    t = s(v, 10)
    mm = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not mm or int(mm.group(1)) > 23 or int(mm.group(2)) > 59:
        raise HubMeetError("შეხვედრის დრო სავალდებულოა (სს:წწ)")
    return f"{int(mm.group(1)):02d}:{mm.group(2)}"


def parse_int(v, label: str, lo: int, hi: int) -> str:
    t = s(v, 10)
    if not t:
        return ""
    try:
        n = int(float(t.replace(",", ".")))
    except ValueError:
        raise HubMeetError(f"{label}: არასწორი რიცხვი") from None
    if not lo <= n <= hi:
        raise HubMeetError(f"{label}: {lo}–{hi}")
    return str(n)


def coop_percent(text: str) -> str:
    """თანამშრომლობის პირობებიდან პროცენტი ('50/50', 'აგენტთან 50%') ძველი ცხრილის 'percent' სვეტისთვის; ვერ ვპოულობთ — ცარიელი."""
    t = str(text or "")
    mm = re.search(r"(\d{1,3})\s*%", t)
    if mm:
        return mm.group(1)
    mm = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b", t)
    return mm.group(1) if mm else ""
