"""
კადრების აყვანის HTTP API (`/api/recruit/...`) — ახალი endpoint-ებია, არსებულს არაფერს ცვლის.

უფლებები (სერვერზე):
  * ნახვა — ადმინი/დირექტორი, თიმლიდერი (მენეჯერი) და „პასუხისმგებელი“ (ადმინი ირჩევს აპიდან);
  * რედაქტირება/შეყვანა/იმპორტი — ადმინი + პასუხისმგებელი (პასუხისმგებელი რამდენიმეც შეიძლება: თუ ერთი ვერ ასწრებს, მეორე ანაცვლებს);
  * პარამეტრები (პასუხისმგებელი, შეხსენების საათი, შეტყობინების ტექსტები) — მხოლოდ ადმინი.
ყველა ცვლილება ისტორიაშია (RecruitLog): ვინ, როდის, რა შეცვალა.
"""

from __future__ import annotations

import csv
import functools
import io
import logging

from flask import Response, jsonify, request

import config
import recruit_model as m
import recruit_store as st

log = logging.getLogger("safehome-recruit-api")

DEFAULT_TEMPLATES = {
    "confirm": "გამარჯობა, {name}! გახსენებთ, რომ ხვალ ({date}) {time}-ზე გაქვთ გასაუბრება Safe Home Agency-ში. გთხოვთ დაადასტუროთ, მოდიხართ თუ არა 🙏",
    "reminder": "გამარჯობა, {name}! დღეს {time}-ზე გელოდებით გასაუბრებაზე Safe Home Agency-ში. გნახავთ! 🙂",
    "noshow": "გამარჯობა, {name}! დღეს გასაუბრებაზე ვერ გნახეთ. გსურთ ახალი დროის დანიშვნა?",
    "training": "გამარჯობა, {name}! ტრენინგი იწყება {date} {time}-ზე. გთხოვთ დაადასტუროთ დასწრება 🙏",
}
LABELS = {"confirm": "დადასტურების მოთხოვნა (გასაუბრებამდე ერთი დღით ადრე)", "reminder": "გასაუბრების დღის შეხსენება", "noshow": "გამოუცხადებლობის შემდეგ",
          "training": "ტრენინგის დადასტურება"}


def render_template(text: str, rec: dict, field: str = "interview_at") -> str:
    iv = m.parse_dt(rec.get(field))
    name = (str(rec.get("name") or "").split() or [""])[0]
    return (text.replace("{name}", name).replace("{date}", iv.strftime("%d.%m") if iv else "—")
            .replace("{time}", iv.strftime("%H:%M") if iv and iv.strftime("%H:%M") != "00:00" else "—"))


