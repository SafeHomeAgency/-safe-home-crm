"""
CRM 2.0 (P2.4) — ახალი ჩანაწერების ავტომატური ასახვა CRM-ში (dual-write).

როცა ახალი დავალება / რეპორტი / შეხვედრა / ექსკლუზივი იქმნება (ძველ ცხრილებში, როგორც
აქამდე), ამ მოდულის ფუნქციები იმავე ჩანაწერს ასახავენ CRM 2.0-ში: კლიენტი/მფლობელი
ტელეფონით (დუბლიკატის გარეშე), აქტივობა timeline-ში, ექსკლუზივიდან ობიექტი.

უსაფრთხოების წესები:
  * **არასდროს აგდებს გამონაკლისს** — ნებისმიერი შეცდომა ლოგში იწერება და მთავარი ოპერაცია
    (დავალების/რეპორტის შექმნა) ამით არ ირღვევა;
  * ძველ ცხრილებს არ ეხება;
  * იდემპოტენტურია `source_ref`-ით (იგივე ჩანაწერი ორჯერ აქტივობას არ ქმნის);
  * გამორთვა: env `CRM2_SYNC=0` (გადატვირთვის შემდეგ) — ერთი ცვლადით, კოდის შეცვლის გარეშე;
  * backfill-თან (`crm2_backfill.py`) თავსებადია: იგივე `source_ref` ფორმატი
    (`task:ID`, `task-owner:ID`, `report:ID`, `meeting:ID`, `meeting-owner:ID`) — backfill-ის
    გაშვება sync-ის შემდეგაც დუბლიკატს არ ქმნის.
"""

from __future__ import annotations

import logging
import os
import queue
import threading

import crm2_model as m
import crm2_store as store

log = logging.getLogger("safehome-crm2-sync")


def enabled() -> bool:
    return os.environ.get("CRM2_SYNC", "1").strip().lower() not in ("0", "false", "no")


# ასახვა ფონურ (ერთ) thread-ში მიმდინარეობს: მომხმარებელი Sheets-ის დამატებით ზარებს არ ელოდება,
# წყობა ინახება თანმიმდევრობით, ჩავარდნა მთავარ ოპერაციას არ ეხება. INLINE=True — ტესტებისთვის.
INLINE = False
_q: "queue.Queue" = queue.Queue(maxsize=1000)
_worker_started = False
_worker_lock = threading.Lock()


def _run(fn, a, kw) -> None:
    try:
        fn(*a, **kw)
    except Exception:  # noqa: BLE001 — sync-მა მთავარი ოპერაცია არასდროს უნდა დააზიანოს
        log.exception("CRM 2.0 sync ვერ მოხერხდა (%s) — მთავარი ოპერაცია არ შეწყვეტილა", fn.__name__)


def _worker_loop() -> None:
    while True:
        fn, a, kw = _q.get()
        try:
            _run(fn, a, kw)
        finally:
            _q.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker_loop, name="crm2-sync", daemon=True).start()
            _worker_started = True


def drain(timeout: float = 10.0) -> None:
    """ელოდება წყობის დაცარიელებას (ტესტები/გამორთვა)."""
    import time
    end = time.monotonic() + timeout
    while _q.unfinished_tasks and time.monotonic() < end:
        time.sleep(0.01)


def _safe(fn):
    def wrapper(*a, **kw):
        if not enabled():
            return None
        if INLINE:
            _run(fn, a, kw)
            return None
        try:
            _ensure_worker()
            _q.put_nowait((fn, a, kw))
        except Exception:  # noqa: BLE001 — წყობა სავსეა/შეცდომა: ვაგდებთ ამ ასახვას, მთავარს არ ვაჩერებთ
            log.exception("CRM 2.0 sync წყობაში ვერ ჩაჯდა (%s)", fn.__name__)
        return None
    wrapper.__name__ = fn.__name__
    return wrapper


