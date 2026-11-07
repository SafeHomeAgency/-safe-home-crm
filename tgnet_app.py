"""
TGNET: კლიენტის Mini App (პოსტის ღილაკიდან იხსნება: t.me/SafeHomeGeBot/<TGNET_MINIAPP_SHORTNAME>?startapp=<განცხადება>_<ენა>). კლიენტი ხედავს ფოტოებს (SH იარლიყით) და მონაცემებს და ტოვებს ნომერს ->
CRM-ში კლიენტი + მენეჯერს შეტყობინება (იგივე ჯაჭვი, რაც ბოტში: tgnet_leads.Flow).

უსაფრთხოება: მომხმარებელს Telegram-ის initData ამოწმებს (HMAC საჯარო ბოტის ტოკენით, ≤24 სთ); გვერდი მხოლოდ საჯარო მონაცემს აჩვენებს (მესაკუთრის ნომერი/შენიშვნა/აგენტის სახელი — არა).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import config

TEXT = {
    "ka": {"want": "📞 მინდა დაკავშირება", "phone": "თქვენი ტელეფონის ნომერი", "send": "გაგზავნა", "thanks": "✅ მიღებულია! მენეჯერი დაგიკავშირდებათ.", "gone": "ეს განცხადება აღარ არის აქტუალური.", "err": "შეცდომა — სცადეთ ხელახლა"},
    "en": {"want": "📞 I want to be contacted", "phone": "Your phone number", "send": "Send", "thanks": "✅ Received! A manager will contact you.", "gone": "This listing is no longer available.", "err": "Error — please try again"},
    "ru": {"want": "📞 Хочу связаться", "phone": "Ваш номер телефона", "send": "Отправить", "thanks": "✅ Принято! Менеджер свяжется с вами.", "gone": "Это объявление уже неактуально.", "err": "Ошибка — попробуйте ещё раз"},
}


def validate_init_data(init_data: str, token: str, max_age: int = 86400, now: float | None = None) -> dict | None:
    """Telegram Mini App initData-ს ოფიციალური შემოწმება. აბრუნებს user dict-ს ან None-ს."""
    if not init_data or not token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    got = pairs.pop("hash", "")
    if not got:
        return None
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
        return None
    try:
        if (now or time.time()) - int(pairs.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(pairs.get("user", "{}"))
    except (ValueError, TypeError):
        return None
    return user if isinstance(user, dict) and user.get("id") else None


PAGE = """<!doctype html><html lang="ka"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Safe Home</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#0a1420;--card:#12304b;--gold:#e9c46a;--cream:#f3efe4;--mut:#9fb0c3}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--cream);font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
.g{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;gap:6px;padding:0}.g img{flex:0 0 100%;width:100%;max-height:60vh;object-fit:cover;scroll-snap-align:center;background:#0d1b2a}
.w{padding:14px 16px 90px}.h{font-size:18px;font-weight:700}.p{font-size:22px;color:var(--gold);font-weight:800;margin:4px 0 10px}.f{color:var(--mut);margin:2px 0}
.b{position:fixed;left:0;right:0;bottom:0;padding:12px 16px;background:linear-gradient(transparent,var(--bg) 40%)}
button,input{width:100%;padding:14px;border-radius:12px;border:0;font:inherit}button{background:var(--gold);color:#1a1405;font-weight:700}
input{background:#0d1b2a;color:var(--cream);border:1px solid #27425e;margin-bottom:8px}.m{padding:30px 16px;text-align:center}
.brand{color:var(--gold);letter-spacing:3px;font-size:12px;margin-bottom:6px}
</style></head><body><div id="app"><div class="m">…</div></div>
<script>
const tg=window.Telegram&&Telegram.WebApp;if(tg){tg.ready();tg.expand();}
const sp=(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.start_param)||new URLSearchParams(location.search).get("l")||"";
const lang=(/_(ka|en|ru)$/.exec(sp)||[])[1]||((tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user&&tg.initDataUnsafe.user.language_code)||"ka").slice(0,2);
const T=""" + json.dumps(TEXT, ensure_ascii=False) + """[["ka","en","ru"].includes(lang)?lang:"ka"];
const H={"X-Tg-Init":(tg&&tg.initData)||""};const $=document.getElementById("app");
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function load(){
  try{const r=await fetch("/api/tgnet/app/listing?l="+encodeURIComponent(sp),{headers:H});const d=await r.json();
    if(!r.ok){$.innerHTML='<div class="m">'+esc(d.error||T.gone)+'</div>';return;}
    $.innerHTML='<div class="g">'+d.photos.map(u=>'<img loading="lazy" src="'+esc(u)+'">').join("")+'</div><div class="w"><div class="brand">SAFE HOME</div><div class="h">'+esc(d.title)+'</div><div class="p">'+esc(d.price)+'</div>'+d.facts.map(f=>'<div class="f">'+esc(f)+'</div>').join("")+'</div><div class="b"><button id="go">'+T.want+'</button></div>';
    document.getElementById("go").onclick=form;
  }catch(e){$.innerHTML='<div class="m">'+T.err+'</div>';}
}
function form(){document.querySelector(".b").innerHTML='<input id="ph" type="tel" inputmode="tel" placeholder="'+T.phone+'" autocomplete="tel"><button id="sd">'+T.send+'</button>';
  document.getElementById("sd").onclick=async()=>{const ph=document.getElementById("ph").value.trim();if(ph.replace(/\\D/g,"").length<9)return;
    try{const r=await fetch("/api/tgnet/app/lead",{method:"POST",headers:Object.assign({"Content-Type":"application/json"},H),body:JSON.stringify({l:sp,phone:ph,lang:lang})});
      if(!r.ok)throw 0;$.innerHTML='<div class="m"><div class="brand">SAFE HOME</div><div class="h">'+T.thanks+'</div></div>';setTimeout(()=>tg&&tg.close&&tg.close(),2500);}catch(e){alert(T.err);}};}
load();
</script></body></html>"""