def register(app, *, authed, audit, rate_limited, get_agents) -> None:
    def _responsible() -> list[str]:
        return st.get_settings()["responsible_ids"]

    def _perm(agent, admin) -> dict:
        aid = str((agent or {}).get("agent_id") or "")
        resp = aid in _responsible()
        lead = str((agent or {}).get("role") or "").strip() == "team_lead"
        return {"view": bool(admin or lead or resp), "edit": bool(admin or resp), "admin": bool(admin), "responsible": resp, "agent_id": aid,
                "name": str((agent or {}).get("name") or ("დირექტორი" if admin else ""))}

    def _guard(need: str = "view"):
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*a, **kw):
                agent, admin, err = authed()
                if err:
                    return err
                p = _perm(agent, admin)
                if not p.get(need):
                    return jsonify(error="კადრების განყოფილებაზე წვდომა არ გაქვთ", code="recruit_forbidden"), 403
                try:
                    return fn(agent, admin, p, *a, **kw)
                except st.RecruitError as e:
                    return jsonify(error=str(e)), e.status
                except ValueError as e:
                    return jsonify(error=str(e)), 400
                except Exception:  # noqa: BLE001
                    log.exception("recruit API შეცდომა: %s", fn.__name__)
                    return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
            return wrapper
        return deco

    def _names(ids) -> list[dict]:
        ag = {str(a.get("agent_id")): a for a in get_agents()}
        return [{"agent_id": i, "name": str((ag.get(i) or {}).get("name") or i)} for i in ids]

    # ---- წვდომა (ტაბის ჩვენებისთვის): ამოწმებს ყველა როლს, ტაბი მხოლოდ უფლების მქონეს ჩანს
    @app.get("/api/recruit/access")
    @rate_limited("recruit_read")
    def recruit_access():
        agent, admin, err = authed()
        if err:
            return err
        p = _perm(agent, admin)
        out = {"can_view": p["view"], "can_edit": p["edit"], "can_admin": p["admin"], "responsible": p["responsible"], "enabled": bool(config.RECRUIT_ENABLED)}
        if p["view"]:
            s = st.get_settings()
            out["responsible_list"] = _names(s["responsible_ids"])
            out["setup_needed"] = not s["responsible_ids"]
        return jsonify(out)

    @app.get("/api/recruit/home")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_home(agent, admin, p):
        s = st.get_settings()
        agents = [{"agent_id": str(a.get("agent_id")), "name": str(a.get("name") or ""), "role": str(a.get("role") or "")} for a in get_agents()
                  if str(a.get("active", "yes")).strip().lower() not in ("no", "false", "0")] if p["admin"] else []
        return jsonify(perm={k: p[k] for k in ("view", "edit", "admin", "responsible")}, lists=st.lists(), stats=st.stats(days=30),
                       responsible=_names(s["responsible_ids"]), remind_hour=s["remind_hour"], stages=m.STAGES, call_status=m.CALL_STATUS,
                       options={"attended": m.ATTENDED, "train_ok": m.TRAIN_OK, "interaction": m.INTERACTION, "sessions": m.TRAIN_SESSIONS},
                       enabled=bool(config.RECRUIT_ENABLED), agents=agents)

    @app.get("/api/recruit/list")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_list(agent, admin, p):
        g = request.args.get
        try:
            page = int(g("page") or 1)
        except ValueError:
            page = 1
        stage = g("stage") or ""
        if stage and stage not in m.STAGES:
            return jsonify(error="ეტაპი არასწორია"), 400

        def pick(key, allowed):
            v = (g(key) or "").strip()
            return v if v in allowed else ""
        f = {
            "stage": stage, "q": (g("q") or "")[:60], "page": page, "responsible": (g("responsible") or "")[:40],
            "state": pick("state", ("active", "closed", "all")) or "active",
            "call": pick("call", ("todo", "confirmed", "declined", "no_contact", "repeat")),
            "iv": pick("iv", ("today", "tomorrow", "week", "past", "none", "date")), "iv_date": (g("iv_date") or "")[:10],
            "added": pick("added", ("today", "7", "30")), "exp": pick("exp", ("yes", "no")), "source": pick("source", ("form", "manual")),
            "flag": pick("flag", tuple(st.FLAG_LABELS)), "sort": pick("sort", ("new", "interview", "name", "activity")) or "new",
            "train": pick("train", ("coming", "rent", "sale", "both", "absent", "none")), "inter": pick("inter", ("none", "scheduled", "held", "passed", "failed", "changed")),
            "age_min": "".join(ch for ch in (g("age_min") or "") if ch.isdigit())[:2], "age_max": "".join(ch for ch in (g("age_max") or "") if ch.isdigit())[:2],
        }
        return jsonify(st.query(f))

    @app.get("/api/recruit/stats")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_stats(agent, admin, p):
        try:
            days = max(7, min(int(request.args.get("days") or 90), 365))
        except ValueError:
            days = 90
        return jsonify(st.stats(days=days))

    @app.get("/api/recruit/calendar")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_calendar(agent, admin, p):
        try:
            days = int(request.args.get("days") or 14)
        except ValueError:
            days = 14
        return jsonify(st.calendar(request.args.get("from") or "", days))

    @app.get("/api/recruit/day")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_day(agent, admin, p):
        return jsonify(st.day_view(request.args.get("date") or st.now_dt().strftime("%Y-%m-%d")))

    @app.get("/api/recruit/slots")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_slots(agent, admin, p):
        day = request.args.get("day") or st.now_dt().strftime("%Y-%m-%d")
        return jsonify(st.slots(day))

    @app.get("/api/recruit/<rid>")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_get(agent, admin, p, rid):
        r = st.get(rid, fresh=True)
        if not r:
            raise st.RecruitError("კანდიდატი ვერ მოიძებნა", 404)
        s = st.get_settings()
        pub = st.public(r)
        tpl = {k: render_template(s["templates"].get(k) or DEFAULT_TEMPLATES[k], r, "training_at" if k == "training" else "interview_at") for k in DEFAULT_TEMPLATES}
        return jsonify(item=pub, log=st.log_for(rid), templates=tpl, template_labels=LABELS, can_edit=p["edit"])

    @app.post("/api/recruit/<rid>")
    @rate_limited("recruit_write")
    @_guard("edit")
    def recruit_update(agent, admin, p, rid):
        body = request.get_json(silent=True) or {}
        changes = body.get("changes") if isinstance(body.get("changes"), dict) else {}
        by = {"name": p["name"], "agent_id": p["agent_id"]}
        r = st.update(rid, changes, by, comment=str(body.get("comment") or "").strip()[:500])
        audit(agent, admin, "recruit_update", "recruit", rid, metadata={"fields": sorted(changes)[:12]})
        return jsonify(item=st.public(r), log=st.log_for(rid))

    @app.post("/api/recruit")
    @rate_limited("recruit_write")
    @_guard("edit")
    def recruit_create(agent, admin, p):
        body = request.get_json(silent=True) or {}
        r = st.create(body.get("fields") if isinstance(body.get("fields"), dict) else {}, {"name": p["name"], "agent_id": p["agent_id"]})
        audit(agent, admin, "recruit_create", "recruit", r["recruit_id"])
        return jsonify(item=st.public(r)), 201

    @app.post("/api/recruit/import")
    @rate_limited("recruit_write")
    @_guard("edit")
    def recruit_import(agent, admin, p):
        try:
            res = st.sync()
        except RuntimeError as e:
            return jsonify(error=str(e), code="sheet_unreadable"), 503
        audit(agent, admin, "recruit_import", "recruit", "", metadata={k: res.get(k) for k in ("added", "skipped", "bootstrap")})
        return jsonify(res)

    @app.post("/api/recruit/settings")
    @rate_limited("recruit_write")
    @_guard("admin")
    def recruit_settings(agent, admin, p):
        body = request.get_json(silent=True) or {}
        if "responsible_ids" in body:
            ids = [str(x).strip() for x in (body.get("responsible_ids") or []) if str(x).strip()][:5]
            known = {str(a.get("agent_id")) for a in get_agents()}
            bad = [i for i in ids if i not in known]
            if bad:
                return jsonify(error="აგენტი ვერ მოიძებნა: " + ", ".join(bad)), 400
            st.set_setting("responsible_ids", ",".join(ids))
        if "remind_hour" in body:
            try:
                st.set_setting("remind_hour", str(min(20, max(8, int(body["remind_hour"])))))
            except (TypeError, ValueError):
                return jsonify(error="საათი არასწორია"), 400
        for k in DEFAULT_TEMPLATES:
            if "tpl_" + k in body:
                st.set_setting("tpl_" + k, str(body["tpl_" + k] or "").strip()[:500])
        audit(agent, admin, "recruit_settings", "recruit", "", metadata={"keys": sorted(body)[:10]})
        s = st.get_settings()
        return jsonify(ok=True, responsible=_names(s["responsible_ids"]), remind_hour=s["remind_hour"])

    @app.get("/api/recruit/templates")
    @rate_limited("recruit_read")
    @_guard("view")
    def recruit_templates(agent, admin, p):
        s = st.get_settings()
        return jsonify(templates={k: s["templates"].get(k) or v for k, v in DEFAULT_TEMPLATES.items()}, labels=LABELS)

    @app.get("/api/recruit/export.csv")
    @rate_limited("recruit_read")
    @_guard("admin")
    def recruit_export(agent, admin, p):
        buf = io.StringIO()
        w = csv.writer(buf)
        keys = [h for h in m.HEADERS if h not in ("src_key", "silent")]
        w.writerow(keys)
        for r in st.all_rows(fresh=True):
            w.writerow([str(r.get(k, "")) for k in keys])
        audit(agent, admin, "recruit_export", "recruit", "")
        return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=recruits.csv", "Cache-Control": "no-store"})
