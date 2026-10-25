"""
Safe Home Property Hub — განცხადებების კატალოგი: მოდელი (ცხრილი, სვეტები, სიახლის ფერები, საჯარო/შიდა ველების გამიჯვნა).

ეს ახალი მოდულია და არსებულ ატვირთვის/KPI ლოგიკას არ ეხება. მონაცემები ივსება:
  * ექსთენშენის მიერ job-ის დასრულებისას (`listing` სნეპშოტი /complete-ში — ახალი ID-ები, ფასი, ფართი, ფოტოები, კოორდინატები);
  * ადმინის ერთჯერადი "backfill"-ით უკვე COMPLETED job-ებიდან (ფოტოს/კოორდინატის გარეშე).

სიახლის ფერი ითვლება `last_verified_at`/`created_at`-ის ასაკით (ორი ველი განზრახ ცალკეა): ახალი → მწვანე, საშუალო → ნარინჯისფერი,
ძველი → წითელი, ძალიან ძველი → ნაცრისფერი (გადასამოწმებელი). ფერი არ ნიშნავს, რომ ბინა თავისუფალია ან ფასი სწორია.
"""

from __future__ import annotations

import datetime
import os
import re

LISTINGS_SHEET = "Listings"

LISTING_HEADERS = [
    "listing_id", "job_id", "agent_id", "agent_name", "team", "source",       # source: upload | backfill
    "myhome_id", "ssge_id", "src_site", "src_id",
    "deal_type", "property_type", "title", "city", "district", "address",
    "price_usd", "area", "rooms", "bedrooms", "floor", "floors", "condition", "status_text",
    "lat", "lng", "photos",
    "owner_number", "notes",                                                  # შიდა — სხვა აგენტს არ ეგზავნება
    "created_at", "last_verified_at", "last_updated_at", "active", "archived",
    "pets",                                                                   # yes | no | ask (მესაკუთრის პირობა; MyHome ტაბის "ცხოველები: კი/არა/შეთანხმებით" შენიშვნიდან)
]
ALL_TABS = [(LISTINGS_SHEET, LISTING_HEADERS, 2000)]

_PETS_RE = re.compile(r"ცხოველები:\s*(არა|კი|შეთანხმებით)")
_PETS_MAP = {"კი": "yes", "არა": "no", "შეთანხმებით": "ask"}


def pets_from_notes(notes) -> str:
    """მესაკუთრის პირობა ცხოველებზე job-ის შენიშვნიდან ('ცხოველები: კი/არა/შეთანხმებით'); მითითებული არ არის — ცარიელი (არ ვივარაუდებთ)."""
    hits = _PETS_RE.findall(str(notes or ""))
    return _PETS_MAP.get(hits[-1], "") if hits else ""

# ეს ველები სხვა აგენტს ეგზავნება; დანარჩენი (owner_number, notes, job_id, src_id, src_site...) — მხოლოდ მფლობელს/გუნდის ლიდერს/ადმინს
PUBLIC_FIELDS = [
    "listing_id", "agent_id", "agent_name", "team", "myhome_id", "ssge_id", "deal_type", "property_type", "title", "city", "district",
    "address", "price_usd", "area", "rooms", "bedrooms", "floor", "floors", "condition", "status_text", "lat", "lng",
    "created_at", "last_verified_at", "last_updated_at", "active", "pets",
]
PRIVATE_FIELDS = ["owner_number", "notes", "job_id", "src_site", "src_id", "source"]

MAX_PHOTOS = 12
PHOTO_SEP = "|"


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default


_PROVIDER = None
_TH_CACHE: tuple[float, dict | None] = (0.0, None)


def set_threshold_provider(fn) -> None:
    """ადმინის შენახული ზღვრები (hubprefs) — გადაფარავს Railway-ს ცვლადებს; fn() -> {fresh, mid, stale} ნაწილობრივიც შეიძლება."""
    global _PROVIDER, _TH_CACHE
    _PROVIDER, _TH_CACHE = fn, (0.0, None)


def invalidate_thresholds() -> None:
    global _TH_CACHE
    _TH_CACHE = (0.0, None)


