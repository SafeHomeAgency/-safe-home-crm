"""
Property Hub — შეხვედრების ავტომატური შეხსენებები (ბოტის JobQueue-დან; ლოგიკა აქ, რომ ტესტირებადი იყოს).

  * შეხვედრამდე ~90 წუთით ადრე (დაგეგმილზე): აგენტს (+ მფლობელ აგენტს თანამშრომლობისას) მიდის შეხსენება ბინის/კლიენტის დეტალებით;
  * შეხვედრიდან 3+ საათის მერე, თუ ისევ "planned"-ია: აგენტს ეხსენება შედეგის ჩაწერა (მონაცემების ხარისხი — სტატისტიკა ზუსტი რომ იყოს).
ერთი და იგივე შეტყობინება ორჯერ არ იგზავნება (`reminded` / `nudged` ნიშნები იწერება მხოლოდ წარმატებული გაგზავნის მერე).
"""

from __future__ import annotations

import datetime

import hubmeet_model as m
import hubmeet_store as store

REMIND_MIN, REMIND_MAX_MIN = 0, 90          # შეხვედრამდე დარჩენილი წუთები: (0, 90]
NUDGE_AFTER_H = 3


def _when(h: dict) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(f"{m.s(h.get('meeting_date'))} {m.s(h.get('meeting_time'))}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _chat(agents: list, aid) -> int | None:
    a = next((x for x in agents if str(x.get("agent_id")) == str(aid)), None)
    try:
        return int(a.get("telegram_chat_id")) if a and a.get("telegram_chat_id") else None
    except (TypeError, ValueError):
        return None


def pending_notifications(get_agents, now: datetime.datetime | None = None) -> list[dict]:
    """აბრუნებს [{hub_id, flag, chat_id, text}] — გასაგზავნ შეტყობინებებს; გაგზავნის მერე `mark_sent`."""
    now = now or store.now_dt()
    agents = get_agents()
    out: list[dict] = []
    for h in store.all_rows(fresh=True):
        if m.s(h.get("status")) != m.PLANNED:
            continue
        w = _when(h)
        if not w:
            continue
        mins = (w - now).total_seconds() / 60.0
        rent = "ქირ" in m.s(h.get("deal_type"))
        base = (f"🏠 {m.s(h.get('listing_title')) or 'ბინა'} · {m.s(h.get('district'))} {m.s(h.get('address'))}\n"
                f"💰 ${m.s(h.get('price_usd')) or '—'}{'/თვე' if rent else ''}\n👤 კლიენტი: {m.s(h.get('client_name'))}")
        if m.s(h.get("reminded")) != "yes" and REMIND_MIN < mins <= REMIND_MAX_MIN:
            for aid, with_phone in ((h.get("requester_agent_id"), True), (h.get("owner_agent_id") if m.s(h.get("coop")) else "", False)):
                cid = _chat(agents, aid) if aid else None
                if cid:
                    txt = f"⏰ შეხვედრა {m.s(h.get('meeting_time'))}-ზე (≈{int(mins)} წთ)\n{base}" + (f" · {m.s(h.get('client_phone'))}" if with_phone else "")
                    if with_phone and h.get("rental_months"):
                        txt += f"\n⏳ პერიოდი: {m.s(h.get('rental_months'))} თვე"
                    if h.get("owner_availability"):
                        txt += f"\n🕒 მეპატრონე: {m.s(h.get('owner_availability'))}"
                    out.append({"hub_id": h["hub_id"], "flag": "reminded", "chat_id": cid, "text": txt})
        if m.s(h.get("nudged")) != "yes" and mins < -NUDGE_AFTER_H * 60:
            cid = _chat(agents, h.get("requester_agent_id"))
            if cid:
                out.append({"hub_id": h["hub_id"], "flag": "nudged", "chat_id": cid,
                            "text": f"📝 როგორ ჩაიარა შეხვედრამ ({m.s(h.get('meeting_date'))} {m.s(h.get('meeting_time'))})?\n{base}\n"
                                    "Mini App → განცხადებები → შეხვედრები → „ჩატარდა“ ან „არ მოვიდა“."})
    return out


def mark_sent(it: dict) -> None:
    with store._lock:  # noqa: SLF001
        store._backend.update(m.HUB_MEETINGS_SHEET, m.HM_HEADERS, it["hub_id"], {it["flag"]: "yes", "updated_at": store.now_str()})  # noqa: SLF001
