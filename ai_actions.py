"""
SAIRO — მოქმედებები **ადამიანის დადასტურებით** (Propose → Confirm → Execute).

პრინციპები:
  * AI მხოლოდ **ამზადებს** შეთავაზებას (`propose`) — გვერდითი ეფექტის გარეშე. ბარათში ჩანს: რას აპირებს, ვის ეხება, რა ტექსტი/ცვლილება შესრულდება, რა შედეგს ელოდება.
  * შესრულება (`confirm`) ხდება **მხოლოდ** მომხმარებლის HTTP-მოთხოვნით (initData), სერვერზე გადამოწმებული პირადობით. მოდელს confirm-ის ინსტრუმენტი არ აქვს.
  * დადასტურება კონკრეტულ შინაარსზეა მიბმული: `hash = sha256(uid + type + payload)`; კლიენტი იმავე hash-ს აბრუნებს. შეცვლილი ტექსტი = **ახალი ბარათი ახალი hash-ით**
    (`revise`) და ისევ ახალი დადასტურება.
  * ერთჯერადობა: მდგომარეობის გადასვლა (proposed → executing → executed) ბლოკირებით და ახლად წაკითხული მონაცემით; განმეორებითი confirm ხელახლა არ ასრულებს,
    მხოლოდ შენახულ შედეგს აბრუნებს. მიმღებზე dedupe-გასაღები (`aiact:<id>:<agent>`) შეტყობინებებს დამატებით იცავს გაორმაგებისგან.
  * უფლებები **ორჯერ** მოწმდება: შეთავაზებისას და შესრულებისას (როლი/გუნდი/კლიენტის ხილვადობა — იგივე წესი, რაც `crm2_api`-ში).
  * შედეგის გადამოწმება: follow-up — წაკითხვით; შეტყობინება — რიგის სტატუსით. „queued“ ≠ „მიიღეს“ — ასე ჩანს და ასე ეწერება.
  ტიპები (v1): `followup_create` (CRM follow-up კლიენტზე), `agent_message` (მენეჯერი/ადმინი → აგენტ(ებ)ი). კლიენტებისთვის შეტყობინება/ჯგუფური გაგზავნა **არ არსებობს**.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
import threading

import ai_model as m
import config
import tab_backend
from ai_model import AiError

log = logging.getLogger("safehome-ai-actions")
_lock = threading.RLock()

SHEET = "AiActions"
HEADERS = ["action_id", "uid", "agent_id", "role", "team", "type", "payload", "payload_hash", "summary", "status", "created_at", "expires_at",
           "decided_at", "result"]
ALL_TABS = [(SHEET, HEADERS, 2000)]
SheetsBackend, MemoryBackend = tab_backend.make(ALL_TABS)
_backend = SheetsBackend()

S_PROPOSED, S_EXECUTING, S_EXECUTED, S_FAILED, S_CANCELLED, S_EXPIRED = "proposed", "executing", "executed", "failed", "cancelled", "expired"
MAX_TEXT, MIN_TEXT = 800, 5
TITLES = {"followup_create": "📌 Follow-up-ის დაგეგმვა", "agent_message": "💬 შეტყობინება აგენტებს"}


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def _s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


def _manager(viewer: dict) -> bool:
    return bool(viewer.get("admin") or viewer.get("role") == "team_lead")


def payload_hash(uid: str, type_: str, payload: dict) -> str:
    return hashlib.sha256(json.dumps([uid, type_, payload], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def _visible_client(viewer: dict, client: dict, agents: list[dict]) -> bool:
    import crm2_api
    chk = crm2_api._scope_checker({"agent_id": viewer.get("agent_id"), "team": viewer.get("team"), "role": viewer.get("role")}, bool(viewer.get("admin")),
                                  lambda a: bool(a) and _s(a.get("role")) == "team_lead", lambda: agents)   # იგივე წესი, რაც /api/crm2-ში (გამეორების გარეშე)
    return bool(client) and client.get("archived") != "yes" and chk(client)


# ====================================================================== ვალიდაცია / ნორმალიზაცია
def _norm_followup(viewer: dict, p: dict, agents: list[dict]) -> tuple[dict, str]:
    import crm2_store
    cid = _s(p.get("client_id"), 40)
    c = crm2_store.get_client(cid) if cid else None
    if c is None or not _visible_client(viewer, c, agents):
        raise AiError("კლიენტი ვერ მოიძებნა ან თქვენთვის მიუწვდომელია", 404, "client_not_found")
    action = _s(p.get("next_action"), 500)
    if len(action) < 3:
        raise AiError("შემდეგი ქმედების ტექსტი სავალდებულოა")
    due = _s(p.get("due_at") or p.get("due_date"), 25)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?", due):
        raise AiError("ვადა: YYYY-MM-DD (ან UTC ISO)")
    try:
        d = datetime.datetime.strptime(due[:10], "%Y-%m-%d").date()
    except ValueError:
        raise AiError("ვადა არასწორი თარიღია") from None
    import crm_time
    if d < crm_time.local_today():
        raise AiError("ვადა წარსულში ვერ იქნება — აირჩიეთ დღევანდელი ან მომავალი თარიღი")
    payload = {"client_id": cid, "due_at": due, "next_action": action}
    summary = f"{_s(c.get('name'), 80) or 'კლიენტი'} · ვადა {due[:10]} · {action}"
    return payload, summary


def _resolve_recipients(viewer: dict, spec, agents: list[dict]) -> list[dict]:
    if not _manager(viewer):
        raise AiError("აგენტებისთვის შეტყობინების გაგზავნა მხოლოდ მენეჯერს/ადმინს შეუძლია", 403, "forbidden")
    active = [a for a in agents if _s(a.get("active", "yes")).lower() not in ("no", "false", "0") and _s(a.get("agent_id")) != _s(viewer.get("agent_id"))]
    if viewer.get("admin"):
        pool = active                                                         # ადმინი: ყველა აქტიური თანამშრომელი
    else:                                                                     # თიმლიდერი: მხოლოდ საკუთარი გუნდის აგენტები (სხვა გუნდი/სხვა თიმლიდერი — არა)
        team = _s(viewer.get("team"))
        pool = [a for a in active if team and _s(a.get("team")) == team and _s(a.get("role")) != "team_lead"]
    if spec in ("team", "all", "all_agents", None, ""):
        chosen = pool
    elif isinstance(spec, (list, tuple)):
        ids = {_s(x, 40) for x in spec}
        chosen = [a for a in pool if _s(a.get("agent_id")) in ids]
        if len(chosen) != len(ids):
            raise AiError("ზოგი მიმღები თქვენი უფლების გარეთაა ან არ არსებობს (მხოლოდ თქვენი გუნდის აქტიური აგენტები)", 403, "recipient_out_of_scope")
    else:
        raise AiError("მიმღებები: team / all / აგენტების სია")
    if not chosen:
        raise AiError("მიმღები აგენტი ვერ მოიძებნა")
    if len(chosen) > config.AI_ACTION_MAX_RECIPIENTS:
        raise AiError(f"ერთ გაგზავნაში მაქსიმუმ {config.AI_ACTION_MAX_RECIPIENTS} მიმღებია")
    return chosen


def _norm_message(viewer: dict, p: dict, agents: list[dict]) -> tuple[dict, str]:
    text = _s(p.get("text"), MAX_TEXT + 1)
    if len(text) < MIN_TEXT:
        raise AiError(f"ტექსტი ძალიან მოკლეა (მინ. {MIN_TEXT} სიმბოლო)")
    if len(text) > MAX_TEXT:
        raise AiError(f"ტექსტი ძალიან გრძელია (მაქს. {MAX_TEXT} სიმბოლო)")
    import ai_privacy as pv
    if pv.redact(text) != text:
        raise AiError("ტექსტში ტელეფონი/ელფოსტა ჩანს — ჯგუფურ შეტყობინებაში პირადი მონაცემი არ იგზავნება; ამოშალეთ")
    chosen = _resolve_recipients(viewer, p.get("recipients"), agents)
    ids = sorted(_s(a.get("agent_id")) for a in chosen)
    payload = {"recipients": ids, "text": text}
    return payload, f"{len(ids)} აგენტი · {text[:90]}"


NORMALIZERS = {"followup_create": _norm_followup, "agent_message": _norm_message}


# ====================================================================== ბარათი
def card(row: dict, agents: list[dict] | None = None) -> dict:
    """UI-სთვის: რას აპირებს, ვის ეხება, რა ტექსტი/ცვლილება, რა შედეგს ელოდება. (მიმღებთა სახელები — სერვერზე, ნამდვილი.)"""
    p = json.loads(row.get("payload") or "{}")
    typ = _s(row.get("type"))
    by_id = {str(a.get("agent_id")): a for a in (agents or [])}
    base = {"action_id": row.get("action_id"), "type": typ, "title": TITLES.get(typ, typ), "hash": row.get("payload_hash"), "status": row.get("status"),
            "expires_at": row.get("expires_at"), "result": json.loads(row.get("result") or "null")}
    if typ == "followup_create":
        import crm2_store
        c = crm2_store.get_client(p.get("client_id")) or {}
        base.update(who=_s(c.get("name"), 80) or "კლიენტი", client_status=_s(c.get("status")),
                    uses=["კლიენტის ბარათი (სახელი, სტატუსი)", "თქვენი უფლებები"], editable={"due_at": p["due_at"][:10], "next_action": p["next_action"]},
                    what=f"CRM-ში დაემატება follow-up: „{p['next_action']}“, ვადა {p['due_at'][:10]}.",
                    effect="ვადის გადაცილებისას SAIRO შეგახსენებთ, ხოლო დაგვიანებისას მენეჯერს ეცნობება. კლიენტს არაფერი გაეგზავნება.",
                    external=False)
    else:
        names = [_s(by_id.get(a, {}).get("name")) or a for a in p.get("recipients", [])]
        base.update(who=f"{len(names)} აგენტი: " + ", ".join(names[:12]) + (f" და კიდევ {len(names) - 12}" if len(names) > 12 else ""),
                    recipients=names, uses=["აგენტების ჩამონათვალი თქვენი უფლებით", "თქვენ მიერ დადასტურებული ტექსტი"], editable={"text": p["text"]},
                    what=f"თითოეულ მათგანს Telegram-ში გაეგზავნება ტექსტი:\n„{p['text']}“",
                    effect="შეტყობინება დადგება რიგში და გაიგზავნება; „მიღებულია“ მხოლოდ Telegram-ის პასუხით დადასტურდება. კლიენტებს არაფერი გაეგზავნება.",
                    external=True)
    return base


# ====================================================================== შეთავაზება / დადასტურება
def _rows(fresh: bool = False) -> list[dict]:
    return _backend.read(SHEET, fresh=fresh)


def _get(action_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in _rows(fresh) if _s(r.get("action_id")) == _s(action_id)), None)


def propose(viewer: dict, type_: str, payload: dict, agents: list[dict], now: datetime.datetime | None = None) -> dict:
    """გვერდითი ეფექტის გარეშე: ვალიდაცია + ჩანაწერი (status=proposed) + ბარათი."""
    if type_ not in NORMALIZERS:
        raise AiError("უცნობი მოქმედების ტიპი", 400, "unknown_type")
    norm, summary = NORMALIZERS[type_](viewer, payload or {}, agents)
    now = now or m.now_dt()
    uid = _s(viewer.get("uid"), 40)
    row = {"action_id": m.new_id("act"), "uid": uid, "agent_id": _s(viewer.get("agent_id"), 40), "role": _s(viewer.get("role"), 20), "team": _s(viewer.get("team"), 80),
           "type": type_, "payload": json.dumps(norm, ensure_ascii=False, sort_keys=True), "payload_hash": payload_hash(uid, type_, norm), "summary": summary[:300],
           "status": S_PROPOSED, "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
           "expires_at": (now + datetime.timedelta(minutes=config.AI_ACTION_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S"), "decided_at": "", "result": ""}
    with _lock:
        _backend.append_many(SHEET, HEADERS, [row])
    return card(row, agents)


def _owned(viewer: dict, action_id: str, fresh: bool = True) -> dict:
    r = _get(action_id, fresh)
    if r is None or _s(r.get("uid")) != _s(viewer.get("uid")):
        raise AiError("მოქმედება ვერ მოიძებნა", 404, "not_found")                 # სხვისი — არსებობას არ ვამხელთ
    return r


def cancel(viewer: dict, action_id: str, now: datetime.datetime | None = None) -> dict:
    with _lock:
        r = _owned(viewer, action_id)
        if _s(r.get("status")) != S_PROPOSED:
            raise AiError("ამ მოქმედების გაუქმება უკვე შეუძლებელია", 409, "not_cancellable")
        _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": S_CANCELLED, "decided_at": (now or m.now_dt()).strftime("%Y-%m-%d %H:%M:%S")}})
        return {"ok": True, "status": S_CANCELLED}


def revise(viewer: dict, action_id: str, changes: dict, agents: list[dict], now: datetime.datetime | None = None) -> dict:
    """შეცვლილი ტექსტი/თარიღი -> ძველი უქმდება, **ახალი ბარათი ახალი hash-ით** (ახალი დადასტურება საჭიროა)."""
    with _lock:
        r = _owned(viewer, action_id)
        if _s(r.get("status")) != S_PROPOSED:
            raise AiError("შეცვლა შესაძლებელია მხოლოდ დადასტურებამდე", 409, "not_revisable")
        p = json.loads(r.get("payload") or "{}")
        allowed = {"followup_create": ("due_at", "next_action"), "agent_message": ("text", "recipients")}[_s(r.get("type"))]
        merged = dict(p, **{k: v for k, v in (changes or {}).items() if k in allowed})
        new = propose(viewer, _s(r.get("type")), merged, agents, now)
        _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": S_CANCELLED, "decided_at": (now or m.now_dt()).strftime("%Y-%m-%d %H:%M:%S"), "result": json.dumps({"superseded_by": new["action_id"]})}})
        return new


def list_mine(viewer: dict, agents: list[dict], now: datetime.datetime | None = None) -> list[dict]:
    now = (now or m.now_dt()).strftime("%Y-%m-%d %H:%M:%S")
    return [card(r, agents) for r in _rows() if _s(r.get("uid")) == _s(viewer.get("uid")) and _s(r.get("status")) == S_PROPOSED and _s(r.get("expires_at")) > now][-10:]


def _exec_followup(viewer: dict, row: dict, p: dict, agents: list[dict], deps: dict) -> dict:
    import crm2_store
    c = crm2_store.get_client(p["client_id"])
    if c is None or not _visible_client(viewer, c, agents):                          # უფლება შესრულებისას ხელახლა
        raise AiError("კლიენტი ვერ მოიძებნა ან თქვენთვის მიუწვდომელია", 404, "client_not_found")
    owner = _s(viewer.get("agent_id") or c.get("assigned_agent_id"), 40)
    owner_name = _s(viewer.get("name") or c.get("assigned_agent_name"), 80)
    fid = crm2_store.create_followup(p["client_id"], owner, p["due_at"], p["next_action"], agent_name=owner_name, by=_s(viewer.get("agent_id") or "admin"))
    crm2_store.add_activity("client", p["client_id"], "system", f"Follow-up დაგეგმილია (SAIRO, მომხმარებლის დადასტურებით): {p['next_action']}",
                            agent_id=owner, agent_name=owner_name, source_ref=f"followup:{fid}")
    verified = any(f.get("followup_id") == fid and f.get("status") == "open" for f in crm2_store.list_followups(status=None))
    return {"followup_id": fid, "verified": verified, "text": "Follow-up დაემატა CRM-ში" + ("" if verified else " (ჩანაწერის გადამოწმება ვერ მოხერხდა)")}


def _exec_message(viewer: dict, row: dict, p: dict, agents: list[dict], deps: dict) -> dict:
    chosen = _resolve_recipients(viewer, p["recipients"], agents)                   # უფლება/აქტიურობა ხელახლა
    ok_ids = {_s(a.get("agent_id")) for a in chosen}
    today = m.today_str()
    sent_today = sum(1 for r in _rows(True) if _s(r.get("uid")) == _s(viewer.get("uid")) and _s(r.get("type")) == "agent_message" and _s(r.get("status")) == S_EXECUTED
                     and _s(r.get("decided_at"))[:10] == today)
    if sent_today >= config.AI_ACTION_MAX_MESSAGES_PER_DAY:
        raise AiError(f"დღეში მაქსიმუმ {config.AI_ACTION_MAX_MESSAGES_PER_DAY} ჯგუფური გაგზავნაა", 429, "daily_message_limit")
    sender = _s(viewer.get("name")) or "მენეჯერი"
    text = f"💬 {sender}:\n{p['text']}"
    per, queued = {}, 0
    for a in agents:
        aid = _s(a.get("agent_id"))
        if aid not in set(p["recipients"]):
            continue
        if aid not in ok_ids:
            per[aid] = "out_of_scope"
            continue
        try:
            chat = int(str(a.get("telegram_chat_id") or "").strip())
        except ValueError:
            per[aid] = "no_telegram"
            continue
        res = deps["send"](chat, text, f"aiact:{row['action_id']}:{aid}")
        per[aid] = str(res)
        queued += 1 if str(res) in ("queued", "sent") else 0
    return {"recipients": len(p["recipients"]), "queued_or_sent": queued, "per_agent": per,
            "text": f"{queued} შეტყობინება რიგშია/გაიგზავნა; ჩავარდა/ვერ მიდის: {len(p['recipients']) - queued}. „მიღებულია“ მხოლოდ Telegram-ის პასუხით დადასტურდება."}


EXECUTORS = {"followup_create": _exec_followup, "agent_message": _exec_message}


def confirm(viewer: dict, action_id: str, expect_hash: str, agents: list[dict], deps: dict, now: datetime.datetime | None = None) -> dict:
    """მხოლოდ მფლობელის მოთხოვნით. განმეორებითი confirm — შენახული შედეგი (ხელახლა არ სრულდება). hash ≠ ბარათის hash -> უარი."""
    now = now or m.now_dt()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        r = _owned(viewer, action_id)
        st = _s(r.get("status"))
        if st == S_EXECUTED:
            return {"ok": True, "already": True, "status": S_EXECUTED, "result": json.loads(r.get("result") or "null")}
        if st == S_EXECUTING:
            raise AiError("მოქმედება ახლა სრულდება", 409, "in_progress")
        if st != S_PROPOSED:
            raise AiError(f"მოქმედება უკვე {st}", 409, "not_confirmable")
        if _s(r.get("expires_at")) <= ts:
            _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": S_EXPIRED, "decided_at": ts}})
            raise AiError("დადასტურების ვადა გავიდა — სთხოვეთ SAIRO-ს ხელახლა", 410, "expired")
        if _s(expect_hash) != _s(r.get("payload_hash")):
            raise AiError("დადასტურება სხვა შინაარსზეა — გახსენით ბარათი ხელახლა", 409, "hash_mismatch")
        p = json.loads(r.get("payload") or "{}")
        if payload_hash(_s(r.get("uid")), _s(r.get("type")), p) != _s(r.get("payload_hash")):
            raise AiError("ჩანაწერი შეცვლილია — შესრულება უარყოფილია", 409, "tampered")
        _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": S_EXECUTING, "decided_at": ts}})       # ერთჯერადობა: პირველი, ვინც დაიკავა
    try:
        res = EXECUTORS[_s(r.get("type"))](viewer, r, p, agents, deps)
        status = S_EXECUTED if (res.get("queued_or_sent", 1) > 0) else S_FAILED
    except AiError as e:
        with _lock:
            _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": S_FAILED, "result": json.dumps({"error": str(e)}, ensure_ascii=False)}})
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("AI action %s ჩავარდა", action_id)
        with _lock:
            _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": S_FAILED, "result": json.dumps({"error": type(e).__name__}, ensure_ascii=False)}})
        raise AiError("შესრულება ვერ მოხერხდა — სცადეთ ხელახლა ახალი ბარათით", 500, "exec_failed") from None
    with _lock:
        _backend.update_many(SHEET, HEADERS, {r["action_id"]: {"status": status, "result": json.dumps(res, ensure_ascii=False)}})
    return {"ok": status == S_EXECUTED, "status": status, "result": res}
