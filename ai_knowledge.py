"""
Safe Home AI — ცოდნის ბაზიდან ამოღება (retrieval) და მსგავსების ძებნა. წმინდა ფუნქციები: ქსელი/Sheets არ სჭირდება.

ძებნა — სიმბოლოების ტრიგრამებით (სიტყვის ფარგლებში): ქართულის (აგლუტინაციური ენის) სუფიქსების ვარიაციას ითვლის სტემერის გარეშე;
ქართული/რუსული/ინგლისური ერთნაირად მუშაობს (ენებს შორის თარგმნას ის არ აკეთებს — ამისთვის: მცირე ბაზა მთლიანად გადაეცემა მოდელს,
დიდზე კი მოდელს აქვს `search_knowledge` ინსტრუმენტი და საკუთარ ენაზე ეძებს).
"""

from __future__ import annotations

import re

import ai_model as m

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NUM = re.compile(r"\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?")


def grams(text: str) -> set[str]:
    out: set[str] = set()
    for w in _WORD.findall(str(text or "").lower()):
        if len(w) < 3:
            continue
        p = f"#{w}#"
        out.update(p[i:i + 3] for i in range(len(p) - 2))
    return out


def jaccard(a: set, b: set) -> float:
    return (len(a & b) / len(a | b)) if a and b else 0.0


def similarity(a: str, b: str) -> float:
    return jaccard(grams(a), grams(b))


def overlap(a: str, b: str) -> float:
    """მოკლე ტექსტის რა ნაწილია გრძელში (ზედმეტი სიტყვები/ნომრები მსგავსებას არ აქვეითებს) — „იგივე კითხვაა სხვა სიტყვებით“."""
    ga, gb = grams(a), grams(b)
    return (len(ga & gb) / min(len(ga), len(gb))) if ga and gb else 0.0


def entry_text(e: dict) -> str:
    return f"{e.get('title', '')}\n{e.get('body', '')}"


def score(question: str, entry: dict) -> float:
    """რა ნაწილს ფარავს კითხვის ტრიგრამები ჩანაწერში (სათაური ორმაგი წონით)."""
    q = grams(question)
    if not q:
        return 0.0
    body, title = grams(entry.get("body", "")), grams(entry.get("title", ""))
    return (len(q & body) + len(q & title)) / (2.0 * len(q))


def rank(question: str, entries: list[dict], k: int = 8, min_score: float = 0.12) -> list[tuple[dict, float]]:
    scored = [(e, score(question, e)) for e in entries]
    scored = [x for x in scored if x[1] >= min_score]
    scored.sort(key=lambda x: -x[1])
    return scored[:k]


def render_entry(e: dict, cap: int = 3000) -> str:
    def esc(t):  # ტეგის გაყალბების თავიდან აცილება
        return str(t or "").replace("<", "＜").replace(">", "＞")
    attrs = f'id="{esc(e.get("kb_id"))}" category="{esc(e.get("category"))}" version="{esc(e.get("version"))}"'
    if e.get("effective_from"):
        attrs += f' effective_from="{esc(e["effective_from"])}"'
    if e.get("effective_to"):
        attrs += f' effective_to="{esc(e["effective_to"])}"'
    return f'<kb_entry {attrs} title="{esc(e.get("title"))}">\n{esc(str(e.get("body", ""))[:cap])}\n</kb_entry>'


def build_context(question: str, entries: list[dict], max_chars: int = 28000, k: int = 8) -> tuple[list[dict], str]:
    """(მოდელს გადასაცემი ჩანაწერები, რეჟიმი). 'all' — მთელი მოქმედი ბაზა; 'ranked' — ტრიგრამებით უახლოესი k (დანარჩენი — search_knowledge-ით)."""
    entries = sorted(entries, key=lambda e: str(e.get("kb_id")))
    if sum(len(entry_text(e)) for e in entries) <= max_chars:
        return entries, "all"
    return [e for e, _ in rank(question, entries, k=k)], "ranked"


def numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", n).replace(",", ".") for n in _NUM.findall(str(text or ""))}


def find_similar(entry: dict, others: list[dict], threshold: float = 0.45) -> list[dict]:
    """ახალი/შეცვლილი ჩანაწერის მსგავსი არსებული დამტკიცებულები (გამოქვეყნებამდე გასაფრთხილებლად). `numbers_differ` — ერთი თემაა, მაგრამ რიცხვები (%, თანხა) სხვაა."""
    ge = grams(entry_text(entry))
    ne = numbers(entry.get("body"))
    out = []
    for o in others:
        if str(o.get("kb_id")) == str(entry.get("kb_id")):
            continue
        sim = jaccard(ge, grams(entry_text(o)))
        tsim = similarity(entry.get("title", ""), o.get("title", ""))
        if sim >= threshold or tsim >= 0.6:
            no = numbers(o.get("body"))
            out.append({"kb_id": o.get("kb_id"), "title": o.get("title"), "category": o.get("category"),
                        "similarity": round(max(sim, tsim), 2), "numbers_differ": bool(ne and no and ne != no)})
    out.sort(key=lambda x: -x["similarity"])
    return out[:5]


def cluster(texts: list[str], threshold: float = 0.4) -> list[dict]:
    """ხშირი/განმეორებადი კითხვების დაჯგუფება (ხარბი): [{text, count, idx:[...]}], რაოდენობით კლებადობით."""
    reps: list[dict] = []
    for i, t in enumerate(texts):
        g = grams(t)
        if not g:
            continue
        best, bs = None, 0.0
        for r in reps:
            s = jaccard(g, r["g"])
            if s > bs:
                best, bs = r, s
        if best is not None and bs >= threshold:
            best["idx"].append(i)
        else:
            reps.append({"text": t, "g": g, "idx": [i]})
    out = [{"text": r["text"], "count": len(r["idx"]), "idx": r["idx"]} for r in reps]
    out.sort(key=lambda x: -x["count"])
    return out


def live_entries(rows: list[dict], team: str | None = None, today: str | None = None) -> list[dict]:
    return [r for r in rows if m.kb_live(r, today=today, team=team)]
