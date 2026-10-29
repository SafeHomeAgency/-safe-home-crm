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
SHIFT_SWAPS_SHEET_NAME = "ShiftSwaps"
EXCLUSIVES_SHEET_NAME = "Exclusives"
QUESTIONS_SHEET_NAME = "Questions"
EXCLUSIVE_SHARES_SHEET_NAME = "ExclusiveShares"
AGENT_REQUESTS_SHEET_NAME = "AgentRequests"
MYHOME_JOBS_SHEET_NAME = "MyHomeJobs"
MYHOME_ACCOUNTS_SHEET_NAME = "MyHomeAccounts"
# კვირის რაიონების განაწილება (მენეჯერი -> აგენტები)
DISTRICT_ASSIGNMENTS_SHEET_NAME = "DistrictAssignments"
# Attendance + GPS: ივენთების ჟურნალი (მხოლოდ check-in/check-out მომენტი,
# მუდმივი ტრეკინგი არა) და admin-ის რედაქტირებადი პარამეტრები
ATTENDANCE_GEO_SHEET_NAME = "AttendanceGeo"
APP_SETTINGS_SHEET_NAME = "AppSettings"

# MyHome სქრეპერის queue-ს ინტეგრაცია: worker.py (გარეთა, ცალკე
# კომპიუტერზე მომუშავე პროცესი) იძახებს webserver.py-ს "/internal/..."
# endpoint-ებს ამ საერთო გასაღებით (Authorization header) — Telegram
# initData-ს მაგივრად, რადგან ეს machine-to-machine გამოძახებაა, არა
# Mini App-იდან. ცარიელი ნიშნავს, რომ ეს endpoint-ები გამორთულია
# (401-ს დააბრუნებენ), სანამ ვინმე შეგნებულად არ დააყენებს.
MYHOME_WORKER_API_KEY = os.environ.get("MYHOME_WORKER_API_KEY", "").strip()
# არასავალდებულო: თითო ანგარიშზე ცალკე გასაღები — "mariam-account=<key>,lika-account=<key>". ასეთი გასაღები მხოლოდ თავის იარლიყს ემსახურება
# და ცალკე ბათილდება/იცვლება; საერთო გასაღები (ზემოთ) ძველებურად მუშაობს ყველაზე. ცარიელი = მხოლოდ საერთო გასაღები.
def _label_keys(raw: str) -> dict:
    out = {}
    for part in (raw or "").split(","):
        label, sep, key = part.strip().partition("=")
        if sep and label.strip() and key.strip():
            out[label.strip()] = key.strip()
    return out


MYHOME_WORKER_API_KEYS = _label_keys(os.environ.get("MYHOME_WORKER_API_KEYS", ""))
# QUEUED job-ი რამდენი წუთის შემდეგ ითვლება „დიდხანს ელოდება“ (ადმინის ალერტი მიზეზით) და worker-ის `/next` რამდენი წამით ითვლება „ცოცხალ ციკლად“
QUEUE_WAIT_ALERT_MINUTES = float(os.environ.get("QUEUE_WAIT_ALERT_MINUTES", "10"))
WORKER_POLL_STALE_SECONDS = float(os.environ.get("WORKER_POLL_STALE_SECONDS", "90"))
# იგივე მდგომარეობის heartbeat-ს Sheets-ში ამ ინტერვალზე ხშირად არ ვწერთ (კვოტის დაზოგვა; stale-ზღვარი 300 წმ-ია)
WORKER_HEARTBEAT_COALESCE_SECONDS = float(os.environ.get("WORKER_HEARTBEAT_COALESCE_SECONDS", "45"))
# არასავალდებულო დღიური ლიმიტი: ერთი აგენტი დღეში (თბილისის დღე) მაქს. რამდენ ატვირთვის job-ს ქმნის (MyHome-ის ფასიანი განთავსება ბალანსიდან იხდის).
# 0 = ლიმიტი გამორთულია (ძველი ქცევა). დირექტორის გადაწყვეტილებაა.
MYHOME_DAILY_JOBS_PER_AGENT = int(os.environ.get("MYHOME_DAILY_JOBS_PER_AGENT", "0"))
# რამდენი წუთის განმავლობაში "PROCESSING"-ში გაჭედილი job ითვლება
# "worker ჩამოვარდნილად" და უბრუნდება "QUEUED"-ს ხელახლა (retry_count-ის
# გაზრდით) — worker-ის restart-ის/crash-ის დაცვა.
MYHOME_JOB_STALE_MINUTES = int(os.environ.get("MYHOME_JOB_STALE_MINUTES", "15"))
MYHOME_JOB_MAX_RETRIES = int(os.environ.get("MYHOME_JOB_MAX_RETRIES", "3"))


