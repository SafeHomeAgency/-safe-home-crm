"""
SAIRO — Lead Protection Engine („კლიენტი არ უნდა დაიკარგოს“).

რას აკეთებს (წესებზე დაფუძნებული, LLM-ის გარეშე — ამიტომ უფასოა, განმეორებადია და ტესტირებადია):
  1. არსებული მონაცემებიდან აღმოაჩენს რისკებს: ვადაგადაცილებული CRM follow-up; აქტიური კლიენტი N დღეა უაქტივობაა და შემდეგი ნაბიჯი დაუგეგმავია;
     შეხვედრის შედეგი ჩაუწერელია; თანამშრომლობის მოთხოვნა უპასუხოა; მინიჭებული კლიენტი დაუდასტურებელია/შეხვედრა არ დაუგეგმეს
     (ბოლო ოთხი — არსებული `hubmeet_store.attention_items`-იდან, დუბლირების გარეშე); გამორთული/მიუწვდომელი აგენტის კლიენტები.
  2. ყოველ რისკს აქვს **მიზეზი ფაქტებით** (რა ვადაა, რამდენი საათია, ვინ), რეკომენდებული შემდეგი ნაბიჯი და დონე (low/medium/high). „ფაქტი“ და
     „AI-ის შეფასება“ არ ირევა: ეს ძრავა მხოლოდ ფაქტებს ადგენს (`assessed_by="rules"`); SAIRO-ს კომენტარი ცალკეა და ასეც მოინიშნება.
  3. აგენტს შეხსენება (არსებული Telegram არხით), მენეჯერს ესკალაცია, ყოველდღიური ანგარიში — **მდგომარეობა ცხრილში `LeadGuardLog` ინახება**
     (არა მეხსიერებაში): Redeploy/რესტარტი შეტყობინებებს არ აორმაგებს. ერთი საქმე: მაქს. N შეხსენება (ინტერვალით), ერთი ესკალაცია (+ერთი, თუ „მაღალი“ გახდა).
     ღამით (22:00–08:00) არ იგზავნება. ერთ აგენტზე ერთი ჯამური შეტყობინება ციკლში (არა ერთი კლიენტზე ერთი).
  4. მონაცემის წყარო ვერ იკითხა -> ეს ღიად ჩანს (`data_errors`), ამ წყაროს საქმეებს „გადაწყვეტილად“ არ ვნიშნავთ და ვერ ვაგზავნით.
არ ამტკიცებს, რომ ყველა დაკარგულ კლიენტს გამორიცხავს: მისი მიზანია რისკების ადრეული აღმოჩენა და გაზომვადი შემცირება.
"""

from __future__ import annotations

import datetime
import logging
import threading

import config
import crm_time
import tab_backend

log = logging.getLogger("safehome-leadguard")
_lock = threading.RLock()

SHEET = "LeadGuardLog"
HEADERS = ["guard_key", "kind", "entity_id", "agent_id", "team", "first_seen", "level", "remind_count", "last_remind_at",
           "escalated_at", "escalated_level", "status", "resolved_at", "last_reason"]
ALL_TABS = [(SHEET, HEADERS, 3000)]
SheetsBackend, MemoryBackend = tab_backend.make(ALL_TABS)
_backend = SheetsBackend()

KINDS = {
    "followup_overdue": "ვადაგადაცილებული follow-up",
    "no_next_action": "შემდეგი ნაბიჯი დაუგეგმავია",
    "outcome_missing": "შეხვედრის შედეგი ჩაუწერელია",
    "pending_undecided": "თანამშრომლობის მოთხოვნა უპასუხოა",
    "lead_unseen": "კლიენტი დაუდასტურებელია",
    "lead_no_meeting": "კლიენტს შეხვედრა არ დაუგეგმეს",
    "agent_inactive": "აგენტი გამორთულია, კლიენტი მიუჩინარებელია",
}
ACTIVE_CLIENT_STATUSES = ("new", "contacted", "viewing", "negotiation")
LEVEL_EMOJI = {"high": "🔴", "medium": "🟠", "low": "🟡"}
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}
DISCLAIMER = "რისკი = წესებით დადგენილი ფაქტი (მიზეზი მითითებულია). ეს ძრავა არ ჰპირდება, რომ ყველა დაკარგულ კლიენტს გამორიცხავს — ის ადრე აჩვენებს რისკს."


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def _s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


