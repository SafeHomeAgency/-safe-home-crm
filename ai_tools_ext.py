"""
SAIRO-ს გაფართოება: **კადრები** (წაკითხვა + მოქმედების შეთავაზება), **ფინანსები** (მხოლოდ FINANCE_CHAT_IDS — დირექტორი), **ნავიგაცია** Mini App-ის ყველა
განყოფილებაზე და **ვიჯეტები** (ბარათები/დიაგრამები), რომლებსაც აპი ჩატში იმავე დიზაინით ხატავს.

უფლებები სერვერზეა და prompt-ით ვერ გადაიწერება:
  * კადრები — ნახვა: ადმინი / თიმლიდერი / „პასუხისმგებელი“ (აპიდან ინიშნება); ცვლილება: ადმინი + პასუხისმგებელი. აგენტს ეს ინსტრუმენტები საერთოდ არ ეძლევა;
  * ფინანსები — მხოლოდ მომხმარებელს, რომლის Telegram ID `FINANCE_CHAT_IDS`-შია (ადმინებისთვისაც კი დახურულია, თუ იქ არ არიან);
  * მოდელს ჩაწერა არ შეუძლია: ცვლილება = `propose_recruit_update` -> ბარათი -> მხოლოდ მომხმარებლის დადასტურებით (იგივე წესი, რაც follow-up-ს);
  * ვიჯეტები (სრული სახელი/ტელეფონი) პირდაპირ მომხმარებელს მიდის და მოდელს არ ეგზავნება — მოდელი ხედავს მხოლოდ პლეისჰოლდერებს ([CANDIDATE_n]) და რიცხვებს.
"""

from __future__ import annotations

import datetime

import ai_model as m
import config
from ai_model import AiError


