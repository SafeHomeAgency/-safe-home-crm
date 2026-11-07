"""
TGNET: საჯარო ბოტი (@SafeHomeGeBot) და ლიდები. პოსტის ღილაკი -> ბოტი -> განცხადების დეტალები -> „მინდა დაკავშირება“ -> ნომერი -> CRM-ში კლიენტი + მენეჯერს შეტყობინება ->
მენეჯერი აპიდან აბამს განცხადების აგენტს (ან სხვას) -> აგენტს მიდის მოთხოვნა. ყოველი დაინტერესება ითვლება: რომელი ბინით არიან ყველაზე მეტად დაინტერესებულები.

უსაფრთხოება: webhook-ს ამოწმებს საიდუმლო (Telegram `secret_token`, ტოკენისგან გამოყვანილი — ცალკე არსად ინახება); განმეორებითი update_id იგნორირდება;
კლიენტს ვუგზავნით მხოლოდ საჯარო მონაცემს (არა მესაკუთრის ნომერს/შენიშვნას); მენეჯერს ვუგზავნით კლიენტის სახელს/ნომერს მხოლოდ შიდა ბოტით (არა საჯარო არხში);
კლიენტის შეტყობინებით არაფერი სრულდება — მხოლოდ ჩანაწერი/შეტყობინება. ჩავარდნა ბოტს არ აჩერებს.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import re

import config
import tgnet_content as ct
import tgnet_model as m
import tgnet_store as st

log = logging.getLogger("safehome-tgnet-leads")
_PAYLOAD = re.compile(r"^(?P<lid>[A-Za-z0-9][A-Za-z0-9-]{0,40}?)(?:_(?P<lang>ka|en|ru))?$")
T = {  # ბოტის ტექსტები (ფიქსირებული, ფაქტების გამოგონების გარეშე)
    "ka": {"hello": "გამარჯობა! 👋 ეს Safe Home Agency-ის ბოტია. გამოგიგზავნეთ დეტალები:", "want": "📞 მინდა დაკავშირება", "ask": "მადლობა! 🙏 გთხოვთ დაგვიტოვოთ ტელეფონის ნომერი — მენეჯერი დაგიკავშირდებათ. შეგიძლიათ ღილაკით გააზიაროთ ან ჩაწეროთ ხელით.",
           "share": "📱 ნომრის გაზიარება", "thanks": "✅ მიღებულია! მენეჯერი უახლოეს დროს დაგიკავშირდებათ.", "bad": "ნომერი ვერ ამოვიცანი — გთხოვთ ჩაწეროთ ფორმატით 599123456 ან გააზიაროთ ღილაკით.",
           "nolist": "ეს განცხადება აღარ არის აქტუალური. დაგვიწერეთ რა გეძებთ და მენეჯერი დაგეხმარებათ.", "plain": "გამარჯობა! დაგვიწერეთ რას ეძებთ (ქირა/ყიდვა, უბანი, ბიუჯეტი) ან ნომერი — მენეჯერი დაგიკავშირდებათ."},
    "en": {"hello": "Hello! 👋 This is the Safe Home Agency bot. Here are the details:", "want": "📞 I want to be contacted", "ask": "Thank you! 🙏 Please leave your phone number and a manager will contact you. Tap the button or type it.",
           "share": "📱 Share my number", "thanks": "✅ Received! A manager will contact you shortly.", "bad": "I couldn't read the number — please type it like 599123456 or share it with the button.",
           "nolist": "This listing is no longer available. Tell us what you are looking for and a manager will help.", "plain": "Hello! Tell us what you are looking for (rent/buy, area, budget) or leave a number — a manager will contact you."},
    "ru": {"hello": "Здравствуйте! 👋 Это бот Safe Home Agency. Вот детали:", "want": "📞 Хочу связаться", "ask": "Спасибо! 🙏 Оставьте, пожалуйста, номер телефона — менеджер свяжется с вами. Нажмите кнопку или напишите номер.",
           "share": "📱 Поделиться номером", "thanks": "✅ Принято! Менеджер свяжется с вами в ближайшее время.", "bad": "Не удалось распознать номер — напишите в формате 599123456 или поделитесь кнопкой.",
           "nolist": "Это объявление уже неактуально. Напишите, что ищете, и менеджер поможет.", "plain": "Здравствуйте! Напишите, что ищете (аренда/покупка, район, бюджет) или оставьте номер — менеджер свяжется с вами."},
}


def webhook_secret() -> str:
    """Telegram-ის secret_token (A–Z a–z 0-9 _ -): ტოკენიდან HMAC — ცალკე ცვლადი/შენახვა არ სჭირდება."""
    return hmac.new(b"tgnet-webhook", (config.TGNET_BOT_TOKEN or "").encode(), hashlib.sha256).hexdigest()[:40]


def secret_ok(header: str) -> bool:
    return bool(config.TGNET_BOT_TOKEN) and hmac.compare_digest(str(header or ""), webhook_secret())


class Flow:
    def __init__(self, client, *, get_listing, notify=None, managers_for=None, crm2=None, agents=None, lang_default="ka"):
        self.c, self.get_listing = client, get_listing
        _n = notify or (lambda *a, **k: None)
        self.notify = lambda chat, text, key=None, reply_markup=None: _n(chat, re.sub(r"<[^>]+>", "", text), key=key, **({"reply_markup": reply_markup} if reply_markup else {}))      # შიდა ბოტის შეტყობინებები უბრალო ტექსტია (HTML ტეგები არ უნდა ჩანდეს)
        self.managers_for = managers_for or (lambda lst: [])
        self.agents = agents or (lambda: [])
        if crm2 is None:
            import crm2_store as crm2
        self.crm2 = crm2
        self.lang_default = lang_default
        self._seen: list = []

    # ---- დამხმარე
    def _lang(self, user: dict, hint: str = "") -> str:
        if hint in T:
            return hint
        lc = str((user or {}).get("language_code") or "").lower()[:2]
        return {"ka": "ka", "ru": "ru", "en": "en"}.get(lc, self.lang_default)

    def _say(self, chat, text, markup=None):
        try:
            self.c.call("sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview="true", reply_markup=markup)
        except Exception:  # noqa: BLE001 — კლიენტისთვის გაგზავნის ჩავარდნა სერვერს არ აჩერებს
            log.warning("TGNET ბოტი: პასუხი ვერ გაიგზავნა (%s)", chat, exc_info=True)

    @staticmethod
    def _name(user: dict) -> str:
        return " ".join(x for x in (str((user or {}).get("first_name") or ""), str((user or {}).get("last_name") or "")) if x).strip()[:80]

    # ---- მთავარი შესასვლელი
    def handle(self, update: dict) -> str:
        uid = update.get("update_id")
        if uid is not None:
            if uid in self._seen:
                return "duplicate"
            self._seen = (self._seen + [uid])[-300:]
        try:
            if "callback_query" in update:
                return self._callback(update["callback_query"])
            msg = update.get("message") or {}
            if not msg or (msg.get("chat") or {}).get("type") != "private":
                return "ignored"
            if msg.get("contact"):
                return self._contact(msg)
            text = str(msg.get("text") or "").strip()
            if text.startswith("/start"):
                return self._start(msg, text[6:].strip())
            if text:
                return self._text(msg, text)
        except Exception:  # noqa: BLE001
            log.exception("TGNET ბოტი: update-ის დამუშავება ვერ მოხერხდა")
            return "error"
        return "ignored"

    def _start(self, msg, payload: str) -> str:
        user, chat = msg.get("from") or {}, msg["chat"]["id"]
        mm = _PAYLOAD.match(payload) if payload else None
        lang = self._lang(user, (mm.group("lang") if mm else "") or "")
        if not mm:
            self._say(chat, T[lang]["plain"])
            return "plain"
        lid = mm.group("lid")
        lst = self.get_listing(lid)
        if not lst or str(lst.get("active") or "yes").lower() == "no":
            self._say(chat, T[lang]["nolist"])
            return "gone"
        st.add_lead_event("view", lid, user.get("id"), self._name(user))
        r = ct.render(lst, lang, cta=False)
        self._say(chat, T[lang]["hello"] + "\n\n" + r["text"], {"inline_keyboard": [[{"text": T[lang]["want"], "callback_data": f"want:{lid}:{lang}"[:64]}]]})
        return "start"

    def _callback(self, cb: dict) -> str:
        data, user = str(cb.get("data") or ""), cb.get("from") or {}
        chat = (cb.get("message") or {}).get("chat", {}).get("id") or user.get("id")
        try:
            self.c.call("answerCallbackQuery", callback_query_id=cb.get("id"))
        except Exception:  # noqa: BLE001
            pass
        parts = data.split(":")
        if len(parts) == 3 and parts[0] == "want":
            lid, lang = parts[1], parts[2] if parts[2] in T else self._lang(user)
            if not self.get_listing(lid):
                self._say(chat, T[lang]["nolist"])
                return "gone"
            st.add_lead_event("intent", lid, user.get("id"), self._name(user), note=lang)       # note = ენა (შემდეგ პასუხს იმავე ენაზე ვაგზავნით)
            self._say(chat, T[lang]["ask"], {"keyboard": [[{"text": T[lang]["share"], "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True})
            return "intent"
        return "ignored"

    def _contact(self, msg: dict) -> str:
        user = msg.get("from") or {}
        ct_ = msg["contact"]
        if ct_.get("user_id") and user.get("id") and ct_["user_id"] != user["id"]:
            return self._text(msg, "")           # სხვისი კონტაქტი — ნომრად არ ვიღებთ (ბოროტად გამოყენების/სპამის თავიდან ასაცილებლად)
        return self._lead(msg, str(ct_.get("phone_number") or ""))

    def _text(self, msg: dict, text: str) -> str:
        user = msg.get("from") or {}
        digits = re.sub(r"\D", "", text)
        if 9 <= len(digits) <= 13 and not re.search(r"[A-Za-zა-ჰА-я]{3,}", re.sub(r"\+|\s|-|\(|\)", "", text)):
            return self._lead(msg, text)
        lang = self._lang(user)
        if st.last_intent(user.get("id")):
            self._say(msg["chat"]["id"], T[lang]["bad"])
            return "bad_phone"
        self._say(msg["chat"]["id"], T[lang]["plain"])
        return "plain"

    def _lead(self, msg: dict, phone_raw: str) -> str:
        user, chat = msg.get("from") or {}, msg["chat"]["id"]
        intent = st.last_intent(user.get("id"))
        lang = self._lang(user, str((intent or {}).get("note") or ""))
        key = self.crm2.m.normalize_phone(phone_raw) if hasattr(self.crm2, "m") else re.sub(r"\D", "", phone_raw)
        if not key:
            self._say(chat, T[lang]["bad"])
            return "bad_phone"
        lid = (intent or {}).get("listing_key", "")
        lst = self.get_listing(lid) if lid else None
        name = self._name(user) or "Telegram კლიენტი"
        summary = st.listing_summary(lst) if lst else "ზოგადი მოთხოვნა"
        src = "telegram" + (f":{lid}" if lid else "")
        try:
            client_id, is_new = self.crm2.upsert_client(phone_raw, {"name": name, "source": src, "notes": f"Telegram: {summary}"[:300], "deal_type": str((lst or {}).get("deal_type") or "")}, by="tgnet")
            self.crm2.add_activity("client", client_id, "system", f"Telegram-იდან დაინტერესდა: {lid or '—'} · {summary}"[:300], source_ref=lid)
        except Exception:  # noqa: BLE001
            log.exception("TGNET: CRM-ში კლიენტის შექმნა ვერ მოხერხდა")
            client_id, is_new = "", False
        rec = st.add_lead_event("lead", lid, user.get("id"), name, phone_norm=key, client_id=client_id, note=("ახალი კლიენტი" if is_new else "არსებული კლიენტი"))
        self._say(chat, T[lang]["thanks"], {"remove_keyboard": True})
        owner = str((lst or {}).get("agent_name") or "—")
        text = (f"📥 <b>ახალი დაინტერესება Telegram-იდან</b>\n{summary}\n🆔 {lid or '—'} · ბინის აგენტი: {owner}\n👤 {name}\n📞 +{key if key.startswith('995') else '995' + key[-9:]}"
                f"{'' if is_new else chr(10) + 'ℹ️ ეს კლიენტი CRM-ში უკვე არსებობს'}\n\n👉 აპი → 📣 Telegram → ლიდები: მიაბით აგენტს")
        for chat_id in self.managers_for(lst or {}):
            try:
                self.notify(chat_id, text, key=f"tglead:{rec['lead_id']}:{chat_id}")
            except Exception:  # noqa: BLE001
                log.warning("TGNET: მენეჯერისთვის შეტყობინება ვერ გაიგზავნა (%s)", chat_id, exc_info=True)
        return "lead"

    def lead_from_app(self, user: dict, lid: str, phone: str, lang: str) -> str:
        """Mini App-იდან: ინტენტი + ლიდი ერთად (იგივე ჯაჭვი, რაც ბოტში)."""
        lang = lang if lang in T else self._lang(user)
        st.add_lead_event("view", lid, user.get("id"), self._name(user))
        st.add_lead_event("intent", lid, user.get("id"), self._name(user), note=lang)
        return self._lead({"from": dict(user, language_code=lang), "chat": {"id": user.get("id")}}, phone)


    # ---- აგენტის მხარე: ნახვა / დადასტურება / შედეგი (სავალდებულო follow-up)
    def lead_button(self, lead_id: str):
        """Mini App-ის ღილაკი შეტყობინებაზე: იხსნება აგენტის ლიდების ეკრანი (?tgl=<ლიდი>)."""
        return {"inline_keyboard": [[{"text": "👤 კლიენტის ნახვა", "web_app": {"url": f"{config.WEBAPP_URL.rstrip('/')}/?tgl={lead_id}"}}]]} if config.WEBAPP_URL else None

    def _lead_row(self, lead_id: str) -> dict:
        r = next((x for x in st.list_lead_rows(fresh=True) if x["lead_id"] == lead_id and x["kind"] == "lead"), None)
        if not r:
            raise st.TgnetError("ლიდი ვერ მოიძებნა", 404, "not_found")
        return r

    def _managers_text(self, lead: dict, text: str, tag: str) -> None:
        lst = self.get_listing(lead["listing_key"]) if lead["listing_key"] else None
        for chat_id in self.managers_for(lst or {}):
            try:
                self.notify(chat_id, text, key=f"tgmgr:{lead['lead_id']}:{tag}:{chat_id}")
            except Exception:  # noqa: BLE001
                log.warning("TGNET: მენეჯერისთვის უკუკავშირი ვერ გაიგზავნა", exc_info=True)

    def _agent_name(self, agent_id: str) -> str:
        return next((str(a.get("name") or "") for a in self.agents() if str(a.get("agent_id")) == str(agent_id)), "აგენტი")

    def _own(self, lead: dict, agent_id: str, manager: bool) -> None:
        if not manager and str(lead["assigned_agent_id"]) != str(agent_id):
            raise st.TgnetError("ეს ლიდი თქვენზე არ არის მიბმული", 403, "not_yours")

    def mark_seen(self, lead_id: str, agent_id: str, manager: bool = False) -> dict:
        """აგენტმა ბარათი გახსნა -> seen_at (პირველად) + მენეჯერს უკუკავშირი „ნახა, ჯერ არ დაუდასტურებია“."""
        lead = self._lead_row(lead_id)
        self._own(lead, agent_id, manager)
        if not lead["seen_at"] and not manager:
            st.update_lead(lead_id, {"seen_at": st.now_str()})
            self._managers_text(lead, f"👀 {self._agent_name(agent_id)}-მ ლიდი გახსნა (ჯერ არ დაუდასტურებია)\n{lead['tg_name'] or '—'}", "seen")
        return lead

    def agent_action(self, lead_id: str, agent_id: str, action: str, note: str = "", follow_up_at: str = "", manager: bool = False) -> dict:
        """ack | contacted | waiting | decline. contacted/waiting — **სავალდებულოა follow-up თარიღი** (CRM-ში follow-up იქმნება); decline — მიზეზი სავალდებულოა და ლიდი ისევ ახალია (მენეჯერს ეგზავნება)."""
        lead = self._lead_row(lead_id)
        self._own(lead, agent_id, manager)
        now = st.now_str()
        who = self._agent_name(lead["assigned_agent_id"] or agent_id)
        note = str(note or "").strip()[:300]
        if action == "ack":
            st.update_lead(lead_id, {"status": "acknowledged", "ack_at": now, "remind_count": "0", "last_remind_at": ""})
            self._managers_text(lead, f"✅ {who} ადასტურებს ლიდს: {lead['tg_name'] or '—'}", "ack")
            return {"status": "acknowledged"}
        if action in ("contacted", "waiting"):
            due = _parse_local(follow_up_at)
            if not due:
                raise st.TgnetError("Follow-up სავალდებულოა: მიუთითეთ შემდეგი კონტაქტის თარიღი და საათი", 400, "followup_required")
            if due < _parse_local(now) - datetime.timedelta(minutes=1):
                raise st.TgnetError("Follow-up წარსულში ვერ იქნება", 400, "followup_past")
            if action == "contacted" and not note:
                raise st.TgnetError("მოკლე შენიშვნა სავალდებულოა (რა შეთანხმდით)", 400, "note_required")
            if lead["client_id"]:
                try:
                    self.crm2.create_followup(lead["client_id"], str(lead["assigned_agent_id"] or agent_id), _to_utc_iso(due), note or "დარეკვა (Telegram ლიდი)", agent_name=who, by="tgnet")
                    self.crm2.add_activity("client", lead["client_id"], "call" if action == "contacted" else "note", (f"Telegram ლიდი: {note}" if note else "Telegram ლიდი: ვადა დაინიშნა")[:300], agent_id=str(agent_id), agent_name=who, source_ref=lead["listing_key"])
                except Exception:  # noqa: BLE001
                    log.exception("TGNET: follow-up CRM-ში ვერ შეიქმნა")
                    raise st.TgnetError("Follow-up CRM-ში ვერ შეიქმნა — სცადეთ ხელახლა", 500, "crm_failed")
            st.update_lead(lead_id, {"status": "contacted" if action == "contacted" else "waiting", "ack_at": lead["ack_at"] or now, "follow_up_at": due.strftime("%Y-%m-%d %H:%M"), "agent_note": note, "remind_count": "0", "last_remind_at": ""})
            self._managers_text(lead, f"📞 {who}: {'დაუკავშირდა კლიენტს' if action == 'contacted' else 'გადადო'} · follow-up {due.strftime('%d.%m %H:%M')}\n{lead['tg_name'] or '—'}" + (f"\n💬 {note}" if note else ""), action)
            return {"status": "contacted" if action == "contacted" else "waiting", "follow_up_at": due.strftime("%Y-%m-%d %H:%M")}
        if action == "decline":
            if not note:
                raise st.TgnetError("მიუთითეთ რატომ ვერ ასრულებთ", 400, "note_required")
            st.update_lead(lead_id, {"status": "new", "assigned_agent_id": "", "assigned_at": "", "seen_at": "", "ack_at": "", "remind_count": "0", "last_remind_at": "", "agent_note": f"უარი ({who}): {note}"})
            self._managers_text(lead, f"🚫 {who} ვერ იღებს ლიდს: {lead['tg_name'] or '—'}\nმიზეზი: {note}\n👉 აპი → Telegram → ლიდები: მიაბით სხვა აგენტს", "decline")
            return {"status": "new"}
        if action == "close":
            st.update_lead(lead_id, {"status": "closed", "closed_at": now, "agent_note": note or lead["agent_note"]})
            return {"status": "closed"}
        raise st.TgnetError("მოქმედება უცნობია", 400, "bad_action")

    def my_leads(self, agent_id: str) -> list[dict]:
        out = []
        for r in st.list_lead_rows(fresh=True):
            if r["kind"] != "lead" or str(r["assigned_agent_id"]) != str(agent_id) or r["status"] == "closed":
                continue
            lst = self.get_listing(r["listing_key"]) if r["listing_key"] else None
            out.append({"lead_id": r["lead_id"], "at": r["at"], "assigned_at": r["assigned_at"], "name": r["tg_name"], "phone": r["phone_norm"], "status": r["status"] or "new",
                        "summary": st.listing_summary(lst) if lst else "ზოგადი მოთხოვნა", "listing_key": r["listing_key"], "seen": bool(r["seen_at"]), "follow_up_at": r["follow_up_at"],
                        "agent_note": r["agent_note"], "client_id": r["client_id"]})
        out.sort(key=lambda x: ({"assigned": 0, "waiting": 1, "acknowledged": 2, "contacted": 3}.get(x["status"], 4), x["at"]))
        return out

    def close_many(self, lead_ids, viewer_team: str = "", admin: bool = True, by: str = "") -> dict:
        """მენეჯერი ერთიანად ხურავს (აქრობს ეკრანიდან) მონიშნულ ლიდებს (≤200). თიმლიდერი — მხოლოდ თავისი გუნდის ბინების ლიდებს. ერთი წაკითხვა; ჩანაწერი რჩება (closed)."""
        ids = {str(i) for i in (lead_ids or []) if str(i)}
        if not ids:
            raise st.TgnetError("აირჩიეთ ლიდი", 400, "nothing_selected")
        if len(ids) > 200:
            raise st.TgnetError("ერთდროულად მაქსიმუმ 200", 400, "too_many")
        now = st.now_str()
        n = skipped = 0
        for r in st.list_lead_rows(fresh=True):
            if r["lead_id"] not in ids or r["kind"] != "lead" or r["status"] == "closed":
                continue
            if not admin:
                lst = self.get_listing(r["listing_key"]) if r["listing_key"] else None
                if str((lst or {}).get("team") or "") != str(viewer_team or "__none__"):
                    skipped += 1
                    continue
            st.update_lead(r["lead_id"], {"status": "closed", "closed_at": now, "agent_note": (r["agent_note"] + f" | დახურა: {by}".rstrip())[:300] if by else r["agent_note"]})
            n += 1
        return {"closed": n, "skipped": skipped}

    # ---- მენეჯერის მიბმა (API-დან)
    def assign(self, lead_id: str, agent_id: str, by: str = "") -> dict:
        lead = next((r for r in st.list_lead_rows(fresh=True) if r["lead_id"] == lead_id and r["kind"] == "lead"), None)
        if not lead:
            raise st.TgnetError("ლიდი ვერ მოიძებნა", 404, "not_found")
        ag = next((a for a in self.agents() if str(a.get("agent_id")) == str(agent_id)), None)
        if not ag:
            raise st.TgnetError("აგენტი ვერ მოიძებნა", 404, "agent_not_found")
        st.update_lead(lead_id, {"status": "assigned", "assigned_agent_id": str(agent_id), "assigned_by": _short(by), "assigned_at": st.now_str(), "seen_at": "", "ack_at": "", "remind_count": "0", "last_remind_at": ""})
        if lead["client_id"]:
            try:
                self.crm2.update_client(lead["client_id"], {"assigned_agent_id": str(agent_id), "assigned_agent_name": str(ag.get("name") or ""), "team": str(ag.get("team") or "")})
                self.crm2.add_activity("client", lead["client_id"], "system", f"მენეჯერმა ({by or '—'}) მიაბა აგენტს: {ag.get('name')}", agent_id=str(agent_id), agent_name=str(ag.get("name") or ""), source_ref=lead["listing_key"])
            except Exception:  # noqa: BLE001
                log.exception("TGNET: კლიენტის აგენტზე მიბმა CRM-ში ვერ მოხერხდა")
        lst = self.get_listing(lead["listing_key"]) if lead["listing_key"] else None
        chat = ag.get("telegram_chat_id")
        if chat:
            phone = lead["phone_norm"]
            try:
                self.notify(int(chat), f"📞 <b>ახალი კლიენტი — Telegram</b>\n{st.listing_summary(lst) if lst else 'ზოგადი მოთხოვნა'}\n👤 {lead['tg_name'] or '—'}\n📱 +{phone if phone.startswith('995') else '995' + phone[-9:]}\n\n"
                            f"გახსენით ბარათი, დაადასტურეთ და მიუთითეთ შედეგი + follow-up (სავალდებულოა). დადასტურებამდე შეხსენება განმეორდება.", key=f"tgassign:{lead_id}:{agent_id}", reply_markup=self.lead_button(lead_id))
            except Exception:  # noqa: BLE001
                log.warning("TGNET: აგენტისთვის შეტყობინება ვერ გაიგზავნა", exc_info=True)
        return {"lead_id": lead_id, "agent_id": str(agent_id), "agent_name": str(ag.get("name") or "")}


def _short(s) -> str:
    return str(s or "")[:60]


def leads_view(get_listing, agents, viewer_team: str = "", admin: bool = True) -> dict:
    """მენეჯერის ეკრანი: ლიდები (ახლები ზევით) + „ყველაზე დაინტერესებული განცხადებები“. თიმლიდერი მხოლოდ თავისი გუნდის განცხადებებს ხედავს."""
    names = {str(a.get("agent_id")): str(a.get("name") or "") for a in agents()}
    out, rows = [], st.list_lead_rows(fresh=True)
    for r in rows:
        if r["kind"] != "lead" or r["status"] == "closed":          # დახურული (წაშლილი) ეკრანზე აღარ ჩანს — ჩანაწერი რჩება აუდიტისთვის
            continue
        lst = get_listing(r["listing_key"]) if r["listing_key"] else None
        if not admin and viewer_team and str((lst or {}).get("team") or "") != viewer_team:
            continue
        out.append({"lead_id": r["lead_id"], "at": r["at"], "listing_key": r["listing_key"], "summary": st.listing_summary(lst) if lst else "ზოგადი მოთხოვნა", "name": r["tg_name"], "phone": r["phone_norm"],
                    "status": r["status"] or "new", "client_id": r["client_id"], "listing_agent_id": str((lst or {}).get("agent_id") or ""), "listing_agent": str((lst or {}).get("agent_name") or ""),
                    "assigned": names.get(r["assigned_agent_id"], ""), "note": r["note"], "seen": bool(r["seen_at"]), "acked": bool(r["ack_at"]), "follow_up_at": r["follow_up_at"],
                    "agent_note": r["agent_note"], "assigned_at": r["assigned_at"], "status_label": m.LEAD_STATUS_LABELS.get(r["status"] or "new", r["status"])})
    out.sort(key=lambda x: (x["status"] != "new", x["at"]), reverse=False)
    out.sort(key=lambda x: x["at"], reverse=True)
    out.sort(key=lambda x: 0 if x["status"] == "new" else 1)
    top = []
    for a in st.interest_stats(40):
        lst = get_listing(a["listing_key"])
        if not admin and viewer_team and str((lst or {}).get("team") or "") != viewer_team:
            continue
        top.append(dict(a, summary=st.listing_summary(lst) if lst else a["listing_key"], agent=str((lst or {}).get("agent_name") or "")))
    return {"leads": out[:100], "top": top[:10], "agents": [{"agent_id": k, "name": v} for k, v in names.items()]}

def _parse_local(s):
    """„YYYY-MM-DD HH:MM“ (ან T-ით) -> datetime (თბილისის ადგილობრივი, naive); არასწორი -> None."""
    try:
        return datetime.datetime.strptime(str(s or "").strip().replace("T", " ")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _to_utc_iso(dt: datetime.datetime) -> str:
    return (dt - datetime.timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")            # თბილისი = UTC+4 (DST-ის გარეშე)


def sla_cycle(flow: "Flow", now: datetime.datetime | None = None) -> dict:
    """ლიდების ვადები. ახალი (მიუბმელი) ლიდი -> მენეჯერს შეხსენება; მიბმული და დაუდასტურებელი -> აგენტს განმეორებით შეხსენება + მენეჯერს უკუკავშირი; „მოგვიანებით/დაკავშირებული“
    follow-up-ის დროს -> აგენტს შეხსენება. განმეორება ≥TGNET_SLA_REPEAT_MIN წთ. აბრუნებს {manager, agent, feedback, followup}."""
    now = now or _parse_local(st.now_str())
    mgr_min, agent_min, rep = config.TGNET_SLA_MANAGER_MIN, config.TGNET_SLA_AGENT_MIN, config.TGNET_SLA_REPEAT_MIN
    rep_td = datetime.timedelta(minutes=rep)
    out = {"manager": 0, "agent": 0, "feedback": 0, "followup": 0}
    for r in st.list_lead_rows(fresh=True):
        if r["kind"] != "lead":
            continue
        status = r["status"] or "new"
        last = _parse_local(r["last_remind_at"])
        cnt = int(r["remind_count"] or 0) if str(r["remind_count"] or "0").isdigit() else 0
        if last and now - last < rep_td:
            continue
        label = r["tg_name"] or "—"
        try:
            if status == "new":
                at = _parse_local(r["at"])
                if at and now - at >= datetime.timedelta(minutes=mgr_min) and cnt < 8:
                    flow._managers_text(r, f"⏰ ლიდი {int((now - at).total_seconds() // 60)} წთ-ია ელოდება მიბმას: {label}\n👉 აპი → Telegram → ლიდები: მიაბით აგენტს", f"mgrsla{cnt}")
                    st.update_lead(r["lead_id"], {"last_remind_at": now.strftime("%Y-%m-%d %H:%M"), "remind_count": str(cnt + 1)})
                    out["manager"] += 1
            elif status == "assigned":
                base = _parse_local(r["assigned_at"]) or _parse_local(r["at"])
                if base and now - base >= datetime.timedelta(minutes=agent_min) and cnt < 12:
                    ag = r["assigned_agent_id"]
                    chat = next((a.get("telegram_chat_id") for a in flow.agents() if str(a.get("agent_id")) == str(ag)), None)
                    mins = int((now - base).total_seconds() // 60)
                    if chat:
                        flow.notify(int(chat), f"⏰ დაუდასტურებელი კლიენტი ({mins} წთ): {label}\nგახსენით ბარათი და დაადასტურეთ.", key=f"tgagsla:{r['lead_id']}:{cnt}", reply_markup=flow.lead_button(r["lead_id"]))
                        out["agent"] += 1
                    if cnt in (0, 3, 8):          # მენეჯერს უკუკავშირი: პირველი შეხსენება, მერე ესკალაცია
                        flow._managers_text(r, f"⚠️ {flow._agent_name(ag)} ({mins} წთ) ჯერ არ აქცევს ყურადღებას ლიდს: {label}" + ("\n👀 ბარათი გაიხსნა, მაგრამ არ დაუდასტურებია" if r["seen_at"] else "\n👁 ბარათი ჯერ არ გაუხსნია") + ("\n👉 საჭიროების შემთხვევაში მიაბით სხვას" if cnt else ""), f"agsla{cnt}")
                        out["feedback"] += 1
                    st.update_lead(r["lead_id"], {"last_remind_at": now.strftime("%Y-%m-%d %H:%M"), "remind_count": str(cnt + 1)})
            elif status in ("waiting", "contacted"):
                due = _parse_local(r["follow_up_at"])
                if due and now >= due and cnt < 6:
                    ag = r["assigned_agent_id"]
                    chat = next((a.get("telegram_chat_id") for a in flow.agents() if str(a.get("agent_id")) == str(ag)), None)
                    if chat:
                        flow.notify(int(chat), f"📅 Follow-up-ის დროა: {label}" + (f"\n💬 {r['agent_note']}" if r["agent_note"] else ""), key=f"tgfu:{r['lead_id']}:{cnt}", reply_markup=flow.lead_button(r["lead_id"]))
                        out["followup"] += 1
                    st.update_lead(r["lead_id"], {"last_remind_at": now.strftime("%Y-%m-%d %H:%M"), "remind_count": str(cnt + 1)})
        except Exception:  # noqa: BLE001 — ერთი ლიდის ჩავარდნა დანარჩენს არ აჩერებს
            log.exception("TGNET SLA: ლიდის დამუშავება ვერ მოხერხდა (%s)", r.get("lead_id"))
    return out
