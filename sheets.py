"""
მონაცემთა ფენის შესასვლელი წერტილი — bot.py და webserver.py მხოლოდ
ამ მოდულს იცნობენ (`import sheets`), და აქედან შემდეგ არაფერი არ
იცვლება მათთვის, სულ ერთია მონაცემები სად ინახება.

ნაგულისხმევად (config.DATA_BACKEND დაყენებული არაა, ანუ ცარიელია)
ყველაფერი ზუსტად ისე მუშაობს, როგორც აქამდე — Google Sheets-ზე
(sheets_gspread.py). ეს არის დღევანდელი production-ქცევა და არაფერი
არ იცვლება მანამ, სანამ ვინმე გააქტიურებულად არ დააყენებს:

    DATA_BACKEND=postgres

environment variable-ს (და შესაბამის DATABASE_URL-საც) — მხოლოდ მას
შემდეგ, რაც Phase 1-ის მიგრაცია (იხ. migrate_sheets_to_postgres.py და
README_PHASE1_POSTGRES.md) გატესტილი და დადასტურებულია.

ორივე მოდულს (sheets_gspread.py და sheets_postgres.py) ერთი და იგივე
საჯარო ფუნქციები აქვს, იდენტური სახელებით/არგუმენტებით — ეს ამ ფაილში
ავტომატურადაც მოწმდება (`_ASSERT_API_PARITY`-ით), რომ შემთხვევით ვინმემ
ერთი ვერსია მეორისგან არ „დააშოროს".
"""

from __future__ import annotations

import logging

import config

log = logging.getLogger("safehome-crm-sheets-dispatch")

if str(config.DATA_BACKEND).strip().lower() == "postgres":
    log.info("მონაცემთა ბექენდი: PostgreSQL (sheets_postgres)")
    from sheets_postgres import *  # noqa: F401,F403
    import sheets_postgres as _impl
else:
    log.info("მონაცემთა ბექენდი: Google Sheets (sheets_gspread) — ნაგულისხმევი, უცვლელი")
    from sheets_gspread import *  # noqa: F401,F403
    import sheets_gspread as _impl


def _ASSERT_API_PARITY() -> None:
    """გამოიძახება ტესტებში/CI-ში (არა runtime-ზე) — ამოწმებს, რომ
    sheets_gspread.py და sheets_postgres.py-ს საჯარო API ზუსტად
    ემთხვევა, რომ ორივე ერთნაირად "ჩანდეს" bot.py-სთვის."""
    import inspect
    import sheets_gspread
    import sheets_postgres

    def public_funcs(mod):
        return {
            name: inspect.signature(obj)
            for name, obj in vars(mod).items()
            if inspect.isfunction(obj) and not name.startswith("_") and obj.__module__ == mod.__name__
        }

    a = public_funcs(sheets_gspread)
    b = public_funcs(sheets_postgres)
    missing_in_pg = set(a) - set(b)
    missing_in_sheets = set(b) - set(a)
    mismatched = {
        name: (str(a[name]), str(b[name]))
        for name in (set(a) & set(b))
        if str(a[name]) != str(b[name])
    }
    assert not missing_in_pg, f"sheets_postgres.py-ს აკლია: {missing_in_pg}"
    assert not missing_in_sheets, f"sheets_gspread.py-ს აკლია: {missing_in_sheets}"
    assert not mismatched, f"სხვადასხვა სიგნატურა: {mismatched}"
