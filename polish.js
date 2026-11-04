/* Safe Home — "პოლიში" ფენა: გახსნის ანიმაცია (ლოგოს შაფლი), ფონტი, ანიმაციები, ყველგან კოპირება და ჩასმა.
   დამოუკიდებელი ფაილია: app.js მას ცალკე ტვირთავს; ჩავარდნისას (ან გამორთვისას: localStorage shPolish=0) აპი ძველებურად მუშაობს.
   არც ერთ ფუნქციას/კლასს, რომელზეც app.js ეყრდნობა, არ ცვლის — მხოლოდ ამატებს. */
(function () {
  "use strict";
  if (window.__shPolish) return;
  try { if (localStorage.getItem("shPolish") === "0") return; } catch (e) { /* ignore */ }
  window.__shPolish = true;

  var tg = window.Telegram ? window.Telegram.WebApp : null;
  var reduce = false;
  try { reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { /* ignore */ }
  var T = window.__shPolishTest || {};                     /* ტესტებისთვის: დროების შემცირება */
  var MIN_SPLASH = T.minSplash != null ? T.minSplash : (reduce ? 300 : 1700), MAX_SPLASH = T.maxSplash != null ? T.maxSplash : 4500;

  function hap(kind) {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (kind === "ok") tg.HapticFeedback.notificationOccurred("success"); else tg.HapticFeedback.impactOccurred(kind || "light");
    } catch (e) { /* ignore */ }
  }
  function say(msg) {
    try { if (typeof window.toast === "function") { window.toast(msg); return; } } catch (e) { /* ignore */ }
    var el = document.getElementById("toast");
    if (el) { el.textContent = msg; el.classList.add("show"); setTimeout(function () { el.classList.remove("show"); }, 2200); }
  }

  /* ------------------------------------------------------------------ ფონტი: ქართულისთვის Noto Sans/Serif Georgian */
  try {
    var fl = document.createElement("link");
    fl.rel = "stylesheet";
    fl.href = "https://fonts.googleapis.com/css2?family=Noto+Sans+Georgian:wght@400;500;600;700;800&family=Noto+Serif+Georgian:wght@600;700&display=swap";
    document.head.appendChild(fl);
  } catch (e) { /* ignore */ }

  /* ------------------------------------------------------------------ სტილები */
  var css = [
    ':root{--font-ui:"Manrope","Noto Sans Georgian",-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif;',
    '--font-brand:"Cormorant Garamond","Noto Serif Georgian",Georgia,"Times New Roman",serif}',
    "*{-webkit-tap-highlight-color:transparent}",
    /* არჩევა/კოპირება ყველგან, გარდა ღილაკებისა */
    "body *{-webkit-user-select:text;user-select:text;-webkit-touch-callout:default}",
    "button,.tabbar,.tabbar *,.hub-chip,.chip,.roleswitch *,.brand-mark,.sitelink,.hub-pill,.cp-i,#shPasteChip *,.hub-lb *{-webkit-user-select:none;user-select:none}",
    /* სპლეში */
    "#shSplash{position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;background:radial-gradient(520px 520px at 50% 42%,rgba(201,162,39,.20),transparent 62%),radial-gradient(900px 600px at 50% 110%,rgba(233,196,106,.10),transparent 60%),#0a1420;transition:opacity .6s ease,transform .6s cubic-bezier(.4,0,.2,1);overflow:hidden}",
    "#shSplash.out{opacity:0;transform:scale(1.06);pointer-events:none}",
    "#shSplash .sp-ring{position:relative;width:148px;height:148px;display:flex;align-items:center;justify-content:center}",
    "#shSplash .sp-ring svg{position:absolute;inset:0;transform:rotate(-90deg);filter:drop-shadow(0 0 14px rgba(233,196,106,.55))}",
    "#shSplash .sp-ring circle{fill:none;stroke:url(#spg);stroke-width:3;stroke-linecap:round;stroke-dasharray:420;stroke-dashoffset:420;animation:spDraw 1.5s .15s cubic-bezier(.5,0,.2,1) forwards}",
    "#shSplash .sp-ring circle.bg{stroke:rgba(201,162,39,.14);stroke-dashoffset:0;animation:none}",
    "#shSplash .sp-mark{width:84px;height:84px;border-radius:24px;display:flex;align-items:center;justify-content:center;font-family:var(--font-brand);font-weight:700;font-size:38px;letter-spacing:1px;color:#0a1420;background:linear-gradient(150deg,#f2d78b,#c9a227 60%,#a9821c);box-shadow:0 0 50px rgba(201,162,39,.55),inset 0 1px 0 rgba(255,255,255,.5);animation:spPop .8s .1s cubic-bezier(.2,1.4,.4,1) both;position:relative;overflow:hidden}",
    "#shSplash .sp-mark::after{content:'';position:absolute;top:-30%;bottom:-30%;width:40%;left:-60%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.75),transparent);transform:skewX(-20deg);animation:spGlint 1.1s .9s ease-in-out 1}",
    "#shSplash .sp-word{margin-top:26px;font-family:var(--font-brand);font-weight:700;font-size:30px;color:#e9c46a;display:flex;gap:2px;height:38px;text-shadow:0 0 24px rgba(233,196,106,.4)}",
    "#shSplash .sp-word span{display:inline-block;min-width:.72em;text-align:center}",
    "#shSplash .sp-word span.sp{min-width:.4em}",
    "#shSplash .sp-word span.rnd{opacity:.55;color:#93a6bc}",
    "#shSplash .sp-sub{margin-top:10px;font-size:12px;letter-spacing:.42em;color:#93a6bc;text-transform:uppercase;opacity:0;animation:spFade .7s 1.1s forwards}",
    "#shSplash .sp-bar{margin-top:28px;width:120px;height:3px;border-radius:3px;background:rgba(147,166,188,.18);overflow:hidden}",
    "#shSplash .sp-bar i{display:block;height:100%;width:40%;border-radius:3px;background:linear-gradient(90deg,transparent,#e9c46a,transparent);animation:spBar 1.1s ease-in-out infinite}",
    "#shSplash .sp-dust{position:absolute;border-radius:50%;background:#e9c46a;opacity:0;animation:spDust 3.2s ease-in-out infinite}",
    "@keyframes spDraw{to{stroke-dashoffset:0}}",
    "@keyframes spPop{from{opacity:0;transform:scale(.4) rotate(-14deg)}to{opacity:1;transform:none}}",
    "@keyframes spGlint{to{left:130%}}",
    "@keyframes spFade{to{opacity:1}}",
    "@keyframes spBar{from{transform:translateX(-120%)}to{transform:translateX(300%)}}",
    "@keyframes spDust{0%{opacity:0;transform:translateY(20px) scale(.6)}30%{opacity:.8}100%{opacity:0;transform:translateY(-120px) scale(1.2)}}",
    /* ბრენდის ნიშნის ბზინვა */
    ".brand-mark{position:relative;overflow:hidden}",
    ".brand-mark::after{content:'';position:absolute;top:-30%;bottom:-30%;width:35%;left:-70%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.7),transparent);transform:skewX(-20deg);animation:shGlint 5.5s ease-in-out 2.5s infinite}",
    "@keyframes shGlint{0%,70%{left:-70%}100%{left:150%}}",
    /* ბარათების ეტაპობრივი გამოჩენა (არსებული fadeInUp-ის გაუმჯობესება) */
    "#content>.card:nth-child(2){animation-delay:.05s}#content>.card:nth-child(3){animation-delay:.1s}#content>.card:nth-child(4){animation-delay:.15s}#content>.card:nth-child(5){animation-delay:.2s}#content>.card:nth-child(6){animation-delay:.25s}#content>.card:nth-child(n+7){animation-delay:.3s}",
    ".hub-card:nth-child(2){animation-delay:.04s}.hub-card:nth-child(3){animation-delay:.08s}.hub-card:nth-child(4){animation-delay:.12s}.hub-card:nth-child(5){animation-delay:.16s}.hub-card:nth-child(6){animation-delay:.2s}.hub-card:nth-child(n+7){animation-delay:.24s}",
    ".hub-card:active{transform:scale(.985)}",
    /* მოდალი */
    ".modal-backdrop:not([hidden]){animation:shFade .22s ease both}",
    ".modal-backdrop:not([hidden]) .modal{animation:shUp .36s cubic-bezier(.2,.9,.25,1) both}",
    "@keyframes shFade{from{opacity:0}to{opacity:1}}@keyframes shUp{from{opacity:0;transform:translateY(34px) scale(.985)}to{opacity:1;transform:none}}",
    /* ღილაკები და ტაბები */
    ".btn,.tabbar button,.roleswitch button,.hub-chip,.chip{transition:transform .12s ease,box-shadow .2s ease,background .2s ease,color .2s ease}",
    ".tabbar button:active{transform:scale(.92)}",
    ".tabbar button.active .ic{animation:shBounce .5s cubic-bezier(.3,1.6,.5,1)}",
    "@keyframes shBounce{0%{transform:translateY(4px) scale(.8)}60%{transform:translateY(-4px) scale(1.2)}100%{transform:translateY(-1px) scale(1.08)}}",
    ".btn:not([disabled]){position:relative;overflow:hidden}",
    ".btn .sh-rip{position:absolute;border-radius:50%;background:rgba(255,255,255,.35);transform:scale(0);animation:shRip .55s ease-out forwards;pointer-events:none}",
    "@keyframes shRip{to{transform:scale(1);opacity:0}}",
    /* კოპირების ხატულა */
    ".cp-i{display:inline-block;margin-left:8px;padding:0 7px;border-radius:8px;font-style:normal;font-size:12px;line-height:20px;color:#e9c46a;background:rgba(201,162,39,.14);border:1px solid rgba(201,162,39,.3);vertical-align:middle;cursor:pointer;transition:transform .12s,background .2s}",
    ".cp-i:active{transform:scale(.88);background:rgba(201,162,39,.3)}.cp-i.ok{color:#34d399;border-color:rgba(52,211,153,.5);background:rgba(52,211,153,.14)}",
    /* ჩასმის ჩიპი */
    "#shPasteChip{position:fixed;z-index:9000;display:none;gap:6px;transform:translateY(4px);opacity:0;transition:opacity .15s,transform .15s}",
    "#shPasteChip.on{display:flex;opacity:1;transform:none}",
    "#shPasteChip button{border:none;border-radius:99px;padding:8px 13px;font-size:13px;font-weight:800;font-family:inherit;color:#16202c;background:linear-gradient(135deg,#f2d78b,#c9a227);box-shadow:0 6px 18px rgba(0,0,0,.45)}",
    "#shPasteChip button.sec{color:#e9c46a;background:#10263c;border:1px solid rgba(201,162,39,.4)}",
    "#shPasteChip button:active{transform:scale(.94)}",
    /* ჩასმის ფურცელი (თუ ბუფერი პირდაპირ არ იკითხება) */
    "#shPasteSheet{position:fixed;inset:0;z-index:9500;background:rgba(5,10,18,.72);display:flex;align-items:flex-end;justify-content:center;animation:shFade .2s}",
    "#shPasteSheet .box{width:100%;max-width:560px;background:linear-gradient(180deg,#17324c,#10263c);border-radius:22px 22px 0 0;padding:18px 16px 22px;border:1px solid rgba(201,162,39,.25);animation:shUp .3s cubic-bezier(.2,.9,.25,1)}",
    "#shPasteSheet h4{margin:0 0 6px;font-size:15px;color:#e9c46a}#shPasteSheet p{margin:0 0 10px;font-size:12.5px;color:#93a6bc;line-height:1.45}",
    "#shPasteSheet textarea{width:100%;min-height:84px;border-radius:13px;border:1px solid rgba(201,162,39,.35);background:rgba(10,20,32,.7);color:#f3efe4;padding:10px;font-family:inherit;font-size:15px}",
    "#shPasteSheet .row{display:flex;gap:8px;margin-top:10px}#shPasteSheet .row button{flex:1;border:none;border-radius:13px;padding:12px;font-weight:800;font-family:inherit;font-size:14px}",
    "#shPasteSheet .ok{background:linear-gradient(135deg,#f2d78b,#c9a227);color:#16202c}#shPasteSheet .no{background:#10263c;color:#93a6bc;border:1px solid rgba(147,166,188,.25)}",
    /* "კარის გაღება" — განცხადების გახსნისას */
    ".sh-door{position:fixed;inset:0;z-index:9100;pointer-events:none;overflow:hidden}",
    ".sh-door i{position:absolute;top:0;bottom:0;width:50.5%;background:repeating-linear-gradient(0deg,transparent 0 46px,rgba(201,162,39,.16) 46px 48px),linear-gradient(180deg,#17324c,#0a1420);box-shadow:inset 0 0 0 2px rgba(233,196,106,.35),0 0 60px rgba(0,0,0,.6);animation:shDoorOpen .62s .16s cubic-bezier(.65,0,.2,1) forwards}",
    ".sh-door i.l{left:0;transform-origin:left center;--dx:-102%}.sh-door i.r{right:0;--dx:102%}",
    ".sh-door i::after{content:'';position:absolute;top:50%;width:10px;height:54px;margin-top:-27px;border-radius:6px;background:linear-gradient(180deg,#f2d78b,#c9a227)}",
    ".sh-door i.l::after{right:14px}.sh-door i.r::after{left:14px}",
    ".sh-door b{position:absolute;left:50%;top:0;bottom:0;width:140px;margin-left:-70px;background:radial-gradient(closest-side,rgba(255,236,170,.95),rgba(233,196,106,.35) 55%,transparent);opacity:0;animation:shLight .62s .16s ease-out forwards}",
    "@keyframes shDoorOpen{to{transform:translateX(var(--dx))}}@keyframes shLight{0%{opacity:0;transform:scaleX(.2)}35%{opacity:1}100%{opacity:0;transform:scaleX(9)}}",
    "@media (prefers-reduced-motion:reduce){#shSplash *,.cp-i,.brand-mark::after,.modal,.modal-backdrop{animation-duration:.01s!important;animation-delay:0s!important}}"
  ].join("\n");
  var st = document.createElement("style");
  st.id = "shPolishCss";
  st.textContent = css;
  document.head.appendChild(st);

  /* ------------------------------------------------------------------ გახსნის ანიმაცია (SAFE HOME-ის შაფლი) */
  var splash = null, splashT0 = Date.now(), splashDone = false;
  function buildSplash() {
    splash = document.createElement("div");
    splash.id = "shSplash";
    var dust = "";
    for (var i = 0; i < 16; i++) {
      dust += '<span class="sp-dust" style="left:' + (6 + (i * 53) % 88) + '%;top:' + (48 + (i * 29) % 46) + '%;width:' + (2 + i % 3) + 'px;height:' + (2 + i % 3) + 'px;animation-delay:' + ((i * 0.23) % 2.6).toFixed(2) + 's"></span>';
    }
    splash.innerHTML = dust +
      '<div class="sp-ring"><svg viewBox="0 0 148 148" width="148" height="148"><defs><linearGradient id="spg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f2d78b"/><stop offset="1" stop-color="#c9a227"/></linearGradient></defs><circle class="bg" cx="74" cy="74" r="67"/><circle cx="74" cy="74" r="67"/></svg><div class="sp-mark">SH</div></div>' +
      '<div class="sp-word" id="spWord"></div><div class="sp-sub">Agency · SAIRO</div><div class="sp-bar"><i></i></div>';
    document.body.appendChild(splash);
    var target = "SAFE HOME", word = splash.querySelector("#spWord"), spans = [];
    for (var k = 0; k < target.length; k++) {
      var s = document.createElement("span");
      if (target[k] === " ") s.className = "sp";
      word.appendChild(s); spans.push(s);
    }
    var pool = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789#%&@$", t0 = Date.now();
    var iv = setInterval(function () {
      var el = Date.now() - t0, allDone = true;
      for (var j = 0; j < target.length; j++) {
        if (target[j] === " ") continue;
        var resolveAt = 450 + j * 95;
        if (el >= resolveAt) { spans[j].textContent = target[j]; spans[j].className = ""; }
        else { spans[j].textContent = pool[Math.floor(Math.random() * pool.length)]; spans[j].className = "rnd"; allDone = false; }
      }
      if (allDone) clearInterval(iv);
      if (!splash || splashDone) clearInterval(iv);
    }, 55);
    if (reduce) { for (var q = 0; q < target.length; q++) { spans[q].textContent = target[q] === " " ? "" : target[q]; spans[q].className = target[q] === " " ? "sp" : ""; } }
  }
  function appReady() {
    var tb = document.getElementById("tabbar"), c = document.getElementById("content");
    if (tb && !tb.hidden) return true;
    if (c && c.querySelector(".empty") && !c.querySelector(".skeleton")) return true;           /* შეცდომის ეკრანიც "მზადაა" */
    return false;
  }
  function endSplash() {
    if (!splash || splashDone) return;
    splashDone = true;
    hap("ok");
    splash.classList.add("out");
    var s = splash;
    setTimeout(function () { try { s.remove(); } catch (e) { /* ignore */ } }, 700);
  }
  function watchSplash() {
    var iv = setInterval(function () {
      var age = Date.now() - splashT0;
      if (age >= MAX_SPLASH || (age >= MIN_SPLASH && appReady())) { clearInterval(iv); endSplash(); }
    }, 80);
  }
  var firstOpen = true;
  try { firstOpen = !sessionStorage.getItem("shSplashSeen"); sessionStorage.setItem("shSplashSeen", "1"); } catch (e) { /* ignore */ }
  if (document.body && (firstOpen || T.forceSplash)) { buildSplash(); watchSplash(); }

  /* ------------------------------------------------------------------ კოპირება */
  function copyText(txt) {
    txt = String(txt == null ? "" : txt);
    function fallback() {
      return new Promise(function (resolve) {
        try {
          var ta = document.createElement("textarea");
          ta.value = txt; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;left:-999px;top:0;opacity:0";
          document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, txt.length);
          var ok = document.execCommand("copy"); ta.remove(); resolve(!!ok);
        } catch (e) { resolve(false); }
      });
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(txt).then(function () { return true; }, fallback);
    }
    return fallback();
  }
  window.shCopy = function (txt, okMsg) {
    return copyText(txt).then(function (ok) {
      if (ok) { hap("ok"); say(okMsg || "📋 დაკოპირდა"); } else { say("ვერ დაკოპირდა — გამოყავით და დააკოპირეთ ხელით"); }
      return ok;
    });
  };
  var COPY_SEL = ".field .v,.hub-kv b,.hub-loc,[data-copy]";
  function cleanText(el) {
    var c = el.cloneNode(true), ic = c.querySelectorAll(".cp-i");
    for (var i = 0; i < ic.length; i++) ic[i].remove();
    return (c.getAttribute && c.getAttribute("data-copy")) || c.textContent.replace(/^\s*📍\s*/, "").trim();
  }
  function enhanceCopy(root) {
    if (!root || !root.querySelectorAll) return;
    var list = root.matches && root.matches(COPY_SEL) ? [root] : [];
    var found = root.querySelectorAll(COPY_SEL);
    for (var i = 0; i < found.length; i++) list.push(found[i]);
    for (var j = 0; j < list.length; j++) {
      var el = list[j];
      if (el.getAttribute("data-cpd")) continue;
      var tx = cleanText(el);
      if (!tx || tx === "—" || tx.length > 400 || el.querySelector("button,input,select,textarea")) { el.setAttribute("data-cpd", "0"); continue; }
      el.setAttribute("data-cpd", "1");
      var b = document.createElement("i");
      b.className = "cp-i"; b.textContent = "⧉"; b.setAttribute("role", "button"); b.setAttribute("aria-label", "დაკოპირება");
      el.appendChild(b);
    }
  }
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.classList || !t.classList.contains("cp-i")) return;
    e.stopPropagation(); e.preventDefault();
    var host = t.parentNode;
    window.shCopy(cleanText(host)).then(function (ok) {
      if (!ok) return;
      t.classList.add("ok"); var old = t.textContent; t.textContent = "✓";
      setTimeout(function () { t.classList.remove("ok"); t.textContent = old; }, 1100);
    });
  }, true);

  /* ------------------------------------------------------------------ ჩასმა (ID / ტელეფონი / ბმული) */
  var chip = document.createElement("div");
  chip.id = "shPasteChip";
  chip.innerHTML = '<button type="button" data-a="paste">📋 ჩასმა</button><button type="button" class="sec" data-a="copy">⧉</button>';
  document.body.appendChild(chip);
  var cur = null, hideT = null;
  var SKIP_TYPES = { password: 1, checkbox: 1, radio: 1, file: 1, range: 1, date: 1, time: 1, "datetime-local": 1, button: 1, submit: 1, color: 1, hidden: 1 };
  function fieldKind(el) {
    var ph = (el.getAttribute("placeholder") || "") + " " + (el.getAttribute("aria-label") || ""), id = el.id || "";
    if (el.getAttribute("data-paste")) return el.getAttribute("data-paste");
    if (id === "mhListingId" || /\bID\b|ბმულ/i.test(ph)) return "id";
    if (el.type === "tel" || /tel/i.test(el.getAttribute("inputmode") || "") || /ტელეფონ|ნომერ/.test(ph)) return "phone";
    return "text";
  }
  function smartValue(kind, raw) {
    var s = String(raw == null ? "" : raw).trim();
    if (!s) return "";
    if (kind === "id") {
      var m = /\/pr\/(\d{5,10})/.exec(s) || /(?:^|[^\d])(\d{6,10})(?:[^\d]|$)/.exec(s);
      return m ? m[1] : s.replace(/[^\d]/g, "");
    }
    if (kind === "phone") return s.replace(/[^\d+\s()-]/g, "").replace(/\s+/g, " ").trim();
    return s;
  }
  function setVal(el, v) {
    var proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var d = Object.getOwnPropertyDescriptor(proto, "value");
    if (d && d.set) d.set.call(el, v); else el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    try { el.focus(); } catch (e) { /* ignore */ }
  }
  function readClip() {
    return new Promise(function (resolve) {
      var done = false;
      function fin(v) { if (!done) { done = true; resolve(v); } }
      function viaNav() {
        if (navigator.clipboard && navigator.clipboard.readText) {
          navigator.clipboard.readText().then(function (t) { fin(t || null); }, function () { fin(null); });
          setTimeout(function () { fin(null); }, 1500);
        } else fin(null);
      }
      try {
        if (tg && tg.readTextFromClipboard && tg.isVersionAtLeast && tg.isVersionAtLeast("6.4")) {
          var answered = false;
          tg.readTextFromClipboard(function (t) { answered = true; if (t) fin(t); else viaNav(); });
          setTimeout(function () { if (!answered) viaNav(); }, 900);
          return;
        }
      } catch (e) { /* ignore */ }
      viaNav();
    });
  }
  function pasteSheet(el, kind) {
    var old = document.getElementById("shPasteSheet"); if (old) old.remove();
    var sh = document.createElement("div");
    sh.id = "shPasteSheet";
    sh.innerHTML = '<div class="box"><h4>📋 ჩასმა</h4><p>ტელეფონი ბუფერს პირდაპირ არ გვაძლევს. დააჭირეთ ქვემოთ ველს ხანგრძლივად და აირჩიეთ „ჩასმა/Paste“ — დანარჩენს (ID-ის ამოღებას ბმულიდან) აპი გააკეთებს.</p><textarea id="shPasteTa" placeholder="აქ ჩასვით…"></textarea><div class="row"><button class="no" type="button">გაუქმება</button><button class="ok" type="button">✅ გამოყენება</button></div></div>';
    document.body.appendChild(sh);
    var ta = sh.querySelector("textarea"); setTimeout(function () { try { ta.focus(); } catch (e) { /* ignore */ } }, 80);
    sh.querySelector(".no").onclick = function () { sh.remove(); };
    sh.onclick = function (e) { if (e.target === sh) sh.remove(); };
    sh.querySelector(".ok").onclick = function () { var v = smartValue(kind, ta.value); sh.remove(); if (v) { setVal(el, v); hap("ok"); say("✅ ჩაისვა"); } };
  }
  function doPaste(el) {
    var kind = fieldKind(el);
    readClip().then(function (t) {
      var v = smartValue(kind, t);
      if (v) { setVal(el, v); hap("ok"); say(kind === "id" && v !== String(t).trim() ? "✅ ID ამოვიღე ბმულიდან" : "✅ ჩაისვა"); }
      else pasteSheet(el, kind);
    });
  }
  window.shPaste = doPaste;
  function placeChip(el) {
    var r = el.getBoundingClientRect();
    if (r.width < 40 || r.bottom < 0 || r.top > innerHeight) { chip.classList.remove("on"); return; }
    var w = 170, top = r.top - 38; if (top < 6) top = r.bottom + 6;
    chip.style.top = Math.round(top) + "px";
    chip.style.left = Math.round(Math.min(innerWidth - w - 6, Math.max(6, r.right - w))) + "px";
    chip.classList.add("on");
  }
  function ok(el) {
    return el && el.tagName && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !SKIP_TYPES[(el.type || "text").toLowerCase()])) && !el.readOnly && !el.disabled && el.id !== "shPasteTa";
  }
  document.addEventListener("focusin", function (e) {
    if (!ok(e.target)) return;
    clearTimeout(hideT); cur = e.target; placeChip(cur);
    chip.querySelector('[data-a="copy"]').style.display = cur.value ? "" : "none";
  }, true);
  document.addEventListener("input", function (e) { if (e.target === cur) chip.querySelector('[data-a="copy"]').style.display = cur.value ? "" : "none"; }, true);
  document.addEventListener("focusout", function (e) { if (e.target === cur) { hideT = setTimeout(function () { chip.classList.remove("on"); cur = null; }, 260); } }, true);
  chip.addEventListener("pointerdown", function (e) { e.preventDefault(); clearTimeout(hideT); });   /* ფოკუსი ველს არ ტოვებს */
  chip.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("button") : null;
    if (!b || !cur) return;
    if (b.getAttribute("data-a") === "paste") doPaste(cur);
    else window.shCopy(cur.value);
  });
  window.addEventListener("scroll", function () { if (cur) placeChip(cur); }, true);
  window.addEventListener("resize", function () { if (cur) placeChip(cur); });
  if (window.visualViewport) window.visualViewport.addEventListener("resize", function () { if (cur) placeChip(cur); });

  /* ------------------------------------------------------------------ კარის გაღება (განცხადების გახსნა) */
  window.shDoor = function () {
    if (reduce || window.__shNoDoor) return;
    try {
      var old = document.querySelector(".sh-door"); if (old) old.remove();
      var d = document.createElement("div");
      d.className = "sh-door"; d.innerHTML = '<i class="l"></i><i class="r"></i><b></b>';
      document.body.appendChild(d); hap("light");
      setTimeout(function () { try { d.remove(); } catch (e) { /* ignore */ } }, 900);
    } catch (e) { /* ignore */ }
  };

  /* ------------------------------------------------------------------ ღილაკებზე "ტალღა", რიცხვების აწევა */
  document.addEventListener("pointerdown", function (e) {
    var b = e.target.closest ? e.target.closest(".btn:not([disabled])") : null;
    if (!b || reduce) return;
    var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 1.6, s = document.createElement("span");
    s.className = "sh-rip"; s.style.width = s.style.height = d + "px"; s.style.left = (e.clientX - r.left - d / 2) + "px"; s.style.top = (e.clientY - r.top - d / 2) + "px";
    b.appendChild(s); setTimeout(function () { s.remove(); }, 600); hap("light");
  }, true);
  function countUp(el) {
    if (reduce || el.getAttribute("data-cu")) return;
    el.setAttribute("data-cu", "1");
    var txt = el.textContent.trim();
    if (!/^\d{1,6}$/.test(txt)) return;
    var end = parseInt(txt, 10); if (end < 2) return;
    var t0 = Date.now(), dur = 650, iv = setInterval(function () {
      var p = Math.min(1, (Date.now() - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(end * e));
      if (p >= 1) clearInterval(iv);
    }, 32);
    setTimeout(function () { clearInterval(iv); el.textContent = String(end); }, dur + 120);     /* ტაიმერები გაჩერდა/შენელდა => რიცხვი მაინც სწორია */
  }
  function scan(root) {
    if (!root || root.nodeType !== 1) return;
    enhanceCopy(root);
    var nums = root.querySelectorAll ? root.querySelectorAll(".stat .num") : [];
    for (var i = 0; i < nums.length; i++) countUp(nums[i]);
  }
  var scanQ = [], scanT = null;
  var mo = new MutationObserver(function (list) {
    for (var i = 0; i < list.length; i++) for (var j = 0; j < list[i].addedNodes.length; j++) { var n = list[i].addedNodes[j]; if (n.nodeType === 1 && !(n.classList && n.classList.contains("cp-i"))) scanQ.push(n); }
    if (scanQ.length && !scanT) scanT = setTimeout(function () { var q = scanQ; scanQ = []; scanT = null; for (var k = 0; k < q.length; k++) scan(q[k]); }, 30);
  });
  mo.observe(document.body, { childList: true, subtree: true });
  scan(document.body);
})();
