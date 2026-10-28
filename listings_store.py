"""
Safe Home Property Hub — განცხადებების შენახვა (Google Sheets, ახალი ცხრილი `Listings`) და ძიება/ფილტრაცია.

სტრუქტურა contracts_store/finance_store-ს იმეორებს: ცხრილი ზარმაცად იქმნება (არსებულებს არ ეხება), ჩაწერა ერთ პროცესულ ბლოკირებაში
და ახლად წაკითხული მონაცემებით, წაშლა არ არსებობს (მხოლოდ `archived`). ბექენდი ტესტში იცვლება `MemoryBackend`-ით.
არსებულ MyHomeJobs/KPI/დუბლიკატების ლოგიკას ეს მოდული არ ცვლის — მხოლოდ კითხულობს job-ებს backfill-ისთვის.
"""

from __future__ import annotations

import datetime
import logging
import re
import threading

import contracts_store as _cs
import listings_model as m
from listings_model import ListingError

log = logging.getLogger("safehome-listings")
_lock = threading.RLock()


class SheetsBackend(_cs.SheetsBackend):
    def ensure(self) -> None:
        if self._ready:
            return
        sg = self._sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in m.ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        self._ready = True


class MemoryBackend(_cs.MemoryBackend):
    def ensure(self) -> None:
        for name, _h, _r in m.ALL_TABS:
            self.tables.setdefault(name, [])


_backend = SheetsBackend()


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def _s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


def _digits(v, cap: int = 20) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())[:cap]


def now_dt() -> datetime.datetime:
    import crm_time
    return crm_time.local_now().replace(tzinfo=None)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")


# ====================================================================== ჩაწერა
def _clean_snapshot(snap: dict | None) -> dict:
    snap = snap if isinstance(snap, dict) else {}
    photos = [str(p).strip() for p in (snap.get("photos") or []) if str(p).strip().lower().startswith(("http://", "https://"))]
    photos = [p for p in photos if m.PHOTO_SEP not in p and len(p) < 400][:m.MAX_PHOTOS]

    def coord(v, lo, hi):
        f = m.num(v)
        return str(round(f, 6)) if f is not None and lo <= f <= hi else ""

    return {
        "myhome_id": _digits(snap.get("myhome_id")), "ssge_id": _digits(snap.get("ssge_id")),
        "deal_type": _s(snap.get("deal_type"), 40), "property_type": _s(snap.get("property_type"), 40),
        "title": _s(snap.get("title"), 160), "city": _s(snap.get("city"), 60), "district": _s(snap.get("district"), 80),
        "address": _s(snap.get("address"), 160),
        "price_usd": _s(snap.get("price_usd"), 20), "area": _s(snap.get("area"), 12), "rooms": _s(snap.get("rooms"), 6),
        "bedrooms": _s(snap.get("bedrooms"), 6), "floor": _s(snap.get("floor"), 6), "floors": _s(snap.get("floors"), 6),
        "condition": _s(snap.get("condition"), 60), "status_text": _s(snap.get("status_text"), 60),
        "lat": coord(snap.get("lat"), 38.0, 46.0), "lng": coord(snap.get("lng"), 38.0, 51.0),
        "photos": m.PHOTO_SEP.join(photos),
    }


