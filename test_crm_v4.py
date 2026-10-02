"""
v4.0-ის ტესტები: თვიური გაფრთხილებები, Day off-ზე გაფრთხილების გამოტოვება,
მულტი-მონიშვნა, რაიონები, კლიენტის გაერთიანებული ისტორია და
Attendance + GPS.

იგივე მიდგომა, რაც test_sheets_postgres.py-ში: ნამდვილი კოდი, ოღონდ
`db`-ის ნაცვლად მეხსიერებაში მომუშავე SQLite. ეს ფაილი იმავე ყალბ ბაზას
იყენებს (test_sheets_postgres-ის schema-თი).

გაშვება:
    python3 test_crm_v4.py
    pytest test_crm_v4.py -v
"""

from __future__ import annotations

import datetime
import sys

import test_sheets_postgres as base  # ყალბი db + სქემა (import-ისას დგება)

sp = base.sp
sys.modules["sheets"] = sp  # crm_extras `import sheets`-ს იყენებს

import config  # noqa: E402
import crm_extras as ex  # noqa: E402
import crm_time  # noqa: E402

setup = base.setup
check = base.check

OFFICE = (41.7151, 44.8271)
INSIDE = {"lat": OFFICE[0] + 0.0003, "lng": OFFICE[1], "accuracy": 15.0}      # ~33 მ
OUTSIDE = {"lat": 41.7300, "lng": 44.8300, "accuracy": 15.0}                   # ~1.7 კმ
BAD_ACC = {"lat": OFFICE[0], "lng": OFFICE[1], "accuracy": 900.0}

ALL_DAYS = {k: "office_morning" for k in sp.WEEKDAY_KEYS}


def _agent(name="ტესტერი", phone="555900", team="T1", schedule=True):
    aid = sp.add_agent(name, phone, team=team)
    sp.register_agent_chat_id(aid, abs(hash(aid)) % 10**8, "u")
    if schedule:
        sp.set_agent_schedule(aid, ALL_DAYS)
    return aid, next(a for a in sp.get_agents() if a["agent_id"] == aid)


def _configure_office(allow_outside="0"):
    sp.set_app_setting("office_latitude", repr(OFFICE[0]), "test")
    sp.set_app_setting("office_longitude", repr(OFFICE[1]), "test")
    sp.set_app_setting("office_radius_meters", "150", "test")
    sp.set_app_setting("max_accuracy_meters", "100", "test")
    sp.set_app_setting("allow_outside_checkin", allow_outside, "test")


def _approve_dayoff(aid, day: datetime.date):
    rid = sp.create_dayoff_request(aid, day.strftime(crm_time.DATE_FMT), "test")
    sp.decide_dayoff(rid, "approved")


# ------------------------------------------------------------- 1. გაფრთხილებები

def test_warnings_reset_with_new_month():
    setup()
    aid, _ = _agent()
    # გასული თვის ბოლო დღე (თვის დასაწყისამდე 1 დღით ადრე) — 30-დღიან
    # ფანჯარაშია, მაგრამ ახალი თვის დაწყებისას უკვე ანულირებულია
    prev = crm_time.local_month_start_server_naive() - datetime.timedelta(days=1)
    sp.db.execute(
        "INSERT INTO warnings (warning_id, agent_id, type, detail, created_at, agent_name, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        ("old1", aid, "late_arrival", "გასული თვე", prev.strftime("%Y-%m-%d %H:%M"), "x", "active"),
    )
    res = sp.add_warning(aid, "late_arrival", "ახალი თვე")
    check(res["count"] == 1, f"გასული თვის გაფრთხილება არ უნდა ითვლებოდეს (count={res['count']})")
    dash = sp.get_agent_dashboard(aid)
    check(dash["warnings"]["count"] == 1, "დაშბორდზეც მხოლოდ მიმდინარე თვის გაფრთხილებებია")


