"""
Safe Home AI — შენახვა: ცოდნის ბაზა (+ვერსიები), საუბრები, უკუკავშირი, განსახილველი რიგი. იგივე ბექენდის ნიმუში, რაც criteria_store/contracts_store
(ცხრილები იქმნება ზარმაცად; არსებულ ცხრილებს არაფერი ეხება). ყველა ჩაწერა ერთ პროცესულ ბლოკირებაშია.

უფლებები (viewer = {"agent_id","role","team","admin"}):
  * მართვა (დრაფტი/რედაქტირება/უარყოფა): ადმინი, თიმლიდერი (თავისი გუნდის/საერთო ჩანაწერები).
  * გამოქვეყნება: ადმინი — ყველა; თიმლიდერი — `config.AI_KB_RESTRICTED_CATEGORIES`-ის (საკომისიო/იურიდიული/ფინანსური) გარდა.
  * AI იყენებს მხოლოდ `approved` + მოქმედ ჩანაწერებს (`ai_model.kb_live`). დრაფტი/უარყოფილი/გაუქმებული — არასდროს.
"""

from __future__ import annotations

import collections
import datetime
import logging
import threading

import ai_knowledge as kn
import ai_model as m
import config
import contracts_store as _cs
from ai_model import AiError

log = logging.getLogger("safehome-ai-store")
_lock = threading.RLock()


# ====================================================================== შენახვის ფენები
class SheetsBackend(_cs.SheetsBackend):
    def ensure(self) -> None:
        if self._ready:
            return
        sg = self._sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in m.ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        self._ready = True

    def append_many(self, name: str, headers: list[str], rows: list[dict]) -> None:
        """ერთი API-გამოძახება რამდენიმე სტრიქონზე (Sheets-ის კვოტის დაზოგვა)."""
        self.ensure()
        sg = self._sg()
        sg._worksheet(name).append_rows([[str(d.get(h, "")) for h in headers] for d in rows], value_input_option="RAW")
        sg._invalidate(name)

    def delete_prefix(self, name: str, n: int) -> None:
        if n <= 0:
            return
        self.ensure()
        sg = self._sg()
        sg._worksheet(name).delete_rows(2, 1 + n)
        sg._invalidate(name)


class MemoryBackend(_cs.MemoryBackend):
    def ensure(self) -> None:
        for name, _h, _r in m.ALL_TABS:
            self.tables.setdefault(name, [])

    def append_many(self, name, headers, rows) -> None:
        for d in rows:
            self.append(name, headers, d)

    def delete_prefix(self, name, n) -> None:
        self.ensure()
        del self.tables[name][:max(0, n)]


_backend = SheetsBackend()


def set_backend(b) -> None:
    global _backend
    _backend = b
    reset_caches()


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


# ====================================================================== უფლებები
def can_manage(viewer: dict) -> bool:
    return bool(viewer.get("admin") or viewer.get("role") == m.ROLE_LEAD)


def can_publish(viewer: dict, category: str, scope_team: str = "") -> bool:
    if viewer.get("admin"):
        return True
    if viewer.get("role") != m.ROLE_LEAD or not config.AI_KB_TEAMLEAD_CAN_PUBLISH:
        return False
    if m.s(category, 30).lower() in config.AI_KB_RESTRICTED_CATEGORIES:
        return False
    sc = m.s(scope_team, 80)
    return not sc or sc == m.s(viewer.get("team"), 80)


def _sees_scope(viewer: dict, scope_team: str) -> bool:
    sc = m.s(scope_team, 80)
    return bool(viewer.get("admin")) or not sc or sc == m.s(viewer.get("team"), 80)


# ====================================================================== ცოდნის ბაზა
def kb_all(fresh: bool = False) -> list[dict]:
    return _backend.read(m.KB_SHEET, fresh=fresh)


def kb_get(kb_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in kb_all(fresh) if m.s(r.get("kb_id")) == m.s(kb_id)), None)


def versions_of(kb_id: str, fresh: bool = False) -> list[dict]:
    rows = [r for r in _backend.read(m.KB_VERSIONS_SHEET, fresh=fresh) if m.s(r.get("kb_id")) == m.s(kb_id)]
    rows.sort(key=lambda r: int(m.s(r.get("version"), 6) or 0))
    return rows


