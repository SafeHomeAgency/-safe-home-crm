"""
TGNET: ფოტოს ბრენდირება — Safe Home „SH“ იარლიყი. ყოველი ფოტო, რომელსაც არხში ვაქვეყნებთ, გადის აქ.

რას აკეთებს (Pillow): 1) ორიენტაციას ასწორებს, ზომას ზღუდავს (≤1600px), 2) არჩევითად ჭრის კიდეებს (TGNET_WM_CROP: "ზედა,ქვედა,მარცხენა,მარჯვენა" პროცენტებში — წყაროს ლოგოს მოსაცილებლად),
3) არჩევითად ფარავს მართკუთხედებს ბუნდოვანი/ერთფეროვანი ლაქით (TGNET_WM_COVER: "x0,y0,x1,y1;..." პროცენტებში), 4) ამატებს „SH“ იარლიყს (TGNET_WM_POS: bl|br|tl|tr, ნაგულისხმევი br).
**ლოგოს ადგილი წყაროს ფოტოზე ჯერ არ ვიცით** — ამიტომ ჭრა/დაფარვა ნაგულისხმევად გამორთულია და ხელით კონფიგურირდება რეალური ფოტოს ნახვის შემდეგ.
Pillow არ არის/ვერ გაიხსნა ფოტო -> TgError (არ ვაქვეყნებთ დაუბრენდებელს, თუ TGNET_BRAND_REQUIRED=1 — ნაგულისხმევია).
"""

from __future__ import annotations

import io
import logging
import os

log = logging.getLogger("safehome-tgnet-brand")
NAVY, GOLD, CREAM = (18, 48, 75), (233, 196, 106), (243, 239, 228)
MAX_SIDE = 1600


def _pcts(s: str, n: int) -> list[float]:
    try:
        v = [float(x) for x in str(s or "").split(",")]
    except ValueError:
        return [0.0] * n
    return (v + [0.0] * n)[:n] if len(v) >= 1 else [0.0] * n


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def sh_badge(width: int):
    """„SH“ მონოგრამა: ლურჯი მომრგვალებული ფირფიტა, ოქროსფერი ჩარჩო და ასოები, ქვემოთ „SAFE HOME“. width — ფირფიტის სიგანე პიქსელებში."""
    from PIL import Image, ImageDraw, ImageFont
    w, h = width, int(width * 0.62)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = max(6, w // 9)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=NAVY + (235,), outline=GOLD + (255,), width=max(2, w // 50))
    f1 = ImageFont.load_default(size=int(h * 0.5))
    f2 = ImageFont.load_default(size=max(8, int(h * 0.16)))
    d.text((w / 2, h * 0.40), "SH", font=f1, fill=GOLD, anchor="mm")
    d.text((w / 2, h * 0.80), "SAFE HOME", font=f2, fill=CREAM, anchor="mm")
    return img


def brand_image(data: bytes, *, crop: str = "", cover: str = "", pos: str = "br", badge_pct: float = 0.17) -> bytes:
    from PIL import Image, ImageFilter, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"სურათი ვერ გაიხსნა: {type(e).__name__}") from e
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    if W < 200 or H < 150:
        raise ValueError("სურათი ძალიან პატარაა")
    t, b, l, r = _pcts(crop, 4)
    if any((t, b, l, r)) and max(t, b, l, r) <= 30:
        im = im.crop((int(W * l / 100), int(H * t / 100), W - int(W * r / 100), H - int(H * b / 100)))
        W, H = im.size
    for rect in [x for x in str(cover or "").split(";") if x.strip()]:
        x0, y0, x1, y1 = _pcts(rect, 4)
        if not (0 <= x0 < x1 <= 100 and 0 <= y0 < y1 <= 100):
            continue
        box = (int(W * x0 / 100), int(H * y0 / 100), int(W * x1 / 100), int(H * y1 / 100))
        im.paste(im.crop(box).filter(ImageFilter.GaussianBlur(max(8, (box[2] - box[0]) // 6))), box)       # ლაქა = ძლიერი დაბუნდოვნება (ფერები არ იკარგება)
    s = max(W, H) / MAX_SIDE
    if s > 1:
        im = im.resize((int(W / s), int(H / s)), Image.LANCZOS)
        W, H = im.size
    badge = sh_badge(max(90, int(W * badge_pct)))
    m = max(10, int(W * 0.025))
    bw, bh = badge.size
    x = m if pos in ("bl", "tl") else W - bw - m
    y = m if pos in ("tl", "tr") else H - bh - m
    im.paste(badge, (x, y), badge)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def brand_from_config(data: bytes) -> bytes:
    import config
    return brand_image(data, crop=config.TGNET_WM_CROP, cover=config.TGNET_WM_COVER, pos=config.TGNET_WM_POS)
