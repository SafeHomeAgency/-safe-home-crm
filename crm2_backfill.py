"""
CRM 2.0 (P2) backfill — ძველი ცხრილებიდან (Tasks / Reports / Meetings / Exclusives)
კლიენტების, მფლობელების, ობიექტებისა და აქტივობების აღდგენა.

უსაფრთხოება:
  * ნაგულისხმევად **DRY-RUN**: არაფერს წერს, მხოლოდ გეგმას და რაოდენობებს ბეჭდავს;
  * ძველ ცხრილებს **არასდროს ცვლის** (მხოლოდ კითხულობს);
  * იდემპოტენტურია: უკვე არსებული კლიენტი/მფლობელი (ნორმალიზებული ტელეფონით) და უკვე
    გადმოწერილი აქტივობა (`source_ref`) თავიდან არ იქმნება — განმეორებით გაშვება უვნებელია;
  * ჩაწერა ერთ ცხრილზე ერთი `append_rows` ზარით (Sheets-ის კვოტა).

გაშვება (პროექტის საქაღალდიდან, production env ცვლადებით):
    python crm2_backfill.py            # dry-run
    python crm2_backfill.py --apply    # ნამდვილი ჩაწერა (მხოლოდ დადასტურების შემდეგ!)
"""

from __future__ import annotations

import sys

import crm2_model as m
import crm2_store as store


def _by_phone_latest(rows: list[dict], phone_key: str, time_key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: str(r.get(time_key, ""))):
        p = m.normalize_phone(r.get(phone_key))
        if p:
            out[p] = r  # ბოლო (ყველაზე ახალი) იგებს
    return out


def build_plan(tasks: list[dict], reports: list[dict], meetings: list[dict],
               exclusives: list[dict], existing: dict | None = None) -> dict:
    """წმინდა ფუნქცია (Sheets-ს არ ეხება) — აბრუნებს ჩასაწერ სტრიქონებს.
    `existing` = {"clients": [...], "owners": [...], "activities": [...], "properties": [...]}"""
    existing = existing or {}
    now = m.utc_now()
    client_by_phone = {c["phone_norm"]: c["client_id"] for c in existing.get("clients", []) if c.get("phone_norm")}
    owner_by_phone = {o["phone_norm"]: o["owner_id"] for o in existing.get("owners", []) if o.get("phone_norm")}
    seen_refs = {a.get("source_ref") for a in existing.get("activities", []) if a.get("source_ref")}
    seen_excl = {p.get("exclusive_id") for p in existing.get("properties", []) if p.get("exclusive_id")}

    new_clients: list[dict] = []
    new_owners: list[dict] = []
    new_props: list[dict] = []
    new_acts: list[dict] = []
    skipped_no_phone = 0

    def ensure_client(phone_raw, latest: dict | None = None) -> str | None:
        p = m.normalize_phone(phone_raw)
        if not p:
            return None
        if p not in client_by_phone:
            cid = m.new_id("cl")
            client_by_phone[p] = cid
            lt = latest or {}
            rec = {h: "" for h in m.CLIENTS_HEADERS}
            rec.update({
                "client_id": cid, "phone_norm": p, "phone_raw": str(phone_raw).strip(),
                "status": "new", "source": "backfill",
                "assigned_agent_id": str(lt.get("assigned_to", "")),
                "assigned_agent_name": str(lt.get("assigned_to_name", "")),
                "deal_type": str(lt.get("deal_type") or lt.get("lead_type") or ""),
                "created_at": now, "updated_at": now, "created_by": "backfill",
            })
            new_clients.append(rec)
        return client_by_phone[p]

    def ensure_owner(phone_raw) -> str | None:
        p = m.normalize_phone(phone_raw)
        if not p:
            return None
        if p not in owner_by_phone:
            oid = m.new_id("ow")
            owner_by_phone[p] = oid
            rec = {h: "" for h in m.OWNERS_HEADERS}
            rec.update({"owner_id": oid, "phone_norm": p, "phone_raw": str(phone_raw).strip(),
                        "created_at": now, "updated_at": now, "created_by": "backfill"})
            new_owners.append(rec)
        return owner_by_phone[p]

    def act(entity_type, entity_id, type_, summary, ref, agent_id="", agent_name="", at=""):
        if not entity_id or ref in seen_refs:
            return
        seen_refs.add(ref)
        new_acts.append({
            "activity_id": m.new_id("ac"), "entity_type": entity_type, "entity_id": entity_id,
            "type": type_, "summary": summary, "agent_id": str(agent_id), "agent_name": str(agent_name),
            "source_ref": ref, "created_at": at or now,
        })

    latest_task = _by_phone_latest(tasks, "client_phone", "created_at")
    for t in tasks:
        cid = ensure_client(t.get("client_phone"), latest_task.get(m.normalize_phone(t.get("client_phone"))))
        if cid is None:
            skipped_no_phone += 1
        else:
            act("client", cid, "task", f"დავალება: {t.get('title', '')} [{t.get('status', '')}]".strip(),
                f"task:{t.get('task_id')}", t.get("assigned_to", ""), t.get("assigned_to_name", ""),
                t.get("created_at", ""))
        oid = ensure_owner(t.get("owner_phone"))
        if oid:
            act("owner", oid, "task", f"დავალება: {t.get('title', '')}", f"task-owner:{t.get('task_id')}",
                t.get("assigned_to", ""), t.get("assigned_to_name", ""), t.get("created_at", ""))
    for r in reports:
        cid = ensure_client(r.get("client_phone"))
        if cid is None:
            skipped_no_phone += 1
            continue
        act("client", cid, "report", f"{r.get('actions', '')} — {r.get('notes', '')}".strip(" —"),
            f"report:{r.get('report_id')}", r.get("agent_id", ""), r.get("agent_name", ""), r.get("created_at", ""))
    for mt in meetings:
        cid = ensure_client(mt.get("client_phone"))
        if cid is None:
            skipped_no_phone += 1
        else:
            act("client", cid, "meeting", f"შეხვედრა: {mt.get('address', '')} {mt.get('meeting_date', '')}".strip(),
                f"meeting:{mt.get('meeting_id')}", mt.get("agent_id", ""), mt.get("agent_name", ""),
                mt.get("timestamp", ""))
        oid = ensure_owner(mt.get("owner_phone"))
        if oid:
            act("owner", oid, "meeting", f"შეხვედრა: {mt.get('address', '')}", f"meeting-owner:{mt.get('meeting_id')}",
                mt.get("agent_id", ""), mt.get("agent_name", ""), mt.get("timestamp", ""))
    for ex in exclusives:
        eid = ex.get("exclusive_id")
        oid = ensure_owner(ex.get("owner_phone"))
        if not oid or not eid or eid in seen_excl:
            if not oid:
                skipped_no_phone += 1
            continue
        seen_excl.add(eid)
        rec = {h: "" for h in m.PROPERTIES_HEADERS}
        rec.update({
            "property_id": m.new_id("pr"), "owner_id": oid, "exclusive_id": eid,
            "agent_id": str(ex.get("agent_id", "")), "agent_name": str(ex.get("agent_name", "")),
            "address": str(ex.get("location", "")), "deal_type": str(ex.get("deal_type", "")),
            "price": str(ex.get("price", "")), "status": "active",
            "created_at": ex.get("created_at") or now, "updated_at": now,
        })
        new_props.append(rec)

    return {
        "clients": new_clients, "owners": new_owners, "properties": new_props,
        "activities": new_acts, "skipped_no_phone": skipped_no_phone,
    }