def _int_list(name: str, default: str) -> list[int]:
    out = []
    for part in os.environ.get(name, default).split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out or [int(x) for x in default.split(",")]


# --- PHASE 1.5: უსაფრთხოება და სტაბილურობა -----------------------------
# Telegram initData-ს მაქსიმალური ასაკი (წამი). Mini App-ი initData-ს
# გახსნისას იღებს და სესიის განმავლობაში იგივეს აგზავნის (Telegram მას ღია
# აპში არ ანახლებს), ამიტომ 24 საათი; გაჟონილი სათაური მაქს. ამდენ ხანს
# მოქმედებს და არა სამუდამოდ. შესამცირებლად: Railway Variables.
INITDATA_MAX_AGE_SECONDS = int(os.environ.get("TELEGRAM_INITDATA_MAX_AGE_SECONDS", "86400"))
# რამდენი წამით "მომავალში" დაშვებულია auth_date (საათების უმნიშვნელო სხვაობა)
INITDATA_FUTURE_SKEW_SECONDS = int(os.environ.get("TELEGRAM_INITDATA_FUTURE_SKEW_SECONDS", "60"))

# worker heartbeat: რამდენი წამის შემდეგ ითვლება worker stale/offline
WORKER_HEARTBEAT_STALE_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS", "300"))
# FAILED job-ის ავტომატური განმეორების დაყოვნება (წუთები) ცდების მიხედვით:
# 1-ლი განმეორება -> 2 წთ, მე-2 -> 10 წთ, მე-3 -> 30 წთ
MYHOME_RETRY_BACKOFF_MINUTES = _int_list("MYHOME_RETRY_BACKOFF_MINUTES", "2,10,30")
# Sheets-ზე job-ის დაკავების შემდეგ რამდენ წამს ველოდებით გადამოწმებამდე
# (ტრანზაქციის არარსებობის კომპენსაცია; იხ. sheets_gspread.claim_next_myhome_job)
MYHOME_CLAIM_SETTLE_SECONDS = float(os.environ.get("MYHOME_CLAIM_SETTLE_SECONDS", "1.0"))

# AuditLog (Sheets): ბუფერიდან ჩაწერის ინტერვალი (წამი)
AUDIT_LOG_SHEET_NAME = "AuditLog"
WORKER_HEARTBEAT_SHEET_NAME = "WorkerHeartbeat"
AUDIT_FLUSH_SECONDS = float(os.environ.get("AUDIT_FLUSH_SECONDS", "3"))

# ატვირთული ფოტოების საქაღალდე. Railway Volume-ის შემთხვევაში მიუთითეთ
# Volume-ის mount path (მაგ. /data/uploads) — წინააღმდეგ შემთხვევაში ფაილები
# ეფემერულ დისკზეა და redeploy-ზე იკარგება. ცარიელი = ძველი ქცევა.
UPLOADS_DIR_OVERRIDE = os.environ.get("UPLOADS_DIR", "").strip()