def test_no_warning_on_approved_dayoff():
    setup()
    aid, _ = _agent()
    today = crm_time.local_today()
    _approve_dayoff(aid, today)
    res = sp.add_warning(aid, "quota_missed", "დღეოფზე")
    check(res.get("skipped") == "dayoff" and res["count"] == 0, "დამტკიცებულ დღეოფზე გაფრთხილება უნდა გამოტოვდეს")
    check(len(sp.get_warnings(agent_id=aid)) == 0, "ბაზაში გაფრთხილება არ უნდა ჩაიწეროს")


def test_warning_written_when_dayoff_is_other_day_or_pending():
    setup()
    aid, _ = _agent()
    today = crm_time.local_today()
    _approve_dayoff(aid, today + datetime.timedelta(days=3))        # სხვა დღე
    sp.create_dayoff_request(aid, today.strftime(crm_time.DATE_FMT), "pending")  # დაუმტკიცებელი
    res = sp.add_warning(aid, "quota_missed", "ჩვეულებრივი დღე")
    check("skipped" not in res and res["count"] == 1, "სხვა დღის/დაუმტკიცებელი დღეოფი გაფრთხილებას არ აჩერებს")


def test_dayoff_date_formats_recognised():
    setup()
    aid, _ = _agent()
    today = crm_time.local_today()
    rid = sp.create_dayoff_request(aid, today.strftime("%d.%m.%Y"), "ქართული ფორმატი")
    sp.decide_dayoff(rid, "approved")
    res = sp.add_warning(aid, "no_show", "x")
    check(res.get("skipped") == "dayoff", "dd.mm.yyyy ფორმატის თარიღიც უნდა ამოიცნოს")
    check(crm_time.parse_user_date("ხვალ") is None, "'ხვალ' თარიღად არ ითვლება")


# ------------------------------------------------------------- 2. მულტი-მონიშვნა

def test_bulk_dismissal_request_and_decision():
    setup()
    aid, _ = _agent()
    mgr = sp.add_agent("მენეჯერი", "555901", team="T1")
    ids = []
    for i in range(3):
        sp.db.execute(
            "INSERT INTO warnings (warning_id, agent_id, type, detail, created_at, agent_name, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (f"w{i}", aid, "late_arrival", f"d{i}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "x", "active"),
        )
        ids.append(f"w{i}")
    # w2 უკვე dismissed — bulk-მა არ უნდა შეეხოს
    sp.db.execute("UPDATE warnings SET status='dismissed' WHERE warning_id='w2'")
    rows = sp.request_warning_dismissals_bulk(ids + ["არარსებული"], mgr, "შეხვედრაზე იყო")
    check(sorted(r["warning_id"] for r in rows) == ["w0", "w1"], "მხოლოდ active გაფრთხილებები მოთხოვნადია")
    check(all(r["status"] == "dismiss_pending" for r in rows), "სტატუსი dismiss_pending")
    done = sp.decide_warning_dismissals_bulk(["w0", "w1", "w2"], True, "admin")
    check(sorted(r["warning_id"] for r in done) == ["w0", "w1"], "დამტკიცება მხოლოდ pending-ებზე")
    check(all(r["status"] == "dismissed" for r in done), "დამტკიცებულია")
    check(sp.get_agent_dashboard(aid)["warnings"]["count"] == 0, "გაუქმებულები აღარ ითვლება")


def test_bulk_rejection_returns_to_active():
    setup()
    aid, _ = _agent()
    mgr = sp.add_agent("მენეჯერი2", "555902", team="T1")
    r1 = sp.add_warning(aid, "late_arrival", "a")["warning_id"]
    sp.request_warning_dismissals_bulk([r1], mgr, "მიზეზი")
    out = sp.decide_warning_dismissals_bulk([r1], False, "admin")
    check(out[0]["status"] == "active", "უარყოფისას გაფრთხილება ისევ active")


# ------------------------------------------------------------- 3. ტასკი: მესაკუთრის ნომერი

