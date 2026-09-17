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
    viewing_time TEXT DEFAULT '', assigned_to_name TEXT DEFAULT '',
    seen TEXT DEFAULT 'no', seen_at TEXT DEFAULT ''
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
    detail TEXT DEFAULT '', created_at TEXT DEFAULT '', agent_name TEXT DEFAULT '',
    status TEXT DEFAULT 'active', dismiss_reason TEXT DEFAULT '',
    dismiss_requested_by TEXT DEFAULT '', dismiss_requested_by_name TEXT DEFAULT '',
    dismiss_requested_at TEXT DEFAULT '', dismiss_decided_by TEXT DEFAULT '',
    dismiss_decided_at TEXT DEFAULT ''
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
CREATE TABLE agent_requests (
    request_id TEXT PRIMARY KEY, kind TEXT DEFAULT 'add', requested_by TEXT DEFAULT '',
    requested_by_name TEXT DEFAULT '', team TEXT DEFAULT '', target_agent_id TEXT DEFAULT '',
    name TEXT DEFAULT '', phone TEXT DEFAULT '', reason TEXT DEFAULT '',
    status TEXT DEFAULT 'pending', created_at TEXT DEFAULT '', decided_at TEXT DEFAULT '',
    decided_by TEXT DEFAULT ''
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
        DROP TABLE IF EXISTS audit_log; DROP TABLE IF EXISTS agent_requests;
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
    fetched = sp.get_dayoff_request(req_id)
    check(fetched is not None and fetched["status"] == "pending", "get_dayoff_request პოულობს pending ჩანაწერს")
    decided = sp.decide_dayoff(req_id, "approved")
    check(decided["status"] == "approved", "დამტკიცების შემდეგ სტატუსი 'approved'")


def test_dayoff_monthly_cap_counter():
    setup()
    aid = sp.add_agent("ხშირი დამსვენებელი", "555013")
    # იმავე თვეში (2026-10) 2 უკვე დამტკიცებული + 1 უარყოფილი (არ
    # უნდა ჩაითვალოს ჭერში) + 1 სხვა თვის (არ უნდა ჩაითვალოს).
    for d in ("2026-10-01", "2026-10-08"):
        rid = sp.create_dayoff_request(aid, d, "")
        sp.decide_dayoff(rid, "approved")
    rid_rejected = sp.create_dayoff_request(aid, "2026-10-15", "")
    sp.decide_dayoff(rid_rejected, "rejected")
    rid_other_month = sp.create_dayoff_request(aid, "2026-11-01", "")
    sp.decide_dayoff(rid_other_month, "approved")

    count_oct = sp.approved_dayoffs_count_this_month(aid, "2026-10-20")
    check(count_oct == 2, f"ოქტომბერში 2 დამტკიცებული უნდა ითვლებოდეს, მივიღეთ {count_oct}")
    count_nov = sp.approved_dayoffs_count_this_month(aid, "2026-11-15")
    check(count_nov == 1, f"ნოემბერში 1 დამტკიცებული უნდა ითვლებოდეს, მივიღეთ {count_nov}")


def test_agent_request_add_flow_creates_real_agent_on_approval():
    setup()
    lead_id = sp.add_agent("გუნდის ლიდერი", "555014", team="TeamX")
    sp.set_agent_role(lead_id, "team_lead")
    req_id = sp.create_agent_request("add", lead_id, team="TeamX", name="ახალი აგენტი", phone="555015")
    pending = sp.get_agent_requests(status="pending", team="TeamX")
    check(len(pending) == 1, "ახალი agent_request 'pending'-ია და თიმით ფილტრდება")

    before = len(sp.get_agents())
    decided = sp.decide_agent_request(req_id, "approved", decided_by="admin")
    check(decided["status"] == "approved", "დამტკიცების შემდეგ სტატუსი 'approved'")
    after = sp.get_agents()
    check(len(after) == before + 1, "დამტკიცებამ რეალურად დაამატა ახალი აგენტი")
    new_agent = next((a for a in after if a["name"] == "ახალი აგენტი"), None)
    check(new_agent is not None and str(new_agent.get("team", "")) == "TeamX",
          "ახალი აგენტი სწორ გუნდშია დამატებული")

    # უკვე გადაწყვეტილი მოთხოვნის მეორედ გადაწყვეტა არ სრულდება.
    again = sp.decide_agent_request(req_id, "rejected", decided_by="admin")
    check(again is None, "უკვე გადაწყვეტილი მოთხოვნა მეორედ არ სრულდება")


def test_agent_request_remove_flow_deactivates_not_deletes():
    setup()
    target_id = sp.add_agent("გასათავისუფლებელი", "555016", team="TeamY")
    req_id = sp.create_agent_request("remove", "", team="TeamY", target_agent_id=target_id, reason="დატოვა კომპანია")
    decided = sp.decide_agent_request(req_id, "approved", decided_by="admin")
    check(decided["status"] == "approved", "გათავისუფლების მოთხოვნაც მტკიცდება")
    # `get_agents()` ნაგულისხმევად მხოლოდ აქტიურებს აბრუნებს — პირდაპირ
    # ბაზიდან ვამოწმებთ, რომ ჩანაწერი დარჩა (არ წაშლილა), უბრალოდ
    # გაითიშა.
    row = sp.db.query_one("SELECT * FROM agents WHERE agent_id = %s", (target_id,))
    check(row is not None, "აგენტი არ წაშლილა ბაზიდან — მხოლოდ გაითიშა")
    check(str(row.get("active")) == "no", "გათავისუფლების დამტკიცების შემდეგ active='no'")


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


def test_agent_dashboard_shows_manager_name():
    setup()
    lead = sp.add_agent("მენეჯერი მენა", "555018", team="")
    sp.set_agent_role(lead, "team_lead")
    sp.set_agent_team(lead, "მენეჯერი მენა")  # ისე, როგორც /api/agents/assign "lead"-ზე აკეთებს
    member = sp.add_agent("წევრი", "555019", team="მენეჯერი მენა")
    independent = sp.add_agent("დამოუკიდებელი", "555020")

    d_member = sp.get_agent_dashboard(member)
    check(d_member["agent"]["manager_name"] == "მენეჯერი მენა", "გუნდის წევრს უჩვენებს სწორ მენეჯერს")

    d_independent = sp.get_agent_dashboard(independent)
    check(d_independent["agent"]["manager_name"] is None, "დამოუკიდებელ აგენტს მენეჯერი არა აქვს")

    d_lead = sp.get_agent_dashboard(lead)
    check(d_lead["agent"]["manager_name"] is None, "თიმლიდერს საკუთარი თავი მენეჯერად არ ეწერება")


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


def test_get_task_history_filters_by_team_and_agent():
    setup()
    lead = sp.add_agent("ისტ. ლიდერი", "555021", team="")
    sp.set_agent_role(lead, "team_lead")
    sp.set_agent_team(lead, "ისტგუნდი1")
    a1 = sp.add_agent("ისტ. წევრი1", "555022", team="ისტგუნდი1")
    a2 = sp.add_agent("ისტ. სხვაგუნდელი", "555023", team="ისტგუნდი2")
    sp.create_task("t1", "", a1, "მაღალი", "", "admin")
    sp.create_task("t2", "", a2, "მაღალი", "", "admin")

    team1_hist = sp.get_task_history(team="ისტგუნდი1")
    ids = {t["assigned_to"] for t in team1_hist}
    check(a1 in ids and a2 not in ids, "get_task_history(team=) მხოლოდ იმ გუნდის დავალებებს აბრუნებს")

    agent_hist = sp.get_task_history(agent_id=a2)
    check(len(agent_hist) == 1 and agent_hist[0]["assigned_to"] == a2,
          "get_task_history(agent_id=) მხოლოდ ერთი აგენტისას აბრუნებს")

    all_hist = sp.get_task_history()
    check(len(all_hist) == 2, "get_task_history() ფილტრის გარეშე ორივეს აბრუნებს")


def test_get_meetings_days_filter():
    setup()
    aid = sp.add_agent("შემხვედრელი", "555024")
    mid_old = sp.create_meeting({"agent_id": aid, "agent_name": "შემხვედრელი", "address": "ძველი მისამართი"})
    import db
    db.execute("UPDATE meetings SET timestamp = ? WHERE meeting_id = ?", ("2000-01-01 10:00", mid_old))
    mid_new = sp.create_meeting({"agent_id": aid, "agent_name": "შემხვედრელი", "address": "ახალი მისამართი"})

    recent = sp.get_meetings(agent_id=aid, days=7)
    ids = {m["meeting_id"] for m in recent}
    check(mid_new in ids and mid_old not in ids, "get_meetings(days=) ძველ ჩანაწერს გამორიცხავს")

    all_meetings = sp.get_meetings(agent_id=aid)
    check(len(all_meetings) == 2, "days-ის გარეშე ორივე ჩანაწერი ბრუნდება")


def test_daily_digest_covers_all_six_points():
    setup()
    lead = sp.add_agent("დიჯესთის ლიდერი", "555025", team="")
    sp.set_agent_role(lead, "team_lead")
    sp.set_agent_team(lead, "დიჯგუნდი")
    sp.register_agent_chat_id(lead, 1001, "lead")
    member = sp.add_agent("დიჯწევრი", "555026", team="დიჯგუნდი")
    sp.set_agent_schedule(member, {k: "office_morning" for k in sp.WEEKDAY_KEYS})
    sp.clock_in(member)
    sp.set_daily_count(member, 5, site=5, myhome=5, ssge=0)
    sp.create_task("კლიენტი დღეს", "", member, "მაღალი", "", "admin")
    sp.create_meeting({"agent_id": member, "agent_name": "დიჯწევრი", "address": "სადღაცერთი ქუჩა"})
    sp.add_warning(member, "late_arrival", "ტესტი")

    digest = sp.get_daily_digest(team="დიჯგუნდი")
    check(any("დიჯწევრი" in s for s in digest["came"]), "digest.came შეიცავს გამოცხადებულ წევრს")
    check(len(digest["clients_assigned"]) == 1, "digest.clients_assigned ხედავს დღეს მინიჭებულ დავალებას")
    check(len(digest["meetings"]) == 1, "digest.meetings ხედავს დღეს დარეგისტრირებულ შეხვედრას")
    check(any("დიჯწევრი: 5" in s for s in digest["listing_counts"]), "digest.listing_counts სწორ რაოდენობას აჩვენებს")
    check(len(digest["warnings_today"]) == 1, "digest.warnings_today ხედავს დღეს გაცემულ გაფრთხილებას")
    check(digest["teams"] == [], "კონკრეტული team-ის მოთხოვნისას teams სია ცარიელია")

    company_digest = sp.get_daily_digest(team=None)
    check(
        any(t.get("team") == "დიჯგუნდი" for t in company_digest["teams"]),
        "team=None-ზე teams სია ყველა გუნდს შეიცავს (ლეიბლირებული ობიექტებით)",
    )


def test_admin_dashboard_late_flag():
    setup()
    aid = sp.add_agent("დაგვიანებული", "555027", team="ლეიტგუნდი")
    sp.set_agent_schedule(aid, {k: "office_morning" for k in sp.WEEKDAY_KEYS})
    # არ ვუშვებთ clock_in-ს — office_morning იწყება 10:00-ზე; ტესტი
    # თავად დროზე არ არის დამოკიდებული (late მხოლოდ საათის მიხედვით
    # გამოითვლება), უბრალოდ ვამოწმებთ, რომ ველი საერთოდ არსებობს და
    # ბულეანია — ცრუ-პოზიტივი/ნეგატივი დროზეა დამოკიდებული საწარმოო
    # გარემოში, აქ მხოლოდ ფორმას ვამოწმებთ.
    admin = sp.get_admin_dashboard()
    row = next(t for t in admin["team"] if t["agent_id"] == aid)
    check("late" in row and isinstance(row["late"], bool), "team_rows-ს აქვს ბულეანი 'late' ველი")
    check("late_count" in admin["summary"], "summary-ს აქვს 'late_count'")


def test_get_team_directory_returns_labeled_teams():
    setup()
    lead1 = sp.add_agent("გაბო", "555030", team="")
    sp.set_agent_role(lead1, "team_lead")
    sp.set_agent_team(lead1, lead1)
    sp.add_agent("წევრი1", "555031", team=lead1)
    sp.add_agent("წევრი2", "555032", team=lead1)

    lead2 = sp.add_agent("ლიკა", "555033", team="")
    sp.set_agent_role(lead2, "team_lead")
    sp.set_agent_team(lead2, lead2)

    directory = sp.get_team_directory()
    check(len(directory) == 2, "get_team_directory ორივე ლიდერს აბრუნებს")
    gabo_entry = next(t for t in directory if t["name"] == "გაბო")
    check(gabo_entry["team"] == lead1, "team-key ლიდერის agent_id-ის ტოლია")
    check(gabo_entry["member_count"] == 2, "member_count სწორად ითვლის წევრებს (ლიდერის გარეშე)")
    lika_entry = next(t for t in directory if t["name"] == "ლიკა")
    check(lika_entry["member_count"] == 0, "წევრების გარეშე ლიდერს member_count=0 აქვს")

    inactive_lead = sp.add_agent("არააქტიური", "555034", team="")
    sp.set_agent_role(inactive_lead, "team_lead")
    sp.set_agent_team(inactive_lead, inactive_lead)
    sp.set_agent_active(inactive_lead, "no")
    directory2 = sp.get_team_directory()
    check(
        all(t["agent_id"] != inactive_lead for t in directory2),
        "get_team_directory დეაქტივირებულ ლიდერებს არ შეიცავს",
    )


def test_find_duplicate_team_keys_detects_collisions():
    setup()
    lead1 = sp.add_agent("დუბლიკატი1", "555035", team="")
    sp.set_agent_role(lead1, "team_lead")
    lead2 = sp.add_agent("დუბლიკატი2", "555036", team="")
    sp.set_agent_role(lead2, "team_lead")
    sp.set_agent_team(lead1, "საერთოგუნდი")
    sp.set_agent_team(lead2, "საერთოგუნდი")

    dups = sp.find_duplicate_team_keys()
    check(len(dups) == 1, "ერთი კოლიზია გამოვლინდა")
    check(dups[0]["team"] == "საერთოგუნდი", "კოლიზიის team-key სწორია")
    names = {l["name"] for l in dups[0]["leads"]}
    check(names == {"დუბლიკატი1", "დუბლიკატი2"}, "ორივე კოლიდირებული ლიდერი ჩამოთვლილია")

    lead3 = sp.add_agent("უნიკალური", "555037", team="")
    sp.set_agent_role(lead3, "team_lead")
    sp.set_agent_team(lead3, lead3)
    dups2 = sp.find_duplicate_team_keys()
    check(len(dups2) == 1, "უნიკალური team-key-ის მქონე ლიდერი კოლიზიაში არ ხვდება")


def test_delete_agent_removes_row_but_keeps_history():
    setup()
    aid = sp.add_agent("წასაშლელი", "555040", team="")
    task_id = sp.create_task(
        title="ტესტი", description="", assigned_to=aid, priority="საშუალო",
        due_date="", created_by="admin", client_phone="555999",
    )
    check(sp.delete_agent(aid) is True, "delete_agent წარმატებით შლის არსებულ აგენტს")
    check(sp.delete_agent(aid) is False, "მეორედ იგივე agent_id-ზე False ბრუნდება")
    check(all(str(a["agent_id"]) != str(aid) for a in sp.get_agents()), "აგენტი აღარ ჩანს get_agents()-ში")
    task = sp.get_task(task_id) if hasattr(sp, "get_task") else next(
        (t for t in sp.get_tasks() if t["task_id"] == task_id), None)
    check(task is not None, "დავალება ისტორიაში უცვლელად რჩება აგენტის წაშლის შემდეგაც")


def test_mark_task_seen_only_by_assigned_agent():
    setup()
    a1 = sp.add_agent("აგენტი1", "555041", team="")
    a2 = sp.add_agent("აგენტი2", "555042", team="")
    task_id = sp.create_task(
        title="ტესტი", description="", assigned_to=a1, priority="საშუალო",
        due_date="", created_by="admin", client_phone="555998",
    )
    check(sp.mark_task_seen(task_id, a2) is None, "სხვა აგენტს არ შეუძლია დადასტურება")
    row = sp.mark_task_seen(task_id, a1)
    check(row is not None and row["seen"] == "yes", "მინიჭებულმა აგენტმა დაადასტურა")

    a3 = sp.add_agent("აგენტი3", "555043", team="")
    sp.reassign_task(task_id, a3)
    row2 = next((t for t in sp.get_tasks() if t["task_id"] == task_id), None)
    check(row2["seen"] == "no", "გადაბარებისას seen ისევ 'no'-ზე ბრუნდება")


def test_warning_dismissal_workflow():
    setup()
    aid = sp.add_agent("გაფრთხილებული", "555044", team="")
    manager = sp.add_agent("მენეჯერი", "555045", team="")
    director = "admin"
    result = sp.add_warning(aid, "quota_missed", "დღიური გეგმა არ შესრულდა")
    warning_id = result["warning_id"]
    check(result["count"] == 1, "პირველი გაფრთხილება ითვლის 1-ს")

    row = sp.request_warning_dismissal(warning_id, manager, "ამ დროს შეხვედრაზე იყო")
    check(row["status"] == "dismiss_pending", "მოთხოვნის შემდეგ სტატუსი dismiss_pending-ია")
    check(sp.request_warning_dismissal(warning_id, manager, "ხელახლა") is None,
          "უკვე მოთხოვნილზე ხელახლა მოთხოვნა არ დაშვებულა")

    approved = sp.decide_warning_dismissal(warning_id, True, director)
    check(approved["status"] == "dismissed", "დირექტორის დამტკიცებით სტატუსი dismissed-ია")

    dash = sp.get_agent_dashboard(aid)
    check(dash["warnings"]["count"] == 0, "გაუქმებული გაფრთხილება აღარ ითვლება დაშბორდზე")


def test_warning_dismissal_rejection_keeps_it_active():
    setup()
    aid = sp.add_agent("გაფრთხილებული2", "555046", team="")
    manager = sp.add_agent("მენეჯერი2", "555047", team="")
    result = sp.add_warning(aid, "late", "დაგვიანება")
    warning_id = result["warning_id"]
    sp.request_warning_dismissal(warning_id, manager, "მიზეზი")
    rejected = sp.decide_warning_dismissal(warning_id, False, "admin")
    check(rejected["status"] == "active", "უარყოფისას გაფრთხილება ისევ active-ზე ბრუნდება")
    dash = sp.get_agent_dashboard(aid)
    check(dash["warnings"]["count"] == 1, "უარყოფილი მოთხოვნის შემდეგაც გაფრთხილება ისევ ითვლება")


def test_get_today_client_phones_and_all_clients():
    setup()
    aid = sp.add_agent("აგენტი", "555048", team="გუნდიX")
    sp.create_task(title="კლ1", description="", assigned_to=aid, priority="საშუალო",
                    due_date="", created_by="admin", client_phone="555111")
    sp.create_task(title="კლ1 დუბლი", description="", assigned_to=aid, priority="საშუალო",
                    due_date="", created_by="admin", client_phone="555111")
    sp.create_task(title="კლ2", description="", assigned_to=aid, priority="საშუალო",
                    due_date="", created_by="admin", client_phone="555222")

    phones = sp.get_today_client_phones(aid)
    check(sorted(phones) == ["555111", "555222"], "დღევანდელი უნიკალური ტელეფონები სწორია")

    clients = sp.get_all_clients()
    client_phones = {c["client_phone"] for c in clients}
    check({"555111", "555222"}.issubset(client_phones), "get_all_clients ორივე კლიენტს შეიცავს")

    clients_team = sp.get_all_clients(team="გუნდიX")
    check(len(clients_team) == len(clients), "team-ფილტრი იმავე გუნდის კლიენტებს არ ჭრის")
    clients_other_team = sp.get_all_clients(team="სხვაგუნდი")
    check(len(clients_other_team) == 0, "სხვა გუნდზე კლიენტი არ ჩანს")


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
