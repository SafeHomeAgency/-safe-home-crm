"""
Property Hub — პარამეტრები და პირადი სია: ფავორიტები (სერვერზე — ყველა მოწყობილობაზე ერთნაირი), სიახლის ზღვრები (ადმინის პანელიდან),
CSV ექსპორტი (ადმინი -> Telegram-ში ფაილად). ახალი ცხრილები: `HubFavs`, `HubSettings`. არსებულს არაფერს ცვლის.

ზღვრები: Railway-ს ცვლადები (HUB_*_DAYS) რჩება ნაგულისხმევად; ადმინის შენახული მნიშვნელობა მათ გადაფარავს (listings_model.set_threshold_provider).
"""

from __future__ import annotations

import csv
import datetime
import functools
import io
import logging
import threading

from flask import jsonify, request

import contracts_store as _cs
import hubmeet_model as mm
import hubmeet_store as mstore
import listings_model as lm
import listings_store as lstore
from listings_api import viewer_of

log = logging.getLogger("safehome-hubprefs")
_lock = threading.RLock()

FAVS_SHEET, SETTINGS_SHEET = "HubFavs", "HubSettings"
FAV_HEADERS = ["fav_id", "agent_id", "listing_id", "on", "updated_at"]
SET_HEADERS = ["key", "value", "updated_at", "updated_by"]
ALL_TABS = [(FAVS_SHEET, FAV_HEADERS, 3000), (SETTINGS_SHEET, SET_HEADERS, 50)]
MAX_FAVS = 200


class PrefError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class SheetsBackend(_cs.SheetsBackend):
    def ensure(self) -> None:
        if self._ready:
            return
        sg = self._sg()
        ss = sg._get_spreadsheet()
        existing = {ws.title: ws for ws in ss.worksheets()}
        for name, headers, rows in ALL_TABS:
            sg._ensure_one_sheet(ss, existing, name, headers, rows)
        self._ready = True


class MemoryBackend(_cs.MemoryBackend):
    def ensure(self) -> None:
        for name, _h, _r in ALL_TABS:
            self.tables.setdefault(name, [])


_backend = SheetsBackend()


def set_backend(b) -> None:
    global _backend
    _backend = b


def _s(v, cap: int = 200) -> str:
    return str(v if v is not None else "").strip()[:cap]


# ====================================================================== ფავორიტები
def favs_of(agent_id: str) -> list[str]:
    aid = _s(agent_id, 40)
    if not aid:
        return []
    rows = [r for r in _backend.read(FAVS_SHEET) if _s(r.get("agent_id")) == aid and _s(r.get("on")) == "yes"]
    rows.sort(key=lambda r: _s(r.get("updated_at")), reverse=True)
    return [_s(r.get("listing_id")) for r in rows][:MAX_FAVS]


def set_fav(agent_id: str, listing_id: str, on: bool) -> bool:
    aid, lid = _s(agent_id, 40), _s(listing_id, 40)
    if not aid:
        raise PrefError("მხოლოდ რეგისტრირებული აგენტისთვის", 403)
    if not lid:
        raise PrefError("listing_id საჭიროა")
    key = f"{aid}|{lid}"
    now = mstore.now_str()
    with _lock:
        rows = _backend.read(FAVS_SHEET, fresh=True)
        ex = next((r for r in rows if _s(r.get("fav_id")) == key), None)
        if on and sum(1 for r in rows if _s(r.get("agent_id")) == aid and _s(r.get("on")) == "yes") >= MAX_FAVS and not (ex and _s(ex.get("on")) == "yes"):
            raise PrefError(f"ფავორიტების მაქსიმუმია {MAX_FAVS}")
        if ex:
            _backend.update(FAVS_SHEET, FAV_HEADERS, key, {"on": "yes" if on else "no", "updated_at": now})
        elif on:
            _backend.append(FAVS_SHEET, FAV_HEADERS, {"fav_id": key, "agent_id": aid, "listing_id": lid, "on": "yes", "updated_at": now})
    return on


# ====================================================================== ზღვრები
def get_thresholds_override() -> dict:
    out = {}
    for r in _backend.read(SETTINGS_SHEET):
        k = _s(r.get("key"))
        if k in ("fresh", "mid", "stale"):
            try:
                out[k] = int(float(_s(r.get("value"))))
            except ValueError:
                pass
    return out


