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
TITLES = {"followup_create": "📌 Follow-up-ის დაგეგმვა", "agent_message": "💬 შეტყობინება აგენტებს", "recruit_update": "🧑‍💼 კადრები — ჩანაწერის განახლება"}


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


def _recruit_perm(viewer: dict) -> None:
    import ai_tools_ext
    if not ai_tools_ext.perms(viewer)["recruit_edit"]:
        raise AiError("კადრების ჩანაწერის შეცვლა მხოლოდ დირექტორს/პასუხისმგებელ მენეჯერს შეუძლია", 403, "forbidden")


def _recruit_pre(p: dict) -> dict:
    import recruit_store as rs
    try:
        return rs.preview_update(_s(p.get("candidate_id"), 40), p.get("changes") or {})
    except rs.RecruitError as e:
        raise AiError(str(e), e.status, getattr(e, "code", "") or "recruit") from None
    except ValueError as e:
        raise AiError(str(e)) from None


def _norm_recruit(viewer: dict, p: dict, agents: list[dict]) -> tuple[dict, str]:
    _recruit_perm(viewer)
    cid = _s(p.get("candidate_id"), 40)
    raw = p.get("changes") if isinstance(p.get("changes"), dict) else {}
    if not cid or not raw:
        raise AiError("კანდიდატი და შესაცვლელი ველები სავალდებულოა")
    pre = _recruit_pre({"candidate_id": cid, "changes": raw})
    if not pre["diffs"]:
        raise AiError("ამ მნიშვნელობებით ჩანაწერში არაფერი იცვლება")
    payload = {"candidate_id": cid, "changes": pre["clean"], "note": _s(p.get("note"), 300)}
    return payload, f"{pre['name']} · " + "; ".join(f"{d['label']}: {d['new']}" for d in pre["diffs"][:4])