def upsert_from_job(job: dict, snap: dict | None) -> dict | None:
    """job-ის დასრულებისას ექსთენშენის სნეპშოტიდან ჩანაწერის შექმნა/განახლება (ერთი ჩანაწერი job-ზე). თუ ID არცერთი პორტალის არ არის — არაფერს ვწერთ."""
    s = _clean_snapshot(snap)
    s["ssge_id"] = s["ssge_id"] or _digits(job.get("ssge_listing_id"))
    if not (s["myhome_id"] or s["ssge_id"]):
        return None
    job_id = _s(job.get("job_id"), 60)
    with _lock:
        rows = _backend.read(m.LISTINGS_SHEET, fresh=True)
        ex = next((r for r in rows if _s(r.get("job_id")) == job_id and job_id), None)
        now = now_str()
        base = {
            "job_id": job_id, "agent_id": _s(job.get("agent_id"), 40), "agent_name": _s(job.get("agent_name"), 80), "team": _s(job.get("team"), 40),
            "source": "upload", "src_site": _s(job.get("listing_source") or "myhome", 10), "src_id": _s(job.get("myhome_listing_id"), 20),
            "owner_number": _s(job.get("owner_number"), 30), "notes": _s(job.get("notes"), 500), "active": "yes", "archived": "",
            "pets": m.pets_from_notes(job.get("notes")),
        }
        rec = dict(base, **s)
        rec["deal_type"] = rec["deal_type"] or _s(job.get("deal_type"), 40)
        rec["city"] = rec["city"] or _s(job.get("city"), 60)
        rec["district"] = rec["district"] or _s(job.get("district"), 80)
        rec["address"] = rec["address"] or _s(job.get("address"), 160)
        rec["price_usd"] = rec["price_usd"] or _s(job.get("final_price"), 20)
        rec["last_updated_at"] = now
        if ex:
            # ხელახალი გაშვება: ისტორია (created_at) რჩება; ახალი მონაცემები ივსება, ცარიელი სნეპშოტი ძველს არ ანადგურებს
            changes = {k: v for k, v in rec.items() if str(v) != "" or k in ("last_updated_at",)}
            changes["last_verified_at"] = now
            _backend.update(m.LISTINGS_SHEET, m.LISTING_HEADERS, _s(ex.get("listing_id")), changes)
            return dict(ex, **changes)
        rec["listing_id"] = ("L" + rec["myhome_id"]) if rec["myhome_id"] else ("S" + rec["ssge_id"])
        if any(_s(r.get("listing_id")) == rec["listing_id"] for r in rows):
            rec["listing_id"] += "-" + (job_id[:4] or "x")
        rec["created_at"] = now
        rec["last_verified_at"] = now
        _backend.append(m.LISTINGS_SHEET, m.LISTING_HEADERS, rec)
        return dict(rec, _new=True)           # ახალი ჩანაწერის ნიშანი (მხოლოდ დაბრუნებულ ასლზე; ცხრილში არ იწერება) — კლიენტის კრიტერიუმებთან შესადარებლად


def backfill_from_jobs(jobs: list[dict]) -> dict:
    """ერთჯერადი (იდემპოტენტური): COMPLETED job-ებიდან ჩანაწერები, რომლებიც ჯერ არ არის ცხრილში. ფოტო/კოორდინატი/ახალი MyHome ID არ არის."""
    with _lock:
        rows = _backend.read(m.LISTINGS_SHEET, fresh=True)
        have = {_s(r.get("job_id")) for r in rows}
        taken = {_s(r.get("listing_id")) for r in rows}
        added = skipped = 0
        for j in jobs:
            jid = _s(j.get("job_id"), 60)
            if _s(j.get("status")).upper() != "COMPLETED" or not jid or jid in have:
                skipped += 1
                continue
            lid = "J" + jid[:8]
            while lid in taken:
                lid += "x"
            taken.add(lid)
            done = _s(j.get("completed_at")) or _s(j.get("created_at"))
            rec = {
                "listing_id": lid, "job_id": jid, "agent_id": _s(j.get("agent_id"), 40), "agent_name": _s(j.get("agent_name"), 80),
                "team": _s(j.get("team"), 40), "source": "backfill", "myhome_id": "", "ssge_id": _digits(j.get("ssge_listing_id")),
                "src_site": _s(j.get("listing_source") or "myhome", 10), "src_id": _s(j.get("myhome_listing_id"), 20),
                "deal_type": _s(j.get("deal_type"), 40), "city": _s(j.get("city"), 60), "district": _s(j.get("district"), 80),
                "address": _s(j.get("address"), 160), "price_usd": _s(j.get("final_price"), 20),
                "owner_number": _s(j.get("owner_number"), 30), "notes": _s(j.get("notes"), 500), "pets": m.pets_from_notes(j.get("notes")),
                "created_at": done, "last_verified_at": "", "last_updated_at": now_str(), "active": "yes", "archived": "",
            }
            _backend.append(m.LISTINGS_SHEET, m.LISTING_HEADERS, rec)
            added += 1
        return {"added": added, "skipped": skipped}


