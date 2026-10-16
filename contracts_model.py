"""
ხელშეკრულებების აღრიცხვის მოდული (Contract Management) — მოდელი: სახელები, სვეტები, სტატუსები, კოდების გენერაცია.

მნიშვნელოვანი განსხვავება:
  * Request ID  — ხელშეკრულების **მოთხოვნისთვის** (აგენტი ითხოვს შეხვედრიდან);
  * Control Code — კონკრეტული **ფიზიკური ეგზემპლარისთვის** (შიდა აღრიცხვის კოდი, იურიდიული ხელშეკრულების ნომერი არ არის).
მოთხოვნის სტატუსი და ფიზიკური ეგზემპლარის სტატუსი ერთმანეთში არ ერევა.

ყველა თარიღი/დრო ინახება თბილისის დროით, ფორმატით `YYYY-MM-DD HH:MM` (კითხვა/შედარება ტექსტურადაც სწორია).
"""

from __future__ import annotations

import datetime
import secrets
import uuid

import crm_time

# ---------------------------------------------------------------- ცხრილები (ახალი — არსებულებს არ ეხება)
REQUESTS_SHEET = "ContractRequests"
COPIES_SHEET = "ContractCopies"
ISSUES_SHEET = "ContractIssueHistory"
AUDIT_SHEET = "ContractAuditLog"

REQUESTS_HEADERS = [
    "request_id", "meeting_id", "client_id", "client_phone", "property_id", "property_address",
    "agent_id", "agent_name", "contract_type", "copy_count", "request_created_at",
    "requested_return_due_at", "request_status", "approved_by", "notes",
    # დამატებითი (ბოლოში):
    "language_pair", "team", "meeting_datetime", "myhome_id", "ssge_id", "issued_count", "approved_at",
    "idempotency_key", "updated_at", "cancelled_reason",
]
COPIES_HEADERS = [
    "copy_id", "control_code", "contract_type", "language_pair", "physical_status", "storage_location",
    "condition", "created_at", "created_by", "active_issue_id",
    # დამატებითი (ბოლოში):
    "reserved_request_id", "updated_at", "last_outcome",
]
ISSUES_HEADERS = [
    "issue_id", "copy_id", "request_id", "meeting_id", "agent_id", "issued_by", "issued_at", "due_at",
    "returned_at", "received_by", "return_condition", "return_reason", "outcome", "notes",
    # დამატებითი (ბოლოში):
    "control_code", "agent_name", "signed_contract_number", "reminder_sent_at", "overdue_notified_at",
    "contract_type", "client_phone", "property_address",
]
AUDIT_HEADERS = [
    "event_id", "timestamp", "actor_id", "action", "entity_type", "entity_id", "old_value", "new_value",
]

ALL_TABS = [
    (REQUESTS_SHEET, REQUESTS_HEADERS, 2000),
    (COPIES_SHEET, COPIES_HEADERS, 2000),
    (ISSUES_SHEET, ISSUES_HEADERS, 4000),
    (AUDIT_SHEET, AUDIT_HEADERS, 10000),
]

# ---------------------------------------------------------------- ხელშეკრულების ტიპები
CONTRACT_TYPES = {
    "RENT_KA_RU": {"label": "ქირავნობა — ქართული/რუსული", "language_pair": "ka-ru"},
    "RENT_EN_KA": {"label": "ქირავნობა — ინგლისური/ქართული", "language_pair": "en-ka"},
    "RENT_KA_KA": {"label": "ქირავნობა — ქართული/ქართული", "language_pair": "ka-ka"},
}

