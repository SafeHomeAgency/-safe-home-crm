"""
ხელშეკრულებების აღრიცხვა — HTTP API (`/api/contracts/...`).

ახალი endpoint-ებია; არსებულ endpoint-ებს არ ცვლის. webserver.py მხოლოდ `contracts_api.register(app, ...)`-ს უმატებს —
ავტორიზაცია, audit, rate limit, შეხვედრების წაკითხვა და Telegram-ის გაგზავნა გადაეცემა დამხმარე ფუნქციებით
(წრიული იმპორტის თავიდან ასაცილებლად, crm2_api.py-ს მსგავსად).

უფლებები (ყოველი მოქმედება მოწმდება **სერვერზე**):
  * აგენტი   — ქმნის მოთხოვნას მხოლოდ საკუთარ შეხვედრაზე; ხედავს მხოლოდ საკუთარ მოთხოვნებს/გატანილ ეგზემპლარებს;
               ვერ ადასტურებს საკუთარი დოკუმენტის გაცემას/დაბრუნებას;
  * თიმლიდერი — ხედავს თავისი გუნდის მოთხოვნებს/გაცემებს/დაგვიანებებს, ამტკიცებს გუნდის მოთხოვნებს (არა საკუთარს);
               გაცემა/მიღება მხოლოდ თუ მისი Telegram ID ჩამოთვლილია `CONTRACT_STAFF_CHAT_IDS`-ში;
  * პასუხისმგებელი თანამშრომელი (`CONTRACT_STAFF_CHAT_IDS`) — გასცემს/იბარებს, ამატებს მარაგს, ამოწმებს ეგზემპლარებს;
  * ადმინი  — ყველაფერი, მათ შორის აუდიტის ისტორია.
"""

from __future__ import annotations

import datetime
import logging

from flask import jsonify, request

import config
import contracts_model as m
import contracts_store as store
from contracts_model import ContractError

log = logging.getLogger("safehome-contracts-api")

_PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "all": 0}


class _Ctx:
    def __init__(self, agent, admin, chat_id, lead):
        self.agent = agent
        self.admin = bool(admin)
        self.chat_id = chat_id
        self.lead = bool(lead) and not self.admin
        self.agent_id = str((agent or {}).get("agent_id", ""))
        self.team = str((agent or {}).get("team", "")).strip()
        self.name = "ადმინი" if self.admin and not agent else str((agent or {}).get("name", "")) or str(chat_id)
        # პასუხისმგებელი თანამშრომელი: ადმინი ან სიაში ჩამოთვლილი Telegram ID
        self.staff = self.admin or (chat_id is not None and int(chat_id) in config.CONTRACT_STAFF_CHAT_IDS)

    @property
    def manager_view(self) -> bool:
        """ხედავს ბევრი აგენტის მონაცემს (ადმინი/თანამშრომელი/თიმლიდერი)."""
        return self.admin or self.staff or self.lead


