/* ============ PyTask Platform 前端逻辑 ============ */
"use strict";

const state = {
  view: "dashboard",
  templates: [],
  runsFilter: { status: "", keyword: "", page: 1, pageSize: 15 },
  dashboardTimer: null,
  runsTimer: null,
  logTimer: null,
  logState: null,   // { runId, offset, autoScroll }
};

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}
const get = (p) => api(p);
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });
const put = (p, b) => api(p, { method: "PUT", body: JSON.stringify(b) });
const del = (p) => api(p, { method: "DELETE" });

/* ---------------- 工具 ---------------- */
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const STATUS = {
  pending:  { label: "排队中", cls: "s-pending" },
  running:  { label: "运行中", cls: "s-running" },
  success:  { label: "成功",   cls: "s-success" },
  failed:   { label: "失败",   cls: "s-failed" },
  stopped:  { label: "已停止", cls: "s-stopped" },
};
const badge = (s) => {
  const m = STATUS[s] || { label: s, cls: "s-stopped" };
  return `<span class="badge ${m.cls}"><i class="dot"></i>${m.label}</span>`;
};

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function fmtDur(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m${Math.round(s % 60)}s`;
}
function toast(msg, type = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toast-root").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

/* ---------------- 弹窗 ---------------- */
function openModal(html, lg = false) {
  $("#modal-root").innerHTML =
    `<div class="modal-mask"><div class="modal${lg ? " lg" : ""}">${html}</div></div>`;
  $(".modal-mask").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeModal();
  });
}
function closeModal() {
  $("#modal-root").innerHTML = "";
  stopLogPolling();
}

/* ---------------- 健康检查 ---------------- */
async function refreshHealth() {
  try {
    const h = await get("/api/health");
    const el = $("#db-status");
    el.classList.toggle("ok", h.ok);
    el.classList.toggle("bad", !h.ok);
    el.title = h.ok ? `MongoDB ${h.mongo} / ${h.db}` : "MongoDB 未连接";
    if (!h.ok && state.view === "dashboard") toast("MongoDB 未连接，请检查 localhost:27017", "err");
  } catch (e) {
    $("#db-status").classList.add("bad");
  }
}

/* ---------------- 视图切换 ---------------- */
function switchView(view) {
  state.view = view;
  $$("#tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  clearPollers();
  const root = $("#view-root");
  if (view === "dashboard") { renderDashboard(); startDashboardPoll(); }
  else if (view === "templates") { renderTemplates(); }
  else if (view === "runs") { renderRuns(); startRunsPoll(); }
  else if (view === "free") { renderFreeRun(); }
}
function clearPollers() {
  clearInterval(state.dashboardTimer); state.dashboardTimer = null;
  clearInterval(state.runsTimer); state.runsTimer = null;
  stopLogPolling();
}

/* ================ 仪表盘 ================ */
async function renderDashboard() {
  const root = $("#view-root");
  root.innerHTML = `<div class="empty">加载中…</div>`;
  let s;
  try { s = await get("/api/stats"); } catch (e) { root.innerHTML = `<div class="card"><div class="empty">${esc(e.message)}</div></div>`; return; }
  const bs = s.by_status;
  const total = Math.max(s.total, 1);
  const seg = (key, color) => bs[key] > 0
    ? `<i style="width:${(bs[key] / total * 100).toFixed(1)}%;background:${color}"></i>` : "";
  root.innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><span class="label">运行中</span><span class="value c-running">${bs.running}</span><span class="sub">当前活动进程</span></div>
      <div class="stat-card"><span class="label">成功</span><span class="value c-success">${bs.success}</span><span class="sub">累计</span></div>
      <div class="stat-card"><span class="label">失败</span><span class="value c-failed">${bs.failed}</span><span class="sub">累计</span></div>
      <div class="stat-card"><span class="label">已停止</span><span class="value c-stopped">${bs.stopped}</span><span class="sub">累计</span></div>
      <div class="stat-card"><span class="label">累计运行</span><span class="value">${s.total}</span><span class="sub">今日 ${s.today} · 近24h ${s.last_24h}</span></div>
      <div class="stat-card"><span class="label">任务模板</span><span class="value">${s.templates}</span><span class="sub">已登记</span></div>
    </div>

    <div class="card">
      <h3>运行状态分布 <span class="hint">按累计运行次数</span></h3>
      <div class="dist-bar">
        ${seg("running", "#2563eb")}${seg("success", "#16a34a")}${seg("failed", "#dc2626")}${seg("stopped", "#64748b")}${seg("pending", "#d97706")}
      </div>
      <div class="legend">
        <span><i style="background:#2563eb"></i>运行中 ${bs.running}</span>
        <span><i style="background:#16a34a"></i>成功 ${bs.success}</span>
        <span><i style="background:#dc2626"></i>失败 ${bs.failed}</span>
        <span><i style="background:#64748b"></i>已停止 ${bs.stopped}</span>
        <span><i style="background:#d97706"></i>排队中 ${bs.pending}</span>
      </div>
    </div>

    <div class="card">
      <h3>正在运行 <span class="hint">${s.running.length} 个</span></h3>
      ${s.running.length
        ? `<div class="table-wrap"><table>
            <thead><tr><th>任务</th><th>PID</th><th>已运行</th><th>命令</th><th>操作</th></tr></thead>
            <tbody>${s.running.map((r) => `
              <tr>
                <td>${esc(r.template_name)}${r.free ? ' <span class="hint" style="font-size:11px;color:var(--text-3)">(自由命令)</span>' : ""}</td>
                <td class="mono">${r.pid ?? "—"}</td>
                <td>${fmtDur(Date.now() - new Date(r.started_at).getTime())}</td>
                <td class="cmd-cell mono" title="${esc(r.resolved_command)}">${esc(r.resolved_command)}</td>
                <td><div class="actions"><button class="btn btn-sm" onclick="openRunLog('${r.id}')">日志</button>
                <button class="btn btn-sm btn-danger" onclick="stopRun('${r.id}')">停止</button></div></td>
              </tr>`).join("")}
            </tbody></table></div>`
        : `<div class="empty">当前没有正在运行的任务</div>`}
    </div>

    <div class="card">
      <h3>最近运行 <span class="hint">最新 10 条</span></h3>
      ${renderRunTable(s.runningRecent || [])}
    </div>`;
  // 最近运行由 stats 不返回，单独补拉一次
  loadRecentRuns(root);
}

