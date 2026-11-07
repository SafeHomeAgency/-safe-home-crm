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


def register(app, *, authed, audit, rate_limited, client_factory=None, notify=None, get_agents=None, sync_webhook=False, crm2=None) -> None:
    import threading

    import tgnet_leads as leads
    import tgnet_publisher as pub
    factory = client_factory or (lambda: cl.Client())
    agents_fn = get_agents or (lambda: [])
    holder: dict = {}

    def _managers(lst) -> list:
        """ადმინები + თიმლიდერები (ბინის გუნდის), რომლებსაც Telegram ID აქვთ."""
        ids = set(config.ADMIN_CHAT_IDS)
        team = str((lst or {}).get("team") or "")
        for a in agents_fn():
            if str(a.get("role") or "").strip() == "team_lead" and a.get("telegram_chat_id") and (not team or str(a.get("team") or "") == team):
                try:
                    ids.add(int(a["telegram_chat_id"]))
                except (TypeError, ValueError):
                    pass
        return sorted(ids)

    def _flow():
        c = factory()
        f = holder.get("flow")
        if f is None or f.c._token != c._token:
            f = holder["flow"] = leads.Flow(c, get_listing=pub.get_listing, notify=notify, managers_for=_managers, agents=agents_fn, crm2=crm2)
        return f

    def _is_lead_mgr(agent, admin) -> bool:
        return bool(admin) or str((agent or {}).get("role") or "").strip() == "team_lead"

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
        return jsonify(can_view=bool(admin), can_leads=_is_lead_mgr(agent, admin), configured=bool(config.TGNET_BOT_TOKEN and ":" in config.TGNET_BOT_TOKEN))

    # ---- საჯარო ბოტის webhook (Telegram-იდან; ავტორიზაცია: secret_token ჰედერი)
    @app.post("/api/tgnet/webhook")
    @rate_limited("tgnet_webhook")
    def tgnet_webhook():
        if not leads.secret_ok(request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")):
            return jsonify(ok=False, error="unauthorized"), 401
        upd = request.get_json(silent=True) or {}
        if sync_webhook:
            return jsonify(ok=True, result=_flow().handle(upd))
        threading.Thread(target=lambda: _flow().handle(upd), daemon=True).start()      # Telegram-ს მაშინვე ვპასუხობთ (Sheets-ის ჩაწერა ნელია); update_id დუბლს იცავს
        return jsonify(ok=True)

    @app.post("/api/tgnet/webhook/set")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_webhook_set(agent, admin):
        c = factory()
        if not c.configured:
            return jsonify(error="ბოტის ტოკენი არ არის დაყენებული (Railway: TGNET_BOT_TOKEN)", code="no_token"), 400
        if not config.WEBAPP_URL:
            return jsonify(error="WEBAPP_URL არ არის დაყენებული", code="no_url"), 400
        url = config.WEBAPP_URL.rstrip("/") + "/api/tgnet/webhook"
        try:
            c.call("setWebhook", url=url, secret_token=leads.webhook_secret(), allowed_updates=["message", "callback_query"], drop_pending_updates="false")
        except cl.TgError as e:
            return jsonify(error=str(e), code="set_failed"), 400
        audit(agent, admin, "tgnet_webhook_set", "tgnet", "webhook", metadata={"url": url})
        return jsonify(ok=True, url=url)

    @app.get("/api/tgnet/webhook/info")
    @rate_limited("tgnet_read")
    @_guard
    def tgnet_webhook_info(agent, admin):
        c = factory()
        if not c.configured:
            return jsonify(error="ბოტის ტოკენი არ არის დაყენებული", code="no_token"), 400
        try:
            i = c.call("getWebhookInfo")
        except cl.TgError as e:
            return jsonify(error=str(e)), 400
        return jsonify(url=i.get("url", ""), pending=i.get("pending_update_count", 0), last_error=i.get("last_error_message", ""), expected=config.WEBAPP_URL.rstrip("/") + "/api/tgnet/webhook")

    # ---- ბრენდირებული ფოტო (ხელმოწერილი ბმულებით) და კლიენტის Mini App
    @app.get("/img/b")
    @rate_limited("tgnet_webhook")
    def tgnet_img_route():
        import tgnet_img
        from flask import Response
        data, code = tgnet_img.serve(request.args.get("u", ""), request.args.get("s", ""))
        if data is None:
            return Response(status=code)
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/tg/app")
    @rate_limited("tgnet_read")
    def tgnet_app_page():
        import tgnet_app
        from flask import Response
        return Response(tgnet_app.PAGE, mimetype="text/html", headers={"Cache-Control": "no-store"})

    def _app_user():
        import tgnet_app
        return tgnet_app.validate_init_data(request.headers.get("X-Tg-Init", ""), config.TGNET_BOT_TOKEN)

    def _split(payload: str):
        import re as _re
        mm = _re.match(r"^([A-Za-z0-9][A-Za-z0-9-]{0,40}?)(?:_(ka|en|ru))?$", payload or "")
        return (mm.group(1), mm.group(2) or "ka") if mm else ("", "ka")

    @app.get("/api/tgnet/app/listing")
    @rate_limited("tgnet_webhook")
    def tgnet_app_listing():
        import tgnet_brand
        import tgnet_content as ct
        import tgnet_img
        user = _app_user()
        if not user:
            return jsonify(error="ავტორიზაცია ვერ დადასტურდა — გახსენით Telegram-იდან"), 401
        lid, lang = _split(request.args.get("l", ""))
        lst = pub.get_listing(lid) if lid else None
        if not lst or str(lst.get("active") or "yes").lower() == "no" or str(lst.get("archived") or "") == "yes":
            return jsonify(error={"ka": "ეს განცხადება აღარ არის აქტუალური.", "en": "This listing is no longer available.", "ru": "Это объявление уже неактуально."}[lang]), 404
        st.add_lead_event("view", lid, user.get("id"), "")
        lines = ct.render(lst, lang, cta=False)["text"].split("\n")
        import re as _re
        plain = [_re.sub(r"<[^>]+>", "", x) for x in lines]
        photos = [tgnet_img.proxy_url(u) if tgnet_brand.available() else u for u in ct.photos_of(lst)]
        return jsonify(title=plain[0].replace("🏠", "").strip(), price=(plain[1].replace("💰", "").strip() if len(plain) > 1 and plain[1].startswith("💰") else ""),
                       facts=[x for x in plain[1:] if x.startswith(("📐", "🚪"))], photos=photos)

    @app.post("/api/tgnet/app/lead")
    @rate_limited("tgnet_webhook")
    def tgnet_app_lead():
        user = _app_user()
        if not user:
            return jsonify(error="ავტორიზაცია ვერ დადასტურდა"), 401
        body = request.get_json(silent=True) or {}
        lid, lang = _split(str(body.get("l") or ""))
        phone = str(body.get("phone") or "")
        if not lid or len("".join(ch for ch in phone if ch.isdigit())) < 9 or not pub.get_listing(lid):
            return jsonify(error="მონაცემი არასწორია"), 400
        res = _flow().lead_from_app(user, lid, phone, str(body.get("lang") or lang))
        return (jsonify(ok=True), 200) if res == "lead" else (jsonify(error="ვერ მოხერხდა"), 400)

    # ---- ლიდები: მენეჯერი (ადმინი/თიმლიდერი)
    def _lead_guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            if not _is_lead_mgr(agent, admin):
                return jsonify(error="ლიდები მხოლოდ მენეჯერისთვისაა", code="tgnet_forbidden"), 403
            try:
                return fn(agent, admin, *a, **kw)
            except st.TgnetError as e:
                return jsonify(error=str(e), code=getattr(e, "code", "")), e.status
            except Exception:  # noqa: BLE001
                log.exception("tgnet leads API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    @app.get("/api/tgnet/leads")
    @rate_limited("tgnet_read")
    @_lead_guard
    def tgnet_leads(agent, admin):
        team = "" if admin else str((agent or {}).get("team") or "")
        return jsonify(**leads.leads_view(pub.get_listing, agents_fn, viewer_team=team, admin=bool(admin)))

    @app.post("/api/tgnet/leads/<lead_id>/assign")
    @rate_limited("tgnet_write")
    @_lead_guard
    def tgnet_lead_assign(agent, admin, lead_id):
        body = request.get_json(silent=True) or {}
        res = _flow().assign(lead_id, str(body.get("agent_id") or ""), by=str((agent or {}).get("name") or "დირექტორი"))
        audit(agent, admin, "tgnet_lead_assign", "tgnet_lead", lead_id, metadata={"agent_id": res["agent_id"]})
        return jsonify(ok=True, **res)

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
        return jsonify(groups=groups, counts=counts, queue_enabled=bool(config.TGNET_QUEUE_ENABLED), auto_approve=bool(config.TGNET_AUTO_APPROVE), posting_available=bool(config.TGNET_PUBLISH_ENABLED))

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
                                "attention": sum(1 for c in ch if c["status"] == "attention")}, posting_available=bool(config.TGNET_PUBLISH_ENABLED))

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

    @app.get("/api/tgnet/preview/<listing_key>")
    @rate_limited("tgnet_read")
    @_guard
    def tgnet_preview(agent, admin, listing_key):
        import tgnet_publisher as pub
        lst = pub.get_listing(listing_key)
        if not lst:
            return jsonify(error="განცხადება კატალოგში ვერ მოიძებნა", code="not_found"), 404
        return jsonify(**pub.preview(lst))

    @app.post("/api/tgnet/test-post")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_test_post(agent, admin):
        """ტესტ-შეტყობინება არხში (თავისით წაიშლება). მხოლოდ დირექტორი, მხოლოდ „მზადაა“ არხზე."""
        import tgnet_publisher as pub
        body = request.get_json(silent=True) or {}
        ch = st.get_channel(str(body.get("key") or ""), fresh=True)
        if not ch:
            return jsonify(error="არხი ვერ მოიძებნა", code="not_found"), 404
        c = factory()
        if not c.configured:
            return jsonify(error="ბოტის ტოკენი არ არის დაყენებული (Railway: TGNET_BOT_TOKEN)", code="no_token"), 400
        try:
            res = pub.send_test(ch, c)
        except cl.TgError as e:
            return jsonify(error=str(e), code="send_failed"), 400
        audit(agent, admin, "tgnet_test_post", "tgnet_channel", ch["channel_key"], metadata={"message_id": res["message_id"]})
        st.log_event(ch["channel_key"], "test_post", f"message {res['message_id']}")
        return jsonify(ok=True, **res)

    @app.post("/api/tgnet/settings")
    @rate_limited("tgnet_write")
    @_guard
    def tgnet_settings(agent, admin):
        body = request.get_json(silent=True) or {}
        if "master" in body:
            st.set_setting("master", "1" if body["master"] else "0")
            st.log_event("", "master", "ჩართულია" if body["master"] else "გამორთულია")
            audit(agent, admin, "tgnet_master", "tgnet", "master", metadata={"on": bool(body["master"])})
        return jsonify(settings=st.get_settings(), posting_available=bool(config.TGNET_PUBLISH_ENABLED))
