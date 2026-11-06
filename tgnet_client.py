"""
TGNET: Telegram Bot API კლიენტი (stdlib; გარე ბიბლიოთეკა არ სჭირდება). ტოკენი მხოლოდ გარემოს ცვლადიდან (config.TGNET_BOT_TOKEN), არასდროს ილოგება და არც შეცდომის ტექსტში ხვდება.

ეტაპი 2B-ში გამოიყენება მხოლოდ **წაკითხვა** (getMe/getChat/getChatMember/getChatMemberCount). გამოქვეყნების ფუნქციები (send/edit/delete) მზადაა, მაგრამ
არც ერთი ადგილი მათ ჯერ არ იძახებს — პოსტინგი ცალკე ეტაპია და ცალკე დამტკიცება სჭირდება.
Telegram-ის შეზღუდვები (ტესტით დადასტურებული 2026-11-07): გარე სურათის ბმულს Telegram ვერ იღებს (ss.ge -> WEBPAGE_CURL_FAILED) — სურათს თავად ვტვირთავთ ბაიტებად;
წარწერა ≤1024, ტექსტი ≤4096.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import config

log = logging.getLogger("safehome-tgnet")
API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_MAX, TEXT_MAX = 1024, 4096


class TgError(Exception):
    def __init__(self, msg: str, code: int = 0, retry_after: int = 0):
        super().__init__(msg)
        self.code = code
        self.retry_after = retry_after


class Client:
    def __init__(self, token: str | None = None, http=None, sleep=time.sleep):
        self._token = (token if token is not None else config.TGNET_BOT_TOKEN or "").strip()
        self._http = http or self._real_http
        self._sleep = sleep

    @property
    def configured(self) -> bool:
        return ":" in self._token

    # ---- დაბალი დონე
    def _real_http(self, method: str, fields: dict, files: dict | None) -> dict:
        url = API.format(token=self._token, method=method)
        if files:
            b = "----tgnet" + uuid.uuid4().hex
            parts = []
            for k, v in fields.items():
                parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            for k, (fn, data) in files.items():
                parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + data + b"\r\n")
            parts.append(f"--{b}--\r\n".encode())
            req = urllib.request.Request(url, data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        else:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"ok": False, "error_code": e.code, "description": f"HTTP {e.code}"}
        except Exception as e:  # noqa: BLE001 — ქსელის შეცდომის ტექსტში URL (=ტოკენი) შეიძლება იყოს
            return {"ok": False, "error_code": 0, "description": str(e).replace(self._token, "***")[:200]}

    def call(self, method: str, files: dict | None = None, **params):
        if not self.configured:
            raise TgError("Telegram ბოტის ტოკენი არ არის დაყენებული (Railway: TGNET_BOT_TOKEN)")
        fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)) for k, v in params.items() if v is not None}
        for attempt in (1, 2):
            res = self._http(method, fields, files)
            if res.get("ok"):
                return res.get("result")
            ra = int((res.get("parameters") or {}).get("retry_after") or 0)
            if res.get("error_code") == 429 and ra and ra <= 30 and attempt == 1:
                self._sleep(ra + 1)
                continue
            desc = str(res.get("description") or "უცნობი შეცდომა").replace(self._token, "***")
            raise TgError(desc, int(res.get("error_code") or 0), ra)
        raise TgError("Telegram: ზედმეტად ბევრი მოთხოვნა")

    # ---- წაკითხვა (ეტაპი 2B)
    def get_me(self) -> dict:
        return self.call("getMe")

    def get_chat(self, chat_id) -> dict:
        return self.call("getChat", chat_id=chat_id)

    def get_member(self, chat_id, user_id) -> dict:
        return self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    def get_member_count(self, chat_id) -> int:
        return int(self.call("getChatMemberCount", chat_id=chat_id))

    # ---- გამოქვეყნება (მზადაა, ჯერ არსად გამოიყენება)
    def send_message(self, chat_id, text: str, **kw) -> int:
        if len(text) > TEXT_MAX:
            raise TgError(f"ტექსტი {len(text)}>{TEXT_MAX}")
        return int(self.call("sendMessage", chat_id=chat_id, text=text, parse_mode=kw.get("parse_mode", "HTML"), disable_web_page_preview="true", reply_markup=kw.get("reply_markup"))["message_id"])

    def send_photo(self, chat_id, photo: bytes, caption: str = "", reply_markup=None) -> int:
        if len(caption) > CAPTION_MAX:
            raise TgError(f"წარწერა {len(caption)}>{CAPTION_MAX}")
        return int(self.call("sendPhoto", files={"photo": ("p.jpg", photo)}, chat_id=chat_id, caption=caption or None, parse_mode="HTML" if caption else None, reply_markup=reply_markup)["message_id"])

    def send_album(self, chat_id, photos: list[bytes], caption: str = "") -> list[int]:
        if not 2 <= len(photos) <= 10:
            raise TgError("ალბომში 2–10 ფოტო უნდა იყოს")
        if len(caption) > CAPTION_MAX:
            raise TgError(f"წარწერა {len(caption)}>{CAPTION_MAX}")
        media = [{"type": "photo", "media": f"attach://f{i}", **({"caption": caption, "parse_mode": "HTML"} if i == 0 and caption else {})} for i in range(len(photos))]
        res = self.call("sendMediaGroup", files={f"f{i}": (f"f{i}.jpg", b) for i, b in enumerate(photos)}, chat_id=chat_id, media=media)
        return [int(m["message_id"]) for m in res]

    def edit_text(self, chat_id, message_id: int, text: str) -> None:
        self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", disable_web_page_preview="true")

    def edit_caption(self, chat_id, message_id: int, caption: str) -> None:
        if len(caption) > CAPTION_MAX:
            raise TgError(f"წარწერა {len(caption)}>{CAPTION_MAX}")
        self.call("editMessageCaption", chat_id=chat_id, message_id=message_id, caption=caption, parse_mode="HTML")

    def delete_message(self, chat_id, message_id: int) -> None:
        self.call("deleteMessage", chat_id=chat_id, message_id=message_id)


def check_channel(client: Client, chat_id, expect_username: str = "", expect_title: str = "") -> dict:
    """ერთი არხის სრული შემოწმება (3 წაკითხვის ზარი, არაფერი იგზავნება). შეცდომა -> status=attention + ახსნა."""
    import tgnet_model as m
    try:
        me = client.get_me()
    except TgError as e:
        return {"status": "attention", "issues": [f"ბოტი ვერ დაუკავშირდა Telegram-ს: {e}"], "members": None, "rights": {}}
    try:
        chat = client.get_chat(chat_id)
    except TgError as e:
        return {"status": "attention", "issues": [f"არხი ვერ მოიძებნა/წვდომა არ არის: {e}"], "members": None, "rights": {}}
    member = count = None
    try:
        member = client.get_member(chat_id, me["id"])
    except TgError:
        member = None
    try:
        count = client.get_member_count(chat_id)
    except TgError:
        count = None
    return m.evaluate_health(chat, member, count, expect_username, expect_title)
