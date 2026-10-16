"""
ხელშეკრულებების ვადები და შეტყობინებები — არსებული ბოტის job-ებიდან გამოსაძახებელი წმინდა ლოგიკა (ახალი scheduler არ იქმნება).

bot.py ამ მოდულიდან იღებს სიას `pending_notifications()` და თავად აგზავნის (`context.bot.send_message`), წარმატებისას კი
`mark_sent(item)`-ს იძახებს — ერთი და იგივე შეტყობინება ორჯერ არ გაიგზავნება (Issue-ის `reminder_sent_at`/`overdue_notified_at`).
დაგვიანება გამოითვლება **აქტიური Issue ჩანაწერიდან** (returned_at ცარიელია და due_at < ახლა), არა მოთხოვნის სტატუსიდან.
დრო — თბილისის (Asia/Tbilisi).
"""

from __future__ import annotations

import datetime
import logging

import config
import contracts_model as m
import contracts_store as store

log = logging.getLogger("safehome-contracts-jobs")


def _chat_of(agent: dict | None):
    try:
        return int(agent.get("telegram_chat_id")) if agent else None
    except (TypeError, ValueError):
        return None


def pending_notifications(get_agents, now: datetime.datetime | None = None) -> list[dict]:
    """[{chat_id, text, issue_id, flag}] — ვადამდე შეხსენება აგენტს; დაგვიანება — აგენტს, გუნდის ლიდერს, თანამშრომლებს, ადმინს."""
    now = now or m.now_local()
    agents = {str(a.get("agent_id")): a for a in get_agents()}
    out: list[dict] = []
    horizon = now + datetime.timedelta(hours=config.CONTRACT_REMINDER_HOURS)
    managers_cache: dict[str, set] = {}

    def managers_of(agent_row) -> set:
        team = str((agent_row or {}).get("team", "")).strip()
        if team not in managers_cache:
            ids = set(config.ADMIN_CHAT_IDS) | set(config.CONTRACT_STAFF_CHAT_IDS)
            for a in agents.values():
                if team and str(a.get("team", "")).strip() == team and str(a.get("role", "")).strip() == "team_lead":
                    c = _chat_of(a)
                    if c:
                        ids.add(c)
            managers_cache[team] = ids
        return managers_cache[team]

    for i in store.list_issues():
        if not store.is_open_issue(i):
            continue
        due = m.parse_dt(i.get("due_at"))
        if not due:
            continue
        agent = agents.get(str(i.get("agent_id")))
        code = i.get("control_code") or i.get("copy_id")
        if due < now:
            if str(i.get("overdue_notified_at") or "").strip():
                continue
            late_h = int((now - due).total_seconds() // 3600)
            who = (agent or {}).get("name") or i.get("agent_name") or "აგენტი"
            text_mgr = (f"⏰ ვადაგადაცილებული ხელშეკრულება {code}\nაგენტი: {who}\n"
                        f"ვადა იყო: {i.get('due_at')} (≈{late_h} სთ-ით დაგვიანებული)\n"
                        f"მისამართი: {i.get('property_address') or '-'}\nმოთხოვნა: {i.get('request_id')}")
            sent_to = set()
            for cid in managers_of(agent):
                out.append({"chat_id": cid, "text": text_mgr, "issue_id": i["issue_id"], "flag": "overdue_notified_at"})
                sent_to.add(cid)
            ac = _chat_of(agent)
            if ac and ac not in sent_to:
                out.append({"chat_id": ac, "text": f"⏰ ხელშეკრულება {code} დასაბრუნებელი იყო {i.get('due_at')}-მდე. "
                                                   f"გთხოვთ დაუყოვნებლივ დააბრუნოთ.", "issue_id": i["issue_id"],
                            "flag": "overdue_notified_at"})
        elif due <= horizon:
            if str(i.get("reminder_sent_at") or "").strip():
                continue
            ac = _chat_of(agent)
            if ac:
                out.append({"chat_id": ac, "text": f"🔔 შეხსენება: ხელშეკრულება {code} უნდა დააბრუნოთ {i.get('due_at')}-მდე.",
                            "issue_id": i["issue_id"], "flag": "reminder_sent_at"})
    return out


def mark_sent(item: dict) -> None:
    try:
        store.mark_issue_flag(item["issue_id"], item["flag"])
    except Exception:  # noqa: BLE001
        log.exception("შეტყობინების მარკერი ვერ ჩაიწერა (%s)", item.get("issue_id"))


def daily_summary_text() -> str:
    """ადმინის ყოველდღიური შეჯამება: მარაგი, დღეს დასაბრუნებელი, ვადაგადაცილებული, პრობლემური ეგზემპლარები."""
    d = store.dashboard()
    if d["total"] == 0 and d["in_process"] == 0:
        return ""
    stock = store.stock_by_type()
    lines = ["📑 ხელშეკრულებები — დღევანდელი შეჯამება",
             f"სულ ეგზემპლარი: {d['total']} · ხელმისაწვდომი: {d['available']} · დაჯავშნილი: {d['reserved']} · აგენტებთან: {d['issued']}",
             f"დღეს დასაბრუნებელი: {d['due_today']} · ვადაგადაცილებული: {d['overdue']}",
             f"დამუშავებაში მოთხოვნა: {d['in_process']}",
             f"შესამოწმებელი: {d['under_review']} · დაზიანებული: {d['damaged']} · დაკარგული: {d['lost']}"]
    for t, s in stock.items():
        lines.append(f"• {m.CONTRACT_TYPES[t]['label']}: თავისუფალი {s['available']}/{s['total']}")
    late = store.overdue_issues()
    for i in late[:10]:
        lines.append(f"⏰ {i.get('control_code')} — {i.get('agent_name')} (ვადა {i.get('due_at')})")
    return "\n".join(lines)