def set_flags(listing_id: str, **flags) -> dict | None:
    """active/archived ცვლილება (ადმინი). წაშლა არ არსებობს."""
    allowed = {k: ("yes" if v else "no") if k == "active" else ("yes" if v else "") for k, v in flags.items() if k in ("active", "archived")}
    with _lock:
        return _backend.update(m.LISTINGS_SHEET, m.LISTING_HEADERS, listing_id, dict(allowed, last_updated_at=now_str()))


# ====================================================================== კითხვა/ძიება
def all_rows(fresh: bool = False) -> list[dict]:
    return _backend.read(m.LISTINGS_SHEET, fresh=fresh)


def _rooms_num(v) -> float | None:
    mm = re.match(r"\s*(\d+)", str(v or ""))
    return float(mm.group(1)) if mm else None


def is_privileged(row: dict, viewer: dict) -> bool:
    if viewer.get("admin"):
        return True
    aid = _s(viewer.get("agent_id"))
    if aid and _s(row.get("agent_id")) == aid:
        return True
    return bool(viewer.get("role") == "team_lead" and _s(viewer.get("team")) and _s(row.get("team")) == _s(viewer.get("team")))


def _lc(v) -> str:
    return str(v or "").strip().lower()


def _match(row: dict, f: dict, viewer: dict, skip: str = "") -> bool:
    if skip != "active" and _lc(row.get("active")) == "no" and not f.get("include_inactive"):
        return False
    if _lc(row.get("archived")) in ("yes", "true", "1"):
        return False
    ids = f.get("ids")
    if ids and _s(row.get("listing_id")) not in ids:
        return False
    q = _lc(f.get("q"))
    if q:
        hay = " ".join(_lc(row.get(k)) for k in ("listing_id", "myhome_id", "ssge_id", "address", "district", "title", "agent_name", "city"))
        if q not in hay:
            return False
    for key in ("city", "district", "deal_type", "property_type", "condition", "agent_id"):
        if key == skip:
            continue
        v = _lc(f.get(key))
        if v and _lc(row.get(key)) != v:
            return False
    if f.get("mine") and _s(row.get("agent_id")) != _s(viewer.get("agent_id")):
        return False
    price = m.num(row.get("price_usd"))
    if f.get("price_min") is not None and (price is None or price < f["price_min"]):
        return False
    if f.get("price_max") is not None and (price is None or price > f["price_max"]):
        return False
    area = m.num(row.get("area"))
    if f.get("area_min") is not None and (area is None or area < f["area_min"]):
        return False
    if f.get("area_max") is not None and (area is None or area > f["area_max"]):
        return False
    def tokens_ok(value, toks) -> bool:                # "2,3,5+" ტიპის არჩევანი (ოთახები/საძინებლები)
        n = _rooms_num(value)
        for tok in toks:
            t = _rooms_num(tok)
            if n is not None and t is not None and ((n >= t) if str(tok).endswith("+") else (n == t)):
                return True
        return False

    if (f.get("rooms") or []) and not tokens_ok(row.get("rooms"), f["rooms"]):
        return False
    if (f.get("bedrooms") or []) and not tokens_ok(row.get("bedrooms"), f["bedrooms"]):
        return False
    if f.get("bedrooms_min") is not None:
        bn = _rooms_num(row.get("bedrooms"))
        if bn is None or bn < f["bedrooms_min"]:
            return False
    # სართული (რომელ სართულზეა) და სართულიანობა (შენობის სართულები)
    fl, fls = _rooms_num(row.get("floor")), _rooms_num(row.get("floors"))
    for key, val, lo in (("floor", fl, True), ("floors", fls, True)):
        mn, mx = f.get(key + "_min"), f.get(key + "_max")
        if mn is not None and (val is None or val < mn):
            return False
        if mx is not None and (val is None or val > mx):
            return False
    if f.get("not_first") and (fl is None or fl <= 1):
        return False
    if f.get("not_last") and (fl is None or fls is None or fl >= fls):
        return False
    if f.get("pets") and _lc(row.get("pets")) != _lc(f["pets"]):
        return False
    if f.get("district_any") is not None and not _district_hit(row, f["district_any"]):
        return False
    return True


