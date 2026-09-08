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

import datetime
import logging
from zoneinfo import ZoneInfo

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
AA_NAME, AA_PHONE, AA_TEAM = range(8, 11)
# ---- /clientreport (ყოფილი "AgentReports" ფორმა) საუბრის საფეხურები ----
RP_PHONE, RP_ACTIONS, RP_NOTES = range(11, 14)
# ---- /dayoff საუბრის საფეხურები ----
DO_DATE, DO_REASON = range(14, 16)
# ---- /meeting (ყოფილი "შეხვედრები" ფორმა) — ერთი state, სვეტების ჯაჭვით ----
(MT_FIELD,) = range(16, 17)
# ---- /setschedule (admin) საუბრის საფეხურები ----
SC_AGENT, SC_DAY = range(17, 19)
# ---- /clockout (agent) — დღიური რაოდენობის კითხვა ----
(CO_COUNT,) = range(19, 20)

PRIORITY_LABELS = ("დაბალი", "საშუალო", "მაღალი")

WEEKDAY_LABELS = [
    ("mon", "ორშაბათი"), ("tue", "სამშაბათი"), ("wed", "ოთხშაბათი"),
    ("thu", "ხუთშაბათი"), ("fri", "პარასკევი"), ("sat", "შაბათი"), ("sun", "კვირა"),
]
SCHEDULE_MODES = [
    ("off", "დასვენება"),
    ("office_morning", "ოფისი 10:00–16:00"),
    ("office_evening", "ოფისი 16:00–22:00"),
    ("online", "ონლაინ (სახლიდან)"),
]
SCHEDULE_MODE_LABELS = dict(SCHEDULE_MODES)

# შეგიძლიათ თავისუფლად შეცვალოთ/დაამატოთ პუნქტები, რომ ზუსტად თქვენი
# ძველი "AgentReports" ფორმის checkbox-ებს დაემთხვეს.
REPORT_ACTIONS = [
    "დარეკვა",
    "ბინის ჩვენება/ნახვა",
    "წინადადება გაიგზავნა",
    "მოლაპარაკება",
    "გარიგება დაიხურა",
    "არ პასუხობს",
    "არ არის დაინტერესებული",
]

