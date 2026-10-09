"""
აგენტის KPI (შედეგი %) — ერთი წყარო Mini App-ისა (აგენტი + მენეჯერი/რეიტინგი) და ბოტის /ranking-ისთვის.

ადრე შედეგი = "24 საათში დახურული დავალებები / მიღებული" — ეს მაჩვენებელი თითქმის არ იცვლებოდა
(აგენტები /done-ს იშვიათად აჭერენ) და ყველა სხვა სამუშაოს (განცხადებები, დისციპლინა, შეხვედრები...)
არ ითვალისწინებდა. ახლა 5 კომპონენტია (წონები: config.KPI_WEIGHTS):

  1. listings     — დადებული განცხადებები / გეგმა (დღეში 20; ონლაინ და ოფისი). ფაქტი დღეზე =
                    max(MyHome job-ები, Attendance-ის count_submitted).
  2. discipline   — დროულად გახსნა (ოფისი: 10:00/16:00 + 15 წთ; ონლაინ: ნებისმიერ დროს) და დროულად დახურვა
                    (ოფისი: ცვლის დასრულებიდან ≤60 წთ; ონლაინ: 22:00+15 წთ-მდე) + ჯარიმა თითო გაფრთხილებაზე.
  3. meetings     — შეხვედრები / გეგმა (config.KPI_MEETINGS_PER_WEEK კვირაში).
  4. clients      — მინიჭებული კლიენტები: 50% მიღება (დადასტურება) + 50% დამუშავება (Done ან რეპორტი).
  5. closed_cases — ჩახურული ქეისები (CRM 2.0 კლიენტი სტატუსით "won") / გეგმა (KPI_CLOSED_CASES_PER_MONTH თვეში).

კომპონენტი, რომელიც აგენტზე არ ვრცელდება (მაგ. პერიოდში კლიენტი არ მიუღია, ცვლა არ ჰქონია), გამოტოვდება და
დანარჩენი წონები ნორმირდება — რომ აგენტს უმოქმედობისთვის არ ვაჯარიმებთ იქ, სადაც მუშაობა არ ეკუთვნოდა.
ყველა დრო თბილისის დღით (crm_time) ითვლება; ცხრილების server-naive დრო იკითხება crm_time-ით.
"""

from __future__ import annotations

import datetime
import re

import config
import crm_time
import shift_rules
import sheets

LABELS = {
    "listings": "განცხადებები გეგმასთან",
    "discipline": "დისციპლინა (გახსნა/დახურვა/გაფრთხილებები)",
    "meetings": "შეხვედრები",
    "clients": "კლიენტები",
    "closed_cases": "ჩახურული ქეისები",
}


def window_dates(days: int) -> list[datetime.date]:
    today = crm_time.local_today()
    days = max(1, int(days or 1))
    return [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]


def _s(d: datetime.date) -> str:
    return d.strftime(crm_time.DATE_FMT)


def _digits9(v) -> str:
    return re.sub(r"\D", "", str(v or ""))[-9:]


def _local_hm(value) -> datetime.datetime | None:
    dt = crm_time.parse_server_dt(value)
    return crm_time.server_naive_to_local(dt) if dt else None


def _comp(score, value, target, text):
    return {"score": None if score is None else round(max(0.0, min(1.0, score)), 4),
            "value": value, "target": target, "text": text}


def _day_mode(att, sched, d: datetime.date) -> str:
    if att and att.get("mode"):
        return str(att.get("mode"))
    return str((sched or {}).get(sheets.WEEKDAY_KEYS[d.weekday()]) or "off")


def _listings_by_day(jobs) -> dict:
    out: dict[tuple, int] = {}
    try:
        import crm_extras
        invalid = crm_extras._is_invalid_listing_job
    except Exception:  # noqa: BLE001
        invalid = lambda j: False  # noqa: E731
    for j in jobs:
        day = crm_time.business_date_of_server_naive(j.get("created_at", ""))
        if day and not invalid(j):
            k = (str(j.get("agent_id")), day)
            out[k] = out.get(k, 0) + 1
    return out