def _district_hit(row: dict, names: list) -> bool:
    """„ჩემი რაიონები“: განცხადების რაიონი/მისამართი ემთხვევა კვირის რაიონებიდან რომელიმეს (ძირის მიხედვით — ბრუნვა/მართლწერა არ ხელყოფს)."""
    hay = f"{_lc(row.get('district'))} {_lc(row.get('address'))}"
    dist = _lc(row.get("district"))
    for n in names or []:
        nm = _lc(n)
        stem = nm[: max(4, len(nm) - 2)]
        if nm and (stem in hay or (dist and len(dist) >= 4 and dist[: max(4, len(dist) - 2)] in nm)):
            return True
    return False


def _sort(rows: list[dict], key: str, now: datetime.datetime) -> list[dict]:
    def newest(r):
        d = max([x for x in (m.parse_dt(r.get("last_verified_at")), m.parse_dt(r.get("created_at"))) if x] or [datetime.datetime.min])
        return d
    if key == "price_asc":
        return sorted(rows, key=lambda r: (m.num(r.get("price_usd")) is None, m.num(r.get("price_usd")) or 0))
    if key == "price_desc":
        return sorted(rows, key=lambda r: -(m.num(r.get("price_usd")) or 0))
    if key == "area_desc":
        return sorted(rows, key=lambda r: -(m.num(r.get("area")) or 0))
    return sorted(rows, key=newest, reverse=True)


def query(f: dict, viewer: dict, now: datetime.datetime | None = None) -> dict:
    """f — უკვე ვალიდირებული ფილტრები (listings_api); viewer = {agent_id, role, team, admin}."""
    now = now or now_dt()
    th = m.thresholds()
    rows = all_rows()
    base = [r for r in rows if _match(r, f, viewer)]
    wanted = {c for c in (f.get("freshness") or []) if c in m.FRESH_LABELS}
    if wanted:
        base = [r for r in base if m.freshness(r, now, th)["color"] in wanted]
    ordered = _sort(base, f.get("sort") or "new", now)
    per = max(1, min(int(f.get("per_page") or 24), 48))
    page = max(1, int(f.get("page") or 1))
    chunk = ordered[(page - 1) * per: page * per]
    items = [m.project(r, now, is_privileged(r, viewer), th) for r in chunk]
    dups = dup_map(rows)
    for it in items:                    # შესაძლო ორეული (გაფრთხილება): id-ები საჯარო ველია, პირადი მონაცემი არ გადადის
        others = dups.get(it["listing_id"]) or []
        it["dup_count"] = len(others)
        it["dup_ids"] = others[:4]

    # ფასეტები: რაიონების/ფერების რაოდენობა მიმდინარე ფილტრებით (თავად იმ ფილტრის გარეშე) — რუკისა და ჩიპებისთვის
    no_district = [r for r in rows if _match(r, f, viewer, skip="district")]
    if wanted:
        no_district = [r for r in no_district if m.freshness(r, now, th)["color"] in wanted]
    dcount: dict[str, int] = {}
    for r in no_district:
        d = _s(r.get("district"))
        if d:
            dcount[d] = dcount.get(d, 0) + 1
    no_fresh = [r for r in rows if _match(r, f, viewer)]
    fcount = {c: 0 for c in m.FRESH_LABELS}
    for r in no_fresh:
        fcount[m.freshness(r, now, th)["color"]] += 1
    visible_all = [r for r in rows if _lc(r.get("active")) != "no" and _lc(r.get("archived")) not in ("yes", "true", "1")]
    mine_total = sum(1 for r in visible_all if viewer.get("agent_id") and _s(r.get("agent_id")) == _s(viewer.get("agent_id")))
    cities = sorted({_s(r.get("city")) for r in visible_all if _s(r.get("city"))})
    return {
        "items": items, "total": len(ordered), "page": page, "per_page": per,
        "facets": {"districts": [{"name": k, "count": v} for k, v in sorted(dcount.items(), key=lambda kv: (-kv[1], kv[0]))],
                   "cities": cities, "fresh": fcount,
                   "deal_types": sorted({_s(r.get("deal_type")) for r in visible_all if _s(r.get("deal_type"))}),
                   "property_types": sorted({_s(r.get("property_type")) for r in visible_all if _s(r.get("property_type"))})},
        "meta": {"total_all": len(visible_all), "mine_total": mine_total, "thresholds": th, "fresh_labels": m.FRESH_LABELS},
    }


_DUP_CACHE: tuple = (0.0, None, {})