# ყოფილი Slack "შეხვედრები" ფორმის ველები — თანმიმდევრობით ისე ეკითხება
# აგენტს, ერთი-ერთზე. (key, კითხვა). agent_id/agent_name/agent_phone
# ავტომატურად ივსება რეგისტრირებული აგენტის მონაცემებით — არ ეკითხებით.
MEETING_FIELDS = [
    ("owner_phone", "მეპატრონის ნომერი?"),
    ("myhome_link", "myhome ბმული? (თუ არ არის — დაწერეთ „-“)"),
    ("myhome_id", "myhome ID? (თუ არ არის — „-“)"),
    ("ssge_link", "ss.ge ბმული? (თუ არ არის — „-“)"),
    ("ssge_id", "ss.ge ID? (თუ არ არის — „-“)"),
    ("condition", "მდგომარეობა?"),
    ("client_phone", "კლიენტის ნომერი?"),
    ("district", "რაიონი?"),
    ("address", "მისამართი?"),
    ("meeting_date", "შეხვედრის თარიღი? (მაგ. 2026-09-15)"),
    ("price", "ფასი?"),
    ("percent", "პროცენტი %?"),
    ("time", "დრო? (შეხვედრის საათი)"),
    ("internal_number", "შიდა ნომერი? (თუ არ არის — „-“)"),
    ("team_leader", "თიმლიდერი?"),
]


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
            "/ranking — აგენტების რეიტინგი (ბოლო 30 დღე)\n"
            "/findclient <ტელეფონი> — კლიენტის სრული ისტორია\n"
            "/dayoffs — დასამტკიცებელი Day off მოთხოვნები\n"
            "/meetings — ბოლო დარეგისტრირებული შეხვედრები\n"
            "/setschedule — აგენტის კვირის გრაფიკის დაყენება\n"
            "/schedule — დღევანდელი გამოცხადების სტატუსი ყველაზე\n"
            "/warnings — გაფრთხილებები (ბოლო 30 დღე)\n"
            "/reactivate <agent_id> — გამორთული აგენტის დაბრუნება\n"
            "/setteam <agent_id> <თიმლიდერი> — აგენტის თიმის დაყენება"
        )
        return

    agent = sheets.find_agent_by_chat_id(chat_id)
    if agent:
        await update.message.reply_text(
            f"გამარჯობა, {agent['name']}! ბრძანებები:\n"
            "/mytasks — შენი დავალებები\n"
            "/clientreport — კლიენტთან შესრულებული სამუშაოს რეპორტი\n"
            "/meeting — შეხვედრის/ნახვის მონაცემების დარეგისტრირება\n"
            "/dayoff — დასვენების დღის მოთხოვნა\n"
            "/myschedule — შენი კვირის გრაფიკი\n"
            "/clockin — სამუშაო დღის დაწყება\n"
            "/clockout — სამუშაო დღის დასრულება"
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
    context.user_data["aa_phone"] = update.message.text.strip()
    await update.message.reply_text("თიმლიდერი/გუნდი? (თუ არ არის — დაწერეთ „-“)")
    return AA_TEAM


async def addagent_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    team_raw = update.message.text.strip()
    team = "" if team_raw == "-" else team_raw
    name = context.user_data.pop("aa_name")
    phone = context.user_data.pop("aa_phone")
    agent_id = sheets.add_agent(name, phone, team=team)
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


# ------------------------------------------------------- /clientreport (agent)
# ყოფილი Slack "AgentReports" ფორმის შემცვლელი: აგენტი წერს რომელ
# კლიენტთან რა იმუშავა (checkbox-ის მაგივრად — ჩართვადი ღილაკები),
# შენიშვნას და, სურვილისამებრ, ფოტო/დოკუმენტს.

def _report_actions_keyboard(selected: set) -> InlineKeyboardMarkup:
    rows = []
    for i, label in enumerate(REPORT_ACTIONS):
        mark = "✅ " if i in selected else "▫️ "
        rows.append([InlineKeyboardButton(mark + label, callback_data=f"rpact:{i}")])
    rows.append([InlineKeyboardButton("➡️ დასრულება", callback_data="rpact_done")])
    return InlineKeyboardMarkup(rows)


async def clientreport_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = sheets.find_agent_by_chat_id(update.effective_chat.id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return ConversationHandler.END
    context.user_data["rp_agent_id"] = agent["agent_id"]
    await update.message.reply_text("კლიენტის ტელეფონის ნომერი?")
    return RP_PHONE


async def clientreport_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rp_phone"] = update.message.text.strip()
    context.user_data["rp_actions"] = set()
    await update.message.reply_text(
        "რა შესრულდა ამ კლიენტთან? მონიშნეთ (შეიძლება რამდენიმეც), მერე დააჭირეთ „დასრულება“:",
        reply_markup=_report_actions_keyboard(set()),
    )
    return RP_ACTIONS


async def clientreport_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    sel = context.user_data.setdefault("rp_actions", set())
    sel.discard(idx) if idx in sel else sel.add(idx)
    await query.edit_message_reply_markup(reply_markup=_report_actions_keyboard(sel))
    return RP_ACTIONS


async def clientreport_actions_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sel = context.user_data.get("rp_actions", set())
    if not sel:
        await query.answer("აირჩიეთ მინიმუმ ერთი პუნქტი.", show_alert=True)
        return RP_ACTIONS
    await query.answer()
    labels = [REPORT_ACTIONS[i] for i in sorted(sel)]
    context.user_data["rp_actions_labels"] = labels
    await query.edit_message_text(
        "მონიშნული: " + ", ".join(labels) +
        "\n\nდაწერეთ შენიშვნა, გამოაგზავნეთ ფოტო/დოკუმენტი, ან /skip."
    )
    return RP_NOTES


async def _clientreport_save(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              notes: str = "", file_id: str = ""):
    d = context.user_data
    report_id = sheets.create_report(
        agent_id=d["rp_agent_id"], client_phone=d["rp_phone"],
        actions=", ".join(d.get("rp_actions_labels", [])),
        notes=notes, file_id=file_id,
    )
    await update.message.reply_text(f"✅ რეპორტი შენახულია (id: {report_id}).")
    d.clear()
    return ConversationHandler.END


async def clientreport_notes_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _clientreport_save(update, context, notes=update.message.text.strip())


async def clientreport_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = ""
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    return await _clientreport_save(update, context, notes=update.message.caption or "", file_id=file_id)


async def clientreport_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _clientreport_save(update, context, notes="")


# ------------------------------------------------------------- /dayoff (agent)
async def dayoff_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = sheets.find_agent_by_chat_id(update.effective_chat.id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return ConversationHandler.END
    context.user_data["do_agent_id"] = agent["agent_id"]
    context.user_data["do_agent_name"] = agent["name"]
    await update.message.reply_text("რომელი თარიღისთვის გინდათ დასვენება? (მაგ. 2026-09-15)")
    return DO_DATE


async def dayoff_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["do_date"] = update.message.text.strip()
    await update.message.reply_text("მიზეზი? (თუ არ გინდათ მითითება, დაწერეთ „-“)")
    return DO_REASON


async def dayoff_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    d = context.user_data
    request_id = sheets.create_dayoff_request(d["do_agent_id"], d["do_date"], reason)
    await update.message.reply_text("✅ მოთხოვნა გაგზავნილია ადმინთან დასამტკიცებლად.")

    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ დამტკიცება", callback_data=f"do_ok:{request_id}"),
        InlineKeyboardButton("❌ უარყოფა", callback_data=f"do_no:{request_id}"),
    ]])
    for admin_id in config.ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🏖 Day off მოთხოვნა: {d['do_agent_name']}\n"
                    f"თარიღი: {d['do_date']}\nმიზეზი: {reason}"
                ),
                reply_markup=buttons,
            )
        except Exception:
            log.exception("Day off შეტყობინება ვერ გაიგზავნა admin=%s", admin_id)
    d.clear()
    return ConversationHandler.END


