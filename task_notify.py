"""
კლიენტის/დავალების გადაბარების შეტყობინებები — ერთი წყარო ბოტისა (ასინქრონული) და Mini App-ის
სერვერისთვის (სინქრონული), რომ ტექსტი/მიმღებები ორ ადგილას არ იყოს გადაწერილი და არ გაიშალოს.

წესები ("არცერთი კლიენტი არ უნდა დაიკარგოს"):
  * აგენტს შეტყობინება ყოველთვის "✅ მივიღე კლიენტი" ღილაკით მიდის (ახალი და გადაბარებულიც);
  * დადასტურებისას მენეჯერს (შემქმნელს) ეცნობება; თუ შემქმნელი ადმინია ან მიუწვდომელია — ადმინებს;
    აგენტის თიმლიდერიც ყოველთვის იღებს; იგივე ადამიანს ორჯერ არ ეგზავნება;
  * ვერგაგზავნილი (აგენტს ტელეგრამი არ აქვს/ვერ მიდის) და დაუდასტურებელი კლიენტი — შეხსენება
    აგენტს და ესკალაცია მენეჯერს (იხ. bot.check_task_followups).
"""

from __future__ import annotations

CONFIRM_TEXT = "✅ მივიღე კლიენტი"


def confirm_markup(task_id: str) -> dict:
    """Telegram Bot API-ის JSON ფორმა (Mini App-ის სერვერისთვის); ბოტი იგივე callback_data-ს იყენებს."""
    return {"inline_keyboard": [[{"text": CONFIRM_TEXT, "callback_data": f"taskseen:{task_id}"}]]}


def assignment_text(t: dict, header: str = "🆕 ახალი დავალება") -> str:
    title = str(t.get("title") or "")
    extra = ""
    phone = str(t.get("client_phone") or "").strip()
    if phone and phone not in title:
        extra += f"\nკლიენტი: {phone}"
    if str(t.get("owner_phone") or "").strip():
        extra += f"\nმესაკუთრე: {t['owner_phone']}"
    if t.get("viewing_time"):
        extra += f"\nნახვის დრო: {t['viewing_time']}"
    details = str(t.get("description") or "").strip()
    details_line = f"\n📝 დეტალი: {details}" if details else ""
    return (
        f"{header}: {title}{extra}{details_line}\n"
        f"პრიორიტეტი: {t.get('priority') or '-'} | ვადა: {t.get('due_date') or '-'}\n"
        f"დახურვა: /done_{t.get('task_id')}\n"
        f"👇 დააჭირეთ დასადასტურებლად, რომ კლიენტი მიიღეთ."
    )


def manager_recipients(row: dict, agent: dict, agents: list[dict], admin_ids) -> list[int]:
    """ვის უნდა ეცნობოს ამ კლიენტის დადასტურება/დაუდასტურებლობა (chat_id-ების უნიკალური სია)."""
    out: list[int] = []

    def add(chat):
        try:
            c = int(str(chat).strip())
        except (TypeError, ValueError):
            return
        if c not in out:
            out.append(c)

    created_by = str(row.get("created_by") or "")
    creator = next((a for a in agents if str(a.get("agent_id")) == created_by), None) if created_by and created_by != "admin" else None
    creator_ok = bool(creator and str(creator.get("telegram_chat_id") or "").strip())
    if creator_ok:
        add(creator["telegram_chat_id"])
    team = str((agent or {}).get("team", "")).strip()
    if team:
        for a in agents:
            if (str(a.get("role", "")).strip() == "team_lead" and str(a.get("team", "")).strip() == team
                    and str(a.get("agent_id")) != str((agent or {}).get("agent_id"))
                    and str(a.get("active", "yes")).strip().lower() not in ("no", "false", "0")
                    and str(a.get("telegram_chat_id") or "").strip()):
                add(a["telegram_chat_id"])
    if created_by == "admin" or not creator_ok:
        for cid in admin_ids:
            add(cid)
    return out


def ack_text(agent: dict, row: dict) -> str:
    return f"✅ {agent.get('name')} დაადასტურა კლიენტის მიღება: {row.get('title')}"