def _norm_th(fresh: int, mid: int, stale: int) -> dict:
    mid = max(fresh + 1, mid)
    stale = max(mid + 1, stale)
    return {"fresh": fresh, "mid": mid, "stale": stale}


def env_thresholds() -> dict:
    return _norm_th(_env_int("HUB_FRESH_DAYS", 3), _env_int("HUB_MID_DAYS", 14), _env_int("HUB_STALE_DAYS", 60))


def thresholds() -> dict:
    """ზღვრები დღეებში: ადმინის პანელის მნიშვნელობა (თუ არის) -> Railway ცვლადები -> 3/14/60. პროვაიდერის ჩავარდნა ნაგულისხმევს არ ანგრევს."""
    global _TH_CACHE
    base = env_thresholds()
    if _PROVIDER is None:
        return base
    import time as _t
    now = _t.monotonic()
    if _TH_CACHE[1] is not None and now - _TH_CACHE[0] < 20:
        return dict(_TH_CACHE[1])
    try:
        ov = _PROVIDER() or {}
        res = _norm_th(int(ov.get("fresh", base["fresh"])), int(ov.get("mid", base["mid"])), int(ov.get("stale", base["stale"])))
    except Exception:  # noqa: BLE001
        res = base
    _TH_CACHE = (now, res)
    return dict(res)

FRESH_LABELS = {"green": "ახალი", "orange": "საშუალო", "red": "ძველი", "grey": "გადასამოწმებელი"}


def parse_dt(v) -> datetime.datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def age_days(row: dict, now: datetime.datetime) -> float | None:
    """ასაკი: ბოლო რეალური გადამოწმება ან (თუ არ არის) ბაზაში დამატება — რომელიც უფრო ახალია."""
    dts = [d for d in (parse_dt(row.get("last_verified_at")), parse_dt(row.get("created_at"))) if d]
    if not dts:
        return None
    return max(0.0, (now - max(dts)).total_seconds() / 86400.0)


def freshness(row: dict, now: datetime.datetime, th: dict | None = None) -> dict:
    th = th or thresholds()
    a = age_days(row, now)
    if a is None:
        return {"color": "grey", "label": FRESH_LABELS["grey"], "age_days": None}
    color = "green" if a <= th["fresh"] else "orange" if a <= th["mid"] else "red" if a <= th["stale"] else "grey"
    return {"color": color, "label": FRESH_LABELS[color], "age_days": int(a)}


def photo_list(row: dict) -> list[str]:
    return [p for p in str(row.get("photos") or "").split(PHOTO_SEP) if p.startswith("http")][:MAX_PHOTOS]


def portal_links(row: dict) -> dict:
    my, ss = str(row.get("myhome_id") or "").strip(), str(row.get("ssge_id") or "").strip()
    return {
        "myhome_url": f"https://www.myhome.ge/pr/{my}" if my.isdigit() else "",
        "ssge_url": f"https://home.ss.ge/ka/udzravi-qoneba/{ss}" if ss.isdigit() else "",
    }


def num(v) -> float | None:
    try:
        s = str(v if v is not None else "").strip().replace(",", ".")
        return float(s) if s not in ("", "None", "null") else None
    except (TypeError, ValueError):
        return None


def project(row: dict, now: datetime.datetime, privileged: bool, th: dict | None = None) -> dict:
    """სერვერული პროექცია: privileged=False-ზე შიდა ველები პასუხში საერთოდ არ არის (არა მხოლოდ დამალული UI-ში)."""
    out = {k: row.get(k, "") for k in PUBLIC_FIELDS}
    out["photos"] = photo_list(row)
    out.update(portal_links(row))
    out["freshness"] = freshness(row, now, th)
    out["price_usd"] = num(row.get("price_usd"))
    out["area"] = num(row.get("area"))
    out["lat"], out["lng"] = num(row.get("lat")), num(row.get("lng"))
    out["private"] = bool(privileged)
    if privileged:
        for k in PRIVATE_FIELDS:
            out[k] = row.get(k, "")
    return out


class ListingError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status
