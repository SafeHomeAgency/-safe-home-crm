"""
v4.0 API-ტესტები (Flask test client): უფლებები, GPS check-in/out,
რაიონები, მულტი-მონიშვნა, Day off თარიღი.

ავტორიზაცია (`_authed_agent`) ტესტში ჩანაცვლებულია — Telegram initData-ს
HMAC-ის შემოწმება აქ არ ვტესტავთ. Telegram-ში გაგზავნა ჩანაცვლებულია
ჩამწერით (არაფერი ნამდვილად არ იგზავნება).

    python3 test_webserver_v4.py
"""

from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST")
os.environ.setdefault("ADMIN_CHAT_IDS", "1")

import test_crm_v4 as t4  # ყალბი db + sys.modules["sheets"] = sp

sp = t4.sp
import webserver as ws  # noqa: E402
import crm_time  # noqa: E402

check = t4.check

SENT: list[tuple] = []
ws._send_telegram_message = lambda chat_id, text, **kw: SENT.append((chat_id, text)) or True
ws._send_telegram_document = lambda chat_id, fname, data, caption="": SENT.append((chat_id, fname)) or True

_CURRENT = {"agent": None, "admin": False}


def _fake_auth():
    return _CURRENT["agent"], _CURRENT["admin"], None


ws._authed_agent = _fake_auth
ws._requester_chat_id = lambda: 999
client = ws.app.test_client()


def as_agent(agent):
    _CURRENT.update(agent=agent, admin=False)


def as_admin():
    _CURRENT.update(agent=None, admin=True)


def _lead(team="T1"):
    aid = sp.add_agent("ლიდერი-" + team, "55590" + team[-1], team=team)
    sp.set_agent_role(aid, "team_lead")
    sp.register_agent_chat_id(aid, 7000 + int(team[-1]), "l")
    return next(a for a in sp.get_agents() if a["agent_id"] == aid)


def _members():
    setup = t4.setup
    setup()
    SENT.clear()
    lead1 = _lead("T1")
    lead2 = _lead("T2")
    a1, ag1 = t4._agent("აგენტი1", "555941", team="T1")
    a2, ag2 = t4._agent("აგენტი2", "555942", team="T2")
    return lead1, lead2, ag1, ag2


def test_attendance_permissions():
    lead1, lead2, ag1, ag2 = _members()
    as_agent(ag1)
    check(client.get("/api/attendance/overview").status_code == 403, "აგენტს მენეჯერის დასწრება არ უნდა ჩანდეს")
    check(client.get("/api/attendance/settings").status_code == 403, "პარამეტრები — მხოლოდ ადმინს")
    check(client.post("/api/attendance/settings", json={"office_radius_meters": 100}).status_code == 403, "პარამეტრის შეცვლა — მხოლოდ ადმინს")
    as_agent(lead1)
    r = client.get("/api/attendance/overview?team=T2")  # ?team იგნორირდება თიმლიდერზე
    names = {x["agent_name"] for x in r.get_json()["rows"]}
    check("აგენტი2" not in names and "აგენტი1" in names, f"თიმლიდერი მხოლოდ საკუთარ გუნდს ხედავს: {names}")
    check(client.get(f"/api/attendance/history?agent_id={ag2['agent_id']}").status_code == 403, "სხვა გუნდის ისტორია აკრძალულია")
    check(client.get(f"/api/attendance/history?agent_id={ag1['agent_id']}").status_code == 200, "საკუთარი გუნდის ისტორია ღიაა")
    as_admin()
    names = {x["agent_name"] for x in client.get("/api/attendance/overview").get_json()["rows"]}
    check({"აგენტი1", "აგენტი2"} <= names, "ადმინი ყველას ხედავს")
    j = client.get("/api/attendance/overview").get_json()
    check("office_latitude" in j["settings"], "ადმინს კოორდინატებიც ეძლევა")
    as_agent(lead1)
    check("office_latitude" not in client.get("/api/attendance/overview").get_json()["settings"], "თიმლიდერს კოორდინატი არ ეძლევა")


def test_admin_settings_roundtrip_and_validation():
    _members()
    as_admin()
    check(client.post("/api/attendance/settings", json={"office_latitude": "41.7151"}).status_code == 400, "განედი მარტო — 400")
    r = client.post("/api/attendance/settings", json={
        "office_name": "მთავარი", "office_latitude": "41.7151", "office_longitude": "44.8271",
        "office_radius_meters": "120", "max_accuracy_meters": "80", "allow_outside_checkin": False})
    check(r.status_code == 200 and r.get_json()["settings"]["configured"], "შენახულია და აქტიურია")
    check(ws.crm_extras.attendance_settings()["office_radius_meters"] == 120, "მაშინვე მოქმედებს")


