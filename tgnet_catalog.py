"""
TGNET: კლიენტის Mini App-ის კატალოგი, ძებნა, მსგავსი განცხადებები და გამოწერები (ფილტრით ახალი ბინის შეტყობინება).

**ხილვადობა:** კლიენტს ჩანს მხოლოდ ის განცხადება, რომელზეც აგენტმა Telegram-ზე გამოქვეყნებაზე თანხმობა მისცა (თიქი), აქტიურია, არ არის დაარქივებული და არხის წესებს ემთხვევა (ბინა/კომერციული).
**საჯარო ველები:** ტიპი, გარიგება, ქალაქი, უბანი, ფასი, ფართი, ოთახები, სართული, ფოტო (SH იარლიყით), კოორდინატი (უბნის სიზუსტით — ზუსტი მისამართი/სახლის ნომერი არ გადაიცემა: კოორდინატი ~3 ათწილადამდე
მრგვალდება ≈110 მ), ID. **არასდროს:** მესაკუთრის ნომერი, შენიშვნა, აგენტი.
"""

from __future__ import annotations

import json
import re
import uuid

import config
import tgnet_content as ct
import tgnet_model as m
import tgnet_store as st

TG_SUBS, SUB_HEADERS = m.TG_SUBS, m.SUB_HEADERS
MAX_SUBS_PER_USER = 5
MAX_NOTIFY_PER_DAY = 5
FILTER_KEYS = ("deal", "city", "q", "price_min", "price_max", "rooms", "seg")


def _rows() -> list[dict]:
    import listings_store
    return listings_store.all_rows()


def visible(row: dict) -> bool:
    """თანხმობა + აქტიური + არხს ეკუთვნის (ფაქტობრივი ხილვადობა — იხ. _visible_rows: დამტკიცებულიც უნდა იყოს)."""
    return (m.opted_in(row.get("notes")) and str(row.get("active") or "yes").lower() != "no" and str(row.get("archived") or "") != "yes" and m.route(row)["eligible"])


def _visible_rows() -> list[dict]:
    """კლიენტს ჩანს მხოლოდ დირექტორის მიერ დამტკიცებული (ან უკვე გამოქვეყნებული) განცხადება — უხარისხო/დაუმტკიცებელი კატალოგში არ ხვდება."""
    ok = {p["listing_key"] for p in st.list_posts(("approved", "published"))}
    return [r for r in _rows() if str(r.get("listing_id")) in ok and visible(r)]


def _norm_filters(f: dict) -> dict:
    out = {}
    f = f or {}
    if f.get("deal") in ("sale", "rent"):
        out["deal"] = f["deal"]
    if f.get("seg") in ("res", "com"):
        out["seg"] = f["seg"]
    if f.get("city") in ("tbilisi", "batumi"):
        out["city"] = f["city"]
    q = re.sub(r"\s+", " ", str(f.get("q") or "")).strip()[:60]
    if q:
        out["q"] = q
    for k in ("price_min", "price_max"):
        v = m._num(f.get(k))
        if v > 0:
            out[k] = int(v)
    rooms = re.match(r"^\s*(\d+)", str(f.get("rooms") or ""))
    if rooms and 1 <= int(rooms.group(1)) <= 10:
        out["rooms"] = int(rooms.group(1))
    return out


def _haystack(row: dict) -> str:
    """ძიების ტექსტი სამ ენაზე: უბანი (ka/en/ru), ქალაქი, ქუჩა."""
    import listings_model as lm
    dist = str(row.get("district") or "").strip()
    tr = ct.DISTRICT.get(dist, ("", ""))
    city = str(row.get("city") or "").strip()
    city_tr = ct.CITY.get(city, {})
    street = lm.street_parts(row.get("address"))[1]
    return " ".join([dist, tr[0], tr[1], city, city_tr.get("en", ""), city_tr.get("ru", ""), street]).lower()


def matches(row: dict, f: dict) -> bool:
    r = m.route(row)
    if not r["eligible"]:
        return False
    if f.get("deal") and r["deal"] != f["deal"]:
        return False
    if f.get("seg") and r["segment"] != f["seg"]:
        return False
    if f.get("city") and r["city"] not in (f["city"], "ge"):
        return False
    price = m._num(row.get("price_usd"))
    if f.get("price_min") and price < f["price_min"]:
        return False
    if f.get("price_max") and (price <= 0 or price > f["price_max"]):
        return False
    if f.get("rooms"):
        rm = re.match(r"\s*(\d+)", str(row.get("rooms") or ""))
        if not rm or int(rm.group(1)) < f["rooms"]:
            return False
    if f.get("q"):
        hs = _haystack(row)
        if not all(tok in hs for tok in f["q"].lower().split()):
            return False
    return True


