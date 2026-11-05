"""
კადრების მოზიდვა/აყვანა (Recruitment) — წმინდა მოდელი: ცხრილების სათაურები, ეტაპები, Google Form-ის ცხრილიდან სტრიქონების გარჩევა
(ტელეფონი, თარიღები ქართულად: „4 სექტემბერი“, „4:00:00 PM“), ეტაპის დადგენა ძველი სტრიქონებიდან, რედაქტირებადი ველების გასუფთავება.
არავითარი ქსელი/Sheets-ი — მხოლოდ `fetch_sheet_rows`, რომელიც მხოლოდ წაკითხვაა და ტესტში ჩანაცვლებადია.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import re
import urllib.parse
import urllib.request

RECRUITS = "Recruits"
RECRUIT_LOG = "RecruitLog"
RECRUIT_SETTINGS = "RecruitSettings"
RECRUIT_ALERTS = "RecruitAlerts"

HEADERS = [
    "recruit_id", "created_at", "source", "src_key", "name", "phone", "phone_raw", "age", "motivation", "experience", "pref_text",
    "interview_at", "stage", "call_status", "attended", "decision", "training_at", "training_ok", "attended_t1", "attended_t2",
    "inter_lasha", "inter_owner", "inter_client", "test_score", "internship_at", "hire", "staffed_at", "left_at", "left_reason",
    "comment", "responsible_id", "last_contact_at", "next_action_at", "silent", "updated_at", "updated_by", "closed",
    # ---- დამატებული (ბოლოში): ცხრილის ყველა ველი უკლებლივ
    "pref_date", "pref_time", "inter_lasha_at", "inter_owner_at", "inter_client_at", "inter_note",
]
LOG_HEADERS = ["log_id", "recruit_id", "at", "by_name", "by_id", "kind", "text"]
SETTINGS_HEADERS = ["key", "value"]
ALERT_HEADERS = ["alert_key", "kind", "recruit_id", "to", "at"]
ALL_TABS = [(RECRUITS, HEADERS, 3000), (RECRUIT_LOG, LOG_HEADERS, 20000), (RECRUIT_SETTINGS, SETTINGS_HEADERS, 50), (RECRUIT_ALERTS, ALERT_HEADERS, 20000)]

# ეტაპები (მიმდევრობით): ბოლო სამი — დასრულებული (closed)
STAGES = {
    "new": "ახალი",
    "invited": "გასაუბრება დანიშნულია",
    "confirmed": "გასაუბრებაზე დადასტურდა",
    "interviewed": "გასაუბრება ჩატარდა",
    "considering": "განიხილება",
    "training": "ტრენინგზეა",
    "internship": "სტაჟირება",
    "staffed": "ჩაშტატდა",
    "left": "წავიდა",
    "rejected": "უარყოფილია",
    "dropped": "გადაიფიქრა / არ მოვიდა",
    "archive": "არქივი (ძველი ფორმა — შედეგი უცნობია)",
}
CLOSED_STAGES = {"left", "rejected", "dropped", "archive"}
FUNNEL = ["new", "invited", "confirmed", "interviewed", "training", "internship", "staffed"]
CALL_STATUS = {"": "დასარეკია", "confirmed": "მოდის", "declined": "არ მოდის", "no_contact": "კონტაქტი ვერ დამყარდა", "repeat": "განმეორებითი ზარი", "pending": "დადასტურებას ექვემდებარება"}
ATTENDED = {"": "—", "yes": "კი", "no": "არა", "changed": "გადაიფიქრა", "postponed": "გადადო"}
TRAIN_OK = {"": "—", "yes": "მოდის", "no": "არ მოდის", "changed": "გადაიფიქრა", "no_answer": "არ გვიპასუხა"}
# ინტერაქცია (ლაშასთან / მეპატრონესთან / კლიენტთან): დანიშნულია -> ჩატარდა -> გაიარა / ვერ გაიარა / გადაიფიქრა
INTERACTION = {"": "—", "scheduled": "დანიშნულია", "held": "ჩატარდა", "passed": "გაიარა", "failed": "ვერ გაიარა", "changed": "გადაიფიქრა"}
TRAIN_SESSIONS = ["", "ქირა", "ყიდვა", "არ მოდის/ქირა", "არ მოდის/ყიდვა", "არ გვპასუხობს", "გადაიფიქრა"]   # ტრენინგის 1/2 და 2/2 (ქირა — ქირის ტრენინგი, ყიდვა — გაყიდვის ტრენინგი)

# რედაქტირებადი ველები (ტიპი)
EDITABLE = {
    "name": "text", "phone": "phone", "age": "int", "motivation": "text", "experience": "text", "interview_at": "dt", "stage": "stage",
    "call_status": "call", "attended": "att", "decision": "decision", "training_at": "dt", "training_ok": "tok", "attended_t1": "text", "attended_t2": "text",
    "inter_lasha": "inter", "inter_owner": "inter", "inter_client": "inter", "inter_lasha_at": "date", "inter_owner_at": "date", "inter_client_at": "date", "inter_note": "text",
    "test_score": "int", "internship_at": "date", "hire": "yn", "staffed_at": "date",
    "left_at": "date", "left_reason": "text", "comment": "text", "responsible_id": "text", "next_action_at": "dt",
}
TEXT_CAP = {"motivation": 600, "comment": 600, "experience": 300, "left_reason": 200, "inter_note": 300, "attended_t1": 40, "attended_t2": 40}

_MONTHS = ["იანვ", "თებერ", "მარტ", "აპრილ", "მაის", "ივნის", "ივლის", "აგვის", "სექტემბ", "ოქტომბ", "ნოემბ", "დეკემბ"]


def _s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


# ---------------------------------------------------------------------------------------------- ტელეფონი
def norm_phone(raw) -> str:
    """ქართული მობილური: 9 ციფრი, 5-ით იწყება / 995… -> '+995XXXXXXXXX'; სხვა საერთაშორისო (≥10 ციფრი) — '+ციფრები'; სხვა — ''."""
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 9 and d.startswith("5"):
        return "+995" + d
    if len(d) == 12 and d.startswith("9955"):
        return "+" + d
    if len(d) >= 10:
        return "+" + d
    return ""


def phone_pretty(p: str) -> str:
    p = _s(p, 30)
    if p.startswith("+995") and len(p) == 13:
        return f"{p[4:7]} {p[7:9]} {p[9:11]} {p[11:13]}"
    return p


# ---------------------------------------------------------------------------------------------- თარიღები
def parse_dt(v) -> datetime.datetime | None:
    """'9/3/2026 22:23:11' (M/D/YYYY), '2026-09-03 18:00', '9/7/2026' -> datetime; ვერ ვიცანით -> None."""
    s = _s(v, 40)
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$", s)
    if m:
        y, mo, d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    else:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?)?$", s, re.I)
        if not m:
            return None
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mo, d = (a, b) if a <= 12 else (b, a)                    # ნაგულისხმევი M/D/YYYY (Google Forms), თუ პირველი >12 — D/M
        h, mi, se = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
        if (m.group(7) or "").upper() == "PM" and h < 12:
            h += 12
        if (m.group(7) or "").upper() == "AM" and h == 12:
            h = 0
    try:
        return datetime.datetime(y, mo, d, h, mi, se)
    except ValueError:
        return None


def fmt_dt(d: datetime.datetime | None) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else ""


def fmt_date(d: datetime.datetime | datetime.date | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def parse_time(v) -> str:
    """'18:00', '4:00:00 PM', '17.30' -> 'HH:MM' ან ''."""
    s = _s(v, 20)
    m = re.match(r"^(\d{1,2})[:.](\d{2})(?::\d{2})?\s*(AM|PM)?$", s, re.I)
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    if (m.group(3) or "").upper() == "PM" and h < 12:
        h += 12
    if (m.group(3) or "").upper() == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else ""


def parse_ge_date(text, ref: datetime.datetime | None) -> datetime.date | None:
    """'4 სექტემბერი', '21სექტემბერი', '4აპრილი' + საორიენტაციო თარიღი (ფორმის გაგზავნის დრო) -> თარიღი. წელი ref-იდან;
    თუ თარიღი ref-ზე 60 დღეზე მეტით ადრეა — მომდევნო წელი."""
    s = _s(text, 60).lower()
    m = re.search(r"(\d{1,2})\s*([ა-ჰ]+)", s)
    if not m:
        d = parse_dt(s)
        return d.date() if d else None
    day, word = int(m.group(1)), m.group(2)
    month = next((i + 1 for i, p in enumerate(_MONTHS) if word.startswith(p[:4])), None)
    if not month:
        return None
    ref = ref or datetime.datetime.now()
    try:
        d = datetime.date(ref.year, month, day)
    except ValueError:
        return None
    if (ref.date() - d).days > 60:
        try:
            d = datetime.date(ref.year + 1, month, day)
        except ValueError:
            return None
    return d


def row_key(ts: str, phone_raw: str, name: str) -> str:
    digits = re.sub(r"\D", "", _s(phone_raw))
    return hashlib.sha1((_s(ts) + "|" + digits + "|" + _s(name).lower()).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------------------------- მნიშვნელობები
def yn(v) -> str:
    """'კი'/'დიახ' -> 'yes', 'არა' -> 'no', 'გადაიფიქრა' -> 'changed', ცარიელი -> ''."""
    s = _s(v, 60).lower()
    if not s:
        return ""
    if s in ("yes", "no", "changed"):
        return s
    if s.startswith(("კი", "დიახ")) or s in ("მოდის", "გაიარა", "+"):
        return "yes"
    if s.startswith("არა") or s.startswith("არ მოდის"):
        return "no"
    if s.startswith("გადაიფიქრა"):
        return "changed"
    return ""


def attended_of(v) -> str:
    s = _s(v, 60).lower()
    if s in ATTENDED and s:
        return s
    if s.startswith(("კი", "დიახ")):
        return "yes"
    if s.startswith("გადადო"):
        return "postponed"
    if s.startswith("გადაიფიქრა"):
        return "changed"
    if s.startswith("არა"):
        return "no"
    return ""


def train_ok_of(v) -> str:
    s = _s(v, 60).lower()
    if s in TRAIN_OK and s:
        return s
    if "არ გვიპასუხა" in s or "არ გვპასუხობს" in s:
        return "no_answer"
    if s.startswith("გადაიფიქრა"):
        return "changed"
    if s.startswith("არ მოდის") or s.startswith("არა"):
        return "no"
    if s.startswith(("მოდის", "კი", "დიახ")):
        return "yes"
    return ""


def inter_of(v, today: datetime.date | None = None) -> tuple[str, str, str]:
    """ინტერაქციის უჯრა -> (სტატუსი, თარიღი, შენიშვნა): 'გაიარა' -> passed; თარიღი -> დანიშნულია/ჩატარდა (დღევანდელამდე — ჩატარდა); 'გადაიფიქრა' -> changed;
    დანარჩენი ტექსტი არ იკარგება — შენიშვნაში გადადის."""
    s = _s(v, 300)
    if not s:
        return "", "", ""
    low = s.lower()
    if low in INTERACTION and low:
        return low, "", ""
    if low.startswith("გაიარ"):
        return "passed", "", ""
    if low.startswith(("ვერ გაიარა", "არ გაიარა", "ჩაიჭრა")):
        return "failed", "", ""
    if low.startswith("გადაიფიქრა"):
        return "changed", "", ""
    d = parse_dt(s)
    if d:
        today = today or datetime.date.today()
        return ("held" if d.date() <= today else "scheduled"), fmt_date(d), ""
    return "", "", s


def train_info(r: dict) -> dict:
    """ტრენინგის სესიებიდან (1/2, 2/2): ჩაიტარა თუ არა ქირის / გაყიდვის (ყიდვა) ტრენინგი, გამოტოვა თუ არა."""
    t = [_s(r.get("attended_t1"), 60).lower(), _s(r.get("attended_t2"), 60).lower()]
    rent = any(x.startswith("ქირა") for x in t)
    sale = any(x.startswith("ყიდვა") for x in t)
    absent = any(x.startswith(("არ მოდის", "არ გვპასუხობს", "გადაიფიქრა")) for x in t)
    return {"rent": rent, "sale": sale, "both": rent and sale, "any": rent or sale, "absent": absent}


def call_of(v) -> str:
    s = _s(v, 60).lower()
    if s in CALL_STATUS and s:
        return s
    if s.startswith("დადასტურებას"):
        return "pending"
    if s.startswith(("კი", "მოდის")):
        return "confirmed"
    if s.startswith(("არა", "არ მოდის")):
        return "declined"
    if "კონტაქტი" in s:
        return "no_contact"
    if "განმეორ" in s:
        return "repeat"
    return ""


def decision_of(v) -> str:
    s = _s(v, 60).lower()
    if not s:
        return ""
    if s in ("accepted", "rejected", "considering"):
        return s
    if "განხილ" in s or "განიხილ" in s:
        return "considering"
    if s.startswith(("კი", "მიღებ")):
        return "accepted"
    if s.startswith(("არა", "უარ")):
        return "rejected"
    return ""


def infer_stage(r: dict) -> str:
    """ცხრილის ძველი/ხელით შევსებული სტრიქონიდან ეტაპის დადგენა (ბოლო ცნობილი)."""
    if r.get("left_at"):
        return "left"
    if r.get("staffed_at"):
        return "staffed"
    if r.get("hire") == "changed" or r.get("hire") == "no":
        return "dropped"
    if r.get("internship_at") or r.get("test_score") or any(r.get(k) in ("scheduled", "held", "passed") for k in ("inter_lasha", "inter_owner", "inter_client")):
        return "internship"
    if r.get("training_at"):
        return "dropped" if r.get("training_ok") in ("changed", "no") else "training"
    if r.get("decision") == "rejected":
        return "rejected"
    if r.get("attended") == "changed" or r.get("call_status") == "declined":
        return "dropped"
    if r.get("decision") == "considering":
        return "considering"
    if r.get("decision") == "accepted":
        return "training"
    if r.get("attended") == "yes":
        return "interviewed"
    if r.get("call_status") == "confirmed":
        return "confirmed"
    if r.get("interview_at"):
        return "invited"
    return "new"


def _find(idx: dict, *keys) -> int | None:
    for k in keys:
        for h, i in idx.items():
            if k in h:
                return i
    return None


def map_row(header: list[str], row: list[str]) -> dict | None:
    """Google Form-ის ცხრილის ერთი სტრიქონი -> ჩანაწერი (შემავსებელი ველები: წყაროს გასაღები და ა.შ.). ცარიელი/უსახელო — None.
    სვეტებს სათაურის ტექსტით ვპოულობთ (არა ადგილით) — სვეტების გადანაცვლება/დამატება აპს არ ამახინჯებს."""
    idx = {_s(h, 200).lower(): i for i, h in enumerate(header)}
    g = lambda i: _s(row[i], 600) if i is not None and i < len(row) else ""  # noqa: E731
    c_ts, c_name = _find(idx, "timestamp"), _find(idx, "სახელი")
    c_phone, c_age = _find(idx, "საკონტაქტო ნომერი"), _find(idx, "ასაკი")
    c_why, c_exp = _find(idx, "დაინტერესების მიზეზი"), _find(idx, "გამოცდილება")
    c_pd, c_pt = _find(idx, "გასაუბრების თქვენთვის მისაღები თარიღი"), _find(idx, "გასაუბრების თქვენთვის მისაღები საათი")
    c_pother = _find(idx, "კონკრეტული თარიღი")
    c_comment = _find(idx, "ჩვენი კომენტარი")
    c_pdate, c_ptime = c_pd, c_pt
    c_comes, c_att, c_dec = _find(idx, "მოდის  გასაუბრებაზე", "მოდის გასაუბრებაზე"), _find(idx, "გასაუბრებაზე იმყოფებოდა"), _find(idx, "უარყოფილია/მიღებულია")
    c_td, c_th = _find(idx, "ტრენინგის დაწყების თარიღი"), idx.get("საათი")
    c_tok = _find(idx, "მოდის/არ მოდის ტრენინგზე")
    c_t1, c_t2 = _find(idx, "ტრენინგზე 1/2"), _find(idx, "ტრენინგზე 2/2")
    c_il, c_io, c_ic = _find(idx, "ინტერაქცია ლაშასთან"), _find(idx, "ინტერაქცია მეპატრონე"), _find(idx, "ინტერაქცია კლიენტი")
    c_test, c_int, c_hire = _find(idx, "ტესტის შედეგები"), _find(idx, "სტაჟირების დაწყების"), _find(idx, "აგვყავს")
    c_staff, c_left = _find(idx, "ჩაშტატვის თარიღი"), _find(idx, "წასვლის თარიღი")

    ts_raw, name, phone_raw = g(c_ts), g(c_name), g(c_phone)
    if not name or not (ts_raw or phone_raw):
        return None
    created = parse_dt(ts_raw)
    rec = {h: "" for h in HEADERS}
    rec.update({
        "created_at": fmt_dt(created), "source": "form", "src_key": row_key(ts_raw, phone_raw, name), "name": name[:120],
        "phone": norm_phone(phone_raw), "phone_raw": phone_raw[:60], "age": re.sub(r"\D", "", g(c_age))[:3], "motivation": g(c_why)[:600],
        "experience": g(c_exp)[:300], "pref_text": g(c_pother)[:300], "comment": g(c_comment)[:600],
        "pref_date": g(c_pdate)[:60], "pref_time": g(c_ptime)[:20],
    })
    # გასაუბრების დრო: მოცემული თარიღი + საათი (წელი — გაგზავნის თარიღიდან)
    d = parse_ge_date(g(c_pd), created) or parse_ge_date(g(c_pother), created)
    t = parse_time(g(c_pt))
    if d:
        rec["interview_at"] = f"{d.strftime('%Y-%m-%d')} {t or '00:00'}"
    rec["call_status"] = call_of(g(c_comes))
    rec["attended"] = attended_of(g(c_att))
    rec["decision"] = decision_of(g(c_dec))
    td = parse_dt(g(c_td))
    if td:
        tt = parse_time(g(c_th))
        rec["training_at"] = f"{td.strftime('%Y-%m-%d')} {tt or '00:00'}"
    rec["training_ok"] = train_ok_of(g(c_tok))
    rec["attended_t1"], rec["attended_t2"] = g(c_t1)[:40], g(c_t2)[:40]
    notes = []
    for key, col in (("lasha", c_il), ("owner", c_io), ("client", c_ic)):
        st_, dt_, nt_ = inter_of(g(col))
        rec["inter_" + key], rec["inter_" + key + "_at"] = st_, dt_
        if nt_:
            notes.append({"lasha": "ლაშა", "owner": "მეპატრონე", "client": "კლიენტი"}[key] + ": " + nt_)
    rec["inter_note"] = "; ".join(notes)[:300]
    rec["test_score"] = re.sub(r"[^\d]", "", g(c_test))[:3]
    rec["internship_at"] = fmt_date(parse_dt(g(c_int)))
    rec["hire"] = yn(g(c_hire))
    rec["staffed_at"] = fmt_date(parse_dt(g(c_staff)))
    rec["left_at"] = fmt_date(parse_dt(g(c_left)))
    rec["stage"] = infer_stage(rec)
    rec["closed"] = "yes" if rec["stage"] in CLOSED_STAGES else ""
    return rec


def fetch_sheet_rows(sheet_id: str, tab: str, timeout: int = 25) -> tuple[list[str], list[list[str]]]:
    """Google Sheets-ის გვერდის წაკითხვა CSV-ად (მხოლოდ წაკითხვა; ცხრილი „ბმულის მქონე ყველასთვის (Viewer)“ უნდა იყოს გაზიარებული).
    ქსელის/ხელმისაწვდომობის შეცდომა -> RuntimeError (გასაგები ტექსტით)."""
    url = f"https://docs.google.com/spreadsheets/d/{urllib.parse.quote(sheet_id)}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(tab)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "SafeHome-CRM/1.0"}), timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("ცხრილი ვერ ჩაიტვირთა — შეამოწმეთ, რომ გაზიარებულია როგორც „ბმულის მქონე ყველასთვის — Viewer“") from e
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "<html" in text[:200].lower():
        raise RuntimeError("ცხრილი ცარიელია ან ხელმისაწვდომი არ არის (გაზიარება: ბმულის მქონე ყველასთვის — Viewer)")
    return rows[0], rows[1:]


def clean_update(data: dict) -> dict:
    """მომხმარებლისგან მოსული ველები -> გასუფთავებული {ველი: მნიშვნელობა}; უცნობი ველი იგნორირდება, არასწორი მნიშვნელობა — ValueError."""
    out: dict = {}
    for k, v in (data or {}).items():
        kind = EDITABLE.get(k)
        if not kind:
            continue
        s = _s(v, TEXT_CAP.get(k, 160))
        if kind == "phone":
            if s and not norm_phone(s):
                raise ValueError("ტელეფონი არასწორია")
            out["phone"] = norm_phone(s) if s else ""
            out["phone_raw"] = s
        elif kind == "int":
            out[k] = re.sub(r"\D", "", s)[:3]
        elif kind == "dt":
            if s and not parse_dt(s):
                raise ValueError(f"თარიღი/დრო არასწორია: {k}")
            out[k] = fmt_dt(parse_dt(s)) if s else ""
        elif kind == "date":
            if s and not parse_dt(s):
                raise ValueError(f"თარიღი არასწორია: {k}")
            out[k] = fmt_date(parse_dt(s)) if s else ""
        elif kind == "stage":
            if s not in STAGES:
                raise ValueError("ეტაპი არასწორია")
            out[k] = s
        elif kind == "call":
            if s not in CALL_STATUS:
                raise ValueError("სტატუსი არასწორია")
            out[k] = s
        elif kind == "yn":
            if s not in ("", "yes", "no", "changed"):
                raise ValueError(f"მნიშვნელობა არასწორია: {k}")
            out[k] = s
        elif kind == "att":
            if s not in ATTENDED:
                raise ValueError("„გასაუბრებაზე იყო“ — მნიშვნელობა არასწორია")
            out[k] = s
        elif kind == "tok":
            if s not in TRAIN_OK:
                raise ValueError("„ტრენინგზე მოდის“ — მნიშვნელობა არასწორია")
            out[k] = s
        elif kind == "inter":
            if s not in INTERACTION:
                raise ValueError(f"ინტერაქციის სტატუსი არასწორია: {k}")
            out[k] = s
        elif kind == "decision":
            if s not in ("", "accepted", "rejected", "considering"):
                raise ValueError("გადაწყვეტილება არასწორია")
            out[k] = s
        else:
            out[k] = s
    if "name" in out and not out["name"]:
        raise ValueError("სახელი სავალდებულოა")
    return out


def map_archive_row(header: list[str], row: list[str]) -> dict | None:
    """ძველი ფორმის ცხრილი (Sheet3, 2025): ველები იგივეა, შედეგების სვეტები არ არის -> ჩანაწერი ეტაპით „არქივი“ (დახურული, უხმო). მონაცემი არ იკარგება:
    გასაუბრების დრო, მოტივაცია, გამოცდილება, არჩეული თარიღი/საათი და კომენტარი გადმოდის; შედეგი არ გამოგვიგონია."""
    idx = {_s(h, 200).lower(): i for i, h in enumerate(header)}
    g = lambda i: _s(row[i], 600) if i is not None and i < len(row) else ""  # noqa: E731
    c_ts, c_name, c_phone, c_age = _find(idx, "timestamp"), _find(idx, "სახელი"), _find(idx, "საკონტაქტო ნომერი"), _find(idx, "ასაკი")
    c_date, c_time = _find(idx, "გასაუბრების თარიღი"), idx.get("საათი")
    c_why, c_exp = _find(idx, "დაინტერესების მიზეზი"), _find(idx, "გამოცდილება")
    c_pd, c_pt, c_po = _find(idx, "მისაღები თარიღი"), _find(idx, "მისაღები საათი"), _find(idx, "კონკრეტული თარიღი")
    c_com = _find(idx, "კომენტარი")
    ts_raw, name, phone_raw = g(c_ts), g(c_name), g(c_phone)
    if not name or not (ts_raw or phone_raw):
        return None
    created = parse_dt(ts_raw)
    rec = {h: "" for h in HEADERS}
    rec.update({
        "created_at": fmt_dt(created), "source": "archive", "src_key": "A" + row_key(ts_raw, phone_raw, name), "name": name[:120], "phone": norm_phone(phone_raw),
        "phone_raw": phone_raw[:60], "age": re.sub(r"\D", "", g(c_age))[:3], "motivation": g(c_why)[:600], "experience": g(c_exp)[:300], "comment": g(c_com)[:600],
        "pref_text": g(c_po)[:300], "pref_date": (g(c_pd) or g(c_date))[:60], "pref_time": (g(c_pt) or g(c_time))[:20],
    })
    d = parse_ge_date(g(c_date), created) or parse_ge_date(g(c_pd), created)
    t = parse_time(g(c_time)) or parse_time(g(c_pt))
    if d:
        rec["interview_at"] = f"{d.strftime('%Y-%m-%d')} {t or '00:00'}"
    rec["stage"], rec["closed"], rec["silent"] = "archive", "yes", "yes"
    return rec