def test_clockin_clockout_with_gps_over_http():
    lead1, lead2, ag1, ag2 = _members()
    t4._configure_office()
    as_agent(ag1)
    r = client.post("/api/clockin", json={})
    check(r.status_code == 400 and r.get_json()["code"] == "location_required", "ლოკაციის გარეშე 400")
    r = client.post("/api/clockin", json={"lat": "abc", "lng": 1})
    check(r.status_code == 400 and r.get_json()["code"] == "invalid_location", "არასწორი კოორდინატი 400")
    r = client.post("/api/clockin", json=t4.OUTSIDE)
    check(r.status_code == 403 and r.get_json()["code"] == "outside_office", "ოფისის გარედან — 403")
    check(sp.get_today_attendance(ag1["agent_id"]) is None, "დაბლოკვისას არაფერი ჩაწერილა")
    r = client.post("/api/clockin", json=t4.INSIDE)
    j = r.get_json()
    check(r.status_code == 200 and j["result"] == "ok" and j["geo_status"] == "OFFICE", f"ოფისში: {j}")
    check(j["attendance"]["state"] in ("ACTIVE",), "ბარათი ACTIVE")
    check(client.post("/api/clockin", json=t4.INSIDE).get_json()["result"] == "already", "დუბლირებული check-in")
    check(len(sp.get_attendance_geo_events(agent_id=ag1["agent_id"])) == 1, "ივენთი მხოლოდ ერთი")

    r = client.post("/api/clockout", json={"site": 0, "ssge": 0})
    check(r.status_code == 400 and r.get_json()["code"] == "location_required", "checkout ლოკაციის გარეშე 400")
    check(sp.get_today_attendance(ag1["agent_id"])["clock_out"] == "", "დღე არ დაიხურა")
    r = client.post("/api/clockout", json=dict(t4.INSIDE, site=0, ssge=0))
    check(r.status_code == 200 and r.get_json()["result"] == "ok", f"checkout: {r.get_json()}")
    check(r.get_json()["attendance"]["state"] == "COMPLETED", "ბარათი COMPLETED")
    r2 = client.post("/api/clockout", json=dict(t4.INSIDE, site=0, ssge=0))
    check(r2.get_json()["result"] == "already_out", "დუბლირებული checkout უარყოფილია")
    quota_warnings = [w for w in sp.get_warnings(agent_id=ag1["agent_id"]) if w["type"] == "quota_missed"]
    check(len(quota_warnings) == 1, f"quota გაფრთხილება ზუსტად ერთხელ (იყო {len(quota_warnings)})")
    check(len(sp.get_attendance_geo_events(agent_id=ag1["agent_id"])) == 2, "ივენთები: check_in + check_out")


def test_clockout_no_warning_on_approved_dayoff():
    lead1, lead2, ag1, ag2 = _members()
    as_agent(ag1)
    client.post("/api/clockin", json={})
    t4._approve_dayoff(ag1["agent_id"], crm_time.local_today())
    r = client.post("/api/clockout", json={"site": 0, "ssge": 0})
    check(r.status_code == 200, "checkout გაიარა")
    check(sp.get_warnings(agent_id=ag1["agent_id"]) == [], "დღეოფზე quota_missed არ ჩაიწერა")


def test_clockout_myhome_count_is_server_side():
    lead1, lead2, ag1, ag2 = _members()
    as_agent(ag1)
    client.post("/api/clockin", json={})
    r = client.post("/api/clockout", json={"site": 0, "ssge": 0, "myhome": 99})   # ტყუილი უგულებელყოფილია
    check(r.status_code == 200, "ok")
    att = sp.get_today_attendance(ag1["agent_id"])
    check(str(att["myhome_count"]) in ("0", ""), f"myhome ავტომატურად ითვლება, არა 99: {att['myhome_count']!r}")


