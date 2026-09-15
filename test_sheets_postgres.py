"""
ავტომატური ტესტები sheets_postgres.py-სთვის (Phase 1-ის დარჩენილი ნაწილი).

ერთ ფაილშია განგებ ჩატანილი — მარტივად გასაშვები, დამატებითი
ინსტალაციის გარეშე.

როგორ მუშაობს (რატომ არ სჭირდება ნამდვილი Postgres აქ):
  ეს ტესტები `sheets_postgres.py`-ს ნამდვილ, უცვლელ კოდს უშვებენ (არა
  ასლს) — უბრალოდ, `db.py`-ს (რომელიც ნამდვილ production-ზე
  PostgreSQL-თან უკავშირდება) ცვლის მსუბუქი, მეხსიერებაში მომუშავე
  SQLite ვერსიით. ორივე იძლევა ერთნაირ query_all/query_one/execute
  ინტერფეისს, ასე რომ `sheets_postgres.py`-ს ერთი ხაზიც არ სჭირდება
  შეიცვალოს ტესტირებისთვის.

გაშვება (ორივე მუშაობს):
    python3 test_sheets_postgres.py        # პირდაპირ, pytest-ის გარეშე
    pytest test_sheets_postgres.py -v      # თუ pytest დაინსტალირებულია
"""

from __future__ import annotations

import sqlite3
import sys
import types

# --- 1. ავაშენოთ "ყალბი" db მოდული (SQLite-ზე დაფუძნებული) და
#        ჩავანაცვლოთ ნამდვილი db.py, სანამ sheets_postgres.py-ს
#        შემოვიტანთ (import) --------------------------------------

_conn = sqlite3.connect(":memory:")
_conn.row_factory = sqlite3.Row