def _active(a: dict) -> bool:
    return _s(a.get("active", "yes")).lower() not in ("no", "false", "0")


def _chat(a: dict | None) -> int | None:
    try:
        return int(str((a or {}).get("telegram_chat_id") or "").strip())
    except ValueError:
        return None


def _now() -> datetime.datetime:
    return crm_time.local_now()


def _fmt_h(h: float) -> str:
    return f"{int(h)} სთ" if h < 48 else f"{int(h // 24)} დღე"


def in_quiet_hours(now: datetime.datetime) -> bool:
    a, b, h = config.LEAD_GUARD_QUIET_FROM, config.LEAD_GUARD_QUIET_TO, now.hour
    return (h >= a or h < b) if a > b else (a <= h < b)


def _lvl(hours: float, mid: float, high: float) -> str:
    return "high" if hours >= high else ("medium" if hours >= mid else "low")


def _label(v: str) -> str:
    import ai_privacy
    return ai_privacy.redact(_s(v, 80)) or "კლიენტი"


# ====================================================================== მონაცემების შეგროვება
def collect(now: datetime.datetime | None = None) -> dict:
    """ყველა წყარო წაკითხვა-მხოლოდ რეჟიმში. წყაროს ჩავარდნა -> `errors`-ში (და არა ჩუმად „რისკი არ არის“)."""
    import hubmeet_store
    import sheets
    now = now or _now()
    data: dict = {"errors": [], "agents": [], "tasks": [], "followups": None, "clients": None, "hub_rows": None, "attention": None}
    try:
        data["agents"] = sheets.get_agents()
    except Exception:  # noqa: BLE001
        log.exception("LeadGuard: აგენტების წაკითხვა ვერ მოხერხდა")
        data["errors"].append("agents")
        return data
    try:
        data["tasks"] = sheets.get_tasks()
    except Exception:  # noqa: BLE001
        log.exception("LeadGuard: დავალებების წაკითხვა ვერ მოხერხდა")
        data["errors"].append("tasks")
    try:
        import crm2_store
        data["followups"] = crm2_store.list_followups(status=None)
        data["clients"] = crm2_store.list_clients()
    except Exception:  # noqa: BLE001
        log.exception("LeadGuard: CRM2 (follow-up/კლიენტები) წაკითხვა ვერ მოხერხდა")
        data["errors"].append("crm2")
        data["followups"] = data["clients"] = None
    try:
        data["hub_rows"] = hubmeet_store.all_rows()
        if "tasks" not in data["errors"]:
            data["attention"] = hubmeet_store.attention_items({"admin": True}, data["tasks"], None, now.replace(tzinfo=None))
    except Exception:  # noqa: BLE001
        log.exception("LeadGuard: Property Hub-ის შეხვედრების წაკითხვა ვერ მოხერხდა")
        data["errors"].append("hub")
    return data


# ====================================================================== რისკების აღმოჩენა (წმინდა ფუნქცია)
NEXT_STEP = {
    "followup_overdue": "დაურეკეთ კლიენტს დღესვე; შემდეგ დახურეთ follow-up ან დაუნიშნეთ ახალი თარიღი.",
    "no_next_action": "დაწერეთ/დაურეკეთ კლიენტს და CRM-ში დაგეგმეთ შემდეგი ნაბიჯი (follow-up).",
    "outcome_missing": "ჩაწერეთ შეხვედრის შედეგი (ჩატარდა / არ მოვიდა) და დაგეგმეთ შემდეგი ნაბიჯი.",
    "pending_undecided": "მფლობელმა აგენტმა დაადასტუროს ან უარყოს თანამშრომლობის მოთხოვნა.",
    "lead_unseen": "დაადასტურეთ კლიენტის მიღება Telegram-ში ან Mini App-ში.",
    "lead_no_meeting": "დაუკავშირდით კლიენტს და დაუგეგმეთ შეხვედრა/ჩვენება.",
    "agent_inactive": "მენეჯერმა გადაანაწილოს კლიენტი აქტიურ აგენტზე.",
}