def dup_map(rows: list[dict] | None = None) -> dict:
    """{listing_id: [ორეულების id-ები]} — 60 წმ-იანი კეში (ცხრილის ზომა+ბოლო ცვლილება გასაღებია). მხოლოდ გაფრთხილება, არაფერი იშლება/ერთიანდება."""
    global _DUP_CACHE
    import time as _t
    rows = all_rows() if rows is None else rows
    key = (len(rows), max((_s(r.get("last_updated_at")) for r in rows), default=""))
    ts, k, val = _DUP_CACHE
    if k == key and _t.monotonic() - ts < 60:
        return val
    val = m.duplicate_groups(rows)
    _DUP_CACHE = (_t.monotonic(), key, val)
    return val


def _find(listing_id: str) -> dict | None:
    return next((x for x in all_rows(fresh=True) if _s(x.get("listing_id")) == _s(listing_id)
                 and _lc(x.get("archived")) not in ("yes", "true", "1")), None)


def verify(listing_id: str, viewer: dict) -> dict:
    """მფლობელი/გუნდის ლიდერი/ადმინი ადასტურებს, რომ განცხადება აქტუალურია → last_verified_at=ახლა (ფერი მწვანდება).
    ეს KPI-ს/ატვირთვის რიცხვებს არ ეხება — მხოლოდ კატალოგის სიახლის აღრიცხვას."""
    with _lock:
        r = _find(listing_id)
        if not r:
            raise ListingError("განცხადება ვერ მოიძებნა", 404)
        if not is_privileged(r, viewer):
            raise ListingError("მხოლოდ მფლობელს, გუნდის ლიდერს ან ადმინს შეუძლია", 403)
        now = now_str()
        _backend.update(m.LISTINGS_SHEET, m.LISTING_HEADERS, _s(r.get("listing_id")),
                        {"last_verified_at": now, "last_updated_at": now, "active": "yes"})
        return {"listing_id": _s(r.get("listing_id")), "last_verified_at": now}


def set_active(listing_id: str, viewer: dict, active: bool) -> dict:
    """გაქირავდა/გაიყიდა (active=no) ან თავიდან გააქტიურება — მფლობელი/გუნდის ლიდერი/ადმინი. ჩანაწერი არ იშლება."""
    with _lock:
        r = _find(listing_id)
        if not r:
            raise ListingError("განცხადება ვერ მოიძებნა", 404)
        if not is_privileged(r, viewer):
            raise ListingError("მხოლოდ მფლობელს, გუნდის ლიდერს ან ადმინს შეუძლია", 403)
        _backend.update(m.LISTINGS_SHEET, m.LISTING_HEADERS, _s(r.get("listing_id")),
                        {"active": "yes" if active else "no", "last_updated_at": now_str()})
        return {"listing_id": _s(r.get("listing_id")), "active": "yes" if active else "no"}


def map_points(f: dict, viewer: dict, now: datetime.datetime | None = None, limit: int = 1500) -> dict:
    """რუკისთვის: ფილტრებს დაქვემდებარებული განცხადებები **რეალური კოორდინატებით** (გამოგონილ წერტილს არ ვხატავთ). მხოლოდ საჯარო ველები."""
    now = now or now_dt()
    th = m.thresholds()
    wanted = {c for c in (f.get("freshness") or []) if c in m.FRESH_LABELS}
    pts, nocoord = [], 0
    for r in all_rows():
        if not _match(r, f, viewer):
            continue
        fr = m.freshness(r, now, th)["color"]
        if wanted and fr not in wanted:
            continue
        lat, lng = m.num(r.get("lat")), m.num(r.get("lng"))
        if lat is None or lng is None:
            nocoord += 1
            continue
        ph = m.photo_list(r)
        pts.append({"id": _s(r.get("listing_id")), "lat": lat, "lng": lng, "price": m.num(r.get("price_usd")), "deal": _s(r.get("deal_type")),
                    "rooms": _s(r.get("rooms")), "area": m.num(r.get("area")), "fr": fr, "photo": ph[0] if ph else "",
                    "district": _s(r.get("district")), "mine": bool(viewer.get("agent_id") and _s(r.get("agent_id")) == _s(viewer.get("agent_id")))})
    pts.sort(key=lambda p: p["id"])
    return {"points": pts[:limit], "total": len(pts), "no_coords": nocoord, "truncated": len(pts) > limit}