_TEST_SCHEMA = """
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY, name TEXT DEFAULT '', phone TEXT DEFAULT '',
    telegram_username TEXT DEFAULT '', telegram_chat_id TEXT DEFAULT '',
    active TEXT DEFAULT 'yes', registered_at TEXT DEFAULT '', team TEXT DEFAULT '',
    role TEXT DEFAULT 'agent', internal_number TEXT DEFAULT ''
);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY, title TEXT DEFAULT '', description TEXT DEFAULT '',
    assigned_to TEXT DEFAULT '', status TEXT DEFAULT 'New', priority TEXT DEFAULT '',
    due_date TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '', notified TEXT DEFAULT 'no', lead_type TEXT DEFAULT '',
    client_phone TEXT DEFAULT '', deal_type TEXT DEFAULT '', listing_id TEXT DEFAULT '',
    viewing_time TEXT DEFAULT '', assigned_to_name TEXT DEFAULT ''
);
CREATE TABLE reports (
    report_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', client_phone TEXT DEFAULT '',
    actions TEXT DEFAULT '', notes TEXT DEFAULT '', file_id TEXT DEFAULT '',
    created_at TEXT DEFAULT '', agent_name TEXT DEFAULT '', quality_auto TEXT DEFAULT '',
    quality_manual TEXT DEFAULT '', rated_by TEXT DEFAULT ''
);
CREATE TABLE dayoff (
    request_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', date TEXT DEFAULT '',
    reason TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TEXT DEFAULT '',
    decided_at TEXT DEFAULT '', agent_name TEXT DEFAULT ''
);
CREATE TABLE meetings (
    meeting_id TEXT PRIMARY KEY, timestamp TEXT DEFAULT '', owner_phone TEXT DEFAULT '',
    myhome_link TEXT DEFAULT '', myhome_id TEXT DEFAULT '', ssge_link TEXT DEFAULT '',
    ssge_id TEXT DEFAULT '', condition TEXT DEFAULT '', client_phone TEXT DEFAULT '',
    district TEXT DEFAULT '', address TEXT DEFAULT '', meeting_date TEXT DEFAULT '',
    agent_id TEXT DEFAULT '', agent_name TEXT DEFAULT '', price TEXT DEFAULT '',
    percent TEXT DEFAULT '', time TEXT DEFAULT '', internal_number TEXT DEFAULT '',
    agent_phone TEXT DEFAULT '', team_leader TEXT DEFAULT ''
);
CREATE TABLE schedule (
    agent_id TEXT PRIMARY KEY, mon TEXT DEFAULT 'off', tue TEXT DEFAULT 'off',
    wed TEXT DEFAULT 'off', thu TEXT DEFAULT 'off', fri TEXT DEFAULT 'off',
    sat TEXT DEFAULT 'off', sun TEXT DEFAULT 'off', updated_at TEXT DEFAULT '',
    agent_name TEXT DEFAULT ''
);
CREATE TABLE attendance (
    attendance_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', date TEXT DEFAULT '',
    mode TEXT DEFAULT '', clock_in TEXT DEFAULT '', clock_out TEXT DEFAULT '',
    count_submitted TEXT DEFAULT '', agent_name TEXT DEFAULT '', site_count TEXT DEFAULT '',
    myhome_count TEXT DEFAULT '', ssge_count TEXT DEFAULT ''
);
CREATE TABLE warnings (
    warning_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', type TEXT DEFAULT '',
    detail TEXT DEFAULT '', created_at TEXT DEFAULT '', agent_name TEXT DEFAULT ''
);
CREATE TABLE shift_swaps (
    swap_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', agent_name TEXT DEFAULT '',
    request_type TEXT DEFAULT '', from_mode TEXT DEFAULT '', to_mode TEXT DEFAULT '',
    target_agent_id TEXT DEFAULT '', target_agent_name TEXT DEFAULT '',
    swap_date TEXT DEFAULT '', note TEXT DEFAULT '', status TEXT DEFAULT '',
    accepted_by TEXT DEFAULT '', accepted_by_name TEXT DEFAULT '',
    created_at TEXT DEFAULT '', decided_at TEXT DEFAULT '', decided_by TEXT DEFAULT ''
);
CREATE TABLE exclusives (
    exclusive_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', agent_name TEXT DEFAULT '',
    contact_internal TEXT DEFAULT '', owner_phone TEXT DEFAULT '', property_type TEXT DEFAULT '',
    deal_type TEXT DEFAULT '', building_status TEXT DEFAULT '', condition TEXT DEFAULT '',
    location TEXT DEFAULT '', cadastral_code TEXT DEFAULT '', area TEXT DEFAULT '',
    rooms TEXT DEFAULT '', bedrooms TEXT DEFAULT '', floors_total TEXT DEFAULT '',
    floor_number TEXT DEFAULT '', project_type TEXT DEFAULT '', bathrooms TEXT DEFAULT '',
    balcony TEXT DEFAULT '', price TEXT DEFAULT '', percent TEXT DEFAULT '',
    notes TEXT DEFAULT '', photos TEXT DEFAULT '', status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT ''
);
CREATE TABLE questions (
    question_id TEXT PRIMARY KEY, agent_id TEXT DEFAULT '', agent_name TEXT DEFAULT '',
    team TEXT DEFAULT '', text TEXT DEFAULT '', status TEXT DEFAULT 'open',
    answer TEXT DEFAULT '', answered_by TEXT DEFAULT '', created_at TEXT DEFAULT '',
    answered_at TEXT DEFAULT ''
);
CREATE TABLE exclusive_shares (
    share_id TEXT PRIMARY KEY, exclusive_id TEXT DEFAULT '', from_agent_id TEXT DEFAULT '',
    from_agent_name TEXT DEFAULT '', to_agent_id TEXT DEFAULT '', to_agent_name TEXT DEFAULT '',
    note TEXT DEFAULT '', created_at TEXT DEFAULT ''
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT DEFAULT '',
    actor_agent_id TEXT DEFAULT '', actor_label TEXT DEFAULT '', action TEXT DEFAULT '',
    entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '', old_value TEXT,
    new_value TEXT, source TEXT DEFAULT 'bot'
);
"""


def _reset_db():
    _conn.executescript("""
        DROP TABLE IF EXISTS agents; DROP TABLE IF EXISTS tasks;
        DROP TABLE IF EXISTS reports; DROP TABLE IF EXISTS dayoff;
        DROP TABLE IF EXISTS meetings; DROP TABLE IF EXISTS schedule;
        DROP TABLE IF EXISTS attendance; DROP TABLE IF EXISTS warnings;
        DROP TABLE IF EXISTS shift_swaps; DROP TABLE IF EXISTS exclusives;
        DROP TABLE IF EXISTS questions; DROP TABLE IF EXISTS exclusive_shares;
        DROP TABLE IF EXISTS audit_log;
    """)
    _conn.executescript(_TEST_SCHEMA)
    _conn.commit()


def _fake_query_all(sql, params=()):
    cur = _conn.execute(sql.replace("%s", "?"), params)
    return [dict(r) for r in cur.fetchall()]


def _fake_query_one(sql, params=()):
    cur = _conn.execute(sql.replace("%s", "?"), params)
    row = cur.fetchone()
    return dict(row) if row else None


