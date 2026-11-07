"""
TGNET ეტაპი 4: გამოქვეყნება. **გამორთულია, სანამ TGNET_PUBLISH_ENABLED=0** (ბოტის ფონური ამოცანა ამას ამოწმებს) და მთავარი ჩამრთველი (TgSettings.master) არ ჩაირთვება.

რას აქვეყნებს: მხოლოდ **დამტკიცებულ** (status=approved) ჩანაწერებს, **ჩართულ და ჯანმრთელ** (enabled + live) არხზე, მხოლოდ სამუშაო საათებში (თბილისი), ლიმიტებით (ინტერვალი/დღიური).
უსაფრთხოება: სურათს ჩვენი სერვერი ჩამოტვირთავს (Telegram ss.ge-ის ბმულს ვერ იღებს) — მხოლოდ დაშვებული დომენებიდან, ზომის/ტიპის შემოწმებით; ტექსტს ვალიდატორი ამოწმებს; სიახლის შემოწმება
გამოქვეყნებამდე (განცხადება აქტიურია და არ არის ძველი); ჩავარდნა -> 3 ცდა გაუმჯობესებული პაუზით; ერთი მარცხი სხვა პოსტებს არ აჩერებს; 429 -> მთელი ციკლი ჩერდება.
სინქრონიზაცია: განცხადება გაუქმდა -> პოსტი იშლება; ფასი შეიცვალა -> წარწერა რედაქტირდება.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import urllib.request
from urllib.parse import urlparse

import config
import crm_time
import tgnet_client as cl
import tgnet_content as content
import tgnet_model as m
import tgnet_store as st

log = logging.getLogger("safehome-tgnet-pub")
MAX_ATTEMPTS = 3
RETRY_MIN = (10, 30, 90)         # პაუზა ცდებს შორის (წუთი)
MAX_IMG_BYTES = 8 * 1024 * 1024
BRAND_FN = None        # ტესტებისთვის ჩანაცვლებადი; None -> tgnet_brand (Pillow)


def brand_photo(data: bytes) -> bytes:
    """ფოტო -> Safe Home „SH“ იარლიყით. ვერ ხერხდება და TGNET_BRAND_REQUIRED=1 -> TgError (დაუბრენდებელს არ ვაქვეყნებთ)."""
    if BRAND_FN is not None:
        return BRAND_FN(data)
    import tgnet_brand
    if not tgnet_brand.available():
        if config.TGNET_BRAND_REQUIRED:
            raise cl.TgError("ბრენდირება ვერ ხერხდება: Pillow არ არის დაყენებული")
        return data
    try:
        return tgnet_brand.brand_from_config(data)
    except Exception as e:  # noqa: BLE001
        if config.TGNET_BRAND_REQUIRED:
            raise cl.TgError(f"ფოტოს ბრენდირება ვერ მოხერხდა: {e}") from e
        return data


def _now() -> datetime.datetime:
    return crm_time.local_now().replace(tzinfo=None)


def _parse(s) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(str(s).strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def get_listing(listing_id: str) -> dict | None:
    import listings_store
    return next((r for r in listings_store.all_rows(fresh=True) if str(r.get("listing_id") or "").strip() == str(listing_id)), None)


def in_window(now: datetime.datetime) -> bool:
    a, b = config.TGNET_POST_HOURS
    return a <= now.hour < b


def allowed_photo_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host or host in ("localhost",) or re.match(r"^[\d.]+$", host) or ":" in host:
        return False
    return any(host == d or host.endswith("." + d) for d in config.TGNET_PHOTO_HOSTS)


def download_photo(url: str, opener=None) -> bytes:
    if not allowed_photo_url(url):
        raise cl.TgError(f"ფოტოს დომენი დაშვებული არ არის: {urlparse(url).hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with (opener or urllib.request.urlopen)(req, timeout=20) as r:
        ctype = str(r.headers.get("Content-Type", "")).lower()
        data = r.read(MAX_IMG_BYTES + 1)
    if len(data) > MAX_IMG_BYTES:
        raise cl.TgError("ფოტო ძალიან დიდია")
    if not ctype.startswith("image/") or len(data) < 2000:
        raise cl.TgError("ბმული სურათს არ აბრუნებს")
    return data


def _ids(p: dict) -> tuple[list[int], str]:
    try:
        d = json.loads(p.get("message_ids") or "{}")
        return [int(x) for x in d.get("ids", [])], str(d.get("h") or "")
    except (ValueError, TypeError):
        return [], ""


def _attempts(p: dict) -> int:
    mm = re.match(r"ცდა (\d+)/", str(p.get("error") or ""))
    return int(mm.group(1)) if mm else 0


def publish_post(post: dict, channel: dict, listing: dict, client: cl.Client, fetch=download_photo) -> dict:
    """ერთი პოსტის გამოქვეყნება. აბრუნებს {status, message_ids, hash, error}. ქსელის შეცდომას ზევით არ აგდებს (გარდა 429-ისა — ის retry_after-ით TgError-ად მიდის)."""
    lang = channel["lang"]
    rendered = content.render(listing, lang, channel["channel_key"])
    problems = content.validate(rendered, listing)
    if problems:
        return {"status": "needs_fix", "error": "ტექსტის შემოწმება: " + "; ".join(problems)}
    urls = rendered["photos"]
    if len(urls) < config.TGNET_MIN_PHOTOS:
        return {"status": "needs_fix", "error": f"ფოტო ცოტაა: {len(urls)}"}
    blobs = []
    for u in urls:
        try:
            blobs.append(brand_photo(fetch(u)))
        except Exception as e:  # noqa: BLE001 — ერთი ჩავარდნილი ფოტო მთელ პოსტს არ აჩერებს
            log.info("TGNET: ფოტო გამოვტოვეთ (%s): %s", urlparse(u).hostname, e)
    if len(blobs) < config.TGNET_MIN_PHOTOS:
        raise cl.TgError(f"ჩამოვტვირთე მხოლოდ {len(blobs)} ფოტო {len(urls)}-დან")
    chat = channel["chat_id"]
    lid = str(listing.get("listing_id") or "")
    if config.TGNET_POST_MODE == "album" and len(blobs) > 1:
        ids = client.send_album(chat, blobs, rendered["text"])
    else:      # ერთი ყდის ფოტო + ღილაკი (კლიენტი ხედავს დეტალებს და ტოვებს მოთხოვნას); დანარჩენი ფოტო ბოტში/Mini App-ში ჩანს
        btn = {"inline_keyboard": [[{"text": "📩 " + content.L[lang]["cta"], "url": content.link_for(lid, lang)}]]} if lid else None
        ids = [client.send_photo(chat, blobs[0], rendered["text"], reply_markup=btn)]
    return {"status": "published", "message_ids": json.dumps({"ids": ids, "h": rendered["hash"]}), "hash": rendered["hash"]}


def run_cycle(client: cl.Client | None = None, now: datetime.datetime | None = None, fetch=download_photo, max_posts: int = 2) -> dict:
    """ერთი ციკლი (ბოტი ყოველ 2 წუთში). აბრუნებს მოკლე ანგარიშს. ყველაფერი ჩავარდნისგან დაცულია."""
    rep = {"published": 0, "retry": 0, "failed": 0, "expired": 0, "removed": 0, "edited": 0, "skipped": ""}
    if not config.TGNET_PUBLISH_ENABLED:
        rep["skipped"] = "TGNET_PUBLISH_ENABLED=0"
        return rep
    if not st.get_settings()["master"]:
        rep["skipped"] = "მთავარი ჩამრთველი გამორთულია"
        return rep
    client = client or cl.Client()
    if not client.configured:
        rep["skipped"] = "ტოკენი არ არის"
        return rep
    now = now or _now()
    chans = {c["channel_key"]: c for c in st.list_channels(fresh=True)}
    posts = st.list_posts(fresh=True)
    changes: dict = {}

    def _set(p, **kw):
        changes[p["post_id"]] = dict(changes.get(p["post_id"], {}), updated_at=now.strftime("%Y-%m-%d %H:%M"), **kw)

    try:
        _sync(posts, chans, client, now, rep, _set)
    except cl.TgError as e:
        if e.code == 429:
            st.update_posts(changes)
            rep["skipped"] = "Telegram: ზედმეტი მოთხოვნა — ციკლი გაჩერდა"
            return rep
    if in_window(now):
        done_today = {}
        last_post = {}
        for p in posts:
            if p["status"] == "published":
                t = _parse(p.get("posted_at"))
                if t:
                    last_post[p["channel_key"]] = max(last_post.get(p["channel_key"], t), t)
                    if t.date() == now.date():
                        done_today[p["channel_key"]] = done_today.get(p["channel_key"], 0) + 1
        queue = sorted([p for p in posts if p["status"] == "approved" and p["channel_key"]], key=lambda p: p["created_at"])
        n = 0
        for p in queue:
            if n >= max_posts:
                break
            ch = chans.get(p["channel_key"])
            if not ch or not ch["enabled"] or ch["status"] != "live" or not ch["chat_id"]:
                continue
            tries = _attempts(p)
            if tries and (_parse(p["updated_at"]) or now) + datetime.timedelta(minutes=RETRY_MIN[min(tries - 1, 2)]) > now:
                continue
            if done_today.get(p["channel_key"], 0) >= config.TGNET_MAX_PER_DAY or (p["channel_key"] in last_post and now - last_post[p["channel_key"]] < datetime.timedelta(minutes=config.TGNET_MIN_GAP_MIN)):
                continue
            lst = get_listing(p["listing_key"])
            created = _parse((lst or {}).get("created_at"))
            if not lst or str(lst.get("active") or "yes").lower() == "no" or str(lst.get("archived") or "") == "yes" or (created and (now - created).days > config.TGNET_MAX_AGE_DAYS):
                _set(p, status="expired", error="განცხადება აქტიური აღარ არის ან ძალიან ძველია")
                rep["expired"] += 1
                continue
            try:
                res = publish_post(p, ch, lst, client, fetch)
            except cl.TgError as e:
                if e.code == 429:
                    rep["skipped"] = "Telegram: ზედმეტი მოთხოვნა — ციკლი გაჩერდა"
                    break
                tries += 1
                if tries >= MAX_ATTEMPTS:
                    _set(p, status="failed", error=f"ცდა {tries}/{MAX_ATTEMPTS}: {e}"[:380])
                    rep["failed"] += 1
                else:
                    _set(p, error=f"ცდა {tries}/{MAX_ATTEMPTS}: {e}"[:380])
                    rep["retry"] += 1
                continue
            except Exception as e:  # noqa: BLE001
                log.exception("TGNET: გამოქვეყნების მოულოდნელი შეცდომა (%s)", p["post_id"])
                _set(p, status="failed", error=f"მოულოდნელი შეცდომა: {type(e).__name__}"[:380])
                rep["failed"] += 1
                continue
            if res["status"] == "published":
                _set(p, status="published", message_ids=res["message_ids"], posted_at=now.strftime("%Y-%m-%d %H:%M"), error="")
                rep["published"] += 1
                n += 1
                last_post[p["channel_key"]] = now
                done_today[p["channel_key"]] = done_today.get(p["channel_key"], 0) + 1
            else:
                _set(p, status=res["status"], error=res["error"][:380])
    st.update_posts(changes)
    return rep


def _sync(posts, chans, client, now, rep, _set, max_ops: int = 6) -> None:
    """გამოქვეყნებული პოსტები: განცხადება გაუქმდა/დაარქივდა -> წაიშლება; ფასი/ტექსტი შეიცვალა -> წარწერა რედაქტირდება. ციკლში ≤6 ოპერაცია."""
    ops = 0
    for p in posts:
        if p["status"] != "published" or ops >= max_ops:
            continue
        ch = chans.get(p["channel_key"])
        ids, h = _ids(p)
        if not ch or not ids:
            continue
        lst = get_listing(p["listing_key"])
        r = None
        gone = (not lst) or str(lst.get("active") or "yes").lower() == "no" or str(lst.get("archived") or "") == "yes"
        try:
            if gone:
                for mid in ids:
                    try:
                        client.delete_message(ch["chat_id"], mid)
                    except cl.TgError as e:
                        if e.code == 429:
                            raise
                _set(p, status="removed", error="განცხადება გაუქმდა — პოსტი წაიშალა")
                rep["removed"] += 1
                ops += 1
            else:
                r = content.render(lst, ch["lang"], ch["channel_key"])
                if r["hash"] != h and not content.validate(r, lst):
                    client.edit_caption(ch["chat_id"], ids[0], r["text"])
                    _set(p, message_ids=json.dumps({"ids": ids, "h": r["hash"]}), error="")
                    rep["edited"] += 1
                    ops += 1
        except cl.TgError as e:
            if e.code == 429:
                raise
            if "message is not modified" in str(e) and r:
                _set(p, message_ids=json.dumps({"ids": ids, "h": r["hash"]}))
            else:
                log.warning("TGNET: სინქრონიზაცია ვერ მოხერხდა (%s): %s", p["post_id"], e)

def send_test(channel: dict, client: cl.Client, delete_after: int = 25, timer=None) -> dict:
    """ტესტ-პოსტი დირექტორის ღილაკიდან: ერთი ტექსტური შეტყობინება არხში (მკაფიოდ ნიშნავს „ტესტი“-ს) და წაშლა delete_after წამში. მხოლოდ „მზადაა“ არხზე."""
    import threading
    if channel.get("status") != "live" or not channel.get("chat_id"):
        raise cl.TgError("არხი ჯერ „მზადაა“ არ არის — ჯერ გაიარეთ შემოწმება")
    mid = client.send_message(channel["chat_id"], "🧪 <b>ტესტი</b> — ეს შეტყობინება თავისით წაიშლება (Safe Home Agency)")
    chat = channel["chat_id"]
    t = (timer or threading.Timer)(delete_after, lambda: _safe_delete(client, chat, mid))
    try:
        t.daemon = True
    except Exception:  # noqa: BLE001
        pass
    t.start()
    return {"message_id": mid, "delete_after": delete_after}


def _safe_delete(client, chat, mid) -> None:
    try:
        client.delete_message(chat, mid)
    except Exception:  # noqa: BLE001 — ტესტ-შეტყობინება თუ ვერ წაიშალა, არხში უვნებელი „ტესტი“ რჩება; ლოგში ჩანს
        log.warning("TGNET: ტესტ-შეტყობინება ვერ წაიშალა (%s/%s)", chat, mid, exc_info=True)


def preview(listing: dict, channel_langs=("ka", "en", "ru")) -> dict:
    """ტექსტის წინასწარი ნახვა 3 ენაზე (გაგზავნის გარეშე) + ვალიდატორის შედეგი — დირექტორი დამტკიცებამდე ხედავს, რა გამოქვეყნდება."""
    out = {}
    for lg in channel_langs:
        r = content.render(listing, lg)
        out[lg] = {"text": r["text"], "problems": content.validate(r, listing), "hash": r["hash"]}
    return {"langs": out, "photos": len(content.photos_of(listing))}