def _open_draft(kb_id: str) -> dict | None:
    return next((v for v in reversed(versions_of(kb_id, fresh=True)) if m.s(v.get("status")) == m.V_DRAFT), None)


def _vrow(kb_id: str, ver: int, data: dict, status: str, actor: str, reason: str = "", approved_by: str = "") -> dict:
    return {"version_id": m.new_id("v"), "kb_id": kb_id, "version": str(ver), "title": data["title"], "body": data["body"],
            "category": data["category"], "language": data["language"], "effective_from": data["effective_from"],
            "effective_to": data["effective_to"], "scope_team": data["scope_team"], "status": status, "changed_by": actor,
            "approved_by": approved_by, "reason": m.s(reason, 300), "at": m.now_str()}


def _vchanges(kb_id: str, ver: int, data: dict, actor: str, reason: str) -> dict:
    """არსებული ვერსიის სტრიქონის განახლება — ID-ს (version_id) არ ვცვლით."""
    return {k: v for k, v in _vrow(kb_id, ver, data, m.V_DRAFT, actor, reason).items() if k != "version_id"}


def kb_create(viewer: dict, data: dict, source: str = "manual", source_ref: str = "", reason: str = "") -> dict:
    if not can_manage(viewer):
        raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    d = m.parse_kb_input(data)
    if not _sees_scope(viewer, d["scope_team"]):
        raise AiError("სხვა გუნდის ჩანაწერს ვერ შექმნით", 403)
    actor = m.s(viewer.get("agent_id") or ("admin" if viewer.get("admin") else ""), 40)
    with _lock:
        kb_id = m.new_id("kb")
        now = m.now_str()
        head = dict(d, kb_id=kb_id, status=m.KB_DRAFT, version="1", source=m.s(source, 30), source_ref=m.s(source_ref, 60),
                    created_by=actor, created_at=now, updated_at=now, approved_by="", approved_at="")
        _backend.append(m.KB_SHEET, m.KB_HEADERS, head)
        _backend.append(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, _vrow(kb_id, 1, d, m.V_DRAFT, actor, reason or "დრაფტი"))
        return head


def kb_edit(viewer: dict, kb_id: str, data: dict, reason: str = "") -> dict:
    """დრაფტი — ადგილზე იცვლება; დამტკიცებულის რედაქტირება ქმნის **ახალ დრაფტ-ვერსიას** (მოქმედი ვერსია გამოქვეყნებამდე უცვლელია)."""
    if not can_manage(viewer):
        raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    with _lock:
        head = kb_get(kb_id, fresh=True)
        if not head or not _sees_scope(viewer, head.get("scope_team")):
            raise AiError("ჩანაწერი ვერ მოიძებნა", 404)
        if m.s(head.get("status")) == m.KB_RETIRED:
            raise AiError("გაუქმებული ჩანაწერი აღარ რედაქტირდება — შექმენით ახალი", 409)
        draft = _open_draft(kb_id)
        base = draft or head
        d = m.parse_kb_input(data, existing=base)
        if not _sees_scope(viewer, d["scope_team"]):
            raise AiError("სხვა გუნდის ჩანაწერად ვერ გადაიტანთ", 403)
        actor = m.s(viewer.get("agent_id") or "admin", 40)
        if m.s(head.get("status")) == m.KB_DRAFT:                       # ჯერ არ გამოქვეყნებულა — ერთი დრაფტი
            ch = dict(d, updated_at=m.now_str())
            _backend.update(m.KB_SHEET, m.KB_HEADERS, kb_id, ch)
            if draft:
                _backend.update(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, draft["version_id"],
                                _vchanges(kb_id, int(draft["version"]), d, actor, reason or "რედაქტირება"))
            return kb_get(kb_id, fresh=True)
        if draft:                                                       # უკვე არსებული მომლოდინე გადასინჯვა
            _backend.update(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, draft["version_id"],
                            _vchanges(kb_id, int(draft["version"]), d, actor, reason or "რედაქტირება"))
        else:
            nxt = 1 + max([int(m.s(v.get("version"), 6) or 0) for v in versions_of(kb_id, fresh=True)] or [0])
            _backend.append(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, _vrow(kb_id, nxt, d, m.V_DRAFT, actor, reason or "ახალი ვერსია"))
        return kb_get(kb_id, fresh=True)


