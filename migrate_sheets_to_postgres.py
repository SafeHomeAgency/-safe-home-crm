#!/usr/bin/env python3
"""
ერთჯერადი მიგრაციის სკრიპტი: Google Sheets -> PostgreSQL.

უსაფრთხოების პრინციპები (მასტერ-გეგმის თავი 1-ის მიხედვით):
  - არაფერს არ შლის Google Sheets-დან — მხოლოდ კითხულობს.
  - იდემპოტენტურია: ხელახლა გაშვება უსაფრთხოა (UPSERT — ON CONFLICT
    DO UPDATE), შეგიძლიათ ტესტირებისას რამდენჯერაც გინდათ გაუშვათ.
  - --dry-run: არაფერს არ წერს Postgres-ში, მხოლოდ დაგითვლით რამდენ
    სტრიქონს გადაიტანდა თითო ცხრილში.
  - ბოლოს ამოწმებს: Sheets-ის და Postgres-ის სტრიქონების რაოდენობა
    ემთხვევა თუ არა თითო ცხრილში (მარტივი, სწრაფი "მართლა ყველაფერი
    გადავიდა?" შემოწმება).

გამოყენება (ტერმინალიდან, კომპიუტერზე ან Railway-ს "Shell"-იდან):

    python3 migrate_sheets_to_postgres.py --dry-run   # ჯერ ასე, ნახეთ რას აპირებს
    python3 migrate_sheets_to_postgres.py              # შემდეგ, ნამდვილად გადასატანად

საჭირო environment variable-ები: იგივეა, რაც ბოტს სჭირდება
(GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON) + ახალი DATABASE_URL
(Postgres-ის მისამართი). DATA_BACKEND ამ სკრიპტს არ სჭირდება — ის
პირდაპირ orchestration-ს აკეთებს ორივე მხარეს შორის, სულ ერთია bot.py
ამ დროისთვის რომელ ბექენდზეა გადართული.
"""

from __future__ import annotations

import argparse
import sys

import config
import db
import sheets_gspread as gs

# (table_name, headers, "get all rows" callable)
_TABLES = [
    ("agents", gs.AGENTS_HEADERS, lambda: gs.get_agents()),
    ("tasks", gs.TASKS_HEADERS, lambda: gs.get_tasks()),
    ("reports", gs.REPORTS_HEADERS, lambda: gs.get_reports()),
    ("dayoff", gs.DAYOFF_HEADERS, lambda: gs.get_dayoff_requests()),
    ("meetings", gs.MEETINGS_HEADERS, lambda: gs.get_meetings()),
    ("schedule", gs.SCHEDULE_HEADERS, lambda: gs._cached_records(config.SCHEDULE_SHEET_NAME)),
    ("attendance", gs.ATTENDANCE_HEADERS, lambda: gs._cached_records(config.ATTENDANCE_SHEET_NAME)),
    ("warnings", gs.WARNINGS_HEADERS, lambda: gs.get_warnings()),
    ("shift_swaps", gs.SHIFT_SWAPS_HEADERS, lambda: gs.get_shift_swaps()),
    ("exclusives", gs.EXCLUSIVES_HEADERS, lambda: gs.get_exclusives()),
    ("questions", gs.QUESTIONS_HEADERS, lambda: gs.get_questions()),
    ("exclusive_shares", gs.EXCLUSIVE_SHARES_HEADERS, lambda: gs.get_exclusive_shares()),
]

# პირველი სვეტი ყოველთვის primary key-ია (იხ. schema.sql).
_PK = {
    "agents": "agent_id", "tasks": "task_id", "reports": "report_id",
    "dayoff": "request_id", "meetings": "meeting_id", "schedule": "agent_id",
    "attendance": "attendance_id", "warnings": "warning_id",
    "shift_swaps": "swap_id", "exclusives": "exclusive_id",
    "questions": "question_id", "exclusive_shares": "share_id",
}


