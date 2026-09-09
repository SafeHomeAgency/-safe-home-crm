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
const MODE_ICON = { office_morning: "🏢", office_evening: "🏢", online: "💻", off: "🌙" };
const WEEKDAY_LABELS = { mon: "ორშ", tue: "სამ", wed: "ოთხ", thu: "ხუთ", fri: "პარ", sat: "შაბ", sun: "კვ" };
const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const WARNING_LABELS = {
  late_report: "დაგვიანებული/გამოტოვებული ანგარიში",
  late_arrival: "დაგვიანება სამუშაოზე",
  no_show: "არ გამოცხადება",
  quota_missed: "დღიური გეგმა ვერ შესრულდა",
};

const state = { role: null, data: null, tab: {} };

const AGENT_TABS = [
  { id: "today", label: "დღეს", icon: "🏠" },
  { id: "tasks", label: "დავალებები", icon: "📋" },
  { id: "kpi", label: "KPI", icon: "📈" },
  { id: "exclusives", label: "ექსკლუზივები", icon: "🏘️", lazy: true },
  { id: "questions", label: "კითხვები", icon: "💬", lazy: true },
];
const ADMIN_TABS = [
  { id: "overview", label: "მიმოხილვა", icon: "📊" },
  { id: "team", label: "გუნდი", icon: "🧑‍🤝‍🧑" },
  { id: "ranking", label: "რეიტინგი", icon: "🏆" },
  { id: "dayoffs", label: "შვებულებები", icon: "🗓️" },
  { id: "warnings", label: "გაფრთხილებები", icon: "⚠️" },
  { id: "swaps", label: "სმენის გაცვლა", icon: "🔁", lazy: true },
  { id: "reports", label: "რეპორტები", icon: "📝", lazy: true },
  { id: "exclusives", label: "ექსკლუზივები", icon: "🏘️", lazy: true },
  { id: "questions", label: "კითხვები", icon: "💬", lazy: true },
];

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
function openDetail(title, fields) {
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  const rows = fields
    .filter((f) => f.value !== undefined && f.value !== null && String(f.value).trim() !== "")
    .map((f) => `<div class="field"><div class="k">${esc(f.label)}</div><div class="v">${esc(f.value)}</div></div>`)
    .join("");
  box.innerHTML = `
    <h3>${esc(title)}<button class="close" id="modalClose">✕</button></h3>
    ${rows || `<div class="empty">დამატებითი ინფორმაცია არ არის</div>`}
  `;
  backdrop.hidden = false;
  document.getElementById("modalClose").onclick = closeDetail;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeDetail(); };
}
function closeDetail() {
  document.getElementById("modalBackdrop").hidden = true;
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
    <div class="week-strip">
      ${WEEKDAY_KEYS.map((k, i) => {
        const isToday = k === WEEKDAY_KEYS[(new Date().getDay() + 6) % 7];
        const m = d.schedule[k] || "off";
        return `<div class="day ${isToday ? "today" : ""}">
          <div class="d">${WEEKDAY_LABELS[k]}</div>
          <div class="m">${MODE_ICON[m] || "🌙"}</div>
        </div>`;
      }).join("")}
    </div>
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
  ["title", "სათაური"], ["description", "აღწერა"], ["priority", "პრიორიტეტი"],
  ["status", "სტატუსი"], ["due_date", "ვადა"], ["client_phone", "კლიენტის ტელეფონი"],
  ["deal_type", "გარიგება"], ["listing_id", "ლისტინგის ID"], ["viewing_time", "ნახვის დრო"],
  ["created_at", "შექმნის თარიღი"],
];

function renderTasks(d) {
  if (!d.tasks.length) {
    return `<div class="card"><div class="empty">ღია დავალება არ გაქვთ ✅</div></div>`;
  }
  const priColor = { "მაღალი": "red", "საშუალო": "amber" };
  return `<div class="card">
    <h2>📋 ჩემი დავალებები <span class="cnt">${d.tasks.length}</span></h2>
    ${d.tasks.map((t, i) => `
      <div class="list-row clickable" data-task-idx="${i}">
        <div class="avatar">${t.lead_type === "listing" ? "🏠" : "👤"}</div>
        <div class="main">
          <div class="title">${esc(t.title || "")}</div>
          <div class="sub">${esc(t.client_phone || t.description || "")}</div>
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
}