def set_thresholds(fresh, mid, stale, actor: str = "") -> dict:
    try:
        f, mi, st = int(float(str(fresh))), int(float(str(mid))), int(float(str(stale)))
    except (TypeError, ValueError):
        raise PrefError("ზღვრები რიცხვები უნდა იყოს") from None
    if not (1 <= f < mi < st <= 365):
        raise PrefError("უნდა სრულდებოდეს: 1 ≤ ახალი < საშუალო < ძველი ≤ 365 დღე")
    now = mstore.now_str()
    with _lock:
        rows = _backend.read(SETTINGS_SHEET, fresh=True)
        for k, v in (("fresh", f), ("mid", mi), ("stale", st)):
            data = {"key": k, "value": str(v), "updated_at": now, "updated_by": _s(actor, 60)}
            if any(_s(r.get("key")) == k for r in rows):
                _backend.update(SETTINGS_SHEET, SET_HEADERS, k, data)
            else:
                _backend.append(SETTINGS_SHEET, SET_HEADERS, data)
    lm.invalidate_thresholds()
    return {"fresh": f, "mid": mi, "stale": st}


def install_provider() -> None:
    """listings_model.thresholds() ამ პროვაიდერით ადმინის მნიშვნელობებს იყენებს (ვარდნისას — ნაგულისხმევი)."""
    lm.set_threshold_provider(get_thresholds_override)


# ====================================================================== CSV ექსპორტი
def _cell(v) -> str:
    t = str(v if v is not None else "")
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t     # ფორმულის ინექციისგან დაცვა


def export_csv(kind: str) -> tuple[str, bytes, int]:
    if kind == "listings":
        headers, rows, name = lm.LISTING_HEADERS, lstore.all_rows(fresh=True), "listings"
    elif kind == "meetings":
        headers, rows, name = mm.HM_HEADERS, mstore.all_rows(fresh=True), "hub_meetings"
    else:
        raise PrefError("kind: listings ან meetings")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([_cell(r.get(h, "")) for h in headers])
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return f"safehome_{name}_{stamp}.csv", ("﻿" + buf.getvalue()).encode("utf-8"), len(rows)


# ====================================================================== API
def register(app, *, authed, audit, rate_limited, chat_id_fn, send_document) -> None:
    install_provider()

    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                return fn(agent, admin, *a, **kw)
            except PrefError as e:
                return jsonify(error=str(e)), e.status
            except Exception:  # noqa: BLE001
                log.exception("hub prefs API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    @app.get("/api/hub/favs")
    @rate_limited("hub_read")
    @_guard
    def hub_favs(agent, admin):
        return jsonify(ids=favs_of((agent or {}).get("agent_id")))

    @app.post("/api/hub/favs")
    @rate_limited("hub_write")
    @_guard
    def hub_fav_set(agent, admin):
        body = request.get_json(silent=True) or {}
        on = set_fav((agent or {}).get("agent_id"), body.get("listing_id"), bool(body.get("on")))
        return jsonify(ok=True, on=on)

    @app.get("/api/hub/settings")
    @rate_limited("hub_read")
    @_guard
    def hub_settings(agent, admin):
        return jsonify(thresholds=lm.thresholds(), can_edit=bool(admin), env_defaults=lm.env_thresholds())

    @app.post("/api/hub/settings")
    @rate_limited("hub_write")
    @_guard
    def hub_settings_save(agent, admin):
        if not admin:
            raise PrefError("მხოლოდ ადმინისთვის", 403)
        b = request.get_json(silent=True) or {}
        res = set_thresholds(b.get("fresh"), b.get("mid"), b.get("stale"), (agent or {}).get("name") or "admin")
        audit(agent, admin, "hub_settings", "hub_settings", "", metadata=res)
        return jsonify(ok=True, thresholds=lm.thresholds())

    @app.post("/api/hub/export")
    @rate_limited("hub_write")
    @_guard
    def hub_export(agent, admin):
        if not admin:
            raise PrefError("მხოლოდ ადმინისთვის", 403)
        kind = str((request.get_json(silent=True) or {}).get("kind") or "").strip()
        fname, content, n = export_csv(kind)
        chat = chat_id_fn()
        if not chat or not send_document(chat, fname, content, f"📄 Property Hub ექსპორტი: {n} ჩანაწერი"):
            raise PrefError("ფაილის გაგზავნა Telegram-ში ვერ მოხერხდა", 502)
        audit(agent, admin, "hub_export", "hub_export", kind, metadata={"rows": n})
        return jsonify(ok=True, rows=n)
