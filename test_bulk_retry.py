"""
ტესტები — ჩავარდნილი MyHome job-ების ერთიანად ხელახლა გაშვება (`myhome_bulk_retry`).

გაშვება:  python test_bulk_retry.py
"""

from __future__ import annotations

import datetime
import os
import sys
import time

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST")
os.environ["ADMIN_CHAT_IDS"] = "1"

import test_phase15 as t  # noqa: E402

Skip, check, H = t.Skip, t.check, t.H
import config  # noqa: E402
import crm_time  # noqa: E402


def _setup():
    if t.sg is None or t.ws is None:
        raise Skip("gspread/flask არ არის")
    t._setup_sg()
    c = t._api_setup(t.sg)
    t.ws.sheets = t.sg
    config.RATE_LIMIT_ENABLED = False
    import myhome_bulk_retry as br
    br._state.update(running=False, total=0, done=0, failed=0)
    return c, br


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def _job(agent, listing, status, **fields):
    jid = t.sg.create_myhome_job(agent, {"team": "T1", "manager_label": "m1", "myhome_listing_id": listing,
                                         "owner_number": "599123456"})
    t.raw_update(t.sg, jid, status=status, **fields)
    return jid


def _wait_done(c, br, secs=10):
    end = time.time() + secs
    while time.time() < end:
        st = c.get("/api/myhome-jobs/retry-failed/status", headers=H(1)).get_json()
        if not st["running"]:
            return st
        time.sleep(0.05)
    return st


def _status(jid):
    return t.sg.find_myhome_job(jid)["status"]


def test_classification_and_dry_run_changes_nothing():
    c, br = _setup()
    a = t._agent(t.sg, "ნინო", 11)
    safe = _job(a, "1", "FAILED", failure_stage="preparing", error_message="TimeoutException")
    safe2 = _job(a, "2", "FAILED", failure_stage="", error_message="ConnectionError")
    pay = _job(a, "3", "FAILED", failure_stage="payment", error_message="გადახდა ვერ დასრულდა")
    perm = _job(a, "4", "FAILED", failure_stage="permanent", error_message="LISTING_UNAVAILABLE: წაშლილი")
    perm2 = _job(a, "5", "FAILED", failure_stage="", error_message="LISTING_UNAVAILABLE: x")
    paid = _job(a, "6", "FAILED", failure_stage="paid", error_message="db ჩაწერა ჩავარდა")
    _job(a, "7", "FAILED", failure_stage="preparing", error_message="Timeout")      # იგივე ID-ით COMPLETED არსებობს
    _job(a, "7", "COMPLETED")
    queued = _job(a, "8", "QUEUED")
    start, _e = crm_time.local_day_bounds_server_naive()
    old = _job(a, "9", "FAILED", failure_stage="preparing", error_message="x", created_at=_fmt(start - datetime.timedelta(days=5)))
    before = {j: _status(j) for j in (safe, safe2, pay, perm, perm2, paid, queued, old)}
    r = c.post("/api/myhome-jobs/retry-failed", headers=H(1), json={"dry_run": True})
    j = r.get_json()
    check(r.status_code == 200 and j["dry_run"] and j["safe"] == 2 and j["payment"] == 1, f"dry-run: safe=2 payment=1: {j}")
    check(j["skipped"]["permanent"] == 2 and j["skipped"]["paid"] == 1 and j["skipped"]["done"] == 1 and j["skipped"]["old"] == 1,
          f"გამოტოვებული: {j['skipped']}")
    check({k: _status(k) for k in before} == before, "dry-run: არცერთი job არ შეცვლილა")


def test_retry_safe_only_by_default_and_payment_with_consent():
    c, br = _setup()
    a = t._agent(t.sg, "ნინო", 11)
    safe = _job(a, "1", "FAILED", failure_stage="preparing", error_message="Timeout", retry_count="3")
    pay = _job(a, "3", "FAILED", failure_stage="payment", error_message="გადახდა ვერ დასრულდა")
    perm = _job(a, "4", "FAILED", failure_stage="permanent", error_message="LISTING_UNAVAILABLE")
    paid = _job(a, "6", "FAILED", failure_stage="paid", error_message="x")
    r = c.post("/api/myhome-jobs/retry-failed", headers=H(1), json={})
    check(r.status_code == 200 and r.get_json()["started"], "გაშვება დაიწყო")
    st = _wait_done(c, br)
    check(st["done"] == 1 and st["failed"] == 0, f"დაბრუნდა 1: {st}")
    check(_status(safe) == "QUEUED" and _status(pay) == "FAILED" and _status(perm) == "FAILED" and _status(paid) == "FAILED",
          "ნაგულისხმევად მხოლოდ უსაფრთხო დაბრუნდა; გადახდის ეტაპი, არარსებული ID და paid — არა")
    check(t.sg.find_myhome_job(safe)["retry_count"] == "3", "retry_count უცვლელია (ისტორია არ იკარგება)")
    r = c.post("/api/myhome-jobs/retry-failed", headers=H(1), json={"include_payment": True})
    st = _wait_done(c, br)
    check(_status(pay) == "QUEUED" and _status(perm) == "FAILED" and _status(paid) == "FAILED",
          "ცალსახა თანხმობით გადახდის ეტაპიც დაბრუნდა; არარსებული ID და paid მაინც არა")