def live_rows(team: str | None = None) -> list[dict]:
    return kn.live_entries(kb_all(), team=team)


def kb_publish(viewer: dict, kb_id: str, confirm_similar: bool = False, note: str = "") -> dict:
    with _lock:
        head = kb_get(kb_id, fresh=True)
        if not head or not _sees_scope(viewer, head.get("scope_team")):
            raise AiError("ჩანაწერი ვერ მოიძებნა", 404)
        draft = _open_draft(kb_id)
        if not draft:
            raise AiError("გამოსაქვეყნებელი დრაფტი არ არის", 409)
        restricted = any(m.s(c).lower() in config.AI_KB_RESTRICTED_CATEGORIES for c in (draft.get("category"), head.get("category")))
        if restricted and not viewer.get("admin"):
            raise AiError("ამ კატეგორიის (საკომისიო/იურიდიული/ფინანსური) გამოქვეყნება მხოლოდ ადმინს შეუძლია", 403)
        if not (can_publish(viewer, draft.get("category"), draft.get("scope_team")) and can_publish(viewer, head.get("category"), head.get("scope_team"))):
            raise AiError("გამოქვეყნების უფლება არ გაქვთ", 403)
        similar = kn.find_similar(draft, [r for r in kb_all(True) if m.s(r.get("status")) == m.KB_APPROVED])
        if similar and not confirm_similar:
            raise AiError("მსგავსი დამტკიცებული ჩანაწერი უკვე არსებობს — გადაამოწმეთ და დაადასტურეთ", 409, "similar", {"similar": similar})
        actor = m.s(viewer.get("agent_id") or "admin", 40)
        for v in versions_of(kb_id, fresh=True):
            if m.s(v.get("status")) == m.V_PUBLISHED:
                _backend.update(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, v["version_id"], {"status": m.V_SUPERSEDED})
        _backend.update(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, draft["version_id"],
                        {"status": m.V_PUBLISHED, "approved_by": actor, "at": m.now_str(), "reason": m.s(note or draft.get("reason"), 300)})
        now = m.now_str()
        _backend.update(m.KB_SHEET, m.KB_HEADERS, kb_id, {
            "title": draft["title"], "body": draft["body"], "category": draft["category"], "language": draft["language"],
            "effective_from": draft["effective_from"], "effective_to": draft["effective_to"], "scope_team": draft["scope_team"],
            "status": m.KB_APPROVED, "version": draft["version"], "approved_by": actor, "approved_at": now, "updated_at": now})
        out = kb_get(kb_id, fresh=True)
        out["similar_confirmed"] = bool(similar)
        return out


def kb_reject(viewer: dict, kb_id: str, reason: str = "") -> dict:
    if not can_manage(viewer):
        raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    with _lock:
        head = kb_get(kb_id, fresh=True)
        if not head or not _sees_scope(viewer, head.get("scope_team")):
            raise AiError("ჩანაწერი ვერ მოიძებნა", 404)
        draft = _open_draft(kb_id)
        if not draft:
            raise AiError("უარსაყოფი დრაფტი არ არის", 409)
        _backend.update(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, draft["version_id"],
                        {"status": m.V_REJECTED, "reason": m.s(reason, 300), "approved_by": m.s(viewer.get("agent_id") or "admin", 40), "at": m.now_str()})
        if m.s(head.get("status")) == m.KB_DRAFT:
            _backend.update(m.KB_SHEET, m.KB_HEADERS, kb_id, {"status": m.KB_RETIRED, "updated_at": m.now_str()})
        return kb_get(kb_id, fresh=True)


