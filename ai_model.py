"""
Safe Home AI — მონაცემთა მოდელი: ცხრილები, კატეგორიები, ვალიდაცია. შენახვა — `ai_store.py`, ძიება — `ai_knowledge.py`, პასუხის ნაკადი — `ai_service.py`.

ძირითადი პრინციპი: **AI-ს პასუხი ან აგენტის ნათქვამი არასდროს ხდება კომპანიის წესი.** წესი ხდება მხოლოდ მაშინ, როცა უფლებამოსილი მენეჯერი/ადმინი
დრაფტს ღილაკით აქვეყნებს; ყოველი ვერსია ინახება (`AiKnowledgeVersions`) და ყოველი გამოქვეყნება იწერება AuditLog-ში.
"""

from __future__ import annotations

import datetime
import re
import uuid

# ---------------------------------------------------------------- ცხრილები
KB_SHEET = "AiKnowledge"
KB_VERSIONS_SHEET = "AiKnowledgeVersions"
MESSAGES_SHEET = "AiMessages"
FEEDBACK_SHEET = "AiFeedback"
REVIEW_SHEET = "AiReviewQueue"

# AiKnowledge — „თავი“: მიმდინარე გამოქვეყნებული ვერსია (ან დრაფტი, თუ ჯერ არ გამოქვეყნებულა)
KB_HEADERS = [
    "kb_id", "title", "body", "category", "language", "owner", "status", "version", "effective_from", "effective_to",
    "scope_team", "source", "source_ref", "created_by", "created_at", "updated_at", "approved_by", "approved_at",
]
# AiKnowledgeVersions — ყოველი ვერსია/გადასინჯვა (ისტორია არასდროს იშლება)
VERSION_HEADERS = [
    "version_id", "kb_id", "version", "title", "body", "category", "language", "effective_from", "effective_to", "scope_team",
    "status", "changed_by", "approved_by", "reason", "at",
]
MESSAGE_HEADERS = [
    "msg_id", "conv_id", "agent_id", "team", "role", "text", "answer_type", "sources", "confidence", "needs_manager",
    "tokens_in", "tokens_out", "cost_usd", "latency_ms", "model", "lang", "outcome", "created_at", "expires_at",
]
FEEDBACK_HEADERS = ["feedback_id", "msg_id", "agent_id", "team", "rating", "reason", "comment", "created_at"]
REVIEW_HEADERS = [
    "item_id", "type", "status", "question_text", "draft_title", "draft_body", "category", "source_question_id", "source_msg_id",
    "team", "similar_count", "kb_id", "created_at", "decided_by", "decided_at", "note",
]
ALL_TABS = [
    (KB_SHEET, KB_HEADERS, 500),
    (KB_VERSIONS_SHEET, VERSION_HEADERS, 1000),
    (MESSAGES_SHEET, MESSAGE_HEADERS, 5000),
    (FEEDBACK_SHEET, FEEDBACK_HEADERS, 1000),
    (REVIEW_SHEET, REVIEW_HEADERS, 1000),
]

# ---------------------------------------------------------------- კატეგორიები / სტატუსები
KB_CATEGORIES = {
    "policy": "კომპანიის პოლიტიკა/წესები",
    "commission": "საკომისიო და თანამშრომლობის პირობები",
    "legal": "იურიდიული საკითხები",
    "finance": "ფინანსური წესები",
    "procedure": "სამუშაო პროცედურა",
    "crm_guide": "CRM-ის გამოყენება",
    "faq": "ხშირი კითხვა (დამტკიცებული პასუხი)",
}
KB_DRAFT, KB_APPROVED, KB_RETIRED = "draft", "approved", "retired"
KB_STATUSES = (KB_DRAFT, KB_APPROVED, KB_RETIRED)
V_DRAFT, V_PUBLISHED, V_SUPERSEDED, V_REJECTED, V_RETIRED = "draft", "published", "superseded", "rejected", "retired"
LANGS = ("ka", "ru", "en", "any")

# პასუხის წყაროს ოთხი ტიპი (ყოველ პასუხს აქვს ერთ-ერთი)
A_POLICY, A_SYSTEM, A_GENERAL, A_UNVERIFIED = "policy", "system_data", "general", "unverified"
ANSWER_TYPES = {
    A_POLICY: "📘 დამტკიცებული კომპანიის წესი",
    A_SYSTEM: "📊 დადასტურებული სისტემის მონაცემი",
    A_GENERAL: "💡 ზოგადი პროფესიული რჩევა (კომპანიის წესი არ არის)",
    A_UNVERIFIED: "❓ დაუდასტურებელი — საიმედო პასუხი ვერ ვიპოვე",
}
CONFIDENCES = ("high", "medium", "low")