def _upsert(table: str, headers: list[str], rows: list[dict]) -> int:
    pk = _PK[table]
    cols = ", ".join(headers)
    placeholders = ", ".join(["%s"] * len(headers))
    update_cols = ", ".join(f"{h} = EXCLUDED.{h}" for h in headers if h != pk)
    sql = (
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk}) DO UPDATE SET {update_cols}"
    )
    written = 0
    for row in rows:
        pk_val = str(row.get(pk, "")).strip()
        if not pk_val:
            continue  # ცარიელი/დაზიანებული სტრიქონი — გამოტოვება, არ ჩერდება მთელი მიგრაცია
        values = tuple(row.get(h, "") for h in headers)
        db.execute(sql, values)
        written += 1
    return written


def run_migration(dry_run: bool) -> tuple[str, bool]:
    """გადააქვს ყველა ცხრილი Sheets-იდან Postgres-ში (ან, dry_run=True-ზე,
    მხოლოდ ითვლის). ბრუნდება (რეპორტის ტექსტი, ყველაფერი_კარგადააო).

    ცალკე ფუნქციად გატანილია, რომ ერთი და იგივე ლოგიკა გამოიყენებოდეს
    როგორც ტერმინალიდან (`python3 migrate_sheets_to_postgres.py`), ისე
    ბოტის admin-only `/migratepg` ბრძანებიდან (იხ. bot.py) — არაპროგრამისტ
    მომხმარებელს Railway-ს shell-ი არ სჭირდება."""
    lines = []
    lines.append("=" * 40)
    lines.append("Safe Home CRM — Sheets -> PostgreSQL მიგრაცია")
    lines.append("რეჟიმი: " + ("DRY RUN (არაფერი არ იწერება)" if dry_run else "ნამდვილი ჩაწერა"))
    lines.append("=" * 40)

    if not dry_run:
        db.init_schema()

    totals = {}
    for table, headers, getter in _TABLES:
        try:
            rows = getter()
        except Exception as e:
            lines.append(f"[შეცდომა] '{table}' ვერ წაიკითხა Sheets-იდან: {e}")
            continue
        totals[table] = len(rows)
        if dry_run:
            lines.append(f"{table}: {len(rows)} სტრიქონი გადაიტანება")
            continue
        written = _upsert(table, headers, rows)
        lines.append(f"{table}: {written}/{len(rows)} სტრიქონი ჩაწერილია")

    if dry_run:
        lines.append("")
        lines.append("Dry-run დასრულდა — არაფერი არ შეცვლილა.")
        return "\n".join(lines), True

    lines.append("")
    lines.append("--- გადამოწმება (Sheets vs Postgres) ---")
    all_ok = True
    for table, headers, _ in _TABLES:
        pg_count_row = db.query_one(f"SELECT COUNT(*) AS c FROM {table}")
        pg_count = pg_count_row["c"] if pg_count_row else 0
        sheet_count = totals.get(table, "?")
        ok = pg_count == sheet_count
        if not ok:
            all_ok = False
        lines.append(f"{table}: Sheets={sheet_count} Postgres={pg_count} {'✅' if ok else '❗'}")

    lines.append("")
    if all_ok:
        lines.append("✅ ყველა ცხრილის რაოდენობა ემთხვევა. მიგრაცია წარმატებულია.")
        lines.append("შემდეგი ნაბიჯი: Railway-ზე დააყენეთ DATA_BACKEND=postgres "
                      "და გადატვირთეთ სერვისი.")
    else:
        lines.append("⚠️ ზოგიერთი ცხრილის რაოდენობა არ ემთხვევა — არ დააყენოთ "
                      "DATA_BACKEND=postgres, სანამ ამის მიზეზი არ გაირკვევა.")
    return "\n".join(lines), all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="მხოლოდ დაითვლის, არაფერს არ ჩაწერს Postgres-ში")
    args = parser.parse_args()
    report, ok = run_migration(dry_run=args.dry_run)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