def _obj(props: dict | None = None, required: list | None = None) -> dict:
    out = {"type": "object", "properties": props or {}, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


def perms(viewer: dict) -> dict:
    admin = bool(viewer.get("admin"))
    lead = m.s(viewer.get("role"), 20) == "team_lead"
    aid = m.s(viewer.get("agent_id"), 40)
    resp = False
    if aid:
        try:
            import recruit_store as rs
            resp = aid in rs.get_settings()["responsible_ids"]
        except Exception:  # noqa: BLE001
            resp = False
    try:
        fin = int(viewer.get("chat_id") or 0) in config.FINANCE_CHAT_IDS
    except (TypeError, ValueError):
        fin = False
    return {"recruit_view": admin or lead or resp, "recruit_edit": admin or resp, "finance": fin, "manager": admin or lead, "admin": admin}


# განყოფილებები (id = Mini App-ის ტაბის id, app.js: AGENT_TABS / ADMIN_TABS + hub/recruit/finance/system/ai).
# kind: all = ორივე ინტერფეისში; agent = მხოლოდ აგენტის ინტერფეისში (მენეჯერს/ადმინს „დღეს/დავალებები/KPI…“ არ აქვს); manager = ადმინი/თიმლიდერი; admin = მხოლოდ დირექტორი.
SECTIONS = {
    "taskhistory": ("📜 ისტორია", "all"), "meetings": ("🤝 შეხვედრები", "all"), "exclusives": ("🏘️ ექსკლუზივები", "all"), "myhomejobs": ("🏘️ MyHome", "all"),
    "questions": ("💬 კითხვები", "all"), "regulations": ("📘 ინსტრუქცია/წესები", "all"), "crm2": ("🗃️ CRM", "all"), "contracts": ("📑 ხელშეკრულებები", "all"),
    "hub": ("🏙️ განცხადებები (კატალოგი, რუკა, 👤 პირადი კაბინეტი: კლიენტები, Telegram ლიდები, შეხვედრები, follow-up, გუნდის ცხრილი)", "all"), "ai": ("🦸 SAIRO", "all"),
    "tgnet": ("📣 Telegram (არხები, რიგი, ლიდები)", "manager"),
    "today": ("🏠 დღეს", "agent"), "tasks": ("📋 დავალებები", "agent"), "kpi": ("📈 KPI", "agent"), "myattendance": ("🕘 დასწრება", "agent"), "mydayoffs": ("🏖️ შვებულება", "agent"),
    "overview": ("📊 მიმოხილვა", "manager"), "team": ("🧑‍🤝‍🧑 გუნდი", "manager"), "ranking": ("🏆 რეიტინგი", "manager"), "attendance": ("🕘 დასწრება (გუნდი)", "manager"),
    "districts": ("📍 რაიონები", "manager"), "agentrequests": ("📥 მოთხოვნები", "manager"), "admintasks": ("📄 დავალებები (გუნდი)", "manager"),
    "digest": ("🗞️ დღის ამბები", "manager"), "dayoffs": ("🗓️ შვებულებები", "manager"), "warnings": ("⚠️ გაფრთხილებები", "manager"), "swaps": ("🔁 სმენის გაცვლა", "manager"),
    "reports": ("📝 რეპორტები", "manager"), "myhomestats": ("📊 MyHome სტატისტიკა", "manager"),
    "agentsmgmt": ("🗂️ აგენტები", "admin"), "system": ("🩺 სისტემა", "admin"),
    "recruit": ("🧑‍💼 კადრები (აყვანა)", "recruit"), "finance": ("💰 ფინანსები", "finance"),
}


def section_allowed(viewer: dict, sid: str) -> bool:
    kind = SECTIONS.get(sid, ("", ""))[1]
    p = perms(viewer)
    return {"all": True, "agent": not p["manager"], "manager": p["manager"], "admin": p["admin"], "recruit": p["recruit_view"], "finance": p["finance"]}.get(kind, False)


RECRUIT_CHANGE_KEYS = ["call_status", "attended", "decision", "interview_at", "training_at", "training_ok", "attended_t1", "attended_t2", "inter_lasha", "inter_owner", "inter_client",
                       "inter_lasha_at", "inter_owner_at", "inter_client_at", "test_score", "internship_at", "hire", "staffed_at", "left_at", "left_reason", "stage", "comment"]
_DATE = {"type": "string", "description": "თარიღი YYYY-MM-DD (ან today / tomorrow / yesterday). ფარდობითი თარიღი („ზეგ“, „11 ნოემბერი“) თავად გადათარგმნე YYYY-MM-DD-ად <knowledge_base today=…>-ის მიხედვით."}

TOOL_DEFS = {
    "recruit_day": {"name": "recruit_day", "description": "კადრები: ერთი დღის გასაუბრებები კლასებად (მისაწერი, მივწერე, დასადასტურებელი, მოდის, არ მოდის, გადაიფიქრა, გადაიდო, მოვიდა, არ მოვიდა) + ტრენინგები/სტაჟირება. აპი ბარათებს ეკრანზე თავად აჩვენებს — ტექსტში მხოლოდ მოკლე შეჯამება.",
                    "input_schema": _obj({"date": _DATE, "class": {"type": "string", "description": "არასავალდებულო: to_message|messaged|pending|confirmed|postponed|declined|changed|attended|noshow"}}, ["date"])},
    "recruit_range": {"name": "recruit_range", "description": "კადრები: პერიოდის (მაქს. 62 დღე) გასაუბრებები დღეების მიხედვით და კლასების ჯამი (რამდენი მოდის / არ მოდის / გადაიფიქრა / დასადასტურებელი / მისაწერი). აპი დიაგრამას ხატავს.",
                      "input_schema": _obj({"from_date": _DATE, "to_date": _DATE}, ["from_date", "to_date"])},
    "recruit_find": {"name": "recruit_find", "description": "კადრები: კანდიდატის ძებნა სახელით/ტელეფონის ნაწილით (candidate_ref-ისთვის). მოდელი სახელს პლეისჰოლდერად ხედავს.",
                     "input_schema": _obj({"query": {"type": "string"}}, ["query"])},
    "recruit_stats": {"name": "recruit_stats", "description": "კადრები: ვორონკა და მაჩვენებლები ბოლო N დღეში — ეტაპები, ტრენინგი (ქირა/ყიდვა), ინტერაქციები, ჩაშტატება, დახურვის მიზეზები. აპი დიაგრამებს ხატავს.",
                      "input_schema": _obj({"days": {"type": "integer", "minimum": 7, "maximum": 365}})},
    "recruit_open_queue": {"name": "recruit_open_queue", "description": "კადრები (მხოლოდ რედაქტორისთვის): ამზადებს WhatsApp-ის რიგს კანდიდატებისთვის — არაფერს აგზავნის; მომხმარებელი ღილაკით აფურცლავს და ყოველ კანდიდატზე თავად აგზავნის (WhatsApp ავტომატურ გაგზავნას არ იძლევა). კანდიდატები: candidate_refs ან date+class.",
                           "input_schema": _obj({"candidate_refs": {"type": "array", "items": {"type": "string"}}, "date": _DATE, "class": {"type": "string"},
                                                  "template": {"type": "string", "description": "confirm|reminder|noshow|training"}})},
    "propose_recruit_update": {"name": "propose_recruit_update", "description": "კადრები (მხოლოდ რედაქტორისთვის): მოამზადე კანდიდატის ჩანაწერის ცვლილება — „დავურეკე და დადასტურდა“, „არ მოვიდა“, „ტრენინგზე გადავიდა 11 ნოემბერს 16:00-ზე“, ტესტი, ჩაშტატება და ა.შ. **არაფერს ცვლის** — მომხმარებელს ბარათი ეჩვენება და ცვლილება მხოლოდ დადასტურებით სრულდება. თუ ცვლილება კანდიდატს ხურავს (არ მოდის / უარყოფილია / გადაიფიქრა / წავიდა), changes.left_reason სავალდებულოა — ჰკითხე მომხმარებელს მიზეზი. მნიშვნელობები: call_status: confirmed|declined|no_contact|repeat|pending; attended: yes|no|changed|postponed; decision: accepted|rejected|considering; training_ok: yes|no|changed|no_answer; hire: yes|no|changed; inter_*: scheduled|held|passed|failed|changed; თარიღი-დრო: YYYY-MM-DD HH:MM, თარიღი: YYYY-MM-DD.",
                               "input_schema": _obj({"candidate_ref": {"type": "string"}, "changes": {"type": "object", "properties": {k: {"type": "string"} for k in RECRUIT_CHANGE_KEYS}, "additionalProperties": False},
                                                      "note": {"type": "string", "description": "მოკლე შენიშვნა ისტორიისთვის"}}, ["candidate_ref", "changes"])},
    "finance_overview": {"name": "finance_overview", "description": "ფინანსები (მხოლოდ დირექტორი): თვეების ინტერვალის შეჯამება — გარიგებები, კომისია, კომპანიის შემოსავალი, ხარჯები, მოგება, ხარჯები კატეგორიებით, საუკეთესო აგენტები/რაიონები. აპი დიაგრამებს ხატავს.",
                         "input_schema": _obj({"from_month": {"type": "string", "description": "YYYY-MM (ნაგულისხმევი: 5 თვის წინ)"}, "to_month": {"type": "string", "description": "YYYY-MM (ნაგულისხმევი: მიმდინარე)"}})},
    "finance_reminders": {"name": "finance_reminders", "description": "ფინანსები (მხოლოდ დირექტორი): მოახლოებული/გასული ხელშეკრულების ვადები და ანგარიშის შეხსენებები გარიგებებზე.", "input_schema": _obj()},
    "open_section": {"name": "open_section", "description": "Mini App-ის ნებისმიერ განყოფილებაზე გადასვლის ღილაკს აჩვენებს მომხმარებელს (კადრებისთვის — view: today|cal|all|stats და date). section = განყოფილების id (იხ. MINI APP MAP).",
                     "input_schema": _obj({"section": {"type": "string"}, "view": {"type": "string"}, "date": _DATE}, ["section"])},
}

RECRUIT_TOOLS = ["recruit_day", "recruit_range", "recruit_find", "recruit_stats"]
RECRUIT_EDIT_TOOLS = ["recruit_open_queue", "propose_recruit_update"]
FINANCE_TOOLS = ["finance_overview", "finance_reminders"]
TG_MANAGER_TOOLS = ["tg_leads", "tg_interest"]
TG_ADMIN_TOOLS = ["tg_queue"]
TG_AGENT_TOOLS = ["tg_my_leads"]
TOOL_DEFS.update({
    "tg_leads": {"name": "tg_leads", "description": "Telegram ლიდები (არხებიდან/Mini App-დან): რამდენი ახალია (მიუბმელი), რომელია აგენტზე და დაუდასტურებელი, ვის რამდენი აქვს, ყველაზე დიდხანს მოლოდინში მყოფი. მენეჯერი/თიმლიდერი. კლიენტის სახელი პლეისჰოლდერია, ტელეფონი არ გადმოგეცემა.",
                 "input_schema": _obj({})},
    "tg_interest": {"name": "tg_interest", "description": "რომელი განცხადებით არიან კლიენტები ყველაზე დაინტერესებულები Telegram-იდან (ნახვა/მოთხოვნა/ლიდი, ქულით). მენეჯერი/თიმლიდერი.", "input_schema": _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 20}})},
    "tg_queue": {"name": "tg_queue", "description": "Telegram-ზე გამოსაქვეყნებელი რიგის შეჯამება: რამდენი ელოდება დამტკიცებას, გასასწორებელია, დამტკიცებულია; ბოლო განცხადებები. მხოლოდ დირექტორი.", "input_schema": _obj({})},
    "tg_my_leads": {"name": "tg_my_leads", "description": "ჩემი Telegram ლიდები (აგენტისთვის): რომელი ელოდება დადასტურებას, რომელს აქვს follow-up და როდის. კლიენტის სახელი პლეისჰოლდერია.", "input_schema": _obj({})},
})

