"""
ახალი Sheets-ცხრილების მოდულებისთვის (LeadGuardLog, AiActions) საერთო შენახვის ფენა — იგივე ნიმუში, რაც criteria/ai/contracts store-ებში
(ცხრილები იქმნება ზარმაცად; არსებულ ცხრილებს არაფერი ეხება) + **ჯგუფური** ჩაწერა: `append_many`, `update_many` (Sheets-ის კვოტის დასაზოგად —
ერთი ციკლი = 2 API-ზარი და არა ათეულობით).
"""

from __future__ import annotations

import contracts_store as _cs


def make(all_tabs):
    """აბრუნებს (SheetsBackend, MemoryBackend) კლასებს მოცემული ცხრილებისთვის: all_tabs = [(სახელი, სათაურები, სტრიქონების რაოდენობა)]."""

    class SheetsBackend(_cs.SheetsBackend):
        def ensure(self) -> None:
            if self._ready:
                return
            sg = self._sg()
            ss = sg._get_spreadsheet()
            existing = {ws.title: ws for ws in ss.worksheets()}
            for name, headers, rows in all_tabs:
                sg._ensure_one_sheet(ss, existing, name, headers, rows)
            self._ready = True

        def append_many(self, name: str, headers: list[str], rows: list[dict]) -> None:
            if not rows:
                return
            self.ensure()
            sg = self._sg()
            sg._worksheet(name).append_rows([[str(d.get(h, "")) for h in headers] for d in rows], value_input_option="RAW")
            sg._invalidate(name)

        def update_many(self, name: str, headers: list[str], changes: dict) -> int:
            """changes = {id: {ველი: მნიშვნელობა}} -> ერთი წაკითხვა + ერთი batch_update. აბრუნებს განახლებულ სტრიქონთა რაოდენობას."""
            if not changes:
                return 0
            self.ensure()
            sg = self._sg()
            ws = sg._worksheet(name)
            values = ws.get_all_values()
            idx = {str(r[0]): i + 1 for i, r in enumerate(values) if r}
            data = []
            for id_, ch in changes.items():
                r = idx.get(str(id_))
                if not r:
                    continue
                cur = dict(zip(headers, (list(values[r - 1]) + [""] * len(headers))[: len(headers)]))
                cur.update({k: str(v) for k, v in ch.items() if k in headers})
                data.append({"range": f"A{r}", "values": [[str(cur.get(h, "")) for h in headers]]})
            if data:
                ws.batch_update(data, value_input_option="RAW")
                sg._invalidate(name)
            return len(data)

    class MemoryBackend(_cs.MemoryBackend):
        def ensure(self) -> None:
            for name, _h, _r in all_tabs:
                self.tables.setdefault(name, [])

        def append_many(self, name, headers, rows) -> None:
            for d in rows:
                self.append(name, headers, d)

        def update_many(self, name, headers, changes) -> int:
            self.ensure()
            n = 0
            for r in self.tables[name]:
                ch = changes.get(str(r.get(headers[0])))
                if ch:
                    r.update({k: str(v) for k, v in ch.items() if k in headers})
                    n += 1
            return n

    return SheetsBackend, MemoryBackend
