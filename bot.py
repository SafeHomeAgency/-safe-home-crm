# -*- coding: utf-8 -*-
"""
Safe Home Agency — აგენტების ტასკ-მენეჯმენტის Telegram ბოტი.

მართავს ტასკებს Google Sheets-ის საშუალებით:
  - ადმინი (ლაშა) ქმნის ტასკებს ბოტში ან პირდაპირ ცხრილში
  - აგენტი იღებს შეტყობინებას Telegram-ზე, ხედავს თავის ტასკებს, /done -ით ხურავს
  - ადმინს ყოველდღე დილით მიდის მოკლე რეპორტი

გაშვება: python bot.py   (საჭირო env ცვლადებისთვის იხ. README.md)
"""

from __future__ import annotations

import logging

from telegram import (
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, CallbackQueryHandler, filters,
)

import config
import sheets

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("safehome-crm-bot")

# ---- /newtask (ლიდის მიღების) საუბრის საფეხურები ----
(
    NL_TYPE, NL_GEN_PHONE, NL_GEN_DEAL, NL_GEN_PRIORITY,
    NL_LISTING_AGENT, NL_LISTING_ID, NL_LISTING_PHONE, NL_LISTING_TIME,
) = range(8)
# ---- /addagent საუბრის საფეხურები ----
AA_NAME, AA_PHONE = range(8, 10)

PRIORITY_LABELS = ("დაბალი", "საშუალო", "მაღალი")


def is_admin(chat_id: int) -> bool:
    return chat_id in config.ADMIN_CHAT_IDS


# ---------------------------------------------------------------- /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if is_admin(chat_id):
        await update.message.reply_text(
            "მოგესალმებით, ადმინო! ბრძანებები:\n"
            "/newtask — ახალი კლიენტის დამატება\n"
            "/agents — აგენტების სია\n"
            "/addagent — ახალი აგენტის დამატება\n"
            "/report — დღევანდელი რეპორტი\n"
            "/ranking — აგენტების რეიტინგი (ბოლო 30 დღე)"
        )
        return

    agent = sheets.find_agent_by_chat_id(chat_id)
    if agent:
        await update.message.reply_text(
            f"გამარჯობა, {agent['name']}! /mytasks — შენი დავალებების სანახავად."
        )
        return

    button = KeyboardButton(text="📱 ნომრის გაზიარება", request_contact=True)
    await update.message.reply_text(
        "მოგესალმებით! რეგისტრაციისთვის გამიზიარეთ თქვენი ტელეფონის ნომერი "
        "(იგივე, რაც ადმინთან გაქვთ დარეგისტრირებული).",
        reply_markup=ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True),
    )


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    chat_id = update.effective_chat.id
    if contact.user_id and contact.user_id != update.effective_user.id:
        await update.message.reply_text("გთხოვთ, გააზიაროთ საკუთარი ნომერი.")
        return

    agent = sheets.find_agent_by_phone(contact.phone_number)
    if not agent:
        await update.message.reply_text(
            "ეს ნომერი ცხრილში ვერ ვიპოვე. სთხოვეთ ადმინს დაგამატოთ (/addagent) და სცადეთ თავიდან.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    sheets.register_agent_chat_id(
        agent["agent_id"], chat_id, update.effective_user.username or ""
    )
    await update.message.reply_text(
        f"რეგისტრაცია დასრულდა, {agent['name']}! /mytasks — დავალებების სანახავად.",
        reply_markup=ReplyKeyboardRemove(),
    )


