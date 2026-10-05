"""
MyHome ანგარიშების დამატება/განახლება Mini App-იდან (ადმინის ფორმა) — კოდში/ფაილებში ქექვის გარეშე.

უსაფრთხოების მოდელი (მნიშვნელოვანია):
  * **email/პაროლი არასდროს ინახება** — არც Google Sheets-ში, არც GitHub-ზე, არც ლოგებში, არც AuditLog-ში.
    ფორმიდან მოსული მონაცემები სერვერის **მეხსიერებაში** (RAM) ინახება მხოლოდ რამდენიმე წუთით,
    სანამ ლოკალური worker (ცალკე კომპიუტერი) HTTPS-ით, თავისი API გასაღებით არ აიღებს და
    საკუთარ ლოკალურ `accounts.json`-ში არ ჩაიწერს. აღებისთანავე სერვერი მათ წაშლის;
    სერვერის გადატვირთვა ან ვადა (TTL) — ასევე წაშლის (მაშინ ფორმა თავიდან უნდა შეივსოს);
  * Sheets-ში იწერება მხოლოდ არასაიდუმლო ბმა: `team -> manager_label -> manager_name`
    (იგივე, რასაც ბოტის `/setmyhome` აკეთებდა);
  * ფორმა მხოლოდ **ადმინს** (ADMIN_CHAT_IDS) ეძლევა, არა თიმლიდერს;
  * AuditLog-ში იწერება მხოლოდ იარლიყი/თიმი და ფაქტი, რომ მონაცემები გადაეცა — არა მნიშვნელობები.
"""

from __future__ import annotations

import logging
import re
import threading
import time

from flask import jsonify, request

log = logging.getLogger("safehome-myhome-accounts")

PENDING_TTL_SECONDS = 15 * 60
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


class PendingVault:
    """მხოლოდ RAM. იარლიყი -> ავტორიზაციის მონაცემები + დროის ნიშნული. არასდროს იწერება დისკზე/ლოგში."""

    def __init__(self, ttl: int = PENDING_TTL_SECONDS):
        self._ttl = ttl
        self._items: dict[str, dict] = {}
        self._delivered: dict[str, float] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.time()
        for label in [k for k, v in self._items.items() if now - v["at"] > self._ttl]:
            self._items.pop(label, None)

    def put(self, label: str, creds: dict) -> None:
        with self._lock:
            self._expire()
            self._items[label] = {"creds": dict(creds), "at": time.time()}
            self._delivered.pop(label, None)

    def pending(self) -> list[dict]:
        with self._lock:
            self._expire()
            return [dict(v["creds"], manager_label=k) for k, v in self._items.items()]

    def ack(self, labels) -> int:
        n = 0
        with self._lock:
            for label in labels or []:
                if self._items.pop(str(label), None) is not None:
                    self._delivered[str(label)] = time.time()
                    n += 1
        return n

    def status(self, label: str) -> dict:
        with self._lock:
            self._expire()
            if label in self._items:
                return {"status": "pending"}
            if label in self._delivered:
                return {"status": "delivered", "delivered_at": int(self._delivered[label])}
            return {"status": "none"}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._delivered.clear()

    def __repr__(self) -> str:  # არასდროს გამოვაჩინოთ შიგთავსი ლოგში/დებაგში
        return f"<PendingVault items={len(self._items)}>"


vault = PendingVault()


def register(app, *, authed, authed_worker, audit, rate_limited, sheets, get_agents) -> None:
    """Flask app-ზე ამატებს ანგარიშების endpoint-ებს."""

    def _admin_only():
        agent, admin, err = authed()
        if err:
            return None, None, err
        if not admin:
            return None, None, (jsonify(error="მხოლოდ ადმინისთვის"), 403)
        return agent, admin, None

    def _no_store(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/api/myhome-accounts")
    @rate_limited("myhome_account")
    def myhome_accounts_list():
        agent, admin, err = _admin_only()
        if err:
            return err
        rows = []
        for r in sheets.get_myhome_accounts():
            label = str(r.get("manager_label", "")).strip()
            rows.append({
                "team": r.get("team", ""), "manager_label": label,
                "manager_name": r.get("manager_name", ""), "updated_at": r.get("updated_at", ""),
                "delivery": vault.status(label)["status"],
            })
        teams = sorted({str(a.get("team", "")).strip() for a in get_agents() if str(a.get("team", "")).strip()})
        return _no_store(jsonify(rows=rows, teams=teams))

    @app.get("/api/myhome-accounts/status")
    @rate_limited("myhome_account")
    def myhome_accounts_status():
        agent, admin, err = _admin_only()
        if err:
            return err
        label = str(request.args.get("label") or "").strip().lower()
        return _no_store(jsonify(vault.status(label)))

    @app.post("/api/myhome-accounts")
    @rate_limited("myhome_account")
    def myhome_accounts_save():
        agent, admin, err = _admin_only()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        team = str(body.get("team") or "").strip()
        label = str(body.get("manager_label") or "").strip().lower()
        manager_name = str(body.get("manager_name") or "").strip()[:80]
        email = str(body.get("email") or "").strip()
        password = str(body.get("password") or "")
        contact_name = str(body.get("contact_name") or "").strip()[:80]
        contact_number = str(body.get("contact_number") or "").strip()[:40]

        if not team or len(team) > 40:
            return jsonify(error="თიმი სავალდებულოა (მაქს. 40 სიმბოლო)"), 400
        if not LABEL_RE.match(label):
            return jsonify(error="იარლიყი: 3–40 სიმბოლო, მხოლოდ პატარა ლათინური ასოები/ციფრები/ტირე (მაგ. nino-account)"), 400
        has_creds = bool(email or password)
        if has_creds:
            if not EMAIL_RE.match(email):
                return jsonify(error="MyHome ელფოსტა არასწორია"), 400
            if not (4 <= len(password) <= 128):
                return jsonify(error="პაროლი: 4–128 სიმბოლო"), 400
            if not contact_name:
                return jsonify(error="საკონტაქტო სახელი სავალდებულოა"), 400
            if len(_digits(contact_number)) < 9:
                return jsonify(error="საკონტაქტო ნომერი არასწორია — მინიმუმ 9 ციფრი"), 400

        sheets.set_myhome_account(team, label, manager_name)
        if has_creds:
            vault.put(label, {"email": email, "password": password,
                              "contact_name": contact_name, "contact_number": contact_number})
        # AuditLog: მხოლოდ ფაქტი და არასაიდუმლო იარლიყი/თიმი — არასდროს email/პაროლი
        audit(agent, admin, "myhome_account_save", "myhome_account", label,
              metadata={"team": team, "credentials_sent": has_creds})
        log.info("MyHome ანგარიში შენახულია: label=%s team=%s credentials=%s", label, team, has_creds)
        return _no_store(jsonify(ok=True, manager_label=label, delivery="pending" if has_creds else "none"))

    # ------------------------------------------------------------------ worker-ისთვის
    @app.get("/internal/worker/pending-accounts")
    @rate_limited("worker")
    def worker_pending_accounts():
        err = authed_worker()
        if err:
            return err
        return _no_store(jsonify(accounts=vault.pending()))

    @app.post("/internal/worker/accounts-ack")
    @rate_limited("worker")
    def worker_accounts_ack():
        err = authed_worker()
        if err:
            return err
        labels = (request.get_json(silent=True) or {}).get("labels") or []
        n = vault.ack([str(x) for x in labels][:50])
        return _no_store(jsonify(ok=True, acked=n))
