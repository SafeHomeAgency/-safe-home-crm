"""
ექსთენშენის ანგარიშები (Chrome Web Store-იდან დაყენებული „Safe Home – MyHome ავტო-ატვირთვა“).

ნაკადი:
  1. აგენტი ექსთენშენში ავსებს ფორმას (სახელი, ტელეფონი, საკონტაქტო სახელი/ნომერი) -> POST /ext/v1/request.
     სერვერი ქმნის „pending“ მოთხოვნას და ადმინებს Telegram-ში უგზავნის შეტყობინებას ღილაკებით.
  2. ადმინი ადასტურებს (Telegram-ის ღილაკი ან Mini App → MyHome → ⚙️ ანგარიშები) ან უარყოფს.
  3. ექსთენშენი რამდენიმე წამში ერთხელ ეკითხება სტატუსს (GET /ext/v1/request/<id>?token=…). დადასტურების შემდეგ
     **ერთხელ** იღებს პირად API გასაღებს — სერვერზე ინახება მხოლოდ მისი SHA-256 ჰეში.
  4. გასაღები მუშაობს მხოლოდ თავისი იარლიყის (manager_label) job-ებზე და მანამ, სანამ ადმინი არ წაშლის (revoke).

უსაფრთხოება:
  * MyHome-ის პაროლი არასდროს მოდის სერვერზე — აგენტი MyHome-ში თავისივე ბრაუზერში შედის;
  * გასაღები ჩანს მხოლოდ ერთხელ (ექსთენშენისთვის); ჩანაწერში მხოლოდ ჰეშია;
  * საჯარო endpoint-ებს აქვს IP-ზე ლიმიტი; poll-token-ის გარეშე სტატუსს ვერავინ ნახავს.

საცავი: AppSettings ცხრილის ერთი გასაღები (`ext_accounts_v1`, JSON) — ახალი ცხრილის/სქემის გარეშე მუშაობს
როგორც Google Sheets, ისე Postgres ბექენდზე.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import jsonify, request

log = logging.getLogger("safehome-ext-accounts")

SETTING_KEY = "ext_accounts_v1"
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")
CACHE_SEC = 20
MAX_PENDING = 30

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}
_sheets = None          # register()-ში ივსება
_notify_admins = None   # (text, reply_markup) -> None


# ------------------------------------------------------------------ საცავი
def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load(fresh: bool = False) -> dict:
    if not fresh and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_SEC:
        return _cache["data"]
    raw = ""
    try:
        raw = (_sheets.get_app_settings() or {}).get(SETTING_KEY, "") if _sheets else ""
    except Exception:  # noqa: BLE001
        log.exception("ext accounts: AppSettings ვერ წავიკითხე")
        if _cache["data"] is not None:
            return _cache["data"]
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        log.error("ext accounts: AppSettings-ის JSON დაზიანებულია — ცარიელით ვიწყებ")
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", {})
    _cache.update(at=time.time(), data=data)
    return data


def _save(data: dict, by: str = "") -> None:
    _sheets.set_app_setting(SETTING_KEY, json.dumps(data, ensure_ascii=False, separators=(",", ":")), by)
    _cache.update(at=time.time(), data=data)


def _hash(v: str) -> str:
    return hashlib.sha256(str(v).encode("utf-8")).hexdigest()


def _digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _public(rec: dict) -> dict:
    """ადმინისთვის ჩვენება — ჰეშების/ტოკენების გარეშე."""
    return {k: v for k, v in rec.items() if k not in ("key_hash", "poll_hash")}


# ------------------------------------------------------------------ webserver-ის/ბოტის გამოსაყენებელი
def label_for_key(bearer: str) -> str | None:
    """Authorization header-იდან (Bearer <key>) — დადასტურებული ექსთენშენის იარლიყი, ან None."""
    tok = str(bearer or "")
    if tok.startswith("Bearer "):
        tok = tok[7:]
    tok = tok.strip()
    if not tok.startswith("shx_") or len(tok) < 20:
        return None
    h = _hash(tok)
    for rec in _load().get("items", {}).values():
        if rec.get("status") == "approved" and rec.get("key_hash") and hmac.compare_digest(rec["key_hash"], h):
            return rec.get("label")
    return None


def label_for_agent(agent_id: str) -> str | None:
    """აგენტზე პირადად მიბმული (mode=agent) დადასტურებული ექსთენშენის იარლიყი — job ამ ანგარიშით დაიდება."""
    aid = str(agent_id or "").strip()
    if not aid:
        return None
    for rec in _load().get("items", {}).values():
        if rec.get("status") == "approved" and rec.get("mode") == "agent" and str(rec.get("agent_id", "")) == aid:
            return rec.get("label")
    return None


def _taken_labels(data: dict) -> set:
    out = {str(r.get("label", "")) for r in data.get("items", {}).values() if r.get("status") in ("pending", "approved")}
    try:
        out |= {str(a.get("manager_label", "")).strip().lower() for a in _sheets.get_myhome_accounts()}
    except Exception:  # noqa: BLE001
        pass
    return out


_TRANSLIT = dict(zip("აბგდევზთიკლმნოპჟრსტუფქღყშჩცძწჭხჯჰ",
                     ["a", "b", "g", "d", "e", "v", "z", "t", "i", "k", "l", "m", "n", "o", "p", "zh", "r", "s", "t", "u",
                      "p", "k", "gh", "q", "sh", "ch", "ts", "dz", "ts", "ch", "kh", "j", "h"]))


def _make_label(name: str, taken: set) -> str:
    base = "".join(_TRANSLIT.get(ch, ch) for ch in str(name or "").lower())
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:24] or "agent"
    if not base[0].isalnum():
        base = "a" + base
    cand = f"{base}-ext"
    i = 2
    while cand in taken or not LABEL_RE.match(cand):
        cand = f"{base}-ext{i}"
        i += 1
    return cand


def decide(req_id: str, action: str, *, by: str = "", team: str = "", agent_id: str = "", mode: str = "") -> tuple[bool, str, dict | None]:
    """approve / reject / revoke. აბრუნებს (ok, შეტყობინება, ჩანაწერი)."""
    action = str(action or "").strip()
    with _lock:
        data = _load(fresh=True)
        rec = data["items"].get(str(req_id))
        if not rec:
            return False, "მოთხოვნა ვერ მოიძებნა", None
        st = rec.get("status")
        if action == "approve":
            if st == "approved":
                return True, "უკვე დადასტურებულია", _public(rec)
            if st != "pending":
                return False, f"ამ მოთხოვნის სტატუსია „{st}“ — დადასტურება აღარ შეიძლება", _public(rec)
            mode = mode or rec.get("mode") or ("agent" if (agent_id or rec.get("agent_id")) else "team")
            if mode == "team":
                team = str(team or rec.get("team") or "").strip()
                if not team:
                    return False, "აირჩიეთ თიმი (Mini App → MyHome → ⚙️ ანგარიშები)", _public(rec)
                rec["team"] = team
            else:
                aid = str(agent_id or rec.get("agent_id") or "").strip()
                if not aid:
                    return False, "აგენტი ვერ დადგინდა — Mini App-ში აირჩიეთ აგენტი ან თიმი", _public(rec)
                rec["agent_id"] = aid
            rec["mode"] = mode
            rec["status"] = "approved"
        elif action == "reject":
            if st != "pending":
                return False, f"სტატუსია „{st}“", _public(rec)
            rec["status"] = "rejected"
        elif action == "revoke":
            if st not in ("approved", "pending"):
                return False, f"სტატუსია „{st}“", _public(rec)
            rec["status"] = "revoked"
            rec["key_hash"] = ""
        else:
            return False, "უცნობი მოქმედება", None
        rec["decided_at"] = _now()
        rec["decided_by"] = str(by)[:60]
        _save(data, by)
    # თიმზე მიბმა MyHomeAccounts-ში (lock-ის გარეთ — Sheets-ის ჩაწერა ნელია)
    if action == "approve" and rec.get("mode") == "team":
        try:
            _sheets.set_myhome_account(rec["team"], rec["label"], rec.get("name", ""))
        except Exception:  # noqa: BLE001
            log.exception("MyHomeAccounts-ში მიბმა ვერ მოხერხდა")
            return True, "დადასტურდა, მაგრამ თიმზე მიბმა ვერ ჩაიწერა — სცადეთ ხელახლა", _public(rec)
    return True, {"approve": "✅ დადასტურდა", "reject": "❌ უარყოფილია", "revoke": "🗑 წაიშალა — გასაღები აღარ მუშაობს"}[action], _public(rec)


def describe(rec: dict) -> str:
    who = rec.get("agent_name") or rec.get("name") or "?"
    lines = [
        "🧩 MyHome ექსთენშენის ანგარიშის მოთხოვნა",
        f"სახელი: {rec.get('name', '')}",
        f"ტელეფონი: {rec.get('phone', '')}",
    ]
    if rec.get("agent_id"):
        lines.append(f"CRM-ის აგენტი: {who}" + (f" (თიმი {rec.get('agent_team')})" if rec.get("agent_team") else ""))
    else:
        lines.append("CRM-ში ამ ნომრით აგენტი ვერ მოიძებნა — დადასტურებისას Mini App-ში აირჩიეთ თიმი")
    if rec.get("myhome_email"):
        lines.append(f"MyHome ანგარიში: {rec['myhome_email']}")
    lines.append(f"განცხადებაზე: {rec.get('contact_name', '')} · {rec.get('contact_phone', '')}")
    lines.append(f"იარლიყი: {rec.get('label')}  ·  მოწყობილობა: {rec.get('device', '')}")
    return "\n".join(lines)


def buttons(req_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ დადასტურება", "callback_data": f"exa_ok:{req_id}"},
        {"text": "❌ უარყოფა", "callback_data": f"exa_no:{req_id}"},
    ]]}


# ------------------------------------------------------------------ IP ლიმიტი (საჯარო endpoint-ებისთვის)
_hits: dict = {}


def _ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else (request.remote_addr or "")) or "unknown"


def _limited(bucket: str, limit: int, window: int) -> bool:
    now = time.time()
    k = (bucket, _ip())
    arr = [t for t in _hits.get(k, []) if now - t < window]
    if len(arr) >= limit:
        _hits[k] = arr
        return True
    arr.append(now)
    _hits[k] = arr
    if len(_hits) > 5000:
        _hits.clear()
    return False


def init(sheets) -> None:
    """ბოტის პროცესისთვის (Flask-ის გარეშე): საცავის მიბმა, რომ decide() იმუშაოს."""
    global _sheets
    if _sheets is None:
        _sheets = sheets


# ------------------------------------------------------------------ Flask
def register(app, *, authed, authed_worker, audit, sheets, get_agents, notify_admins, sheety_url: str = "") -> None:
    global _sheets, _notify_admins
    _sheets = sheets
    _notify_admins = notify_admins

    def _no_store(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def _find_agent(phone: str):
        d = _digits(phone)[-9:]
        if len(d) < 9:
            return None
        for a in get_agents() or []:
            for f in ("phone", "phone_number", "mobile"):
                if _digits(a.get(f))[-9:] == d:
                    return a
        return None

    # --- ექსთენშენი: მოთხოვნა -------------------------------------------------
    @app.post("/ext/v1/request")
    def ext_request():
        if _limited("ext_req", 6, 3600):
            return jsonify(error="ძალიან ბევრი მოთხოვნა — სცადეთ ერთ საათში"), 429
        b = request.get_json(silent=True) or {}
        name = str(b.get("name") or "").strip()[:60]
        phone = str(b.get("phone") or "").strip()[:30]
        contact_name = str(b.get("contact_name") or name).strip()[:60]
        contact_phone = str(b.get("contact_phone") or phone).strip()[:30]
        email = str(b.get("myhome_email") or "").strip()[:80]
        device = str(b.get("device") or "").strip()[:60]
        if len(name) < 2:
            return jsonify(error="შეიყვანეთ სახელი და გვარი"), 400
        if len(_digits(phone)) < 9:
            return jsonify(error="ტელეფონი არასწორია — მინიმუმ 9 ციფრი"), 400
        if len(_digits(contact_phone)) < 9:
            return jsonify(error="საკონტაქტო ნომერი არასწორია — მინიმუმ 9 ციფრი"), 400
        agent = _find_agent(phone)
        poll = secrets.token_urlsafe(24)
        with _lock:
            data = _load(fresh=True)
            pending = [r for r in data["items"].values() if r.get("status") == "pending"]
            if len(pending) >= MAX_PENDING:
                return jsonify(error="ძალიან ბევრი დაუდასტურებელი მოთხოვნაა — მიმართეთ ადმინს"), 429
            req_id = secrets.token_hex(6)
            rec = {
                "id": req_id, "status": "pending", "created_at": _now(),
                "name": name, "phone": phone, "contact_name": contact_name, "contact_phone": contact_phone,
                "myhome_email": email, "device": device,
                "label": _make_label(name, _taken_labels(data)),
                "agent_id": str((agent or {}).get("agent_id", "")), "agent_name": str((agent or {}).get("name", "")),
                "agent_team": str((agent or {}).get("team", "")),
                "mode": "agent" if agent else "team", "team": "",
                "poll_hash": _hash(poll), "key_hash": "", "key_issued": False,
            }
            data["items"][req_id] = rec
            _save(data, "ext-request")
        try:
            notify_admins(describe(rec), buttons(req_id))
        except Exception:  # noqa: BLE001
            log.exception("ადმინს შეტყობინება ვერ გაეგზავნა")
        log.info("ექსთენშენის მოთხოვნა: id=%s label=%s agent=%s", req_id, rec["label"], rec["agent_id"] or "-")
        return _no_store(jsonify(ok=True, request_id=req_id, poll_token=poll, label=rec["label"]))

    @app.get("/ext/v1/request/<req_id>")
    def ext_request_status(req_id):
        if _limited("ext_poll", 240, 3600):
            return jsonify(error="ძალიან ხშირი შემოწმება"), 429
        token = str(request.args.get("token") or "")
        data = _load()
        rec = data["items"].get(str(req_id))
        if not rec or not token or not hmac.compare_digest(rec.get("poll_hash", ""), _hash(token)):
            return jsonify(error="მოთხოვნა ვერ მოიძებნა"), 404
        st = rec.get("status")
        out = {"status": st, "label": rec.get("label")}
        if st == "approved" and not rec.get("key_issued"):
            key = "shx_" + secrets.token_urlsafe(32)
            with _lock:
                data = _load(fresh=True)
                rec = data["items"].get(str(req_id))
                if rec and rec.get("status") == "approved" and not rec.get("key_issued"):
                    rec["key_hash"] = _hash(key)
                    rec["key_issued"] = True
                    rec["key_issued_at"] = _now()
                    _save(data, "ext-key")
                    out.update(api_key=key, contact_name=rec.get("contact_name", ""), contact_phone=rec.get("contact_phone", ""))
                    log.info("ექსთენშენს გასაღები გადაეცა: id=%s label=%s", req_id, rec.get("label"))
        elif st == "approved":
            out["already_issued"] = True
        return _no_store(jsonify(out))

    # --- ექსთენშენი: „ბაზა“ ცხრილი სერვერის გავლით (Sheety-ის მისამართი ექსთენშენში აღარ ინახება) ----------
    def _sheety(method: str, suffix: str = "", body: dict | None = None):
        if not sheety_url:
            return jsonify(error="SHEETY_URL არ არის დაყენებული სერვერზე"), 503
        url = sheety_url.rstrip("/") + suffix
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return app.response_class(r.read(), status=r.status, mimetype="application/json")
        except urllib.error.HTTPError as e:
            return app.response_class(e.read(), status=e.code, mimetype="application/json")
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"ბაზა მიუწვდომელია: {type(e).__name__}"), 502

    @app.route("/internal/ext/base", methods=["GET", "POST"])
    def ext_base():
        err = authed_worker()
        if err:
            return err
        if request.method == "POST":
            return _sheety("POST", "", request.get_json(silent=True) or {})
        q = {k: v for k, v in request.args.items() if k.startswith("filter[")}
        return _sheety("GET", ("?" + urllib.parse.urlencode(q)) if q else "")

    @app.put("/internal/ext/base/<int:row_id>")
    def ext_base_put(row_id):
        err = authed_worker()
        if err:
            return err
        return _sheety("PUT", f"/{row_id}", request.get_json(silent=True) or {})

    # --- ადმინი (Mini App) ---------------------------------------------------
    def _admin():
        agent, admin, err = authed()
        if err:
            return None, err
        if not admin:
            return None, (jsonify(error="მხოლოდ ადმინისთვის"), 403)
        return agent, None

    @app.get("/api/ext-accounts")
    def ext_accounts_list():
        agent, err = _admin()
        if err:
            return err
        items = sorted(_load(fresh=True)["items"].values(), key=lambda r: r.get("created_at", ""), reverse=True)
        teams = sorted({str(a.get("team", "")).strip() for a in get_agents() if str(a.get("team", "")).strip()})
        agents = [{"agent_id": a.get("agent_id"), "name": a.get("name"), "team": a.get("team")} for a in get_agents()]
        return _no_store(jsonify(rows=[_public(r) for r in items if r.get("status") != "rejected"][:100], teams=teams, agents=agents))

    @app.post("/api/ext-accounts/<req_id>/<action>")
    def ext_accounts_decide(req_id, action):
        agent, err = _admin()
        if err:
            return err
        if action not in ("approve", "reject", "revoke"):
            return jsonify(error="უცნობი მოქმედება"), 400
        b = request.get_json(silent=True) or {}
        by = str((agent or {}).get("name") or "admin")
        ok, msg, rec = decide(req_id, action, by=by, team=str(b.get("team") or ""), agent_id=str(b.get("agent_id") or ""),
                              mode=str(b.get("mode") or ""))
        try:
            audit(agent, True, f"ext_account_{action}", "ext_account", req_id,
                  metadata={"ok": ok, "label": (rec or {}).get("label"), "mode": (rec or {}).get("mode"), "team": (rec or {}).get("team")})
        except Exception:  # noqa: BLE001
            pass
        if not ok:
            return _no_store(jsonify(ok=False, error=msg, message=msg, row=rec)), 409
        return _no_store(jsonify(ok=True, message=msg, row=rec))

    # --- კონფიდენციალურობის პოლიტიკა (Chrome Web Store-ს სჭირდება საჯარო ბმული) -----------------------
    @app.get("/ext/privacy")
    def ext_privacy():
        return app.response_class(PRIVACY_HTML, mimetype="text/html")


PRIVACY_HTML = """<!doctype html><html lang="ka"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Safe Home – MyHome Auto-Upload: Privacy Policy</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;line-height:1.6;color:#1b1b1b}h1{font-size:22px}h2{font-size:17px;margin-top:24px}</style></head><body>
<h1>Safe Home – MyHome Auto-Upload — Privacy Policy</h1>
<p>This extension is an internal tool of the Safe Home real-estate agency. It is used only by agents approved by the agency administrator.</p>
<h2>What it does</h2>
<p>It takes listing tasks from the agency CRM queue and fills in the listing form on myhome.ge (and optionally ss.ge) in the agent's own browser, using the agent's own logged-in MyHome account.</p>
<h2>Data it handles</h2>
<ul>
<li><b>Registration data</b> the agent enters (name, phone number, the contact name and phone shown on listings, optional MyHome e-mail) is sent to the agency CRM server so the administrator can approve the device.</li>
<li><b>Listing data</b> (address, price, photos, description, owner phone number entered by the agent in the CRM) is read from the CRM and from public myhome.ge listing pages and is submitted to myhome.ge/ss.ge.</li>
<li><b>Results</b> (new listing ID, status, error messages) are sent back to the agency CRM.</li>
</ul>
<h2>What it never does</h2>
<ul>
<li>It never reads, stores or transmits passwords. The agent logs in to MyHome themselves.</li>
<li>It does not sell or share data with third parties, does not show ads and does not track browsing.</li>
</ul>
<h2>Storage</h2>
<p>A personal access key and settings are stored locally in Chrome (chrome.storage). The administrator can revoke the key at any time; removing the extension deletes local data.</p>
<h2>Contact</h2><p>Safe Home agency administrator, via the agency Telegram bot.</p>
</body></html>"""
