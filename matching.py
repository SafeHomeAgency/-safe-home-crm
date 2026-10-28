"""
კლიენტის კრიტერიუმები ↔ განცხადებები: ავტომატური შესატყვისობა **ახსნით** (რატომ ერგება / რომელი კრიტერიუმია შეუსაბამო).

წმინდა ლოგიკაა (Flask/Sheets-ის გარეშე). ნეიტრალური, არადისკრიმინაციული პირობები: გარიგება, ბიუჯეტი, რაიონი, ტიპი, ფართი, ოთახები/საძინებლები,
სართული, შინაური ცხოველი (მესაკუთრის პირობა), მინ. ქირავნობის პერიოდი (ცნობილია თუ არა), სასურველი თარიღი.

შედეგი: {"score": 0..100, "hard_fail": bool, "matched": [..], "mismatched": [..], "unknown": [..]}
  * hard_fail — გარიგება/ბიუჯეტი (10%-ზე მეტი გადაჭარბება)/ტიპი/ოთახების მინიმუმი/ცხოველი („არა“) — ასეთი ბინა არ ეთავაზება;
  * ბიუჯეტი 0-10%-ით მეტი — „ახლოსაა“ (ქულა მცირდება, მაგრამ არ გამოირიცხება);
  * განცხადებაში მონაცემი არ არის (ფართი/სართული/ცხოველი...) — „უცნობია“ (ქულას არ აკლდება, მაგრამ ჩანს, რომ გადასამოწმებელია).
"""

from __future__ import annotations

import re

NEAR_BUDGET = 1.10
MIN_NOTIFY_SCORE = 60

W = {"deal": 0, "budget": 30, "district": 20, "ptype": 10, "area": 10, "rooms": 15, "bedrooms": 5, "floor": 5, "pets": 5}   # ჯამი 100 (deal — მხოლოდ ფილტრი)


def _num(v):
    try:
        s = str(v if v is not None else "").strip().replace(",", ".")
        return float(s) if s not in ("", "None", "null") else None
    except (TypeError, ValueError):
        return None


def _int_prefix(v):
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def _stem(s: str) -> str:
    s = str(s or "").strip().lower()
    return s[: max(4, len(s) - 2)]


def district_hit(listing: dict, wanted) -> bool:
    hay = f"{str(listing.get('district') or '').lower()} {str(listing.get('address') or '').lower()}"
    dist = str(listing.get("district") or "").strip().lower()
    for n in wanted or []:
        nm = str(n).strip().lower()
        if nm and (_stem(nm) in hay or (len(dist) >= 4 and _stem(dist) in nm)):
            return True
    return False


