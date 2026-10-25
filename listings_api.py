"""
Safe Home Property Hub — HTTP API (`/api/listings...`). ახალი endpoint-ებია; არსებულებს არ ცვლის. webserver.py მხოლოდ
`listings_api.register(app, ...)`-ს უმატებს და /complete-ში ერთ try/except ხაზს (`listings_api.on_job_finished`).

წვდომა: ნებისმიერ რეგისტრირებულ აგენტს/თიმლიდერს/ადმინს (initData). პასუხში შიდა ველები (მესაკუთრის ნომერი, შენიშვნები, job/წყაროს ID)
**სერვერზე** ამოიღება, თუ მომხმარებელი არ არის განცხადების მფლობელი, იმავე გუნდის თიმლიდერი ან ადმინი.
ფერები/ზღვრები ითვლება სერვერზე (listings_model). ბრაუზერიდან მოსულ agent_id/role/team-ს არავის ვენდობით.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify, request

import listings_model as m
import listings_store as store
from listings_model import ListingError

log = logging.getLogger("safehome-listings-api")


def parse_filters(args=None) -> dict:
    a = args if args is not None else request.args
    g = lambda k: (a.get(k) or "").strip()  # noqa: E731

    def fl(k):
        v = g(k)
        try:
            return float(v.replace(",", ".")) if v else None
        except ValueError:
            return None

    def it(k, d):
        try:
            return int(g(k) or d)
        except ValueError:
            return d

    return {
        "q": g("q")[:80], "city": g("city")[:60], "district": g("district")[:80], "deal_type": g("deal_type")[:40],
        "property_type": g("property_type")[:40], "condition": g("condition")[:60], "agent_id": g("agent_id")[:40],
        "mine": g("mine") in ("1", "true", "yes"),
        "price_min": fl("price_min"), "price_max": fl("price_max"), "area_min": fl("area_min"), "area_max": fl("area_max"),
        "rooms": [t.strip() for t in g("rooms").split(",") if t.strip()][:8], "bedrooms_min": fl("bedrooms_min"),
        "freshness": [t.strip() for t in g("freshness").split(",") if t.strip()][:4],
        "sort": g("sort") if g("sort") in ("new", "price_asc", "price_desc", "area_desc") else "new",
        "page": it("page", 1), "per_page": it("per_page", 24),
    "include_inactive": g("inactive") in ("1", "true", "yes"),
    "ids": [x.strip() for x in g("ids").split(",") if x.strip()][:100],
    }


def viewer_of(agent, admin: bool) -> dict:
    agent = agent or {}
    return {"agent_id": str(agent.get("agent_id") or ""), "role": str(agent.get("role") or "").strip(),
            "team": str(agent.get("team") or "").strip(), "admin": bool(admin)}


def on_job_finished(job_row: dict, snapshot) -> None:
    """webserver /complete-დან (წარმატებული დასრულებისას/ss.ge-ნაწილის ჩავარდნისას): კატალოგში ჩანაწერის შენახვა.
    ნებისმიერი შეცდომა ჩაიყლაპება — ატვირთვის შედეგის დაფიქსირებას ეს არასდროს აფერხებს."""
    try:
        store.upsert_from_job(job_row or {}, snapshot)
    except Exception:  # noqa: BLE001
        log.exception("Property Hub: ჩანაწერის შენახვა ვერ მოხერხდა (job %s)", (job_row or {}).get("job_id"))


def register(app, *, authed, audit, rate_limited, get_jobs, interest=None) -> None:
    """authed() -> (agent, admin, err); audit(agent, admin, action, entity_type, entity_id, metadata=...); get_jobs() -> MyHomeJobs სტრიქონები; interest() -> {listing_id: შეხვედრების რაოდენობა} ("ცხელი ბინის" ნიშნისთვის)."""

    def _interest():
        try:
            return interest() if interest else {}
        except Exception:  # noqa: BLE001
            log.exception("Property Hub: დაინტერესების რაოდენობა ვერ ჩაიტვირთა")
            return {}

    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            try:
                return fn(agent, admin, *a, **kw)
            except ListingError as e:
                return jsonify(error=str(e)), e.status
            except Exception:  # noqa: BLE001
                log.exception("listings API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    @app.get("/api/listings")
    @rate_limited("listings_read")
    @_guard
    def listings_list(agent, admin):
        res = store.query(parse_filters(), viewer_of(agent, admin))
        ic = _interest()
        for it in res["items"]:
            it["interest"] = ic.get(it["listing_id"], 0)
        return jsonify(res)

    @app.get("/api/listings/map")
    @rate_limited("listings_read")
    @_guard
    def listings_map(agent, admin):
        return jsonify(store.map_points(parse_filters(), viewer_of(agent, admin)))

    @app.get("/api/listings/insights")
    @rate_limited("listings_read")
    @_guard
    def listings_insights(agent, admin):
        return jsonify(store.insights(viewer_of(agent, admin)))

    @app.post("/api/listings/<listing_id>/verify")
    @rate_limited("listings_write")
    @_guard
    def listings_verify(agent, admin, listing_id):
        res = store.verify(listing_id, viewer_of(agent, admin))
        audit(agent, admin, "listing_verify", "listing", listing_id)
        return jsonify(ok=True, **res)

    @app.post("/api/listings/<listing_id>/status")
    @rate_limited("listings_write")
    @_guard
    def listings_status(agent, admin, listing_id):
        body = request.get_json(silent=True) or {}
        if "active" not in body:
            raise ListingError("active საჭიროა")
        res = store.set_active(listing_id, viewer_of(agent, admin), bool(body.get("active")))
        audit(agent, admin, "listing_status", "listing", listing_id, metadata={"active": res["active"]})
        return jsonify(ok=True, **res)

    @app.get("/api/listings/<listing_id>")
    @rate_limited("listings_read")
    @_guard
    def listings_one(agent, admin, listing_id):
        row = store.get_one(listing_id, viewer_of(agent, admin))
        if not row:
            raise ListingError("განცხადება ვერ მოიძებნა", 404)
        row["interest"] = _interest().get(row["listing_id"], 0)
        return jsonify(listing=row)

    @app.post("/api/listings/backfill")
    @rate_limited("listings_write")
    @_guard
    def listings_backfill(agent, admin):
        if not admin:
            raise ListingError("მხოლოდ ადმინისთვის", 403)
        res = store.backfill_from_jobs(get_jobs())
        audit(agent, admin, "listings_backfill", "listings", "", metadata=res)
        return jsonify(ok=True, **res)

    @app.post("/api/listings/<listing_id>/flags")
    @rate_limited("listings_write")
    @_guard
    def listings_flags(agent, admin, listing_id):
        if not admin:
            raise ListingError("მხოლოდ ადმინისთვის", 403)
        body = request.get_json(silent=True) or {}
        flags = {k: bool(body[k]) for k in ("active", "archived") if k in body}
        if not flags:
            raise ListingError("active ან archived საჭიროა")
        row = store.set_flags(listing_id, **flags)
        if row is None:
            raise ListingError("განცხადება ვერ მოიძებნა", 404)
        audit(agent, admin, "listings_flags", "listing", listing_id, metadata=flags)
        return jsonify(ok=True)
