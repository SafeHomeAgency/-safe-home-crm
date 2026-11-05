"""
კადრების აყვანის ფონური ციკლი (ბოტის JobQueue-დან; ლოგიკა აქ — ტესტირებადია). **წესებზე დაფუძნებულია (LLM-ის გარეშე)**.

რას აგზავნის (მხოლოდ პერსონალს — პასუხისმგებელს და ადმინებს; კანდიდატებს არასდროს წერს):
  🆕 ახალი კანდიდატი — მაშინვე (პასუხისმგებელს + ადმინებს); 3 სთ-ში არავინ დაუკავშირდა — პასუხისმგებელს შეხსენება; 8 სთ-ში — ადმინებს ესკალაცია;
  📞 გასაუბრებამდე ერთი დღით ადრე — დასადასტურებლების სია (შეხსენების საათზე), +4 სთ-ზე — ისევ დარჩენილები, +6 სთ-ზე — ადმინებს, თუ რჩება;
  🗓 გასაუბრების დღის დილის სია; ⏱ გასაუბრების შემდეგ — „ჩაწერეთ მოვიდა თუ არა“; ✍️ გადაწყვეტილება 48 სთ-ზე მეტია არ არის;
  🎓 ტრენინგი ხვალ — დაუდასტურებლების სია.
დედუპლიკაცია ცხრილში RecruitAlerts (რესტარტი არ აორმაგებს); ღამით (22:00–08:00) არ იგზავნება; ძველი (silent) ჩანაწერებზე შეტყობინებები არ მიდის.
"""

from __future__ import annotations

import datetime
import logging

import config
import recruit_model as m
import recruit_store as st

log = logging.getLogger("safehome-recruit-jobs")
QUIET_FROM, QUIET_TO = 22, 8


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def in_quiet(now: datetime.datetime) -> bool:
    return now.hour >= QUIET_FROM or now.hour < QUIET_TO


def _awake_start(created: datetime.datetime) -> datetime.datetime:
    """ღამით შემოსული კანდიდატის 'ასაკი' დილის 08:00-დან იწყება (ღამით არავინ უნდა ერეოდეს)."""
    if created.hour >= QUIET_FROM:
        return (created + datetime.timedelta(days=1)).replace(hour=QUIET_TO, minute=0, second=0)
    if created.hour < QUIET_TO:
        return created.replace(hour=QUIET_TO, minute=0, second=0)
    return created


def _chats(agents: list[dict]) -> tuple[list[int], list[int]]:
    """(პასუხისმგებლების chat id-ები, ადმინების chat id-ები)."""
    resp_ids = set(st.get_settings()["responsible_ids"])
    resp = []
    for a in agents:
        if _s(a.get("agent_id")) in resp_ids and _s(a.get("active", "yes")).lower() not in ("no", "false", "0"):
            try:
                resp.append(int(_s(a.get("telegram_chat_id"))))
            except ValueError:
                pass
    return sorted(set(resp)), sorted(config.ADMIN_CHAT_IDS)


def _line(r: dict, now: datetime.datetime, with_time: bool = True) -> str:
    p = st.public(r, now)
    t = f"{p.get('interview_time')} — " if with_time and p.get("interview_time") else ""
    call = {"confirmed": " ✅", "declined": " ❌", "no_contact": " 📵", "repeat": " 🔁"}.get(_s(r.get("call_status")), "")
    return f"• {t}{p['name']}{' (' + p['age'] + ')' if p.get('age') else ''}{call} 📞 {p.get('phone_pretty') or p.get('phone_raw') or '—'}"