# Rate limiting (პროცესის შიდა, არა განაწილებული!): bucket -> (მოთხოვნა, წამი)
# ლიმიტები განზრახ ფართოა — რეალურ აგენტს არ უნდა შეუშალოს ხელი.
RATE_LIMITS = {
    "auth_fail":    (30, 60),    # IP-ზე: წარუმატებელი ავტორიზაციები
    "job_create":   (20, 60),    # მომხმარებელზე: MyHome job-ის შექმნა
    "worker":       (240, 60),   # worker-ის endpoint-ები (poll ~2/წთ + heartbeat)
    "clockout":     (10, 60),    # დღის დახურვა (ფოტო-ატვირთვა base64-ით)
    "bulk_notify":  (30, 60),    # შეტყობინებების გამომწვევი მასობრივი endpoint-ები
    "photo":        (240, 60),   # ფოტოების ჩამოტვირთვა
    "export":       (6, 60),     # CSV ექსპორტი (Telegram-ში ფაილის გაგზავნა)
    "crm2_read":    (120, 60),   # CRM 2.0: კლიენტების სია/ბარათი/follow-up-ები (წაკითხვა)
    "crm2_write":   (30, 60),    # CRM 2.0: follow-up/შენიშვნის ჩაწერა
    "myhome_account": (10, 60),  # ადმინის ფორმა: MyHome ანგარიშის დამატება
    "contracts_read": (120, 60),   # ხელშეკრულებების მოდული: სიები/დეტალები (წაკითხვა)
    "contracts_write": (40, 60),   # ხელშეკრულებების მოდული: მოთხოვნა/გაცემა/დაბრუნება
    "finance_read": (120, 60),     # ფინანსური ტრეკერი: დაშბორდი/სიები (წაკითხვა)
    "finance_write": (60, 60),     # ფინანსური ტრეკერი: გარიგება/ხარჯი (ჩაწერა)
    "listings_read": (240, 60),    # Property Hub: კატალოგი/ძიება/დეტალი (წაკითხვა; ფილტრების შეცვლა ხშირია)
    "listings_write": (30, 60),    # Property Hub: backfill/ადმინის ფლაგები
    "hub_read": (240, 60),         # Property Hub: შეხვედრების სია/სტატისტიკა
    "hub_write": (40, 60),         # Property Hub: შეხვედრის შექმნა/დადასტურება/სტატუსი
    "ai_ask": (8, 60),             # Safe Home AI: კითხვა (მომხმარებელზე; ყოველი კითხვა ფასიანია)
    "ai_read": (120, 60),          # Safe Home AI: ისტორია/ცოდნის ბაზა/დაშბორდი (წაკითხვა)
    "ai_write": (40, 60),          # Safe Home AI: უკუკავშირი, ცოდნის ბაზის რედაქტირება/დამტკიცება
    "leadguard_read": (60, 60),    # SAIRO Lead Protection: რისკების ანგარიში/წინასწარი ნახვა (წაკითხვა)
}
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "1").strip().lower() not in ("0", "false", "no")

# თვეში მაქსიმუმ რამდენჯერ შეუძლია აგენტს სმენის გაცვლის მოთხოვნა
SHIFT_SWAP_MONTHLY_LIMIT = int(os.environ.get("SHIFT_SWAP_MONTHLY_LIMIT", "2"))

# თვეში მაქსიმუმ რამდენი "approved" Day off შეიძლება ჰქონდეს ერთ
# აგენტს (კალენდარული თვის მიხედვით, ყოველ თვე თავიდან ითვლება)
DAYOFF_MONTHLY_LIMIT = int(os.environ.get("DAYOFF_MONTHLY_LIMIT", "3"))

