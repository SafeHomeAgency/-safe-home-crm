"""
დამატებითი (ახალი) ბიზნეს-ლოგიკა — მხოლოდ `sheets`-ის საჯარო API-ზე
დაყრდნობით, ამიტომ ერთნაირად მუშაობს Google Sheets-ზეც და Postgres-ზეც
და ორივე backend-ში დუბლირებას არ საჭიროებს.

შიგთავსი:
  1. ტელეფონის ნორმალიზაცია + კლიენტების გაერთიანებული ისტორია
  2. MyHome-ის რეალური (COMPLETED) დადებების დღიური დათვლა
  3. რაიონების სია (კვირის განაწილებისთვის)
  4. Attendance + GPS: მანძილის დათვლა, სტატუსის განსაზღვრა,
     პარამეტრები (config-ის ნაგულისხმევი + admin-ის override)
"""

from __future__ import annotations

import datetime
import math
import re

import config
import crm_time
import shift_rules
import sheets


# ====================================================================
# 1. ტელეფონი + კლიენტების გაერთიანებული ისტორია
# ====================================================================

def phone_key(value) -> str:
    """ტელეფონის შესადარებელი გასაღები: მხოლოდ ციფრები, ბოლო 9 (ქართული
    მობილური ნომრის სიგრძე) — ასე "+995 599 12 34 56", "599123456",
    "0599123456" და "995599123456" ერთსა და იმავე კლიენტად ითვლება."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-9:] if len(digits) >= 9 else digits


def _agent_team_map() -> dict[str, str]:
    return {str(a.get("agent_id")): str(a.get("team", "")).strip() for a in sheets.get_agents()}


def client_directory(team: str | None = None) -> list[dict]:
    """კლიენტების ჯამური სია — თითო უნიკალურ ნომერზე ერთი სტრიქონი,
    მიუხედავად იმისა, ნომერი რა ფორმატით ჩაიწერა და **სად** ჩაიწერა:
    დავალებაში, აგენტის რეპორტში თუ შეხვედრაში. (ძველი ვერსია მხოლოდ
    დავალებებს ითვალისწინებდა — თუ ვინმემ ნომერზე მხოლოდ რეპორტი/
    შეხვედრა გააკეთა, ის სიაში საერთოდ არ ჩანდა.)"""
    agents = {str(a.get("agent_id")): a for a in sheets.get_agents()}
    team_of = _agent_team_map()
    groups: dict[str, dict] = {}

    def bucket(raw_phone):
        key = phone_key(raw_phone)
        if not key:
            return None
        return groups.setdefault(key, {
            "phone_variants": set(), "tasks": [], "reports": [], "meetings": [], "agent_ids": set(),
        })

    for t in sheets.get_tasks():
        b = bucket(t.get("client_phone"))
        if b is None:
            continue
        b["phone_variants"].add(str(t.get("client_phone")).strip())
        b["tasks"].append(t)
        b["agent_ids"].add(str(t.get("assigned_to")))
    for r in sheets.get_reports():
        b = bucket(r.get("client_phone"))
        if b is None:
            continue
        b["phone_variants"].add(str(r.get("client_phone")).strip())
        b["reports"].append(r)
        b["agent_ids"].add(str(r.get("agent_id")))
    for m in sheets.get_meetings():
        b = bucket(m.get("client_phone"))
        if b is None:
            continue
        b["phone_variants"].add(str(m.get("client_phone")).strip())
        b["meetings"].append(m)
        b["agent_ids"].add(str(m.get("agent_id")))

    out = []
    for key, g in groups.items():
        if team is not None and not any(team_of.get(aid, "") == team for aid in g["agent_ids"]):
            continue
        tasks = sorted(g["tasks"], key=lambda t: str(t.get("created_at", "")))
        reports = sorted(g["reports"], key=lambda r: str(r.get("created_at", "")))
        meetings = sorted(g["meetings"], key=lambda m: str(m.get("timestamp", "")))
        stamps = (
            [str(t.get("updated_at") or t.get("created_at", "")) for t in tasks]
            + [str(r.get("created_at", "")) for r in reports]
            + [str(m.get("timestamp", "")) for m in meetings]
        )
        stamps = [s for s in stamps if s]
        firsts = (
            [str(t.get("created_at", "")) for t in tasks]
            + [str(r.get("created_at", "")) for r in reports]
            + [str(m.get("timestamp", "")) for m in meetings]
        )
        firsts = [s for s in firsts if s]
        if tasks:
            latest = tasks[-1]
            cur_id = latest.get("assigned_to")
            cur_name = latest.get("assigned_to_name") or (agents.get(str(cur_id)) or {}).get("name", "")
            status = latest.get("status")
            deal = latest.get("deal_type") or latest.get("lead_type")
        else:
            src = (reports or meetings)[-1]
            cur_id = src.get("agent_id")
            cur_name = src.get("agent_name") or (agents.get(str(cur_id)) or {}).get("name", "")
            status = "—"
            deal = ""
        display = sorted(g["phone_variants"], key=len, reverse=True)[0] if g["phone_variants"] else key
        out.append({
            "client_phone": display,
            "phone_key": key,
            "current_agent_id": cur_id,
            "current_agent_name": cur_name,
            "status": status,
            "deal_type": deal,
            "task_count": len(tasks),
            "report_count": len(reports),
            "meeting_count": len(meetings),
            "first_seen": min(firsts) if firsts else "",
            "last_activity": max(stamps) if stamps else "",
        })
    out.sort(key=lambda c: str(c.get("last_activity") or ""), reverse=True)
    return out


def client_history(phone: str) -> dict:
    """ერთი ნომრის **ყველა** კვალი სისტემაში: დავალებები, აგენტის
    რეპორტები, შეხვედრები, ექსკლუზივები (როგორც მესაკუთრის ნომერი),
    MyHome დადებები (როგორც მესაკუთრის ნომერი) — ერთად.
    `agent_ids` — ყველა აგენტი, ვისაც ამ ნომერთან შეხება ჰქონია
    (მენეჯერისთვის წვდომის შესამოწმებლად)."""
    key = phone_key(phone)
    if not key:
        return {"tasks": [], "reports": [], "meetings": [], "exclusives": [], "myhome_jobs": [], "agent_ids": set()}
    tasks = [t for t in sheets.get_tasks() if phone_key(t.get("client_phone")) == key or phone_key(t.get("owner_phone")) == key]
    reports = [r for r in sheets.get_reports() if phone_key(r.get("client_phone")) == key]
    meetings = [
        m for m in sheets.get_meetings()
        if phone_key(m.get("client_phone")) == key or phone_key(m.get("owner_phone")) == key
    ]
    exclusives = [e for e in sheets.get_exclusives() if phone_key(e.get("owner_phone")) == key]
    myhome = [j for j in sheets.get_myhome_jobs() if phone_key(j.get("owner_number")) == key]
    agent_ids = set()
    for t in tasks:
        agent_ids.add(str(t.get("assigned_to")))
    for r in reports:
        agent_ids.add(str(r.get("agent_id")))
    for m in meetings:
        agent_ids.add(str(m.get("agent_id")))
    for e in exclusives:
        agent_ids.add(str(e.get("agent_id")))
    for j in myhome:
        agent_ids.add(str(j.get("agent_id")))
    return {
        "tasks": tasks, "reports": reports, "meetings": meetings,
        "exclusives": exclusives, "myhome_jobs": myhome, "agent_ids": agent_ids,
    }


# ====================================================================
# 2. MyHome-ის რეალური დადებების დღიური დათვლა (რეგლამენტისთვის)
# ====================================================================

def count_myhome_completed_today(agent_id: str) -> int:
    """worker.py-ს მიერ რეალურად დადებული (COMPLETED) MyHome განცხადებები
    დღეს (თბილისის დღე) — აგენტის ხელით შეყვანილი რიცხვის ნაცვლად."""
    start, end = crm_time.local_day_bounds_server_naive()
    total = 0
    for j in sheets.get_myhome_jobs(agent_id=agent_id, status="COMPLETED"):
        done = crm_time.parse_server_dt(j.get("completed_at"))
        if done and start <= done < end:
            total += 1
    return total


def _is_invalid_listing_job(j: dict) -> bool:
    """მუდმივი "ლისტინგი წაშლილია/არ არსებობს" (LISTING_UNAVAILABLE) — ამას აგენტის
    არასწორი/გაუქმებული ID იწვევს და არა ჩვენი სისტემა; ასეთი job არ ითვლება."""
    return str(j.get("status")) == "FAILED" and (
        str(j.get("failure_stage") or "") == "permanent"
        or "LISTING_UNAVAILABLE" in str(j.get("error_message") or "")
    )


def count_myhome_submitted_today(agent_id: str) -> int:
    """რამდენი MyHome განცხადება **გაგზავნა/შეიყვანა აგენტმა** დღეს (თბილისის დღე) —
    სტატუსის მიუხედავად (QUEUED / PROCESSING / COMPLETED / FAILED). ამით აგენტს არ ვაზარალებთ
    იმით, რომ დადება ჩვენთან ჯერ რიგშია, ან ჩვენი მხრიდან ჩავარდა (ტექნიკური შეცდომა).

    ერთადერთი გამონაკლისი: მუდმივად არარსებული/წაშლილი ლისტინგის ID (LISTING_UNAVAILABLE) —
    ეს აგენტის შეყვანილი არასწორი ID-ია და მუშაობად არ ითვლება (რომ ყალბი ID-ებით
    რიცხვის გაბერვა შეუძლებელი იყოს). დუბლიკატი (იგივე აგენტი+ID+დღე) job-ად საერთოდ არ იქმნება."""
    start, end = crm_time.local_day_bounds_server_naive()
    total = 0
    for j in sheets.get_myhome_jobs(agent_id=agent_id):
        created = crm_time.parse_server_dt(j.get("created_at"))
        if created and start <= created < end and not _is_invalid_listing_job(j):
            total += 1
    return total


# ====================================================================
# 3. რაიონები (კვირის განაწილებისთვის)
# ====================================================================

DISTRICT_GROUPS: list[tuple[str, list[str]]] = [
    ("ვაკე-საბურთალო", [
        "ლისის მიმდებარედ", "ბაგები", "ვაკე", "ვაშლიჯვარი", "ვეძისი", "თხინვალი",
        "კუს ტბა", "ლისი", "მუხათგვერდი", "მუხათწყარო", "საბურთალო", "დიღომი 1-9",
        "ნუცუბიძის ფერდობი", "სოფ. დიღომი", "დიღმის ჭალა", "ქოშიგორა", "დიდგორი",
        "დიდი დიღომი",
    ]),
    ("ძველი თბილისი", [
        "ელია", "ვერა", "კრწანისი", "მთაწმინდა", "სოლოლაკი", "აბანოთუბანი",
        "ავლაბარი", "წავკისის ველი", "ორთაჭალა",
    ]),
    ("დიდუბე-ჩუღურეთი", [
        "დიდუბე", "დიღმის მასივი", "კუკია", "ჩუღურეთი", "ივერთუბანი", "სვანეთის უბანი",
    ]),
    ("გლდანი-ნაძალადევი", [
        "ლოტკინი", "გლდანი", "გლდანულა", "თბილისის ზღვა", "თემქა", "კონიაკის დასახლება",
        "მუხიანი", "ნაძალადევი", "ავშნიანი", "ავჭალა", "ზაჰესი", "სოფ. გლდანი",
        "სან. ზონა", "გიორგიწმინდას დასახლება",
    ]),
    ("ისანი-სამგორი", [
        "ისანი", "მოსკოვის გამზირი", "ვარკეთილი", "ლილო", "მესამე მასივი", "აფრიკა",
        "ნავთლუღი", "აეროპორტის დასახლება", "დამპალოს დასახლება", "ვაზისუბანი",
        "ორხევი", "სამგორი", "ფონიჭალა",
    ]),
    ("თბილისის შემოგარენი", [
        "ახალდაბა", "ბეთანია", "კაკლები", "კიკეთი", "კოჯორი", "ოქროყანა",
        "ტაბახმელა", "შინდისი", "წავკისი", "წყნეთი", "ზემო ლისი", "წვერი",
        "მსხალდიდი", "წოდორეთი", "კვესეთი",
    ]),
]

VALID_DISTRICTS: set[str] = {name for group, kids in DISTRICT_GROUPS for name in [group, *kids]}


def districts_catalog() -> list[dict]:
    return [{"group": g, "districts": list(kids)} for g, kids in DISTRICT_GROUPS]


def clean_districts(values) -> list[str]:
    """მხოლოდ ცნობილი რაიონები, დუბლიკატების გარეშე, თავდაპირველი რიგით."""
    seen, out = set(), []
    for v in values or []:
        name = str(v).strip()
        if name in VALID_DISTRICTS and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def split_districts(joined: str) -> list[str]:
    return [d for d in str(joined or "").split("|") if d.strip()]


def week_label(week_start: datetime.date) -> str:
    end = week_start + datetime.timedelta(days=6)
    return f"{week_start.strftime('%d.%m')} – {end.strftime('%d.%m.%Y')}"


# ====================================================================
# 4. Attendance + GPS
# ====================================================================

_SETTING_KEYS = (
    "office_name", "office_latitude", "office_longitude", "office_radius_meters",
    "max_accuracy_meters", "allow_outside_checkin",
)


def _truthy(v) -> bool:
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")


def attendance_settings() -> dict:
    """ეფექტური პარამეტრები: config-ის (ENV) ნაგულისხმევი, რომელსაც
    admin-ის მიერ Mini App-იდან შენახული მნიშვნელობა (AppSettings)
    გადაწერს, თუ არსებობს. ყოველი გამოძახებისას ახლიდან იკითხება —
    admin-ის ცვლილება მაშინვე მოქმედებს, restart არ სჭირდება."""
    try:
        override = sheets.get_app_settings()
    except Exception:
        override = {}

    def pick(key, default):
        v = override.get(key)
        return default if v is None or str(v).strip() == "" else v

    def as_float(v):
        try:
            return float(str(v).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None

    def as_int(v, fallback):
        try:
            return int(float(str(v).strip()))
        except (TypeError, ValueError):
            return fallback

    lat = as_float(pick("office_latitude", config.OFFICE_LATITUDE))
    lng = as_float(pick("office_longitude", config.OFFICE_LONGITUDE))
    return {
        "office_name": str(pick("office_name", config.OFFICE_NAME)),
        "office_latitude": lat,
        "office_longitude": lng,
        "office_radius_meters": as_int(pick("office_radius_meters", config.OFFICE_RADIUS_METERS), config.OFFICE_RADIUS_METERS),
        "max_accuracy_meters": as_int(pick("max_accuracy_meters", config.MAX_ACCEPTABLE_ACCURACY_METERS), config.MAX_ACCEPTABLE_ACCURACY_METERS),
        "allow_outside_checkin": _truthy(pick("allow_outside_checkin", "1" if config.ALLOW_OUTSIDE_CHECKIN else "0")),
        "configured": lat is not None and lng is not None,
    }


def validate_settings_input(body: dict) -> tuple[dict, str | None]:
    """admin-ის მიერ გამოგზავნილი პარამეტრების გასუფთავება/ვალიდაცია.
    აბრუნებს (გასაწერი key->str, შეცდომის ტექსტი|None)."""
    out: dict[str, str] = {}
    if "office_name" in body:
        out["office_name"] = str(body.get("office_name") or "").strip()[:80]
    for key, lo, hi in (("office_latitude", -90, 90), ("office_longitude", -180, 180)):
        if key in body:
            raw = str(body.get(key) or "").strip().replace(",", ".")
            if raw == "":
                out[key] = ""
                continue
            try:
                val = float(raw)
            except ValueError:
                return {}, f"{key}: არასწორი რიცხვი"
            if not (lo <= val <= hi):
                return {}, f"{key}: დიაპაზონი {lo}..{hi}"
            out[key] = repr(val)
    for key, lo, hi in (("office_radius_meters", 10, 5000), ("max_accuracy_meters", 10, 2000)):
        if key in body:
            try:
                val = int(float(str(body.get(key)).strip()))
            except (TypeError, ValueError):
                return {}, f"{key}: არასწორი რიცხვი"
            if not (lo <= val <= hi):
                return {}, f"{key}: დიაპაზონი {lo}..{hi}"
            out[key] = str(val)
    if "allow_outside_checkin" in body:
        out["allow_outside_checkin"] = "1" if _truthy(body.get("allow_outside_checkin")) else "0"
    lat_set = "office_latitude" in out
    lng_set = "office_longitude" in out
    if lat_set != lng_set:
        return {}, "განედი და გრძედი ერთად უნდა მიეთითოს"
    return out, None


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_geo_input(body) -> tuple[dict | None, str | None]:
    """მოთხოვნის `geo`/ზედა დონის {lat,lng,accuracy}-ის ვალიდაცია.
    აბრუნებს ({lat,lng,accuracy}|None, შეცდომა|None). None+None =
    ლოკაცია საერთოდ არ გამოგზავნილა."""
    geo = body.get("geo") if isinstance(body.get("geo"), dict) else body
    if geo is None or ("lat" not in geo and "lng" not in geo):
        return None, None
    try:
        lat = float(geo.get("lat"))
        lng = float(geo.get("lng"))
    except (TypeError, ValueError):
        return None, "invalid_location"
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None, "invalid_location"
    try:
        acc = float(geo.get("accuracy"))
        if acc < 0:
            acc = None
    except (TypeError, ValueError):
        acc = None
    return {"lat": lat, "lng": lng, "accuracy": acc}, None


def evaluate_location(geo: dict, settings: dict) -> dict:
    """სერვერის მხარეს მანძილისა და სტატუსის განსაზღვრა (frontend-ს
    მხოლოდ კოორდინატები მოაქვს, ოფისის კოორდინატი/რადიუსი/სიზუსტის
    ზღვარი არასდროს გადის კლიენტზე და მასზე არ არის დამოკიდებული)."""
    note = []
    lat_s, lng_s = repr(geo["lat"]), repr(geo["lng"])
    if all(len(s.split(".")[-1]) <= 3 for s in (lat_s, lng_s) if "." in s):
        note.append("low_precision_coords")
    acc = geo.get("accuracy")
    if not settings["configured"]:
        return {"distance_m": None, "geo_status": "NOT_CONFIGURED", "reliable": acc is not None, "note": ",".join(note)}
    dist = haversine_m(geo["lat"], geo["lng"], settings["office_latitude"], settings["office_longitude"])
    if acc is None or acc > settings["max_accuracy_meters"]:
        status = "LOCATION_UNRELIABLE"
    elif dist <= settings["office_radius_meters"]:
        status = "OFFICE"
    else:
        status = "OUTSIDE_OFFICE"
    return {"distance_m": int(round(dist)), "geo_status": status, "reliable": status != "LOCATION_UNRELIABLE", "note": ",".join(note)}


def shift_start_hour(mode: str) -> int | None:
    return {"office_morning": 10, "office_evening": 16}.get(mode)


def is_late(mode: str, local_dt: datetime.datetime) -> bool:
    """იგივე წესი, რასაც ბოტის `check_late_arrivals` იყენებს: ოფისის
    ცვლის დაწყება (10:00/16:00) + ATTENDANCE_GRACE_MINUTES."""
    return shift_rules.is_late_open(mode, local_dt)


def fmt_hours(minutes: int | None) -> str:
    if minutes is None or minutes < 0:
        return ""
    return f"{minutes // 60}სთ {minutes % 60}წთ"


GEO_STATUS_LABELS = {
    "OFFICE": "🏢 ოფისში",
    "OUTSIDE_OFFICE": "📍 ოფისის გარეთ",
    "LOCATION_UNRELIABLE": "⚠️ არასანდო ლოკაცია",
    "NOT_CONFIGURED": "—",
}

STATE_LABELS = {
    "NOT_STARTED": "🔴 არ დაუწყია",
    "ACTIVE": "🟢 მუშაობს",
    "COMPLETED": "✅ დასრულებული",
    "MISSING_CHECKOUT": "❗ დასრულება არ დაუფიქსირებია",
    "DAY_OFF": "🏖 დასვენების დღე",
    "OFF": "🌙 გამოსავალი",
}


def _is_active_agent(a: dict) -> bool:
    return str(a.get("active", "yes")).strip().lower() not in ("no", "false", "0")


def _hhmm_from_server(value) -> str:
    dt = crm_time.parse_server_dt(value)
    return crm_time.server_naive_to_local(dt).strftime("%H:%M") if dt else ""


def _hhmm_from_event(ev) -> str:
    dt = crm_time.utc_iso_to_local((ev or {}).get("at_utc"))
    return dt.strftime("%H:%M") if dt else ""


def _last_event(events: list[dict], kind: str) -> dict | None:
    evs = sorted((e for e in events if e.get("event") == kind), key=lambda e: str(e.get("at_utc", "")))
    return evs[-1] if evs else None


def _minutes_between(att: dict, in_ev: dict | None, out_ev: dict | None) -> int | None:
    a = crm_time.utc_iso_to_local((in_ev or {}).get("at_utc"))
    b = crm_time.utc_iso_to_local((out_ev or {}).get("at_utc"))
    if a and b:
        return int((b - a).total_seconds() // 60)
    a2 = crm_time.parse_server_dt(att.get("clock_in"))
    b2 = crm_time.parse_server_dt(att.get("clock_out"))
    if a2 and b2:
        return int((b2 - a2).total_seconds() // 60)
    return None


def _dayoff_dates() -> set[tuple[str, str]]:
    out = set()
    for r in sheets.get_dayoff_requests(status="approved"):
        d = crm_time.parse_user_date(r.get("date", ""))
        if d:
            out.add((str(r.get("agent_id")), d.strftime(crm_time.DATE_FMT)))
    return out


def _state_for(att: dict | None, day_str: str, expected_mode: str, on_dayoff: bool) -> str:
    today = crm_time.local_today().strftime(crm_time.DATE_FMT)
    if att and att.get("clock_in"):
        if att.get("clock_out"):
            return "COMPLETED"
        past = day_str < today
        late_today = day_str == today and crm_time.local_now().hour >= config.MISSING_CHECKOUT_HOUR
        return "MISSING_CHECKOUT" if (past or late_today) else "ACTIVE"
    if on_dayoff:
        return "DAY_OFF"
    if expected_mode == "off":
        return "OFF"
    return "NOT_STARTED"


def _row_for(agent: dict, day_str: str, att: dict | None, events: list[dict],
             expected_mode: str, on_dayoff: bool) -> dict:
    in_ev = _last_event(events, "check_in")
    out_ev = _last_event(events, "check_out")
    state = _state_for(att, day_str, expected_mode, on_dayoff)
    mode = (att or {}).get("mode") or expected_mode
    in_time = _hhmm_from_event(in_ev) or _hhmm_from_server((att or {}).get("clock_in"))
    out_time = _hhmm_from_event(out_ev) or _hhmm_from_server((att or {}).get("clock_out"))
    minutes = _minutes_between(att or {}, in_ev, out_ev) if (att and att.get("clock_out")) else None
    late = False
    if att and att.get("clock_in"):
        if in_ev:
            late = str(in_ev.get("late", "")).lower() == "yes"
        else:
            dt = crm_time.parse_server_dt(att.get("clock_in"))
            late = bool(dt and is_late(mode, crm_time.server_naive_to_local(dt)))
    return {
        "agent_id": agent.get("agent_id"),
        "agent_name": agent.get("name"),
        "team": str(agent.get("team", "")).strip(),
        "date": day_str,
        "mode": mode,
        "state": state,
        "state_label": STATE_LABELS.get(state, state),
        "check_in": in_time,
        "check_in_geo": (in_ev or {}).get("geo_status", ""),
        "check_in_distance": (in_ev or {}).get("distance_m", ""),
        "check_in_accuracy": (in_ev or {}).get("accuracy", ""),
        "check_in_lat": (in_ev or {}).get("lat", ""),
        "check_in_lng": (in_ev or {}).get("lng", ""),
        "check_out": out_time,
        "check_out_geo": (out_ev or {}).get("geo_status", ""),
        "check_out_distance": (out_ev or {}).get("distance_m", ""),
        "check_out_accuracy": (out_ev or {}).get("accuracy", ""),
        "check_out_lat": (out_ev or {}).get("lat", ""),
        "check_out_lng": (out_ev or {}).get("lng", ""),
        "minutes": minutes,
        "hours_text": fmt_hours(minutes),
        "late": late,
        "note": (in_ev or {}).get("note", ""),
    }


def attendance_card(agent: dict) -> dict:
    """აგენტის დღევანდელი Attendance ბარათი (Mini App-ის მთავარი
    ეკრანისა და /attendance ბოტ-ბრძანებისთვის)."""
    agent_id = agent["agent_id"]
    settings = attendance_settings()
    today = crm_time.local_today().strftime(crm_time.DATE_FMT)
    att = sheets.get_today_attendance(agent_id)
    events = sheets.get_attendance_geo_events(agent_id=agent_id, date_from=today, date_to=today)
    mode = sheets.get_today_mode(agent_id)
    on_dayoff = (str(agent_id), today) in _dayoff_dates()
    row = _row_for(agent, today, att, events, mode, on_dayoff)
    row.update({
        "gps_enabled": settings["configured"],
        "allow_outside": settings["allow_outside_checkin"],
        "radius_m": settings["office_radius_meters"],
        "can_start": not (att and att.get("clock_in")),
        "can_finish": bool(att and att.get("clock_in") and not att.get("clock_out")),
    })
    return row


def check_in(agent: dict, geo: dict | None) -> dict:
    """სამუშაოს დაწყება (სერვერის მხარეს ვერიფიკაციით). აბრუნებს
    {"ok": bool, "code": str, ...}. შეცდომის შემთხვევაში არაფერი არ
    ჩაიწერება (არც Attendance, არც ივენთი)."""
    agent_id = agent["agent_id"]
    settings = attendance_settings()
    att = sheets.get_today_attendance(agent_id)
    if att and att.get("clock_in"):
        return {"ok": True, "result": "already", "code": "already"}
    if settings["configured"] and geo is None:
        return {"ok": False, "code": "location_required",
                "message": "📍 Location permission საჭიროა სამუშაოს დაწყების დასადასტურებლად."}
    mode = sheets.get_today_mode(agent_id)
    office_shift = mode in ("office_morning", "office_evening")
    ev = evaluate_location(geo, settings) if geo else None
    if ev and ev["geo_status"] == "OUTSIDE_OFFICE" and office_shift and not settings["allow_outside_checkin"]:
        km = ev["distance_m"] / 1000
        dist = f"{km:.1f} კმ" if ev["distance_m"] >= 1000 else f"{ev['distance_m']} მ"
        return {"ok": False, "code": "outside_office", "distance_m": ev["distance_m"],
                "message": f"⚠️ თქვენ იმყოფებით ოფისის გეოზონის გარეთ.\nოფისიდან დაშორება: {dist}"}
    result = sheets.clock_in(agent_id)
    if result != "ok":
        return {"ok": True, "result": result, "code": result}
    late = is_late(mode, crm_time.local_now())
    event = None
    if geo and ev:
        event = sheets.add_attendance_geo_event(
            agent_id, "check_in", repr(geo["lat"]), repr(geo["lng"]),
            "" if geo.get("accuracy") is None else str(round(geo["accuracy"], 1)),
            "" if ev["distance_m"] is None else str(ev["distance_m"]),
            ev["geo_status"], mode=mode, late="yes" if late else "no", note=ev["note"],
        )
    return {
        "ok": True, "result": "ok", "code": "ok", "mode": mode, "office_shift": office_shift,
        "late": late, "event": event,
        "geo_status": (ev or {}).get("geo_status", ""), "distance_m": (ev or {}).get("distance_m"),
    }


def check_out_precheck(agent: dict, geo: dict | None) -> dict | None:
    """სამუშაოს დასრულებამდე წინასწარი შემოწმება — თუ GPS ჩართულია და
    ლოკაცია არ გამოუგზავნია, დღე არ იხურება (შეცდომა), რომ არაფერი
    ნახევრად არ ჩაიწეროს. None = გაგრძელება შეიძლება."""
    settings = attendance_settings()
    if settings["configured"] and geo is None:
        att = sheets.get_today_attendance(agent["agent_id"])
        if att and att.get("clock_in") and not att.get("clock_out"):
            return {"code": "location_required",
                    "message": "📍 Location permission საჭიროა სამუშაოს დასრულების დასადასტურებლად."}
    return None


def record_check_out(agent: dict, geo: dict | None) -> dict | None:
    """დასრულების ლოკაციის ივენთის ჩაწერა (გამოიძახება მხოლოდ მას
    შემდეგ, რაც `sheets.clock_out` წარმატებით შესრულდა)."""
    if not geo:
        return None
    settings = attendance_settings()
    ev = evaluate_location(geo, settings)
    mode = sheets.get_today_mode(agent["agent_id"])
    return sheets.add_attendance_geo_event(
        agent["agent_id"], "check_out", repr(geo["lat"]), repr(geo["lng"]),
        "" if geo.get("accuracy") is None else str(round(geo["accuracy"], 1)),
        "" if ev["distance_m"] is None else str(ev["distance_m"]),
        ev["geo_status"], mode=mode, late="no", note=ev["note"],
    )


def checkin_alert_text(agent: dict, res: dict) -> str | None:
    """მენეჯერის/ადმინის შეტყობინება: ოფისის ცვლაზე ოფისის გარედან
    დაწყება ან არასანდო ლოკაცია. ონლაინ დღეზე ოფისის გარეთ ყოფნა
    მოსალოდნელია — იქ გაფრთხილება არ იგზავნება."""
    status = res.get("geo_status")
    if status == "LOCATION_UNRELIABLE":
        title = "⚠️ Location accuracy too low"
    elif status == "OUTSIDE_OFFICE" and res.get("office_shift"):
        title = "🔴 სამუშაო დაიწყო ოფისის გარეთ"
    else:
        return None
    dist = res.get("distance_m")
    dist_text = "" if dist is None else (f"{dist / 1000:.1f} კმ" if dist >= 1000 else f"{dist} მ")
    now_local = crm_time.local_now().strftime("%H:%M")
    return (
        f"{title}\nთანამშრომელი: {agent.get('name')}\nდრო: {now_local}\n"
        f"დაშორება: {dist_text or '—'}\nსტატუსი: {status}"
    )


def attendance_overview(day_str: str, team: str | None = None, agent_id: str | None = None,
                        state: str = "", geo: str = "", late_only: bool = False) -> dict:
    """დღის დასწრების ცხრილი + შეჯამება. `team` — მხოლოდ ამ გუნდის
    აგენტები (თიმლიდერისთვის სერვერი თავად აიძულებს საკუთარ გუნდს),
    ადმინისთვის None = ყველა."""
    day = crm_time.parse_user_date(day_str) or crm_time.local_today()
    day_str = day.strftime(crm_time.DATE_FMT)
    weekday_key = sheets.WEEKDAY_KEYS[day.weekday()]
    agents = [a for a in sheets.get_agents() if _is_active_agent(a)]
    if team is not None:
        agents = [a for a in agents if str(a.get("team", "")).strip() == team]
    if agent_id:
        agents = [a for a in agents if str(a.get("agent_id")) == str(agent_id)]
    att_by = {str(r.get("agent_id")): r for r in sheets.get_attendance_records(date_from=day_str, date_to=day_str)}
    events = sheets.get_attendance_geo_events(date_from=day_str, date_to=day_str)
    ev_by: dict[str, list[dict]] = {}
    for e in events:
        ev_by.setdefault(str(e.get("agent_id")), []).append(e)
    dayoffs = _dayoff_dates()

    rows = []
    for a in agents:
        aid = str(a.get("agent_id"))
        sched = sheets.get_agent_schedule(aid) or {}
        expected = str(sched.get(weekday_key) or "off")
        rows.append(_row_for(a, day_str, att_by.get(aid), ev_by.get(aid, []), expected, (aid, day_str) in dayoffs))

    summary = {
        "date": day_str, "total": 0, "started": 0, "office": 0, "outside": 0,
        "unreliable": 0, "not_started": 0, "completed": 0, "missing_checkout": 0,
        "late": 0, "day_off": 0, "working": 0,
    }
    for r in rows:
        if r["state"] in ("OFF",):
            continue
        summary["total"] += 1
        if r["state"] == "DAY_OFF":
            summary["day_off"] += 1
            continue
        if r["state"] == "NOT_STARTED":
            summary["not_started"] += 1
            continue
        summary["started"] += 1
        if r["state"] == "ACTIVE":
            summary["working"] += 1
        if r["state"] == "COMPLETED":
            summary["completed"] += 1
        if r["state"] == "MISSING_CHECKOUT":
            summary["missing_checkout"] += 1
        if r["late"]:
            summary["late"] += 1
        g = r["check_in_geo"]
        if g == "OFFICE":
            summary["office"] += 1
        elif g == "OUTSIDE_OFFICE":
            summary["outside"] += 1
        elif g == "LOCATION_UNRELIABLE":
            summary["unreliable"] += 1

    if state:
        rows = [r for r in rows if r["state"] == state]
    if geo:
        rows = [r for r in rows if r["check_in_geo"] == geo]
    if late_only:
        rows = [r for r in rows if r["late"]]
    order = {"MISSING_CHECKOUT": 0, "NOT_STARTED": 1, "ACTIVE": 2, "COMPLETED": 3, "DAY_OFF": 4, "OFF": 5}
    rows.sort(key=lambda r: (order.get(r["state"], 9), str(r.get("agent_name") or "")))
    return {"summary": summary, "rows": rows[:500]}


def attendance_history(agent: dict, month: str = "") -> list[dict]:
    """ერთი აგენტის თვის დასწრების ისტორია (YYYY-MM; ცარიელი = მიმდინარე)."""
    month = month if re.fullmatch(r"\d{4}-\d{2}", month or "") else crm_time.local_today().strftime("%Y-%m")
    first = datetime.datetime.strptime(month + "-01", crm_time.DATE_FMT).date()
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    last = nxt - datetime.timedelta(days=1)
    d_from, d_to = first.strftime(crm_time.DATE_FMT), last.strftime(crm_time.DATE_FMT)
    aid = str(agent["agent_id"])
    records = sheets.get_attendance_records(agent_id=aid, date_from=d_from, date_to=d_to)
    events = sheets.get_attendance_geo_events(agent_id=aid, date_from=d_from, date_to=d_to)
    ev_by_day: dict[str, list[dict]] = {}
    for e in events:
        ev_by_day.setdefault(str(e.get("date")), []).append(e)
    out = []
    for r in sorted(records, key=lambda r: str(r.get("date")), reverse=True):
        d = str(r.get("date"))
        out.append(_row_for(agent, d, r, ev_by_day.get(d, []), str(r.get("mode") or "off"), False))
    return out


def attendance_csv(date_from: str, date_to: str, team: str | None = None) -> str:
    """CSV (UTF-8, Excel-ისთვის BOM-ით აგენტზე): Date, Employee, Manager,
    Team, Check-in..., Hours, Late, Location reliability."""
    import csv
    import io
    agents = {str(a.get("agent_id")): a for a in sheets.get_agents()}
    leads = {
        str(a.get("team", "")).strip(): a.get("name", "")
        for a in agents.values() if str(a.get("role", "")).strip() == "team_lead"
    }
    records = sheets.get_attendance_records(date_from=date_from, date_to=date_to)
    events = sheets.get_attendance_geo_events(date_from=date_from, date_to=date_to)
    ev_by: dict[tuple[str, str], list[dict]] = {}
    for e in events:
        ev_by.setdefault((str(e.get("agent_id")), str(e.get("date"))), []).append(e)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Employee", "Manager", "Team", "Check-in", "Check-in distance (m)",
                "Check-in status", "Check-out", "Check-out distance (m)", "Check-out status",
                "Hours", "Late", "Location reliability"])
    for r in sorted(records, key=lambda r: (str(r.get("date")), str(r.get("agent_name")))):
        a = agents.get(str(r.get("agent_id")))
        if not a:
            continue
        tm = str(a.get("team", "")).strip()
        if team is not None and tm != team:
            continue
        row = _row_for(a, str(r.get("date")), r, ev_by.get((str(r.get("agent_id")), str(r.get("date"))), []),
                       str(r.get("mode") or "off"), False)
        reliable = ""
        if row["check_in_geo"]:
            reliable = "no" if row["check_in_geo"] == "LOCATION_UNRELIABLE" else "yes"
        w.writerow([
            row["date"], row["agent_name"], leads.get(tm, ""), tm, row["check_in"],
            row["check_in_distance"], row["check_in_geo"], row["check_out"],
            row["check_out_distance"], row["check_out_geo"], row["hours_text"],
            "yes" if row["late"] else "no", reliable,
        ])
    return buf.getvalue()