def prepare_alerts(now: datetime.datetime | None = None, agents: list[dict] | None = None) -> list[dict]:
    now = now or st.now_dt()
    if in_quiet(now):
        return []
    if agents is None:
        import sheets
        agents = sheets.get_agents()
    resp, admins = _chats(agents)
    everyone = sorted(set(resp) | set(admins))
    if not everyone:
        return []
    owners = resp or admins                                  # პასუხისმგებელი არ არის მითითებული => ადმინებს ეგზავნებათ
    settings = st.get_settings()
    hour = settings["remind_hour"]
    rows = [r for r in st.all_rows(fresh=True) if _s(r.get("closed")) != "yes"]
    today, tomorrow = now.date(), now.date() + datetime.timedelta(days=1)
    out: list[dict] = []

    def emit(key: str, kind: str, rid: str, chats: list[int], text: str, buttons: list | None = None) -> None:
        if chats and text and st.claim_alert(key, kind, rid, ",".join(map(str, chats))):
            out.append({"key": key, "kind": kind, "chat_ids": chats, "text": text, "recruit_id": rid, "buttons": buttons or []})

    def openers(arr: list, extra: tuple | None = None) -> list:
        """ღილაკები: თითო კანდიდატზე (Mini App პირდაპირ მის ბარათზე იხსნება) + დამატებითი (სია/კალენდარი)."""
        btns = [(f"📂 {_s(r.get('name'))[:28]}", "rc=" + _s(r.get("recruit_id"))) for r in arr[:5]]
        return btns + ([extra] if extra else [])

    # 1) ახალი კანდიდატები
    fresh = [r for r in rows if _s(r.get("stage")) == "new" and not _s(r.get("silent")) and not _s(r.get("last_contact_at"))
             and (c := m.parse_dt(r.get("created_at"))) and now - c < datetime.timedelta(hours=72)]
    new_now, new_3h, new_8h = [], [], []
    done = st.alert_keys()
    for r in fresh:
        rid = _s(r.get("recruit_id"))
        age = (now - _awake_start(m.parse_dt(r.get("created_at")))).total_seconds() / 3600
        if f"new:{rid}" not in done:
            new_now.append(r)
        elif age >= 3 and f"new3:{rid}" not in done:
            new_3h.append(r)
        if age >= 8 and f"new8:{rid}" not in done and resp:
            new_8h.append(r)
    if new_now:
        keys = [f"new:{_s(r.get('recruit_id'))}" for r in new_now]
        claimed = [r for r, k in zip(new_now, keys) if st.claim_alert(k, "new", _s(r.get("recruit_id")), "all")]
        if claimed:
            head = "🆕 ახალი კანდიდატი" if len(claimed) == 1 else f"🆕 ახალი კანდიდატები: {len(claimed)}"
            def detail(r):
                p = st.public(r, now)
                s = _line(r, now, False)
                if _s(r.get("interview_at")):
                    s += f"\n   🗓 არჩეული გასაუბრება: {p.get('interview_day', '')} {p.get('interview_time', '')}".rstrip()
                if _s(r.get("motivation")):
                    s += "\n   💬 " + _s(r.get("motivation"))[:110]
                if _s(r.get("experience")):
                    s += "\n   🧰 გამოცდილება: " + _s(r.get("experience"))[:40]
                return s
            body = "\n\n".join(detail(r) for r in claimed)
            out.append({"key": ",".join(keys), "kind": "new", "chat_ids": everyone, "recruit_id": "", "keys": [k for r, k in zip(new_now, keys) if r in claimed],
                        "buttons": openers(claimed, ("📋 დღევანდელი სია", "rv=today")),
                        "text": f"{head}\n\n{body}\n\n👉 დარეკეთ და დაადასტურეთ გასაუბრება — ღილაკზე დაჭერით კანდიდატის ბარათი პირდაპირ იხსნება."})
    if new_3h:
        for r in new_3h:
            if not st.claim_alert(f"new3:{_s(r.get('recruit_id'))}", "new3", _s(r.get("recruit_id")), "owners"):
                continue
            out.append({"key": f"new3:{_s(r.get('recruit_id'))}", "kind": "new3", "chat_ids": owners, "recruit_id": _s(r.get("recruit_id")), "buttons": openers([r]),
                        "text": "⏰ კანდიდატს ჯერ არავინ დაუკავშირდა (3 საათზე მეტია):\n" + _line(r, now, False)})
    for r in new_8h:
        if st.claim_alert(f"new8:{_s(r.get('recruit_id'))}", "new8", _s(r.get("recruit_id")), "admins"):
            out.append({"key": f"new8:{_s(r.get('recruit_id'))}", "kind": "new8", "chat_ids": admins, "recruit_id": _s(r.get("recruit_id")), "buttons": openers([r]),
                        "text": "⚠️ კანდიდატს 8 საათზე მეტია არავინ დაუკავშირდა (პასუხისმგებელმა ვერ მოასწრო):\n" + _line(r, now, False) + "\n\nთქვენც შეგიძლიათ აპში შეიყვანოთ შედეგი."})

    # 2) ხვალინდელი გასაუბრებების დადასტურება
    tm = [r for r in rows if (d := m.parse_dt(r.get("interview_at"))) and d.date() == tomorrow and _s(r.get("stage")) in ("new", "invited", "confirmed")]
    unconf = sorted([r for r in tm if _s(r.get("call_status")) in ("", "repeat", "no_contact")], key=lambda r: _s(r.get("interview_at")))
    dk = tomorrow.strftime("%Y-%m-%d")
    if unconf and hour <= now.hour < 21:
        emit(f"confirm:{dk}", "confirm", "", owners if now.hour >= hour else [],
             f"📞 ხვალ გასაუბრება {len(tm)}-ს აქვს, დასადასტურებელია {len(unconf)}:\n" + "\n".join(_line(r, now) for r in unconf) + "\n\nდარეკეთ და ჩაწერეთ: მოდის / არ მოდის (Mini App → 👥 კადრები).", openers(unconf, ("📋 სია", "rv=today")))
    if unconf and now.hour >= hour + 4 and now.hour < 21:
        emit(f"confirm2:{dk}", "confirm2", "", owners, f"🔁 ხვალინდელი გასაუბრებებიდან ისევ დაუდასტურებელია {len(unconf)}:\n" + "\n".join(_line(r, now) for r in unconf), openers(unconf, ("📋 სია", "rv=today")))
    if unconf and now.hour >= hour + 6 and now.hour < 21:
        emit(f"confirm3:{dk}", "confirm3", "", admins, f"⚠️ ხვალინდელი გასაუბრებებიდან {len(unconf)} დაუდასტურებელია (პასუხისმგებელმა ვერ მოასწრო):\n" + "\n".join(_line(r, now) for r in unconf), openers(unconf, ("📋 სია", "rv=today")))

    # 3) დღევანდელი გასაუბრებები (დილით)
    td = sorted([r for r in rows if (d := m.parse_dt(r.get("interview_at"))) and d.date() == today and _s(r.get("stage")) in ("new", "invited", "confirmed")], key=lambda r: _s(r.get("interview_at")))
    if td and now.hour >= 9:
        emit(f"today:{today.strftime('%Y-%m-%d')}", "today", "", everyone, f"🗓 დღეს გასაუბრება: {len(td)}\n" + "\n".join(_line(r, now) for r in td), openers(td, ("📅 კალენდარი", "rv=cal")))

    # 4) გასაუბრების შედეგი ჩაუწერელია
    pend = [r for r in rows if (d := m.parse_dt(r.get("interview_at"))) and datetime.timedelta(minutes=60) <= now - d < datetime.timedelta(hours=26)
            and _s(r.get("stage")) in ("new", "invited", "confirmed") and not _s(r.get("attended"))]
    new_pend = [r for r in pend if f"result:{_s(r.get('recruit_id'))}" not in done]
    claimed = [r for r in new_pend if st.claim_alert(f"result:{_s(r.get('recruit_id'))}", "result", _s(r.get("recruit_id")), "owners")]
    if claimed:
        out.append({"key": ",".join(f"result:{_s(r.get('recruit_id'))}" for r in claimed), "kind": "result", "chat_ids": owners, "recruit_id": "", "buttons": openers(claimed),
                    "keys": [f"result:{_s(r.get('recruit_id'))}" for r in claimed],
                    "text": "✍️ ჩაწერეთ, მოვიდა თუ არა გასაუბრებაზე:\n" + "\n".join(_line(r, now) for r in claimed)})

    # 5) გადაწყვეტილება არ არის
    und = [r for r in rows if _s(r.get("stage")) == "interviewed" and not _s(r.get("decision")) and (c := m.parse_dt(r.get("last_contact_at") or r.get("interview_at")))
           and now - c >= datetime.timedelta(hours=48)]
    claimed = [r for r in und if st.claim_alert(f"decision:{_s(r.get('recruit_id'))}", "decision", _s(r.get("recruit_id")), "owners+admins")]
    if claimed:
        out.append({"key": ",".join(f"decision:{_s(r.get('recruit_id'))}" for r in claimed), "kind": "decision", "chat_ids": everyone, "recruit_id": "", "buttons": openers(claimed),
                    "keys": [f"decision:{_s(r.get('recruit_id'))}" for r in claimed],
                    "text": "🧭 გასაუბრების შემდეგ გადაწყვეტილება 48 საათზე მეტია არ არის (მიღებულია / განიხილება / უარყოფილია):\n" + "\n".join(_line(r, now) for r in claimed)})

    # 6) ტრენინგი ხვალ
    tr = sorted([r for r in rows if (d := m.parse_dt(r.get("training_at"))) and d.date() == tomorrow and _s(r.get("training_ok")) != "yes" and _s(r.get("stage")) in ("training", "interviewed", "considering")],
                key=lambda r: _s(r.get("training_at")))
    if tr and hour <= now.hour < 21:
        emit(f"train:{dk}", "train", "", owners, f"🎓 ხვალ ტრენინგია, არ არის დადასტურებული ({len(tr)}):\n" + "\n".join(_line(r, now, False) for r in tr), openers(tr, ("📅 კალენდარი", "rv=cal")))
    return out