async def dayoff_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update.effective_chat.id):
        await query.answer()
        return
    action, request_id = query.data.split(":", 1)
    status = "approved" if action == "do_ok" else "rejected"
    row = sheets.decide_dayoff(request_id, status)
    if not row:
        await query.answer("ეს მოთხოვნა ვერ მოიძებნა (შეიძლება უკვე გადაწყვეტილია).", show_alert=True)
        return
    await query.answer()
    label = "✅ დამტკიცებულია" if status == "approved" else "❌ უარყოფილია"
    await query.edit_message_text(query.message.text + f"\n\n{label}")

    agents_by_id = {a["agent_id"]: a for a in sheets.get_agents()}
    agent = agents_by_id.get(row.get("agent_id"))
    if agent and agent.get("telegram_chat_id"):
        try:
            await context.bot.send_message(
                chat_id=int(agent["telegram_chat_id"]),
                text=f"თქვენი Day off მოთხოვნა ({row.get('date')}) — {label}",
            )
        except Exception:
            log.exception("Day off პასუხი ვერ გაეგზავნა აგენტს")


async def dayoffs_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    pending = sheets.get_dayoff_requests(status="pending")
    if not pending:
        await update.message.reply_text("დასამტკიცებელი Day off მოთხოვნა არ არის.")
        return
    agents_by_id = {a["agent_id"]: a["name"] for a in sheets.get_agents()}
    for r in pending:
        name = agents_by_id.get(r.get("agent_id"), r.get("agent_id"))
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ დამტკიცება", callback_data=f"do_ok:{r['request_id']}"),
            InlineKeyboardButton("❌ უარყოფა", callback_data=f"do_no:{r['request_id']}"),
        ]])
        await update.message.reply_text(
            f"🏖 {name} — {r.get('date')}\nმიზეზი: {r.get('reason') or '-'}",
            reply_markup=buttons,
        )


# ------------------------------------------------------------ /meeting (agent)
# ყოფილი Slack "შეხვედრები" ფორმის შემცვლელი — კლიენტთან შეხვედრის/ნახვის
# დანიშვნისას აგენტი ავსებს ყველა იმ ველს, რასაც ადრე ფორმაში წერდა.

async def meeting_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = sheets.find_agent_by_chat_id(update.effective_chat.id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return ConversationHandler.END
    context.user_data["mt_agent"] = agent
    context.user_data["mt_data"] = {}
    context.user_data["mt_idx"] = 0
    await update.message.reply_text(
        "ვავსებთ შეხვედრის მონაცემებს. სადაც აქტუალური არაა, დაწერეთ „-“.\n\n"
        + MEETING_FIELDS[0][1]
    )
    return MT_FIELD


async def meeting_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("mt_idx", 0)
    key, _ = MEETING_FIELDS[idx]
    value = update.message.text.strip()
    context.user_data["mt_data"][key] = "" if value == "-" else value
    idx += 1
    context.user_data["mt_idx"] = idx

    if idx < len(MEETING_FIELDS):
        await update.message.reply_text(MEETING_FIELDS[idx][1])
        return MT_FIELD

    agent = context.user_data["mt_agent"]
    d = context.user_data["mt_data"]
    fields = dict(d)
    fields["agent_id"] = agent["agent_id"]
    fields["agent_name"] = agent["name"]
    fields["agent_phone"] = agent.get("phone", "")
    meeting_id = sheets.create_meeting(fields)

    await update.message.reply_text(f"✅ შეხვედრის მონაცემები შენახულია (id: {meeting_id}).")

    summary = (
        f"📅 ახალი შეხვედრა — {agent['name']}\n"
        f"კლიენტი: {d.get('client_phone') or '-'} | მეპატრონე: {d.get('owner_phone') or '-'}\n"
        f"რაიონი/მისამართი: {d.get('district') or '-'}, {d.get('address') or '-'}\n"
        f"თარიღი/დრო: {d.get('meeting_date') or '-'} {d.get('time') or ''}\n"
        f"ფასი: {d.get('price') or '-'} | %: {d.get('percent') or '-'}\n"
        f"myhome ID: {d.get('myhome_id') or '-'} | ss.ge ID: {d.get('ssge_id') or '-'}"
    )
    for admin_id in config.ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=summary)
        except Exception:
            log.exception("შეხვედრის შეტყობინება ვერ გაეგზავნა admin=%s", admin_id)

    context.user_data.clear()
    return ConversationHandler.END


async def meetings_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    rows = sheets.get_meetings()
    if not rows:
        await update.message.reply_text("შეხვედრები ჯერ არ დარეგისტრირებულა.")
        return
    rows = rows[-15:][::-1]
    lines = ["📅 ბოლო შეხვედრები:", ""]
    for r in rows:
        lines.append(
            f"• {r.get('meeting_date') or '-'} {r.get('time') or ''} — {r.get('agent_name')}\n"
            f"   კლიენტი: {r.get('client_phone') or '-'} | {r.get('district') or '-'}, {r.get('address') or '-'}\n"
            f"   ფასი: {r.get('price') or '-'} | %: {r.get('percent') or '-'}"
        )
    await update.message.reply_text("\n\n".join(lines))


