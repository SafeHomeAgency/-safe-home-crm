"""
რაიონების ავტომატური კვირეული გადანაწილება ("შაფლი"): ყოველ ორშაბათს დილით ყველა აქტიურ აგენტს ეძლევა **საკუთარი, ერთმანეთისგან
განსხვავებული** რაიონები, ისე რომ გასულ კვირებში უკვე ნამუშევარი რაიონები შეძლებისდაგვარად არ განმეორდეს.

ალგორითმი (წმინდა ლოგიკა, ტესტირებადი):
  1. რაიონების კატალოგი (crm_extras.DISTRICT_GROUPS) — ჯგუფები და ქვერაიონები. ყოველი საცდელისას ჯგუფებიც და ჯგუფის შიგნით რაიონებიც
     ირევა (კვირის seed-ით, ანუ ერთი კვირა — ერთი განმეორებადი შედეგი), მერე ერთიანი სია N თანაბარ "ტერიტორიად" იჭრება — მეზობელი
     რაიონები (ერთი ჯგუფიდან) ძირითადად ერთ აგენტს ხვდება;
  2. ტერიტორიები აგენტებზე ნაწილდება უნგრული ალგორითმით (მინიმალური ჯამური "ჯარიმა"): ჯარიმა = რამდენად ახლახან ამუშავა ამ აგენტმა
     ეს რაიონი (გასული კვირა — ყველაზე ძვირი, 8 კვირის წინანდელი — ყველაზე იაფი);
  3. ვარჩევთ ყველაზე ნაკლები ჯარიმის მქონე საცდელს (40 საცდელიდან).
ხელით (მენეჯერის მიერ) გაკეთებულ განაწილებას არ ვეხებით; ხელით მინიჭებული რაიონები ავტომატურ გაცემაში აღარ მონაწილეობს.
"""

from __future__ import annotations

import datetime
import random

import crm_extras

AUTO_BY = "auto"
AUTO_BY_NAME = "ავტომატური განაწილება"
HISTORY_WEEKS = 8
_WEIGHTS = {1: 12, 2: 6, 3: 4, 4: 3}      # 5..8 კვირის წინ — 1
TRIALS = 40


def catalog_pool() -> list[tuple[str, str]]:
    """[(ჯგუფი, რაიონი)] — მხოლოდ ქვერაიონები (ჯგუფის სახელი ცალკე რაიონად არ გაიცემა)."""
    return [(g, d) for g, kids in crm_extras.DISTRICT_GROUPS for d in kids]


def penalty_of(history_sets: list[tuple[int, set]], district: str) -> int:
    """history_sets = [(რამდენი კვირის წინ, {რაიონები})]; ჯამური ჯარიმა ამ რაიონისთვის."""
    return sum(_WEIGHTS.get(w, 1) for w, s in history_sets if district in s)