def _fake_execute(sql, params=()):
    cur = _conn.execute(sql.replace("%s", "?"), params)
    _conn.commit()
    return cur.rowcount


_fake_db_module = types.ModuleType("db")
_fake_db_module.query_all = _fake_query_all
_fake_db_module.query_one = _fake_query_one
_fake_db_module.execute = _fake_execute
_fake_db_module.init_schema = _reset_db
sys.modules["db"] = _fake_db_module

_reset_db()

import sheets_postgres as sp  # noqa: E402  (განზრახ import-ის შემდეგ, ზემოთ)

# ---------------------------------------------------------------------
# დამხმარეები
# ---------------------------------------------------------------------


def setup():
    """ყოველი ტესტის წინ სუფთა ბაზა."""
    _reset_db()


class Fail(AssertionError):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


# ---------------------------------------------------------------------
# ტესტები
# ---------------------------------------------------------------------

def test_add_and_find_agent():
    setup()
    aid = sp.add_agent("გიორგი", "+995555000111", team="Team1")
    check(len(aid) == 8, "agent_id უნდა იყოს 8-სიმბოლოიანი")
    agents = sp.get_agents()
    check(len(agents) == 1, "ერთი აგენტი უნდა იყოს")
    found = sp.find_agent_by_phone("995555000111")
    check(found is not None and found["agent_id"] == aid, "ტელეფონით პოვნა (+/-ის გარეშეც)")
    check(sp.agent_name_by_id(aid) == "გიორგი", "სახელის მოძებნა agent_id-ით")
    check(sp.agent_name_by_id("არარსებული") == "", "არარსებული id -> ცარიელი სტრიქონი")


def test_set_agent_active_and_role_audit():
    setup()
    aid = sp.add_agent("ანა", "555222333")
    ok = sp.set_agent_active(aid, "no")
    check(ok, "დეაქტივაცია უნდა დაბრუნდეს True")
    check(sp.get_agents()[0]["active"] == "no", "active ველი ნამდვილად შეიცვალა")
    sp.set_agent_role(aid, "team_lead")
    check(sp.get_agents()[0]["role"] == "team_lead", "როლი შეიცვალა")
    logs = sp.db.query_all("SELECT * FROM audit_log")
    actions = [r["action"] for r in logs]
    check("set_agent_active" in actions and "set_agent_role" in actions,
          "ორივე მოქმედება უნდა გაჩნდეს audit_log-ში")


def test_task_lifecycle_and_performance():
    setup()
    aid = sp.add_agent("დავალების_ტესტი", "555000222")
    sp.register_agent_chat_id(aid, 12345, "user1")
    task_id = sp.create_task("სათაური", "აღწერა", aid, "მაღალი", "", "admin")
    tasks = sp.get_tasks_for_agent(aid)
    check(len(tasks) == 1 and tasks[0]["status"] == "New", "ახალი დავალება 'New' სტატუსით")
    ok = sp.mark_task_done(task_id)
    check(ok, "დავალების დახურვა უნდა დაბრუნდეს True")
    open_tasks = sp.get_tasks_for_agent(aid, only_open=True)
    check(len(open_tasks) == 0, "დახურული დავალება აღარ უნდა ჩანდეს ღიაში")
    perf = sp.get_agent_performance(days=30)
    check(perf[aid]["assigned"] == 1 and perf[aid]["on_time"] == 1,
          "1 დავალება, 1 დროულად დასრულებული (იმავე წამში შექმნა+დახურვა)")
    check(perf[aid]["rate"] == 1.0, "rate უნდა იყოს 1.0")


def test_pick_agent_for_priority_prefers_best_performer():
    setup()
    strong = sp.add_agent("ძლიერი", "555001")
    weak = sp.add_agent("სუსტი", "555002")
    for aid in (strong, weak):
        sp.register_agent_chat_id(aid, hash(aid) % 100000, "u")
    # ძლიერს — ერთი დავალება, დახურული (100% on-time)
    t1 = sp.create_task("t1", "", strong, "მაღალი", "", "admin")
    sp.mark_task_done(t1)
    # სუსტს — ერთი დავალება, ღია (0% on-time)
    sp.create_task("t2", "", weak, "მაღალი", "", "admin")

    best = sp.pick_agent_for_priority("მაღალი")
    worst = sp.pick_agent_for_priority("საშუალო")
    check(best == strong, "'მაღალი' პრიორიტეტმა საუკეთესო შემსრულებელი უნდა აირჩიოს")
    check(worst == weak, "'საშუალო' პრიორიტეტმა ყველაზე სუსტი უნდა აირჩიოს")


