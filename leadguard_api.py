"""
SAIRO — Lead Protection Engine HTTP API (`/api/leadguard/...`). ახალი endpoint-ებია; არსებულს არაფერს ცვლის.

  * `GET /api/leadguard/report` — რისკების ანგარიში (წაკითხვა-მხოლოდ). სერვერზე დაცული ხილვადობა: აგენტი — მხოლოდ საკუთარი; თიმლიდერი — თავისი გუნდი;
    ადმინი — ყველა. პასუხში ტელეფონი არ არის.
  * `GET /api/leadguard/preview` — მენეჯერს/ადმინს უჩვენებს, **რას გააგზავნიდა** ძრავა ახლა (არაფერს აგზავნის, არაფერს წერს) — ჩართვამდე შესამოწმებლად.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify

import ai_service
import config
import lead_guard as lg

log = logging.getLogger("safehome-leadguard-api")


def register(app, *, authed, audit, rate_limited, chat_id) -> None:
    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                return fn(agent, admin, ai_service.viewer_of(agent, admin, uid=f"tg{chat_id()}"), *a, **kw)
            except Exception:  # noqa: BLE001
                log.exception("LeadGuard API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    def _engine():
        return {"enabled": bool(config.LEAD_GUARD_ENABLED), "remind_cooldown_h": config.LEAD_GUARD_REMIND_COOLDOWN_H, "max_reminders": config.LEAD_GUARD_MAX_REMINDERS,
                "escalate_after_h": config.LEAD_GUARD_ESCALATE_AFTER_H, "high_after_h": config.LEAD_GUARD_HIGH_AFTER_H, "silent_days": config.LEAD_GUARD_SILENT_DAYS,
                "quiet_hours": f"{config.LEAD_GUARD_QUIET_FROM:02d}:00–{config.LEAD_GUARD_QUIET_TO:02d}:00", "report_hour": config.LEAD_GUARD_REPORT_HOUR}

    @app.get("/api/leadguard/report")
    @rate_limited("leadguard_read")
    @_guard
    def leadguard_report(agent, admin, v):
        rep = lg.report(v)
        rep["engine"] = _engine()
        rep["kinds"] = lg.KINDS
        return jsonify(rep)

    @app.get("/api/leadguard/preview")
    @rate_limited("leadguard_read")
    @_guard
    def leadguard_preview(agent, admin, v):
        if not (admin or v.get("role") == "team_lead"):
            return jsonify(error="მხოლოდ მენეჯერს/ადმინს შეუძლია"), 403
        now = lg._now()
        data = lg.collect(now)
        if "agents" in data["errors"]:
            return jsonify(error="აგენტების წაკითხვა ვერ მოხერხდა"), 503
        risks, _g = lg.detect(now, data)
        by_key = lg.log_rows()
        acts = lg.plan(now, risks, by_key, data["agents"])
        inside = lg._scope(v, data["agents"])  # noqa: SLF001
        out = []
        for a in acts:
            if not any(inside(r) for r in a["risks"]):
                continue
            out.append({"type": a["type"], "agent_id": a["agent_id"], "count": len(a["keys"]), "text": a["text"]})
        return jsonify(planned=out, quiet_hours_now=lg.in_quiet_hours(now), engine=_engine(), note="ეს წინასწარი ნახვაა — არაფერი გაგზავნილა და არაფერი ჩაწერილა.")