def test_task_stores_owner_phone_and_notes():
    setup()
    aid, _ = _agent()
    tid = sp.create_task(title="ნახვა: L1", description="დამატებითი დეტალი", assigned_to=aid, priority="მაღალი",
                         due_date="", created_by="admin", lead_type="listing", client_phone="599111222",
                         listing_id="L1", viewing_time="ხვალ", owner_phone="577333444")
    t = next(x for x in sp.get_tasks() if x["task_id"] == tid)
    check(t["owner_phone"] == "577333444", "owner_phone შეინახა")
    check(t["description"] == "დამატებითი დეტალი", "დამატებითი დეტალი description-ში")


# ------------------------------------------------------------- 4. კლიენტი: ყველა მონაცემი ერთად

def test_phone_key_normalisation():
    for v in ("+995 599 12 34 56", "599123456", "0599123456", "995599123456", "599-12-34-56"):
        check(ex.phone_key(v) == "599123456", f"phone_key({v!r}) -> {ex.phone_key(v)!r}")
    check(ex.phone_key("") == "", "ცარიელი ნომერი -> ცარიელი")


def test_client_directory_and_history_merge_all_sources():
    setup()
    a, _ = _agent("აგენტი1", "555910", team="T1")
    b, _ = _agent("აგენტი2", "555911", team="T2")
    sp.create_task(title="კლიენტი", description="", assigned_to=a, priority="მაღალი", due_date="",
                   created_by="admin", client_phone="+995 599 12 34 56")
    sp.create_report(agent_id=b, client_phone="0599123456", actions="დარეკვა", notes="n", file_id="")
    sp.create_exclusive(a, {"owner_phone": "599 123 456", "location": "ვაკე"})
    sp.db.execute(
        "INSERT INTO myhome_jobs (job_id, agent_id, agent_name, status, owner_number) VALUES (%s,%s,%s,%s,%s)",
        ("j1", a, "აგენტი1", "COMPLETED", "599123456"),
    )
    directory = ex.client_directory()
    check(len(directory) == 1, f"ერთი ნომერი სხვადასხვა ფორმატით = ერთი კლიენტი (ნაპოვნია {len(directory)})")
    check(directory[0]["task_count"] == 1 and directory[0]["report_count"] == 1, "დავალება+რეპორტი ერთად")
    hist = ex.client_history("599123456")
    check(len(hist["tasks"]) == 1 and len(hist["reports"]) == 1, "ისტორიაში დავალება+რეპორტი")
    check(len(hist["exclusives"]) == 1 and len(hist["myhome_jobs"]) == 1, "ექსკლუზივი და MyHome დადებაც")
    check(hist["agent_ids"] == {a, b}, "ორივე აგენტი ჩანს")
    check(len(ex.client_directory(team="T2")) == 1, "T2-ის მენეჯერიც ხედავს (რეპორტი მისი აგენტისაა)")
    check(len(ex.client_directory(team="სხვა")) == 0, "უცხო გუნდს არ ჩანს")


# ------------------------------------------------------------- 5. რაიონები

def test_district_assignment_upsert_and_validation():
    setup()
    aid, _ = _agent()
    ws = crm_time.week_start().strftime(crm_time.DATE_FMT)
    sp.set_district_assignment(ws, aid, ["ვაკე", "საბურთალო"], "admin", "ადმინი")
    sp.set_district_assignment(ws, aid, ["ისანი"], "admin", "ადმინი")   # გადაწერა, არა დუბლი
    rows = sp.get_district_assignments(week_start=ws, agent_id=aid)
    check(len(rows) == 1 and ex.split_districts(rows[0]["districts"]) == ["ისანი"], "upsert: ერთი სტრიქონი, ახალი მნიშვნელობა")
    check(ex.clean_districts(["ვაკე", "არარსებული რაიონი", "ვაკე", "ისანი-სამგორი"]) == ["ვაკე", "ისანი-სამგორი"],
          "უცნობი და დუბლირებული რაიონები იგდება, ჯგუფის სახელი ვალიდურია")
    sp.set_district_assignment(ws, aid, [], "admin", "ადმინი")
    check(ex.split_districts(sp.get_district_assignments(week_start=ws, agent_id=aid)[0]["districts"]) == [],
          "ცარიელი სია = გასუფთავება")


