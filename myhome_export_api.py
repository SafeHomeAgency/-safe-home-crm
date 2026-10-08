"""
დასრულებული MyHome job-ების ექსპორტი worker-ისთვის (მხოლოდ worker-ის API გასაღებით) — ბაზაში (Sheety) ვერჩაწერილი
განცხადებების აღსადგენად: agent_name, მესაკუთრის ნომერი, ფასი, საკომისიო, შენიშვნა და ა.შ. ინფორმაცია CRM-შია,
worker-ს ლოკალურად კი არ აქვს. მხოლოდ კითხვაა — არაფერს ცვლის.
"""

from __future__ import annotations

from flask import jsonify, request

import crm_time

FIELDS = ("job_id", "myhome_listing_id", "team", "manager_label", "agent_id", "agent_name", "owner_number",
          "final_price", "cooperation_percent", "notes", "status", "created_at", "started_at", "completed_at",
          "address", "district", "city", "deal_type")
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
        out = []
        for j in sheets.get_myhome_jobs(status="COMPLETED"):
            done = crm_time.parse_server_dt(j.get("completed_at"))
            if not done or done < since or (until and done > until):
                continue
            out.append({k: j.get(k, "") for k in FIELDS})
        out.sort(key=lambda r: r.get("completed_at", ""))
        resp = jsonify(rows=out[:MAX_ROWS], total=len(out))
        resp.headers["Cache-Control"] = "no-store"
        return resp
