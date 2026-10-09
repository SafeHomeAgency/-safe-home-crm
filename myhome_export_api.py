"""
MyHome job-ების ექსპორტი worker-ისთვის/ექსთენშენისთვის (მხოლოდ worker-ის API გასაღებით) — ბაზაში (Sheety) ვერჩაწერილი
განცხადებების აღსადგენად: agent_name, მესაკუთრის ნომერი, ფასი, საკომისიო, შენიშვნა და ა.შ. ინფორმაცია CRM-შია.
  * GET  /internal/myhome-jobs/export?since=&until=&status=COMPLETED|FAILED|ALL  — მხოლოდ კითხვა (ნაგულისხმევი COMPLETED)
  * POST /internal/myhome-jobs/<job_id>/recover {"listing_id": "..."} — გადახდილი, მაგრამ ჩავარდნილად დარჩენილი job
    (FAILED + failure_stage paid/payment, განცხადება უკვე გამოქვეყნებულია) -> COMPLETED. სხვა job-ზე არაფერს აკეთებს.
"""

from __future__ import annotations

import re

from flask import jsonify, request

import crm_time

FIELDS = ("job_id", "myhome_listing_id", "team", "manager_label", "agent_id", "agent_name", "owner_number",
          "final_price", "cooperation_percent", "notes", "status", "created_at", "started_at", "completed_at",
          "address", "district", "city", "deal_type", "failure_stage", "error_message")
MAX_ROWS = 600


def register(app, *, authed_worker, rate_limited, sheets) -> None:
    @app.get("/internal/myhome-jobs/export")
    @rate_limited("worker")
    def myhome_jobs_export():
        err = authed_worker()
        if err:
            return err
        since = crm_time.parse_server_dt(request.args.get("since"))
        until = crm_time.parse_server_dt(request.args.get("until"))
        if not since:
            return jsonify(error="since საჭიროა: YYYY-MM-DD HH:MM (სერვერის UTC დრო)"), 400
        status = str(request.args.get("status") or "COMPLETED").strip().upper()
        if status not in ("COMPLETED", "FAILED", "ALL"):
            return jsonify(error="status: COMPLETED | FAILED | ALL"), 400
        out = []
        for j in sheets.get_myhome_jobs(status=None if status == "ALL" else status):
            done = crm_time.parse_server_dt(j.get("completed_at"))
            if not done or done < since or (until and done > until):
                continue
            out.append({k: j.get(k, "") for k in FIELDS})
        out.sort(key=lambda r: r.get("completed_at", ""))
        resp = jsonify(rows=out[:MAX_ROWS], total=len(out))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/internal/myhome-jobs/<job_id>/recover")
    @rate_limited("worker")
    def myhome_job_recover(job_id):
        err = authed_worker()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        listing_id = str(body.get("listing_id") or "").strip()
        if not re.fullmatch(r"\d{7,9}", listing_id):
            return jsonify(error="listing_id საჭიროა (გამოქვეყნებული განცხადების ID, 7-9 ციფრი)"), 400
        res = sheets.recover_paid_myhome_job(job_id, listing_id)
        if not res.get("ok"):
            code = 404 if res.get("code") == "not_found" else 409
            return jsonify(ok=False, code=res.get("code")), code
        resp = jsonify(ok=True, code=res.get("code"))
        resp.headers["Cache-Control"] = "no-store"
        return resp