def finish(msg: dict, ok: bool) -> None:
    """გაგზავნა ჩავარდა -> გასაღებებს ვანთავისუფლებთ (შემდეგ ციკლზე ისევ ეცდება)."""
    if ok:
        return
    for k in msg.get("keys") or [msg.get("key")]:
        for kk in str(k).split(","):
            if kk:
                try:
                    st.release_alert(kk)
                except Exception:  # noqa: BLE001
                    log.warning("RecruitAlerts: გასაღები ვერ გათავისუფლდა (%s)", kk, exc_info=True)


def run_cycle_sync(send, now: datetime.datetime | None = None, agents: list[dict] | None = None, do_sync: bool = False) -> dict:
    """ტესტი/ხელით გაშვება: send(chat_id, text) -> bool."""
    stats = {"sent": 0, "failed": 0, "messages": []}
    for msg in prepare_alerts(now, agents):
        ok = False
        for cid in msg["chat_ids"]:
            try:
                if send(cid, msg["text"]):
                    ok = True
                    stats["messages"].append({"kind": msg["kind"], "chat_id": cid, "text": msg["text"]})
            except Exception:  # noqa: BLE001
                log.warning("Recruit: გაგზავნა ვერ მოხერხდა (%s)", cid, exc_info=True)
        finish(msg, ok)
        stats["sent" if ok else "failed"] += 1
    return stats
