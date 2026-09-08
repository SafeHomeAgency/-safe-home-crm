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
SCHEDULE_SHEET_NAME = "Schedule"
ATTENDANCE_SHEET_NAME = "Attendance"
WARNINGS_SHEET_NAME = "Warnings"

# რამდენი გაფრთხილების მერე ითიშება აგენტი ავტომატურად (30-დღიან ფანჯარაში)
WARNING_LIMIT = int(os.environ.get("WARNING_LIMIT", "4"))
WARNING_WINDOW_DAYS = int(os.environ.get("WARNING_WINDOW_DAYS", "30"))
# რომელ საათზე მოწმდება დღიური ანგარიშის/გამოცხადების შესრულება
REPORT_DEADLINE_HOUR = int(os.environ.get("REPORT_DEADLINE_HOUR", "22"))
# რამდენი წუთის დაგვიანება ითვლება ჯერ კიდევ დასაშვებად (ოფისის ცვლაზე)
ATTENDANCE_GRACE_MINUTES = int(os.environ.get("ATTENDANCE_GRACE_MINUTES", "15"))
# დღიური გეგმა (განცხადებების რაოდენობა) ონლაინ დღეზე მყოფი აგენტისთვის
ONLINE_DAILY_QUOTA = int(os.environ.get("ONLINE_DAILY_QUOTA", "20"))

# Mini App (ვიზუალური დაშბორდი ტელეგრამშივე). Railway-ზე
# Settings → Networking → Generate Domain-ით მიღებული საჯარო https
# მისამართი (მაგ. https://xxx.up.railway.app). ცარიელი — Mini App-ის
# ღილაკები არ გამოჩნდება, ბოტი ტექსტურ რეჟიმში მაინც სრულად იმუშავებს.
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip().rstrip("/")
# დაცვა: თუ Railway-ის დომენი "https://"-ის გარეშე ჩაწერეს (Telegram
# მხოლოდ https ბმულებს იღებს Mini App-ისთვის) — თავად ვამატებთ.
if WEBAPP_URL and not WEBAPP_URL.startswith("http"):
    WEBAPP_URL = "https://" + WEBAPP_URL
# პორტი, რომელზეც Mini App-ის ვებ-სერვერი ეშვება (Railway ავტომატურად
# აწვდის PORT env ცვლადს)
PORT = int(os.environ.get("PORT", "8080"))


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