def compute(days: int = 30, agent_ids=None, now_local: datetime.datetime | None = None) -> dict:
    """{agent_id: {"score": 0..1|None, "pct": int|None, "components": {...}, "warnings": int}}"""
    now = now_local or crm_time.local_now().replace(tzinfo=None)
    dates = window_dates(days)
    dset = {_s(d) for d in dates}
    today = _s(now.date())
    ndays = len(dates)

    agents = [a for a in sheets.get_agents() if str(a.get("active", "yes")).strip().lower() not in ("no", "false", "0")]
    if agent_ids is not None:
        want = {str(x) for x in agent_ids}
        agents = [a for a in agents if str(a.get("agent_id")) in want]

    att_rows = sheets.get_attendance_records(date_from=_s(dates[0]), date_to=_s(dates[-1]) )
    att = {(str(r.get("agent_id")), str(r.get("date"))): r for r in att_rows}
    jobs_by_day = _listings_by_day(sheets.get_myhome_jobs())
    dayoffs = set()
    for r in sheets.get_dayoff_requests(status="approved"):
        d = crm_time.parse_user_date(r.get("date", ""))
        if d:
            dayoffs.add((str(r.get("agent_id")), _s(d)))
    warns = [w for w in sheets.get_warnings() if str(w.get("status") or "active") != "dismissed"]
    meetings = sheets.get_meetings()
    tasks = sheets.get_tasks()
    try:
        reports = sheets.get_reports()
    except Exception:  # noqa: BLE001
        reports = []
    try:
        import crm2_store
        won = [c for c in crm2_store.list_clients(status="won")]
    except Exception:  # noqa: BLE001
        won = None

    meet_target = max(1, round(config.KPI_MEETINGS_PER_WEEK * ndays / 7))
    closed_target = max(1, round(config.KPI_CLOSED_CASES_PER_MONTH * ndays / 30))
    out: dict = {}

    for a in agents:
        aid = str(a.get("agent_id"))
        sched = sheets.get_agent_schedule(aid) or {}
        comps = {}

        # ---- 1. listings + 2. discipline (დღეების მიხედვით)
        plan = actual = 0
        day_scores: list[float] = []
        for d in dates:
            ds = _s(d)
            row = att.get((aid, ds))
            mode = _day_mode(row, sched, d)
            if mode == "off" or (aid, ds) in dayoffs:
                continue
            opened = shift_rules.is_opened(row)
            end_h = shift_rules.end_hour(mode)
            shift_over = ds < today or (ds == today and end_h is not None and now.hour >= end_h)
            if ds == today and not opened and not shift_over:
                continue                                    # დღევანდელი ცვლა ჯერ არ დაწყებულა
            quota = sheets.quota_for_mode(mode)
            if quota:
                plan += quota
                try:
                    cs = int((row or {}).get("count_submitted") or 0)
                except (TypeError, ValueError):
                    cs = 0
                actual += max(jobs_by_day.get((aid, ds), 0), cs)
            # დისციპლინა
            if not opened:
                day_scores.append(0.0)
                continue
            parts = []
            o = shift_rules.opened_at_local(row)
            parts.append(1.0 if (mode == "online" or o is None or not shift_rules.is_late_open(mode, o)) else 0.0)
            if shift_over:
                closed = shift_rules.is_closed(row)
                ok = False
                if closed:
                    c = _local_hm((row or {}).get("clock_out"))
                    limit_h = (end_h + 1) if mode != "online" else None
                    if c is None:
                        ok = True
                    elif mode == "online":
                        ok = c.replace(second=0) <= c.replace(hour=end_h, minute=config.ATTENDANCE_GRACE_MINUTES, second=0)
                    else:
                        ok = c.hour < limit_h or (c.hour == limit_h and c.minute == 0)
                parts.append(1.0 if ok else 0.0)
            day_scores.append(sum(parts) / len(parts))

        comps["listings"] = _comp(
            (actual / plan) if plan else None, actual, plan,
            f"{actual}/{plan}" if plan else "გეგმა არ ეკუთვნოდა")
        nwarn = sum(1 for w in warns if str(w.get("agent_id")) == aid
                    and crm_time.business_date_of_server_naive(w.get("created_at", "")) in dset)
        if day_scores or nwarn:
            base = (sum(day_scores) / len(day_scores)) if day_scores else 1.0
            disc = base - nwarn * config.KPI_WARNING_PENALTY
            comps["discipline"] = _comp(disc, round(base * 100), nwarn,
                                        f"გახსნა/დახურვა {round(base * 100)}%, გაფრთხილება: {nwarn}")
        else:
            comps["discipline"] = _comp(None, 0, 0, "ცვლა არ ეკუთვნოდა")

        # ---- 3. meetings
        nm = sum(1 for m in meetings if str(m.get("agent_id")) == aid
                 and crm_time.business_date_of_server_naive(m.get("timestamp", "")) in dset)
        comps["meetings"] = _comp(nm / meet_target, nm, meet_target, f"{nm}/{meet_target}")

        # ---- 4. clients
        mine = [t for t in tasks if str(t.get("assigned_to")) == aid
                and crm_time.business_date_of_server_naive(t.get("created_at", "")) in dset]
        if mine:
            my_reports = [r for r in reports if str(r.get("agent_id")) == aid]
            tot = 0.0
            handled_n = 0
            for t in mine:
                sc = 0.5 if str(t.get("seen")).strip().lower() == "yes" else 0.0
                ph = _digits9(t.get("client_phone"))
                done = str(t.get("status")) == "Done" or bool(
                    ph and any(_digits9(r.get("client_phone")) == ph for r in my_reports))
                if done:
                    sc += 0.5
                    handled_n += 1
                tot += sc
            comps["clients"] = _comp(tot / len(mine), len(mine), len(mine),
                                     f"მიღებული {len(mine)}, დამუშავებული {handled_n}")
        else:
            comps["clients"] = _comp(None, 0, 0, "კლიენტი არ მიუღია")

        # ---- 5. closed cases
        if won is None:
            comps["closed_cases"] = _comp(None, 0, closed_target, "მონაცემი მიუწვდომელია")
        else:
            nc = 0
            for c in won:
                if str(c.get("assigned_agent_id")) != aid:
                    continue
                dt = crm_time.utc_iso_to_local(c.get("updated_at"))
                if dt and _s(dt.date()) in dset:
                    nc += 1
            comps["closed_cases"] = _comp(nc / closed_target, nc, closed_target, f"{nc}/{closed_target}")

        num = den = 0.0
        for k, c in comps.items():
            c["label"] = LABELS[k]
            c["weight"] = config.KPI_WEIGHTS.get(k, 0)
            if c["score"] is not None and c["weight"] > 0:
                num += c["score"] * c["weight"]
                den += c["weight"]
        score = (num / den) if den else None
        out[aid] = {
            "agent_id": aid, "name": a.get("name", ""), "team": a.get("team", ""),
            "score": None if score is None else round(score, 4),
            "pct": None if score is None else round(score * 100),
            "components": comps, "warnings": nwarn, "days": ndays,
        }
    return out


def ranking(kpis: dict, limit: int | None = None) -> list[dict]:
    rows = [v for v in kpis.values() if v.get("score") is not None]
    rows.sort(key=lambda v: (-v["score"], str(v.get("name"))))
    return rows[:limit] if limit else rows