def kb_retire(viewer: dict, kb_id: str, reason: str = "") -> dict:
    with _lock:
        head = kb_get(kb_id, fresh=True)
        if not head or not _sees_scope(viewer, head.get("scope_team")):
            raise AiError("ჩანაწერი ვერ მოიძებნა", 404)
        if not can_publish(viewer, head.get("category"), head.get("scope_team")):
            raise AiError("გაუქმების უფლება არ გაქვთ (შეზღუდული კატეგორია — მხოლოდ ადმინი)", 403)
        for v in versions_of(kb_id, fresh=True):
            if m.s(v.get("status")) == m.V_PUBLISHED:
                _backend.update(m.KB_VERSIONS_SHEET, m.VERSION_HEADERS, v["version_id"], {"status": m.V_RETIRED, "reason": m.s(reason, 300), "at": m.now_str()})
        _backend.update(m.KB_SHEET, m.KB_HEADERS, kb_id, {"status": m.KB_RETIRED, "updated_at": m.now_str()})
        return kb_get(kb_id, fresh=True)


def kb_list(viewer: dict, status: str = "") -> list[dict]:
    if not can_manage(viewer):
        raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    drafts: dict[str, dict] = {}
    for v in _backend.read(m.KB_VERSIONS_SHEET):
        if m.s(v.get("status")) == m.V_DRAFT:
            drafts[m.s(v.get("kb_id"))] = v
    out = []
    for r in kb_all():
        if not _sees_scope(viewer, r.get("scope_team")):
            continue
        if status and m.s(r.get("status")) != status:
            continue
        item = dict(r)
        pend = drafts.get(m.s(r.get("kb_id")))
        item["pending_revision"] = bool(pend) and m.s(r.get("status")) == m.KB_APPROVED
        item["pending_title"] = pend.get("title") if item["pending_revision"] else ""
        item["can_publish"] = can_publish(viewer, r.get("category"), r.get("scope_team"))
        out.append(item)
    out.sort(key=lambda r: (m.s(r.get("status")) != m.KB_DRAFT, not r.get("pending_revision"), m.s(r.get("updated_at"))), reverse=False)
    return out


def import_seed(viewer: dict, items: list[dict]) -> dict:
    """ძველი ხისტი ტექსტების იმპორტი **დრაფტებად** (არასდროს approved). იდემპოტენტურია source_ref-ით."""
    if not viewer.get("admin"):
        raise AiError("მხოლოდ ადმინს შეუძლია", 403)
    have = {m.s(r.get("source_ref")) for r in kb_all(True) if m.s(r.get("source")) == "legacy_regulations"}
    created = skipped = 0
    for it in items:
        if it["source_ref"] in have:
            skipped += 1
            continue
        kb_create(viewer, {"title": it["title"], "body": it["body"], "category": it.get("category", "policy"), "language": "ka",
                           "owner": "დირექტორი (გადასამოწმებელი)"}, source="legacy_regulations", source_ref=it["source_ref"],
                  reason="იმპორტი Mini App-ის ძველი „ინსტრუქცია/წესები“ ტექსტიდან — არ არის დამტკიცებული")
        created += 1
    return {"created": created, "skipped": skipped}


# ====================================================================== საუბრები
_conv_cache: "collections.OrderedDict[str, list[dict]]" = collections.OrderedDict()
_CONV_CACHE_MAX = 300
_usage = {"day": None, "month": None, "per_agent": {}, "month_cost": 0.0}
_sync = {"at": 0.0}


def reset_caches() -> None:
    with _lock:
        _conv_cache.clear()
        _usage.update(day=None, month=None, per_agent={}, month_cost=0.0)
        _sync["at"] = 0.0


def expires_str(now: datetime.datetime | None = None) -> str:
    return ((now or m.now_dt()) + datetime.timedelta(days=max(1, config.AI_RETENTION_DAYS))).strftime("%Y-%m-%d %H:%M:%S")


def messages_append(rows: list[dict]) -> None:
    with _lock:
        _backend.append_many(m.MESSAGES_SHEET, m.MESSAGE_HEADERS, rows)
        for r in rows:
            h = _conv_cache.setdefault(m.s(r["conv_id"]), [])
            h.append({"role": r["role"], "text": r["text"], "agent_id": r["agent_id"], "msg_id": r["msg_id"],
                      "answer_type": r.get("answer_type", ""), "outcome": r.get("outcome", "")})
            _conv_cache.move_to_end(m.s(r["conv_id"]))
        while len(_conv_cache) > _CONV_CACHE_MAX:
            _conv_cache.popitem(last=False)


