"""
TGNET: არხების რეესტრის შენახვა (ცხრილები TgChannels / TgPosts / TgSettings / TgLog; tab_backend-ის ნიმუში — იგივე რაც კადრებში).
საწყისი 18 არხი იკითხება `tgnet_channels.json`-იდან (გენერატორი: TGNET/build_pack.py); seed **არასდროს ანადგურებს** ხელით შეყვანილ მონაცემს (chat_id, ჩამრთველი, შენიშვნა).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import uuid

import config
import crm_time
import tab_backend
import tgnet_model as m

log = logging.getLogger("safehome-tgnet")
_lock = threading.RLock()
SheetsBackend, MemoryBackend = tab_backend.make(m.ALL_TABS)
_backend = SheetsBackend()
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tgnet_channels.json")


class TgnetError(Exception):
    def __init__(self, msg: str, status: int = 400, code: str = ""):
        super().__init__(msg)
        self.status = status
        self.code = code


def set_backend(b) -> None:
    global _backend
    _backend = b


def ensure_tabs() -> None:
    with _lock:
        _backend.ensure()


def now_str() -> str:
    return crm_time.local_now().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")


def _s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


# ---------------------------------------------------------------------------------------------- პარამეტრები
def get_settings() -> dict:
    rows = {r.get("key"): r.get("value", "") for r in _backend.read(m.TG_SETTINGS)}
    return {"master": (rows.get("master") if rows.get("master") in ("0", "1") else ("1" if config.TGNET_ENABLED else "0")) == "1"}


def set_setting(key: str, value: str) -> None:
    with _lock:
        rows = _backend.read(m.TG_SETTINGS, fresh=True)
        if any(r.get("key") == key for r in rows):
            _backend.update(m.TG_SETTINGS, m.SETTINGS_HEADERS, key, {"value": value})
        else:
            _backend.append(m.TG_SETTINGS, m.SETTINGS_HEADERS, {"key": key, "value": value})


def log_event(channel_key: str, kind: str, text: str) -> None:
    try:
        _backend.append(m.TG_LOG, m.LOG_HEADERS, {"log_id": uuid.uuid4().hex[:10], "at": now_str(), "channel_key": _s(channel_key, 60), "kind": _s(kind, 30), "text": _s(text, 400)})
    except Exception:  # noqa: BLE001 — ლოგის ჩავარდნა ძირითად ქმედებას არ აჩერებს
        log.warning("TgLog ჩაწერა ვერ მოხერხდა", exc_info=True)


# ---------------------------------------------------------------------------------------------- არხები
def seed_rows() -> list[dict]:
    with open(SEED_FILE, encoding="utf-8") as f:
        return json.load(f)["channels"]


def seed_channels() -> int:
    """ამატებს მხოლოდ იმ არხებს, რომლებიც ცხრილში ჯერ არ არის (channel_key-ით). არსებულს არ ეხება. აბრუნებს დამატებულთა რაოდენობას."""
    with _lock:
        have = {_s(r.get("channel_key")) for r in _backend.read(m.TG_CHANNELS, fresh=True)}
        new = []
        for c in seed_rows():
            if c["key"] in have:
                continue
            new.append({"channel_key": c["key"], "n": c["n"], "lang": c["lang"], "segment": c["segment"], "deal": c["deal"], "city": c["city"], "title": c["title"],
                        "username": c["username"], "chat_id": "", "link": c["link"], "enabled": "0", "status": "planned", "members": "", "members_at": "",
                        "last_check_at": "", "last_error": "", "note": "", "description": c["description"]})
        if new:
            _backend.append_many(m.TG_CHANNELS, m.HEADERS, new)
            log_event("", "seed", f"დაემატა {len(new)} არხი")
        return len(new)


def list_channels(fresh: bool = False) -> list[dict]:
    rows = _backend.read(m.TG_CHANNELS, fresh=fresh)
    out = []
    for r in rows:
        d = {k: _s(r.get(k), 400) for k in m.HEADERS}
        d["enabled"] = d["enabled"] == "1"
        try:
            d["n"] = int(d["n"])
        except ValueError:
            d["n"] = 0
        d["status_label"] = m.STATUS_LABELS.get(d["status"], d["status"])
        out.append(d)
    out.sort(key=lambda x: x["n"])
    return out


def get_channel(key: str, fresh: bool = False) -> dict | None:
    return next((c for c in list_channels(fresh) if c["channel_key"] == _s(key)), None)


def update_channel(key: str, changes: dict, by: str = "") -> dict:
    """ხელით რედაქტირება: chat_id, enabled, status (მხოლოდ paused/გაუქმება), note. username/სათაური არ იცვლება აქედან (ისინი Telegram-ში არსებულს უნდა ემთხვეოდეს)."""
    with _lock:
        ch = get_channel(key, fresh=True)
        if not ch:
            raise TgnetError("არხი ვერ მოიძებნა", 404, "not_found")
        upd: dict = {}
        if "chat_id" in changes:
            cid = _s(changes["chat_id"], 30)
            if cid and not m.valid_chat_id(cid):
                raise TgnetError("chat_id არასწორია: უნდა იყოს ფორმის -100xxxxxxxxxx", 400, "bad_chat_id")
            if cid and any(c["chat_id"] == cid and c["channel_key"] != ch["channel_key"] for c in list_channels()):
                raise TgnetError("ეს chat_id სხვა არხზეა უკვე მიბმული", 409, "dup_chat_id")
            upd["chat_id"] = cid
            if cid != ch["chat_id"]:
                upd.update({"status": "linked" if cid else "planned", "enabled": "0", "last_error": "", "members": "", "members_at": ""})   # ახალი მიბმა -> ხელახლა შემოწმებამდე გამორთულია
        if "enabled" in changes:
            want = bool(changes["enabled"])
            if want and (upd.get("chat_id", ch["chat_id"]) == "" or (upd.get("status") or ch["status"]) not in ("live",)):
                raise TgnetError("არხის ჩასართავად ჯერ chat_id მიაბით და გაიარეთ შემოწმება (სტატუსი „მზადაა“)", 400, "not_ready")
            upd["enabled"] = "1" if want else "0"
        if "note" in changes:
            upd["note"] = _s(changes["note"], 300)
        if "status" in changes:
            if changes["status"] not in ("paused", "linked", "created", "planned"):
                raise TgnetError("სტატუსი ხელით ასე ვერ შეიცვლება", 400, "bad_status")
            upd["status"] = changes["status"]
            if changes["status"] == "paused":
                upd["enabled"] = "0"
        if not upd:
            return ch
        _backend.update(m.TG_CHANNELS, m.HEADERS, ch["channel_key"], upd)
        log_event(ch["channel_key"], "edit", f"{by or 'ადმინი'}: " + ", ".join(f"{k}={v}" for k, v in upd.items() if k != "last_error"))
        return get_channel(ch["channel_key"], fresh=True)


def record_checks(results: dict) -> int:
    """results = {channel_key: health-dict} -> ერთი batch ჩაწერა (Sheets-ის კვოტის დასაზოგად). ჯანმრთელი არხი -> live; პრობლემა -> attention + ახსნა; enabled ითიშება პრობლემისას."""
    changes = {}
    now = now_str()
    cur = {c["channel_key"]: c for c in list_channels(fresh=True)}
    for key, h in results.items():
        c = cur.get(key)
        if not c:
            continue
        ch = {"last_check_at": now, "last_error": "; ".join(h.get("issues") or [])[:380], "status": h.get("status", "attention")}
        if h.get("members") is not None:
            ch.update({"members": str(h["members"]), "members_at": now})
        if ch["status"] != "live":
            ch["enabled"] = "0"
        if c["status"] == "paused":                     # ხელით შეჩერებული არხი შემოწმებით ავტომატურად არ აქტიურდება
            ch["status"] = "paused"
            ch["enabled"] = "0"
        changes[key] = ch
    with _lock:
        n = _backend.update_many(m.TG_CHANNELS, m.HEADERS, changes) if changes else 0
        if n:
            log_event("", "check", f"შემოწმდა {n} არხი; პრობლემა: {sum(1 for h in results.values() if h.get('status') != 'live')}")
    return n

# ====================================================================== ეტაპი 3: გასაგზავნი რიგი (TgPosts) — **გაგზავნის გარეშე**
def listing_summary(rec: dict) -> str:
    """ერთი ხაზი რიგის ეკრანისთვის (შიდა ველები — მესაკუთრის ნომერი/შენიშვნა — აქ არასდროს ხვდება)."""
    price = m._num(rec.get("price_usd"))
    parts = [str(rec.get("property_type") or "").strip(), str(rec.get("deal_type") or "").strip(),
             ", ".join(x for x in (str(rec.get("city") or "").strip(), str(rec.get("district") or "").strip()) if x),
             (f"{int(price)}$" if price else ""), (f"{_s(rec.get('area'), 10)} მ²" if m._num(rec.get("area")) else ""), (f"{_s(rec.get('rooms'), 4)} ოთ." if _s(rec.get("rooms")) else "")]
    return " · ".join(p for p in parts if p)[:300]


def enqueue_listing(rec: dict, auto_approve: bool | None = None, min_photos: int | None = None) -> dict:
    """ახალი განცხადება -> რიგის ჩანაწერები (თითო არხზე, 3 ენა). **განმეორებით უვნებელია** (post_id = listing:channel). აბრუნებს {created, status, reasons, channels}.
    სტატუსი: skipped (არხს არ ეკუთვნის) | needs_fix (ხარისხის ფილტრი) | pending (ელოდება დამტკიცებას) | approved (TGNET_AUTO_APPROVE=1). არაფერი იგზავნება."""
    auto = config.TGNET_AUTO_APPROVE if auto_approve is None else auto_approve
    mp = config.TGNET_MIN_PHOTOS if min_photos is None else min_photos
    lid = _s(rec.get("listing_id"), 60)
    if not lid:
        return {"created": 0, "status": "ignored", "reasons": ["listing_id არ არის"], "channels": []}
    r = m.route(rec)
    if not r["eligible"]:
        status, reasons, channels = "skipped", [r["reason"]], [""]
    else:
        reasons = m.quality(rec, mp)
        status = "needs_fix" if reasons else ("approved" if auto else "pending")
        channels = r["channels"]
    now = now_str()
    with _lock:
        have = {_s(p.get("post_id")) for p in _backend.read(m.TG_POSTS, fresh=True)}
        rows = []
        for ch in channels:
            pid = f"{lid}:{ch}" if ch else f"{lid}:-"
            if pid in have:
                continue
            rows.append({"post_id": pid, "listing_key": lid, "channel_key": ch, "message_ids": "", "status": status, "posted_at": "", "updated_at": now,
                         "error": "; ".join(reasons)[:380], "created_at": now, "decided_by": "ავტომატური" if status == "approved" else "", "decided_at": now if status == "approved" else "",
                         "summary": listing_summary(rec), "agent_name": _s(rec.get("agent_name"), 80)})
        if rows:
            _backend.append_many(m.TG_POSTS, m.POST_HEADERS, rows)
            log_event("", "enqueue", f"{lid}: {status} ({len(rows)} არხი)")
    return {"created": len(rows), "status": status, "reasons": reasons, "channels": [c for c in channels if c]}


def list_posts(statuses=None, fresh: bool = False) -> list[dict]:
    rows = _backend.read(m.TG_POSTS, fresh=fresh)
    out = [{k: _s(r.get(k), 400) for k in m.POST_HEADERS} for r in rows]
    if statuses:
        out = [p for p in out if p["status"] in statuses]
    return out


def queue_groups(statuses=("pending", "needs_fix", "approved", "rejected", "skipped"), limit: int | None = 60) -> list[dict]:
    """პოსტები განცხადებით დაჯგუფებული (ერთი განცხადება = ერთი ბარათი 3 არხით). ახალი პირველი."""
    groups: dict = {}
    for p in list_posts(statuses, fresh=True):
        g = groups.setdefault(p["listing_key"], {"listing_key": p["listing_key"], "summary": p["summary"], "agent_name": p["agent_name"], "created_at": p["created_at"],
                                                 "status": p["status"], "error": p["error"], "channels": [], "decided_by": p["decided_by"], "decided_at": p["decided_at"]})
        if p["channel_key"]:
            g["channels"].append(p["channel_key"])
    out = sorted(groups.values(), key=lambda g: g["created_at"], reverse=True)
    return out[:limit] if limit else out


def decide_listing(listing_key: str, action: str, by: str = "") -> int:
    """დირექტორის გადაწყვეტილება: approve | reject — ყველა ამ განცხადების pending/needs_fix ჩანაწერზე (3 არხი ერთად). approve needs_fix-ზეც შეიძლება (შეგნებული გადაწყვეტილება)."""
    if action not in ("approve", "reject"):
        raise TgnetError("მოქმედება უცნობია", 400, "bad_action")      # წაშლა — decide_many-ით (ერთიანი ან ერთეული)
    new = "approved" if action == "approve" else "rejected"
    now = now_str()
    with _lock:
        rows = [p for p in list_posts(("pending", "needs_fix", "approved", "rejected"), fresh=True) if p["listing_key"] == _s(listing_key)]
        if not rows:
            raise TgnetError("რიგში ასეთი განცხადება არ არის", 404, "not_found")
        changes = {p["post_id"]: {"status": new, "decided_by": _s(by, 80) or "დირექტორი", "decided_at": now, "updated_at": now} for p in rows if p["status"] != new}
        n = _backend.update_many(m.TG_POSTS, m.POST_HEADERS, changes) if changes else 0
        log_event("", "decide", f"{listing_key}: {new} ({n} არხი)")
    return n

def update_posts(changes: dict) -> int:
    """changes = {post_id: {ველი: მნიშვნელობა}} -> ერთი batch ჩაწერა (Sheets-ის კვოტა)."""
    if not changes:
        return 0
    with _lock:
        return _backend.update_many(m.TG_POSTS, m.POST_HEADERS, changes)


def get_post(post_id: str) -> dict | None:
    return next((p for p in list_posts(fresh=True) if p["post_id"] == _s(post_id)), None)

# ====================================================================== ლიდები (Telegram-იდან დაინტერესება)
def add_lead_event(kind: str, listing_key: str, tg_user_id, tg_name: str = "", channel_key: str = "", phone_norm: str = "", client_id: str = "", note: str = "") -> dict:
    rec = {"lead_id": uuid.uuid4().hex[:10], "at": now_str(), "listing_key": _s(listing_key, 60), "channel_key": _s(channel_key, 60), "kind": kind, "tg_user_id": _s(tg_user_id, 20),
           "tg_name": _s(tg_name, 80), "phone_norm": _s(phone_norm, 20), "client_id": _s(client_id, 30), "status": "new" if kind == "lead" else "", "assigned_agent_id": "", "assigned_by": "", "note": _s(note, 300)}
    with _lock:
        _backend.append(m.TG_LEADS, m.LEAD_HEADERS, rec)
    return rec


def list_lead_rows(fresh: bool = False) -> list[dict]:
    return [{k: _s(r.get(k), 300) for k in m.LEAD_HEADERS} for r in _backend.read(m.TG_LEADS, fresh=fresh)]


def update_lead(lead_id: str, changes: dict) -> dict | None:
    with _lock:
        return _backend.update(m.TG_LEADS, m.LEAD_HEADERS, lead_id, changes)


def last_intent(tg_user_id, within_min: int = 60) -> dict | None:
    """ბოლო „მინდა დაკავშირება“ ამ მომხმარებლისგან (ტელეფონის გაზიარებისას ვიცით რომელი განცხადებაა)."""
    now = datetime.datetime.strptime(now_str(), "%Y-%m-%d %H:%M")
    for r in reversed(list_lead_rows(fresh=True)):
        if r["kind"] == "intent" and r["tg_user_id"] == _s(tg_user_id, 20):
            try:
                t = datetime.datetime.strptime(r["at"], "%Y-%m-%d %H:%M")
            except ValueError:
                return None
            return r if (now - t).total_seconds() <= within_min * 60 else None
    return None


def interest_stats(limit: int = 20) -> list[dict]:
    """რომელი განცხადებით არიან კლიენტები ყველაზე დაინტერესებულები: ლიდი = 3 ქულა, „დაკავშირება“ = 2, ნახვა = 1."""
    agg: dict = {}
    for r in list_lead_rows(fresh=True):
        if not r["listing_key"]:
            continue
        a = agg.setdefault(r["listing_key"], {"listing_key": r["listing_key"], "views": 0, "intents": 0, "leads": 0, "last_at": ""})
        a[{"view": "views", "intent": "intents", "lead": "leads"}.get(r["kind"], "views")] += 1
        a["last_at"] = max(a["last_at"], r["at"])
    for a in agg.values():
        a["score"] = a["leads"] * 3 + a["intents"] * 2 + a["views"]
    return sorted(agg.values(), key=lambda a: (a["score"], a["last_at"]), reverse=True)[:limit]


QUEUE_STATUSES = ("pending", "needs_fix", "approved", "rejected", "skipped")


def queue_page(status: str = "", q: str = "", date_from: str = "", date_to: str = "", limit: int = 20, offset: int = 0) -> dict:
    """რიგის გვერდი ფილტრებით (სერვერზე): სტატუსი (მძიმით), ძიება (ID/აღწერა/აგენტი), თარიღი (YYYY-MM-DD). counts — სტატუსების რაოდენობა ფილტრის გარეშე, რომ ღილაკებზე რიცხვები სწორი იყოს."""
    allg = queue_groups(QUEUE_STATUSES, limit=None)
    counts: dict = {}
    for g in allg:
        counts[g["status"]] = counts.get(g["status"], 0) + 1
    want = {x for x in str(status or "").split(",") if x in QUEUE_STATUSES}
    ql = _s(q, 80).lower()
    rows = []
    for g in allg:
        if want and g["status"] not in want:
            continue
        if ql and ql not in f"{g['listing_key']} {g['summary']} {g['agent_name']}".lower():
            continue
        day = g["created_at"][:10]
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        rows.append(g)
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    return {"groups": rows[offset:offset + limit], "total": len(rows), "counts": counts, "limit": limit, "offset": offset}


def decide_many(listing_keys, action: str, by: str = "") -> dict:
    """ერთიანი მოქმედება მონიშნულ განცხადებებზე (≤200): approve | reject | delete. ერთი წაკითხვა + ერთი ჩაწერა. გამოქვეყნებული პოსტის მქონე განცხადებას არ ვეხებით (მისი წაშლა სინქრონიზაციით ხდება, რომ არხში „ობოლი“ შეტყობინება არ დარჩეს)."""
    if action not in ("approve", "reject", "delete"):
        raise TgnetError("მოქმედება უცნობია", 400, "bad_action")
    keys = {_s(k, 60) for k in (listing_keys or []) if _s(k, 60)}
    if not keys:
        raise TgnetError("აირჩიეთ განცხადება", 400, "nothing_selected")
    if len(keys) > 200:
        raise TgnetError("ერთდროულად მაქსიმუმ 200 განცხადება", 400, "too_many")
    new = {"approve": "approved", "reject": "rejected", "delete": "deleted"}[action]
    allowed_from = ("pending", "needs_fix", "approved", "rejected") + (("skipped",) if action == "delete" else ())
    now = now_str()
    with _lock:
        rows = [p for p in list_posts(fresh=True) if p["listing_key"] in keys]
        blocked = {p["listing_key"] for p in rows if p["status"] == "published"}
        changes, touched = {}, set()
        for p in rows:
            if p["listing_key"] in blocked or p["status"] not in allowed_from or p["status"] == new:
                continue
            changes[p["post_id"]] = {"status": new, "decided_by": _s(by, 80) or "დირექტორი", "decided_at": now, "updated_at": now}
            touched.add(p["listing_key"])
        n = _backend.update_many(m.TG_POSTS, m.POST_HEADERS, changes) if changes else 0
        if n:
            log_event("", "bulk_" + action, f"{len(touched)} განცხადება, {n} არხი")
    return {"changed": n, "listings": len(touched), "skipped_published": len(blocked), "not_found": len(keys - {p["listing_key"] for p in rows})}
