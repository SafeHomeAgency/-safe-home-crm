"""
Safe Home AI — HTTP API (`/api/ai/...`). მხოლოდ ახალი endpoint-ებია; არსებულს არაფერს ცვლის (`/api/questions*` — უცვლელი).

ავტორიზაცია — იგივე, რაც მთელ Mini App-ში (Telegram initData HMAC, `webserver._authed_agent`); უფლებები სერვერზე:
  * აგენტი: ჩატი, საკუთარი საუბრები/უკუკავშირი/ესკალაცია;
  * თიმლიდერი: + ცოდნის ბაზა (დრაფტი, არაშეზღუდული კატეგორიის გამოქვეყნება), განსახილველი რიგი და დაშბორდი საკუთარი გუნდისთვის;
  * ადმინი: ყველაფერი, შეზღუდული კატეგორიების (საკომისიო/იურიდიული/ფინანსური) გამოქვეყნება, ხარჯი, ძველი ტექსტის იმპორტი.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify, request

import ai_actions
import ai_insights as insights
import config
import ai_model as m
import ai_service as svc
import ai_store as store
from ai_model import AiError

log = logging.getLogger("safehome-ai-api")


def register(app, *, authed, audit, rate_limited, get_agents, get_questions, create_question, chat_id, send_message=None) -> None:
    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                store.ensure_tabs()
                ai_actions.ensure_tabs()
                v = svc.viewer_of(agent, admin, uid=f"tg{chat_id()}")
                return fn(agent, admin, v, *a, **kw)
            except AiError as e:
                return jsonify(error=str(e), code=e.code, **e.extra), e.status
            except Exception:  # noqa: BLE001
                log.exception("AI API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    def _body() -> dict:
        return request.get_json(silent=True) or {}

    # ------------------------------------------------------------ ჩატი
    @app.get("/api/ai/status")
    @rate_limited("ai_read")
    @_guard
    def ai_status(agent, admin, v):
        return jsonify(svc.status(v))

    @app.post("/api/ai/ask")
    @rate_limited("ai_ask")
    @_guard
    def ai_ask(agent, admin, v):
        b = _body()
        res = svc.ask(v, b.get("text"), b.get("conv_id") or "")
        audit(agent, admin, "ai_ask", "ai_msg", res["msg_id"], metadata={"type": res["answer_type"], "outcome": res["outcome"]})
        return jsonify(res)

    @app.get("/api/ai/conversations")
    @rate_limited("ai_read")
    @_guard
    def ai_convs(agent, admin, v):
        return jsonify(items=store.my_conversations(v["uid"]))

    @app.get("/api/ai/conversations/<conv_id>")
    @rate_limited("ai_read")
    @_guard
    def ai_conv(agent, admin, v, conv_id):
        by_id = {m.s(e.get("kb_id")): e for e in store.kb_all()}
        rows = []
        for r in store.conv_messages(conv_id, v["uid"]):
            src = [x for x in m.s(r.get("sources")).split("|") if x]
            rows.append({"msg_id": r.get("msg_id"), "role": r.get("role"), "text": r.get("text"), "answer_type": r.get("answer_type"),
                         "label": m.ANSWER_TYPES.get(m.s(r.get("answer_type")), ""), "confidence": r.get("confidence"),
                         "needs_manager": m.s(r.get("needs_manager")) in ("yes", "escalated"), "escalated": m.s(r.get("needs_manager")) == "escalated",
                         "outcome": r.get("outcome"), "created_at": r.get("created_at"),
                         "sources": [{"kb_id": s, "title": (by_id.get(s) or {}).get("title", s), "version": (by_id.get(s) or {}).get("version", "")} for s in src]})
        return jsonify(conv_id=conv_id, messages=rows)

    @app.post("/api/ai/feedback")
    @rate_limited("ai_write")
    @_guard
    def ai_feedback(agent, admin, v):
        b = _body()
        res = svc.give_feedback(v, agent, m.s(b.get("msg_id"), 60), m.s(b.get("rating"), 10), m.s(b.get("reason"), 20), m.s(b.get("comment"), 500))
        audit(agent, admin, "ai_feedback", "ai_msg", m.s(b.get("msg_id"), 60), metadata={"rating": b.get("rating")})
        return jsonify(res)

    @app.post("/api/ai/escalate")
    @rate_limited("ai_write")
    @_guard
    def ai_escalate(agent, admin, v):
        b = _body()
        res = svc.escalate(v, agent, m.s(b.get("msg_id"), 60), b.get("text") or "", create_question)
        audit(agent, admin, "ai_escalate", "question", str(res["question_id"]))
        return jsonify(res)

    # ------------------------------------------------------------ მოქმედებები ადამიანის დადასტურებით (SAIRO ამზადებს, მომხმარებელი ადასტურებს)
    def _deps():
        if send_message is None:
            raise AiError("შეტყობინების არხი მორგებული არ არის", 503, "no_sender")
        return {"send": send_message}

    @app.get("/api/ai/actions")
    @rate_limited("ai_read")
    @_guard
    def actions_list(agent, admin, v):
        return jsonify(items=ai_actions.list_mine(v, get_agents()))

    @app.post("/api/ai/actions/<action_id>/confirm")
    @rate_limited("ai_write")
    @_guard
    def actions_confirm(agent, admin, v, action_id):
        res = ai_actions.confirm(v, action_id, m.s(_body().get("hash"), 40), get_agents(), _deps())
        audit(agent, admin, "ai_action_confirm", "ai_action", action_id, metadata={"via": "ai", "status": res.get("status"), "already": bool(res.get("already"))})
        return jsonify(res)

    @app.post("/api/ai/actions/<action_id>/cancel")
    @rate_limited("ai_write")
    @_guard
    def actions_cancel(agent, admin, v, action_id):
        res = ai_actions.cancel(v, action_id)
        audit(agent, admin, "ai_action_cancel", "ai_action", action_id, metadata={"via": "ai"})
        return jsonify(res)

    @app.post("/api/ai/actions/<action_id>/revise")
    @rate_limited("ai_write")
    @_guard
    def actions_revise(agent, admin, v, action_id):
        new = ai_actions.revise(v, action_id, _body(), get_agents())
        audit(agent, admin, "ai_action_revise", "ai_action", action_id, metadata={"via": "ai", "new_action": new["action_id"]})
        return jsonify(ok=True, action=new)

    # ------------------------------------------------------------ ცოდნის ბაზა (მენეჯერები)
    def _need_manager(v):
        if not store.can_manage(v):
            raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)

    @app.get("/api/ai/kb")
    @rate_limited("ai_read")
    @_guard
    def kb_list(agent, admin, v):
        rows = store.kb_list(v, status=m.s(request.args.get("status"), 12))
        return jsonify(items=rows[:400], total=len(rows), categories=m.KB_CATEGORIES, restricted=sorted(config.AI_KB_RESTRICTED_CATEGORIES))

    @app.get("/api/ai/kb/<kb_id>")
    @rate_limited("ai_read")
    @_guard
    def kb_detail(agent, admin, v, kb_id):
        _need_manager(v)
        head = store.kb_get(kb_id, fresh=True)
        if not head or not store._sees_scope(v, head.get("scope_team")):
            raise AiError("ჩანაწერი ვერ მოიძებნა", 404)
        return jsonify(entry=dict(head, can_publish=store.can_publish(v, head.get("category"), head.get("scope_team"))), versions=store.versions_of(kb_id, fresh=True))

    @app.post("/api/ai/kb")
    @rate_limited("ai_write")
    @_guard
    def kb_create(agent, admin, v):
        row = store.kb_create(v, _body(), reason=m.s(_body().get("reason"), 300))
        audit(agent, admin, "ai_kb_create", "ai_kb", row["kb_id"], metadata={"category": row["category"]})
        return jsonify(ok=True, entry=row), 201

    @app.post("/api/ai/kb/import-legacy")
    @rate_limited("ai_write")
    @_guard
    def kb_import(agent, admin, v):
        import ai_seed
        res = store.import_seed(v, ai_seed.LEGACY_REGULATIONS)
        audit(agent, admin, "ai_kb_import_legacy", "ai_kb", "", metadata=res)
        return jsonify(ok=True, **res)

    @app.post("/api/ai/kb/<kb_id>")
    @rate_limited("ai_write")
    @_guard
    def kb_edit(agent, admin, v, kb_id):
        b = _body()
        row = store.kb_edit(v, kb_id, b, reason=m.s(b.get("reason"), 300))
        audit(agent, admin, "ai_kb_edit", "ai_kb", kb_id)
        return jsonify(ok=True, entry=row)

    @app.post("/api/ai/kb/<kb_id>/publish")
    @rate_limited("ai_write")
    @_guard
    def kb_publish(agent, admin, v, kb_id):
        b = _body()
        row = store.kb_publish(v, kb_id, confirm_similar=bool(b.get("confirm_similar")), note=m.s(b.get("note"), 300))
        audit(agent, admin, "ai_kb_publish", "ai_kb", kb_id, metadata={"version": row.get("version"), "category": row.get("category"), "similar_confirmed": row.get("similar_confirmed")})
        return jsonify(ok=True, entry=row)

    @app.post("/api/ai/kb/<kb_id>/reject")
    @rate_limited("ai_write")
    @_guard
    def kb_reject(agent, admin, v, kb_id):
        row = store.kb_reject(v, kb_id, reason=m.s(_body().get("reason"), 300))
        audit(agent, admin, "ai_kb_reject", "ai_kb", kb_id)
        return jsonify(ok=True, entry=row)

    @app.post("/api/ai/kb/<kb_id>/retire")
    @rate_limited("ai_write")
    @_guard
    def kb_retire(agent, admin, v, kb_id):
        row = store.kb_retire(v, kb_id, reason=m.s(_body().get("reason"), 300))
        audit(agent, admin, "ai_kb_retire", "ai_kb", kb_id)
        return jsonify(ok=True, entry=row)

    # ------------------------------------------------------------ განსახილველი რიგი / დაშბორდი
    @app.get("/api/ai/review")
    @rate_limited("ai_read")
    @_guard
    def review_list(agent, admin, v):
        _need_manager(v)
        try:
            store.sync_candidates(get_questions())
        except Exception:  # noqa: BLE001 — კანდიდატების სინქრონიზაცია სიას არ ანგრევს
            log.exception("AI: კანდიდატების სინქრონიზაცია ვერ მოხერხდა")
        rows = store.review_visible(v, status=m.s(request.args.get("status") or m.RV_OPEN, 12), type_=m.s(request.args.get("type"), 12))
        counts = {t: sum(1 for r in rows if m.s(r.get("type")) == t) for t in m.REVIEW_TYPES}
        return jsonify(items=rows[:150], total=len(rows), counts=counts)

    @app.post("/api/ai/review/<item_id>/draft")
    @rate_limited("ai_write")
    @_guard
    def review_draft(agent, admin, v, item_id):
        _need_manager(v)
        kb, item = store.review_to_draft(v, item_id, _body())
        audit(agent, admin, "ai_review_to_draft", "ai_review", item_id, metadata={"kb_id": kb["kb_id"]})
        return jsonify(ok=True, entry=kb, item=item), 201

    @app.post("/api/ai/review/<item_id>/dismiss")
    @rate_limited("ai_write")
    @_guard
    def review_dismiss(agent, admin, v, item_id):
        item = store.review_dismiss(v, item_id, note=m.s(_body().get("note"), 300))
        audit(agent, admin, "ai_review_dismiss", "ai_review", item_id)
        return jsonify(ok=True, item=item)

    @app.get("/api/ai/dashboard")
    @rate_limited("ai_read")
    @_guard
    def dashboard(agent, admin, v):
        _need_manager(v)
        svc.maybe_purge()
        names = {}
        if v.get("admin"):
            try:
                names = {str(a.get("agent_id")): a.get("name") for a in get_agents()}
            except Exception:  # noqa: BLE001
                names = {}
        try:
            days = int(request.args.get("days", 30))
        except ValueError:
            days = 30
        return jsonify(insights.dashboard(v, days=days, names=names))