def card(row: dict, lang: str) -> dict:
    """საჯარო ბარათი (მესაკუთრის/შიდა მონაცემის გარეშე)."""
    import tgnet_img
    r = ct.render(row, lang, cta=False)
    lines = re.sub(r"<[^>]+>", "", r["text"]).split("\n")
    photos = ct.photos_of(row, 1)
    lat, lng = m._num(row.get("lat")), m._num(row.get("lng"))
    return {"id": str(row.get("listing_id")), "title": lines[0].replace("🏠", "").strip() if lines else "", "price": (lines[1].replace("💰", "").strip() if len(lines) > 1 and lines[1].startswith("💰") else ""),
            "facts": next((x for x in lines[1:] if x.startswith("📐") or x.startswith("🚪")), ""), "photo": tgnet_img.proxy_url(photos[0]) if photos else "",
            "lat": round(lat, 3) if lat else None, "lng": round(lng, 3) if lng else None, "price_num": int(m._num(row.get("price_usd")))}


def search(f: dict, lang: str = "ka", page: int = 1, limit: int = 24, sort: str = "new") -> dict:
    f = _norm_filters(f)
    rows = [r for r in _visible_rows() if matches(r, f)]
    if sort == "price_asc":
        rows.sort(key=lambda r: m._num(r.get("price_usd")) or 1e12)
    elif sort == "price_desc":
        rows.sort(key=lambda r: -m._num(r.get("price_usd")))
    else:
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    limit = max(1, min(int(limit or 24), 60))
    page = max(1, int(page or 1))
    chunk = rows[(page - 1) * limit: page * limit]
    return {"items": [card(r, lang) for r in chunk], "total": len(rows), "page": page, "limit": limit, "filters": f}


def map_points(f: dict, lang: str = "ka", cap: int = 1500) -> dict:
    f = _norm_filters(f)
    pts = []
    for r in _visible_rows():
        if not matches(r, f):
            continue
        lat, lng = m._num(r.get("lat")), m._num(r.get("lng"))
        if not (38 < lat < 46 and 38 < lng < 51):
            continue
        pts.append({"id": str(r.get("listing_id")), "lat": round(lat, 3), "lng": round(lng, 3), "price": int(m._num(r.get("price_usd"))), "rooms": str(r.get("rooms") or "")})
    return {"points": pts[:cap], "total": len(pts), "truncated": len(pts) > cap}


def similar(listing_id: str, lang: str = "ka", n: int = 6) -> list[dict]:
    """მსგავსი: იგივე გარიგება/ქალაქი, ფასი ±30%, ოთახები ±1; უახლოესი ფასით."""
    rows = _visible_rows()
    base = next((r for r in _rows() if str(r.get("listing_id")) == str(listing_id)), None)
    if not base:
        return []
    rb = m.route(base)
    pb = m._num(base.get("price_usd"))
    rmb = re.match(r"\s*(\d+)", str(base.get("rooms") or ""))
    out = []
    for r in rows:
        if str(r.get("listing_id")) == str(listing_id):
            continue
        rr = m.route(r)
        if rr["deal"] != rb.get("deal") or rr["city"] != rb.get("city") or rr["segment"] != rb.get("segment"):
            continue
        p = m._num(r.get("price_usd"))
        if pb and p and not (0.7 * pb <= p <= 1.3 * pb):
            continue
        rm = re.match(r"\s*(\d+)", str(r.get("rooms") or ""))
        if rmb and rm and abs(int(rm.group(1)) - int(rmb.group(1))) > 1:
            continue
        out.append((abs(p - pb) if pb and p else 1e9, r))
    out.sort(key=lambda x: x[0])
    return [card(r, lang) for _, r in out[:n]]


# ====================================================================== გამოწერები
def _subs(fresh: bool = False) -> list[dict]:
    return [{k: str(r.get(k) or "") for k in SUB_HEADERS} for r in st._backend.read(TG_SUBS, fresh=fresh)]


def list_subs(tg_user_id) -> list[dict]:
    out = []
    for s in _subs(fresh=True):
        if s["tg_user_id"] == str(tg_user_id) and s["active"] == "yes":
            out.append({"sub_id": s["sub_id"], "filters": json.loads(s["filter_json"] or "{}"), "lang": s["lang"], "created_at": s["created_at"]})
    return out