def test_dayoff_request_endpoint_date_validation():
    lead1, lead2, ag1, ag2 = _members()
    as_agent(ag1)
    today = crm_time.local_today()
    check(client.post("/api/dayoff/request", json={"date": "ხვალ"}).status_code == 400, "ტექსტი თარიღი არ ვარგა")
    past = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    check(client.post("/api/dayoff/request", json={"date": past}).status_code == 400, "წარსული არ შეიძლება")
    day = (today + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    r = client.post("/api/dayoff/request", json={"date": day, "reason": "პირადი"})
    check(r.status_code == 200 and r.get_json()["date"] == day, "ISO თარიღით ინახება")
    check(client.post("/api/dayoff/request", json={"date": day}).status_code == 409, "იგივე თარიღზე დუბლიკატი 409")
    mine = client.get("/api/dayoff/mine").get_json()
    check(len(mine["rows"]) == 1, "ჩემი მოთხოვნები სიაში ჩანს")
    check(any(c[0] == 1 for c in SENT), "ადმინს შეტყობინება გაეგზავნა")
    check(any(c[0] == lead1["telegram_chat_id"] or str(c[0]) == str(lead1["telegram_chat_id"]) for c in SENT), "თიმლიდერსაც")


def test_districts_flow_and_permissions():
    lead1, lead2, ag1, ag2 = _members()
    week = crm_time.local_today().strftime("%Y-%m-%d")
    as_agent(ag1)
    check(client.get("/api/districts").status_code == 403, "აგენტს განაწილების სია არ ჩანს")
    check(client.post("/api/districts/assign", json={"week": week, "agent_ids": [ag1["agent_id"]], "districts": ["ვაკე"]}).status_code == 403,
          "აგენტი ვერ ანაწილებს")
    as_agent(lead1)
    r = client.post("/api/districts/assign", json={"week": week, "agent_ids": [ag2["agent_id"]], "districts": ["ვაკე"]})
    check(r.status_code == 403, "თიმლიდერი სხვა გუნდის აგენტს ვერ ანაწილებს")
    r = client.post("/api/districts/assign", json={"week": week, "agent_ids": [ag1["agent_id"]], "districts": ["ვაკე", "ისანი-სამგორი", "ისანი"]})
    check(r.status_code == 200 and r.get_json()["changed"] == 1, f"მინიჭება: {r.get_json()}")
    check(any("ვაკე" in c[1] and "წარმატებას" in c[1] for c in SENT), "აგენტს მოუვიდა შეტყობინება")
    n = len(SENT)
    client.post("/api/districts/assign", json={"week": week, "agent_ids": [ag1["agent_id"]], "districts": ["ვაკე", "ისანი-სამგორი", "ისანი"]})
    check(len(SENT) == n, "იგივე მნიშვნელობაზე განმეორებითი შეტყობინება არ იგზავნება")
    check(client.post("/api/districts/assign", json={"week": week, "agent_ids": [ag1["agent_id"]], "districts": ["სულ სხვა"]}).status_code == 400, "უცნობი რაიონი 400")
    old = (crm_time.local_today() - datetime.timedelta(days=14)).strftime("%Y-%m-%d")
    check(client.post("/api/districts/assign", json={"week": old, "agent_ids": [ag1["agent_id"]], "districts": ["ვაკე"]}).status_code == 400, "წარსული კვირა დაბლოკილია")
    j = client.get("/api/districts").get_json()
    row = next(a for a in j["agents"] if a["agent_id"] == ag1["agent_id"])
    check(row["districts"] == ["ვაკე", "ისანი-სამგორი", "ისანი"], "მენეჯერი ხედავს მინიჭებულს")
    check(all(a["team"] == "T1" for a in j["agents"]), "თიმლიდერს მხოლოდ საკუთარი გუნდი")
    as_agent(ag1)
    mine = client.get("/api/districts/mine").get_json()
    check(mine["districts"] == ["ვაკე", "ისანი-სამგორი", "ისანი"], "აგენტი ხედავს საკუთარს")
    dash = client.get("/api/dashboard").get_json()
    check(dash["districts"]["districts"] and "attendance" in dash, "დაშბორდზე რაიონები + attendance ბარათი")


def test_bulk_warning_endpoints_permissions():
    lead1, lead2, ag1, ag2 = _members()
    w1 = sp.add_warning(ag1["agent_id"], "late_arrival", "a")["warning_id"]
    w2 = sp.add_warning(ag2["agent_id"], "late_arrival", "b")["warning_id"]
    as_agent(ag1)
    check(client.post("/api/warnings/request-dismiss-bulk", json={"warning_ids": [w1], "reason": "x"}).status_code == 403, "აგენტი ვერ ითხოვს")
    as_agent(lead1)
    r = client.post("/api/warnings/request-dismiss-bulk", json={"warning_ids": [w1, w2], "reason": "შეხვედრა"})
    j = r.get_json()
    check(r.status_code == 200 and j["requested"] == 1 and j["skipped"] == 1, f"სხვა გუნდის გაფრთხილება გამოტოვებულია: {j}")
    check(client.post("/api/warnings/request-dismiss-bulk", json={"warning_ids": [w1]}).status_code == 400, "მიზეზი სავალდებულოა")
    check(client.post("/api/warnings/decide-dismiss-bulk", json={"warning_ids": [w1], "approve": True}).status_code == 403, "თიმლიდერი ვერ ამტკიცებს")
    as_admin()
    r = client.post("/api/warnings/decide-dismiss-bulk", json={"warning_ids": [w1, w2], "approve": True})
    check(r.get_json()["decided"] == 1 and r.get_json()["skipped"] == 1, "ადმინი ამტკიცებს მხოლოდ pending-ს")
    check(next(w for w in sp.get_warnings() if w["warning_id"] == w1)["status"] == "dismissed", "w1 გაუქმდა")


def test_tasks_new_notes_and_owner_phone():
    lead1, lead2, ag1, ag2 = _members()
    as_admin()
    r = client.post("/api/tasks/new", json={"kind": "listing", "agent_id": ag1["agent_id"], "listing_id": "L9",
                                            "phone": "599000111", "owner_phone": "577000222", "notes": "მეტი დეტალი"})
    check(r.status_code == 200, f"listing: {r.get_json()}")
    r = client.post("/api/tasks/new", json={"kind": "general", "phone": "599000333", "deal_type": "ქირა",
                                            "priority": "მაღალი", "notes": "ზოგადი დეტალი"})
    check(r.status_code == 200, f"general: {r.get_json()}")
    tasks = {t["client_phone"]: t for t in sp.get_tasks()}
    check(tasks["599000111"]["owner_phone"] == "577000222" and tasks["599000111"]["description"] == "მეტი დეტალი", "listing: owner_phone+notes")
    check(tasks["599000333"]["description"] == "ზოგადი დეტალი", "general: notes description-ში")
    check("ვიზიტის დრო" not in tasks["599000111"]["description"], "ნახვის დრო აღარ იწერება description-ში (დუბლირება აღარ არის)")


def test_clients_endpoint_shows_all_data():
    lead1, lead2, ag1, ag2 = _members()
    sp.create_task(title="კლ", description="", assigned_to=ag1["agent_id"], priority="მაღალი", due_date="", created_by="admin", client_phone="+995 599 11 22 33")
    sp.create_report(agent_id=ag2["agent_id"], client_phone="599112233", actions="დარეკვა", notes="", file_id="")
    sp.create_exclusive(ag1["agent_id"], {"owner_phone": "0599112233", "location": "ვაკე"})
    as_admin()
    rows = client.get("/api/clients").get_json()["rows"]
    check(len(rows) == 1, "ერთი კლიენტი")
    tl = client.get("/api/clients/" + rows[0]["phone_key"]).get_json()["timeline"]
    kinds = sorted(e["kind"] for e in tl)
    check(kinds == ["exclusive", "report", "task"], f"ყველა წყარო ერთად: {kinds}")
    as_agent(lead2)
    check(client.get("/api/clients/599112233").status_code == 200, "T2 ხედავს (მისი აგენტის რეპორტია)")
    lead3 = _lead("T3")
    as_agent(lead3)
    check(client.get("/api/clients/599112233").status_code == 403, "უცხო გუნდს აკრძალულია")


def test_csv_export_endpoint():
    lead1, lead2, ag1, ag2 = _members()
    as_agent(ag1)
    client.post("/api/clockin", json={})
    as_agent(ag1)
    check(client.post("/api/attendance/export", json={}).status_code == 403, "აგენტს ექსპორტი არ შეუძლია")
    as_agent(lead1)
    r = client.post("/api/attendance/export", json={})
    check(r.status_code == 200, f"export: {r.get_json()}")
    check(any(str(c[1]).startswith("attendance_") for c in SENT), "CSV ფაილი გაიგზავნა")


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
            import traceback
            failed.append((name, e))
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
    print()
    print(f"სულ: {len(tests)}   ✅ გავიდა: {passed}   ❌ ჩავარდა: {len(failed)}")
    sys.exit(1 if failed else 0)