def _has_ref(ref: str) -> bool:
    return any(a.get("source_ref") == ref for a in store._read(m.ACTIVITIES_SHEET, fresh=True))


def _agent_name(agent_id) -> str:
    try:
        return store._sg().agent_name_by_id(agent_id) or ""
    except Exception:  # noqa: BLE001
        return ""


@_safe
def task_created(task_id: str, assigned_to: str = "", client_phone: str = "", owner_phone: str = "",
                 title: str = "", deal_type: str = "", lead_type: str = "", by: str = "") -> None:
    """დავალება -> კლიენტი (+ მფლობელი, თუ მითითებულია) და 'task' აქტივობა."""
    name = _agent_name(assigned_to)
    if m.normalize_phone(client_phone):
        cid, _ = store.upsert_client(client_phone, {
            "assigned_agent_id": str(assigned_to), "assigned_agent_name": name,
            "deal_type": deal_type, "source": "task",
        }, by=by or "sync")
        ref = f"task:{task_id}"
        if not _has_ref(ref):
            store.add_activity("client", cid, "task", f"დავალება: {title}".strip(),
                               agent_id=str(assigned_to), agent_name=name, source_ref=ref)
    if m.normalize_phone(owner_phone):
        oid, _ = store.upsert_owner(owner_phone, by=by or "sync")
        ref = f"task-owner:{task_id}"
        if not _has_ref(ref):
            store.add_activity("owner", oid, "task", f"დავალება: {title}".strip(),
                               agent_id=str(assigned_to), agent_name=name, source_ref=ref)


@_safe
def report_created(report_id: str, agent_id: str = "", client_phone: str = "",
                   actions: str = "", notes: str = "") -> None:
    if not m.normalize_phone(client_phone):
        return
    name = _agent_name(agent_id)
    cid, _ = store.upsert_client(client_phone, {}, by="sync")
    ref = f"report:{report_id}"
    if not _has_ref(ref):
        store.add_activity("client", cid, "report", f"{actions} — {notes}".strip(" —"),
                           agent_id=str(agent_id), agent_name=name, source_ref=ref)


@_safe
def meeting_created(meeting_id: str, fields: dict) -> None:
    agent_id = str(fields.get("agent_id", ""))
    name = str(fields.get("agent_name", "")) or _agent_name(agent_id)
    summary = f"შეხვედრა: {fields.get('address', '')} {fields.get('meeting_date', '')}".strip()
    if m.normalize_phone(fields.get("client_phone")):
        cid, _ = store.upsert_client(fields.get("client_phone"), {}, by="sync")
        ref = f"meeting:{meeting_id}"
        if not _has_ref(ref):
            store.add_activity("client", cid, "meeting", summary, agent_id=agent_id, agent_name=name, source_ref=ref)
    if m.normalize_phone(fields.get("owner_phone")):
        oid, _ = store.upsert_owner(fields.get("owner_phone"), by="sync")
        ref = f"meeting-owner:{meeting_id}"
        if not _has_ref(ref):
            store.add_activity("owner", oid, "meeting", summary, agent_id=agent_id, agent_name=name, source_ref=ref)


@_safe
def exclusive_created(exclusive_id: str, agent_id: str, fields: dict) -> None:
    """ექსკლუზივი -> მფლობელი (ტელეფონით) + ობიექტი (იგივე exclusive_id-ით ერთხელ)."""
    if not m.normalize_phone(fields.get("owner_phone")):
        return
    if any(p.get("exclusive_id") == exclusive_id for p in store._read(m.PROPERTIES_SHEET, fresh=True)):
        return
    oid, _ = store.upsert_owner(fields.get("owner_phone"), by="sync")
    store.create_property(oid, {
        "exclusive_id": exclusive_id, "agent_id": str(agent_id), "agent_name": _agent_name(agent_id),
        "address": str(fields.get("location", "")), "deal_type": str(fields.get("deal_type", "")),
        "price": str(fields.get("price", "")),
    })