def _risk(kind, entity_id, agent, level, age_h, reason, label="", facts=None, notify=True, escalate_now=False, extra_team="", source="crm"):
    team = _s((agent or {}).get("team")) or extra_team
    import ai_privacy
    reason = ai_privacy.redact(reason)                                      # ტელეფონი რისკის ტექსტში არასდროს ხვდება (არსებული სიგნალის ტექსტშიც კი)
    facts = [ai_privacy.redact(x) for x in (facts or [])]
    return {"key": f"{kind}:{entity_id}", "kind": kind, "kind_label": KINDS.get(kind, kind), "entity_id": _s(entity_id, 60), "client_label": _label(label),
            "agent_id": _s((agent or {}).get("agent_id")), "agent_name": _s((agent or {}).get("name")), "team": team, "level": level,
            "age_hours": int(age_h), "reason": reason, "facts": facts, "next_step": NEXT_STEP.get(kind, ""), "source": source,
            "assessed_by": "rules", "notify_agent": notify, "escalate_now": escalate_now}


def detect(now: datetime.datetime, data: dict) -> tuple[list[dict], list[dict]]:
    """აბრუნებს (risks, data_gaps). now — თბილისის aware დრო."""
    agents = {str(a.get("agent_id")): a for a in data.get("agents", [])}
    clients = {c.get("client_id"): c for c in (data.get("clients") or [])}
    risks: list[dict] = []
    gaps: list[dict] = []
    cfg_mid, cfg_high = config.LEAD_GUARD_ESCALATE_AFTER_H, config.LEAD_GUARD_HIGH_AFTER_H

    def owner_flags(agent_id):
        a = agents.get(str(agent_id))
        if a is not None and not _active(a):
            return a, False, True                      # აგენტი გამორთულია: შეხსენება ვერ მივა, მაგრამ ესკალაცია მაშინვე
        return a, True, False

    # ---- 1) CRM follow-up-ები
    fus = data.get("followups")
    if fus is not None:
        open_by_client: dict[str, int] = {}
        late_closed: dict[str, int] = {}
        for f in fus:
            cid = f.get("client_id")
            if f.get("status") == "open":
                open_by_client[cid] = open_by_client.get(cid, 0) + 1
            elif f.get("status") == "done":
                due, done = crm_time.utc_iso_to_local(f.get("due_at")), crm_time.utc_iso_to_local(f.get("done_at"))
                if due and done and (done - due).total_seconds() > 24 * 3600 and (now - done).days <= 30:
                    late_closed[cid] = late_closed.get(cid, 0) + 1
        for f in fus:
            if f.get("status") != "open":
                continue
            c = clients.get(f.get("client_id"))
            if c is None or c.get("archived") == "yes" or _s(c.get("status")) in ("won", "lost", "inactive"):
                continue
            due = crm_time.utc_iso_to_local(f.get("due_at"))
            if due is None:
                gaps.append({"kind": "bad_due_date", "entity_id": _s(f.get("followup_id")), "text": "follow-up-ს ვადა არასწორი ფორმატით აქვს — რისკი ვერ შეფასდა"})
                continue
            if due >= now:
                continue
            aid = f.get("agent_id") or c.get("assigned_agent_id")
            a, notify, esc_now = owner_flags(aid)
            if a is None:
                gaps.append({"kind": "no_owner", "entity_id": _s(f.get("followup_id")), "text": f"follow-up-ს პასუხისმგებელი აგენტი ვერ მოიძებნა ({_label(c.get('name'))})"})
                continue
            h = (now - due).total_seconds() / 3600
            repeat = late_closed.get(c.get("client_id"), 0)
            lvl = _lvl(h, cfg_mid, cfg_high)
            if repeat >= 2 and lvl == "low":
                lvl = "medium"
            facts = [f"ვადა იყო {due.strftime('%Y-%m-%d %H:%M')}", f"გადაცილებულია {_fmt_h(h)}", f"შემდეგი ქმედება: {_s(f.get('next_action'), 120)}"]
            if repeat >= 2:
                facts.append(f"ბოლო 30 დღეში {repeat}-ჯერ დაგვიანებით დაიხურა")
            r = _risk("followup_overdue", f.get("followup_id"), a, lvl, h, f"follow-up ვადაგადაცილებულია {_fmt_h(h)} — {_s(f.get('next_action'), 100)}",
                      label=c.get("name"), facts=facts, notify=notify, escalate_now=esc_now, extra_team=_s(c.get("team")))
            r["client_id"] = c.get("client_id")
            r["repeat_late"] = repeat >= 2
            risks.append(r)
        # ---- 2) აქტიური კლიენტი, follow-up-ის გარეშე, დიდი ხანია უაქტივობა
        for c in (data.get("clients") or []):
            if c.get("archived") == "yes" or _s(c.get("status")) not in ACTIVE_CLIENT_STATUSES or open_by_client.get(c.get("client_id")):
                continue
            last = crm_time.utc_iso_to_local(c.get("last_activity_at")) or crm_time.utc_iso_to_local(c.get("created_at"))
            if last is None:
                gaps.append({"kind": "unknown_activity", "entity_id": _s(c.get("client_id")), "text": f"კლიენტს ({_label(c.get('name'))}) აქტივობის თარიღი არ აქვს — რისკი ვერ შეფასდა"})
                continue
            days = (now - last).total_seconds() / 86400
            if days < config.LEAD_GUARD_SILENT_DAYS or days > config.LEAD_GUARD_SILENT_MAX_DAYS:
                continue
            aid = c.get("assigned_agent_id")
            if not aid:
                gaps.append({"kind": "no_owner", "entity_id": _s(c.get("client_id")), "text": f"აქტიურ კლიენტს ({_label(c.get('name'))}) აგენტი მიკუთვნებული არ აჰყავს"})
                continue
            a, notify, esc_now = owner_flags(aid)
            if a is None:
                gaps.append({"kind": "no_owner", "entity_id": _s(c.get("client_id")), "text": f"კლიენტის აგენტი ვერ მოიძებნა ({_label(c.get('name'))})"})
                continue
            h = days * 24
            r = _risk("no_next_action", c.get("client_id"), a, "high" if days >= 7 else "medium", h,
                      f"{int(days)} დღეა აქტივობა არ ფიქსირდება და შემდეგი ნაბიჯი დაგეგმილი არ არის (სტატუსი: {_s(c.get('status'))})",
                      label=c.get("name"), facts=[f"ბოლო აქტივობა: {last.strftime('%Y-%m-%d')}", "ღია follow-up არ არსებობს", f"სტატუსი: {_s(c.get('status'))}"],
                      notify=notify, escalate_now=esc_now, extra_team=_s(c.get("team")))
            r["client_id"] = c.get("client_id")
            r["data_gap"] = "no_followup"
            risks.append(r)

    # ---- 3) Property Hub / დავალებები (არსებული attention_items; დუბლირების გარეშე)
    hub_by_id = {_s(h.get("hub_id")): h for h in (data.get("hub_rows") or [])}
    task_by_id = {_s(t.get("task_id")): t for t in data.get("tasks", [])}
    for it in (data.get("attention") or []):
        kind, age = it.get("kind"), float(it.get("age_hours") or 0)
        if kind in ("outcome_missing", "pending_undecided"):
            h = hub_by_id.get(_s(it.get("hub_id")))
            if not h:
                continue
            aid = h.get("requester_agent_id") if kind == "outcome_missing" else h.get("owner_agent_id")
            a, notify, esc_now = owner_flags(aid)
            if a is None:
                continue
            risks.append(_risk(kind, it.get("hub_id"), a, _lvl(age, cfg_mid, cfg_high), age, _s(it.get("text"), 160), label=h.get("client_name"),
                               facts=[f"გასულია ≈{_fmt_h(age)}", f"შეხვედრა: {_s(h.get('meeting_date'))} {_s(h.get('meeting_time'))}"], notify=notify,
                               escalate_now=esc_now, source="hub"))
        elif kind in ("lead_unseen", "lead_no_meeting"):
            t = task_by_id.get(_s(it.get("task_id")))
            if not t:
                continue
            a, notify, esc_now = owner_flags(t.get("assigned_to"))
            if a is None:
                continue
            lvl = _lvl(age, 6, 24) if kind == "lead_unseen" else _lvl(age, 48, 120)
            risks.append(_risk(kind, it.get("task_id"), a, lvl, age, _s(it.get("text"), 160), label=t.get("title"),
                               facts=[f"დავალება მინიჭებულია ≈{_fmt_h(age)} წინ"], notify=(notify and kind != "lead_unseen"),   # lead_unseen-ს არსებული job აგზავნის
                               escalate_now=esc_now, source="task"))

    # ---- გამორთული აგენტის ღია რისკები უკვე esc_now-ია; დუბლიკატი გასაღებების მოხსნა
    seen, out = set(), []
    for r in risks:
        if r["key"] not in seen:
            seen.add(r["key"])
            out.append(r)
    for r in out:
        if r["escalate_now"]:
            r["reason"] = "⚠️ აგენტი გამორთულია — " + r["reason"]
            r["facts"].append("პასუხისმგებელი აგენტი გამორთულია (კლიენტი მიუჩინარებელია)")
            r["next_step"] = NEXT_STEP["agent_inactive"]
            r["level"] = "high"
    out.sort(key=lambda r: (LEVEL_ORDER.get(r["level"], 9), -r["age_hours"]))
    return out, gaps