def test_clock_in_out_flow():
    setup()
    aid = sp.add_agent("საათი", "555003")
    check(sp.clock_in(aid) == "ok", "პირველი clock_in -> ok")
    check(sp.clock_in(aid) == "already", "მეორედ იმავე დღეს -> already")
    check(sp.clock_out(aid) == "ok", "clock_out -> ok")
    att = sp.get_today_attendance(aid)
    check(att["clock_in"] and att["clock_out"], "orივე დროც უნდა იყოს ჩაწერილი")

    aid2 = sp.add_agent("არდაწყებული", "555004")
    check(sp.clock_out(aid2) == "not_in", "clock_out დაწყების გარეშე -> not_in")


def test_warning_auto_deactivation():
    setup()
    aid = sp.add_agent("გაფრთხილებადი", "555005")
    limit = sp.config.WARNING_LIMIT
    result = None
    for i in range(limit):
        result = sp.add_warning(aid, "late_arrival", f"დაგვიანება #{i+1}")
    check(result["count"] == limit, f"{limit}-ე გაფრთხილებაზე count == {limit}")
    check(result["deactivated"] is True, f"{limit}-ე გაფრთხილებაზე აგენტი ავტომატურად უნდა გამოირთოს")
    check(sp.get_agents()[0]["active"] == "no", "active='no' ბაზაშიც უნდა აისახოს")


def test_shift_swap_change_mode_updates_schedule():
    setup()
    aid = sp.add_agent("გრაფიკელი", "555006")
    sp.set_agent_schedule(aid, {"mon": "office_morning"})
    swap_id = sp.create_shift_swap_request(aid, "change_mode", "2026-09-14",  # ორშაბათი
                                            from_mode="office_morning", to_mode="online")
    row = sp.decide_shift_swap(swap_id, "approved", "admin")
    check(row["status"] == "approved", "swap სტატუსი 'approved'-ზე უნდა გადავიდეს")
    sched = sp.get_agent_schedule(aid)
    check(sched["mon"] == "online", "ორშაბათის რეჟიმი 'online'-ზე უნდა შეიცვალოს approval-ის შემდეგ")


def test_shift_swap_between_two_agents_swaps_modes():
    setup()
    a = sp.add_agent("ა", "555007")
    b = sp.add_agent("ბ", "555008")
    sp.set_agent_schedule(a, {"tue": "office_morning"})
    sp.set_agent_schedule(b, {"tue": "off"})
    swap_id = sp.create_shift_swap_request(a, "swap_agent", "2026-09-15",  # სამშაბათი
                                            target_agent_id=b)
    sp.accept_shift_swap(swap_id, b)
    sp.decide_shift_swap(swap_id, "approved", "admin")
    check(sp.get_agent_schedule(a)["tue"] == "off", "ა-ს სამშაბათი ახლა 'off'")
    check(sp.get_agent_schedule(b)["tue"] == "office_morning", "ბ-ს სამშაბათი ახლა 'office_morning'")


def test_exclusives_and_sharing_and_collaboration_count():
    setup()
    a = sp.add_agent("გამყიდველი", "555009")
    b = sp.add_agent("კოლეგა", "555010")
    ex_id = sp.create_exclusive(a, {"location": "საბურთალო", "price": "150000"})
    ex = sp.find_exclusive(ex_id)
    check(ex is not None and ex["status"] == "active", "ახალი ექსკლუზივი 'active'-ია ნაგულისხმევად")
    share = sp.share_exclusive(ex_id, a, b, note="კლიენტი დაინტერესდა")
    check(share is not None, "გაზიარება წარმატებული")
    check(sp.collaboration_count(a) == 1 and sp.collaboration_count(b) == 1,
          "ორივე მხარეს თანამშრომლობის მაჩვენებელი +1")


def test_dayoff_flow():
    setup()
    aid = sp.add_agent("დასვენებელი", "555011")
    req_id = sp.create_dayoff_request(aid, "2026-10-01", "ოჯახური მიზეზი")
    pending = sp.get_dayoff_requests(status="pending")
    check(len(pending) == 1, "ახალი მოთხოვნა 'pending'-ია")
    decided = sp.decide_dayoff(req_id, "approved")
    check(decided["status"] == "approved", "დამტკიცების შემდეგ სტატუსი 'approved'")