def test_admin_only_and_no_double_run_and_audit():
    c, br = _setup()
    a = t._agent(t.sg, "ნინო", 11)
    t._agent(t.sg, "ლიდერი", 12, role="team_lead")
    _job(a, "1", "FAILED", failure_stage="preparing", error_message="x")
    check(c.post("/api/myhome-jobs/retry-failed", json={}).status_code == 401, "ავტორიზაციის გარეშე 401")
    check(c.post("/api/myhome-jobs/retry-failed", headers=H(11), json={}).status_code == 403, "აგენტს 403")
    check(c.post("/api/myhome-jobs/retry-failed", headers=H(12), json={}).status_code == 403, "თიმლიდერს 403")
    check(c.get("/api/myhome-jobs/retry-failed/status", headers=H(11)).status_code == 403, "status აგენტს 403")
    br._state["running"] = True
    check(c.post("/api/myhome-jobs/retry-failed", headers=H(1), json={}).status_code == 409, "მიმდინარეობისას მეორე გაშვება 409")
    br._state["running"] = False
    c.post("/api/myhome-jobs/retry-failed", headers=H(1), json={})
    _wait_done(c, br)
    t.sg.flush_audit_log()
    ev = [e for e in t.sg.get_audit_events(limit=50) if e["action"] == "myhome_bulk_retry"]
    check(len(ev) == 1 and str(ev[0]["actor_telegram_id"]) == "1", "AuditLog: ადმინის ID-ით ჩაიწერა")


def test_jobs_list_is_limited_newest_first():
    c, br = _setup()
    a = t._agent(t.sg, "ნინო", 11)
    t._agent(t.sg, "გიო", 12)
    start, _e = crm_time.local_day_bounds_server_naive()
    for i in range(30):
        _job(a, str(1000 + i), "COMPLETED", created_at=_fmt(start + datetime.timedelta(minutes=i)))
    r = c.get("/api/myhome-jobs?limit=10", headers=H(1)).get_json()
    check(len(r["rows"]) == 10 and r["total"] == 30, f"limit=10: rows={len(r['rows'])} total={r['total']}")
    ids = [x["myhome_listing_id"] for x in r["rows"]]
    check(ids[0] == "1029", f"უახლესი პირველია: {ids[:3]}")
    r = c.get("/api/myhome-jobs", headers=H(1)).get_json()
    check(len(r["rows"]) == 30 and r["total"] == 30, "ნაგულისხმევი ლიმიტი 150 — 30 ჩანაწერი სრულად")
    r = c.get("/api/myhome-jobs?limit=abc", headers=H(1)).get_json()
    check(len(r["rows"]) == 30, "არასწორი limit -> ნაგულისხმევი")
    r = c.get("/api/myhome-jobs?limit=0", headers=H(1)).get_json()
    check(len(r["rows"]) == 1, "limit მინიმუმ 1")
    r = c.get("/api/myhome-jobs?limit=5", headers=H(11)).get_json()
    check(len(r["rows"]) == 5 and r["total"] == 30, "აგენტსაც იგივე ლიმიტი (საკუთარი job-ებიდან)")
    r = c.get("/api/myhome-jobs?limit=5", headers=H(12)).get_json()
    check(r["rows"] == [] and r["total"] == 0, "სხვა აგენტს სხვისი job-ები არ ჩანს")


def test_worker_export_endpoint():
    c, br = _setup()
    config.MYHOME_WORKER_API_KEY = "k"
    a = t._agent(t.sg, "ნინო", 11)
    start, _e = crm_time.local_day_bounds_server_naive()
    done_in = _job(a, "7001", "COMPLETED", completed_at=_fmt(start + datetime.timedelta(hours=3)), owner_number="599777888", agent_name="ნინო")
    _job(a, "7002", "COMPLETED", completed_at=_fmt(start - datetime.timedelta(days=3)))     # ფანჯრის გარეთ
    _job(a, "7003", "FAILED", completed_at=_fmt(start + datetime.timedelta(hours=3)))        # არა COMPLETED
    since = _fmt(start)
    check(c.get("/internal/myhome-jobs/export?since=" + since).status_code == 401, "worker გასაღების გარეშე 401")
    check(c.get("/internal/myhome-jobs/export?since=" + since, headers=H(1)).status_code == 401, "ადმინის initData არ გამოდგება")
    r = c.get("/internal/myhome-jobs/export", headers=t.WH)
    check(r.status_code == 400, "since გარეშე 400")
    r = c.get("/internal/myhome-jobs/export?since=" + since, headers=t.WH)
    j = r.get_json()
    check(r.status_code == 200 and j["total"] == 1 and j["rows"][0]["job_id"] == done_in, f"მხოლოდ ფანჯარაში მოქცეული COMPLETED: {j.get('total')}")
    check(j["rows"][0]["agent_name"] == "ნინო" and j["rows"][0]["owner_number"] == "599777888", "agent_name და owner_number ბრუნდება")
    check(r.headers.get("Cache-Control") == "no-store", "no-store")