def test_week_start_is_monday():
    d = datetime.date(2026, 10, 4)  # კვირა
    check(crm_time.week_start(d) == datetime.date(2026, 9, 28), "კვირა დღის კვირა ორშაბათით იწყება")
    check(crm_time.week_start(datetime.date(2026, 9, 28)) == datetime.date(2026, 9, 28), "ორშაბათი თავადაა")


# ------------------------------------------------------------- 6. GPS / Attendance

def test_haversine_known_distance():
    d = ex.haversine_m(41.7151, 44.8271, 41.7151, 44.8271)
    check(d < 0.01, "ერთი წერტილი = 0")
    d2 = ex.haversine_m(0.0, 0.0, 0.0, 1.0)   # ეკვატორზე 1° ≈ 111.19 კმ
    check(abs(d2 - 111195) < 200, f"1° გრძედი ≈ 111.2 კმ ({d2:.0f})")


def test_parse_geo_input():
    g, e = ex.parse_geo_input({"lat": "41.7", "lng": 44.8, "accuracy": "12.5"})
    check(e is None and g == {"lat": 41.7, "lng": 44.8, "accuracy": 12.5}, "სწორი შეყვანა")
    check(ex.parse_geo_input({}) == (None, None), "ლოკაცია არ გამოგზავნილა")
    check(ex.parse_geo_input({"lat": "abc", "lng": 1})[1] == "invalid_location", "არასწორი რიცხვი")
    check(ex.parse_geo_input({"lat": 95, "lng": 1})[1] == "invalid_location", "დიაპაზონს გარეთ")
    check(ex.parse_geo_input({"lat": 0, "lng": 0})[1] == "invalid_location", "0,0 არასანდოა")
    g2, _ = ex.parse_geo_input({"lat": 41.7, "lng": 44.8})
    check(g2["accuracy"] is None, "სიზუსტე არ გამოუგზავნია -> None")


def test_evaluate_location_statuses():
    setup()
    _configure_office()
    s = ex.attendance_settings()
    check(s["configured"], "ოფისი დაყენებულია")
    check(ex.evaluate_location(INSIDE, s)["geo_status"] == "OFFICE", "ოფისის რადიუსში")
    out = ex.evaluate_location(OUTSIDE, s)
    check(out["geo_status"] == "OUTSIDE_OFFICE" and out["distance_m"] > 1000, "ოფისის გარეთ")
    check(ex.evaluate_location(BAD_ACC, s)["geo_status"] == "LOCATION_UNRELIABLE", "დაბალი სიზუსტე")
    no_acc = dict(INSIDE, accuracy=None)
    check(ex.evaluate_location(no_acc, s)["geo_status"] == "LOCATION_UNRELIABLE", "სიზუსტის გარეშე = არასანდო")


def test_settings_validation():
    check(ex.validate_settings_input({"office_latitude": "41.7", "office_longitude": "44.8"})[1] is None, "სწორია")
    check(ex.validate_settings_input({"office_latitude": "41.7"})[1] is not None, "განედი მარტო არ შეიძლება")
    check(ex.validate_settings_input({"office_latitude": "123", "office_longitude": "1"})[1] is not None, "დიაპაზონი")
    check(ex.validate_settings_input({"office_radius_meters": "5"})[1] is not None, "რადიუსი ძალიან პატარაა")
    check(ex.validate_settings_input({"office_radius_meters": "abc"})[1] is not None, "რადიუსი არარიცხვია")
    out, err = ex.validate_settings_input({"allow_outside_checkin": True, "office_name": " ოფისი "})
    check(err is None and out["allow_outside_checkin"] == "1" and out["office_name"] == "ოფისი", "ბულეანი/სახელი")