TOOL_DEFS.update({
    "propose_tg_assign": {"name": "propose_tg_assign", "description": "მენეჯერი/დირექტორი: მოამზადე Telegram ლიდის გადაბარება აგენტზე (lead_ref — tg_leads-იდან, agent_ref — აგენტის id tg_leads.agents-იდან; ნაგულისხმევად ბინის აგენტი listing_agent_ref). **არაფერს ცვლის** — ეჩვენება ბარათი, სრულდება მხოლოდ დადასტურებით.",
                          "input_schema": _obj({"lead_ref": {"type": "string"}, "agent_ref": {"type": "string"}}, ["lead_ref", "agent_ref"])},
    "propose_tg_lead_result": {"name": "propose_tg_lead_result", "description": "აგენტი: მოამზადე თავისი Telegram ლიდის სტატუსი — ack (მივიღე), contacted (დავუკავშირდი: note სავალდებულოა), waiting (მოგვიანებით). contacted/waiting-ზე follow_up_at სავალდებულოა „YYYY-MM-DD HH:MM“ (მომავალში) — თუ მომხმარებელმა დრო არ თქვა, ჰკითხე. ბარათი — დადასტურებით.",
                               "input_schema": _obj({"lead_ref": {"type": "string"}, "action": {"type": "string", "enum": ["ack", "contacted", "waiting"]}, "follow_up_at": {"type": "string"}, "note": {"type": "string"}}, ["lead_ref", "action"])},
    "propose_tg_queue": {"name": "propose_tg_queue", "description": "მხოლოდ დირექტორი: მოამზადე Telegram რიგის განცხადებების (listing ID-ები tg_queue-დან, მაქს. 50) დამტკიცება ან უარყოფა. ბარათი — დადასტურებით.",
                         "input_schema": _obj({"listing_keys": {"type": "array", "items": {"type": "string"}}, "action": {"type": "string", "enum": ["approve", "reject"]}}, ["listing_keys", "action"])},
})
TG_MANAGER_TOOLS.append("propose_tg_assign")
TG_ADMIN_TOOLS.append("propose_tg_queue")
TG_AGENT_TOOLS.append("propose_tg_lead_result")