def insights(viewer: dict, now: datetime.datetime | None = None) -> dict:
    """სიახლის/აქტივობის შეჯამება: ადმინი — ყველა აგენტი; გუნდის ლიდერი — თავისი გუნდი; აგენტი — მხოლოდ საკუთარი. ტელეფონი/შიდა ველები არ გადადის."""
    now = now or now_dt()
    th = m.thresholds()
    rows = [r for r in all_rows() if _lc(r.get("active")) != "no" and _lc(r.get("archived")) not in ("yes", "true", "1")]
    if not viewer.get("admin"):
        if viewer.get("role") == "team_lead" and _s(viewer.get("team")):
            rows = [r for r in rows if _s(r.get("team")) == _s(viewer.get("team"))]
        else:
            rows = [r for r in rows if viewer.get("agent_id") and _s(r.get("agent_id")) == _s(viewer.get("agent_id"))]
    scope = "all" if viewer.get("admin") else ("team" if viewer.get("role") == "team_lead" else "mine")
    tot = {"total": 0, "new_7d": 0, "no_photo": 0, "no_coords": 0, "no_area": 0, "no_rooms": 0, "no_price": 0,
           "backfill_only": 0, "dup_listings": 0, "fresh": {c: 0 for c in m.FRESH_LABELS}}
    dups = dup_map()
    by: dict[str, dict] = {}
    for r in rows:
        tot["no_area"] += 1 if m.num(r.get("area")) is None else 0
        tot["no_rooms"] += 0 if _rooms_num(r.get("rooms")) is not None else 1
        tot["no_price"] += 1 if m.num(r.get("price_usd")) is None else 0
        tot["backfill_only"] += 1 if _s(r.get("source")) == "backfill" else 0
        tot["dup_listings"] += 1 if dups.get(_s(r.get("listing_id"))) else 0
        fr = m.freshness(r, now, th)
        created = m.parse_dt(r.get("created_at"))
        is_new = bool(created and (now - created).total_seconds() <= 7 * 86400)
        a = by.setdefault(_s(r.get("agent_id")) or "-", {"agent_id": _s(r.get("agent_id")), "name": _s(r.get("agent_name")) or "—", "team": _s(r.get("team")),
                                                         "total": 0, "new_7d": 0, "fresh": {c: 0 for c in m.FRESH_LABELS}, "need_verify": 0})
        for d in (tot, a):
            d["total"] += 1
            d["new_7d"] += 1 if is_new else 0
            d["fresh"][fr["color"]] += 1
        a["need_verify"] += 1 if fr["color"] in ("red", "grey") else 0
        tot["no_photo"] += 0 if m.photo_list(r) else 1
        tot["no_coords"] += 0 if (m.num(r.get("lat")) is not None and m.num(r.get("lng")) is not None) else 1
    agents = sorted(by.values(), key=lambda a: (-a["total"], a["name"]))
    return {"scope": scope, "totals": tot, "agents": agents[:60], "thresholds": th}


def get_one(listing_id: str, viewer: dict, now: datetime.datetime | None = None) -> dict | None:
    now = now or now_dt()
    r = next((x for x in all_rows() if _s(x.get("listing_id")) == _s(listing_id)), None)
    if not r or _lc(r.get("archived")) in ("yes", "true", "1"):
        return None
    return m.project(r, now, is_privileged(r, viewer))


def find_by_ref(ref: str) -> dict | None:
    """ბინა გარე ბმულით/ID-ით: შიდა listing_id, ჩვენი MyHome/ss.ge ID ან წყაროს (მესაკუთრის) ID — დავალებაში მენეჯერი ხშირად ამას წერს.
    სწრაფი ძებნა ახლადწაკითხული არ არის (cache); აბრუნებს სრულ სტრიქონს — გამომძახებელი თავად ირჩევს რომელი ველები გაიცეს."""
    r = _s(ref, 60)
    d = _digits(r)
    if not r:
        return None
    for x in all_rows():
        if _lc(x.get("archived")) in ("yes", "true", "1"):
            continue
        if _s(x.get("listing_id")) == r or (d and (_s(x.get("myhome_id")) == d or _s(x.get("ssge_id")) == d or _s(x.get("src_id")) == d)):
            return x
    return None