def conv_rows(conv_id: str, agent_id: str, limit: int | None = None) -> list[dict]:
    """მხოლოდ **ამ აგენტის** საუბრის ბოლო შეტყობინებები (სხვისი conv_id-ით ცარიელი სია), ძველიდან ახლისკენ: [{role, text, answer_type}]."""
    limit = limit or config.AI_HISTORY_TURNS
    with _lock:
        cached = _conv_cache.get(m.s(conv_id))
    if cached is None:
        cached = [{"role": r["role"], "text": r["text"], "agent_id": r["agent_id"], "msg_id": r["msg_id"],
                   "answer_type": r.get("answer_type", ""), "outcome": r.get("outcome", "")}
                  for r in _backend.read(m.MESSAGES_SHEET) if m.s(r.get("conv_id")) == m.s(conv_id)]
    return [x for x in cached if m.s(x.get("agent_id")) == m.s(agent_id)][-limit:]


def messages_since(cutoff: str) -> list[dict]:
    return [r for r in _backend.read(m.MESSAGES_SHEET) if m.s(r.get("created_at")) >= cutoff]


def feedback_since(cutoff: str) -> list[dict]:
    return [r for r in _backend.read(m.FEEDBACK_SHEET) if m.s(r.get("created_at")) >= cutoff]


def find_message(msg_id: str) -> dict | None:
    return next((r for r in _backend.read(m.MESSAGES_SHEET) if m.s(r.get("msg_id")) == m.s(msg_id)), None)


def my_conversations(agent_id: str, limit: int = 10) -> list[dict]:
    convs: dict[str, dict] = {}
    for r in _backend.read(m.MESSAGES_SHEET):
        if m.s(r.get("agent_id")) != m.s(agent_id):
            continue
        c = convs.setdefault(m.s(r.get("conv_id")), {"conv_id": m.s(r.get("conv_id")), "title": "", "last_at": "", "messages": 0})
        c["messages"] += 1
        c["last_at"] = max(c["last_at"], m.s(r.get("created_at")))
        if r.get("role") == "user" and not c["title"]:
            c["title"] = m.s(r.get("text"), 70)
    return sorted(convs.values(), key=lambda c: c["last_at"], reverse=True)[:limit]


def conv_messages(conv_id: str, agent_id: str) -> list[dict]:
    return [dict(r) for r in _backend.read(m.MESSAGES_SHEET)
            if m.s(r.get("conv_id")) == m.s(conv_id) and m.s(r.get("agent_id")) == m.s(agent_id)]


# ---- გამოყენება/ხარჯი (მეხსიერებაში; დღეში ერთხელ ცხრილიდან ისევ ივსება)
def _ensure_usage() -> None:
    day, month = m.today_str(), m.today_str()[:7]
    with _lock:
        if _usage["day"] == day and _usage["month"] == month:
            return
        per, mc = {}, 0.0
        for r in _backend.read(m.MESSAGES_SHEET):
            if m.s(r.get("role")) != "assistant" or m.s(r.get("outcome")) not in ("ok", "no_answer"):
                continue
            at = m.s(r.get("created_at"))
            if at[:7] == month:
                try:
                    mc += float(r.get("cost_usd") or 0)
                except ValueError:
                    pass
            if at[:10] == day:
                a = per.setdefault(m.s(r.get("agent_id")), {"requests": 0, "cost": 0.0})
                a["requests"] += 1
                try:
                    a["cost"] += float(r.get("cost_usd") or 0)
                except ValueError:
                    pass
        _usage.update(day=day, month=month, per_agent=per, month_cost=mc)


def usage_today(agent_id: str) -> dict:
    _ensure_usage()
    return dict(_usage["per_agent"].get(m.s(agent_id), {"requests": 0, "cost": 0.0}))