def names_for(viewer: dict) -> list[str]:
    p = perms(viewer)
    out = ["open_section"]
    if p["recruit_view"]:
        out += RECRUIT_TOOLS
    if p["recruit_edit"]:
        out += RECRUIT_EDIT_TOOLS
    if p["finance"]:
        out += FINANCE_TOOLS
    if p["admin"] or p["manager"]:
        out += TG_MANAGER_TOOLS
    if p["admin"]:
        out += TG_ADMIN_TOOLS
    if m.s(viewer.get("agent_id"), 40):
        out += TG_AGENT_TOOLS
    return out


def _date(v, default_today: bool = True) -> str:
    s = m.s(v, 20).lower()
    import crm_time
    today = crm_time.local_today()
    if not s and default_today:
        return today.strftime("%Y-%m-%d")
    if s in ("today", "დღეს"):
        return today.strftime("%Y-%m-%d")
    if s in ("tomorrow", "ხვალ"):
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if s in ("yesterday", "გუშინ"):
        return (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        return datetime.datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise AiError("თარიღი უნდა იყოს YYYY-MM-DD ფორმატში") from None


class ExtTools:
    """ToolContext-ის მიქსინი: `self.viewer`, `self.pseudo`, `self.widgets`, `self.actions`, `self._agents()` არსებული კლასიდან."""

    widgets: list

    def _cand(self, rec: dict) -> dict:
        return {"ref": rec.get("recruit_id"), "name": self.pseudo.token("CANDIDATE", rec.get("name")), "stage": rec.get("stage_label"), "class": rec.get("cls"),
                "interview": f"{rec.get('interview_day', '')} {rec.get('interview_time', '')}".strip(), "call": rec.get("call_label")}

    # ---------------------------------------------------------------- Telegram (ლიდები/რიგი)
    def _t_tg_leads(self, args):
        import tgnet_leads as tl
        import tgnet_store as ts
        rows = [r for r in ts.list_lead_rows(fresh=True) if r["kind"] == "lead"]
        by = {}
        for r in rows:
            by[r["status"] or "new"] = by.get(r["status"] or "new", 0) + 1
        names = {str(a.get("agent_id")): a.get("name") for a in self._agents()}
        per_agent = {}
        for r in rows:
            if r["status"] in ("assigned", "acknowledged", "waiting", "contacted") and r["assigned_agent_id"]:
                k = names.get(r["assigned_agent_id"]) or r["assigned_agent_id"]
                per_agent[k] = per_agent.get(k, 0) + 1
        now = tl._parse_local(ts.now_str())
        waiting = []
        for r in rows:
            at = tl._parse_local(r["assigned_at"] if r["status"] == "assigned" else r["at"])
            if r["status"] in ("new", "assigned") and at:
                import tgnet_publisher as tp
                lst = tp.get_listing(r["listing_key"]) if r["listing_key"] else None
                waiting.append({"lead_ref": r["lead_id"], "client": self.pseudo.token("CLIENT", r["tg_name"] or "-"), "status": r["status"], "minutes": int((now - at).total_seconds() // 60), "seen": bool(r["seen_at"]),
                                "agent": names.get(r["assigned_agent_id"], ""), "listing": r["listing_key"], "listing_agent_ref": str((lst or {}).get("agent_id") or ""), "listing_team": str((lst or {}).get("team") or "")})
        waiting.sort(key=lambda x: -x["minutes"])
        ags = [{"agent_ref": str(a.get("agent_id")), "name": a.get("name"), "team": a.get("team", "")} for a in self._agents() if str(a.get("active", "yes")).lower() not in ("no", "false", "0")
               and (self.viewer.get("admin") or str(a.get("team") or "") == str(self.viewer.get("team") or ""))]
        return {"total": len(rows), "by_status": by, "per_agent_open": per_agent, "longest_waiting": waiting[:12], "agents": ags[:60],
                "note": "გადასაბარებლად: propose_tg_assign(lead_ref, agent_ref) — ნაგულისხმევად listing_agent_ref (ბინის აგენტი). ან აპი → განცხადებები → 👤 კაბინეტი → კლიენტები"}

    def _t_tg_interest(self, args):
        import tgnet_publisher as tp
        import tgnet_store as ts
        try:
            n = max(1, min(20, int(args.get("limit", 8))))
        except (TypeError, ValueError):
            n = 8
        out = []
        for a in ts.interest_stats(n):
            lst = tp.get_listing(a["listing_key"])
            out.append({"listing": a["listing_key"], "summary": ts.listing_summary(lst) if lst else "", "views": a["views"], "requests": a["intents"], "leads": a["leads"], "score": a["score"]})
        return {"top": out}

    def _t_tg_queue(self, args):
        import tgnet_store as ts
        pg = ts.queue_page(status=m.s(args.get("status"), 20), limit=20)
        return {"counts": pg["counts"], "total": pg["total"], "latest": [{"listing": g["listing_key"], "status": g["status"], "summary": g["summary"], "problem": g["error"]} for g in pg["groups"]],
                "note": "დასამტკიცებლად: propose_tg_queue(listing_keys, approve|reject) — ბარათით; ან ტაბი Telegram → რიგი (მონიშვნით ერთიანადაც)"}

    def _t_tg_my_leads(self, args):
        import tgnet_leads as tl
        import tgnet_publisher as tp
        flow = tl.Flow(None, get_listing=tp.get_listing, agents=self._agents)
        items = flow.my_leads(m.s(self.viewer.get("agent_id"), 40))
        return {"total": len(items), "leads": [{"lead_ref": x["lead_id"], "client": self.pseudo.token("CLIENT", x["name"] or "-"), "status": x["status"], "listing": x["summary"], "seen": x["seen"], "follow_up": x["follow_up_at"]} for x in items[:12]],
                "note": "სტატუსის ჩასაწერად: propose_tg_lead_result(lead_ref, action, follow_up_at, note) — follow-up სავალდებულოა; ან აპი → განცხადებები → 👤 კაბინეტი"}

    def _t_propose_tg_assign(self, args):
        import ai_actions
        card = ai_actions.propose(self.viewer, "tg_assign", {"lead_id": m.s(args.get("lead_ref"), 40), "agent_id": m.s(args.get("agent_ref"), 40)}, self._agents())
        self.actions.append(card)
        return {"proposed": True, "action_id": card["action_id"], "note": "ბარათი ეკრანზეა; გადაბარება შესრულდება მხოლოდ დადასტურების შემდეგ."}

    def _t_propose_tg_lead_result(self, args):
        import ai_actions
        payload = {"lead_id": m.s(args.get("lead_ref"), 40), "action": m.s(args.get("action"), 20), "follow_up_at": m.s(args.get("follow_up_at"), 20), "note": self.pseudo.restore(m.s(args.get("note"), 300))}
        card = ai_actions.propose(self.viewer, "tg_lead_result", payload, self._agents())
        self.actions.append(card)
        return {"proposed": True, "action_id": card["action_id"], "note": "ბარათი ეკრანზეა; ჩაიწერება მხოლოდ დადასტურების შემდეგ."}

    def _t_propose_tg_queue(self, args):
        import ai_actions
        keys = [m.s(k, 40) for k in (args.get("listing_keys") or []) if m.s(k, 40)]
        card = ai_actions.propose(self.viewer, "tg_queue_decide", {"keys": keys, "action": m.s(args.get("action"), 20)}, self._agents())
        self.actions.append(card)
        return {"proposed": True, "action_id": card["action_id"], "note": "ბარათი ეკრანზეა; შესრულდება მხოლოდ დადასტურების შემდეგ."}

    # ---------------------------------------------------------------- კადრები
    def _t_recruit_day(self, args):
        import recruit_model as rm
        import recruit_store as rs
        day = _date(args.get("date"))
        dv = rs.day_view(day)
        f = m.s(args.get("class"), 20)
        items = [x for x in dv["interviews"] if not f or x.get("cls") == f]
        self.widgets.append({"type": "recruit_day", "date": day, "groups": dv["groups"], "class_labels": dv["class_labels"], "class_order": dv["class_order"], "items": dv["interviews"],
                             "filter": f if f in rm.CLASS_LABELS else "", "trainings": dv["trainings"], "internship": dv["internship"], "staffed": dv["staffed"], "left": dv["left"]})
        return {"date": day, "interviews_total": len(dv["interviews"]), "by_class": {dv["class_labels"][k]: n for k, n in dv["groups"].items() if n},
                "candidates": [self._cand(x) for x in items[:40]], "trainings": len(dv["trainings"]), "internship_starts": len(dv["internship"]), "staffed": len(dv["staffed"]), "left": len(dv["left"]),
                "note": "ბარათები და დიაგრამა ეკრანზე ავტომატურად ჩანს — ტექსტში მოკლედ შეაჯამე"}

    def _t_recruit_range(self, args):
        import recruit_model as rm
        import recruit_store as rs
        a, b = _date(args.get("from_date")), _date(args.get("to_date"))
        da, db = datetime.datetime.strptime(a, "%Y-%m-%d").date(), datetime.datetime.strptime(b, "%Y-%m-%d").date()
        if db < da:
            raise AiError("დასასრული თარიღი დასაწყისზე ადრეა")
        n = min(62, (db - da).days + 1)
        cal = rs.calendar(a, n)
        tot = {k: sum(d["classes"][k] for d in cal["days"]) for k in rm.CLASS_ORDER}
        self.widgets.append({"type": "recruit_range", "from": a, "to": cal["days"][-1]["date"], "days": cal["days"], "totals": tot, "class_labels": rm.CLASS_LABELS, "class_order": rm.CLASS_ORDER})
        return {"from": a, "to": cal["days"][-1]["date"], "interviews_total": sum(tot.values()), "by_class": {rm.CLASS_LABELS[k]: v for k, v in tot.items() if v},
                "per_day": [{"date": d["date"], "interviews": d["interviews"]["total"], "trainings": d["trainings"]["total"]} for d in cal["days"] if d["interviews"]["total"] or d["trainings"]["total"]],
                "note": "დიაგრამა ეკრანზე ავტომატურად ჩანს — ტექსტში მოკლედ შეაჯამე"}

    def _t_recruit_find(self, args):
        import recruit_store as rs
        q = m.s(args.get("query"), 60)
        if len(q) < 2:
            raise AiError("ძიების ტექსტი ძალიან მოკლეა")
        res = rs.query({"q": q, "state": "all", "per_page": 8})
        self.widgets.append({"type": "recruit_list", "title": f"🔎 „{q}“", "items": res["items"]})
        return {"total": res["total"], "candidates": [self._cand(x) for x in res["items"]],
                "note": "ერთზე მეტი ემთხვევა => ჰკითხე მომხმარებელს, ვინ იგულისხმება (ref-ებით); ჩანაწერის შესაცვლელად გამოიყენე propose_recruit_update"}

    def _t_recruit_stats(self, args):
        import recruit_store as rs
        try:
            days = max(7, min(365, int(args.get("days", 90))))
        except (TypeError, ValueError):
            days = 90
        s = rs.stats(days=days)
        self.widgets.append({"type": "recruit_stats", "stats": s, "stages": __import__("recruit_model").STAGES})
        return {"days": days, "total": s["total"], "by_stage": s["by_stage"], "conv": s["conv"], "training": {k: v for k, v in s["training"].items() if k != "by_day"}, "interactions": s["interactions"],
                "outcome": s["outcome"], "closing_reasons": s["reasons"], "reason_unknown": s["reason_unknown"], "median_first_contact_h": s["median_first_contact_h"]}

    def _t_recruit_open_queue(self, args):
        import recruit_api
        import recruit_store as rs
        refs = [m.s(x, 40) for x in (args.get("candidate_refs") or []) if m.s(x)] if isinstance(args.get("candidate_refs"), list) else []
        items = []
        if refs:
            for rid in refs[:100]:
                r = rs.get(rid, fresh=True)
                if r and m.s(r.get("closed")) != "yes":
                    items.append(rs.public(r))
        elif args.get("date"):
            f = m.s(args.get("class"), 20)
            items = [x for x in rs.day_view(_date(args.get("date")))["interviews"] if (not f or x.get("cls") == f) and x.get("closed") != "yes"]
        if not items:
            raise AiError("კანდიდატი ვერ მოიძებნა (ან დახურულია)")
        key = m.s(args.get("template"), 12) or "confirm"
        tpls = rs.get_settings()["templates"]
        text = tpls.get(key) or recruit_api.DEFAULT_TEMPLATES.get(key) or recruit_api.DEFAULT_TEMPLATES["confirm"]
        self.widgets.append({"type": "recruit_queue", "items": items, "template": text, "template_key": key if key in recruit_api.DEFAULT_TEMPLATES else "custom"})
        return {"prepared": len(items), "note": "WhatsApp-ის რიგი ეკრანზე ღილაკით მზადაა; არაფერი გაგზავნილა — მომხმარებელი თავად აგზავნის ყოველ კანდიდატზე. ავტომატურად გაგზავნა შეუძლებელია."}

    def _t_propose_recruit_update(self, args):
        import ai_actions
        ch = args.get("changes") if isinstance(args.get("changes"), dict) else {}
        payload = {"candidate_id": m.s(args.get("candidate_ref"), 40), "changes": {k: self.pseudo.restore(m.s(v, 300)) for k, v in ch.items() if k in RECRUIT_CHANGE_KEYS},
                   "note": self.pseudo.restore(m.s(args.get("note"), 300))}
        card = ai_actions.propose(self.viewer, "recruit_update", payload, self._agents())
        self.actions.append(card)
        return {"proposed": True, "action_id": card["action_id"], "note": "ბარათი მომხმარებელს ეკრანზე გამოუჩნდა; ცვლილება შესრულდება მხოლოდ მისი დადასტურების შემდეგ. ეს ჯერ არ არის შესრულებული."}

    # ---------------------------------------------------------------- ფინანსები (დირექტორი)
    def _t_finance_overview(self, args):
        import finance_model as fm
        import finance_store as fs
        today = fs.today_local()
        to = m.s(args.get("to_month"), 7) or fm.month_of(today)
        frm = m.s(args.get("from_month"), 7) or fm.month_of(fm.add_months(today.replace(day=1), -5))
        try:
            frm, to = fm.parse_month(frm, "საწყისი თვე"), fm.parse_month(to, "ბოლო თვე")
        except Exception:  # noqa: BLE001
            raise AiError("თვე: YYYY-MM") from None
        if frm > to or len(fm.month_range(frm, to)) > 36:
            raise AiError("პერიოდი: მაქსიმუმ 36 თვე, დასაწყისი დასასრულზე ადრე")
        s = fs.summary(frm, to)
        self.widgets.append({"type": "finance", "summary": {k: s[k] for k in ("from", "to", "totals", "series", "expenses_by_category", "distribution", "usd_rate")}, "top_agents": s["by_agent"][:5], "top_districts": s["by_district"][:5]})
        return {"from": s["from"], "to": s["to"], "currency": "GEL", "totals": s["totals"], "series": s["series"], "expenses_by_category": s["expenses_by_category"][:8],
                "top_agents": [{"agent": self.pseudo.token("AGENT", r["name"]), "commission": r.get("commission"), "deals": r.get("deals")} for r in s["by_agent"][:5]],
                "top_districts": [{"district": r["name"], "company_income": r.get("company_income")} for r in s["by_district"][:5]], "usd_rate": s["usd_rate"], "unconverted_usd": s["unconverted_usd"],
                "note": "დიაგრამები ეკრანზე ავტომატურად ჩანს; თანხები ლარშია (USD — დაყენებული კურსით)"}

    def _t_finance_reminders(self, args):
        import finance_store as fs
        r = fs.reminders()
        self.widgets.append({"type": "stats", "title": "💰 ფინანსური შეხსენებები", "items": [{"label": "ხელშეკრულების ვადა ახლოვდება", "value": len(r["expiring"]), "tone": "amber"},
                                                                                       {"label": "ვადა გასულია", "value": len(r["expired"]), "tone": "red"}, {"label": "ანგარიშის შეხსენება", "value": len(r["report_due"]), "tone": "blue"}]})
        pick = lambda arr: [{"deal": x.get("invoice_no"), "client": self.pseudo.token("CLIENT", x.get("client_name")), "days_left": x.get("days_left"), "months": x.get("months")} for x in arr[:8]]  # noqa: E731
        return {"expiring": pick(r["expiring"]), "expired": pick(r["expired"]), "report_due": pick(r["report_due"]), "counts": {k: len(v) for k, v in r.items()}}

    # ---------------------------------------------------------------- ნავიგაცია
    def _t_open_section(self, args):
        sid = m.s(args.get("section"), 30)
        if sid not in SECTIONS:
            raise AiError("უცნობი განყოფილება: " + ", ".join(SECTIONS))
        if not section_allowed(self.viewer, sid):
            raise AiError("ეს განყოფილება თქვენი როლისთვის მიუწვდომელია")
        view = m.s(args.get("view"), 12)
        date = _date(args.get("date"), default_today=False) if args.get("date") else ""
        self.widgets.append({"type": "link", "section": sid, "label": SECTIONS[sid][0], "view": view if view in ("today", "cal", "all", "stats") else "", "date": date})
        return {"opened": sid, "note": "ღილაკი ეკრანზე გამოჩნდა — მომხმარებელი დააჭერს და გადავა"}