def covered_kinds(data: dict) -> set[str]:
    """რომელი კატეგორიის „მოსნმა“ (resolved) შეიძლება ვიცოდეთ საიმედოდ — მხოლოდ ის, რისი წყაროც წარმატებით წაიკითხა."""
    ok = set()
    if data.get("followups") is not None:
        ok |= {"followup_overdue", "no_next_action"}
    if data.get("attention") is not None:
        ok |= {"outcome_missing", "pending_undecided", "lead_unseen", "lead_no_meeting"}
    return ok


# ====================================================================== მდგომარეობა (ცხრილი)
def log_rows(fresh: bool = False) -> dict:
    return {r.get("guard_key"): r for r in _backend.read(SHEET, fresh=fresh)}


def sync_log(risks: list[dict], covered: set[str], now: datetime.datetime) -> dict:
    """ახალი რისკები -> ჩანაწერი; შეცვლილი დონე -> განახლება; გაქრილი (და წყარო წაკითხულია) -> resolved. ყველაფერი ერთი ჯგუფური ჩაწერით."""
    with _lock:
        by_key = log_rows(fresh=True)
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        cur = {r["key"]: r for r in risks}
        new, changes = [], {}
        for k, r in cur.items():
            L = by_key.get(k)
            if L is None:
                row = {h: "" for h in HEADERS}
                row.update({"guard_key": k, "kind": r["kind"], "entity_id": r["entity_id"], "agent_id": r["agent_id"], "team": r["team"], "first_seen": ts,
                            "level": r["level"], "remind_count": "0", "status": "open", "last_reason": r["reason"][:200]})
                new.append(row)
                by_key[k] = row
            elif _s(L.get("status")) == "resolved":                      # იგივე გასაღები ხელახლა გაჩნდა -> ახალი ეპიზოდი
                ch = {"status": "open", "resolved_at": "", "first_seen": ts, "level": r["level"], "remind_count": "0", "last_remind_at": "",
                      "escalated_at": "", "escalated_level": "", "last_reason": r["reason"][:200]}
                changes[k] = ch
                L.update(ch)
            elif _s(L.get("level")) != r["level"]:
                changes[k] = {"level": r["level"]}
                L["level"] = r["level"]
        for k, L in by_key.items():
            if k not in cur and _s(L.get("kind")) in covered and _s(L.get("status")) == "open":
                changes[k] = {"status": "resolved", "resolved_at": ts}
                L.update(changes[k])
        if new:
            _backend.append_many(SHEET, HEADERS, new)
        if changes:
            _backend.update_many(SHEET, HEADERS, {k: v for k, v in changes.items() if k not in {n["guard_key"] for n in new}})
        return by_key


