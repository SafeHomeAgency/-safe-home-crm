"""
ცვლის წესები და "რომელი გაფრთხილება ეკუთვნის ახლა" — ერთი წყარო.

წესები (თბილისის დრო):
  * office_morning: იხსნება 10:00-ზე, იხურება 16:00-ზე;
  * office_evening: იხსნება 16:00-ზე, იხურება 22:00-ზე;
    ორივეს გახსნაზე მაქსიმუმ ATTENDANCE_GRACE_MINUTES (15 წთ) შეღავათი;
  * online: იხსნება 10:00-ის შემდეგ ნებისმიერ დროს, უნდა დაიხუროს
    REPORT_DEADLINE_HOUR-მდე (22:00); დაგვიანება არ არსებობს;
  * off: არაფერი.

გაფრთხილება მხოლოდ რეალური მდგომარეობიდან გამოითვლება: თუ ცვლა გახსნილია
(Attendance-ში clock_in არსებობს) — "არ გამოცხადდა"/"არ დაუწყია" არასდროს
ეკუთვნის; "დაგვიანება" ეკუთვნის მხოლოდ მაშინ, თუ გახსნის რეალური დრო
დასაშვებ ზღვარს აღემატება. ფუნქციები წმინდაა (ბაზას არ ეხება) — ტესტირებადია.
"""

from __future__ import annotations

import datetime

import config
import crm_time

OFFICE_WINDOWS = {"office_morning": (10, 16), "office_evening": (16, 22)}
ONLINE_OPEN_HOUR = 10

# ერთი და იმავე "არ გამოცხადდა" ამბის ორმაგად ჩაწერის თავიდან ასაცილებლად
# ეს ორი ტიპი ერთმანეთს გამორიცხავს (დღეში ერთი იმ აგენტზე).
ATTENDANCE_TYPES = ("late_arrival", "no_show")


def start_hour(mode: str):
    w = OFFICE_WINDOWS.get(mode)
    return w[0] if w else None


def end_hour(mode: str) -> int | None:
    w = OFFICE_WINDOWS.get(mode)
    if w:
        return w[1]
    if mode == "online":
        return config.REPORT_DEADLINE_HOUR
    return None


def open_deadline(mode: str, day: datetime.datetime) -> datetime.datetime | None:
    """ცვლის გახსნის ბოლო დასაშვები წუთი (შეღავათიანად), `day`-ის თარიღზე."""
    s = start_hour(mode)
    if s is None:
        return None
    return day.replace(hour=s, minute=0, second=0, microsecond=0) + datetime.timedelta(
        minutes=config.ATTENDANCE_GRACE_MINUTES)


def opened_at_local(att: dict | None) -> datetime.datetime | None:
    """Attendance-ის clock_in (სერვერის naive დრო) -> თბილისის naive დრო.
    გახსნილია, მაგრამ დრო ვერ წაიკითხა -> None (გახსნილად მაინც ითვლება)."""
    dt = crm_time.parse_server_dt((att or {}).get("clock_in"))
    return crm_time.server_naive_to_local(dt) if dt else None


def is_opened(att: dict | None) -> bool:
    return bool(att and str(att.get("clock_in") or "").strip())


def is_closed(att: dict | None) -> bool:
    return bool(att and str(att.get("clock_out") or "").strip())


def is_late_open(mode: str, opened_local: datetime.datetime) -> bool:
    """გახსნის დრო აღემატება ცვლის დასაწყისს + შეღავათს? (წუთის სიზუსტით:
    10:15:40 ჯერ კიდევ დროულია.)"""
    dl = open_deadline(mode, opened_local)
    if dl is None:
        return False
    return opened_local.replace(second=0, microsecond=0) > dl


def late_arrival_due(mode: str, att: dict | None, now_local: datetime.datetime) -> str:
    """თუ ახლა "დაგვიანება" ეკუთვნის — აბრუნებს ახსნას (detail), სხვაგვარად ''.
    მხოლოდ ოფისის ცვლებზე."""
    s = start_hour(mode)
    if s is None:
        return ""
    if is_opened(att):
        o = opened_at_local(att)
        if o is not None and is_late_open(mode, o):
            return (f"ცვლა {s}:00-ზე იწყებოდა, გახსნა {o.strftime('%H:%M')}-ზე "
                    f"(დასაშვებია {config.ATTENDANCE_GRACE_MINUTES} წუთამდე)")
        return ""
    dl = open_deadline(mode, now_local)
    end = end_hour(mode)
    if now_local.replace(second=0, microsecond=0) > dl and now_local.hour < end:
        return f"ცვლა {s}:00-ზე იწყებოდა, {now_local.strftime('%H:%M')}-ზეც არ გაუხსნია"
    return ""


def no_show_due(mode: str, att: dict | None, now_local: datetime.datetime) -> bool:
    """"არ გამოცხადდა": ცვლა საერთოდ არ გახსნილა და მისი დახურვის დრო უკვე
    დადგა (ოფისი: 16:00/22:00; ონლაინ: 22:00). გახსნილ ცვლაზე — არასდროს."""
    if mode == "off" or is_opened(att):
        return False
    end = end_hour(mode)
    return end is not None and now_local.hour >= end