# -------------------------------------------------------------- /mytasks
async def mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    agent = sheets.find_agent_by_chat_id(chat_id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return

    tasks = sheets.get_tasks_for_agent(agent["agent_id"])
    if not tasks:
        await update.message.reply_text("გახსნილი დავალებები არ გაქვთ. 🎉")
        return

    lines = ["თქვენი ღია დავალებები:\n"]
    for t in tasks:
        extra = ""
        if t.get("client_phone"):
            extra += f"\n   კლიენტი: {t['client_phone']}"
        if t.get("viewing_time"):
            extra += f"\n   ნახვა: {t['viewing_time']}"
        lines.append(
            f"🔹 [{t['task_id']}] {t['title']}\n"
            f"   სტატუსი: {t['status']} | პრიორიტეტი: {t.get('priority') or '-'} | ვადა: {t.get('due_date') or '-'}"
            f"{extra}\n"
            f"   დახურვა: /done_{t['task_id']}"
        )
    await update.message.reply_text("\n\n".join(lines))


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    task_id = None
    if text.startswith("/done_"):
        task_id = text[len("/done_"):]
    elif context.args:
        task_id = context.args[0]

    if not task_id:
        await update.message.reply_text("გამოყენება: /done <task_id> (ან დააჭირეთ /done_XXXXXXXX ლინკს /mytasks-დან)")
        return

    ok = sheets.mark_task_done(task_id)
    if ok:
        await update.message.reply_text(f"✅ დავალება {task_id} დახურულია.")
    else:
        await update.message.reply_text("ასეთი task_id ვერ ვიპოვე.")


# -------------------------------------------------------------- /agents (admin)
async def agents_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    agents = sheets.get_agents()
    if not agents:
        await update.message.reply_text("აგენტები ჯერ არ დამატებულა. /addagent")
        return
    lines = []
    for a in agents:
        status = "✅ დარეგისტრირებული" if a.get("telegram_chat_id") else "⏳ ელოდება რეგისტრაციას"
        lines.append(f"• {a['name']} ({a['phone']}) — {status}")
    await update.message.reply_text("\n".join(lines))


# ----------------------------------------------------------- /addagent (admin)
async def addagent_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return ConversationHandler.END
    await update.message.reply_text("ახალი აგენტის სახელი?")
    return AA_NAME


async def addagent_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["aa_name"] = update.message.text.strip()
    await update.message.reply_text("ტელეფონის ნომერი? (მაგ. +995555123456)")
    return AA_PHONE


async def addagent_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    name = context.user_data.pop("aa_name")
    agent_id = sheets.add_agent(name, phone)
    await update.message.reply_text(
        f"დამატებულია: {name} ({phone}), agent_id={agent_id}.\n"
        f"აგენტმა უნდა დაწეროს ბოტს /start და გაუზიაროს ნომერი."
    )
    return ConversationHandler.END


# ------------------------------------------------------------- /newtask (admin)
# ორი ტიპის ლიდი:
#   1) "ზოგადი" — ვიცით მხოლოდ ტელეფონი და ქირა/ყიდვა. აგენტი აირჩევა
#      ავტომატურად, ბოლო 30 დღის შესრულების მაჩვენებლის მიხედვით:
#      მაღალი პრიორიტეტი -> საუკეთესო აგენტთან, საშუალო -> ყველაზე სუსტთან.
#   2) "ლისტინგი" — კონკრეტული აგენტის უკვე გამოქვეყნებულ ბინაზე მოსული
#      კლიენტი (ნახვის მოთხოვნა) — პირდაპირ იმ აგენტს ერგება.

async def newtask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton("ზოგადი კლიენტი (ქირა/ყიდვა)", callback_data="nl_type:general")],
        [InlineKeyboardButton("კონკრეტული ბინა (ნახვა)", callback_data="nl_type:listing")],
    ]
    await update.message.reply_text(
        "რა ტიპის კლიენტია?", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return NL_TYPE


async def newtask_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lead_type = query.data.split(":", 1)[1]
    context.user_data["nl_type"] = lead_type

    if lead_type == "general":
        await query.edit_message_text("კლიენტის ტელეფონის ნომერი?")
        return NL_GEN_PHONE

    agents = [a for a in sheets.get_agents() if str(a.get("active", "")).lower() != "no"]
    if not agents:
        await query.edit_message_text("აგენტები არ არსებობს. ჯერ დაამატეთ /addagent-ით.")
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(a["name"], callback_data=f"nl_lagent:{a['agent_id']}")]
        for a in agents
    ]
    await query.edit_message_text(
        "რომელი აგენტის ბინაზეა (ვისი ლისტინგია)?", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return NL_LISTING_AGENT


# ---- ზოგადი კლიენტის შტო ----

async def newtask_gen_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nl_phone"] = update.message.text.strip()
    buttons = [[
        InlineKeyboardButton("ქირა", callback_data="nl_deal:ქირა"),
        InlineKeyboardButton("ყიდვა", callback_data="nl_deal:ყიდვა"),
    ]]
    await update.message.reply_text("გარიგების ტიპი?", reply_markup=InlineKeyboardMarkup(buttons))
    return NL_GEN_DEAL


async def newtask_gen_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["nl_deal"] = query.data.split(":", 1)[1]
    buttons = [[InlineKeyboardButton(p, callback_data=f"nl_priority:{p}")] for p in PRIORITY_LABELS]
    await query.edit_message_text("პრიორიტეტი?", reply_markup=InlineKeyboardMarkup(buttons))
    return NL_GEN_PRIORITY


async def newtask_gen_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    priority = query.data.split(":", 1)[1]
    d = context.user_data

    agent_id = sheets.pick_agent_for_priority(priority)
    if not agent_id:
        await query.edit_message_text(
            "დარეგისტრირებული (Telegram-ში /start-გავლილი) აქტიური აგენტი არ მოიძებნა."
        )
        d.clear()
        return ConversationHandler.END

    title = f"კლიენტი {d['nl_phone']} ({d['nl_deal']})"
    task_id = sheets.create_task(
        title=title, description="", assigned_to=agent_id, priority=priority,
        due_date="", created_by=str(update.effective_user.id),
        lead_type="general", client_phone=d["nl_phone"], deal_type=d["nl_deal"],
    )
    agent_name = next(
        (a["name"] for a in sheets.get_agents() if a["agent_id"] == agent_id), agent_id
    )
    await query.edit_message_text(
        f"შექმნილია და მინიჭებულია {agent_name}-ზე (id: {task_id}, პრიორიტეტი: {priority}).\n"
        f"შეტყობინება მიუვა ~{config.POLL_INTERVAL_SECONDS}წმ-ში."
    )
    d.clear()
    return ConversationHandler.END


# ---- ლისტინგის (ნახვის) შტო ----

async def newtask_listing_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["nl_listing_agent"] = query.data.split(":", 1)[1]
    await query.edit_message_text("ლისტინგის/ბინის ID?")
    return NL_LISTING_ID


async def newtask_listing_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nl_listing_id"] = update.message.text.strip()
    await update.message.reply_text("კლიენტის ტელეფონის ნომერი?")
    return NL_LISTING_PHONE


async def newtask_listing_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nl_listing_phone"] = update.message.text.strip()
    await update.message.reply_text("ნახვის დრო? (მაგ. 'ხვალ 12:00')")
    return NL_LISTING_TIME


async def newtask_listing_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    viewing_time = update.message.text.strip()
    d = context.user_data
    agent_id = d["nl_listing_agent"]

    title = f"ნახვა: {d['nl_listing_id']}"
    description = f"ნახვის დრო: {viewing_time}"
    task_id = sheets.create_task(
        title=title, description=description, assigned_to=agent_id,
        priority="მაღალი", due_date=viewing_time,
        created_by=str(update.effective_user.id),
        lead_type="listing", client_phone=d["nl_listing_phone"],
        listing_id=d["nl_listing_id"], viewing_time=viewing_time,
    )
    agent_name = next(
        (a["name"] for a in sheets.get_agents() if a["agent_id"] == agent_id), agent_id
    )
    await update.message.reply_text(
        f"შექმნილია და მინიჭებულია {agent_name}-ზე (id: {task_id}).\n"
        f"შეტყობინება მიუვა ~{config.POLL_INTERVAL_SECONDS}წმ-ში."
    )
    d.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("გაუქმდა.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def busy_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ჯერ უპასუხეთ წინა შეკითხვას, ან დაწერეთ /cancel მიმდინარე ნაბიჯის გასაუქმებლად."
    )
    return None


# -------------------------------------------------------------- /report (admin)
def _build_report_text() -> str:
    tasks = sheets.get_tasks()
    agents = {a["agent_id"]: a["name"] for a in sheets.get_agents()}
    new_ = [t for t in tasks if t["status"] == "New"]
    in_progress = [t for t in tasks if t["status"] == "InProgress"]
    done = [t for t in tasks if t["status"] == "Done"]

    lines = [
        "📊 დღევანდელი რეპორტი",
        f"ახალი: {len(new_)} | მუშავდება: {len(in_progress)} | დასრულებული: {len(done)}",
        "",
    ]
    open_tasks = [t for t in tasks if t["status"] != "Done"]
    if open_tasks:
        lines.append("ღია დავალებები აგენტების მიხედვით:")
        by_agent: dict[str, list] = {}
        for t in open_tasks:
            by_agent.setdefault(t.get("assigned_to", ""), []).append(t)
        for agent_id, ts in by_agent.items():
            name = agents.get(agent_id, agent_id or "(მიუნიჭებელი)")
            lines.append(f"• {name}: {len(ts)}")
    else:
        lines.append("ღია დავალება არ არის. 🎉")
    return "\n".join(lines)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    await update.message.reply_text(_build_report_text())


# -------------------------------------------------------------- /ranking (admin)
async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    perf = sheets.get_agent_performance(30)
    agents = {a["agent_id"]: a["name"] for a in sheets.get_agents()}

    if not perf:
        await update.message.reply_text("ბოლო 30 დღეში მინიჭებული დავალება არცერთ აგენტს არ ჰქონია.")
        return

    rows = []
    for agent_id, s in perf.items():
        name = agents.get(agent_id, agent_id)
        rate = s["rate"]
        rate_str = f"{rate * 100:.0f}%" if rate is not None else "-"
        rows.append((rate if rate is not None else -1, name, s["assigned"], s["on_time"], rate_str))
    rows.sort(key=lambda r: r[0], reverse=True)

    lines = ["🏆 აგენტების რეიტინგი (ბოლო 30 დღე, 24სთ-ში დახურვის %):", ""]
    for _, name, assigned, on_time, rate_str in rows:
        lines.append(f"• {name}: {rate_str} ({on_time}/{assigned} დროულად)")
    await update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------ background jobs
async def check_new_tasks(context: ContextTypes.DEFAULT_TYPE):
    try:
        pending = sheets.get_unnotified_tasks()
    except Exception:
        log.exception("ცხრილის შემოწმება ვერ მოხერხდა")
        return

    if not pending:
        return

    agents_by_id = {a["agent_id"]: a for a in sheets.get_agents()}
    for t in pending:
        agent = agents_by_id.get(str(t.get("assigned_to")))
        if agent and agent.get("telegram_chat_id"):
            try:
                extra = ""
                if t.get("client_phone"):
                    extra += f"\nკლიენტი: {t['client_phone']}"
                if t.get("viewing_time"):
                    extra += f"\nნახვის დრო: {t['viewing_time']}"
                await context.bot.send_message(
                    chat_id=int(agent["telegram_chat_id"]),
                    text=(
                        f"🆕 ახალი დავალება: {t['title']}\n"
                        f"{t.get('description') or ''}"
                        f"{extra}\n"
                        f"პრიორიტეტი: {t.get('priority') or '-'} | ვადა: {t.get('due_date') or '-'}\n"
                        f"დახურვა: /done_{t['task_id']}"
                    ),
                )
                sheets.mark_task_notified(t["task_id"])
            except Exception:
                log.exception("შეტყობინების გაგზავნა ვერ მოხერხდა agent_id=%s", t.get("assigned_to"))
        else:
            # აგენტი ჯერ არაა დარეგისტრირებული ტელეგრამში — მოგვიანებით ისევ ვცდით
            pass


async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    text = _build_report_text()
    for admin_id in config.ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            log.exception("დღიური რეპორტის გაგზავნა ვერ მოხერხდა admin=%s", admin_id)


def main():
    config.validate()
    sheets.ensure_sheets()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(CommandHandler("mytasks", mytasks))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/done_\S+"), done_command))
    app.add_handler(CommandHandler("agents", agents_list))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("ranking", ranking))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addagent", addagent_start)],
        states={
            AA_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addagent_name)],
            AA_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addagent_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("newtask", newtask_start)],
        states={
            NL_TYPE: [CallbackQueryHandler(newtask_type, pattern=r"^nl_type:")],
            NL_GEN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newtask_gen_phone)],
            NL_GEN_DEAL: [CallbackQueryHandler(newtask_gen_deal, pattern=r"^nl_deal:")],
            NL_GEN_PRIORITY: [CallbackQueryHandler(newtask_gen_priority, pattern=r"^nl_priority:")],
            NL_LISTING_AGENT: [CallbackQueryHandler(newtask_listing_agent, pattern=r"^nl_lagent:")],
            NL_LISTING_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, newtask_listing_id)],
            NL_LISTING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newtask_listing_phone)],
            NL_LISTING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, newtask_listing_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    if app.job_queue:
        app.job_queue.run_repeating(check_new_tasks, interval=config.POLL_INTERVAL_SECONDS, first=10)
        app.job_queue.run_daily(
            send_daily_report,
            time=__import__("datetime").time(hour=config.DAILY_REPORT_HOUR, tzinfo=__import__("zoneinfo").ZoneInfo(config.TIMEZONE)),
        )

    log.info("ბოტი გაშვებულია...")
    app.run_polling()


if __name__ == "__main__":
    main()
