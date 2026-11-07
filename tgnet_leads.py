"""
TGNET: საჯარო ბოტი (@SafeHomeGeBot) და ლიდები. პოსტის ღილაკი -> ბოტი -> განცხადების დეტალები -> „მინდა დაკავშირება“ -> ნომერი -> CRM-ში კლიენტი + მენეჯერს შეტყობინება ->
მენეჯერი აპიდან აბამს განცხადების აგენტს (ან სხვას) -> აგენტს მიდის მოთხოვნა. ყოველი დაინტერესება ითვლება: რომელი ბინით არიან ყველაზე მეტად დაინტერესებულები.

უსაფრთხოება: webhook-ს ამოწმებს საიდუმლო (Telegram `secret_token`, ტოკენისგან გამოყვანილი — ცალკე არსად ინახება); განმეორებითი update_id იგნორირდება;
კლიენტს ვუგზავნით მხოლოდ საჯარო მონაცემს (არა მესაკუთრის ნომერს/შენიშვნას); მენეჯერს ვუგზავნით კლიენტის სახელს/ნომერს მხოლოდ შიდა ბოტით (არა საჯარო არხში);
კლიენტის შეტყობინებით არაფერი სრულდება — მხოლოდ ჩანაწერი/შეტყობინება. ჩავარდნა ბოტს არ აჩერებს.
"""

from __future__ import annotations

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
        self.notify = lambda chat, text, key=None: _n(chat, re.sub(r"<[^>]+>", "", text), key=key)      # შიდა ბოტის შეტყობინებები უბრალო ტექსტია (HTML ტეგები არ უნდა ჩანდეს)
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

    # ---- მენეჯერის მიბმა (API-დან)
    def assign(self, lead_id: str, agent_id: str, by: str = "") -> dict:
        lead = next((r for r in st.list_lead_rows(fresh=True) if r["lead_id"] == lead_id and r["kind"] == "lead"), None)
        if not lead:
            raise st.TgnetError("ლიდი ვერ მოიძებნა", 404, "not_found")
        ag = next((a for a in self.agents() if str(a.get("agent_id")) == str(agent_id)), None)
        if not ag:
            raise st.TgnetError("აგენტი ვერ მოიძებნა", 404, "agent_not_found")
        st.update_lead(lead_id, {"status": "assigned", "assigned_agent_id": str(agent_id), "assigned_by": _short(by)})
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
                            f"დარეკეთ და მიუთითეთ შედეგი CRM-ში (კლიენტი უკვე შეყვანილია).", key=f"tgassign:{lead_id}:{agent_id}")
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
        if r["kind"] != "lead":
            continue
        lst = get_listing(r["listing_key"]) if r["listing_key"] else None
        if not admin and viewer_team and str((lst or {}).get("team") or "") != viewer_team:
            continue
        out.append({"lead_id": r["lead_id"], "at": r["at"], "listing_key": r["listing_key"], "summary": st.listing_summary(lst) if lst else "ზოგადი მოთხოვნა", "name": r["tg_name"], "phone": r["phone_norm"],
                    "status": r["status"] or "new", "client_id": r["client_id"], "listing_agent_id": str((lst or {}).get("agent_id") or ""), "listing_agent": str((lst or {}).get("agent_name") or ""),
                    "assigned": names.get(r["assigned_agent_id"], ""), "note": r["note"]})
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