def add_sub(tg_user_id, tg_name: str, lang: str, filters: dict) -> dict:
    f = _norm_filters(filters)
    if not f:
        raise st.TgnetError("აირჩიეთ მინიმუმ ერთი ფილტრი", 400, "empty_filter")
    mine = list_subs(tg_user_id)
    if any(x["filters"] == f for x in mine):
        raise st.TgnetError("ასეთი გამოწერა უკვე გაქვთ", 409, "duplicate")
    if len(mine) >= MAX_SUBS_PER_USER:
        raise st.TgnetError(f"მაქსიმუმ {MAX_SUBS_PER_USER} გამოწერა", 400, "too_many")
    rec = {"sub_id": uuid.uuid4().hex[:10], "tg_user_id": str(tg_user_id), "tg_name": str(tg_name or "")[:60], "lang": lang if lang in ("ka", "en", "ru") else "ka", "filter_json": json.dumps(f, ensure_ascii=False),
           "created_at": st.now_str(), "active": "yes", "last_sent_at": "", "sent_count": "0", "sent_ids": "", "fail_count": "0"}
    st._backend.ensure()
    st._backend.append(TG_SUBS, SUB_HEADERS, rec)
    return {"sub_id": rec["sub_id"], "filters": f}


def remove_sub(tg_user_id, sub_id: str) -> bool:
    s = next((x for x in _subs(fresh=True) if x["sub_id"] == sub_id and x["tg_user_id"] == str(tg_user_id) and x["active"] == "yes"), None)
    if not s:
        return False
    st._backend.update(TG_SUBS, SUB_HEADERS, sub_id, {"active": "no"})
    return True


def notify_new_listing(listing_row: dict, send) -> dict:
    """ახალი (დამტკიცებული) განცხადება -> შესაბამისი გამოწერები. send(chat_id, text, markup) -> True/False. დაცვა: ერთ ბინას ერთი მომხმარებელი ერთხელ იღებს; ≤5 შეტყობინება დღეში;
    3 წარუმატებელი გაგზავნა (ბოტი დაბლოკილია/არ გაუხსნია) -> გამოწერა ითიშება."""
    out = {"sent": 0, "skipped": 0, "disabled": 0}
    if not visible(listing_row):
        return out
    lid = str(listing_row.get("listing_id"))
    today = st.now_str()[:10]
    per_user_today: dict = {}
    for s in _subs(fresh=True):
        if s["active"] != "yes":
            continue
        if lid in s["sent_ids"].split(","):
            out["skipped"] += 1
            continue
        if not matches(listing_row, json.loads(s["filter_json"] or "{}")):
            continue
        if s["last_sent_at"][:10] == today and per_user_today.get(s["tg_user_id"], 0) >= MAX_NOTIFY_PER_DAY:
            out["skipped"] += 1
            continue
        sent_today = sum(1 for x in _subs(fresh=False) if x["tg_user_id"] == s["tg_user_id"] and x["last_sent_at"][:10] == today and int(x["sent_count"] or 0) > 0)
        if sent_today >= MAX_NOTIFY_PER_DAY:
            out["skipped"] += 1
            continue
        lang = s["lang"]
        c = card(listing_row, lang)
        text = {"ka": "🔔 ახალი ბინა თქვენი ფილტრით", "en": "🔔 New listing for your filter", "ru": "🔔 Новый объект по вашему фильтру"}[lang] + f"\n\n🏠 {c['title']}\n💰 {c['price']}\n{c['facts']}"
        markup = {"inline_keyboard": [[{"text": ct.L[lang]["cta"], "url": ct.link_for(lid, lang)}]]}
        ok = False
        try:
            ok = bool(send(int(s["tg_user_id"]), text, markup))
        except Exception:  # noqa: BLE001
            ok = False
        ids = ",".join((s["sent_ids"].split(",") + [lid])[-200:]).strip(",")
        if ok:
            st._backend.update(TG_SUBS, SUB_HEADERS, s["sub_id"], {"last_sent_at": st.now_str(), "sent_count": str(int(s["sent_count"] or 0) + 1), "sent_ids": ids, "fail_count": "0"})
            per_user_today[s["tg_user_id"]] = per_user_today.get(s["tg_user_id"], 0) + 1
            out["sent"] += 1
        else:
            fails = int(s["fail_count"] or 0) + 1
            st._backend.update(TG_SUBS, SUB_HEADERS, s["sub_id"], {"fail_count": str(fails), **({"active": "no"} if fails >= 3 else {})})
            out["disabled"] += 1 if fails >= 3 else 0
    return out