def month_cost() -> float:
    _ensure_usage()
    return float(_usage["month_cost"])


def usage_add(agent_id: str, cost: float) -> None:
    _ensure_usage()
    with _lock:
        a = _usage["per_agent"].setdefault(m.s(agent_id), {"requests": 0, "cost": 0.0})
        a["requests"] += 1
        a["cost"] += float(cost or 0)
        _usage["month_cost"] += float(cost or 0)


def purge_expired(now: datetime.datetime | None = None) -> dict:
    """ვადაგასული საუბრების/უკუკავშირის წაშლა. ჩანაწერები ქრონოლოგიურია, ამიტომ ვადაგასული — ყოველთვის **პრეფიქსია**: ერთი delete_rows-ით."""
    now = now or m.now_dt()
    out = {"messages": 0, "feedback": 0}
    with _lock:
        rows = _backend.read(m.MESSAGES_SHEET, fresh=True)
        n = 0
        for r in rows:
            exp = m.parse_dt(r.get("expires_at"))
            if exp is not None and exp < now:
                n += 1
            else:
                break
        if n:
            _backend.delete_prefix(m.MESSAGES_SHEET, n)
        out["messages"] = n
        cutoff = now - datetime.timedelta(days=max(1, config.AI_RETENTION_DAYS))
        fb = _backend.read(m.FEEDBACK_SHEET, fresh=True)
        k = 0
        for r in fb:
            at = m.parse_dt(r.get("created_at"))
            if at is not None and at < cutoff:
                k += 1
            else:
                break
        if k:
            _backend.delete_prefix(m.FEEDBACK_SHEET, k)
        out["feedback"] = k
        if n:
            _conv_cache.clear()
    return out


# ====================================================================== უკუკავშირი
def feedback_get(msg_id: str, agent_id: str) -> dict | None:
    return next((r for r in _backend.read(m.FEEDBACK_SHEET, fresh=True)
                 if m.s(r.get("msg_id")) == m.s(msg_id) and m.s(r.get("agent_id")) == m.s(agent_id)), None)


def feedback_add(agent: dict, msg_id: str, rating: str, reason: str = "", comment: str = "") -> tuple[dict, bool]:
    """(ჩანაწერი, ახალია?). ერთი უკუკავშირი ერთ პასუხზე ერთ აგენტზე; განმეორება იდემპოტენტურია. აგენტს მხოლოდ **საკუთარ** პასუხზე შეუძლია."""
    import ai_privacy as pv
    if rating not in m.RATINGS:
        raise AiError("rating: up / down / report")
    if reason and reason not in m.FEEDBACK_REASONS:
        raise AiError("მიზეზი: " + ", ".join(m.FEEDBACK_REASONS))
    msg = find_message(msg_id)
    if not msg or m.s(msg.get("agent_id")) != m.s(agent.get("agent_id")) or m.s(msg.get("role")) != "assistant":
        raise AiError("პასუხი ვერ მოიძებნა", 404)
    with _lock:
        ex = feedback_get(msg_id, agent.get("agent_id"))
        if ex:
            return ex, False
        row = {"feedback_id": m.new_id("f"), "msg_id": m.s(msg_id), "agent_id": m.s(agent.get("agent_id")), "team": m.s(agent.get("team"), 80),
               "rating": rating, "reason": m.s(reason, 20), "comment": pv.redact(m.s(comment, 500)), "created_at": m.now_str()}
        _backend.append(m.FEEDBACK_SHEET, m.FEEDBACK_HEADERS, row)
        return row, True


# ====================================================================== განსახილველი რიგი
def review_all(fresh: bool = False) -> list[dict]:
    return _backend.read(m.REVIEW_SHEET, fresh=fresh)


def review_get(item_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in review_all(fresh) if m.s(r.get("item_id")) == m.s(item_id)), None)


def _review_row(type_: str, **kw) -> dict:
    row = {h: "" for h in m.REVIEW_HEADERS}
    row.update({"item_id": m.new_id("r"), "type": type_, "status": m.RV_OPEN, "similar_count": "1", "created_at": m.now_str()})
    row.update({k: m.s(v, 3000) for k, v in kw.items() if k in m.REVIEW_HEADERS})
    return row