# რამდენი გაფრთხილების მერე ითიშება აგენტი ავტომატურად (30-დღიან ფანჯარაში)
WARNING_LIMIT = int(os.environ.get("WARNING_LIMIT", "4"))
WARNING_WINDOW_DAYS = int(os.environ.get("WARNING_WINDOW_DAYS", "30"))
# გაფრთხილებები ყოველი კალენდარული თვის დასაწყისში ავტომატურად
# "ნულდება" (აღარ ითვლება ლიმიტში და აღარ ჩანს აგენტის მიმდინარე
# მრიცხველში) — ჩანაწერები ისტორიისთვის რჩება. "0"/"false"-ზე
# დაყენებით ბრუნდება ძველი, მხოლოდ მოძრავი WARNING_WINDOW_DAYS ფანჯარა.
WARNING_RESET_MONTHLY = os.environ.get("WARNING_RESET_MONTHLY", "1").strip().lower() not in ("0", "false", "no")
# რომელ საათზე მოწმდება დღიური ანგარიშის/გამოცხადების შესრულება
REPORT_DEADLINE_HOUR = int(os.environ.get("REPORT_DEADLINE_HOUR", "22"))
# რამდენი წუთის დაგვიანება ითვლება ჯერ კიდევ დასაშვებად (ოფისის ცვლაზე)
ATTENDANCE_GRACE_MINUTES = int(os.environ.get("ATTENDANCE_GRACE_MINUTES", "15"))
# დღიური გეგმა (განცხადებების რაოდენობა) — ცალ-ცალკე ონლაინ დღეზე და
# ოფისის ცვლაზე მყოფი აგენტისთვის (ოფისზე იზომება ჯამურად: საიტი +
# myhome + ss.ge)
ONLINE_DAILY_QUOTA = int(os.environ.get("ONLINE_DAILY_QUOTA", "20"))
OFFICE_DAILY_QUOTA = int(os.environ.get("OFFICE_DAILY_QUOTA", "20"))

# KPI (აგენტის შედეგი %): 5 კომპონენტის წონები (ჯამი თავისუფალია — ნორმირდება;
# კომპონენტი, რომელიც აგენტზე არ ვრცელდება (მაგ. კლიენტი არ ჰყოლია), გამოტოვდება).
KPI_WEIGHTS = {"listings": 30, "discipline": 25, "meetings": 15, "clients": 15, "closed_cases": 15}
for _pair in os.environ.get("KPI_WEIGHTS", "").split(","):
    if ":" in _pair:
        _k, _v = _pair.split(":", 1)
        if _k.strip() in KPI_WEIGHTS:
            try:
                KPI_WEIGHTS[_k.strip()] = float(_v)
            except ValueError:
                pass
# შეხვედრების გეგმა კვირაში / ჩახურული ქეისების გეგმა თვეში / ერთი გაფრთხილების ჯარიმა დისციპლინის ქულაში
KPI_MEETINGS_PER_WEEK = float(os.environ.get("KPI_MEETINGS_PER_WEEK", "3"))
KPI_CLOSED_CASES_PER_MONTH = float(os.environ.get("KPI_CLOSED_CASES_PER_MONTH", "2"))
KPI_WARNING_PENALTY = float(os.environ.get("KPI_WARNING_PENALTY", "0.10"))
# Property Hub-იდან დაგეგმილი შეხვედრა KPI-ში ითვლება მხოლოდ სტატუსით „ჩატარდა“ (დაგეგმილი ≠ ჩატარებული; გაუქმებული/არ გამოცხადებული
# არ ითვლება). ძველი (/meeting) ჩანაწერები უცვლელად ითვლება. "0" აბრუნებს ძველ ქცევას (ყველა Meetings-სტრიქონი).
KPI_HUB_MEETINGS_HELD_ONLY = os.environ.get("KPI_HUB_MEETINGS_HELD_ONLY", "1").strip().lower() not in ("0", "false", "no")
# ონლაინ დღეზე რომელ საათზე შევახსენოთ აგენტს დაწყება (/clockin), თუ
# ჯერ არ დაუწყია — ონლაინ რეჟიმს ფიქსირებული საწყისი საათი არა აქვს,
# ამიტომ ეს მხოლოდ ერთხელადი, დღის შუა საათის შეხსენებაა.
ONLINE_START_REMINDER_HOUR = int(os.environ.get("ONLINE_START_REMINDER_HOUR", "12"))

