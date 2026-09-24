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
  { id: "taskhistory", label: "ისტორია", icon: "📜", lazy: true },
  { id: "meetings", label: "შეხვედრები", icon: "🤝", lazy: true },
  { id: "exclusives", label: "ექსკლუზივები", icon: "🏘️", lazy: true },
  { id: "myhomejobs", label: "MyHome", icon: "🏘️", lazy: true },
  { id: "questions", label: "კითხვები", icon: "💬", lazy: true },
  { id: "regulations", label: "ინსტრუქცია", icon: "📘", lazy: true },
];
const ADMIN_TABS = [
  { id: "overview", label: "მიმოხილვა", icon: "📊" },
  { id: "team", label: "გუნდი", icon: "🧑‍🤝‍🧑" },
  { id: "ranking", label: "რეიტინგი", icon: "🏆" },
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
  { id: "questions", label: "კითხვები", icon: "💬", lazy: true },
  { id: "regulations", label: "ინსტრუქცია/წესები", icon: "📘", lazy: true },
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
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || "დაფიქსირდა შეცდომა");
  return body;
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
  </div>

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
  ["title", "სათაური"], ["description", "აღწერა"], ["assigned_to_name", "შემსრულებელი"],
  ["priority", "პრიორიტეტი"], ["status", "სტატუსი"], ["lead_type", "ტიპი"],
  ["due_date", "ვადა"], ["client_phone", "კლიენტის ტელეფონი"],
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

function renderKpi(d) {
  const p = d.performance;
  const r = ratePct(p.rate);
  const meetings = d.meetings || [];
  const chart = barChart([
    { label: "მიღებული", value: p.assigned || 0 },
    { label: "დროულად", value: p.on_time || 0 },
  ]);
  return `
  <div class="card">
    ${renderPeriodSwitch()}
    <h2>📈 შედეგები — ${esc(PERIOD_TITLES[state.period] || "")}</h2>
    ${chart}
    <div class="grid3">
      <div class="stat"><div class="num">${p.assigned}</div><div class="lbl">მიღებული</div></div>
      <div class="stat"><div class="num">${p.on_time}</div><div class="lbl">დროულად</div></div>
      <div class="stat"><div class="num">${r == null ? "—" : r + "%"}</div><div class="lbl">შედეგი</div></div>
    </div>
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
  if (btnIn) btnIn.onclick = async () => {
    btnIn.disabled = true;
    try {
      const res = await api("/api/clockin", { method: "POST" });
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast(res.result === "already" ? "უკვე დაწყებულია" : "დღე დაიწყო ✅");
      await load();
    } catch (e) { toast(e.message); btnIn.disabled = false; }
  };
  if (btnOut) btnOut.onclick = async () => {
    const isOffice = d.today.mode === "office_morning" || d.today.mode === "office_evening";
    const hasQuota = !!d.today.quota;
    let body = {};
    if (isOffice) {
      const site = prompt("რამდენი განცხადება ატვირთეთ დღეს ჩვენს საიტზე?", d.today.site_count || "0");
      if (site === null) return;
      const myhome = prompt("რამდენი — myhome-ზე?", d.today.myhome_count || "0");
      if (myhome === null) return;
      const ssge = prompt("რამდენი — ss.ge-ზე?", d.today.ssge_count || "0");
      if (ssge === null) return;
      body = { site, myhome, ssge };
    } else if (hasQuota) {
      const count = prompt("რამდენი განცხადება შეიყვანეთ დღეს?", d.today.count_submitted || "0");
      if (count === null) return;
      body = { count };
    }

    const doClockout = async (finalBody) => {
      btnOut.disabled = true;
      try {
        const res = await api("/api/clockout", { method: "POST", body: JSON.stringify(finalBody) });
        if (res.result === "not_in") { toast("ჯერ არ დაგიწყიათ დღე"); btnOut.disabled = false; return; }
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("დღე დასრულდა ✅");
        await load();
      } catch (e) {
        toast(e.message);
        btnOut.disabled = false;
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

    await doClockout(body);
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
  ["team", "გუნდი"], ["mode", "დღევანდელი რეჟიმი"], ["count_submitted", "შეყვანილი დღეს (ჯამი)"],
  ["site_count", "საიტი"], ["myhome_count", "myhome"], ["ssge_count", "ss.ge"], ["quota", "დღიური გეგმა"],
  ["clients_today", "კლიენტი დღეს"], ["clients_total", "კლიენტი ჯამურად"], ["assigned", "მიღებული (30დღე)"],
  ["warnings", "გაფრთხილებები"], ["collaboration", "თანამშრომლობა (ექსკლუზივის გაზიარება)"],
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
          <div class="top"><span>${i + 1}. ${esc(t.name)} <span class="sub">(${t.assigned})</span></span><span>${ratePct(t.rate)}%</span></div>
          <div class="track"><div class="fill" style="width:${ratePct(t.rate)}%"></div></div>
        </div>`).join("")}
  </div>`;
}

/* Day off ისტორია — სამ ცალკე კატეგორიად: მომლოდინე (გადაწყვეტილების
   ღილაკებით), დამტკიცებული და უარყოფილი (ორივე მხოლოდ ისტორიისთვის).
   თვის ჭერი (მაქს. N დღეოფი თვეში ერთ აგენტზე) ვიზუალურადაც ჩანს. */
function renderDayoffs(payload) {
  const p = payload || {};
  const pending = p.pending || [];
  const approved = p.approved || [];
  const rejected = p.rejected || [];
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
  return `<div class="card">
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

  const warnRowHtml = (w) => {
    const statusLabel = WARNING_STATUS_LABEL[w.status] || "";
    return `
      <div class="list-row clickable" data-warn-idx="${rows.indexOf(w)}">
        <div class="avatar" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">⚠️</div>
        <div class="main">
          <div class="title">${esc(w.agent_name)} — ${esc(WARNING_LABELS[w.type] || w.type)}</div>
          <div class="sub">${esc(w.detail || "")}${statusLabel ? " · " + statusLabel : ""}</div>
        </div>
        <div class="side sub">${esc((w.created_at || "").split(" ")[0] || "")}</div>
      </div>`;
  };
  const section = (icon, title, list) => `<div class="card">
    <h2>${icon} ${title} <span class="cnt">${list.length}</span></h2>
    ${list.length === 0 ? `<div class="empty">ცარიელია</div>` : list.map(warnRowHtml).join("")}
  </div>`;

  return filterBar + agentCardsHtml
    + section("🕐", "დასადასტურებელი", buckets.pending)
    + section("✅", "დადასტურებული (გაუქმებულია)", buckets.dismissed)
    + section("❌", "უარყოფილი (აქტიურად რჩება)", buckets.rejected)
    + section("⚠️", "აქტიური", buckets.active);
}