def review_add(type_: str, **kw) -> dict:
    row = _review_row(type_, **kw)
    with _lock:
        _backend.append(m.REVIEW_SHEET, m.REVIEW_HEADERS, row)
    return row


def review_unanswered(question_redacted: str, team: str, msg_id: str, category: str = "") -> dict:
    """კითხვა, რომელზეც AI-მ საიმედოდ ვერ უპასუხა: მსგავსი ღია ჩანაწერის მრიცხველს ვზრდით (ახალს არ ვქმნით) — განმეორებადი კითხვა ერთ ხაზად ჩანს."""
    q = m.s(question_redacted, 1500)
    with _lock:
        for r in review_all(True):
            if m.s(r.get("type")) == m.R_UNANSWERED and m.s(r.get("status")) == m.RV_OPEN and m.s(r.get("team")) == m.s(team, 80) \
                    and (m.norm_text(r.get("question_text")) == m.norm_text(q) or kn.similarity(r.get("question_text"), q) >= 0.7):
                n = int(m.s(r.get("similar_count"), 6) or 1) + 1
                _backend.update(m.REVIEW_SHEET, m.REVIEW_HEADERS, r["item_id"], {"similar_count": str(n)})
                return dict(r, similar_count=str(n))
        return review_add(m.R_UNANSWERED, question_text=q, team=m.s(team, 80), source_msg_id=msg_id, category=category)


def review_feedback(msg: dict, question_text: str, rating: str, reason: str, comment: str, team: str) -> dict:
    return review_add(m.R_FEEDBACK, question_text=m.s(question_text, 1500), draft_body=m.s(msg.get("text"), 1500), team=m.s(team, 80),
                      source_msg_id=m.s(msg.get("msg_id")), note=f"{rating}/{reason}: {m.s(comment, 400)}")


def sync_candidates(question_rows: list[dict], now: datetime.datetime | None = None, force: bool = False, cap: int = 100) -> int:
    """მენეჯერის პასუხი არსებულ „კითხვა მენეჯერს“ ნაკადში -> **კანდიდატი** განსახილველ რიგში (არ ქვეყნდება!). არსებული endpoint-ები უცვლელია:
    კანდიდატებს ვქმნით რიგის წაკითხვისას (≥60 წმ ინტერვალით). ტელეფონები/ელფოსტები ამოღებულია; ბოლო AI_CANDIDATE_LOOKBACK_DAYS დღე."""
    import time

    import ai_privacy as pv
    if not force and time.time() - _sync["at"] < 60:
        return 0
    _sync["at"] = time.time()
    now = now or m.now_dt()
    cutoff = now - datetime.timedelta(days=max(1, config.AI_CANDIDATE_LOOKBACK_DAYS))
    with _lock:
        seen = {m.s(r.get("source_question_id")) for r in review_all(True) if m.s(r.get("source_question_id"))}
        answered = [q for q in question_rows if m.s(q.get("answer")) and m.s(q.get("status")) != "open"]
        recent = []
        for q in answered:
            at = m.parse_dt(q.get("answered_at")) or m.parse_dt(q.get("created_at"))
            if at is None or at >= cutoff:
                recent.append(q)
        recent.sort(key=lambda q: m.s(q.get("answered_at") or q.get("created_at")), reverse=True)
        pool = [pv.redact(m.s(q.get("text"), 1500)) for q in question_rows]
        new_rows = []
        for q in recent:
            qid = m.s(q.get("question_id"))
            if not qid or qid in seen or len(new_rows) >= cap:
                continue
            text = pv.redact(m.s(q.get("text"), 1500))
            sim = sum(1 for p in pool if kn.overlap(text, p) >= 0.6)
            new_rows.append(_review_row(m.R_CANDIDATE, question_text=text, draft_title=m.s(text, 120), draft_body=pv.redact(m.s(q.get("answer"), 3000)),
                                        category="faq", source_question_id=qid, team=m.s(q.get("team"), 80), similar_count=str(max(1, sim)),
                                        note=f"პასუხი: {m.s(q.get('answered_by'), 60)}"))
        if new_rows:
            _backend.append_many(m.REVIEW_SHEET, m.REVIEW_HEADERS, new_rows)      # ერთი API-გამოძახება
    return len(new_rows)


