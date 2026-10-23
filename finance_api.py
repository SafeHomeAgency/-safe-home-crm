"""
ფინანსური ტრეკერი — HTTP API (`/api/finance/...`). ხელმისაწვდომია **მხოლოდ** `config.FINANCE_CHAT_IDS`-ში მითითებული
Telegram ID-ებისთვის (ადმინებიც კი ვერ ხედავენ, თუ სიაში არ არიან). უფლება მოწმდება სერვერზე ყოველ მოთხოვნაზე; სხვას 403.

ახალი endpoint-ებია; არსებულებს არ ცვლის. webserver.py მხოლოდ `finance_api.register(app, ...)`-ს უმატებს.
პერსონალური მონაცემები (პირადი №, ტელეფონი) AuditLog-ში არასდროს იწერება — მხოლოდ ID-ები და თანხები.
"""

from __future__ import annotations

import datetime
import functools
import logging

from flask import jsonify, request

import config
import finance_model as m
import finance_store as store
from finance_model import FinanceError

log = logging.getLogger("safehome-finance-api")


def register(app, *, authed, audit, rate_limited, get_agents, chat_id_fn, send_document) -> None:
    """authed() -> (agent, admin, err); audit(agent, admin, action, entity_type, entity_id, metadata=...);
    chat_id_fn() -> მიმდინარე მომხმარებლის Telegram ID; send_document(chat_id, filename, bytes, caption) -> bool."""

    def _allowed(chat) -> bool:
        return chat is not None and int(chat) in config.FINANCE_CHAT_IDS

    def _guard(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            agent, admin, err = authed()
            if err:
                return err
            chat = chat_id_fn()
            if not _allowed(chat):
                return jsonify(error="ფინანსურ ტაბზე წვდომა არ გაქვთ", code="finance_forbidden"), 403
            try:
                return fn(agent, admin, chat, *a, **kw)
            except FinanceError as e:
                return jsonify(error=str(e)), e.status
            except Exception:  # noqa: BLE001
                log.exception("finance API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    def _range():
        today = store.today_local()
        to = request.args.get("to") or m.month_of(today)
        frm = request.args.get("from") or m.month_of(m.add_months(today.replace(day=1), -11))
        frm, to = m.parse_month(frm, "საწყისი თვე"), m.parse_month(to, "ბოლო თვე")
        if frm > to:
            raise FinanceError("საწყისი თვე ბოლოს უნდა უსწრებდეს")
        if len(m.month_range(frm, to)) > 60:
            raise FinanceError("პერიოდი მაქსიმუმ 60 თვეა")
        return frm, to

    def _agent_fields(data: dict) -> dict:
        """აგენტის სახელი სერვერზე ივსება agent_id-დან (კლიენტის გამოგზავნილ სახელს არ ვენდობით)."""
        data = dict(data or {})
        aid = str(data.get("agent_id") or "").strip()
        if aid:
            a = next((x for x in get_agents() if str(x.get("agent_id")) == aid), None)
            if not a:
                raise FinanceError("აგენტი ვერ მოიძებნა")
            data["agent_name"] = str(a.get("name", ""))
        return data

    # ------------------------------------------------------------------ წვდომა (ტაბის ჩვენებისთვის)
    @app.get("/api/finance/access")
    @rate_limited("finance_read")
    def finance_access():
        agent, admin, err = authed()
        if err:
            return err
        chat = chat_id_fn()
        if _allowed(chat):
            return jsonify(allowed=True)
        # სანამ FINANCE_CHAT_IDS საერთოდ არ არის დაყენებული, ადმინს ვაჩვენებთ ინსტრუქციას თავისი Telegram ID-ით
        if admin and not config.FINANCE_CHAT_IDS:
            return jsonify(allowed=False, setup=True, your_id=chat)
        return jsonify(allowed=False)

    # ------------------------------------------------------------------ დაშბორდი
    @app.get("/api/finance/dashboard")
    @rate_limited("finance_read")
    @_guard
    def finance_dashboard(agent, admin, chat):
        frm, to = _range()
        today = store.today_local()
        agents = [{"agent_id": str(a.get("agent_id")), "name": a.get("name", ""), "team": a.get("team", ""), "role": a.get("role", "")}
                  for a in get_agents() if str(a.get("active", "yes")).strip().lower() not in ("no", "false", "0")]
        agents.sort(key=lambda a: a["name"])
        rem = store.reminders(today)
        return jsonify(
            summary=store.summary(frm, to), reminders=rem,
            lookups={"agents": agents, "property_types": m.PROPERTY_TYPES, "expense_categories": m.EXPENSE_CATEGORIES,
                     "currencies": list(m.CURRENCIES)},
            usd_rate=(float(store.usd_rate()) if store.usd_rate() else None), today=today.isoformat(),
            month=m.month_of(today), range={"from": frm, "to": to})

    # ------------------------------------------------------------------ გარიგებები
    def _deal_public(d: dict, full: bool = False) -> dict:
        keys = [k for k in m.DEAL_HEADERS if k not in ("expiry_reminder_60", "expiry_reminder_30", "report_notified",
                                                         "last_report_reminder", "created_by")]
        out = {k: d.get(k, "") for k in keys}
        if not full:
            # სიაში პირადი ნომრები/ტელეფონები არ გადადის (მხოლოდ დეტალში)
            for k in ("recipient_pid", "client_pid", "recipient_phone", "client_phone", "cadastral_code", "notes"):
                out.pop(k, None)
        return out

    @app.get("/api/finance/deals")
    @rate_limited("finance_read")
    @_guard
    def finance_deals(agent, admin, chat):
        frm, to = _range()
        q = (request.args.get("q") or "").strip().lower()
        aid = (request.args.get("agent_id") or "").strip()
        rows = [d for d in store.list_deals() if frm <= str(d.get("month")) <= to]
        if aid:
            rows = [d for d in rows if str(d.get("agent_id")) == aid]
        ptype, cur, expf = [(request.args.get(k) or "").strip() for k in ("ptype", "cur", "exp")]
        if ptype:
            rows = [d for d in rows if str(d.get("property_type")) == ptype]
        if cur:
            rows = [d for d in rows if str(d.get("currency") or "GEL") == cur]
        if expf in ("soon", "expired", "none"):
            today = store.today_local()

            def _left(d):
                e = m.parse_date(d.get("contract_expiry"), required=False)
                return None if not e else (e - today).days
            rows = [d for d in rows if (_left(d) is None) == (expf == "none")
                    and (expf == "none" or (expf == "expired" and _left(d) < 0) or (expf == "soon" and 0 <= _left(d) <= 60))]
        if q:
            # ძებნა ყველა შეყვანილ ველზე (ტელეფონი/პირადი № — ციფრებით, ფორმატის მიუხედავად); შედეგში პირადი მონაცემი მაინც არ გადადის
            qd = "".join(ch for ch in q if ch.isdigit())
            text_keys = ("invoice_no", "date", "provider", "property_type", "recipient", "cadastral_code", "district", "address",
                         "agent_name", "team_leader", "contract_expiry", "client_name", "notes", "currency", "value", "commission")
            digit_keys = ("recipient_phone", "recipient_pid", "client_phone", "client_pid")

            def _hit(d):
                if q in " ".join(str(d.get(k, "")) for k in text_keys + digit_keys).lower():
                    return True
                return bool(len(qd) >= 3 and any(qd in "".join(ch for ch in str(d.get(k, "")) if ch.isdigit()) for k in digit_keys))
            rows = [d for d in rows if _hit(d)]
        rows.sort(key=lambda d: (str(d.get("date")), str(d.get("created_at"))), reverse=True)
        return jsonify(rows=[_deal_public(d) for d in rows[:400]], count=len(rows))

    @app.get("/api/finance/deals/<deal_id>")
    @rate_limited("finance_read")
    @_guard
    def finance_deal(agent, admin, chat, deal_id):
        d = store.get_deal(deal_id, fresh=True)
        if not d or str(d.get("status")) == m.DEAL_DELETED:
            raise FinanceError("გარიგება ვერ მოიძებნა", 404)
        return jsonify(deal=_deal_public(d, full=True))

    @app.post("/api/finance/deals")
    @rate_limited("finance_write")
    @_guard
    def finance_deal_create(agent, admin, chat):
        row = store.create_deal(_agent_fields(request.get_json(silent=True)), chat)
        audit(agent, admin, "finance_deal_create", "finance_deal", row["deal_id"],
              metadata={"invoice": row["invoice_no"], "commission": row["commission"], "company": row["company_income"]})
        return jsonify(ok=True, deal=_deal_public(row, full=True)), 201

    @app.put("/api/finance/deals/<deal_id>")
    @rate_limited("finance_write")
    @_guard
    def finance_deal_update(agent, admin, chat, deal_id):
        row = store.update_deal(deal_id, _agent_fields(request.get_json(silent=True)), chat)
        audit(agent, admin, "finance_deal_update", "finance_deal", deal_id,
              metadata={"invoice": row.get("invoice_no"), "commission": row.get("commission"), "company": row.get("company_income")})
        return jsonify(ok=True, deal=_deal_public(row, full=True))

    @app.delete("/api/finance/deals/<deal_id>")
    @rate_limited("finance_write")
    @_guard
    def finance_deal_delete(agent, admin, chat, deal_id):
        row = store.delete_deal(deal_id, chat)
        audit(agent, admin, "finance_deal_delete", "finance_deal", deal_id, metadata={"invoice": row.get("invoice_no")})
        return jsonify(ok=True)

    @app.post("/api/finance/deals/<deal_id>/report-done")
    @rate_limited("finance_write")
    @_guard
    def finance_report_done(agent, admin, chat, deal_id):
        store.mark_report_done(deal_id)
        audit(agent, admin, "finance_report_done", "finance_deal", deal_id)
        return jsonify(ok=True)

    # ------------------------------------------------------------------ ხარჯები
    @app.get("/api/finance/expenses")
    @rate_limited("finance_read")
    @_guard
    def finance_expenses(agent, admin, chat):
        frm, to = _range()
        months = set(m.month_range(frm, to))
        rows = [e for e in store.list_expenses() if any(store._expense_in_month(e, mo) for mo in months)]
        rows.sort(key=lambda e: (str(e.get("date")), str(e.get("created_at"))), reverse=True)
        return jsonify(rows=[{k: e.get(k, "") for k in m.EXPENSE_HEADERS if k != "created_by"} for e in rows[:500]], count=len(rows))

    @app.post("/api/finance/expenses")
    @rate_limited("finance_write")
    @_guard
    def finance_expense_create(agent, admin, chat):
        row = store.create_expense(request.get_json(silent=True) or {}, chat)
        audit(agent, admin, "finance_expense_create", "finance_expense", row["expense_id"],
              metadata={"category": row["category"], "amount": row["amount"]})
        return jsonify(ok=True, expense=row), 201

    @app.put("/api/finance/expenses/<expense_id>")
    @rate_limited("finance_write")
    @_guard
    def finance_expense_update(agent, admin, chat, expense_id):
        row = store.update_expense(expense_id, request.get_json(silent=True) or {}, chat)
        audit(agent, admin, "finance_expense_update", "finance_expense", expense_id,
              metadata={"category": row.get("category"), "amount": row.get("amount")})
        return jsonify(ok=True, expense=row)

    @app.delete("/api/finance/expenses/<expense_id>")
    @rate_limited("finance_write")
    @_guard
    def finance_expense_delete(agent, admin, chat, expense_id):
        store.delete_expense(expense_id, chat)
        audit(agent, admin, "finance_expense_delete", "finance_expense", expense_id)
        return jsonify(ok=True)

    # ------------------------------------------------------------------ პარამეტრები / ექსპორტი
    @app.post("/api/finance/settings")
    @rate_limited("finance_write")
    @_guard
    def finance_settings(agent, admin, chat):
        data = request.get_json(silent=True) or {}
        rate = store.set_usd_rate(data.get("usd_rate"), chat)
        audit(agent, admin, "finance_settings", "finance_settings", "usd_rate", metadata={"usd_rate": str(rate or "")})
        return jsonify(ok=True, usd_rate=(float(rate) if rate else None))

    @app.get("/api/finance/export")
    @rate_limited("export")
    @_guard
    def finance_export(agent, admin, chat):
        kind = (request.args.get("kind") or "deals").strip()
        if kind not in ("deals", "expenses"):
            raise FinanceError("ექსპორტის ტიპი არასწორია")
        frm, to = _range()
        if kind == "deals":
            rows = [d for d in store.list_deals() if frm <= str(d.get("month")) <= to]
        else:
            months = set(m.month_range(frm, to))
            rows = [e for e in store.list_expenses() if any(store._expense_in_month(e, mo) for mo in months)]
        rows.sort(key=lambda r: str(r.get("date")))
        data = store.to_csv(kind, rows)
        name = f"finance_{kind}_{frm}_{to}.csv"
        ok = send_document(chat, name, data, f"{'გარიგებები' if kind == 'deals' else 'ხარჯები'} {frm} — {to} ({len(rows)} ჩანაწერი)")
        audit(agent, admin, "finance_export", "finance_export", kind, metadata={"rows": len(rows), "from": frm, "to": to})
        if not ok:
            raise FinanceError("ფაილის გაგზავნა Telegram-ში ვერ მოხერხდა", 502)
        return jsonify(ok=True, rows=len(rows))
