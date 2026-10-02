"""
დროის დამხმარე ფუნქციები.

მნიშვნელოვანი კონტექსტი: ცხრილებში ყველა დრო (`created_at`, `clock_in`
და ა.შ.) იწერება `datetime.datetime.now()`-ით, ანუ **სერვერის ადგილობრივ
დროში** (Railway-ზე ეს UTC-ა), ხოლო ბიზნეს-წესები (თვის დასაწყისი,
დღის საზღვარი, კვირის დასაწყისი) უნდა მუშაობდეს **თბილისის (config.
TIMEZONE) დროით**. ეს მოდული მათ შორის უსაფრთხო გადაყვანას აკეთებს —
სერვერის TZ-ზე დამოკიდებულების გარეშე (offset-ს ყოველ გამოძახებაზე
თავად ითვლის, ამიტომ Railway-ზე TZ-ის შეცვლა არაფერს გააფუჭებს).
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import config

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M"


def tz():
    """თბილისის დროის ზონა. თუ სერვერზე tz-ბაზა არ არის (მინიმალური
    Docker/Windows გარემო, `tzdata` პაკეტის გარეშე), ვეცემით ფიქსირებულ
    UTC+4-ზე — საქართველოში DST არ არის, ამიტომ შედეგი იდენტურია."""
    try:
        return ZoneInfo(config.TIMEZONE)
    except Exception:  # ZoneInfoNotFoundError და ა.შ.
        if str(config.TIMEZONE) == "Asia/Tbilisi":
            return datetime.timezone(datetime.timedelta(hours=4), "Asia/Tbilisi")
        return datetime.timezone.utc


def local_now() -> datetime.datetime:
    """ახლანდელი დრო თბილისში (timezone-aware)."""
    return datetime.datetime.now(tz())


def local_today() -> datetime.date:
    return local_now().date()


def server_offset() -> datetime.timedelta:
    """რამდენით უსწრებს თბილისის დრო სერვერის naive დროს (წუთებამდე
    დამრგვალებული). Railway-ზე (UTC) ეს +4სთ-ია."""
    local_naive = local_now().replace(tzinfo=None)
    server_naive = datetime.datetime.now()
    seconds = (local_naive - server_naive).total_seconds()
    return datetime.timedelta(minutes=round(seconds / 60))


def local_to_server_naive(dt_local_naive: datetime.datetime) -> datetime.datetime:
    """თბილისის (naive) დროის წერტილი -> იგივე მომენტი სერვერის naive
    დროში (ცხრილებში ჩაწერილ timestamp-ებთან შესადარებლად)."""
    return dt_local_naive - server_offset()


def server_naive_to_local(dt_server_naive: datetime.datetime) -> datetime.datetime:
    return dt_server_naive + server_offset()


def parse_server_dt(value) -> datetime.datetime | None:
    """ცხრილის `YYYY-MM-DD HH:MM` ტექსტი -> datetime (სერვერის naive)."""
    try:
        return datetime.datetime.strptime(str(value).strip(), DATETIME_FMT)
    except (ValueError, AttributeError, TypeError):
        return None


def local_month_start_server_naive() -> datetime.datetime:
    """მიმდინარე კალენდარული თვის დასაწყისი (თბილისში, 1 რიცხვი 00:00),
    სერვერის naive დროში."""
    today = local_today()
    return local_to_server_naive(datetime.datetime(today.year, today.month, 1))


def local_day_bounds_server_naive(day: datetime.date | None = None) -> tuple[datetime.datetime, datetime.datetime]:
    """მითითებული (თბილისის) დღის [00:00, მომდევნო 00:00) საზღვრები
    სერვერის naive დროში."""
    day = day or local_today()
    start_local = datetime.datetime(day.year, day.month, day.day)
    start = local_to_server_naive(start_local)
    return start, start + datetime.timedelta(days=1)


def week_start(day: datetime.date | None = None) -> datetime.date:
    """მითითებული დღის კვირის ორშაბათი (თბილისის კალენდარით)."""
    day = day or local_today()
    return day - datetime.timedelta(days=day.weekday())


def parse_user_date(text: str) -> datetime.date | None:
    """აგენტის/მენეჯერის მიერ ხელით აკრეფილი თარიღის ამოცნობა:
    2026-09-15, 15.09.2026, 15/09/2026, 15-09-2026, 15.09.26.
    ვერ ამოიცნო -> None (ხმაურიანი "ხვალ"/"ორშაბათს" ტიპის ტექსტი
    დღეოფის თარიღად არასდროს ჩაითვლება)."""
    s = str(text or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def business_date(moment: datetime.datetime | None = None) -> str:
    """ბიზნეს-დღე (YYYY-MM-DD) თბილისის დროით (Asia/Tbilisi) — არა UTC-ით:
    ახალი ბიზნეს-დღე 00:00-ზე იწყება თბილისში. `moment` — timezone-aware
    datetime (ნაგულისხმევი: ახლა)."""
    m = moment or datetime.datetime.now(datetime.timezone.utc)
    return m.astimezone(tz()).strftime(DATE_FMT)


def business_date_of_server_naive(value) -> str:
    """ცხრილში `_now()`-ით ჩაწერილი (სერვერის naive) დროის ბიზნეს-დღე
    თბილისის დროით; ვერ წაიკითხა -> ცარიელი."""
    dt = parse_server_dt(value)
    return server_naive_to_local(dt).strftime(DATE_FMT) if dt else ""


def iso_utc_now() -> str:
    """ზუსტი UTC timestamp (ISO, წამებით) — GPS/ატენდანსის ივენთებისთვის,
    სადაც დროის ზონებს შორის გაურკვევლობა დაუშვებელია."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_since_utc_iso(value) -> float | None:
    """რამდენი წამი გავიდა `iso_utc_now()`-ით ჩაწერილი დროიდან (None —
    ცარიელი/არასწორი მნიშვნელობა). worker heartbeat-ისთვის."""
    try:
        dt = datetime.datetime.strptime(str(value).strip(), "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - dt.replace(tzinfo=datetime.timezone.utc)).total_seconds()


def utc_iso_to_local(value: str) -> datetime.datetime | None:
    try:
        dt = datetime.datetime.strptime(str(value).strip(), "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=datetime.timezone.utc).astimezone(tz())
