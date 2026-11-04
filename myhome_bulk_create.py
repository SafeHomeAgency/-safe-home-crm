"""
MyHome job-ების მასობრივი დამატება რიგში (მხოლოდ worker-ის API გასაღებით) — ერთი აგენტის სახელით ბევრი ID ერთად.
  * POST /internal/myhome-jobs/bulk-create?manager_label=<label>
    {"agent_id": "...", "dry_run": false,
     "jobs": [{"myhome_listing_id": "...", "final_price": "...", "cooperation_percent": "...", "owner_number": "...", "notes": ""}]}
Mini App-ის `/api/myhome-jobs`-ის იგივე წესები: ნომერი მინ. 9 ციფრი, ანგარიში აგენტის გუნდიდან, დუბლიკატი
`agent_id + ID + ბიზნეს-დღე` (sheets.create_myhome_job_once_per_day). ერთ მოთხოვნაში მაქს. MAX_JOBS (Sheets-ის კვოტა).
აგენტს თითო job-ზე შეტყობინება არ ეგზავნება — ერთი შეჯამება.
"""

from __future__ import annotations

import re

from flask import jsonify, request

MAX_JOBS = 25


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def register(app, *, authed_worker, rate_limited, sheets, send_message) -> None:
    @app.post("/internal/myhome-jobs/bulk-create")
    @rate_limited("worker")
    def myhome_jobs_bulk_create():
        err = authed_worker()
        if err:
            return err
        manager_label = str(request.args.get("manager_label") or "").strip()
        if not manager_label:
            return jsonify(error="manager_label საჭიროა"), 400
        body = request.get_json(silent=True) or {}
        jobs = body.get("jobs") or []
        if not isinstance(jobs, list) or not jobs:
            return jsonify(error="jobs ცარიელია"), 400
        if len(jobs) > MAX_JOBS:
            return jsonify(error=f"ერთ მოთხოვნაში მაქსიმუმ {MAX_JOBS} job"), 400

        agent_id = str(body.get("agent_id") or "").strip()
        agent = next((a for a in sheets.get_agents() if str(a.get("agent_id")) == agent_id), None)
        if not agent:
            return jsonify(error="აგენტი ვერ მოიძებნა"), 404
        if str(agent.get("active", "")).strip().lower() not in ("yes", "true", "1", ""):
            return jsonify(error="აგენტი აქტიური არ არის"), 409
        team = str(agent.get("team", "")).strip()
        account = sheets.get_myhome_account_for_team(team)
        label = str((account or {}).get("manager_label", "")).strip()
        if label != manager_label:
            return jsonify(error=f"აგენტის გუნდის ანგარიში არის „{label or '—'}“, არა „{manager_label}“", code="label_mismatch"), 409

        dry_run = bool(body.get("dry_run"))
        created, duplicates, invalid = [], [], []
        for j in jobs:
            j = j if isinstance(j, dict) else {}
            lid = str(j.get("myhome_listing_id") or "").strip()
            owner = str(j.get("owner_number") or "").strip()
            price = str(j.get("final_price") or "").strip()
            if not re.fullmatch(r"\d{7,9}", lid):
                invalid.append({"myhome_listing_id": lid, "error": "ID არასწორია"})
                continue
            if len(_digits(owner)) < 9:
                invalid.append({"myhome_listing_id": lid, "error": "ნომერი — მინ. 9 ციფრი"})
                continue
            if not re.fullmatch(r"\d+(\.\d+)?", price) or float(price) <= 0:
                invalid.append({"myhome_listing_id": lid, "error": "ფასი არასწორია"})
                continue
            if dry_run:
                created.append({"myhome_listing_id": lid, "job_id": None})
                continue
            job_id, existing = sheets.create_myhome_job_once_per_day(agent_id, {
                "team": team,
                "manager_label": label,
                "myhome_listing_id": lid,
                "cooperation_percent": str(j.get("cooperation_percent") or "").strip(),
                "final_price": price,
                "notes": str(j.get("notes") or "").strip(),
                "owner_number": owner,
                "listing_source": "myhome",
                "publish_target": "myhome",
            })
            if job_id is None:
                duplicates.append({"myhome_listing_id": lid, "job_id": (existing or {}).get("job_id")})
            else:
                created.append({"myhome_listing_id": lid, "job_id": job_id})

        if created and not dry_run:
            sheets.add_audit_event("", "worker", "myhome_job_bulk_create", "myhome_job", "", "",
                                   {"agent_id": agent_id, "manager_label": label, "count": len(created)})
            if agent.get("telegram_chat_id"):
                try:
                    send_message(int(agent["telegram_chat_id"]),
                                 f"🏠 რიგს დაემატა {len(created)} MyHome განცხადება (QUEUED) — შეგატყობინებთ დამუშავებისას.")
                except Exception:
                    pass
        resp = jsonify(ok=True, dry_run=dry_run, created=created, duplicates=duplicates, invalid=invalid)
        resp.headers["Cache-Control"] = "no-store"
        return resp
