"""
TGNET (Telegram არხების ქსელი) — ცხრილების აღწერა და წმინდა წესები. არსებულ ცხრილებს არაფერი ეხება; ახალი ცხრილები იქმნება ზარმაცად (tab_backend).

ეტაპი 2B: მხოლოდ არხების რეესტრი + ჯანმრთელობის შემოწმება. პოსტინგი ამ ეტაპზე **არ არსებობს** (TgPosts მომავალი ეტაპისთვისაა).
"""

from __future__ import annotations

import re

TG_CHANNELS = "TgChannels"
TG_POSTS = "TgPosts"
TG_SETTINGS = "TgSettings"
TG_LOG = "TgLog"

HEADERS = ["channel_key", "n", "lang", "segment", "deal", "city", "title", "username", "chat_id", "link", "enabled", "status", "members", "members_at",
           "last_check_at", "last_error", "note", "description"]
POST_HEADERS = ["post_id", "listing_key", "channel_key", "message_ids", "status", "posted_at", "updated_at", "error", "created_at", "decided_by", "decided_at", "summary", "agent_name"]
# post_id = "<listing_key>:<channel_key>" (განმეორებითი გაშვება დუბლს ვერ ქმნის). status: pending (ელოდება დამტკიცებას) | approved | rejected | needs_fix (ხარისხის ფილტრი) |
# skipped (არხს არ ეკუთვნის) | published/failed/removed (მომავალი ეტაპი: პოსტინგი)
POST_STATUSES = ["pending", "approved", "rejected", "needs_fix", "skipped", "published", "failed", "removed", "expired"]
SETTINGS_HEADERS = ["key", "value"]
LOG_HEADERS = ["log_id", "at", "channel_key", "kind", "text"]
TG_LEADS = "TgLeads"
# kind: view (ბოტი გაიხსნა განცხადებით) | intent (დააჭირა „მინდა დაკავშირება“) | lead (ნომერი დატოვა -> CRM-ში კლიენტი). status: new -> assigned -> closed
LEAD_HEADERS = ["lead_id", "at", "listing_key", "channel_key", "kind", "tg_user_id", "tg_name", "phone_norm", "client_id", "status", "assigned_agent_id", "assigned_by", "note"]
ALL_TABS = [(TG_CHANNELS, HEADERS, 60), (TG_POSTS, POST_HEADERS, 20000), (TG_SETTINGS, SETTINGS_HEADERS, 50), (TG_LOG, LOG_HEADERS, 5000), (TG_LEADS, LEAD_HEADERS, 20000)]

# planned = გეგმაშია; created = არხი შექმნილია, chat_id ჯერ არ ვიცით; linked = chat_id მითითებულია, ჯერ არ შემოწმებულა; live = შემოწმდა (ბოტი ადმინია, უფლებები საკმარისია);
# attention = შემოწმებამ პრობლემა აჩვენა; paused = ხელით შეჩერებულია
STATUSES = ["planned", "created", "linked", "live", "attention", "paused"]
STATUS_LABELS = {"planned": "გეგმაშია", "created": "შექმნილია", "linked": "მიბმულია", "live": "მზადაა", "attention": "საჭიროებს ყურადღებას", "paused": "შეჩერებულია"}

CHAT_ID_RE = re.compile(r"^-100\d{6,13}$")
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
REQUIRED_RIGHTS = ("can_post_messages", "can_edit_messages", "can_delete_messages")   # პოსტინგისთვის აუცილებელი უფლებები
OPTIONAL_RIGHTS = ("can_invite_users",)                                                # რეფერალის ბმულებისთვის (არა აუცილებელი)


def valid_chat_id(v) -> bool:
    return bool(CHAT_ID_RE.match(str(v or "").strip()))


def evaluate_health(chat: dict | None, member: dict | None, count: int | None, expect_username: str = "", expect_title: str = "") -> dict:
    """Telegram-ის პასუხებიდან (getChat/getChatMember/getChatMemberCount) ჯანმრთელობის დასკვნა. წმინდა ფუნქცია — ქსელი არ სჭირდება.
    აბრუნებს {status: live|attention, issues: [...], members, rights}. პრობლემები ქართულად, რომ დირექტორმა გაიგოს რა გაასწოროს."""
    issues: list[str] = []
    if not chat:
        return {"status": "attention", "issues": ["არხი ვერ მოიძებნა ან ბოტს წვდომა არ აქვს (chat_id შეამოწმეთ და ბოტი ადმინად დაამატეთ)"], "members": None, "rights": {}}
    if chat.get("type") != "channel":
        issues.append("ეს არ არის არხი (ჯგუფი/ჩატია)")
    uname = str(chat.get("username") or "")
    if not uname:
        issues.append("არხი კერძოა — საჯარო username არ აქვს (ძიებაში არ ჩანს)")
    elif expect_username and uname.lower() != expect_username.lower():
        issues.append(f"username განსხვავდება: არის @{uname}, უნდა იყოს @{expect_username}")
    if expect_title and str(chat.get("title") or "").strip() != expect_title.strip():
        issues.append(f"სათაური განსხვავდება: არის «{chat.get('title')}», უნდა იყოს «{expect_title}»")
    rights = {k: bool((member or {}).get(k)) for k in REQUIRED_RIGHTS + OPTIONAL_RIGHTS}
    if not member or member.get("status") != "administrator":
        issues.append("ბოტი არხის ადმინი არ არის")
    else:
        names = {"can_post_messages": "პოსტის გამოქვეყნება", "can_edit_messages": "პოსტის რედაქტირება", "can_delete_messages": "პოსტის წაშლა"}
        for k in REQUIRED_RIGHTS:
            if not rights[k]:
                issues.append(f"ბოტს არ აქვს უფლება: {names[k]}")
    return {"status": "attention" if issues else "live", "issues": issues, "members": count, "rights": rights}

