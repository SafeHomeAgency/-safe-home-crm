"""
TGNET ეტაპი 3: CRM-თან შეერთება. `listings_api.NEW_LISTING_HOOKS`-ით (არსებული გაფართოების წერტილი — listings_api არ იცვლება) ახალი განცხადება, რომელზეც აგენტმა
„Telegram-ზეც გამოქვეყნება“ თიქი მონიშნა, ექცევა რიგში (TgPosts). **არაფერი იგზავნება.** გამორთულია, სანამ TGNET_QUEUE_ENABLED=0.
ნებისმიერი შეცდომა ჩაიყლაპება (listings_api თავადაც იცავს თავს) — განცხადების ატვირთვას ეს არასდროს აფერხებს.
"""

from __future__ import annotations

import logging

import config
import tgnet_model as m
import tgnet_store as st

log = logging.getLogger("safehome-tgnet")


def on_new_listing(rec: dict) -> None:
    if not config.TGNET_QUEUE_ENABLED:
        return
    if not m.opted_in((rec or {}).get("notes")):
        return                                           # აგენტს თიქი არ მოუნიშნავს — არაფერს ვაკეთებთ (ნაგულისხმევად არ ვაქვეყნებთ)
    try:
        res = st.enqueue_listing(rec)
        log.info("TGNET: %s -> %s (%s)", (rec or {}).get("listing_id"), res.get("status"), "; ".join(res.get("reasons") or []))
    except Exception:  # noqa: BLE001
        log.exception("TGNET: განცხადების რიგში დამატება ვერ მოხერხდა (%s)", (rec or {}).get("listing_id"))


def register_hook() -> None:
    import listings_api
    if on_new_listing not in listings_api.NEW_LISTING_HOOKS:
        listings_api.NEW_LISTING_HOOKS.append(on_new_listing)
