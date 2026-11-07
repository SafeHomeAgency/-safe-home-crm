"""
TGNET ეტაპი 4: პოსტის ტექსტის აგება (წმინდა ფუნქციები, ქსელი/ცხრილი არ სჭირდება).

**ფაქტების გამოგონება არ ხდება:** ტექსტი მხოლოდ განცხადების ველებიდან იწყობა ფიქსირებული შაბლონით (ქართული/English/Русский). AI ამ ეტაპზე არ გამოიყენება.
ველი, რომელიც არ არის (ან რომლის თარგმანიც არ ვიცით), უბრალოდ გამოტოვებულია. **არასდროს ჩანს:** მესაკუთრის ნომერი, შიდა შენიშვნა, აგენტის სახელი, ზუსტი მისამართი/სახლის ნომერი.
ვალიდატორი ამოწმებს ლიმიტს (წარწერა ≤1024), ტელეფონის ნომრის ფორმას, დაუდასტურებელ დაპირებებს, შიდა სიტყვებს.
"""

from __future__ import annotations

import hashlib
import html
import re

import tgnet_model as m

BOT = "SafeHomeGeBot"
BRAND = "Safe Home Agency"
CAPTION_MAX = 1024

TYPE = {"ბინა": {"ka": "ბინა", "en": "Apartment", "ru": "Квартира"},
        "კომერციული ფართი": {"ka": "კომერციული ფართი", "en": "Commercial space", "ru": "Коммерческое помещение"}}
DEAL = {"იყიდება": {"ka": "იყიდება", "en": "for sale", "ru": "продаётся"},
        "ქირავდება": {"ka": "ქირავდება", "en": "for rent", "ru": "сдаётся"},
        "ქირავდება დღიურად": {"ka": "ქირავდება დღიურად", "en": "daily rent", "ru": "посуточно"}}
CITY = {"თბილისი": {"ka": "თბილისი", "en": "Tbilisi", "ru": "Тбилиси"}, "ბათუმი": {"ka": "ბათუმი", "en": "Batumi", "ru": "Батуми"},
        "ქუთაისი": {"ka": "ქუთაისი", "en": "Kutaisi", "ru": "Кутаиси"}, "რუსთავი": {"ka": "რუსთავი", "en": "Rustavi", "ru": "Рустави"},
        "გორი": {"ka": "გორი", "en": "Gori", "ru": "Гори"}, "ფოთი": {"ka": "ფოთი", "en": "Poti", "ru": "Поти"}}
DISTRICT = {"ვაკე": ("Vake", "Ваке"), "საბურთალო": ("Saburtalo", "Сабуртало"), "ვერა": ("Vera", "Вера"), "დიდუბე": ("Didube", "Дидубе"), "ისანი": ("Isani", "Исани"),
            "ნაძალადევი": ("Nadzaladevi", "Надзаладеви"), "გლდანი": ("Gldani", "Глдани"), "ჩუღურეთი": ("Chughureti", "Чугурети"), "კრწანისი": ("Krtsanisi", "Крцаниси"),
            "მთაწმინდა": ("Mtatsminda", "Мтацминда"), "სამგორი": ("Samgori", "Самгори"), "დიღომი": ("Dighomi", "Дигоми"), "ძველი თბილისი": ("Old Tbilisi", "Старый Тбилиси"),
            "ძველი ბათუმი": ("Old Batumi", "Старый Батуми"), "ახალი ბულვარი": ("New Boulevard", "Новый бульвар")}
