"""
ფინანსური ტრეკერი (მხოლოდ დირექტორის უფროსისთვის) — მოდელი: ცხრილები, სვეტები, გამოთვლები, ვალიდაცია.

გამოთვლის წესი (სერვერზე, ერთადერთი სიმართლე; ბრაუზერი მხოლოდ გადახედვას აჩვენებს):
    საკომისიო        = რეალიზაციის ღირებულება × თანამშრომლობის %  (ან ხელით მითითებული თანხა)
    აგენტის ანაზღ.   = საკომისიო × აგენტის %
    თიმლიდერის ანაზღ.= საკომისიო × თიმლიდერის %
    კომპანიის შემოს. = საკომისიო − აგენტის ანაზღ. − თიმლიდერის ანაზღ.
ყველა თანხა ინახება ტექსტად 2 ნიშნით ათწილადის შემდეგ (Decimal, ROUND_HALF_UP). თარიღები — `YYYY-MM-DD`, თვე — `YYYY-MM`.
"""

from __future__ import annotations

import datetime
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

DEALS_SHEET = "FinDeals"
EXPENSES_SHEET = "FinExpenses"
SETTINGS_SHEET = "FinSettings"

DEAL_HEADERS = [
    "deal_id", "invoice_no", "date", "provider", "property_type", "recipient", "recipient_phone", "recipient_pid",
    "cadastral_code", "district", "address", "value", "coop_percent", "commission", "agent_id", "agent_name",
    "agent_percent", "agent_payout", "team_leader", "tl_percent", "tl_payout", "company_income", "contract_expiry",
    "client_phone", "client_name", "client_pid", "remind_report_months", "remind_expiry_days", "currency", "status",
    "notes", "created_at", "updated_at", "created_by", "last_report_reminder", "expiry_reminder_60", "expiry_reminder_30",
    "month", "report_notified",
]
# CSV ექსპორტი: სვეტები შენი ძველი ცხრილის თანმიმდევრობით (ქართული სათაურები)
DEAL_CSV_COLUMNS = [
    ("ინვოისის ნომერი", "invoice_no"), ("თარიღი", "date"), ("მომსახურების გამწევი", "provider"), ("ქონების ტიპი", "property_type"),
    ("მომსახურების მიმღები", "recipient"), ("მომსახურების მიმღების ტელ. ნომერი", "recipient_phone"),
    ("მომსახურების მიმღების პირადი ნომერი", "recipient_pid"), ("ბინის საკადასტრო კოდი", "cadastral_code"), ("რაიონი", "district"),
    ("მისამართი", "address"), ("რეალიზაციის ღირებულება", "value"), ("ვალუტა", "currency"), ("თანამშრომლობის პროცენტი", "coop_percent"),
    ("ანაზღაურება/საკომისიოს სახით", "commission"), ("აგენტი", "agent_name"), ("აგენტის პროცენტი", "agent_percent"),
    ("აგენტის ანაზღაურება", "agent_payout"), ("თიმლიდერი", "team_leader"), ("თიმლიდერის პროცენტი", "tl_percent"),
    ("თიმლიდერის ანაზღაურება", "tl_payout"), ("კომპანიის შემოსავალი", "company_income"), ("კონტრაქტის მოქმედების ვადა", "contract_expiry"),
    ("კლიენტის საკონტაქტო ნომერი", "client_phone"), ("კლიენტის სახელი/გვარი", "client_name"), ("კლიენტის პირადი ნომერი", "client_pid"),
    ("შენიშვნა", "notes"),
]
EXPENSE_CSV_COLUMNS = [
    ("თარიღი", "date"), ("კატეგორია", "category"), ("აღწერა", "description"), ("თანხა", "amount"), ("ვალუტა", "currency"),
    ("განმეორებადი (ყოველთვიური)", "recurring"), ("დასრულების თვე", "until_month"),
]
EXPENSE_HEADERS = [
    "expense_id", "date", "month", "category", "description", "amount", "currency", "recurring", "until_month",
    "status", "created_at", "updated_at", "created_by",
]
SETTINGS_HEADERS = ["key", "value", "updated_at", "updated_by"]

ALL_TABS = [
    (DEALS_SHEET, DEAL_HEADERS, 2000),
    (EXPENSES_SHEET, EXPENSE_HEADERS, 1000),
    (SETTINGS_SHEET, SETTINGS_HEADERS, 50),
]