# ------------------------------------------------- /setschedule (admin) — ყოფილი "პირბადული ცხრილი"
async def setschedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return ConversationHandler.END
    agents = sheets.get_agents()
    if not agents:
        await update.message.reply_text("აგენტები არ არსებობს. ჯერ დაამატეთ /addagent-ით.")
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(a["name"], callback_data=f"sc_agent:{a['agent_id']}")]
        for a in agents
    ]
    await update.message.reply_text(
        "რომელი აგენტის გრაფიკს ვსვამთ?", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return SC_AGENT


def _schedule_mode_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, callback_data=f"sc_mode:{key}")] for key, label in SCHEDULE_MODES]
    return InlineKeyboardMarkup(rows)


async def setschedule_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    agent_id = query.data.split(":", 1)[1]
    agent_name = next((a["name"] for a in sheets.get_agents() if a["agent_id"] == agent_id), agent_id)
    context.user_data["sc_agent_id"] = agent_id
    context.user_data["sc_agent_name"] = agent_name
    context.user_data["sc_pattern"] = {}
    context.user_data["sc_idx"] = 0
    day_label = WEEKDAY_LABELS[0][1]
    await query.edit_message_text(
        f"{agent_name} — გრაფიკი.\n\n{day_label}?", reply_markup=_schedule_mode_keyboard()
    )
    return SC_DAY


async def setschedule_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":", 1)[1]
    idx = context.user_data.get("sc_idx", 0)
    day_key, _ = WEEKDAY_LABELS[idx]
    context.user_data["sc_pattern"][day_key] = mode
    idx += 1
    context.user_data["sc_idx"] = idx

    if idx < len(WEEKDAY_LABELS):
        day_label = WEEKDAY_LABELS[idx][1]
        await query.edit_message_text(f"{day_label}?", reply_markup=_schedule_mode_keyboard())
        return SC_DAY

    agent_id = context.user_data["sc_agent_id"]
    agent_name = context.user_data["sc_agent_name"]
    pattern = context.user_data["sc_pattern"]
    sheets.set_agent_schedule(agent_id, pattern)

    summary = "\n".join(
        f"• {label}: {SCHEDULE_MODE_LABELS.get(pattern.get(key, 'off'), 'დასვენება')}"
        for key, label in WEEKDAY_LABELS
    )
    await query.edit_message_text(f"✅ გრაფიკი შენახულია — {agent_name}:\n{summary}")
    context.user_data.clear()
    return ConversationHandler.END