# ====================================================================== გეგმა: ვის რა გავუგზავნოთ
ESCALATE_AFTER = {"followup_overdue": None, "outcome_missing": None, "pending_undecided": None, "lead_no_meeting": 72, "no_next_action": 24 * 7}


def _managers(agent_id: str, team: str, agents: list[dict], level: str) -> list[int]:
    out: list[int] = []
    if team:
        for a in agents:
            if (_s(a.get("role")) == "team_lead" and _s(a.get("team")) == team and _s(a.get("agent_id")) != _s(agent_id) and _active(a) and _chat(a)):
                out.append(_chat(a))
    if not out or level == "high":
        for cid in config.ADMIN_CHAT_IDS:
            if cid not in out:
                out.append(cid)
    return out


def _line(i: int, r: dict, with_agent: bool = False) -> str:
    who = f" · {r['agent_name']}" if with_agent and r.get("agent_name") else ""
    return f"{i}) {LEVEL_EMOJI.get(r['level'], '•')} {r['client_label']}{who} — {r['reason']}\n   👉 {r['next_step']}"


def _compose(header: str, risks: list[dict], with_agent: bool = False, footer: str = "") -> str:
    lines = [header, ""]
    for i, r in enumerate(risks[:6], 1):
        lines.append(_line(i, r, with_agent))
    if len(risks) > 6:
        lines.append(f"… და კიდევ {len(risks) - 6} — Mini App → SAIRO → 🛡️ კლიენტები")
    if footer:
        lines += ["", footer]
    return "\n".join(lines)[:3800]