async function loadRecentRuns(root) {
  try {
    const d = await get("/api/runs?page=1&page_size=10");
    const cards = $$(".card", root);
    const last = cards[cards.length - 1];
    if (last) {
      last.innerHTML = `<h3>最近运行 <span class="hint">最新 10 条</span></h3>${renderRunTable(d.items)}`;
    }
  } catch (e) { /* ignore */ }
}

/* ================ 任务模板 ================ */
let templateKeyword = "";

async function renderTemplates() {
  const root = $("#view-root");
  root.innerHTML = `
    <div class="card">
      <h3>任务模板
        <button class="btn btn-sm btn-primary" onclick="openTaskForm()">+ 新建模板</button>
      </h3>
      <div class="filter-bar">
        <input type="text" id="tpl-search" placeholder="搜索名称 / 描述…" value="${esc(templateKeyword)}">
        <span class="spacer"></span>
        <span class="hint" style="color:var(--text-3);font-size:12px">模板命令中的 {参数名} 会在运行时替换为表单填写值</span>
      </div>
      <div id="tpl-body"><div class="empty">加载中…</div></div>
    </div>`;
  $("#tpl-search").addEventListener("keyup", (e) => {
    if (e.key === "Enter") { templateKeyword = e.target.value; renderTemplates(); }
  });
  await loadTemplates();
}