async def myschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = sheets.find_agent_by_chat_id(update.effective_chat.id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return
    sched = sheets.get_agent_schedule(agent["agent_id"])
    if not sched:
        await update.message.reply_text("თქვენთვის გრაფიკი ჯერ არ დაყენებულა — სთხოვეთ ადმინს /setschedule.")
        return
    lines = ["📆 თქვენი კვირის გრაფიკი:", ""]
    for key, label in WEEKDAY_LABELS:
        lines.append(f"• {label}: {SCHEDULE_MODE_LABELS.get(sched.get(key, 'off'), 'დასვენება')}")
    att = sheets.get_today_attendance(agent["agent_id"])
    lines.append("")
    if att and att.get("clock_in") and not att.get("clock_out"):
        lines.append(f"✅ დღეს გამოცხადებული ხართ — დაწყება: {att['clock_in']}")
    elif att and att.get("clock_out"):
        count = att.get("count_submitted")
        count_str = f" | შეყვანილია: {count}" if count not in (None, "") else ""
        lines.append(f"დღეს დასრულებულია — {att['clock_in']} → {att['clock_out']}{count_str}")
    else:
        lines.append("⏳ დღეს ჯერ არ დაგირეგისტრირებიათ დაწყება — /clockin")
    await update.message.reply_text("\n".join(lines))


async def clockin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = sheets.find_agent_by_chat_id(update.effective_chat.id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return
    mode = sheets.get_today_mode(agent["agent_id"])
    if mode == "off":
        await update.message.reply_text("დღეს თქვენთვის გრაფიკის მიხედვით დასვენების დღეა.")
        return
    result = sheets.clock_in(agent["agent_id"])
    if result == "already":
        await update.message.reply_text("დღეს უკვე დარეგისტრირებული გაქვთ დაწყება.")
    else:
        await update.message.reply_text(
            f"✅ სამუშაო დღე დაწყებულია ({SCHEDULE_MODE_LABELS.get(mode, mode)}). "
            "ახლა შეგიძლიათ მიიღოთ ახალი კლიენტები."
        )


async def clockout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ყოფილი "ანგარიშფაქტურა" ფორმის ჩამნაცვლებელი: სამუშაო დღის
    დასრულებისას (მოსვლის/წასვლის დრო უკვე /clockin-/clockout-ითაა
    ცნობილი) ერთადერთი დამატებითი კითხვა — რამდენი განცხადება
    შეიყვანა დღეს."""
    agent = sheets.find_agent_by_chat_id(update.effective_chat.id)
    if not agent:
        await update.message.reply_text("ჯერ დარეგისტრირდით — გამოიყენეთ /start.")
        return ConversationHandler.END
    att = sheets.get_today_attendance(agent["agent_id"])
    if not att or not att.get("clock_in"):
        await update.message.reply_text("დღეს ჯერ არ დაგირეგისტრირებიათ დაწყება (/clockin).")
        return ConversationHandler.END
    if att.get("clock_out"):
        await update.message.reply_text("დღეს უკვე დასრულებული გაქვთ.")
        return ConversationHandler.END
    context.user_data["co_agent"] = agent
    await update.message.reply_text("რამდენი განცხადება შეიყვანეთ/დაამუშავეთ დღეს? (მხოლოდ რიცხვი, მაგ. 20)")
    return CO_COUNT


async def clockout_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        count = int(text)
    except ValueError:
        await update.message.reply_text("გთხოვთ, დაწერეთ მხოლოდ რიცხვი (მაგ. 20 ან 0).")
        return CO_COUNT

    agent = context.user_data.pop("co_agent")
    agent_id = agent["agent_id"]
    sheets.clock_out(agent_id)
    sheets.set_daily_count(agent_id, count)

    mode = sheets.get_today_mode(agent_id)
    note = ""
    if mode == "online" and count < config.ONLINE_DAILY_QUOTA:
        note = f"\n\n⚠️ დღევანდელი გეგმა ({config.ONLINE_DAILY_QUOTA}) ვერ შესრულდა — ეცნობებათ მენეჯერს."
        for admin_id in config.ADMIN_CHAT_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"📉 {agent['name']}-მა დღეს ონლაინ გეგმა ვერ შეასრულა: "
                        f"{count}/{config.ONLINE_DAILY_QUOTA}"
                    ),
                )
            except Exception:
                log.exception("გეგმის შეტყობინება ვერ გაეგზავნა admin=%s", admin_id)

    await update.message.reply_text(f"✅ სამუშაო დღე დასრულებულია. შეყვანილია: {count}.{note}")
    return ConversationHandler.END


async def schedule_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    agents = sheets.get_agents()
    if not agents:
        await update.message.reply_text("აგენტები არ არსებობს.")
        return
    lines = ["📆 დღევანდელი მდგომარეობა:", ""]
    for a in agents:
        mode = sheets.get_today_mode(a["agent_id"])
        if mode == "off":
            lines.append(f"• {a['name']}: დასვენება")
            continue
        att = sheets.get_today_attendance(a["agent_id"])
        if att and att.get("clock_in") and not att.get("clock_out"):
            status = f"✅ გამოცხადებული ({att['clock_in']})"
        elif att and att.get("clock_out"):
            count = att.get("count_submitted")
            count_str = f", განცხადება: {count}" if count not in (None, "") else ""
            status = f"დასრულებული ({att['clock_in']} → {att['clock_out']}{count_str})"
        else:
            status = "⏳ ჯერ არ გამოცხადებულა"
        lines.append(f"• {a['name']}: {SCHEDULE_MODE_LABELS.get(mode, mode)} — {status}")
    await update.message.reply_text("\n".join(lines))


# ----------------------------------------------------------- გაფრთხილებები
async def warnings_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    rows = sheets.get_warnings(days=config.WARNING_WINDOW_DAYS)
    if not rows:
        await update.message.reply_text(f"ბოლო {config.WARNING_WINDOW_DAYS} დღეში გაფრთხილება არ ყოფილა.")
        return
    agents_by_id = {a["agent_id"]: a["name"] for a in sheets.get_agents()}
    by_agent: dict[str, list] = {}
    for r in rows:
        by_agent.setdefault(str(r.get("agent_id")), []).append(r)

    lines = [f"⚠️ გაფრთხილებები (ბოლო {config.WARNING_WINDOW_DAYS} დღე):", ""]
    for agent_id, warns in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
        name = agents_by_id.get(agent_id, agent_id)
        flag = " 🚫 (გამორთულია)" if len(warns) >= config.WARNING_LIMIT else ""
        lines.append(f"• {name}: {len(warns)}/{config.WARNING_LIMIT}{flag}")
        for w in warns[-3:]:
            lines.append(f"   – {w.get('created_at')}: {w.get('type')} ({w.get('detail') or '-'})")
    await update.message.reply_text("\n".join(lines))


async def reactivate_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    if not context.args:
        inactive = [a for a in sheets.get_agents() if str(a.get("active", "")).lower() == "no"]
        if not inactive:
            await update.message.reply_text("გამორთული აგენტი არცერთი არ არის.")
            return
        lines = ["გამორთული აგენტები:", ""]
        for a in inactive:
            lines.append(f"• {a['name']} — agent_id: {a['agent_id']}")
        lines.append("\nგამოყენება: /reactivate <agent_id>")
        await update.message.reply_text("\n".join(lines))
        return
    agent_id = context.args[0]
    ok = sheets.set_agent_active(agent_id, "yes")
    if ok:
        await update.message.reply_text(f"✅ აგენტი {agent_id} ისევ აქტიურია.")
    else:
        await update.message.reply_text("ასეთი agent_id ვერ ვიპოვე.")


async def setteam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("გამოყენება: /setteam <agent_id> <თიმლიდერის სახელი>")
        return
    agent_id = context.args[0]
    team = " ".join(context.args[1:])
    ok = sheets.set_agent_team(agent_id, team)
    if ok:
        await update.message.reply_text(f"✅ თიმი განახლდა: {team}")
    else:
        await update.message.reply_text("ასეთი agent_id ვერ ვიპოვე. სია: /agents")


# --------------------------------------------------------- /findclient (admin)
async def findclient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        return
    if not context.args:
        await update.message.reply_text("გამოყენება: /findclient <ტელეფონი>")
        return
    phone = context.args[0]
    hist = sheets.get_client_history(phone)
    if not hist["tasks"] and not hist["reports"] and not hist["meetings"]:
        await update.message.reply_text("ამ ნომერზე ისტორია ვერ მოიძებნა.")
        return

    agents_by_id = {a["agent_id"]: a["name"] for a in sheets.get_agents()}
    lines = [f"📋 კლიენტის ისტორია: {phone}", ""]
    if hist["tasks"]:
        lines.append("დავალებები:")
        for t in hist["tasks"]:
            name = agents_by_id.get(str(t.get("assigned_to")), t.get("assigned_to"))
            lines.append(f"• [{t['task_id']}] {t['title']} — {name} — {t['status']} ({t.get('created_at')})")
        lines.append("")
    if hist["meetings"]:
        lines.append("შეხვედრები:")
        for m in hist["meetings"]:
            lines.append(
                f"• {m.get('meeting_date') or '-'} {m.get('time') or ''} — {m.get('agent_name')} "
                f"— {m.get('district') or '-'}, {m.get('address') or '-'} (ფასი: {m.get('price') or '-'})"
            )
        lines.append("")
    if hist["reports"]:
        lines.append("რეპორტები:")
        for r in hist["reports"]:
            name = agents_by_id.get(str(r.get("agent_id")), r.get("agent_id"))
            note = f" — {r['notes']}" if r.get("notes") else ""
            lines.append(f"• {r.get('created_at')} — {name}: {r.get('actions')}{note}")
    await update.message.reply_text("\n".join(lines))


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

    import datetime as _dt
    today_str = _dt.datetime.now().strftime("%Y-%m-%d")
    reports_today = [r for r in sheets.get_reports() if str(r.get("created_at", "")).startswith(today_str)]
    meetings_today = [m for m in sheets.get_meetings() if str(m.get("timestamp", "")).startswith(today_str)]
    pending_dayoffs = sheets.get_dayoff_requests(status="pending")
    warnings_today = [w for w in sheets.get_warnings() if str(w.get("created_at", "")).startswith(today_str)]
    att_today = [a for a in sheets.get_today_attendance_all() if a.get("count_submitted") not in (None, "")]
    lines.append("")
    lines.append(f"დღეს შემოსული კლიენტის რეპორტები: {len(reports_today)}")
    lines.append(f"დღეს დარეგისტრირებული შეხვედრები: {len(meetings_today)}")
    if att_today:
        agents_by_id = {a["agent_id"]: a["name"] for a in sheets.get_agents()}
        total = sum(int(a["count_submitted"]) for a in att_today if str(a["count_submitted"]).isdigit())
        lines.append(f"დღეს შეყვანილი განცხადებები (დასრულებულებზე): სულ {total}")
        short = [a for a in att_today if str(a.get("count_submitted", "")).isdigit()
                 and int(a["count_submitted"]) < config.ONLINE_DAILY_QUOTA]
        if short:
            names = ", ".join(agents_by_id.get(a["agent_id"], a["agent_id"]) for a in short)
            lines.append(f"   გეგმის ({config.ONLINE_DAILY_QUOTA}) ქვემოთ: {names}")
    if pending_dayoffs:
        lines.append(f"⏳ დასამტკიცებელი Day off მოთხოვნები: {len(pending_dayoffs)} (/dayoffs)")
    if warnings_today:
        lines.append(f"⚠️ დღეს გაცემული გაფრთხილებები: {len(warnings_today)} (/warnings)")
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


WARNING_LABELS = {
    "late_report": "დაგვიანებული/გამოტოვებული ანგარიში",
    "late_arrival": "დაგვიანება სამუშაოზე",
    "no_show": "არ გამოცხადება",
}


async def _notify_warning(context: ContextTypes.DEFAULT_TYPE, agent: dict, w_type: str, detail: str, result: dict):
    label = WARNING_LABELS.get(w_type, w_type)
    text_admin = (
        f"⚠️ გაფრთხილება — {agent['name']}: {label}\n{detail}\n"
        f"ბოლო {config.WARNING_WINDOW_DAYS} დღეში: {result['count']}/{config.WARNING_LIMIT}"
    )
    if result["deactivated"]:
        text_admin += (
            f"\n\n🚫 აგენტი ავტომატურად გამოირთო (მიაღწია {config.WARNING_LIMIT} "
            f"გაფრთხილებას). დასაბრუნებლად: /reactivate {agent['agent_id']}"
        )
    for admin_id in config.ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text_admin)
        except Exception:
            log.exception("გაფრთხილების შეტყობინება ვერ გაეგზავნა admin=%s", admin_id)

    if agent.get("telegram_chat_id"):
        try:
            agent_text = f"⚠️ მიიღეთ გაფრთხილება: {label}."
            if result["deactivated"]:
                agent_text += (
                    "\n\nსამწუხაროდ, გაფრთხილებების ლიმიტს მიაღწიეთ და თქვენი "
                    "ანგარიში დროებით გამოირთო. დაუკავშირდით მენეჯერს."
                )
            await context.bot.send_message(chat_id=int(agent["telegram_chat_id"]), text=agent_text)
        except Exception:
            log.exception("გაფრთხილება ვერ გაეგზავნა აგენტს agent_id=%s", agent.get("agent_id"))


async def check_late_arrivals(context: ContextTypes.DEFAULT_TYPE):
    """15 წუთში ერთხელ — ვინც ოფისის ცვლაზეა და +grace წუთის მერეც არ
    დაუწყია (/clockin), იღებს "დაგვიანება"-ს (დღეში ერთხელ, ერთი აგენტისთვის)."""
    try:
        now = datetime.datetime.now(ZoneInfo(config.TIMEZONE))
        weekday_key = sheets.WEEKDAY_KEYS[now.weekday()]
        agents = sheets.get_agents()
    except Exception:
        log.exception("დაგვიანების შემოწმება ვერ მოხერხდა")
        return

    for a in agents:
        agent_id = a["agent_id"]
        if str(a.get("active", "")).strip().lower() == "no":
            continue
        sched = sheets.get_agent_schedule(agent_id)
        if not sched:
            continue
        mode = str(sched.get(weekday_key) or "off")
        if mode not in ("office_morning", "office_evening"):
            continue
        start_hour = 10 if mode == "office_morning" else 16
        deadline = now.replace(hour=start_hour, minute=config.ATTENDANCE_GRACE_MINUTES, second=0, microsecond=0)
        if now < deadline:
            continue
        if sheets.has_warning_today(agent_id, "late_arrival"):
            continue
        att = sheets.get_today_attendance(agent_id)
        if att and att.get("clock_in"):
            continue
        result = sheets.add_warning(agent_id, "late_arrival", f"ცვლა {start_hour}:00-ზე, ჯერ არ დაწყებია")
        await _notify_warning(context, a, "late_arrival", f"ცვლის დაწყება: {start_hour}:00", result)


async def check_daily_compliance(context: ContextTypes.DEFAULT_TYPE):
    """ყოველდღე REPORT_DEADLINE_HOUR-ზე — ვინც დღეს საერთოდ არ გამოცხადდა
    (no_show) ან გამოცხადდა, მაგრამ /clientreport არ გამოგზავნა
    (late_report), იღებს გაფრთხილებას."""
    try:
        now = datetime.datetime.now(ZoneInfo(config.TIMEZONE))
        weekday_key = sheets.WEEKDAY_KEYS[now.weekday()]
        agents = sheets.get_agents()
    except Exception:
        log.exception("დღიური შემოწმება ვერ მოხერხდა")
        return

    today = now.strftime("%Y-%m-%d")
    for a in agents:
        agent_id = a["agent_id"]
        if str(a.get("active", "")).strip().lower() == "no":
            continue
        sched = sheets.get_agent_schedule(agent_id)
        if not sched:
            continue
        mode = str(sched.get(weekday_key) or "off")
        if mode == "off":
            continue

        att = sheets.get_today_attendance(agent_id)
        if not att or not att.get("clock_in"):
            if sheets.has_warning_today(agent_id, "no_show"):
                continue
            result = sheets.add_warning(agent_id, "no_show", f"{today}: არ გამოცხადებულა")
            await _notify_warning(context, a, "no_show", today, result)
            continue

        if sheets.has_warning_today(agent_id, "late_report"):
            continue
        reports_today = [
            r for r in sheets.get_reports(agent_id=agent_id)
            if str(r.get("created_at", "")).startswith(today)
        ]
        if not reports_today:
            result = sheets.add_warning(
                agent_id, "late_report",
                f"{today}: ანგარიში ({config.REPORT_DEADLINE_HOUR}:00-მდე) არ გამოგზავნილა",
            )
            await _notify_warning(context, a, "late_report", today, result)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    გლობალური შეცდომების დამჭერი — თუ რომელიმე ბრძანების დამუშავებისას
    გაუთვალისწინებელი შეცდომა მოხდება, ბოტი აქამდე "იჭედებოდა" (ის
    კონკრეტული საუბარი ჩერდებოდა და მომხმარებელს აღარაფერს პასუხობდა,
    Railway-ის ლოგებში კი უჩუმრად რჩებოდა). ახლა: 1) ეს ჩაიწერება
    ლოგში, 2) ადმინებს მაშინვე მიუვათ შეტყობინება, 3) იმ საუბრის
    user_data გასუფთავდება, რომ შემდეგმა ბრძანებამ ისევ იმუშაოს.
    """
    log.exception("დაუჭერავი შეცდომა update-ის დამუშავებისას", exc_info=context.error)

    try:
        if isinstance(update, Update) and update.effective_chat:
            if context.user_data is not None:
                context.user_data.clear()
            if not is_admin(update.effective_chat.id):
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ მოხდა შეცდომა. სცადეთ ისევ, ან დაწერეთ /cancel და თავიდან.",
                )
    except Exception:
        log.exception("on_error-ის თავად დამუშავებაც ჩავარდა")

    for admin_id in config.ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ ბოტში მოხდა შეცდომა: {context.error!r}\nRailway-ის ლოგებში მეტი დეტალია.",
            )
        except Exception:
            log.exception("შეცდომის შეტყობინება ვერ გაეგზავნა admin=%s", admin_id)


