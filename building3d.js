/* Safe Home — შენობის 3D (იზომეტრიული) ხედი რუკისთვის: ერთ კორპუსში ბევრი ბინაა => კორპუსი "ამოვარდება", ჩანს სართულები,
   სართულზე დაჭერა => "ბინაში შესვლა" (კამერა ზუმდება, კარი იღება) და იხსნება განცხადება.
   ცალკე ფაილია (app.js მას რუკის დროს ტვირთავს); მონაცემებს არ ცვლის, ახალ მოთხოვნას სერვერზე არ აკეთებს. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var reduce = false;
  try { reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { /* ignore */ }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function S(tag, attrs, parent) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
  function num(v) { var n = parseInt(String(v == null ? "" : v).replace(/[^\d-]/g, ""), 10); return isNaN(n) ? null : n; }
  function money(n) { return n == null ? "—" : "$" + Math.round(n).toLocaleString("en-US"); }
  function hap(k) { try { var tg = window.Telegram && window.Telegram.WebApp; if (tg && tg.HapticFeedback) { if (k === "ok") tg.HapticFeedback.notificationOccurred("success"); else tg.HapticFeedback.impactOccurred(k || "light"); } } catch (e) { /* ignore */ } }

  var css = [
    ".b3d{position:fixed;inset:0;z-index:45;display:flex;flex-direction:column;background:radial-gradient(700px 500px at 50% 28%,rgba(233,196,106,.16),transparent 60%),radial-gradient(900px 700px at 50% 110%,rgba(23,50,76,.9),transparent 60%),#07101a;animation:b3in .35s ease both;overflow:hidden;color:#f3efe4;font-family:var(--font-ui,sans-serif)}",
    "@keyframes b3in{from{opacity:0}to{opacity:1}}",
    ".b3d.out{animation:b3out .3s ease both;pointer-events:none}@keyframes b3out{to{opacity:0}}",
    ".b3d-head{display:flex;align-items:flex-start;gap:10px;padding:16px 16px 6px;position:relative;z-index:3;transition:opacity .4s}",
    ".b3d-head h3{margin:0;font-size:17px;line-height:1.25}.b3d-head p{margin:3px 0 0;font-size:12.5px;color:#93a6bc}",
    ".b3d-x{margin-left:auto;flex:none;width:38px;height:38px;border-radius:50%;border:1px solid rgba(201,162,39,.35);background:rgba(16,38,60,.85);color:#e9c46a;font-size:16px}",
    ".b3d-stage{flex:1;min-height:0;position:relative;transition:transform .75s cubic-bezier(.55,0,.25,1),opacity .6s;will-change:transform}",
    ".b3d-stage svg{width:100%;height:100%;display:block;overflow:visible}",
    ".b3d.zoom .b3d-head,.b3d.zoom .b3d-sheet{opacity:0}",
    ".b3d-sheet{position:relative;z-index:3;padding:8px 12px 16px;transition:opacity .4s;max-height:38%;overflow:auto}",
    ".b3d-list{display:flex;gap:8px;overflow-x:auto;padding:4px 2px 8px;-webkit-overflow-scrolling:touch}",
    ".b3d-it{flex:none;min-width:150px;border-radius:15px;padding:9px 12px;font-size:12.5px;line-height:1.35;background:linear-gradient(180deg,#17324c,#10263c);border:1px solid rgba(147,166,188,.2);color:#f3efe4;text-align:left;font-family:inherit}",
    ".b3d-it b{display:block;font-size:15px;color:#e9c46a}.b3d-it.on{border-color:#e9c46a;box-shadow:0 0 0 2px rgba(233,196,106,.35),0 8px 24px rgba(0,0,0,.45)}",
    ".b3d-it i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}",
    ".b3d-go{display:block;width:100%;border:none;border-radius:16px;padding:14px;font-size:15px;font-weight:800;font-family:inherit;color:#16202c;background:linear-gradient(135deg,#f2d78b,#c9a227);box-shadow:0 8px 24px rgba(201,162,39,.35)}",
    ".b3d-go[disabled]{opacity:.45}",
    ".b3d-hint{font-size:12px;color:#93a6bc;text-align:center;padding:2px 0 8px}",
    ".b3-fl{animation:b3drop .7s cubic-bezier(.2,1.25,.4,1) both}",
    "@keyframes b3drop{from{opacity:0;transform:translateY(-420px)}55%{opacity:1}to{opacity:1;transform:none}}",
    ".b3-fl .face{transition:filter .25s}.b3-fl.lit{cursor:pointer}",
    ".b3-fl.lit:hover .face,.b3-fl.sel .face{filter:brightness(1.35)}",
    ".b3-fl.sel{animation:b3pulse 1.1s ease-in-out infinite}",
    "@keyframes b3pulse{0%,100%{filter:drop-shadow(0 0 4px rgba(233,196,106,.6))}50%{filter:drop-shadow(0 0 16px rgba(233,196,106,1))}}",
    ".b3-lbl{animation:b3lbl .5s ease both;cursor:pointer}@keyframes b3lbl{from{opacity:0;transform:translateX(24px)}to{opacity:1;transform:none}}",
    ".b3-lbl rect{transition:fill .2s,stroke .2s}.b3-lbl.sel rect{fill:#c9a227;stroke:#f2d78b}.b3-lbl.sel text{fill:#16202c}",
    ".b3-shadow{animation:b3sh .9s ease both;transform-box:fill-box;transform-origin:center}@keyframes b3sh{from{opacity:0;transform:scale(.3)}to{opacity:1;transform:none}}",
    ".b3-tower{animation:b3float 6s ease-in-out 1.6s infinite}@keyframes b3float{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}",
    ".b3-star{animation:b3tw 3s ease-in-out infinite}@keyframes b3tw{0%,100%{opacity:.15}50%{opacity:.9}}",
    ".hub-bld{background:linear-gradient(135deg,#17324c,#0e1e30)!important;border-color:#e9c46a!important;color:#f2d78b;gap:5px;animation:bldPop .5s cubic-bezier(.2,1.4,.4,1) both}",
    ".hub-bld small{font-size:10.5px;font-weight:700;color:#93a6bc}",
    "@keyframes bldPop{from{transform:translate(-50%,-50%) scale(.3)}to{transform:translate(-50%,-50%) scale(1)}}",
    "@media (prefers-reduced-motion:reduce){.b3-fl,.b3-lbl,.b3-shadow,.b3-tower,.b3-star{animation-duration:.01s!important;animation-delay:0s!important}}"
  ].join("\n");
  function ensureCss() { if (document.getElementById("b3dCss")) return; var s = document.createElement("style"); s.id = "b3dCss"; s.textContent = css; document.head.appendChild(s); }

  var FR = { green: "#34d399", orange: "#f5b942", red: "#f26d6d", grey: "#93a6bc" };

  /* წმინდა გათვლა: სართულები, ბინები სართულებზე (ტესტირებადი) */
  function plan(items) {
    var fl = items.map(function (p) { return num(p.floor); });
    var declared = 0;
    items.forEach(function (p) { var t = num(p.floors); if (t && t > declared) declared = t; });
    var maxF = Math.max.apply(null, fl.filter(function (x) { return x != null; }).concat([0]));
    var total = Math.max(declared, maxF, 2);
    var capped = total > 40; if (capped) total = 40;
    var byFloor = {}, unknown = [];
    items.forEach(function (p, i) {
      var f = fl[i];
      if (f == null || f < 1 || f > total) unknown.push(p); else (byFloor[f] = byFloor[f] || []).push(p);
    });
    return { total: total, byFloor: byFloor, unknown: unknown, capped: capped };
  }

  function build(b, api) {
    ensureCss();
    var old = document.getElementById("b3d"); if (old) old.remove();
    var items = (b.items || []).slice();
    var pl = plan(items);
    var addr = items[0] && items[0].addr ? items[0].addr : "შენობა";
    var ov = document.createElement("div");
    ov.id = "b3d"; ov.className = "b3d";
    ov.innerHTML = '<div class="b3d-head"><div><h3>🏢 ' + esc(addr) + '</h3><p>' + items.length + " ბინა გაყიდვაში/ქირაში · " + pl.total + ' სართული' + (pl.capped ? "+" : "") + '</p></div><button class="b3d-x" type="button" aria-label="დახურვა">✕</button></div>' +
      '<div class="b3d-stage"></div><div class="b3d-sheet"><div class="b3d-hint">დააჭირეთ ოქროსფერ სართულს ან ბინას სიიდან</div><div class="b3d-list"></div><button class="b3d-go" type="button" disabled>🚪 ბინაში შესვლა</button></div>';
    document.body.appendChild(ov);

    var stage = ov.querySelector(".b3d-stage"), list = ov.querySelector(".b3d-list"), go = ov.querySelector(".b3d-go");
    var H = Math.max(14, Math.min(30, Math.floor(430 / pl.total))), a = 86, d = 44, cx = 205;
    var top = 70, gy = top + pl.total * H + 30, vbW = 540, vbH = gy + d + 70;
    var svg = S("svg", { viewBox: "0 0 " + vbW + " " + vbH, preserveAspectRatio: "xMidYMid meet" }, stage);
    var defs = S("defs", {}, svg);
    function grad(id, c1, c2, x2, y2) { var g = S("linearGradient", { id: id, x1: 0, y1: 0, x2: x2, y2: y2 }, defs); S("stop", { offset: 0, "stop-color": c1 }, g); S("stop", { offset: 1, "stop-color": c2 }, g); }
    grad("b3L", "#27476b", "#17324c", 1, 1); grad("b3R", "#14283f", "#0b1827", 1, 1); grad("b3T", "#3a6190", "#27476b", 1, 1);
    grad("b3LL", "#c9a227", "#8a6d1a", 1, 1); grad("b3RR", "#8a6d1a", "#5c4812", 1, 1); grad("b3TT", "#f2d78b", "#e9c46a", 1, 1);
    var sun = S("radialGradient", { id: "b3S" }, defs); S("stop", { offset: 0, "stop-color": "#f2d78b", "stop-opacity": ".55" }, sun); S("stop", { offset: 1, "stop-color": "#f2d78b", "stop-opacity": 0 }, sun);
    S("circle", { cx: cx + 110, cy: top - 10, r: 170, fill: "url(#b3S)" }, svg);
    for (var s = 0; s < 22; s++) S("circle", { cx: 14 + (s * 211) % 520, cy: 10 + (s * 97) % 200, r: 1 + (s % 3) * .6, fill: "#e9c46a", "class": "b3-star", style: "animation-delay:" + ((s * .37) % 3).toFixed(2) + "s" }, svg);
    S("ellipse", { cx: cx, cy: gy + d + 6, rx: a + 60, ry: d + 22, fill: "rgba(0,0,0,.45)", "class": "b3-shadow" }, svg);
    S("ellipse", { cx: cx, cy: gy + d + 4, rx: a + 40, ry: d + 10, fill: "none", stroke: "rgba(233,196,106,.25)", "stroke-width": 2, "class": "b3-shadow" }, svg);
    var tower = S("g", { "class": "b3-tower" }, svg);

    var floorEls = {}, labelEls = [];
    for (var f = 1; f <= pl.total; f++) {
      var yb = gy - (f - 1) * H, has = pl.byFloor[f], lit = !!has;
      var g = S("g", { "class": "b3-fl" + (lit ? " lit" : ""), "data-f": f, style: "animation-delay:" + ((reduce ? 0 : (f - 1) * 0.055 + 0.15)).toFixed(3) + "s" }, tower);
      var L = [cx - a, yb], B = [cx, yb + d], R = [cx + a, yb], T = [cx, yb - d];
      function poly(pts, fill, extra) { return S("polygon", Object.assign({ points: pts.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "), fill: fill, "class": "face" }, extra || {}), g); }
      poly([L, B, [B[0], B[1] - H], [L[0], L[1] - H]], lit ? "url(#b3LL)" : "url(#b3L)", { stroke: "rgba(7,16,26,.6)", "stroke-width": 1 });
      poly([B, R, [R[0], R[1] - H], [B[0], B[1] - H]], lit ? "url(#b3RR)" : "url(#b3R)", { stroke: "rgba(7,16,26,.6)", "stroke-width": 1 });
      poly([[L[0], L[1] - H], [B[0], B[1] - H], [R[0], R[1] - H], [T[0], T[1] - H]], lit ? "url(#b3TT)" : "url(#b3T)", { stroke: "rgba(7,16,26,.5)", "stroke-width": 1 });
      var wh = H * 0.5, lo = H * 0.25;
      [[L, B, 1], [B, R, -1]].forEach(function (side, si) {
        [0.17, 0.5, 0.83].forEach(function (u, ui) {
          var w = 0.19, p0 = [side[0][0] + (side[1][0] - side[0][0]) * (u - w / 2), side[0][1] + (side[1][1] - side[0][1]) * (u - w / 2)], p1 = [side[0][0] + (side[1][0] - side[0][0]) * (u + w / 2), side[0][1] + (side[1][1] - side[0][1]) * (u + w / 2)];
          var on = lit || ((f * 7 + si * 3 + ui * 5) % 5 === 0);
          S("polygon", { points: [[p0[0], p0[1] - lo], [p1[0], p1[1] - lo], [p1[0], p1[1] - lo - wh], [p0[0], p0[1] - lo - wh]].map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "), fill: on ? (lit ? "#ffe9a8" : "#d9b45a") : "#0d1d30", opacity: on ? 0.95 : 0.85 }, g);
        });
      });
      if (f === 1) {                                                       /* შესასვლელი კარი */
        var dx0 = B[0] + 8, dx1 = B[0] + 8 + 26, k = (R[1] - B[1]) / (R[0] - B[0]);
        S("polygon", { points: [[dx0, B[1] + (dx0 - B[0]) * k], [dx1, B[1] + (dx1 - B[0]) * k], [dx1, B[1] + (dx1 - B[0]) * k - H * 0.8], [dx0, B[1] + (dx0 - B[0]) * k - H * 0.8]].map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "), fill: "#e9c46a", opacity: 0.9 }, g);
      }
      floorEls[f] = g;
      if (lit) {
        g.addEventListener("click", (function (ff) { return function () { var arr = pl.byFloor[ff]; select(arr[0].id); }; })(f));
      }
    }
    /* სახურავი */
    var yr = gy - pl.total * H, rg = S("g", { "class": "b3-fl", style: "animation-delay:" + ((reduce ? 0 : pl.total * 0.055 + 0.25)).toFixed(3) + "s" }, tower);
    S("polygon", { points: [[cx - a - 5, yr], [cx, yr + d + 5], [cx + a + 5, yr], [cx, yr - d - 5]].map(function (p) { return p.join(","); }).join(" "), fill: "#4a76a8", stroke: "rgba(7,16,26,.5)" }, rg);
    S("polygon", { points: [[cx - 14, yr - 6], [cx, yr + 1], [cx + 14, yr - 6], [cx, yr - 13]].map(function (p) { return p.join(","); }).join(" "), fill: "#27476b" }, rg);
    S("rect", { x: cx - 14, y: yr - 30, width: 28, height: 24, fill: "#17324c", opacity: 0.0 }, rg);
    S("line", { x1: cx + 30, y1: yr - 4, x2: cx + 30, y2: yr - 44, stroke: "#93a6bc", "stroke-width": 2 }, rg);
    S("circle", { cx: cx + 30, cy: yr - 46, r: 3.2, fill: "#f26d6d", "class": "b3-star" }, rg);

    /* ეტიკეტები მარჯვნივ (ერთმანეთს არ ფარავს) */
    var rows = [];
    Object.keys(pl.byFloor).forEach(function (fk) {
      var f2 = +fk, yb2 = gy - (f2 - 1) * H;
      pl.byFloor[fk].forEach(function (p) { rows.push({ p: p, f: f2, y: yb2 - H / 2 }); });
    });
    rows.sort(function (x, y) { return x.y - y.y; });
    var minGap = 34, lastY = -1e9;
    rows.forEach(function (r) { r.ly = Math.max(r.y, lastY + minGap); lastY = r.ly; });
    rows.forEach(function (r, i) {
      var lx = cx + a + 44, g2 = S("g", { "class": "b3-lbl", "data-id": r.p.id, style: "animation-delay:" + ((reduce ? 0 : pl.total * 0.055 + 0.5 + i * 0.07)).toFixed(2) + "s" }, svg);
      S("line", { x1: cx + a, y1: r.y, x2: lx, y2: r.ly, stroke: "rgba(233,196,106,.55)", "stroke-width": 1.5, "stroke-dasharray": "3 3" }, g2);
      S("rect", { x: lx, y: r.ly - 15, width: 190, height: 30, rx: 15, fill: "#10263c", stroke: "rgba(233,196,106,.55)", "stroke-width": 1.5 }, g2);
      var t = S("text", { x: lx + 12, y: r.ly + 5, fill: "#f3efe4", "font-size": 12.5, "font-weight": 800, "font-family": "inherit" }, g2);
      t.textContent = r.f + " სს · " + money(r.p.price) + (r.p.rooms ? " · " + r.p.rooms + "ოთ" : "") + (/ქირ/.test(r.p.deal || "") ? "/თვე" : "");
      g2.addEventListener("click", function () { select(r.p.id); });
      labelEls.push(g2);
    });

    /* ქვედა სია */
    var sorted = items.slice().sort(function (x, y) { return (num(y.floor) || 0) - (num(x.floor) || 0); });
    sorted.forEach(function (p) {
      var bt = document.createElement("button");
      bt.type = "button"; bt.className = "b3d-it"; bt.setAttribute("data-id", p.id);
      bt.innerHTML = '<b>' + money(p.price) + (/ქირ/.test(p.deal || "") ? " /თვე" : "") + '</b><i style="background:' + (FR[p.fr] || FR.grey) + '"></i>' + (num(p.floor) ? p.floor + " სართული" : "სართული უცნობია") + (p.rooms ? " · " + esc(p.rooms) + " ოთ" : "") + (p.area ? " · " + Math.round(p.area) + " მ²" : "");
      bt.onclick = function () { select(p.id); };
      list.appendChild(bt);
    });

    var selId = null;
    function select(id) {
      selId = id; hap("light");
      var it = items.filter(function (x) { return x.id === id; })[0];
      Object.keys(floorEls).forEach(function (k) { floorEls[k].classList.remove("sel"); });
      var fnum = it ? num(it.floor) : null;
      if (fnum && floorEls[fnum]) floorEls[fnum].classList.add("sel");
      labelEls.forEach(function (l) { l.classList.toggle("sel", l.getAttribute("data-id") === id); });
      Array.prototype.forEach.call(list.children, function (c) { c.classList.toggle("on", c.getAttribute("data-id") === id); if (c.getAttribute("data-id") === id && c.scrollIntoView) { try { c.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" }); } catch (e) { /* ignore */ } } });
      go.disabled = !it;
      go.textContent = it ? "🚪 ბინაში შესვლა — " + money(it.price) + (fnum ? " · " + fnum + " სს" : "") : "🚪 ბინაში შესვლა";
      ov.querySelector(".b3d-hint").style.display = "none";
    }
    function close() { ov.classList.add("out"); setTimeout(function () { ov.remove(); }, 320); }
    ov.querySelector(".b3d-x").onclick = close;
    go.onclick = function () {
      if (!selId) return;
      hap("ok");
      var it = items.filter(function (x) { return x.id === selId; })[0], fnum = it ? num(it.floor) : null, fe = fnum && floorEls[fnum];
      function openNow() { try { api.open(selId); } catch (e) { /* ignore */ } setTimeout(function () { stage.style.transition = "none"; stage.style.transform = ""; stage.style.opacity = 1; ov.classList.remove("zoom"); void stage.offsetWidth; stage.style.transition = ""; }, 900); }
      if (reduce || !fe) { openNow(); return; }
      var sr = stage.getBoundingClientRect(), fr = fe.getBoundingClientRect();
      var ox = fr.left + fr.width / 2 - sr.left, oy = fr.top + fr.height / 2 - sr.top;                       /* კამერა სართულისკენ იწევა */
      stage.style.transformOrigin = ox + "px " + oy + "px";
      ov.classList.add("zoom");
      stage.style.transform = "scale(5.5)";
      setTimeout(function () { stage.style.opacity = 0.0; }, 480);
      setTimeout(openNow, 560);
    };
    if (sorted.length && sorted.some(function (p) { return num(p.floor); })) { /* არჩევა არ ხდება ავტომატურად — მომხმარებელი თავად ირჩევს */ }
    return { el: ov, select: select, close: close };
  }

  window.shBuilding3D = function (b, api) { return build(b, api || {}); };
  window.shBuilding3D.plan = plan;
})();