R_CANDIDATE, R_UNANSWERED, R_FEEDBACK, R_CONFLICT = "candidate", "unanswered", "feedback", "conflict"
REVIEW_TYPES = (R_CANDIDATE, R_UNANSWERED, R_FEEDBACK, R_CONFLICT)
RV_OPEN, RV_PUBLISHED, RV_DISMISSED = "open", "converted", "dismissed"

RATINGS = ("up", "down", "report")
FEEDBACK_REASONS = ("wrong", "incomplete", "outdated", "unclear", "other")

# Mini App-ის როლები (იხ. webserver._authed_agent): admin / team_lead / agent
ROLE_ADMIN, ROLE_LEAD, ROLE_AGENT = "admin", "team_lead", "agent"


class AiError(Exception):
    def __init__(self, msg: str, status: int = 400, code: str = "", extra: dict | None = None):
        super().__init__(msg)
        self.status = status
        self.code = code
        self.extra = extra or {}


# ---------------------------------------------------------------- დამხმარეები
def s(v, cap: int = 300) -> str:
    return str(v if v is not None else "").strip()[:cap]


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def now_dt() -> datetime.datetime:
    import crm_time
    return crm_time.local_now().replace(tzinfo=None)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return now_dt().strftime("%Y-%m-%d")


def parse_dt(v) -> datetime.datetime | None:
    t = str(v or "").strip()
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.datetime.strptime(t[:n], fmt)
        except ValueError:
            continue
    return None


def _date(v, label: str) -> str:
    t = s(v, 12)
    if not t:
        return ""
    try:
        return datetime.datetime.strptime(t[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise AiError(f"{label}: ფორმატი წწწწ-თთ-დდ") from None


def parse_kb_input(data: dict, existing: dict | None = None) -> dict:
    """ცოდნის ბაზის ჩანაწერის ვალიდირებული ველები. `existing` — რედაქტირებისას გაუცვლელი ველები რჩება."""
    data = data or {}
    out: dict = {}
    base = existing or {}

    def pick(key, default=""):
        return data[key] if key in data else base.get(key, default)

    title = s(pick("title"), 160)
    body = s(pick("body"), 6000)
    if len(title) < 3:
        raise AiError("სათაური სავალდებულოა (მინიმუმ 3 სიმბოლო)")
    if len(body) < 10:
        raise AiError("ტექსტი სავალდებულოა (მინიმუმ 10 სიმბოლო)")
    cat = s(pick("category", "policy"), 30).lower()
    if cat not in KB_CATEGORIES:
        raise AiError("უცნობი კატეგორია: " + ", ".join(KB_CATEGORIES))
    lang = s(pick("language", "any"), 4).lower() or "any"
    if lang not in LANGS:
        raise AiError("ენა: ka / ru / en / any")
    out.update(title=title, body=body, category=cat, language=lang,
               owner=s(pick("owner"), 80),
               effective_from=_date(pick("effective_from"), "მოქმედების დაწყება"),
               effective_to=_date(pick("effective_to"), "მოქმედების დასასრული"),
               scope_team=s(pick("scope_team"), 80))
    if out["effective_from"] and out["effective_to"] and out["effective_from"] > out["effective_to"]:
        raise AiError("მოქმედების დასაწყისი დასასრულზე გვიანაა")
    return out


def kb_live(row: dict, today: str | None = None, team: str | None = None) -> bool:
    """AI-სთვის ხელმისაწვდომია მხოლოდ დამტკიცებული, ამჟამად მოქმედი და (მოთხოვნისას) ამ გუნდისთვის განკუთვნილი ჩანაწერი."""
    today = today or today_str()
    if s(row.get("status")) != KB_APPROVED:
        return False
    ef, et = s(row.get("effective_from"), 12), s(row.get("effective_to"), 12)
    if ef and today < ef:
        return False
    if et and today > et:
        return False
    sc = s(row.get("scope_team"), 80)
    if sc and team is not None and sc != s(team, 80):
        return False
    return True


_WS = re.compile(r"\s+")


def norm_text(t: str) -> str:
    return _WS.sub(" ", str(t or "").strip().lower())