def main():
    config.validate()
    try:
        sheets.ensure_sheets()
    except Exception:
        log.exception(
            "ცხრილთან საწყისი დაკავშირება/მომზადება ჩავარდა — ამის გარეშე ბოტი "
            "ვერ იმუშავებს. გადაამოწმეთ GOOGLE_SHEET_ID/GOOGLE_SERVICE_ACCOUNT_JSON "
            "და რომ სერვის-აქაუნთს Editor წვდომა აქვს ცხრილზე."
        )
        raise

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(on_error)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(CommandHandler("mytasks", mytasks))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/done_\S+"), done_command))
    app.add_handler(CommandHandler("agents", agents_list))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("findclient", findclient))
    app.add_handler(CommandHandler("dayoffs", dayoffs_pending))
    app.add_handler(CommandHandler("meetings", meetings_list))
    app.add_handler(CommandHandler("myschedule", myschedule))
    app.add_handler(CommandHandler("clockin", clockin_cmd))
    app.add_handler(CommandHandler("schedule", schedule_today))
    app.add_handler(CommandHandler("warnings", warnings_list))
    app.add_handler(CommandHandler("reactivate", reactivate_agent))
    app.add_handler(CommandHandler("setteam", setteam_cmd))
    app.add_handler(CallbackQueryHandler(dayoff_decide, pattern=r"^do_(ok|no):"))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addagent", addagent_start)],
        states={
            AA_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addagent_name)],
            AA_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addagent_phone)],
            AA_TEAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, addagent_team)],
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

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("clientreport", clientreport_start)],
        states={
            RP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, clientreport_phone)],
            RP_ACTIONS: [
                CallbackQueryHandler(clientreport_toggle, pattern=r"^rpact:\d+$"),
                CallbackQueryHandler(clientreport_actions_done, pattern=r"^rpact_done$"),
            ],
            RP_NOTES: [
                CommandHandler("skip", clientreport_skip),
                MessageHandler(filters.PHOTO | filters.Document.ALL, clientreport_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, clientreport_notes_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("dayoff", dayoff_start)],
        states={
            DO_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dayoff_date)],
            DO_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, dayoff_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("meeting", meeting_start)],
        states={
            MT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_field)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("setschedule", setschedule_start)],
        states={
            SC_AGENT: [CallbackQueryHandler(setschedule_agent, pattern=r"^sc_agent:")],
            SC_DAY: [CallbackQueryHandler(setschedule_day, pattern=r"^sc_mode:")],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("clockout", clockout_cmd)],
        states={
            CO_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, clockout_count)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.COMMAND, busy_fallback)],
    ))

    if app.job_queue:
        app.job_queue.run_repeating(check_new_tasks, interval=config.POLL_INTERVAL_SECONDS, first=10)
        app.job_queue.run_repeating(check_late_arrivals, interval=900, first=120)
        app.job_queue.run_daily(
            send_daily_report,
            time=datetime.time(hour=config.DAILY_REPORT_HOUR, tzinfo=ZoneInfo(config.TIMEZONE)),
        )
        app.job_queue.run_daily(
            check_daily_compliance,
            time=datetime.time(hour=config.REPORT_DEADLINE_HOUR, minute=5, tzinfo=ZoneInfo(config.TIMEZONE)),
        )

    log.info("ბოტი გაშვებულია...")
    # drop_pending_updates=True: სტარტზე ასუფთავებს დაგროვილ ძველ/გაფუჭებულ
    # update-ებს (getWebhookInfo-მ აჩვენა pending_update_count: 28) — წინააღმდეგ
    # შემთხვევაში ბოტი მარადიულად ცდილობს იმავე ძველი, ჩამტვრეული update-ის
    # დამუშავებას და ახალ შეტყობინებებამდე (მაგ. /start) საერთოდ ვერ აღწევს.
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