def _hungarian(cost: list[list[int]]) -> list[int]:
    """კვადრატული ხარჯების მატრიცა -> assignment[row] = col (მინიმალური ჯამი). კლასიკური O(n^3) ვერსია."""
    n = len(cost)
    INF = float("inf")
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [0] * n
    for j in range(1, n + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


def shuffle(agent_ids: list[str], history: dict[str, list[tuple[int, set]]], seed: str, pool: list[tuple[str, str]] | None = None,
            trials: int = TRIALS) -> dict[str, list[str]]:
    """აბრუნებს {agent_id: [რაიონები]}; ყველა აგენტი იღებს ≥1 რაიონს, რაიონები აგენტებს შორის არ მეორდება (თუ აგენტი რაიონებზე მეტია — მეორდება)."""
    ids = list(agent_ids)
    n = len(ids)
    pool = pool if pool is not None else catalog_pool()
    if n == 0 or not pool:
        return {}
    best, best_cost = None, None
    for trial in range(trials):
        rng = random.Random(f"{seed}:{trial}")
        groups: dict[str, list[str]] = {}
        for g, d in pool:
            groups.setdefault(g, []).append(d)
        order = list(groups)
        rng.shuffle(order)
        flat: list[str] = []
        for g in order:
            kids = groups[g][:]
            rng.shuffle(kids)
            flat.extend(kids)
        if n > len(flat):                                   # აგენტი მეტია, ვიდრე რაიონი: ციკლურად ვიმეორებთ (ერთ აგენტზე ერთი რაიონი)
            chunks = [[flat[i % len(flat)]] for i in range(n)]
        else:
            base, extra = divmod(len(flat), n)
            sizes = [base + 1] * extra + [base] * (n - extra)
            rng.shuffle(sizes)
            chunks, pos = [], 0
            for sz in sizes:
                chunks.append(flat[pos:pos + sz])
                pos += sz
        cost = [[sum(penalty_of(history.get(aid, []), d) for d in ch) for ch in chunks] for aid in ids]
        match = _hungarian(cost)
        total = sum(cost[i][match[i]] for i in range(n))
        if best_cost is None or total < best_cost:
            best_cost, best = total, {ids[i]: chunks[match[i]] for i in range(n)}
        if total == 0:
            break
    return best or {}


# ====================================================================== კვირის გაშვება (Sheets-თან)
def _week_str(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def build_history(sheets, week_start: datetime.date) -> dict[str, list[tuple[int, set]]]:
    """წინა HISTORY_WEEKS კვირის განაწილებები აგენტების მიხედვით (ახლიდან ძველისკენ)."""
    by_week: dict[str, dict[str, set]] = {}
    for r in sheets.get_district_assignments():
        ws = str(r.get("week_start", "")).strip()
        by_week.setdefault(ws, {})[str(r.get("agent_id"))] = set(crm_extras.split_districts(r.get("districts", "")))
    hist: dict[str, list[tuple[int, set]]] = {}
    for w in range(1, HISTORY_WEEKS + 1):
        day = _week_str(week_start - datetime.timedelta(days=7 * w))
        for aid, s in (by_week.get(day) or {}).items():
            if s:
                hist.setdefault(aid, []).append((w, s))
    return hist


def settings(sheets) -> dict:
    s = sheets.get_app_settings()
    return {"enabled": str(s.get("district_auto", "1")).strip().lower() not in ("0", "false", "no", "off"),
            "exclude": [x for x in str(s.get("district_shuffle_exclude", "")).split(",") if x.strip()]}


def auto_done(sheets, week_start: datetime.date) -> bool:
    return any(str(r.get("assigned_by", "")).strip() == AUTO_BY for r in sheets.get_district_assignments(week_start=_week_str(week_start)))


def run(sheets, week_start: datetime.date, notify=None, overwrite_manual: bool = False, dry_run: bool = False) -> dict:
    """ავტომატური განაწილება კონკრეტული კვირისთვის (ორშაბათის თარიღი). ხელით განაწილებულს არ ვეხებით (overwrite_manual=False)."""
    ws = _week_str(week_start)
    st = settings(sheets)
    agents = [a for a in sheets.get_agents() if crm_extras._is_active_agent(a) and str(a.get("agent_id")) not in st["exclude"]]  # noqa: SLF001
    existing = {str(r.get("agent_id")): r for r in sheets.get_district_assignments(week_start=ws)}
    manual = {aid for aid, r in existing.items() if str(r.get("assigned_by", "")).strip() != AUTO_BY and crm_extras.split_districts(r.get("districts", ""))}
    if overwrite_manual:
        manual = set()
    taken = set()
    for aid in manual:
        taken |= set(crm_extras.split_districts(existing[aid].get("districts", "")))
    participants = [a for a in agents if str(a.get("agent_id")) not in manual]
    pool = [(g, d) for g, d in catalog_pool() if d not in taken] or catalog_pool()
    ids = sorted(str(a.get("agent_id")) for a in participants)
    result = shuffle(ids, build_history(sheets, week_start), seed=f"districts:{ws}", pool=pool)
    out = {"week_start": ws, "assigned": len(result), "skipped_manual": len(manual), "assignments": result, "dry_run": dry_run}
    if dry_run or not result:
        return out
    by_id = {str(a.get("agent_id")): a for a in participants}
    label = crm_extras.week_label(week_start)
    for aid, districts in result.items():
        before = crm_extras.split_districts((existing.get(aid) or {}).get("districts", ""))
        sheets.set_district_assignment(ws, aid, districts, AUTO_BY, AUTO_BY_NAME)
        chat = by_id[aid].get("telegram_chat_id")
        if notify and chat and before != districts:
            try:
                notify(int(chat), f"📍 ამ კვირის ({label}) რაიონები (ავტომატური განაწილება):\n{', '.join(districts)}\n\nგისურვებთ წარმატებას! 🍀")
            except Exception:  # noqa: BLE001
                pass
    return out
