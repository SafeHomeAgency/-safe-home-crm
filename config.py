"""
კონფიგურაცია — ყველა მნიშვნელობა იკითხება environment variable-ებიდან,
რომ საიდუმლო მონაცემები (ტოკენები) კოდში არ იყოს ჩაწერილი.

საჭირო environment variable-ები (იხ. .env.example და README.md):

  TELEGRAM_BOT_TOKEN     - BotFather-ისგან მიღებული ტოკენი
  ADMIN_CHAT_IDS         - ადმინის (ლაშას) Telegram chat id, მძიმით თუ რამდენიმეა
  GOOGLE_SERVICE_ACCOUNT_JSON - სერვის-აქაუნთის JSON გასაღების ფაილის გზა
  GOOGLE_SHEET_ID        - სამუშაო Google Sheet-ის ID (URL-დან)
  TIMEZONE               - ნაგულისხმევი: Asia/Tbilisi
  POLL_INTERVAL_SECONDS  - რამდენ წამში ერთხელ შეამოწმოს ცხრილში ახალი ტასკები (ნაგულისხმევი: 60)
  DAILY_REPORT_HOUR      - რომელ საათზე გაეგზავნოს ადმინს დღიური რეპორტი (0-23, ნაგულისხმევი: 9)
"""

import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

ADMIN_CHAT_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_CHAT_IDS", "").split(",")
    if x.strip()
}

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json"
)
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

TIMEZONE = os.environ.get("TIMEZONE", "Asia/Tbilisi")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "9"))

AGENTS_SHEET_NAME = "Agents"
TASKS_SHEET_NAME = "Tasks"
REPORTS_SHEET_NAME = "Reports"
DAYOFF_SHEET_NAME = "DayOff"
MEETINGS_SHEET_NAME = "Meetings"


def validate():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GOOGLE_SHEET_ID:
        missing.append("GOOGLE_SHEET_ID")
    if not ADMIN_CHAT_IDS:
        missing.append("ADMIN_CHAT_IDS")
    if missing:
        raise SystemExit(
            "აკლია environment variable-ები: " + ", ".join(missing) +
            "\nიხილეთ README.md, ნაბიჯი 5 (Deploy)."
        )
