"""
Safe Home AI — მენეჯმენტის დაშბორდი: ხშირი კითხვები, უპასუხო/არასაიმედო პასუხები, უკუკავშირი, დოკუმენტაციის ხარვეზი/კონფლიქტი, FAQ-ის შეთავაზება,
გამოყენება/ხარჯი (**მხოლოდ ადმინს**), ხარისხი/სიჩქარე.

კონფიდენციალურობა: კითხვების ტექსტი უკვე ტელეფონებამოღებულია; დაშბორდზე **აგენტის სახელი/ID არ ჩანს** (მენეჯერები კითხვას მაინც ხედავენ არსებულ „კითხვა მენეჯერს“
ნაკადში, თუ აგენტმა თავად გადაუგზავნა). ხარჯი აგენტების მიხედვით — მხოლოდ ადმინს, ტექნიკური ID-ით/სახელით.
"""

from __future__ import annotations

import datetime

import ai_knowledge as kn
import ai_model as m
import ai_store as store
import config


def _pct(vals: list[float], p: float) -> int:
    if not vals:
        return 0
    v = sorted(vals)
    return int(v[min(len(v) - 1, int(round(p * (len(v) - 1))))])


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def conflicts(live: list[dict], cap: int = 200) -> list[dict]:
    """ერთ თემაზე დამტკიცებული ჩანაწერები, რომლებშიც რიცხვები (%, თანხა) განსხვავდება — შესაძლო წინააღმდეგობა."""
    out, seen = [], set()
    for e in live[:cap]:
        for s in kn.find_similar(e, live):
            if not s["numbers_differ"]:
                continue
            key = tuple(sorted((str(e.get("kb_id")), str(s["kb_id"]))))
            if key in seen:
                continue
            seen.add(key)
            out.append({"a": {"kb_id": e.get("kb_id"), "title": e.get("title")}, "b": {"kb_id": s["kb_id"], "title": s["title"]}, "similarity": s["similarity"]})
    return out[:20]