def test_export_failed_and_recover_paid_job():
    c, br = _setup()
    config.MYHOME_WORKER_API_KEY = "k"
    a = t._agent(t.sg, "ნინო", 21)
    start, _e = crm_time.local_day_bounds_server_naive()
    ts = _fmt(start + datetime.timedelta(hours=3))
    paid = _job(a, "8001", "FAILED", completed_at=ts, failure_stage="paid", error_message="TimeoutException ID", agent_name="ნინო", owner_number="599111222")
    pay_stage = _job(a, "8002", "FAILED", completed_at=ts, failure_stage="payment", error_message="x")
    prep = _job(a, "8003", "FAILED", completed_at=ts, failure_stage="preparing", error_message="y")
    since = _fmt(start)
    j = c.get("/internal/myhome-jobs/export?since=" + since + "&status=FAILED", headers=t.WH).get_json()
    ids = {r["job_id"]: r for r in j["rows"]}
    check(set(ids) == {paid, pay_stage, prep}, f"status=FAILED აბრუნებს ჩავარდნილებს: {sorted(ids)}")
    check(ids[paid]["failure_stage"] == "paid" and ids[paid]["owner_number"] == "599111222", "failure_stage/owner_number ბრუნდება")
    check(c.get("/internal/myhome-jobs/export?since=" + since + "&status=NOPE", headers=t.WH).status_code == 400, "არასწორი status 400")
    # recover
    url = f"/internal/myhome-jobs/{paid}/recover"
    check(c.post(url, json={"listing_id": "26301255"}).status_code == 401, "recover: გასაღების გარეშე 401")
    check(c.post(url, json={}, headers=t.WH).status_code == 400, "recover: listing_id სავალდებულოა")
    check(c.post(url, json={"listing_id": "abc"}, headers=t.WH).status_code == 400, "recover: არაციფრული ID უარყოფილია")
    r = c.post(url, json={"listing_id": "26301255"}, headers=t.WH)
    check(r.status_code == 200 and r.get_json()["code"] == "ok" and _status(paid) == "COMPLETED", "paid-ზე ჩავარდნილი -> COMPLETED")
    r = c.post(url, json={"listing_id": "26301255"}, headers=t.WH)
    check(r.status_code == 200 and r.get_json()["code"] == "duplicate", "განმეორებით — უვნებელი duplicate")
    r = c.post(f"/internal/myhome-jobs/{prep}/recover", json={"listing_id": "26301256"}, headers=t.WH)
    check(r.status_code == 409 and _status(prep) == "FAILED", "preparing-ზე ჩავარდნილი არ აღდგება (განცხადება არ დადებულა)")
    r = c.post("/internal/myhome-jobs/nope1234/recover", json={"listing_id": "26301257"}, headers=t.WH)
    check(r.status_code == 404, "უცნობი job 404")


def test_wiring_and_ui_present():
    here = os.path.dirname(os.path.abspath(__file__))
    web = open(os.path.join(here, "webserver.py"), encoding="utf-8").read()
    js = open(os.path.join(here, "app.js"), encoding="utf-8").read()
    check("myhome_bulk_retry.register" in web, "webserver: რეგისტრაცია")
    check("runBulkRetry" in js and 'id="mhRetryBtn"' in js and "retry-failed" in js, "app.js: ღილაკი + გამოძახება")


# ----------------------------------------------------------------------------------

def _all_tests():
    return {n: f for n, f in globals().items() if n.startswith("test_") and callable(f)}


if __name__ == "__main__":
    tests = _all_tests()
    passed, failed, errors, skipped = 0, [], [], []
    for name, fn in tests.items():
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except Skip as e:
            skipped.append((name, str(e)))
            print(f"  ⏭  {name}: გამოტოვებულია — {e}")
        except AssertionError as e:
            failed.append((name, e))
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            import traceback
            errors.append((name, e))
            print(f"  💥 {name}: {type(e).__name__}: {e}")
            traceback.print_exc(limit=4)
    print()
    print(f"სულ: {len(tests)}   ✅ გავიდა: {passed}   ❌ ჩავარდა: {len(failed)}   💥 შეცდომა: {len(errors)}   ⏭ გამოტოვებული: {len(skipped)}")
    sys.exit(1 if (failed or errors) else 0)