# --- ფინანსური ტრეკერი (მხოლოდ დირექტორის უფროსისთვის) ---------------------
# FINANCE_CHAT_IDS — Telegram ID-ები (მძიმით), ვისაც ფინანსურ ტაბზე წვდომა აქვს. ცარიელია = არავის (ადმინებიც ვერ ხედავენ),
# სანამ Railway-ზე არ დააყენებთ. ეს განზრახ ცალკეა ADMIN_CHAT_IDS-ისგან: ადმინებს/დირექტორს ფინანსები არ უჩანთ.
FINANCE_CHAT_IDS = {
    int(x.strip())
    for x in os.environ.get("FINANCE_CHAT_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
# რომელ საათზე (თბილისი) მოდის ფინანსური შეხსენებები (ანგარიშგება ყოველ 2 თვეში, კონტრაქტის ვადის ამოწურვა)
FINANCE_REMINDER_HOUR = int(os.environ.get("FINANCE_REMINDER_HOUR", "10"))

# --- ხელშეკრულებების აღრიცხვა (Contract Management) --------------------
# CONTRACT_STAFF_CHAT_IDS — Telegram ID-ები (მძიმით), ვისაც ფიზიკური გაცემა/მიღება შეუძლია (ადმინებს ეს ყოველთვის აქვთ).
# თიმლიდერს ეს უფლება მხოლოდ მაშინ აქვს, თუ აქ არის ჩამოთვლილი.
CONTRACT_STAFF_CHAT_IDS = {
    int(x.strip())
    for x in os.environ.get("CONTRACT_STAFF_CHAT_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
# გაცემისას დაბრუნების ვადა ნაგულისხმევად (საათი), თუ გამცემმა არ მიუთითა
CONTRACT_DEFAULT_RETURN_HOURS = int(os.environ.get("CONTRACT_DEFAULT_RETURN_HOURS", "48"))
# რამდენი საათით ადრე შევახსენოთ აგენტს დაბრუნების ვადა
CONTRACT_REMINDER_HOURS = int(os.environ.get("CONTRACT_REMINDER_HOURS", "4"))
# რომელ საათზე (თბილისი) მიდის ადმინებს ყოველდღიური შეჯამება
CONTRACT_SUMMARY_HOUR = int(os.environ.get("CONTRACT_SUMMARY_HOUR", "9"))

# --- Attendance + ოფისის GPS ვერიფიკაცია (ახალი მოდული) --------------
# ყველა ეს მნიშვნელობა ნაგულისხმევია; ადმინს შეუძლია Mini App-იდან
# ("დასწრება" ტაბი -> პარამეტრები) გადააწეროს (AppSettings ცხრილში
# ინახება) ან Railway-ის environment variable-ებით შეცვალოს.
# OFFICE_LATITUDE/OFFICE_LONGITUDE განზრახ ცარიელია — გამოგონილი
# კოორდინატი არ ჩაიწერა. სანამ ორივე არ დაყენდება, GPS ვერიფიკაცია
# გამორთულია და დასწრება ძველებურად (GPS-ის გარეშე) მუშაობს.
OFFICE_NAME = os.environ.get("OFFICE_NAME", "Safe Home Office").strip()
OFFICE_LATITUDE = os.environ.get("OFFICE_LATITUDE", "").strip()
OFFICE_LONGITUDE = os.environ.get("OFFICE_LONGITUDE", "").strip()
OFFICE_RADIUS_METERS = int(os.environ.get("OFFICE_RADIUS_METERS", "100"))
# GPS სიზუსტე (მეტრი), რომელზე უარესი მონაცემიც არასანდოდ ითვლება
MAX_ACCEPTABLE_ACCURACY_METERS = int(os.environ.get("MAX_ACCEPTABLE_ACCURACY_METERS", "150"))
# true -> ოფისის გარედან დაწყება შესაძლებელია, მაგრამ აუცილებლად
# OUTSIDE_OFFICE-დ ფიქსირდება; false -> ოფისის ცვლაზე გარედან დაწყება
# შეუძლებელია (ონლაინ დღეზე ეს შეზღუდვა არ მოქმედებს)
ALLOW_OUTSIDE_CHECKIN = os.environ.get("ALLOW_OUTSIDE_CHECKIN", "1").strip().lower() not in ("0", "false", "no")
# რომელ საათზე (თბილისის დრო) მოწმდება, ვინ დაივიწყა სამუშაოს დასრულება
MISSING_CHECKOUT_HOUR = int(os.environ.get("MISSING_CHECKOUT_HOUR", "23"))

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

# --- Phase 1: მონაცემთა ბექენდი (Google Sheets -> PostgreSQL) --------
#
# DATA_BACKEND ცარიელი/დაუყენებელი (ნაგულისხმევი) => ყველაფერი ზუსტად
# ისე, როგორც აქამდე: Google Sheets. არაფერი არ იცვლება production-ში,
# სანამ ვინმე ცნობიერად არ დააყენებს "postgres"-ს — იხილეთ
# README_PHASE1_POSTGRES.md, სანამ ამას გააკეთებდეთ.
DATA_BACKEND = os.environ.get("DATA_BACKEND", "sheets").strip().lower()
# Railway-ს Postgres add-on-ი ამას ავტომატურად გამოიმუშავებს, როცა
# add-on-ს დაამატებთ პროექტზე — ხელით არაფრის ჩაწერა არ სჭირდება.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def validate():
    missing = []
    if DATA_BACKEND == "postgres":
        if not DATABASE_URL:
            missing.append("DATABASE_URL")
    else:
        if not GOOGLE_SHEET_ID:
            missing.append("GOOGLE_SHEET_ID")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not ADMIN_CHAT_IDS:
        missing.append("ADMIN_CHAT_IDS")
    if missing:
        raise SystemExit(
            "აკლია environment variable-ები: " + ", ".join(missing) +
            "\nიხილეთ README.md, ნაბიჯი 5 (Deploy)."
        )


# --- Safe Home AI (შიდა ასისტენტი) -------------------------------------------
# AI_ENABLED=0 (ნაგულისხმევი) — ჩატი გამორთულია; ცოდნის ბაზის მართვა (დრაფტი/დამტკიცება) მენეჯერებს მაინც შეუძლიათ.
# გასაღები მხოლოდ Railway-ის env-ში (ANTHROPIC_API_KEY); ფრონტში/ფაილში არასდროს.
def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


AI_ENABLED = _flag("AI_ENABLED", "0")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "anthropic").strip().lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-5-5").strip()
AI_EFFORT = os.environ.get("AI_EFFORT", "medium").strip().lower()          # low|medium|high — პასუხის სიღრმე/ხარჯი
AI_MAX_OUTPUT_TOKENS = int(os.environ.get("AI_MAX_OUTPUT_TOKENS", "1800"))
AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "45"))
AI_MAX_QUESTION_CHARS = int(os.environ.get("AI_MAX_QUESTION_CHARS", "1500"))
AI_HISTORY_TURNS = int(os.environ.get("AI_HISTORY_TURNS", "6"))             # წინა შეტყობინებები, რაც მოდელს გადაეცემა
AI_DAILY_LIMIT_PER_AGENT = int(os.environ.get("AI_DAILY_LIMIT_PER_AGENT", "40"))   # 0 = შეუზღუდავი
AI_MONTHLY_BUDGET_USD = float(os.environ.get("AI_MONTHLY_BUDGET_USD", "50"))        # 0 = შეუზღუდავი; ბიუჯეტის ამოწურვისას AI ითიშება
AI_RETENTION_DAYS = int(os.environ.get("AI_RETENTION_DAYS", "90"))          # საუბრების შენახვის ვადა
# ფასი $ / 1 მლნ ტოკენზე (შეფასებისთვის; ცარიელი = ცნობილი მოდელის ცხრილიდან). გადაამოწმეთ ოფიციალურ ფასებთან.
AI_PRICE_IN_PER_MTOK = os.environ.get("AI_PRICE_IN_PER_MTOK", "").strip()
AI_PRICE_OUT_PER_MTOK = os.environ.get("AI_PRICE_OUT_PER_MTOK", "").strip()
# ცოდნის ბაზა: ამ კატეგორიების გამოქვეყნება მხოლოდ ადმინს შეუძლია (თიმლიდერს — დანარჩენის)
AI_KB_RESTRICTED_CATEGORIES = {
    x.strip().lower() for x in os.environ.get("AI_KB_RESTRICTED_CATEGORIES", "commission,legal,finance").split(",") if x.strip()
}
AI_KB_TEAMLEAD_CAN_PUBLISH = _flag("AI_KB_TEAMLEAD_CAN_PUBLISH", "1")
AI_CANDIDATE_LOOKBACK_DAYS = int(os.environ.get("AI_CANDIDATE_LOOKBACK_DAYS", "60"))   # მენეჯერის პასუხები კანდიდატად ამ პერიოდიდან


# --- SAIRO: Lead Protection Engine + AI მოქმედებები + ბიუჯეტის დამცავი ----------------------------------------
# LEAD_GUARD_ENABLED=0 (ნაგულისხმევი) — ფონური შეხსენებები/ესკალაცია/დღიური ანგარიში გამორთულია (ანგარიში Mini App-ში მაინც ჩანს, ის მხოლოდ კითხვაა).
LEAD_GUARD_ENABLED = _flag("LEAD_GUARD_ENABLED", "0")
LEAD_GUARD_PILOT_TEAMS = {x.strip() for x in os.environ.get("LEAD_GUARD_PILOT_TEAMS", "").split(",") if x.strip()}   # ცარიელი = ყველა გუნდი; მითითებისას შეხსენება/ესკალაცია/ანგარიში მხოლოდ ამ გუნდებზე (პილოტი)
LEAD_GUARD_REPORT_HOUR = int(os.environ.get("LEAD_GUARD_REPORT_HOUR", "9"))                  # დღიური ანგარიში მენეჯერებს/ადმინს (თბილისი)
LEAD_GUARD_REMIND_COOLDOWN_H = float(os.environ.get("LEAD_GUARD_REMIND_COOLDOWN_H", "24"))   # ერთი საქმის შეხსენებებს შორის მინიმუმი
LEAD_GUARD_MAX_REMINDERS = int(os.environ.get("LEAD_GUARD_MAX_REMINDERS", "3"))             # ამდენი შეხსენების მერე — ესკალაცია, აღარ ვიმეორებთ
LEAD_GUARD_ESCALATE_AFTER_H = float(os.environ.get("LEAD_GUARD_ESCALATE_AFTER_H", "24"))    # რამდენი საათის გადაცილების მერე ეცნობება მენეჯერს
LEAD_GUARD_HIGH_AFTER_H = float(os.environ.get("LEAD_GUARD_HIGH_AFTER_H", "72"))            # „მაღალი რისკი“
LEAD_GUARD_SILENT_DAYS = int(os.environ.get("LEAD_GUARD_SILENT_DAYS", "3"))                 # აქტიური კლიენტი N დღეა უაქტივობაა და follow-up არ აქვს
LEAD_GUARD_SILENT_MAX_DAYS = int(os.environ.get("LEAD_GUARD_SILENT_MAX_DAYS", "30"))        # ამაზე ძველი „მიძინებული“ კლიენტი რისკად არ ითვლება
LEAD_GUARD_QUIET_FROM = int(os.environ.get("LEAD_GUARD_QUIET_FROM", "22"))                  # ღამის საათები: შეხსენება არ იგზავნება (დილას გაგრძელდება)
LEAD_GUARD_QUIET_TO = int(os.environ.get("LEAD_GUARD_QUIET_TO", "8"))
# AI ბიუჯეტი: ხისტი ზღვარი = AI_MONTHLY_BUDGET_USD × (1 − ბუფერი%); გამოძახებამდე ვამოწმებთ „ახლანდელი ხარჯი + ამ გამოძახების მაქსიმუმი“-ს
AI_BUDGET_BUFFER_PCT = float(os.environ.get("AI_BUDGET_BUFFER_PCT", "10"))
AI_MODEL_FAST = os.environ.get("AI_MODEL_FAST", "").strip()                                 # იაფი მოდელი მარტივი კითხვებისთვის (ცარიელი = მარშრუტიზაცია გამორთულია)
AI_ACTION_TTL_MINUTES = int(os.environ.get("AI_ACTION_TTL_MINUTES", "30"))                  # მოქმედების დადასტურების ვადა
AI_ACTION_MAX_RECIPIENTS = int(os.environ.get("AI_ACTION_MAX_RECIPIENTS", "60"))
AI_ACTION_MAX_MESSAGES_PER_DAY = int(os.environ.get("AI_ACTION_MAX_MESSAGES_PER_DAY", "5"))             # ჯგუფური გაგზავნა მენეჯერზე დღეში