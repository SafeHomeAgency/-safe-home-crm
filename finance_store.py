"""
ფინანსური ტრეკერი — შენახვა (Google Sheets) და ბიზნეს-ლოგიკა: გარიგებები, ხარჯები, დაშბორდის შეჯამება, შეხსენებები.

სტრუქტურა contracts_store.py-ს იმეორებს: ცხრილები ზარმაცად იქმნება (არსებულებს არ ეხება), ყველა ჩაწერა ერთ პროცესულ
ბლოკირებაში (`_lock`) და ახლად წაკითხული მონაცემებით. წაშლა **რბილია** (status="deleted") — ისტორია არ იკარგება.
ბექენდი ტესტში იცვლება `MemoryBackend`-ით (`set_backend`).
"""

from __future__ import annotations

import csv
import datetime
import io
import logging
import threading
from decimal import Decimal

import contracts_store as _cs
import finance_model as m
from finance_model import FinanceError

log = logging.getLogger("safehome-finance")
_lock = threading.RLock()


# ====================================================================== შენახვის ფენები
class SheetsBackend(_cs.SheetsBackend):
    """იგივე Sheets-ის ფენა, ოღონდ ფინანსური ცხრილებისთვის."""

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


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _int(v, default=0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def today_local() -> datetime.date:
    import crm_time
    return crm_time.local_today()


def now_str() -> str:
    import crm_time
    return crm_time.local_now().strftime("%Y-%m-%d %H:%M")


# ====================================================================== პარამეტრები (დოლარის კურსი)
def get_settings() -> dict:
    return {_s(r.get("key")): _s(r.get("value")) for r in _backend.read(m.SETTINGS_SHEET) if _s(r.get("key"))}


def set_setting(key: str, value: str, actor: str = "") -> None:
    with _lock:
        rows = _backend.read(m.SETTINGS_SHEET, fresh=True)
        data = {"key": key, "value": str(value), "updated_at": now_str(), "updated_by": str(actor)}
        if any(_s(r.get("key")) == key for r in rows):
            _backend.update(m.SETTINGS_SHEET, m.SETTINGS_HEADERS, key, data)
        else:
            _backend.append(m.SETTINGS_SHEET, m.SETTINGS_HEADERS, data)


def usd_rate() -> Decimal | None:
    v = m.D(get_settings().get("usd_rate", ""), default=None)
    return v if v and v > 0 else None


def set_usd_rate(value, actor: str = "") -> Decimal | None:
    v = m.D(value, default=None)
    if v is None:
        set_setting("usd_rate", "", actor)
        return None
    if v <= 0 or v > 100:
        raise FinanceError("დოლარის კურსი არასწორია")
    set_setting("usd_rate", format(v.normalize(), "f"), actor)
    return v


# ====================================================================== გარიგებები (ინვოისები)
def list_deals(include_deleted: bool = False, fresh: bool = False) -> list[dict]:
    rows = _backend.read(m.DEALS_SHEET, fresh=fresh)
    return rows if include_deleted else [r for r in rows if _s(r.get("status")) != m.DEAL_DELETED]


def get_deal(deal_id: str, fresh: bool = False) -> dict | None:
    return next((r for r in _backend.read(m.DEALS_SHEET, fresh=fresh) if _s(r.get("deal_id")) == _s(deal_id)), None)


def _next_invoice_no(date: datetime.date, taken: set) -> str:
    prefix = f"INV-{date.year:04d}{date.month:02d}-"
    n = sum(1 for t in taken if t.startswith(prefix)) + 1
    while f"{prefix}{n:04d}" in taken:
        n += 1
    return f"{prefix}{n:04d}"


def _normalize_deal(data: dict, existing: dict | None, all_rows: list[dict]) -> dict:
    g = lambda k, default="": data.get(k, (existing or {}).get(k, default))  # noqa: E731
    date = m.parse_date(g("date"), "ინვოისის თარიღი")
    expiry = m.parse_date(g("contract_expiry"), "კონტრაქტის ვადა", required=False)
    if expiry and expiry < date:
        raise FinanceError("კონტრაქტის ვადა ინვოისის თარიღზე ადრე ვერ იქნება")
    currency = (_s(g("currency", "GEL")) or "GEL").upper()
    if currency not in m.CURRENCIES:
        raise FinanceError("ვალუტა: GEL ან USD")
    value = m.D(g("value"), default=None)
    if value is None:
        raise FinanceError("რეალიზაციის ღირებულება სავალდებულოა")
    coop = m.D(g("coop_percent", "100"), default=None)
    if coop is None:
        raise FinanceError("თანამშრომლობის პროცენტი სავალდებულოა")
    if "commission" in data:
        ov = data.get("commission")
    elif existing:
        # შენახული საკომისიო ხელით გადაწერილად ითვლება მხოლოდ თუ ავტომატურ გამოთვლას განსხვავდება
        ev, ec = m.D(existing.get("value"), default=None), m.D(existing.get("coop_percent"), default=None)
        auto = m.q2(ev * ec / Decimal(100)) if ev is not None and ec is not None else None
        stored = m.D(existing.get("commission"), default=None)
        ov = stored if stored is not None and auto is not None and stored != auto else ""
    else:
        ov = ""
    # ცარიელი/"auto" საკომისიო = ავტომატური გამოთვლა
    ov = None if _s(ov).lower() in ("", "auto") else ov
    res = m.calc(value, coop, g("agent_percent", "0"), g("tl_percent", "0"), ov)
    rep = _int(g("remind_report_months", m.DEFAULT_REPORT_MONTHS), m.DEFAULT_REPORT_MONTHS)
    exd = _int(g("remind_expiry_days", m.DEFAULT_EXPIRY_DAYS), m.DEFAULT_EXPIRY_DAYS)
    if not (0 <= rep <= 24) or not (0 <= exd <= 365):
        raise FinanceError("შეხსენების პარამეტრები არასწორია (თვე 0–24, დღე 0–365)")
    notes = m.clean(g("notes"), m.MAX_NOTES)
    taken = {_s(r.get("invoice_no")) for r in all_rows if _s(r.get("deal_id")) != _s((existing or {}).get("deal_id"))}
    inv = m.clean(g("invoice_no"), 60)
    if inv:
        if inv in taken:
            raise FinanceError(f"ინვოისის ნომერი {inv} უკვე არსებობს", 409)
    else:
        inv = _next_invoice_no(date, taken)
    out = {
        "invoice_no": inv, "date": date.isoformat(), "month": m.month_of(date),
        "provider": m.clean(g("provider")), "property_type": m.clean(g("property_type")),
        "recipient": m.clean(g("recipient")), "recipient_phone": m.clean(g("recipient_phone"), 40),
        "recipient_pid": m.clean(g("recipient_pid"), 40), "cadastral_code": m.clean(g("cadastral_code"), 60),
        "district": m.clean(g("district"), 80), "address": m.clean(g("address")),
        "value": m.s2(value), "currency": currency, "coop_percent": m.s2(coop),
        "commission": m.s2(res["commission"]),
        "agent_id": m.clean(g("agent_id"), 40), "agent_name": m.clean(g("agent_name"), 120),
        "agent_percent": m.s2(m.D(g("agent_percent", "0"))), "agent_payout": m.s2(res["agent_payout"]),
        "team_leader": m.clean(g("team_leader"), 120), "tl_percent": m.s2(m.D(g("tl_percent", "0"))),
        "tl_payout": m.s2(res["tl_payout"]), "company_income": m.s2(res["company_income"]),
        "contract_expiry": expiry.isoformat() if expiry else "",
        "client_phone": m.clean(g("client_phone"), 40), "client_name": m.clean(g("client_name"), 160),
        "client_pid": m.clean(g("client_pid"), 40),
        "remind_report_months": str(rep), "remind_expiry_days": str(exd), "notes": notes,
    }
    return out


def create_deal(data: dict, actor) -> dict:
    with _lock:
        rows = _backend.read(m.DEALS_SHEET, fresh=True)
        row = _normalize_deal(data, None, rows)
        row.update({"deal_id": m.new_id("D-"), "status": m.DEAL_ACTIVE, "created_at": now_str(), "updated_at": now_str(),
                    "created_by": _s(actor), "last_report_reminder": "", "expiry_reminder_60": "", "expiry_reminder_30": "",
                    "report_notified": ""})
        _backend.append(m.DEALS_SHEET, m.DEAL_HEADERS, row)
        return row


def update_deal(deal_id: str, data: dict, actor) -> dict:
    with _lock:
        rows = _backend.read(m.DEALS_SHEET, fresh=True)
        cur = next((r for r in rows if _s(r.get("deal_id")) == _s(deal_id) and _s(r.get("status")) != m.DEAL_DELETED), None)
        if not cur:
            raise FinanceError("გარიგება ვერ მოიძებნა", 404)
        row = _normalize_deal(data, cur, rows)
        # თუ ვადა/თარიღი შეიცვალა, შეხსენებების მარკერები ახლიდან დაიწყოს
        reset = row["contract_expiry"] != _s(cur.get("contract_expiry")) or row["date"] != _s(cur.get("date"))
        row["updated_at"] = now_str()
        if reset:
            row.update({"expiry_reminder_60": "", "expiry_reminder_30": "", "report_notified": ""})
        out = _backend.update(m.DEALS_SHEET, m.DEAL_HEADERS, deal_id, row)
        return out or row


def delete_deal(deal_id: str, actor) -> dict:
    with _lock:
        cur = get_deal(deal_id, fresh=True)
        if not cur or _s(cur.get("status")) == m.DEAL_DELETED:
            raise FinanceError("გარიგება ვერ მოიძებნა", 404)
        return _backend.update(m.DEALS_SHEET, m.DEAL_HEADERS, deal_id, {"status": m.DEAL_DELETED, "updated_at": now_str()})


def mark_report_done(deal_id: str, today: datetime.date | None = None) -> dict:
    today = today or today_local()
    with _lock:
        cur = get_deal(deal_id, fresh=True)
        if not cur or _s(cur.get("status")) == m.DEAL_DELETED:
            raise FinanceError("გარიგება ვერ მოიძებნა", 404)
        return _backend.update(m.DEALS_SHEET, m.DEAL_HEADERS, deal_id,
                               {"last_report_reminder": m.month_of(today), "updated_at": now_str()})


# ====================================================================== ხარჯები
def list_expenses(include_deleted: bool = False, fresh: bool = False) -> list[dict]:
    rows = _backend.read(m.EXPENSES_SHEET, fresh=fresh)
    return rows if include_deleted else [r for r in rows if _s(r.get("status")) != m.DEAL_DELETED]


def _normalize_expense(data: dict, existing: dict | None) -> dict:
    g = lambda k, default="": data.get(k, (existing or {}).get(k, default))  # noqa: E731
    date = m.parse_date(g("date"), "ხარჯის თარიღი")
    amount = m.D(g("amount"), default=None)
    if amount is None or amount <= 0:
        raise FinanceError("ხარჯის თანხა უნდა იყოს 0-ზე მეტი")
    currency = (_s(g("currency", "GEL")) or "GEL").upper()
    if currency not in m.CURRENCIES:
        raise FinanceError("ვალუტა: GEL ან USD")
    recurring = "yes" if _s(g("recurring")).lower() in ("yes", "true", "1", "on") else "no"
    until = _s(g("until_month"))
    if until:
        until = m.parse_month(until, "დასრულების თვე")
        if until < m.month_of(date):
            raise FinanceError("დასრულების თვე დაწყებამდე ვერ იქნება")
    if recurring == "no":
        until = ""
    category = m.clean(g("category"), 80)
    if not category:
        raise FinanceError("აირჩიეთ ხარჯის კატეგორია")
    return {"date": date.isoformat(), "month": m.month_of(date), "category": category,
            "description": m.clean(g("description")), "amount": m.s2(amount), "currency": currency,
            "recurring": recurring, "until_month": until}


def create_expense(data: dict, actor) -> dict:
    with _lock:
        row = _normalize_expense(data, None)
        row.update({"expense_id": m.new_id("E-"), "status": m.DEAL_ACTIVE, "created_at": now_str(), "updated_at": now_str(),
                    "created_by": _s(actor)})
        _backend.append(m.EXPENSES_SHEET, m.EXPENSE_HEADERS, row)
        return row


def update_expense(expense_id: str, data: dict, actor) -> dict:
    with _lock:
        cur = next((r for r in _backend.read(m.EXPENSES_SHEET, fresh=True)
                    if _s(r.get("expense_id")) == _s(expense_id) and _s(r.get("status")) != m.DEAL_DELETED), None)
        if not cur:
            raise FinanceError("ხარჯი ვერ მოიძებნა", 404)
        row = _normalize_expense(data, cur)
        row["updated_at"] = now_str()
        return _backend.update(m.EXPENSES_SHEET, m.EXPENSE_HEADERS, expense_id, row) or row


def delete_expense(expense_id: str, actor) -> dict:
    with _lock:
        cur = next((r for r in _backend.read(m.EXPENSES_SHEET, fresh=True) if _s(r.get("expense_id")) == _s(expense_id)), None)
        if not cur or _s(cur.get("status")) == m.DEAL_DELETED:
            raise FinanceError("ხარჯი ვერ მოიძებნა", 404)
        return _backend.update(m.EXPENSES_SHEET, m.EXPENSE_HEADERS, expense_id, {"status": m.DEAL_DELETED, "updated_at": now_str()})


def _expense_in_month(e: dict, month: str) -> bool:
    """ერთჯერადი: მხოლოდ თავის თვეში; განმეორებადი: დაწყების თვიდან (და until-მდე, თუ მითითებულია) ყოველ თვეს."""
    start = _s(e.get("month"))
    if _s(e.get("recurring")) == "yes":
        until = _s(e.get("until_month"))
        return start <= month and (not until or month <= until)
    return start == month


# ====================================================================== შეჯამება (დაშბორდი / ანგარიშგება)
def _conv(amount: Decimal, currency: str, rate: Decimal | None, unconverted: dict) -> Decimal:
    if currency == "USD":
        if rate is None:
            unconverted["usd"] += amount
            return Decimal("0")
        return amount * rate
    return amount


def _bucket():
    return {"deals": 0, "value": Decimal(0), "commission": Decimal(0), "agent_payout": Decimal(0),
            "tl_payout": Decimal(0), "company_income": Decimal(0)}


def summary(frm: str, to: str, deals: list[dict] | None = None, expenses: list[dict] | None = None,
            rate: Decimal | None = None) -> dict:
    """თვეების ინტერვალის [frm, to] ფინანსური შეჯამება (ყველაფერი GEL-ში; USD — კურსით, თუ დაყენებულია)."""
    months = m.month_range(frm, to)
    deals = list_deals() if deals is None else deals
    expenses = list_expenses() if expenses is None else expenses
    rate = usd_rate() if rate is None else rate
    unconv = {"usd": Decimal(0), "deals": 0}
    series = {mo: dict(_bucket(), expenses=Decimal(0)) for mo in months}
    by_agent: dict[str, dict] = {}
    by_tl: dict[str, dict] = {}
    by_district: dict[str, dict] = {}
    by_type: dict[str, dict] = {}
    top = []
    tot = _bucket()
    for d in deals:
        mo = _s(d.get("month"))
        if mo not in series:
            continue
        cur = _s(d.get("currency")) or "GEL"
        if cur == "USD" and rate is None:
            unconv["deals"] += 1
        c = lambda k: _conv(m.D(d.get(k)), cur, rate, unconv if k == "commission" else {"usd": Decimal(0)})  # noqa: E731
        vals = {k: c(k) for k in ("value", "commission", "agent_payout", "tl_payout", "company_income")}
        for b in (series[mo], tot):
            b["deals"] += 1
            for k, v in vals.items():
                b[k] += v
        for key, label, field in ((by_agent, _s(d.get("agent_name")) or "—", "agent_payout"),
                                  (by_tl, _s(d.get("team_leader")) or "—", "tl_payout"),
                                  (by_district, _s(d.get("district")) or "—", "company_income"),
                                  (by_type, _s(d.get("property_type")) or "—", "company_income")):
            b = key.setdefault(label, _bucket())
            b["deals"] += 1
            for k, v in vals.items():
                b[k] += v
        top.append((vals["company_income"], d))
    exp_by_cat: dict[str, Decimal] = {}
    exp_total = Decimal(0)
    for e in expenses:
        cur = _s(e.get("currency")) or "GEL"
        amt = m.D(e.get("amount"))
        for mo in months:
            if _expense_in_month(e, mo):
                v = _conv(amt, cur, rate, {"usd": Decimal(0)})
                series[mo]["expenses"] += v
                exp_total += v
                cat = _s(e.get("category")) or "სხვა"
                exp_by_cat[cat] = exp_by_cat.get(cat, Decimal(0)) + v
    profit = tot["company_income"] - exp_total
    f2 = lambda x: float(m.q2(x))  # noqa: E731

    def pack(b):
        return {k: (f2(v) if isinstance(v, Decimal) else v) for k, v in b.items()}

    def ranking(dct, key):
        rows = [dict(name=n, **pack(b)) for n, b in dct.items()]
        rows.sort(key=lambda r: r[key], reverse=True)
        return rows

    top.sort(key=lambda x: x[0], reverse=True)
    series_out = []
    for mo in months:
        b = series[mo]
        series_out.append({"month": mo, **pack({k: v for k, v in b.items()}),
                           "profit": f2(b["company_income"] - b["expenses"])})
    return {
        "from": frm, "to": to, "months": months,
        "totals": {**pack(tot), "expenses": f2(exp_total), "profit": f2(profit),
                   "margin_pct": round(float(profit / tot["company_income"] * 100), 1) if tot["company_income"] else None},
        "series": series_out,
        "distribution": {"company": f2(tot["company_income"]), "agents": f2(tot["agent_payout"]), "team_leaders": f2(tot["tl_payout"])},
        "by_agent": ranking(by_agent, "commission")[:30], "by_team_leader": ranking(by_tl, "tl_payout")[:20],
        "by_district": ranking(by_district, "company_income")[:20], "by_property_type": ranking(by_type, "company_income"),
        "expenses_by_category": sorted([{"name": k, "amount": f2(v)} for k, v in exp_by_cat.items()], key=lambda r: r["amount"], reverse=True),
        "top_deals": [{"deal_id": d["deal_id"], "invoice_no": d.get("invoice_no"), "address": d.get("address"),
                       "agent_name": d.get("agent_name"), "company_income": f2(v), "date": d.get("date")} for v, d in top[:8]],
        "usd_rate": float(rate) if rate else None,
        "unconverted_usd": {"deals": unconv["deals"]} if rate is None and unconv["deals"] else None,
    }


# ====================================================================== შეხსენებები
def _deal_dates(d: dict):
    return (m.parse_date(d.get("date"), required=False), m.parse_date(d.get("contract_expiry"), required=False))


def reminders(today: datetime.date | None = None, deals: list[dict] | None = None) -> dict:
    """{report_due: [...], expiring: [...], expired: [...]} — აქტიური გარიგებებიდან."""
    today = today or today_local()
    deals = list_deals() if deals is None else deals
    report_due, expiring, expired = [], [], []
    for d in deals:
        start, expiry = _deal_dates(d)
        if not start:
            continue
        base = {"deal_id": d.get("deal_id"), "invoice_no": d.get("invoice_no"), "address": d.get("address"),
                "client_name": d.get("client_name"), "agent_name": d.get("agent_name"), "contract_expiry": d.get("contract_expiry"),
                "date": d.get("date")}
        n = _int(d.get("remind_report_months"), 0)
        if n > 0 and (not expiry or today <= expiry):
            mb = m.months_between(start, today)
            if mb >= n and mb % n == 0 and _s(d.get("last_report_reminder")) != m.month_of(today):
                report_due.append({**base, "months": mb})
        if expiry:
            left = (expiry - today).days
            win = _int(d.get("remind_expiry_days"), 0)
            if left < 0:
                expired.append({**base, "days_left": left})
            elif win > 0 and left <= win:
                expiring.append({**base, "days_left": left})
    expiring.sort(key=lambda r: r["days_left"])
    expired.sort(key=lambda r: r["days_left"], reverse=True)
    report_due.sort(key=lambda r: r["months"], reverse=True)
    return {"report_due": report_due, "expiring": expiring, "expired": expired[:50]}


def pending_notifications(today: datetime.date | None = None) -> list[dict]:
    """[{deal_id, flag, value, text}] — რაც ჯერ არ გაგზავნილა (ერთხელ თითო მოვლენაზე)."""
    today = today or today_local()
    out = []
    deals = list_deals()
    r = reminders(today, deals)
    by_id = {d["deal_id"]: d for d in deals}
    for it in r["report_due"]:
        d = by_id[it["deal_id"]]
        if _s(d.get("report_notified")) != m.month_of(today):
            out.append({"deal_id": it["deal_id"], "flag": "report_notified", "value": m.month_of(today),
                        "text": f"📊 რეპორტინგის დრო: ხელშეკრულებიდან გავიდა {it['months']} თვე\n"
                                f"{it['address'] or '-'} · {it['client_name'] or '-'}\nინვოისი: {it['invoice_no']} · აგენტი: {it['agent_name'] or '-'}"})
    for it in r["expiring"]:
        d = by_id[it["deal_id"]]
        win = _int(d.get("remind_expiry_days"), 0)
        flag = "expiry_reminder_30" if it["days_left"] <= 30 and win > 30 else "expiry_reminder_60"
        if _s(d.get(flag)):
            continue
        out.append({"deal_id": it["deal_id"], "flag": flag, "value": today.isoformat(),
                    "text": f"⏳ ხელშეკრულება იწურება {it['days_left']} დღეში ({it['contract_expiry']})\n"
                            f"{it['address'] or '-'} · {it['client_name'] or '-'}\nინვოისი: {it['invoice_no']} · აგენტი: {it['agent_name'] or '-'}"})
    return out


def mark_notified(deal_id: str, flag: str, value: str) -> None:
    if flag in ("report_notified", "expiry_reminder_60", "expiry_reminder_30"):
        with _lock:
            _backend.update(m.DEALS_SHEET, m.DEAL_HEADERS, deal_id, {flag: value})


# ====================================================================== CSV
def to_csv(kind: str, rows: list[dict]) -> bytes:
    cols = m.DEAL_CSV_COLUMNS if kind == "deals" else m.EXPENSE_CSV_COLUMNS
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for h, _k in cols])
    for r in rows:
        w.writerow([_safe_cell(r.get(k, "")) for _h, k in cols])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _safe_cell(v) -> str:
    """CSV-ინჟექციისგან დაცვა: =,+,-,@-ით დაწყებული ტექსტი (ტელეფონი +995… არ ირღვევა, რადგან ციფრებია)."""
    s = _s(v)
    if s[:1] in ("=", "@") or (s[:1] in ("+", "-") and not s[1:].replace(" ", "").replace(".", "").isdigit()):
        return "'" + s
    return s