L = {  # ფიქსირებული ტექსტები
    "ka": {"month": "თვეში", "day": "დღეში", "m2": "მ²", "rooms": "ოთახი", "rooms1": "ოთახი", "bed": "საძინებელი", "bed1": "საძინებელი", "floor": "სართული", "cta": "დეტალები და დათვალიერება", "id": "ID"},
    "en": {"month": "month", "day": "day", "m2": "m²", "rooms": "rooms", "rooms1": "room", "bed": "bedrooms", "bed1": "bedroom", "floor": "floor", "cta": "Details & viewing", "id": "ID"},
    "ru": {"month": "в месяц", "day": "в сутки", "m2": "м²", "rooms": "комн.", "rooms1": "комн.", "bed": "спальни", "bed1": "спальня", "floor": "этаж", "cta": "Детали и просмотр", "id": "ID"},
}
TAGS = {"ka": {"tbilisi": "#თბილისი", "batumi": "#ბათუმი", "ge": "#საქართველო", "sale": "#იყიდება", "rent": "#ქირავდება", "res": "#ბინა", "com": "#კომერციული"},
        "en": {"tbilisi": "#Tbilisi", "batumi": "#Batumi", "ge": "#Georgia", "sale": "#ForSale", "rent": "#ForRent", "res": "#Apartments", "com": "#CommercialProperty"},
        "ru": {"tbilisi": "#Тбилиси", "batumi": "#Батуми", "ge": "#Грузия", "sale": "#НаПродажу", "rent": "#Аренда", "res": "#Квартиры", "com": "#КоммерческаяНедвижимость"}}


def _t(table: dict, key: str, lang: str) -> str:
    v = table.get(key)
    return v[lang] if isinstance(v, dict) and lang in v else ""


def _district(name: str, lang: str) -> str:
    name = str(name or "").strip()
    if not name:
        return ""
    if lang == "ka":
        return name
    tr = DISTRICT.get(name)
    return tr[0 if lang == "en" else 1] if tr else ""      # თარგმანი არ ვიცით -> გამოტოვებულია (არ ვხვდებით)


def _int(v):
    mm = re.match(r"\s*(\d+)", str(v or ""))
    return int(mm.group(1)) if mm else 0


def money(price: float, daily: bool, rent: bool, lang: str) -> str:
    s = f"${int(round(price)):,}"
    if rent:
        s += (" / " if lang == "en" else " ") + L[lang]["day" if daily else "month"]
    return s


def photos_of(listing: dict, limit: int = 10) -> list[str]:
    return [p.strip() for p in str(listing.get("photos") or "").split("|") if p.strip().startswith("http")][:limit]


def start_payload(lid: str, lang: str) -> str:
    return f"{lid}_{lang}"[:64]


def link_for(lid: str, lang: str) -> str:
    """ბმული განცხადებაზე: Mini App (თუ TGNET_MINIAPP_SHORTNAME დაყენებულია BotFather-ში) ან ბოტის /start."""
    import config
    sn = getattr(config, "TGNET_MINIAPP_SHORTNAME", "")
    return f"https://t.me/{BOT}/{sn}?startapp={start_payload(lid, lang)}" if sn else f"https://t.me/{BOT}?start={start_payload(lid, lang)}"


CATALOG_LABEL = {"ka": "🗺 კატალოგი და რუკა", "en": "🗺 Catalog & map", "ru": "🗺 Каталог и карта"}


def catalog_link(lang: str) -> str:
    """Mini App-ის კატალოგი/რუკა (მხოლოდ თუ TGNET_MINIAPP_SHORTNAME დაყენებულია BotFather-ში; სხვაგვარად — ცარიელი)."""
    import config
    sn = getattr(config, "TGNET_MINIAPP_SHORTNAME", "")
    return f"https://t.me/{BOT}/{sn}?startapp=catalog_{lang}" if sn else ""