function renderKpi(d) {
  const p = d.performance;
  const r = ratePct(p.rate);
  const meetings = d.meetings || [];
  return `
  <div class="card">
    <h2>📈 ბოლო 30 დღე</h2>
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
    btnOut.disabled = true;
    try {
      const res = await api("/api/clockout", { method: "POST", body: JSON.stringify(body) });
      if (res.result === "not_in") { toast("ჯერ არ დაგიწყიათ დღე"); btnOut.disabled = false; return; }
      tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
      toast("დღე დასრულდა ✅");
      await load();
    } catch (e) { toast(e.message); btnOut.disabled = false; }
  };
}

/* ---------------------------------------------------------- ADMIN VIEW */

function renderOverview(d) {
  const s = d.summary;
  return `
  <div class="card">
    <h2>📊 დღევანდელი სურათი</h2>
    <div class="grid2">
      <div class="stat"><div class="num">${s.clocked_in}/${s.active_total}</div><div class="lbl">გახსნილი დღეს</div></div>
      <div class="stat"><div class="num">${s.total_submitted}/${s.total_quota_target || 0}</div><div class="lbl">განცხადებები (გეგმასთან)</div></div>
      <div class="stat"><div class="num">${s.clients_today}</div><div class="lbl">კლიენტი დღეს</div></div>
      <div class="stat"><div class="num">${s.clients_total}</div><div class="lbl">კლიენტი ჯამურად</div></div>
      <div class="stat"><div class="num">${s.quota_missed}</div><div class="lbl">გეგმა ვერ შესრულდა</div></div>
      <div class="stat"><div class="num">${s.pending_dayoffs}</div><div class="lbl">მოლოდინში (შვებ.)</div></div>
      <div class="stat"><div class="num">${s.agents_total}</div><div class="lbl">სულ აგენტი</div></div>
    </div>
  </div>
  <div class="card">
    <h2>🏆 ტოპ 5</h2>
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

function renderTeam(d) {
  const team = d.team.slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  return `<div class="card">
    <h2>🧑‍🤝‍🧑 გუნდი <span class="cnt">${team.length}</span></h2>
    ${team.map((t, i) => `
      <div class="list-row clickable" data-team-idx="${i}">
        <div class="avatar">${initials(t.name)}</div>
        <div class="main">
          <div class="title">${esc(t.name)} ${t.active === "no" ? "🚫" : ""}</div>
          <div class="sub">${esc(t.team || "—")} · ${MODE_ICON[t.mode] || "🌙"} ${esc(MODE_LABELS[t.mode] || t.mode)}</div>
        </div>
        <div class="side">
          ${statusBadge(t.mode, t.clocked_in, false)}
          <div class="sub" style="margin-top:3px">👥 ${t.clients_today || 0} დღეს · ${t.clients_total || 0} ჯამურად</div>
          ${t.warnings ? `<div class="sub" style="color:var(--red);margin-top:3px">⚠️ ${t.warnings}</div>` : ""}
        </div>
      </div>`).join("")}
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
      );
    };
  });
}

function renderRanking(d) {
  const rk = d.ranking || [];
  return `<div class="card">
    <h2>🏆 შესრულების რეიტინგი (30დღე)</h2>
    ${rk.length === 0 ? `<div class="empty">ჯერ საკმარისი მონაცემი არ არის</div>` :
      rk.map((t, i) => `
        <div class="bar-row">
          <div class="top"><span>${i + 1}. ${esc(t.name)} <span class="sub">(${t.assigned})</span></span><span>${ratePct(t.rate)}%</span></div>
          <div class="track"><div class="fill" style="width:${ratePct(t.rate)}%"></div></div>
        </div>`).join("")}
  </div>`;
}

function renderDayoffs(d) {
  const rows = d.pending_dayoffs || [];
  return `<div class="card">
    <h2>🗓️ შვებულების მოთხოვნები <span class="cnt">${rows.length}</span></h2>
    ${rows.length === 0 ? `<div class="empty">მოლოდინში აღარაფერია</div>` :
      rows.map((r) => `
      <div class="list-row" data-id="${esc(r.request_id)}">
        <div class="avatar">${initials(r.agent_name)}</div>
        <div class="main">
          <div class="title">${esc(r.agent_name)} — ${esc(r.date)}</div>
          <div class="sub">${esc(r.reason || "")}</div>
        </div>
      </div>
      <div class="actions" style="margin:-2px 0 12px">
        <button class="btn" data-act="approved" data-id="${esc(r.request_id)}">✅ დამტკიცება</button>
        <button class="btn danger" data-act="rejected" data-id="${esc(r.request_id)}">✖️ უარყოფა</button>
      </div>`).join("")}
  </div>`;
}

function renderWarnings(d) {
  const rows = d.recent_warnings || [];
  return `<div class="card">
    <h2>⚠️ ბოლო გაფრთხილებები</h2>
    ${rows.length === 0 ? `<div class="empty">ცარიელია</div>` :
      rows.map((w) => `
        <div class="list-row">
          <div class="avatar" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">⚠️</div>
          <div class="main">
            <div class="title">${esc(w.agent_name)} — ${esc(WARNING_LABELS[w.type] || w.type)}</div>
            <div class="sub">${esc(w.detail || "")}</div>
          </div>
          <div class="side sub">${esc((w.created_at || "").split(" ")[0] || "")}</div>
        </div>`).join("")}
  </div>`;
}

function bindAdminActions() {
  document.querySelectorAll("[data-act]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api("/api/dayoff/decide", {
          method: "POST",
          body: JSON.stringify({ request_id: btn.dataset.id, status: btn.dataset.act }),
        });
        tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred("success");
        toast(btn.dataset.act === "approved" ? "დამტკიცდა ✅" : "უარყოფილია");
        await load();
      } catch (e) { toast(e.message); btn.disabled = false; }
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

function renderReports(rows) {
  if (!rows.length) return `<div class="card"><div class="empty">რეპორტი ჯერ არ არის</div></div>`;
  return `<div class="card">
    <h2>📝 ბოლო რეპორტები</h2>
    ${rows.map((r, i) => `
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

function renderSwaps(rows) {
  if (!rows.length) return `<div class="card"><div class="empty">დასადასტურებელი მოთხოვნა არ არის</div></div>`;
  return `<div class="card">
    <h2>🔁 დასადასტურებელი სმენის გაცვლები <span class="cnt">${rows.length}</span></h2>
    ${rows.map((r) => `
      <div class="list-row" data-id="${esc(r.swap_id)}">
        <div class="avatar">🔁</div>
        <div class="main">
          <div class="title">${esc(REQUEST_TYPE_LABELS[r.request_type] || r.request_type)}</div>
          <div class="sub">${esc(r.agent_name)}${r.target_agent_name ? " ⇄ " + esc(r.target_agent_name) : ""} · ${esc(r.swap_date || "-")}</div>
          <div class="sub">${esc(r.note || "")}</div>
        </div>
      </div>
      <div class="actions" style="margin:-2px 0 12px">
        <button class="btn" data-swapact="approved" data-id="${esc(r.swap_id)}">✅ დამტკიცება</button>
        <button class="btn danger" data-swapact="rejected" data-id="${esc(r.swap_id)}">✖️ უარყოფა</button>
      </div>`).join("")}
  </div>`;
}

function bindReportsActions(rows) {
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
}

function bindSwapsActions() {
  document.querySelectorAll("[data-swapact]").forEach((btn) => {
    btn.onclick = async () => {
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

/* ---------------------------------------------------------- shell */

const LAZY_ENDPOINTS = {
  exclusives: "/api/exclusives",
  swaps: "/api/swaps",
  reports: "/api/reports",
  questions: "/api/questions",
};

function tabsFor(role) {
  return role === "admin" ? ADMIN_TABS : AGENT_TABS;
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
          lazyCache[tab] = (await api(LAZY_ENDPOINTS[tab])).rows || [];
        } catch (e) {
          content.innerHTML = `<div class="card"><div class="empty">⚠️ ${esc(e.message)}</div></div>`;
          return;
        }
      }
      const rows = lazyCache[tab];
      if (tab === "exclusives") { content.innerHTML = renderExclusives(rows); bindExclusivesActions(rows); }
      else if (tab === "reports") { content.innerHTML = renderReports(rows); bindReportsActions(rows); }
      else if (tab === "swaps") { content.innerHTML = renderSwaps(rows); bindSwapsActions(); }
      else if (tab === "questions") { content.innerHTML = renderQuestions(rows, state.role); bindQuestionsActions(state.role); }
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
      else if (tab === "dayoffs") html = renderDayoffs(admin);
      else if (tab === "warnings") html = renderWarnings(admin);
    }
    content.innerHTML = html;
    if (state.role === "agent" && tab === "today") bindAgentActions(d.agent);
    if (state.role === "agent" && tab === "tasks") bindTasksActions(d.agent);
    if (state.role === "admin" && tab === "dayoffs") bindAdminActions();
    if (state.role === "admin" && tab === "team") bindTeamActions(d.admin);
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
    const d = await api("/api/dashboard");
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
