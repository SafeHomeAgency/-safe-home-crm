"""
KPI (5 კომპონენტი) და კლიენტის გადაბარება/დადასტურება: დუბლირებული chat_id, განმეორებითი დაჭერა,
მენეჯერის მიმღებები, ვერგაგზავნილი/დაუდასტურებელი კლიენტის ესკალაცია.

გაშვება:  python test_kpi_tasks.py
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
import kpi  # noqa: E402
import task_notify as tn  # noqa: E402

D = datetime.datetime


def _agent(mode="online", name="აგენტი", phone="555111", team="T1", chat=None):
    aid = sp.add_agent(name, phone, team=team)
    sp.register_agent_chat_id(aid, chat or (abs(hash(aid)) % 10**8 + 1000), "u")
    sp.set_agent_schedule(aid, {k: mode for k in sp.WEEKDAY_KEYS})
    return aid


def _srv(day: datetime.date, h: int, m: int = 0) -> str:
    return crm_time.local_to_server_naive(D(day.year, day.month, day.day, h, m)).strftime("%Y-%m-%d %H:%M")


def _att(aid, day, mode, in_hm, out_hm, count):
    ds = day.strftime("%Y-%m-%d")
    sp.db.execute(
        "INSERT INTO attendance (attendance_id, agent_id, date, mode, clock_in, clock_out, count_submitted) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (f"a{aid}{ds}", aid, ds, mode, _srv(day, *in_hm), _srv(day, *out_hm) if out_hm else "", str(count)))


def _noon_today():
    t = crm_time.local_today()
    return D(t.year, t.month, t.day, 12, 0)


def _days_ago(n):
    return crm_time.local_today() - datetime.timedelta(days=n)


# ------------------------------------------------------------------ KPI

def test_kpi_full_marks_and_warning_penalty():
    setup()
    aid = _agent("online")
    for n in (1, 2):
        _att(aid, _days_ago(n), "online", (11, 0), (21, 30), 20)
    k = kpi.compute(3, [aid], now_local=_noon_today())[aid]
    c = k["components"]
    check(c["listings"]["score"] == 1.0 and c["listings"]["value"] == 40 and c["listings"]["target"] == 40, f"განცხადებები 40/40: {c['listings']}")
    check(c["discipline"]["score"] == 1.0, f"დისციპლინა 100%: {c['discipline']}")
    check(c["clients"]["score"] is None, "კლიენტი არ მიუღია — კომპონენტი გამოტოვებულია")
    sp.add_warning(aid, "late_arrival", "t")
    k2 = kpi.compute(3, [aid], now_local=_noon_today())[aid]
    check(abs(k2["components"]["discipline"]["score"] - 0.9) < 1e-6 and k2["warnings"] == 1, f"1 გაფრთხილება = -10 პუნქტი: {k2['components']['discipline']}")
    check(k2["score"] < k["score"], "გაფრთხილება ჯამურ KPI-ს ამცირებს")


def test_kpi_listings_vs_plan_and_late_open_and_missing_close():
    setup()
    aid = _agent("office_morning")
    _att(aid, _days_ago(1), "office_morning", (10, 40), None, 10)          # გვიან გახსნა, არ დაუხურავს, 10/20
    _att(aid, _days_ago(2), "office_morning", (10, 5), (16, 10), 20)        # სრულყოფილი
    k = kpi.compute(3, [aid], now_local=_noon_today())[aid]["components"]
    check(k["listings"]["value"] == 30 and k["listings"]["target"] == 40, f"30/40: {k['listings']}")
    # დღე1: გახსნა 0 + დახურვა 0 = 0; დღე2: 1.0  -> 50%
    check(abs(k["discipline"]["score"] - 0.5) < 1e-6, f"დისციპლინა 50%: {k['discipline']}")


def test_kpi_absent_day_counts_zero_and_off_day_not_counted():
    setup()
    aid = _agent("online")
    _att(aid, _days_ago(1), "online", (11, 0), (21, 0), 20)               # გუშინ იმუშავა; გუშინწინ ცვლა ეკუთვნოდა, არ გამოცხადდა
    k = kpi.compute(3, [aid], now_local=_noon_today())[aid]["components"]
    check(abs(k["discipline"]["score"] - 0.5) < 1e-6, f"გამოუცხადებელი დღე 0-ად: {k['discipline']}")
    off = _agent("off", phone="555222")
    k_off = kpi.compute(3, [off], now_local=_noon_today())[off]
    check(k_off["components"]["listings"]["score"] is None and k_off["components"]["discipline"]["score"] is None,
          "off დღეებზე გეგმა/დისციპლინა არ ეკუთვნის")


def test_kpi_changes_with_period_and_between_agents():
    setup()
    a = _agent("online", name="კარგი", phone="555333")
    b = _agent("online", name="სუსტი", phone="555444")
    for n in (1, 2, 3, 4, 5, 6):
        _att(a, _days_ago(n), "online", (11, 0), (21, 0), 20)
        _att(b, _days_ago(n), "online", (11, 0), (21, 0), 5)
    _att(b, _days_ago(8), "online", (11, 0), (21, 0), 20)
    day = kpi.compute(1, [a, b], now_local=_noon_today())
    month = kpi.compute(30, [a, b], now_local=_noon_today())
    check(month[a]["score"] > month[b]["score"], "კარგი აგენტი უფრო მაღალია — KPI განსხვავდება აგენტებს შორის")
    check(month[b]["components"]["listings"]["value"] != day[b]["components"]["listings"]["value"], "პერიოდის შეცვლა შედეგს ცვლის")
    r = kpi.ranking(month)
    check([x["name"] for x in r][0] == "კარგი", "რეიტინგი KPI-ით დალაგებულია")


def test_kpi_clients_meetings_and_weights():
    setup()
    aid = _agent("online", phone="555555")
    t1 = sp.create_task("კლიენტი 599111222 (ქირა)", "", aid, "მაღალი", "", "admin", lead_type="general", client_phone="599111222", deal_type="ქირა")
    sp.mark_task_seen(t1, aid)
    sp.create_report(aid, "599111222", "დაურეკა", "", "")                       # დამუშავებულია (რეპორტი)
    t2 = sp.create_task("კლიენტი 599333444 (ქირა)", "", aid, "მაღალი", "", "admin", lead_type="general", client_phone="599333444", deal_type="ქირა")  # არც მიღებული, არც დამუშავებული
    k = kpi.compute(7, [aid], now_local=_noon_today())[aid]["components"]
    check(abs(k["clients"]["score"] - 0.5) < 1e-6, f"(1.0 + 0.0)/2 = 50%: {k['clients']}")
    check(k["meetings"]["score"] == 0.0 and k["meetings"]["target"] == 3, f"შეხვედრა 0/3: {k['meetings']}")
    out = kpi.compute(7, [aid], now_local=_noon_today())[aid]
    used = {n: c for n, c in out["components"].items() if c["score"] is not None}
    exp = sum(c["score"] * c["weight"] for c in used.values()) / sum(c["weight"] for c in used.values())
    check(abs(out["score"] - exp) < 1e-3, "ჯამი = წონებით ნორმირებული საშუალო (გამოტოვებული კომპონენტების გარეშე)")


# ------------------------------------------------------------------ კლიენტის გადაბარება/დადასტურება

def test_find_agent_prefers_active_and_duplicate_chat_can_confirm():
    setup()
    old = sp.add_agent("ძველი ჩანაწერი", "555601", team="T1")
    sp.register_agent_chat_id(old, 777001, "u")
    sp.set_agent_active(old, "no")
    new = sp.add_agent("ახალი ჩანაწერი", "555602", team="T1")
    sp.register_agent_chat_id(new, 777001, "u")
    check(sp.find_agent_by_chat_id(777001)["agent_id"] == new, "იმავე chat_id-ზე აქტიური ჩანაწერია არჩეული")
    tid = sp.create_task("კლიენტი", "", old, "მაღალი", "", "admin", client_phone="599000111")
    row = sp.mark_task_seen(tid, new)
    check(row and row["seen"] == "yes", "იმავე ადამიანის სხვა ჩანაწერზე მინიჭებული კლიენტიც დასტურდება")


def test_confirm_idempotent_and_foreign_task_rejected():
    setup()
    a = _agent(phone="555701")
    b = _agent(phone="555702", name="სხვა")
    tid = sp.create_task("კლიენტი", "", a, "მაღალი", "", "admin", client_phone="599000222")
    check(sp.mark_task_seen(tid, b) is None, "სხვა აგენტი ვერ ადასტურებს")
    r1 = sp.mark_task_seen(tid, a)
    r2 = sp.mark_task_seen(tid, a)
    check(r1 and not r1.get("already_seen"), "პირველი დადასტურება")
    check(r2 and r2.get("already_seen"), "განმეორებითი დაჭერა — უკვე დადასტურებული, შეცდომა არაა")
    sp.reassign_task(tid, b)
    check(sp.mark_task_seen(tid, a) is None, "გადაბარების მერე ძველი აგენტი ვეღარ ადასტურებს")
    check(sp.mark_task_seen(tid, b) is not None, "ახალი აგენტი ადასტურებს")


def test_manager_recipients():
    lead = sp.add_agent("ლიდერი", "555801", team="T9")
    sp.register_agent_chat_id(lead, 880001, "u")
    sp.db.execute("UPDATE agents SET role='team_lead' WHERE agent_id=%s", (lead,))
    creator = sp.add_agent("შემქმნელი", "555802", team="T9")
    sp.register_agent_chat_id(creator, 880002, "u")
    ag = sp.add_agent("აგენტი", "555803", team="T9")
    sp.register_agent_chat_id(ag, 880003, "u")
    agents = sp.get_agents()
    agent = next(a for a in agents if a["agent_id"] == ag)
    r = tn.manager_recipients({"created_by": creator}, agent, agents, [111])
    check(set(r) == {880002, 880001}, f"შემქმნელს + თიმლიდერს (ადმინის გარეშე): {r}")
    r = tn.manager_recipients({"created_by": "admin"}, agent, agents, [111])
    check(set(r) == {111, 880001}, f"ადმინის შექმნილზე ადმინს + თიმლიდერს: {r}")
    r = tn.manager_recipients({"created_by": "ghost"}, agent, agents, [111])
    check(111 in r, f"მიუწვდომელი შემქმნელი — ადმინებს მაინც მიუვა: {r}")
    check(len(r) == len(set(r)), "დუბლიკატი მიმღები არ არის")


# ------------------------------------------------------------------ ბოტი: follow-up job

class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup") is not None))


def _bot_mod():
    sys.modules.setdefault("migrate_sheets_to_postgres", types.ModuleType("migrate_sheets_to_postgres"))
    import bot
    bot.sheets = sp
    bot._task_followup_sent.clear()
    return bot


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def _age_task(tid, minutes, notified="yes", seen="no"):
    stamp = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
    sp.db.execute("UPDATE tasks SET updated_at=%s, created_at=%s, notified=%s, seen=%s WHERE task_id=%s",
                  (stamp, stamp, notified, seen, tid))


def test_followups_remind_then_escalate_once():
    setup()
    bot = _bot_mod()
    agent = _agent(phone="555901", chat=991001)
    tid = sp.create_task("კლიენტი 599", "", agent, "მაღალი", "", "admin", client_phone="599555666")
    _age_task(tid, 20)
    ctx = types.SimpleNamespace(bot=_Bot())
    config.ADMIN_CHAT_IDS = [111]
    _run(bot.check_task_followups(ctx))
    check([c for c, _t, _m in ctx.bot.sent] == [991001], f"20 წუთზე მხოლოდ აგენტს შეხსენება: {ctx.bot.sent}")
    check(ctx.bot.sent[0][2], "შეხსენებას ღილაკი აქვს")
    bot.UNCONFIRMED_ESCALATE_MIN = 18        # იგივე დავალება "დაბერდა" ესკალაციის ზღვარს
    _run(bot.check_task_followups(ctx))
    _run(bot.check_task_followups(ctx))
    chats = [c for c, _t, _m in ctx.bot.sent]
    check(chats.count(111) == 1 and chats.count(991001) == 1, f"მენეჯერს ერთი ესკალაცია, აგენტს ერთი შეხსენება: {chats}")


def test_followups_undelivered_alerts_manager_once_and_confirmed_is_silent():
    setup()
    bot = _bot_mod()
    nochat = sp.add_agent("უჩატო", "555902", team="T1")        # ტელეგრამი არ აქვს
    tid = sp.create_task("კლიენტი", "", nochat, "მაღალი", "", "admin", client_phone="599777888")
    _age_task(tid, 12, notified="no")
    seen_agent = _agent(phone="555903", chat=991002)
    tid2 = sp.create_task("კლიენტი2", "", seen_agent, "მაღალი", "", "admin", client_phone="599999000")
    _age_task(tid2, 90, notified="yes", seen="yes")
    ctx = types.SimpleNamespace(bot=_Bot())
    config.ADMIN_CHAT_IDS = [111]
    _run(bot.check_task_followups(ctx))
    _run(bot.check_task_followups(ctx))
    check(len(ctx.bot.sent) == 1 and ctx.bot.sent[0][0] == 111 and "ტელეგრამში არ არის" in ctx.bot.sent[0][1],
          f"ვერგაგზავნილზე მენეჯერს ერთი გაფრთხილება; დადასტურებულზე არაფერი: {ctx.bot.sent}")


def test_assignment_text_has_confirm_and_details():
    txt = tn.assignment_text({"task_id": "x1", "title": "ნახვა: 123", "client_phone": "599", "owner_phone": "598",
                              "viewing_time": "18:00", "description": "დეტალი", "priority": "მაღალი"})
    check("599" in txt and "598" in txt and "18:00" in txt and "დეტალი" in txt and "/done_x1" in txt, "ტექსტში ყველა ველია")
    check(tn.confirm_markup("x1")["inline_keyboard"][0][0]["callback_data"] == "taskseen:x1", "ღილაკის callback")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK  ", name)
            except Exception as e:  # noqa: BLE001
                import traceback
                fails += 1
                print("FAIL", name, "->", repr(e))
                traceback.print_exc()
    print("FAILED:", fails)
    sys.exit(1 if fails else 0)
