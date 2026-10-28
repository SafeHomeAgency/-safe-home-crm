/* Safe Home Agency — Mini App dashboard (frontend, no build step). */

/* დაუჭერელი JS შეცდომების "დაჭერა" — რომ თუ რამე გაფუჭდა, ეკრანი
   უბრალოდ არ "გაშავდეს" დუმილში, არამედ თავად შეცდომის ტექსტი ჩანდეს
   (ეს გვეხმარება მალე ვიპოვოთ პრობლემა). */
window.addEventListener("error", (ev) => {
  const content = document.getElementById("content");
  if (content) {
    content.innerHTML = `<div class="card"><div class="empty">⚠️ JS შეცდომა: ${String(ev.message || ev)} </div></div>`;
  }
});

const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) {
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor("secondary_bg_color"); } catch (e) {}
  // მნიშვნელოვანი მობილურზე სქროლისთვის: ამის გარეშე ტელეგრამის
  // კლიენტი გვერდზე ვერტიკალურ სვაიპს საკუთარ თავზე (მინი აპის
  // დახურვა/მინიმიზება) იღებს და გვერდის შიგნით სქროლვას ბლოკავს.
  try { tg.disableVerticalSwipes(); } catch (e) {}
}

const MODE_LABELS = {
  office_morning: "ოფისი — დილის ცვლა",
  office_evening: "ოფისი — საღამოს ცვლა",
  online: "ონლაინ დღე",
  off: "დასვენება",
};
/* ერთი, ცალსახა ემოჯი თითო რეჟიმზე (არა კომბინაცია) — ოფისის დილის
   ცვლა = მზე, ოფისის საღამოს ცვლა = მზის ჩასვლა, სახლიდან (online) =
   სახლი, დასვენება = მთვარე. */
const MODE_ICON = { office_morning: "☀️", office_evening: "🌇", online: "🏠", off: "🌙" };
const MODE_SUBLABEL = { office_morning: "დილა", office_evening: "საღამო", online: "სახლი", off: "" };
const WEEKDAY_LABELS = { mon: "ორშ", tue: "სამ", wed: "ოთხ", thu: "ხუთ", fri: "პარ", sat: "შაბ", sun: "კვ" };
const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const WARNING_LABELS = {
  late_report: "დაგვიანებული/გამოტოვებული ანგარიში",
  late_arrival: "დაგვიანება სამუშაოზე",
  no_show: "არ გამოცხადება",
  quota_missed: "დღიური გეგმა ვერ შესრულდა",
};

const state = { role: null, data: null, tab: {}, period: "month" };

const AGENT_TABS = [
  { id: "today", label: "დღეს", icon: "🏠" },
  { id: "tasks", label: "დავალებები", icon: "📋" },
  { id: "kpi", label: "KPI", icon: "📈" },
  { id: "myattendance", label: "დასწრება", icon: "🕘", lazy: true },
  { id: "mydayoffs", label: "შვებულება", icon: "🏖️", lazy: true },
  { id: "taskhistory", label: "ისტორია", icon: "📜", lazy: true },
  { id: "meetings", label: "შეხვედრები", icon: "🤝", lazy: true },
  { id: "exclusives", label: "ექსკლუზივები", icon: "🏘️", lazy: true },
  { id: "myhomejobs", label: "MyHome", icon: "🏘️", lazy: true },
  { id: "questions", label: "კითხვები", icon: "💬", lazy: true },
  { id: "regulations", label: "ინსტრუქცია", icon: "📘", lazy: true },
  { id: "crm2", label: "CRM", icon: "🗃️", lazy: true },
  { id: "contracts", label: "ხელშეკრულებები", icon: "📑", lazy: true },
];
const ADMIN_TABS = [
  { id: "overview", label: "მიმოხილვა", icon: "📊" },
  { id: "team", label: "გუნდი", icon: "🧑‍🤝‍🧑" },
  { id: "ranking", label: "რეიტინგი", icon: "🏆" },
  { id: "attendance", label: "დასწრება", icon: "🕘", lazy: true },
  { id: "districts", label: "რაიონები", icon: "📍", lazy: true },
  { id: "agentsmgmt", label: "აგენტები", icon: "🗂️", lazy: true, adminOnly: true },
  { id: "agentrequests", label: "მოთხოვნები", icon: "📥", lazy: true },
  { id: "admintasks", label: "დავალებები", icon: "📄", lazy: true },
  { id: "taskhistory", label: "ისტორია", icon: "📜", lazy: true },
  { id: "meetings", label: "შეხვედრები", icon: "🤝", lazy: true },
  { id: "digest", label: "დღის ამბები", icon: "🗞️", lazy: true },
  { id: "dayoffs", label: "შვებულებები", icon: "🗓️", lazy: true },
  { id: "warnings", label: "გაფრთხილებები", icon: "⚠️", lazy: true },
  { id: "swaps", label: "სმენის გაცვლა", icon: "🔁", lazy: true },
  { id: "reports", label: "რეპორტები", icon: "📝", lazy: true },
  { id: "clients", label: "კლიენტები", icon: "👥", lazy: true },
  { id: "exclusives", label: "ექსკლუზივები", icon: "🏘️", lazy: true },
  { id: "myhomejobs", label: "MyHome", icon: "🏘️", lazy: true },
  { id: "myhomestats", label: "MyHome სტატისტიკა", icon: "📊", lazy: true },
  { id: "questions", label: "კითხვები", icon: "💬", lazy: true },
  { id: "regulations", label: "ინსტრუქცია/წესები", icon: "📘", lazy: true },
  { id: "crm2", label: "CRM", icon: "🗃️", lazy: true },
  { id: "contracts", label: "ხელშეკრულებები", icon: "📑", lazy: true },
];

const PERIODS = [
  ["day", "დღე"],
  ["week", "კვირა"],
  ["month", "თვე"],
];

/* პერიოდის ფილტრი (დღე/კვირა/თვე) — შედეგების/რეიტინგის ფანჯარას
   ცვლის სერვერზე (`/api/dashboard?period=...`). ერთი საერთო state,
   ვრცელდება KPI-ზეც (აგენტი) და მიმოხილვა/რეიტინგზეც (ადმინი). */
function renderPeriodSwitch() {
  return `<div class="period-switch" id="periodSwitch">
    ${PERIODS.map(([id, label]) => `<button data-period="${id}" class="${state.period === id ? "active" : ""}">${label}</button>`).join("")}
  </div>`;
}
function bindPeriodSwitch() {
  const el = document.getElementById("periodSwitch");
  if (!el) return;
  el.querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      if (state.period === b.dataset.period) return;
      state.period = b.dataset.period;
      load();
    };
  });
}

/* მარტივი, დამოუკიდებელი SVG სვეტოვანი დიაგრამა (გარე ბიბლიოთეკის
   გარეშე — იმავე პრინციპით, რაც ring()-ია KPI-ის რგოლისთვის). */
function barChart(items, opts = {}) {
  if (!items.length) return "";
  const h = opts.height || 108;
  const barW = opts.barWidth || 34;
  const gap = opts.gap || 16;
  const max = opts.max || Math.max(1, ...items.map((i) => i.value || 0));
  const w = items.length * (barW + gap) + gap;
  const bars = items.map((it, i) => {
    const bh = Math.max(2, Math.round(((it.value || 0) / max) * (h - 30)));
    const x = gap + i * (barW + gap);
    const y = h - bh - 20;
    return `
      <rect x="${x}" y="${y}" width="${barW}" height="${bh}" rx="7" fill="url(#barg)"/>
      <text x="${x + barW / 2}" y="${h - 6}" text-anchor="middle" class="chart-lbl">${esc(it.label)}</text>
      <text x="${x + barW / 2}" y="${y - 7}" text-anchor="middle" class="chart-val">${esc(it.valueLabel != null ? it.valueLabel : it.value)}</text>
    `;
  }).join("");
  return `<div class="chart-wrap">
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="xMinYMid meet">
      <defs><linearGradient id="barg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--accent-2)"/><stop offset="100%" stop-color="var(--accent)"/>
      </linearGradient></defs>
      ${bars}
    </svg>
  </div>`;
}

const REQUEST_TYPE_LABELS = {
  open_swap: "ღია გაცვლა",
  swap_agent: "გაცვლა კოლეგასთან",
  change_mode: "ცვლის ტიპის შეცვლა",
};

const lazyCache = {};

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/);
  return (parts[0]?.[0] || "?") + (parts[1]?.[0] || "");
}
function pct(a, b) {
  if (!b) return 0;
  return Math.max(0, Math.min(100, Math.round((a / b) * 100)));
}
function ratePct(rate) {
  return rate == null ? null : Math.round(rate * 100);
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

/* ---------------------------------------------------- დეტალის მოდალი */
/* დააწექით ნებისმიერ სიის სტრიქონს და ნახავთ ჩანაწერის ყველა ველს —
   ასე მოკლე ბარათებზეც ხელმისაწვდომია სრული ინფორმაცია. */
function openDetail(title, fields, extraHtml) {
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  const rows = fields
    .filter((f) => f.value !== undefined && f.value !== null && String(f.value).trim() !== "")
    .map((f) => `<div class="field"><div class="k">${esc(f.label)}</div><div class="v">${esc(f.value)}</div></div>`)
    .join("");
  box.innerHTML = `
    <h3>${esc(title)}<button class="close" id="modalClose">✕</button></h3>
    ${rows || `<div class="empty">დამატებითი ინფორმაცია არ არის</div>`}
    ${extraHtml || ""}
  `;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
}
function closeDetail() {
  document.getElementById("modalBackdrop").hidden = true;
}

/* კლიენტის ანგარიშის ფორმა (დღის დახურვისას) — REPORT_ACTIONS იგივეა,
   რაც ბოტის /clientreport-ში (bot.py). თუ დღეს ამ აგენტს კონკრეტული
   კლიენტი ჰქონდა მინიჭებული, ტელეფონს აღარ ვთხოვთ ხელახლა (სისტემას
   უკვე აქვს მენეჯერისგან) — პირდაპირ ვაჩვენებთ/ვარჩევინებთ, და
   ყურადღებას ვამახვილებთ დეტალებზე (მოქმედება+შენიშვნა+ფოტო). */
const REPORT_ACTIONS = [
  "დარეკვა", "ბინის ჩვენება/ნახვა", "წინადადება გაიგზავნა",
  "მოლაპარაკება", "გარიგება დაიხურა", "არ პასუხობს", "არ არის დაინტერესებული",
];

function _filesToBase64(fileList) {
  const files = Array.from(fileList || []).slice(0, 5);
  return Promise.all(files.map((f) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(f);
  })));
}

function openClientReportModal({ phones, mandatory, onSubmit }) {
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  const phoneList = phones || [];
  const phoneHtml = phoneList.length === 1
    ? `<div class="field"><div class="k">კლიენტი</div><div class="v">${esc(phoneList[0])}</div></div>`
    : phoneList.length > 1
      ? `<select id="crPhone">${phoneList.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("")}</select>`
      : `<input id="crPhoneFree" placeholder="კლიენტის ტელეფონი (არასავალდებულო)" />`;
  const actionsHtml = REPORT_ACTIONS.map((a, i) => `
    <label style="display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13.5px">
      <input type="checkbox" data-cract="${i}" style="width:17px;height:17px" /> ${esc(a)}
    </label>`).join("");

  box.innerHTML = `
    <h3>📋 კლიენტის ანგარიში
      ${mandatory ? "" : `<button class="close" id="modalClose">✕</button>`}
    </h3>
    ${mandatory ? `<div class="field"><div class="k">⚠️ სავალდებულოა</div><div class="v">დღეს კლიენტი გქონდათ მინიჭებული — დღის დასახურად ანგარიშის შევსება საჭიროა.</div></div>` : ""}
    <div class="qa-compose">
      ${phoneHtml}
      <div class="field" style="border:none;padding-bottom:0"><div class="k">რა შესრულდა? (მინიმუმ ერთი)</div></div>
      ${actionsHtml}
      <textarea id="crNotes" placeholder="შენიშვნა/დეტალები (რაც მნიშვნელოვანია KPI-სთვის)"></textarea>
      <input type="file" id="crPhotos" accept="image/*" multiple />
      <button class="btn" id="crSubmit" style="margin-top:4px">✅ დასრულება</button>
    </div>
  `;
  backdrop.hidden = false;
  if (!mandatory) {
    document.getElementById("modalClose").onclick = closeDetail;
    backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
  } else {
    backdrop.onclick = null;
  }
  document.getElementById("crSubmit").onclick = async () => {
    const submitBtn = document.getElementById("crSubmit");
    const phone = phoneList.length === 1
      ? phoneList[0]
      : phoneList.length > 1
        ? document.getElementById("crPhone").value
        : (document.getElementById("crPhoneFree").value || "").trim();
    const actions = REPORT_ACTIONS.filter((_, i) =>
      document.querySelector(`[data-cract="${i}"]`).checked);
    if (mandatory && !actions.length) { toast("აირჩიეთ მინიმუმ ერთი მოქმედება"); return; }
    if (mandatory && !phone) { toast("კლიენტის ტელეფონი ვერ დადგინდა"); return; }
    submitBtn.disabled = true;
    submitBtn.textContent = "იგზავნება…";
    try {
      const photos = await _filesToBase64(document.getElementById("crPhotos").files);
      await onSubmit({
        phone,
        actions: actions.join(", "),
        notes: (document.getElementById("crNotes").value || "").trim(),
        photos,
      });
      closeDetail();
    } catch (e) {
      toast(e.message || "შეცდომა");
      submitBtn.disabled = false;
      submitBtn.textContent = "✅ დასრულება";
    }
  };
}

async function api(path, opts) {
  const headers = Object.assign(
    { "Content-Type": "application/json", "X-Telegram-Init-Data": tg ? tg.initData : "" },
    (opts && opts.headers) || {}
  );
  let res;
  try {
    res = await fetch(path, Object.assign({}, opts, { headers }));
  } catch (netErr) {
    const err = new Error("⚠️ ქსელი მიუწვდომელია — შეამოწმეთ ინტერნეტი და სცადეთ ხელახლა");
    err.code = "network";
    throw err;
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // 401 = initData-ს ვადა გავიდა (Telegram მას ღია აპში არ ანახლებს) ან
    // არასწორია — მომხმარებელს ვეუბნებით, როგორ გააგრძელოს
    const msg = res.status === 401
      ? "🔒 სესიის ვადა ამოიწურა — დახურეთ Mini App და თავიდან გახსენით ბოტიდან (/app)"
      : (body.error || "დაფიქსირდა შეცდომა");
    const err = new Error(msg);
    err.code = body.code || (res.status === 401 ? "auth_failed" : "");
    throw err;
  }
  return body;
}

/* ფოტოები ახლა ავტორიზებულია (initData სათაურით) — <img src> სათაურს ვერ
   აგზავნის, ამიტომ სურათს fetch-ით ვკითხულობთ და blob URL-ით ვაჩვენებთ. */
async function hydratePhotos(root) {
  const imgs = Array.from(root.querySelectorAll("img[data-photo]"));
  for (const img of imgs) {
    try {
      const res = await fetch("/" + img.dataset.photo, {
        headers: { "X-Telegram-Init-Data": tg ? tg.initData : "" },
      });
      if (!res.ok) throw new Error("photo " + res.status);
      img.src = URL.createObjectURL(await res.blob());
    } catch (e) {
      img.alt = "🔒";
      img.style.opacity = "0.35";
    }
  }
}

/* ------------------------------------------------ GPS (Attendance) */
/* ლოკაცია მოითხოვება მხოლოდ "დაწყება"/"დასრულება" ღილაკზე დაჭერისას
   (ერთჯერადად) — არანაირი ფონური თვალყურის დევნება. მანძილს/სტატუსს
   სერვერი ითვლის, აქედან მხოლოდ {lat, lng, accuracy} მიდის. */
function _geoError(code, message) {
  const e = new Error(message);
  e.code = code;
  return e;
}
function _browserGeo() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(_geoError("gps_unavailable", "GPS ამ მოწყობილობაზე მიუწვდომელია")); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy }),
      (err) => {
        if (err && err.code === 1) reject(_geoError("gps_denied", "📍 Location permission საჭიროა"));
        else if (err && err.code === 3) reject(_geoError("gps_timeout", "⏱ მდებარეობის განსაზღვრას დიდი დრო დასჭირდა"));
        else reject(_geoError("gps_unavailable", "⚠️ მდებარეობის განსაზღვრა ვერ მოხერხდა"));
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
    );
  });
}
function _telegramGeo() {
  return new Promise((resolve, reject) => {
    const lm = tg && tg.LocationManager;
    if (!lm) { reject(_geoError("gps_unavailable", "GPS მიუწვდომელია")); return; }
    // callback-ი შეიძლება არასდროს დაბრუნდეს (ძველი კლიენტი/WebView) —
    // ღილაკი უსასრულოდ რომ არ "გაიჭედოს", 10 წამში ვწყვეტთ.
    const timer = setTimeout(() => reject(_geoError("gps_timeout", "⏱ მდებარეობის განსაზღვრას დიდი დრო დასჭირდა")), 10000);
    const ask = () => lm.getLocation((loc) => {
      clearTimeout(timer);
      if (!loc) { reject(_geoError("gps_denied", "📍 Location permission საჭიროა")); return; }
      resolve({ lat: loc.latitude, lng: loc.longitude, accuracy: loc.horizontal_accuracy });
    });
    try { lm.isInited ? ask() : lm.init(ask); } catch (e) { reject(_geoError("gps_unavailable", "GPS მიუწვდომელია")); }
  });
}
async function getGeo() {
  try {
    return await _browserGeo();
  } catch (e) {
    if (tg && tg.LocationManager && (e.code === "gps_denied" || e.code === "gps_unavailable")) {
      try { return await _telegramGeo(); } catch (e2) { /* ქვემოთ პირველ შეცდომას ვაბრუნებთ */ }
    }
    throw e;
  }
}

function ring(percent, size = 74, stroke = 8) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c - (Math.max(0, Math.min(100, percent)) / 100) * c;
  return `
  <div class="ring" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="var(--bg)" stroke-width="${stroke}" fill="none"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="url(#g)" stroke-width="${stroke}" fill="none"
        stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}"/>
      <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--accent)"/><stop offset="100%" stop-color="var(--accent-2)"/>
      </linearGradient></defs>
    </svg>
    <div class="pct">${percent}%</div>
  </div>`;
}

/* კვირის გრაფიკის ზოლი — გამოიყენება როგორც აგენტის საკუთარ "დღეს"
   ტაბში, ისე ადმინის/მენეჯერის გუნდის დეტალების window-ში (რომ
   მენეჯერსაც ჰქონდეს იგივე დილა/საღამო/სახლი ინფორმაცია, აგენტს
   რომ დააწვება). schedule — {mon:"office_morning", ...} ტიპის obj. */
function weekStripHtml(schedule) {
  const sch = schedule || {};
  return `<div class="week-strip">
      ${WEEKDAY_KEYS.map((k) => {
        const isToday = k === WEEKDAY_KEYS[(new Date().getDay() + 6) % 7];
        const m = sch[k] || "off";
        return `<div class="day ${isToday ? "today" : ""}">
          <div class="d">${WEEKDAY_LABELS[k]}</div>
          <div class="m">${MODE_ICON[m] || "🌙"}</div>
          ${MODE_SUBLABEL[m] ? `<div class="msub">${MODE_SUBLABEL[m]}</div>` : ""}
        </div>`;
      }).join("")}
    </div>`;
}

function statusBadge(mode, clockedIn, clockOut) {
  if (mode === "off") return `<span class="badge gray">დასვენება</span>`;
  if (clockOut) return `<span class="badge gray">დღე დასრულდა</span>`;
  if (clockedIn) return `<span class="badge green">გახსნილია</span>`;
  return `<span class="badge amber">არ დაწყებულა</span>`;
}

/* ---------------------------------------------------------- AGENT VIEW */

const GEO_LABEL = {
  OFFICE: "🏢 ოფისში", OUTSIDE_OFFICE: "📍 ოფისის გარეთ",
  LOCATION_UNRELIABLE: "⚠️ არასანდო ლოკაცია", NOT_CONFIGURED: "—",
};
const ATT_STATE_BADGE = {
  NOT_STARTED: ["amber", "არ დაწყებულა"], ACTIVE: ["green", "მუშაობს"],
  COMPLETED: ["gray", "დასრულებული"], MISSING_CHECKOUT: ["red", "დასრულება არ დაფიქსირდა"],
  DAY_OFF: ["gray", "დასვენების დღე"], OFF: ["gray", "დასვენება"],
};
function attStateBadge(s) {
  const [cls, label] = ATT_STATE_BADGE[s] || ["gray", s || "-"];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}
function fmtDistance(m) {
  if (m === "" || m == null) return "—";
  const n = Number(m);
  if (!isFinite(n)) return "—";
  return n >= 1000 ? (n / 1000).toFixed(1) + " კმ" : Math.round(n) + " მ";
}

/* აგენტის დღევანდელი დასწრების ბარათი (მონაცემი /api/dashboard-იდან). */
function renderAttendanceCard() {
  const a = state.data && state.data.attendance;
  if (!a) return "";
  const geoLine = a.check_in_geo
    ? `${esc(GEO_LABEL[a.check_in_geo] || a.check_in_geo)}${a.check_in_distance !== "" ? " · " + esc(fmtDistance(a.check_in_distance)) : ""}`
    : "—";
  return `<div class="card">
    <h2>🕘 დასწრება ${attStateBadge(a.state)}</h2>
    <div class="att-grid">
      <div class="stat"><div class="num">${esc(a.check_in || "—")}</div><div class="lbl">დაწყება${a.late ? " · 🔴 დაგვიანება" : ""}</div></div>
      <div class="stat"><div class="num">${esc(a.check_out || "—")}</div><div class="lbl">დასრულება</div></div>
      <div class="stat"><div class="num" style="font-size:14px">${esc(a.hours_text || "—")}</div><div class="lbl">ნამუშევარი დრო</div></div>
      <div class="stat"><div class="num" style="font-size:13px">${geoLine}</div><div class="lbl">ლოკაცია დაწყებისას</div></div>
    </div>
    ${a.gps_enabled
      ? `<div class="att-note">📍 დაწყებისა და დასრულებისას ერთჯერადად მოგეთხოვებათ მდებარეობა (ოფისის რადიუსი: ${esc(a.radius_m)} მ). ფონურად ლოკაცია არ მოწმდება.</div>`
      : `<div class="att-note">ოფისის GPS ვერიფიკაცია ჯერ არ არის ჩართული.</div>`}
  </div>`;
}

/* კვირის რაიონები — აგენტი ხედავს ამ კვირის (და უკვე განაწილებულ
   მომავალი კვირის) რაიონებს. */
function renderDistrictsCard() {
  const dd = state.data && state.data.districts;
  if (!dd) return "";
  const chips = (list) => `<div class="chip-row">${list.map((x) => `<span class="chip sel">📍 ${esc(x)}</span>`).join("")}</div>`;
  return `<div class="card">
    <h2>📍 ამ კვირის რაიონები <span class="cnt">${esc(dd.week_label || "")}</span></h2>
    ${dd.districts && dd.districts.length
      ? chips(dd.districts)
      : `<div class="empty">ამ კვირისთვის რაიონი ჯერ არ არის მინიჭებული</div>`}
    ${dd.next_districts && dd.next_districts.length
      ? `<div class="att-note">შემდეგი კვირა (${esc(dd.next_week_label || "")}):</div>${chips(dd.next_districts)}`
      : ""}
  </div>`;
}

function renderToday(d) {
  const t = d.today;
  const isOffice = t.mode === "office_morning" || t.mode === "office_evening";
  const hasQuota = !!t.quota;
  const quota = t.quota || 0;
  const submitted = parseInt(t.count_submitted || 0, 10) || 0;
  const clockedIn = !!t.clock_in && !t.clock_out;
  const canClockIn = t.mode !== "off" && !t.clock_in;
  const canClockOut = clockedIn;
  const c = d.clients || { today: 0, total: 0 };

  const ringHtml = hasQuota
    ? ring(pct(submitted, quota))
    : `<div class="ring" style="display:flex;align-items:center;justify-content:center;font-size:30px">${MODE_ICON[t.mode] || "🏠"}</div>`;

  const breakdown = isOffice
    ? `<div class="grid3" style="margin-top:10px">
        <div class="stat"><div class="num">${esc(t.site_count || 0)}</div><div class="lbl">საიტი</div></div>
        <div class="stat"><div class="num">${esc(t.myhome_count || 0)}</div><div class="lbl">myhome</div></div>
        <div class="stat"><div class="num">${esc(t.ssge_count || 0)}</div><div class="lbl">ss.ge</div></div>
      </div>`
    : "";

  return `
  <div class="card">
    <div class="today-hero">
      ${ringHtml}
      <div class="today-info">
        <div class="mode">${MODE_LABELS[t.mode] || t.mode}</div>
        <div class="meta">${hasQuota ? `${submitted} / ${quota} განცხადება` : (t.clock_in ? `დაწყებულია ${esc(t.clock_in).split(" ")[1] || ""}` : "დღევანდელი გეგმა")}</div>
        <div style="margin-top:6px">${statusBadge(t.mode, clockedIn, t.clock_out)}</div>
        ${d.agent && d.agent.manager_name ? `<div class="meta" style="margin-top:4px">👔 მენეჯერი: ${esc(d.agent.manager_name)}</div>` : ""}
      </div>
    </div>
    ${breakdown}
    <div class="actions">
      <button class="btn" id="btnClockIn" ${canClockIn ? "" : "disabled"}>▶️ დაწყება</button>
      <button class="btn secondary" id="btnClockOut" ${canClockOut ? "" : "disabled"}>⏹️ დასრულება</button>
    </div>
    <div id="attErr" hidden></div>
  </div>

  ${renderAttendanceCard()}
  ${renderDistrictsCard()}

  <div class="card">
    <h2>👥 კლიენტები</h2>
    <div class="grid2">
      <div class="stat"><div class="num">${c.today}</div><div class="lbl">დღეს</div></div>
      <div class="stat"><div class="num">${c.total}</div><div class="lbl">ჯამურად</div></div>
    </div>
  </div>

  <div class="card">
    <h2>📅 კვირის გრაფიკი</h2>
    ${weekStripHtml(d.schedule)}
  </div>

  <div class="card">
    <h2>⚠️ გაფრთხილებები <span class="cnt">${d.warnings.count}/${d.warnings.limit}</span></h2>
    ${d.warnings.recent.length === 0
      ? `<div class="empty">ამ თვეში გაფრთხილება არ გაქვთ 🎉</div>`
      : d.warnings.recent.map((w) => `
        <div class="list-row">
          <div class="avatar" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">⚠️</div>
          <div class="main">
            <div class="title">${esc(WARNING_LABELS[w.type] || w.type)}</div>
            <div class="sub">${esc(w.detail || "")}</div>
          </div>
          <div class="side sub">${esc((w.created_at || "").split(" ")[0] || "")}</div>
        </div>`).join("")}
  </div>`;
}

const TASK_FIELD_LABELS = [
  ["title", "სათაური"], ["description", "დამატებითი დეტალი"], ["assigned_to_name", "შემსრულებელი"],
  ["priority", "პრიორიტეტი"], ["status", "სტატუსი"], ["lead_type", "ტიპი"],
  ["due_date", "ვადა"], ["client_phone", "კლიენტის ტელეფონი"], ["owner_phone", "მესაკუთრის ნომერი"],
  ["deal_type", "გარიგება"], ["listing_id", "ლისტინგის ID"], ["viewing_time", "ნახვის დრო"],
  ["created_at", "შექმნის თარიღი"], ["updated_at", "ბოლო განახლება"],
];

const MEETING_FIELD_LABELS = [
  ["agent_name", "აგენტი"], ["address", "მისამართი"], ["district", "რაიონი"],
  ["owner_phone", "მეპატრონის ტელეფონი"], ["client_phone", "კლიენტის ტელეფონი"],
  ["condition", "მდგომარეობა"], ["price", "ფასი"], ["percent", "საკომისიო %"],
  ["meeting_date", "შეხვედრის თარიღი"], ["time", "დრო"],
  ["myhome_link", "myhome ბმული"], ["myhome_id", "myhome ID"],
  ["ssge_link", "ss.ge ბმული"], ["ssge_id", "ss.ge ID"],
  ["internal_number", "შიდა ნომერი"], ["agent_phone", "აგენტის ტელეფონი"],
  ["team_leader", "თიმლიდერი"], ["timestamp", "დაფიქსირების დრო"],
];

function renderTasks(d) {
  if (!d.tasks.length) {
    return `<div class="card"><div class="empty">ღია დავალება არ გაქვთ ✅</div></div>`;
  }
  const priColor = { "მაღალი": "red", "საშუალო": "amber" };
  return `<div class="card">
    <h2>📋 ჩემი დავალებები <span class="cnt">${d.tasks.length}</span></h2>
    ${d.tasks.map((t, i) => `
      <div class="list-row clickable" style="align-items:flex-start" data-task-idx="${i}">
        <div class="avatar">${t.lead_type === "listing" ? "🏠" : "👤"}</div>
        <div class="main">
          <div class="title">${esc(t.title || "")}</div>
          <div class="sub">${esc(t.client_phone || t.description || "")}</div>
          ${t.client_phone && t.description ? `<div class="sub" style="white-space:normal">📝 ${esc(t.description)}</div>` : ""}
          ${t.seen === "yes"
            ? `<div class="sub">✅ მიღებულია</div>`
            : `<button class="btn secondary" data-ack-btn="${esc(t.task_id)}" style="margin-top:6px;padding:7px 10px">✅ მივიღე კლიენტი</button>`}
        </div>
        <div class="side"><span class="badge ${priColor[t.priority] || "gray"}">${esc(t.priority || "-")}</span></div>
      </div>`).join("")}
  </div>`;
}

function bindTasksActions(d) {
  document.querySelectorAll("[data-task-idx]").forEach((el) => {
    el.onclick = () => {
      const t = d.tasks[parseInt(el.dataset.taskIdx, 10)];
      if (!t) return;
      openDetail(t.title || "დავალება", TASK_FIELD_LABELS.map(([k, label]) => ({ label, value: t[k] })));
    };
  });
  document.querySelectorAll("[data-ack-btn]").forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      btn.disabled = true;
      try {
        await api("/api/tasks/ack", { method: "POST", body: JSON.stringify({ task_id: btn.dataset.ackBtn }) });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("დადასტურდა ✅");
        await load();
      } catch (e2) { toast(e2.message); btn.disabled = false; }
    };
  });
}

const PERIOD_TITLES = { day: "დღეს", week: "ბოლო კვირა", month: "ბოლო თვე" };

/* KPI-ის 5 კომპონენტი (განცხადებები გეგმასთან, დისციპლინა, შეხვედრები, კლიენტები,
   ჩახურული ქეისები) — სერვერზე გამოთვლილი (kpi.py); ერთი და იგივე ფორმულა აგენტისთვისაც და მენეჯერისთვისაც. */
function kpiBreakdown(k) {
  if (!k || !k.components) return `<div class="empty">KPI ჯერ ვერ გამოითვალა</div>`;
  const order = ["listings", "discipline", "meetings", "clients", "closed_cases"];
  return order.map((key) => {
    const c = k.components[key];
    if (!c) return "";
    const pct = c.score == null ? null : Math.round(c.score * 100);
    return `<div class="bar-row">
      <div class="top"><span>${esc(c.label)} <span class="sub">(${esc(c.text || "")})</span></span><span>${pct == null ? "—" : pct + "%"}</span></div>
      <div class="track"><div class="fill" style="width:${pct == null ? 0 : pct}%"></div></div>
    </div>`;
  }).join("");
}

function renderKpi(d) {
  const p = d.performance;
  const k = d.kpi;
  const total = k && k.pct != null ? k.pct : null;
  const meetings = d.meetings || [];
  return `
  <div class="card">
    ${renderPeriodSwitch()}
    <h2>📈 შედეგები — ${esc(PERIOD_TITLES[state.period] || "")}</h2>
    <div class="grid3">
      <div class="stat"><div class="num">${total == null ? "—" : total + "%"}</div><div class="lbl">ჯამური KPI</div></div>
      <div class="stat"><div class="num">${k ? k.warnings : 0}</div><div class="lbl">გაფრთხილება</div></div>
      <div class="stat"><div class="num">${p.assigned}</div><div class="lbl">მიღებული კლიენტი</div></div>
    </div>
    ${kpiBreakdown(k)}
    <div class="sub" style="margin-top:8px">ფორმულა: განცხადებები გეგმასთან, დისციპლინა (დროულად გახსნა/დახურვა + გაფრთხილებები), შეხვედრები, კლიენტები, ჩახურული ქეისები. რაც არ გეხება (მაგ. კლიენტი არ მიგიღია), ჯამში არ ითვლება.</div>
  </div>
  <div class="card">
    <h2>📅 ბოლო შეხვედრები</h2>
    ${meetings.length === 0
      ? `<div class="empty">ჯერ არ დაფიქსირებულა</div>`
      : meetings.map((m) => `
        <div class="list-row">
          <div class="avatar">📍</div>
          <div class="main">
            <div class="title">${esc(m.district || "")} ${esc(m.address ? "· " + m.address : "")}</div>
            <div class="sub">${esc(m.meeting_date || "")} ${esc(m.time || "")}</div>
          </div>
        </div>`).join("")}
  </div>`;
}

function bindAgentActions(d) {
  const btnIn = document.getElementById("btnClockIn");
  const btnOut = document.getElementById("btnClockOut");
  const attBox = document.getElementById("attErr");
  const showAttError = (e, retry) => {
    if (!attBox) { toast(e.message); return; }
    const gpsCodes = ["gps_denied", "gps_unavailable", "gps_timeout", "invalid_location", "location_required"];
    const help = gpsCodes.includes(e.code)
      ? "ჩართეთ მდებარეობა (Location) ტელეფონის პარამეტრებში და Telegram-ისთვის, გადით ღია სივრცეში/ფანჯარასთან და სცადეთ ხელახლა. ალტერნატივა: ბოტში გამოიყენეთ /clockin და გააგზავნეთ ლოკაცია."
      : (e.code === "outside_office" ? "დაწყება შესაძლებელია მხოლოდ ოფისის ტერიტორიიდან." : "");
    attBox.hidden = false;
    attBox.className = "att-err";
    attBox.innerHTML = `${esc(e.message)}${help ? `<div style="margin-top:6px;color:var(--text)">${esc(help)}</div>` : ""}
      <button class="btn secondary" id="attRetry">🔄 ხელახლა ცდა</button>`;
    const rb = document.getElementById("attRetry");
    if (rb && retry) rb.onclick = retry;
  };
  const clearAttError = () => { if (attBox) { attBox.hidden = true; attBox.innerHTML = ""; } };
  const gpsEnabled = !!(state.data && state.data.attendance && state.data.attendance.gps_enabled);
  const busy = (btn, text) => { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = text; };
  const unbusy = (btn) => { btn.disabled = false; if (btn.dataset.label) btn.textContent = btn.dataset.label; };

  const startDay = async () => {
    clearAttError();
    busy(btnIn, gpsEnabled ? "📍 მდებარეობა…" : "…");
    try {
      const body = gpsEnabled ? await getGeo() : {};
      const res = await api("/api/clockin", { method: "POST", body: JSON.stringify(body) });
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast(res.result === "already" ? "უკვე დაწყებულია" : (res.late ? "დღე დაიწყო (დაგვიანებით) ✅" : "დღე დაიწყო ✅"));
      await load();
    } catch (e) {
      unbusy(btnIn);
      showAttError(e, startDay);
    }
  };
  if (btnIn) btnIn.onclick = startDay;
  if (btnOut) btnOut.onclick = async () => {
    const isOffice = d.today.mode === "office_morning" || d.today.mode === "office_evening";
    let body = {};
    if (isOffice) {
      // MyHome-ის რაოდენობა აღარ იკითხება — სერვერი ავტომატურად ითვლის
      // რეალურად დადებული განცხადებებიდან; საიტი/ss.ge თვითდეკლარაციაა.
      const site = prompt("რამდენი განცხადება ატვირთეთ დღეს ჩვენს საიტზე?", d.today.site_count || "0");
      if (site === null) return;
      const ssge = prompt("რამდენი — ss.ge-ზე?", d.today.ssge_count || "0");
      if (ssge === null) return;
      body = { site, ssge };
    }

    const doClockout = async (finalBody) => {
      clearAttError();
      busy(btnOut, gpsEnabled ? "📍 მდებარეობა…" : "…");
      try {
        const geo = gpsEnabled ? await getGeo() : {};
        const res = await api("/api/clockout", { method: "POST", body: JSON.stringify(Object.assign({}, finalBody, geo)) });
        if (res.result === "not_in") { toast("ჯერ არ დაგიწყიათ დღე"); unbusy(btnOut); return; }
        if (res.result === "already_out") { toast("დღე უკვე დასრულებულია"); await load(); return; }
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("დღე დასრულდა ✅");
        await load();
      } catch (e) {
        unbusy(btnOut);
        showAttError(e, () => doClockout(finalBody));
        throw e;
      }
    };

    // მკაცრი წესი: თუ დღეს კონკრეტული კლიენტი ჰქონდა მინიჭებული,
    // ანგარიშის შევსება სავალდებულოა და "გამოტოვება" აღარ შეიძლება
    // (ტელეფონსაც აღარ ვთხოვთ ხელახლა — სისტემას უკვე აქვს).
    const clientPhones = d.today.client_phones || [];
    if (clientPhones.length > 0) {
      openClientReportModal({
        phones: clientPhones,
        mandatory: true,
        onSubmit: async (cr) => doClockout(Object.assign({}, body, { client_report: cr })),
      });
      return;
    }

    const wantsReport = confirm("დღეს რომელიმე კლიენტთან იმუშავეთ? (არასავალდებულო ჩანაწერისთვის)");
    if (wantsReport) {
      openClientReportModal({
        phones: [],
        mandatory: false,
        onSubmit: async (cr) => doClockout(cr.phone ? Object.assign({}, body, { client_report: cr }) : body),
      });
      return;
    }

    try { await doClockout(body); } catch (e) { /* შეცდომა უკვე ნაჩვენებია (attErr) */ }
  };
}

/* ---------------------------------------------------------- ADMIN VIEW */

function renderOverview(d) {
  const s = d.summary;
  const chart = barChart([
    { label: "შესრ.", value: s.total_submitted || 0 },
    { label: "გეგმა", value: s.total_quota_target || 0 },
  ]);
  return `
  <div class="card">
    ${renderPeriodSwitch()}
    <h2>📊 დღევანდელი სურათი</h2>
    <div class="grid2">
      <div class="stat"><div class="num">${s.clocked_in}/${s.active_total}</div><div class="lbl">გახსნილი დღეს</div></div>
      <div class="stat"><div class="num">${s.total_submitted}/${s.total_quota_target || 0}</div><div class="lbl">განცხადებები (გეგმასთან)</div></div>
      <div class="stat"><div class="num">${s.clients_today}</div><div class="lbl">კლიენტი დღეს</div></div>
      <div class="stat"><div class="num">${s.clients_total}</div><div class="lbl">კლიენტი ჯამურად</div></div>
      <div class="stat"><div class="num">${s.quota_missed}</div><div class="lbl">გეგმა ვერ შესრულდა</div></div>
      <div class="stat"><div class="num">${s.pending_dayoffs}</div><div class="lbl">მოლოდინში (შვებ.)</div></div>
      <div class="stat"><div class="num">${s.active_total}</div><div class="lbl">აქტიური აგენტი</div></div>
      ${s.inactive_total ? `<div class="stat"><div class="num">${s.inactive_total}</div><div class="lbl">გათავისუფლებული</div></div>` : ""}
      ${s.late_count ? `<div class="stat" style="border-color:var(--red)"><div class="num" style="color:var(--red)">${s.late_count}</div><div class="lbl">🔴 დაგვიანებული დღეს</div></div>` : ""}
    </div>
    ${chart}
  </div>
  <div class="card">
    <h2>🏆 ტოპ 5 — ${esc(PERIOD_TITLES[state.period] || "")}</h2>
    ${(d.ranking || []).slice(0, 5).length === 0 ? `<div class="empty">ჯერ საკმარისი მონაცემი არ არის</div>` :
      d.ranking.slice(0, 5).map((t, i) => `
        <div class="bar-row">
          <div class="top"><span>${i + 1}. ${esc(t.name)}</span><span>${ratePct(t.rate)}%</span></div>
          <div class="track"><div class="fill" style="width:${ratePct(t.rate)}%"></div></div>
        </div>`).join("")}
  </div>`;
}

const TEAM_FIELD_LABELS = [
  ["team", "გუნდი"], ["kpi_pct", "KPI (არჩეული პერიოდი)"], ["mode", "დღევანდელი რეჟიმი"], ["count_submitted", "შეყვანილი დღეს (ჯამი)"],
  ["site_count", "საიტი"], ["myhome_count", "myhome"], ["ssge_count", "ss.ge"], ["quota", "დღიური გეგმა"],
  ["clients_today", "კლიენტი დღეს"], ["clients_total", "კლიენტი ჯამურად"], ["assigned", "მიღებული (30დღე)"],
  ["warnings", "გაფრთხილებები"], ["districts", "ამ კვირის რაიონები"],
  ["collaboration", "თანამშრომლობა (ექსკლუზივის გაზიარება)"],
];

/* გუნდი დაჯგუფებულია მენეჯერის/თიმის მიხედვით (t.team ველით) — ადმინს
   საშუალებას აძლევს ერთბაშად ნახოს, რომელი მენეჯერის ქვეშ რომელი
   აგენტები არიან და თითოეული ჯგუფის საშუალო შედეგი. თიმლიდერს (რომლის
   ხედვაც სერვერზეა უკვე გაფილტრული საკუთარ გუნდზე) უბრალოდ ერთი
   ჯგუფი გამოუჩნდება. */
function renderTeam(d) {
  const team = d.team.slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  const groups = new Map();
  team.forEach((t, i) => {
    const key = (t.team || "").trim() || "დაუნაწილებელი";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ t, i });
  });
  // ჯგუფის სახელად ყოველთვის თიმლიდერის სახელი ჩანს (არა ნედლი "team"
  // კოდი, რომელიც შეიძლება წაუკითხავი ან, კოლიზიის შემთხვევაში,
  // შეცდომაში შემყვანი იყოს) — გამონაკლისი მხოლოდ "დაუნაწილებელი"
  // ჯგუფია, სადაც თიმლიდერი საერთოდ არ ფიგურირებს.
  const groupEntries = Array.from(groups.entries()).map(([key, members]) => {
    const lead = members.find((m) => m.t.role === "team_lead");
    const label = key === "დაუნაწილებელი" ? key : (lead ? `${lead.t.name}-ის გუნდი` : key);
    return { key, label, members };
  }).sort((a, b) => a.label.localeCompare(b.label));

  const groupsHtml = groupEntries.map(({ label, members }) => {
    const rates = members.map((m) => m.t.rate).filter((r) => r != null);
    const avgRate = rates.length ? Math.round((rates.reduce((a, b) => a + b, 0) / rates.length) * 100) : null;
    const lead = members.find((m) => m.t.role === "team_lead");
    return `
      <div class="team-group">
        <div class="team-group-head">
          <span class="tg-name">🧑‍💼 ${esc(label)}</span>
          <span class="tg-meta">${members.length} წევრი${avgRate != null ? " · საშ. " + avgRate + "%" : ""}</span>
        </div>
        ${members.map(({ t, i }) => `
          <div class="list-row clickable" data-team-idx="${i}" ${t.late ? `style="border-left:3px solid var(--red)"` : ""}>
            <div class="avatar">${initials(t.name)}</div>
            <div class="main">
              <div class="title">${esc(t.name)} ${t.role === "team_lead" ? "👑" : ""} ${t.late ? "🔴" : ""}</div>
              <div class="sub">${MODE_ICON[t.mode] || "🌙"} ${esc(MODE_LABELS[t.mode] || t.mode)}${t.late ? " · <span style=\"color:var(--red)\">დაგვიანებულია</span>" : ""}</div>
            </div>
            <div class="side">
              ${statusBadge(t.mode, t.clocked_in, false)}
              <div class="sub" style="margin-top:3px">👥 ${t.clients_today || 0} დღეს · ${t.clients_total || 0} ჯამურად</div>
              ${t.warnings ? `<div class="sub" style="color:var(--red);margin-top:3px">⚠️ ${t.warnings}</div>` : ""}
            </div>
          </div>`).join("")}
      </div>`;
  }).join("");

  return `<div class="card">
    <h2>🧑‍🤝‍🧑 გუნდი <span class="cnt">${team.length}</span></h2>
    ${groupsHtml}
  </div>`;
}

function bindTeamActions(d) {
  const team = d.team.slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  document.querySelectorAll("[data-team-idx]").forEach((el) => {
    el.onclick = () => {
      const t = team[parseInt(el.dataset.teamIdx, 10)];
      if (!t) return;
      const rateStr = t.rate == null ? "-" : ratePct(t.rate) + "%";
      openDetail(
        t.name,
        TEAM_FIELD_LABELS.map(([k, label]) => ({
          label,
          value: k === "mode" ? (MODE_LABELS[t.mode] || t.mode) : t[k],
        })).concat([{ label: "შედეგი (30დღე)", value: rateStr }]),
        `<div class="field"><div class="k">კვირის გრაფიკი</div></div>${weekStripHtml(t.schedule)}`,
      );
    };
  });
}

function renderRanking(d) {
  const rk = d.ranking || [];
  const chart = barChart(
    rk.slice(0, 6).map((t) => ({
      label: (t.name || "").length > 7 ? t.name.slice(0, 6) + "…" : (t.name || ""),
      value: ratePct(t.rate),
      valueLabel: ratePct(t.rate) + "%",
    })),
    { max: 100 },
  );
  return `<div class="card">
    ${renderPeriodSwitch()}
    <h2>🏆 შესრულების რეიტინგი — ${esc(PERIOD_TITLES[state.period] || "")}</h2>
    ${chart}
    ${rk.length === 0 ? `<div class="empty">ჯერ საკმარისი მონაცემი არ არის</div>` :
      rk.map((t, i) => `
        <div class="bar-row">
          <div class="top"><span>${i + 1}. ${esc(t.name)}</span><span>${ratePct(t.rate)}%</span></div>
          <div class="track"><div class="fill" style="width:${ratePct(t.rate)}%"></div></div>
          <details style="margin-top:4px"><summary class="sub">კომპონენტები</summary>${kpiBreakdown(t.kpi)}</details>
        </div>`).join("")}
  </div>`;
}

/* Day off ისტორია — სამ ცალკე კატეგორიად: მომლოდინე (გადაწყვეტილების
   ღილაკებით), დამტკიცებული და უარყოფილი (ორივე მხოლოდ ისტორიისთვის).
   თვის ჭერი (მაქს. N დღეოფი თვეში ერთ აგენტზე) ვიზუალურადაც ჩანს. */
function renderDayoffs(payload) {
  const p = payload || {};
  const df = state.dayoffDateFilter || "";
  const byDate = (list) => (df ? list.filter((r) => String(r.date || "").trim() === df) : list);
  const pending = byDate(p.pending || []);
  const approved = byDate(p.approved || []);
  const rejected = byDate(p.rejected || []);
  const dateFilterCard = `<div class="card">
    <h2>📅 თარიღით ფილტრი</h2>
    <div class="qa-compose">
      <input type="date" id="dayoffDateFilter" value="${esc(df)}" />
      ${df ? `<button class="btn secondary" id="dayoffDateClear">✖ გაწმენდა</button>` : ""}
    </div>
  </div>`;
  const row = (r, withActions) => `
      <div class="list-row clickable" data-detail-id="${esc(r.request_id)}">
        <div class="avatar">${initials(r.agent_name)}</div>
        <div class="main">
          <div class="title">${esc(r.agent_name)} — ${esc(r.date)}</div>
          <div class="sub">${esc(r.reason || "")}</div>
          <div class="sub">${esc((r.decided_at || r.created_at || "").split(" ")[0] || "")}</div>
        </div>
      </div>
      ${withActions ? `<div class="actions" style="margin:-2px 0 12px">
        <button class="btn" data-act="approved" data-id="${esc(r.request_id)}">✅ დამტკიცება</button>
        <button class="btn danger" data-act="rejected" data-id="${esc(r.request_id)}">✖️ უარყოფა</button>
      </div>` : ""}`;
  return dateFilterCard + `<div class="card">
    <h2>⏳ მომლოდინე მოთხოვნები <span class="cnt">${pending.length}</span></h2>
    <div class="sub" style="margin-bottom:8px">მაქსიმუმ ${esc(p.monthly_limit || 3)} დღეოფი, ერთ აგენტზე, კალენდარულ თვეში</div>
    ${pending.length === 0 ? `<div class="empty">მოლოდინში აღარაფერია</div>` : pending.map((r) => row(r, true)).join("")}
  </div>
  <div class="card">
    <h2>✅ დამტკიცებული <span class="cnt">${approved.length}</span></h2>
    ${approved.length === 0 ? `<div class="empty">ჯერ არაფერია</div>` : approved.map((r) => row(r, false)).join("")}
  </div>
  <div class="card">
    <h2>❌ უარყოფილი <span class="cnt">${rejected.length}</span></h2>
    ${rejected.length === 0 ? `<div class="empty">ჯერ არაფერია</div>` : rejected.map((r) => row(r, false)).join("")}
  </div>`;
}

const DAYOFF_STATUS_LABEL = { pending: "⏳ მომლოდინე", approved: "✅ დამტკიცებული", rejected: "❌ უარყოფილი" };
const DAYOFF_FIELD_LABELS = [
  ["agent_name", "აგენტი"], ["date", "თარიღი"], ["reason", "მიზეზი"],
  ["status", "სტატუსი"], ["created_at", "მოთხოვნის თარიღი"], ["decided_at", "გადაწყვეტილების თარიღი"],
];

function bindDayoffsActions(payload) {
  const p = payload || {};
  const allRows = [...(p.pending || []), ...(p.approved || []), ...(p.rejected || [])];
  const dateInput = document.getElementById("dayoffDateFilter");
  if (dateInput) dateInput.onchange = () => { state.dayoffDateFilter = dateInput.value || ""; renderContent(); };
  const dateClear = document.getElementById("dayoffDateClear");
  if (dateClear) dateClear.onclick = () => { state.dayoffDateFilter = ""; renderContent(); };
  document.querySelectorAll("[data-detail-id]").forEach((el) => {
    el.onclick = () => {
      const r = allRows.find((x) => String(x.request_id) === el.dataset.detailId);
      if (!r) return;
      const fields = DAYOFF_FIELD_LABELS.map(([k, label]) => ({
        label, value: k === "status" ? (DAYOFF_STATUS_LABEL[r.status] || r.status) : r[k],
      }));
      openDetail(`${r.agent_name} — დასვენების მოთხოვნა`, fields);
    };
  });
  document.querySelectorAll("[data-act]").forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      btn.disabled = true;
      try {
        await api("/api/dayoff/decide", {
          method: "POST",
          body: JSON.stringify({ request_id: btn.dataset.id, status: btn.dataset.act }),
        });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast(btn.dataset.act === "approved" ? "დამტკიცდა ✅" : "უარყოფილია");
        await load();
      } catch (e2) { toast(e2.message); btn.disabled = false; }
    };
  });
}

const WARNING_STATUS_LABEL = {
  active: "", dismiss_pending: "⏳ მოთხოვნილია გაუქმება", dismissed: "✅ გაუქმებულია",
};
const WARNING_FIELD_LABELS = [
  ["agent_name", "აგენტი"], ["type", "ტიპი"], ["detail", "დეტალი"], ["created_at", "თარიღი"],
  ["dismiss_reason", "გაუქმების მოთხოვნის მიზეზი"], ["dismiss_requested_by_name", "მოითხოვა"],
  ["dismiss_requested_at", "მოთხოვნის თარიღი"], ["dismiss_decided_by", "გადაწყვიტა"],
  ["dismiss_decided_at", "გადაწყვეტილების თარიღი"],
];

function renderWarnings(rows) {
  rows = rows || [];
  if (!rows.length) return `<div class="card"><div class="empty">გაფრთხილება არ არის ✅</div></div>`;

  const agentOptions = [];
  const seenAgents = new Set();
  rows.forEach((w) => {
    const id = String(w.agent_id || "");
    if (id && !seenAgents.has(id)) { seenAgents.add(id); agentOptions.push({ id, name: w.agent_name || id }); }
  });
  agentOptions.sort((a, b) => (a.name || "").localeCompare(b.name || "", "ka"));
  const managerNames = [...new Set(rows.map((w) => w.dismiss_requested_by_name).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "ka"));

  const filtered = rows.filter((w) => {
    if (state.warningsAgentFilter && String(w.agent_id) !== state.warningsAgentFilter) return false;
    if (state.warningsManagerFilter && w.dismiss_requested_by_name !== state.warningsManagerFilter) return false;
    return true;
  });

  const byAgent = {};
  filtered.forEach((w) => {
    const id = String(w.agent_id || "");
    if (!id) return;
    if (!byAgent[id]) byAgent[id] = { agent_id: id, agent_name: w.agent_name, count: 0 };
    if ((w.status || "active") !== "dismissed") byAgent[id].count += 1;
  });
  const agentCards = Object.values(byAgent).sort((a, b) => b.count - a.count);

  const buckets = { pending: [], dismissed: [], rejected: [], active: [] };
  filtered.forEach((w) => buckets[_warningBucket(w)].push(w));

  const filterBar = `<div class="card">
    <h2>🔍 ფილტრი</h2>
    <div class="qa-compose">
      <select id="warnAgentFilter">
        <option value="">ყველა აგენტი</option>
        ${agentOptions.map((a) => `<option value="${esc(a.id)}" ${state.warningsAgentFilter === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
      </select>
      ${managerNames.length ? `<select id="warnManagerFilter">
        <option value="">ყველა მენეჯერი</option>
        ${managerNames.map((m) => `<option value="${esc(m)}" ${state.warningsManagerFilter === m ? "selected" : ""}>${esc(m)}</option>`).join("")}
      </select>` : ""}
    </div>
  </div>`;

  const agentCardsHtml = `<div class="card">
    <h2>👤 აგენტების მიხედვით</h2>
    ${agentCards.length === 0 ? `<div class="empty">ვერაფერი მოიძებნა</div>` : agentCards.map((a) => `
      <div class="list-row clickable" data-agent-warn="${esc(a.agent_id)}">
        <div class="avatar">${initials(a.agent_name)}</div>
        <div class="main"><div class="title">${esc(a.agent_name)}</div></div>
        <div class="side"><span class="badge ${a.count > 0 ? "red" : "gray"}">${a.count}</span></div>
      </div>`).join("")}
  </div>`;

  const isLeadView = !!(state.data && state.data.is_team_lead);
  const warnRowHtml = (w) => {
    const statusLabel = WARNING_STATUS_LABEL[w.status] || "";
    const bucket = _warningBucket(w);
    // მულტი-მონიშვნა: აქტიურზე (გაუქმების მოთხოვნისთვის) და მომლოდინეზე
    // (დამტკიცება/უარყოფა — მხოლოდ ადმინი).
    const selectable = w.warning_id && (bucket === "active" || bucket === "rejected" || (bucket === "pending" && !isLeadView));
    const pickKind = bucket === "pending" ? "pending" : "active";
    return `
      <div class="list-row clickable chk-row" data-warn-idx="${rows.indexOf(w)}">
        ${selectable ? `<input type="checkbox" class="chk-pick" data-warn-chk="${esc(w.warning_id)}" data-kind="${pickKind}" ${state.warnSel.has(String(w.warning_id)) ? "checked" : ""} />` : ""}
        <div class="avatar" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">⚠️</div>
        <div class="main">
          <div class="title">${esc(w.agent_name)} — ${esc(WARNING_LABELS[w.type] || w.type)}</div>
          <div class="sub">${esc(w.detail || "")}${statusLabel ? " · " + statusLabel : ""}</div>
        </div>
        <div class="side sub">${esc((w.created_at || "").split(" ")[0] || "")}</div>
      </div>`;
  };
  const section = (icon, title, list, selKind) => `<div class="card">
    <h2>${icon} ${title} <span class="cnt">${list.length}</span></h2>
    ${selKind && list.length > 1 && (selKind === "active" || !isLeadView)
      ? `<div style="margin-bottom:8px"><button class="chip" data-sel-all="${selKind}">☑ ყველას მონიშვნა / მოხსნა</button></div>` : ""}
    ${list.length === 0 ? `<div class="empty">ცარიელია</div>` : list.map(warnRowHtml).join("")}
  </div>`;

  return filterBar + agentCardsHtml + `<div id="warnBulk"></div>`
    + section("🕐", "დასადასტურებელი", buckets.pending, "pending")
    + section("✅", "დადასტურებული (გაუქმებულია)", buckets.dismissed)
    + section("❌", "უარყოფილი (აქტიურად რჩება)", buckets.rejected)
    + section("⚠️", "აქტიური", buckets.active, "active");
}

function _warningBucket(w) {
  const status = w.status || "active";
  if (status === "dismiss_pending") return "pending";
  if (status === "dismissed") return "dismissed";
  if (status === "active" && w.dismiss_decided_by) return "rejected";
  return "active";
}

/* მულტი-მონიშვნის პანელი: აქტიური გაფრთხილებებისთვის — "გაუქმების
   მოთხოვნა" (მენეჯერი/ადმინი), მომლოდინეებისთვის — "დამტკიცება/უარყოფა"
   (მხოლოდ ადმინი). მონიშვნა გადახაზვის გარეშე ახლდება (გვერდი არ
   "ხტება"). */
function bindWarningsBulk(rows, isAdmin) {
  const bar = document.getElementById("warnBulk");
  if (!bar) return;
  const kindOf = (id) => {
    const w = rows.find((x) => String(x.warning_id) === id);
    return w && _warningBucket(w) === "pending" ? "pending" : "active";
  };
  // ფილტრის/სიის ცვლილებისას გაქრობილი ID-ები მონიშვნიდან ამოვიღოთ
  const present = new Set(rows.map((w) => String(w.warning_id)));
  state.warnSel.forEach((id) => { if (!present.has(id)) state.warnSel.delete(id); });

  const refresh = () => {
    const ids = [...state.warnSel];
    const act = ids.filter((id) => kindOf(id) === "active");
    const pen = ids.filter((id) => kindOf(id) === "pending");
    if (!ids.length) { bar.innerHTML = ""; return; }
    bar.innerHTML = `<div class="bulk-bar">
      <span class="grow">☑ მონიშნულია: ${ids.length}</span>
      ${act.length ? `<button class="btn" id="bulkReq">📝 გაუქმების მოთხოვნა (${act.length})</button>` : ""}
      ${pen.length && isAdmin ? `<button class="btn" id="bulkApprove">✅ დამტკიცება (${pen.length})</button>
        <button class="btn danger" id="bulkReject">❌ უარყოფა (${pen.length})</button>` : ""}
      <button class="btn secondary" id="bulkClear">✖</button>
    </div>`;
    document.getElementById("bulkClear").onclick = () => {
      state.warnSel.clear();
      document.querySelectorAll("[data-warn-chk]").forEach((c) => { c.checked = false; });
      refresh();
    };
    const done = async (fn, okMsg) => {
      try {
        const res = await fn();
        state.warnSel.clear();
        toast(okMsg(res));
        delete lazyCache.warnings;
        await renderContent();
      } catch (e) { toast(e.message); }
    };
    const reqBtn = document.getElementById("bulkReq");
    if (reqBtn) reqBtn.onclick = async () => {
      const reason = prompt(`რატომ ითხოვთ ${act.length} გაფრთხილების გაუქმებას? (ერთი მიზეზი ყველასთვის)`);
      if (!reason || !reason.trim()) return;
      reqBtn.disabled = true;
      await done(
        () => api("/api/warnings/request-dismiss-bulk", { method: "POST", body: JSON.stringify({ warning_ids: act, reason: reason.trim() }) }),
        (r) => `მოთხოვნა გაიგზავნა ✅ (${r.requested}${r.skipped ? `, გამოტოვებული: ${r.skipped}` : ""})`,
      );
    };
    const decide = (approve) => async () => {
      if (!confirm(`${approve ? "დამტკიცდეს" : "უარყოფილ იქნეს"} ${pen.length} მოთხოვნა?`)) return;
      await done(
        () => api("/api/warnings/decide-dismiss-bulk", { method: "POST", body: JSON.stringify({ warning_ids: pen, approve }) }),
        (r) => `გადაწყვეტილება შენახულია ✅ (${r.decided})`,
      );
    };
    const ap = document.getElementById("bulkApprove");
    const rj = document.getElementById("bulkReject");
    if (ap) ap.onclick = decide(true);
    if (rj) rj.onclick = decide(false);
  };

  document.querySelectorAll("[data-warn-chk]").forEach((c) => {
    c.onclick = (e) => e.stopPropagation();
    c.onchange = () => {
      const id = c.dataset.warnChk;
      if (c.checked) state.warnSel.add(id); else state.warnSel.delete(id);
      refresh();
    };
  });
  document.querySelectorAll("[data-sel-all]").forEach((b) => {
    b.onclick = () => {
      const boxes = [...document.querySelectorAll(`[data-warn-chk][data-kind="${b.dataset.selAll}"]`)];
      const allOn = boxes.length && boxes.every((c) => c.checked);
      boxes.forEach((c) => {
        c.checked = !allOn;
        if (c.checked) state.warnSel.add(c.dataset.warnChk); else state.warnSel.delete(c.dataset.warnChk);
      });
      refresh();
    };
  });
  refresh();
}

function bindWarningsActions(rows) {
  const isTeamLead = state.role === "admin" && state.data && state.data.is_team_lead;
  const isAdmin = state.role === "admin" && !isTeamLead;
  bindWarningsBulk(rows, isAdmin);

  const agentFilterSel = document.getElementById("warnAgentFilter");
  if (agentFilterSel) {
    agentFilterSel.onchange = () => {
      state.warningsAgentFilter = agentFilterSel.value;
      renderContent();
    };
  }
  const managerFilterSel = document.getElementById("warnManagerFilter");
  if (managerFilterSel) {
    managerFilterSel.onchange = () => {
      state.warningsManagerFilter = managerFilterSel.value;
      renderContent();
    };
  }

  document.querySelectorAll("[data-agent-warn]").forEach((el) => {
    el.onclick = () => {
      const aid = el.dataset.agentWarn;
      const agentWarnings = rows.filter((w) => String(w.agent_id) === aid);
      if (!agentWarnings.length) return;
      const agentName = agentWarnings[0].agent_name || "";
      const listHtml = agentWarnings.map((w) => `
        <div class="list-row">
          <div class="avatar" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">⚠️</div>
          <div class="main">
            <div class="title">${esc(WARNING_LABELS[w.type] || w.type)}</div>
            <div class="sub">${esc(w.detail || "")}</div>
            <div class="sub">${esc((w.created_at || "").split(" ")[0] || "")} · ${esc(WARNING_STATUS_LABEL[w.status] || "აქტიური")}</div>
          </div>
        </div>`).join("");
      openDetail(`${agentName} — ${agentWarnings.length} გაფრთხილება`, [], listHtml);
    };
  });

  document.querySelectorAll("[data-warn-idx]").forEach((el) => {
    el.onclick = () => {
      const w = rows[parseInt(el.dataset.warnIdx, 10)];
      if (!w) return;
      const fields = WARNING_FIELD_LABELS.map(([k, label]) => ({
        label, value: k === "type" ? (WARNING_LABELS[w.type] || w.type) : w[k],
      }));
      let extraHtml = "";
      if (w.status === "active" || !w.status) {
        extraHtml = `<button class="btn" id="wReqDismiss" style="margin-top:10px;width:100%">📝 მოთხოვნა გაუქმებაზე</button>`;
      } else if (w.status === "dismiss_pending" && isAdmin) {
        extraHtml = `<div class="actions">
          <button class="btn" id="wApprove">✅ დამტკიცება</button>
          <button class="btn danger" id="wReject">❌ უარყოფა</button>
        </div>`;
      }
      openDetail(`${w.agent_name} — გაფრთხილება`, fields, extraHtml);

      const reqBtn = document.getElementById("wReqDismiss");
      if (reqBtn && (isTeamLead || isAdmin)) {
        reqBtn.onclick = async () => {
          const reason = prompt("რატომ ითხოვთ ამ გაფრთხილების გაუქმებას? (მაგ: ამ დროს შეხვედრაზე იყო)");
          if (!reason || !reason.trim()) return;
          reqBtn.disabled = true;
          try {
            await api("/api/warnings/request-dismiss", {
              method: "POST",
              body: JSON.stringify({ warning_id: w.warning_id, reason: reason.trim() }),
            });
            toast("მოთხოვნა გაიგზავნა ✅");
            closeDetail();
            delete lazyCache.warnings;
            await renderContent();
          } catch (e) { toast(e.message); reqBtn.disabled = false; }
        };
      }
      const approveBtn = document.getElementById("wApprove");
      const rejectBtn = document.getElementById("wReject");
      const decide = async (approve) => {
        try {
          await api("/api/warnings/decide-dismiss", {
            method: "POST",
            body: JSON.stringify({ warning_id: w.warning_id, approve }),
          });
          toast("გადაწყვეტილება შენახულია ✅");
          closeDetail();
          delete lazyCache.warnings;
          await renderContent();
        } catch (e) { toast(e.message); }
      };
      if (approveBtn) approveBtn.onclick = () => decide(true);
      if (rejectBtn) rejectBtn.onclick = () => decide(false);
    };
  });
}

/* ---------------------------------------------------------- კლიენტები */

function _clientRowsHtml(rows) {
  if (!rows.length) return `<div class="empty">კლიენტი არ არის</div>`;
  return rows.map((c, i) => `
    <div class="list-row clickable" data-client-idx="${i}">
      <div class="avatar">👤</div>
      <div class="main">
        <div class="title">${esc(c.client_phone)}</div>
        <div class="sub">${esc(c.current_agent_name || "—")} · ${esc(c.status || "-")}${c.deal_type ? " · " + esc(c.deal_type) : ""}</div>
        <div class="sub">📋 ${c.task_count || 0} · 📝 ${c.report_count || 0} · 📍 ${c.meeting_count || 0}</div>
      </div>
      <div class="side sub">${esc((c.last_activity || "").split(" ")[0] || "")}</div>
    </div>`).join("");
}

function renderClients(rows) {
  rows = rows || [];
  return `<div class="card">
    <h2>👥 კლიენტები <span class="cnt">${rows.length}</span></h2>
    <div class="qa-compose">
      <input id="clientSearch" placeholder="ძებნა — ტელეფონი ან აგენტის სახელი" />
    </div>
    <div id="clientsList">${_clientRowsHtml(rows)}</div>
  </div>`;
}

/* ერთი ჩანაწერის ყველა არა-ცარიელი ველი — რომ კლიენტზე ჩაწერილი
   არაფერი დაიმალოს (ტელეფონით ნაპოვნი ნებისმიერი მოქმედება). */
function _kvLines(d, labels) {
  return labels
    .filter(([k]) => d[k] !== undefined && d[k] !== null && String(d[k]).trim() !== "")
    .map(([k, label]) => `<div class="sub" style="white-space:normal">${esc(label)}: ${esc(d[k])}</div>`)
    .join("");
}

function _clientTimelineItemHtml(entry) {
  const d = entry.data;
  if (entry.kind === "task") {
    return `<div class="list-row">
      <div class="avatar">${d.lead_type === "listing" ? "🏠" : "👤"}</div>
      <div class="main" style="overflow:visible">
        <div class="title" style="white-space:normal">📋 ${esc(d.title || "დავალება")}</div>
        <div class="sub" style="white-space:normal">შემსრულებელი: ${esc(d.assigned_to_name || "-")} · სტატუსი: ${esc(d.status || "-")}</div>
        ${_kvLines(d, [
          ["description", "დამატებითი დეტალი"], ["client_phone", "კლიენტის ნომერი"], ["owner_phone", "მესაკუთრის ნომერი"],
          ["listing_id", "ლისტინგი"], ["viewing_time", "ნახვის დრო"], ["deal_type", "გარიგება"], ["priority", "პრიორიტეტი"],
        ])}
        <div class="sub">${esc(d.created_at || "")}${d.updated_at && d.updated_at !== d.created_at ? " → " + esc(d.updated_at) : ""}</div>
      </div>
    </div>`;
  }
  if (entry.kind === "exclusive") {
    return `<div class="list-row">
      <div class="avatar">🏘️</div>
      <div class="main" style="overflow:visible">
        <div class="title" style="white-space:normal">ექსკლუზივი — ${esc(d.agent_name || "-")}</div>
        ${_kvLines(d, [
          ["property_type", "ტიპი"], ["deal_type", "გარიგება"], ["location", "მდებარეობა"], ["price", "ფასი"],
          ["owner_phone", "მესაკუთრის ნომერი"], ["notes", "შენიშვნა"],
        ])}
        <div class="sub">${esc(d.created_at || "")}</div>
      </div>
    </div>`;
  }
  if (entry.kind === "myhome") {
    return `<div class="list-row">
      <div class="avatar">🌐</div>
      <div class="main" style="overflow:visible">
        <div class="title" style="white-space:normal">MyHome განცხადება — ${esc(d.agent_name || "-")}</div>
        ${_kvLines(d, [
          ["status", "სტატუსი"], ["myhome_listing_id", "MyHome ID"], ["owner_number", "მესაკუთრის ნომერი"],
          ["final_price", "ფასი"], ["address", "მისამართი"], ["error_message", "შეცდომა"],
        ])}
        <div class="sub">${esc(d.completed_at || d.created_at || "")}</div>
      </div>
    </div>`;
  }
  if (entry.kind === "report") {
    const photos = String(d.file_id || "").split(",").map((s) => s.trim()).filter((s) => s.startsWith("uploads/"));
    return `<div class="list-row">
      <div class="avatar">📝</div>
      <div class="main" style="overflow:visible">
        <div class="title" style="white-space:normal">რეპორტი — ${esc(d.agent_name || "-")}</div>
        <div class="sub">${esc(d.actions || "-")}</div>
        ${d.notes ? `<div class="sub">${esc(d.notes)}</div>` : ""}
        <div class="sub">${esc(d.created_at || "")}</div>
        ${photos.length ? `<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">${photos.map((p) => `<img data-photo="${esc(p)}" alt="" style="width:56px;height:56px;object-fit:cover;border-radius:8px" />`).join("")}</div>` : ""}
      </div>
    </div>`;
  }
  return `<div class="list-row">
    <div class="avatar">📍</div>
    <div class="main" style="overflow:visible">
      <div class="title" style="white-space:normal">შეხვედრა — ${esc(d.agent_name || "-")}</div>
      <div class="sub" style="white-space:normal">${esc(d.address || d.district || "-")}${d.price ? " · " + esc(d.price) : ""}</div>
      ${_kvLines(d, [["owner_phone", "მესაკუთრის ნომერი"], ["client_phone", "კლიენტის ნომერი"], ["district", "რაიონი"], ["condition", "მდგომარეობა"], ["percent", "პროცენტი"]])}
      <div class="sub">${esc(d.meeting_date || "")} ${esc(d.time || "")}</div>
    </div>
  </div>`;
}

function bindClientsActions(rows) {
  rows = rows || [];
  const searchInput = document.getElementById("clientSearch");
  if (searchInput) {
    searchInput.oninput = () => {
      const q = searchInput.value.trim().toLowerCase();
      const filtered = !q ? rows : rows.filter((c) =>
        String(c.client_phone || "").toLowerCase().includes(q)
        || String(c.current_agent_name || "").toLowerCase().includes(q));
      document.getElementById("clientsList").innerHTML = _clientRowsHtml(filtered);
      bindClientRowClicks(filtered);
    };
  }
  bindClientRowClicks(rows);
}

function bindClientRowClicks(rows) {
  document.querySelectorAll("[data-client-idx]").forEach((el) => {
    el.onclick = async () => {
      const c = rows[parseInt(el.dataset.clientIdx, 10)];
      if (!c) return;
      const backdrop = document.getElementById("modalBackdrop");
      const box = document.getElementById("modalBox");
      box.innerHTML = `<h3>${esc(c.client_phone)}<button class="close" id="modalClose">✕</button></h3><div class="empty">იტვირთება…</div>`;
      backdrop.hidden = false;
      document.getElementById("modalClose").onclick = closeDetail;
      backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
      try {
        const res = await api(`/api/clients/${encodeURIComponent(c.phone_key || c.client_phone)}`);
        const timeline = res.timeline || [];
        box.innerHTML = `
          <h3>${esc(c.client_phone)}<button class="close" id="modalClose">✕</button></h3>
          ${timeline.length === 0 ? `<div class="empty">ისტორია არ არის</div>` : timeline.map(_clientTimelineItemHtml).join("")}
        `;
        document.getElementById("modalClose").onclick = closeDetail;
        hydratePhotos(box);
      } catch (e) {
        box.innerHTML += `<div class="empty">⚠️ ${esc(e.message)}</div>`;
      }
    };
  });
}

const EXCLUSIVE_FIELD_LABELS = [
  ["property_type", "ტიპი"], ["deal_type", "გარიგება"], ["building_status", "სტატუსი"],
  ["condition", "მდგომარეობა"], ["location", "მდებარეობა"], ["cadastral_code", "საკადასტრო კოდი"],
  ["area", "ფართი (მ²)"], ["rooms", "ოთახები"], ["bedrooms", "საძინებლები"],
  ["floors_total", "სართულები (სულ)"], ["floor_number", "სართული"], ["project_type", "პროექტის ტიპი"],
  ["bathrooms", "სველი წერტილი"], ["balcony", "აივანი"], ["price", "ფასი"], ["percent", "საკომისიო %"],
  ["contact_internal", "საკონტაქტო (შიდა)"], ["owner_phone", "მესაკუთრის ტელეფონი"],
  ["notes", "შენიშვნა"], ["agent_name", "აგენტი"], ["created_at", "დამატების თარიღი"],
];

function renderExclusives(rows) {
  if (!rows.length) return `<div class="card"><div class="empty">აქტიური ექსკლუზივი არ არის. დაამატეთ ბოტში /addexclusive-ით.</div></div>`;
  return `<div class="card">
    <h2>🏘️ ექსკლუზივები <span class="cnt">${rows.length}</span></h2>
    ${rows.map((r, i) => `
      <div class="list-row clickable" data-exclusive-idx="${i}">
        <div class="avatar">${r.deal_type === "ქირავდება" ? "🔑" : "🏠"}</div>
        <div class="main">
          <div class="title">${esc(r.property_type || "-")} · ${esc(r.deal_type || "-")} — ${esc(r.agent_name)}</div>
          <div class="sub">${esc(r.location || "-")} · ${esc(r.area || "-")} მ² · ${esc(r.rooms || "-")} ოთახი</div>
          <div class="sub">💰 ${esc(r.price || "-")} ${r.percent ? "· " + esc(r.percent) + "%" : ""}${r.collaboration_count ? " · 🤝 " + esc(r.collaboration_count) : ""}</div>
        </div>
      </div>`).join("")}
  </div>`;
}

function bindExclusivesActions(rows) {
  document.querySelectorAll("[data-exclusive-idx]").forEach((el) => {
    el.onclick = () => {
      const r = rows[parseInt(el.dataset.exclusiveIdx, 10)];
      if (!r) return;
      openExclusiveDetail(r);
    };
  });
}

/* ექსკლუზივის დეტალი + გაზიარება კოლეგასთან (თანამშრომლობა, v3.10):
   თუ სხვა აგენტს დასჭირდება კოლეგის ბინა (კლიენტი დაინტერესდა), აქედანვე
   უზიარებს — სისტემა იმახსოვრებს ვინ ვისთან თანამშრომლობს ამ ბინაზე. */
async function openExclusiveDetail(r) {
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  const fieldsHtml = EXCLUSIVE_FIELD_LABELS
    .map(([k, label]) => ({ label, value: r[k] }))
    .filter((f) => f.value !== undefined && f.value !== null && String(f.value).trim() !== "")
    .map((f) => `<div class="field"><div class="k">${esc(f.label)}</div><div class="v">${esc(f.value)}</div></div>`)
    .join("");

  box.innerHTML = `
    <h3>${esc(r.property_type || "ობიექტი")} — ${esc(r.location || "")}<button class="close" id="modalClose">✕</button></h3>
    ${fieldsHtml}
    <div class="field"><div class="k">თანამშრომლობა</div><div class="v">🤝 ${esc(r.collaboration_count || 0)} გაზიარება</div></div>
    <div class="share-box">
      <div class="lbl">🔗 გაზიარება კოლეგასთან — კლიენტი დაინტერესდა?</div>
      <div class="qa-compose">
        <select id="shareColleagueSelect"><option value="">კოლეგის არჩევა…</option></select>
        <textarea id="shareNote" placeholder="შენიშვნა (არასავალდებულო)"></textarea>
        <button class="btn" id="shareSubmitBtn">გაზიარება</button>
      </div>
    </div>
  `;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };

  try {
    const { rows: colleagues } = await api("/api/colleagues");
    const sel = document.getElementById("shareColleagueSelect");
    if (sel) {
      sel.innerHTML = `<option value="">კოლეგის არჩევა…</option>` +
        colleagues.map((c) => `<option value="${esc(c.agent_id)}">${esc(c.name)}${c.team ? " (" + esc(c.team) + ")" : ""}</option>`).join("");
    }
  } catch (e) { /* კოლეგების სია ჩავარდა — გაზიარების ველი ცარიელი დარჩება */ }

  const shareBtn = document.getElementById("shareSubmitBtn");
  if (shareBtn) {
    shareBtn.onclick = async () => {
      const toId = document.getElementById("shareColleagueSelect").value;
      if (!toId) { toast("აირჩიეთ კოლეგა"); return; }
      const note = document.getElementById("shareNote").value.trim();
      shareBtn.disabled = true;
      try {
        await api("/api/exclusives/share", {
          method: "POST",
          body: JSON.stringify({ exclusive_id: r.exclusive_id, to_agent_id: toId, note }),
        });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("გაზიარდა ✅");
        closeDetail();
        delete lazyCache.exclusives;
        await renderContent();
      } catch (e) { toast(e.message); shareBtn.disabled = false; }
    };
  }
}

const REPORT_FIELD_LABELS = [
  ["agent_name", "აგენტი"], ["client_phone", "კლიენტის ტელეფონი"], ["actions", "მოქმედებები"],
  ["notes", "შენიშვნა"], ["file_id", "დანართები (ფაილების რაოდენობა)"], ["created_at", "თარიღი"],
  ["quality_auto", "ავტომატური ხარისხი (1-5)"], ["quality_manual", "ხელით შეფასება (1-5)"],
  ["rated_by", "შეაფასა"],
];

/* რეპორტების ისტორია — დღე/კვირა/თვე (renderPeriodSwitch) პლიუს
   კონკრეტული თარიღის picker (state.reportsDate, ორივეს ერთად ვერ
   ვიყენებთ — თარიღი თუ არჩეულია, ის ჭარბობს) და (ადმინისთვის) გუნდი
   → აგენტი დრილდაუნი, task-history-ის იგივე პრინციპით. */
function renderReports(payload) {
  const rows = (payload && payload.rows) || [];
  const teams = (payload && payload.teams) || [];
  const agents = (payload && payload.agents) || [];
  const isAdmin = state.role === "admin" && !(state.data && state.data.is_team_lead);
  const drilldown = (isAdmin || agents.length > 1) ? `
    <div class="qa-compose" style="margin-bottom:10px">
      ${isAdmin ? `<select id="repTeamSelect">
        <option value="">ყველა გუნდი</option>
        ${teams.map((t) => `<option value="${esc(t.team)}" ${state.reportsTeam === t.team ? "selected" : ""}>${esc(t.name)}-ის გუნდი (${t.member_count})</option>`).join("")}
      </select>` : ""}
      <select id="repAgentSelect">
        <option value="">ყველა აგენტი</option>
        ${agents.map((a) => `<option value="${esc(a.agent_id)}" ${state.reportsAgent === String(a.agent_id) ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
      </select>
    </div>` : "";
  return `<div class="card">
    ${renderPeriodSwitch()}
    <div class="qa-compose" style="margin-top:10px">
      <input type="date" id="repDateInput" value="${esc(state.reportsDate || "")}" />
      ${state.reportsDate ? `<button class="btn secondary" id="repDateClear" style="padding:9px 12px">✕ თარიღის გასუფთავება</button>` : ""}
    </div>
    <h2 style="margin-top:10px">📝 რეპორტების ისტორია ${state.reportsDate ? "— " + esc(state.reportsDate) : "— " + esc(PERIOD_TITLES[state.period] || "")} <span class="cnt">${rows.length}</span></h2>
    ${drilldown}
    ${!rows.length ? `<div class="empty">ამ პერიოდში რეპორტი არ არის</div>` :
      rows.map((r, i) => `
      <div class="list-row clickable" data-report="${esc(r.report_id)}" data-report-idx="${i}">
        <div class="avatar">${initials(r.agent_name)}</div>
        <div class="main">
          <div class="title">${esc(r.agent_name)} — ${esc(r.client_phone || "-")}</div>
          <div class="sub">${esc(r.actions || "-")}</div>
          <div class="sub">${esc((r.created_at || "").split(" ")[0] || "")} · ავტომ. ხარისხი: ${esc(r.quality_auto || "-")}/5${r.quality_manual ? " · ხელით: " + esc(r.quality_manual) + "/5" : ""}</div>
        </div>
        <div class="side">
          <button class="btn" data-rate="${esc(r.report_id)}" style="padding:6px 10px">⭐ შეფასება</button>
        </div>
      </div>`).join("")}
  </div>`;
}

/* ------------------------------------------ აგენტების/მენეჯერების მართვა
   ("პირამიდის" აწყობა) — მხოლოდ ადმინისთვის (დირექტორის დონის
   მოქმედება). თითო აგენტს ერთი dropdown-ით ენიშნება: დამოუკიდებელი /
   თიმლიდერი (საკუთარი გუნდი) / კონკრეტული თიმლიდერის გუნდის წევრი.
   მენეჯერს ავტომატურად მიდის შეტყობინება ახალი წევრის შესახებ, და
   აგენტსაც — თავისი მენეჯერის შესახებ. */
function _agentsMgmtRowsHtml(rows, managers) {
  if (!rows.length) return `<div class="empty">ვერაფერი მოიძებნა</div>`;
  return rows.map((r) => {
    const sel = r.role === "team_lead" ? "lead" : (r.manager ? "member:" + r.manager.agent_id : "independent");
    const roleBadge = r.role === "team_lead"
      ? `<span class="badge amber">👑 თიმლიდერი</span>`
      : (r.manager ? `<span class="badge gray">აგენტი</span>` : `<span class="badge gray">დამოუკიდებელი</span>`);
    const options = [
      `<option value="independent" ${sel === "independent" ? "selected" : ""}>დამოუკიდებელი აგენტი</option>`,
      `<option value="lead" ${sel === "lead" ? "selected" : ""}>თიმლიდერი (საკუთარი გუნდი)</option>`,
      ...managers
        .filter((m) => String(m.agent_id) !== String(r.agent_id))
        .map((m) => `<option value="member:${esc(m.agent_id)}" ${sel === "member:" + m.agent_id ? "selected" : ""}>${esc(m.name)}-ის გუნდის წევრი</option>`),
    ].join("");
    return `
    <div class="list-row" style="align-items:flex-start">
      <div class="avatar">${initials(r.name)}</div>
      <div class="main">
        <div class="title">${esc(r.name)} ${r.active === "no" ? "🚫" : ""} ${roleBadge}</div>
        <div class="sub">${esc(r.phone || "")} · ${r.registered ? "✅ დარეგისტრირებული" : "⏳ ელოდება რეგისტრაციას"}</div>
        ${r.manager ? `<div class="sub">მენეჯერი: ${esc(r.manager.name)}</div>` : ""}
        <div class="qa-compose" style="margin-top:8px">
          <select data-assign-select="${esc(r.agent_id)}">${options}</select>
          <button class="btn" data-assign-btn="${esc(r.agent_id)}" style="padding:9px 12px">შენახვა</button>
        </div>
        <div class="actions" style="margin-top:8px">
          ${r.active === "no"
            ? `<button class="btn secondary" data-active-btn="${esc(r.agent_id)}" data-active-val="yes" style="padding:9px 12px">✅ გააქტიურება</button>`
            : `<button class="btn danger" data-active-btn="${esc(r.agent_id)}" data-active-val="no" style="padding:9px 12px">🚫 გათავისუფლება</button>`}
          <button class="btn danger" data-delete-btn="${esc(r.agent_id)}" data-delete-name="${esc(r.name)}" style="padding:9px 12px">🗑️ სამუდამო წაშლა</button>
        </div>
      </div>
    </div>`;
  }).join("");
}

function renderAgentsMgmt(payload) {
  const rows = (payload && payload.rows) || [];
  const managers = (payload && payload.managers) || [];
  const duplicateTeams = (payload && payload.duplicate_teams) || [];
  if (!rows.length) return `<div class="card"><div class="empty">აგენტი ჯერ არ დამატებულა. /addagent</div></div>`;
  const warningHtml = duplicateTeams.length ? `<div class="card" style="border-color:var(--red)">
    <h2 style="color:var(--red)">⚠️ ორ თიმლიდერს ერთი გუნდის კოდი ერგო</h2>
    <div class="sub" style="margin-bottom:8px">ეს ნიშნავს, რომ ქვემოთ ჩამოთვლილი თიმლიდერების გუნდის წევრები Mini App-ში შეიძლება ერთმანეთში აირიოს (მცდარი მენეჯერი უჩვენოს). დააჭირეთ „გასწორებას" თითოეულზე — ამის შემდეგ, ვისი მენეჯერიც არასწორად ჩანდა, „აგენტების მართვა" სიაში ხელახლა აარჩიეთ სწორი მენეჯერი და დააჭირეთ „შენახვა".</div>
    ${duplicateTeams.map((d) => d.leads.map((l) => `
      <div class="list-row">
        <div class="main"><div class="title">${esc(l.name)}</div><div class="sub">გუნდის კოდი გაზიარებულია: ${esc(d.leads.map((x) => x.name).join(", "))}</div></div>
        <div class="side"><button class="btn" data-rekey-btn="${esc(l.agent_id)}" style="padding:8px 10px">🔑 გასწორება</button></div>
      </div>`).join("")).join("")}
  </div>` : "";
  return warningHtml + `<div class="card">
    <h2>🗂️ აგენტების მართვა <span class="cnt">${rows.length}</span></h2>
    <input id="agentsMgmtSearch" placeholder="🔍 ძებნა სახელით/გვარით…" style="width:100%;margin-bottom:10px" />
    <div id="agentsMgmtList">${_agentsMgmtRowsHtml(rows, managers)}</div>
  </div>`;
}

function bindAgentsMgmtActions() {
  const payload = lazyCache.agentsmgmt || {};
  const allRows = payload.rows || [];
  const managers = payload.managers || [];
  const searchInput = document.getElementById("agentsMgmtSearch");
  if (searchInput) {
    searchInput.oninput = () => {
      const q = searchInput.value.trim().toLowerCase();
      const filtered = !q ? allRows : allRows.filter((r) => String(r.name || "").toLowerCase().includes(q));
      document.getElementById("agentsMgmtList").innerHTML = _agentsMgmtRowsHtml(filtered, managers);
      bindAgentsMgmtRowActions();
    };
  }
  bindAgentsMgmtRowActions();
}

function bindAgentsMgmtRowActions() {
  document.querySelectorAll("[data-delete-btn]").forEach((btn) => {
    btn.onclick = async () => {
      const name = btn.dataset.deleteName || "";
      if (!confirm(`ნამდვილად გსურთ „${name}"-ის სამუდამო წაშლა? ეს ვეღარ დაბრუნდება — ისტორია (დავალებები/რეპორტები) უცვლელი დარჩება, მაგრამ თავად აგენტი აღარსად გამოჩნდება.`)) return;
      btn.disabled = true;
      try {
        await api("/api/agents/delete", { method: "POST", body: JSON.stringify({ agent_id: btn.dataset.deleteBtn }) });
        toast("წაიშალა");
        delete lazyCache.agentsmgmt;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-assign-btn]").forEach((btn) => {
    btn.onclick = async () => {
      const agentId = btn.dataset.assignBtn;
      const sel = document.querySelector(`[data-assign-select="${CSS.escape(agentId)}"]`);
      const val = sel && sel.value;
      if (!val) return;
      const body = { agent_id: agentId };
      if (val === "independent") body.mode = "independent";
      else if (val === "lead") body.mode = "lead";
      else { body.mode = "member"; body.manager_id = val.split(":")[1]; }
      btn.disabled = true;
      try {
        await api("/api/agents/assign", { method: "POST", body: JSON.stringify(body) });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("განახლდა ✅");
        delete lazyCache.agentsmgmt;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-active-btn]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api("/api/agents/active", {
          method: "POST",
          body: JSON.stringify({ agent_id: btn.dataset.activeBtn, active: btn.dataset.activeVal }),
        });
        toast(btn.dataset.activeVal === "yes" ? "გააქტიურდა ✅" : "გათავისუფლდა");
        delete lazyCache.agentsmgmt;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-rekey-btn]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api("/api/agents/rekey_team", { method: "POST", body: JSON.stringify({ agent_id: btn.dataset.rekeyBtn }) });
        toast("გუნდის კოდი გასწორდა ✅ — ახლა გადაამოწმეთ ამ თიმლიდერის წევრები ქვემოთ და საჭიროებისამებრ ხელახლა შეარჩიეთ");
        delete lazyCache.agentsmgmt;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
}

/* ------------------------------------------ დავალების/კლიენტის გადაბარება
   და ახალი კლიენტის დამატება (ადმინი — ნებისმიერ აგენტზე/მთელ
   კომპანიაზე, თიმლიდერი — მხოლოდ საკუთარ გუნდში, კურატორის
   პრინციპით — ადრე ორივე ეს ფუნქცია მხოლოდ ადმინს შეეძლო, ბოტის
   /newtask ბრძანებით ან ცხრილის ხელით რედაქტირებით). */
const ADMINTASKS_PRIORITY_COLOR = { "მაღალი": "red", "საშუალო": "amber" };
let newTaskKind = "general";

function renderNewTaskForm(agents) {
  const agentOptions = agents
    .map((a) => `<option value="${esc(a.agent_id)}">${esc(a.name)}${a.team ? " (" + esc(a.team) + ")" : ""}</option>`)
    .join("");
  return `<div class="card">
    <h2>➕ ახალი კლიენტი</h2>
    <div class="period-switch" id="newTaskKindSwitch">
      <button data-kind="general" class="${newTaskKind === "general" ? "active" : ""}">ზოგადი კლიენტი</button>
      <button data-kind="listing" class="${newTaskKind === "listing" ? "active" : ""}">კონკრეტული ბინა</button>
    </div>
    <div class="qa-compose" data-kind-fields="general" ${newTaskKind === "general" ? "" : "hidden"}>
      <input id="ntPhone" placeholder="კლიენტის ტელეფონი" />
      <select id="ntDeal">
        <option value="ქირა">ქირა</option>
        <option value="ყიდვა">ყიდვა</option>
      </select>
      <select id="ntPriority">
        <option value="მაღალი">პრიორიტეტი: მაღალი (საუკეთესო აგენტს ერგება)</option>
        <option value="საშუალო">პრიორიტეტი: საშუალო (ყველაზე სუსტს ერგება)</option>
        <option value="დაბალი">პრიორიტეტი: დაბალი (შემთხვევით ერგება)</option>
      </select>
      <label class="check-row" style="display:flex;align-items:center;gap:8px;margin-top:4px">
        <input type="checkbox" id="ntAssignSelf" />
        <span class="sub" style="margin:0">საკუთარ თავზე დავარეგისტრირო (ავტომატური აგენტის არჩევის გარეშე)</span>
      </label>
      <textarea id="ntNotes" rows="2" maxlength="1000" placeholder="დამატებითი დეტალი (არასავალდებულო) — აგენტი წაიკითხავს ამ კლიენტზე"></textarea>
    </div>
    <div class="qa-compose" data-kind-fields="listing" ${newTaskKind === "listing" ? "" : "hidden"}>
      <select id="ntAgent">${agentOptions || `<option value="">აგენტი არ არის</option>`}</select>
      <input id="ntListingId" placeholder="ლისტინგის/ბინის ID" />
      <input id="ntListingPhone" placeholder="კლიენტის ტელეფონი" />
      <input id="ntOwnerPhone" placeholder="მესაკუთრის ნომერი (არასავალდებულო)" inputmode="tel" />
      <input id="ntViewingTime" placeholder="ნახვის დრო (მაგ. ხვალ 12:00)" />
      <textarea id="ntListingNotes" rows="2" maxlength="1000" placeholder="დამატებითი დეტალი (არასავალდებულო) — აგენტი წაიკითხავს ამ კლიენტზე"></textarea>
    </div>
    <button class="btn" id="ntSubmit" style="margin-top:4px">დამატება</button>
  </div>`;
}

function renderAdminTasks(payload) {
  const tasks = (payload && payload.rows) || [];
  const agents = (payload && payload.agents) || [];
  const optionsFor = (currentAgentId) => `<option value="">აგენტის არჩევა…</option>` +
    agents
      .filter((a) => String(a.agent_id) !== String(currentAgentId))
      .map((a) => `<option value="${esc(a.agent_id)}">${esc(a.name)}${a.team ? " (" + esc(a.team) + ")" : ""}</option>`)
      .join("");
  const tasksHtml = !tasks.length
    ? `<div class="card"><div class="empty">ღია დავალება არ არის ✅</div></div>`
    : `<div class="card">
    <h2>📄 ღია დავალებები <span class="cnt">${tasks.length}</span></h2>
    ${tasks.map((t) => `
      <div class="list-row" style="align-items:flex-start">
        <div class="avatar">${t.lead_type === "listing" ? "🏠" : "👤"}</div>
        <div class="main">
          <div class="title">${esc(t.title || "")} <span class="badge ${ADMINTASKS_PRIORITY_COLOR[t.priority] || "gray"}" style="margin-left:2px">${esc(t.priority || "-")}</span></div>
          <div class="sub">კურატორი: ${esc(t.assigned_to_name || t.assigned_to || "—")}${t.client_phone ? " · " + esc(t.client_phone) : ""}</div>
          <div class="qa-compose" style="margin-top:8px">
            <select data-reassign-select="${esc(t.task_id)}">${optionsFor(t.assigned_to)}</select>
            <button class="btn" data-reassign-btn="${esc(t.task_id)}" style="padding:9px 12px">🔁 გადაბარება</button>
          </div>
        </div>
      </div>`).join("")}
  </div>`;
  return renderNewTaskForm(agents) + tasksHtml;
}

function bindAdminTasksActions() {
  document.querySelectorAll("[data-reassign-btn]").forEach((btn) => {
    btn.onclick = async () => {
      const taskId = btn.dataset.reassignBtn;
      const sel = document.querySelector(`[data-reassign-select="${CSS.escape(taskId)}"]`);
      const toId = sel && sel.value;
      if (!toId) { toast("აირჩიეთ აგენტი"); return; }
      btn.disabled = true;
      try {
        await api("/api/tasks/reassign", { method: "POST", body: JSON.stringify({ task_id: taskId, to_agent_id: toId }) });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("გადაბარდა ✅");
        delete lazyCache.admintasks;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });

  const kindSwitch = document.getElementById("newTaskKindSwitch");
  if (kindSwitch) {
    kindSwitch.querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        newTaskKind = b.dataset.kind;
        kindSwitch.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
        document.querySelectorAll("[data-kind-fields]").forEach((el) => {
          el.hidden = el.dataset.kindFields !== newTaskKind;
        });
      };
    });
  }

  const submitBtn = document.getElementById("ntSubmit");
  if (submitBtn) {
    submitBtn.onclick = async () => {
      let body;
      if (newTaskKind === "general") {
        const phone = (document.getElementById("ntPhone").value || "").trim();
        if (!phone) { toast("შეიყვანეთ ტელეფონის ნომერი"); return; }
        const assignSelf = document.getElementById("ntAssignSelf");
        body = {
          kind: "general",
          phone,
          deal_type: document.getElementById("ntDeal").value,
          priority: document.getElementById("ntPriority").value,
          assign_to_self: !!(assignSelf && assignSelf.checked),
          notes: (document.getElementById("ntNotes").value || "").trim(),
        };
      } else {
        const agentId = document.getElementById("ntAgent").value;
        const listingId = (document.getElementById("ntListingId").value || "").trim();
        const phone = (document.getElementById("ntListingPhone").value || "").trim();
        if (!agentId) { toast("აირჩიეთ აგენტი"); return; }
        if (!listingId || !phone) { toast("შეავსეთ ლისტინგის ID და ტელეფონი"); return; }
        body = {
          kind: "listing",
          agent_id: agentId,
          listing_id: listingId,
          phone,
          viewing_time: (document.getElementById("ntViewingTime").value || "").trim(),
          owner_phone: (document.getElementById("ntOwnerPhone").value || "").trim(),
          notes: (document.getElementById("ntListingNotes").value || "").trim(),
        };
      }
      submitBtn.disabled = true;
      try {
        const created = await api("/api/tasks/new", { method: "POST", body: JSON.stringify(body) });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast(created && created.delivered === false
          ? "დამატებულია ✅, მაგრამ აგენტთან ჯერ ვერ მივიდა — ავტომატურად გავიმეორებ, 10 წთ-ში გაგაფრთხილებ"
          : "დამატებულია და აგენტს მიუვიდა ✅");
        delete lazyCache.admintasks;
        await renderContent();
      } catch (e) { toast(e.message); submitBtn.disabled = false; }
    };
  }
}

/* ------------------------------------------------------ შეხვედრები */
function renderMeetings(payload) {
  const rows = (payload && payload.rows) || [];
  const isTeamLead = state.role === "admin" && state.data && state.data.is_team_lead;
  const scopeSwitch = isTeamLead ? `<div class="period-switch" id="meetingsScopeSwitch">
      <button data-scope="team" class="${state.meetingsScope !== "own" ? "active" : ""}">👥 გუნდის</button>
      <button data-scope="own" class="${state.meetingsScope === "own" ? "active" : ""}">👤 ჩემი პირადი</button>
    </div>` : "";
  return `<div class="card">
    ${scopeSwitch}
    ${renderPeriodSwitch()}
    <h2>🤝 შეხვედრები — ${isTeamLead ? (state.meetingsScope === "own" ? "ჩემი პირადი — " : "გუნდის — ") : ""}${esc(PERIOD_TITLES[state.period] || "")} <span class="cnt">${rows.length}</span></h2>
    ${!rows.length ? `<div class="empty">ამ პერიოდში შეხვედრა არ ყოფილა</div>` :
      rows.map((m, i) => `
      <div class="list-row clickable" style="align-items:flex-start" data-meeting-idx="${i}">
        <div class="avatar">🏠</div>
        <div class="main">
          <div class="title">${esc(m.address || m.district || "მისამართი უცნობია")}</div>
          <div class="sub">${esc(m.agent_name || "")}${m.owner_phone ? " · მეპატრონე: " + esc(m.owner_phone) : ""}</div>
          <div class="sub">${esc(m.meeting_date || "")} ${esc(m.time || "")}${m.price ? " · " + esc(m.price) : ""}</div>
        </div>
        <div class="side sub">${esc((m.timestamp || "").split(" ")[0] || "")}</div>
      </div>`).join("")}
  </div>`;
}

function bindMeetingsActions(payload) {
  const rows = (payload && payload.rows) || [];
  const scopeSwitch = document.getElementById("meetingsScopeSwitch");
  if (scopeSwitch) {
    scopeSwitch.querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        if (state.meetingsScope === b.dataset.scope) return;
        state.meetingsScope = b.dataset.scope;
        delete lazyCache.meetings;
        renderContent();
      };
    });
  }
  document.querySelectorAll("[data-meeting-idx]").forEach((el) => {
    el.onclick = () => {
      const m = rows[parseInt(el.dataset.meetingIdx, 10)];
      if (!m) return;
      openDetail(m.address || m.district || "შეხვედრა", MEETING_FIELD_LABELS.map(([k, label]) => ({ label, value: m[k] })),
        `<div class="share-box" id="ctMeetingBox"><div class="lbl">📑 ხელშეკრულებები</div><div class="sub">იტვირთება…</div></div>`);
      ctLoadMeetingBox(m);
    };
  });
}

/* ------------------------------------------------------ დავალებების ისტორია */
function renderTaskHistory(payload) {
  const rows = (payload && payload.rows) || [];
  const teams = (payload && payload.teams) || [];
  const agents = (payload && payload.agents) || [];
  const isAdmin = state.role === "admin" && !(state.data && state.data.is_team_lead);
  const statusLabel = { New: "ახალი", InProgress: "მუშავდება", Done: "დასრულებული" };
  const drilldown = (isAdmin || agents.length > 1) ? `
    <div class="qa-compose" style="margin-bottom:10px">
      ${isAdmin ? `<select id="histTeamSelect">
        <option value="">ყველა გუნდი</option>
        ${teams.map((t) => `<option value="${esc(t.team)}" ${state.historyTeam === t.team ? "selected" : ""}>${esc(t.name)}-ის გუნდი (${t.member_count})</option>`).join("")}
      </select>` : ""}
      <select id="histAgentSelect">
        <option value="">ყველა აგენტი</option>
        ${agents.map((a) => `<option value="${esc(a.agent_id)}" ${state.historyAgent === String(a.agent_id) ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
      </select>
    </div>` : "";
  return `<div class="card">
    ${renderPeriodSwitch()}
    <h2>📜 დავალებების ისტორია — ${esc(PERIOD_TITLES[state.period] || "")} <span class="cnt">${rows.length}</span></h2>
    ${drilldown}
    ${!rows.length ? `<div class="empty">ამ პერიოდში დავალება არ ყოფილა</div>` :
      rows.map((t, i) => `
      <div class="list-row clickable" style="align-items:flex-start" data-hist-idx="${i}">
        <div class="avatar">${t.lead_type === "listing" ? "🏠" : "👤"}</div>
        <div class="main">
          <div class="title">${esc(t.title || "")}</div>
          <div class="sub">${esc(t.assigned_to_name || "")}${t.client_phone ? " · " + esc(t.client_phone) : ""}</div>
          <div class="sub">${esc((t.created_at || "").split(" ")[0] || "")}</div>
        </div>
        <div class="side"><span class="badge ${t.status === "Done" ? "green" : "gray"}">${esc(statusLabel[t.status] || t.status || "-")}</span></div>
      </div>`).join("")}
  </div>`;
}

function bindTaskHistoryActions(payload) {
  const rows = (payload && payload.rows) || [];
  document.querySelectorAll("[data-hist-idx]").forEach((el) => {
    el.onclick = () => {
      const t = rows[parseInt(el.dataset.histIdx, 10)];
      if (!t) return;
      openDetail(t.title || "დავალება", TASK_FIELD_LABELS.map(([k, label]) => ({ label, value: t[k] })));
    };
  });
  const teamSel = document.getElementById("histTeamSelect");
  if (teamSel) {
    teamSel.onchange = () => {
      state.historyTeam = teamSel.value;
      state.historyAgent = "";
      delete lazyCache.taskhistory;
      renderContent();
    };
  }
  const agentSel = document.getElementById("histAgentSelect");
  if (agentSel) {
    agentSel.onchange = () => {
      state.historyAgent = agentSel.value;
      delete lazyCache.taskhistory;
      renderContent();
    };
  }
}

/* ------------------------------------------------------ დღის ამბები (digest) */
function renderDigest(payload) {
  const d = payload || {};
  const isAdmin = state.role === "admin" && !(state.data && state.data.is_team_lead);
  const teams = d.teams || [];
  const DIGEST_TITLE_WORD = { day: "დღის", week: "კვირის", month: "თვის" };
  const titleWord = DIGEST_TITLE_WORD[state.period] || "დღის";
  const isDay = (d.days || 1) <= 1;
  const periodWord = isDay ? "დღეს" : (PERIOD_TITLES[state.period] || "") + "ში";
  const section = (icon, title, items, empty) => `
    <div class="field"><div class="k">${icon} ${esc(title)}</div></div>
    ${items && items.length
      ? items.map((s) => `<div class="list-row"><div class="main"><div class="title">${esc(s)}</div></div></div>`).join("")
      : `<div class="empty">${esc(empty)}</div>`}`;
  return `<div class="card">
    ${renderPeriodSwitch()}
    ${isAdmin ? `<div class="qa-compose" style="margin-bottom:10px">
      <select id="digestTeamSelect">
        <option value="">მთელი კომპანია</option>
        ${teams.map((t) => `<option value="${esc(t.team)}" ${state.digestTeam === t.team ? "selected" : ""}>${esc(t.name)}-ის გუნდი</option>`).join("")}
      </select>
    </div>` : ""}
    <h2>🗞️ ${esc(titleWord)} ამბები — ${isAdmin ? (state.digestTeam ? esc((teams.find((t) => t.team === state.digestTeam) || {}).name || "") + "-ის გუნდი — " : "მთელი კომპანია — ") : "ჩემი გუნდი — "}${esc(d.date || "")}</h2>
    ${section("1️⃣", `დღეს გამოცხადდა (${(d.came || []).length})`, d.came, "დღეს ჯერ არავინ დაწყებულა")}
    ${d.not_started && d.not_started.length ? section("🔴", "დღეს ჯერ არ დაწყებულა", d.not_started, "") : ""}
    ${section("2️⃣", `${periodWord} კლიენტი ჩაბარდა`, d.clients_assigned, `${periodWord} არავის ჩაბარებია`)}
    ${section("3️⃣", `${periodWord} შეხვედრაზე იყო`, d.meetings, `${periodWord} შეხვედრა არ ყოფილა`)}
    ${section("4️⃣", "დღეს შეყვანილი განცხადებები", d.listing_counts, "ჯერ არავის შეუყვანია")}
    ${section("5️⃣", `${periodWord} გაფრთხილება მიიღო`, d.warnings_today, `${periodWord} გაფრთხილება არ ყოფილა`)}
    ${section("6️⃣", "საჭიროებს ყურადღებას", d.attention, "ყველაფერი წესრიგშია 🎉")}
  </div>`;
}

function bindDigestActions() {
  bindPeriodSwitch();
  const sel = document.getElementById("digestTeamSelect");
  if (sel) {
    sel.onchange = () => {
      state.digestTeam = sel.value;
      delete lazyCache.digest;
      renderContent();
    };
  }
}

const SWAP_STATUS_LABEL = {
  pending_peer: "⏳ კოლეგის პასუხის მოლოდინში", pending_manager: "⏳ მენეჯერის მოლოდინში",
  approved: "✅ დამტკიცებული", rejected: "❌ უარყოფილი",
};
const SWAP_FIELD_LABELS = [
  ["agent_name", "მოითხოვა"], ["target_agent_name", "გაცვლის მხარე"],
  ["request_type", "ტიპი"], ["swap_date", "თარიღი"],
  ["from_mode", "ძველი სმენა"], ["to_mode", "ახალი სმენა"],
  ["note", "შენიშვნა"], ["accepted_by_name", "დაეთანხმა"],
  ["status", "სტატუსი"], ["decided_by", "გადაწყვიტა"], ["decided_at", "გადაწყვეტის დრო"],
  ["created_at", "მოთხოვნის დრო"],
];

function renderSwaps(payload) {
  const pending = (payload && payload.pending) || [];
  const history = (payload && payload.history) || [];
  const swapRow = (r, withActions) => `
      <div class="list-row clickable" data-swap-id="${esc(r.swap_id)}">
        <div class="avatar">🔁</div>
        <div class="main">
          <div class="title">${esc(REQUEST_TYPE_LABELS[r.request_type] || r.request_type)}</div>
          <div class="sub">${esc(r.agent_name)}${r.target_agent_name ? " ⇄ " + esc(r.target_agent_name) : ""} · ${esc(r.swap_date || "-")}</div>
          <div class="sub">${r.from_mode ? esc(MODE_LABELS[r.from_mode] || r.from_mode) + " → " : ""}${r.to_mode ? esc(MODE_LABELS[r.to_mode] || r.to_mode) : ""}${r.note ? " · " + esc(r.note) : ""}</div>
          ${!withActions ? `<div class="sub">${esc(SWAP_STATUS_LABEL[r.status] || r.status)}</div>` : ""}
        </div>
      </div>
      ${withActions ? `<div class="actions" style="margin:-2px 0 12px">
        <button class="btn" data-swapact="approved" data-id="${esc(r.swap_id)}">✅ დამტკიცება</button>
        <button class="btn danger" data-swapact="rejected" data-id="${esc(r.swap_id)}">✖️ უარყოფა</button>
      </div>` : ""}`;
  return `<div class="card">
    <h2>🔁 დასადასტურებელი სმენის გაცვლები <span class="cnt">${pending.length}</span></h2>
    ${!pending.length ? `<div class="empty">დასადასტურებელი მოთხოვნა არ არის</div>` : pending.map((r) => swapRow(r, true)).join("")}
  </div>
  <div class="card">
    <h2>📜 გაცვლების ისტორია <span class="cnt">${history.length}</span></h2>
    ${!history.length ? `<div class="empty">ისტორია ჯერ ცარიელია</div>` : history.map((r) => swapRow(r, false)).join("")}
  </div>`;
}

function bindReportsActions(payload) {
  const rows = (payload && payload.rows) || [];
  document.querySelectorAll("[data-rate]").forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const input = prompt("შეაფასეთ ხარისხი 1-დან 5-მდე:");
      const score = parseInt(input, 10);
      if (!input || isNaN(score) || score < 1 || score > 5) return;
      btn.disabled = true;
      try {
        await api("/api/reports/rate", { method: "POST", body: JSON.stringify({ report_id: btn.dataset.rate, score }) });
        toast("შეფასდა ✅");
        delete lazyCache.reports;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-report-idx]").forEach((el) => {
    el.onclick = () => {
      const r = rows[parseInt(el.dataset.reportIdx, 10)];
      if (!r) return;
      openDetail(
        `რეპორტი — ${r.agent_name || ""}`,
        REPORT_FIELD_LABELS.map(([k, label]) => ({ label, value: r[k] })),
      );
    };
  });
  const dateInput = document.getElementById("repDateInput");
  if (dateInput) {
    dateInput.onchange = () => {
      state.reportsDate = dateInput.value || "";
      delete lazyCache.reports;
      renderContent();
    };
  }
  const dateClear = document.getElementById("repDateClear");
  if (dateClear) {
    dateClear.onclick = () => {
      state.reportsDate = "";
      delete lazyCache.reports;
      renderContent();
    };
  }
  const teamSel = document.getElementById("repTeamSelect");
  if (teamSel) {
    teamSel.onchange = () => {
      state.reportsTeam = teamSel.value;
      state.reportsAgent = "";
      delete lazyCache.reports;
      renderContent();
    };
  }
  const agentSel = document.getElementById("repAgentSelect");
  if (agentSel) {
    agentSel.onchange = () => {
      state.reportsAgent = agentSel.value;
      delete lazyCache.reports;
      renderContent();
    };
  }
}

function bindSwapsActions(payload) {
  const all = [...((payload && payload.pending) || []), ...((payload && payload.history) || [])];
  document.querySelectorAll("[data-swapact]").forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      btn.disabled = true;
      try {
        await api("/api/swaps/decide", {
          method: "POST",
          body: JSON.stringify({ swap_id: btn.dataset.id, status: btn.dataset.swapact }),
        });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast(btn.dataset.swapact === "approved" ? "დამტკიცდა ✅" : "უარყოფილია");
        delete lazyCache.swaps;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-swap-id]").forEach((el) => {
    el.onclick = () => {
      const r = all.find((x) => String(x.swap_id) === el.dataset.swapId);
      if (!r) return;
      openDetail(REQUEST_TYPE_LABELS[r.request_type] || "სმენის გაცვლა", SWAP_FIELD_LABELS.map(([k, label]) => ({ label, value: k === "status" ? (SWAP_STATUS_LABEL[r.status] || r.status) : r[k] })));
    };
  });
}

/* ---------------------------------------------------- კითხვა მენეჯერს */

function renderQuestions(rows, role) {
  const compose = `
    <div class="card">
      <h2>💬 კითხვა მენეჯერს</h2>
      <div class="qa-compose">
        <textarea id="qaText" placeholder="დაწერეთ კითხვა…"></textarea>
        <button class="btn" id="qaSend">გაგზავნა</button>
      </div>
    </div>`;

  if (role === "agent") {
    const thread = !rows.length
      ? `<div class="card"><div class="empty">ჯერ კითხვა არ დაგისვამთ</div></div>`
      : `<div class="card">
          <h2>🗂️ ჩემი კითხვები <span class="cnt">${rows.length}</span></h2>
          <div class="qa-thread">
            ${rows.map((q) => `
              <div class="qa-item">
                <div class="qa-q">${esc(q.text)}</div>
                <div class="qa-meta">${esc((q.created_at || "").split(" ")[0] || "")} · ${q.status === "open" ? "⏳ ლოდინში" : "✅ პასუხგაცემული"}</div>
                ${q.answer ? `<div class="qa-a"><div class="who">${esc(q.answered_by || "მენეჯერი")}</div>${esc(q.answer)}</div>` : ""}
              </div>`).join("")}
          </div>
        </div>`;
    return compose + thread;
  }

  const open = rows.filter((q) => q.status === "open");
  const answered = rows.filter((q) => q.status !== "open");
  const openHtml = !open.length
    ? `<div class="card"><div class="empty">ღია კითხვა არ არის 🎉</div></div>`
    : `<div class="card">
        <h2>⏳ ღია კითხვები <span class="cnt">${open.length}</span></h2>
        <div class="qa-thread">
          ${open.map((q) => `
            <div class="qa-item">
              <div class="qa-q"><b>${esc(q.agent_name)}</b>: ${esc(q.text)}</div>
              <div class="qa-meta">${esc((q.created_at || "").split(" ")[0] || "")}</div>
              <textarea placeholder="პასუხი…" data-answer-text="${esc(q.question_id)}"></textarea>
              <button class="btn" data-answer-send="${esc(q.question_id)}">პასუხის გაგზავნა</button>
            </div>`).join("")}
        </div>
      </div>`;
  const answeredHtml = !answered.length ? "" : `<div class="card">
      <h2>🗂️ ბოლო პასუხგაცემული</h2>
      <div class="qa-thread">
        ${answered.map((q) => `
          <div class="qa-item">
            <div class="qa-q"><b>${esc(q.agent_name)}</b>: ${esc(q.text)}</div>
            <div class="qa-a"><div class="who">${esc(q.answered_by || "მენეჯერი")}</div>${esc(q.answer || "")}</div>
          </div>`).join("")}
      </div>
    </div>`;
  return openHtml + answeredHtml;
}

function bindQuestionsActions(role) {
  const sendBtn = document.getElementById("qaSend");
  if (sendBtn) {
    sendBtn.onclick = async () => {
      const ta = document.getElementById("qaText");
      const text = (ta.value || "").trim();
      if (!text) return;
      sendBtn.disabled = true;
      try {
        await api("/api/questions", { method: "POST", body: JSON.stringify({ text }) });
        toast("გაიგზავნა ✅");
        delete lazyCache.questions;
        await renderContent();
      } catch (e) { toast(e.message); sendBtn.disabled = false; }
    };
  }
  document.querySelectorAll("[data-answer-send]").forEach((btn) => {
    btn.onclick = async () => {
      const qid = btn.dataset.answerSend;
      const ta = document.querySelector(`[data-answer-text="${CSS.escape(qid)}"]`);
      const answer = (ta && ta.value || "").trim();
      if (!answer) return;
      btn.disabled = true;
      try {
        await api("/api/questions/answer", { method: "POST", body: JSON.stringify({ question_id: qid, answer }) });
        toast("გაიგზავნა ✅");
        delete lazyCache.questions;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
}

/* ------------------------------------------- MyHome ლისტინგის queue */

const MYHOME_JOB_STATUS_LABEL = {
  QUEUED: `<span class="badge amber">⏳ რიგშია</span>`,
  PROCESSING: `<span class="badge amber">⚙️ მუშავდება</span>`,
  COMPLETED: `<span class="badge green">✅ დასრულდა</span>`,
  FAILED: `<span class="badge red">❌ ჩავარდა</span>`,
};

if (!state.mhSearch) state.mhSearch = { q: "", dealType: "", status: "", dateFrom: "", dateTo: "" };
let mhSearchResults = null; // null = ჩემი/გუნდის ჩვეულებრივი სია; array = ძებნის შედეგი (ყველა კოლეგა)
let mhRowsById = {}; // job_id -> row, დეტალის მოდალისთვის (ორიგინალი, გაუფილტრავი ველებით)

function _renderMyHomeRow(r, showAgentName) {
  const canRetry = r.status === "FAILED" || r.status === "PROCESSING";
  return `
    <div class="list-row" data-mh-row="${esc(r.job_id)}" style="cursor:pointer">
      <div class="avatar">🏠</div>
      <div class="main">
        <div class="title">${r.listing_source === "ssge" ? "ss.ge" : "MyHome"} ID: ${esc(r.myhome_listing_id)}${r.publish_target === "both" ? " → MyHome+ss.ge" : (r.publish_target === "ssge" && r.listing_source !== "ssge" ? " → ss.ge" : (r.publish_target === "myhome" && r.listing_source === "ssge" ? " → MyHome" : ""))}${showAgentName ? " · " + esc(r.agent_name) : ""}</div>
        <div class="sub">${MYHOME_JOB_STATUS_LABEL[r.status] || esc(r.status)}${r.deal_type ? " · " + esc(r.deal_type) : ""}${r.cooperation_percent ? " · " + esc(r.cooperation_percent) + "%" : ""}${r.final_price ? " · 💰 " + esc(r.final_price) : ""}</div>
        ${r.address ? `<div class="sub">📍 ${esc(r.address)}${r.district ? ", " + esc(r.district) : ""}</div>` : ""}
        ${r.notes ? `<div class="sub">📝 ${esc(r.notes)}</div>` : ""}
        <div class="sub">${esc((r.created_at || "").split(" ")[0] || "")}${r.completed_at ? " → " + esc((r.completed_at || "").split(" ")[0] || "") : ""}</div>
        ${r.status === "FAILED" && r.error_message ? `<div class="sub">⚠️ ${esc(r.error_message)}</div>` : ""}
      </div>
      ${canRetry ? `<button class="btn" data-mh-retry="${esc(r.job_id)}" style="padding:8px 10px">🔁</button>` : ""}
    </div>`;
}

function _openMyHomeDetail(jobId) {
  const r = mhRowsById[jobId];
  if (!r) return;
  const canRetry = r.status === "FAILED" || r.status === "PROCESSING";
  openDetail(`🏘️ MyHome ID: ${r.myhome_listing_id}`, [
    { label: "სტატუსი", value: MYHOME_JOB_STATUS_LABEL[r.status] || r.status },
    { label: "აგენტი", value: r.agent_name },
    { label: "გუნდი", value: r.team },
    { label: "გარიგება", value: r.deal_type },
    { label: "თანამშრომლობის %", value: r.cooperation_percent },
    { label: "ავტომატური ცდები", value: r.retry_count && r.retry_count !== "0" ? `${r.retry_count} / 3` : "" },
    { label: "შემდეგი ავტო-ცდა", value: r.next_retry_at },
    { label: "ჩავარდნის ეტაპი", value: r.failure_stage },
    { label: "საბოლოო ფასი", value: r.final_price },
    { label: "მისამართი", value: r.address },
    { label: "რაიონი", value: r.district },
    { label: "ქალაქი", value: r.city },
    { label: "შენიშვნა", value: r.notes },
    { label: "მესაკუთრის ნომერი", value: r.owner_number },
    { label: "დაემატა", value: r.created_at },
    { label: "დაიწყო დამუშავება", value: r.started_at },
    { label: "დასრულდა", value: r.completed_at },
    { label: "ცდების რაოდენობა", value: r.retry_count },
    { label: "შეცდომა", value: r.error_message },
    { label: "MyHome ლინკი", value: r.status === "COMPLETED" && r.listing_source !== "ssge" && r.publish_target !== "ssge" ? `https://myhome.ge/pr/${r.myhome_listing_id}` : "" },
    { label: "წყარო (საიტი)", value: r.listing_source === "ssge" ? "ss.ge" : "" },
    { label: "სად უნდა დადებულიყო", value: r.publish_target === "ssge" ? "ss.ge" : (r.publish_target === "both" ? "MyHome + ss.ge" : "") },
    { label: "ss.ge-ზე დადებული განცხადება", value: r.ssge_listing_id ? `https://home.ss.ge/ka/udzravi-qoneba/${r.ssge_listing_id}` : "" },
  ], canRetry ? `<button class="btn" id="mhDetailRetry" style="margin-top:10px;width:100%">🔁 ხელახლა გაშვება</button>` : "");
  const retryBtn = document.getElementById("mhDetailRetry");
  if (retryBtn) retryBtn.onclick = () => _mhRetryJob(jobId, retryBtn);
}

async function _mhRetryJob(jobId, el) {
  if (el) el.disabled = true;
  try {
    await api("/api/myhome-jobs/retry", { method: "POST", body: JSON.stringify({ job_id: jobId }) });
    tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
    toast("ხელახლა რიგშია ✅");
    closeDetail();
    delete lazyCache.myhomejobs;
    mhSearchResults = null;
    await renderContent();
  } catch (e) { toast(e.message); if (el) el.disabled = false; }
}

/* ადმინს: worker-ის მდგომარეობა (heartbeat) — ონლაინ/ოფლაინ + ბოლო სიგნალი */
function renderWorkerBadge(role) {
  if (role !== "admin" || !state.workers) return "";
  if (!state.workers.length) {
    return `<div class="card"><h2>🖥️ Worker</h2><div class="sub">heartbeat ჯერ არ მიღებულა (worker-ის ახალი ვერსია უნდა ჩაირთოს)</div></div>`;
  }
  return `<div class="card"><h2>🖥️ Worker</h2>${state.workers.map((w) => {
    const mins = w.age_seconds == null ? "?" : Math.max(0, Math.round(w.age_seconds / 60));
    return `<div class="list-row"><div class="avatar">${w.online ? "🟢" : "🔴"}</div><div class="main">
      <div class="title">${esc(w.worker_id)} — ${w.online ? "ონლაინ" : "ოფლაინ"}</div>
      <div class="sub">ბოლო სიგნალი: ${mins} წთ წინ${w.current_job_id ? " · job " + esc(w.current_job_id) + (w.stage ? " (" + esc(w.stage) + ")" : "") : ""}</div>
    </div></div>`;
  }).join("")}</div>`;
}

/* ============================================ MyHome ანგარიშები (ადმინის ფორმა) ====
   პატარა ღილაკი MyHome ტაბში -> ფორმა: ახალი MyHome ანგარიშის გააქტიურება/პაროლის განახლება
   კოდში ქექვის გარეშე. email/პაროლი სერვერზე არსად ინახება — worker-მა (ლოკალური კომპიუტერი)
   რამდენიმე წამში იღებს და თავის accounts.json-ში წერს. ფორმა მხოლოდ ადმინს ეჩვენება. */
function renderMhAccountsButton(role) {
  if (role !== "admin" || !state.data || !state.data.is_admin) return "";
  return `<div style="display:flex;justify-content:flex-end;margin:0 0 8px">
    <button class="btn secondary" id="mhRetryBtn" style="padding:6px 12px;font-size:12.5px;width:auto;margin-right:6px">🔁 ჩავარდნილების გაშვება</button>
    <button class="btn secondary" id="mhAccBtn" style="padding:6px 12px;font-size:12.5px;width:auto">⚙️ MyHome ანგარიშები</button>
  </div>`;
}

/* ჩავარდნილი job-ების ერთიანად ხელახლა გაშვება: ჯერ მშრალი გამოთვლა (dry-run), მერე თანხმობა; ორმაგი გადახდისგან
   დაცვა სერვერზეა (არარსებული ID, გადახდილი და უკვე დადებული არ ბრუნდება). */
async function runBulkRetry() {
  try {
    const pre = await api("/api/myhome-jobs/retry-failed", { method: "POST", body: JSON.stringify({ dry_run: true }) });
    if (!pre.safe && !pre.payment) {
      alert("ხელახლა გასაშვები ჩავარდნილი არ არის (ბოლო 2 დღეში).\n"
        + `გამოტოვებული: არარსებული ID ${pre.skipped.permanent}, უკვე დადებული ${pre.skipped.done}, გადახდილი ${pre.skipped.paid}`);
      return;
    }
    if (!confirm(`ხელახლა გაეშვას ${pre.safe} ჩავარდნილი (გადახდამდე ჩავარდნილი — უსაფრთხო)?\n`
      + `გამოტოვებულია: არარსებული ID ${pre.skipped.permanent}, უკვე დადებული ${pre.skipped.done}, გადახდილი ${pre.skipped.paid}.`)) {
      if (!pre.payment) return;
    }
    let includePayment = false;
    if (pre.payment) {
      includePayment = confirm(`დამატებით ${pre.payment} job, რომელიც გადახდის ეტაპზე ჩავარდა (MyHome-მა გადახდა უარყო/გვერდი არ გადავიდა).\n`
        + "ისინიც გაეშვას? გააკეთეთ მხოლოდ თუ ბალანსი შევსებულია და დარწმუნებული ხართ, რომ ეს განცხადებები MyHome-ზე არ დადებულა (ორმაგი გადახდის რისკი).");
    }
    if (!pre.safe && !includePayment) return;
    const res = await api("/api/myhome-jobs/retry-failed", { method: "POST", body: JSON.stringify({ include_payment: includePayment }) });
    if (!res.started) { toast("გასაშვები არაფერია"); return; }
    toast(`⏳ ${res.will_retry} job ბრუნდება რიგში…`);
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 4000));
      const st = await api("/api/myhome-jobs/retry-failed/status");
      if (!st.running) {
        toast(`✅ რიგში დაბრუნდა ${st.done}${st.failed ? ", ვერ დაბრუნდა " + st.failed : ""}`);
        break;
      }
    }
    delete lazyCache.myhomejobs;
    await renderContent();
  } catch (e) { toast(e.message || "შეცდომა"); }
}

const _MH_DELIVERY_LABELS = { pending: "⏳ worker-ს ელოდება", delivered: "✅ worker-მა მიიღო", none: "" };

async function openMhAccountsModal() {
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  box.innerHTML = `<h3>⚙️ MyHome ანგარიშები<button class="close" id="modalClose">✕</button></h3><div class="empty">იტვირთება…</div>`;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };

  let data;
  try { data = await api("/api/myhome-accounts"); }
  catch (e) { box.innerHTML += `<div class="empty">⚠️ ${esc(e.message)}</div>`; return; }

  const rows = data.rows || [];
  const list = rows.length ? rows.map((r) => `
      <div class="list-row clickable" data-mh-acc="${esc(r.manager_label)}" data-mh-team="${esc(r.team)}" data-mh-name="${esc(r.manager_name)}">
        <div class="avatar">🔑</div>
        <div class="main">
          <div class="title">${esc(r.manager_label)}</div>
          <div class="sub">თიმი: ${esc(r.team)}${r.manager_name ? " · " + esc(r.manager_name) : ""}</div>
          ${_MH_DELIVERY_LABELS[r.delivery] ? `<div class="sub">${_MH_DELIVERY_LABELS[r.delivery]}</div>` : ""}
        </div>
      </div>`).join("") : `<div class="empty">ანგარიში ჯერ არ არის მიბმული</div>`;

  box.innerHTML = `
    <h3>⚙️ MyHome ანგარიშები<button class="close" id="modalClose">✕</button></h3>
    ${list}
    <h3 style="margin-top:14px">➕ ახალი ანგარიში / განახლება</h3>
    <div class="sub" style="white-space:normal;margin-bottom:6px">
      🔒 ელფოსტა და პაროლი სერვერზე არ ინახება — worker მათ რამდენიმე წამში იღებს და მხოლოდ საკუთარ კომპიუტერზე წერს.
      არსებულ იარლიყს თუ მიუთითებთ — ის განახლდება (მაგ. პაროლის შესაცვლელად).
    </div>
    <div class="qa-compose">
      <input id="mhaTeam" list="mhaTeams" placeholder="თიმი (რომელი თიმი გამოიყენებს)" autocomplete="off">
      <datalist id="mhaTeams">${(data.teams || []).map((t) => `<option value="${esc(t)}">`).join("")}</datalist>
      <input id="mhaLabel" placeholder="იარლიყი (მაგ. nino-account — პატარა ლათინური, ციფრი, ტირე)" autocomplete="off" autocapitalize="off">
      <input id="mhaName" placeholder="მენეჯერის სახელი (ჩვენებისთვის)" autocomplete="off">
      <input id="mhaEmail" type="email" placeholder="MyHome ელფოსტა" autocomplete="off" autocapitalize="off">
      <input id="mhaPassword" type="password" placeholder="MyHome პაროლი" autocomplete="new-password">
      <input id="mhaContactName" placeholder="საკონტაქტო სახელი (განცხადებაზე)" autocomplete="off">
      <input id="mhaContactNumber" type="tel" inputmode="tel" placeholder="საკონტაქტო ნომერი (განცხადებაზე)" autocomplete="off">
      <button class="btn" id="mhaSave">💾 შენახვა</button>
      <div class="sub" id="mhaStatus" style="white-space:normal"></div>
    </div>`;
  document.getElementById("modalClose").onclick = closeDetail;

  // არსებულ იარლიყზე დაჭერა ავსებს იარლიყს/თიმს/სახელს (პაროლის შესაცვლელად)
  box.querySelectorAll("[data-mh-acc]").forEach((el) => {
    el.onclick = () => {
      document.getElementById("mhaLabel").value = el.dataset.mhAcc || "";
      document.getElementById("mhaTeam").value = el.dataset.mhTeam || "";
      document.getElementById("mhaName").value = el.dataset.mhName || "";
      document.getElementById("mhaEmail").focus();
    };
  });

  document.getElementById("mhaSave").onclick = async () => {
    const val = (id) => (document.getElementById(id).value || "").trim();
    const payload = {
      team: val("mhaTeam"),
      manager_label: val("mhaLabel").toLowerCase(),
      manager_name: val("mhaName"),
      email: val("mhaEmail"),
      password: document.getElementById("mhaPassword").value || "",
      contact_name: val("mhaContactName"),
      contact_number: val("mhaContactNumber"),
    };
    if (!payload.team || !payload.manager_label) { toast("შეიყვანეთ თიმი და იარლიყი"); return; }
    const btn = document.getElementById("mhaSave");
    const statusEl = document.getElementById("mhaStatus");
    btn.disabled = true;
    try {
      const res = await api("/api/myhome-accounts", { method: "POST", body: JSON.stringify(payload) });
      // პაროლი ფორმიდან მაშინვე ვშლით (არც state-ში ვინახავთ)
      document.getElementById("mhaPassword").value = "";
      document.getElementById("mhaEmail").value = "";
      if (res.delivery !== "pending") {
        statusEl.textContent = "✅ შენახულია (თიმი მიბმულია იარლიყზე). ელფოსტა/პაროლი არ გაგიგზავნიათ.";
        btn.disabled = false;
        return;
      }
      statusEl.textContent = "⏳ ველოდები worker-ს…";
      let delivered = false;
      for (let i = 0; i < 25 && !delivered; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        try {
          const st = await api("/api/myhome-accounts/status?label=" + encodeURIComponent(payload.manager_label));
          delivered = st.status === "delivered";
          if (st.status === "none") break;
        } catch (e) { break; }
      }
      statusEl.textContent = delivered
        ? "✅ worker-მა მიიღო — ანგარიში მზადაა (შემდეგი ამ თიმის განცხადება უკვე ამ ანგარიშით გამოქვეყნდება)."
        : "⚠️ worker-მა ჯერ ვერ მიიღო (კომპიუტერი გამორთულია/გაჩერებულია?). მონაცემები სერვერზე 15 წუთს დარჩება; ამის შემდეგ თავიდან შეიყვანეთ.";
      btn.disabled = false;
    } catch (e) {
      toast(e.message || "შეცდომა");
      btn.disabled = false;
    }
  };
}

function renderMyHomeJobs(rows, role) {
  const compose = `
    <div class="card">
      <h2>🏘️ MyHome ლისტინგის დამატება</h2>
      <div class="qa-compose">
        <select id="mhSource" title="საიდან ავიღოთ განცხადება">
          <option value="myhome">📥 წყარო: MyHome-ის განცხადება (ID)</option>
          <option value="ssge">📥 წყარო: ss.ge-ს განცხადება (ID ან ბმული)</option>
        </select>
        <select id="mhTarget" title="სად დავდოთ">
          <option value="myhome">📤 დადება: მხოლოდ MyHome-ზე</option>
          <option value="ssge">📤 დადება: მხოლოდ ss.ge-ზე</option>
          <option value="both">📤 დადება: MyHome-ზეც და ss.ge-ზეც</option>
        </select>
        <input id="mhListingId" type="text" inputmode="numeric" placeholder="MyHome ID (მაგ. 20134412)">
        <input id="mhOwnerNumber" type="text" inputmode="tel" placeholder="მესაკუთრის ნომერი (სავალდებულო)">
        <input id="mhPercent" type="text" inputmode="decimal" placeholder="თანამშრომლობის საკომისიო % — გადავა ბაზაში (არასავალდებულო)">
        <input id="mhPrice" type="text" inputmode="decimal" placeholder="საბოლოო ფასი (არასავალდებულო)">
        <textarea id="mhNotes" placeholder="შეზღუდვები / შენიშვნა — გადავა ბაზაში (არასავალდებულო). ss.ge-ზე დადებისას: თუ განცხადების მისამართს სახლის ნომერი არ აქვს, ჩაიწერება „2“ (სხვა ნომრისთვის დაწერეთ აქ „სახლი: 12“)"></textarea>
        <label style="display:flex;align-items:center;gap:8px"><input id="mhNoPets" type="checkbox" style="width:auto"> 🐾 მესაკუთრე ცხოველებს არ უშვებს</label>
        <button class="btn" id="mhSubmit">დამატება</button>
      </div>
    </div>`;

  const s = state.mhSearch;
  const searchBar = `
    <div class="card">
      <h2>🔎 ძებნა ყველა კოლეგაში</h2>
      <div class="qa-compose">
        <input id="mhSearchQ" type="text" placeholder="მისამართი, MyHome ID, აგენტის სახელი..." value="${esc(s.q)}">
        <select id="mhSearchDealType">
          <option value="">ყველა გარიგება</option>
          <option value="იყიდება" ${s.dealType === "იყიდება" ? "selected" : ""}>იყიდება</option>
          <option value="ქირავდება" ${s.dealType === "ქირავდება" ? "selected" : ""}>ქირავდება</option>
        </select>
        <select id="mhSearchStatus">
          <option value="">ყველა სტატუსი</option>
          <option value="QUEUED" ${s.status === "QUEUED" ? "selected" : ""}>⏳ რიგშია</option>
          <option value="PROCESSING" ${s.status === "PROCESSING" ? "selected" : ""}>⚙️ მუშავდება</option>
          <option value="COMPLETED" ${s.status === "COMPLETED" ? "selected" : ""}>✅ დადებულია</option>
          <option value="FAILED" ${s.status === "FAILED" ? "selected" : ""}>❌ ჩავარდა</option>
        </select>
        <input id="mhSearchFrom" type="date" value="${esc(s.dateFrom)}">
        <input id="mhSearchTo" type="date" value="${esc(s.dateTo)}">
        <button class="btn" id="mhSearchBtn">ძებნა</button>
        ${mhSearchResults !== null ? `<button class="btn" id="mhSearchClear">✕ გასუფთავება</button>` : ""}
      </div>
    </div>`;

  const baseRows = mhSearchResults !== null ? mhSearchResults : rows;
  // სტატუსის ფილტრი ვრცელდება ჩვეულებრივ (არა-ძებნის) სიაზეც — ცალკე
  // API-ს გამოძახების გარეშე, იმავე მონაცემებზე კლიენტის მხარეს.
  const displayRows = s.status ? baseRows.filter((r) => r.status === s.status) : baseRows;
  mhRowsById = {};
  displayRows.forEach((r) => { mhRowsById[r.job_id] = r; });
  const showAgentName = mhSearchResults !== null || role !== "agent";
  const listTitle = mhSearchResults !== null
    ? "ძებნის შედეგი"
    : (role === "agent" ? "ჩემი დავალებები" : "MyHome დავალებები");
  const emptyText = mhSearchResults !== null
    ? "ვერაფერი მოიძებნა"
    : "ჯერ არცერთი MyHome ID არაა დამატებული";

  const list = !displayRows.length
    ? `<div class="card"><div class="empty">${emptyText}</div></div>`
    : `<div class="card">
        <h2>📋 ${listTitle} <span class="cnt">${displayRows.length}</span></h2>
        ${displayRows.map((r) => _renderMyHomeRow(r, showAgentName)).join("")}
        ${(mhSearchResults === null && state.mhTotal && state.mhTotal > rows.length)
          ? `<button class="btn secondary" id="mhMore" style="margin-top:8px">⬇️ მეტის ჩვენება (კიდევ ${state.mhTotal - rows.length})</button>` : ""}
      </div>`;
  return renderWorkerBadge(role) + renderMhAccountsButton(role) + compose + searchBar + list;
}

function bindMyHomeJobsActions() {
  const accBtn = document.getElementById("mhAccBtn");
  if (accBtn) accBtn.onclick = openMhAccountsModal;
  const moreBtn = document.getElementById("mhMore");
  if (moreBtn) moreBtn.onclick = async () => { state.mhLimit = (state.mhLimit || 150) + 150; delete lazyCache.myhomejobs; await renderContent(); };
  const retryBtn = document.getElementById("mhRetryBtn");
  if (retryBtn) retryBtn.onclick = runBulkRetry;
  const srcSel = document.getElementById("mhSource");
  if (srcSel) srcSel.onchange = () => {
    const inp = document.getElementById("mhListingId");
    if (inp) {
      inp.placeholder = srcSel.value === "ssge" ? "ss.ge ID ან ბმული (მაგ. 37071652)" : "MyHome ID (მაგ. 20134412)";
      inp.inputMode = srcSel.value === "ssge" ? "text" : "numeric";
    }
  };
  const btn = document.getElementById("mhSubmit");
  if (btn) {
    btn.onclick = async () => {
      const listingId = (document.getElementById("mhListingId").value || "").trim();
      const ownerNumber = (document.getElementById("mhOwnerNumber").value || "").trim();
      const percent = (document.getElementById("mhPercent").value || "").trim();
      const price = (document.getElementById("mhPrice").value || "").trim();
      // ცხოველების თიქი შენიშვნის ბოლოს ცალკე სტრიქონად იწერება — worker (tg_export.py)
      // აქედან ავსებს ბაზის "pets" სვეტს; სერვერის/ბაზის ცვლილება არ სჭირდება.
      const petsLine = "ცხოველები: " + (document.getElementById("mhNoPets").checked ? "არა" : "კი");
      const notes = [(document.getElementById("mhNotes").value || "").trim(), petsLine].filter(Boolean).join("\n");
      const listingSource = (document.getElementById("mhSource") || {}).value || "myhome";
      const publishTarget = (document.getElementById("mhTarget") || {}).value || "myhome";
      if (listingSource === "ssge") {
        if (!listingId || !/\d{7,9}/.test(listingId)) { toast("შეიყვანეთ სწორი ss.ge ID (ციფრები) ან განცხადების ბმული"); return; }
      } else if (!listingId || !/^\d+$/.test(listingId)) { toast("შეიყვანეთ სწორი MyHome ID (მხოლოდ ციფრები)"); return; }
      if (!ownerNumber) { toast("შეიყვანეთ მესაკუთრის ნომერი"); return; }
      btn.disabled = true;
      try {
        await api("/api/myhome-jobs", {
          method: "POST",
          body: JSON.stringify({
            myhome_listing_id: listingId,
            owner_number: ownerNumber,
            cooperation_percent: percent,
            final_price: price,
            notes,
            listing_source: listingSource,
            publish_target: publishTarget,
          }),
        });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("დაემატა რიგში ✅");
        delete lazyCache.myhomejobs;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  }

  const searchBtn = document.getElementById("mhSearchBtn");
  if (searchBtn) {
    searchBtn.onclick = async () => {
      state.mhSearch = {
        q: (document.getElementById("mhSearchQ").value || "").trim(),
        dealType: document.getElementById("mhSearchDealType").value,
        status: document.getElementById("mhSearchStatus").value,
        dateFrom: document.getElementById("mhSearchFrom").value,
        dateTo: document.getElementById("mhSearchTo").value,
      };
      searchBtn.disabled = true;
      try {
        const s = state.mhSearch;
        const params = [];
        if (s.q) params.push("q=" + encodeURIComponent(s.q));
        if (s.dealType) params.push("deal_type=" + encodeURIComponent(s.dealType));
        if (s.status) params.push("status=" + encodeURIComponent(s.status));
        if (s.dateFrom) params.push("date_from=" + encodeURIComponent(s.dateFrom));
        if (s.dateTo) params.push("date_to=" + encodeURIComponent(s.dateTo));
        const resp = await api("/api/myhome-jobs/search" + (params.length ? "?" + params.join("&") : ""));
        mhSearchResults = resp.rows || [];
        await renderContent();
      } catch (e) { toast(e.message); searchBtn.disabled = false; }
    };
  }

  const clearBtn = document.getElementById("mhSearchClear");
  if (clearBtn) {
    clearBtn.onclick = async () => {
      mhSearchResults = null;
      state.mhSearch = { q: "", dealType: "", status: "", dateFrom: "", dateTo: "" };
      await renderContent();
    };
  }

  // სტატუსის dropdown-ის ცვლილება მაშინვე ფილტრავს უკვე ჩატვირთულ სიას
  // (ცალკე API-ს გამოძახების გარეშე) — ჩვეულებრივ, არა-ძებნის რეჟიმში.
  const statusSel = document.getElementById("mhSearchStatus");
  if (statusSel) {
    statusSel.onchange = () => {
      state.mhSearch = { ...state.mhSearch, status: statusSel.value };
      renderContent();
    };
  }

  document.querySelectorAll("[data-mh-row]").forEach((rowEl) => {
    rowEl.onclick = (e) => {
      if (e.target.closest("[data-mh-retry]")) return; // retry ღილაკზე დაჭერა ცალკე იმართება
      _openMyHomeDetail(rowEl.dataset.mhRow);
    };
  });
  document.querySelectorAll("[data-mh-retry]").forEach((retryBtn) => {
    retryBtn.onclick = (e) => {
      e.stopPropagation();
      _mhRetryJob(retryBtn.dataset.mhRetry, retryBtn);
    };
  });
}

/* ------------------------------------------- MyHome სტატისტიკა (მენეჯერი/ადმინი) */

function renderMyHomeStats(rows) {
  if (!state.mhStatsFrom) state.mhStatsFrom = "";
  if (!state.mhStatsTo) state.mhStatsTo = "";
  const filterBar = `
    <div class="card">
      <h2>📊 MyHome სტატისტიკა</h2>
      <div class="qa-compose">
        <input id="mhStatsFrom" type="date" value="${esc(state.mhStatsFrom)}">
        <input id="mhStatsTo" type="date" value="${esc(state.mhStatsTo)}">
        <button class="btn" id="mhStatsFilterBtn">გაფილტვრა</button>
      </div>
    </div>`;

  if (!rows.length) {
    return filterBar + `<div class="card"><div class="empty">ამ პერიოდში მონაცემები არ არის</div></div>`;
  }

  const totals = rows.reduce((acc, r) => {
    acc.total += r.total; acc.completed += r.completed; acc.failed += r.failed;
    acc.processing += r.processing; acc.queued += r.queued;
    return acc;
  }, { total: 0, completed: 0, failed: 0, processing: 0, queued: 0 });

  const summary = `
    <div class="card">
      <h2>ჯამური მაჩვენებლები</h2>
      <div class="sub">სულ: <b>${totals.total}</b> · ✅ ${totals.completed} · ❌ ${totals.failed} · ⚙️ ${totals.processing} · ⏳ ${totals.queued}</div>
    </div>`;

  const list = `
    <div class="card">
      <h2>თითო აგენტზე</h2>
      ${rows.map((r) => `
        <div class="list-row">
          <div class="avatar">👤</div>
          <div class="main">
            <div class="title">${esc(r.agent_name)}${r.team ? " · " + esc(r.team) : ""}</div>
            <div class="sub">სულ: <b>${r.total}</b> · ✅ ${r.completed} · ❌ ${r.failed} · ⚙️ ${r.processing} · ⏳ ${r.queued}</div>
          </div>
        </div>`).join("")}
    </div>`;

  return filterBar + summary + list;
}

function bindMyHomeStatsActions() {
  const btn = document.getElementById("mhStatsFilterBtn");
  if (!btn) return;
  btn.onclick = async () => {
    state.mhStatsFrom = document.getElementById("mhStatsFrom").value;
    state.mhStatsTo = document.getElementById("mhStatsTo").value;
    delete lazyCache.myhomestats;
    await renderContent();
  };
}

/* ------------------------------------------------ აგენტის დამატება/
   გათავისუფლების მოთხოვნები (მენეჯერი ითხოვს, ადმინი ამტკიცებს) */
const AGENT_REQUEST_STATUS_LABEL = { pending: "⏳ მოლოდინში", approved: "✅ დამტკიცებული", rejected: "❌ უარყოფილი" };
const AGENT_REQUEST_KIND_LABEL = { add: "➕ დამატება", remove: "➖ გათავისუფლება" };
let arKind = "add";

function renderAgentRequests(payload) {
  const rows = (payload && payload.rows) || [];
  const teamsDirectory = (payload && payload.teams) || [];
  const isTeamLead = state.role === "admin" && state.data && state.data.is_team_lead;
  const isAdmin = state.role === "admin" && !isTeamLead;
  // თიმლიდერს საკუთარი გუნდის აგენტების სია მოსდის უკვე ჩატვირთული
  // დაშბორდიდან (state.data.admin.team ისედაც მისივე გუნდზეა
  // გაფილტრული); ადმინს — მთელი კომპანიის როსტერი (იმავე ველიდან,
  // რადგან ადმინისთვის ეს ველი არ ფილტრდება არცერთ გუნდზე).
  const rosterAgents = ((state.data && state.data.admin && state.data.admin.team) || [])
    .filter((a) => a.role !== "team_lead");

  const teamPicker = isAdmin ? `<select id="arTeamSelect" style="margin-top:8px">
      <option value="">დამოუკიდებელი (გუნდის გარეშე)</option>
      ${teamsDirectory.map((t) => `<option value="${esc(t.team)}">${esc(t.name)}-ის გუნდი</option>`).join("")}
    </select>` : "";

  const form = `<div class="card">
    <h2>📥 ${isAdmin ? "ახალი მოთხოვნა" : "ახალი მოთხოვნა ადმინთან"}</h2>
    ${isTeamLead ? `<div class="sub" style="margin-bottom:8px">აქედან სთხოვთ ადმინს ახალი აგენტის დამატებას თქვენს გუნდში, ან არსებულის გათავისუფლებას — ის ქვემოთ, „მოთხოვნების ისტორიაში", დაადასტურებს ან უარყოფს.</div>` : ""}
    <div class="period-switch" id="arKindSwitch">
      <button data-kind="add" class="${arKind === "add" ? "active" : ""}">აგენტის მოწვევა</button>
      <button data-kind="remove" class="${arKind === "remove" ? "active" : ""}">აგენტის გათავისუფლება</button>
    </div>
    <div class="qa-compose" data-ar-fields="add" ${arKind === "add" ? "" : "hidden"} style="margin-top:10px">
      <input id="arName" placeholder="ახალი აგენტის სახელი" />
      <input id="arPhone" placeholder="ტელეფონის ნომერი" />
      ${teamPicker}
    </div>
    <div class="qa-compose" data-ar-fields="remove" ${arKind === "remove" ? "" : "hidden"} style="margin-top:10px">
      <select id="arTargetAgent">
        <option value="">აირჩიეთ აგენტი…</option>
        ${rosterAgents.map((a) => `<option value="${esc(a.agent_id)}">${esc(a.name)}${a.team ? " (" + esc(a.team) + ")" : ""}</option>`).join("")}
      </select>
    </div>
    <div class="qa-compose" style="margin-top:8px">
      <textarea id="arReason" placeholder="მიზეზი (არასავალდებულო)"></textarea>
    </div>
    <button class="btn" id="arSubmit" style="margin-top:8px">გაგზავნა</button>
  </div>`;

  const listHtml = `<div class="card">
    <h2>📋 მოთხოვნების ისტორია <span class="cnt">${rows.length}</span></h2>
    ${!rows.length ? `<div class="empty">მოთხოვნა ჯერ არ არის</div>` :
      rows.map((r) => `
      <div class="list-row">
        <div class="avatar">${r.kind === "add" ? "➕" : "➖"}</div>
        <div class="main">
          <div class="title">${esc(AGENT_REQUEST_KIND_LABEL[r.kind] || r.kind)} — ${esc(r.name || r.target_agent_id || "")}</div>
          <div class="sub">მოითხოვა: ${esc(r.requested_by_name || "ადმინმა")}${r.team ? " · " + esc(r.team) : ""}</div>
          ${r.reason ? `<div class="sub">${esc(r.reason)}</div>` : ""}
          <div class="sub">${esc((r.created_at || "").split(" ")[0] || "")} · ${esc(AGENT_REQUEST_STATUS_LABEL[r.status] || r.status)}</div>
        </div>
      </div>
      ${r.status === "pending" && isAdmin ? `<div class="actions" style="margin:-2px 0 12px">
        <button class="btn" data-reqact="approved" data-id="${esc(r.request_id)}">✅ დამტკიცება</button>
        <button class="btn danger" data-reqact="rejected" data-id="${esc(r.request_id)}">✖️ უარყოფა</button>
      </div>` : ""}`).join("")}
  </div>`;

  return form + listHtml;
}

function bindAgentRequestsActions() {
  const kindSwitch = document.getElementById("arKindSwitch");
  if (kindSwitch) {
    kindSwitch.querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        arKind = b.dataset.kind;
        kindSwitch.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
        document.querySelectorAll("[data-ar-fields]").forEach((el) => {
          el.hidden = el.dataset.arFields !== arKind;
        });
      };
    });
  }
  const submitBtn = document.getElementById("arSubmit");
  if (submitBtn) {
    submitBtn.onclick = async () => {
      const body = { kind: arKind, reason: (document.getElementById("arReason").value || "").trim() };
      if (arKind === "add") {
        const name = (document.getElementById("arName").value || "").trim();
        if (!name) { toast("შეიყვანეთ სახელი"); return; }
        body.name = name;
        body.phone = (document.getElementById("arPhone").value || "").trim();
        const teamSel = document.getElementById("arTeamSelect");
        if (teamSel) body.team = teamSel.value || "";
      } else {
        const targetId = document.getElementById("arTargetAgent").value;
        if (!targetId) { toast("აირჩიეთ აგენტი"); return; }
        body.target_agent_id = targetId;
      }
      submitBtn.disabled = true;
      try {
        await api("/api/agent-requests", { method: "POST", body: JSON.stringify(body) });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("მოთხოვნა გაგზავნილია ✅");
        delete lazyCache.agentrequests;
        await renderContent();
      } catch (e) { toast(e.message); submitBtn.disabled = false; }
    };
  }
  document.querySelectorAll("[data-reqact]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api("/api/agent-requests/decide", {
          method: "POST",
          body: JSON.stringify({ request_id: btn.dataset.id, status: btn.dataset.reqact }),
        });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast(btn.dataset.reqact === "approved" ? "დამტკიცდა ✅" : "უარყოფილია");
        delete lazyCache.agentrequests;
        await renderContent();
      } catch (e) { toast(e.message); btn.disabled = false; }
    };
  });
}

/* ------------------------------------------------ რეგულაციები/ინსტრუქცია
   (item 3, გაფართოებული item 10-ის თხოვნით — მეტი დეტალი და ვიზუალური
   დატვირთვა) — კომპანიის რეგულაციები კატეგორიებად (თავდაპირველი,
   ადმინის მიერ მომავალში დასარედაქტირებელი ვერსია — საიტზე ცალკე
   გამოქვეყნებული ტექსტი ვერ მოიძებნა ავტომატურად) + ბოტის სრული
   გამოყენების ინსტრუქცია კატეგორიებად, ცალ-ცალკე აგენტისთვის და
   მენეჯერისთვის (ბოტის რეალურ ბრძანებებზე დაყრდნობით), პლუს
   ცოცხალი (server-იდან წამოსული, არა ტექსტში ჩაწერილი) ლიმიტების
   ცხრილი. */
const REGULATION_GROUPS = [
  { icon: "🗣️", title: "კომუნიკაცია და პროფესიონალიზმი", items: [
    { title: "კლიენტთან კომუნიკაცია",
      detail: "კომუნიკაცია კლიენტთან ყოველთვის თავაზიანი, სწრაფი და პროფესიულია. ზარზე/მიმოწერაზე პასუხი გონივრულ ვადაში (იდეალურად — რამდენიმე საათში) აუცილებელია, თუნდაც უარყოფითი პასუხის მისატანად. კომპანიის სახელით საუბრისას აგენტი წარმოადგენს მთელ ბრენდს." },
    { title: "კოლეგებთან ურთიერთობა",
      detail: "კოლეგებთან ურთიერთობაშიც კორექტულობა და ურთიერთდახმარებაა მოსალოდნელი — ერთი კლიენტის ორმა აგენტმა რომ არ „მოინადირონ“ ერთმანეთის ხელიდან, ამისთვისვე არსებობს ექსკლუზივის გაზიარების ფუნქცია (იხ. „კონფიდენციალურობა“)." },
  ] },
  { icon: "📊", title: "დღიური გეგმა და ანგარიშგება", items: [
    { title: "დღიური განცხადებების გეგმა",
      detail: "ოფისის ცვლაზე გეგმა იზომება საიტზე/myhome-ზე/ss.ge-ზე ატვირთული განცხადებებით ცალ-ცალკე (საიტისა და myhome-ის ჯამი არ იკრიბება — ერთი და იგივე განცხადება ორივეგან იტვირთება ერთდროულად), ონლაინ დღეზე კი — საერთო რაოდენობით. გეგმის შეუსრულებლობა ავტომატურად აღირიცხება „quota_missed“ გაფრთხილებად /clockout-ის დროს." },
    { title: "კლიენტის ანგარიში სავალდებულოა",
      detail: "თუ დღეს კონკრეტული კლიენტი გქონდათ მინიჭებული (მენეჯერისგან), დღის დახურვისას (/clockout ან Mini App) ანგარიშის შევსება — რა შესრულდა, რა დეტალები — სავალდებულოა და აღარ შეიძლება გამოტოვება. ეს პირდაპირ მოქმედებს KPI-ის სისწორეზე." },
    { title: "შეხვედრის ფიქსაცია",
      detail: "შეხვედრაზე ყოფნისას /meeting-ით (ან Mini App-იდან) ფიქსირდება მისამართი, მეპატრონის საკონტაქტო და გარიგების პირობები — ეს მონაცემი მერე მენეჯერსაც და დირექტორსაც უჩანს „შეხვედრების“ ისტორიაში." },
  ] },
  { icon: "🕐", title: "დასწრება და სამუშაო დღე", items: [
    { title: "დღის დაწყება/დასრულება",
      detail: "სამუშაო დღის დაწყება/დასრულება ბოტში (/clockin, /clockout) ან Mini App-ის „დღეს“ ტაბიდან აღინიშნება — არარეგისტრირებული დღე არ ითვლება ნამუშევრად, თუნდაც ფაქტობრივად ნამუშევარი იყოს. ოფისის ცვლაზე დაგვიანება (grace-პერიოდის მეტ ხანს) ავტომატურ გაფრთხილებას იწვევს." },
    { title: "ცვლის გაცვლა",
      detail: "ცვლის ტიპის შეცვლა (მაგ. დღეს სახლიდან მუშაობა ჩვეულებრივი ოფისის ცვლის ნაცვლად) წინასწარ, /swapshift-ით ხდება და საბოლოოდ მენეჯერის დამტკიცებას საჭიროებს — თვეში შეზღუდული რაოდენობით." },
  ] },
  { icon: "🏖️", title: "დასვენების დღეები", items: [
    { title: "დასვენების მოთხოვნა",
      detail: "დასვენების დღე წინასწარ, /dayoff ბრძანებით ან Mini App-იდან მოთხოვნილია — დამტკიცებამდე დასვენება არ ითვლება ოფიციალურად და ჩვეულებრივ სამუშაო დღედ ითვლება, სანამ არ დამტკიცდება." },
    { title: "დამტკიცების უფლება და თვიური ჭერი",
      detail: "დამტკიცება/უარყოფა შეუძლია ადმინს (ყველაზე), ან საკუთარი გუნდის ფარგლებში — მენეჯერს. თვეში დასაშვები დამტკიცებული დღეოფების რაოდენობას ჭერი აქვს (იხ. ზემოთ „მოქმედი ლიმიტები“) — ჭერს გადაცილებული მოთხოვნა ავტომატურად ითიშება, თუნდაც მენეჯერს სურდეს დამტკიცება." },
  ] },
  { icon: "🔒", title: "კონფიდენციალურობა", items: [
    { title: "ექსკლუზივის ინფორმაცია",
      detail: "ექსკლუზივის (მეპატრონის საკონტაქტო, ფასი/პირობები, საკადასტრო კოდი) ინფორმაცია მკაცრად კონფიდენციალურია — მხოლოდ პასუხისმგებელი აგენტისა და მენეჯმენტისთვის." },
    { title: "გაზიარების წესი",
      detail: "კოლეგისთვის ექსკლუზივზე ინფორმაცია მხოლოდ Mini App-ის „გაზიარების“ ფუნქციით ნაწილდება (თანამშრომლობის აღრიცხვითურთ), არასდროს პირდაპირ სკრინშოთით/ზეპირად — ასე ჩანს ვინ ვისთან ითანამშრომლა, საკომისიოს სამართლიანი დანაწილებისთვისაც." },
  ] },
  { icon: "⚠️", title: "დისციპლინა", items: [
    { title: "გაფრთხილება და ავტომატური გათიშვა",
      detail: "განმეორებითი გაფრთხილება (დაგვიანება, გამოტოვებული რეპორტი, არ-გამოცხადება, შეუსრულებელი დღიური გეგმა) აღირიცხება. დაწესებულ ლიმიტს მიღწევისას (იხ. „მოქმედი ლიმიტები“) აგენტის ანგარიში ავტომატურად ითიშება — ხელახლა გააქტიურება მხოლოდ ადმინს შეუძლია." },
    { title: "გაფრთხილების გაუქმების მოთხოვნა",
      detail: "თუ გაფრთხილება უსამართლოდ ჩანს (მაგ. ამ დროს აგენტი შეხვედრაზე იყო) — მენეჯერს შეუძლია „გაფრთხილებები“ ტაბიდან კონკრეტულ გაფრთხილებაზე დაწეროს გაუქმების მოთხოვნა მიზეზის მითითებით. საბოლოო გადაწყვეტილებას მხოლოდ დირექტორი იღებს, და აგენტიც, და მომთხოვნი მენეჯერიც იღებენ შეტყობინებას შედეგზე." },
  ] },
];

const AGENT_BOT_COMMAND_GROUPS = [
  { icon: "ℹ️", title: "ზოგადი", items: [
    ["/start", "რეგისტრაცია ბოტში", "პირველი გაშვებისას საჭირო ბრძანება — აგენტს ბოტში რეგისტრირებს და აძლევს წვდომას ყველა დანარჩენ ფუნქციაზე. თუ უკვე რეგისტრირებული ხართ, ხელახლა გაშვება უვნებელია."],
    ["/app", "Mini App-ის (ვიზუალური დაშბორდის) გახსნა", "ხსნის ვიზუალურ დაშბორდს, სადაც ერთ სივრცეშია დღევანდელი მდგომარეობა, დავალებები, KPI, გრაფიკი და ა.შ. — უმეტესი ყოველდღიური მოქმედება აქედან კეთდება ბრძანებების ნაცვლად."],
    ["/cancel", "მიმდინარე ნაბიჯოვანი ბრძანების გაუქმება", "თუ რომელიმე მრავალნაბიჯოვანი ბრძანება (მაგ. /newtask, /addexclusive) შუაში გაგიჭირდათ ან შეცდომით დაიწყეთ — /cancel წყვეტს მას და ბოტს საწყის მდგომარეობაში აბრუნებს."],
  ] },
  { icon: "🕐", title: "ყოველდღიური სამუშაო", items: [
    ["/clockin", "სამუშაო დღის დაწყება (+ მდებარეობა)", "აღნიშნავს დღის დაწყების ზუსტ დროს. თუ ოფისის GPS ვერიფიკაცია ჩართულია, ბოტი ითხოვს მდებარეობას (ღილაკი „📍 მდებარეობის გაგზავნა“) — მხოლოდ დაწყების მომენტში, ფონური თვალყურის გარეშე. ოფისის ცვლაზე დაგვიანებით დაწყება ავტომატურ გაფრთხილებას წარმოშობს; დამტკიცებულ დასვენების დღეს გაფრთხილება არ იწერება."],
    ["/attendance", "დღევანდელი დასწრება", "აჩვენებს დღევანდელ დაწყების/დასრულების დროს, ნამუშევარ საათებს და ლოკაციის სტატუსს (ოფისში/ოფისის გარეთ). მენეჯერს/ადმინს — გუნდის დღევანდელ შეჯამებას."],
    ["/clockout", "სამუშაო დღის დასრულება — განცხადებების რაოდენობა + კლიენტის რეპორტი", "დღის ბოლოს გამოსაყენებელია: ოფისის ცვლაზე ითხოვს საიტისა და ss.ge-ის რიცხვებს (MyHome-ის რაოდენობა ავტომატურად ითვლება რეალურად დადებული განცხადებებიდან), ხოლო თუ დღეს კონკრეტული კლიენტი გქონდათ მინიჭებული — სავალდებულოდ ითხოვს იმ კლიენტის ანგარიშსაც (რა შესრულდა, დეტალები, სურათებიც კი). ეს უკანასკნელი აღარ იტოვება გამოტოვებას."],
    ["/mytasks", "ჩემი მიმდინარე დავალებების ნახვა", "აჩვენებს ყველა დავალებას, რომელიც ამჟამად თქვენზეა მინიჭებული და ჯერ არაა დასრულებული."],
    ["/done (task_id)", "დავალების დასრულებულად მონიშვნა", "კონკრეტული task_id-ის მითითებით დავალებას სრულდება-ს სტატუსში გადაჰყავს — task_id ჩანს /mytasks-ის სიაში."],
  ] },
  { icon: "📝", title: "რეპორტები და შეხვედრები", items: [
    ["/clientreport", "კლიენტთან მუშაობის რეპორტის ცალკე შევსება", "საშუალებას იძლევა კლიენტის რეპორტი შეავსოთ დღის განმავლობაში ნებისმიერ დროს, არა მხოლოდ /clockout-ის დროს — მაგალითად, თუ რამდენიმე კლიენტთან გქონდათ საქმე."],
    ["/meeting", "შეხვედრის დაფიქსირება", "შეხვედრაზე ყოფნისას ფიქსირდება მისამართი, მეპატრონის საკონტაქტო და გარიგების პირობები — ეს ავტომატურად ითვლება საპატიო მიზეზად და მენეჯერსაც/დირექტორსაც უჩანს „შეხვედრების“ ისტორიაში, ასე რომ დღიური გეგმის შეუსრულებლობის დროს ეს კონტექსტი ჩანს."],
  ] },
  { icon: "🏖️", title: "დასვენება და გრაფიკი", items: [
    ["/dayoff", "დასვენების დღის მოთხოვნა", "თარიღის მითითებით იგზავნება მოთხოვნა მენეჯერთან/ადმინთან დასამტკიცებლად — დამტკიცებამდე დღე ჩვეულებრივ სამუშაო დღედ ითვლება. თვეში დამტკიცებული დღეოფების რაოდენობას ჭერი აქვს."],
    ["/myschedule", "საკუთარი კვირის გრაფიკის ნახვა", "აჩვენებს კვირის განმავლობაში დაგეგმილ ცვლებს (ოფისი/ონლაინ/დასვენება) დღეების მიხედვით."],
    ["/swapshift", "სამუშაო ცვლის გაცვლის მოთხოვნა (თვეში შეზღუდული რაოდენობა)", "თუ კონკრეტულ დღეს გინდათ ცვლის ტიპის შეცვლა (მაგ. ოფისის ნაცვლად ონლაინ) — მოთხოვნა წინასწარ იგზავნება და მენეჯერის დამტკიცებას საჭიროებს. თვეში დასაშვები რაოდენობა შეზღუდულია."],
    ["/swapnumber", "შიდა სამუშაო ნომრის გაცვლა კოლეგასთან", "საშუალებას იძლევა ორმა აგენტმა ურთიერთშეთანხმებით გაცვალონ შიდა სამუშაო ნომრები (მაგ. კლიენტებთან ურთიერთობისთვის გამოყოფილი ნომერი)."],
  ] },
  { icon: "🏘️", title: "ექსკლუზივები", items: [
    ["/addexclusive", "ახალი ექსკლუზივის დამატება", "ამატებს ახალ ექსკლუზივს თქვენს სახელზე — მისამართი, მეპატრონის საკონტაქტო, ფასი/პირობები. ეს ინფორმაცია მკაცრად კონფიდენციალურია."],
    ["/exclusives", "აქტიური ექსკლუზივების სია", "აჩვენებს ყველა ექსკლუზივს, რომელიც ამჟამად თქვენზეა რეგისტრირებული."],
  ] },
];

const ADMIN_ONLY_BOT_COMMAND_GROUPS = [
  { icon: "👑", title: "პერსონალის მართვა", items: [
    ["/addagent", "ახალი აგენტის დამატება (ან Mini App-ის „აგენტების მართვა“/„მოთხოვნები“)", "ამატებს ახალ აგენტს სისტემაში (სახელი, გვარი, გუნდი, სამუშაო რეჟიმი). იგივეს აკეთებს Mini App-ის „აგენტების მართვა“ ტაბიც, ვიზუალურად."],
    ["/agents", "ყველა აგენტის სია", "აჩვენებს ყველა რეგისტრირებულ (აქტიურ და გათავისუფლებულ) აგენტს."],
    ["/setrole", "თიმლიდერის დანიშვნა (agent_id team_lead)", "კონკრეტულ აგენტს ანიჭებს თიმლიდერის/მენეჯერის უფლებებს — ეს აძლევს წვდომას გუნდის მართვის ფუნქციებზე Mini App-ში."],
    ["/setteam", "აგენტის გუნდში ჩართვა ხელით", "ხელით ანაწილებს აგენტს კონკრეტულ გუნდში, თუ ავტომატური განაწილება საჭირო არაა."],
    ["/reactivate", "გათავისუფლებული აგენტის ხელახლა გააქტიურება", "აბრუნებს გათიშულ/გათავისუფლებულ აგენტს აქტიურ სტატუსში. საბოლოო, სამუდამო წაშლა (რომელიც აღარ დააბრუნებს) ცალკე, Mini App-ის „აგენტების მართვა“ ტაბიდან კეთდება."],
  ] },
  { icon: "📄", title: "დავალებები და ანგარიშები", items: [
    ["/newtask", "ახალი კლიენტის/დავალების დამატება", "ამატებს ახალ კლიენტს/დავალებას და გადასცემს კონკრეტულ აგენტს ან თავად თქვენს თავზე (მენეჯერს/დირექტორსაც შეუძლია საკუთარ თავზე დარეგისტრირება)."],
    ["/report", "დღიური ტექსტური ანგარიში", "აგზავნის მოკლე ტექსტურ შეჯამებას დღის მდგომარეობაზე."],
    ["/ranking", "შედეგების რეიტინგი", "აჩვენებს აგენტების რეიტინგს შედეგების მიხედვით, პერიოდის მითითებით."],
    ["/findclient", "კლიენტის ძებნა ტელეფონით (დავალება+რეპორტი+შეხვედრა)", "ტელეფონის ნომრით პოულობს კონკრეტულ კლიენტთან დაკავშირებულ სრულ ისტორიას — ვის გადაეცა, რა რეპორტები/შეხვედრები დაფიქსირდა. იგივეს, ვიზუალურად და უფრო დეტალურად, აკეთებს Mini App-ის ახალი „კლიენტები“ ტაბი."],
  ] },
  { icon: "🗓️", title: "დამტკიცებები", items: [
    ["/dayoffs", "დასადასტურებელი დღეოფების სია", "აჩვენებს ყველა მოლოდინში მყოფ დასვენების მოთხოვნას დასამტკიცებლად/უარსაყოფად."],
    ["/swaps", "დასადასტურებელი ცვლის გაცვლების სია", "აჩვენებს ყველა მოლოდინში მყოფ ცვლის გაცვლის მოთხოვნას."],
    ["/warnings", "ბოლო გაფრთხილებების სია", "აჩვენებს ბოლო გაფრთხილებებს და მათ სტატუსს (აქტიური/გაუქმებულია/გაუქმებას ითხოვს). გაუქმების მოთხოვნის შეტანა და საბოლოო გადაწყვეტილება Mini App-ის „გაფრთხილებები“ ტაბიდან ხდება."],
  ] },
];

/* მენეჯერის Mini App ტაბები — იგივე იკონები, რაც ADMIN_TABS-შია
   გამოყენებული, რომ ვიზუალურად ცალსახად ერთმანეთს ემთხვეოდეს. */
const MANAGER_MINIAPP_TABS = [
  ["🧑‍🤝‍🧑", "გუნდი", "საკუთარი გუნდის დღევანდელი მდგომარეობა, ვინ დაგვიანდა/არ დაუწყია"],
  ["📊", "მიმოხილვა / 🏆 რეიტინგი", "გუნდის შედეგები დღე/კვირა/თვის ჭრილში"],
  ["📥", "მოთხოვნები", "ახალი აგენტის მოწვევის ან არსებულის გათავისუფლების მოთხოვნა — საბოლოო დამტკიცება ადმინთანაა"],
  ["📝", "რეპორტები", "გუნდის რეპორტების ისტორია + ხარისხის შეფასება (1-5), თარიღით/პერიოდით ფილტრი"],
  ["🕘", "დასწრება", "გუნდის დღევანდელი დაწყება/დასრულება, ოფისში/გარეთ, დაგვიანება, საათები + ფილტრები და CSV ექსპორტი"],
  ["📍", "რაიონები", "ყოველკვირეული რაიონების განაწილება აგენტებზე (მულტი-არჩევა) — აგენტი ხედავს დაშბორდზე და იღებს შეტყობინებას"],
  ["🗓️", "შვებულებები", "გუნდის დღეოფის მოთხოვნების დამტკიცება/უარყოფა (თარიღით ფილტრი), პლუს ისტორია"],
  ["🔁", "სმენის გაცვლა", "გუნდის წევრებს შორის ცვლის გაცვლის მოთხოვნების გადაწყვეტა + ისტორია"],
  ["📄", "დავალებები", "ახალი კლიენტის დამატება და დავალების გუნდში გადაბარება"],
  ["🗞️", "დღის ამბები", "6 პუნქტიანი დღიური შეჯამება გუნდზე"],
  ["💬", "კითხვები", "აგენტების კითხვებზე პასუხის გაცემა"],
];

let _regDetailStore = [];

function _renderRegGroups(groups, isBotCommands) {
  return groups.map((g) => `<div class="card">
    <h2>${g.icon} ${esc(g.title)}</h2>
    ${g.items.map((item) => {
      let title, sub, detail;
      if (isBotCommands) {
        title = item[0];
        sub = item[1];
        detail = item[2] || item[1] || "";
      } else {
        title = item.title;
        sub = "";
        detail = item.detail || "";
      }
      const idx = _regDetailStore.length;
      _regDetailStore.push({ title, detail });
      return `<div class="list-row clickable" data-reg-idx="${idx}">
        <div class="avatar">${g.icon}</div>
        <div class="main"><div class="title">${esc(title)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>
      </div>`;
    }).join("")}
  </div>`).join("");
}

function bindRegulationsActions() {
  document.querySelectorAll("[data-reg-idx]").forEach((el) => {
    el.onclick = () => {
      const entry = _regDetailStore[parseInt(el.dataset.regIdx, 10)];
      if (!entry || !entry.detail) return;
      openDetail(entry.title, [], `<div class="sub" style="margin-top:10px;line-height:1.6;white-space:pre-line">${esc(entry.detail)}</div>`);
    };
  });
}

function renderRegulations(payload) {
  _regDetailStore = [];
  const limits = (payload && payload.limits) || {};
  const isTeamLead = state.role === "admin" && state.data && state.data.is_team_lead;
  const isAdminOnly = state.role === "admin" && !isTeamLead;

  const limitsCard = `<div class="card">
    <h2>🔢 მოქმედი ლიმიტები</h2>
    <div class="grid3">
      <div class="stat"><div class="num">${esc(limits.office_daily_quota != null ? limits.office_daily_quota : "-")}</div><div class="lbl">ოფისის დღიური გეგმა</div></div>
      <div class="stat"><div class="num">${esc(limits.online_daily_quota != null ? limits.online_daily_quota : "-")}</div><div class="lbl">ონლაინ დღიური გეგმა</div></div>
      <div class="stat"><div class="num">${esc(limits.dayoff_monthly_limit != null ? limits.dayoff_monthly_limit : "-")}</div><div class="lbl">დღეოფი / თვე</div></div>
      <div class="stat"><div class="num">${esc(limits.shift_swap_monthly_limit != null ? limits.shift_swap_monthly_limit : "-")}</div><div class="lbl">ცვლის გაცვლა / თვე</div></div>
      <div class="stat"><div class="num">${esc(limits.warning_limit != null ? limits.warning_limit : "-")}</div><div class="lbl">გაფრთხილება → გათიშვა (${esc(limits.warning_window_days || 30)} დღეში)</div></div>
      <div class="stat"><div class="num">${esc(limits.attendance_grace_minutes != null ? limits.attendance_grace_minutes : "-")} წთ</div><div class="lbl">დაგვიანების ზღვარი</div></div>
    </div>
  </div>`;

  const regsHtml = `<div class="card"><h2>📄 კომპანიის რეგულაციები</h2><div class="sub">ეს საწყისი ვერსიაა — ადმინს შეუძლია მოგვიანებით ზუსტი ტექსტით ჩანაცვლება.</div></div>` + _renderRegGroups(REGULATION_GROUPS, false);

  let guideHtml;
  if (isAdminOnly) {
    guideHtml = `<div class="card">
        <h2>📘 ბოტის სრული ინსტრუქცია — ადმინი (დირექტორი)</h2>
        <div class="sub">Mini App-ში ყველა ტაბი ხელმისაწვდომია, მენეჯერის ტაბების ჩათვლით. ბოტში კი, ჩვეულებრივი ბრძანებების გარდა, დამატებით გაქვთ:</div>
      </div>` + _renderRegGroups(ADMIN_ONLY_BOT_COMMAND_GROUPS, true) + _renderRegGroups(AGENT_BOT_COMMAND_GROUPS, true);
  } else if (isTeamLead) {
    guideHtml = `<div class="card">
        <h2>📘 ბოტის ინსტრუქცია — მენეჯერი</h2>
        <div class="sub">მენეჯერული მოქმედებები (გუნდის მართვა, რეპორტების შეფასება, დამტკიცებები) — მხოლოდ Mini App-იდან (/app):</div>
        ${MANAGER_MINIAPP_TABS.map(([icon, t, d]) => `<div class="list-row"><div class="avatar">${icon}</div><div class="main"><div class="title">${esc(t)}</div><div class="sub">${esc(d)}</div></div></div>`).join("")}
      </div>
      <div class="card">
        <h2>👤 საკუთარი, პირადი სამუშაო დღისთვის</h2>
        <div class="sub">იგივე ბრძანებები გაქვთ, რაც აგენტებს — თქვენც ხართ გუნდის წევრი:</div>
      </div>` + _renderRegGroups(AGENT_BOT_COMMAND_GROUPS, true);
  } else {
    guideHtml = `<div class="card"><h2>📘 ბოტის ინსტრუქცია — აგენტი</h2></div>` + _renderRegGroups(AGENT_BOT_COMMAND_GROUPS, true);
  }

  return limitsCard + regsHtml + guideHtml;
}

/* ============================================== v4.0 — ახალი ტაბები */

function todayIso() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function addDaysIso(iso, n) {
  const [y, m, d] = String(iso).split("-").map((x) => parseInt(x, 10));
  const dt = new Date(Date.UTC(y, (m || 1) - 1, d || 1));
  dt.setUTCDate(dt.getUTCDate() + n);
  return dt.toISOString().slice(0, 10);
}
function mapsLink(lat, lng) {
  if (lat === "" || lat == null || lng === "" || lng == null) return "";
  return `https://www.google.com/maps?q=${encodeURIComponent(lat)},${encodeURIComponent(lng)}`;
}
function openExternal(url) {
  if (tg && tg.openLink) tg.openLink(url); else window.open(url, "_blank");
}
const ATT_FIELDS = [
  ["agent_name", "თანამშრომელი"], ["date", "თარიღი"], ["check_in", "დაწყება"],
  ["check_in_distance", "დაშორება დაწყებისას (მ)"], ["check_in_accuracy", "სიზუსტე დაწყებისას (მ)"],
  ["check_out", "დასრულება"], ["check_out_distance", "დაშორება დასრულებისას (მ)"],
  ["check_out_accuracy", "სიზუსტე დასრულებისას (მ)"], ["hours_text", "ნამუშევარი დრო"], ["note", "შენიშვნა"],
];

/* ----- აგენტი: შვებულების მოთხოვნა (თარიღის არჩევით) ----- */
function renderMyDayoffs(p) {
  p = p || {};
  const rows = p.rows || [];
  const min = todayIso();
  return `<div class="card">
    <h2>🏖️ შვებულების/Day off მოთხოვნა</h2>
    <div class="sub" style="margin-bottom:8px">ამ თვეში დამტკიცებული: ${esc(p.approved_this_month || 0)} / ${esc(p.monthly_limit || 3)}</div>
    <div class="qa-compose">
      <input type="date" id="doDate" min="${min}" value="${min}" />
      <textarea id="doReason" rows="2" maxlength="500" placeholder="მიზეზი (არასავალდებულო)"></textarea>
      <button class="btn" id="doSubmit">📨 მოთხოვნის გაგზავნა</button>
    </div>
    <div class="att-note">დამტკიცებულ დასვენების დღეს გაფრთხილება არ ინიშნება.</div>
  </div>
  <div class="card">
    <h2>📜 ჩემი მოთხოვნები <span class="cnt">${rows.length}</span></h2>
    ${rows.length === 0 ? `<div class="empty">მოთხოვნა ჯერ არ გაქვთ</div>` : rows.map((r) => `
      <div class="list-row">
        <div class="avatar">🗓️</div>
        <div class="main">
          <div class="title">${esc(r.date)}</div>
          <div class="sub">${esc(r.reason && r.reason !== "-" ? r.reason : "")}</div>
        </div>
        <div class="side sub">${esc(DAYOFF_STATUS_LABEL[r.status] || r.status)}</div>
      </div>`).join("")}
  </div>`;
}
function bindMyDayoffs() {
  const btn = document.getElementById("doSubmit");
  if (!btn) return;
  btn.onclick = async () => {
    const date = document.getElementById("doDate").value;
    if (!date) { toast("აირჩიეთ თარიღი"); return; }
    btn.disabled = true;
    try {
      await api("/api/dayoff/request", {
        method: "POST",
        body: JSON.stringify({ date, reason: (document.getElementById("doReason").value || "").trim() }),
      });
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast("მოთხოვნა გაიგზავნა ✅");
      delete lazyCache.mydayoffs;
      await renderContent();
    } catch (e) { toast(e.message); btn.disabled = false; }
  };
}

/* ----- აგენტი: დასწრების ისტორია (თვე) ----- */
if (!state.myAttMonth) state.myAttMonth = "";
function renderMyAttendance(rows) {
  rows = rows || [];
  const month = state.myAttMonth || todayIso().slice(0, 7);
  const totalMin = rows.reduce((s, r) => s + (r.minutes || 0), 0);
  return `<div class="card">
    <h2>🕘 დასწრების ისტორია</h2>
    <div class="qa-compose"><input type="month" id="myAttMonth" value="${esc(month)}" /></div>
    <div class="att-grid">
      <div class="stat"><div class="num">${rows.length}</div><div class="lbl">დღე</div></div>
      <div class="stat"><div class="num" style="font-size:15px">${Math.floor(totalMin / 60)}სთ ${totalMin % 60}წთ</div><div class="lbl">ჯამური დრო</div></div>
    </div>
  </div>
  <div class="card">
    ${rows.length === 0 ? `<div class="empty">ამ თვეში ჩანაწერი არ არის</div>` : rows.map((r) => `
      <div class="list-row">
        <div class="avatar">${r.late ? "🔴" : "🟢"}</div>
        <div class="main">
          <div class="title">${esc(r.date)} · ${esc(r.check_in || "—")} → ${esc(r.check_out || "—")}</div>
          <div class="sub">${esc(r.hours_text || "")} ${r.check_in_geo ? "· " + esc(GEO_LABEL[r.check_in_geo] || r.check_in_geo) : ""}</div>
        </div>
        <div class="side">${attStateBadge(r.state)}</div>
      </div>`).join("")}
  </div>`;
}
function bindMyAttendance() {
  const m = document.getElementById("myAttMonth");
  if (m) m.onchange = () => { state.myAttMonth = m.value || ""; delete lazyCache.myattendance; renderContent(); };
}

/* ----- მენეჯერი/ადმინი: დღის დასწრება ----- */
if (state.attDate === undefined) Object.assign(state, { attDate: "", attTeam: "", attState: "", attGeo: "", attLate: false });
const ATT_STATE_FILTER = [
  ["", "ყველა სტატუსი"], ["NOT_STARTED", "არ დაუწყია"], ["ACTIVE", "მუშაობს"], ["COMPLETED", "დასრულებული"],
  ["MISSING_CHECKOUT", "დასრულება არ დაუფიქსირებია"], ["DAY_OFF", "დასვენების დღე"],
];
const ATT_GEO_FILTER = [
  ["", "ყველა ლოკაცია"], ["OFFICE", "ოფისში"], ["OUTSIDE_OFFICE", "ოფისის გარეთ"], ["LOCATION_UNRELIABLE", "არასანდო"],
];
function renderAttendanceAdmin(p) {
  p = p || {};
  const s = p.summary || {};
  const rows = p.rows || [];
  const teams = p.teams || [];
  const set = p.settings || {};
  const isDirector = "office_latitude" in set; // სერვერი კოორდინატს მხოლოდ ადმინს აძლევს
  const opts = (list, cur) => list.map(([v, l]) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  const stat = (n, l) => `<div class="stat"><div class="num">${esc(n == null ? 0 : n)}</div><div class="lbl">${esc(l)}</div></div>`;

  const filters = `<div class="card">
    <h2>🔍 ფილტრი</h2>
    <div class="filter-row">
      <input type="date" id="attDate" value="${esc(state.attDate || todayIso())}" />
      ${teams.length ? `<select id="attTeam"><option value="">ყველა გუნდი</option>${teams.map((t) => `<option value="${esc(t.team)}" ${state.attTeam === t.team ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select>` : ""}
    </div>
    <div class="filter-row">
      <select id="attState">${opts(ATT_STATE_FILTER, state.attState)}</select>
      <select id="attGeo">${opts(ATT_GEO_FILTER, state.attGeo)}</select>
    </div>
    <label class="chk-row" style="font-size:13px"><input type="checkbox" id="attLate" ${state.attLate ? "checked" : ""} /> მხოლოდ დაგვიანებულები</label>
  </div>`;

  const summary = `<div class="card">
    <h2>📊 ${esc(s.date || "")}</h2>
    <div class="grid3">
      ${stat(s.total, "სულ")}${stat(s.started, "დაიწყო")}${stat(s.not_started, "არ დაუწყია")}
      ${stat(s.working, "მუშაობს")}${stat(s.completed, "დაასრულა")}${stat(s.missing_checkout, "დასრულების გარეშე")}
      ${stat(s.office, "ოფისში")}${stat(s.outside, "ოფისის გარეთ")}${stat(s.unreliable, "არასანდო GPS")}
      ${stat(s.late, "დაგვიანებული")}${stat(s.day_off, "Day off")}
    </div>
    ${set.configured === false ? `<div class="att-err">ოფისის კოორდინატი ჯერ არ არის დაყენებული — GPS ვერიფიკაცია გამორთულია.</div>` : ""}
  </div>`;

  const table = `<div class="card">
    <h2>👥 თანამშრომლები <span class="cnt">${rows.length}</span></h2>
    ${rows.length === 0 ? `<div class="empty">ჩანაწერი არ მოიძებნა</div>` : `<div class="tbl-scroll"><table class="att-table">
      <thead><tr><th>სახელი</th><th>დაწყება</th><th>დასრულება</th><th>სთ</th><th>ლოკაცია</th><th>სტატუსი</th></tr></thead>
      <tbody>${rows.map((r, i) => `<tr class="clickable" data-att-idx="${i}">
        <td>${esc(r.agent_name)}${r.late ? " 🔴" : ""}</td>
        <td>${esc(r.check_in || "—")}</td><td>${esc(r.check_out || "—")}</td>
        <td>${esc(r.hours_text || "—")}</td>
        <td>${esc(GEO_LABEL[r.check_in_geo] || "—")}${r.check_in_distance !== "" && r.check_in_distance != null ? " · " + esc(fmtDistance(r.check_in_distance)) : ""}</td>
        <td>${attStateBadge(r.state)}</td></tr>`).join("")}</tbody></table></div>`}
  </div>`;

  const monthStart = todayIso().slice(0, 8) + "01";
  const exportCard = `<div class="card">
    <h2>📤 CSV ექსპორტი</h2>
    <div class="filter-row">
      <input type="date" id="attExFrom" value="${monthStart}" /><input type="date" id="attExTo" value="${todayIso()}" />
    </div>
    <button class="btn secondary" id="attExport" style="width:100%">📤 გამომიგზავნე ბოტში (CSV)</button>
  </div>`;

  const settingsCard = isDirector ? `<div class="card">
    <h2>⚙️ ოფისი და GPS პარამეტრები</h2>
    <div class="qa-compose">
      <input id="stName" placeholder="ოფისის სახელი" value="${esc(set.office_name || "")}" />
      <input id="stLat" inputmode="decimal" placeholder="განედი (latitude)" value="${esc(set.office_latitude == null ? "" : set.office_latitude)}" />
      <input id="stLng" inputmode="decimal" placeholder="გრძედი (longitude)" value="${esc(set.office_longitude == null ? "" : set.office_longitude)}" />
      <button class="btn secondary" id="stHere">📍 ამჟამინდელი ლოკაციის გამოყენება (ოფისიდან დააჭირეთ)</button>
      <input id="stRadius" inputmode="numeric" placeholder="რადიუსი (მ)" value="${esc(set.office_radius_meters || "")}" />
      <input id="stAcc" inputmode="numeric" placeholder="მაქს. დასაშვები GPS ცდომილება (მ)" value="${esc(set.max_accuracy_meters || "")}" />
      <label class="chk-row" style="font-size:13px"><input type="checkbox" id="stOutside" ${set.allow_outside_checkin ? "checked" : ""} /> ოფისის გარედან დაწყების დაშვება (ოფისის ცვლაზე)</label>
      <button class="btn" id="stSave">💾 შენახვა</button>
    </div>
    <div class="att-note">კოორდინატებს ნუ მოიგონებთ — გამოიყენეთ ზუსტი ადგილმდებარეობა. მანძილი/სტატუსი ითვლება სერვერზე.</div>
  </div>` : "";

  return filters + summary + table + exportCard + settingsCard;
}
function bindAttendanceAdmin(p) {
  const rows = (p && p.rows) || [];
  const refetch = () => { delete lazyCache.attendance; renderContent(); };
  const bindSel = (id, key, isCheck) => {
    const el = document.getElementById(id);
    if (el) el.onchange = () => { state[key] = isCheck ? el.checked : el.value; refetch(); };
  };
  bindSel("attDate", "attDate"); bindSel("attTeam", "attTeam"); bindSel("attState", "attState");
  bindSel("attGeo", "attGeo"); bindSel("attLate", "attLate", true);

  document.querySelectorAll("[data-att-idx]").forEach((tr) => {
    tr.onclick = async () => {
      const r = rows[parseInt(tr.dataset.attIdx, 10)];
      if (!r) return;
      const fields = ATT_FIELDS.map(([k, label]) => ({ label, value: r[k] }))
        .concat([
          { label: "სტატუსი", value: STATE_LABEL_TEXT(r.state) },
          { label: "ლოკაცია დაწყებისას", value: GEO_LABEL[r.check_in_geo] || "" },
          { label: "ლოკაცია დასრულებისას", value: GEO_LABEL[r.check_out_geo] || "" },
          { label: "დაგვიანება", value: r.late ? "დიახ" : "" },
        ]);
      const inLink = mapsLink(r.check_in_lat, r.check_in_lng);
      const outLink = mapsLink(r.check_out_lat, r.check_out_lng);
      const extra = `${inLink ? `<button class="btn secondary" id="mapIn" style="margin-top:8px;width:100%">🗺 დაწყების წერტილი რუკაზე</button>` : ""}
        ${outLink ? `<button class="btn secondary" id="mapOut" style="margin-top:8px;width:100%">🗺 დასრულების წერტილი რუკაზე</button>` : ""}
        <div class="share-box"><div class="lbl">📆 ამ თვის ისტორია</div><div id="attHist"><div class="empty">იტვირთება…</div></div></div>`;
      openDetail(r.agent_name, fields, extra);
      const mi = document.getElementById("mapIn"); if (mi) mi.onclick = () => openExternal(inLink);
      const mo = document.getElementById("mapOut"); if (mo) mo.onclick = () => openExternal(outLink);
      try {
        const month = String(r.date || todayIso()).slice(0, 7);
        const h = await api(`/api/attendance/history?agent_id=${encodeURIComponent(r.agent_id)}&month=${encodeURIComponent(month)}`);
        const box = document.getElementById("attHist");
        if (box) box.innerHTML = (h.rows || []).length ? h.rows.map((x) => `
          <div class="list-row"><div class="main">
            <div class="title">${esc(x.date)} · ${esc(x.check_in || "—")} → ${esc(x.check_out || "—")}</div>
            <div class="sub">${esc(x.hours_text || "")} ${x.late ? "· 🔴 დაგვიანება" : ""} ${x.check_in_geo ? "· " + esc(GEO_LABEL[x.check_in_geo] || "") : ""}</div>
          </div><div class="side">${attStateBadge(x.state)}</div></div>`).join("") : `<div class="empty">ჩანაწერი არ არის</div>`;
      } catch (e) {
        const box = document.getElementById("attHist");
        if (box) box.innerHTML = `<div class="empty">⚠️ ${esc(e.message)}</div>`;
      }
    };
  });

  const ex = document.getElementById("attExport");
  if (ex) ex.onclick = async () => {
    ex.disabled = true;
    try {
      await api("/api/attendance/export", {
        method: "POST",
        body: JSON.stringify({
          date_from: document.getElementById("attExFrom").value, date_to: document.getElementById("attExTo").value,
          team: state.attTeam || "",
        }),
      });
      toast("ფაილი გამოგიგზავნეთ ბოტში ✅");
    } catch (e) { toast(e.message); }
    ex.disabled = false;
  };

  const here = document.getElementById("stHere");
  if (here) here.onclick = async () => {
    here.disabled = true;
    try {
      const g = await getGeo();
      document.getElementById("stLat").value = g.lat;
      document.getElementById("stLng").value = g.lng;
      toast(`ლოკაცია ჩაიწერა (სიზუსტე ≈ ${Math.round(g.accuracy || 0)} მ) — დააჭირეთ „შენახვა"`);
    } catch (e) { toast(e.message); }
    here.disabled = false;
  };
  const save = document.getElementById("stSave");
  if (save) save.onclick = async () => {
    save.disabled = true;
    try {
      await api("/api/attendance/settings", {
        method: "POST",
        body: JSON.stringify({
          office_name: document.getElementById("stName").value,
          office_latitude: document.getElementById("stLat").value,
          office_longitude: document.getElementById("stLng").value,
          office_radius_meters: document.getElementById("stRadius").value,
          max_accuracy_meters: document.getElementById("stAcc").value,
          allow_outside_checkin: document.getElementById("stOutside").checked,
        }),
      });
      toast("პარამეტრები შენახულია ✅");
      refetch();
    } catch (e) { toast(e.message); save.disabled = false; }
  };
}
function STATE_LABEL_TEXT(s) { return (ATT_STATE_BADGE[s] || [0, s || ""])[1]; }

/* ----- მენეჯერი/ადმინი: კვირის რაიონების განაწილება ----- */
if (state.distWeek === undefined) Object.assign(state, { distWeek: "", distTeam: "" });
if (!state.distAgents) state.distAgents = new Set();
if (!state.distPick) state.distPick = new Set();

function renderDistricts(p) {
  p = p || {};
  const agents = p.agents || [];
  const teams = p.teams || [];
  const catalog = p.catalog || [];
  const locked = !!p.is_past;
  const groups = new Map();
  agents.forEach((a) => { const k = a.team_label || "—"; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(a); });

  const weekNav = `<div class="card">
    <h2>📍 კვირის რაიონები <span class="cnt">${esc(p.week_label || "")}</span></h2>
    <div class="filter-row">
      <button class="btn secondary" id="dwPrev" style="flex:none;padding:9px 14px">◀</button>
      <input type="date" id="dwDate" value="${esc(p.week_start || "")}" />
      <button class="btn secondary" id="dwNext" style="flex:none;padding:9px 14px">▶</button>
    </div>
    <div class="sub">${p.is_current ? "✅ მიმდინარე კვირა" : (locked ? "🔒 გასული კვირა — მხოლოდ ნახვა" : "შემდეგი კვირა")}</div>
    ${teams.length ? `<div class="filter-row" style="margin-top:8px"><select id="dwTeam"><option value="">ყველა გუნდი</option>${teams.map((t) => `<option value="${esc(t.team)}" ${state.distTeam === t.team ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></div>` : ""}
  </div>`;

  const agentsHtml = `<div class="card">
    <h2>🧑‍🤝‍🧑 აგენტები <span class="cnt">${agents.length}</span></h2>
    ${agents.length > 1 && !locked ? `<div style="margin-bottom:8px"><button class="chip" id="dwAll">☑ ყველას მონიშვნა / მოხსნა</button></div>` : ""}
    ${agents.length === 0 ? `<div class="empty">აგენტი არ არის</div>` : [...groups.entries()].map(([label, list]) => `
      <div class="team-group">
        <div class="team-group-head"><span class="tg-name">🧑‍💼 ${esc(label)}</span></div>
        ${list.map((a) => `
          <div class="list-row chk-row" style="align-items:flex-start">
            ${locked ? "" : `<input type="checkbox" class="chk-pick" data-dw-agent="${esc(a.agent_id)}" ${state.distAgents.has(String(a.agent_id)) ? "checked" : ""} />`}
            <div class="main" style="overflow:visible">
              <div class="title">${esc(a.name)}${a.role === "team_lead" ? " 👑" : ""}</div>
              <div class="chip-row" data-dw-cur="${esc(a.agent_id)}">${(a.districts || []).length
                ? a.districts.map((x) => `<span class="chip sel">${esc(x)}</span>`).join("")
                : `<span class="sub">რაიონი არ არის მინიჭებული</span>`}</div>
            </div>
          </div>`).join("")}
      </div>`).join("")}
  </div>`;

  const pickerHtml = locked ? "" : `<div class="card">
    <h2>🗺 რაიონების არჩევა <span class="cnt" id="dwPickCnt">${state.distPick.size}</span></h2>
    <div class="att-note">მონიშნეთ აგენტები ზემოთ, აქ — რაიონები (რამდენიმე შეიძლება). ჯგუფის სახელზე დაჭერა = მთელი ჯგუფი.</div>
    ${catalog.map((g) => `<div class="dist-group">
      <button class="chip" data-dw-d="${esc(g.group)}" style="font-weight:800">${esc(g.group)}</button>
      <div class="chip-row">${g.districts.map((x) => `<button class="chip" data-dw-d="${esc(x)}">${esc(x)}</button>`).join("")}</div>
    </div>`).join("")}
    <div class="actions">
      <button class="btn" id="dwSave">💾 მინიჭება</button>
      <button class="btn danger" id="dwClear">🧹 გასუფთავება</button>
    </div>
  </div>`;
  const isAdm = state.role === "admin" && !(state.data && state.data.is_team_lead);
  return (isAdm ? `<div class="card" id="dwAutoBox"><div class="empty">იტვირთება…</div></div>` : "") + weekNav + agentsHtml + pickerHtml;
}

/* 🔀 ავტომატური კვირეული განაწილება (მხოლოდ ადმინი): ორშაბათს 08:30-ზე ბოტი ყველა აქტიურ აგენტს ანიჭებს საკუთარ, გასულ კვირებში არ განმეორებულ რაიონებს */
async function dwAuto(box, week, refetch) {
  let st;
  try { st = await api("/api/districts/auto"); } catch (e) { box.hidden = true; return; }
  const draw = (s) => {
    box.innerHTML = `<h2>🔀 ავტომატური განაწილება</h2>
      <div class="att-note">ყოველ ორშაბათს 08:30-ზე ბოტი ყველა აქტიურ აგენტს თავად ანაწილებს საკუთარ რაიონებზე — აგენტებს შორის არ მეორდება და გასულ კვირებში ნამუშევარი რაიონები შეძლებისდაგვარად არ ბრუნდება. ხელით მინიჭებულს არ ვეხებით.</div>
      <div class="list-row" style="margin:8px 0"><div class="main"><div class="title">ავტომატური გაშვება ორშაბათს</div>
        <div class="sub">${s.this_week_done ? "✅ ამ კვირის განაწილება გაკეთებულია" : "ამ კვირის განაწილება ჯერ არ გაკეთებულა"}${s.last_auto_week ? ` · ბოლოს: ${esc(s.last_auto_week)}` : ""}</div></div>
        <div class="side"><button class="chip ${s.enabled ? "sel" : ""}" id="dwAutoToggle">${s.enabled ? "ჩართულია" : "გამორთულია"}</button></div></div>
      <div class="actions"><button class="btn secondary" id="dwShufPrev">👁 გადახედვა</button><button class="btn" id="dwShufNow">🔀 გადანაწილება ახლა</button></div>
      <div id="dwShufOut" class="sub" style="margin-top:8px;white-space:normal"></div>`;
    document.getElementById("dwAutoToggle").onclick = async () => {
      try { draw(await api("/api/districts/auto", { method: "POST", body: JSON.stringify({ enabled: !s.enabled }) })); toast(!s.enabled ? "✅ ჩაირთო" : "გამოირთო"); }
      catch (e) { toast(e.message || "შეცდომა"); }
    };
    const run = async (dry) => {
      const out = document.getElementById("dwShufOut");
      if (!dry && !confirm("ყველა აქტიურ აგენტს ახლავე გადაენაწილება რაიონები (ხელით მინიჭებულს არ შევეხებით) და შეტყობინება გაეგზავნება. გავაგრძელოთ?")) return;
      out.textContent = "მიმდინარეობს…";
      try {
        const r = await api("/api/districts/shuffle", { method: "POST", body: JSON.stringify({ week, dry_run: dry }) });
        out.innerHTML = `${dry ? "👁 გადახედვა" : "✅ გადანაწილდა"}: <b>${r.assigned}</b> აგენტი${r.skipped_manual ? ` · ხელით დარჩა: ${r.skipped_manual}` : ""}<br>` +
          (r.preview || []).slice(0, 12).map((x) => `• ${esc(x.name)}: ${esc((x.districts || []).join(", "))}`).join("<br>") + ((r.preview || []).length > 12 ? "<br>…" : "");
        if (!dry) { toast("✅ რაიონები გადანაწილდა"); refetch(); }
      } catch (e) { out.textContent = e.message || "შეცდომა"; }
    };
    document.getElementById("dwShufPrev").onclick = () => run(true);
    document.getElementById("dwShufNow").onclick = () => run(false);
  };
  draw(st);
}

function bindDistricts(p) {
  p = p || {};
  const agents = p.agents || [];
  const refetch = () => { delete lazyCache.districts; renderContent(); };
  const wk = () => p.week_start || todayIso();
  const autoBox = document.getElementById("dwAutoBox");
  if (autoBox) dwAuto(autoBox, p.week_start || todayIso(), refetch);
  const goWeek = (iso) => { state.distWeek = iso; state.distAgents.clear(); state.distPick.clear(); refetch(); };
  const prev = document.getElementById("dwPrev"); if (prev) prev.onclick = () => goWeek(addDaysIso(wk(), -7));
  const next = document.getElementById("dwNext"); if (next) next.onclick = () => goWeek(addDaysIso(wk(), 7));
  const dt = document.getElementById("dwDate"); if (dt) dt.onchange = () => dt.value && goWeek(dt.value);
  const tm = document.getElementById("dwTeam");
  if (tm) tm.onchange = () => { state.distTeam = tm.value; state.distAgents.clear(); state.distPick.clear(); refetch(); };
  if (p.is_past) return;

  const syncChips = () => {
    document.querySelectorAll("[data-dw-d]").forEach((c) => c.classList.toggle("sel", state.distPick.has(c.dataset.dwD)));
    const cnt = document.getElementById("dwPickCnt"); if (cnt) cnt.textContent = state.distPick.size;
  };
  const loadFromSingle = () => {
    // ერთი აგენტის მონიშვნისას მისი მიმდინარე რაიონები ავტომატურად ივსება
    if (state.distAgents.size !== 1) return;
    const a = agents.find((x) => String(x.agent_id) === [...state.distAgents][0]);
    state.distPick = new Set((a && a.districts) || []);
    syncChips();
  };
  document.querySelectorAll("[data-dw-agent]").forEach((c) => {
    c.onchange = () => {
      const id = c.dataset.dwAgent;
      if (c.checked) state.distAgents.add(id); else state.distAgents.delete(id);
      loadFromSingle();
    };
  });
  const all = document.getElementById("dwAll");
  if (all) all.onclick = () => {
    const boxes = [...document.querySelectorAll("[data-dw-agent]")];
    const allOn = boxes.every((c) => c.checked);
    boxes.forEach((c) => {
      c.checked = !allOn;
      if (c.checked) state.distAgents.add(c.dataset.dwAgent); else state.distAgents.delete(c.dataset.dwAgent);
    });
    loadFromSingle();
  };
  document.querySelectorAll("[data-dw-d]").forEach((c) => {
    c.onclick = () => {
      const v = c.dataset.dwD;
      if (state.distPick.has(v)) state.distPick.delete(v); else state.distPick.add(v);
      syncChips();
    };
  });
  syncChips();

  const send = async (districts, okMsg) => {
    if (!state.distAgents.size) { toast("აირჩიეთ მინიმუმ ერთი აგენტი"); return; }
    try {
      const res = await api("/api/districts/assign", {
        method: "POST",
        body: JSON.stringify({ week: wk(), agent_ids: [...state.distAgents], districts }),
      });
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast(`${okMsg} (${res.changed} შეტყობინება გაიგზავნა)`);
      state.distAgents.clear(); state.distPick.clear();
      refetch();
    } catch (e) { toast(e.message); }
  };
  const save = document.getElementById("dwSave");
  if (save) save.onclick = () => {
    if (!state.distPick.size) { toast("აირჩიეთ მინიმუმ ერთი რაიონი (ან გამოიყენეთ გასუფთავება)"); return; }
    send([...state.distPick], "რაიონები მიენიჭა ✅");
  };
  const clear = document.getElementById("dwClear");
  if (clear) clear.onclick = () => {
    if (!state.distAgents.size) { toast("აირჩიეთ მინიმუმ ერთი აგენტი"); return; }
    if (confirm("ამ კვირისთვის მონიშნული აგენტების რაიონები გასუფთავდეს?")) send([], "გასუფთავდა");
  };
}

/* ================================================ ხელშეკრულებები (Contract Management) =====
   მონაცემი: /api/contracts/... ; უფლებები სერვერზეა (აგენტი — საკუთარი, თიმლიდერი — გუნდის, თანამშრომელი/ადმინი — ყველა).
   frontend მხოლოდ ღილაკებს მალავს/აჩვენებს (caps) — რეალურ შემოწმებას სერვერი აკეთებს.
   არსებულ ტაბებს არ ეხება. შეხვედრის დეტალში ემატება "+ ხელშეკრულების მოთხოვნა" (იხ. bindMeetingsActions). */
if (!state.ctSection) state.ctSection = "requests";
if (!state.ctFilter) state.ctFilter = { status: "", agent: "", type: "", q: "" };
if (!state.ctInv) state.ctInv = { type: "", status: "", q: "" };

const CT_REQ_CLS = { REQUESTED: "amber", APPROVED: "amber", ISSUED: "green", PARTIALLY_ISSUED: "amber", COMPLETED: "gray", CANCELLED: "gray" };
const CT_PH_CLS = { AVAILABLE: "green", RESERVED: "amber", ISSUED: "amber", RETURNED_UNUSED: "green", USED_SIGNED: "gray",
  DAMAGED: "red", LOST: "red", UNDER_REVIEW: "amber" };

function ctPost(path, body) { return api(path, { method: "POST", body: JSON.stringify(body || {}) }); }
/* შეცდომა/მინიშნება პირდაპირ ფორმაში (მოდალის შიგნით) — რომ მომხმარებელმა აუცილებლად დაინახოს, რატომ არ სრულდება მოქმედება */
function ctErr(msg) {
  const el = document.getElementById("ctMsg");
  if (el) { el.textContent = "⚠️ " + msg; el.hidden = false; }
  else toast(msg);
}
const CT_MSG = `<div id="ctMsg" class="sub" hidden style="color:var(--red);font-weight:650"></div>`;
function ctReload() { delete lazyCache.contracts; closeDetail(); renderContent(); }
function ctIdemKey() {
  try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) { /* ignore */ }
  return "k" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}
function ctReqBadge(r) { return `<span class="badge ${CT_REQ_CLS[r.request_status] || "gray"}">${esc(r.status_label || r.request_status)}</span>`; }
function ctCopyBadge(c) { return `<span class="badge ${CT_PH_CLS[c.physical_status] || "gray"}">${esc(c.status_label || c.physical_status)}</span>`; }
function ctOptions(map, selected, allLabel) {
  return `<option value="">${esc(allLabel)}</option>` + Object.keys(map).map((k) => `<option value="${esc(k)}" ${selected === k ? "selected" : ""}>${esc(map[k])}</option>`).join("");
}

function ctIssueRow(i, idx, withAgent) {
  return `<div class="list-row clickable" data-ct-issue="${idx}">
    <div class="avatar">${i.overdue ? "⏰" : "📑"}</div>
    <div class="main">
      <div class="title" ${i.control_code ? `style="font-family:monospace;letter-spacing:.5px"` : `style="white-space:normal"`}>${esc(i.control_code || i.property_address || i.type_label || "ხელშეკრულება")}${i.overdue ? ` <span class="badge red">ვადაგადაცილებული</span>` : ""}</div>
      <div class="sub">${withAgent ? esc(i.agent_name) + " · " : ""}${esc(i.type_label || "")} · ${esc(i.property_address || "")}</div>
      <div class="sub">გაიცა: ${esc(i.issued_at)} · დასაბრუნებელი: <b>${esc(i.due_at)}</b></div>
    </div>
  </div>`;
}

function renderContracts(p) {
  p = p || {};
  const caps = p.caps || {};
  const reqs = p.requests || [];
  const active = p.active_issues || [];
  const manager = !!(caps.admin || caps.staff || caps.lead);
  let html = "";

  if (!manager) {                                   // ---- აგენტი: მინიმალისტური ხედი
    html += `<div class="card"><h2>➕ ახალი ხელშეკრულების მოთხოვნა</h2>
      <div class="sub" style="margin-bottom:8px">აირჩიეთ შეხვედრა, რომელზეც ხელშეკრულება გჭირდებათ (კლიენტისა და ბინის მონაცემები ავტომატურად შეივსება):</div>
      <div id="ctMeetList"><div class="sub">შეხვედრები იტვირთება…</div></div>
    </div>
    <div class="card"><h2>📑 ჩემთან გატანილი ხელშეკრულებები <span class="cnt">${active.length}</span></h2>
      ${active.length ? active.map((i, k) => ctIssueRow(i, k, false)).join("") : `<div class="empty">ამჟამად ხელშეკრულება არ გაქვთ გატანილი</div>`}
    </div>
    <div class="card"><h2>📋 ჩემი მოთხოვნების ისტორია <span class="cnt">${reqs.length}</span></h2>
      ${reqs.length ? reqs.map((r, k) => ctReqRow(r, k)).join("") : `<div class="empty">მოთხოვნა ჯერ არ გაქვთ</div>`}
    </div>`;
    return html;
  }

  // ---- მენეჯერი/თანამშრომელი/ადმინი
  const s = p.summary || {};
  const stat = (n, l) => `<div class="stat"><div class="num">${esc(n == null ? 0 : n)}</div><div class="lbl">${esc(l)}</div></div>`;
  html += `<div class="card"><h2>📑 ხელშეკრულებები — მიმოხილვა</h2>
    <div class="grid3">
      ${stat(s.total, "სულ ეგზემპლარი")}${stat(s.available, "ხელმისაწვდომი")}${stat(s.reserved, "დაჯავშნილი")}
      ${stat(s.issued, "აგენტებთან")}${stat(s.due_today, "დღეს დასაბრუნებელი")}${stat(s.overdue, "ვადაგადაცილებული")}
      ${stat(s.returned_unused, "დაბრუნებული გამოუყენებელი")}${stat(s.signed, "ხელმოწერილი")}${stat(s.in_process, "მოთხოვნა პროცესში")}
      ${stat(s.damaged, "დაზიანებული")}${stat(s.lost, "დაკარგული")}${stat(s.under_review, "შესამოწმებელი")}
    </div>
    <div class="sub" style="margin-top:10px">${Object.keys(p.stock || {}).map((t) => `${esc((p.types || {})[t] || t)}: თავისუფალი <b>${p.stock[t].available}</b>/${p.stock[t].total}`).join("<br>")}</div>
  </div>`;

  const sections = [["requests", "მოთხოვნები"], ["active", "გატანილი"], ["overdue", "დაგვიანება"], ["problems", "პრობლემური"]];
  if (caps.staff) sections.push(["inventory", "მარაგი"]);
  sections.push(["history", "დაბრუნებები"]);
  if (!sections.some(([id]) => id === state.ctSection)) state.ctSection = "requests";
  html += `<div class="card"><div class="period-switch" id="ctSections" style="flex-wrap:wrap">
    ${sections.map(([id, l]) => `<button data-ct-sec="${id}" class="${state.ctSection === id ? "active" : ""}">${l}</button>`).join("")}</div>`;

  if (state.ctSection === "requests") {
    const f = state.ctFilter;
    const agents = [...new Map(reqs.map((r) => [r.agent_id, r.agent_name])).entries()];
    const shown = reqs.filter((r) =>
      (!f.status || r.request_status === f.status) && (!f.agent || r.agent_id === f.agent) && (!f.type || r.contract_type === f.type)
      && (!f.q || [r.property_address, r.request_id, r.agent_name, r.property_id, r.meeting_id].join(" ").toLowerCase().includes(f.q.toLowerCase())));
    html += `<div class="qa-compose" style="margin-top:10px">
      <select id="ctFStatus">${ctOptions(p.request_statuses || {}, f.status, "ყველა სტატუსი")}</select>
      <select id="ctFType">${ctOptions(p.types || {}, f.type, "ყველა ტიპი")}</select>
      <select id="ctFAgent"><option value="">ყველა აგენტი</option>${agents.map(([id, n]) => `<option value="${esc(id)}" ${f.agent === id ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
      <input id="ctFQ" placeholder="ძებნა: მისამართი / მოთხოვნის ID / აგენტი" value="${esc(f.q)}">
    </div>
    <h2 style="margin-top:12px">📋 მოთხოვნები <span class="cnt">${shown.length}</span></h2>
    ${shown.length ? shown.map((r) => ctReqRow(r, reqs.indexOf(r))).join("") : `<div class="empty">ვერაფერი მოიძებნა</div>`}`;
  } else if (state.ctSection === "active") {
    html += `<h2 style="margin-top:12px">📑 აგენტებთან გატანილი <span class="cnt">${active.length}</span></h2>
      ${active.length ? active.map((i, k) => ctIssueRow(i, k, true)).join("") : `<div class="empty">ახლა არავისთანაა</div>`}`;
  } else if (state.ctSection === "overdue") {
    const od = (p.overdue || []), td = (p.today_due || []);
    html += `<h2 style="margin-top:12px">⏰ ვადაგადაცილებული <span class="cnt">${od.length}</span></h2>
      ${od.length ? od.map((i, k) => ctIssueRow(i, k, true)).join("") : `<div class="empty">ვადაგადაცილებული არ არის ✅</div>`}
      <h2 style="margin-top:14px">📅 დღეს დასაბრუნებელი <span class="cnt">${td.length}</span></h2>
      ${td.length ? td.map((i, k) => ctIssueRow(i, 1000 + k, true)).join("") : `<div class="empty">დღეს დასაბრუნებელი არ არის</div>`}`;
  } else if (state.ctSection === "problems") {
    const pc = p.problem_copies || [];
    html += `<h2 style="margin-top:12px">⚠️ დაზიანებული / დაკარგული / შესამოწმებელი <span class="cnt">${pc.length}</span></h2>
      ${pc.length ? pc.map((c, k) => ctCopyRow(c, k)).join("") : `<div class="empty">პრობლემური ეგზემპლარი არ არის ✅</div>`}`;
  } else if (state.ctSection === "inventory" && caps.staff) {
    const f = state.ctInv;
    const copies = (p.copies || []).filter((c) => (!f.type || c.contract_type === f.type) && (!f.status || c.physical_status === f.status)
      && (!f.q || String(c.control_code).toUpperCase().includes(f.q.toUpperCase())));
    html += `<div class="qa-compose" style="margin-top:10px">
      <div class="sub"><b>ახალი ეგზემპლარების დამატება მარაგში</b> (კოდები სერვერზე ენიჭება)</div>
      <select id="ctNewType">${ctOptions(p.types || {}, "", "აირჩიეთ ტიპი")}</select>
      <input id="ctNewQty" type="number" min="1" max="200" value="10" placeholder="რაოდენობა">
      <input id="ctNewLoc" placeholder="შენახვის ადგილი (არასავალდებულო)">
      <button class="btn" id="ctNewBtn">➕ დამატება</button>
    </div>
    <div class="qa-compose" style="margin-top:12px">
      <select id="ctIType">${ctOptions(p.types || {}, f.type, "ყველა ტიპი")}</select>
      <select id="ctIStatus">${ctOptions(p.physical_statuses || {}, f.status, "ყველა სტატუსი")}</select>
      <input id="ctIQ" placeholder="ძებნა კოდით (SH-…)" value="${esc(f.q)}">
    </div>
    <h2 style="margin-top:12px">📦 ეგზემპლარები <span class="cnt">${copies.length}</span></h2>
    ${copies.length ? copies.slice().reverse().slice(0, 200).map((c, k) => ctCopyRow(c, (p.copies || []).indexOf(c))).join("") : `<div class="empty">ვერაფერი მოიძებნა</div>`}`;
  } else if (state.ctSection === "history") {
    const rr = p.recent_returns || [];
    html += `<h2 style="margin-top:12px">↩️ ბოლო დაბრუნებები <span class="cnt">${rr.length}</span></h2>
      ${rr.length ? rr.map((i, k) => `<div class="list-row clickable" data-ct-ret="${k}"><div class="avatar">↩️</div><div class="main">
        <div class="title" style="font-family:monospace">${esc(i.control_code)} <span class="badge gray">${esc(i.outcome_label || i.outcome)}</span></div>
        <div class="sub">${esc(i.agent_name)} · დაბრუნდა: ${esc(i.returned_at)} · მიიღო: ${esc(i.received_by)}</div></div></div>`).join("") : `<div class="empty">ჯერ არ არის</div>`}`;
  }
  html += `</div>`;
  return html;
}

function ctReqRow(r, idx) {
  return `<div class="list-row clickable" style="align-items:flex-start" data-ct-req="${idx}">
    <div class="avatar">📑</div>
    <div class="main">
      <div class="title" style="white-space:normal">${esc(r.property_address || "მისამართი უცნობია")}</div>
      <div class="sub">${esc(r.agent_name)} · ${esc(r.type_label)} · ${esc(r.issued_count)}/${esc(r.copy_count)} ეგზ.</div>
      <div class="sub">${esc(r.request_id)} · ${esc(r.request_created_at)}</div>
    </div>
    <div class="side">${ctReqBadge(r)}</div>
  </div>`;
}
function ctCopyRow(c, idx) {
  return `<div class="list-row clickable" data-ct-copy="${idx}">
    <div class="avatar">📄</div>
    <div class="main">
      <div class="title" style="font-family:monospace;letter-spacing:.5px">${esc(c.control_code)}</div>
      <div class="sub">${esc(c.type_label)}${c.storage_location ? " · " + esc(c.storage_location) : ""}</div>
    </div>
    <div class="side">${ctCopyBadge(c)}</div>
  </div>`;
}

function bindContractsActions(p) {
  p = p || {};
  const caps = p.caps || {};
  const reqs = p.requests || [];
  const active = p.active_issues || [];
  document.querySelectorAll("[data-ct-sec]").forEach((b) => {
    b.onclick = () => { state.ctSection = b.dataset.ctSec; renderContent(); };
  });
  // აგენტი: ბოლო შეხვედრების სია, საიდანაც პირდაპირ იგზავნება მოთხოვნა
  const ml = document.getElementById("ctMeetList");
  if (ml) ctLoadMeetList(ml, caps);
  document.querySelectorAll("[data-ct-req]").forEach((el) => {
    el.onclick = () => { const r = reqs[parseInt(el.dataset.ctReq, 10)]; if (r) ctOpenRequest(r.request_id); };
  });
  document.querySelectorAll("[data-ct-issue]").forEach((el) => {
    el.onclick = () => {
      const n = parseInt(el.dataset.ctIssue, 10);
      let i;
      if (n >= 1000) i = (p.today_due || [])[n - 1000];                    // „დღეს დასაბრუნებელი“ (დაგვიანების ტაბში)
      else if (state.ctSection === "overdue") i = (p.overdue || [])[n];
      else i = active[n];
      if (i) ctOpenIssue(i, caps);
    };
  });
  document.querySelectorAll("[data-ct-copy]").forEach((el) => {
    el.onclick = () => {
      const n = parseInt(el.dataset.ctCopy, 10);
      const c = (state.ctSection === "problems" ? (p.problem_copies || []) : (p.copies || []))[n];
      if (c) ctOpenCopy(c, caps);
    };
  });
  document.querySelectorAll("[data-ct-ret]").forEach((el) => {
    el.onclick = () => { const i = (p.recent_returns || [])[parseInt(el.dataset.ctRet, 10)]; if (i) ctOpenIssue(i, caps); };
  });
  // ფილტრები
  const bindF = (id, key, obj, ev) => { const el = document.getElementById(id); if (el) el[ev || "onchange"] = () => { obj[key] = el.value; renderContent(); }; };
  bindF("ctFStatus", "status", state.ctFilter); bindF("ctFType", "type", state.ctFilter); bindF("ctFAgent", "agent", state.ctFilter);
  const q = document.getElementById("ctFQ");
  if (q) q.onchange = () => { state.ctFilter.q = q.value; renderContent(); };
  bindF("ctIType", "type", state.ctInv); bindF("ctIStatus", "status", state.ctInv);
  const iq = document.getElementById("ctIQ");
  if (iq) iq.onchange = () => { state.ctInv.q = iq.value; renderContent(); };
  const nb = document.getElementById("ctNewBtn");
  if (nb) nb.onclick = async () => {
    const type = document.getElementById("ctNewType").value;
    const qty = parseInt(document.getElementById("ctNewQty").value, 10);
    if (!type) { toast("აირჩიეთ ტიპი"); return; }
    if (!qty || qty < 1) { toast("მიუთითეთ რაოდენობა"); return; }
    nb.disabled = true;
    try {
      const r = await ctPost("/api/contracts/copies", { contract_type: type, quantity: qty, storage_location: document.getElementById("ctNewLoc").value });
      openDetail("დაემატა " + r.count + " ეგზემპლარი", [],
        `<div class="sub" style="margin:8px 0">დაბეჭდვამდე გადაიწერეთ საკონტროლო კოდები:</div>
         <div style="font-family:monospace;line-height:1.9;user-select:all">${r.copies.map((c) => esc(c.control_code)).join("<br>")}</div>
         <button class="btn" id="ctDoneBtn" style="margin-top:10px">კარგი</button>`);
      document.getElementById("ctDoneBtn").onclick = ctReload;
    } catch (e) { toast(e.message); nb.disabled = false; }
  };
}

/* ახალი მოთხოვნა ხელშეკრულებების ტაბიდანაც: ბოლო შეხვედრები (30 დღე) + ღილაკი თითოეულზე */
async function ctLoadMeetList(box, caps) {
  try {
    const own = state.data && state.data.is_team_lead ? "&scope=own" : "";
    const resp = await api("/api/meetings?period=month" + own);
    const rows = (resp.rows || []).slice(0, 30);
    if (!rows.length) { box.innerHTML = `<div class="empty">ბოლო 30 დღეში შეხვედრა არ გაქვთ დაფიქსირებული. ჯერ დააფიქსირეთ შეხვედრა (/meeting).</div>`; return; }
    box.innerHTML = rows.map((m, k) => `<div class="list-row" style="align-items:center">
        <div class="avatar">🏠</div>
        <div class="main"><div class="title" style="white-space:normal">${esc(m.address || m.district || "მისამართი უცნობია")}</div>
          <div class="sub">${esc(m.meeting_date || "")} ${esc(m.time || "")}</div></div>
        <div class="side"><button class="btn" data-ct-pick="${k}" style="padding:8px 10px;font-size:12px">+ მოთხოვნა</button></div></div>`).join("");
    box.querySelectorAll("[data-ct-pick]").forEach((b) => {
      b.onclick = async () => {
        const m = rows[parseInt(b.dataset.ctPick, 10)];
        b.disabled = true;
        try {
          const d = await api("/api/contracts/meeting/" + encodeURIComponent(m.meeting_id));
          if (!d.can_create) { toast("ამ შეხვედრაზე მოთხოვნას ვერ შექმნით"); b.disabled = false; return; }
          ctOpenRequestForm(m, d);
        } catch (e) { toast(e.message); }
        b.disabled = false;
      };
    });
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

/* მოთხოვნის დეტალი + მოქმედებები (უფლებების მიხედვით; სერვერი ამას მაინც ამოწმებს) */
async function ctOpenRequest(rid) {
  let d;
  try { d = await api("/api/contracts/requests/" + encodeURIComponent(rid)); } catch (e) { toast(e.message); return; }
  const r = d.request, caps = d.caps || {};
  const fields = [
    { label: "მოთხოვნის ID", value: r.request_id }, { label: "სტატუსი", value: r.status_label },
    { label: "ხელშეკრულების ტიპი", value: r.type_label }, { label: "ეგზემპლარი (გაცემული/მოთხოვნილი)", value: `${r.issued_count}/${r.copy_count}` },
    { label: "აგენტი", value: r.agent_name }, { label: "მისამართი", value: r.property_address },
    { label: "MyHome ID", value: r.myhome_id }, { label: "SS.ge ID", value: r.ssge_id },
    { label: "კლიენტის ტელეფონი", value: r.client_phone }, { label: "შეხვედრა", value: `${r.meeting_datetime || ""} (ID: ${r.meeting_id})` },
    { label: "მოთხოვნის დრო", value: r.request_created_at }, { label: "დამტკიცა", value: r.approved_by ? `${r.approved_by} · ${r.approved_at}` : "" },
    { label: "კომენტარი", value: r.notes }, { label: "გაუქმების მიზეზი", value: r.cancelled_reason },
  ];
  const issues = d.issues || [];
  const status = r.request_status;
  let extra = `<div class="share-box"><div class="lbl">📑 გაცემა/დაბრუნების ისტორია</div>${issues.length ? issues.map((i, k) => `
      <div class="list-row clickable" data-ctm-issue="${k}"><div class="main">
        <div class="title" ${i.control_code ? `style="font-family:monospace"` : ""}>${esc(i.control_code || "ეგზემპლარი " + (k + 1))} ${i.open ? (i.overdue ? `<span class="badge red">ვადაგადაცილებული</span>` : `<span class="badge amber">აგენტთანაა</span>`) : `<span class="badge gray">${esc(i.outcome_label || i.outcome)}</span>`}</div>
        <div class="sub">გაიცა ${esc(i.issued_at)} (${esc(i.issued_by)}) · ვადა ${esc(i.due_at)}</div>
        ${i.returned_at ? `<div class="sub">დაბრუნდა ${esc(i.returned_at)} · მიიღო ${esc(i.received_by)}${i.return_condition ? " · " + esc(i.return_condition) : ""}</div>` : ""}
      </div></div>`).join("") : `<div class="sub">ჯერ არ გაცემულა</div>`}</div>`;
  const btns = [];
  const canApproveNow = status === "REQUESTED" && (caps.admin || (caps.can_approve && r.agent_id !== caps.agent_id));
  if (canApproveNow) btns.push(`<button class="btn" id="ctApprove">✅ დამტკიცება</button>`);
  if (caps.can_handle_physical && (status === "APPROVED" || status === "PARTIALLY_ISSUED")) btns.push(`<button class="btn" id="ctIssue">📤 გაცემა</button>`);
  if (caps.can_handle_physical && status === "PARTIALLY_ISSUED") btns.push(`<button class="btn secondary" id="ctCloseRem">დარჩენილის გაუქმება</button>`);
  if (status === "REQUESTED" || status === "APPROVED") btns.push(`<button class="btn danger" id="ctCancel">✖ გაუქმება</button>`);
  if (btns.length) extra += `<div class="chip-row" style="margin-top:12px;gap:8px">${btns.join("")}</div>`;
  if ((status === "APPROVED" || status === "PARTIALLY_ISSUED") && !caps.can_handle_physical) {
    extra += `<div class="sub" style="margin-top:10px">ℹ️ ფიზიკურ გაცემას ადასტურებს მხოლოდ ადმინი ან პასუხისმგებელი თანამშრომელი. თქვენთან გაცემის ღილაკი ამიტომ არ ჩანს.</div>`;
  }
  if (d.audit && d.audit.length) {
    extra += `<div class="share-box"><div class="lbl">🧾 აუდიტი</div>${d.audit.map((e) => `<div class="sub">${esc(e.timestamp)} · ${esc(e.action)} · ${esc(e.actor_id)}</div>`).join("")}</div>`;
  }
  openDetail("ხელშეკრულების მოთხოვნა", fields, extra);
  document.querySelectorAll("[data-ctm-issue]").forEach((el) => {
    el.onclick = () => { const i = issues[parseInt(el.dataset.ctmIssue, 10)]; if (i) ctOpenIssue(i, caps); };
  });
  const act = (id, fn) => { const b = document.getElementById(id); if (b) b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { toast(e.message); b.disabled = false; } }; };
  act("ctApprove", async () => { const x = await ctPost(`/api/contracts/requests/${rid}/approve`); toast(`დამტკიცდა ✅ (დაჯავშნილი: ${x.reserved})`); ctReload(); });
  act("ctCancel", async () => {
    const reason = prompt("გაუქმების მიზეზი (არასავალდებულო)") ; if (reason === null) throw new Error("გაუქმება შეჩერდა");
    await ctPost(`/api/contracts/requests/${rid}/cancel`, { reason }); toast("გაუქმდა"); ctReload();
  });
  act("ctCloseRem", async () => { if (!confirm("დარჩენილი ეგზემპლარების გაცემა გაუქმდეს?")) throw new Error("შეჩერდა"); await ctPost(`/api/contracts/requests/${rid}/close-remaining`); ctReload(); });
  act("ctIssue", async () => { await ctOpenIssueForm(r); });
}

/* გაცემის ფორმა (თანამშრომელი): თავისუფალი ეგზემპლარების არჩევა */
async function ctOpenIssueForm(r) {
  const left = parseInt(r.copy_count, 10) - parseInt(r.issued_count, 10);
  let a;
  try { a = await api(`/api/contracts/available?contract_type=${encodeURIComponent(r.contract_type)}&request_id=${encodeURIComponent(r.request_id)}`); } catch (e) { toast(e.message); return; }
  const rows = a.rows || [];
  openDetail(`გაცემა — ${r.request_id}`, [
    { label: "აგენტი", value: r.agent_name }, { label: "ტიპი", value: r.type_label }, { label: "გასაცემია კიდევ", value: left },
  ], `<div class="qa-compose" style="margin-top:8px">
      <div class="sub"><b>აირჩიეთ ეგზემპლარი (მაქს. ${left})</b> — თავისუფალი: ${rows.length}</div>
      ${rows.length ? rows.map((c, k) => `<label class="chip" style="display:flex;gap:8px;align-items:center;padding:8px"><input type="checkbox" class="ctPick" value="${esc(c.copy_id)}" ${k < left ? "checked" : ""}>
        <span style="font-family:monospace">${esc(c.control_code)}</span> ${c.physical_status === "RESERVED" ? "· დაჯავშნილია" : ""} ${c.storage_location ? "· " + esc(c.storage_location) : ""}</label>`).join("")
        : `<div class="empty">გასაცემად თავისუფალი ეგზემპლარი არ არის — ჯერ დაამატეთ მარაგი: „ხელშეკრულებები“ → „მარაგი“ → „➕ დამატება“</div>`}
      <label class="sub">დაბრუნების ვადა (ცარიელი = სისტემის ნაგულისხმევი ვადა ახლიდან)</label>
      <input id="ctDue" type="datetime-local">
      <input id="ctIssueNote" placeholder="კომენტარი (არასავალდებულო)">
      ${CT_MSG}
      <button class="btn" id="ctIssueGo" ${rows.length ? "" : "disabled"}>📤 გაცემის დადასტურება</button>
    </div>`);
  document.getElementById("ctIssueGo").onclick = async function () {
    const ids = [...document.querySelectorAll(".ctPick:checked")].map((x) => x.value);
    if (!ids.length) { ctErr("აირჩიეთ მინიმუმ ერთი ეგზემპლარი (მონიშნეთ ჩექბოქსი)"); return; }
    if (ids.length > left) { ctErr(`ამ მოთხოვნაზე მაქსიმუმ ${left} ეგზემპლარის გაცემაა შესაძლებელი — მოხსენით ზედმეტი`); return; }
    this.disabled = true;
    this.textContent = "იგზავნება…";
    try {
      const due = document.getElementById("ctDue").value;
      await ctPost(`/api/contracts/requests/${r.request_id}/issue`, { copy_ids: ids, due_at: due ? due.replace("T", " ") : "", notes: document.getElementById("ctIssueNote").value });
      toast("გაცემა დაფიქსირდა ✅"); ctReload();
    } catch (e) { ctErr(e.message); this.disabled = false; this.textContent = "📤 გაცემის დადასტურება"; }
  };
}

/* გაცემის დეტალი (+ დაბრუნების რეგისტრაცია თანამშრომლისთვის) */
function ctOpenIssue(i, caps) {
  const fields = [
    { label: "საკონტროლო კოდი", value: i.control_code }, { label: "აგენტი", value: i.agent_name },
    { label: "ტიპი", value: i.type_label }, { label: "მისამართი", value: i.property_address },
    { label: "მოთხოვნა", value: i.request_id }, { label: "შეხვედრა", value: i.meeting_id },
    { label: "გასცა", value: `${i.issued_by} · ${i.issued_at}` }, { label: "დაბრუნების ვადა", value: i.due_at + (i.overdue ? " ⏰ ვადაგადაცილებული" : "") },
    { label: "დაბრუნდა", value: i.returned_at ? `${i.returned_at} · მიიღო: ${i.received_by}` : "" },
    { label: "შედეგი", value: i.outcome_label }, { label: "მდგომარეობა", value: i.return_condition },
    { label: "მიზეზი", value: i.return_reason }, { label: "ხელმოწერილი ხელშეკრულების №", value: i.signed_contract_number },
    { label: "კომენტარი", value: i.notes },
  ];
  const canReturn = caps && caps.can_handle_physical && i.open;
  openDetail("გაცემა" + (i.control_code ? " — " + i.control_code : ""), fields, canReturn ? `<div class="chip-row" style="margin-top:12px"><button class="btn" id="ctRetBtn">↩️ დაბრუნების რეგისტრაცია</button></div>` : "");
  const b = document.getElementById("ctRetBtn");
  if (b) b.onclick = () => ctOpenReturnForm(i);
}

function ctOpenReturnForm(i) {
  openDetail("დაბრუნება — " + i.control_code, [{ label: "აგენტი", value: i.agent_name }, { label: "დაბრუნების ვადა", value: i.due_at }],
    `<div class="qa-compose" style="margin-top:8px">
      <label class="sub">დაბრუნების შედეგი (შეამოწმეთ დოკუმენტი ფიზიკურად)</label>
      <select id="ctOut">
        <option value="RETURNED_UNUSED">დაბრუნდა გამოუყენებელი</option>
        <option value="USED_SIGNED">ხელმოწერილია / გაფორმდა</option>
        <option value="DAMAGED">დაზიანებულია</option>
        <option value="LOST">დაკარგულია</option>
      </select>
      <label class="chip" id="ctReuseBox" style="display:flex;gap:8px;align-items:center;padding:8px">
        <input type="checkbox" id="ctReuse"> სუფთაა, გამოუყენებელია და ხელახლა გამოსაყენებლად უსაფრთხოა</label>
      <div class="sub" id="ctReuseHint">თუ დოკუმენტზე კლიენტის მონაცემი/ხელმოწერა წერია ან მდგომარეობა გაურკვეველია — არ მონიშნოთ: ეგზემპლარი შემოწმებაზე გადავა და ხელახლა არ გაიცემა.</div>
      <input id="ctCond" placeholder="მდგომარეობა (მაგ. სუფთა / დაჭმუჭნილი)">
      <input id="ctSigned" placeholder="ხელმოწერილი ხელშეკრულების №, თუ არსებობს" hidden>
      <input id="ctReason" placeholder="მიზეზი/შენიშვნა (მაგ. ბინა არ მოეწონა)">
      ${CT_MSG}
      <button class="btn" id="ctRetGo">✅ დაბრუნების დადასტურება</button>
    </div>`);
  const out = document.getElementById("ctOut");
  const sync = () => {
    const unused = out.value === "RETURNED_UNUSED";
    document.getElementById("ctReuseBox").hidden = !unused;
    document.getElementById("ctReuseHint").hidden = !unused;
    document.getElementById("ctSigned").hidden = out.value !== "USED_SIGNED";
  };
  out.onchange = sync; sync();
  document.getElementById("ctRetGo").onclick = async function () {
    this.disabled = true;
    try {
      await ctPost(`/api/contracts/issues/${i.issue_id}/return`, {
        outcome: out.value, reusable: document.getElementById("ctReuse").checked, condition: document.getElementById("ctCond").value,
        reason: document.getElementById("ctReason").value, signed_contract_number: document.getElementById("ctSigned").value,
      });
      toast("დაბრუნება დაფიქსირდა ✅"); ctReload();
    } catch (e) { ctErr(e.message); this.disabled = false; }
  };
}

/* ფიზიკური ეგზემპლარის დეტალი: ისტორია + (თანამშრომლისთვის) შემოწმების გადაწყვეტილება */
async function ctOpenCopy(c, caps) {
  let h = { issues: [] };
  try { h = await api(`/api/contracts/copies/${encodeURIComponent(c.copy_id)}/history`); } catch (e) { toast(e.message); }
  const cc = h.copy || c;
  const fields = [
    { label: "საკონტროლო კოდი", value: cc.control_code }, { label: "ტიპი", value: cc.type_label }, { label: "სტატუსი", value: cc.status_label },
    { label: "შენახვის ადგილი", value: cc.storage_location }, { label: "მდგომარეობა", value: cc.condition }, { label: "დაემატა", value: `${cc.created_at}` },
  ];
  let extra = `<div class="share-box"><div class="lbl">📜 გაცემა/დაბრუნების ისტორია</div>${(h.issues || []).length ? h.issues.map((i) => `
    <div class="sub" style="margin:6px 0">• ${esc(i.agent_name)} · ${esc(i.issued_at)} → ${i.returned_at ? esc(i.returned_at) + " (" + esc(i.outcome_label || i.outcome) + ")" : "ჯერ არ დაუბრუნებია"}</div>`).join("") : `<div class="sub">არ გაცემულა</div>`}</div>`;
  if (h.audit && h.audit.length) extra += `<div class="share-box"><div class="lbl">🧾 აუდიტი</div>${h.audit.map((e) => `<div class="sub">${esc(e.timestamp)} · ${esc(e.action)} · ${esc(e.actor_id)}</div>`).join("")}</div>`;
  if (caps && caps.can_handle_physical && cc.physical_status === "UNDER_REVIEW") {
    extra += `<div class="qa-compose" style="margin-top:12px"><label class="sub">შემოწმების გადაწყვეტილება</label>
      <select id="ctRev"><option value="available">სუფთაა — ხელახლა გამოსაყენებელი (AVAILABLE)</option><option value="signed">ხელმოწერილია (USED_SIGNED)</option>
      <option value="damaged">დაზიანებულია</option><option value="lost">დაკარგულია</option></select>
      <button class="btn" id="ctRevGo">შენახვა</button></div>`;
  }
  openDetail("ეგზემპლარი " + cc.control_code, fields, extra);
  const go = document.getElementById("ctRevGo");
  if (go) go.onclick = async function () {
    this.disabled = true;
    try { await ctPost(`/api/contracts/copies/${cc.copy_id}/review`, { decision: document.getElementById("ctRev").value }); toast("შენახულია ✅"); ctReload(); }
    catch (e) { toast(e.message); this.disabled = false; }
  };
}

/* შეხვედრის დეტალში: ამ შეხვედრის ხელშეკრულებები + "+ ხელშეკრულების მოთხოვნა" (მონაცემები ავტომატურად მოდის შეხვედრიდან) */
async function ctLoadMeetingBox(m) {
  const box = document.getElementById("ctMeetingBox");
  if (!box || !m.meeting_id) return;
  let d;
  try { d = await api("/api/contracts/meeting/" + encodeURIComponent(m.meeting_id)); }
  catch (e) { box.innerHTML = `<div class="lbl">📑 ხელშეკრულებები</div><div class="sub">${esc(e.message)}</div>`; return; }
  const reqs = d.requests || [], issues = d.issues || [];
  box.innerHTML = `<div class="lbl">📑 ხელშეკრულებები</div>
    ${reqs.length ? reqs.map((r) => `<div class="list-row clickable" data-ctm-req="${esc(r.request_id)}"><div class="main">
        <div class="title" style="white-space:normal">${esc(r.type_label)} · ${esc(r.issued_count)}/${esc(r.copy_count)} ეგზ.</div>
        <div class="sub">${esc(r.request_id)} · ${esc(r.request_created_at)}</div></div><div class="side">${ctReqBadge(r)}</div></div>`).join("")
      : `<div class="sub">ამ შეხვედრაზე მოთხოვნა ჯერ არ არის</div>`}
    ${issues.length ? `<div class="sub" style="margin-top:8px"><b>გაცემის ისტორია</b></div>` + issues.map((i) => `<div class="sub">• ${i.control_code ? esc(i.control_code) + " · " : ""}გაიცა ${esc(i.issued_at)} · ვადა ${esc(i.due_at)}${i.returned_at ? " · დაბრუნდა " + esc(i.returned_at) + " (" + esc(i.outcome_label || i.outcome) + ")" : (i.overdue ? " · ⏰ ვადაგადაცილებული" : "")}</div>`).join("") : ""}
    ${d.can_create ? `<button class="btn" id="ctNewReq" style="margin-top:10px">+ ხელშეკრულების მოთხოვნა</button>` : ""}`;
  box.querySelectorAll("[data-ctm-req]").forEach((el) => { el.onclick = () => ctOpenRequest(el.dataset.ctmReq); });
  const nb = document.getElementById("ctNewReq");
  if (nb) nb.onclick = () => ctOpenRequestForm(m, d);
}

/* მოთხოვნის ფორმა: შეხვედრის/კლიენტის/ბინის/აგენტის მონაცემები ავტომატურია (მხოლოდ კითხვადი); აგენტი ირჩევს ტიპს და რაოდენობას */
function ctOpenRequestForm(m, d) {
  const key = ctIdemKey();                  // ერთი ფორმა = ერთი გასაღები: ორმაგი დაჭერა დუბლიკატს არ ქმნის
  const types = d.types || {};
  openDetail("+ ხელშეკრულების მოთხოვნა", [
    { label: "შეხვედრის ID", value: m.meeting_id }, { label: "შეხვედრა", value: `${m.meeting_date || ""} ${m.time || ""}`.trim() },
    { label: "აგენტი", value: m.agent_name }, { label: "მისამართი", value: m.address },
    { label: "MyHome ID", value: m.myhome_id }, { label: "SS.ge ID", value: m.ssge_id },
    { label: "კლიენტის ტელეფონი", value: m.client_phone },
  ], `<div class="qa-compose" style="margin-top:10px">
      <label class="sub">ხელშეკრულების ტიპი</label>
      <select id="ctType"><option value="">— აირჩიეთ —</option>${Object.keys(types).map((k) => `<option value="${esc(k)}">${esc(types[k])}${d.available && d.available[k] != null ? ` (თავისუფალია: ${d.available[k]})` : ""}</option>`).join("")}</select>
      <label class="sub">ეგზემპლარების რაოდენობა</label>
      <input id="ctCopies" type="number" min="1" max="10" value="1">
      <textarea id="ctNotes" rows="2" placeholder="კომენტარი (საჭიროების შემთხვევაში)"></textarea>
      ${CT_MSG}
      <button class="btn" id="ctSend">📑 მოთხოვნის გაგზავნა</button>
    </div>`);
  document.getElementById("ctSend").onclick = async function () {
    const type = document.getElementById("ctType").value;
    const n = parseInt(document.getElementById("ctCopies").value, 10);
    if (!type) { ctErr("აირჩიეთ ხელშეკრულების ტიპი"); return; }
    if (!n || n < 1 || n > 10) { ctErr("რაოდენობა უნდა იყოს 1–10"); return; }
    this.disabled = true;
    try {
      const r = await ctPost("/api/contracts/requests", { meeting_id: m.meeting_id, contract_type: type, copy_count: n, notes: document.getElementById("ctNotes").value, idempotency_key: key });
      toast(r.created ? `მოთხოვნა გაიგზავნა ✅ ${r.request.request_id}` : `ეს მოთხოვნა უკვე არსებობს: ${r.request.request_id}`);
      if (r.stock_warning) alert(r.stock_warning);
      delete lazyCache.contracts;
      closeDetail();
    } catch (e) { ctErr(e.message); this.disabled = false; }
  };
}

/* ---------------------------------------------------------- shell */

const LAZY_ENDPOINTS = {
  contracts: "/api/contracts/overview",
  mydayoffs: "/api/dayoff/mine",
  myattendance: "/api/attendance/me/history",
  attendance: "/api/attendance/overview",
  districts: "/api/districts",
  exclusives: "/api/exclusives",
  myhomejobs: "/api/myhome-jobs",
  myhomestats: "/api/myhome-jobs/stats",
  swaps: "/api/swaps",
  reports: "/api/reports",
  questions: "/api/questions",
  admintasks: "/api/tasks",
  agentsmgmt: "/api/agents",
  meetings: "/api/meetings",
  taskhistory: "/api/task-history",
  digest: "/api/digest",
  dayoffs: "/api/dayoffs",
  agentrequests: "/api/agent-requests",
  regulations: "/api/regulations",
  warnings: "/api/warnings",
  clients: "/api/clients",
  crm2: "/api/crm2/clients",
};
/* ტაბები, რომელთა endpoint-საც სჭირდება ?period=day|week|month —
   period-ის შეცვლისას load() ისედაც წმენდს lazyCache-ს მთლიანად,
   ასე რომ საკმარისია URL-ში დღევანდელი state.period გადავცეთ. */
const PERIOD_AWARE_TABS = new Set(["meetings", "taskhistory", "digest", "reports"]);
/* taskhistory-ს დამატებითი დრილდაუნი (ადმინი: გუნდი → აგენტი). */
if (!state.historyTeam) state.historyTeam = "";
if (!state.historyAgent) state.historyAgent = "";
if (!state.digestTeam) state.digestTeam = "";
/* რეპორტების ისტორიის დრილდაუნი + კონკრეტული თარიღი. */
if (!state.reportsTeam) state.reportsTeam = "";
if (!state.reportsAgent) state.reportsAgent = "";
if (!state.reportsDate) state.reportsDate = "";
/* თიმლიდერისთვის: შეხვედრების ჩვენება „გუნდის" ან „საკუთარი" ჭრილში. */
if (!state.meetingsScope) state.meetingsScope = "team";
/* გაფრთხილებების ტაბის ფილტრები (აგენტი/მენეჯერი) — client-side. */
if (!state.mhLimit) state.mhLimit = 150;
if (!state.warningsAgentFilter) state.warningsAgentFilter = "";
if (!state.warningsManagerFilter) state.warningsManagerFilter = "";
if (!state.warnSel) state.warnSel = new Set();

/* ===================================================== CRM 2.0 (P2.3b) =====
   ახალი "CRM" ტაბი: კლიენტების სია → ბარათი (ისტორია, follow-up-ები, შენიშვნა).
   მონაცემი: /api/crm2/... (ხილვადობა სერვერზეა: ადმინი ყველა / თიმლიდერი გუნდი /
   აგენტი მხოლოდ საკუთარი). არსებულ ტაბებს არ ეხება. */
const CRM2_STATUS_LABELS = {
  new: "ახალი", contacted: "დაკავშირებული", viewing: "ჩვენება", negotiation: "მოლაპარაკება",
  won: "დაიხურა ✅", lost: "დაიკარგა", inactive: "პასიური",
};
const CRM2_ACT_ICONS = { call: "📞", meeting: "📍", note: "📝", task: "📋", report: "📝", job: "🌐", system: "⚙️" };

/* UTC ISO (…Z) -> მოკლე ლოკალური დრო (თბილისი) */
function _crm2Time(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("ka-GE", { timeZone: "Asia/Tbilisi", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function _crm2RowsHtml(rows) {
  if (!rows.length) return `<div class="empty">კლიენტი ვერ მოიძებნა</div>`;
  return rows.map((c, i) => `
    <div class="list-row clickable" data-crm2-idx="${i}">
      <div class="avatar">${c.overdue_followups ? "⏰" : "👤"}</div>
      <div class="main">
        <div class="title">${esc(c.name || c.phone_raw || c.phone_norm)}</div>
        <div class="sub">${esc(c.phone_raw || c.phone_norm)} · ${esc(CRM2_STATUS_LABELS[c.status] || c.status || "-")}</div>
        <div class="sub">${esc(c.assigned_agent_name || "—")}${c.open_followups ? ` · ⏳ ${c.open_followups}${c.overdue_followups ? ` (⚠️ ვადაგადაცილებული ${c.overdue_followups})` : ""}` : ""}</div>
      </div>
      <div class="side sub">${esc(_crm2Time(c.last_activity_at))}</div>
    </div>`).join("");
}

function renderCrm2(rows) {
  rows = rows || [];
  return `<div class="card">
    <h2>🗃️ CRM — კლიენტები <span class="cnt">${rows.length}</span></h2>
    <div class="qa-compose">
      <input id="crm2Search" placeholder="ძებნა — სახელი ან ტელეფონი" />
    </div>
    <div id="crm2List">${_crm2RowsHtml(rows)}</div>
  </div>`;
}

function bindCrm2Actions(rows) {
  rows = rows || [];
  const input = document.getElementById("crm2Search");
  const bindRows = (list) => {
    document.querySelectorAll("[data-crm2-idx]").forEach((el) => {
      el.onclick = () => openCrm2Card(list[parseInt(el.dataset.crm2Idx, 10)]);
    });
  };
  if (input) {
    input.oninput = () => {
      const q = input.value.trim().toLowerCase();
      let digits = q.replace(/\D/g, "");
      if (digits.startsWith("995") && digits.length > 3) digits = digits.slice(3);
      else if (digits.startsWith("0") && digits.length > 1) digits = digits.slice(1);
      const list = !q ? rows : rows.filter((c) =>
        String(c.name || "").toLowerCase().includes(q)
        || (digits && String(c.phone_norm || "").includes(digits)));
      document.getElementById("crm2List").innerHTML = _crm2RowsHtml(list);
      bindRows(list);
    };
  }
  bindRows(rows);
}

function _crm2CardHtml(res) {
  const c = res.client || {};
  const open = (res.followups || []).filter((f) => f.status === "open")
    .sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)));
  const nowIso = new Date().toISOString();
  const fuHtml = open.length ? open.map((f) => `
    <div class="list-row">
      <div class="avatar">${String(f.due_at) < nowIso ? "⚠️" : "⏳"}</div>
      <div class="main" style="overflow:visible">
        <div class="title" style="white-space:normal">${esc(f.next_action)}</div>
        <div class="sub">${esc(_crm2Time(f.due_at))} · ${esc(f.agent_name || "")}</div>
      </div>
      <button class="btn secondary" data-fu-done="${esc(f.followup_id)}" style="padding:7px 10px">✅</button>
    </div>`).join("") : `<div class="empty">ღია follow-up არ არის</div>`;
  const tl = res.timeline || [];
  const tlHtml = tl.length ? tl.map((a) => `
    <div class="list-row">
      <div class="avatar">${CRM2_ACT_ICONS[a.type] || "•"}</div>
      <div class="main" style="overflow:visible">
        <div class="title" style="white-space:normal">${esc(a.summary)}</div>
        <div class="sub">${esc(a.agent_name || "")} · ${esc(_crm2Time(a.created_at))}</div>
      </div>
    </div>`).join("") : `<div class="empty">ისტორია ცარიელია</div>`;
  return `
    <h3>${esc(c.name || c.phone_raw || c.phone_norm)}<button class="close" id="modalClose">✕</button></h3>
    <div class="field"><div class="k">ტელეფონი</div><div class="v">${esc(c.phone_raw || c.phone_norm)}</div></div>
    <div class="field"><div class="k">სტატუსი · აგენტი</div><div class="v">${esc(CRM2_STATUS_LABELS[c.status] || c.status || "-")} · ${esc(c.assigned_agent_name || "—")}</div></div>
    <h3 style="margin-top:14px">⏳ Follow-up-ები</h3>
    ${fuHtml}
    <div class="qa-compose">
      <input id="fuAction" maxlength="500" placeholder="შემდეგი ქმედება (მაგ. დარეკე თავიდან)" />
      <input id="fuDue" type="date" />
      <button class="btn" id="fuAdd">➕ Follow-up-ის დამატება</button>
    </div>
    <h3 style="margin-top:14px">📝 შენიშვნა</h3>
    <div class="qa-compose">
      <textarea id="crm2Note" maxlength="2000" placeholder="რა მოხდა კლიენტთან?"></textarea>
      <button class="btn secondary" id="crm2NoteAdd">💾 შენიშვნის შენახვა</button>
    </div>
    <h3 style="margin-top:14px">🕘 ისტორია</h3>
    ${tlHtml}`;
}

async function openCrm2Card(c) {
  if (!c) return;
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  box.innerHTML = `<h3>${esc(c.name || c.phone_raw || c.phone_norm)}<button class="close" id="modalClose">✕</button></h3><div class="empty">იტვირთება…</div>`;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };

  const refresh = async () => {
    const res = await api(`/api/crm2/clients/${encodeURIComponent(c.client_id)}`);
    box.innerHTML = _crm2CardHtml(res);
    document.getElementById("modalClose").onclick = () => { closeDetail(); delete lazyCache.crm2; renderContent(); };
    box.querySelectorAll("[data-fu-done]").forEach((b) => {
      b.onclick = async () => {
        b.disabled = true;
        try {
          await api(`/api/crm2/followups/${encodeURIComponent(b.dataset.fuDone)}/close`, { method: "POST", body: JSON.stringify({ status: "done" }) });
          toast("✅ დაიხურა");
          await refresh();
        } catch (e) { toast(e.message || "შეცდომა"); b.disabled = false; }
      };
    });
    document.getElementById("fuAdd").onclick = async () => {
      const action = (document.getElementById("fuAction").value || "").trim();
      const due = document.getElementById("fuDue").value;
      if (!action) { toast("ჩაწერეთ შემდეგი ქმედება"); return; }
      if (!due) { toast("აირჩიეთ თარიღი"); return; }
      const btn = document.getElementById("fuAdd");
      btn.disabled = true;
      try {
        await api(`/api/crm2/clients/${encodeURIComponent(c.client_id)}/followups`, { method: "POST", body: JSON.stringify({ next_action: action, due_at: due }) });
        toast("✅ დაემატა");
        await refresh();
      } catch (e) { toast(e.message || "შეცდომა"); btn.disabled = false; }
    };
    document.getElementById("crm2NoteAdd").onclick = async () => {
      const text = (document.getElementById("crm2Note").value || "").trim();
      if (!text) { toast("ჩაწერეთ ტექსტი"); return; }
      const btn = document.getElementById("crm2NoteAdd");
      btn.disabled = true;
      try {
        await api(`/api/crm2/clients/${encodeURIComponent(c.client_id)}/notes`, { method: "POST", body: JSON.stringify({ text }) });
        toast("✅ შენახულია");
        await refresh();
      } catch (e) { toast(e.message || "შეცდომა"); btn.disabled = false; }
    };
  };
  try { await refresh(); }
  catch (e) { box.innerHTML += `<div class="empty">⚠️ ${esc(e.message)}</div>`; }
}

/* ================================================ ფინანსური ტრეკერი (დირექტორის ტაბი) =====
   წვდომა მხოლოდ სერვერზე მითითებულ Telegram ID-ებს (Railway: FINANCE_CHAT_IDS). ტაბი ჩანს მხოლოდ მაშინ, როცა
   /api/finance/access აბრუნებს allowed=true; რეალურ შემოწმებას სერვერი აკეთებს ყოველ მოთხოვნაზე.
   არსებულ ტაბებს არ ეხება: ემატება tabsFor-ში, renderContent-ში და load()-ის ბოლოს. */
const FIN_TAB = { id: "finance", label: "ფინანსები", icon: "💰" };
const FIN_SECTIONS = [["dash", "📊 დაშბორდი"], ["deals", "🧾 გარიგებები"], ["exp", "💸 ხარჯები"], ["rep", "📑 ანგარიში"], ["rem", "🔔 შეხსენებები"]];
const FIN_C = { income: "#e9c46a", exp: "#f26d6d", profit: "#34d399", agents: "#4aa8d8", tl: "#a78bfa" };
state.fin = state.fin || { section: "dash", from: "", to: "", q: "", agent: "", seq: 0 };

const finGet = (path) => api(path);
const finSend = (method, path, body) => api(path, { method, body: JSON.stringify(body || {}) });
function finNow() { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0"); }
function finAdd(ym, n) { const p = ym.split("-").map(Number); const t = p[0] * 12 + (p[1] - 1) + n; return Math.floor(t / 12) + "-" + String(t % 12 + 1).padStart(2, "0"); }
function finEnsureRange() { const f = state.fin; if (!f.to) f.to = finNow(); if (!f.from) f.from = finAdd(f.to, -11); }
function finQS() { finEnsureRange(); return "from=" + encodeURIComponent(state.fin.from) + "&to=" + encodeURIComponent(state.fin.to); }
function finMoney(n, cur) {
  const v = Number(n || 0);
  return v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 }) + (cur === "USD" ? " $" : " ₾");
}
function finShort(n) { const a = Math.abs(n); return (n < 0 ? "-" : "") + (a >= 1000 ? (Math.round(a / 100) / 10) + "k" : Math.round(a)); }
/* "2,5" → "2.5"; "1,200.50" → "1200.50" (ათწილადი მძიმე არ უნდა აღიქვას ათასების გამყოფად) */
function finNum(s) { s = String(s == null ? "" : s).trim().replace(/\s+/g, ""); if (s.includes(",") && !s.includes(".")) s = s.replace(",", "."); return s.replace(/,/g, ""); }
function finMoLabel(ym) { const p = String(ym).split("-"); return p[1] + "/" + p[0].slice(2); }
function finToneClass(v) { return v < 0 ? "neg" : "pos"; }

/* ---------------------------------------------------------------- დიაგრამები (SVG, გარე ბიბლიოთეკის გარეშე) */
function finChart(series) {
  if (!series.length) return "";
  const n = series.length, colW = Math.max(30, Math.min(52, Math.floor(340 / n))), barW = Math.max(7, Math.floor(colW * 0.32));
  const padL = 4, padR = 4, padT = 14, padB = 22, H = 190, W = padL + padR + n * colW;
  const maxV = Math.max(1, ...series.map((s) => Math.max(s.company_income, s.expenses, s.profit)));
  const minV = Math.min(0, ...series.map((s) => s.profit));
  const rng = maxV - minV, plotH = H - padT - padB;
  const Y = (v) => padT + ((maxV - v) / rng) * plotH, y0 = Y(0);
  let g = "";
  for (let i = 0; i <= 3; i++) {
    const v = minV + (rng * i) / 3, y = Y(v);
    g += `<line x1="0" x2="${W}" y1="${y}" y2="${y}" stroke="rgba(147,166,188,.16)"/><text x="2" y="${y - 2}" class="chart-lbl">${finShort(v)}</text>`;
  }
  const bar = (cx, v, color) => {
    const y = Math.min(Y(v), y0), h = Math.max(1, Math.abs(Y(v) - y0));
    return `<rect x="${cx}" y="${y}" width="${barW}" height="${h}" rx="3" fill="${color}"/>`;
  };
  let bars = "", pts = [], hits = "", labels = "";
  series.forEach((s, i) => {
    const cx = padL + i * colW + colW / 2;
    bars += bar(cx - barW - 1, s.company_income, FIN_C.income) + bar(cx + 1, s.expenses, FIN_C.exp);
    pts.push([cx, Y(s.profit)]);
    labels += `<text x="${cx}" y="${H - 6}" text-anchor="middle" class="chart-lbl">${finMoLabel(s.month)}</text>`;
    hits += `<rect data-fin-mo="${i}" x="${padL + i * colW}" y="0" width="${colW}" height="${H}" fill="transparent" style="cursor:pointer"/>`;
  });
  const line = `<polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="${FIN_C.profit}" stroke-width="2" stroke-linejoin="round"/>`
    + pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="${FIN_C.profit}"/>`).join("");
  return `<div class="fin-scroll"><svg viewBox="0 0 ${W} ${H}" style="min-width:${W}px;width:100%;display:block">${g}${bars}${line}${labels}${hits}</svg></div>`;
}

function finDonut(parts) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  if (!total) return `<div class="empty">მონაცემი ჯერ არ არის</div>`;
  let off = 25;
  const segs = parts.filter((p) => p.value > 0).map((p) => {
    const pc = (p.value / total) * 100;
    const s = `<circle r="15.9155" cx="21" cy="21" fill="transparent" stroke="${p.color}" stroke-width="6" stroke-dasharray="${pc} ${100 - pc}" stroke-dashoffset="${off}"/>`;
    off -= pc;
    return s;
  }).join("");
  return `<div class="fin-donut">
    <svg viewBox="0 0 42 42" width="132" height="132">
      <circle r="15.9155" cx="21" cy="21" fill="transparent" stroke="rgba(147,166,188,.12)" stroke-width="6"/>${segs}
      <text x="21" y="20.5" text-anchor="middle" style="font-size:5px;font-weight:800;fill:var(--text)">${finShort(total)}</text>
      <text x="21" y="26" text-anchor="middle" style="font-size:3px;fill:var(--hint)">საკომისიო ₾</text>
    </svg>
    <div class="fin-legend">${parts.map((p) => `<div><span class="dot" style="background:${p.color}"></span>${esc(p.label)}<b>${finMoney(p.value)}</b><span class="pc">${Math.round((p.value / total) * 100)}%</span></div>`).join("")}</div>
  </div>`;
}

function finBars(rows, key, color, empty) {
  if (!rows.length) return `<div class="empty">${esc(empty || "მონაცემი ჯერ არ არის")}</div>`;
  const max = Math.max(1, ...rows.map((r) => r[key]));
  return rows.map((r) => `<div class="bar-row"><div class="top"><span>${esc(r.name)}${r.deals ? ` <span style="color:var(--hint);font-weight:500">· ${r.deals}</span>` : ""}</span><span>${finMoney(r[key])}</span></div>
    <div class="track"><div class="fill" style="width:${Math.max(2, (r[key] / max) * 100)}%;${color ? `background:${color};box-shadow:none` : ""}"></div></div></div>`).join("");
}

/* ---------------------------------------------------------------- მთავარი ხედი */
async function renderFinance(content) {
  const f = state.fin, acc = state.finAccess || {};
  if (!acc.allowed) {
    content.innerHTML = acc.setup
      ? `<div class="card"><h2>💰 ფინანსური ტრეკერი — ჩასართავია</h2>
          <div class="sub" style="white-space:normal;line-height:1.55">ფინანსურ ტაბს მხოლოდ ის Telegram ID ხედავს, რომელიც სერვერზეა მითითებული. დაყენება (ერთხელ):<br>
          1) Railway → თქვენი პროექტი → <b>Variables</b><br>2) ახალი ცვლადი: <b>FINANCE_CHAT_IDS</b> = <b style="font-family:monospace;user-select:all">${esc(acc.your_id)}</b><br>
          3) შეინახეთ და დაელოდეთ ხელახალ გაშვებას, შემდეგ თავიდან გახსენით Mini App.<br>
          ამის შემდეგ ტაბი ჩანს მხოლოდ ამ ID-ზე — სხვა ადმინებს/მენეჯერებს ვერ დაინახავენ.</div>
          <div class="chip-row" style="margin-top:12px"><button class="btn" id="finCopyId">📋 ID-ის კოპირება</button></div></div>`
      : `<div class="card"><div class="empty">ამ განყოფილებაზე წვდომა არ გაქვთ</div></div>`;
    const cp = document.getElementById("finCopyId");
    if (cp) cp.onclick = () => { try { navigator.clipboard.writeText(String(acc.your_id)); toast("დაკოპირდა"); } catch (e) { toast("ID: " + acc.your_id); } };
    return;
  }
  finEnsureRange();
  const seq = ++f.seq;
  content.innerHTML = `<div class="card"><div class="empty">იტვირთება…</div></div>`;
  let dash, extra = null;
  try {
    dash = await finGet("/api/finance/dashboard?" + finQS());
    if (f.section === "deals") extra = await finGet("/api/finance/deals?" + finQS() + "&q=" + encodeURIComponent(f.q) + "&agent_id=" + encodeURIComponent(f.agent)
      + "&ptype=" + encodeURIComponent(f.ptype || "") + "&cur=" + encodeURIComponent(f.cur || "") + "&exp=" + encodeURIComponent(f.exp || ""));
    else if (f.section === "exp") extra = await finGet("/api/finance/expenses?" + finQS());
  } catch (e) {
    if (seq !== f.seq) return;
    content.innerHTML = `<div class="card"><div class="empty">⚠️ ${esc(e.message)}</div><div class="chip-row" style="justify-content:center"><button class="btn secondary" id="finRetry">თავიდან ცდა</button></div></div>`;
    document.getElementById("finRetry").onclick = () => renderContent();
    return;
  }
  if (seq !== f.seq || state.tab[state.role] !== "finance") return; // ამასობაში სხვა ტაბზე გადავიდა
  state.finDash = dash;
  content.innerHTML = finShell(dash) + finBody(dash, extra);
  finBind(dash, extra);
}

function finShell(d) {
  const f = state.fin, rem = d.reminders || {};
  const rc = (rem.report_due || []).length + (rem.expiring || []).length + (rem.expired || []).length;
  const sections = FIN_SECTIONS.map(([id, l]) => `<button data-fin-sec="${id}" class="${f.section === id ? "active" : ""}">${l}${id === "rem" && rc ? ` <span class="badge red">${rc}</span>` : ""}</button>`).join("");
  const now = finNow();
  const presets = [["ეს თვე", now, now], ["3 თვე", finAdd(now, -2), now], ["6 თვე", finAdd(now, -5), now], ["ეს წელი", now.slice(0, 4) + "-01", now], ["12 თვე", finAdd(now, -11), now]];
  return `<div class="card"><div class="period-switch fin-sec" id="finSections">${sections}</div>
    ${f.section === "rem" ? "" : `<div class="fin-range">
      <input type="month" id="finFrom" value="${esc(f.from)}"><span>—</span><input type="month" id="finTo" value="${esc(f.to)}">
    </div>
    <div class="chip-row">${presets.map(([l, a, b]) => `<button class="chip ${f.from === a && f.to === b ? "sel" : ""}" data-fin-preset="${a}|${b}">${l}</button>`).join("")}</div>`}
  </div>`;
}

function finBody(d, extra) {
  const f = state.fin;
  if (f.section === "deals") return finDealsView(d, extra);
  if (f.section === "exp") return finExpensesView(d, extra);
  if (f.section === "rep") return finReportView(d);
  if (f.section === "rem") return finRemindersView(d);
  return finDashView(d);
}

function finDashView(d) {
  const s = d.summary, t = s.totals, ds = s.distribution, rem = d.reminders || {};
  const stat = (n, l, cls) => `<div class="stat"><div class="num fin-num ${cls || ""}">${n}</div><div class="lbl">${esc(l)}</div></div>`;
  let h = "";
  if (s.unconverted_usd) h += `<div class="card" style="border-color:rgba(245,185,66,.5)"><div class="sub" style="white-space:normal;color:var(--amber);font-weight:650">⚠️ ${s.unconverted_usd.deals} გარიგება დოლარშია და ჯერ არ ჩაითვალა ჯამებში — ქვემოთ მიუთითეთ დოლარის კურსი.</div></div>`;
  const rc = (rem.report_due || []).length, ec = (rem.expiring || []).length, xc = (rem.expired || []).length;
  if (rc + ec + xc) h += `<div class="card fin-alert" data-fin-go="rem"><b>🔔 ყურადღება:</b> ${rc ? `რეპორტინგი: <b>${rc}</b> · ` : ""}${ec ? `იწურება: <b>${ec}</b> · ` : ""}${xc ? `ვადაგასული: <b>${xc}</b>` : ""}<span style="float:right">›</span></div>`;
  h += `<div class="card"><h2>💰 შეჯამება <span class="cnt">${finMoLabel(s.from)} — ${finMoLabel(s.to)}</span></h2>
    <div class="grid3">
      ${stat(finMoney(t.company_income), "კომპანიის შემოსავალი", "gold")}
      ${stat(finMoney(t.expenses), "ხარჯები", "")}
      ${stat(finMoney(t.profit), "წმინდა მოგება", finToneClass(t.profit))}
      ${stat(t.margin_pct == null ? "—" : t.margin_pct + "%", "მარჟა", finToneClass(t.profit))}
      ${stat(finMoney(t.commission), "სრული საკომისიო", "")}
      ${stat(t.deals, "გარიგება", "")}
      ${stat(finMoney(t.agent_payout), "აგენტებს", "")}
      ${stat(finMoney(t.tl_payout), "თიმლიდერებს", "")}
      ${stat(finMoney(t.deals ? t.commission / t.deals : 0), "საშ. საკომისიო", "")}
    </div></div>`;
  h += `<div class="card"><h2>📈 შემოსავალი / ხარჯი / მოგება</h2>
    <div class="fin-legend inline"><span><i class="dot" style="background:${FIN_C.income}"></i>შემოსავალი</span><span><i class="dot" style="background:${FIN_C.exp}"></i>ხარჯი</span><span><i class="dot" style="background:${FIN_C.profit}"></i>მოგება</span></div>
    ${finChart(s.series)}<div class="sub" id="finMoInfo" style="white-space:normal;margin-top:6px">დააჭირეთ თვის სვეტს დეტალებისთვის</div></div>`;
  h += `<div class="card"><h2>🥧 საკომისიოს განაწილება</h2>${finDonut([
    { label: "კომპანია", value: ds.company, color: FIN_C.income }, { label: "აგენტები", value: ds.agents, color: FIN_C.agents }, { label: "თიმლიდერები", value: ds.team_leaders, color: FIN_C.tl }])}</div>`;
  h += `<div class="card"><h2>🏆 აგენტები — კომპანიის შემოსავალი</h2>${finBars([...s.by_agent].sort((a, b) => b.company_income - a.company_income).slice(0, 10), "company_income")}</div>`;
  h += `<div class="card"><h2>📍 რაიონები — კომპანიის შემოსავალი</h2>${finBars(s.by_district.slice(0, 8), "company_income")}</div>`;
  h += `<div class="card"><h2>🏠 ქონების ტიპი</h2>${finBars(s.by_property_type, "company_income")}</div>`;
  h += `<div class="card"><h2>💸 ხარჯები კატეგორიებით</h2>${finBars(s.expenses_by_category.map((c) => ({ name: c.name, amount: c.amount })), "amount", FIN_C.exp, "ხარჯი ამ პერიოდში არ არის")}</div>`;
  h += `<div class="card"><h2>⭐ საუკეთესო გარიგებები</h2>${s.top_deals.length ? s.top_deals.map((x) => `<div class="list-row clickable" data-fin-deal="${esc(x.deal_id)}"><div class="main"><div class="title" style="white-space:normal">${esc(x.address || x.invoice_no || "—")}</div><div class="sub">${esc(x.date)} · ${esc(x.agent_name || "—")}</div></div><div class="side"><b>${finMoney(x.company_income)}</b></div></div>`).join("") : `<div class="empty">გარიგება არ არის</div>`}</div>`;
  h += `<div class="card"><h2>⚙️ დოლარის კურსი</h2><div class="qa-compose"><input id="finRate" inputmode="decimal" placeholder="მაგ. 2.70" value="${d.usd_rate == null ? "" : esc(d.usd_rate)}">
    <button class="btn" id="finRateSave">შენახვა</button></div><div class="sub" style="white-space:normal;margin-top:6px">USD გარიგებები/ხარჯები ჯამებში ლარად გადაითვლება ამ კურსით (1 $ = X ₾). ერთი კურსი ყველა პერიოდზე.</div></div>`;
  return h;
}

function finDealRow(d) {
  let badge = "";
  if (d.contract_expiry) {
    const days = Math.round((new Date(d.contract_expiry + "T00:00:00") - new Date(new Date().toDateString())) / 864e5);
    badge = days < 0 ? `<span class="badge red">ვადაგასული</span>` : days <= 60 ? `<span class="badge amber">${days} დღე</span>` : "";
  }
  return `<div class="list-row clickable" style="align-items:flex-start" data-fin-deal="${esc(d.deal_id)}"><div class="avatar">🧾</div>
    <div class="main"><div class="title" style="white-space:normal">${esc(d.address || d.recipient || "—")}</div>
      <div class="sub">${esc(d.date)} · ${esc(d.invoice_no)}${d.district ? " · " + esc(d.district) : ""}</div>
      <div class="sub">${esc(d.agent_name || "—")} · საკომისიო ${finMoney(d.commission, d.currency)}</div></div>
    <div class="side"><b>${finMoney(d.company_income, d.currency)}</b><div>${badge}</div></div></div>`;
}

function finDealsView(d, x) {
  const f = state.fin, agents = d.lookups.agents;
  return `<div class="card"><div class="qa-compose">
      <input id="finQ" type="search" placeholder="🔎 ძებნა: ინვოისი, ტელეფონი, პირადი №, მისამართი, ვადა, კლიენტი…" value="${esc(f.q)}">
      <select id="finAgentF"><option value="">ყველა აგენტი</option>${agents.map((a) => `<option value="${esc(a.agent_id)}" ${f.agent === a.agent_id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>
      <select id="finTypeF"><option value="">ყველა ტიპი</option>${d.lookups.property_types.map((p) => `<option value="${esc(p)}" ${f.ptype === p ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
      <select id="finCurF"><option value="">ყველა ვალუტა</option><option value="GEL" ${f.cur === "GEL" ? "selected" : ""}>₾ GEL</option><option value="USD" ${f.cur === "USD" ? "selected" : ""}>$ USD</option></select>
      <select id="finExpF"><option value="">ვადა: ყველა</option><option value="soon" ${f.exp === "soon" ? "selected" : ""}>იწურება (≤60 დღე)</option><option value="expired" ${f.exp === "expired" ? "selected" : ""}>ვადაგასული</option><option value="none" ${f.exp === "none" ? "selected" : ""}>ვადის გარეშე</option></select>
      <div class="chip-row"><button class="btn" id="finNewDeal">➕ ახალი გარიგება</button><button class="btn secondary" id="finCsvDeals">📤 CSV</button></div>
    </div>
    <h2 style="margin-top:12px">🧾 გარიგებები <span class="cnt">${x.count}</span></h2>
    ${x.rows.length ? x.rows.map(finDealRow).join("") : `<div class="empty">ამ პერიოდში გარიგება არ არის</div>`}
    ${x.count > x.rows.length ? `<div class="sub" style="text-align:center;margin-top:8px">ნაჩვენებია პირველი ${x.rows.length} — დააზუსტეთ პერიოდი/ძებნა</div>` : ""}</div>`;
}

function finExpenseRow(e) {
  return `<div class="list-row clickable" data-fin-exp="${esc(e.expense_id)}"><div class="avatar">💸</div>
    <div class="main"><div class="title" style="white-space:normal">${esc(e.category)}${e.description ? " — " + esc(e.description) : ""}</div>
      <div class="sub">${esc(e.date)}${e.recurring === "yes" ? ` · ყოველთვიური${e.until_month ? " (" + esc(e.until_month) + "-მდე)" : ""}` : ""}</div></div>
    <div class="side"><b>${finMoney(e.amount, e.currency)}</b>${e.recurring === "yes" ? `<div><span class="badge amber">🔁</span></div>` : ""}</div></div>`;
}

function finExpensesView(d, x) {
  return `<div class="card"><div class="chip-row"><button class="btn" id="finNewExp">➕ ახალი ხარჯი</button><button class="btn secondary" id="finCsvExp">📤 CSV</button></div>
    <h2 style="margin-top:12px">💸 ხარჯები <span class="cnt">${x.count}</span></h2>
    ${x.rows.length ? x.rows.map(finExpenseRow).join("") : `<div class="empty">ამ პერიოდში ხარჯი არ არის</div>`}
    <div class="sub" style="white-space:normal;margin-top:8px">🔁 ყოველთვიური ხარჯი ითვლება დაწყების თვიდან ყოველ თვეს (ან მითითებულ თვემდე).</div></div>`;
}

function finReportView(d) {
  const s = d.summary, t = s.totals;
  const trs = (rows, key) => rows.length ? rows.map((r) => `<div class="list-row"><div class="main"><div class="title" style="white-space:normal">${esc(r.name)}</div>
      <div class="sub">${r.deals} გარიგება · საკომისიო ${finMoney(r.commission)}</div></div><div class="side"><b>${finMoney(r[key])}</b></div></div>`).join("") : `<div class="empty">მონაცემი არ არის</div>`;
  return `<div class="card"><h2>📑 ანგარიში <span class="cnt">${finMoLabel(s.from)} — ${finMoLabel(s.to)}</span></h2>
      <div class="list-row"><div class="main"><div class="title">გარიგება</div></div><div class="side"><b>${t.deals}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">რეალიზაციის ჯამი</div></div><div class="side"><b>${finMoney(t.value)}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">სრული საკომისიო</div></div><div class="side"><b>${finMoney(t.commission)}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">აგენტებს გადასახდელი</div></div><div class="side"><b>${finMoney(t.agent_payout)}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">თიმლიდერებს გადასახდელი</div></div><div class="side"><b>${finMoney(t.tl_payout)}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">კომპანიის შემოსავალი</div></div><div class="side"><b style="color:${FIN_C.income}">${finMoney(t.company_income)}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">ხარჯები</div></div><div class="side"><b>${finMoney(t.expenses)}</b></div></div>
      <div class="list-row"><div class="main"><div class="title">წმინდა მოგება</div></div><div class="side"><b style="color:${t.profit < 0 ? "var(--red)" : "var(--green)"}">${finMoney(t.profit)}</b></div></div>
      <div class="chip-row" style="margin-top:12px"><button class="btn secondary" id="finCsvDeals">📤 გარიგებები CSV</button><button class="btn secondary" id="finCsvExp">📤 ხარჯები CSV</button></div>
      <div class="sub" style="white-space:normal;margin-top:6px">CSV ფაილი გამოგეგზავნებათ Telegram-ში (ქართული სათაურებით, Excel/Google Sheets-ში იხსნება).</div></div>
    <div class="card"><h2>🧑‍💼 აგენტების მიხედვით <span class="cnt">${s.by_agent.length}</span></h2>${trs(s.by_agent, "company_income")}<div class="sub" style="margin-top:6px">მარჯვნივ — კომპანიის შემოსავალი</div></div>
    <div class="card"><h2>👥 თიმლიდერების მიხედვით</h2>${trs(s.by_team_leader, "tl_payout")}<div class="sub" style="margin-top:6px">მარჯვნივ — თიმლიდერის წილი</div></div>
    <div class="card"><h2>📍 რაიონების მიხედვით</h2>${trs(s.by_district, "company_income")}</div>
    <div class="card"><h2>🏠 ქონების ტიპის მიხედვით</h2>${trs(s.by_property_type, "company_income")}</div>`;
}

function finRemRow(r, kind) {
  const right = kind === "report" ? `<span class="badge amber">${r.months} თვე</span>`
    : kind === "expiring" ? `<span class="badge amber">${r.days_left} დღე</span>` : `<span class="badge red">${-r.days_left} დღით ვადაგასული</span>`;
  return `<div class="list-row" style="align-items:flex-start"><div class="main clickable" data-fin-deal="${esc(r.deal_id)}" style="cursor:pointer">
      <div class="title" style="white-space:normal">${esc(r.address || "—")}</div>
      <div class="sub">${esc(r.client_name || "—")} · ${esc(r.agent_name || "—")} · ${esc(r.invoice_no)}</div>
      ${kind !== "report" ? `<div class="sub">ვადა: ${esc(r.contract_expiry)}</div>` : `<div class="sub">ხელშეკრულებიდან: ${esc(r.date)}</div>`}</div>
    <div class="side">${right}${kind === "report" ? `<div style="margin-top:6px"><button class="btn" data-fin-done="${esc(r.deal_id)}" style="padding:7px 9px;font-size:12px">✅ გაკეთდა</button></div>` : ""}</div></div>`;
}

function finRemindersView(d) {
  const r = d.reminders || {};
  const sec = (title, rows, kind, empty) => `<div class="card"><h2>${title} <span class="cnt">${rows.length}</span></h2>${rows.length ? rows.map((x) => finRemRow(x, kind)).join("") : `<div class="empty">${empty}</div>`}</div>`;
  return sec("📊 რეპორტინგის დრო", r.report_due || [], "report", "ამ თვეს რეპორტინგი არავისზე გმართებთ ✅")
    + sec("⏳ ხელშეკრულება იწურება", r.expiring || [], "expiring", "მალე ვადა არავის გასდის ✅")
    + sec("⛔ ვადაგასული", r.expired || [], "expired", "ვადაგასული არ არის ✅")
    + `<div class="card"><div class="sub" style="white-space:normal">ℹ️ რეპორტინგი — ყოველ N თვეში ხელშეკრულების გაფორმებიდან (ნაგულისხმევად 2). ვადის შეხსენება — ვადამდე 60 და 30 დღით ადრე. ეს შეხსენებები Telegram-შიც მოგივათ ყოველდღე 10:00-ზე (ერთხელ თითო მოვლენაზე). პარამეტრები ცალკე გარიგებაზე იცვლება.</div></div>`;
}

/* ---------------------------------------------------------------- მოდალები */
function finModal(title, html) {
  const backdrop = document.getElementById("modalBackdrop"), box = document.getElementById("modalBox");
  box.innerHTML = `<h3>${esc(title)}<button class="close" id="modalClose">✕</button></h3>${html}`;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
}
const FIN_MSG = `<div id="finMsg" class="sub" hidden style="color:var(--red);font-weight:650;white-space:normal"></div>`;
function finErr(msg) { const el = document.getElementById("finMsg"); if (el) { el.textContent = "⚠️ " + msg; el.hidden = false; } else toast(msg); }
function finIn(id, label, val, attrs) { return `<label class="fin-l" for="${id}">${esc(label)}</label><input id="${id}" value="${esc(val == null ? "" : val)}" ${attrs || ""}>`; }
function finSel(id, label, opts, sel, first) {
  const list = opts.slice(); if (sel && !list.some((o) => o[0] === sel)) list.push([sel, sel]);
  return `<label class="fin-l" for="${id}">${esc(label)}</label><select id="${id}">${first != null ? `<option value="">${esc(first)}</option>` : ""}${list.map(([v, l]) => `<option value="${esc(v)}" ${v === sel ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
}
const finV = (id) => { const el = document.getElementById(id); return el ? el.value : ""; };

async function finOpenDeal(id) {
  let x;
  try { x = (await finGet("/api/finance/deals/" + encodeURIComponent(id))).deal; } catch (e) { toast(e.message); return; }
  const c = x.currency;
  const fields = [
    ["ინვოისის ნომერი", x.invoice_no], ["თარიღი", x.date], ["მომწოდებელი", x.provider], ["ქონების ტიპი", x.property_type],
    ["მიმღები", x.recipient], ["მიმღების ტელეფონი", x.recipient_phone], ["მიმღების პირადი №", x.recipient_pid], ["საკადასტრო კოდი", x.cadastral_code],
    ["რაიონი", x.district], ["მისამართი", x.address], ["რეალიზაციის ღირებულება", finMoney(x.value, c)], ["თანამშრომლობის %", x.coop_percent + "%"],
    ["საკომისიო", finMoney(x.commission, c)], ["აგენტი", `${x.agent_name || "—"} (${x.agent_percent}%) → ${finMoney(x.agent_payout, c)}`],
    ["თიმლიდერი", x.team_leader ? `${x.team_leader} (${x.tl_percent}%) → ${finMoney(x.tl_payout, c)}` : ""],
    ["კომპანიის შემოსავალი", finMoney(x.company_income, c)], ["კონტრაქტის ვადა", x.contract_expiry], ["კლიენტი", x.client_name],
    ["კლიენტის ტელეფონი", x.client_phone], ["კლიენტის პირადი №", x.client_pid],
    ["შეხსენებები", `რეპორტინგი ყოველ ${x.remind_report_months} თვეში · ვადამდე ${x.remind_expiry_days} დღით ადრე`], ["შენიშვნა", x.notes],
  ].map(([label, value]) => ({ label, value }));
  openDetail("🧾 " + (x.invoice_no || "გარიგება"), fields,
    `<div class="chip-row" style="margin-top:12px;gap:8px"><button class="btn" id="finEditDeal">✏️ რედაქტირება</button><button class="btn danger" id="finDelDeal">🗑 წაშლა</button></div>`);
  document.getElementById("finEditDeal").onclick = () => finDealForm(x);
  document.getElementById("finDelDeal").onclick = async (ev) => {
    if (!confirm("გარიგება წაიშალოს? (ჩანაწერი ცხრილში შენახული დარჩება, მაგრამ ჯამებში აღარ ჩაითვლება)")) return;
    ev.target.disabled = true;
    try { await finSend("DELETE", "/api/finance/deals/" + encodeURIComponent(x.deal_id)); toast("წაიშალა"); closeDetail(); renderContent(); }
    catch (e) { toast(e.message); ev.target.disabled = false; }
  };
}

function finDealForm(x) {
  const d = state.finDash, L = d.lookups, edit = !!x;
  x = x || { date: d.today, currency: "GEL", coop_percent: "100", agent_percent: "", tl_percent: "", remind_report_months: "2", remind_expiry_days: "60" };
  // ხელით საკომისიო ივსება მხოლოდ თუ ავტომატურისგან განსხვავდება
  const auto = Math.round(parseFloat(x.value || 0) * parseFloat(x.coop_percent || 0)) / 100;
  const manualComm = edit && Math.abs(parseFloat(x.commission) - auto) > 0.009 ? x.commission : "";
  const tls = [...new Set(L.agents.filter((a) => a.role === "team_lead").map((a) => a.name))];
  const num = `type="text" inputmode="decimal"`;
  finModal(edit ? "✏️ გარიგების რედაქტირება" : "➕ ახალი გარიგება", `<div class="qa-compose fin-form">
    <div class="fin-h">ინვოისი და ქონება</div>
    ${finIn("fdInv", "ინვოისის № (ცარიელი = ავტომატური)", edit ? x.invoice_no : "", 'placeholder="INV-YYYYMM-0001"')}
    ${finIn("fdDate", "თარიღი", x.date, 'type="date"')}
    ${finIn("fdProv", "მომწოდებელი", x.provider)}
    ${finSel("fdType", "ქონების ტიპი", L.property_types.map((p) => [p, p]), x.property_type, "— აირჩიეთ —")}
    ${finIn("fdRec", "მიმღები (მესაკუთრე)", x.recipient)}
    ${finIn("fdRPhone", "მიმღების ტელეფონი", x.recipient_phone, 'inputmode="tel"')}
    ${finIn("fdRPid", "მიმღების პირადი ნომერი", x.recipient_pid, 'inputmode="numeric"')}
    ${finIn("fdCad", "საკადასტრო კოდი", x.cadastral_code)}
    ${finIn("fdDist", "რაიონი", x.district)}
    ${finIn("fdAddr", "მისამართი", x.address)}
    <div class="fin-h">თანხა და განაწილება</div>
    ${finIn("fdVal", "რეალიზაციის ღირებულება", x.value, num)}
    ${finSel("fdCur", "ვალუტა", [["GEL", "₾ GEL"], ["USD", "$ USD"]], x.currency)}
    ${finIn("fdCoop", "თანამშრომლობის პროცენტი %", x.coop_percent, num)}
    ${finIn("fdComm", "საკომისიო (ცარიელი = ღირებულება × პროცენტი)", manualComm, num + ' placeholder="ავტომატური"')}
    ${finSel("fdAgent", "აგენტი", L.agents.map((a) => [a.agent_id, a.name + (a.team ? " · " + a.team : "")]), x.agent_id, "— აგენტის გარეშე —")}
    ${finIn("fdAPct", "აგენტის პროცენტი % (საკომისიოდან)", x.agent_percent, num)}
    ${finIn("fdTL", "თიმლიდერი", x.team_leader, 'list="fdTLs"')}<datalist id="fdTLs">${tls.map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
    ${finIn("fdTPct", "თიმლიდერის პროცენტი % (საკომისიოდან)", x.tl_percent, num)}
    <div class="fin-calc" id="fdCalc"></div>
    <div class="fin-h">კლიენტი და ხელშეკრულება</div>
    ${finIn("fdExp", "კონტრაქტის ვადა", x.contract_expiry, 'type="date"')}
    ${finIn("fdCName", "კლიენტის სახელი", x.client_name)}
    ${finIn("fdCPhone", "კლიენტის ტელეფონი", x.client_phone, 'inputmode="tel"')}
    ${finIn("fdCPid", "კლიენტის პირადი ნომერი", x.client_pid, 'inputmode="numeric"')}
    <div class="fin-h">შეხსენებები და შენიშვნა</div>
    ${finIn("fdRep", "რეპორტინგი ყოველ N თვეში (0 = გამორთვა)", x.remind_report_months, 'type="number" min="0" max="24"')}
    ${finIn("fdExpDays", "ვადის შეხსენება N დღით ადრე (0 = გამორთვა)", x.remind_expiry_days, 'type="number" min="0" max="365"')}
    <label class="fin-l" for="fdNotes">შენიშვნა</label><textarea id="fdNotes">${esc(x.notes || "")}</textarea>
    ${FIN_MSG}
    <button class="btn" id="fdSave">${edit ? "💾 შენახვა" : "✅ დამატება"}</button>
  </div>`);
  const calc = () => {
    const r2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100;
    const val = parseFloat(finNum(finV("fdVal"))) || 0, coop = parseFloat(finNum(finV("fdCoop"))) || 0;
    const cm = finNum(finV("fdComm"));
    const com = cm !== "" ? parseFloat(cm) || 0 : r2((val * coop) / 100);
    const ap = parseFloat(finNum(finV("fdAPct"))) || 0, tp = parseFloat(finNum(finV("fdTPct"))) || 0;
    const a = r2((com * ap) / 100), t = r2((com * tp) / 100), c = r2(com - a - t), cur = finV("fdCur");
    document.getElementById("fdCalc").innerHTML = `<b>გამოთვლა:</b> საკომისიო <b>${finMoney(com, cur)}</b> · აგენტი <b>${finMoney(a, cur)}</b> · თიმლიდერი <b>${finMoney(t, cur)}</b><br>`
      + `კომპანიის შემოსავალი: <b style="color:${c < 0 ? "var(--red)" : FIN_C.income}">${finMoney(c, cur)}</b>${ap + tp > 100 ? `<br><span style="color:var(--red)">⚠️ პროცენტების ჯამი 100-ს აღემატება</span>` : ""}`;
  };
  ["fdVal", "fdCur", "fdCoop", "fdComm", "fdAPct", "fdTPct"].forEach((id) => { const el = document.getElementById(id); el.oninput = calc; el.onchange = calc; });
  document.getElementById("fdAgent").onchange = () => {
    const a = L.agents.find((z) => z.agent_id === finV("fdAgent"));
    const tl = a && L.agents.find((z) => z.role === "team_lead" && z.team && z.team === a.team && z.agent_id !== a.agent_id);
    if (tl && !finV("fdTL")) document.getElementById("fdTL").value = tl.name;
  };
  calc();
  document.getElementById("fdSave").onclick = async (ev) => {
    const body = {
      invoice_no: finV("fdInv").trim(), date: finV("fdDate"), provider: finV("fdProv"), property_type: finV("fdType"),
      recipient: finV("fdRec"), recipient_phone: finV("fdRPhone"), recipient_pid: finV("fdRPid"), cadastral_code: finV("fdCad"),
      district: finV("fdDist"), address: finV("fdAddr"), value: finNum(finV("fdVal")), currency: finV("fdCur"),
      coop_percent: finNum(finV("fdCoop")), commission: finNum(finV("fdComm")), agent_id: finV("fdAgent"),
      agent_name: "", agent_percent: finNum(finV("fdAPct")) || "0", team_leader: finV("fdTL"), tl_percent: finNum(finV("fdTPct")) || "0",
      contract_expiry: finV("fdExp"), client_name: finV("fdCName"), client_phone: finV("fdCPhone"), client_pid: finV("fdCPid"),
      remind_report_months: finV("fdRep"), remind_expiry_days: finV("fdExpDays"), notes: finV("fdNotes"),
    };
    if (!body.value) { finErr("მიუთითეთ რეალიზაციის ღირებულება"); return; }
    if (!body.date) { finErr("მიუთითეთ თარიღი"); return; }
    ev.target.disabled = true;
    try {
      if (edit) await finSend("PUT", "/api/finance/deals/" + encodeURIComponent(x.deal_id), body);
      else await finSend("POST", "/api/finance/deals", body);
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast(edit ? "შენახულია ✅" : "გარიგება დაემატა ✅");
      closeDetail(); renderContent();
    } catch (e) { finErr(e.message); ev.target.disabled = false; }
  };
}

function finExpenseForm(x) {
  const d = state.finDash, L = d.lookups, edit = !!x;
  x = x || { date: d.today, currency: "GEL", recurring: "no" };
  finModal(edit ? "✏️ ხარჯის რედაქტირება" : "➕ ახალი ხარჯი", `<div class="qa-compose fin-form">
    ${finIn("feDate", "თარიღი (განმეორებადისთვის — დაწყების თარიღი)", x.date, 'type="date"')}
    ${finSel("feCat", "კატეგორია", L.expense_categories.map((c) => [c, c]), x.category, "— აირჩიეთ —")}
    ${finIn("feDesc", "აღწერა", x.description)}
    ${finIn("feAmt", "თანხა", x.amount, 'type="text" inputmode="decimal"')}
    ${finSel("feCur", "ვალუტა", [["GEL", "₾ GEL"], ["USD", "$ USD"]], x.currency)}
    <label class="chk-row"><input type="checkbox" id="feRec" ${x.recurring === "yes" ? "checked" : ""}> 🔁 ყოველთვიური (მეორდება ყოველ თვეს)</label>
    <div id="feUntilBox" ${x.recurring === "yes" ? "" : "hidden"}>${finIn("feUntil", "ბოლო თვე (ცარიელი = უვადოდ)", x.until_month, 'type="month"')}</div>
    ${FIN_MSG}
    <button class="btn" id="feSave">${edit ? "💾 შენახვა" : "✅ დამატება"}</button>
    ${edit ? `<button class="btn danger" id="feDel">🗑 წაშლა</button>` : ""}
  </div>`);
  document.getElementById("feRec").onchange = (e) => { document.getElementById("feUntilBox").hidden = !e.target.checked; };
  document.getElementById("feSave").onclick = async (ev) => {
    const body = { date: finV("feDate"), category: finV("feCat"), description: finV("feDesc"), amount: finNum(finV("feAmt")), currency: finV("feCur"),
      recurring: document.getElementById("feRec").checked ? "yes" : "no", until_month: document.getElementById("feRec").checked ? finV("feUntil") : "" };
    if (!body.category) { finErr("აირჩიეთ კატეგორია"); return; }
    if (!body.amount) { finErr("მიუთითეთ თანხა"); return; }
    ev.target.disabled = true;
    try {
      if (edit) await finSend("PUT", "/api/finance/expenses/" + encodeURIComponent(x.expense_id), body);
      else await finSend("POST", "/api/finance/expenses", body);
      toast("შენახულია ✅"); closeDetail(); renderContent();
    } catch (e) { finErr(e.message); ev.target.disabled = false; }
  };
  const del = document.getElementById("feDel");
  if (del) del.onclick = async () => {
    if (!confirm("ხარჯი წაიშალოს?")) return;
    del.disabled = true;
    try { await finSend("DELETE", "/api/finance/expenses/" + encodeURIComponent(x.expense_id)); toast("წაიშალა"); closeDetail(); renderContent(); }
    catch (e) { toast(e.message); del.disabled = false; }
  };
}

/* ---------------------------------------------------------------- მოვლენები */
function finBind(d, extra) {
  const f = state.fin;
  document.querySelectorAll("[data-fin-sec]").forEach((b) => { b.onclick = () => { f.section = b.dataset.finSec; renderContent(); }; });
  const range = () => { const a = finV("finFrom"), b = finV("finTo"); if (a && b) { f.from = a; f.to = b; renderContent(); } };
  const fe = document.getElementById("finFrom"), te = document.getElementById("finTo");
  if (fe) fe.onchange = range;
  if (te) te.onchange = range;
  document.querySelectorAll("[data-fin-preset]").forEach((b) => { b.onclick = () => { const p = b.dataset.finPreset.split("|"); f.from = p[0]; f.to = p[1]; renderContent(); }; });
  document.querySelectorAll("[data-fin-go]").forEach((b) => { b.onclick = () => { f.section = b.dataset.finGo; renderContent(); }; });
  document.querySelectorAll("[data-fin-deal]").forEach((b) => { b.onclick = () => finOpenDeal(b.dataset.finDeal); });
  document.querySelectorAll("[data-fin-exp]").forEach((b) => {
    b.onclick = () => { const e = (extra.rows || []).find((r) => r.expense_id === b.dataset.finExp); if (e) finExpenseForm(e); };
  });
  document.querySelectorAll("[data-fin-done]").forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      try { await finSend("POST", `/api/finance/deals/${encodeURIComponent(b.dataset.finDone)}/report-done`); toast("დაფიქსირდა ✅"); renderContent(); }
      catch (e) { toast(e.message); b.disabled = false; }
    };
  });
  const q = document.getElementById("finQ");
  if (q) q.onchange = () => { f.q = q.value.trim(); renderContent(); };
  const af = document.getElementById("finAgentF");
  if (af) af.onchange = () => { f.agent = af.value; renderContent(); };
  [["finTypeF", "ptype"], ["finCurF", "cur"], ["finExpF", "exp"]].forEach(([id, k]) => {
    const el = document.getElementById(id);
    if (el) el.onchange = () => { f[k] = el.value; renderContent(); };
  });
  const nd = document.getElementById("finNewDeal"); if (nd) nd.onclick = () => finDealForm(null);
  const ne = document.getElementById("finNewExp"); if (ne) ne.onclick = () => finExpenseForm(null);
  const csv = (id, kind) => {
    const b = document.getElementById(id);
    if (b) b.onclick = async () => {
      b.disabled = true;
      try { const r = await finGet(`/api/finance/export?kind=${kind}&${finQS()}`); toast(`ფაილი გამოგეგზავნათ Telegram-ში (${r.rows} ჩანაწერი)`); }
      catch (e) { toast(e.message); }
      b.disabled = false;
    };
  };
  csv("finCsvDeals", "deals"); csv("finCsvExp", "expenses");
  const rs = document.getElementById("finRateSave");
  if (rs) rs.onclick = async () => {
    rs.disabled = true;
    try { await finSend("POST", "/api/finance/settings", { usd_rate: finNum(finV("finRate")) }); toast("კურსი შენახულია ✅"); renderContent(); }
    catch (e) { toast(e.message); rs.disabled = false; }
  };
  // დიაგრამა: თვის სვეტზე დაჭერა → დეტალები
  const info = document.getElementById("finMoInfo");
  if (info && d.summary) {
    const series = d.summary.series;
    const show = (i) => {
      const s = series[i]; if (!s) return;
      info.innerHTML = `<b>${esc(s.month)}</b> · შემოსავალი <b style="color:${FIN_C.income}">${finMoney(s.company_income)}</b> · ხარჯი <b style="color:${FIN_C.exp}">${finMoney(s.expenses)}</b> · მოგება <b style="color:${s.profit < 0 ? "var(--red)" : "var(--green)"}">${finMoney(s.profit)}</b> · გარიგება ${s.deals}`;
    };
    document.querySelectorAll("[data-fin-mo]").forEach((r) => { r.onclick = () => show(parseInt(r.dataset.finMo, 10)); });
  }
}

async function finLoadAccess() {
  try {
    const a = await api("/api/finance/access");
    const changed = JSON.stringify(a) !== JSON.stringify(state.finAccess || null);
    state.finAccess = a;
    if (changed) renderTabbar();
  } catch (e) { /* წვდომა არ აქვს ან ქსელი — ტაბი უბრალოდ არ გამოჩნდება */ }
}

/* ================================================ Safe Home Property Hub (განცხადებების კატალოგი) =====
   ახალი ტაბი: ყველა აგენტი ხედავს სააგენტოს განცხადებებს (ფოტო, ფასი, ფართი, სიახლის ფერი), ძიება/ფილტრები სერვერზეა
   (/api/listings), რუკა — რეალური კოორდინატებით (Leaflet + მუქი რუკა), ჭკვიანი ძიება ("3 ოთახი საბურთალო 500$-მდე"),
   ფავორიტები, აქტუალურობის დადასტურება, მენეჯერის მიმოხილვა. მესაკუთრის ნომერი/შენიშვნები სხვა აგენტს სერვერიდან საერთოდ არ მოდის.
   არსებულ ტაბებს არ ეხება. */
const HUB_TAB = { id: "hub", label: "განცხადებები", icon: "🏙️" };
const HUB_FR = { green: "ახალი", orange: "საშუალო", red: "ძველი", grey: "გადასამოწმებელი" };
const HUB_DEALS = [["", "ყველა"], ["იყიდება", "იყიდება"], ["ქირავდება", "ქირავდება"], ["ქირავდება დღიურად", "დღიურად"]];
const HUB_CITIES = { თბილისი: [41.7151, 44.8271, 12], ბათუმი: [41.6168, 41.6367, 13] };
const HUB_FR_RANK = { green: 0, orange: 1, red: 2, grey: 3 };
state.hub = state.hub || {
  q: "", deal: "", ptype: "", rooms: [], pmin: "", pmax: "", district: "", fresh: [], mine: false, favOnly: false, agent: "", sort: "new",
  bedrooms: [], amin: "", amax: "", fmin: "", fmax: "", tmin: "", tmax: "", notFirst: false, notLast: false, pets: "", myDist: false, myDistNames: null, lead: null,
  view: "list", page: 1, items: [], total: 0, facets: null, meta: null, seq: 0, panel: false, loading: false, err: "", ins: null, insOpen: false,
  map: null, mapSeq: 0,
};

/* ---- პატარა დამხმარეები ---- */
function hubHaptic(kind) { try { if (tg && tg.HapticFeedback) { if (kind === "ok") tg.HapticFeedback.notificationOccurred("success"); else tg.HapticFeedback.impactOccurred(kind || "light"); } } catch (e) { /* არა-Telegram გარემო */ } }
function hubFavs() { try { return JSON.parse(localStorage.getItem("hubFav") || "[]"); } catch (e) { return []; } }
function hubToggleFav(id) {
  let f = hubFavs();
  f = f.includes(id) ? f.filter((x) => x !== id) : f.concat(id).slice(-100);
  try { localStorage.setItem("hubFav", JSON.stringify(f)); } catch (e) { /* ignore */ }
  const on = f.includes(id);
  // სერვერზეც ვინახავთ (ყველა მოწყობილობაზე ერთნაირი); ვარდნისას ადგილობრივი ასლი რჩება და შემდეგ სინქრონიზაციაზე გასწორდება
  api("/api/hub/favs", { method: "POST", body: JSON.stringify({ listing_id: id, on }) }).catch(() => { /* ოფლაინ */ });
  return on;
}
async function hubSyncFavs() {
  try {
    const r = await api("/api/hub/favs");
    if (r && Array.isArray(r.ids)) { try { localStorage.setItem("hubFav", JSON.stringify(r.ids)); } catch (e) { /* ignore */ } hubDrawChips(); hubDrawList(); }
  } catch (e) { /* ადგილობრივი ასლი რჩება */ }
}
function hubMoney(n) { return n == null ? "—" : "$" + Math.round(n).toLocaleString("en-US"); }
function hubShort(n) { return n == null ? "—" : n >= 10000 ? "$" + Math.round(n / 1000) + "k" : hubMoney(n); }
function hubOpenLink(url) { if (tg && tg.openLink) tg.openLink(url); else window.open(url, "_blank"); }
function hubNum(s) { return String(s == null ? "" : s).replace(/[^\d]/g, ""); }

/* ---- ჭკვიანი ძიება: "3 ოთახი საბურთალო 500$-მდე ქირა" → ფილტრები + დარჩენილი ტექსტი (ბრაუზერში, ეკრანზე ჩანს ჩიპებად) ---- */
function hubSmart(text, districts) {
  let s = " " + String(text || "").toLowerCase() + " ";
  const out = { rooms: [], pmax: "", pmin: "", deal: "", district: "", chips: [], q: "" };
  s = s.replace(/(\d{1,2})\s*-?\s*(ოთახ\S*|rooms?|rm)(?=\s)/g, (m0, n) => { out.rooms.push(n); out.chips.push("🛏 " + n + " ოთახი"); return " "; });
  out.bedrooms = []; out.amin = ""; out.amax = ""; out.pets = "";
  s = s.replace(/(\d{1,2})\s*-?\s*(საძინებელ\S*|bedrooms?|bd)(?=\s)/g, (m0, n) => { out.bedrooms.push(n); out.chips.push("🛌 " + n + " საძინებელი"); return " "; });
  s = s.replace(/(\d{2,4})\s*-?\s*(კვ\S*|მ²|მ2|sqm|m2)\s*-?\s*(მდე|დან)?(?=\s)/g, (m0, n, u, tail) => {
    if (tail === "მდე") { out.amax = n; out.chips.push("📐 ≤ " + n + " მ²"); } else { out.amin = n; out.chips.push("📐 ≥ " + n + " მ²"); }
    return " ";
  });
  if (/ცხოველ/.test(s)) { out.pets = "yes"; out.chips.push("🐾 ცხოველებით"); s = s.replace(/ცხოველ\S*/g, " "); }
  const price = (m0, n, tail) => {
    const v = hubNum(n); if (!v) return m0;
    if (tail === "დან" || tail === "min") { out.pmin = v; out.chips.push("💲 ≥ " + v); } else { out.pmax = v; out.chips.push("💲 ≤ " + v); }
    return " ";
  };
  s = s.replace(/(\d[\d.,]*)\s*(?:\$|დოლარ\S*|usd)\s*-?\s*(მდე|დან|max|min)?/g, (m0, n, tail) => price(m0, n, tail));
  s = s.replace(/\$\s*(\d[\d.,]*)\s*-?\s*(მდე|დან|max|min)?/g, (m0, n, tail) => price(m0, n, tail));
  if (/დღიურ/.test(s)) { out.deal = "ქირავდება დღიურად"; out.chips.push("🔑 დღიურად"); s = s.replace(/დღიურ\S*/g, " "); }
  else if (/(ქირა|ქირავდ|rent)/.test(s)) { out.deal = "ქირავდება"; out.chips.push("🔑 ქირავდება"); s = s.replace(/ქირა\S*|ქირავდ\S*|rent/g, " "); }
  else if (/(იყიდ|გაყიდ|sale|sell)/.test(s)) { out.deal = "იყიდება"; out.chips.push("🏷 იყიდება"); s = s.replace(/იყიდ\S*|გაყიდ\S*|sale|sell/g, " "); }
  for (const d of (districts || [])) {
    const nm = String(d.name || d).toLowerCase(), stem = nm.slice(0, Math.max(3, nm.length - 2));
    if (stem.length >= 3 && s.includes(stem)) {
      out.district = d.name || d; out.chips.push("📍 " + out.district);
      s = s.split(/\s+/).filter((w) => !w.includes(stem)).join(" "); break;
    }
  }
  out.q = out.chips.length ? s.replace(/\s+/g, " ").replace(/^[\s\-–,.]+|[\s\-–,.]+$/g, "") : String(text || "").trim();
  return out;
}
function hubEff() {                        // ეფექტური ფილტრები = პანელი + ჭკვიანი ძიების შედეგი
  const h = state.hub, sm = hubSmart(h.q, (h.facets && h.facets.districts) || []);
  return { sm, q: sm.q, deal: sm.deal || h.deal, district: sm.district || h.district, rooms: sm.rooms.length ? sm.rooms : h.rooms,
           pmax: sm.pmax || h.pmax, pmin: sm.pmin || h.pmin, bedrooms: sm.bedrooms.length ? sm.bedrooms : h.bedrooms,
           amin: sm.amin || h.amin, amax: sm.amax || h.amax, pets: sm.pets || h.pets };
}
function hubActiveCount() {                // ფილტრების რაოდენობა ⚙️ ღილაკის ბეჯისთვის
  const h = state.hub;
  return [h.ptype, h.district, h.pmin, h.pmax, h.amin, h.amax, h.fmin, h.fmax, h.tmin, h.tmax, h.pets].filter(Boolean).length
    + (h.rooms.length ? 1 : 0) + (h.bedrooms.length ? 1 : 0) + (h.notFirst ? 1 : 0) + (h.notLast ? 1 : 0) + (h.myDist ? 1 : 0);
}
function hubQS(page, forMap) {
  const h = state.hub, e = hubEff(), p = [];
  const add = (k, v) => { if (v !== "" && v != null && !(Array.isArray(v) && !v.length)) p.push(k + "=" + encodeURIComponent(Array.isArray(v) ? v.join(",") : v)); };
  add("q", e.q); add("deal_type", e.deal); add("property_type", h.ptype); add("district", e.district);
  add("rooms", e.rooms); add("price_min", e.pmin); add("price_max", e.pmax); add("freshness", h.fresh); add("agent_id", h.agent);
  add("bedrooms", e.bedrooms); add("area_min", e.amin); add("area_max", e.amax); add("floor_min", h.fmin); add("floor_max", h.fmax);
  add("floors_min", h.tmin); add("floors_max", h.tmax); add("pets", e.pets);
  if (h.notFirst) p.push("not_first=1");
  if (h.notLast) p.push("not_last=1");
  if (h.mine) p.push("mine=1");
  if (h.myDist) p.push("my_districts=1");
  if (h.favOnly) { const f = hubFavs(); p.push("ids=" + encodeURIComponent(f.length ? f.join(",") : "-")); p.push("inactive=1"); }
  if (!forMap) { add("sort", h.sort); p.push("page=" + page); p.push("per_page=24"); }
  return p.join("&");
}

/* ---- ბარათი ---- */
function hubPriceHtml(it) {
  const rent = /ქირ/.test(it.deal_type || ""), daily = /დღიურ/.test(it.deal_type || "");
  const per = it.price_usd && it.area && !rent ? `<small>${hubMoney(it.price_usd / it.area)}/მ²</small>` : "";
  return `<div class="hub-price">${hubMoney(it.price_usd)}${rent ? `<small>${daily ? "/დღე" : "/თვე"}</small>` : per}</div>`;
}
function hubFrHtml(fr) {
  const c = (fr && fr.color) || "grey";
  return `<span class="hub-fr fr-${c}"><i></i>${esc(HUB_FR[c] || "")}${fr && fr.age_days != null ? ` · ${fr.age_days} დღე` : ""}</span>`;
}
function hubFacts(it) {
  const f = [];
  if (it.rooms) f.push(`<div><b>${esc(it.rooms)}</b>ოთახი</div>`);
  if (it.area) f.push(`<div><b>${esc(String(Math.round(it.area * 10) / 10))}</b>მ²</div>`);
  if (it.floor) f.push(`<div><b>${esc(it.floor)}${it.floors ? "/" + esc(it.floors) : ""}</b>სართული</div>`);
  if (it.bedrooms) f.push(`<div><b>${esc(it.bedrooms)}</b>საძინებელი</div>`);
  return f.join("") || `<div class="muted">დეტალები მითითებული არ არის</div>`;
}
function hubCard(it, i) {
  const ph = it.photos && it.photos[0], fav = hubFavs().includes(it.listing_id);
  const img = ph ? `<img loading="lazy" decoding="async" referrerpolicy="no-referrer" src="${esc(ph)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'hub-noph',textContent:'🏠'}))">`
                 : `<div class="hub-noph">🏠</div>`;
  const loc = [it.address, it.district].filter(Boolean).join(" · ");
  return `<div class="hub-card" data-hub-id="${esc(it.listing_id)}" style="animation-delay:${Math.min(i, 8) * 40}ms">
    <div class="hub-ph">${img}${hubFrHtml(it.freshness)}
      <button class="hub-fav ${fav ? "on" : ""}" data-hub-fav="${esc(it.listing_id)}" aria-label="ფავორიტი">${fav ? "♥" : "♡"}</button>
      ${it.interest ? `<span class="hub-hot">🔥 ${it.interest}</span>` : ""}${it.photos && it.photos.length > 1 ? `<span class="hub-cnt">📷 ${it.photos.length}</span>` : ""}</div>
    <div class="hub-body">
      ${hubPriceHtml(it)}
      <div class="hub-facts">${hubFacts(it)}</div>
      <div class="hub-loc">📍 ${esc(loc || it.city || "მისამართი მითითებული არ არის")}</div>
      <div class="hub-foot"><span class="hub-agent">${it.private ? "⭐ " : "👤 "}${esc(it.agent_name || "")}</span>
        <span class="hub-deal">${it.dup_count ? `<span class="hub-dup" title="იგივე ბინის სხვა განცხადება (გაფრთხილება — არაფერი იშლება)">⚠️ ორეული</span> ` : ""}${it.pets === "yes" ? "🐾 " : ""}${esc(it.deal_type || "")}</span></div>
    </div></div>`;
}
const hubSkeleton = () => Array.from({ length: 6 }, () => `<div class="hub-card hub-skel"><div class="hub-ph"></div><div class="hub-body"><div class="sk w60"></div><div class="sk w90"></div><div class="sk w40"></div></div></div>`).join("");

/* ---- ჩიპები / პანელი / მიმოხილვა ---- */
function hubDrawChips() {
  const h = state.hub, fc = (h.facets && h.facets.fresh) || {}, el = document.getElementById("hubChips");
  if (!el) return;
  const sm = hubEff().sm;
  el.innerHTML = `
    <div class="hub-row">${HUB_DEALS.map(([v, l]) => `<button class="hub-chip ${hubEff().deal === v ? "on" : ""}" data-hub-deal="${esc(v)}">${esc(l)}</button>`).join("")}
      <button class="hub-chip ${h.mine ? "on" : ""}" data-hub-mine="1">⭐ ჩემი${h.meta ? ` (${h.meta.mine_total})` : ""}</button>
      <button class="hub-chip ${h.favOnly ? "on" : ""}" data-hub-favonly="1">♥ ფავორიტები (${hubFavs().length})</button>
      <button class="hub-chip ${h.myDist ? "on" : ""}" data-hub-mydist="1">📍 ჩემი რაიონები</button></div>
    ${h.myDist ? `<div class="hub-note" style="margin-bottom:8px">${h.myDistNames && h.myDistNames.length ? "📍 ამ კვირის რაიონები: " + h.myDistNames.map(esc).join(", ") : "ამ კვირას რაიონი ჯერ არ გაქვთ მინიჭებული — ორშაბათს ავტომატურად გადანაწილდება ან მენეჯერი მოგანიჭებთ."}</div>` : ""}
    <div class="hub-row">${["green", "orange", "red", "grey"].map((c) => `<button class="hub-chip fr-${c} ${h.fresh.includes(c) ? "on" : ""}" data-hub-fr="${c}"><i></i>${HUB_FR[c]}${fc[c] != null ? ` <b>${fc[c]}</b>` : ""}</button>`).join("")}</div>
    ${sm.chips.length ? `<div class="hub-row hub-smart"><span class="hub-k" style="margin:0">ჭკვიანი ძიება:</span>${sm.chips.map((c) => `<span class="hub-chip on">${esc(c)}</span>`).join("")}</div>` : ""}`;
  const fb = document.getElementById("hubFilterBtn");
  if (fb) { const n = hubActiveCount(); fb.textContent = "⚙️" + (n ? " " + n : ""); fb.classList.toggle("hub-on", n > 0); }
  el.querySelectorAll("[data-hub-deal]").forEach((b) => { b.onclick = () => { hubHaptic(); h.deal = b.dataset.hubDeal; hubReload(); }; });
  el.querySelectorAll("[data-hub-mine]").forEach((b) => { b.onclick = () => { hubHaptic(); h.mine = !h.mine; hubReload(); }; });
  el.querySelectorAll("[data-hub-mydist]").forEach((b) => { b.onclick = () => { hubHaptic(); h.myDist = !h.myDist; hubReload(); }; });
  el.querySelectorAll("[data-hub-favonly]").forEach((b) => { b.onclick = () => { hubHaptic(); h.favOnly = !h.favOnly; hubReload(); }; });
  el.querySelectorAll("[data-hub-fr]").forEach((b) => { b.onclick = () => { hubHaptic(); const c = b.dataset.hubFr; h.fresh = h.fresh.includes(c) ? h.fresh.filter((x) => x !== c) : h.fresh.concat(c); hubReload(); }; });
}
/* პანელის ველების მნიშვნელობები state-ში (ღილაკზე დაჭერისას პანელი თავიდან იხატება — ჩაწერილი არ უნდა დაიკარგოს) */
function hubKeepPanel() {
  const h = state.hub, g = (id) => { const e = document.getElementById(id); return e ? e.value : null; };
  const set = (key, id, fn) => { const v = g(id); if (v !== null) h[key] = fn ? fn(v) : v; };
  set("ptype", "hubPtype"); set("district", "hubDistrict"); set("pmin", "hubPmin", hubNum); set("pmax", "hubPmax", hubNum);
  set("amin", "hubAmin", hubNum); set("amax", "hubAmax", hubNum); set("fmin", "hubFmin", hubNum); set("fmax", "hubFmax", hubNum); set("tmin", "hubTmin", hubNum); set("tmax", "hubTmax", hubNum);
}
function hubDrawPanel() {
  const h = state.hub, f = h.facets || {}, el = document.getElementById("hubPanel");
  if (!el) return;
  el.hidden = !h.panel;
  if (!h.panel) { el.innerHTML = ""; return; }
  const opts = (arr, cur, all) => `<option value="">${all}</option>` + arr.map((o) => `<option value="${esc(o.name || o)}" ${(o.name || o) === cur ? "selected" : ""}>${esc(o.name || o)}${o.count != null ? ` (${o.count})` : ""}</option>`).join("");
  el.innerHTML = `
    <div class="hub-grid2">
      <label>ქონების ტიპი<select id="hubPtype">${opts(f.property_types || [], h.ptype, "ყველა")}</select></label>
      <label>რაიონი<select id="hubDistrict">${opts(f.districts || [], h.district, "ყველა")}</select></label>
      <label>ფასი, $ (დან)<input id="hubPmin" inputmode="numeric" value="${esc(h.pmin)}" placeholder="0"></label>
      <label>ფასი, $ (მდე)<input id="hubPmax" inputmode="numeric" value="${esc(h.pmax)}" placeholder="∞"></label>
    </div>
    <div class="hub-k">ოთახები</div>
    <div class="hub-row">${["1", "2", "3", "4", "5+"].map((r) => `<button class="hub-chip ${h.rooms.includes(r) ? "on" : ""}" data-hub-room="${r}">${r}</button>`).join("")}</div>
    <div class="hub-k">საძინებლები</div>
    <div class="hub-row">${["1", "2", "3", "4+"].map((r) => `<button class="hub-chip ${h.bedrooms.includes(r) ? "on" : ""}" data-hub-bed="${r}">${r}</button>`).join("")}</div>
    <div class="hub-grid2">
      <label>ფართი, მ² (დან)<input id="hubAmin" inputmode="numeric" value="${esc(h.amin)}" placeholder="0"></label>
      <label>ფართი, მ² (მდე)<input id="hubAmax" inputmode="numeric" value="${esc(h.amax)}" placeholder="∞"></label>
      <label>სართული (დან)<input id="hubFmin" inputmode="numeric" value="${esc(h.fmin)}" placeholder="1"></label>
      <label>სართული (მდე)<input id="hubFmax" inputmode="numeric" value="${esc(h.fmax)}" placeholder="∞"></label>
      <label>სართულიანობა (დან)<input id="hubTmin" inputmode="numeric" value="${esc(h.tmin)}" placeholder="1"></label>
      <label>სართულიანობა (მდე)<input id="hubTmax" inputmode="numeric" value="${esc(h.tmax)}" placeholder="∞"></label>
    </div>
    <div class="hub-row"><button class="hub-chip ${h.notFirst ? "on" : ""}" data-hub-tog="notFirst">პირველის გარდა</button><button class="hub-chip ${h.notLast ? "on" : ""}" data-hub-tog="notLast">ბოლოს გარდა</button>
      <button class="hub-chip ${h.pets === "yes" ? "on" : ""}" data-hub-pets="yes">🐾 ცხოველები დაიშვება</button><button class="hub-chip ${h.pets === "ask" ? "on" : ""}" data-hub-pets="ask">🐾 შეთანხმებით</button></div>
    <div class="hub-k">დალაგება</div>
    <div class="hub-row">${[["new", "უახლესი"], ["price_asc", "იაფი"], ["price_desc", "ძვირი"], ["area_desc", "დიდი ფართი"]].map(([v, l]) => `<button class="hub-chip ${h.sort === v ? "on" : ""}" data-hub-sort="${v}">${l}</button>`).join("")}</div>
    <div class="hub-row" style="margin-top:10px"><button class="btn" id="hubApply">გამოყენება</button><button class="btn secondary" id="hubReset">გასუფთავება</button></div>`;
  el.querySelectorAll("[data-hub-room]").forEach((b) => { b.onclick = () => { hubKeepPanel(); const r = b.dataset.hubRoom; h.rooms = h.rooms.includes(r) ? h.rooms.filter((x) => x !== r) : h.rooms.concat(r); hubDrawPanel(); }; });
  el.querySelectorAll("[data-hub-sort]").forEach((b) => { b.onclick = () => { hubKeepPanel(); h.sort = b.dataset.hubSort; hubDrawPanel(); }; });
  // ღილაკების არჩევანი ინახება ისე, რომ ჩაწერილი ველები არ დაიკარგოს (პანელი თავიდან იხატება)
  const keepInputs = hubKeepPanel;
  el.querySelectorAll("[data-hub-bed]").forEach((b) => { b.onclick = () => { keepInputs(); const r = b.dataset.hubBed; h.bedrooms = h.bedrooms.includes(r) ? h.bedrooms.filter((x) => x !== r) : h.bedrooms.concat(r); hubDrawPanel(); }; });
  el.querySelectorAll("[data-hub-tog]").forEach((b) => { b.onclick = () => { keepInputs(); h[b.dataset.hubTog] = !h[b.dataset.hubTog]; hubDrawPanel(); }; });
  el.querySelectorAll("[data-hub-pets]").forEach((b) => { b.onclick = () => { keepInputs(); h.pets = h.pets === b.dataset.hubPets ? "" : b.dataset.hubPets; hubDrawPanel(); }; });
  document.getElementById("hubApply").onclick = () => { keepInputs(); h.panel = false; hubReload(); };
  document.getElementById("hubReset").onclick = () => {
    Object.assign(h, { q: "", deal: "", ptype: "", rooms: [], pmin: "", pmax: "", district: "", fresh: [], mine: false, favOnly: false, agent: "", sort: "new", panel: false,
      bedrooms: [], amin: "", amax: "", fmin: "", fmax: "", tmin: "", tmax: "", notFirst: false, notLast: false, pets: "", myDist: false, myDistNames: null });
    const s = document.getElementById("hubQ"); if (s) s.value = "";
    hubReload();
  };
}
function hubFrBar(fr, total) {
  const t = Math.max(1, total);
  return `<div class="hub-stack">${["green", "orange", "red", "grey"].map((c) => (fr[c] ? `<span class="fr-bg-${c}" style="width:${(fr[c] / t) * 100}%" title="${HUB_FR[c]}: ${fr[c]}"></span>` : "")).join("")}</div>`;
}
function hubDrawIns() {
  const h = state.hub, el = document.getElementById("hubIns");
  if (!el) return;
  const d = h.ins;
  if (!d) { el.innerHTML = ""; return; }
  const t = d.totals, mgr = d.scope !== "mine";
  const need = t.fresh.red + t.fresh.grey;
  el.innerHTML = `
    <div class="hub-ins-top" id="hubInsToggle">
      <div class="hub-stat"><b>${t.total}</b><span>${mgr ? (d.scope === "team" ? "გუნდის" : "სულ") : "ჩემი"} განცხადება</span></div>
      <div class="hub-stat"><b>${t.new_7d}</b><span>ახალი 7 დღეში</span></div>
      <div class="hub-stat ${need ? "warn" : ""}" ${need ? 'data-hub-need="1"' : ""}><b>${need}</b><span>გადასამოწმებელი</span></div>
      ${mgr ? `<div class="hub-stat"><b>${d.agents.length}</b><span>აგენტი</span></div>` : ""}
    </div>
    ${hubFrBar(t.fresh, t.total)}
    ${mgr && (t.no_photo || t.no_coords || t.dup_listings || t.no_area) ? `<div class="hub-k hub-q">📊 მონაცემთა ხარისხი: ${t.no_photo ? `📷 ფოტოს გარეშე ${t.no_photo}` : ""}${t.no_coords ? ` · 📍 კოორდინატის გარეშე ${t.no_coords}` : ""}${t.no_area ? ` · 📐 ფართის გარეშე ${t.no_area}` : ""}${t.dup_listings ? ` · ⚠️ შესაძლო ორეული ${t.dup_listings}` : ""}</div>` : ""}
    ${mgr && h.insOpen ? `<div class="hub-lead">${d.agents.map((a) => `
      <div class="hub-lead-row" data-hub-agent="${esc(a.agent_id)}"><div class="n">${esc(a.name)}<small>${esc(a.team || "")}</small></div>
        <div class="v"><b>${a.total}</b><small>+${a.new_7d} · ⚠${a.need_verify}</small></div>${hubFrBar(a.fresh, a.total)}</div>`).join("") || `<div class="empty">მონაცემი ჯერ არ არის</div>`}</div>` : ""}
    ${mgr ? `<div class="hub-k" style="text-align:center;margin:6px 0 0"><button class="hub-link" id="hubInsMore">${h.insOpen ? "▲ აგენტების სია" : "▼ აგენტების განაწილება"}</button></div>` : ""}
    ${d.scope === "all" ? `<div class="hub-row" style="justify-content:center;margin:8px 0 0"><button class="hub-chip" id="hubAdmSet">⚙️ სიახლის ზღვრები</button><button class="hub-chip" id="hubAdmExpL">⬇️ განცხადებები CSV</button><button class="hub-chip" id="hubAdmExpM">⬇️ შეხვედრები CSV</button></div>` : ""}`;
  const as = document.getElementById("hubAdmSet"); if (as) as.onclick = () => hubAdminSettings();
  const ae1 = document.getElementById("hubAdmExpL"); if (ae1) ae1.onclick = () => hubAdminExport("listings");
  const ae2 = document.getElementById("hubAdmExpM"); if (ae2) ae2.onclick = () => hubAdminExport("meetings");
  const need2 = el.querySelector("[data-hub-need]");
  if (need2) need2.onclick = () => { hubHaptic(); h.mine = d.scope === "mine"; h.fresh = ["red", "grey"]; hubReload(); };
  const more = document.getElementById("hubInsMore"); if (more) more.onclick = () => { h.insOpen = !h.insOpen; hubDrawIns(); };
  el.querySelectorAll("[data-hub-agent]").forEach((r) => { r.onclick = () => { h.agent = h.agent === r.dataset.hubAgent ? "" : r.dataset.hubAgent; hubHaptic(); hubReload(); window.scrollTo({ top: 0, behavior: "smooth" }); }; });
}

/* ---- სია ---- */
function hubDrawList() {
  const h = state.hub, el = document.getElementById("hubList"), more = document.getElementById("hubMore"), cnt = document.getElementById("hubCount");
  if (!el) return;
  if (cnt) cnt.textContent = h.err ? "" : (h.loading && !h.items.length ? "იტვირთება…" : `ნაპოვნია ${h.total} · სულ ${h.meta ? h.meta.total_all : 0}`);
  if (h.view === "map" || h.view === "meet") { el.hidden = true; more.innerHTML = ""; return; }
  el.hidden = false;
  if (h.err) { el.innerHTML = `<div class="empty" style="grid-column:1/-1">⚠️ ${esc(h.err)}</div>`; more.innerHTML = ""; return; }
  if (h.loading && !h.items.length) { el.innerHTML = hubSkeleton(); more.innerHTML = ""; return; }
  if (!h.items.length) {
    const admin = state.role === "admin" && !(state.data && state.data.is_team_lead);
    const none = !(h.meta && h.meta.total_all);
    el.innerHTML = `<div class="empty" style="grid-column:1/-1">${none ? "კატალოგი ჯერ ცარიელია. ახალი განცხადებები აქ ავტომატურად გამოჩნდება, ატვირთვისთანავე." : "ამ ფილტრებით განცხადება ვერ მოიძებნა"}
      ${none && admin ? `<div style="margin-top:10px"><button class="btn" id="hubBackfill">📥 ძველი განცხადებების შემოტანა</button></div>` : ""}</div>`;
    more.innerHTML = "";
    const bf = document.getElementById("hubBackfill");
    if (bf) bf.onclick = async () => {
      bf.disabled = true; bf.textContent = "იტვირთება…";
      try { const r = await api("/api/listings/backfill", { method: "POST", body: "{}" }); toast(`✅ დაემატა ${r.added}`); hubReload(); }
      catch (e) { toast(e.message || "შეცდომა"); bf.disabled = false; }
    };
    return;
  }
  el.innerHTML = h.items.map(hubCard).join("");
  el.querySelectorAll("[data-hub-id]").forEach((c) => { c.onclick = () => hubOpenDetail(c.dataset.hubId); });
  el.querySelectorAll("[data-hub-fav]").forEach((b) => {
    b.onclick = (ev) => { ev.stopPropagation(); hubHaptic(); const on = hubToggleFav(b.dataset.hubFav); b.classList.toggle("on", on); b.textContent = on ? "♥" : "♡"; hubDrawChips(); };
  });
  more.innerHTML = h.items.length < h.total ? `<button class="btn secondary" id="hubMoreBtn">მეტის ჩატვირთვა (${h.items.length}/${h.total})</button>` : "";
  const mb = document.getElementById("hubMoreBtn"); if (mb) mb.onclick = () => hubLoad(true);
}

async function hubLoad(append) {
  const h = state.hub, seq = ++h.seq;
  h.loading = true; h.err = "";
  if (!append) { h.page = 1; } else { h.page += 1; }
  hubDrawList();
  try {
    const r = await api("/api/listings?" + hubQS(h.page));
    if (seq !== h.seq) return;
    h.items = append ? h.items.concat(r.items) : r.items;
    h.total = r.total; h.facets = r.facets; h.meta = r.meta; h.myDistNames = r.my_districts || null;
  } catch (e) {
    if (seq !== h.seq) return;
    h.err = e.message || "შეცდომა"; if (append) h.page -= 1;
  }
  h.loading = false;
  hubDrawChips(); hubDrawPanel(); hubDrawList();
  if (h.view === "map") hubMapRefresh();
}
function hubReload() { return hubLoad(false); }

/* ---- დეტალი ---- */
function hubShareText(it) {
  const rent = /ქირ/.test(it.deal_type || "");
  return [`🏠 ${it.property_type || "განცხადება"} · ${it.deal_type || ""}`, `💰 ${hubMoney(it.price_usd)}${rent ? (/დღიურ/.test(it.deal_type) ? "/დღე" : "/თვე") : ""}`,
    `📍 ${[it.city, it.district, it.address].filter(Boolean).join(", ")}`, `📐 ${it.rooms ? it.rooms + " ოთახი · " : ""}${it.area || "?"} მ²${it.floor ? " · სართ. " + it.floor + (it.floors ? "/" + it.floors : "") : ""}`,
    `🆔 ${it.myhome_id || it.ssge_id || it.listing_id}`, it.myhome_url, it.ssge_url].filter(Boolean).join("\n");
}
function hubLightbox(photos, start) {
  let i = start || 0;
  const ov = document.createElement("div");
  ov.className = "hub-lb";
  ov.innerHTML = `<button class="hub-lb-x">✕</button><div class="hub-lb-img"><img referrerpolicy="no-referrer" alt=""></div><button class="hub-lb-n l">‹</button><button class="hub-lb-n r">›</button><div class="hub-lb-c"></div>`;
  const img = ov.querySelector("img"), c = ov.querySelector(".hub-lb-c");
  const show = () => { i = (i + photos.length) % photos.length; img.src = photos[i]; c.textContent = `${i + 1} / ${photos.length}`; };
  ov.querySelector(".hub-lb-x").onclick = () => ov.remove();
  ov.querySelector(".l").onclick = (e) => { e.stopPropagation(); i--; show(); };
  ov.querySelector(".r").onclick = (e) => { e.stopPropagation(); i++; show(); };
  let x0 = null;
  ov.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
  ov.addEventListener("touchend", (e) => { if (x0 == null) return; const dx = e.changedTouches[0].clientX - x0; if (Math.abs(dx) > 40) { i += dx < 0 ? 1 : -1; show(); } x0 = null; }, { passive: true });
  ov.onclick = (e) => { if (e.target === ov || e.target.classList.contains("hub-lb-img")) ov.remove(); };
  document.body.appendChild(ov); show();
}
async function hubOpenDetail(idOrItem) {
  const h = state.hub;
  let it = typeof idOrItem === "object" ? idOrItem : h.items.find((x) => x.listing_id === idOrItem);
  if (!it) { try { it = (await api("/api/listings/" + encodeURIComponent(idOrItem))).listing; } catch (e) { toast(e.message || "შეცდომა"); return; } }
  const backdrop = document.getElementById("modalBackdrop"), box = document.getElementById("modalBox");
  const photos = it.photos || [];
  const gal = photos.map((p, k) => `<img loading="lazy" referrerpolicy="no-referrer" data-hub-ph="${k}" src="${esc(p)}" alt="" onerror="this.style.display='none'">`).join("");
  const row = (k, v) => (v === "" || v == null ? "" : `<div class="hub-kv"><span>${esc(k)}</span><b>${esc(v)}</b></div>`);
  const fr = it.freshness || {}, fav = hubFavs().includes(it.listing_id);
  const links = [it.myhome_url ? `<button class="btn secondary" data-hub-link="${esc(it.myhome_url)}">MyHome ↗</button>` : "", it.ssge_url ? `<button class="btn secondary" data-hub-link="${esc(it.ssge_url)}">ss.ge ↗</button>` : ""].join("");
  box.innerHTML = `
    <h3>${esc(it.property_type || "განცხადება")} · ${esc(it.deal_type || "")}<button class="close" id="modalClose">✕</button></h3>
    <div class="hub-galwrap">${photos.length ? `<div class="hub-gal" id="hubGal">${gal}</div><span class="hub-gal-c" id="hubGalC">1 / ${photos.length}</span>` : `<div class="hub-noph" style="height:180px">🏠</div>`}</div>
    <div class="hub-pricerow">${hubPriceHtml(it)}<button class="hub-fav big ${fav ? "on" : ""}" id="hubDetFav">${fav ? "♥" : "♡"}</button></div>
    <div class="hub-facts big">${hubFacts(it)}</div>
    <div class="hub-loc">📍 ${esc([it.city, it.district, it.address].filter(Boolean).join(" · ") || "—")}</div>
    <div class="hub-detail-fr">${hubFrHtml(fr)}<span class="muted">დამატებულია: ${esc(String(it.created_at || "—").slice(0, 10))}${it.last_verified_at ? " · გადამოწმდა: " + esc(String(it.last_verified_at).slice(0, 10)) : ""}</span></div>
    <div class="hub-kvs">
      ${row("მდგომარეობა", it.condition)}${row("სტატუსი", it.status_text)}${row("საძინებლები", it.bedrooms)}${it.pets ? row("🐾 ცხოველები", { yes: "დაიშვება", no: "არ დაიშვება", ask: "შეთანხმებით" }[it.pets]) : ""}
      ${it.interest ? `<div class="hub-kv"><span>🔥 დაინტერესება (30 დღე)</span><b>${it.interest} შეხვედრა</b></div>` : ""}${it.dup_count ? `<div class="hub-kv"><span>⚠️ შესაძლო ორეული</span><b>${it.dup_count} სხვა განცხადება (${esc((it.dup_ids || []).join(", "))})</b></div>` : ""}${row("ID", it.myhome_id || it.ssge_id || it.listing_id)}${row("აგენტი", [it.agent_name, it.team].filter(Boolean).join(" · "))}
    </div>
    ${it.private ? `<div class="hub-priv"><div class="k">🔒 შიდა ინფორმაცია (ხედავთ მხოლოდ თქვენ/გუნდის ლიდერი/ადმინი)</div>
      ${row("მესაკუთრის ნომერი", it.owner_number)}${row("შენიშვნა", it.notes)}${row("წყარო", it.src_site ? it.src_site + " " + (it.src_id || "") : "")}
      <div class="hub-row" style="margin-top:8px"><button class="btn" id="hubVerify">✅ ვადასტურებ — აქტუალურია</button>
        <button class="btn secondary" id="hubSold">🏁 ${/ქირ/.test(it.deal_type || "") ? "გაქირავდა" : "გაიყიდა"}</button></div></div>` : ""}
    <div class="hub-row" style="margin-top:12px">${links}<button class="btn secondary" id="hubCopy">📋 კოპირება</button><button class="btn" id="hubCoop">${it.private ? "📅 შეხვედრა" : "🤝 შეხვედრა + თანამშრომლობა"}</button>
      ${state.hub.ins && state.hub.ins.scope !== "mine" ? `<button class="btn secondary" id="hubAssign">👤 კლიენტის გადაბარება</button>` : ""}</div>`;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
  box.querySelectorAll("[data-hub-link]").forEach((b) => { b.onclick = () => hubOpenLink(b.dataset.hubLink); });
  box.querySelectorAll("[data-hub-ph]").forEach((p) => { p.onclick = () => hubLightbox(photos, Number(p.dataset.hubPh)); });
  const gl = document.getElementById("hubGal");
  if (gl) gl.onscroll = () => { const k = Math.round(gl.scrollLeft / Math.max(1, gl.firstElementChild.offsetWidth)); const c = document.getElementById("hubGalC"); if (c) c.textContent = `${Math.min(photos.length, k + 1)} / ${photos.length}`; };
  document.getElementById("hubDetFav").onclick = (e) => { hubHaptic(); const on = hubToggleFav(it.listing_id); e.target.classList.toggle("on", on); e.target.textContent = on ? "♥" : "♡"; hubDrawChips(); hubDrawList(); };
  document.getElementById("hubCopy").onclick = async () => {
    const txt = hubShareText(it);
    try { await navigator.clipboard.writeText(txt); toast("📋 დაკოპირდა — გაუგზავნეთ კლიენტს"); }
    catch (e) { const ta = document.createElement("textarea"); ta.value = txt; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); toast("📋 დაკოპირდა"); } catch (e2) { toast(txt.slice(0, 80)); } ta.remove(); }
  };
  document.getElementById("hubCoop").onclick = () => hubBookForm(it);
  const asg = document.getElementById("hubAssign"); if (asg) asg.onclick = async () => { await hubEnsureLeadsMeta(); hubAssignForm(it); };
  const vb = document.getElementById("hubVerify");
  if (vb) vb.onclick = async () => {
    vb.disabled = true;
    try { await api(`/api/listings/${encodeURIComponent(it.listing_id)}/verify`, { method: "POST", body: "{}" }); hubHaptic("ok"); toast("✅ დადასტურდა — განცხადება გამწვანდა"); closeDetail(); hubReload(); hubLoadIns(); }
    catch (e) { toast(e.message || "შეცდომა"); vb.disabled = false; }
  };
  const sb = document.getElementById("hubSold");
  if (sb) sb.onclick = async () => {
    if (!confirm("განცხადება კატალოგიდან გაქრება (ჩანაწერი არ წაიშლება). გავაგრძელოთ?")) return;
    sb.disabled = true;
    try { await api(`/api/listings/${encodeURIComponent(it.listing_id)}/status`, { method: "POST", body: JSON.stringify({ active: false }) }); hubHaptic("ok"); toast("🏁 მონიშნულია"); closeDetail(); hubReload(); hubLoadIns(); }
    catch (e) { toast(e.message || "შეცდომა"); sb.disabled = false; }
  };
}

/* ---- რუკა (Leaflet, მუქი რუკა; მხოლოდ რეალური კოორდინატები) ---- */
let _hubLeaflet = null;
function hubLoadLeaflet() {
  if (typeof L !== "undefined") return Promise.resolve(true);
  if (_hubLeaflet) return _hubLeaflet;
  _hubLeaflet = new Promise((resolve) => {
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css";
    document.head.appendChild(css);
    const js = document.createElement("script"); js.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
    js.onload = () => resolve(typeof L !== "undefined"); js.onerror = () => { _hubLeaflet = null; resolve(false); };
    document.head.appendChild(js);
  });
  return _hubLeaflet;
}
/* წერტილების დაჯგუფება ეკრანულ უჯრებად (წმინდა ფუნქცია): project(lat,lng) -> {x,y}; cell — უჯრის ზომა პიქსელებში */
function hubCluster(points, project, cell) {
  const groups = new Map();
  points.forEach((p) => {
    const xy = project(p.lat, p.lng), key = Math.floor(xy.x / cell) + ":" + Math.floor(xy.y / cell);
    let g = groups.get(key);
    if (!g) { g = { items: [], x: 0, y: 0 }; groups.set(key, g); }
    g.items.push(p); g.x += xy.x; g.y += xy.y;
  });
  return Array.from(groups.values()).map((g) => {
    const n = g.items.length, best = g.items.reduce((a, b) => (HUB_FR_RANK[b.fr] < HUB_FR_RANK[a.fr] ? b : a));
    const prices = g.items.map((p) => p.price).filter((v) => v != null);
    return { n, items: g.items, fr: best.fr, minPrice: prices.length ? Math.min(...prices) : null,
             lat: g.items.reduce((s, p) => s + p.lat, 0) / n, lng: g.items.reduce((s, p) => s + p.lng, 0) / n };
  });
}
function hubPill(g) {
  const rent = g.n === 1 && /ქირ/.test(g.items[0].deal || "");
  const label = g.n === 1 ? hubShort(g.items[0].price) + (rent ? "/თვე" : "") : `from ${hubShort(g.minPrice)} <b>${g.n}</b>`;
  return `<div class="hub-pill fr-b-${g.fr} ${g.n > 1 ? "multi" : ""} ${g.n === 1 && g.items[0].mine ? "mine" : ""}">${label}</div>`;
}
async function hubMapRefresh() {
  const h = state.hub, box = document.getElementById("hubMapBox");
  if (!box || h.view !== "map") return;
  const seq = ++h.mapSeq;
  const info = document.getElementById("hubMapInfo");
  if (info) info.textContent = "რუკა იტვირთება…";
  const okL = await hubLoadLeaflet();
  if (!okL) { box.innerHTML = `<div class="empty">⚠️ რუკის ბიბლიოთეკა ვერ ჩაიტვირთა — შეამოწმეთ ინტერნეტი</div>`; return; }
  let data;
  try { data = await api("/api/listings/map?" + hubQS(1, true)); } catch (e) { if (info) info.textContent = "⚠️ " + (e.message || "შეცდომა"); return; }
  if (seq !== h.mapSeq || h.view !== "map") return;
  if (!h.map || !h.map.map || !document.getElementById("hubMapCanvas")) {
    box.innerHTML = `<div id="hubMapCanvas"></div>
      <div class="hub-map-top"><div class="hub-row" style="margin:0">${Object.keys(HUB_CITIES).map((c) => `<button class="hub-chip" data-hub-city="${c}">${c}</button>`).join("")}</div></div>
      <div class="hub-map-legend"><span class="fr-green"><i></i>ახალი</span><span class="fr-orange"><i></i>საშუალო</span><span class="fr-red"><i></i>ძველი</span></div>`;
    const map = L.map("hubMapCanvas", { zoomControl: true, attributionControl: true, preferCanvas: true }).setView([41.7151, 44.8271], 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);   /* მუქი სტილი CSS ფილტრით (.hub-mapbox .leaflet-tile-pane) */
    const layer = L.layerGroup().addTo(map);
    h.map = { map, layer, fitted: false, points: [] };
    map.on("zoomend moveend", () => hubMapDraw());
    box.querySelectorAll("[data-hub-city]").forEach((b) => { b.onclick = () => { hubHaptic(); const c = HUB_CITIES[b.dataset.hubCity]; map.flyTo([c[0], c[1]], c[2], { duration: 0.8 }); }; });
    setTimeout(() => map.invalidateSize(), 60);
  }
  h.map.points = data.points;
  if (info) info.textContent = `🗺 ${data.total} განცხადება რუკაზე${data.no_coords ? ` · ${data.no_coords} კოორდინატის გარეშე (სიაში ჩანს)` : ""}${data.truncated ? " · ნაწილი" : ""}`;
  if (data.points.length && !h.map.fitted) {
    h.map.fitted = true;
    try { h.map.map.fitBounds(data.points.map((p) => [p.lat, p.lng]), { padding: [40, 40], maxZoom: 15 }); } catch (e) { /* ignore */ }
  }
  hubMapDraw();
}
function hubMapDraw() {
  const h = state.hub, m = h.map;
  if (!m || !m.map) return;
  m.layer.clearLayers();
  const proj = (lat, lng) => { const p = m.map.latLngToContainerPoint([lat, lng]); return { x: p.x, y: p.y }; };
  hubCluster(m.points, proj, 70).forEach((g) => {
    const mk = L.marker([g.lat, g.lng], { icon: L.divIcon({ className: "hub-pin", html: hubPill(g), iconSize: null }) }).addTo(m.layer);
    mk.on("click", () => {
      hubHaptic();
      if (g.n === 1) hubOpenDetail(g.items[0].id);
      else m.map.fitBounds(g.items.map((p) => [p.lat, p.lng]), { padding: [60, 60], maxZoom: 18 });
    });
  });
}
function hubSetView(v) {
  const h = state.hub;
  h.view = v;
  document.querySelectorAll("[data-hub-view]").forEach((b) => b.classList.toggle("on", b.dataset.hubView === v));
  const box = document.getElementById("hubMapBox");
  if (box) box.hidden = v !== "map";
  const fl = document.getElementById("hubFilters"), ins = document.getElementById("hubIns"), mt = document.getElementById("hubMeet"), inf = document.getElementById("hubMapInfo");
  if (fl) fl.hidden = v === "meet";
  hubDrawLeadBar();
  if (ins) ins.hidden = v === "meet";
  if (mt) mt.hidden = v !== "meet";
  if (inf && v !== "map") inf.textContent = "";
  hubDrawList();
  if (v === "map") { h.map = null; hubMapRefresh(); }
  if (v === "meet") hubLoadMeet();
  else if (!h.items.length && !h.loading) hubLoad(false);
}

async function hubLoadIns() {
  try { state.hub.ins = await api("/api/listings/insights"); } catch (e) { state.hub.ins = null; }
  hubDrawIns();
}

/* ---- შეხვედრები (ბინიდან დაგეგმვა · დადასტურება · ხელშეკრულება · დაინტერესების სტატისტიკა) ---- */
const HUB_ST = { pending: "დასადასტურებელი", planned: "დაგეგმილი", done: "ჩატარდა", cancelled: "გაუქმდა", rejected: "უარყოფილია", no_show: "არ გამოცხადდა" };
const HUB_WD = ["კვირა", "ორშაბათი", "სამშაბათი", "ოთხშაბათი", "ხუთშაბათი", "პარასკევი", "შაბათი"];
const HUB_COOP_CHIPS = ["მესაკუთრესთან პირდაპირ", "აგენტთან 50/50", "აგენტთან 100%", "შეთანხმებით"];
state.hub.mv = state.hub.mv || { tab: "clients", items: [], meta: null, stats: null, loading: false, err: "", leads: [], leadsMeta: null };

function hubIso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
function hubDayLabel(iso) {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const d = new Date(String(iso) + "T00:00:00");
  if (isNaN(d)) return String(iso || "—");
  const diff = Math.round((d - t) / 86400000);
  const base = diff === 0 ? "დღეს" : diff === 1 ? "ხვალ" : diff === -1 ? "გუშინ" : HUB_WD[d.getDay()];
  return `${base} · ${String(iso).slice(5).replace("-", "/")}`;
}
function hubMapsUrl(mt) { return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent([mt.city, mt.district, mt.address].filter(Boolean).join(" ")); }

/* მცირე დიალოგი (modalBox-ის გამოყენებით): title, html (ველები), submit-ის ტექსტი, onSubmit(box) -> Promise */
function hubAsk(title, html, submitLabel, onSubmit) {
  const backdrop = document.getElementById("modalBackdrop"), box = document.getElementById("modalBox");
  box.innerHTML = `<h3>${esc(title)}<button class="close" id="modalClose">✕</button></h3><div class="hub-form">${html}</div>
    <div class="hub-row" style="margin-top:12px"><button class="btn" id="hubAskOk">${esc(submitLabel)}</button></div><div class="hub-err" id="hubAskErr" hidden></div>`;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
  const ok = document.getElementById("hubAskOk");
  ok.onclick = async () => {
    ok.disabled = true;
    try { await onSubmit(box); }
    catch (e) { const er = document.getElementById("hubAskErr"); er.hidden = false; er.textContent = e.message || "შეცდომა"; ok.disabled = false; }
  };
  return box;
}

/* ---- ბინიდან შეხვედრის დაგეგმვა ---- */
function hubBookForm(it, pre) {
  pre = pre || state.hub.lead || {};              // კლიენტის დავალებიდან: ტელეფონი/სახელი/task_id წინასწარ ივსება
  const mine = !!it.private;
  const rent = /ქირ/.test(it.deal_type || "");
  const tomorrow = new Date(Date.now() + 86400000);
  const photo = it.photos && it.photos[0];
  const html = `
    <div class="hub-mini">${photo ? `<img referrerpolicy="no-referrer" src="${esc(photo)}" alt="">` : `<div class="hub-noph">🏠</div>`}
      <div><b>${hubMoney(it.price_usd)}${rent ? "/თვე" : ""}</b><div class="muted">${esc([it.district, it.address].filter(Boolean).join(" · "))}</div><div class="muted">${esc(it.agent_name || "")}</div></div></div>
    ${mine ? "" : `<div class="hub-note">🤝 ეს ბინა სხვა აგენტისაა — მოთხოვნა გადაეგზავნება მფლობელ აგენტს დასადასტურებლად. კლიენტის ტელეფონი მას არ გადაეცემა.</div>`}
    ${pre.task_id ? `<div class="hub-note">📥 კლიენტის დავალებიდან — შეხვედრა ამ დავალებას მიება.</div>` : ""}
    <div class="hub-grid2"><label>კლიენტის სახელი *<input id="bkName" placeholder="მაგ: გიორგი მ." value="${esc(pre.client_name || "")}"></label>
      <label>ტელეფონი *<input id="bkPhone" type="tel" inputmode="tel" placeholder="5xx xx xx xx" value="${esc(pre.client_phone || "")}"></label>
      <label>თარიღი *<input id="bkDate" type="date" min="${hubIso(new Date())}" value="${hubIso(tomorrow)}"></label>
      <label>საათი *<input id="bkTime" type="time" value="12:00"></label></div>
    ${rent ? `<div class="hub-k">გაქირავების პერიოდი (თვე)</div><div class="hub-row" id="bkRentChips">${[3, 6, 12, 24].map((n) => `<button class="hub-chip" data-bk-rent="${n}">${n}</button>`).join("")}
      <input id="bkRent" inputmode="numeric" placeholder="სხვა" style="width:80px"></div>
      <div class="hub-grid2"><label>შესვლის თარიღი<input id="bkMove" type="date"></label><label>ბიუჯეტი, $<input id="bkBudget" inputmode="numeric" placeholder="${esc(String(Math.round(it.price_usd || 0)) || "")}"></label></div>`
          : `<div class="hub-grid2"><label>ბიუჯეტი, $<input id="bkBudget" inputmode="numeric" placeholder="${esc(String(Math.round(it.price_usd || 0)) || "")}"></label></div>`}
    <label class="hub-lbl">ვინ ცხოვრობს / კლიენტის მოთხოვნები<input id="bkTenants" placeholder="წყვილი, ბავშვი, შინაური ცხოველი, ექსპატი…"></label>
    <div class="hub-k">თანამშრომლობა მეპატრონესთან</div>
    <div class="hub-row">${HUB_COOP_CHIPS.map((c) => `<button class="hub-chip" data-bk-coop="${esc(c)}">${esc(c)}</button>`).join("")}</div>
    <input id="bkCoop" placeholder="პირობები (მაგ: აგენტთან 50/50, მეპატრონე 1 თვის ავანსს ითხოვს)">
    <label class="hub-lbl">მეპატრონე როდის არის თავისუფალი<input id="bkAvail" placeholder="მაგ: ყოველდღე 18:00-ის მერე"></label>
    <label class="hub-lbl">შენიშვნა<textarea id="bkNotes" rows="2"></textarea></label>`;
  const box = hubAsk("📅 შეხვედრის დაგეგმვა", html, mine ? "📅 დაგეგმვა" : "🤝 მოთხოვნის გაგზავნა", async (bx) => {
    const g = (id) => { const e = bx.querySelector("#" + id); return e ? e.value.trim() : ""; };
    const r = await api("/api/hub/meetings", { method: "POST", body: JSON.stringify({
      listing_id: it.listing_id, client_name: g("bkName"), client_phone: g("bkPhone"), meeting_date: g("bkDate"), meeting_time: g("bkTime"),
      rental_months: rent ? g("bkRent") : "", move_in_date: rent ? g("bkMove") : "", budget_usd: g("bkBudget"), tenants: g("bkTenants"),
      coop_terms: g("bkCoop"), owner_availability: g("bkAvail"), notes: g("bkNotes"), task_id: pre.task_id || "" }) });
    hubHaptic("ok");
    toast(r.meeting.status === "pending" ? "🤝 მოთხოვნა გაიგზავნა — მფლობელი დაადასტურებს" : "✅ შეხვედრა დაგეგმილია");
    closeDetail();
    state.hub.lead = null; hubDrawLeadBar();
    state.hub.mv.tab = pre.task_id ? "clients" : "upcoming";
    hubSetView("meet");
  });
  box.querySelectorAll("[data-bk-rent]").forEach((b) => { b.onclick = () => { box.querySelector("#bkRent").value = b.dataset.bkRent; box.querySelectorAll("[data-bk-rent]").forEach((x) => x.classList.toggle("on", x === b)); }; });
  box.querySelectorAll("[data-bk-coop]").forEach((b) => { b.onclick = () => { box.querySelector("#bkCoop").value = b.dataset.bkCoop; box.querySelectorAll("[data-bk-coop]").forEach((x) => x.classList.toggle("on", x === b)); }; });
}

/* ---- შეხვედრების სია ---- */
async function hubLoadMeet() {
  const mv = state.hub.mv;
  mv.loading = true; mv.err = ""; hubDrawMeet();
  try {
    const listless = ["clients", "attention", "criteria"].includes(mv.tab);          // ამ ჩანართებს შეხვედრების სია არ სჭირდება
    const mtab = listless ? "upcoming" : mv.tab;
    const [list, stats, leads, att, crit] = await Promise.all([api("/api/hub/meetings?view=" + encodeURIComponent(mtab) + (mtab === "past" ? "&days=60" : "")), api("/api/hub/stats?days=30"),
      api("/api/hub/leads?view=open").catch(() => ({ items: [], total: 0, unseen_mine: 0, can_manage: false, agents: [] })),
      api("/api/hub/attention").catch(() => ({ items: [], total: 0, counts: {} })),
      mv.tab === "criteria" ? api("/api/hub/criteria").catch(() => ({ items: [], total: 0 })) : Promise.resolve(mv.crit || { items: [], total: 0 })]);
    mv.items = listless ? [] : list.items; mv.meta = list.meta; mv.stats = stats; mv.leads = leads.items || []; mv.leadsMeta = leads; mv.att = att; mv.crit = crit;
    hubSetBadge();
  } catch (e) { mv.err = e.message || "შეცდომა"; }
  mv.loading = false;
  hubDrawMeet();
}
function hubMeetCard(mt) {
  const st = mt.status, thumb = mt.photo ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(mt.photo)}" alt="" onerror="this.style.display='none'">` : `<div class="hub-noph">🏠</div>`;
  const rent = /ქირ/.test(mt.deal_type || "");
  const acts = [];
  if (mt.can_decide) acts.push(`<button class="btn" data-mt-act="accept">✅ დადასტურება</button><button class="btn secondary" data-mt-act="resched">🕒 სხვა დრო</button><button class="btn secondary" data-mt-act="reject">❌ უარი</button>`);
  if (mt.can_close) acts.push(`<button class="btn" data-mt-act="done">✅ ჩატარდა</button><button class="btn secondary" data-mt-act="no_show">🚫 არ მოვიდა</button>`);
  if (mt.can_contract) acts.push(`<button class="btn secondary" data-mt-act="contract">📑 ხელშეკრულება</button>`);
  if (mt.can_cancel && !mt.can_decide) acts.push(`<button class="btn secondary" data-mt-act="cancel">გაუქმება</button>`);
  return `<div class="hub-mt st-${st}" data-mt-id="${esc(mt.hub_id)}">
    <div class="hub-mt-top"><div class="hub-mt-th">${thumb}</div>
      <div class="hub-mt-main">
        <div class="hub-mt-when"><b>${esc(hubDayLabel(mt.meeting_date))}</b> · ${esc(mt.meeting_time)} <span class="hub-pillst st-${st}">${esc(HUB_ST[st] || mt.status_label || st)}</span></div>
        <div class="hub-mt-addr">📍 ${esc([mt.district, mt.address].filter(Boolean).join(" · ") || "—")}</div>
        <div class="muted">${hubMoney(Number(mt.price_usd) || null)}${rent ? "/თვე" : ""} · ${esc(mt.listing_title || "")}</div></div></div>
    <div class="hub-mt-people">
      <div>👤 <b>${esc(mt.client_name || "—")}</b>${mt.client_phone ? ` · <a href="tel:${esc(String(mt.client_phone).replace(/[^\d+]/g, ""))}">📞 ${esc(mt.client_phone)}</a>` : ""}</div>
      <div>🧑‍💼 ${esc(mt.requester_name || "")}${mt.coop ? ` <span class="muted">→ მფლობელი:</span> ${esc(mt.owner_agent_name || "")}` : ""}</div></div>
    <div class="hub-mt-tags">${mt.rental_months ? `<span class="hub-tag">⏳ ${esc(mt.rental_months)} თვე</span>` : ""}${mt.move_in_date ? `<span class="hub-tag">🔑 ${esc(mt.move_in_date)}</span>` : ""}${mt.budget_usd ? `<span class="hub-tag">💲 ${esc(mt.budget_usd)}</span>` : ""}
      ${mt.coop ? `<span class="hub-tag gold">🤝 თანამშრომლობა</span>` : ""}${mt.coop_terms ? `<span class="hub-tag">${esc(mt.coop_terms)}</span>` : ""}${mt.outcome_label ? `<span class="hub-tag ok">${esc(mt.outcome_label)}</span>` : ""}</div>
    ${mt.tenants || mt.owner_availability || mt.notes || mt.reject_reason ? `<div class="hub-mt-notes">${[mt.tenants && "👪 " + mt.tenants, mt.owner_availability && "🕒 მეპატრონე: " + mt.owner_availability, mt.notes && "📝 " + mt.notes, mt.reject_reason && "💬 უარი: " + mt.reject_reason].filter(Boolean).map(esc).join("<br>")}</div>` : ""}
    <div class="hub-mt-acts">${acts.join("")}<button class="btn secondary" data-mt-act="map">🗺</button><button class="btn secondary" data-mt-act="listing">🏠 ბინა</button></div></div>`;
}
function hubDrawMeet() {
  const mv = state.hub.mv, el = document.getElementById("hubMeet");
  if (!el) return;
  const s = mv.stats, tot = s && s.totals;
  const lm = mv.leadsMeta || {};
  const attN = (mv.att && mv.att.total) || 0;
  const tabs = [["clients", `📥 კლიენტები${lm.total ? ` (${lm.total})` : ""}`], ["attention", `🔔 ყურადღება${attN ? ` (${attN})` : ""}`], ["criteria", "🎯 კრიტერიუმები"],
    ["upcoming", "📅 შეხვედრები"], ["pending", `დასადასტურებელი${mv.meta && mv.meta.pending_for_me ? ` (${mv.meta.pending_for_me})` : ""}`], ["past", "ისტორია"]];
  const strip = tot ? `<div class="hub-ins-top"><div class="hub-stat"><b>${tot.today}</b><span>დღეს</span></div><div class="hub-stat"><b>${tot.tomorrow}</b><span>ხვალ</span></div>
      <div class="hub-stat ${tot.pending ? "warn" : ""}"><b>${tot.pending}</b><span>დასადასტურებელი</span></div><div class="hub-stat"><b>${tot.done}</b><span>ჩატარდა (30დ)</span></div><div class="hub-stat"><b>${tot.contracts}</b><span>ხელშეკრულება</span></div></div>` : "";
  let body = "";
  if (mv.err) body = `<div class="empty">⚠️ ${esc(mv.err)}</div>`;
  else if (mv.tab === "clients") body = mv.loading && !mv.leads.length ? hubSkeleton() : hubLeadsBody(mv);
  else if (mv.tab === "attention") body = mv.loading && !mv.att ? hubSkeleton() : hubAttBody(mv);
  else if (mv.tab === "criteria") body = mv.loading && !mv.crit ? hubSkeleton() : hubCritBody(mv);
  else if (mv.loading && !mv.items.length) body = hubSkeleton();
  else if (!mv.items.length) body = `<div class="empty">${mv.tab === "pending" ? "დასადასტურებელი მოთხოვნა არ არის 🎉" : "შეხვედრა ჯერ არ არის. გახსენით ბინა და დააჭირეთ „შეხვედრის დაგეგმვა“."}</div>`;
  else {
    let last = "";
    body = mv.items.map((mt) => { const g = mt.meeting_date; const head = g !== last ? `<div class="hub-day">${esc(hubDayLabel(g))}</div>` : ""; last = g; return head + hubMeetCard(mt); }).join("");
  }
  const top = s && s.top_listings && s.top_listings.length ? `<div class="hub-k" style="margin-top:14px">🔥 ყველაზე მოთხოვნადი ბინები (30 დღე)</div><div class="hub-toprow">${s.top_listings.map((l) => `
      <div class="hub-topcard" data-hub-top="${esc(l.listing_id)}">${l.photo ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(l.photo)}" alt="" onerror="this.style.display='none'">` : `<div class="hub-noph">🏠</div>`}
        <b>🔥 ${l.meetings}</b><span>${esc(l.district || "")} ${esc(l.address || "")}</span><small>${hubMoney(Number(l.price_usd) || null)}${l.contracts ? " · 📑" + l.contracts : ""}</small></div>`).join("")}</div>` : "";
  const rank = (title, rows, valFn, sub) => rows && rows.length ? `<div class="hub-k" style="margin-top:12px">${title}</div>${rows.slice(0, 6).map((r, i) => `<div class="hub-rank"><span class="n">${i + 1}</span><span class="nm">${esc(r.name)}<small>${esc(r.team || "")}</small></span><span class="v">${valFn(r)}</span></div>`).join("")}` : "";
  const ranks = s ? rank(s.scope === "mine" ? "🏠 შენს ბინებზე შეხვედრები" : "🏠 ვის ბინებზეა ყველაზე მეტი დაინტერესება", s.owners, (r) => `<b>${r.meetings}</b> <small>· ${r.listings} ბინა</small>`)
    + rank(s.scope === "mine" ? "🚶 შენი შეხვედრები" : "🚶 ვინ დადის ყველაზე ხშირად შეხვედრებზე", s.requesters, (r) => `<b>${r.done}</b> <small>/ ${r.meetings}${r.no_show ? " · 🚫" + r.no_show : ""}${r.contracts ? " · 📑" + r.contracts : ""}</small>`) : "";
  el.innerHTML = `${strip}<div class="hub-row" style="margin-top:10px">${tabs.map(([k, l]) => `<button class="hub-chip ${mv.tab === k ? "on" : ""}" data-mt-tab="${k}">${l}</button>`).join("")}</div>
    <div class="hub-mt-list">${body}</div>${top}${ranks}`;
  el.querySelectorAll("[data-mt-tab]").forEach((b) => { b.onclick = () => { hubHaptic(); mv.tab = b.dataset.mtTab; hubLoadMeet(); }; });
  el.querySelectorAll("[data-hub-top]").forEach((c) => { c.onclick = () => hubOpenDetail(c.dataset.hubTop); });
  el.querySelectorAll("[data-mt-act]").forEach((b) => {
    b.onclick = () => { const mt = mv.items.find((x) => x.hub_id === b.closest("[data-mt-id]").dataset.mtId); if (mt) hubMeetAct(mt, b.dataset.mtAct); };
  });
  el.querySelectorAll("[data-ld-act]").forEach((b) => {
    b.onclick = () => { const ld = mv.leads.find((x) => x.task_id === b.closest("[data-ld-id]").dataset.ldId); if (ld) hubLeadAct(ld, b.dataset.ldAct); };
  });
  const nl = document.getElementById("hubNewLead"); if (nl) nl.onclick = () => hubNewLeadForm();
  el.querySelectorAll("[data-att-go]").forEach((b) => { b.onclick = () => { hubHaptic(); mv.tab = b.dataset.attGo; hubLoadMeet(); }; });
  const nc = document.getElementById("hubNewCrit"); if (nc) nc.onclick = () => hubCritForm();
  el.querySelectorAll("[data-crit-act]").forEach((b) => {
    b.onclick = () => { const c = ((mv.crit || {}).items || []).find((x) => x.criteria_id === b.closest("[data-crit-id]").dataset.critId); if (c) hubCritAct(c, b.dataset.critAct); };
  });
}

/* ---- 🔔 ყურადღება: დაგვიანებული Follow-up-ები (შედეგი არ ჩაწერილა / პასუხი არ გაცემულა / კლიენტი მიუღებელია / შეხვედრა არ დაგეგმილა) ---- */
const HUB_ATT = { outcome_missing: ["📝", "შეხვედრის შედეგი არ ჩაწერილა", "upcoming"], pending_undecided: ["⏳", "თანამშრომლობის მოთხოვნას პასუხი არ გაეცა", "pending"],
  lead_unseen: ["🔔", "კლიენტი მიუღებელია", "clients"], lead_no_meeting: ["📅", "კლიენტს შეხვედრა არ დაუგეგმეს", "clients"] };
function hubAttBody(mv) {
  const a = mv.att || { items: [] };
  if (!a.items.length) return `<div class="empty">დაგვიანებული Follow-up არ არის 🎉</div>`;
  const cnt = a.counts || {};
  const sum = Object.keys(HUB_ATT).filter((k) => cnt[k]).map((k) => `<span class="hub-tag">${HUB_ATT[k][0]} ${cnt[k]}</span>`).join("");
  return `<div class="hub-mt-tags" style="margin:6px 0">${sum}</div>` + a.items.map((it) => {
    const m = HUB_ATT[it.kind] || ["•", it.kind, "upcoming"];
    return `<div class="hub-att k-${esc(it.kind)}"><div><b>${m[0]} ${esc(m[1])}</b><div class="muted">${esc(it.text)}</div>
      <div class="muted">${it.agent_name ? "👤 " + esc(it.agent_name) + " · " : ""}${it.age_hours >= 48 ? Math.round(it.age_hours / 24) + " დღე" : it.age_hours + " სთ"}</div></div>
      <button class="btn secondary" data-att-go="${esc(m[2])}">გახსნა</button></div>`;
  }).join("");
}

/* ---- 🎯 კლიენტის კრიტერიუმები და ავტომატური შესატყვისობა ---- */
function hubCritSummary(c) {
  const p = [];
  if (c.deal_type) p.push(c.deal_type);
  if (c.budget_min || c.budget_max) p.push(`💲 ${c.budget_min || "0"}–${c.budget_max || "∞"}`);
  if ((c.districts || []).length) p.push("📍 " + c.districts.join(", "));
  if (c.property_type) p.push(c.property_type);
  if (c.area_min || c.area_max) p.push(`📐 ${c.area_min || "0"}–${c.area_max || "∞"} მ²`);
  if (c.rooms_min || c.rooms_max) p.push(`🚪 ${c.rooms_min || "1"}${c.rooms_max ? "–" + c.rooms_max : "+"}`);
  if (c.bedrooms_min) p.push(`🛏 ${c.bedrooms_min}+`);
  if (c.not_first) p.push("არა 1-ლი სართული");
  if (c.not_last) p.push("არა ბოლო სართული");
  if (c.pets_needed) p.push("🐾 ცხოველი ჰყავს");
  if (c.min_rent_months) p.push(`⏳ ${c.min_rent_months} თვე`);
  if (c.move_in_date) p.push(`🔑 ${c.move_in_date}`);
  return p;
}
function hubCritBody(mv) {
  const items = (mv.crit && mv.crit.items) || [];
  const bar = `<div class="hub-row" style="margin:6px 0 10px"><button class="btn" id="hubNewCrit">➕ ახალი კრიტერიუმი</button>
    <div class="muted" style="flex:1 1 100%">ახალი ბინის დამატებისას შესაბამის აგენტს Telegram-ში მიუვა შეტყობინება — რატომ ერგება და რა არ ემთხვევა.</div></div>`;
  if (!items.length) return bar + `<div class="empty">კრიტერიუმი ჯერ არ არის. დაამატეთ კლიენტის მოთხოვნა — სისტემა თავად მოძებნის ბინებს.</div>`;
  return bar + items.map((c) => `<div class="hub-crit ${c.active ? "" : "off"}" data-crit-id="${esc(c.criteria_id)}">
    <div class="hub-ld-top"><div><b>${esc(c.client_name || "კლიენტი")}</b>${c.client_phone ? ` · <a href="tel:${esc(String(c.client_phone).replace(/[^\d+]/g, ""))}">📞 ${esc(c.client_phone)}</a>` : ""}</div>
      <span class="hub-pillst">${c.active ? "აქტიური" : "შეჩერებულია"}</span></div>
    <div class="muted">${esc(c.agent_name || "")}</div>
    <div class="hub-mt-tags">${hubCritSummary(c).map((x) => `<span class="hub-tag">${esc(x)}</span>`).join("")}</div>
    ${c.notes ? `<div class="hub-mt-notes">📝 ${esc(c.notes)}</div>` : ""}
    <div class="hub-mt-acts"><button class="btn" data-crit-act="matches">🔍 შესაბამისი ბინები</button><button class="btn secondary" data-crit-act="edit">✏️ შეცვლა</button>
      <button class="btn secondary" data-crit-act="toggle">${c.active ? "⏸ შეჩერება" : "▶ გააქტიურება"}</button></div></div>`).join("");
}
function hubCritForm(c) {
  c = c || {};
  const v = (k) => esc(c[k] == null ? "" : String(c[k]));
  const pts = (state.hub.facets && state.hub.facets.property_types) || [];
  const html = `
    <div class="hub-grid2"><label>კლიენტის სახელი<input id="crName" value="${v("client_name")}" placeholder="მაგ: გიორგი მ."></label>
      <label>ტელეფონი *<input id="crPhone" type="tel" inputmode="tel" value="${v("client_phone")}" placeholder="5xx xx xx xx"></label></div>
    <div class="hub-k">გარიგება</div>
    <div class="hub-row" id="crDeal">${[["ქირავდება", "ქირა"], ["იყიდება", "ყიდვა"], ["", "ორივე"]].map(([k, l]) => `<button class="hub-chip ${(c.deal_type || "") === k ? "on" : ""}" data-cr-deal="${esc(k)}">${l}</button>`).join("")}</div>
    <div class="hub-grid2"><label>ბიუჯეტი მინ., $<input id="crBMin" inputmode="numeric" value="${v("budget_min")}"></label><label>ბიუჯეტი მაქს., $<input id="crBMax" inputmode="numeric" value="${v("budget_max")}"></label></div>
    <label class="hub-lbl">რაიონები (მძიმით)<input id="crDist" value="${esc((c.districts || []).join(", "))}" placeholder="ვაკე, საბურთალო"></label>
    <div class="hub-grid2"><label>ტიპი<input id="crType" list="crTypes" value="${v("property_type")}" placeholder="ბინა"><datalist id="crTypes">${pts.map((p) => `<option value="${esc(p)}">`).join("")}</datalist></label>
      <label>სასურველი შესვლა<input id="crMove" type="date" value="${v("move_in_date")}"></label>
      <label>ფართი მინ., მ²<input id="crAMin" inputmode="numeric" value="${v("area_min")}"></label><label>ფართი მაქს., მ²<input id="crAMax" inputmode="numeric" value="${v("area_max")}"></label>
      <label>ოთახები მინ.<input id="crRMin" inputmode="numeric" value="${v("rooms_min")}"></label><label>ოთახები მაქს.<input id="crRMax" inputmode="numeric" value="${v("rooms_max")}"></label>
      <label>საძინებლები მინ.<input id="crBed" inputmode="numeric" value="${v("bedrooms_min")}"></label><label>ქირავნობა მინ., თვე<input id="crMonths" inputmode="numeric" value="${v("min_rent_months")}"></label></div>
    <div class="hub-row" style="margin-top:8px"><label class="hub-chk"><input type="checkbox" id="crNF" ${c.not_first ? "checked" : ""}> არა პირველი სართული</label>
      <label class="hub-chk"><input type="checkbox" id="crNL" ${c.not_last ? "checked" : ""}> არა ბოლო სართული</label>
      <label class="hub-chk"><input type="checkbox" id="crPets" ${c.pets_needed ? "checked" : ""}> 🐾 კლიენტს შინაური ცხოველი ჰყავს</label></div>
    <label class="hub-lbl">შენიშვნა<textarea id="crNotes" rows="2">${v("notes")}</textarea></label>`;
  const box = hubAsk(c.criteria_id ? "✏️ კრიტერიუმის შეცვლა" : "🎯 ახალი კრიტერიუმი", html, "💾 შენახვა", async (bx) => {
    const g = (id) => { const e = bx.querySelector("#" + id); return e ? e.value.trim() : ""; };
    const ck = (id) => { const e = bx.querySelector("#" + id); return !!(e && e.checked); };
    const deal = (bx.querySelector("[data-cr-deal].on") || {}).dataset;
    const r = await api("/api/hub/criteria", { method: "POST", body: JSON.stringify({
      criteria_id: c.criteria_id || "", task_id: c.task_id || "", client_name: g("crName"), client_phone: g("crPhone"), deal_type: deal ? deal.crDeal : "",
      budget_min: g("crBMin"), budget_max: g("crBMax"), districts: g("crDist").split(/[,;|]/).map((x) => x.trim()).filter(Boolean), property_type: g("crType"),
      area_min: g("crAMin"), area_max: g("crAMax"), rooms_min: g("crRMin"), rooms_max: g("crRMax"), bedrooms_min: g("crBed"), min_rent_months: g("crMonths"),
      move_in_date: g("crMove"), not_first: ck("crNF"), not_last: ck("crNL"), pets_needed: ck("crPets"), notes: g("crNotes") }) });
    hubHaptic("ok"); toast(r.existing ? "ℹ️ ასეთი კრიტერიუმი უკვე არსებობს" : "✅ კრიტერიუმი შენახულია"); closeDetail();
    state.hub.mv.tab = "criteria"; hubSetView("meet");
  });
  box.querySelectorAll("[data-cr-deal]").forEach((b) => { b.onclick = () => box.querySelectorAll("[data-cr-deal]").forEach((x) => x.classList.toggle("on", x === b)); });
}
async function hubCritAct(c, act) {
  if (act === "edit") { hubCritForm(c); return; }
  if (act === "toggle") {
    try { await api(`/api/hub/criteria/${encodeURIComponent(c.criteria_id)}/status`, { method: "POST", body: JSON.stringify({ active: !c.active }) }); hubHaptic("ok"); hubLoadMeet(); }
    catch (e) { toast(e.message || "შეცდომა"); }
    return;
  }
  if (act === "matches") {
    let res;
    try { res = await api(`/api/hub/criteria/${encodeURIComponent(c.criteria_id)}/matches`); } catch (e) { toast(e.message || "შეცდომა"); return; }
    const backdrop = document.getElementById("modalBackdrop"), box = document.getElementById("modalBox");
    const rows = (res.items || []).map((x, i) => {
      const L = x.listing, m = x.match, ph = L.photos && L.photos[0], rent = /ქირ/.test(L.deal_type || "");
      return `<div class="hub-match" data-mi="${i}"><div class="hub-mini">${ph ? `<img referrerpolicy="no-referrer" src="${esc(ph)}" alt="" onerror="this.style.display='none'">` : `<div class="hub-noph">🏠</div>`}
        <div><b>${hubMoney(L.price_usd)}${rent ? "/თვე" : ""}</b> <span class="hub-pillst">${m.score}%</span><div class="muted">${esc([L.district, L.address].filter(Boolean).join(" · "))}</div>
        <div class="muted">${esc([L.rooms && L.rooms + " ოთ.", L.area && L.area + " მ²", L.floor && L.floor + " სართ."].filter(Boolean).join(" · "))}</div></div></div>
        <div class="hub-why">${[...m.matched, ...m.mismatched, ...m.unknown].map((t) => `<div>${esc(t)}</div>`).join("")}</div>
        <div class="hub-mt-acts"><button class="btn secondary" data-mi-act="open">🏠 ბინა</button><button class="btn" data-mi-act="book">📅 შეხვედრა</button></div></div>`;
    }).join("");
    box.innerHTML = `<h3>🔍 შესაბამისი ბინები — ${esc(c.client_name || c.client_phone)}<button class="close" id="modalClose">✕</button></h3>
      <div class="muted" style="margin-bottom:8px">${hubCritSummary(c).map(esc).join(" · ")}</div>${rows || `<div class="empty">ამ წუთისთვის შესაბამისი ბინა არ არის — ახალი განცხადების დამატებისას შეგატყობინებთ.</div>`}`;
    backdrop.hidden = false;
    document.getElementById("modalClose").onclick = closeDetail;
    backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
    box.querySelectorAll("[data-mi-act]").forEach((b) => {
      b.onclick = () => { const it = res.items[Number(b.closest("[data-mi]").dataset.mi)].listing; if (b.dataset.miAct === "open") hubOpenDetail(it); else hubBookForm(it, { client_name: c.client_name || "", client_phone: c.client_phone || "", task_id: c.task_id || "" }); };
    });
  }
}

/* ---- კლიენტები (დავალებები) — ერთ სივრცეში ბინებთან და შეხვედრებთან ერთად ---- */
function hubLeadCard(ld) {
  const L = ld.listing, rent = L && /ქირ/.test(L.deal_type || "");
  const pr = { "მაღალი": "hi", "საშუალო": "mid", "დაბალი": "lo" }[ld.priority] || "mid";
  const listing = L ? `<div class="hub-ld-ls" data-ld-act="listing">${L.photo ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(L.photo)}" alt="" onerror="this.style.display='none'">` : `<div class="hub-noph">🏠</div>`}
      <div><b>${hubMoney(Number(L.price_usd) || null)}${rent ? "/თვე" : ""}</b><div class="muted">${esc([L.district, L.address].filter(Boolean).join(" · "))}</div>
      <div class="muted">${esc(L.agent_name || "")}</div></div></div>`
    : (ld.listing_ref ? `<div class="hub-note">🏠 ბინა: ${esc(ld.listing_ref)} (კატალოგში ვერ მოიძებნა)</div>` : `<div class="hub-note">🧊 ზოგადი კლიენტი (ცივი ლიდი)${ld.deal_type ? " · " + esc(ld.deal_type) : ""} — აირჩიეთ ბინა და დაგეგმეთ შეხვედრა</div>`);
  const mts = (ld.meetings || []).map((x) => `<span class="hub-tag gold">📅 ${esc(x.meeting_date)} ${esc(x.meeting_time)} · ${esc(x.status_label || x.status)}</span>`).join("");
  return `<div class="hub-ld pr-${pr}" data-ld-id="${esc(ld.task_id)}">
    <div class="hub-ld-top"><div><b>${ld.client_phone ? `<a href="tel:${esc(String(ld.client_phone).replace(/[^\d+]/g, ""))}">📞 ${esc(ld.client_phone)}</a>` : "კლიენტი"}</b>
      ${ld.is_mine && !ld.seen ? `<span class="hub-new">🔔 ახალი</span>` : ""}</div><span class="hub-pillst">${esc(ld.priority || "")}</span></div>
    <div class="muted">${esc(ld.assigned_to_name || "")}${ld.created_at ? " · " + esc(String(ld.created_at).slice(0, 16)) : ""}${ld.viewing_time ? " · ნახვა: " + esc(ld.viewing_time) : ""}</div>
    ${listing}
    ${ld.notes ? `<div class="hub-mt-notes">📝 ${esc(ld.notes)}</div>` : ""}
    ${mts ? `<div class="hub-mt-tags">${mts}</div>` : ""}
    <div class="hub-mt-acts">
      ${ld.is_mine && !ld.seen ? `<button class="btn" data-ld-act="ack">✅ მივიღე</button>` : ""}
      <button class="btn ${ld.is_mine && !ld.seen ? "secondary" : ""}" data-ld-act="meet">📅 ${L ? "შეხვედრა" : "ბინის არჩევა"}</button>
      <button class="btn secondary" data-ld-act="crit">🎯 კრიტერიუმი</button>
      ${(state.hub.mv.leadsMeta || {}).can_manage ? `<button class="btn secondary" data-ld-act="reassign">🔁 გადაბარება</button>` : ""}
    </div></div>`;
}
function hubLeadsBody(mv) {
  const lm = mv.leadsMeta || {};
  const bar = `<div class="hub-row" style="margin:6px 0 10px">${lm.can_manage ? `<button class="btn" id="hubNewLead">➕ ახალი კლიენტი (ცივი ლიდი)</button>` : ""}
    <div class="muted" style="flex:1 1 100%">${lm.can_manage ? "ბინაზე გადასაბარებლად გახსენით ბინა და დააჭირეთ „👤 კლიენტის გადაბარება“." : "მენეჯერის მიერ გადმოცემული კლიენტები ბინებთან ერთად."}</div></div>`;
  if (!mv.leads.length) return bar + `<div class="empty">ღია კლიენტი არ არის 🎉</div>`;
  return bar + mv.leads.map(hubLeadCard).join("");
}
function hubSetBadge() {
  const mv = state.hub.mv, n = ((mv.meta && mv.meta.pending_for_me) || 0) + ((mv.leadsMeta && mv.leadsMeta.unseen_mine) || 0);
  state.hub.pendingForMe = n;
  const b = document.getElementById("hubMeetBadge"); if (b) { b.textContent = n ? ` ${n}` : ""; b.hidden = !n; }
}
async function hubLeadAct(ld, act) {
  const mv = state.hub.mv;
  if (act === "listing") { if (ld.listing) hubOpenDetail(ld.listing.listing_id); return; }
  if (act === "crit") {                                  // კლიენტის მოთხოვნა -> კრიტერიუმები (ავტომატური შესატყვისობისთვის)
    hubCritForm({ client_phone: ld.client_phone || "", task_id: ld.task_id, deal_type: /ყიდვ/.test(ld.deal_type || "") ? "იყიდება" : (/ქირ/.test(ld.deal_type || "") ? "ქირავდება" : "") });
    return;
  }
  if (act === "ack") {
    try { await api("/api/tasks/ack", { method: "POST", body: JSON.stringify({ task_id: ld.task_id }) }); hubHaptic("ok"); toast("✅ კლიენტი მიღებულია"); hubLoadMeet(); }
    catch (e) { toast(e.message || "შეცდომა"); }
    return;
  }
  if (act === "meet") {
    const pre = { task_id: ld.task_id, client_phone: ld.client_phone || "" };
    if (ld.listing) {                                   // ბინა ცნობილია: პირდაპირ შეხვედრის ფორმა წინასწარ შევსებული კლიენტით
      try { const it = (await api("/api/listings/" + encodeURIComponent(ld.listing.listing_id))).listing; hubBookForm(it, pre); }
      catch (e) { toast(e.message || "შეცდომა"); }
    } else {                                            // ზოგადი კლიენტი: გადავდივართ ბინების სიაზე სათანადო გარიგებით, ზედა ზოლში კლიენტი ჩანს
      state.hub.lead = pre; state.hub.deal = /ყიდვ/.test(ld.deal_type || "") ? "იყიდება" : (/ქირ/.test(ld.deal_type || "") ? "ქირავდება" : "");
      hubSetView("list"); hubDrawLeadBar(); hubReload(); toast("🏠 აირჩიეთ ბინა — შეხვედრაში კლიენტი უკვე ჩაწერილია");
    }
    return;
  }
  if (act === "reassign") {
    const ags = (mv.leadsMeta || {}).agents || [];
    hubAsk("🔁 კლიენტის გადაბარება", `<label class="hub-lbl">აგენტი<select id="raAgent">${ags.map((a) => `<option value="${esc(a.agent_id)}" ${a.agent_id === ld.assigned_to ? "selected" : ""}>${esc(a.name)}${a.team ? " · " + esc(a.team) : ""}</option>`).join("")}</select></label>`,
      "გადაბარება", async (bx) => {
        await api("/api/tasks/reassign", { method: "POST", body: JSON.stringify({ task_id: ld.task_id, to_agent_id: bx.querySelector("#raAgent").value }) });
        hubHaptic("ok"); toast("🔁 გადაბარებულია"); closeDetail(); hubLoadMeet();
      });
  }
}
/* ზედა ზოლი ბინების სიაში, როცა ზოგადი კლიენტისთვის ბინას ვარჩევთ */
function hubDrawLeadBar() {
  const el = document.getElementById("hubLeadBar"), l = state.hub.lead;
  if (!el) return;
  if (!l) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  el.innerHTML = `📥 კლიენტი ${esc(l.client_phone || "")} — აირჩიეთ ბინა <button class="hub-link" id="hubLeadCancel">✕ გაუქმება</button>`;
  document.getElementById("hubLeadCancel").onclick = () => { state.hub.lead = null; hubDrawLeadBar(); };
}
function hubNewLeadForm() {
  const ags = (state.hub.mv.leadsMeta || {}).agents || [];
  hubAsk("➕ ახალი კლიენტი (ცივი ლიდი)", `
    <label class="hub-lbl">ტელეფონი *<input id="nlPhone" type="tel" inputmode="tel" placeholder="5xx xx xx xx"></label>
    <div class="hub-k">გარიგება</div><div class="hub-row" id="nlDeal"><button class="hub-chip on" data-v="ქირა">ქირა</button><button class="hub-chip" data-v="ყიდვა">ყიდვა</button></div>
    <div class="hub-k">პრიორიტეტი</div><div class="hub-row" id="nlPri"><button class="hub-chip on" data-v="მაღალი">მაღალი</button><button class="hub-chip" data-v="საშუალო">საშუალო</button><button class="hub-chip" data-v="დაბალი">დაბალი</button></div>
    <label class="hub-lbl">ვის გადაეცეს<select id="nlAgent"><option value="">🤖 ავტომატურად (საუკეთესო აგენტი)</option><option value="__me">👤 ჩემზე</option>${ags.map((a) => `<option value="${esc(a.agent_id)}">${esc(a.name)}${a.team ? " · " + esc(a.team) : ""}</option>`).join("")}</select></label>
    <label class="hub-lbl">დეტალი / შენიშვნა<textarea id="nlNotes" rows="2" placeholder="რა სჭირდება კლიენტს (ბიუჯეტი, რაიონი...)"></textarea></label>`,
  "გაგზავნა", async (bx) => {
    const pick = (id) => (bx.querySelector("#" + id + " .on") || {}).dataset.v;
    const a = bx.querySelector("#nlAgent").value;
    const body = { kind: "general", phone: bx.querySelector("#nlPhone").value.trim(), deal_type: pick("nlDeal"), priority: pick("nlPri"), notes: bx.querySelector("#nlNotes").value.trim() };
    if (a === "__me") body.assign_to_self = true; else if (a) body.agent_id = a;
    await api("/api/tasks/new", { method: "POST", body: JSON.stringify(body) });
    hubHaptic("ok"); toast("✅ კლიენტი გაიგზავნა"); closeDetail(); hubLoadMeet();
  });
  ["nlDeal", "nlPri"].forEach((id) => document.querySelectorAll("#" + id + " .hub-chip").forEach((b) => { b.onclick = () => document.querySelectorAll("#" + id + " .hub-chip").forEach((x) => x.classList.toggle("on", x === b)); }));
}
/* ბინიდან კლიენტის გადაბარება (მენეჯერი): არსებული /api/tasks/new, ბინა მიება დავალებას */
function hubAssignForm(it) {
  const ags = (state.hub.mv.leadsMeta || {}).agents || [];
  const def = ags.find((a) => a.agent_id === it.agent_id) ? it.agent_id : (ags[0] || {}).agent_id;
  hubAsk("👤 კლიენტის გადაბარება ამ ბინაზე", `
    <div class="hub-mini"><div class="hub-noph" style="width:56px;height:56px;flex:0 0 56px">🏠</div><div><b>${hubMoney(it.price_usd)}</b><div class="muted">${esc([it.district, it.address].filter(Boolean).join(" · "))}</div></div></div>
    <label class="hub-lbl">კლიენტის ტელეფონი *<input id="asPhone" type="tel" inputmode="tel" placeholder="5xx xx xx xx"></label>
    <label class="hub-lbl">აგენტი<select id="asAgent">${ags.map((a) => `<option value="${esc(a.agent_id)}" ${a.agent_id === def ? "selected" : ""}>${esc(a.name)}${a.team ? " · " + esc(a.team) : ""}</option>`).join("")}</select></label>
    <div class="hub-grid2"><label>ნახვის თარიღი<input id="asDate" type="date" min="${hubIso(new Date())}"></label><label>საათი<input id="asTime" type="time"></label></div>
    <label class="hub-lbl">დეტალი / შენიშვნა<textarea id="asNotes" rows="2"></textarea></label>`,
  "გაგზავნა", async (bx) => {
    const d = bx.querySelector("#asDate").value, tm = bx.querySelector("#asTime").value;
    await api("/api/tasks/new", { method: "POST", body: JSON.stringify({ kind: "listing", agent_id: bx.querySelector("#asAgent").value, listing_id: String(it.myhome_id || it.ssge_id || it.listing_id),
      phone: bx.querySelector("#asPhone").value.trim(), viewing_time: d ? (d + (tm ? " " + tm : "")) : "", notes: bx.querySelector("#asNotes").value.trim(), owner_phone: it.owner_number || "" }) });
    hubHaptic("ok"); toast("✅ კლიენტი გადაეცა აგენტს"); closeDetail(); state.hub.mv.tab = "clients"; hubSetView("meet");
  });
}
async function hubMeetPost(mt, path, body, okMsg) {
  await api(`/api/hub/meetings/${encodeURIComponent(mt.hub_id)}/${path}`, { method: "POST", body: JSON.stringify(body || {}) });
  hubHaptic("ok"); toast(okMsg); closeDetail(); hubLoadMeet(); hubLoadMeetBadge();
}
function hubMeetAct(mt, act) {
  if (act === "map") { hubOpenLink(hubMapsUrl(mt)); return; }
  if (act === "listing") { hubOpenDetail(mt.listing_id); return; }
  if (act === "accept") { hubMeetPost(mt, "decide", { action: "accept" }, "✅ დადასტურდა — შეხვედრა დაგეგმილია").catch((e) => toast(e.message || "შეცდომა")); return; }
  if (act === "resched") {
    hubAsk("🕒 სხვა დროით დადასტურება", `<div class="hub-grid2"><label>თარიღი<input id="rsDate" type="date" value="${esc(mt.meeting_date)}"></label><label>საათი<input id="rsTime" type="time" value="${esc(mt.meeting_time)}"></label></div>`,
      "✅ დადასტურება ახალი დროით", (bx) => hubMeetPost(mt, "decide", { action: "accept", meeting_date: bx.querySelector("#rsDate").value, meeting_time: bx.querySelector("#rsTime").value }, "✅ დადასტურდა ახალი დროით"));
    return;
  }
  if (act === "reject") { hubAsk("❌ უარი", `<label class="hub-lbl">მიზეზი (მომთხოვნს გაეგზავნება)<input id="rjReason" placeholder="მაგ: უკვე გაქირავდა / დაკავებულია"></label>`, "უარის გაგზავნა", (bx) => hubMeetPost(mt, "decide", { action: "reject", reason: bx.querySelector("#rjReason").value }, "უარი გაიგზავნა")); return; }
  if (act === "done") {
    const oc = { interested: "დაინტერესდა", thinking: "ფიქრობს", refused: "უარი თქვა", deal: "გარიგება", other: "სხვა" };
    hubAsk("✅ შეხვედრა ჩატარდა", `<div class="hub-k">შედეგი</div><div class="hub-row" id="dnOc">${Object.keys(oc).map((k, i) => `<button class="hub-chip ${i === 0 ? "on" : ""}" data-oc="${k}">${oc[k]}</button>`).join("")}</div>
      <label class="hub-lbl">შენიშვნა<input id="dnNote" placeholder="რა მოხდა / შემდეგი ნაბიჯი"></label>`, "შენახვა", (bx) => hubMeetPost(mt, "status", { status: "done", outcome: (bx.querySelector("#dnOc .on") || {}).dataset.oc || "other", note: bx.querySelector("#dnNote").value }, "✅ ჩაიწერა"));
    document.querySelectorAll("#dnOc [data-oc]").forEach((b) => { b.onclick = () => document.querySelectorAll("#dnOc [data-oc]").forEach((x) => x.classList.toggle("on", x === b)); });
    return;
  }
  if (act === "no_show") { if (confirm("მონიშნოთ, რომ კლიენტი არ გამოცხადდა?")) hubMeetPost(mt, "status", { status: "no_show" }, "მონიშნულია").catch((e) => toast(e.message || "შეცდომა")); return; }
  if (act === "cancel") { if (confirm("გავაუქმოთ შეხვედრა? მეორე მხარეს შეტყობინება გაეგზავნება.")) hubMeetPost(mt, "status", { status: "cancelled" }, "გაუქმდა").catch((e) => toast(e.message || "შეცდომა")); return; }
  if (act === "contract") { hubContract(mt); return; }
}
/* ხელშეკრულების მოთხოვნა შეხვედრიდან — არსებული ხელშეკრულებების მოდულის ფორმით (მოთხოვნა ეყრდნობა ძველ meeting_id-ს) */
async function hubContract(mt) {
  if (!mt.meeting_id) { toast("შეხვედრა ჯერ არ არის დადასტურებული"); return; }
  try {
    const d = await api("/api/contracts/meeting/" + encodeURIComponent(mt.meeting_id));
    ctOpenRequestForm({ meeting_id: mt.meeting_id, meeting_date: mt.meeting_date, time: mt.meeting_time, agent_name: mt.requester_name, address: mt.address,
      myhome_id: mt.myhome_id, ssge_id: mt.ssge_id, client_phone: mt.client_phone }, d);
  } catch (e) { toast(e.message || "შეცდომა"); }
}
async function hubLoadMeetBadge() {
  try {
    const [r, l] = await Promise.all([api("/api/hub/meetings?view=pending"), api("/api/hub/leads?view=open").catch(() => null)]);
    const mv = state.hub.mv;
    mv.meta = Object.assign({}, mv.meta, r.meta);
    if (l) { mv.leadsMeta = l; mv.leads = l.items || []; }
    hubSetBadge();
  } catch (e) { /* ბეჯი არასავალდებულოა */ }
}
async function hubEnsureLeadsMeta() {                 // მენეჯერის აგენტების სია (გადაბარების ფორმებისთვის)
  const mv = state.hub.mv;
  if (mv.leadsMeta && mv.leadsMeta.agents) return;
  try { const l = await api("/api/hub/leads?view=open"); mv.leadsMeta = l; mv.leads = l.items || []; } catch (e) { /* ფორმა სიის გარეშე გაიხსნება */ }
}

/* ---- ადმინის ინსტრუმენტები: სიახლის ზღვრები + CSV ექსპორტი (ფაილი Telegram-ში მოდის) ---- */
async function hubAdminSettings() {
  let s;
  try { s = await api("/api/hub/settings"); } catch (e) { toast(e.message || "შეცდომა"); return; }
  const t = s.thresholds || {};
  hubAsk("⚙️ სიახლის ზღვრები (დღე)", `
    <div class="hub-note">მწვანე: 0–<b>ახალი</b> დღე · ნარინჯისფერი: –<b>საშუალო</b> · წითელი: –<b>ძველი</b> · მეტი — ნაცრისფერი (გადასამოწმებელი). წესი: ახალი &lt; საშუალო &lt; ძველი.</div>
    <div class="hub-grid2"><label>ახალი (მწვანე)<input id="thFresh" inputmode="numeric" value="${esc(t.fresh)}"></label><label>საშუალო (ნარინჯისფერი)<input id="thMid" inputmode="numeric" value="${esc(t.mid)}"></label>
    <label>ძველი (წითელი)<input id="thStale" inputmode="numeric" value="${esc(t.stale)}"></label></div>`,
  "შენახვა", async (bx) => {
    await api("/api/hub/settings", { method: "POST", body: JSON.stringify({ fresh: bx.querySelector("#thFresh").value, mid: bx.querySelector("#thMid").value, stale: bx.querySelector("#thStale").value }) });
    hubHaptic("ok"); toast("✅ ზღვრები შენახულია"); closeDetail(); hubReload(); hubLoadIns();
  });
}
async function hubAdminExport(kind) {
  try {
    const r = await api("/api/hub/export", { method: "POST", body: JSON.stringify({ kind }) });
    hubHaptic("ok"); toast(`📄 ფაილი (${r.rows} ჩანაწერი) გამოგეგზავნათ Telegram-ში`);
  } catch (e) { toast(e.message || "შეცდომა"); }
}

async function renderHub(content) {
  const h = state.hub;
  h.map = null; h.mapSeq++;
  content.innerHTML = `
    <div class="card hub-head">
      <div class="hub-title"><h2>🏙️ განცხადებები</h2><span class="sub" id="hubCount"></span></div>
      <div class="hub-seg"><button data-hub-view="list" class="${h.view === "list" ? "on" : ""}">📋 სია</button><button data-hub-view="map" class="${h.view === "map" ? "on" : ""}">🗺 რუკა</button><button data-hub-view="meet" class="${h.view === "meet" ? "on" : ""}">📥 სამუშაო<b id="hubMeetBadge" class="hub-badge" hidden></b></button></div>
      <div id="hubFilters" ${h.view === "meet" ? "hidden" : ""}>
        <div class="hub-search"><input id="hubQ" type="search" placeholder="მაგ: 3 ოთახი საბურთალო 500$-მდე ქირა · ID · მისამართი" value="${esc(h.q)}">
          <button class="btn secondary" id="hubFilterBtn">⚙️</button></div>
        <div id="hubChips"></div><div id="hubPanel" class="hub-panel" hidden></div>
      </div>
    </div>
    <div id="hubLeadBar" class="hub-leadbar" hidden></div>
    <div class="card hub-ins" id="hubIns" ${h.view === "meet" ? "hidden" : ""}></div>
    <div id="hubMeet" class="hub-meetbox" ${h.view === "meet" ? "" : "hidden"}></div>
    <div id="hubMapBox" class="hub-mapbox" ${h.view === "map" ? "" : "hidden"}><div class="empty">იტვირთება…</div></div>
    <div id="hubMapInfo" class="hub-mapinfo"></div>
    <div id="hubList" class="hub-grid"></div><div id="hubMore" class="hub-more"></div>`;
  let t = null;
  document.getElementById("hubQ").oninput = (e) => { h.q = e.target.value; clearTimeout(t); t = setTimeout(hubReload, 380); };
  document.getElementById("hubFilterBtn").onclick = () => { h.panel = !h.panel; hubDrawPanel(); };
  document.querySelectorAll("[data-hub-view]").forEach((b) => { b.onclick = () => { hubHaptic(); hubSetView(b.dataset.hubView); }; });
  hubDrawChips(); hubDrawPanel(); hubDrawList(); hubDrawIns(); hubDrawLeadBar();
  hubLoadIns(); hubLoadMeetBadge(); hubSyncFavs();
  if (h.view === "meet") { hubLoadMeet(); return; }
  await hubLoad(false);
}

/* ===== 🩺 სისტემის ჯანმრთელობა (მხოლოდ ადმინი; თიმლიდერს არ უჩანს) ===== */
const SYS_TAB = { id: "system", label: "სისტემა", icon: "🩺" };
const SYS_LVL = { ok: "🟢", warn: "🟡", bad: "🔴", unknown: "⚪" };
const SYS_LVL_TXT = { ok: "ყველაფერი რეალურად მუშაობს", warn: "ყურადღება სჭირდება", bad: "პრობლემაა — საჭიროა მოქმედება", unknown: "ზოგი კომპონენტი ვერ დადასტურდა" };
const SYS_CAUSE = { no_worker: "worker არ ჩანს", offline: "ოფლაინი", disabled: "გამორთულია", paused: "პაუზაა", login: "შესვლა სჭირდება", not_polling: "job-ს არ ითხოვს", team_mismatch: "გუნდი არ ემთხვევა", busy: "სხვა job-ზე მუშაობს", queue_backlog: "რიგია" };
function sysExtra(key, c) {
  const d = c.data;
  if (key === "workers") return (Array.isArray(d) ? d : []).map((w) => `<div class="sys-row"><span>${w.healthy ? "🟢" : "🔴"} ${esc(w.label || w.worker_id || "")}</span><span>${esc(w.online ? (w.state_label || "") : "ოფლაინი")}${w.reason ? " · " + esc(w.reason) : ""} · ${esc(w.version || "v?")} · ♥ ${w.age_seconds == null ? "—" : w.age_seconds + "წმ"} · job-მოთხოვნა ${w.poll_age_seconds == null ? "—" : w.poll_age_seconds + "წმ"}</span></div>`).join("");
  if (key === "queue") return ((d && d.stuck) || []).slice(0, 6).map((s) => `<div class="sys-row"><span>${esc(s.label)} · ${esc(s.agent_name || "")} · ${esc(String(s.source_id || ""))}</span><span>${s.age_min} წთ · ${esc(SYS_CAUSE[s.cause] || s.cause)}</span></div>`).join("");
  if (key === "uploads") return ((d && d.failures) || []).slice(0, 6).map((f) => `<div class="sys-row"><span>${esc(f.portal)} · ${esc(f["class"])}</span><span>${f.count}${f.repeating ? " 🔁 განმეორებადი" : ""}</span></div>`).join("");
  if (key === "bot_jobs") return (Array.isArray(d) ? d : []).filter((j) => j.status !== "ok").slice(0, 8).map((j) => `<div class="sys-row"><span>${esc(j.name)}</span><span>${esc(j.status)}${j.last_error ? " · " + esc(j.last_error) : ""}</span></div>`).join("");
  return "";
}
function sysCard(key, c) {
  return `<div class="sys-card lv-${esc(c.level)}" data-sys="${esc(key)}"><div class="sys-h"><span class="sys-dot">${SYS_LVL[c.level] || SYS_LVL.unknown}</span><b>${esc(c.title)}</b></div>
    <div class="sys-d">${esc(c.detail || "")}</div>${sysExtra(key, c)}</div>`;
}
function sysQualityCard(ins) {
  if (!ins || !ins.totals) return "";
  const t = ins.totals, bad = (n) => (n ? `<b class="warn">${n}</b>` : `<b>${n}</b>`);
  return `<div class="sys-card lv-${t.no_photo || t.no_coords || t.dup_listings ? "warn" : "ok"}" data-sys="quality"><div class="sys-h"><span class="sys-dot">📦</span><b>განცხადებების მონაცემთა ხარისხი</b></div>
    <div class="sys-d">სულ ${t.total} აქტიური განცხადება</div>
    <div class="sys-row"><span>📷 ფოტო აკლია</span>${bad(t.no_photo)}</div><div class="sys-row"><span>📍 კოორდინატი აკლია</span>${bad(t.no_coords)}</div>
    <div class="sys-row"><span>📐 ფართი აკლია</span>${bad(t.no_area || 0)}</div><div class="sys-row"><span>🛏 ოთახობა აკლია</span>${bad(t.no_rooms || 0)}</div>
    <div class="sys-row"><span>💲 ფასი აკლია</span>${bad(t.no_price || 0)}</div><div class="sys-row"><span>⚠️ შესაძლო დუბლიკატი</span>${bad(t.dup_listings || 0)}</div>
    <div class="sys-row"><span>🕘 გადასამოწმებელი (წითელი/ნაცრისფერი)</span>${bad((t.fresh.red || 0) + (t.fresh.grey || 0))}</div>
    <div class="sys-row"><span>📥 ძველი (backfill — ფოტო/კოორდინატის გარეშე)</span>${bad(t.backfill_only || 0)}</div></div>`;
}
async function renderSystem(content) {
  if (state.sysTimer) { clearTimeout(state.sysTimer); state.sysTimer = null; }
  if (!content.querySelector("[data-sys]")) content.innerHTML = `<div class="card"><div class="empty">იტვირთება…</div></div>`;
  let rep, ins = null;
  try {
    [rep, ins] = await Promise.all([api("/api/system/health"), api("/api/listings/insights").catch(() => null)]);
  } catch (e) { content.innerHTML = `<div class="card"><div class="empty">⚠️ ${esc(e.message || "შეცდომა")}</div></div>`; return; }
  const order = ["workers", "queue", "uploads", "bot_jobs", "backend", "sheets", "notifications", "backup"];
  const comps = rep.components || {};
  content.innerHTML = `<div class="sys-banner lv-${esc(rep.overall)}"><span class="sys-dot">${SYS_LVL[rep.overall] || SYS_LVL.unknown}</span><div><b>${esc(SYS_LVL_TXT[rep.overall] || "")}</b>
      <div class="muted">„მწვანე“ მხოლოდ რეალური მუშაობით; რაც ვერ დადასტურდა — ⚪</div></div><button class="btn secondary" id="sysRefresh">🔄</button></div>
    ${order.filter((k) => comps[k]).map((k) => sysCard(k, comps[k])).join("")}${sysQualityCard(ins)}`;
  const rb = document.getElementById("sysRefresh"); if (rb) rb.onclick = () => renderSystem(content);
  state.sysTimer = setTimeout(() => { if (state.tab[state.role] === "system") renderSystem(content); }, 30000);
}

/* ტაბების დაჯგუფება: მთავარ ზოლზე მხოლოდ ყოველდღიური ტაბები, დანარჩენი — „სხვა“-ში (არცერთი ფუნქცია არ იმალება — ყველა ერთი შეხებით მისაწვდომია) */
const PRIMARY_TABS = {
  agent: ["today", "hub", "myhomejobs", "tasks", "crm2", "kpi"],
  admin: ["overview", "finance", "hub", "team", "attendance", "myhomejobs", "system"],
};
function tabGroups(role, tabs) {
  const want = PRIMARY_TABS[role] || [];
  const primary = want.map((id) => tabs.find((t) => t.id === id)).filter(Boolean);
  const rest = tabs.filter((t) => !primary.includes(t));
  return { primary, rest };
}
function openMoreSheet(rest) {
  let el = document.getElementById("moreSheet");
  if (!el) { el = document.createElement("div"); el.id = "moreSheet"; el.className = "more-sheet"; document.body.appendChild(el); }
  el.hidden = false;
  el.innerHTML = `<div class="more-box"><div class="more-h"><b>სხვა განყოფილებები</b><button class="close" id="moreClose" aria-label="დახურვა">✕</button></div>
    <div class="more-grid">${rest.map((t) => `<button data-more-tab="${esc(t.id)}" class="${state.tab[state.role] === t.id ? "active" : ""}"><span class="ic">${t.icon}</span>${esc(t.label)}</button>`).join("")}</div></div>`;
  const close = () => { el.hidden = true; };
  el.onclick = (e) => { if (e.target === el) close(); };
  document.getElementById("moreClose").onclick = close;
  el.querySelectorAll("[data-more-tab]").forEach((b) => { b.onclick = () => { state.tab[state.role] = b.dataset.moreTab; close(); renderContent(); }; });
}

/* `adminOnly` ტაბები (მაგ. აგენტების/მენეჯერების მართვა) დირექტორის
   დონის მოქმედებაა — თიმლიდერს (რომელიც ტექნიკურად იმავე "admin"
   role-ზეა Mini App-ში, საკუთარი გუნდის ფილტრირებული ხედვით) არ
   უჩნდება, რომ არ დაერიოს პირამიდის სტრუქტურაში. */
function tabsFor(role) {
  let tabs = role === "admin" ? ADMIN_TABS : AGENT_TABS;
  if (role === "admin" && state.data && state.data.is_team_lead) {
    tabs = tabs.filter((t) => !t.adminOnly);
  }
  if (role === "admin" && state.data && !state.data.is_team_lead) {     // 🩺 სისტემის ჯანმრთელობა — მხოლოდ დირექტორი/ადმინი (სერვერიც ამოწმებს)
    tabs = tabs.slice();
    tabs.push(SYS_TAB);
  }
  // 💰 ფინანსები: მხოლოდ სერვერის მიერ დადასტურებულ ID-ს (ან ადმინს ინსტრუქციისთვის, სანამ ჯერ არავინ არის მითითებული)
  const fa = state.finAccess;
  if (fa && (fa.allowed || (fa.setup && role === "admin"))) {
    tabs = tabs.slice();
    tabs.splice(1, 0, FIN_TAB);
  }
  // 🏙️ განცხადებების კატალოგი (Property Hub): ყველა როლს; ფინანსების ტაბის (თუ ჩანს) მერე, რომ მისი ადგილი არ შეიცვალოს
  tabs = tabs.slice();
  tabs.splice(tabs.includes(FIN_TAB) ? 2 : 1, 0, HUB_TAB);
  return tabs;
}

function renderTabbar() {
  const tabs = tabsFor(state.role);
  if (!state.tab[state.role]) state.tab[state.role] = tabs[0].id;
  const bar = document.getElementById("tabbar");
  bar.hidden = false;
  const { primary, rest } = tabGroups(state.role, tabs);
  const cur = state.tab[state.role];
  const inRest = rest.find((t) => t.id === cur);
  const btn = (t) => `
    <button data-tab="${t.id}" class="${cur === t.id ? "active" : ""}">
      <span class="ic">${t.icon}</span>${esc(t.label)}
    </button>`;
  bar.innerHTML = primary.map(btn).join("") + (rest.length ? `
    <button data-more="1" class="${inRest ? "active" : ""}"><span class="ic">${inRest ? inRest.icon : "☰"}</span>${esc(inRest ? inRest.label : "სხვა")}</button>` : "");
  bar.querySelectorAll("button[data-tab]").forEach((b) => {
    b.onclick = () => { state.tab[state.role] = b.dataset.tab; renderContent(); };
  });
  const more = bar.querySelector("button[data-more]");
  if (more) more.onclick = () => openMoreSheet(rest);
}

async function renderContent() {
  const content = document.getElementById("content");
  const d = state.data;
  renderTabbar(); // ჯერ ტაბის ნაგულისხმევ მნიშვნელობას აყენებს (პირველი ჩატვირთვისას ცარიელი იყო)
  const tab = state.tab[state.role];

  try {
    if (tab !== "system" && state.sysTimer) { clearTimeout(state.sysTimer); state.sysTimer = null; }
    if (tab === "finance") { await renderFinance(content); return; }
    if (tab === "hub") { await renderHub(content); return; }
    if (tab === "system") { await renderSystem(content); return; }
    if (LAZY_ENDPOINTS[tab]) {
      if (!lazyCache[tab]) {
        content.innerHTML = `<div class="card"><div class="empty">იტვირთება…</div></div>`;
        try {
          let url = LAZY_ENDPOINTS[tab];
          const params = [];
          if (PERIOD_AWARE_TABS.has(tab)) params.push("period=" + encodeURIComponent(state.period));
          if (tab === "taskhistory") {
            if (state.historyTeam) params.push("team=" + encodeURIComponent(state.historyTeam));
            if (state.historyAgent) params.push("agent_id=" + encodeURIComponent(state.historyAgent));
          }
          if (tab === "reports") {
            if (state.reportsTeam) params.push("team=" + encodeURIComponent(state.reportsTeam));
            if (state.reportsAgent) params.push("agent_id=" + encodeURIComponent(state.reportsAgent));
            if (state.reportsDate) params.push("date=" + encodeURIComponent(state.reportsDate));
          }
          if (tab === "digest" && state.digestTeam) params.push("team=" + encodeURIComponent(state.digestTeam));
          if (tab === "meetings" && state.meetingsScope === "own") params.push("scope=own");
          if (tab === "myhomestats") {
            if (state.mhStatsFrom) params.push("date_from=" + encodeURIComponent(state.mhStatsFrom));
            if (state.mhStatsTo) params.push("date_to=" + encodeURIComponent(state.mhStatsTo));
          }
          if (tab === "myhomejobs") params.push("limit=" + (state.mhLimit || 150));
          if (tab === "myattendance" && state.myAttMonth) params.push("month=" + encodeURIComponent(state.myAttMonth));
          if (tab === "attendance") {
            if (state.attDate) params.push("date=" + encodeURIComponent(state.attDate));
            if (state.attTeam) params.push("team=" + encodeURIComponent(state.attTeam));
            if (state.attState) params.push("state=" + encodeURIComponent(state.attState));
            if (state.attGeo) params.push("geo=" + encodeURIComponent(state.attGeo));
            if (state.attLate) params.push("late=1");
          }
          if (tab === "districts") {
            if (state.distWeek) params.push("week=" + encodeURIComponent(state.distWeek));
            if (state.distTeam) params.push("team=" + encodeURIComponent(state.distTeam));
          }
          if (params.length) url += "?" + params.join("&");
          const resp = await api(url);
          if (tab === "myhomejobs") { state.workers = resp.workers || null; state.mhTotal = resp.total || null; }
          const wholeObjTabs = ["contracts", "admintasks", "agentsmgmt", "meetings", "taskhistory", "digest", "reports", "dayoffs", "swaps", "regulations", "mydayoffs", "attendance", "districts"];
          lazyCache[tab] = wholeObjTabs.includes(tab) ? resp : (resp.rows || []);
        } catch (e) {
          content.innerHTML = `<div class="card"><div class="empty">⚠️ ${esc(e.message)}</div></div>`;
          return;
        }
      }
      const rows = lazyCache[tab];
      if (tab === "exclusives") { content.innerHTML = renderExclusives(rows); bindExclusivesActions(rows); }
      else if (tab === "myhomejobs") { content.innerHTML = renderMyHomeJobs(rows, state.role); bindMyHomeJobsActions(); }
      else if (tab === "myhomestats") { content.innerHTML = renderMyHomeStats(rows); bindMyHomeStatsActions(); }
      else if (tab === "reports") { content.innerHTML = renderReports(rows); bindReportsActions(rows); }
      else if (tab === "swaps") { content.innerHTML = renderSwaps(rows); bindSwapsActions(rows); }
      else if (tab === "questions") { content.innerHTML = renderQuestions(rows, state.role); bindQuestionsActions(state.role); }
      else if (tab === "admintasks") { content.innerHTML = renderAdminTasks(rows); bindAdminTasksActions(); }
      else if (tab === "agentsmgmt") { content.innerHTML = renderAgentsMgmt(rows); bindAgentsMgmtActions(); }
      else if (tab === "meetings") { content.innerHTML = renderMeetings(rows); bindPeriodSwitch(); bindMeetingsActions(rows); }
      else if (tab === "taskhistory") { content.innerHTML = renderTaskHistory(rows); bindTaskHistoryActions(rows); }
      else if (tab === "digest") { content.innerHTML = renderDigest(rows); bindDigestActions(); }
      else if (tab === "dayoffs") { content.innerHTML = renderDayoffs(rows); bindDayoffsActions(rows); }
      else if (tab === "agentrequests") { content.innerHTML = renderAgentRequests(rows); bindAgentRequestsActions(); }
      else if (tab === "regulations") { content.innerHTML = renderRegulations(rows); bindRegulationsActions(); }
      else if (tab === "warnings") { content.innerHTML = renderWarnings(rows); bindWarningsActions(rows); }
      else if (tab === "clients") { content.innerHTML = renderClients(rows); bindClientsActions(rows); }
      else if (tab === "crm2") { content.innerHTML = renderCrm2(rows); bindCrm2Actions(rows); }
      else if (tab === "contracts") { content.innerHTML = renderContracts(rows); bindContractsActions(rows); }
      else if (tab === "mydayoffs") { content.innerHTML = renderMyDayoffs(rows); bindMyDayoffs(); }
      else if (tab === "myattendance") { content.innerHTML = renderMyAttendance(rows); bindMyAttendance(); }
      else if (tab === "attendance") { content.innerHTML = renderAttendanceAdmin(rows); bindAttendanceAdmin(rows); }
      else if (tab === "districts") { content.innerHTML = renderDistricts(rows); bindDistricts(rows); }
      return;
    }

    let html = "";
    if (state.role === "agent") {
      const ad = d.agent;
      if (tab === "today") html = renderToday(ad);
      else if (tab === "tasks") html = renderTasks(ad);
      else if (tab === "kpi") html = renderKpi(ad);
    } else {
      const admin = d.admin;
      if (tab === "overview") html = renderOverview(admin);
      else if (tab === "team") html = renderTeam(admin);
      else if (tab === "ranking") html = renderRanking(admin);
    }
    content.innerHTML = html;
    if (state.role === "agent" && tab === "today") bindAgentActions(d.agent);
    if (state.role === "agent" && tab === "tasks") bindTasksActions(d.agent);
    if (state.role === "agent" && tab === "kpi") bindPeriodSwitch();
    if (state.role === "admin" && tab === "team") bindTeamActions(d.admin);
    if (state.role === "admin" && (tab === "overview" || tab === "ranking")) bindPeriodSwitch();
  } catch (e) {
    console.error("renderContent შეცდომა:", e);
    content.innerHTML = `<div class="card"><div class="empty">⚠️ ვერ ჩაიტვირთა: ${esc(e.message || e)}</div></div>`;
  }
}

function updateSubtitle() {
  const d = state.data;
  if (!d) return;
  const sub = document.getElementById("subtitle");
  if (state.role === "admin" && d.is_admin) {
    sub.textContent = d.is_team_lead ? "თიმლიდერის დაშბორდი" : "მენეჯერის დაშბორდი";
  } else if (d.agent) {
    sub.textContent = `👋 ${d.agent.name}`;
  } else {
    sub.textContent = "";
  }
}

function renderRoleSwitch(hasAgent, hasAdmin) {
  const el = document.getElementById("roleSwitch");
  if (!(hasAgent && hasAdmin)) { el.hidden = true; return; }
  el.hidden = false;
  el.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.role === state.role);
    b.onclick = () => { state.role = b.dataset.role; renderRoleSwitch(hasAgent, hasAdmin); updateSubtitle(); renderContent(); };
  });
}

async function load() {
  try {
    const d = await api("/api/dashboard?period=" + encodeURIComponent(state.period));
    state.data = d;
    for (const k in lazyCache) delete lazyCache[k];
    const hasAgent = !!d.agent;
    const hasAdmin = !!d.is_admin;
    if (!state.role) state.role = hasAgent ? "agent" : "admin";
    updateSubtitle();
    renderRoleSwitch(hasAgent, hasAdmin);
    renderContent();
    finLoadAccess();
  } catch (e) {
    document.getElementById("content").innerHTML =
      `<div class="card"><div class="empty">⚠️ ${esc(e.message)}</div></div>`;
    document.getElementById("subtitle").textContent = "შეცდომა";
  }
}

const siteLinkBtn = document.getElementById("siteLink");
if (siteLinkBtn) {
  siteLinkBtn.onclick = () => {
    const url = "https://safehome.ge/";
    if (tg && tg.openLink) tg.openLink(url);
    else window.open(url, "_blank");
  };
}

load();
