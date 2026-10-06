"""
ჩავარდნილი MyHome job-ების ერთიანად ხელახლა გაშვება (მხოლოდ ადმინი) — ღილაკი Mini App-ის MyHome ჩანართში.

რა ხდება: FAILED job-ები უბრუნდება რიგს (იგივე `retry_myhome_job`, რასაც ცალკეული „ხელახლა ცდა“ იყენებს), worker
კი სათითაოდ ამუშავებს. უსაფრთხოების წესები (ორმაგი გადახდისა და ზედმეტი ასლებისგან):
  * **არასდროს** ბრუნდება: `permanent` / `LISTING_UNAVAILABLE` (არარსებული ID — ხელახლა უშედეგოა), `paid`
    (უკვე გადახდილი/გამოქვეყნებული), და ის job, რომლისთვისაც იმავე აგენტს იმავე ID-ით COMPLETED job უკვე აქვს;
  * `payment` ეტაპზე ჩავარდნილი (გადახდამდე ფორმა/MyHome-ის გადახდის შეცდომა) ცალკე კატეგორიაა და
    ბრუნდება **მხოლოდ** ცალსახა თანხმობით (`include_payment=true`);
  * ნაგულისხმევად მხოლოდ ბოლო 2 დღის (თბილისი) job-ები;
  * ფონური thread-ი (Sheets-ის კვოტა ნელა გადის ბევრ ჩაწერას) + სტატუსი; ერთდროულად მხოლოდ ერთი გაშვება.
"""

from __future__ import annotations

import datetime
import logging
import threading

from flask import jsonify, request

import crm_time

log = logging.getLogger("safehome-bulk-retry")

MAX_JOBS = 80

_state = {"running": False, "total": 0, "done": 0, "failed": 0, "started_at": "", "finished_at": ""}
_lock = threading.Lock()


def _job_day_ok(job: dict, days: int) -> bool:
    created = crm_time.parse_server_dt(job.get("created_at"))
    if not created:
        return False
    cutoff = crm_time.local_day_bounds_server_naive()[0] - datetime.timedelta(days=max(days - 1, 0))
    return created >= cutoff


def classify(jobs: list[dict], days: int = 2) -> dict:
    """აბრუნებს {"safe": [...], "payment": [...], "skipped": {"permanent": n, "paid": n, "done": n, "old": n}}."""
    completed = {(str(j.get("agent_id")), str(j.get("myhome_listing_id")).strip())
                 for j in jobs if str(j.get("status")) == "COMPLETED"}
    out = {"safe": [], "payment": [], "skipped": {"permanent": 0, "paid": 0, "done": 0, "old": 0}}
    for j in jobs:
        if str(j.get("status")) != "FAILED":
            continue
        if not _job_day_ok(j, days):
            out["skipped"]["old"] += 1
            continue
        stage = str(j.get("failure_stage") or "")
        err = str(j.get("error_message") or "")
        if stage == "permanent" or "LISTING_UNAVAILABLE" in err:
            out["skipped"]["permanent"] += 1
        elif stage == "paid":
            out["skipped"]["paid"] += 1
        elif (str(j.get("agent_id")), str(j.get("myhome_listing_id")).strip()) in completed:
            out["skipped"]["done"] += 1
        elif stage == "payment":
            out["payment"].append(j)
        else:
            out["safe"].append(j)
    return out


def register(app, *, authed, audit, rate_limited, sheets) -> None:

    def _admin():
        agent, admin, err = authed()
        if err:
            return None, None, err
        if not admin:
            return None, None, (jsonify(error="მხოლოდ ადმინისთვის"), 403)
        return agent, admin, None

    def _worker(ids: list[str]):
        done = failed = 0
        for jid in ids:
            try:
                if sheets.retry_myhome_job(jid):
                    done += 1
                else:
                    failed += 1
            except Exception:
                log.exception("job %s ხელახლა რიგში ვერ ჩაჯდა", jid)
                failed += 1
            with _lock:
                _state["done"], _state["failed"] = done, failed
        with _lock:
            _state["running"] = False
            _state["finished_at"] = crm_time.iso_utc_now()

    @app.post("/api/myhome-jobs/retry-failed")
    @rate_limited("myhome_account")
    def myhome_retry_failed():
        agent, admin, err = _admin()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        days = max(1, min(int(body.get("days") or 2), 7))
        include_payment = bool(body.get("include_payment"))
        plan = classify(sheets.get_myhome_jobs(), days)
        chosen = plan["safe"] + (plan["payment"] if include_payment else [])
        summary = {
            "safe": len(plan["safe"]), "payment": len(plan["payment"]), "skipped": plan["skipped"],
            "will_retry": min(len(chosen), MAX_JOBS), "capped": len(chosen) > MAX_JOBS,
        }
        if body.get("dry_run"):
            return jsonify(ok=True, dry_run=True, **summary)
        with _lock:
            if _state["running"]:
                return jsonify(error="ხელახლა გაშვება უკვე მიმდინარეობს", code="already_running"), 409
            ids = [str(j["job_id"]) for j in chosen][:MAX_JOBS]
            if not ids:
                return jsonify(ok=True, started=False, **summary)
            _state.update(running=True, total=len(ids), done=0, failed=0,
                          started_at=crm_time.iso_utc_now(), finished_at="")
        audit(agent, admin, "myhome_bulk_retry", "myhome_job", "", metadata={
            "count": len(ids), "include_payment": include_payment, "days": days})
        threading.Thread(target=_worker, args=(ids,), name="myhome-bulk-retry", daemon=True).start()
        return jsonify(ok=True, started=True, **summary)

    @app.get("/api/myhome-jobs/retry-failed/status")
    @rate_limited("myhome_account")
    def myhome_retry_failed_status():
        agent, admin, err = _admin()
        if err:
            return err
        with _lock:
            return jsonify(dict(_state))