# ---------------------------------------------------------------- სტატუსები
# მოთხოვნა
REQ_REQUESTED = "REQUESTED"
REQ_APPROVED = "APPROVED"
REQ_ISSUED = "ISSUED"
REQ_PARTIAL = "PARTIALLY_ISSUED"
REQ_COMPLETED = "COMPLETED"
REQ_CANCELLED = "CANCELLED"
REQUEST_STATUSES = {
    REQ_REQUESTED: "მოთხოვნილია",
    REQ_APPROVED: "დამტკიცებულია",
    REQ_ISSUED: "ეგზემპლარი გაცემულია",
    REQ_PARTIAL: "ნაწილობრივ გაცემულია",
    REQ_COMPLETED: "დასრულებულია",
    REQ_CANCELLED: "გაუქმებულია",
}
# ფიზიკური ეგზემპლარი
PH_AVAILABLE = "AVAILABLE"
PH_RESERVED = "RESERVED"
PH_ISSUED = "ISSUED"
PH_RETURNED_UNUSED = "RETURNED_UNUSED"
PH_USED_SIGNED = "USED_SIGNED"
PH_DAMAGED = "DAMAGED"
PH_LOST = "LOST"
PH_UNDER_REVIEW = "UNDER_REVIEW"
PHYSICAL_STATUSES = {
    PH_AVAILABLE: "ხელმისაწვდომია",
    PH_RESERVED: "დაჯავშნილია",
    PH_ISSUED: "აგენტთანაა",
    PH_RETURNED_UNUSED: "დაბრუნდა გამოუყენებელი",
    PH_USED_SIGNED: "ხელმოწერილია",
    PH_DAMAGED: "დაზიანებულია",
    PH_LOST: "დაკარგულია",
    PH_UNDER_REVIEW: "საჭიროებს შემოწმებას",
}
# დაბრუნების შედეგი (Issue.outcome)
OUT_UNUSED = "RETURNED_UNUSED"
OUT_SIGNED = "USED_SIGNED"
OUT_DAMAGED = "DAMAGED"
OUT_LOST = "LOST"
OUT_UNDER_REVIEW = "UNDER_REVIEW"
OUTCOMES = {
    OUT_UNUSED: "დაბრუნდა გამოუყენებელი",
    OUT_SIGNED: "ხელმოწერილია/გაფორმდა",
    OUT_DAMAGED: "დაზიანებულია",
    OUT_LOST: "დაკარგულია",
    OUT_UNDER_REVIEW: "შემოწმებას საჭიროებს",
}

# ეგზემპლარი, რომელიც აღარ ბრუნდება მარაგში და მისი ხელახლა გაცემა დაუშვებელია
TERMINAL_PHYSICAL = {PH_USED_SIGNED, PH_DAMAGED, PH_LOST}
# მოთხოვნის სტატუსები, რომლებზეც გაცემა შეიძლება
ISSUABLE_REQUEST = {REQ_APPROVED, REQ_PARTIAL}
# სტატუსები, რომლებზეც გაუქმება შეიძლება (გაცემის შემდეგ — დაბრუნებით ირთვება დასრულება)
CANCELLABLE_REQUEST = {REQ_REQUESTED, REQ_APPROVED}

MAX_COPIES_PER_REQUEST = 10
MAX_COPIES_PER_BATCH = 200
MAX_NOTE_LEN = 1000

# ეგზემპლარის კოდის ანბანი: ორაზროვანი სიმბოლოების გარეშე (0/O, 1/I)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ContractError(ValueError):
    """მოსალოდნელი ვალიდაციის/ბიზნეს-წესის შეცდომა (მესიჯი პირდაპირ მომხმარებელს ეჩვენება)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- დრო
def now_local() -> datetime.datetime:
    return crm_time.local_now().replace(tzinfo=None, second=0, microsecond=0)


def fmt(dt: datetime.datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def now_str() -> str:
    return fmt(now_local())


def parse_dt(value) -> datetime.datetime | None:
    """`YYYY-MM-DD HH:MM` (ან `YYYY-MM-DD`, ან `YYYY-MM-DDTHH:MM`) -> naive datetime (თბილისი)."""
    s = str(value or "").strip().replace("T", " ")
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, f)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- ID-ები და კოდები
def new_request_id() -> str:
    return "CR-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def new_control_code() -> str:
    """`SH-` + 6 კრიპტოგრაფიულად შემთხვევითი სიმბოლო (მაგ. SH-7K4P92)."""
    return "SH-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def new_copy_id() -> str:
    return "CP-" + uuid.uuid4().hex[:12].upper()


def new_issue_id() -> str:
    return "IS-" + uuid.uuid4().hex[:12].upper()


def new_event_id() -> str:
    return "EV-" + uuid.uuid4().hex[:14].upper()


def normalize_phone(value) -> str:
    d = "".join(ch for ch in str(value or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 else d


def mask_phone(value) -> str:
    d = normalize_phone(value)
    return ("•••" + d[-3:]) if d else ""