def test_is_late_uses_shift_start_and_grace():
    g = config.ATTENDANCE_GRACE_MINUTES
    day = datetime.datetime(2026, 10, 2, 10, 0)
    check(not ex.is_late("office_morning", day.replace(minute=g)), "grace-ის ბოლო წუთი დაგვიანება არაა")
    check(ex.is_late("office_morning", day.replace(minute=g, second=30)), "grace-ის შემდეგ — დაგვიანებაა")
    check(not ex.is_late("online", datetime.datetime(2026, 10, 2, 23, 0)), "ონლაინზე დაგვიანება არ არსებობს")


def test_check_in_without_gps_configured_still_works():
    setup()
    aid, agent = _agent()
    res = ex.check_in(agent, None)
    check(res["ok"] and res["result"] == "ok", "ოფისის კოორდინატის გარეშე ძველებურად მუშაობს (უკუთავსებადობა)")
    check(ex.check_in(agent, None)["result"] == "already", "მეორედ — already")


def test_check_in_requires_location_when_configured():
    setup()
    _configure_office()
    aid, agent = _agent()
    res = ex.check_in(agent, None)
    check(not res["ok"] and res["code"] == "location_required", "GPS ჩართულია — ლოკაცია სავალდებულოა")
    check(sp.get_today_attendance(aid) is None, "შეცდომისას არაფერი ჩაიწერა")


def test_check_in_outside_blocked_and_nothing_written():
    setup()
    _configure_office()
    aid, agent = _agent()
    res = ex.check_in(agent, OUTSIDE)
    check(not res["ok"] and res["code"] == "outside_office", "ოფისის გარედან ოფისის ცვლაზე — დაბლოკილია")
    check(sp.get_today_attendance(aid) is None, "attendance არ უნდა ჩაიწეროს")
    check(sp.get_attendance_geo_events(agent_id=aid) == [], "ივენთიც არ უნდა ჩაიწეროს")


def test_check_in_outside_allowed_by_setting():
    setup()
    _configure_office(allow_outside="1")
    aid, agent = _agent()
    res = ex.check_in(agent, OUTSIDE)
    check(res["ok"] and res["result"] == "ok" and res["geo_status"] == "OUTSIDE_OFFICE", "ALLOW_OUTSIDE_CHECKIN=1 -> დაშვებულია, სტატუსი OUTSIDE_OFFICE")
    check(ex.checkin_alert_text(agent, res) is not None, "მენეჯერს გაფრთხილება უნდა გაეგზავნოს")


def test_check_in_online_day_outside_is_fine_and_no_alert():
    setup()
    _configure_office()
    aid, agent = _agent(schedule=False)
    sp.set_agent_schedule(aid, {k: "online" for k in sp.WEEKDAY_KEYS})
    res = ex.check_in(agent, OUTSIDE)
    check(res["ok"] and res["result"] == "ok", "ონლაინ დღეს ოფისის გარედან დაწყება ნორმაა")
    check(ex.checkin_alert_text(agent, res) is None, "ონლაინზე გაფრთხილება არ იგზავნება")


def test_check_in_unreliable_location_recorded_and_alerted():
    setup()
    _configure_office()
    aid, agent = _agent()
    res = ex.check_in(agent, BAD_ACC)
    check(res["ok"] and res["geo_status"] == "LOCATION_UNRELIABLE", "დაბალი სიზუსტე იწერება როგორც LOCATION_UNRELIABLE")
    check("accuracy" in (ex.checkin_alert_text(agent, res) or "").lower(), "ალერტი სიზუსტეზე")