async function loadTemplates() {
  try {
    const d = await get(`/api/tasks?keyword=${encodeURIComponent(templateKeyword)}`);
    state.templates = d.items;
    const body = $("#tpl-body");
    if (!d.items.length) {
      body.innerHTML = `<div class="empty"><div class="big">🗂</div>暂无任务模板，点击右上角「新建模板」创建</div>`;
      return;
    }
    body.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>名称</th><th>命令</th><th>参数</th><th>超时</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>${d.items.map((t) => `
        <tr>
          <td><b>${esc(t.name)}</b><br><span style="font-size:11px;color:var(--text-3)">${esc(t.description || "")}</span></td>
          <td class="cmd-cell mono" title="${esc(t.command)}">${esc(t.command)}</td>
          <td>${t.params.length ? t.params.map((p) => `<span class="mono" style="font-size:11px;color:var(--text-2)">{${esc(p.key)}}</span>`).join(" ") : "—"}</td>
          <td>${t.timeout > 0 ? `${t.timeout}s` : "不限"}</td>
          <td>${t.enabled ? '<span class="badge s-success"><i class="dot"></i>启用</span>' : '<span class="badge s-stopped"><i class="dot"></i>停用</span>'}</td>
          <td><div class="actions">
            <button class="btn btn-sm btn-primary" onclick="openRunTaskForm('${t.id}')">运行</button>
            <button class="btn btn-sm" onclick="openTaskForm('${t.id}')">编辑</button>
            <button class="btn btn-sm btn-danger" onclick="deleteTask('${t.id}','${esc(t.name)}')">删除</button>
          </div></td>
        </tr>`).join("")}
      </tbody></table></div>`;
  } catch (e) {
    $("#tpl-body").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function openTaskForm(id = null) {
  const t = id ? state.templates.find((x) => x.id === id) : null;
  const f = t || { name: "", description: "", command: "", interpreter: "python", cwd: "", params: [{ key: "", label: "", default: "", required: false }], timeout: 0, enabled: true };
  openModal(`
    <div class="modal-head"><h2>${id ? "编辑任务模板" : "新建任务模板"}</h2><button class="x" onclick="closeModal()">×</button></div>
    <div class="form-grid">
      <div class="form-item"><label>名称 *</label><input id="tf-name" value="${esc(f.name)}" placeholder="例如：数据清洗"></div>
      <div class="form-item"><label>解释器</label><input id="tf-interp" value="${esc(f.interpreter)}" placeholder="python / python3 / 绝对路径"><span class="help">留空默认 python</span></div>
      <div class="form-item full"><label>命令 *</label><input id="tf-command" value="${esc(f.command)}" placeholder="例如：process.py {input} {output}"><span class="help">相对命令在「工作目录」下执行；{参数名} 会在运行时被替换</span></div>
      <div class="form-item"><label>工作目录</label><input id="tf-cwd" value="${esc(f.cwd)}" placeholder="脚本所在目录（可选）"></div>
      <div class="form-item"><label>超时（秒）</label><input id="tf-timeout" type="number" min="0" value="${f.timeout}"><span class="help">0 = 不限时，超时自动终止</span></div>
      <div class="form-item full"><label>描述</label><textarea id="tf-desc" placeholder="这个任务做什么（可选）">${esc(f.description)}</textarea></div>
    </div>
    <div class="form-item full" style="margin-top:12px">
      <label>参数（命令中用 {key} 引用）</label>
      <div id="param-rows"></div>
      <button class="btn btn-sm" onclick="addParamRow()">+ 添加参数</button>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveTask('${id || ""}')">保存</button>
    </div>`);
  const box = $("#param-rows");
  f.params.forEach((p) => box.appendChild(paramRow(p)));
}

function paramRow(p = {}) {
  const row = document.createElement("div");
  row.className = "param-row";
  row.innerHTML = `
    <input class="pk" placeholder="参数名 key" value="${esc(p.key)}">
    <input class="pl" placeholder="显示名 label" value="${esc(p.label)}">
    <input class="pd" placeholder="默认值" value="${esc(p.default)}">
    <label class="ck"><input type="checkbox" class="pq" ${p.required ? "checked" : ""}>必填</label>
    <button class="icon-btn" onclick="this.parentElement.remove()">×</button>`;
  return row;
}
function addParamRow() { $("#param-rows").appendChild(paramRow()); }

async function saveTask(id) {
  const name = $("#tf-name").value.trim();
  const command = $("#tf-command").value.trim();
  if (!name || !command) { toast("名称和命令不能为空", "err"); return; }
  const params = $$("#param-rows .param-row").map((r) => ({
    key: $(".pk", r).value.trim(),
    label: $(".pl", r).value.trim(),
    default: $(".pd", r).value,
    required: $(".pq", r).checked,
  })).filter((p) => p.key);
  const body = {
    name,
    description: $("#tf-desc").value.trim(),
    command,
    interpreter: $("#tf-interp").value.trim() || "python",
    cwd: $("#tf-cwd").value.trim(),
    params,
    timeout: parseInt($("#tf-timeout").value, 10) || 0,
    enabled: true,
  };
  try {
    if (id) { await put(`/api/tasks/${id}`, body); toast("模板已更新"); }
    else { await post("/api/tasks", body); toast("模板已创建"); }
    closeModal();
    await loadTemplates();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteTask(id, name) {
  if (!confirm(`确定删除模板「${name}」？运行历史不会受影响。`)) return;
  try { await del(`/api/tasks/${id}`); toast("模板已删除"); await loadTemplates(); }
  catch (e) { toast(e.message, "err"); }
}

/* 运行模板：填参数 */
function openRunTaskForm(id) {
  const t = state.templates.find((x) => x.id === id);
  if (!t) return;
  openModal(`
    <div class="modal-head"><h2>运行「${esc(t.name)}」</h2><button class="x" onclick="closeModal()">×</button></div>
    <div class="run-meta">
      <div class="m"><span class="k">命令</span><span class="v mono">${esc(t.command)}</span></div>
      <div class="m"><span class="k">工作目录</span><span class="v mono">${esc(t.cwd || "（平台目录）")}</span></div>
      <div class="m"><span class="k">超时</span><span class="v">${t.timeout > 0 ? t.timeout + "s" : "不限"}</span></div>
    </div>
    <div class="form-grid">
      ${t.params.length ? t.params.map((p, i) => `
        <div class="form-item"><label>${esc(p.label || p.key)}${p.required ? " *" : ""}</label>
        <input id="rp-${i}" value="${esc(p.default)}" placeholder="${esc(p.key)}"></div>`).join("")
        : `<div class="form-item full"><span class="help">该模板没有参数，直接启动</span></div>`}
      <div class="form-item"><label>超时覆盖（秒）</label><input id="rp-timeout" type="number" min="0" value="0"><span class="help">0 = 沿用模板设置</span></div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="launchTemplate('${t.id}', ${t.params.length})">启动</button>
    </div>`);
}

async function launchTemplate(id, n) {
  const params = {};
  for (let i = 0; i < n; i++) {
    const el = $(`#rp-${i}`);
    if (el) params[el.placeholder || `p${i}`] = el.value;
  }
  const timeout = parseInt($("#rp-timeout").value, 10) || 0;
  try {
    const run = await post(`/api/tasks/${id}/run`, { params, timeout });
    closeModal();
    toast(`已启动：${run.template_name}`);
    switchView("runs");
    openRunLog(run.id);
  } catch (e) { toast(e.message, "err"); }
}