def plan(now: datetime.datetime, risks: list[dict], by_key: dict, agents: list[dict]) -> list[dict]:
    """აბრუნებს გასაგზავნ მოქმედებებს: {type: remind|escalate, chat_id, text, keys:[...], snapshot:{key:(count,last,esc,esc_level)}}.
    ღამით — ცარიელი. წესები: config.LEAD_GUARD_*."""
    if in_quiet_hours(now):
        return []
    if config.LEAD_GUARD_PILOT_TEAMS:                                      # პილოტი: მხოლოდ არჩეული გუნდები (ანგარიშში ყველაფერი ჩანს — ის წაკითხვაა)
        risks = [r for r in risks if r["team"] in config.LEAD_GUARD_PILOT_TEAMS]
    by_agent = {str(a.get("agent_id")): a for a in agents}
    cooldown = datetime.timedelta(hours=config.LEAD_GUARD_REMIND_COOLDOWN_H)
    remind: dict[str, list[dict]] = {}
    escal: dict[tuple, list[dict]] = {}
    for r in risks:
        L = by_key.get(r["key"]) or {}
        count = int(_s(L.get("remind_count")) or 0)
        last = None
        if _s(L.get("last_remind_at")):
            try:
                last = datetime.datetime.strptime(_s(L.get("last_remind_at")), "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)
            except ValueError:
                last = None
        agent = by_agent.get(r["agent_id"])
        reachable = bool(agent and _active(agent) and _chat(agent))
        # --- შეხსენება აგენტს
        if r["notify_agent"] and reachable and count < config.LEAD_GUARD_MAX_REMINDERS and (last is None or now - last >= cooldown):
            remind.setdefault(r["agent_id"], []).append(r)
        # --- ესკალაცია მენეჯერს
        thr = ESCALATE_AFTER.get(r["kind"], "x")
        by_age = (thr is None and r["age_hours"] >= config.LEAD_GUARD_ESCALATE_AFTER_H) or (isinstance(thr, (int, float)) and r["age_hours"] >= thr)
        exhausted = r["notify_agent"] and count >= config.LEAD_GUARD_MAX_REMINDERS
        unreachable = r["notify_agent"] and not reachable
        due = r["escalate_now"] or by_age or exhausted or unreachable
        if r["kind"] == "lead_unseen" and not r["escalate_now"]:
            due = False                                                    # არსებული check_task_followups ესკალაციას უკვე აკეთებს
        already, was_level = _s(L.get("escalated_at")), _s(L.get("escalated_level"))
        if due and (not already or (r["level"] == "high" and was_level != "high")):
            recips = tuple(sorted(_managers(r["agent_id"], r["team"], agents, r["level"])))
            if recips:                                                     # ერთი ესკალაცია = ერთი დაკავება, რამდენიმე მიმღებით
                escal.setdefault((r["agent_id"], recips), []).append(dict(r, _why=("unreachable" if unreachable else "exhausted" if exhausted else "age")))
    actions: list[dict] = []

    def snap(rs, typ):
        """მხოლოდ ის ველები, რასაც ეს მოქმედება ცვლის (შეხსენების დაკავება ესკალაციის სნეპშოტს არ აფუჭებს)."""
        out = {}
        for x in rs:
            L = by_key.get(x["key"]) or {}
            out[x["key"]] = ({"count": int(_s(L.get("remind_count")) or 0), "last": _s(L.get("last_remind_at"))} if typ == "remind"
                             else {"esc": _s(L.get("escalated_at")), "esc_level": _s(L.get("escalated_level"))})
        return out

    for aid, rs in remind.items():
        a = by_agent[aid]
        rs.sort(key=lambda x: (LEVEL_ORDER.get(x["level"], 9), -x["age_hours"]))
        header = "🛡️ SAIRO — კლიენტების დაცვა\nგაქვთ {n} საქმე, რომელიც ყურადღებას საჭიროებს:"
        footer = "დახურვის შემდეგ შეხსენება აღარ მოვა. ჩანაწერები: Mini App → CRM"
        actions.append({"type": "remind", "chat_id": _chat(a), "chat_ids": [_chat(a)], "agent_id": aid, "keys": [x["key"] for x in rs], "snapshot": snap(rs, "remind"), "risks": rs,
                        "header": header, "footer": footer, "text": _compose(header.replace("{n}", str(len(rs))), rs, footer=footer)})
    for (aid, recips), rs in escal.items():
        rs.sort(key=lambda x: (LEVEL_ORDER.get(x["level"], 9), -x["age_hours"]))
        a = by_agent.get(aid) or {}
        why = "; ".join(sorted({"აგენტთან შეხსენება ვერ მიდის (Telegram არ აქვს/გამორთულია)" if x["_why"] == "unreachable" else
                               f"{config.LEAD_GUARD_MAX_REMINDERS} შეხსენების მერე გადაუწყვეტელია" if x["_why"] == "exhausted" else "ვადა გადაცილებულია" for x in rs}))
        header = f"🔔 SAIRO — ესკალაცია\n{_s(a.get('name')) or aid} ({_s(a.get('team')) or '—'}): " + "{n}" + f" საქმე საჭიროებს ჩარევას.\nმიზეზი: {why}"
        actions.append({"type": "escalate", "chat_id": recips[0], "chat_ids": list(recips), "agent_id": aid, "keys": [x["key"] for x in rs], "snapshot": snap(rs, "escalate"), "risks": rs,
                        "header": header, "footer": "", "text": _compose(header.replace("{n}", str(len(rs))), rs)})
    return actions


def claim(action: dict, now: datetime.datetime) -> dict | None:
    """ჩაწერა **გაგზავნამდე** (at-most-once): გასაღები, რომელიც სხვა ციკლმა/ინსტანსმა უკვე დაიკავა, ამოვარდება; დარჩენილზე ჩაიწერება. None — არაფერი დარჩა."""
    with _lock:
        fresh = log_rows(fresh=True)
        keep, changes, prev = [], {}, {}
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        for r in action["risks"]:
            k, s0, L = r["key"], action["snapshot"][r["key"]], fresh.get(r["key"])
            if L is None or _s(L.get("status")) != "open":
                continue
            full = {"count": int(_s(L.get("remind_count")) or 0), "last": _s(L.get("last_remind_at")), "esc": _s(L.get("escalated_at")), "esc_level": _s(L.get("escalated_level"))}
            cur = {k: full[k] for k in s0}
            if cur != s0:                                                  # სხვამ უკვე შეცვალა
                continue
            keep.append(r)
            if action["type"] == "remind":
                changes[k] = {"remind_count": str(full["count"] + 1), "last_remind_at": ts}
                prev[k] = {"remind_count": str(full["count"]), "last_remind_at": full["last"]}
            else:
                changes[k] = {"escalated_at": full["esc"] or ts, "escalated_level": r["level"]}
                prev[k] = {"escalated_at": full["esc"], "escalated_level": full["esc_level"]}
        if not keep:
            return None
        _backend.update_many(SHEET, HEADERS, changes)
        out = dict(action, risks=keep, keys=[r["key"] for r in keep], prev=prev)
        if len(keep) != len(action["risks"]):
            out["text"] = _compose(action["header"].replace("{n}", str(len(keep))), keep, footer=action.get("footer", ""))
        return out


def release(action: dict) -> None:
    """გაგზავნა ვერ მოხერხდა -> დაკავება უკან (შემდეგ ციკლზე ისევ ეცდება; მრიცხველი ტყუილად არ იზრდება)."""
    with _lock:
        _backend.update_many(SHEET, HEADERS, {k: v for k, v in (action.get("prev") or {}).items()})


# ====================================================================== ანგარიში (როლებით დაცული)
def _scope(viewer: dict, agents: list[dict]):
    if viewer.get("admin"):
        return lambda r: True
    if viewer.get("role") == "team_lead":
        ids = {str(a.get("agent_id")) for a in agents if _s(a.get("team")) == _s(viewer.get("team"))}
        return lambda r: r["agent_id"] in ids or (not r["agent_id"] and r["team"] == _s(viewer.get("team")))
    aid = _s(viewer.get("agent_id"))
    return lambda r: bool(aid) and r["agent_id"] == aid


def report(viewer: dict, now: datetime.datetime | None = None, data: dict | None = None, only_teams=None) -> dict:
    """წაკითხვა-მხოლოდ (არაფერს წერს/აგზავნის). ადმინი — ყველა; თიმლიდერი — თავისი გუნდი; აგენტი — მხოლოდ საკუთარი."""
    now = now or _now()
    data = data if data is not None else collect(now)
    risks, gaps = detect(now, data)
    inside = _scope(viewer, data.get("agents", []))
    mine = [r for r in risks if inside(r) and (not only_teams or r["team"] in only_teams)]
    log = {}
    try:
        log = log_rows()
    except Exception:  # noqa: BLE001
        pass
    items = []
    for r in mine[:200]:
        L = log.get(r["key"]) or {}
        d = {k: v for k, v in r.items() if k not in ("notify_agent", "escalate_now")}
        d["reminders_sent"] = int(_s(L.get("remind_count")) or 0)
        d["escalated"] = bool(_s(L.get("escalated_at")))
        d["first_seen"] = _s(L.get("first_seen"))
        items.append(d)
    counts = {"total": len(mine), "high": sum(1 for r in mine if r["level"] == "high"), "medium": sum(1 for r in mine if r["level"] == "medium"),
              "low": sum(1 for r in mine if r["level"] == "low"), "by_kind": {}}
    for r in mine:
        counts["by_kind"][r["kind"]] = counts["by_kind"].get(r["kind"], 0) + 1
    out = {"generated_at": now.strftime("%Y-%m-%d %H:%M"), "scope": "all" if viewer.get("admin") else ("team" if viewer.get("role") == "team_lead" else "own"),
           "counts": counts, "items": items, "priorities": [{"key": i["key"], "client_label": i["client_label"], "agent_name": i["agent_name"], "level": i["level"],
                                                               "reason": i["reason"], "next_step": i["next_step"]} for i in items[:5]],
           "data_errors": data.get("errors", []), "disclaimer": DISCLAIMER}
    if viewer.get("admin") or viewer.get("role") == "team_lead":
        ag: dict[str, dict] = {}
        for r in mine:
            a = ag.setdefault(r["agent_id"] or "—", {"agent_id": r["agent_id"], "agent_name": r["agent_name"] or "უცნობი", "team": r["team"], "total": 0, "high": 0})
            a["total"] += 1
            a["high"] += 1 if r["level"] == "high" else 0
        out["by_agent"] = sorted(ag.values(), key=lambda x: (-x["high"], -x["total"]))
        out["data_gaps"] = [g for g in gaps][:50]
    return out


def digest_text(rep: dict, heading: str) -> str:
    c = rep["counts"]
    lines = [heading, f"📅 {rep['generated_at']}", f"სულ რისკი: {c['total']}  (🔴 {c['high']} · 🟠 {c['medium']} · 🟡 {c['low']})", ""]
    for i, p in enumerate(rep["priorities"], 1):
        lines.append(f"{i}) {LEVEL_EMOJI.get(p['level'], '•')} {p['client_label']} · {p['agent_name']} — {p['reason']}\n   👉 {p['next_step']}")
    if rep.get("by_agent"):
        lines += ["", "აგენტები: " + ", ".join(f"{a['agent_name']} {a['total']}" for a in rep["by_agent"][:8])]
    if rep.get("data_errors"):
        lines += ["", "⚠️ ვერ ვიკითხე წყარო: " + ", ".join(rep["data_errors"]) + " — ამ ნაწილზე რისკი ვერ შეფასდა"]
    if rep.get("data_gaps"):
        lines += ["", f"ℹ️ მონაცემთა ხარვეზი: {len(rep['data_gaps'])} ჩანაწერზე რისკი ვერ შეფასდა"]
    lines += ["", "დეტალები: Mini App → SAIRO → 🛡️ კლიენტები"]
    return "\n".join(lines)[:3800]