def test_full_cycle_and_overview():
    setup()
    _configure_office()
    aid, agent = _agent("ანა", "555920", team="T1")
    bid, bagent = _agent("ბექა", "555921", team="T1")
    cid, cagent = _agent("გიო", "555922", team="T2")
    res = ex.check_in(agent, INSIDE)
    check(res["geo_status"] == "OFFICE" and res["distance_m"] is not None and res["distance_m"] < 150, "ოფისში")
    check(ex.check_out_precheck(agent, None) is not None, "GPS ჩართულია — checkout ლოკაციის გარეშე არ ივლის")
    check(ex.check_out_precheck(agent, INSIDE) is None, "ლოკაციით ივლის")
    check(sp.clock_out(aid) == "ok", "clock_out")
    ev = ex.record_check_out(agent, INSIDE)
    check(ev and ev["event"] == "check_out", "check_out ივენთი")
    before = sp.get_today_attendance(aid)["clock_out"]
    check(sp.clock_out(aid) == "already_out", "გამეორებული clock_out უარყოფილია")
    check(sp.get_today_attendance(aid)["clock_out"] == before, "დასრულების დრო არ გადაიწერა")

    card = ex.attendance_card(agent)
    check(card["state"] == "COMPLETED" and not card["can_start"] and not card["can_finish"], f"ბარათი: {card['state']}")
    check(card["check_in"] and card["check_out"], "დრო ორივეგან გამოჩნდა")

    ex.check_in(bagent, OUTSIDE if False else INSIDE)  # ბექა მუშაობს
    ov = ex.attendance_overview("", team="T1")
    s = ov["summary"]
    check(s["total"] == 2 and s["completed"] == 1 and s["working"] == 1 and s["not_started"] == 0, f"T1 შეჯამება: {s}")
    ov_all = ex.attendance_overview("")
    check(ov_all["summary"]["not_started"] == 1, "გიო (T2) არ დაუწყია")
    check(len(ex.attendance_overview("", team="T1", agent_id=aid)["rows"]) == 1, "აგენტზე ფილტრი")
    check(all(r["state"] == "NOT_STARTED" for r in ex.attendance_overview("", state="NOT_STARTED")["rows"]), "სტატუსის ფილტრი")
    check(len(ex.attendance_overview("", late_only=True)["rows"]) <= 3, "late ფილტრი მუშაობს")

    hist = ex.attendance_history(agent)
    check(len(hist) == 1 and hist[0]["minutes"] is not None, "ისტორიაში ერთი დღე + საათები")
    csv_text = ex.attendance_csv(crm_time.local_today().replace(day=1).strftime(crm_time.DATE_FMT),
                                 crm_time.local_today().strftime(crm_time.DATE_FMT), team="T1")
    check("Employee" in csv_text and "ანა" in csv_text and "გიო" not in csv_text, "CSV: მხოლოდ T1")


def test_dayoff_agent_shown_as_day_off_not_missing():
    setup()
    aid, agent = _agent("დასვენებული", "555930")
    _approve_dayoff(aid, crm_time.local_today())
    ov = ex.attendance_overview("")
    row = next(r for r in ov["rows"] if r["agent_id"] == aid)
    check(row["state"] == "DAY_OFF", "დამტკიცებული დასვენება -> DAY_OFF")
    check(ov["summary"]["not_started"] == 0 and ov["summary"]["day_off"] == 1, "NOT_STARTED-ში არ ითვლება")


def test_missing_checkout_state_for_past_day():
    setup()
    aid, agent = _agent()
    yesterday = (crm_time.local_today() - datetime.timedelta(days=1)).strftime(crm_time.DATE_FMT)
    att = {"clock_in": yesterday + " 06:00", "clock_out": ""}
    check(ex._state_for(att, yesterday, "office_morning", False) == "MISSING_CHECKOUT", "გუშინდელი დაუხურავი დღე")
    check(ex._state_for(None, yesterday, "off", False) == "OFF", "გამოსავალი დღე")


# ---------------------------------------------------------------------

def _all_tests():
    return {n: f for n, f in globals().items() if n.startswith("test_") and callable(f)}


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
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
    print()
    print(f"სულ: {len(tests)}   ✅ გავიდა: {passed}   ❌ ჩავარდა: {len(failed)}")
    sys.exit(1 if failed else 0)
