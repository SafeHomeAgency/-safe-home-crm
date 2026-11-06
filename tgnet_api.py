"""
TGNET HTTP API (`/api/tgnet/...`) — ახალი endpoint-ებია, არსებულს არაფერს ცვლის. **მხოლოდ დირექტორი/ადმინი** (config.ADMIN_CHAT_IDS); თიმლიდერი/აგენტი — 403.
ეტაპი 2B: არხების სია, chat_id-ის მიბმა, ჯანმრთელობის შემოწმება (Telegram-ში მხოლოდ წაკითხვა). არაფერი ქვეყნდება.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify, request

import config
import tgnet_client as cl
import tgnet_model as m
import tgnet_store as st

log = logging.getLogger("safehome-tgnet-api")


def register(app, *, authed, audit, rate_limited, client_factory=None) -> None:
    factory = client_factory or (lambda: cl.Client())

    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            if not admin:
                return jsonify(error="Telegram ქსელის განყოფილება მხოლოდ დირექტორისთვისაა", code="tgnet_forbidden"), 403
            try:
                return fn(agent, admin, *a, **kw)
            except st.TgnetError as e:
                return jsonify(error=str(e), code=getattr(e, "code", "")), e.status
            except Exception:  # noqa: BLE001
                log.exception("tgnet API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    @app.get("/api/tgnet/access")
    @rate_limited("tgnet_read")
    def tgnet_access():
        agent, admin, err = authed()
        if err:
            return err
        return jsonify(can_view=bool(admin), configured=bool(config.TGNET_BOT_TOKEN and ":" in config.TGNET_BOT_TOKEN))

    @app.get("/api/tgnet/share-config")
    @rate_limited("tgnet_read")
    def tgnet_share_config():
        """ყველა ავტორიზებულისთვის (აგენტის ფორმა): ჩანს თუ არა „Telegram-ზეც გამოქვეყნება“ თიქი. გამორთულია, სანამ TGNET_QUEUE_ENABLED=0."""
        agent, admin, err = authed()
        if err:
            return err
        return jsonify(share_option=bool(config.TGNET_QUEUE_ENABLED), marker=m.OPT_IN_LINE)

    @app.get("/api/tgnet/queue")
    @rate_limited("tgnet_read")
    @_guard
    def tgnet_queue(agent, admin):
        groups = st.queue_groups()
        counts = {}
        for g in groups:
            counts[g["status"]] = counts.get(g["status"], 0) + 1
        return jsonify(groups=groups, counts=counts, queue_enabled=bool(config.TGNET_QUEUE_ENABLED), auto_approve=bool(config.TGNET_AUTO_APPROVE), posting_available=False)

    @app.post("/api/tgnet/queue/<listing_key>")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_queue_decide(agent, admin, listing_key):
        body = request.get_json(silent=True) or {}
        n = st.decide_listing(listing_key, str(body.get("action") or ""), by=str((agent or {}).get("name") or "დირექტორი"))
        audit(agent, admin, "tgnet_queue_" + str(body.get("action")), "tgnet_listing", listing_key, metadata={"posts": n})
        return jsonify(ok=True, changed=n, groups=st.queue_groups())

    @app.get("/api/tgnet/channels")
    @rate_limited("tgnet_read")
    @_guard
    def tgnet_channels(agent, admin):
        if not st.list_channels():
            st.seed_channels()                                   # პირველი გახსნისას 18 არხის რეესტრი თავად ივსება (ხელით შეყვანილს არასდროს ეხება)
        ch = st.list_channels(fresh=True)
        return jsonify(channels=ch, settings=st.get_settings(), configured=bool(config.TGNET_BOT_TOKEN and ":" in config.TGNET_BOT_TOKEN),
                       summary={"total": len(ch), "linked": sum(1 for c in ch if c["chat_id"]), "live": sum(1 for c in ch if c["status"] == "live"),
                                "attention": sum(1 for c in ch if c["status"] == "attention")}, posting_available=False)

    @app.post("/api/tgnet/channels/<key>")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_update(agent, admin, key):
        body = request.get_json(silent=True) or {}
        allowed = {k: body[k] for k in ("chat_id", "enabled", "note", "status") if k in body}
        ch = st.update_channel(key, allowed, by=str((agent or {}).get("name") or "დირექტორი"))
        audit(agent, admin, "tgnet_channel_edit", "tgnet_channel", key, metadata={"fields": sorted(allowed)})
        return jsonify(channel=ch)

    @app.post("/api/tgnet/check")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_check(agent, admin):
        """ჯანმრთელობის შემოწმება: მხოლოდ წაკითხვა (getMe/getChat/getChatMember/getChatMemberCount). body: {key} ერთი არხისთვის, ან ცარიელი — ყველა მიბმული."""
        c = factory()
        if not c.configured:
            return jsonify(error="ბოტის ტოკენი არ არის დაყენებული (Railway: TGNET_BOT_TOKEN)", code="no_token"), 400
        body = request.get_json(silent=True) or {}
        key = str(body.get("key") or "").strip()
        targets = [x for x in st.list_channels(fresh=True) if x["chat_id"] and (not key or x["channel_key"] == key)]
        if not targets:
            return jsonify(error="შესამოწმებელი არხი არ არის: ჯერ chat_id მიაბით", code="nothing_to_check"), 400
        results = {t["channel_key"]: cl.check_channel(c, t["chat_id"], t["username"], t["title"]) for t in targets[:25]}
        st.record_checks(results)
        audit(agent, admin, "tgnet_check", "tgnet_channel", key or "all", metadata={"count": len(results)})
        return jsonify(results=results, channels=st.list_channels(fresh=True))

    @app.post("/api/tgnet/settings")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_settings(agent, admin):
        body = request.get_json(silent=True) or {}
        if "master" in body:
            st.set_setting("master", "1" if body["master"] else "0")
            st.log_event("", "master", "ჩართულია" if body["master"] else "გამორთულია")
            audit(agent, admin, "tgnet_master", "tgnet", "master", metadata={"on": bool(body["master"])})
        return jsonify(settings=st.get_settings(), posting_available=False)
