"""
CRM 2.0 (P2) — მონაცემთა მოდელი Google Sheets-ზე.

ეს მოდული მხოლოდ **განმარტებებია** (ცხრილების სათაურები, სტატუსები, ტელეფონის
ნორმალიზაცია, ID-ები). არც Sheets-ს ეხება, არც არსებულ ცხრილებს. ძველი ცხრილები
(Tasks / Reports / Meetings / Exclusives / ...) უცვლელია — CRM 2.0 ცხრილები მათ გვერდით
**ემატება** და ძველი ინფორმაცია backfill-ით (ჯერ dry-run) გადმოიწერება.

წესები:
  * ყველა ველი TEXT-ია (როგორც სხვა ცხრილებში);
  * დროის ველები — UTC ISO `YYYY-MM-DDTHH:MM:SSZ` (ცალსახა; ძველი ცხრილების სერვერის naive
    დროსთან არ ირევა);
  * წაშლა არასდროს ფიზიკურია — `archived = "yes"`;
  * ახალი სვეტი მომავალში მხოლოდ **ბოლოში** ემატება.
"""

from __future__ import annotations

import datetime
import re
import uuid

# ---- ცხრილების სახელები ----
CLIENTS_SHEET = "Clients"
OWNERS_SHEET = "Owners"
PROPERTIES_SHEET = "Properties"
ACTIVITIES_SHEET = "Activities"
FOLLOWUPS_SHEET = "FollowUps"
DEALS_SHEET = "Deals"
NOTIFICATIONS_SHEET = "Notifications"

CLIENTS_HEADERS = [
    "client_id", "phone_norm", "phone_raw", "name", "status", "source",
    "assigned_agent_id", "assigned_agent_name", "team", "deal_type", "budget",
    "notes", "created_at", "updated_at", "created_by", "archived", "last_activity_at",
]
OWNERS_HEADERS = [
    "owner_id", "phone_norm", "phone_raw", "name", "notes",
    "created_at", "updated_at", "created_by", "archived",
]
PROPERTIES_HEADERS = [
    "property_id", "owner_id", "exclusive_id", "myhome_id", "agent_id", "agent_name",
    "address", "district", "city", "deal_type", "price", "status",
    "created_at", "updated_at", "archived",
]
ACTIVITIES_HEADERS = [
    "activity_id", "entity_type", "entity_id", "type", "summary",
    "agent_id", "agent_name", "source_ref", "created_at",
]
FOLLOWUPS_HEADERS = [
    "followup_id", "client_id", "agent_id", "agent_name", "due_at", "next_action",
    "status", "done_at", "created_at", "created_by",
]
# P5 / P8-ისთვის — ახლა მხოლოდ სათაურებია (ცხრილები იქმნება, ლოგიკა ჯერ არ არის)
DEALS_HEADERS = [
    "deal_id", "client_id", "property_id", "agent_id", "stage", "value",
    "lost_reason", "created_at", "updated_at", "archived",
]
NOTIFICATIONS_HEADERS = [
    "notification_id", "recipient_agent_id", "kind", "entity_type", "entity_id",
    "text", "status", "created_at", "read_at",
]

ALL_TABS = [
    (CLIENTS_SHEET, CLIENTS_HEADERS, 2000),
    (OWNERS_SHEET, OWNERS_HEADERS, 2000),
    (PROPERTIES_SHEET, PROPERTIES_HEADERS, 2000),
    (ACTIVITIES_SHEET, ACTIVITIES_HEADERS, 5000),
    (FOLLOWUPS_SHEET, FOLLOWUPS_HEADERS, 2000),
    (DEALS_SHEET, DEALS_HEADERS, 1000),
    (NOTIFICATIONS_SHEET, NOTIFICATIONS_HEADERS, 2000),
]

# ---- სტატუსები ----
CLIENT_STATUSES = ("new", "contacted", "viewing", "negotiation", "won", "lost", "inactive")
FOLLOWUP_STATUSES = ("open", "done", "cancelled")
ACTIVITY_ENTITY_TYPES = ("client", "owner", "property")
ACTIVITY_TYPES = ("call", "meeting", "note", "task", "report", "job", "system")
PROPERTY_STATUSES = ("active", "reserved", "sold", "withdrawn")


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    """მოკლე უნიკალური ID პრეფიქსით (მაგ. `cl_3fa9c01b`) — ტიპი ID-იდანაც ჩანს."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def normalize_phone(raw) -> str:
    """ტელეფონის ერთიანი ფორმა დუბლიკატების აღმოსაჩენად.

    * მხოლოდ ციფრები;
    * საქართველო: `+995 5xx xx xx xx`, `995 5xx...`, `0 5xx...` -> 9 ციფრი `5xxxxxxxx`;
    * უცხოური/უცნობი ნომერი — უბრალოდ ციფრები (არ ვიცნობთ, არ ვამახინჯებთ);
    * ცარიელი/ციფრების გარეშე -> "".
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("995") and len(digits) == 12:
        digits = digits[3:]
    elif len(digits) == 10 and digits.startswith("0"):
        digits = digits[1:]
    return digits