/* ================ 运行记录 ================ */
async function renderRuns() {
  const root = $("#view-root");
  const st = state.runsFilter;
  root.innerHTML = `
    <div class="card">
      <h3>运行记录</h3>
      <div class="filter-bar">
        <select id="rf-status">
          <option value="">全部状态</option>
          ${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${st.status === k ? "selected" : ""}>${v.label}</option>`).join("")}
        </select>
        <input type="text" id="rf-q" placeholder="搜索任务名 / 命令…" value="${esc(st.keyword)}">
        <button class="btn" onclick="applyRunFilter()">筛选</button>
        <span class="spacer"></span>
        <button class="btn" onclick="renderRuns()">刷新</button>
      </div>
      <div id="runs-body"><div class="empty">加载中…</div></div>
      <div class="pager" id="runs-pager"></div>
    </div>`;
  $("#rf-status").addEventListener("change", () => { st.status = $("#rf-status").value; st.page = 1; renderRuns(); });
  $("#rf-q").addEventListener("keyup", (e) => { if (e.key === "Enter") applyRunFilter(); });
  await loadRuns();
}

function applyRunFilter() {
  state.runsFilter.status = $("#rf-status").value;
  state.runsFilter.keyword = $("#rf-q").value.trim();
  state.runsFilter.page = 1;
  renderRuns();
}

async function loadRuns() {
  const st = state.runsFilter;
  try {
    const d = await get(`/api/runs?status=${encodeURIComponent(st.status)}&keyword=${encodeURIComponent(st.keyword)}&page=${st.page}&page_size=${st.pageSize}`);
    const body = $("#runs-body");
    if (!d.items.length) {
      body.innerHTML = `<div class="empty"><div class="big">📋</div>没有符合条件的运行记录</div>`;
    } else {
      body.innerHTML = renderRunTable(d.items);
    }
    const totalPages = Math.max(1, Math.ceil(d.total / st.pageSize));
    $("#runs-pager").innerHTML = `
      <button class="btn btn-sm" ${st.page <= 1 ? "disabled" : ""} onclick="pageRun(-1)">上一页</button>
      <span>第 ${st.page} / ${totalPages} 页 · 共 ${d.total} 条</span>
      <button class="btn btn-sm" ${st.page >= totalPages ? "disabled" : ""} onclick="pageRun(1)">下一页</button>`;
  } catch (e) {
    $("#runs-body").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}
function pageRun(delta) {
  state.runsFilter.page = Math.max(1, state.runsFilter.page + delta);
  renderRuns();
}

function renderRunTable(items) {
  if (!items.length) return `<div class="empty">暂无记录</div>`;
  return `<div class="table-wrap"><table>
    <thead><tr>
      <th>#</th><th>任务</th><th>命令</th><th>状态</th><th>PID</th><th>退出码</th><th>耗时</th><th>启动时间</th><th>操作</th>
    </tr></thead>
    <tbody>${items.map((r) => `
      <tr>
        <td class="mono" style="color:var(--text-3)">${String(r.id).slice(-6)}</td>
        <td>${esc(r.template_name)}${r.free ? ' <span style="font-size:11px;color:var(--text-3)">(自由)</span>' : ""}</td>
        <td class="cmd-cell mono" title="${esc(r.resolved_command || r.command)}">${esc(r.resolved_command || r.command)}</td>
        <td>${badge(r.status)}${r.killed_by === "timeout" ? ' <span style="font-size:11px;color:var(--text-3)">超时</span>' : ""}${r.killed_by === "user" ? ' <span style="font-size:11px;color:var(--text-3)">手动停止</span>' : ""}</td>
        <td class="mono">${r.pid ?? "—"}</td>
        <td class="mono">${r.exit_code == null ? "—" : r.exit_code}</td>
        <td>${fmtDur(r.duration_ms)}</td>
        <td>${fmtTime(r.started_at || r.created_at)}</td>
        <td><div class="actions">
          <button class="btn btn-sm" onclick="openRunLog('${r.id}')">日志</button>
          ${r.status === "running" || r.status === "pending" ? `<button class="btn btn-sm btn-danger" onclick="stopRun('${r.id}')">停止</button>` : ""}
          <button class="btn btn-sm" onclick="retryRun('${r.id}')">重跑</button>
        </div></td>
      </tr>`).join("")}
    </tbody></table></div>`;
}

async function stopRun(id) {
  if (!confirm("确定停止该任务？会终止其进程树。")) return;
  try {
    await post(`/api/runs/${id}/stop`);
    toast("已发起停止");
    if (state.view === "runs") renderRuns(); else renderDashboard();
  } catch (e) { toast(e.message, "err"); }
}

async function retryRun(id) {
  try {
    const run = await post(`/api/runs/${id}/retry`);
    toast("已重新启动");
    renderRuns();
    openRunLog(run.id);
  } catch (e) { toast(e.message, "err"); }
}

/* ================ 自由运行 ================ */
function renderFreeRun() {
  $("#view-root").innerHTML = `
    <div class="card" style="max-width:720px">
      <h3>自由运行 <span class="hint">临时执行任意命令，不保存为模板</span></h3>
      <div class="form-grid">
        <div class="form-item full"><label>任务名（可选）</label><input id="fr-name" placeholder="例如：临时抓取任务"></div>
        <div class="form-item full"><label>命令 *</label><input id="fr-command" placeholder="例如：python D:\\scripts\\fetch.py --date 2026-10-12"><span class="help">整行命令，含解释器；支持空格和引号</span></div>
        <div class="form-item"><label>工作目录（可选）</label><input id="fr-cwd" placeholder="脚本所在目录"></div>
        <div class="form-item"><label>超时（秒）</label><input id="fr-timeout" type="number" min="0" value="0"><span class="help">0 = 不限时</span></div>
      </div>
      <div class="modal-foot" style="margin-top:16px">
        <button class="btn btn-primary" onclick="launchFree()">立即运行</button>
      </div>
    </div>`;
}

async function launchFree() {
  const command = $("#fr-command").value.trim();
  if (!command) { toast("请输入命令", "err"); return; }
  try {
    const run = await post("/api/runs", {
      command,
      name: $("#fr-name").value.trim() || "自由命令",
      cwd: $("#fr-cwd").value.trim(),
      timeout: parseInt($("#fr-timeout").value, 10) || 0,
    });
    toast("已启动");
    switchView("runs");
    openRunLog(run.id);
  } catch (e) { toast(e.message, "err"); }
}

/* ================ 运行日志（弹窗 + 轮询） ================ */
function openRunLog(runId) {
  stopLogPolling();
  state.logState = { runId, offset: 0, autoScroll: true };
  openModal(`
    <div class="modal-head"><h2>运行日志</h2><button class="x" onclick="closeModal()">×</button></div>
    <div id="log-meta" class="run-meta"></div>
    <div style="display:flex;gap:10px;margin-bottom:10px;align-items:center">
      <label class="ck" style="font-size:12px;color:var(--text-2)"><input type="checkbox" id="log-auto" checked>自动刷新</label>
      <label class="ck" style="font-size:12px;color:var(--text-2)"><input type="checkbox" id="log-scroll" checked>跟随滚动</label>
      <span class="spacer" style="flex:1"></span>
      <button class="btn btn-sm" onclick="stopRun('${runId}')">停止任务</button>
    </div>
    <div class="log-box" id="log-box"></div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">关闭</button>
    </div>`, true);
  $("#log-auto").addEventListener("change", () => {
    if ($("#log-auto").checked) startLogPolling(); else stopLogPolling();
  });
  $("#log-scroll").addEventListener("change", () => { state.logState.autoScroll = $("#log-scroll").checked; });
  loadLogs(true);
  startLogPolling();
}

async function loadLogs(reset) {
  const ls = state.logState;
  if (!ls) return;
  try {
    const d = await get(`/api/runs/${ls.runId}/logs?offset=${reset ? 0 : ls.offset}`);
    const box = $("#log-box");
    if (reset) box.innerHTML = "";
    d.items.forEach((e) => {
      const line = document.createElement("div");
      const cls = e.stream === "stderr" ? "err" : "out";
      line.innerHTML = `<span class="t">${esc(fmtTime(e.ts))}</span><span class="st">${e.stream === "stderr" ? "ERR" : "OUT"}</span><span class="${cls}">${esc(e.line)}</span>`;
      box.appendChild(line);
    });
    ls.offset = d.offset;
    if (ls.autoScroll) box.scrollTop = box.scrollHeight;
    // 刷新元信息（仅在重置或状态变化时）
    const meta = $("#log-meta");
    if (reset || !meta.dataset.status || meta.dataset.status !== d.status) {
      meta.dataset.status = d.status;
      refreshLogMeta(ls.runId);
    }
    if (d.status !== "running" && d.status !== "pending" && $("#log-auto").checked) {
      stopLogPolling();
    }
  } catch (e) {
    const box = $("#log-box");
    if (box && reset) box.innerHTML = `<div style="color:#f87171">${esc(e.message)}</div>`;
  }
}

async function refreshLogMeta(runId) {
  try {
    const r = await get(`/api/runs/${runId}`);
    $("#log-meta").innerHTML = `
      <div class="m"><span class="k">任务</span><span class="v">${esc(r.template_name)}</span></div>
      <div class="m"><span class="k">状态</span><span class="v">${badge(r.status)}</span></div>
      <div class="m"><span class="k">PID</span><span class="v mono">${r.pid ?? "—"}</span></div>
      <div class="m"><span class="k">退出码</span><span class="v mono">${r.exit_code == null ? "—" : r.exit_code}</span></div>
      <div class="m"><span class="k">耗时</span><span class="v">${fmtDur(r.duration_ms)}</span></div>
      <div class="m"><span class="k">命令</span><span class="v mono" style="word-break:break-all">${esc(r.resolved_command || r.command)}</span></div>`;
  } catch (e) { /* ignore */ }
}

function startLogPolling() {
  if (state.logTimer) return;
  state.logTimer = setInterval(() => loadLogs(false), 2000);
}
function stopLogPolling() {
  clearInterval(state.logTimer); state.logTimer = null;
}

/* ================ 轮询 ================ */
function startDashboardPoll() {
  if (state.dashboardTimer) return;
  state.dashboardTimer = setInterval(async () => {
    try {
      const s = await get("/api/stats");
      if (s.running.length) renderDashboard(); else loadRecentRuns($("#view-root"));
    } catch (e) { /* ignore */ }
  }, 3000);
}
function startRunsPoll() {
  if (state.runsTimer) return;
  state.runsTimer = setInterval(async () => {
    try {
      const d = await get("/api/runs?status=&page=1&page_size=5");
      if (d.items.some((r) => r.status === "running" || r.status === "pending")) {
        if (state.view === "runs") loadRuns();
      }
    } catch (e) { /* ignore */ }
  }, 3000);
}

/* ================ 初始化 ================ */
document.addEventListener("DOMContentLoaded", () => {
  $("#tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab");
    if (tab) switchView(tab.dataset.view);
  });
  $("#btn-new-task").addEventListener("click", () => openTaskForm());
  refreshHealth();
  setInterval(refreshHealth, 15000);
  switchView("dashboard");
});

// 暴露给内联 onclick 使用
window.openRunLog = openRunLog;
window.stopRun = stopRun;
window.retryRun = retryRun;
window.openTaskForm = openTaskForm;
window.deleteTask = deleteTask;
window.openRunTaskForm = openRunTaskForm;
window.launchTemplate = launchTemplate;
window.launchFree = launchFree;
window.addParamRow = addParamRow;
window.saveTask = saveTask;
window.closeModal = closeModal;
window.applyRunFilter = applyRunFilter;
window.pageRun = pageRun;