PROPERTY_TYPES = ["ბინა", "კერძო სახლი", "კომერციული ფართი", "მიწის ნაკვეთი", "სასტუმრო/აპარტამენტი", "სხვა"]
EXPENSE_CATEGORIES = ["ოფისის ქირა", "ხელფასები", "რეკლამა/მარკეტინგი", "MyHome/განცხადებების ბალანსი", "კომუნალური",
                      "ტექნიკა/პროგრამები", "ტრანსპორტი", "გადასახადები", "სხვა"]
CURRENCIES = ("GEL", "USD")
DEAL_ACTIVE, DEAL_DELETED = "active", "deleted"
DEFAULT_REPORT_MONTHS = 2          # რეპორტინგის შეხსენება: ხელშეკრულების დადებიდან ყოველ 2 თვეში
DEFAULT_EXPIRY_DAYS = 60           # ვადის ამოწურვამდე ~2 თვით ადრე (+ მეორე შეხსენება 30 დღით ადრე)

MAX_TEXT = 300
MAX_NOTES = 1500


class FinanceError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ რიცხვები
def D(v, default: Decimal | None = Decimal("0")) -> Decimal | None:
    """'1 200,50' / '1200.5' / '' -> Decimal (ცარიელი -> default)."""
    s = str(v if v is not None else "").strip().replace(" ", "").replace(" ", "")
    if not s:
        return default
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise FinanceError(f"არასწორი რიცხვი: {str(v)[:30]}")


def q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def s2(x: Decimal) -> str:
    return format(q2(x), "f")


def calc(value, coop_percent, agent_percent, tl_percent, commission_override=None) -> dict:
    """აბრუნებს {"commission","agent_payout","tl_payout","company_income"} — Decimal-ებად."""
    val = D(value)
    coop, ap, tp = D(coop_percent), D(agent_percent), D(tl_percent)
    if val < 0:
        raise FinanceError("რეალიზაციის ღირებულება უარყოფითი ვერ იქნება")
    for name, p in (("თანამშრომლობის %", coop), ("აგენტის %", ap), ("თიმლიდერის %", tp)):
        if p < 0 or p > 100:
            raise FinanceError(f"{name} უნდა იყოს 0–100 შუალედში")
    if ap + tp > 100:
        raise FinanceError("აგენტისა და თიმლიდერის პროცენტების ჯამი 100-ს ვერ აღემატება")
    ov = D(commission_override, default=None)
    commission = q2(ov) if ov is not None else q2(val * coop / Decimal(100))
    if commission < 0:
        raise FinanceError("საკომისიო უარყოფითი ვერ იქნება")
    agent_payout = q2(commission * ap / Decimal(100))
    tl_payout = q2(commission * tp / Decimal(100))
    company = q2(commission - agent_payout - tl_payout)
    return {"commission": commission, "agent_payout": agent_payout, "tl_payout": tl_payout, "company_income": company}


# ------------------------------------------------------------------ თარიღები
def parse_date(v, field="თარიღი", required=True) -> datetime.date | None:
    s = str(v or "").strip()
    if not s:
        if required:
            raise FinanceError(f"{field} სავალდებულოა")
        return None
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            continue
    raise FinanceError(f"{field} არასწორია (ფორმატი: წწწწ-თთ-დდ)")


def month_of(d: datetime.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_month(v, field="თვე") -> str:
    s = str(v or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s):
        raise FinanceError(f"{field} არასწორია (ფორმატი: წწწწ-თთ)")
    return s


def month_range(frm: str, to: str) -> list[str]:
    y, m = int(frm[:4]), int(frm[5:7])
    ty, tm = int(to[:4]), int(to[5:7])
    out = []
    while (y, m) <= (ty, tm) and len(out) < 120:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def add_months(d: datetime.date, n: int) -> datetime.date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    import calendar
    return datetime.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(start: datetime.date, today: datetime.date) -> int:
    """სრული თვეები start-იდან today-მდე."""
    n = (today.year - start.year) * 12 + (today.month - start.month)
    if today.day < start.day:
        n -= 1
    return n


# ------------------------------------------------------------------ ID-ები და ტექსტი
def new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:10].upper()


def clean(v, limit=MAX_TEXT) -> str:
    return str(v if v is not None else "").strip()[:limit]