NORMALIZERS = {"followup_create": _norm_followup, "agent_message": _norm_message, "recruit_update": _norm_recruit}


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
    elif typ.startswith("tg_"):
        base.update(_card_tg(typ, p, agents))
    elif typ == "recruit_update":
        try:
            pre = _recruit_pre(p)
        except AiError:
            pre = {"name": "კანდიდატი", "diffs": [], "stage_before": "", "stage_after": "", "closing": False}
        import recruit_model as rm
        base.update(who=pre["name"], uses=["კანდიდატის ჩანაწერი (კადრები)", "თქვენი უფლებები"], editable={}, diffs=pre["diffs"],
                    stage_after=rm.STAGES.get(pre["stage_after"], pre["stage_after"]), closing=pre["closing"],
                    what="ჩანაწერში შეიცვლება: " + ("; ".join(f"{d['label']}: {d['old']} → {d['new']}" for d in pre["diffs"]) or "—") + (f". ეტაპი გახდება: {rm.STAGES.get(pre['stage_after'], pre['stage_after'])}" if pre["stage_after"] != pre["stage_before"] else ""),
                    effect="ცვლილება ჩაიწერება კადრების ისტორიაში თქვენი სახელით („SAIRO-ს მეშვეობით“)." + (" კანდიდატი დაიხურება." if pre["closing"] else "") + " კანდიდატს არაფერი გაეგზავნება.",
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
        allowed = {"followup_create": ("due_at", "next_action"), "agent_message": ("text", "recipients"), "recruit_update": ("note",)}.get(_s(r.get("type")), ())
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


def _exec_recruit(viewer: dict, row: dict, p: dict, agents: list[dict], deps: dict) -> dict:
    import recruit_store as rs
    _recruit_perm(viewer)                                                            # უფლება შესრულებისას ხელახლა
    by = {"name": _s(viewer.get("name")) or "დირექტორი", "agent_id": _s(viewer.get("agent_id"))}
    note = ("SAIRO-ს მეშვეობით, დადასტურებით" + (": " + p["note"] if p.get("note") else ""))[:500]
    try:
        r = rs.update(p["candidate_id"], p["changes"], by, comment=note)
    except rs.RecruitError as e:
        raise AiError(str(e), e.status, getattr(e, "code", "") or "recruit") from None
    except ValueError as e:
        raise AiError(str(e)) from None
    verified = all(_s(r.get(k)) == _s(v) for k, v in p["changes"].items() if k not in ("phone_raw",))
    return {"candidate_id": p["candidate_id"], "verified": verified, "stage": rs.m.STAGES.get(_s(r.get("stage")), _s(r.get("stage"))),
            "text": "ჩანაწერი განახლდა" + ("" if verified else " (გადამოწმებისას ზოგი ველი სხვაგვარია — გახსენით კანდიდატის ბარათი)")}


EXECUTORS = {"followup_create": _exec_followup, "agent_message": _exec_message, "recruit_update": _exec_recruit}


# ====================================================================== Telegram ლიდები / რიგი (SAIRO ამზადებს, მომხმარებელი ადასტურებს)
TITLES.update({"tg_assign": "📣 Telegram ლიდის გადაბარება აგენტზე", "tg_lead_result": "📞 Telegram ლიდი — შედეგი / დადასტურება", "tg_queue_decide": "📥 Telegram რიგი — დამტკიცება/უარყოფა"})
TG_RESULT_ACTIONS = {"ack": "ვადასტურებ (მივიღე)", "contacted": "დავუკავშირდი", "waiting": "მოგვიანებით"}


def _tg_flow():
    import tgnet_api
    f = getattr(tgnet_api, "FLOW", None)
    if not f:
        raise AiError("Telegram ქსელი ამ სერვერზე ჩართული არ არის", 409, "tgnet_off")
    return f()


def _tg_lead(lead_id: str) -> dict:
    import tgnet_store as ts
    r = next((x for x in ts.list_lead_rows(fresh=True) if _s(x.get("lead_id")) == _s(lead_id) and _s(x.get("kind")) == "lead"), None)
    if not r or _s(r.get("status")) == "closed":
        raise AiError("ლიდი ვერ მოიძებნა ან დახურულია", 404, "lead_not_found")
    return r


def _tg_listing(r: dict) -> dict:
    import tgnet_publisher as tp
    return (tp.get_listing(r.get("listing_key")) if _s(r.get("listing_key")) else None) or {}


def _norm_tg_assign(viewer: dict, p: dict, agents: list[dict]) -> tuple[dict, str]:
    if not _manager(viewer):
        raise AiError("ლიდის გადაბარება მხოლოდ მენეჯერს/დირექტორს შეუძლია", 403, "forbidden")
    r = _tg_lead(p.get("lead_id"))
    if _s(r.get("status")) not in ("new", "assigned", "acknowledged", "waiting", "contacted"):
        raise AiError("ამ ლიდის გადაბარება შეუძლებელია")
    lst = _tg_listing(r)
    ag = next((a for a in agents if _s(a.get("agent_id")) == _s(p.get("agent_id"), 40) and _s(a.get("active", "yes")).lower() not in ("no", "false", "0")), None)
    if not ag:
        raise AiError("აგენტი ვერ მოიძებნა ან არააქტიურია", 404, "agent_not_found")
    if not viewer.get("admin"):
        team = _s(viewer.get("team"))
        if _s(lst.get("team")) and _s(lst.get("team")) != team:
            raise AiError("ეს ლიდი სხვა გუნდის ბინაზეა — მხოლოდ თქვენი გუნდის ლიდებს გადაბარებთ", 403, "out_of_scope")
        if _s(ag.get("team")) != team:
            raise AiError("აგენტი თქვენი გუნდიდან არ არის", 403, "out_of_scope")
    if _s(r.get("assigned_agent_id")) == _s(ag.get("agent_id")) and _s(r.get("status")) != "new":
        raise AiError("ლიდი უკვე ამ აგენტზეა")
    payload = {"lead_id": _s(r.get("lead_id")), "agent_id": _s(ag.get("agent_id"))}
    return payload, f"{_s(r.get('tg_name'), 60) or 'კლიენტი'} → {_s(ag.get('name'), 60)}"


def _norm_tg_result(viewer: dict, p: dict, agents: list[dict]) -> tuple[dict, str]:
    import tgnet_leads as tl
    import tgnet_store as ts
    r = _tg_lead(p.get("lead_id"))
    mine = _s(r.get("assigned_agent_id")) and _s(r.get("assigned_agent_id")) == _s(viewer.get("agent_id"))
    if not mine and not _manager(viewer):
        raise AiError("ეს ლიდი თქვენზე არ არის", 403, "forbidden")
    act = _s(p.get("action"), 20)
    if act not in TG_RESULT_ACTIONS:
        raise AiError("მოქმედება: ack | contacted | waiting")
    note = _s(p.get("note"), 300)
    due = ""
    if act in ("contacted", "waiting"):
        d = tl._parse_local(p.get("follow_up_at"))
        if not d:
            raise AiError("Follow-up სავალდებულოა: მიუთითეთ შემდეგი კონტაქტის თარიღი და საათი (YYYY-MM-DD HH:MM)", 400, "followup_required")
        if d < tl._parse_local(ts.now_str()):
            raise AiError("Follow-up წარსულში ვერ იქნება", 400, "followup_past")
        due = d.strftime("%Y-%m-%d %H:%M")
        if act == "contacted" and len(note) < 3:
            raise AiError("მოკლე შენიშვნა სავალდებულოა (რა შეთანხმდით)", 400, "note_required")
    payload = {"lead_id": _s(r.get("lead_id")), "action": act, "follow_up_at": due, "note": note}
    return payload, f"{_s(r.get('tg_name'), 60) or 'კლიენტი'} · {TG_RESULT_ACTIONS[act]}" + (f" · follow-up {due}" if due else "")


def _norm_tg_queue(viewer: dict, p: dict, agents: list[dict]) -> tuple[dict, str]:
    import tgnet_store as ts
    if not viewer.get("admin"):
        raise AiError("რიგის დამტკიცება მხოლოდ დირექტორს შეუძლია", 403, "forbidden")
    act = _s(p.get("action"), 20)
    if act not in ("approve", "reject"):
        raise AiError("მოქმედება: approve | reject")
    want = [_s(k, 40) for k in (p.get("keys") or []) if _s(k, 40)]
    if not want or len(want) > 50:
        raise AiError("მიუთითეთ 1–50 განცხადება")
    known = {g["listing_key"] for g in ts.queue_groups(limit=None)}
    missing = [k for k in want if k not in known]
    if missing:
        raise AiError("რიგში ვერ მოიძებნა: " + ", ".join(missing[:5]), 404, "not_in_queue")
    keys = sorted(set(want))
    return {"keys": keys, "action": act}, f"{len(keys)} განცხადება · {'დამტკიცება' if act == 'approve' else 'უარყოფა'}"


def _card_tg(typ: str, p: dict, agents: list[dict]) -> dict:
    import tgnet_store as ts
    by_id = {str(a.get("agent_id")): a for a in (agents or [])}
    if typ == "tg_queue_decide":
        groups = {g["listing_key"]: g for g in ts.queue_groups(limit=None)}
        lines = [f"• {k} — {(groups.get(k) or {}).get('summary') or ''}".rstrip(" —") for k in p["keys"][:12]]
        return {"who": f"{len(p['keys'])} განცხადება", "uses": ["გამოსაქვეყნებელი რიგი"], "editable": {},
                "what": ("დამტკიცდება და ჩართულ არხებში თავისით გავა (საათების/ინტერვალის წესით):\n" if p["action"] == "approve" else "უარყოფილი იქნება (არხებში არ გავა):\n") + "\n".join(lines),
                "effect": "ცვლილება ჩაიწერება რიგში თქვენი სახელით. გამოქვეყნებულ პოსტებს არ ეხება.", "external": p["action"] == "approve"}
    try:
        r = _tg_lead(p["lead_id"])
    except AiError:
        r = {}
    name = _s(r.get("tg_name"), 60) or "კლიენტი"
    lst = _tg_listing(r) if r else {}
    summ = ts.listing_summary(lst) if lst else "ზოგადი მოთხოვნა"
    if typ == "tg_assign":
        ag = by_id.get(p["agent_id"], {})
        return {"who": f"{name} · {summ}", "uses": ["Telegram ლიდი", "აგენტების სია თქვენი უფლებით"], "editable": {},
                "what": f"ლიდი გადაბარდება აგენტს: {_s(ag.get('name')) or p['agent_id']}" + (" (ბინის აგენტი)" if _s(lst.get("agent_id")) == p["agent_id"] else ""),
                "effect": "აგენტს Telegram-ში მიუვა შეტყობინება „👤 კლიენტის ნახვა“ ღილაკით; დადასტურებამდე შეხსენება განმეორდება, თქვენ კი უკუკავშირი მოგივათ. კლიენტს არაფერი ეგზავნება.",
                "external": True}
    return {"who": f"{name} · {summ}", "uses": ["თქვენი Telegram ლიდი"], "editable": {},
            "what": f"სტატუსი: {TG_RESULT_ACTIONS[p['action']]}" + (f"; follow-up {p['follow_up_at']} (CRM-ში შეიქმნება)" if p.get("follow_up_at") else "") + (f"; შენიშვნა: {p['note']}" if p.get("note") else ""),
            "effect": "მენეჯერს უკუკავშირი მიუვა; follow-up-ის დროს შეგახსენებთ. კლიენტს არაფერი ეგზავნება.", "external": False}


def _exec_tg_assign(viewer: dict, row: dict, p: dict, agents: list[dict], deps: dict) -> dict:
    _norm_tg_assign(viewer, p, agents)                                               # უფლება/მდგომარეობა შესრულებისას ხელახლა
    res = _tg_flow().assign(p["lead_id"], p["agent_id"], by=_s(viewer.get("name")) or "მენეჯერი (SAIRO)")
    return {"lead_id": p["lead_id"], "agent_id": res["agent_id"], "text": f"ლიდი გადაბარდა: {res['agent_name']} — შეტყობინება გაიგზავნა"}


def _exec_tg_result(viewer: dict, row: dict, p: dict, agents: list[dict], deps: dict) -> dict:
    import tgnet_store as ts
    r = _tg_lead(p["lead_id"])
    mgr = _manager(viewer) and _s(r.get("assigned_agent_id")) != _s(viewer.get("agent_id"))
    try:
        res = _tg_flow().agent_action(p["lead_id"], _s(viewer.get("agent_id")), p["action"], p.get("note", ""), p.get("follow_up_at", ""), manager=mgr)
    except ts.TgnetError as e:
        raise AiError(str(e), e.status, getattr(e, "code", "") or "tgnet") from None
    return {"lead_id": p["lead_id"], "status": res.get("status"), "text": f"ჩაიწერა: {TG_RESULT_ACTIONS[p['action']]}" + (f" · follow-up {res.get('follow_up_at')}" if res.get("follow_up_at") else "")}


def _exec_tg_queue(viewer: dict, row: dict, p: dict, agents: list[dict], deps: dict) -> dict:
    import tgnet_store as ts
    if not viewer.get("admin"):
        raise AiError("რიგის დამტკიცება მხოლოდ დირექტორს შეუძლია", 403, "forbidden")
    try:
        res = ts.decide_many(p["keys"], p["action"], by=_s(viewer.get("name")) or "დირექტორი (SAIRO)")
    except ts.TgnetError as e:
        raise AiError(str(e), e.status, getattr(e, "code", "") or "tgnet") from None
    return dict(res, text=f"{'დამტკიცდა' if p['action'] == 'approve' else 'უარყოფილია'}: {res.get('listings', res.get('changed', len(p['keys'])))}")


NORMALIZERS.update({"tg_assign": _norm_tg_assign, "tg_lead_result": _norm_tg_result, "tg_queue_decide": _norm_tg_queue})
EXECUTORS.update({"tg_assign": _exec_tg_assign, "tg_lead_result": _exec_tg_result, "tg_queue_decide": _exec_tg_queue})


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