def test_questions_ask_and_answer():
    setup()
    aid = sp.add_agent("მკითხველი", "555012", team="Team1")
    qid = sp.create_question(aid, "როგორ დავამატო ახალი ბინა?")
    open_q = sp.get_questions(status="open")
    check(len(open_q) == 1, "ახალი კითხვა 'open'-ია")
    answered = sp.answer_question(qid, "პასუხი", "admin")
    check(answered["status"] == "answered" and answered["answer"] == "პასუხი",
          "პასუხის შემდეგ სტატუსი და ტექსტი განახლდა")


def test_quota_for_mode():
    setup()
    check(sp.quota_for_mode("online") == sp.config.ONLINE_DAILY_QUOTA, "online quota")
    check(sp.quota_for_mode("office_morning") == sp.config.OFFICE_DAILY_QUOTA, "office quota")
    check(sp.quota_for_mode("off") is None, "off რეჟიმს quota არ აქვს")


def test_agent_dashboard_and_admin_dashboard_shape():
    setup()
    aid = sp.add_agent("დაშბორდი", "555013", team="TeamX")
    sp.register_agent_chat_id(aid, 999, "u")
    sp.create_task("t", "", aid, "მაღალი", "", "admin")
    d = sp.get_agent_dashboard(aid)
    check(d is not None and d["agent"]["name"] == "დაშბორდი", "აგენტის დაშბორდი აბრუნებს სწორ სახელს")
    check(d["clients"]["total"] == 1, "ერთი დავალება == ერთი კლიენტი client_counts-ის მიხედვით")

    admin = sp.get_admin_dashboard()
    check(admin["summary"]["agents_total"] == 1, "admin dashboard-ში ჯამური აგენტების რაოდენობა სწორია")
    check(len(admin["team"]) == 1, "team სია შეიცავს ერთ აგენტს")


def test_reassign_task_moves_to_new_agent_and_resets_notified():
    setup()
    a = sp.add_agent("ძველი_კურატორი", "555014")
    b = sp.add_agent("ახალი_კურატორი", "555015")
    task_id = sp.create_task("კლიენტის ნახვა", "", a, "მაღალი", "", "admin", client_phone="+995500000000")
    sp.mark_task_notified(task_id)
    row = sp.reassign_task(task_id, b, actor_agent_id="admin")
    check(row is not None and row["assigned_to"] == b, "დავალება ახალ აგენტზეა გადაბარებული")
    check(row["assigned_to_name"] == "ახალი_კურატორი", "assigned_to_name განახლდა ახალი აგენტის სახელით")
    check(row["notified"] == "no", "notified ისევ 'no'-ზეა, რომ ახალმა აგენტმა შეტყობინება მიიღოს")
    check(len(sp.get_tasks_for_agent(a)) == 0, "ძველ აგენტს ღია დავალება აღარ ერგება")
    check(len(sp.get_tasks_for_agent(b)) == 1, "ახალ აგენტს დავალება გადაეცა")
    check(sp.reassign_task("არარსებული_id", b) is None, "არარსებულ task_id-ზე None უბრუნდება")


def test_admin_dashboard_excludes_deactivated_agents():
    setup()
    active = sp.add_agent("აქტიური", "555016", team="TeamY")
    fired = sp.add_agent("გათავისუფლებული", "555017", team="TeamY")
    sp.set_agent_active(fired, "no")
    admin = sp.get_admin_dashboard()
    ids_shown = {t["agent_id"] for t in admin["team"]}
    check(active in ids_shown, "აქტიური აგენტი ჩანს გუნდის სიაში")
    check(fired not in ids_shown, "გათავისუფლებული აგენტი აღარ ჩანს გუნდის სიაში")
    check(admin["summary"]["agents_total"] == 2, "agents_total მოიცავს ორივეს (სრული ისტორია)")
    check(admin["summary"]["active_total"] == 1, "active_total ითვლის მხოლოდ აქტიურებს")
    check(admin["summary"]["inactive_total"] == 1, "inactive_total სწორად ითვლის გათავისუფლებულებს")


# ---------------------------------------------------------------------
# მარტივი გამშვები (pytest-ის გარეშეც მუშაობს)
# ---------------------------------------------------------------------

def _all_tests():
    return {name: fn for name, fn in globals().items()
            if name.startswith("test_") and callable(fn)}


if __name__ == "__main__":
    tests = _all_tests()
    passed, failed = 0, []
    for name, fn in tests.items():
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except Exception as e:  # noqa: BLE001
            failed.append((name, e))
            print(f"  ❌ {name}: {e}")

    print()
    print(f"სულ: {len(tests)}   ✅ გავიდა: {passed}   ❌ ჩავარდა: {len(failed)}")
    if failed:
        sys.exit(1)