function _warningBucket(w) {
  const status = w.status || "active";
  if (status === "dismiss_pending") return "pending";
  if (status === "dismissed") return "dismissed";
  if (status === "active" && w.dismiss_decided_by) return "rejected";
  return "active";
}

function bindWarningsActions(rows) {
  const isTeamLead = state.role === "admin" && state.data && state.data.is_team_lead;
  const isAdmin = state.role === "admin" && !isTeamLead;

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

function _clientTimelineItemHtml(entry) {
  const d = entry.data;
  if (entry.kind === "task") {
    return `<div class="list-row">
      <div class="avatar">${d.lead_type === "listing" ? "🏠" : "👤"}</div>
      <div class="main">
        <div class="title">📋 ${esc(d.title || "დავალება")}</div>
        <div class="sub">შემსრულებელი: ${esc(d.assigned_to_name || "-")} · სტატუსი: ${esc(d.status || "-")}</div>
        <div class="sub">${esc(d.created_at || "")}${d.updated_at && d.updated_at !== d.created_at ? " → " + esc(d.updated_at) : ""}</div>
      </div>
    </div>`;
  }
  if (entry.kind === "report") {
    const photos = String(d.file_id || "").split(",").map((s) => s.trim()).filter((s) => s.startsWith("uploads/"));
    return `<div class="list-row">
      <div class="avatar">📝</div>
      <div class="main">
        <div class="title">რეპორტი — ${esc(d.agent_name || "-")}</div>
        <div class="sub">${esc(d.actions || "-")}</div>
        ${d.notes ? `<div class="sub">${esc(d.notes)}</div>` : ""}
        <div class="sub">${esc(d.created_at || "")}</div>
        ${photos.length ? `<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">${photos.map((p) => `<img src="/${esc(p)}" style="width:56px;height:56px;object-fit:cover;border-radius:8px" />`).join("")}</div>` : ""}
      </div>
    </div>`;
  }
  return `<div class="list-row">
    <div class="avatar">📍</div>
    <div class="main">
      <div class="title">შეხვედრა — ${esc(d.agent_name || "-")}</div>
      <div class="sub">${esc(d.address || d.district || "-")}${d.price ? " · " + esc(d.price) : ""}</div>
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
        const res = await api(`/api/clients/${encodeURIComponent(c.client_phone)}`);
        const timeline = res.timeline || [];
        box.innerHTML = `
          <h3>${esc(c.client_phone)}<button class="close" id="modalClose">✕</button></h3>
          ${timeline.length === 0 ? `<div class="empty">ისტორია არ არის</div>` : timeline.map(_clientTimelineItemHtml).join("")}
        `;
        document.getElementById("modalClose").onclick = closeDetail;
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
    </div>
    <div class="qa-compose" data-kind-fields="listing" ${newTaskKind === "listing" ? "" : "hidden"}>
      <select id="ntAgent">${agentOptions || `<option value="">აგენტი არ არის</option>`}</select>
      <input id="ntListingId" placeholder="ლისტინგის/ბინის ID" />
      <input id="ntListingPhone" placeholder="კლიენტის ტელეფონი" />
      <input id="ntViewingTime" placeholder="ნახვის დრო (მაგ. ხვალ 12:00)" />
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
        };
      }
      submitBtn.disabled = true;
      try {
        await api("/api/tasks/new", { method: "POST", body: JSON.stringify(body) });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast("დამატებულია ✅");
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
      openDetail(m.address || m.district || "შეხვედრა", MEETING_FIELD_LABELS.map(([k, label]) => ({ label, value: m[k] })));
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

function renderMyHomeJobs(rows, role) {
  const compose = `
    <div class="card">
      <h2>🏘️ MyHome ლისტინგის დამატება</h2>
      <div class="qa-compose">
        <input id="mhListingId" type="text" inputmode="numeric" placeholder="MyHome ID (მაგ. 20134412)">
        <input id="mhPercent" type="text" inputmode="decimal" placeholder="თანამშრომლობის % (არასავალდებულო)">
        <input id="mhPrice" type="text" inputmode="decimal" placeholder="საბოლოო ფასი (არასავალდებულო)">
        <textarea id="mhNotes" placeholder="შენიშვნა (არასავალდებულო)"></textarea>
        <button class="btn" id="mhSubmit">დამატება</button>
      </div>
    </div>`;

  const list = !rows.length
    ? `<div class="card"><div class="empty">ჯერ არცერთი MyHome ID არაა დამატებული</div></div>`
    : `<div class="card">
        <h2>📋 ${role === "agent" ? "ჩემი დავალებები" : "MyHome დავალებები"} <span class="cnt">${rows.length}</span></h2>
        ${rows.map((r) => `
          <div class="list-row">
            <div class="avatar">🏠</div>
            <div class="main">
              <div class="title">MyHome ID: ${esc(r.myhome_listing_id)}${role !== "agent" ? " · " + esc(r.agent_name) : ""}</div>
              <div class="sub">${MYHOME_JOB_STATUS_LABEL[r.status] || esc(r.status)}${r.cooperation_percent ? " · " + esc(r.cooperation_percent) + "%" : ""}${r.final_price ? " · 💰 " + esc(r.final_price) : ""}</div>
              ${r.notes ? `<div class="sub">📝 ${esc(r.notes)}</div>` : ""}
              <div class="sub">${esc((r.created_at || "").split(" ")[0] || "")}${r.completed_at ? " → " + esc((r.completed_at || "").split(" ")[0] || "") : ""}</div>
              ${r.status === "FAILED" && r.error_message ? `<div class="sub">⚠️ ${esc(r.error_message)}</div>` : ""}
            </div>
          </div>`).join("")}
      </div>`;
  return compose + list;
}

function bindMyHomeJobsActions() {
  const btn = document.getElementById("mhSubmit");
  if (!btn) return;
  btn.onclick = async () => {
    const listingId = (document.getElementById("mhListingId").value || "").trim();
    const percent = (document.getElementById("mhPercent").value || "").trim();
    const price = (document.getElementById("mhPrice").value || "").trim();
    const notes = (document.getElementById("mhNotes").value || "").trim();
    if (!listingId || !/^\d+$/.test(listingId)) { toast("შეიყვანეთ სწორი MyHome ID (მხოლოდ ციფრები)"); return; }
    btn.disabled = true;
    try {
      await api("/api/myhome-jobs", {
        method: "POST",
        body: JSON.stringify({
          myhome_listing_id: listingId,
          cooperation_percent: percent,
          final_price: price,
          notes,
        }),
      });
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast("დაემატა რიგში ✅");
      delete lazyCache.myhomejobs;
      await renderContent();
    } catch (e) { toast(e.message); btn.disabled = false; }
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
    ["/clockin", "სამუშაო დღის დაწყება", "აღნიშნავს დღის დაწყების ზუსტ დროს. ოფისის ცვლაზე დაგვიანებით დაწყება (grace-პერიოდის მეტ ხანს) ავტომატურ გაფრთხილებას წარმოშობს — ამიტომ სჯობს დროულად."],
    ["/clockout", "სამუშაო დღის დასრულება — განცხადებების რაოდენობა + კლიენტის რეპორტი", "დღის ბოლოს გამოსაყენებელია: ითხოვს დღიური გეგმის რიცხვებს (განცხადებები საიტზე/myhome/ss.ge ან ონლაინის შემთხვევაში საერთო რაოდენობა), ხოლო თუ დღეს კონკრეტული კლიენტი გქონდათ მინიჭებული — სავალდებულოდ ითხოვს იმ კლიენტის ანგარიშსაც (რა შესრულდა, დეტალები, სურათებიც კი). ეს უკანასკნელი აღარ იტოვება გამოტოვებას."],
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
  ["🗓️", "შვებულებები", "გუნდის დღეოფის მოთხოვნების დამტკიცება/უარყოფა, პლუს ისტორია"],
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

/* ---------------------------------------------------------- shell */

const LAZY_ENDPOINTS = {
  exclusives: "/api/exclusives",
  myhomejobs: "/api/myhome-jobs",
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
if (!state.warningsAgentFilter) state.warningsAgentFilter = "";
if (!state.warningsManagerFilter) state.warningsManagerFilter = "";

/* `adminOnly` ტაბები (მაგ. აგენტების/მენეჯერების მართვა) დირექტორის
   დონის მოქმედებაა — თიმლიდერს (რომელიც ტექნიკურად იმავე "admin"
   role-ზეა Mini App-ში, საკუთარი გუნდის ფილტრირებული ხედვით) არ
   უჩნდება, რომ არ დაერიოს პირამიდის სტრუქტურაში. */
function tabsFor(role) {
  const tabs = role === "admin" ? ADMIN_TABS : AGENT_TABS;
  if (role === "admin" && state.data && state.data.is_team_lead) {
    return tabs.filter((t) => !t.adminOnly);
  }
  return tabs;
}

function renderTabbar() {
  const tabs = tabsFor(state.role);
  if (!state.tab[state.role]) state.tab[state.role] = tabs[0].id;
  const bar = document.getElementById("tabbar");
  bar.hidden = false;
  bar.innerHTML = tabs.map((t) => `
    <button data-tab="${t.id}" class="${state.tab[state.role] === t.id ? "active" : ""}">
      <span class="ic">${t.icon}</span>${esc(t.label)}
    </button>`).join("");
  bar.querySelectorAll("button").forEach((b) => {
    b.onclick = () => { state.tab[state.role] = b.dataset.tab; renderContent(); };
  });
}

async function renderContent() {
  const content = document.getElementById("content");
  const d = state.data;
  const tab = state.tab[state.role];
  renderTabbar();

  try {
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
          if (params.length) url += "?" + params.join("&");
          const resp = await api(url);
          const wholeObjTabs = ["admintasks", "agentsmgmt", "meetings", "taskhistory", "digest", "reports", "dayoffs", "swaps", "regulations"];
          lazyCache[tab] = wholeObjTabs.includes(tab) ? resp : (resp.rows || []);
        } catch (e) {
          content.innerHTML = `<div class="card"><div class="empty">⚠️ ${esc(e.message)}</div></div>`;
          return;
        }
      }
      const rows = lazyCache[tab];
      if (tab === "exclusives") { content.innerHTML = renderExclusives(rows); bindExclusivesActions(rows); }
      else if (tab === "myhomejobs") { content.innerHTML = renderMyHomeJobs(rows, state.role); bindMyHomeJobsActions(); }
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