def render(listing: dict, lang: str, channel_key: str = "", cta: bool = True) -> dict:
    """აბრუნებს {text, photos, hash, lang}. text — HTML (Telegram parse_mode=HTML), უკვე გაექსკეიპებული."""
    if lang not in L:
        raise ValueError("ენა უცნობია")
    r = m.route(listing)
    seg, deal, city = r.get("segment", "res"), r.get("deal", "sale"), r.get("city", "ge")
    ty = _t(TYPE, str(listing.get("property_type") or "").strip(), lang) or _t(TYPE, "ბინა", lang)
    dt_raw = str(listing.get("deal_type") or "").strip()
    dl = _t(DEAL, dt_raw, lang)
    city_raw = str(listing.get("city") or "").strip()
    city_t = _t(CITY, city_raw, lang) or (city_raw if lang == "ka" else "")
    dist = _district(listing.get("district"), lang)
    loc = ", ".join(x for x in (city_t, dist) if x)
    price = m._num(listing.get("price_usd"))
    rent = deal == "rent"
    daily = dt_raw == "ქირავდება დღიურად"
    head = f"🏠 <b>{html.escape((ty + ' ' + dl).strip())}</b>" + (f" · {html.escape(loc)}" if loc else "")
    lines = [head]
    if price > 0:
        lines.append(f"💰 <b>{html.escape(money(price, daily, rent, lang))}</b>")
    facts = []
    area = m._num(listing.get("area"))
    if area > 0:
        facts.append(f"📐 {area:g} {L[lang]['m2']}")
    rooms, beds = _int(listing.get("rooms")), _int(listing.get("bedrooms"))
    if rooms:
        facts.append(f"🚪 {rooms} {L[lang]['rooms1' if rooms == 1 else 'rooms']}")
    if beds:
        facts.append(f"🛏 {beds} {L[lang]['bed1' if beds == 1 else 'bed']}")
    fl, fls = _int(listing.get("floor")), _int(listing.get("floors"))
    if fl:
        facts.append(f"🏢 {L[lang]['floor']} {fl}" + (f"/{fls}" if fls else ""))
    if facts:
        lines.append(" · ".join(facts))
    lid = str(listing.get("listing_id") or "").strip()
    if cta:
        lines.append(f'📩 <a href="{html.escape(link_for(lid, lang))}">{L[lang]["cta"]}</a>' if lid else f"📩 @{BOT}")
    tg = TAGS[lang]
    lines.append(" ".join([tg.get(city, ""), tg[deal], tg[seg]]).strip())
    lines.append(f"{BRAND}" + (f" · {L[lang]['id']}: {html.escape(lid)}" if lid else ""))
    text = "\n".join(x for x in lines if x)
    return {"text": text, "photos": photos_of(listing), "hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12], "lang": lang, "channel_key": channel_key}


_PHONE = re.compile(r"(?<!\d)(?:\+?995[\s-]?)?5\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2}(?!\d)|(?<!\d)\d{9,}(?!\d)")
_PROMISE = re.compile(r"გარანტი|guarantee|гаранти|#1\b|best price|лучш\w* цен|საუკეთესო ფას", re.I)


def validate(rendered: dict, listing: dict | None = None) -> list[str]:
    """პრობლემების სია (ცარიელი = გადის). ამოწმებს ლიმიტს, ტელეფონს, დაპირებებს, შიდა მონაცემის გაჟონვას."""
    t = rendered.get("text") or ""
    plain = re.sub(r"<[^>]+>", "", t)
    out = []
    if len(plain) > CAPTION_MAX or len(t) > 4000:
        out.append(f"წარწერა ძალიან გრძელია ({len(plain)}>{CAPTION_MAX})")
    if "$" not in plain:
        out.append("ფასი არ ჩანს ტექსტში")
    if _PHONE.search(re.sub(r"(ID|L)\s*:?\s*[A-Za-z]?\d+", "", re.sub(r"https?://\S+", "", plain))):
        out.append("ტექსტში ტელეფონის ნომერს მივაგენი")
    if _PROMISE.search(plain):
        out.append("ტექსტში დაუდასტურებელი დაპირებაა")
    if re.search(r"crm|სისტემა", plain, re.I):
        out.append("ტექსტში შიდა სიტყვაა")
    if listing:
        for k in ("owner_number", "notes", "agent_name"):
            parts = [str(listing.get(k) or "").strip()] if k != "notes" else [x.strip() for x in str(listing.get(k) or "").splitlines()]
            for v in parts:
                if len(v) >= 4 and not re.match(r"(?i)(telegram|ცხოველები|ინდაურები)\s*:", v) and v.lower() in plain.lower():
                    out.append(f"ტექსტში გაჟონა შიდა ველი: {k}")
                    break
    return out