def register(app, *, authed, is_team_lead, audit, rate_limited, get_agents, get_meetings, chat_id_fn, notify,
             find_client=None) -> None:
    """authed() -> (agent, admin, err); audit(agent, admin, action, entity_type, entity_id, metadata=...);
    get_meetings() -> [meeting rows]; chat_id_fn() -> მიმდინარე მომხმარებლის Telegram ID; notify(chat_id, text) -> bool;
    find_client(phone) -> CRM 2.0 კლიენტი ან None (არასავალდებულო)."""

    def _ctx():
        agent, admin, err = authed()
        if err:
            return None, err
        return _Ctx(agent, admin, chat_id_fn(), is_team_lead(agent)), None

    def _agents_by_id() -> dict:
        return {str(a.get("agent_id")): a for a in get_agents()}

    def _team_ids(team: str) -> set:
        return {str(a.get("agent_id")) for a in get_agents() if team and str(a.get("team", "")).strip() == team}

    def _can_see_agent(ctx: _Ctx, agent_id) -> bool:
        aid = str(agent_id or "")
        if ctx.admin or ctx.staff:
            return True
        if ctx.lead:
            return aid == ctx.agent_id or aid in _team_ids(ctx.team)
        return bool(ctx.agent_id) and aid == ctx.agent_id

    def _guard(fn):
        """ContractError -> JSON პასუხი სწორი HTTP კოდით; მოულოდნელი შეცდომა — 500 (დეტალები ლოგში, არა მომხმარებელთან)."""
        import functools

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            try:
                return fn(*a, **kw)
            except ContractError as e:
                return jsonify(error=str(e)), e.status
            except Exception:  # noqa: BLE001
                log.exception("contracts API შეცდომა: %s", fn.__name__)
                return jsonify(error="სერვერის შეცდომა — სცადეთ ხელახლა"), 500
        return wrapper

    # ------------------------------------------------------------------ სერიალიზაცია
    def _pub_request(r: dict, ctx: _Ctx) -> dict:
        d = {k: r.get(k, "") for k in (
            "request_id", "meeting_id", "client_id", "property_id", "property_address", "agent_id", "agent_name",
            "contract_type", "language_pair", "copy_count", "issued_count", "request_created_at",
            "requested_return_due_at", "request_status", "approved_by", "approved_at", "notes", "meeting_datetime",
            "myhome_id", "ssge_id", "team", "cancelled_reason")}
        # ტელეფონი სრულად მხოლოდ იმას, ვისაც ამ აგენტის მონაცემი ეკუთვნის (სერვერზე უკვე გაფილტრულია) — აქ დამატებით
        # სია მაინც ნაწილობრივ დაფარულია; სრული ნომერი მხოლოდ დეტალში
        d["client_phone_masked"] = m.mask_phone(r.get("client_phone"))
        d["type_label"] = m.CONTRACT_TYPES.get(r.get("contract_type"), {}).get("label", r.get("contract_type", ""))
        d["status_label"] = m.REQUEST_STATUSES.get(r.get("request_status"), r.get("request_status", ""))
        return d

    def _pub_issue(i: dict, ctx: _Ctx, full: bool = False) -> dict:
        now = m.now_local()
        due = m.parse_dt(i.get("due_at"))
        open_ = store.is_open_issue(i)
        d = {k: i.get(k, "") for k in (
            "issue_id", "copy_id", "request_id", "meeting_id", "agent_id", "agent_name", "control_code", "issued_by",
            "issued_at", "due_at", "returned_at", "received_by", "return_condition", "return_reason", "outcome", "notes",
            "contract_type", "property_address", "signed_contract_number")}
        d["open"] = open_
        d["overdue"] = bool(open_ and due and due < now)
        d["type_label"] = m.CONTRACT_TYPES.get(i.get("contract_type"), {}).get("label", i.get("contract_type", ""))
        d["outcome_label"] = m.OUTCOMES.get(i.get("outcome"), "")
        d["client_phone_masked"] = m.mask_phone(i.get("client_phone"))
        if full:
            d["client_phone"] = i.get("client_phone", "")
        if not ctx.manager_view:
            # რიგითი აგენტი: საკონტროლო კოდი (და ფიზიკური ეგზემპლარის ID) არ ჩანს — მხოლოდ ადმინს/მენეჯერს/თანამშრომელს
            d["control_code"] = ""
            d["copy_id"] = ""
        return d

    def _pub_copy(c: dict) -> dict:
        d = {k: c.get(k, "") for k in (
            "copy_id", "control_code", "contract_type", "language_pair", "physical_status", "storage_location",
            "condition", "created_at", "created_by", "active_issue_id", "reserved_request_id", "last_outcome")}
        d["type_label"] = m.CONTRACT_TYPES.get(c.get("contract_type"), {}).get("label", c.get("contract_type", ""))
        d["status_label"] = m.PHYSICAL_STATUSES.get(c.get("physical_status"), c.get("physical_status", ""))
        return d

    def _scope_requests(ctx: _Ctx, rows: list[dict]) -> list[dict]:
        if ctx.admin or ctx.staff:
            return rows
        if ctx.lead:
            ids = _team_ids(ctx.team) | {ctx.agent_id}
            return [r for r in rows if str(r.get("agent_id")) in ids]
        return [r for r in rows if ctx.agent_id and str(r.get("agent_id")) == ctx.agent_id]

    def _scope_issues(ctx: _Ctx, rows: list[dict]) -> list[dict]:
        return _scope_requests(ctx, rows)       # ორივეს agent_id აქვს

    def _caps(ctx: _Ctx) -> dict:
        return {"admin": ctx.admin, "staff": ctx.staff, "lead": ctx.lead, "agent_id": ctx.agent_id,
                "can_approve": bool(ctx.admin or ctx.staff or ctx.lead),
                "can_handle_physical": ctx.staff, "can_see_audit": ctx.admin}

    def _approvers_chat_ids(agent_row: dict | None) -> list:
        ids = set(config.ADMIN_CHAT_IDS) | set(config.CONTRACT_STAFF_CHAT_IDS)
        team = str((agent_row or {}).get("team", "")).strip()
        if team:
            for a in get_agents():
                if str(a.get("team", "")).strip() == team and str(a.get("role", "")).strip() == "team_lead":
                    try:
                        ids.add(int(a.get("telegram_chat_id")))
                    except (TypeError, ValueError):
                        pass
        return sorted(ids)

    def _agent_chat(agent_id) -> int | None:
        a = _agents_by_id().get(str(agent_id))
        try:
            return int(a.get("telegram_chat_id")) if a else None
        except (TypeError, ValueError):
            return None

    def _safe_notify(chat, text: str) -> None:
        if chat is None:
            return
        try:
            notify(chat, text)
        except Exception:  # noqa: BLE001
            log.warning("ხელშეკრულების შეტყობინება ვერ გაიგზავნა (%s)", chat, exc_info=True)

    # ------------------------------------------------------------------ მეტა / მიმოხილვა
    @app.get("/api/contracts/overview")
    @rate_limited("contracts_read")
    @_guard
    def contracts_overview():
        ctx, err = _ctx()
        if err:
            return err
        days = _PERIOD_DAYS.get((request.args.get("period") or "all").strip().lower(), 0)
        reqs = _scope_requests(ctx, store.list_requests())
        if days:
            cutoff = m.now_local() - datetime.timedelta(days=days)
            reqs = [r for r in reqs if (m.parse_dt(r.get("request_created_at")) or cutoff) >= cutoff]
        reqs.sort(key=lambda r: str(r.get("request_created_at", "")), reverse=True)
        issues = _scope_issues(ctx, store.list_issues())
        active = [i for i in issues if store.is_open_issue(i)]
        active.sort(key=lambda i: str(i.get("due_at", "")))
        payload = {
            "caps": _caps(ctx),
            "types": {k: v["label"] for k, v in m.CONTRACT_TYPES.items()},
            "request_statuses": m.REQUEST_STATUSES, "physical_statuses": m.PHYSICAL_STATUSES, "outcomes": m.OUTCOMES,
            "requests": [_pub_request(r, ctx) for r in reqs[:400]],
            "active_issues": [_pub_issue(i, ctx) for i in active[:300]],
            "recent_returns": [_pub_issue(i, ctx) for i in sorted(
                (x for x in issues if not store.is_open_issue(x)), key=lambda x: str(x.get("returned_at", "")), reverse=True)[:60]],
        }
        if ctx.manager_view:
            copies = store.list_copies()
            # თიმლიდერს მარაგის ჯამი და დაზიანებული/დაკარგული/შესამოწმებელი ეგზემპლარები ეჩვენება (არა სრული სია —
            # `copies` სრული სია მხოლოდ თანამშრომელს/ადმინს მიეცემა ქვემოთ)
            payload["summary"] = store.dashboard(issues=issues, requests=reqs, copies=copies)
            payload["stock"] = store.stock_by_type()
            payload["problem_copies"] = [_pub_copy(c) for c in copies if str(c.get("physical_status")) in (
                m.PH_UNDER_REVIEW, m.PH_DAMAGED, m.PH_LOST)][:200]
            payload["today_due"] = [_pub_issue(i, ctx) for i in store.due_today_issues() if _can_see_agent(ctx, i.get("agent_id"))]
            payload["overdue"] = [_pub_issue(i, ctx) for i in store.overdue_issues() if _can_see_agent(ctx, i.get("agent_id"))]
        if ctx.staff:
            payload["copies"] = [_pub_copy(c) for c in store.list_copies()][-600:]
        return jsonify(payload)

    # ------------------------------------------------------------------ მოთხოვნის შექმნა (შეხვედრიდან)
    def _meeting_or_error(ctx: _Ctx, meeting_id: str, for_create: bool):
        meeting = next((x for x in get_meetings() if str(x.get("meeting_id")) == str(meeting_id)), None)
        if not meeting:
            raise ContractError("შეხვედრა ვერ მოიძებნა", 404)
        owner = str(meeting.get("agent_id"))
        if for_create:
            allowed = ctx.admin or (ctx.agent_id and owner == ctx.agent_id) or (ctx.lead and owner in _team_ids(ctx.team))
        else:
            allowed = _can_see_agent(ctx, owner)
        if not allowed:
            # არსებობას არ ვამხელთ
            raise ContractError("ამ შეხვედრაზე წვდომა არ გაქვთ", 403)
        return meeting

    @app.get("/api/contracts/meeting/<meeting_id>")
    @rate_limited("contracts_read")
    @_guard
    def contracts_for_meeting(meeting_id):
        ctx, err = _ctx()
        if err:
            return err
        meeting = _meeting_or_error(ctx, meeting_id, for_create=False)
        reqs = [r for r in store.list_requests() if str(r.get("meeting_id")) == str(meeting_id)]
        reqs = _scope_requests(ctx, reqs)
        rids = {r["request_id"] for r in reqs}
        issues = [i for i in store.list_issues() if str(i.get("request_id")) in rids]
        can_create = bool(ctx.admin or (ctx.agent_id and str(meeting.get("agent_id")) == ctx.agent_id)
                          or (ctx.lead and str(meeting.get("agent_id")) in _team_ids(ctx.team)))
        # მარაგის რაოდენობა მხოლოდ ადმინს/მენეჯერს/თანამშრომელს ჩანს (რიგით აგენტს — არა)
        available = None
        if ctx.manager_view:
            available = {k: v["available"] + v["reserved"] for k, v in store.stock_by_type().items()}
        return jsonify(
            requests=[_pub_request(r, ctx) for r in sorted(reqs, key=lambda r: str(r.get("request_created_at", "")), reverse=True)],
            issues=[_pub_issue(i, ctx) for i in sorted(issues, key=lambda i: str(i.get("issued_at", "")), reverse=True)],
            types={k: v["label"] for k, v in m.CONTRACT_TYPES.items()},
            available=available,
            can_create=can_create, caps=_caps(ctx))

    @app.post("/api/contracts/requests")
    @rate_limited("contracts_write")
    @_guard
    def contracts_create_request():
        ctx, err = _ctx()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        meeting = _meeting_or_error(ctx, data.get("meeting_id"), for_create=True)
        owner = _agents_by_id().get(str(meeting.get("agent_id")))
        client_id = ""
        if find_client:
            try:
                c = find_client(meeting.get("client_phone"))
                client_id = str((c or {}).get("client_id", ""))
            except Exception:  # noqa: BLE001
                client_id = ""
        row, created = store.create_request(
            meeting=meeting, agent=owner, actor_id=ctx.chat_id or ctx.agent_id,
            contract_type=str(data.get("contract_type") or "").strip(), copy_count=data.get("copy_count", 1),
            notes=data.get("notes") or "", idempotency_key=str(data.get("idempotency_key") or ""), client_id=client_id)
        stock = store.stock_by_type().get(row.get("contract_type"), {})
        free = stock.get("available", 0)
        warn = ""
        if created and free < int(row.get("copy_count") or 1):
            if ctx.manager_view:
                warn = f"ამჟამად ამ ტიპის თავისუფალი ეგზემპლარი: {free}. მოთხოვნა მიღებულია, გაცემა მარაგის შევსების შემდეგ მოხდება."
            else:
                warn = "მოთხოვნა მიღებულია. გაცემა მოხდება, როგორც კი ეგზემპლარი მზად იქნება."
        if created:
            audit(ctx.agent, ctx.admin, "contract_request_created", "contract_request", row["request_id"],
                  metadata={"meeting_id": row["meeting_id"], "type": row["contract_type"], "copies": row["copy_count"]})
            text = (f"📑 ახალი ხელშეკრულების მოთხოვნა {row['request_id']}\n"
                    f"აგენტი: {row['agent_name']}\nტიპი: {m.CONTRACT_TYPES[row['contract_type']]['label']}\n"
                    f"ეგზემპლარი: {row['copy_count']}\nმისამართი: {row['property_address'] or '-'}\n"
                    f"შეხვედრა: {row['meeting_datetime'] or '-'}")
            for cid in _approvers_chat_ids(owner):
                if cid != ctx.chat_id:
                    _safe_notify(cid, text)
        return jsonify(ok=True, created=created, request=_pub_request(row, ctx), stock_warning=warn), (201 if created else 200)

    # ------------------------------------------------------------------ სია / დეტალი
    @app.get("/api/contracts/requests")
    @rate_limited("contracts_read")
    @_guard
    def contracts_list_requests():
        ctx, err = _ctx()
        if err:
            return err
        a = request.args
        rows = _scope_requests(ctx, store.list_requests())
        days = _PERIOD_DAYS.get((a.get("period") or "all").strip().lower(), 0)
        if days:
            cutoff = m.now_local() - datetime.timedelta(days=days)
            rows = [r for r in rows if (m.parse_dt(r.get("request_created_at")) or cutoff) >= cutoff]
        for key, col in (("agent_id", "agent_id"), ("contract_type", "contract_type"), ("language_pair", "language_pair"),
                         ("status", "request_status"), ("meeting_id", "meeting_id"), ("team", "team")):
            v = (a.get(key) or "").strip()
            if v:
                rows = [r for r in rows if str(r.get(col)) == v]
        q = (a.get("q") or "").strip().lower()
        if q:
            qd = m.normalize_phone(q)
            rows = [r for r in rows if q in str(r.get("property_address", "")).lower() or q in str(r.get("property_id", "")).lower()
                    or q in str(r.get("agent_name", "")).lower() or q in str(r.get("request_id", "")).lower()
                    or (qd and qd in m.normalize_phone(r.get("client_phone")))]
        rows.sort(key=lambda r: str(r.get("request_created_at", "")), reverse=True)
        return jsonify(rows=[_pub_request(r, ctx) for r in rows[:400]], count=len(rows))

    @app.get("/api/contracts/requests/<request_id>")
    @rate_limited("contracts_read")
    @_guard
    def contracts_request_detail(request_id):
        ctx, err = _ctx()
        if err:
            return err
        r = store.get_request(request_id, fresh=True)
        if not r or not _can_see_agent(ctx, r.get("agent_id")):
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        issues = [i for i in store.list_issues() if str(i.get("request_id")) == request_id]
        d = _pub_request(r, ctx)
        d["client_phone"] = r.get("client_phone", "")        # უკვე გაფილტრულია უფლებებით (საკუთარი/გუნდი/ადმინი)
        out = {"request": d, "issues": [_pub_issue(i, ctx, full=True) for i in sorted(issues, key=lambda i: str(i.get("issued_at", "")))],
               "caps": _caps(ctx)}
        if ctx.admin:
            out["audit"] = store.list_audit(request_id, 100)
        return jsonify(out)

    # ------------------------------------------------------------------ დამტკიცება / გაუქმება
    @app.post("/api/contracts/requests/<request_id>/approve")
    @rate_limited("contracts_write")
    @_guard
    def contracts_approve(request_id):
        ctx, err = _ctx()
        if err:
            return err
        r = store.get_request(request_id, fresh=True)
        if not r:
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        owner_id = str(r.get("agent_id"))
        if not ctx.admin:
            if owner_id == ctx.agent_id:
                raise ContractError("საკუთარ მოთხოვნას ვერ დაამტკიცებთ", 403)
            allowed = ctx.staff or (ctx.lead and owner_id in _team_ids(ctx.team))
            if not allowed:
                raise ContractError("მოთხოვნის დამტკიცების უფლება არ გაქვთ", 403)
        new = store.approve_request(request_id, ctx.chat_id or ctx.agent_id, ctx.name)
        audit(ctx.agent, ctx.admin, "contract_request_approved", "contract_request", request_id,
              metadata={"reserved": new.get("_reserved", 0)})
        _safe_notify(_agent_chat(owner_id), f"✅ ხელშეკრულების მოთხოვნა {request_id} დამტკიცებულია. "
                                            f"ფიზიკურ ეგზემპლარს მიიღებთ პასუხისმგებელი თანამშრომლისგან.")
        return jsonify(ok=True, request=_pub_request(new, ctx), reserved=new.get("_reserved", 0))

    @app.post("/api/contracts/requests/<request_id>/cancel")
    @rate_limited("contracts_write")
    @_guard
    def contracts_cancel(request_id):
        ctx, err = _ctx()
        if err:
            return err
        r = store.get_request(request_id, fresh=True)
        if not r or not _can_see_agent(ctx, r.get("agent_id")):
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        owner_id = str(r.get("agent_id"))
        mine = ctx.agent_id and owner_id == ctx.agent_id
        manager = ctx.admin or ctx.staff or (ctx.lead and owner_id in _team_ids(ctx.team))
        if not (mine or manager):
            raise ContractError("ამ მოთხოვნის გაუქმების უფლება არ გაქვთ", 403)
        if mine and not manager and str(r.get("request_status")) != m.REQ_REQUESTED:
            raise ContractError("დამტკიცებული მოთხოვნის გაუქმება მხოლოდ მენეჯერს შეუძლია", 403)
        data = request.get_json(silent=True) or {}
        new = store.cancel_request(request_id, ctx.chat_id or ctx.agent_id, data.get("reason") or "")
        audit(ctx.agent, ctx.admin, "contract_request_cancelled", "contract_request", request_id)
        if not mine:
            _safe_notify(_agent_chat(owner_id), f"❌ ხელშეკრულების მოთხოვნა {request_id} გაუქმდა.")
        return jsonify(ok=True, request=_pub_request(new, ctx))

    # ------------------------------------------------------------------ მარაგი (თანამშრომელი)
    def _need_staff(ctx: _Ctx):
        if not ctx.staff:
            raise ContractError("ამ მოქმედების უფლება მხოლოდ პასუხისმგებელ თანამშრომელს/ადმინს აქვს", 403)

    @app.post("/api/contracts/copies")
    @rate_limited("contracts_write")
    @_guard
    def contracts_register_copies():
        ctx, err = _ctx()
        if err:
            return err
        _need_staff(ctx)
        data = request.get_json(silent=True) or {}
        created = store.register_copies(str(data.get("contract_type") or ""), data.get("quantity", 1),
                                        ctx.chat_id or ctx.agent_id, data.get("storage_location") or "", data.get("condition") or "ახალი")
        audit(ctx.agent, ctx.admin, "contract_copies_registered", "contract_copy", created[0]["copy_id"] if created else "",
              metadata={"count": len(created), "type": data.get("contract_type")})
        return jsonify(ok=True, count=len(created), copies=[_pub_copy(c) for c in created]), 201

    @app.get("/api/contracts/copies")
    @rate_limited("contracts_read")
    @_guard
    def contracts_list_copies():
        ctx, err = _ctx()
        if err:
            return err
        if not ctx.manager_view:
            raise ContractError("წვდომა არ გაქვთ", 403)
        a = request.args
        rows = store.list_copies()
        for key in ("contract_type", "language_pair", "physical_status"):
            v = (a.get(key) or "").strip()
            if v:
                rows = [c for c in rows if str(c.get(key)) == v]
        if not (ctx.admin or ctx.staff):
            # თიმლიდერი: მხოლოდ პრობლემური ეგზემპლარები და გუნდის აგენტებთან გატანილები
            team_issues = {str(i.get("copy_id")) for i in store.list_issues()
                           if store.is_open_issue(i) and _can_see_agent(ctx, i.get("agent_id"))}
            rows = [c for c in rows if str(c.get("physical_status")) in (m.PH_UNDER_REVIEW, m.PH_DAMAGED, m.PH_LOST)
                    or str(c.get("copy_id")) in team_issues]
        q = (a.get("q") or "").strip().upper()
        if q:
            rows = [c for c in rows if q in str(c.get("control_code", "")).upper()]
        return jsonify(rows=[_pub_copy(c) for c in rows[-600:]], count=len(rows))

    @app.get("/api/contracts/copies/<copy_id>/history")
    @rate_limited("contracts_read")
    @_guard
    def contracts_copy_history(copy_id):
        ctx, err = _ctx()
        if err:
            return err
        if not ctx.manager_view:
            raise ContractError("წვდომა არ გაქვთ", 403)
        c = store.get_copy(copy_id, fresh=True)
        if not c:
            raise ContractError("ეგზემპლარი ვერ მოიძებნა", 404)
        issues = [i for i in store.list_issues() if str(i.get("copy_id")) == copy_id]
        if not (ctx.admin or ctx.staff):
            issues = [i for i in issues if _can_see_agent(ctx, i.get("agent_id"))]
        out = {"copy": _pub_copy(c), "issues": [_pub_issue(i, ctx, full=True) for i in sorted(issues, key=lambda i: str(i.get("issued_at", "")), reverse=True)]}
        if ctx.admin:
            out["audit"] = store.list_audit(copy_id, 100)
        return jsonify(out)

    @app.get("/api/contracts/available")
    @rate_limited("contracts_read")
    @_guard
    def contracts_available():
        ctx, err = _ctx()
        if err:
            return err
        _need_staff(ctx)
        t = (request.args.get("contract_type") or "").strip()
        rid = (request.args.get("request_id") or "").strip()
        rows = []
        for c in store.list_copies():
            if t and str(c.get("contract_type")) != t:
                continue
            st = str(c.get("physical_status"))
            if (st == m.PH_AVAILABLE or (st == m.PH_RESERVED and rid and str(c.get("reserved_request_id")) == rid)) \
                    and not str(c.get("active_issue_id")):
                rows.append(c)
        rows.sort(key=lambda c: (str(c.get("physical_status")) != m.PH_RESERVED, str(c.get("created_at", ""))))
        return jsonify(rows=[_pub_copy(c) for c in rows[:300]], count=len(rows))

    # ------------------------------------------------------------------ გაცემა / დაბრუნება (მხოლოდ თანამშრომელი)
    @app.post("/api/contracts/requests/<request_id>/issue")
    @rate_limited("contracts_write")
    @_guard
    def contracts_issue(request_id):
        ctx, err = _ctx()
        if err:
            return err
        _need_staff(ctx)
        r = store.get_request(request_id, fresh=True)
        if not r:
            raise ContractError("მოთხოვნა ვერ მოიძებნა", 404)
        if not ctx.admin and str(r.get("agent_id")) == ctx.agent_id:
            raise ContractError("საკუთარ მოთხოვნაზე გაცემას ვერ დაადასტურებთ", 403)
        data = request.get_json(silent=True) or {}
        issues = store.issue_copies(request_id, data.get("copy_ids") or [], ctx.chat_id or ctx.agent_id, ctx.name,
                                    data.get("due_at") or "", data.get("notes") or "")
        audit(ctx.agent, ctx.admin, "contract_copies_issued", "contract_request", request_id,
              metadata={"count": len(issues), "codes": [i["control_code"] for i in issues]})
        # აგენტს საკონტროლო კოდი არ ეგზავნება — მხოლოდ რაოდენობა, ტიპი, მისამართი და ვადა
        _safe_notify(_agent_chat(r.get("agent_id")),
                     f"📑 გადმოგეცათ ხელშეკრულება ({len(issues)} ეგზ.) — {r.get('property_address') or 'შეხვედრა'}\n"
                     f"დაბრუნების ვადა: {issues[0]['due_at']}\nმოთხოვნა: {request_id}")
        return jsonify(ok=True, issues=[_pub_issue(i, ctx, full=True) for i in issues])

    @app.post("/api/contracts/issues/<issue_id>/return")
    @rate_limited("contracts_write")
    @_guard
    def contracts_return(issue_id):
        ctx, err = _ctx()
        if err:
            return err
        _need_staff(ctx)
        i = store.get_issue(issue_id, fresh=True)
        if not i:
            raise ContractError("გაცემის ჩანაწერი ვერ მოიძებნა", 404)
        holder_chat = _agent_chat(i.get("agent_id"))
        # აგენტი ვერ ადასტურებს საკუთარი დოკუმენტის დაბრუნებას (ადმინიც კი — იგივე პირი)
        if (ctx.agent_id and str(i.get("agent_id")) == ctx.agent_id) or (
                holder_chat is not None and ctx.chat_id is not None and int(ctx.chat_id) == holder_chat):
            raise ContractError("საკუთარი დოკუმენტის დაბრუნებას თქვენ ვერ დაადასტურებთ — სხვა უფლებამოსილი თანამშრომელი საჭიროა", 403)
        data = request.get_json(silent=True) or {}
        new = store.return_issue(
            issue_id, ctx.chat_id or ctx.agent_id, ctx.name, outcome=str(data.get("outcome") or ""),
            reusable=bool(data.get("reusable")), condition=str(data.get("condition") or ""),
            reason=str(data.get("reason") or ""), notes=str(data.get("notes") or ""),
            signed_number=str(data.get("signed_contract_number") or ""))
        audit(ctx.agent, ctx.admin, "contract_copy_returned", "contract_issue", issue_id,
              metadata={"outcome": new.get("outcome") if new else ""})
        _safe_notify(holder_chat, f"✅ ხელშეკრულების დაბრუნება დაფიქსირდა — {i.get('property_address') or i.get('request_id')}")
        return jsonify(ok=True, issue=_pub_issue(new or i, ctx, full=True))

    @app.post("/api/contracts/copies/<copy_id>/review")
    @rate_limited("contracts_write")
    @_guard
    def contracts_review(copy_id):
        ctx, err = _ctx()
        if err:
            return err
        _need_staff(ctx)
        data = request.get_json(silent=True) or {}
        new = store.review_copy(copy_id, str(data.get("decision") or ""), ctx.chat_id or ctx.agent_id, data.get("note") or "")
        audit(ctx.agent, ctx.admin, "contract_copy_reviewed", "contract_copy", copy_id, metadata={"decision": data.get("decision")})
        return jsonify(ok=True, copy=_pub_copy(new))

    @app.post("/api/contracts/requests/<request_id>/close-remaining")
    @rate_limited("contracts_write")
    @_guard
    def contracts_close_remaining(request_id):
        ctx, err = _ctx()
        if err:
            return err
        _need_staff(ctx)
        new = store.close_remaining(request_id, ctx.chat_id or ctx.agent_id)
        audit(ctx.agent, ctx.admin, "contract_request_remaining_closed", "contract_request", request_id)
        return jsonify(ok=True, request=_pub_request(new, ctx))

    # ------------------------------------------------------------------ აუდიტი (მხოლოდ ადმინი)
    @app.get("/api/contracts/audit")
    @rate_limited("contracts_read")
    @_guard
    def contracts_audit():
        ctx, err = _ctx()
        if err:
            return err
        if not ctx.admin:
            raise ContractError("აუდიტის ისტორია მხოლოდ ადმინს ჩანს", 403)
        return jsonify(rows=store.list_audit((request.args.get("entity_id") or "").strip(), 300))