def review_visible(viewer: dict, status: str = "", type_: str = "") -> list[dict]:
    if not can_manage(viewer):
        raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    out = []
    for r in review_all():
        if not (viewer.get("admin") or not m.s(r.get("team")) or m.s(r.get("team")) == m.s(viewer.get("team"))):
            continue
        if status and m.s(r.get("status")) != status:
            continue
        if type_ and m.s(r.get("type")) != type_:
            continue
        out.append(dict(r))
    out.sort(key=lambda r: (-int(m.s(r.get("similar_count"), 6) or 1), m.s(r.get("created_at"))), reverse=False)
    return out


def review_dismiss(viewer: dict, item_id: str, note: str = "") -> dict:
    if not can_manage(viewer):
        raise AiError("მხოლოდ მენეჯერს/ადმინს შეუძლია", 403)
    with _lock:
        r = review_get(item_id, True)
        if not r or not (viewer.get("admin") or not m.s(r.get("team")) or m.s(r.get("team")) == m.s(viewer.get("team"))):
            raise AiError("ვერ მოიძებნა", 404)
        _backend.update(m.REVIEW_SHEET, m.REVIEW_HEADERS, item_id, {"status": m.RV_DISMISSED, "decided_by": m.s(viewer.get("agent_id") or "admin", 40),
                                                                      "decided_at": m.now_str(), "note": m.s(note or r.get("note"), 300)})
        return review_get(item_id, True)


def review_to_draft(viewer: dict, item_id: str, data: dict) -> tuple[dict, dict]:
    """კანდიდატი/უპასუხო კითხვა -> ცოდნის ბაზის **დრაფტი** (მენეჯერი სათაურს/ტექსტს ამოწმებს და ასწორებს). გამოქვეყნება ცალკე ნაბიჯია."""
    with _lock:
        r = review_get(item_id, True)
        if not r or m.s(r.get("status")) != m.RV_OPEN or not (viewer.get("admin") or not m.s(r.get("team")) or m.s(r.get("team")) == m.s(viewer.get("team"))):
            raise AiError("ვერ მოიძებნა ან უკვე დამუშავებულია", 404)
        payload = {"title": r.get("draft_title") or r.get("question_text"), "body": r.get("draft_body"), "category": r.get("category") or "faq", "language": "any"}
        payload.update({k: v for k, v in (data or {}).items() if k in ("title", "body", "category", "language", "owner", "effective_from", "effective_to", "scope_team")})
        kb = kb_create(viewer, payload, source="question" if r.get("source_question_id") else "ai_suggestion", source_ref=m.s(r.get("source_question_id") or r.get("item_id"), 60),
                       reason="კანდიდატიდან (მენეჯერის პასუხი)")
        now, who = m.now_str(), m.s(viewer.get("agent_id") or "admin", 40)
        _backend.update(m.REVIEW_SHEET, m.REVIEW_HEADERS, item_id, {"status": m.RV_PUBLISHED, "kb_id": kb["kb_id"], "decided_by": who, "decided_at": now})
        for o in review_all(True):                                   # იმავე კითხვაზე ღია „უპასუხო“ ჩანაწერები დრაფტით იფარება
            if m.s(o.get("type")) == m.R_UNANSWERED and m.s(o.get("status")) == m.RV_OPEN and m.s(o.get("team")) == m.s(r.get("team")) \
                    and kn.overlap(o.get("question_text"), r.get("question_text")) >= 0.6:
                _backend.update(m.REVIEW_SHEET, m.REVIEW_HEADERS, o["item_id"], {"status": m.RV_PUBLISHED, "kb_id": kb["kb_id"], "decided_by": who, "decided_at": now})
        return kb, review_get(item_id, True)


def message_mark(msg_id: str, **changes) -> None:
    with _lock:
        _backend.update(m.MESSAGES_SHEET, m.MESSAGE_HEADERS, msg_id, changes)
