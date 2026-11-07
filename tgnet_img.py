"""
TGNET: ბრენდირებული ფოტოს გამცემი `/img/b?u=<წყაროს ბმული>&s=<ხელმოწერა>` — ფოტო „SH“ იარლიყით (MyHome/ss.ge-ს ლოგოს ნაცვლად, tgnet_brand-ის პარამეტრებით).
გამოიყენება Mini App-ში და (თუ BRAND_PHOTOS_PROXY=1) ჩვენს კატალოგში (Property Hub): `listings_model.photo_list` ბმულებს აქ გადაამისამართებს.

უსაფრთხოება: ბმულს ხელს ვაწერთ (HMAC) — მხოლოდ ჩვენგან გაცემული ბმულები მუშაობს (ღია პროქსი არ ვართ); დომენი დაშვებულთა სიაშია (TGNET_PHOTO_HOSTS); ზომა/ტიპი მოწმდება;
შედეგი ინახება მეხსიერების ქეშში (ზომით შეზღუდული) და ბრაუზერისთვის Cache-Control-ით. გამორთულია, სანამ BRAND_PHOTOS_PROXY=0 (ამ შემთხვევაში ბმულები უცვლელია).
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import logging
import threading
from urllib.parse import quote

import config
import tgnet_publisher as pub

log = logging.getLogger("safehome-tgnet-img")
_cache: "collections.OrderedDict[str, bytes]" = collections.OrderedDict()
_cache_bytes = 0
_lock = threading.Lock()
CACHE_MAX_BYTES = 60 * 1024 * 1024


def _key() -> bytes:
    return (config.TELEGRAM_BOT_TOKEN or "tgnet-dev").encode()


def sign(url: str) -> str:
    return hmac.new(_key(), b"img:" + url.encode(), hashlib.sha256).hexdigest()[:24]


def proxy_url(url: str) -> str:
    return f"/img/b?u={quote(url, safe='')}&s={sign(url)}"


def maybe_proxy(url: str) -> str:
    """BRAND_PHOTOS_PROXY=1 და დომენი დაშვებულია -> ბრენდირებული ბმული; სხვა შემთხვევაში ორიგინალი (არაფერი ირღვევა)."""
    if not getattr(config, "BRAND_PHOTOS_PROXY", False) or not pub.allowed_photo_url(url):
        return url
    return proxy_url(url)


def serve(url: str, sig: str, fetch=None, brand=None) -> tuple[bytes | None, int]:
    """აბრუნებს (jpeg ბაიტები | None, HTTP სტატუსი)."""
    global _cache_bytes
    if not url or not hmac.compare_digest(str(sig or ""), sign(url)):
        return None, 403
    if not pub.allowed_photo_url(url):
        return None, 403
    with _lock:
        if url in _cache:
            _cache.move_to_end(url)
            return _cache[url], 200
    try:
        raw = (fetch or pub.download_photo)(url)
        out = (brand or pub.brand_photo)(raw)
    except Exception as e:  # noqa: BLE001
        log.info("TGNET img: %s ვერ მოვამზადეთ: %s", url[:80], e)
        return None, 502
    with _lock:
        _cache[url] = out
        _cache_bytes += len(out)
        while _cache_bytes > CACHE_MAX_BYTES and _cache:
            _, v = _cache.popitem(last=False)
            _cache_bytes -= len(v)
    return out, 200
