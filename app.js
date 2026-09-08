/* Safe Home Agency — Mini App dashboard (frontend, no build step). */

const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) {
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor("secondary_bg_color"); } catch (e) {}
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
};

const state = { role: null, data: null, tab: {} };

const AGENT_TABS = [
  { id: "today", label: "დღეს", icon: "🏠" },
  { id: "tasks", label: "დავალებები", icon: "📋" },
  { id: "kpi", label: "KPI", icon: "📈" },
];
const ADMIN_TABS = [
  { id: "overview", label: "მიმოხილვა", icon: "📊" },
  { id: "team", label: "გუნდი", icon: "🧑‍🤝‍🧑" },
  { id: "ranking", label: "რეიტინგი", icon: "🏆" },
  { id: "dayoffs", label: "შვებულებები", icon: "🗓️" },
  { id: "warnings", label: "გაფრთხილებები", icon: "⚠️" },
];

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
  const isOnline = t.mode === "online";
  const quota = t.quota || 0;
  const submitted = parseInt(t.count_submitted || 0, 10) || 0;
  const clockedIn = !!t.clock_in && !t.clock_out;
  const canClockIn = t.mode !== "off" && !t.clock_in;
  const canClockOut = clockedIn;

  const ringHtml = isOnline
    ? ring(pct(submitted, quota))
    : `<div class="ring" style="display:flex;align-items:center;justify-content:center;font-size:30px">${MODE_ICON[t.mode] || "🏠"}</div>`;

  return `
  <div class="card">
    <div class="today-hero">
      ${ringHtml}
      <div class="today-info">
        <div class="mode">${MODE_LABELS[t.mode] || t.mode}</div>
        <div class="meta">${isOnline ? `${submitted} / ${quota} განცხადება` : (t.clock_in ? `დაწყებულია ${esc(t.clock_in).split(" ")[1] || ""}` : "დღევანდელი გეგმა")}</div>
        <div style="margin-top:6px">${statusBadge(t.mode, clockedIn, t.clock_out)}</div>
      </div>
    </div>
    <div class="actions">
      <button class="btn" id="btnClockIn" ${canClockIn ? "" : "disabled"}>▶️ დაწყება</button>
      <button class="btn secondary" id="btnClockOut" ${canClockOut ? "" : "disabled"}>⏹️ დასრულება</button>
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

function renderTasks(d) {
  if (!d.tasks.length) {
    return `<div class="card"><div class="empty">ღია დავალება არ გაქვთ ✅</div></div>`;
  }
  const priColor = { "მაღალი": "red", "საშუალო": "amber" };
  return `<div class="card">
    <h2>📋 ჩემი დავალებები <span class="cnt">${d.tasks.length}</span></h2>
    ${d.tasks.map((t) => `
      <div class="list-row">
        <div class="avatar">${t.lead_type === "listing" ? "🏠" : "👤"}</div>
        <div class="main">
          <div class="title">${esc(t.title || "")}</div>
          <div class="sub">${esc(t.client_phone || t.description || "")}</div>
        </div>
        <div class="side"><span class="badge ${priColor[t.priority] || "gray"}">${esc(t.priority || "-")}</span></div>
      </div>`).join("")}
  </div>`;
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
    const quota = d.today.quota;
    let count;
    if (quota) {
      count = prompt("რამდენი განცხადება შეიყვანეთ დღეს?", d.today.count_submitted || "0");
      if (count === null) return;
    }
    btnOut.disabled = true;
    try {
      const res = await api("/api/clockout", { method: "POST", body: JSON.stringify({ count }) });
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
      <div class="stat"><div class="num">${s.total_submitted}/${s.total_quota_target || 0}</div><div class="lbl">განცხადებები (online)</div></div>
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

function renderTeam(d) {
  const team = d.team.slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  return `<div class="card">
    <h2>🧑‍🤝‍🧑 გუნდი <span class="cnt">${team.length}</span></h2>
    ${team.map((t) => `
      <div class="list-row">
        <div class="avatar">${initials(t.name)}</div>
        <div class="main">
          <div class="title">${esc(t.name)} ${t.active === "no" ? "🚫" : ""}</div>
          <div class="sub">${esc(t.team || "—")} · ${MODE_ICON[t.mode] || "🌙"} ${esc(MODE_LABELS[t.mode] || t.mode)}</div>
        </div>
        <div class="side">
          ${statusBadge(t.mode, t.clocked_in, false)}
          ${t.warnings ? `<div class="sub" style="color:var(--red);margin-top:3px">⚠️ ${t.warnings}</div>` : ""}
        </div>
      </div>`).join("")}
  </div>`;
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

/* ---------------------------------------------------------- shell */

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

function renderContent() {
  const content = document.getElementById("content");
  const d = state.data;
  const tab = state.tab[state.role];
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
  renderTabbar();
  if (state.role === "agent" && tab === "today") bindAgentActions(d.agent);
  if (state.role === "admin" && tab === "dayoffs") bindAdminActions();
}

function renderRoleSwitch(hasAgent, hasAdmin) {
  const el = document.getElementById("roleSwitch");
  if (!(hasAgent && hasAdmin)) { el.hidden = true; return; }
  el.hidden = false;
  el.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.role === state.role);
    b.onclick = () => { state.role = b.dataset.role; renderRoleSwitch(hasAgent, hasAdmin); renderContent(); };
  });
}

async function load() {
  try {
    const d = await api("/api/dashboard");
    state.data = d;
    const hasAgent = !!d.agent;
    const hasAdmin = !!d.is_admin;
    if (!state.role) state.role = hasAgent ? "agent" : "admin";
    document.getElementById("subtitle").textContent = hasAdmin
      ? "მენეჯერის დაშბორდი"
      : (d.agent ? `👋 ${d.agent.name}` : "");
    renderRoleSwitch(hasAgent, hasAdmin);
    renderContent();
  } catch (e) {
    document.getElementById("content").innerHTML =
      `<div class="card"><div class="empty">⚠️ ${esc(e.message)}</div></div>`;
    document.getElementById("subtitle").textContent = "შეცდომა";
  }
}

load();