def match(crit: dict, listing: dict) -> dict:
    matched, mism, unknown = [], [], []
    score, max_score, hard = 0.0, 0.0, False

    def add(key, ok, text_ok, text_bad, partial=None):
        nonlocal score, max_score
        if ok is not None:                      # უცნობი მონაცემი ქულას არ აკლებს (მხოლოდ „გადასამოწმებელად“ ჩანს)
            max_score += W[key]
        if ok is True:
            score += W[key]
            matched.append(text_ok)
        elif ok == "near":
            score += W[key] * (partial if partial is not None else 0.4)
            mism.append(text_bad)
        elif ok is False:
            mism.append(text_bad)
        else:
            unknown.append(text_ok)

    # --- გარიგება (მკაცრი ფილტრი)
    cd, ld = str(crit.get("deal_type") or "").strip().lower(), str(listing.get("deal_type") or "").strip().lower()
    if cd and ld and cd != ld:
        return {"score": 0, "hard_fail": True, "matched": [], "mismatched": [f"❌ გარიგება: {listing.get('deal_type')} (მოთხოვნილია {crit.get('deal_type')})"], "unknown": []}
    if cd and ld:
        matched.append(f"✅ გარიგება: {listing.get('deal_type')}")

    # --- ბიუჯეტი
    price, bmax, bmin = _num(listing.get("price_usd")), _num(crit.get("budget_max")), _num(crit.get("budget_min"))
    if bmax is not None or bmin is not None:
        if price is None:
            add("budget", None, "❔ ფასი განცხადებაში არ ჩანს", "")
        elif bmax is not None and price > bmax * NEAR_BUDGET:
            hard = True
            add("budget", False, "", f"❌ ბიუჯეტი: ${price:g} > ${bmax:g} (10%-ზე მეტით ძვირია)")
        elif bmax is not None and price > bmax:
            add("budget", "near", "", f"⚠️ ბიუჯეტი: ${price:g} — ბიუჯეტზე ${price - bmax:g}-ით მეტია (${bmax:g})", 0.4)
        elif bmin is not None and price < bmin:
            add("budget", "near", "", f"⚠️ ბიუჯეტი: ${price:g} — მინიმუმზე დაბალია (${bmin:g}); შესაძლოა სხვა კლასია", 0.6)
        else:
            add("budget", True, f"✅ ბიუჯეტი: ${price:g}" + (f" ≤ ${bmax:g}" if bmax is not None else ""), "")

    # --- რაიონი
    wanted = [d for d in (crit.get("districts") or []) if str(d).strip()]
    if wanted:
        add("district", district_hit(listing, wanted), f"✅ რაიონი: {listing.get('district') or listing.get('address')}",
            f"❌ რაიონი: {listing.get('district') or '—'} (არ არის არჩეულებში)")

    # --- ტიპი
    pt, lpt = str(crit.get("property_type") or "").strip().lower(), str(listing.get("property_type") or "").strip().lower()
    if pt:
        if not lpt:
            add("ptype", None, "❔ ტიპი განცხადებაში არ ჩანს", "")
        elif pt == lpt:
            add("ptype", True, f"✅ ტიპი: {listing.get('property_type')}", "")
        else:
            hard = True
            add("ptype", False, "", f"❌ ტიპი: {listing.get('property_type')} (მოთხოვნილია {crit.get('property_type')})")

    # --- ფართი
    area, amin, amax = _num(listing.get("area")), _num(crit.get("area_min")), _num(crit.get("area_max"))
    if amin is not None or amax is not None:
        if area is None:
            add("area", None, "❔ ფართი განცხადებაში არ ჩანს", "")
        elif (amin is not None and area < amin) or (amax is not None and area > amax):
            near = (amin is None or area >= amin * 0.9) and (amax is None or area <= amax * 1.1)
            want = (f"{amin:g}–{amax:g}" if amin is not None and amax is not None else f"მინიმუმი {amin:g}" if amin is not None else f"მაქსიმუმი {amax:g}")
            add("area", "near" if near else False, "", f"{'⚠️' if near else '❌'} ფართი: {area:g} მ² (მოთხოვნა: {want})", 0.5)
        else:
            add("area", True, f"✅ ფართი: {area:g} მ²", "")

    # --- ოთახები / საძინებლები
    rmin, rmax = _int_prefix(crit.get("rooms_min")), _int_prefix(crit.get("rooms_max"))
    rooms = _int_prefix(listing.get("rooms"))
    if rmin is not None or rmax is not None:
        if rooms is None:
            add("rooms", None, "❔ ოთახობა განცხადებაში არ ჩანს", "")
        elif rmin is not None and rooms < rmin:
            hard = True
            add("rooms", False, "", f"❌ ოთახები: {rooms} (მინიმუმი {rmin})")
        elif rmax is not None and rooms > rmax:
            add("rooms", "near", "", f"⚠️ ოთახები: {rooms} (მაქსიმუმი {rmax})", 0.5)
        else:
            add("rooms", True, f"✅ ოთახები: {rooms}", "")
    bmin_r, bed = _int_prefix(crit.get("bedrooms_min")), _int_prefix(listing.get("bedrooms"))
    if bmin_r is not None:
        add("bedrooms", None if bed is None else (bed >= bmin_r), f"✅ საძინებლები: {bed}" if bed is not None else "❔ საძინებლები განცხადებაში არ ჩანს",
            f"❌ საძინებლები: {bed} (მინიმუმი {bmin_r})")

    # --- სართული
    fl, fls = _int_prefix(listing.get("floor")), _int_prefix(listing.get("floors"))
    fmin = _int_prefix(crit.get("floor_min"))
    if str(crit.get("not_first") or "").lower() in ("1", "yes", "true") or fmin is not None:
        need = max(fmin or 1, 2) if str(crit.get("not_first") or "").lower() in ("1", "yes", "true") else fmin
        add("floor", None if fl is None else fl >= need, f"✅ სართული: {fl}" if fl is not None else "❔ სართული განცხადებაში არ ჩანს",
            f"❌ სართული: {fl} (სასურველია {need}+)")
    if str(crit.get("not_last") or "").lower() in ("1", "yes", "true") and fl is not None and fls is not None and fl >= fls:
        mism.append(f"⚠️ ბოლო სართულია ({fl}/{fls})")
        score -= 2

    # --- შინაური ცხოველი (მესაკუთრის პირობა; კლიენტს ჰყავს)
    if str(crit.get("pets_needed") or "").lower() in ("1", "yes", "true"):
        lp = str(listing.get("pets") or "").strip().lower()
        if lp == "no":
            hard = True
            add("pets", False, "", "❌ მესაკუთრე ცხოველებს არ უშვებს")
        elif lp in ("yes", "ask"):
            add("pets", True, "✅ ცხოველები: " + ("დასაშვებია" if lp == "yes" else "შეთანხმებით"), "")
        else:
            add("pets", None, "❔ ცხოველების პირობა მითითებული არ არის — გადაამოწმეთ მესაკუთრესთან", "")

    # კრიტერიუმი არ მიუთითებიათ -> max_score=0 -> 100 (ყველაფერი ერგება, გარიგების გარდა); უცნობი მონაცემი ქულაში არ მონაწილეობს
    pct = 100 if max_score == 0 else max(0, min(100, round(100 * score / max_score)))
    return {"score": pct, "hard_fail": hard, "matched": matched, "mismatched": mism, "unknown": unknown}


def rank(crit: dict, listings: list[dict], limit: int = 20, min_score: int = 0) -> list[dict]:
    """[{listing, match}] — მკაცრად შეუსაბამოები გამოირიცხება; დალაგება: ქულა კლებადობით, შემდეგ ფასი."""
    out = []
    for L in listings:
        res = match(crit, L)
        if res["hard_fail"] or res["score"] < min_score:
            continue
        out.append({"listing": L, "match": res})
    out.sort(key=lambda x: (-x["match"]["score"], _num(x["listing"].get("price_usd")) or 0))
    return out[:limit]