def dashboard(viewer: dict, days: int = 30, names: dict | None = None) -> dict:
    if not store.can_manage(viewer):
        raise m.AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    days = max(1, min(180, int(days or 30)))
    cutoff = (m.now_dt() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    team_ok = (lambda r: True) if viewer.get("admin") else (lambda r: m.s(r.get("team")) == m.s(viewer.get("team")))
    msgs = [r for r in store.messages_since(cutoff) if team_ok(r)]
    users = {m.s(r.get("msg_id")): r for r in msgs if m.s(r.get("role")) == "user"}
    asst = [r for r in msgs if m.s(r.get("role")) == "assistant"]
    answered = [r for r in asst if m.s(r.get("outcome")) in ("ok", "no_answer")]

    by_type: dict[str, int] = {}
    for r in answered:
        k = m.s(r.get("answer_type")) or "unknown"
        by_type[k] = by_type.get(k, 0) + 1
    lat = [_num(r.get("latency_ms")) for r in answered if _num(r.get("latency_ms")) > 0]
    qtexts = [m.s(u.get("text")) for u in users.values()]
    live = store.live_rows()

    top = [{"question": c["text"], "count": c["count"]} for c in kn.cluster(qtexts)[:8]]
    unans_texts = [m.s(users.get(m.s(r.get("msg_id"))[:-1], {}).get("text")) for r in asst
                   if m.s(r.get("outcome")) in ("no_answer", "error") or m.s(r.get("needs_manager")) in ("yes", "escalated")]
    unans = [{"question": c["text"], "count": c["count"]} for c in kn.cluster([t for t in unans_texts if t])[:10]]
    faq = []
    for c in kn.cluster(qtexts):
        if c["count"] < 3:
            break
        if not any(kn.score(c["text"], e) >= 0.25 for e in live):
            faq.append({"question": c["text"], "count": c["count"]})
    faq = faq[:8]

    fb = [r for r in store.feedback_since(cutoff) if team_ok(r)]
    fb_counts = {k: sum(1 for r in fb if m.s(r.get("rating")) == k) for k in m.RATINGS}
    fb_reasons: dict[str, int] = {}
    for r in fb:
        if m.s(r.get("reason")):
            fb_reasons[m.s(r.get("reason"))] = fb_reasons.get(m.s(r.get("reason")), 0) + 1
    by_msg = {m.s(r.get("msg_id")): r for r in asst}
    reports = []
    for r in sorted([x for x in fb if m.s(x.get("rating")) in ("down", "report")], key=lambda x: m.s(x.get("created_at")), reverse=True)[:10]:
        a = by_msg.get(m.s(r.get("msg_id")), {})
        reports.append({"question": m.s(users.get(m.s(r.get("msg_id"))[:-1], {}).get("text"), 300), "answer": m.s(a.get("text"), 300),
                        "rating": r.get("rating"), "reason": r.get("reason"), "comment": r.get("comment"), "at": r.get("created_at")})

    kb = [r for r in store.kb_all() if viewer.get("admin") or not m.s(r.get("scope_team")) or m.s(r.get("scope_team")) == m.s(viewer.get("team"))]
    today = m.today_str()
    soon = (m.now_dt() + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
    kb_health = {
        "approved": sum(1 for r in kb if m.s(r.get("status")) == m.KB_APPROVED), "drafts": sum(1 for r in kb if m.s(r.get("status")) == m.KB_DRAFT),
        "retired": sum(1 for r in kb if m.s(r.get("status")) == m.KB_RETIRED),
        "expiring": [{"kb_id": r.get("kb_id"), "title": r.get("title"), "effective_to": r.get("effective_to")} for r in kb
                     if m.s(r.get("status")) == m.KB_APPROVED and m.s(r.get("effective_to")) and today <= m.s(r.get("effective_to")) <= soon],
        "expired": [{"kb_id": r.get("kb_id"), "title": r.get("title"), "effective_to": r.get("effective_to")} for r in kb
                    if m.s(r.get("status")) == m.KB_APPROVED and m.s(r.get("effective_to")) and m.s(r.get("effective_to")) < today],
        "conflicts": conflicts([r for r in live if viewer.get("admin") or not m.s(r.get("scope_team")) or m.s(r.get("scope_team")) == m.s(viewer.get("team"))]),
    }
    review = store.review_visible(viewer, status=m.RV_OPEN)
    out = {
        "days": days, "enabled": bool(config.AI_ENABLED),
        "totals": {"questions": len(users), "answered": len(answered), "errors": sum(1 for r in asst if m.s(r.get("outcome")) == "error"),
                   "refused": sum(1 for r in asst if m.s(r.get("outcome")) == "refused"), "escalated": sum(1 for r in asst if m.s(r.get("needs_manager")) == "escalated"),
                   "by_type": by_type, "no_answer": sum(1 for r in answered if m.s(r.get("outcome")) == "no_answer")},
        "quality": {"avg_latency_ms": int(sum(lat) / len(lat)) if lat else 0, "p95_latency_ms": _pct(lat, 0.95),
                    "helpful_pct": round(100 * fb_counts["up"] / max(1, fb_counts["up"] + fb_counts["down"] + fb_counts["report"])) if fb else None},
        "top_questions": top, "unanswered": unans, "faq_suggestions": faq, "feedback": {"counts": fb_counts, "reasons": fb_reasons, "recent": reports},
        "knowledge": kb_health,
        "review_open": {t: sum(1 for r in review if m.s(r.get("type")) == t) for t in m.REVIEW_TYPES},
    }
    if viewer.get("admin"):
        by_agent: dict[str, dict] = {}
        for r in answered:
            a = by_agent.setdefault(m.s(r.get("agent_id")), {"requests": 0, "cost_usd": 0.0, "tokens": 0})
            a["requests"] += 1
            a["cost_usd"] += _num(r.get("cost_usd"))
            a["tokens"] += int(_num(r.get("tokens_in")) + _num(r.get("tokens_out")))
        top_users = sorted(by_agent.items(), key=lambda kv: -kv[1]["cost_usd"])[:10]
        out["cost"] = {"total_usd": round(sum(_num(r.get("cost_usd")) for r in answered), 4), "month_usd": round(store.month_cost(), 4),
                       "monthly_budget_usd": config.AI_MONTHLY_BUDGET_USD, "estimate": True,
                       "tokens_in": int(sum(_num(r.get("tokens_in")) for r in answered)), "tokens_out": int(sum(_num(r.get("tokens_out")) for r in answered)),
                       "by_user": [{"user": (names or {}).get(k, k), "requests": v["requests"], "cost_usd": round(v["cost_usd"], 4), "tokens": v["tokens"]} for k, v in top_users]}
    else:
        out["cost"] = None
    return out
