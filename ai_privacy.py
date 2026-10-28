"""
Safe Home AI — კონფიდენციალურობა: რა გადის გარე AI-ს პროვაიდერთან და რა — არა.

1. `redact` — ტელეფონების/ელფოსტების/პირადი ნომრების ამოღება ტექსტიდან (კითხვაც და შენახული ტექსტიც). ეს **ევრისტიკაა**, 100%-იანი გარანტია არა.
2. `Pseudonymizer` — სისტემის მონაცემებში (შეხვედრა, დავალება, გუნდის KPI) კლიენტების/კოლეგების სახელები პროვაიდერს ეგზავნება
   პლეისჰოლდერით ([CLIENT_1]); მომხმარებელს პასუხში ნამდვილი სახელი უბრუნდება. ტელეფონები ინსტრუმენტებიდან საერთოდ არ გადის.
3. `protected_attribute_request` — ეროვნების/რასის/ეთნიკური ნიშნით ფილტრაციის თხოვნა: ფიქსირებული უარი, პროვაიდერის გამოძახების გარეშე.
4. `detect_lang` — ka / ru / en (სკრიპტის მიხედვით), `injection_suspect` — მხოლოდ ლოგისთვის (მოთხოვნას არ ბლოკავს: დაცვა სტრუქტურულია).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- redaction
_DATE_PATTERNS = (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b"))
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_RUN = re.compile(r"(?<![\w])\+?\d[\d\s().\-]{6,}\d(?![\w])")


def redact(text: str) -> str:
    t = str(text or "")
    keep: list[str] = []

    def hold(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"

    for p in _DATE_PATTERNS:
        t = p.sub(hold, t)
    t = _EMAIL.sub("[ელფოსტა]", t)

    def phone(m):
        digits = sum(ch.isdigit() for ch in m.group(0))
        return "[ტელეფონი]" if digits >= 9 else m.group(0)

    t = _RUN.sub(phone, t)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], t)


# ---------------------------------------------------------------- pseudonymization
class Pseudonymizer:
    """ერთი მოთხოვნის ფარგლებში: ნამდვილი სახელი -> [CLIENT_1] / [AGENT_1]; პასუხში უკან ბრუნდება."""

    def __init__(self):
        self._by_real: dict[tuple[str, str], str] = {}
        self._by_token: dict[str, str] = {}

    def token(self, kind: str, real) -> str:
        real = str(real or "").strip()
        if not real:
            return ""
        key = (kind, real.lower())
        if key not in self._by_real:
            n = 1 + sum(1 for k in self._by_real if k[0] == kind)
            tok = f"[{kind}_{n}]"
            self._by_real[key] = tok
            self._by_token[tok] = real
        return self._by_real[key]

    def restore(self, text: str) -> str:
        out = str(text or "")
        for tok, real in sorted(self._by_token.items(), key=lambda kv: -len(kv[0])):
            out = out.replace(tok, real)
        return out

    @property
    def used(self) -> bool:
        return bool(self._by_token)


# ---------------------------------------------------------------- protected attributes
_PROTECTED = re.compile(
    r"ეროვნებ|ეთნიკ|რასის|რასობრივ|რასა\b|ნაციონალ|национальност|этническ|расов|\brace\b|racial|ethnic|ethnicity|nationality|"
    r"აზერბაიჯანელ|სომეხ|ებრაელ|რუს(ი|ებ)ი|თურქ|არაბ|ქართველ(ებ|ი)ს?\s+(მხოლოდ|არ)|азербайджан|армян|евре|грузин|турок|араб",
    re.IGNORECASE)
_SELECTION = re.compile(
    r"ფილტრ|გაფილტრ|არ\s*გავაქირ|არ\s*ვაქირ|არ\s*გავყიდ|მხოლოდ|აირჩი|გამოარჩი|არ\s*მიიღ|უარი|არ\s*უნდა|არ\s*გვინდა|ვისაც\s+არ|გამორიცხ|"
    r"фильтр|не\s*сдава|не\s*продава|только|отбир|не\s*принима|отказ|исключ|"
    r"filter|only|don'?t\s+rent|do\s+not\s+rent|reject|exclude|avoid|refuse|not\s+allow",
    re.IGNORECASE)

PROTECTED_REFUSAL = {
    "ka": "ამ კრიტერიუმით (ეროვნება, რასა, ეთნიკური წარმოშობა) კლიენტების ან მესაკუთრეების გაფილტვრაში დაგეხმარებით ვერ ვიქნები — ეს დისკრიმინაციაა და "
          "კომპანიის წესებსაც ეწინააღმდეგება. შემიძლია ნეიტრალური პირობებით დაგეხმაროთ: ბიუჯეტი, ქირავნობის ვადა, დასახლებულ პირთა რაოდენობა, ცხოველები, "
          "მოწევა, დოკუმენტები/გარანტიები.",
    "ru": "Я не могу помочь с отбором клиентов или собственников по национальности, расе или этническому происхождению — это дискриминация и противоречит правилам компании. "
          "Могу помочь с нейтральными условиями: бюджет, срок аренды, число жильцов, животные, курение, документы/гарантии.",
    "en": "I can't help filter clients or owners by nationality, race or ethnic origin — that is discrimination and against company rules. "
          "I can help with neutral conditions instead: budget, lease term, number of occupants, pets, smoking, documents/guarantees.",
}


def protected_attribute_request(text: str) -> bool:
    t = str(text or "")
    return bool(_PROTECTED.search(t) and _SELECTION.search(t))


# ---------------------------------------------------------------- language / injection
def detect_lang(text: str) -> str:
    ka = sum(1 for ch in str(text or "") if "Ⴀ" <= ch <= "ჿ")
    ru = sum(1 for ch in str(text or "") if "Ѐ" <= ch <= "ӿ")
    en = sum(1 for ch in str(text or "") if ch.isascii() and ch.isalpha())
    if ka >= ru and ka >= en and ka:
        return "ka"
    if ru >= en and ru:
        return "ru"
    return "en" if en else "ka"


_INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above)|disregard (the )?(system|previous)|system prompt|reveal (your|the) (prompt|instructions)|"
    r"игнорируй (все )?(предыдущ|прежн)|системн\w+ промпт|"
    r"წინა ინსტრუქციებ\w* (უგულებელ|დაივიწყ)|სისტემურ\w* (პრომპტ|ინსტრუქცი)",
    re.IGNORECASE)


def injection_suspect(text: str) -> bool:
    return bool(_INJECTION.search(str(text or "")))