# ====================================================================== ეტაპი 3: აგენტის თანხმობა, მარშრუტი, ხარისხის ფილტრი (წმინდა ფუნქციები)
OPT_IN_LINE = "Telegram: კი"                    # აგენტის თიქი ფორმაში -> job-ის შენიშვნის ხაზი (ახალი სვეტი/სქემა არ სჭირდება — როგორც „ინდაურები: კი“)
_OPT_RE = re.compile(r"(?im)^\s*telegram:\s*(კი|yes)\s*$")
LANGS = ("ka", "en", "ru")


def opted_in(notes) -> bool:
    """true მხოლოდ მაშინ, როცა შენიშვნაში ცალკე ხაზად წერია „Telegram: კი“ (აგენტმა თიქი მონიშნა). სხვა შემთხვევაში — არასოდეს (ნაგულისხმევად არ ვაქვეყნებთ)."""
    return bool(_OPT_RE.search(str(notes or "")))


def _num(v) -> float:
    mm = re.search(r"\d[\d\s.,]*", str(v or ""))
    if not mm:
        return 0.0
    s = mm.group(0).replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def route(listing: dict) -> dict:
    """განცხადება -> რომელ არხებში ხვდება. აბრუნებს {eligible, reason, segment, deal, city, channels:[channel_key...]}.
    არხები: საცხოვრებელი (ბინა) — თბილისი/ბათუმი; კომერციული — მთელი საქართველო. სახლი/აგარაკი/მიწა/სასტუმრო/გირავნობა არხებს არ ეკუთვნის (არხების სათაურები „ბინები“-ა)."""
    pt = str(listing.get("property_type") or "").strip()
    dt = str(listing.get("deal_type") or "").strip()
    city_raw = str(listing.get("city") or "").strip().lower()
    if pt == "ბინა":
        seg = "res"
    elif pt.startswith("კომერციული"):
        seg = "com"
    else:
        return {"eligible": False, "reason": f"ტიპი არხებს არ ეკუთვნის ({pt or 'მითითებული არ არის'}): არხებია მხოლოდ ბინებისა და კომერციულისთვის", "channels": []}
    if dt == "იყიდება":
        deal = "sale"
    elif dt in ("ქირავდება", "ქირავდება დღიურად"):
        deal = "rent"
    else:
        return {"eligible": False, "reason": f"გარიგება არხებს არ ეკუთვნის ({dt or 'მითითებული არ არის'})", "channels": []}
    if seg == "com":
        city = "ge"
    elif "თბილის" in city_raw or "tbilisi" in city_raw:
        city = "tbilisi"
    elif "ბათუმ" in city_raw or "batumi" in city_raw:
        city = "batumi"
    else:
        return {"eligible": False, "reason": f"ბინების არხები მხოლოდ თბილისსა და ბათუმზეა (განცხადება: {listing.get('city') or 'ქალაქი მითითებული არ არის'})", "channels": []}
    return {"eligible": True, "reason": "", "segment": seg, "deal": deal, "city": city, "channels": [f"{lg}-{seg}-{deal}-{city}" for lg in LANGS]}


def quality(listing: dict, min_photos: int = 3) -> list[str]:
    """ხარისხის ფილტრი: აბრუნებს „რა აკლია/რა საეჭვოა“ სიას (ცარიელი = გადის). მიზანი — უაზრო/არასრული განცხადებით არხი არ დავაბინძუროთ.
    ამ ეტაპზე არაფერი იგზავნება; ეს სია დირექტორის რიგში ჩანს."""
    out: list[str] = []
    r = route(listing)
    seg, deal = r.get("segment"), r.get("deal")
    price = _num(listing.get("price_usd"))
    if price <= 0:
        out.append("ფასი არ არის მითითებული")
    elif seg == "res" and deal == "rent" and not 50 <= price <= 10000:
        out.append(f"ქირის ფასი საეჭვოა ({int(price)}$) — დარწმუნდით, რომ თვიური/დღიური ფასია სწორი")
    elif seg == "res" and deal == "sale" and price < 5000:
        out.append(f"გასაყიდი ფასი საეჭვოდ დაბალია ({int(price)}$) — ბოლო ნული ხომ არ აკლია?")
    photos = [p for p in str(listing.get("photos") or "").split("|") if p.strip().startswith("http")]     # listings_model.PHOTO_SEP
    if len(photos) < min_photos:
        out.append(f"ფოტო ცოტაა: {len(photos)} (მინიმუმ {min_photos})")
    if not str(listing.get("district") or "").strip() and not str(listing.get("address") or "").strip():
        out.append("უბანი/მისამართი არ არის მითითებული")
    if _num(listing.get("area")) <= 0:
        out.append("ფართი არ არის მითითებული")
    if str(listing.get("active") or "yes").strip().lower() == "no":
        out.append("განცხადება აქტიური აღარ არის")
    return out
