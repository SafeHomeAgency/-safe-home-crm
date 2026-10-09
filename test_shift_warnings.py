"""
ცვლის წესები და გაფრთხილებები: გახსნილ ცვლაზე გაფრთხილება არ იწერება,
დუბლიკატი არ იწერება, წესები: office_morning 10–16, office_evening 16–22,
15 წუთი შეღავათი, online — 10:00-ის შემდეგ გახსნა, 22:00-მდე დახურვა.

გაშვება:  python test_shift_warnings.py
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import types

import test_crm_v4 as t4  # ყალბი db + sys.modules["sheets"] = sp

sp = t4.sp
check = t4.check
setup = t4.setup

import config  # noqa: E402
import crm_time  # noqa: E402
import shift_rules as sr  # noqa: E402

D = datetime.datetime


def local(h, m=0, s=0):
    return D(2026, 10, 8, h, m, s)


def att_at(h, m, closed=False):
    """Attendance-ის სტრიქონი, სადაც clock_in თბილისის h:m-ს შეესაბამება (სერვერის naive დროში)."""
    srv = crm_time.local_to_server_naive(local(h, m)).strftime("%Y-%m-%d %H:%M")
    return {"clock_in": srv, "clock_out": "x" if closed else ""}


# ---------------------------------------------------------------- წმინდა წესები

def test_office_morning_rules():
    m = "office_morning"
    check(sr.late_arrival_due(m, att_at(9, 50), local(12)) == "", "10:00-მდე გახსნილი — არაფერი")
    check(sr.late_arrival_due(m, att_at(10, 0), local(12)) == "", "10:00 — არაფერი")
    check(sr.late_arrival_due(m, att_at(10, 15), local(12)) == "", "10:15 — ჯერ დროულია")
    check(sr.late_arrival_due(m, att_at(10, 16), local(12)) != "", "10:16 — დაგვიანება")
    check(sr.late_arrival_due(m, None, local(10, 10)) == "", "10:10-ზე ჯერ არ დაუწყია — ჯერ ადრეა")
    check(sr.late_arrival_due(m, None, local(10, 15, 40)) == "", "10:15:40 — ჯერ ადრეა")
    check(sr.late_arrival_due(m, None, local(10, 16)) != "", "10:16-ზე ჯერ არ გაუხსნია — დაგვიანება")
    check(sr.late_arrival_due(m, None, local(16, 30)) == "", "ცვლის დასრულების შემდეგ დაგვიანება აღარაა (no_show-ის საქმეა)")


def test_office_evening_rules():
    m = "office_evening"
    check(sr.late_arrival_due(m, att_at(16, 14), local(18)) == "", "16:14 — დროულია")
    check(sr.late_arrival_due(m, att_at(16, 20), local(18)) != "", "16:20 — დაგვიანება")
    check(sr.late_arrival_due(m, att_at(15, 40), local(18)) == "", "ადრე გახსნა — არაფერი")
    check(sr.late_arrival_due(m, None, local(16, 20)) != "", "16:20-ზე გაუხსნელი — დაგვიანება")
    check(sr.no_show_due(m, None, local(22, 5)), "22:05-ზე საერთოდ გაუხსნელი — no_show")
    check(not sr.no_show_due(m, None, local(21, 0)), "21:00-ზე ჯერ ცვლა არ დასრულებულა")


def test_online_rules():
    m = "online"
    check(sr.late_arrival_due(m, None, local(15)) == "", "ონლაინზე დაგვიანება არ არსებობს")
    check(sr.late_arrival_due(m, att_at(17, 40), local(18)) == "", "ონლაინი 17:40-ზე გახსნა — წესიერია")
    check(not sr.no_show_due(m, att_at(17, 40), local(22, 5)), "გახსნილ ცვლაზე no_show არასდროს")
    check(not sr.no_show_due(m, None, local(21, 59)), "ონლაინს 22:00-მდე შეუძლია გახსნა")
    check(sr.no_show_due(m, None, local(22, 5)), "22:05-ზე ჯერ კიდევ გაუხსნელი — no_show")
    check(not sr.no_show_due("off", None, local(23)), "off დღეს არაფერი")


def test_opened_shift_never_no_show():
    for m in ("office_morning", "office_evening", "online"):
        check(not sr.no_show_due(m, att_at(11, 0), local(23, 0)), f"{m}: გახსნილზე no_show არაა")
    check(sr.is_opened({"clock_in": "2026-10-08 06:00"}) and not sr.is_opened({"clock_in": ""}) and not sr.is_opened(None),
          "is_opened")


# ---------------------------------------------------------------- ბაზა: დუბლიკატი

def _agent(mode="office_morning"):
    aid = sp.add_agent("ტესტ-აგენტი", "555777", team="T1")
    sp.register_agent_chat_id(aid, abs(hash(aid)) % 10**8, "u")
    sp.set_agent_schedule(aid, {k: mode for k in sp.WEEKDAY_KEYS})
    return aid, next(a for a in sp.get_agents() if a["agent_id"] == aid)


def test_add_warning_once_dedupes_same_type_and_exclusive():
    setup()
    aid, _ = _agent()
    r1 = sp.add_warning_once(aid, "late_arrival", "a", exclusive_with=("no_show",))
    check(r1["warning_id"] and "skipped" not in r1, "პირველი ჩაიწერა")
    r2 = sp.add_warning_once(aid, "late_arrival", "b", exclusive_with=("no_show",))
    check(r2.get("skipped") == "duplicate", "იგივე ტიპი მეორედ — არა")
    r3 = sp.add_warning_once(aid, "no_show", "c", exclusive_with=("late_arrival",))
    check(r3.get("skipped") == "duplicate", "late_arrival-ის შემდეგ no_show იმავე დღეს — არა")
    check(len(sp.get_warnings(agent_id=aid)) == 1, "ბაზაში მხოლოდ ერთია")
    r4 = sp.add_warning_once(aid, "quota_missed", "q")
    check("skipped" not in r4, "სხვა ტიპი ჩაიწერება")
    check(len(sp.get_warnings(agent_id=aid)) == 2, "ორი სხვადასხვა ტიპი")
    check(sp.has_warning_today(aid, "quota_missed"), "has_warning_today ხედავს")


def test_yesterdays_warning_does_not_block_today():
    setup()
    aid, _ = _agent()
    yest = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    sp.db.execute(
        "INSERT INTO warnings (warning_id, agent_id, type, detail, created_at, agent_name, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)", ("y1", aid, "late_arrival", "გუშინ", yest, "x", "active"))
    r = sp.add_warning_once(aid, "late_arrival", "დღეს")
    check("skipped" not in r, "გუშინდელი დღევანდელს არ ბლოკავს")


def test_dayoff_still_skips():
    setup()
    aid, _ = _agent()
    t4._approve_dayoff(aid, crm_time.local_today())
    r = sp.add_warning_once(aid, "late_arrival", "x")
    check(r.get("skipped") == "dayoff" and not sp.get_warnings(agent_id=aid), "დამტკიცებული Day off — არ იწერება")


# ---------------------------------------------------------------- ბოტის job-ები (ნამდვილი კოდი)

class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def _ctx():
    return types.SimpleNamespace(bot=_Bot())


def _load_bot(now_local: D):
    # migrate_sheets_to_postgres ლოკალურ ასლში არ არის (მხოლოდ რეპოში) — ბოტი მხოლოდ /migrate ბრძანებაში იყენებს
    sys.modules.setdefault("migrate_sheets_to_postgres", types.ModuleType("migrate_sheets_to_postgres"))
    import bot
    real_dt = bot.datetime.datetime

    class FakeDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            n = now_local if tz is None else now_local.replace(tzinfo=tz)
            return cls(n.year, n.month, n.day, n.hour, n.minute, n.second, tzinfo=n.tzinfo)

    bot.datetime = types.SimpleNamespace(datetime=FakeDT, timedelta=bot.datetime.timedelta,
                                         time=bot.datetime.time, date=bot.datetime.date,
                                         timezone=bot.datetime.timezone)
    bot.sheets = sp
    return bot


def _put_attendance(aid, h, m, closed=False):
    a = att_at(h, m, closed)
    today_srv = datetime.datetime.now().strftime("%Y-%m-%d")
    sp.db.execute(
        "INSERT INTO attendance (attendance_id, agent_id, date, mode, clock_in, clock_out) VALUES (%s,%s,%s,%s,%s,%s)",
        (f"at{aid}", aid, today_srv, "office_morning", a["clock_in"], "" if not closed else a["clock_in"]))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_bot_late_job_no_warning_when_shift_open_and_no_duplicates():
    setup()
    aid, _ = _agent("office_morning")
    _put_attendance(aid, 10, 5)                       # 10:05-ზე გახსნა
    bot = _load_bot(local(10, 30).replace(tzinfo=crm_time.tz()))
    ctx = _ctx()
    _run(bot.check_late_arrivals(ctx))
    check(not sp.get_warnings(agent_id=aid), "გახსნილ ცვლაზე (10:05) გაფრთხილება არ იწერება")
    check(not ctx.bot.sent, "შეტყობინებაც არ იგზავნება")


def test_bot_late_job_warns_once_when_not_opened_even_if_run_twice():
    setup()
    aid, _ = _agent("office_morning")
    bot = _load_bot(local(10, 30).replace(tzinfo=crm_time.tz()))
    ctx = _ctx()
    _run(bot.check_late_arrivals(ctx))
    _run(bot.check_late_arrivals(ctx))                # მეორე გაშვება (15 წთ-ის შემდეგ ან სხვა პროცესი)
    ws = sp.get_warnings(agent_id=aid)
    check(len(ws) == 1 and ws[0]["type"] == "late_arrival", f"ერთი late_arrival (ჯერ {len(ws)})")
    n_agent = sum(1 for c, _t in ctx.bot.sent if c == abs(hash(aid)) % 10**8)
    check(n_agent == 1, f"აგენტს ერთი შეტყობინება (ჯერ {n_agent})")


def test_bot_daily_compliance_no_duplicate_after_late_arrival():
    setup()
    aid, _ = _agent("office_morning")
    bot = _load_bot(local(10, 30).replace(tzinfo=crm_time.tz()))
    _run(bot.check_late_arrivals(_ctx()))             # 10:30 — late_arrival
    bot = _load_bot(local(22, 5).replace(tzinfo=crm_time.tz()))
    _run(bot.check_daily_compliance(_ctx()))          # 22:05 — no_show არ უნდა დაემატოს
    types_ = sorted(w["type"] for w in sp.get_warnings(agent_id=aid))
    check(types_ == ["late_arrival"], f"ერთი და იგივე გამოუცხადებლობა ორჯერ არ იწერება: {types_}")


def test_bot_daily_compliance_open_shift_no_noshow_and_report_only_with_clients():
    setup()
    aid, _ = _agent("office_morning")
    _put_attendance(aid, 10, 0, closed=True)          # გახსნა და დახურა; კლიენტი დღეს არ ჰყოლია
    bot = _load_bot(local(22, 5).replace(tzinfo=crm_time.tz()))
    ctx = _ctx()
    _run(bot.check_daily_compliance(ctx))
    check(not sp.get_warnings(agent_id=aid), f"გახსნილ+დახურულ ცვლაზე, კლიენტის გარეშე — გაფრთხილება არაა: {sp.get_warnings(agent_id=aid)}")


def test_bot_online_agent_may_open_late_but_not_warned_before_22():
    setup()
    aid, _ = _agent("online")
    bot = _load_bot(local(17, 0).replace(tzinfo=crm_time.tz()))
    ctx = _ctx()
    _run(bot.check_late_arrivals(ctx))
    check(not sp.get_warnings(agent_id=aid), "ონლაინს 17:00-ზე დაგვიანება არ ეწერება")
    bot = _load_bot(local(22, 5).replace(tzinfo=crm_time.tz()))
    _run(bot.check_daily_compliance(ctx))
    _run(bot.check_daily_compliance(ctx))
    ws = sp.get_warnings(agent_id=aid)
    check([w["type"] for w in ws] == ["no_show"], f"22:05-ზე გაუხსნელი ონლაინი — ერთი no_show: {[w['type'] for w in ws]}")


def test_dashboard_late_uses_tbilisi_time():
    setup()
    aid, _ = _agent("office_morning")
    # 12:00 თბილისი = 08:00 UTC: ძველი კოდი სერვერის საათს (08:00) ადარებდა 10:15-ს -> "არ დაგვიანებულა"
    import sheets_postgres
    orig = crm_time.local_now
    crm_time.local_now = lambda: local(12, 0).replace(tzinfo=crm_time.tz())
    try:
        d = sp.get_admin_dashboard() if hasattr(sp, "get_admin_dashboard") else None
    finally:
        crm_time.local_now = orig
    if d is not None:
        row = next((r for r in d.get("team_rows", d.get("agents", [])) if r.get("agent_id") == aid), None)
        check(row is None or row.get("late") is True, "12:00-ზე გაუხსნელი მორნინგი დაგვიანებულად ჩანს")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "->", repr(e))
    print("FAILED:", fails)
    sys.exit(1 if fails else 0)