def _load_existing() -> dict:
    return {
        "clients": store._read(m.CLIENTS_SHEET, fresh=True),
        "owners": store._read(m.OWNERS_SHEET, fresh=True),
        "properties": store._read(m.PROPERTIES_SHEET, fresh=True),
        "activities": store._read(m.ACTIVITIES_SHEET, fresh=True),
    }


def summarize(plan: dict) -> str:
    return (f"კლიენტი +{len(plan['clients'])}, მფლობელი +{len(plan['owners'])}, "
            f"ობიექტი +{len(plan['properties'])}, აქტივობა +{len(plan['activities'])}, "
            f"ტელეფონის გარეშე გამოტოვებული: {plan['skipped_no_phone']}")


def apply_plan(plan: dict) -> None:
    """ერთი append_rows თითო ცხრილზე; წინასწარ ensure_tabs()."""
    sg = store._sg()
    with store._lock:
        store.ensure_tabs()
        for name, headers, key in (
            (m.CLIENTS_SHEET, m.CLIENTS_HEADERS, "clients"),
            (m.OWNERS_SHEET, m.OWNERS_HEADERS, "owners"),
            (m.PROPERTIES_SHEET, m.PROPERTIES_HEADERS, "properties"),
            (m.ACTIVITIES_SHEET, m.ACTIVITIES_HEADERS, "activities"),
        ):
            rows = [store._row(headers, r) for r in plan[key]]
            if rows:
                sg._worksheet(name).append_rows(rows, value_input_option="RAW")
                sg._invalidate(name)


def run(apply: bool = False) -> dict:
    sg = store._sg()
    if apply:
        store.ensure_tabs()
    # dry-run-ში ცხრილებს არ ვქმნით: თუ ჯერ არ არსებობს — "არსებული" ცარიელია
    titles = {w.title for w in sg._get_spreadsheet().worksheets()}
    all_there = all(name in titles for name, _h, _r in m.ALL_TABS[:4])
    if all_there:
        store._ready = True  # ensure_tabs-ის გარეშე ვკითხულობთ (ცხრილები უკვე არსებობს)
        existing = _load_existing()
    else:
        existing = {}
    plan = build_plan(sg.get_tasks(), sg.get_reports(), sg.get_meetings(), sg.get_exclusives(), existing)
    print(("APPLY: " if apply else "DRY-RUN (არაფერი ჩაიწერა): ") + summarize(plan))
    if apply:
        apply_plan(plan)
        print("ჩაწერილია.")
    return plan


if __name__ == "__main__":
    run(apply="--apply" in sys.argv[1:])
