// Web QC nhan 2D — giao dien (JS thuan, khong can build)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = { cho: "Đang chờ", dang_chay: "Đang chạy", xong: "Xong", loi: "Lỗi" };
const ROLE_VI = { labeler: "Labeler", qc: "QC", admin: "Admin" };
const fmtTime = t => t ? new Date(t * 1000).toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
const fmtIso = s => s ? fmtTime(Date.parse(s) / 1000) : "";
const pctTxt = p => p == null ? "—" : (p * 100).toFixed(1) + "%";
const ok = t => `<span class="ok-text">${esc(t)}</span>`, bad = t => `<span class="err">${esc(t)}</span>`;
const debounce = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };

let ME = null, CFG = null, RUN = null, RUN_DATA = null, POLL = null, CUR_G = null, CUR_F = null, JOBINFO = null;
let FEEDBACK = {}, VIEW = "list", FRAME_FILTER = null, GUIDES = [], JP = { page: 1, count: 0 }, RULE_ATTRS = {};
const SELECTED = new Set();
const THR = () => CFG?.pass_threshold ?? 0.97;
const canQc = () => ME && ME.role !== "labeler";

async function api(path, opt = {}) {
  const o = { credentials: "same-origin", ...opt };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; delete o.json; }
  const r = await fetch(path, o);
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Chưa đăng nhập."); }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error(data?.detail || `Lỗi ${r.status}`);
  return data;
}

// ============================================================ dang nhap
function showLogin() {
  $("#login").classList.remove("hidden"); $("#app").classList.add("hidden");
  fetch("/api/setup").then(r => r.json()).then(s => {
    const h = $("#loginHint");
    if (s.first_run) {
      h.innerHTML = `<b>Lần đầu dùng?</b> Tài khoản <code>admin</code>, mật khẩu nằm trong file <code>${esc(s.admin_file)}</code> trên máy chủ. Đăng nhập xong vào Cài đặt đổi mật khẩu rồi xoá file đó.`;
      h.classList.remove("hidden");
    } else h.classList.add("hidden");
  }).catch(() => {});
  $("#lgUser").focus();
}
$("#loginForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/login", { method: "POST", json: { username: f.get("username").trim(), password: f.get("password") } });
    $("#loginErr").textContent = ""; start();
  } catch (err) { $("#loginErr").textContent = err.message; }
};
$("#logout").onclick = async () => { await api("/api/logout", { method: "POST" }); location.hash = ""; location.reload(); };

async function start() {
  try { ME = await api("/api/me"); } catch { return showLogin(); }
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#whoName").textContent = `${ME.username} · ${ROLE_VI[ME.role] || ME.role}`;
  $("#avatar").textContent = (ME.username[0] || "?").toUpperCase();
  $("#usersCard").classList.toggle("hidden", ME.role !== "admin");
  $("#setForm").classList.toggle("hidden", ME.role !== "admin");
  $("#gUpload").closest(".panel").classList.toggle("hidden", !canQc());
  $("#connNew").classList.toggle("hidden", !canQc());
  await loadConfig();
  await loadGuideOptions();
  refreshJobCtx();
  const m = location.hash.match(/run=(\d+)/), t = location.hash.match(/tab=(\w+)/);
  if (m) openRun(+m[1]);
  else if (t && $("#tab-" + t[1])) showTab(t[1]);
  else if (!CFG.connections.length) showTab("conn"); else showTab("auto");
}

// ============================================================ dieu huong
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", e => { const a = e.target.closest("[data-goto]"); if (a) { e.preventDefault(); showTab(a.dataset.goto); } });
function showTab(t) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach(s => s.classList.toggle("hidden", s.id !== "tab-" + t));
  clearInterval(AUTO_POLL);
  if (t === "auto") AUTO_POLL = setInterval(() => { if (!document.hidden) loadAuto(); }, 15000);
  if (t !== "review") history.replaceState(null, "", "#tab=" + t);       // link mo thang trang nay (vd #tab=trust)
  window.scrollTo({ top: 0 });
  ({ dash: loadDash, auto: loadAuto, trust: loadTrust, history: loadHistory, guide: loadGuides, conn: loadConns, settings: loadSettings })[t]?.();
}
let AUTO_POLL = null;

// ============================================================ cau hinh + ket noi
async function loadConfig() {
  CFG = await api("/api/config");
  const sel = $("#fConn"), cur = sel.value;
  sel.innerHTML = CFG.connections.length
    ? CFG.connections.map(c => `<option value="${c.id}">${esc(c.name)}${c.is_default ? " · mặc định" : ""}</option>`).join("")
    : `<option value="">Chưa có kết nối</option>`;
  sel.value = cur && CFG.connections.some(c => String(c.id) === cur) ? cur : (CFG.default_connection ?? "");
  const f = $("#runForm");
  if (!f.job_id.value && CFG.env_job_id) f.job_id.value = CFG.env_job_id;
  if (!f.task_id.value && CFG.env_task_id) f.task_id.value = CFG.env_task_id;
  if (!f.dataset.modeSet) { f.mode.value = CFG.default_mode || "chinh_xac"; f.dataset.modeSet = 1; }
  renderSideStatus();
}
function curConn() { return CFG?.connections.find(c => String(c.id) === $("#fConn").value); }
function renderSideStatus() {
  const c = curConn(), gpu = CFG.device.startsWith("GPU");
  const host = c ? c.url.replace(/^https?:\/\//, "") : "chưa có kết nối";
  $("#sideStatus").innerHTML =
    `<div class="st-row" title="${esc(c?.url || "")}"><i class="dot ${c ? "ok" : "no"}"></i><span>${esc(host)}</span></div>` +
    (c?.org ? `<div class="st-row"><i class="dot ok"></i><span>Tổ chức ${esc(c.org)}</span></div>` : "") +
    `<div class="st-row" title="${esc(CFG.device)}"><i class="dot ${gpu ? "ok" : "no"}"></i><span>${gpu ? esc(CFG.device.replace(/^GPU \((.*)\)$/, "$1")) : "CPU (chậm)"}</span></div>` +
    (CFG.webhook_enabled ? `<div class="st-row"><i class="dot ok"></i><span>Webhook đang bật</span></div>` : "") +
    (CFG.auto_validation ? `<div class="st-row"><i class="dot ok live"></i><span>Tự review khi sang validation</span></div>` : "");
  $("#navLive").classList.toggle("hidden", !CFG.auto_validation);
}
$("#fConn").onchange = () => { renderSideStatus(); refreshJobCtx(); };

async function loadGuideOptions() {
  GUIDES = await api("/api/guidelines");
  const sel = $("#runGuide"), cur = sel.value;
  sel.innerHTML = `<option value="">Tự chọn theo task</option><option value="0">Không dùng guideline</option>` +
    GUIDES.map(g => `<option value="${g.id}">${esc(g.name)} · ${g.n_labels ? g.n_labels + " nhãn có luật" : "chưa có luật"}</option>`).join("");
  sel.value = cur;
}
function guideFor(taskId) {
  const v = $("#runGuide").value;
  if (v === "0") return null;
  if (v) return GUIDES.find(g => String(g.id) === v) || null;
  return GUIDES.find(g => g.tasks.includes(+taskId)) || null;
}

// --- dong ngu canh duoi thanh cong cu: job nao, 2D/3D, guideline nao, bao nhieu luat ---
const refreshJobCtx = debounce(async () => {
  const jid = $("#fJob").value.trim(), cid = $("#fConn").value;
  JOBINFO = null;
  if (jid && cid && /^\d+$/.test(jid)) {
    try { JOBINFO = await api(`/api/connections/${cid}/jobs/${jid}`); }
    catch (err) { JOBINFO = { error: err.message }; }
    if (JOBINFO?.task_id && String($("#fTask").value) !== String(JOBINFO.task_id)) $("#fTask").value = JOBINFO.task_id;
  }
  renderJobCtx();
}, 350);
function renderJobCtx() {
  const box = $("#jobCtx"), jid = $("#fJob").value.trim(), file = $("#fFile").files[0];
  const chips = [];
  if (JOBINFO?.error) chips.push(`<span class="chip bad">Job ${esc(jid)}: ${esc(JOBINFO.error)}</span>`);
  else if (JOBINFO) {
    chips.push(`<span class="chip">Job ${JOBINFO.id} · ${esc(JOBINFO.task_name || "Task " + JOBINFO.task_id)}</span>`);
    chips.push(JOBINFO.dimension === "3d" ? `<span class="chip bad" title="Job này là dữ liệu 3D (lidar). Tool chỉ chấm được ảnh 2D.">Job 3D (lidar), không chấm được · hãy chọn job 2D khác</span>` : `<span class="chip ok">2D · ${JOBINFO.frames ?? "?"} frame</span>`);
    chips.push(`<span class="chip">${esc(JOBINFO.stage)} · ${esc(JOBINFO.state)}</span>`);
    if (JOBINFO.assignee) chips.push(`<span class="chip">Labeler: ${esc(JOBINFO.assignee)}</span>`);
  } else if (file) chips.push(`<span class="chip warn">Chấm từ file ${esc(file.name)} · không đẩy Issue được nếu không có số job</span>`);
  const g = guideFor($("#fTask").value);
  if ($("#runGuide").value === "0") chips.push(`<span class="chip">Không dùng guideline · chỉ chạy tầng 2 (so với model)</span>`);
  else if (g) chips.push(`<span class="chip ${g.n_labels ? "ok" : "warn"}">Guideline: ${esc(g.name)} · ${g.n_labels ? g.n_labels + " nhãn có luật, chạy cả tầng 1" : "chưa có luật, chỉ để tra cứu"}</span>`);
  else chips.push(`<span class="chip warn">Task chưa gán guideline · chỉ chạy tầng 2. <a href="#" data-goto="guide">Gán guideline</a></span>`);
  box.innerHTML = chips.join("");
  $("#runBtn").disabled = JOBINFO?.dimension === "3d";
}
$("#fJob").addEventListener("input", refreshJobCtx);
$("#fTask").addEventListener("input", renderJobCtx);
$("#runGuide").addEventListener("change", renderJobCtx);
$("#fFile").addEventListener("change", renderJobCtx);

// ============================================================ hop chon job
$("#pickJob").onclick = () => { if (!$("#fConn").value) return showTab("conn"); JP.page = 1; $("#jobPicker").classList.remove("hidden"); loadJobs(); $("#jpSearch").focus(); };
$("#jpClose").onclick = () => $("#jobPicker").classList.add("hidden");
["#jpStage", "#jpState", "#jp2d"].forEach(s => $(s).onchange = () => { JP.page = 1; loadJobs(); });
$("#jpSearch").oninput = debounce(() => { JP.page = 1; loadJobs(); }, 350);
$("#jpPrev").onclick = () => { if (JP.page > 1) { JP.page--; loadJobs(); } };
$("#jpNext").onclick = () => { if (JP.page * 25 < JP.count) { JP.page++; loadJobs(); } };
async function loadJobs() {
  const tb = $("#jpTable tbody");
  tb.innerHTML = `<tr><td colspan="7" class="empty-row">Đang tải danh sách job…</td></tr>`;
  const q = new URLSearchParams({ page: JP.page, search: $("#jpSearch").value, stage: $("#jpStage").value, state: $("#jpState").value, dimension: $("#jp2d").checked ? "2d" : "" });
  try {
    const d = await api(`/api/connections/${$("#fConn").value}/jobs?${q}`);
    JP.count = d.count;
    $("#jpInfo").textContent = `${d.count} job · trang ${d.page}/${Math.max(1, Math.ceil(d.count / d.page_size))}`;
    tb.innerHTML = d.results.map(j => {
      const is3d = j.dimension === "3d", lr = j.last_run;
      const last = lr ? (lr.status === "xong" && lr.pct != null ? `<span class="pill ${lr.pct >= THR() ? "pass" : "fail"}">${pctTxt(lr.pct)}</span>` : `<span class="pill ${lr.status}">${STATUS[lr.status]}</span>`) + ` <span class="meta">#${lr.id}</span>` : `<span class="meta">chưa review</span>`;
      return `<tr class="${is3d ? "dis" : ""}"><td class="strong">${j.id}${is3d ? ' <span class="fp-badge">3D</span>' : ""}</td>
        <td>${esc(j.task_name || "Task " + j.task_id)}</td><td>${esc(j.assignee || "—")}</td><td>${esc(j.stage)} · ${esc(j.state)}</td>
        <td class="r">${j.frames ?? "—"}</td><td>${last}</td>
        <td class="r"><button type="button" class="btn sm" data-job="${j.id}" data-task="${j.task_id}" ${is3d ? 'disabled title="Web này chỉ review job 2D"' : ""}>Chọn</button></td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty-row">Không có job nào. Kiểm tra bộ lọc, hoặc tổ chức trong Kết nối CVAT.</td></tr>`;
  } catch (err) { tb.innerHTML = `<tr><td colspan="7" class="empty-row">${bad(err.message)}</td></tr>`; }
}
$("#jpTable tbody").addEventListener("click", e => {
  const b = e.target.closest("button[data-job]");
  if (!b) return;
  $("#fJob").value = b.dataset.job; $("#fTask").value = b.dataset.task;
  $("#jobPicker").classList.add("hidden");
  refreshJobCtx();
});

// ============================================================ chay review
$("#runForm").onsubmit = async e => {
  e.preventDefault();
  const f = e.target, fd = new FormData();
  ["connection_id", "job_id", "task_id", "guideline_id", "mode", "max_frames"].forEach(k => fd.append(k, f[k].value));
  fd.append("rider", f.rider.checked ? "1" : "0");
  fd.append("auto_push", f.auto_push.checked ? "1" : "0");
  if (f.file.files[0]) fd.append("file", f.file.files[0]);
  $("#runErr").textContent = "";
  $("#optPop").open = false;
  try { const r = await api("/api/runs", { method: "POST", body: fd }); openRun(r.id); }
  catch (err) { $("#runErr").textContent = err.message; }
};
document.addEventListener("click", e => { const p = $("#optPop"); if (p.open && !p.contains(e.target)) p.open = false; });

function openRun(id) {
  showTab("review");
  RUN = id; RUN_DATA = null; CUR_F = null; FRAME_FILTER = null; FEEDBACK = {}; NOTES = []; EDITS = {}; CUR_NAME = null; DRAFT = null; SELECTED.clear();
  $("#frameFilter").classList.add("hidden"); $("#runCompare").innerHTML = ""; $("#copyReport").classList.add("hidden"); $("#noteForm").classList.add("hidden");
  location.hash = "run=" + id;
  $("#runEmpty").classList.add("hidden");
  $("#runPanel").classList.remove("hidden");
  $("#runResult").classList.add("hidden");
  $("#stats").innerHTML = "";
  $("#logBox").open = true;
  $("#runProgress").style.width = "0";
  $("#runProgress").className = "progress-bar";
  $("#pushRes").textContent = "";
  setView("list");
  clearInterval(POLL);
  poll();
  POLL = setInterval(poll, 2000);
}
$("#rerunBtn").onclick = async () => { try { const r = await api(`/api/runs/${RUN}/rerun`, { method: "POST" }); openRun(r.id); } catch (err) { $("#pushRes").innerHTML = bad(err.message); } };

function runMeta(r) {
  return [r.connection?.name, r.assignee ? "Labeler " + r.assignee : "", r.username ? "chạy bởi " + r.username : "", fmtTime(r.created),
    r.guideline_name ? "Guideline " + r.guideline_name : "không dùng guideline", r.source === "webhook" ? "tự chạy qua webhook" : r.source === "validation" ? "tự chạy khi job sang validation" : ""].filter(Boolean).join(" · ");
}

async function poll() {
  const id = RUN;
  let r;
  try { r = await api(`/api/runs/${id}`); } catch { return; }
  if (id !== RUN) return;
  $("#runTitle").textContent = `Lần review #${r.id} · ${r.job_id ? "Job " + r.job_id : "file tải lên"}${r.task_name ? " · " + r.task_name : r.task_id ? " · Task " + r.task_id : ""}`;
  $("#runMeta").textContent = runMeta(r);
  $("#openCvat").classList.toggle("hidden", !r.cvat_job_url);
  if (r.cvat_job_url) $("#openCvat").href = r.cvat_job_url;
  const m = [...(r.log || []).join("\n").matchAll(/\[(\d+)\/(\d+)\]/g)].pop();
  const pct = r.status === "xong" ? 100 : m ? 100 * m[1] / m[2] : r.status === "dang_chay" ? 4 : 0;
  const bar = $("#runProgress");
  bar.style.width = pct + "%";
  bar.className = "progress-bar" + (r.status === "xong" ? " done" : r.status === "loi" ? " fail" : "");
  const st = $("#runStatus");
  st.className = "pill " + r.status;
  const eta = r.eta != null ? (r.eta < 60 ? ` · còn ~${Math.max(5, Math.round(r.eta / 5) * 5)} giây` : ` · còn ~${Math.round(r.eta / 60)} phút`) : "";
  st.textContent = STATUS[r.status] + (r.status === "cho" && r.position ? ` · thứ ${r.position} trong hàng đợi` : r.status === "dang_chay" && m ? ` · ảnh ${m[1]}/${m[2]}` : "") + eta;
  const log = $("#runLog");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 10;
  log.textContent = (r.log || []).join("\n") + (r.error ? `\n❌ ${r.error}` : "");
  if (atBottom) log.scrollTop = log.scrollHeight;
  if (r.status === "xong" || r.status === "loi") {
    clearInterval(POLL);
    if (r.status === "xong") { $("#logBox").open = false; showResult(r); }
  }
}

// ============================================================ ket qua
// Moi dong trong danh sach la 1 "muc": loi cua tool (id = "0","1",…) hoac ghi chu tay cua nguoi review (id = "n12").
let NOTES = [], EDITS = {}, DRAW = false, DRAFT = null;
const isNote = id => String(id).startsWith("n");
const isFp = id => !isNote(id) && FEEDBACK[id]?.verdict === "tool_nham";
const frameOf = name => RUN_DATA.frames.find(fr => fr.name === name);
function noteItems() {
  return NOTES.map(n => ({ id: "n" + n.id, nid: n.id, note: true, frame: n.frame, name: n.name, kind_vi: "Ghi chú người review", sure: true,
    label: "", tang: 0, box: n.box.map(Math.round), msg: n.msg, ref: null, username: n.username,
    preview: (frameOf(n.name)?.preview || "").split("/").pop() || null }));
}
function allItems() { return RUN_DATA.findings.map(f => ({ ...f, id: String(f.id) })).concat(noteItems()); }
const itemById = id => allItems().find(f => f.id === String(id));
const msgOf = f => (!f.note && EDITS[f.id]) || f.msg;

function showResult(r) {
  RUN_DATA = r; FEEDBACK = r.feedback || {}; NOTES = r.notes || []; EDITS = r.edits || {};
  $("#runResult").classList.remove("hidden");
  const s = r.stats || {}, pct = r.pct ?? 0, pass = pct >= THR(), sec = s.giay || 0;
  $("#stats").innerHTML = `
    <div class="kpi main-k"><div class="v">${pctTxt(pct)}<span class="pill ${pass ? "pass" : "fail"}">${pass ? "Đạt" : "Chưa đạt"}</span></div><div class="k">Box không có lỗi chắc chắn · ngưỡng ${(THR() * 100).toFixed(0)}%</div></div>
    <div class="kpi ${s.sure ? "bad" : ""}"><div class="v">${s.sure ?? 0}</div><div class="k">Lỗi chắc chắn</div></div>
    <div class="kpi ${s.unsure ? "warn" : ""}"><div class="v">${s.unsure ?? 0}</div><div class="k">Đang xem xét, cần người xem</div></div>
    <div class="kpi"><div class="v">${s.boxes ?? 0}</div><div class="k">Box trong ${s.frames ?? 0} ảnh</div></div>
    <div class="kpi"><div class="v">${sec < 90 ? Math.round(sec) + "s" : (sec / 60).toFixed(1) + "m"}</div><div class="k">Thời gian chạy · ${s.frames ? (sec / s.frames).toFixed(1) : "?"}s/ảnh</div></div>`;
  $("#runStatus").className = "pill " + (pass ? "pass" : "fail");
  $("#runStatus").textContent = pass ? `Đạt · ${pctTxt(pct)} box đúng` : `Chưa đạt · ${pctTxt(pct)} < ${(THR() * 100).toFixed(0)}%`;
  $("#runStatus").title = `Đã chấm xong. ${pctTxt(pct)} box không có lỗi chắc chắn, ngưỡng đạt là ${(THR() * 100).toFixed(0)}% (đổi trong Cài đặt).`;
  if (r.skipped_labels?.length) $("#runMeta").textContent = runMeta(r) + ` · tool không đánh giá được nhãn: ${r.skipped_labels.join(", ")}`;
  const c = r.compare;
  $("#runCompare").innerHTML = c ? `<span class="c">So với lần #${c.prev_id}${c.prev_pct != null ? " (" + pctTxt(c.prev_pct) + ")" : ""}</span>` +
    `<span class="c good">Đã sửa ${c.fixed}</span><span class="c ${c.still ? "bad" : ""}">Còn ${c.still}</span><span class="c ${c.new ? "bad" : ""}">Mới ${c.new}</span>` : "";
  $("#copyReport").classList.toggle("hidden", !r.report_url);
  $("#fKind").innerHTML = `<option value="">Mọi loại lỗi</option>` + [...new Set(r.findings.map(f => f.kind_vi))].map(k => `<option>${esc(k)}</option>`).join("");
  SELECTED.clear();
  r.findings.forEach(f => { if (f.sure && !isFp(String(f.id))) SELECTED.add(String(f.id)); });   // mac dinh: chon loi chac (tru tool nham)
  NOTES.forEach(n => SELECTED.add("n" + n.id));
  $("#csv").href = `/api/runs/${r.id}/report.csv`;
  $("#pushBtn").disabled = !r.job_id;
  $("#drawBtn").disabled = !r.frames.length;
  $("#pushRes").innerHTML = r.pushed ? pushedText(r.pushed) : r.job_id ? "" : "Review từ file nên không đẩy Issue được. Chạy lại theo số job để đẩy.";
  updateCounts();
  renderList();
  const first = filtered()[0];
  if (first) select(first.id);
  else { $("#pvBox").innerHTML = `<div class="viewer-empty">Không có lỗi nào. Job đạt yêu cầu.</div>`; $("#detail").innerHTML = ""; $("#gRef").innerHTML = ""; }
}
function updateCounts() {
  const F = RUN_DATA.findings.map(f => ({ ...f, id: String(f.id) }));
  $("#cAll").textContent = F.length + NOTES.length;
  $("#cSure").textContent = F.filter(f => f.sure && !isFp(f.id)).length;
  $("#cUnsure").textContent = F.filter(f => !f.sure && !isFp(f.id)).length;
  $("#cFp").textContent = F.filter(f => isFp(f.id)).length;
  $("#cNote").textContent = NOTES.length;
}

let SURE_FILTER = "";
function filtered() {
  const k = $("#fKind").value, t = $("#fTang").value;
  return allItems().filter(f =>
    (!k || f.kind_vi === k || f.note) && (!t || String(f.tang) === t || f.note) && (!FRAME_FILTER || f.name === FRAME_FILTER) &&
    (SURE_FILTER === "" || (SURE_FILTER === "fp" ? isFp(f.id) : SURE_FILTER === "note" ? f.note : !f.note && !isFp(f.id) && String(+f.sure) === SURE_FILTER)));
}
["#fKind", "#fTang"].forEach(s => $(s).onchange = renderList);
$$("#segSure button").forEach(b => b.onclick = () => {
  $$("#segSure button").forEach(x => x.classList.toggle("on", x === b));
  SURE_FILTER = b.dataset.v; renderList();
});

function renderList() {
  const rows = filtered();
  $("#flist").innerHTML = rows.map(f => `
    <li class="fi ${f.note ? "note" : "s" + (+f.sure)}${f.id === CUR_F ? " cur" : ""}${isFp(f.id) ? " fp" : ""}" data-id="${f.id}">
      <input type="checkbox" aria-label="Chọn mục ${esc(f.id)}" ${SELECTED.has(f.id) ? "checked" : ""} ${isFp(f.id) ? "disabled" : ""}>
      <div>
        <div class="fi-top"><span class="fi-kind">${f.note ? "Ghi chú" : esc(f.kind_vi)}</span>${f.label ? `<span class="fi-lab">${esc(f.label)}</span>` : ""}${f.tang === 1 ? '<span class="fi-tier">luật</span>' : ""}${isFp(f.id) ? '<span class="fp-badge">tool nhầm</span>' : ""}${!f.note && EDITS[f.id] ? '<span class="edited-badge">đã sửa</span>' : ""}<span class="fi-frame">${f.frame != null ? "F" + f.frame : ""}</span></div>
        <div class="fi-msg">${esc(msgOf(f))}</div>
      </div>
    </li>`).join("") || `<li class="fl-empty">Không có mục nào với bộ lọc này.</li>`;
  updatePush();
}
$("#flist").addEventListener("click", e => {
  const li = e.target.closest("li[data-id]");
  if (!li) return;
  const id = li.dataset.id;
  if (e.target.type === "checkbox") { e.target.checked ? SELECTED.add(id) : SELECTED.delete(id); return updatePush(); }
  select(id);
});
function select(id) {
  CUR_F = String(id);
  $$("#flist .fi.cur").forEach(x => x.classList.remove("cur"));
  const li = $(`#flist li[data-id="${CUR_F}"]`);
  if (li) { li.classList.add("cur"); li.scrollIntoView({ block: "nearest" }); }
  const f = itemById(CUR_F);
  if (f) showFinding(f);
}

// --- khung xem anh: anh co ve san loi + lop SVG ve khung dang xem va ghi chu tay ---
let CUR_NAME = null;
function showFinding(f) {
  setDraw(false);
  const src = f.preview ? `/api/runs/${RUN}/preview/${encodeURIComponent(f.preview)}` : null;
  if (!src) $("#pvBox").innerHTML = `<div class="viewer-empty">Không có ảnh xem trước cho mục này.</div>`;
  else if (CUR_NAME !== f.name || !$("#pvImg")) {
    $("#pvBox").innerHTML = `<div class="stage" id="stage"><img id="pvImg" src="${src}" alt="Ảnh frame ${f.frame ?? ""} có vẽ lỗi" title="Bấm để phóng to"><svg id="pvSvg" aria-hidden="true"></svg></div>`;
    $("#pvImg").onload = () => { drawOverlay(); drawZoom(); };
  }
  CUR_NAME = src ? f.name : null;
  if ($("#pvImg")?.complete && $("#pvImg").naturalWidth) drawOverlay();
  renderDetail(f);
  const refs = f.note ? [] : (RUN_DATA.guideline_refs?.[f.label] || []);
  $("#gRef").innerHTML = f.note ? "" : RUN_DATA.guideline_name
    ? `<h3>Guideline nói gì về "${esc(f.label)}"</h3>` + (refs.length
      ? refs.map(x => `<div class="gref"><b>${esc(x.title)}</b>${esc(x.snippet)}</div>`).join("")
      : `<p class="meta">Không tìm thấy đoạn nào nhắc tới nhãn này. Thêm tên gọi khác vào cột "Tên gọi khác" trong luật của guideline.</p>`)
    : `<p class="meta">Lần review này không dùng guideline. Gán guideline cho task để thấy đoạn guideline liên quan ở đây.</p>`;
}
function drawOverlay() {
  const img = $("#pvImg"), svg = $("#pvSvg");
  if (!img || !svg || !img.naturalWidth) return;
  const W = img.naturalWidth, H = img.naturalHeight, f = itemById(CUR_F);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const rect = (b, cls) => `<rect class="${cls}" x="${b[0]}" y="${b[1]}" width="${Math.max(1, b[2] - b[0])}" height="${Math.max(1, b[3] - b[1])}" rx="2"/>`;
  let html = noteItems().filter(n => n.name === CUR_NAME).map(n => rect(n.box, "ov-note" + (n.id === CUR_F ? " cur" : ""))).join("");
  if (f && !f.note && f.name === CUR_NAME) {
    html += rect(f.box, "ov-cur");
    // loi vien polygon / vung duong: to dung hinh phan sai (lem / to thua)
    if (f.poly && f.poly.length >= 6) html += `<polygon class="ov-poly" points="${f.poly.map((v, i) => v + (i % 2 ? " " : ",")).join("").trim()}"/>`;
  }
  if (DRAFT) html += rect(DRAFT, "ov-draft");
  svg.innerHTML = html;
}
function drawZoom() {
  const cv = $("#zoomCv"), img = $("#pvImg"), f = itemById(CUR_F);
  if (!cv || !img || !img.naturalWidth || !f) return;
  const [x1, y1, x2, y2] = f.box, w = x2 - x1, h = y2 - y1, pad = Math.max(30, Math.max(w, h) * .45);
  const sx = Math.max(0, x1 - pad), sy = Math.max(0, y1 - pad);
  const sw = Math.min(img.naturalWidth - sx, w + 2 * pad), sh = Math.min(img.naturalHeight - sy, h + 2 * pad);
  if (sw < 2 || sh < 2) return;
  cv.width = 440; cv.height = Math.round(440 * sh / sw);
  const g = cv.getContext("2d");
  g.drawImage(img, sx, sy, sw, sh, 0, 0, cv.width, cv.height);
  const k = cv.width / sw;
  g.strokeStyle = f.note ? "#a07cff" : "#4d7cff"; g.lineWidth = 3; g.setLineDash([10, 6]);
  g.strokeRect((x1 - sx) * k, (y1 - sy) * k, w * k, h * k);
  if (f.poly && f.poly.length >= 6) {           // phan sai cua polygon (lem / to thua) to mau
    g.setLineDash([]); g.beginPath();
    for (let i = 0; i < f.poly.length; i += 2) { const px = (f.poly[i] - sx) * k, py = (f.poly[i + 1] - sy) * k; i ? g.lineTo(px, py) : g.moveTo(px, py); }
    g.closePath(); g.fillStyle = "rgba(239, 68, 68, .28)"; g.fill(); g.strokeStyle = "#ef4444"; g.lineWidth = 2; g.stroke();
  }
}
function renderDetail(f) {
  const fb = FEEDBACK[f.id], edited = !f.note && EDITS[f.id];
  const tags = f.note
    ? `<span class="tag note">Ghi chú người review</span><span class="tag k">${esc(f.username || "")}</span>`
    : `<span class="tag s${+f.sure}">${f.sure ? "Lỗi" : "Đang xem xét"}</span><span class="tag k">${esc(f.kind_vi)}</span><span class="tag k">${esc(f.label)}</span>${f.tang === 1 ? '<span class="tag k">Tầng 1 · luật</span>' : '<span class="tag k">Tầng 2 · model</span>'}${edited ? '<span class="edited-badge">lời nhắn đã sửa</span>' : ""}`;
  $("#detail").innerHTML = `
    <div class="zoom-wrap"><canvas id="zoomCv" title="Phóng to vùng ${f.note ? "ghi chú" : "lỗi"}"></canvas>
      <div>
        <div class="detail-head">${tags}</div>
        <div class="detail-msg" id="detailMsg">${esc(msgOf(f))}</div>
        <div class="detail-meta">${f.frame != null ? "frame " + f.frame + " · " : ""}${esc(f.name)} · box [${f.box.join(", ")}]${f.ref ? " · " + esc(f.ref) : ""}</div>
        <div class="detail-actions">
          <button type="button" class="btn sm" id="editBtn"><svg class="ic"><use href="#i-pen"/></svg>${f.note ? "Sửa ghi chú" : "Sửa lời nhắn"}</button>
          ${f.note ? `<button type="button" class="link-danger" id="delNoteBtn">Xoá ghi chú</button>`
            : `<button type="button" class="btn sm ${fb ? "fp-on" : ""}" id="fpBtn"><svg class="ic"><use href="#i-flag"/></svg>${fb ? "Bỏ đánh dấu tool nhầm" : "Tool nhầm"}</button>${fb ? `<span class="meta">${esc(fb.username)}${fb.note ? ": " + esc(fb.note) : ""}</span>` : ""}`}
        </div>
        <div id="editBox" class="edit-box hidden">
          <textarea id="editText" maxlength="500" aria-label="Lời nhắn cho labeler">${esc(msgOf(f))}</textarea>
          <div class="row-actions"><button type="button" class="btn primary sm" id="editSave">Lưu</button><button type="button" class="btn sm" id="editCancel">Huỷ</button>${edited ? '<button type="button" class="txt-btn" id="editReset">Về lời nhắn gốc của tool</button>' : ""}</div>
        </div>
      </div>
    </div>`;
  drawZoom();
  $("#editBtn").onclick = () => { $("#editBox").classList.remove("hidden"); $("#editText").focus(); };
  $("#editCancel").onclick = () => $("#editBox").classList.add("hidden");
  $("#editSave").onclick = () => saveMsg(f, $("#editText").value.trim());
  if ($("#editReset")) $("#editReset").onclick = () => saveMsg(f, "");
  if ($("#fpBtn")) $("#fpBtn").onclick = () => toggleFp(f.id, "");
  if ($("#delNoteBtn")) $("#delNoteBtn").onclick = async () => {
    if (!(await askConfirm("Xoá ghi chú này?", "Xoá", "Xoá ghi chú?"))) return;
    NOTES = await api(`/api/runs/${RUN}/notes/${f.nid}`, { method: "DELETE" });
    SELECTED.delete(f.id); updateCounts(); renderList();
    const first = filtered()[0]; if (first) select(first.id); else { $("#detail").innerHTML = ""; drawOverlay(); }
  };
}
async function saveMsg(f, msg) {
  try {
    if (f.note) {
      if (!msg) return;
      NOTES = await api(`/api/runs/${RUN}/notes/${f.nid}`, { method: "PUT", json: { msg } });
    } else EDITS = await api(`/api/runs/${RUN}/findings/${f.id}`, { method: "PUT", json: { msg } });
    renderList(); select(f.id);
  } catch (err) { $("#pushRes").innerHTML = bad(err.message); }
}
async function toggleFp(id, note) {
  if (isNote(id)) return;
  try {
    FEEDBACK = await api(`/api/runs/${RUN}/feedback`, { method: "POST", json: { finding_id: +id, verdict: isFp(id) ? "" : "tool_nham", note } });
    if (isFp(id)) SELECTED.delete(id);
    updateCounts(); renderList(); select(id);
  } catch (err) { $("#pushRes").innerHTML = bad(err.message); }
}

// --- ve khung ghi chu tren anh ---
function setDraw(on) {
  DRAW = on; DRAFT = on ? DRAFT : null;
  $("#drawBtn").classList.toggle("on", on);
  $("#stage")?.classList.toggle("drawing", on);
  if (!on) $("#noteForm").classList.add("hidden");
  drawOverlay();
}
$("#drawBtn").onclick = () => {
  if (!$("#pvImg")) { const fr = RUN_DATA.frames[0]; if (!fr) return; FRAME_FILTER = null; showFinding({ id: "", name: fr.name, frame: fr.frame, preview: fr.preview.split("/").pop(), box: [0, 0, 0, 0], note: true, msg: "" }); }
  setDraw(!DRAW);
};
function toNat(e) {
  const img = $("#pvImg"), r = img.getBoundingClientRect();
  return [Math.max(0, Math.min(img.naturalWidth, (e.clientX - r.left) / r.width * img.naturalWidth)),
          Math.max(0, Math.min(img.naturalHeight, (e.clientY - r.top) / r.height * img.naturalHeight))];
}
let DRAG = null;
$("#pvBox").addEventListener("pointerdown", e => {
  if (!DRAW || !$("#pvImg") || !e.target.closest("#stage")) return;
  e.preventDefault(); DRAG = toNat(e); DRAFT = [...DRAG, ...DRAG]; drawOverlay();
  $("#stage").setPointerCapture?.(e.pointerId);
});
$("#pvBox").addEventListener("pointermove", e => {
  if (!DRAG) return;
  const [x, y] = toNat(e);
  DRAFT = [Math.min(DRAG[0], x), Math.min(DRAG[1], y), Math.max(DRAG[0], x), Math.max(DRAG[1], y)]; drawOverlay();
});
$("#pvBox").addEventListener("pointerup", () => {
  if (!DRAG) return;
  DRAG = null;
  if (!DRAFT || DRAFT[2] - DRAFT[0] < 6 || DRAFT[3] - DRAFT[1] < 6) { DRAFT = null; drawOverlay(); return; }
  $("#noteForm").classList.remove("hidden"); $("#noteText").value = ""; $("#noteText").focus();
});
$("#noteCancel").onclick = () => { DRAFT = null; setDraw(false); };
$("#noteForm").onsubmit = async e => {
  e.preventDefault();
  const fr = frameOf(CUR_NAME);
  try {
    const r = await api(`/api/runs/${RUN}/notes`, { method: "POST", json: { frame: fr?.frame, name: CUR_NAME, box: DRAFT, msg: $("#noteText").value.trim() } });
    NOTES = r.notes; SELECTED.add("n" + r.id);
    DRAFT = null; setDraw(false); updateCounts(); renderList(); select("n" + r.id);
  } catch (err) { $("#pushRes").innerHTML = bad(err.message); }
};
$("#pvBox").addEventListener("click", e => {
  if (DRAW || e.target.id !== "pvImg") return;
  $("#modalImg").src = e.target.src; $("#modal").classList.remove("hidden");
});
$("#modal").onclick = () => $("#modal").classList.add("hidden");
window.addEventListener("resize", debounce(drawOverlay, 100));

$("#selSure").onclick = () => { SELECTED.clear(); allItems().forEach(f => (f.note || (f.sure && !isFp(f.id))) && SELECTED.add(f.id)); renderList(); };
$("#selAll").onclick = () => { filtered().forEach(f => !isFp(f.id) && SELECTED.add(f.id)); renderList(); };
$("#selNone").onclick = () => { filtered().forEach(f => SELECTED.delete(f.id)); renderList(); };
function updatePush() {
  $("#pushLabel").textContent = SELECTED.size ? `Đẩy ${SELECTED.size} Issue lên CVAT` : "Đẩy Issue lên CVAT";
  if (RUN_DATA) $("#selInfo").textContent = `Đã chọn ${SELECTED.size} / ${RUN_DATA.findings.length + NOTES.length}`;
}
$("#copyReport").onclick = async () => {
  const url = RUN_DATA?.report_url; if (!url) return;
  const b = $("#copyReport");
  try { await navigator.clipboard.writeText(url); b.classList.add("copied"); b.lastChild.textContent = "Đã copy, dán gửi labeler"; }
  catch { window.open(url, "_blank"); }
  setTimeout(() => { b.classList.remove("copied"); b.lastChild.textContent = "Copy link gửi labeler"; }, 2500);
};

// phim tat: len/xuong chuyen, Space chon/bo, X tool nham, N ghi chu tren anh, Esc thoat ve
document.addEventListener("keydown", e => {
  if (!RUN_DATA || VIEW !== "list" || $("#tab-review").classList.contains("hidden")) return;
  if ($$(".modal").some(m => !m.classList.contains("hidden"))) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  if (e.key === "n" || e.key === "N") { e.preventDefault(); $("#drawBtn").click(); return; }
  const rows = filtered(); if (!rows.length) return;
  const i = Math.max(0, rows.findIndex(f => f.id === CUR_F));
  if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); select(rows[Math.min(rows.length - 1, i + 1)].id); }
  else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); select(rows[Math.max(0, i - 1)].id); }
  else if (e.key === " " && CUR_F != null && !isFp(CUR_F)) {
    e.preventDefault();
    SELECTED.has(CUR_F) ? SELECTED.delete(CUR_F) : SELECTED.add(CUR_F);
    const cb = $(`#flist li[data-id="${CUR_F}"] input`); if (cb) cb.checked = SELECTED.has(CUR_F);
    updatePush();
  } else if ((e.key === "x" || e.key === "X") && CUR_F != null) { e.preventDefault(); toggleFp(CUR_F, ""); }
});

// --- 3 che do xem: danh sach / khung hinh / issue ---
$$(".wb-head .tabs-inline button").forEach(b => b.onclick = () => setView(b.dataset.view));
function setView(v) {
  VIEW = v;
  if (v !== "list") setDraw(false);
  $$(".wb-head .tabs-inline button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  $("#viewList").classList.toggle("hidden", v !== "list");
  $("#viewFrames").classList.toggle("hidden", v !== "frames");
  $("#viewIssues").classList.toggle("hidden", v !== "issues");
  $("#viewAnalysis").classList.toggle("hidden", v !== "analysis");
  if (v === "analysis") openAnalysis();
  if (v === "frames") renderFrames();
  if (v === "issues") loadIssues();
}
function renderFrames() {
  if (!RUN_DATA) return;
  $("#frameGrid").innerHTML = RUN_DATA.frames.map(fr => {
    const nn = NOTES.filter(n => n.name === fr.name).length, unsure = fr.n - fr.sure;
    return `<button type="button" class="frame-card ${fr.n || nn ? "" : "clean"}" data-name="${esc(fr.name)}">
      <img src="${fr.preview}" alt="Frame ${fr.frame ?? ""}" loading="lazy">
      <div class="fc-meta">${fr.sure ? `<span class="tag s1">${fr.sure} lỗi</span>` : ""}${unsure ? `<span class="tag s0">${unsure} đang xem xét</span>` : ""}${nn ? `<span class="tag note">${nn} ghi chú</span>` : ""}${fr.n || nn ? "" : '<span class="tag k">Không lỗi</span>'}<span class="fc-name" title="${esc(fr.name)}">${fr.frame != null ? "F" + fr.frame + " · " : ""}${esc(fr.name)}</span></div>
    </button>`;
  }).join("") || `<p class="empty-note">Không có ảnh.</p>`;
}
$("#frameGrid").addEventListener("click", e => {
  const c = e.target.closest(".frame-card"); if (!c) return;
  FRAME_FILTER = c.dataset.name;
  $("#frameFilter").innerHTML = `Chỉ hiện ${esc(FRAME_FILTER.slice(0, 32))}${FRAME_FILTER.length > 32 ? "…" : ""}<button type="button" aria-label="Bỏ lọc khung hình">×</button>`;
  $("#frameFilter").classList.remove("hidden");
  setView("list"); renderList();
  const first = filtered()[0];
  if (first) select(first.id);
  else { const fr = frameOf(FRAME_FILTER); showFinding({ id: "", name: fr.name, frame: fr.frame, preview: fr.preview.split("/").pop(), box: [0, 0, 0, 0], note: true, msg: "Khung hình này không có lỗi. Bấm Ghi chú trên ảnh nếu muốn nhắc labeler điều gì." }); }
});
$("#frameFilter").addEventListener("click", e => { if (e.target.tagName === "BUTTON") { FRAME_FILTER = null; $("#frameFilter").classList.add("hidden"); renderList(); } });
async function loadIssues() {
  const tb = $("#issueTable tbody");
  if (!RUN_DATA?.job_id) { tb.innerHTML = `<tr><td colspan="5" class="empty-row">Lần review từ file không gắn job nên không có Issue.</td></tr>`; return; }
  tb.innerHTML = `<tr><td colspan="5" class="empty-row">Đang tải Issue từ CVAT…</td></tr>`;
  try {
    const items = await api(`/api/runs/${RUN}/issues`);
    const done = items.filter(x => x.resolved).length;
    $("#issuesMeta").textContent = `${items.length} Issue do tool tạo · ${done} đã xử lý · ${items.length - done} còn mở. Labeler bấm Resolve trên CVAT thì Issue chuyển sang "Đã xử lý".`;
    tb.innerHTML = items.map(x => `<tr><td class="strong">#${x.id}</td><td>${x.frame ?? "—"}</td><td style="white-space:normal">${esc(x.message)}</td>
      <td class="r">${Math.max(0, x.comments - 1)}</td><td>${x.resolved ? '<span class="pill pass">Đã xử lý</span>' : '<span class="pill fail">Còn mở</span>'}</td></tr>`).join("")
      || `<tr><td colspan="5" class="empty-row">Chưa có Issue nào do tool tạo trên job này.</td></tr>`;
  } catch (err) { tb.innerHTML = `<tr><td colspan="5" class="empty-row">${bad(err.message)}</td></tr>`; }
}
$("#reloadIssues").onclick = loadIssues;

function pushedText(p) {
  const parts = [`Tạo <b>${p.created}</b> Issue mới`];
  if (p.kept) parts.push(`giữ ${p.kept} Issue cũ (lỗi vẫn còn)`);
  if (p.resolved) parts.push(`đóng ${p.resolved} Issue cũ (lỗi đã hết)`);
  if (p.removed) parts.push(`thay ${p.removed} Issue cũ (lỗi còn nhưng lời nhắn đổi)`);
  return parts.join(", ") + ` · ${fmtTime(p.time)} · ` + (p.unchanged ? ok("Nhãn gốc không đổi ✔") : bad("Nhãn trên CVAT đã khác lúc review (có người đang sửa job?)"));
}
$("#pushBtn").onclick = async () => {
  const ids = [...SELECTED].filter(x => !isNote(x)).map(Number), noteIds = [...SELECTED].filter(isNote).map(x => +x.slice(1));
  const summary = $("#addSummary").checked;
  if (!ids.length && !noteIds.length && !summary) { $("#pushRes").innerHTML = bad("Chưa chọn mục nào."); return; }
  const nUnsure = RUN_DATA.findings.filter(f => SELECTED.has(String(f.id)) && !f.sure).length;
  const sure = await askConfirm(`Đẩy lên job ${RUN_DATA.job_id}: ${ids.length} lỗi${nUnsure ? ` (${nUnsure} đang xem xét)` : ""}, ${noteIds.length} ghi chú của bạn${summary ? ", kèm 1 Issue tổng kết có link trang lỗi cho labeler" : ""}. ` +
    ($("#replaceOld").checked ? "Lỗi đã có Issue từ lần trước sẽ không bị tạo trùng. " : "") + "Mỗi mục thành 1 Issue ghim đúng chỗ trên ảnh. Tool không sửa nhãn.", "Đẩy Issue", "Đẩy Issue lên CVAT?");
  if (!sure) return;
  const b = $("#pushBtn"); b.disabled = true; $("#pushRes").textContent = "Đang đẩy…";
  try {
    const p = await api(`/api/runs/${RUN}/push`, { method: "POST", json: { ids, note_ids: noteIds, summary, replace_old: $("#replaceOld").checked } });
    $("#pushRes").innerHTML = pushedText(p);
  } catch (err) { $("#pushRes").innerHTML = bad(err.message); }
  b.disabled = false;
};

// ============================================================ tong quan
let DASH_DAYS = 30;
$$("#dashDays button").forEach(b => b.onclick = () => { $$("#dashDays button").forEach(x => x.classList.toggle("on", x === b)); DASH_DAYS = +b.dataset.d; loadDash(); });
async function loadDash() {
  const d = await api(`/api/dashboard?days=${DASH_DAYS}`);
  const k = (v, label, cls = "") => `<div class="kpi ${cls}"><div class="v">${v}</div><div class="k">${label}</div></div>`;
  $("#dashKpis").innerHTML =
    k(d.done, `Lần review xong · ${d.days} ngày`) +
    k(d.done ? pctTxt(d.passed / d.done) : "—", `Tỉ lệ đạt (ngưỡng ${(d.threshold * 100).toFixed(0)}%)`, d.done && d.passed / d.done < .8 ? "bad" : "") +
    k(pctTxt(d.avg_pct), "% box đúng trung bình") +
    k(d.sure, `Lỗi chắc chắn · ${d.unsure} đang xem xét`, d.sure ? "bad" : "") +
    k(d.issues_pushed, "Issue đã đẩy lên CVAT") +
    k(d.fp_rate == null ? "—" : pctTxt(d.fp_rate), `Tỉ lệ tool nhầm · ${d.fp} lỗi`, d.fp_rate > .15 ? "warn" : "");
  const max = Math.max(1, ...d.kinds.map(x => x[1]));
  $("#dashKindsMeta").textContent = d.kinds.length ? `${d.kinds.reduce((a, x) => a + x[1], 0)} lỗi` : "";
  $("#dashKinds").innerHTML = d.kinds.map(([n, v]) => `<div class="bar-row"><span>${esc(n)}</span><span class="bar"><i style="width:${(v / max * 100).toFixed(1)}%"></i></span><span class="n">${v}</span></div>`).join("")
    || `<p class="empty-note">Chưa có dữ liệu trong khoảng này.</p>`;
  const tr = d.trend.slice(-30);
  $("#dashTrend").innerHTML = tr.map(t => `<div class="t-col" title="${t.day}: ${t.runs} lần, ${pctTxt(t.avg_pct)}"><div class="t-bar ${t.avg_pct < d.threshold ? "low" : ""}" style="height:${Math.max(2, (t.avg_pct - .5) / .5 * 100).toFixed(0)}%"></div><span class="t-lab">${t.day.slice(5).replace("-", "/")}</span></div>`).join("")
    || `<p class="empty-note" style="width:100%">Chưa có dữ liệu trong khoảng này.</p>`;
  $("#dashAss tbody").innerHTML = d.assignees.map(a => `<tr><td class="strong">${esc(a.name)}</td><td class="r">${a.runs}</td><td class="r">${a.jobs}</td>
    <td class="r">${pctTxt(a.avg_pct)}<span class="pbar ${a.avg_pct < d.threshold ? "low" : ""}"><i style="width:${(a.avg_pct * 100).toFixed(0)}%"></i></span></td>
    <td class="r">${pctTxt(a.pass_rate)}</td><td class="r">${a.sure} / ${a.unsure}</td><td>${fmtTime(a.last)}</td></tr>`).join("")
    || `<tr><td colspan="7" class="empty-row">Chưa có lần review nào trong khoảng này.</td></tr>`;
}

// hieu qua Issue: doc tu CVAT (cham), chi chay khi bam "Do"
$("#effBtn").onclick = loadEffect;
async function loadEffect() {
  $("#effBox").innerHTML = `<p class="meta">Đang đọc Issue và nhãn trên CVAT…</p>`;
  let e;
  try { e = await api(`/api/hieu_qua?days=${DASH_DAYS}`); }
  catch (err) { $("#effBox").innerHTML = bad(err.message); return; }
  const k = (v, label, cls = "") => `<div class="kpi ${cls}"><div class="v">${v}</div><div class="k">${label}</div></div>`;
  const judged = e.da_sua + e.khong_sua + e.tool_nham;
  const rows = Object.entries(e.theo_loai).filter(([, v]) => v.da_sua + v.khong_sua + v.tool_nham + v.chua_xu_ly > 0).sort((a, b) => (b[1].da_sua + b[1].khong_sua) - (a[1].da_sua + a[1].khong_sua));
  $("#effBox").innerHTML = (e.jobs ? `<div class="kpis kpis-4">` +
      k(e.ti_le_issue_dung == null ? "—" : pctTxt(e.ti_le_issue_dung), `Issue đúng (annotator đã sửa theo) · ${e.da_sua}/${judged}`, e.ti_le_issue_dung < .8 ? "warn" : "") +
      k(e.bat_truoc_review_cheo == null ? "—" : pctTxt(e.bat_truoc_review_cheo), `Lỗi tool bắt trước review chéo · người review tìm thêm ${e.nguoi_tim}`) +
      k(e.vong_tra_lai_tb == null ? "—" : e.vong_tra_lai_tb.toFixed(1), `Số vòng bị trả lại / job · ${e.jobs} job`) +
      k(e.chua_xu_ly, "Issue còn mở, chưa sửa" + (e.khong_ro ? ` · ${e.khong_ro} không rõ (Issue do bản web khác tạo, không tính)` : "")) + `</div>` : `<p class="empty-note">Chưa có job nào đã đẩy Issue trong khoảng này.</p>`) +
    (rows.length ? `<div class="tablewrap mt"><table class="tbl"><thead><tr><th>Loại lỗi</th><th class="r">Đã sửa (đúng)</th><th class="r">Đóng không sửa</th><th class="r">Tool nhầm</th><th class="r">Còn mở</th><th class="r">% đúng</th></tr></thead><tbody>` +
      rows.map(([n, v]) => `<tr><td>${esc(n)}</td><td class="r">${v.da_sua}</td><td class="r">${v.khong_sua}</td><td class="r">${v.tool_nham}</td><td class="r">${v.chua_xu_ly}</td><td class="r">${v.ti_le_dung == null ? "—" : pctTxt(v.ti_le_dung)}</td></tr>`).join("") + `</tbody></table></div>` : "") +
    (e.per_job.length ? `<div class="tablewrap mt"><table class="tbl"><thead><tr><th>Job</th><th>Labeler</th><th class="r">Vòng trả lại</th><th class="r">Issue tool</th><th class="r">% đúng</th><th class="r">Người tìm thêm</th></tr></thead><tbody>` +
      e.per_job.map(j => `<tr><td>${j.job_id}</td><td>${esc(j.assignee || "—")}</td><td class="r">${j.so_vong_tra_lai}</td><td class="r">${j.so_issue_tool}</td><td class="r">${j.ti_le_issue_dung == null ? "—" : pctTxt(j.ti_le_issue_dung)}</td><td class="r">${j.nguoi_tim}</td></tr>`).join("") + `</tbody></table></div>` : "") +
    (e.errors.length ? `<div class="mt">${bad("Không đọc được: " + e.errors.join("; "))}</div>` : "");
}

// ============================================================ lich su
let HIST = [];
async function loadHistory() { HIST = await api("/api/runs" + ($("#hJob").value ? `?job_id=${encodeURIComponent($("#hJob").value)}` : "")); renderHistory(); }
function renderHistory() {
  const w = $("#hWho").value.trim().toLowerCase();
  const rows = HIST.filter(r => !w || (r.assignee || "").toLowerCase().includes(w) || (r.username || "").toLowerCase().includes(w));
  $("#htable tbody").innerHTML = rows.map(r => {
    const s = r.stats || {}, p = r.pct;
    const st = r.status === "xong" && p != null ? (p >= THR() ? ["pass", "Đạt"] : ["fail", "Chưa đạt"]) : [r.status, STATUS[r.status] + (r.position ? " · thứ " + r.position : "")];
    return `<tr data-id="${r.id}"><td class="strong">#${r.id}</td><td>${r.job_id ?? "file"}</td><td>${esc(r.task_name || r.task_id || "—")}</td>
      <td>${esc(r.assignee || "—")}</td><td>${esc(r.username)}${r.source === "webhook" || r.source === "validation" ? ' <span class="fp-badge">tự động</span>' : ""}</td><td>${fmtTime(r.created)}</td>
      <td><span class="pill ${st[0]}">${st[1]}${r.eta != null ? " · ~" + Math.max(1, Math.round(r.eta / 60)) + " phút" : ""}</span></td><td class="r">${pctTxt(p)}</td><td class="r">${s.boxes !== undefined ? `${s.sure} / ${s.unsure}` : "—"}</td>
      <td class="r">${r.fp || "—"}</td><td class="r">${r.pushed ? r.pushed.created + (r.pushed.kept ? " +" + r.pushed.kept : "") : "—"}</td></tr>`;
  }).join("") || `<tr><td colspan="11" class="empty-row">Chưa có lần review nào.</td></tr>`;
}
$("#hJob").oninput = debounce(loadHistory, 300);
$("#hWho").oninput = renderHistory;
$("#htable tbody").addEventListener("click", e => { const tr = e.target.closest("tr[data-id]"); if (tr) openRun(+tr.dataset.id); });

// ============================================================ guideline
async function loadGuides() {
  await loadGuideOptions();
  $("#gtable tbody").innerHTML = GUIDES.map(g => `<tr data-id="${g.id}" class="${CUR_G?.id === g.id ? "row-cur" : ""}"><td class="strong">${esc(g.name)}</td><td>${esc(g.file_name)}</td>
    <td>${g.tasks.length ? g.tasks.join(", ") : '<span class="meta">chưa gán</span>'}</td>
    <td>${g.n_labels ? `<span class="pill pass">${g.n_labels} nhãn</span>` : '<span class="pill">Chưa có luật</span>'}${g.warnings?.length ? ' <span class="pill fail" title="' + esc(g.warnings.join(" · ")) + '">cần xem lại</span>' : ""}</td>
    <td class="r"><div class="row-btns"><button class="btn sm" data-open="${g.id}">${canQc() ? "Mở · soạn luật" : "Mở"}</button>${canQc() ? `<button class="link-danger" data-del="${g.id}">Xoá</button>` : ""}</div></td></tr>`).join("")
    || `<tr><td colspan="5" class="empty-row">Chưa có guideline nào. Tải file guideline của dự án lên ở trên: web sẽ đọc file, chia mục để tra cứu, rồi bạn soạn luật kiểm tra ngay bên dưới.</td></tr>`;
  // tu mo san guideline dang xem (hoac cai dau tien) de khong ai nghi trang chi co danh sach
  const keep = CUR_G && GUIDES.find(g => g.id === CUR_G.id);
  if (GUIDES.length) openGuide((keep || GUIDES[0]).id, false); else $("#gDetail").classList.add("hidden");
}
$("#gtable tbody").addEventListener("click", async e => {
  if (e.target.dataset.open) { openGuide(+e.target.dataset.open); return; }
  if (e.target.dataset.del) {
    e.stopPropagation();
    if (await askConfirm("Xoá guideline này? File gốc và luật sẽ bị xoá.", "Xoá", "Xoá guideline?")) {
      await api(`/api/guidelines/${e.target.dataset.del}`, { method: "DELETE" }); loadGuides(); $("#gDetail").classList.add("hidden");
    }
    return;
  }
  const tr = e.target.closest("tr[data-id]");
  if (tr) openGuide(+tr.dataset.id);
});
$("#gUpload").onsubmit = async e => {
  e.preventDefault();
  $("#gUpErr").textContent = "Đang đọc file…";
  try {
    const r = await api("/api/guidelines", { method: "POST", body: new FormData(e.target) });
    $("#gUpErr").textContent = r.warning || ""; e.target.reset();
    await loadGuides(); openGuide(r.id);
  } catch (err) { $("#gUpErr").innerHTML = bad(err.message); }
};

async function openGuide(id, scroll = true) {
  const g = await api(`/api/guidelines/${id}`);
  const same = CUR_G?.id === id;
  CUR_G = g; if (!same) RULE_ATTRS = {};
  $("#gDetail").classList.remove("hidden");
  $("#gName").textContent = g.name;
  $("#gFile").href = `/api/guidelines/${id}/file`;
  $("#gTasks").textContent = g.tasks.length ? `Đang gán cho task ${g.tasks.join(", ")}: review các task này sẽ tự dùng guideline này.` : "Chưa gán cho task nào: nhập số task ở dưới rồi bấm Gán.";
  $("#gTask").value = $("#gTask").value || $("#fTask").value || CFG.env_task_id || "";
  $("#gRules").value = g.rules;
  if (!same) {
    $("#ruleMsg").innerHTML = g.warnings?.length ? bad("Cần xem lại: " + g.warnings.join(" · ")) : "";
    $("#gMsg").textContent = "";
  }
  renderRuleTable(g.rules_obj || {});
  renderSections(g.sections);
  const ro = !canQc();
  ["#gRules", "#gSave", "#gTemplate", "#gAssign", "#ruleAdd", "#ruleSave"].forEach(s => $(s).disabled = ro);
  setGTab("rules");
  $$("#gtable tbody tr").forEach(tr => tr.classList.toggle("row-cur", +tr.dataset.id === id));
  if (scroll) $("#gDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}
$$(".gtabs button").forEach(b => b.onclick = () => setGTab(b.dataset.g));
function setGTab(t) {
  $$(".gtabs button").forEach(b => b.classList.toggle("on", b.dataset.g === t));
  $("#gPaneRules").classList.toggle("hidden", t !== "rules");
  $("#gPaneContent").classList.toggle("hidden", t !== "content");
  $("#gPaneYaml").classList.toggle("hidden", t !== "yaml");
}

// --- trinh soan luat dang bang ---
const list2txt = v => (v || []).join(", ");
const txt2list = s => s.split(",").map(x => x.trim()).filter(Boolean);
function ruleRow(name, sp = {}) {
  const tc = CUR_G?.tool_classes || [];
  const rr = sp.ti_le_rong_cao || [];
  const attrs = RULE_ATTRS[name];
  return `<tr>
    <td><input class="in-name" value="${esc(name)}" aria-label="Tên nhãn"></td>
    <td><select class="in-tool" aria-label="Tool hiểu là"><option value="">— không kiểm tầng 2 —</option>${tc.map(c => `<option ${sp.loai_tool === c ? "selected" : ""}>${c}</option>`).join("")}</select></td>
    <td><input class="in-num in-min" inputmode="numeric" value="${sp.kich_thuoc_toi_thieu_px || ""}" placeholder="0" aria-label="Kích thước tối thiểu"></td>
    <td><div class="in-ratio"><input class="in-rmin" inputmode="decimal" value="${rr[0] ?? ""}" placeholder="min" aria-label="Tỉ lệ tối thiểu"><span>–</span><input class="in-rmax" inputmode="decimal" value="${rr[1] ?? ""}" placeholder="max" aria-label="Tỉ lệ tối đa"></div></td>
    <td><input class="in-txt in-req" value="${esc(list2txt(sp.thuoc_tinh_bat_buoc))}" placeholder="${attrs?.length ? esc(attrs.join(", ")) : "occluded, truncated"}" aria-label="Thuộc tính bắt buộc"></td>
    <td><input class="in-txt in-def" value="${esc(list2txt(sp.khong_de_mac_dinh))}" aria-label="Không để mặc định"></td>
    <td><input class="in-txt in-syn" value="${esc(list2txt(sp.dong_nghia))}" placeholder="ô tô, xe hơi" aria-label="Tên gọi khác"></td>
    <td><input class="in-muc" value="${esc(sp.muc || "")}" placeholder="3.1" aria-label="Mục guideline"></td>
    <td class="r"><button type="button" class="link-danger rule-del" aria-label="Xoá dòng">Xoá</button></td></tr>`;
}
let RULE_Q = {};               // quy tac chung dang soan (giu ca khoa web chua co o sua)
function renderRuleTable(obj) {
  const nhan = obj.nhan || {}, q = obj.quy_tac || {};
  RULE_Q = { ...q };
  $("#ruleTable tbody").innerHTML = Object.entries(nhan).map(([n, sp]) => ruleRow(n, sp || {})).join("")
    || `<tr class="rule-empty"><td colspan="9" class="empty-row">Chưa có nhãn nào. Nhập số task rồi bấm <b>Lấy nhãn từ task</b>, hoặc bấm <b>Thêm nhãn</b>.</td></tr>`;
  $("#qRider").checked = q.nguoi_lai_co_box_rieng ?? true;
  $("#qAmodal").value = q.toan_bo_vat == null ? "" : q.toan_bo_vat ? "1" : "0";
  $("#qOutside").checked = !!q.nhan_ngoai_guideline;
  $("#qEdge").value = q.box_ra_ngoai_anh_px ?? 2;
  $("#qMinPx").value = q.khong_bat_buoc_duoi_px ?? "";
  $("#qMuc").value = q.muc_chung || "";
  $("#qKieu").value = ["shape", "track"].includes(q.kieu_nhan) ? q.kieu_nhan : "";
  $("#qPair").value = ["cap", "trung"].includes(q.polygon_kem_box) ? q.polygon_kem_box : "";
}
function collectRules() {
  const nhan = {};
  $$("#ruleTable tbody tr:not(.rule-empty)").forEach(tr => {
    const name = $(".in-name", tr).value.trim(); if (!name) return;
    const rmin = parseFloat($(".in-rmin", tr).value), rmax = parseFloat($(".in-rmax", tr).value);
    nhan[name] = {
      loai_tool: $(".in-tool", tr).value || undefined, dong_nghia: txt2list($(".in-syn", tr).value),
      kich_thuoc_toi_thieu_px: parseInt($(".in-min", tr).value) || 0,
      ti_le_rong_cao: isFinite(rmin) && isFinite(rmax) ? [rmin, rmax] : undefined,
      thuoc_tinh_bat_buoc: txt2list($(".in-req", tr).value), khong_de_mac_dinh: txt2list($(".in-def", tr).value),
      muc: $(".in-muc", tr).value.trim() || undefined,
    };
  });
  return { nhan, quy_tac: { ...RULE_Q, nguoi_lai_co_box_rieng: $("#qRider").checked, nhan_ngoai_guideline: $("#qOutside").checked,
    box_ra_ngoai_anh_px: parseInt($("#qEdge").value) || 0, muc_chung: $("#qMuc").value.trim() || undefined,
    khong_bat_buoc_duoi_px: parseInt($("#qMinPx").value) || undefined,
    toan_bo_vat: $("#qAmodal").value === "" ? undefined : $("#qAmodal").value === "1",
    kieu_nhan: $("#qKieu").value || undefined, polygon_kem_box: $("#qPair").value || undefined } };
}
$("#ruleAdd").onclick = () => { $("#ruleTable tbody .rule-empty")?.remove(); $("#ruleTable tbody").insertAdjacentHTML("beforeend", ruleRow("", {})); $("#ruleTable tbody tr:last-child .in-name").focus(); };
$("#ruleTable tbody").addEventListener("click", e => { if (e.target.classList.contains("rule-del")) e.target.closest("tr").remove(); });
$("#ruleSave").onclick = async () => {
  try {
    const r = await api(`/api/guidelines/${CUR_G.id}/rules`, { method: "PUT", json: { rules_obj: collectRules() } });
    $("#gRules").value = r.rules;
    $("#ruleMsg").innerHTML = r.warnings.length ? bad("Đã lưu, cần xem lại: " + r.warnings.join(" · ")) : ok(`Đã lưu ${Object.keys(r.rules_obj.nhan || {}).length} nhãn ✔`);
    loadGuides();
  } catch (err) { $("#ruleMsg").innerHTML = bad(err.message); }
};
$("#gTemplate").onclick = async () => {
  if ($$("#ruleTable tbody tr:not(.rule-empty)").length && !(await askConfirm("Thay bảng luật hiện tại bằng danh sách nhãn lấy từ task? Các giá trị đã nhập sẽ mất.", "Thay", "Lấy nhãn từ task?"))) return;
  try {
    const r = await api(`/api/guidelines/${CUR_G.id}/template`, { method: "POST", json: { task_id: $("#gTask").value, connection_id: $("#fConn").value } });
    RULE_ATTRS = r.attributes || {};
    renderRuleTable(r.rules_obj);
    const ev = r.evidence || [];
    $("#ruleMsg").textContent = `Đã lấy ${Object.keys(r.rules_obj.nhan || {}).length} nhãn từ task ${r.task_id}` +
      (ev.length ? `, tự đọc được ${ev.length} yêu cầu từ guideline (xem bên dưới). Kiểm lại rồi bấm Lưu luật.` : ". Không tìm thấy yêu cầu nào trong guideline, điền tay rồi bấm Lưu luật.");
    $("#ruleEvidence").classList.toggle("hidden", !ev.length);
    $("#ruleEvidence").innerHTML = `<h3>Tool đọc được từ guideline</h3><ul>` + ev.map(e =>
      `<li><b>${esc(e.gia_tri)}</b> <span class="meta">(${esc(e.luat)}${e.muc ? " · mục " + esc(e.muc) : ""})</span><br><q>${esc(e.trich)}</q></li>`).join("") + `</ul>`;
  } catch (err) { $("#ruleMsg").innerHTML = bad(err.message); }
};
$("#gAssign").onclick = async () => {
  try {
    await api(`/api/guidelines/${CUR_G.id}/tasks`, { method: "POST", json: { task_id: $("#gTask").value } });
    await openGuide(CUR_G.id); loadGuides(); renderJobCtx();
    $("#ruleMsg").innerHTML = ok(`Đã gán cho task ${$("#gTask").value} ✔`);
  } catch (err) { $("#ruleMsg").innerHTML = bad(err.message); }
};
function renderSections(secs, words = []) {
  const hl = s => { let h = esc(s); words.forEach(w => { if (w) h = h.replace(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), m => `<mark>${m}</mark>`); }); return h; };
  $("#gSections").innerHTML = secs.map(s => `<div class="sec"><b>${hl(s.title)}</b><div>${hl(s.body || s.snippet || "")}</div></div>`).join("") || `<p class="fl-empty">Không có kết quả.</p>`;
}
$("#gSearchBtn").onclick = async () => {
  const q = $("#gSearch").value.trim();
  if (!q) return renderSections(CUR_G.sections);
  renderSections(await api(`/api/guidelines/${CUR_G.id}/search?q=${encodeURIComponent(q)}`), q.split(",").map(x => x.trim()));
};
$("#gSearch").onkeydown = e => { if (e.key === "Enter") $("#gSearchBtn").click(); };
$("#gSave").onclick = async () => {
  try {
    const r = await api(`/api/guidelines/${CUR_G.id}/rules`, { method: "PUT", json: { rules: $("#gRules").value } });
    $("#gMsg").innerHTML = r.warnings.length ? bad("Đã lưu, cần xem lại: " + r.warnings.join(" · ")) : ok("Đã lưu ✔");
    renderRuleTable(r.rules_obj); loadGuides();
  } catch (err) { $("#gMsg").innerHTML = bad(err.message); }
};

// ============================================================ ket noi CVAT
async function loadConns() {
  await loadConfig();
  $("#connTable tbody").innerHTML = CFG.connections.map(c => `<tr data-id="${c.id}">
    <td class="strong">${esc(c.name)}${c.is_default ? ' <span class="pill pass">Mặc định</span>' : ""}</td><td>${esc(c.url)}</td><td>${esc(c.org || "—")}</td>
    <td><code>${esc(c.token_mask || "chưa có")}</code></td><td class="conn-st" id="cst${c.id}"><span class="meta">chưa kiểm tra</span></td>
    <td class="r"><div class="row-btns">
      <button class="btn sm" data-act="test">Thử</button>
      ${canQc() ? `<button class="btn sm" data-act="edit">Sửa</button>${c.is_default ? "" : '<button class="btn sm" data-act="default">Đặt mặc định</button>'}<button class="link-danger" data-act="del">Xoá</button>` : ""}
    </div></td></tr>`).join("") || `<tr><td colspan="6" class="empty-row">Chưa có kết nối nào. Bấm <b>Thêm kết nối</b> để bắt đầu.</td></tr>`;
  if (!CFG.connections.length && canQc()) openConnForm(null);
}
$("#connTable tbody").addEventListener("click", async e => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  const id = +b.closest("tr").dataset.id, c = CFG.connections.find(x => x.id === id);
  if (b.dataset.act === "test") {
    const cell = $("#cst" + id); cell.innerHTML = '<span class="meta">đang thử…</span>';
    try { const r = await api("/api/connections/test", { method: "POST", json: { id } }); cell.innerHTML = ok(`OK · ${r.username}`) + (r.version ? ` <span class="meta">CVAT ${esc(r.version)} · ${r.jobs ?? "?"} job</span>` : ""); }
    catch (err) { cell.innerHTML = bad(err.message); }
  } else if (b.dataset.act === "edit") openConnForm(c);
  else if (b.dataset.act === "default") { await api(`/api/connections/${id}/default`, { method: "POST" }); loadConns(); }
  else if (b.dataset.act === "del" && await askConfirm(`Xoá kết nối "${c.name}"? Lịch sử review vẫn giữ.`, "Xoá", "Xoá kết nối?")) { await api(`/api/connections/${id}`, { method: "DELETE" }); loadConns(); }
});
$("#connNew").onclick = () => openConnForm(null);
function openConnForm(c) {
  $("#connForm").classList.remove("hidden");
  $("#connFormTitle").textContent = c ? `Sửa kết nối: ${c.name}` : "Thêm kết nối";
  $("#cId").value = c?.id || ""; $("#cName").value = c?.name || ""; $("#cUrl").value = c?.url || ""; $("#cOrg").value = c?.org || "";
  $("#cToken").value = ""; $("#cToken").placeholder = c ? `giữ token hiện tại (${c.token_mask})` : "dán token vào đây";
  $("#cDefault").checked = !!c?.is_default; $("#cMsg").textContent = "";
  $("#connForm").scrollIntoView({ behavior: "smooth", block: "start" }); $("#cName").focus();
}
$("#cCancel").onclick = () => $("#connForm").classList.add("hidden");
$("#cTest").onclick = async () => {
  $("#cMsg").textContent = "Đang thử kết nối…";
  const id = $("#cId").value, tok = $("#cToken").value.trim();
  try {
    const r = await api("/api/connections/test", { method: "POST", json: tok || !id ? { url: $("#cUrl").value, token: tok, org: $("#cOrg").value } : { id: +id } });
    $("#orgList").innerHTML = (r.orgs || []).map(o => `<option value="${esc(o)}">`).join("");
    $("#cMsg").innerHTML = ok(`Kết nối được ✔ tài khoản ${r.username}`) + ` <span class="meta">${r.version ? "CVAT " + esc(r.version) + " · " : ""}${r.jobs ?? "?"} job thấy được${r.orgs?.length ? " · tổ chức: " + esc(r.orgs.join(", ")) : ""}</span>`;
  } catch (err) { $("#cMsg").innerHTML = bad(err.message); }
};
$("#connForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#cId").value;
  const body = { name: $("#cName").value, url: $("#cUrl").value, token: $("#cToken").value, org: $("#cOrg").value, is_default: $("#cDefault").checked };
  try {
    if (id) await api(`/api/connections/${id}`, { method: "PUT", json: body });
    else await api("/api/connections", { method: "POST", json: body });
    $("#connForm").classList.add("hidden");
    await loadConns(); refreshJobCtx();
  } catch (err) { $("#cMsg").innerHTML = bad(err.message); }
};

// ============================================================ cai dat
async function loadSettings() {
  await loadConfig();
  $("#cfgBox").innerHTML = `<dt>Máy chạy</dt><dd>${esc(CFG.device)}</dd><dt>Kết nối</dt><dd>${CFG.connections.length} kết nối CVAT</dd>
    <dt>Số job/task trong .env</dt><dd>${CFG.env_job_id ?? "—"} / ${CFG.env_task_id ?? "—"}</dd>`;
  if (ME.role !== "admin") return;
  const s = await api("/api/settings");
  $("#sThr").value = (s.pass_threshold * 100).toFixed(1).replace(/\.0$/, "");
  $("#sMode").value = s.default_mode;
  try {
    const gs = await api("/api/guidelines");
    $("#sGuide").innerHTML = `<option value="">Không dùng (chỉ so với nhãn của task)</option>` +
      gs.map(g => `<option value="${g.id}" ${s.default_guideline_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("");
  } catch (err) { $("#sGuide").innerHTML = `<option value="">(không đọc được danh sách guideline)</option>`; }
  $("#sHook").checked = s.webhook_enabled; $("#sHookPush").checked = s.webhook_auto_push;
  $("#sAuto").checked = s.auto_validation; $("#sAutoPush").checked = s.auto_push; $("#sAutoReturn").checked = s.auto_return;
  $("#sAutoConn").innerHTML = `<option value="">Kết nối mặc định</option>` + CFG.connections.map(c => `<option value="${c.id}" ${s.auto_connection_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  renderAuto(s);
  $("#sHookConn").innerHTML = `<option value="">Kết nối mặc định</option>` + CFG.connections.map(c => `<option value="${c.id}" ${s.webhook_connection_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  renderHook(s);
  loadUsers();
}
function renderAuto(s) {
  const L = s.auto_last;
  let st = "";
  if (s.auto_error) st = `<div>${bad("Lần hỏi CVAT gần nhất bị lỗi: " + s.auto_error)}</div>`;
  else if (s.auto_validation && L) st = `<div>Lần kiểm tra gần nhất ${fmtTime(L.time)} trên <b>${esc(L.connection)}</b>: ${L.jobs} job đang ở validation`
    + (L.first ? " (lần đầu: chỉ ghi nhận, không chạy job cũ)" : `, xếp ${L.started} lần review mới`) + ".</div>";
  $("#autoBox").innerHTML = s.auto_validation ? `${st}
    <div class="meta">Cứ 60 giây web hỏi CVAT một lần. Job nào vừa chuyển sang stage <b>validation</b> thì tự xếp vào hàng review, người chạy hiện là "tự động".
    Job bị trả về annotation rồi nộp lại validation sẽ được review lại. Không cần cấu hình webhook hay mạng.</div>
    <div><button type="button" class="btn sm" id="autoNow">Kiểm tra ngay</button> <span id="autoMsg" class="meta"></span></div>`
    : `<div class="meta">Bật rồi bấm Lưu cài đặt. Từ lúc bật, job nào chuyển sang validation sẽ được tự review.</div>`;
  const b = $("#autoNow");
  if (b) b.onclick = async () => {
    $("#autoMsg").textContent = "Đang hỏi CVAT…";
    try { const r = await api("/api/auto/check", { method: "POST" }); $("#autoMsg").innerHTML = ok(r.started.length ? `Đã xếp ${r.started.length} lần review` : "Không có job mới vào validation"); renderAuto({ ...s, auto_last: r.last, auto_error: null }); }
    catch (err) { $("#autoMsg").innerHTML = bad(err.message); }
  };
}
function renderHook(s) {
  $("#hookBox").innerHTML = s.webhook_enabled && s.webhook_secret ? `
    <div><b>Dán vào CVAT</b> (Project hoặc Task → Actions → Setup webhooks → Create):</div>
    <div>Target URL: <code>${esc(s.webhook_url)}</code></div>
    <div>Secret: <code>${esc(s.webhook_secret)}</code></div>
    <div>Events: chọn <code>job</code> (update). Content type: <code>application/json</code>.</div>
    <div class="meta">Máy CVAT phải truy cập được máy chủ này (chạy web_qc.bat --lan). Khi job chuyển sang "completed", web tự xếp một lần review vào hàng đợi.</div>`
    : (s.webhook_enabled ? "" : `<div class="meta">Bật webhook rồi lưu để nhận địa chỉ và secret dán vào CVAT.</div>`);
}
$("#setForm").onsubmit = async e => {
  e.preventDefault();
  try {
    const s = await api("/api/settings", { method: "PUT", json: {
      pass_threshold: (parseFloat($("#sThr").value) || 97) / 100, default_mode: $("#sMode").value,
      webhook_enabled: $("#sHook").checked, webhook_auto_push: $("#sHookPush").checked,
      webhook_connection_id: $("#sHookConn").value ? +$("#sHookConn").value : null,
      auto_validation: $("#sAuto").checked, auto_push: $("#sAutoPush").checked, auto_return: $("#sAutoReturn").checked,
      auto_connection_id: $("#sAutoConn").value ? +$("#sAutoConn").value : null,
      default_guideline_id: $("#sGuide").value ? +$("#sGuide").value : null } });
    s.webhook_url = location.origin + "/api/webhook/cvat";
    renderHook(s); renderAuto(s); $("#setMsg").innerHTML = ok("Đã lưu ✔"); await loadConfig();
  } catch (err) { $("#setMsg").innerHTML = bad(err.message); }
};
$("#pwForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try { await api("/api/password", { method: "POST", json: { old: f.get("old"), new: f.get("new") } }); $("#pwMsg").innerHTML = ok("Đã đổi ✔"); e.target.reset(); }
  catch (err) { $("#pwMsg").innerHTML = bad(err.message); }
};
async function loadUsers() {
  const us = await api("/api/users");
  $("#utable tbody").innerHTML = us.map(u => `<tr><td class="strong">${esc(u.username)}</td><td>${esc(ROLE_VI[u.role] || u.role)}</td>
    <td class="r">${u.username !== ME.username ? `<button class="link-danger" data-u="${esc(u.username)}">Xoá</button>` : '<span class="meta">bạn</span>'}</td></tr>`).join("");
}
$("#utable tbody").addEventListener("click", async e => {
  const n = e.target.dataset.u;
  if (n && await askConfirm(`Xoá tài khoản ${n}?`, "Xoá", "Xoá tài khoản?")) { await api(`/api/users/${encodeURIComponent(n)}`, { method: "DELETE" }); loadUsers(); }
});
$("#userForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/users", { method: "POST", json: { username: f.get("username"), password: f.get("password"), role: f.get("role") } });
    $("#userMsg").innerHTML = ok("Đã lưu ✔"); e.target.reset(); loadUsers();
  } catch (err) { $("#userMsg").innerHTML = bad(err.message); }
};

// ============================================================ hop xac nhan (confirm() co the bi trinh duyet chan)
function askConfirm(text, yes = "Đồng ý", title = "Xác nhận") {
  return new Promise(res => {
    $("#cfText").textContent = text; $("#cfYes").textContent = yes; $("#cfTitle").textContent = title;
    $("#confirmBox").classList.remove("hidden");
    $("#cfYes").focus();
    const done = v => { $("#confirmBox").classList.add("hidden"); $("#cfYes").onclick = $("#cfNo").onclick = null; res(v); };
    $("#cfYes").onclick = () => done(true);
    $("#cfNo").onclick = () => done(false);
  });
}
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  $("#modal").classList.add("hidden"); $("#optPop").open = false; $("#jobPicker").classList.add("hidden");
  if (!$("#confirmBox").classList.contains("hidden")) $("#cfNo").click();
});

// ============================================================ che do Phan tich
// Ve chong len anh goc: nhan cua labeler (theo ket luan), vat tool phat hien, mat duong model to, cho thieu.
const AN = { idx: 0, data: null, img: null, items: [], hover: null, pick: null, scale: 1, layers: { lab: true, tool: true, road: false, miss: true } };
const AN_COL = { dung: "#22c55e", nghi: "#f0a020", loi: "#ef4444", tool: "#22d3ee", miss: "#e879f9", road: "rgba(34,197,94,.30)", area: "#3b82f6" };
const ST_VI = { dung: "Khớp", nghi: "Nghi", loi: "Lỗi" };

function openAnalysis() {
  if (!RUN_DATA) return;
  const fr = RUN_DATA.frames || [];
  $("#anFrame").innerHTML = fr.map((f, i) => `<option value="${i}">${f.frame != null ? "F" + f.frame + " · " : ""}${esc(f.name)}${f.sure ? ` · ${f.sure} lỗi` : ""}</option>`).join("");
  if (FRAME_FILTER) { const i = fr.findIndex(f => f.name === FRAME_FILTER); if (i >= 0) AN.idx = i; }
  if (AN.idx >= fr.length) AN.idx = 0;
  loadAnalysis(AN.idx);
}
async function loadAnalysis(i) {
  const fr = RUN_DATA.frames[i]; if (!fr) return;
  AN.idx = i; AN.pick = AN.hover = null; $("#anFrame").value = i;
  $("#anPrev").disabled = i <= 0; $("#anNext").disabled = i >= RUN_DATA.frames.length - 1;
  if (!fr.analysis) {
    AN.data = null; AN.items = [];
    $("#anSum").innerHTML = `<p class="empty-note">Lần review này chạy bằng bản cũ nên chưa có dữ liệu phân tích. Bấm <b>Review lại</b> để có.</p>`;
    $("#anTable tbody").innerHTML = ""; $("#anDetail").innerHTML = "";
    const c = $("#anCanvas"); c.width = c.height = 0; return;
  }
  try {
    const [d, img] = await Promise.all([api(fr.analysis), new Promise((ok, no) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => no(new Error("Không tải được ảnh gốc")); im.src = fr.raw; })]);
    if (AN.idx !== i) return;
    AN.data = d; AN.img = img;
    buildAnItems(); renderAnSide(); drawAnalysis();
  } catch (err) { $("#anSum").innerHTML = bad(err.message); }
}
function buildAnItems() {
  const d = AN.data, items = [];
  d.labels.forEach((l, k) => items.push({ key: "l" + k, type: "lab", label: l.label, box: l.box, status: l.status, msgs: l.msgs, iou: l.iou, tool: l.match != null ? d.tool[l.match] : null, id: l.id, occluded: l.occluded }));
  d.areas.forEach((a, k) => items.push({ key: "a" + k, type: "area", label: a.label, polys: a.polys, status: a.status, msgs: a.msgs, id: a.id, kind: a.kind, road: a.road, ref_polys: a.ref_polys, ref_iou: a.ref_iou }));
  d.missing.forEach((m, k) => items.push({ key: "m" + k, type: "miss", label: m.label, box: m.box, poly: m.poly, sure: m.sure, msgs: [m.msg], kind: m.kind }));
  // vat tool thay ma labeler khong co box, va chua thanh loi "Thieu" (tool chua du chac) -> de nguoi review tu xem
  const iou = (a, b) => { const w = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])), h = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1])), i = w * h; return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i || 1); };
  d.tool.forEach((t, k) => { if (!t.matched && !d.missing.some(m => iou(m.box, t.box) > 0.5)) items.push({ key: "t" + k, type: "tool", label: t.label, box: t.box, score: t.score, sure: t.sure }); });
  AN.items = items;
}
function renderAnSide() {
  const d = AN.data, L = d.labels, cnt = s => L.filter(l => l.status === s).length + d.areas.filter(a => a.status === s).length;
  const nMiss = d.missing.length, nLab = L.length + d.areas.length, nFree = AN.items.filter(i => i.type === "tool").length;
  let road = "";
  if (d.road) {
    const r = d.road, only = Math.max(0, r.model_pct - r.both_pct), extra = Math.max(0, r.label_pct - r.both_pct);
    road = `<div class="an-road"><b>Mặt đường:</b> model thấy ${r.model_pct}% ảnh · labeler tô ${r.label_pct}% · trùng nhau ${r.both_pct}%.
      ${only > 1 ? `<span class="err">Chưa tô ~${only.toFixed(1)}% ảnh.</span>` : ""} ${extra > 1 ? `<span class="err">Tô ngoài đường ~${extra.toFixed(1)}%.</span>` : ""}
      <div class="bar" title="Xanh đậm: cả hai cùng tô · xanh nhạt: chỉ model thấy · đỏ: chỉ labeler tô">
        <i style="width:${r.both_pct}%;background:#22c55e"></i><i style="left:${r.both_pct}%;width:${only}%;background:rgba(34,197,94,.35)"></i><i style="left:${r.both_pct + only}%;width:${extra}%;background:#ef4444"></i></div></div>`;
  }
  $("#anSum").innerHTML = `<div class="an-kpis">
      <div class="an-kpi good"><div class="v">${cnt("dung")}</div><div class="k">Khớp với tool</div></div>
      <div class="an-kpi warn"><div class="v">${cnt("nghi")}</div><div class="k">Nghi, cần xem</div></div>
      <div class="an-kpi bad"><div class="v">${cnt("loi")}</div><div class="k">Lỗi</div></div>
      <div class="an-kpi bad"><div class="v">${nMiss}</div><div class="k">Thiếu</div></div>
    </div>
    <div class="meta">Labeler gán ${nLab} nhãn · tool phát hiện ${d.tool.length} vật${nFree ? ` · ${nFree} vật tool thấy nhưng chưa chắc, nên xem bằng mắt` : ""}.</div>${road}`;
  const rank = it => it.type === "miss" ? (it.sure ? 1 : 2.5) : it.type === "tool" ? 3 : { loi: 0, nghi: 2, dung: 4 }[it.status];
  const rows = [...AN.items].sort((a, b) => rank(a) - rank(b));
  $("#anTable tbody").innerHTML = rows.map((it, n) => {
    const st = it.type === "miss" ? "thieu" : it.type === "tool" ? "tool" : it.status;
    const labCell = it.type === "lab" ? `${ST_VI[it.status]}<span class="sub">box ${Math.round(it.box[2] - it.box[0])}×${Math.round(it.box[3] - it.box[1])}${it.occluded ? " · bị che" : ""}</span>`
      : it.type === "area" ? `${ST_VI[it.status]}<span class="sub">${it.kind === "mask" ? "mask" : "polygon"}</span>`
      : it.type === "miss" ? `<span class="err">Không có</span>` : `<span class="meta">Không có</span>`;
    const toolCell = it.type === "lab" ? (it.tool ? `${esc(it.tool.label)} <span class="sub">tin cậy ${Math.round(it.tool.score * 100)}%</span>` : `<span class="meta">Không thấy</span>`)
      : it.type === "area" ? (it.road ? "so với mặt đường" : it.ref_iou != null ? `mask SAM2 <span class="sub">viền nét đứt</span>` : "—")
      : it.type === "tool" ? `${esc(it.label)} <span class="sub">tin cậy ${Math.round(it.score * 100)}%${it.sure ? "" : " · thấp"}</span>`
      : `${esc(it.label)}<span class="sub">${it.sure ? "chắc chắn" : "đang xem xét"}</span>`;
    const iou = it.type === "lab" && it.tool ? Math.round(it.iou * 100) + "%" : it.type === "area" && it.ref_iou != null ? Math.round(it.ref_iou * 100) + "%" : "—";
    return `<tr data-key="${it.key}"><td>${n + 1}</td><td><span class="st ${st}"></span>${esc(it.label)}</td><td>${labCell}</td><td>${toolCell}</td><td class="r">${iou}</td></tr>`;
  }).join("") || `<tr><td colspan="5" class="empty-row">Ảnh này không có nhãn nào.</td></tr>`;
  showAnDetail(null);
}
function anDesc(it) {
  if (!it) return "";
  const head = it.type === "lab" ? `Box <b>${esc(it.label)}</b> của labeler — <b>${ST_VI[it.status]}</b>`
    : it.type === "area" ? `${it.kind === "mask" ? "Mask" : "Polygon"} <b>${esc(it.label)}</b> của labeler — <b>${ST_VI[it.status]}</b>`
    : it.type === "miss" ? `<b>Thiếu ${esc(it.label)}</b>${it.sure ? "" : " (đang xem xét)"}`
    : `Tool thấy <b>${esc(it.label)}</b> (tin cậy ${Math.round(it.score * 100)}%), labeler không có box. Tool chưa đủ chắc để báo thiếu, nên xem bằng mắt.`;
  let body = "";
  if (it.type === "area" && it.ref_iou != null) body = `<br>Viền nét đứt xanh = mask SAM2 tự tìm cho vật này, trùng ${Math.round(it.ref_iou * 100)}% với polygon của labeler. Chỗ lệch giữa 2 viền là chỗ vẽ lẹm / tô thừa.`;
  if (it.type === "lab") body = it.tool ? `<br>Tool thấy <b>${esc(it.tool.label)}</b> ở đây, tin cậy ${Math.round(it.tool.score * 100)}%, khung trùng ${Math.round(it.iou * 100)}%.` : "<br>Tool không thấy vật nào khớp với box này.";
  const msgs = (it.msgs || []).map(m => `<li>${esc(m)}</li>`).join("");
  return `${head}${body}${msgs ? `<ul style="margin:6px 0 0 16px;padding:0">${msgs}</ul>` : it.type === "lab" && it.status === "dung" ? "<br>Không có lỗi." : ""}`;
}
function showAnDetail(it) {
  $("#anDetail").innerHTML = it ? anDesc(it) : `<p class="empty-note">Bấm một dòng hoặc một vật trên ảnh để xem chi tiết.</p>`;
  $$("#anTable tr[data-key]").forEach(tr => tr.classList.toggle("on", !!it && tr.dataset.key === it.key));
}
function anPath(g, polys) {
  g.beginPath();
  polys.forEach(p => { g.moveTo(p[0], p[1]); for (let k = 2; k < p.length; k += 2) g.lineTo(p[k], p[k + 1]); g.closePath(); });
}
function drawAnalysis() {
  const c = $("#anCanvas"), d = AN.data, img = AN.img; if (!d || !img) return;
  const wrap = $("#anWrap"), W = d.W, H = d.H;
  const s = Math.min(wrap.clientWidth / W, (wrap.clientHeight || 600) / H), dpr = window.devicePixelRatio || 1;
  AN.scale = s;
  c.style.width = W * s + "px"; c.style.height = H * s + "px";
  c.width = Math.round(W * s * dpr); c.height = Math.round(H * s * dpr);
  const g = c.getContext("2d");
  g.setTransform(s * dpr, 0, 0, s * dpr, 0, 0);
  g.drawImage(img, 0, 0, W, H);
  const lw = 2 / s, focus = AN.pick || AN.hover;
  if (AN.layers.road && d.road) { anPath(g, d.road.polys); g.fillStyle = AN_COL.road; g.fill("evenodd"); }
  if (AN.layers.lab) for (const it of AN.items) if (it.type === "area") {
    anPath(g, it.polys); g.fillStyle = it.road ? "rgba(59,130,246,.16)" : "rgba(59,130,246,.10)"; g.fill("evenodd");
    g.strokeStyle = it.status === "dung" ? AN_COL.area : AN_COL[it.status]; g.lineWidth = lw; g.setLineDash([]); g.stroke();
  }
  if (AN.layers.tool) for (const it of AN.items) if (it.type === "area" && it.ref_polys) {   // mask SAM2 cua vat
    anPath(g, it.ref_polys); g.strokeStyle = AN_COL.tool; g.lineWidth = 1.5 / s; g.setLineDash([5 / s, 4 / s]); g.stroke();
  }
  g.setLineDash([]);
  if (AN.layers.tool) for (const t of d.tool) {
    const [x1, y1, x2, y2] = t.box; g.strokeStyle = AN_COL.tool; g.lineWidth = 1.5 / s; g.setLineDash([5 / s, 4 / s]); g.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }
  g.setLineDash([]);
  if (AN.layers.lab) for (const it of AN.items) if (it.type === "lab") {
    const [x1, y1, x2, y2] = it.box; g.strokeStyle = AN_COL[it.status]; g.lineWidth = lw; g.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }
  if (AN.layers.miss) for (const it of AN.items) if (it.type === "miss") {
    g.strokeStyle = AN_COL.miss; g.lineWidth = lw; g.setLineDash([6 / s, 4 / s]);
    if (it.poly) { anPath(g, [it.poly]); g.fillStyle = "rgba(232,121,249,.18)"; g.fill(); g.stroke(); }
    else { const [x1, y1, x2, y2] = it.box; g.strokeRect(x1, y1, x2 - x1, y2 - y1); }
    g.setLineDash([]);
  }
  if (focus) {                     // to dam vat dang chon / re chuot
    g.lineWidth = 4 / s; g.strokeStyle = "#ffffff"; g.setLineDash([]);
    if (focus.polys || focus.poly) { anPath(g, focus.polys || [focus.poly]); g.stroke(); }
    if (focus.ref_polys) { anPath(g, focus.ref_polys); g.strokeStyle = AN_COL.tool; g.lineWidth = 3 / s; g.setLineDash([6 / s, 4 / s]); g.stroke(); g.setLineDash([]); }
    else { const [x1, y1, x2, y2] = focus.box; g.strokeRect(x1 - 2 / s, y1 - 2 / s, x2 - x1 + 4 / s, y2 - y1 + 4 / s); }
    if (focus.tool) { const [x1, y1, x2, y2] = focus.tool.box; g.strokeStyle = AN_COL.tool; g.lineWidth = 3 / s; g.setLineDash([5 / s, 4 / s]); g.strokeRect(x1, y1, x2 - x1, y2 - y1); g.setLineDash([]); }
  }
}
function anHit(x, y) {
  const inBox = b => b && x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
  const area = b => (b[2] - b[0]) * (b[3] - b[1]);
  const vis = AN.items.filter(it => (it.type === "lab" || it.type === "area") ? AN.layers.lab : it.type === "tool" ? AN.layers.tool : AN.layers.miss);
  const boxes = vis.filter(it => it.box && !it.poly && inBox(it.box)).sort((a, b) => area(a.box) - area(b.box));
  if (boxes.length) return boxes[0];
  const g = document.createElement("canvas").getContext("2d");
  for (const it of vis) {
    const polys = it.polys || (it.poly ? [it.poly] : null);
    if (!polys) continue;
    anPath(g, polys);
    if (g.isPointInPath(x, y, "evenodd")) return it;
  }
  return null;
}
$("#anCanvas").addEventListener("mousemove", e => {
  if (!AN.data) return;
  const r = e.currentTarget.getBoundingClientRect(), x = (e.clientX - r.left) / AN.scale, y = (e.clientY - r.top) / AN.scale;
  const it = anHit(x, y), tip = $("#anTip");
  if (it !== AN.hover) { AN.hover = it; drawAnalysis(); }
  if (!it) { tip.classList.add("hidden"); return; }
  tip.innerHTML = anDesc(it); tip.classList.remove("hidden");
  const wr = $("#anWrap").getBoundingClientRect();
  let lx = e.clientX - wr.left + 14, ly = e.clientY - wr.top + 14;
  if (lx + 300 > wr.width) lx = Math.max(4, e.clientX - wr.left - 310);
  if (ly + tip.offsetHeight > wr.height) ly = Math.max(4, e.clientY - wr.top - tip.offsetHeight - 10);
  tip.style.left = lx + "px"; tip.style.top = ly + "px";
});
$("#anCanvas").addEventListener("mouseleave", () => { AN.hover = null; $("#anTip").classList.add("hidden"); drawAnalysis(); });
$("#anCanvas").addEventListener("click", () => {
  AN.pick = AN.hover; showAnDetail(AN.pick); drawAnalysis();
  const tr = AN.pick && $(`#anTable tr[data-key="${AN.pick.key}"]`); if (tr) tr.scrollIntoView({ block: "nearest" });
});
$("#anTable").addEventListener("click", e => { const tr = e.target.closest("tr[data-key]"); if (!tr) return; AN.pick = AN.items.find(i => i.key === tr.dataset.key); showAnDetail(AN.pick); drawAnalysis(); });
$("#anTable").addEventListener("mouseover", e => { const tr = e.target.closest("tr[data-key]"); if (!tr) return; const it = AN.items.find(i => i.key === tr.dataset.key); if (it !== AN.hover) { AN.hover = it; drawAnalysis(); } });
$("#anTable").addEventListener("mouseleave", () => { AN.hover = null; drawAnalysis(); });
$$(".an-layers input").forEach(cb => cb.onchange = () => { AN.layers[cb.dataset.layer] = cb.checked; drawAnalysis(); });
$("#anFrame").onchange = e => loadAnalysis(+e.target.value);
$("#anPrev").onclick = () => loadAnalysis(AN.idx - 1);
$("#anNext").onclick = () => loadAnalysis(AN.idx + 1);
window.addEventListener("resize", debounce(() => { if (VIEW === "analysis") drawAnalysis(); }, 120));

// ============================================================ chu thich khi re chuot (bieu do, o so lieu): phan tu co data-tip
document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-tip]"), tip = $("#vizTip");
  if (!el) { tip.classList.add("hidden"); return; }
  tip.innerHTML = el.dataset.tip; tip.classList.remove("hidden");
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
  tip.style.top = (r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8) + "px";
});
document.addEventListener("scroll", () => $("#vizTip").classList.add("hidden"), true);
const pct0 = p => p == null ? "—" : Math.round(p * 100) + "%";

// ============================================================ tu review khi job sang validation
const RET = { tra_ve: ["fail", "Trả về annotation"], giu: ["pass", "Chờ reviewer"], chay: ["dang_chay", "Đang review"],
  loi: ["fail", "Không trả về được"], loi_chay: ["loi", "Review lỗi"], xong: ["xong", "Đã review"] };
let AUTO = { runs: [], st: null, filter: "" };
function retOf(r) {                       // ket qua 1 lan tu review (ban cu chua luu 'returned' -> suy tu tham so + so loi)
  if (r.status === "cho" || r.status === "dang_chay") return "chay";
  if (r.status === "loi") return "loi_chay";
  if (r.returned) return r.returned;
  if (!(r.params || {}).auto_return) return "xong";
  return (r.stats?.sure || 0) > 0 ? "tra_ve" : "giu";
}
async function loadAuto() {
  let st, runs;
  try { [st, runs] = await Promise.all([api("/api/auto/status"), api("/api/runs")]); }
  catch (err) { $("#autoMsgTop").innerHTML = bad(err.message); return; }
  AUTO.st = st;
  AUTO.runs = runs.filter(r => r.source === "validation" || r.source === "webhook");
  renderAutoStatus(st);
  renderAuto();
}
function renderAutoStatus(st) {
  const p = $("#autoPill");
  p.className = "pill " + (st.enabled ? (st.error ? "fail" : "pass live") : "");
  p.textContent = st.enabled ? (st.error ? "Lỗi khi hỏi CVAT" : `Đang theo dõi · ${st.connection || "kết nối mặc định"}`) : "Đang tắt";
  const L = st.last;
  $("#autoMsgTop").innerHTML = st.error ? bad("Lần hỏi CVAT gần nhất bị lỗi: " + st.error)
    : !st.enabled ? `Chưa bật. Vào <a href="#" data-goto="settings">Cài đặt</a> → <b>Tự review khi job chuyển sang validation</b>, tick Bật rồi Lưu.`
    : L ? `Lần kiểm tra gần nhất ${fmtTime(L.time)}: ${L.jobs} job đang ở validation${L.first ? " (lần đầu chỉ ghi nhận, không chạy job cũ)" : `, xếp ${L.started} lần review mới`}. ` +
          `${st.auto_push ? "Tự đẩy lỗi chắc chắn lên CVAT" : "Không tự đẩy Issue"}${st.auto_return ? ", còn lỗi chắc chắn thì trả job về annotation" : ""}.`
    : "Đang chờ lần kiểm tra đầu tiên (tối đa 60 giây).";
  $("#autoCheckBtn").classList.toggle("hidden", !st.can_check || !st.enabled);
}
$("#autoCheckBtn").onclick = async () => {
  const b = $("#autoCheckBtn"); b.disabled = true;
  try { const r = await api("/api/auto/check", { method: "POST" }); await loadAuto(); $("#autoMsgTop").insertAdjacentHTML("afterbegin", ok(r.started.length ? `Đã xếp ${r.started.length} lần review mới. ` : "Không có job mới vào validation. ")); }
  catch (err) { $("#autoMsgTop").innerHTML = bad(err.message); }
  b.disabled = false;
};
$$("#autoFilter button").forEach(b => b.onclick = () => { $$("#autoFilter button").forEach(x => x.classList.toggle("on", x === b)); AUTO.filter = b.dataset.f; renderAuto(); });

function renderAuto() {
  const R_ = AUTO.runs, st = AUTO.st || {};
  const byJob = new Map();
  [...R_].sort((a, b) => a.id - b.id).forEach(r => { if (r.job_id == null) return; (byJob.get(r.job_id) || byJob.set(r.job_id, []).get(r.job_id)).push(r); });
  const jobs = [...byJob.entries()].map(([job, rs]) => {
    const done = rs.filter(r => r.status === "xong"), last = rs[rs.length - 1];
    return { job, rs, done, last, ret: retOf(last), rounds: done.length, returned: done.filter(r => retOf(r) === "tra_ve").length };
  }).sort((a, b) => b.last.id - a.last.id);
  const done = R_.filter(r => r.status === "xong"), ret = done.filter(r => retOf(r) === "tra_ve").length, kept = done.filter(r => retOf(r) === "giu").length;
  const issues = R_.reduce((a, r) => a + (r.pushed?.created || 0), 0);
  const secs = done.map(r => r.stats?.giay).filter(Boolean);
  const avgRounds = jobs.length ? jobs.reduce((a, j) => a + j.rounds, 0) / jobs.length : null;
  // so tren so do luong
  const n = (k, v, sub) => { const el = $(`#autoFlow em[data-n="${k}"]`); if (el) el.innerHTML = v == null ? "" : `<strong>${v}</strong>${sub ? " " + sub : ""}`; };
  n("submitted", jobs.length, "job"); n("queue", (st.waiting || 0) + (st.current ? 1 : 0), "đang chờ / chạy"); n("runs", done.length, "lần review");
  n("returned", ret, "lần"); n("kept", kept, "lần"); n("rounds", avgRounds == null ? null : avgRounds.toFixed(1), "vòng / job");
  const k = (v, label, cls = "", tip = "") => `<div class="kpi ${cls}"${tip ? ` data-tip="${esc(tip)}"` : ""}><div class="v">${v}</div><div class="k">${label}</div></div>`;
  $("#autoKpis").innerHTML =
    k(jobs.length, "Job đã tự review") +
    k(done.length, "Lần review tự động", "", "Mỗi lần annotator nộp validation là 1 lần.") +
    k(done.length ? pct0(ret / done.length) : "—", "Lần bị trả về annotation", ret / Math.max(1, done.length) > .5 ? "warn" : "", "Lần review còn lỗi chắc chắn nên job bị trả về cho annotator sửa.") +
    k(avgRounds == null ? "—" : avgRounds.toFixed(1), "Vòng review / job", "", "Số lần một job được review cho tới nay.") +
    k(issues, "Issue tự đẩy lên CVAT") +
    k(secs.length ? (secs.reduce((a, b) => a + b, 0) / secs.length / 60).toFixed(1) + "m" : "—", "Thời gian TB / lần review");
  // bang job
  const rows = jobs.filter(j => !AUTO.filter || j.ret === AUTO.filter);
  $("#autoTable tbody").innerHTML = rows.map(j => {
    const L = j.last, s = L.stats || {}, [cls, txt] = RET[j.ret] || ["", j.ret];
    const trend = j.done.map((r, i) => `<span class="rnd ${r.pct != null && r.pct >= THR() ? "ok" : "low"}" data-tip="Vòng ${i + 1} · lần #${r.id}: ${pctTxt(r.pct)} box đúng · ${r.stats?.sure ?? 0} lỗi chắc, ${r.stats?.unsure ?? 0} đang xem xét">${pct0(r.pct)}</span>`).join('<svg class="ic rnd-arrow"><use href="#i-arrow"/></svg>');
    return `<tr data-id="${L.id}"><td class="strong">${j.job}</td><td>${esc(L.task_name || (L.task_id ? "Task " + L.task_id : "—"))}</td><td>${esc(L.assignee || "—")}</td>
      <td class="r">${j.rounds}</td><td><div class="rounds">${trend || '<span class="meta">—</span>'}</div></td>
      <td class="r">${s.boxes !== undefined ? `<span class="${s.sure ? "err" : ""}">${s.sure}</span> / ${s.unsure}` : "—"}</td>
      <td class="r">${L.pushed ? L.pushed.created + (L.pushed.kept ? " +" + L.pushed.kept : "") : "—"}</td>
      <td><span class="pill ${cls}">${txt}</span></td><td class="meta">${fmtTime(L.finished || L.created)}</td></tr>`;
  }).join("") || `<tr><td colspan="9" class="empty-row">${AUTO.runs.length ? "Không có job nào với bộ lọc này." : "Chưa có lần tự review nào. Bật ở <b>Cài đặt → Tự review khi job chuyển sang validation</b>, rồi cho annotator chuyển job sang validation."}</td></tr>`;
  // cho reviewer
  const wait = jobs.filter(j => j.ret === "giu");
  $("#autoWaitList").innerHTML = wait.map(j => `<li data-id="${j.last.id}"><span class="wl-job">Job ${j.job}</span><span class="wl-who">${esc(j.last.assignee || "—")}</span>
      <span class="tag ${j.last.stats?.unsure ? "s0" : "k"}">${j.last.stats?.unsure || 0} đang xem xét</span><svg class="ic"><use href="#i-arrow"/></svg></li>`).join("")
    || `<li class="wl-empty">Không có job nào đang chờ reviewer.</li>`;
  // annotator bi tra ve
  const ppl = {};
  jobs.forEach(j => { const a = j.last.assignee || "(chưa giao)"; const p = ppl[a] || (ppl[a] = { jobs: 0, ret: 0 }); p.jobs++; p.ret += j.returned; });
  const top = Object.entries(ppl).filter(([, v]) => v.ret).sort((a, b) => b[1].ret - a[1].ret).slice(0, 8), mx = Math.max(1, ...top.map(x => x[1].ret));
  $("#autoPeople").innerHTML = top.map(([a, v]) => `<div class="bar-row" data-tip="${esc(a)}: ${v.ret} lần bị trả về trên ${v.jobs} job"><span>${esc(a)}</span><span class="bar"><i style="width:${(v.ret / mx * 100).toFixed(1)}%"></i></span><span class="n">${v.ret}</span></div>`).join("")
    || `<p class="empty-note">Chưa có job nào bị trả về.</p>`;
}
$("#autoTable tbody").addEventListener("click", e => { const tr = e.target.closest("tr[data-id]"); if (tr) openRun(+tr.dataset.id); });
$("#autoWaitList").addEventListener("click", e => { const li = e.target.closest("li[data-id]"); if (li) openRun(+li.dataset.id); });

// ============================================================ do tin cay cua tool (static/do_tin_cay.json, tao bang tao_do_tin_cay.py)
let TRUST = null, TRUST_SET = "bdd";
const COND_VI = { daytime: "Ban ngày", "dawn/dusk": "Bình minh / hoàng hôn", night: "Ban đêm", clear: "Trời quang", overcast: "U ám",
  "partly cloudy": "Có mây", rainy: "Mưa", snowy: "Tuyết" };
const SEG_VI = { "co lem vien": "Vẽ lẹm viền", "phinh ra nen": "Phình ra nền", "lech vi tri": "Lệch vị trí", "mat 1 phan vat": "Mất 1 phần vật", "ve tho (it diem)": "Vẽ thô (ít điểm)" };
$$("#trustSet button").forEach(b => b.onclick = () => { $$("#trustSet button").forEach(x => x.classList.toggle("on", x === b)); TRUST_SET = b.dataset.s; renderTrust(); });
async function loadTrust() {
  if (!TRUST) {
    try { const r = await fetch("do_tin_cay.json", { cache: "no-store" }); if (!r.ok) throw new Error(); TRUST = await r.json(); }
    catch { $("#trustHero").innerHTML = `<p class="empty-note">Chưa có số đo. Chạy <code>review_eval.py --json</code> rồi <code>web_qc/tao_do_tin_cay.py</code> để tạo <code>static/do_tin_cay.json</code>.</p>`; return; }
  }
  renderTrust();
}
// 1 thanh chong: bat chac | dang xem xet | bo lot (cung 1 mau xanh dam -> nhat, bo lot xam)
function stackBar(name, v, extra = "") {
  const a = v.chac * 100, b = v.khong_chac * 100, c = Math.max(0, 100 - a - b);
  const seg = (w, cls, t) => w > 0 ? `<i class="${cls}" style="width:${w.toFixed(2)}%" data-tip="<b>${esc(name)}</b><br>${t}: ${w.toFixed(1)}%${v.tong ? ` · ${Math.round(w * v.tong / 100)}/${v.tong} lỗi` : ""}"></i>` : "";
  return `<div class="sb-row"><span class="sb-name">${esc(name)}${extra}</span><span class="sb-bar">${seg(a, "k1", "Bắt chắc chắn")}${seg(b, "k2", "Bắt, ghi Đang xem xét")}${seg(c, "k3", "Bỏ lọt")}</span><span class="sb-val">${Math.round(a + b)}%</span></div>`;
}
function renderTrust() {
  const T = TRUST, D = T.bo_du_lieu[TRUST_SET] || Object.values(T.bo_du_lieu)[0];
  if (!D) return;
  const m = D.moi, o = D.cu;
  const delta = (nv, ov, lowerBetter = false, fmt = pct0) => {
    if (ov == null || nv == null) return "";
    const better = lowerBetter ? nv < ov : nv > ov, same = Math.abs(nv - ov) < 1e-3;
    return `<span class="delta ${same ? "" : better ? "up" : "down"}">trước: ${fmt(ov)}</span>`;
  };
  const f1 = v => v.toFixed(1);
  $("#trustHero").innerHTML = `
    <div class="hero-tile main" data-tip="Annotator mắc 100 lỗi thì tool tìm ra bao nhiêu (gồm cả lỗi ghi Đang xem xét)."><span class="hero-k">Bắt được lỗi</span><span class="hero-v">${pct0(m.bat)}</span><span class="hero-s">${pct0(m.bat_chac)} bắt chắc chắn ${delta(m.bat, o?.bat)}</span></div>
    <div class="hero-tile" data-tip="Tool ghi 100 Issue lỗi chắc chắn thì bao nhiêu cái đúng là lỗi thật."><span class="hero-k">Issue chắc chắn đúng</span><span class="hero-v">${pct0(m.issue_chac_dung)}</span><span class="hero-s">${delta(m.issue_chac_dung, o?.issue_chac_dung)}</span></div>
    <div class="hero-tile" data-tip="Review nhãn hoàn toàn đúng: cứ 100 box thì tool ghi nhầm bao nhiêu lỗi chắc chắn. Càng thấp càng tốt."><span class="hero-k">Báo nhầm / 100 box đúng</span><span class="hero-v">${f1(m.bao_nham_chac)}</span><span class="hero-s">+ ${f1(m.bao_nham_kc)} mục Đang xem xét ${delta(m.bao_nham_chac, o?.bao_nham_chac, true, f1)}</span></div>
    <div class="hero-tile" data-tip="Ảnh tool nói không có lỗi: bao nhiêu % thật sự sạch."><span class="hero-k">Tool nói "sạch" thì đúng</span><span class="hero-v">${pct0(m.sach_dung)}</span><span class="hero-s">${D.ten} · ${m.anh} ảnh · ${m.box.toLocaleString("vi-VN")} box · ${m.loi_cai} lỗi cài</span></div>`;
  // theo loai loi
  const types = Object.entries(m.theo_loai).sort((a, b) => (b[1].chac + b[1].khong_chac) - (a[1].chac + a[1].khong_chac));
  $("#trustTypeMeta").textContent = `${D.ten} · ${m.loi_cai} lỗi cài vào`;
  $("#trustTypes").innerHTML = `<div class="legend-inline"><span><i class="key k1"></i>Bắt chắc chắn</span><span><i class="key k2"></i>Bắt, ghi "Đang xem xét"</span><span><i class="key k3"></i>Bỏ lọt</span></div>` +
    types.map(([n, v]) => stackBar(n, v, ` <em>${v.tong}</em>`)).join("");
  $("#trustTypesTbl").innerHTML = `<table class="tbl"><thead><tr><th>Loại lỗi</th><th class="r">Số lỗi</th><th class="r">Bắt chắc</th><th class="r">Đang xem xét</th><th class="r">Bỏ lọt</th></tr></thead><tbody>` +
    types.map(([n, v]) => `<tr><td>${esc(n)}</td><td class="r">${v.tong}</td><td class="r">${pctTxt(v.chac)}</td><td class="r">${pctTxt(v.khong_chac)}</td><td class="r">${pctTxt(1 - v.chac - v.khong_chac)}</td></tr>`).join("") + `</tbody></table>`;
  // truoc / sau
  const rowsC = [["Bắt được lỗi", o?.bat, m.bat, 1, pct0, false], ["Issue chắc chắn đúng", o?.issue_chac_dung, m.issue_chac_dung, 1, pct0, false],
    ["Báo nhầm chắc chắn / 100 box", o?.bao_nham_chac, m.bao_nham_chac, Math.max(o?.bao_nham_chac || 0, m.bao_nham_chac, 1), f1, true]];
  $("#trustCompare").innerHTML = o ? rowsC.map(([n, a, b, mx, fmt, low]) => `<div class="pb-row"><span class="pb-name">${n}${low ? ' <em>càng thấp càng tốt</em>' : ""}</span>
      <span class="pb-bars"><span class="pb-line"><i class="k-old" style="width:${(a / mx * 100).toFixed(1)}%" data-tip="Bản cũ · ${n}: ${fmt(a)}"></i><b>${fmt(a)}</b></span>
      <span class="pb-line"><i class="k1" style="width:${(b / mx * 100).toFixed(1)}%" data-tip="Bản mới · ${n}: ${fmt(b)}"></i><b>${fmt(b)}</b></span></span></div>`).join("")
    : `<p class="empty-note">Chưa có số đo bản cũ cho bộ này.</p>`;
  // theo dieu kien
  const cond = (T.dieu_kien?.moi) || {}, condOld = (T.dieu_kien?.cu) || {};
  $("#trustCondPanel").classList.toggle("hidden", TRUST_SET !== "bdd" || !Object.keys(cond).length);
  const groups = [["Thời điểm", ["daytime", "dawn/dusk", "night"]], ["Thời tiết", ["clear", "partly cloudy", "overcast", "rainy", "snowy"]]];
  $("#trustCond").innerHTML = groups.map(([g, keys]) => `<div class="cond-col"><h3>${g}</h3>` + keys.filter(k => cond[k]).map(k => {
    const c = cond[k], co = condOld[k];
    return `<div class="cond-row" data-tip="<b>${COND_VI[k]}</b> · ${c.anh} ảnh<br>Bắt được ${pctTxt(c.bat)} (chắc chắn ${pctTxt(c.bat_chac)})<br>Báo nhầm chắc chắn ${c.bao_nham_chac.toFixed(1)} / 100 box${co ? `<br>Bản cũ: bắt ${pctTxt(co.bat)}, báo nhầm ${co.bao_nham_chac.toFixed(1)}` : ""}">
      <span class="cr-name">${COND_VI[k] || k}<em>${c.anh} ảnh</em></span>
      <span class="cr-bar"><i class="k1" style="width:${(c.bat_chac * 100).toFixed(1)}%"></i><i class="k2" style="width:${((c.bat - c.bat_chac) * 100).toFixed(1)}%"></i></span>
      <span class="cr-val">${pct0(c.bat)}</span><span class="cr-fp">${c.bao_nham_chac.toFixed(1)}<em>nhầm/100</em></span></div>`;
  }).join("") + `</div>`).join("");
  // segmentation
  const S = T.seg;
  if (S) {
    $("#trustSegMeta").textContent = `COCO val2017 · ${S.anh} ảnh · ${S.polygon} polygon người vẽ · ${S.loi_cai} lỗi cài · bắt ${pct0(S.bat)} · báo nhầm ${S.bao_nham_chac.toFixed(1)} / 100 polygon`;
    $("#trustSeg").innerHTML = Object.entries(S.theo_loai).sort((a, b) => (b[1].chac + b[1].khong_chac) - (a[1].chac + a[1].khong_chac))
      .map(([n, v]) => stackBar(SEG_VI[n] || n, v, ` <em>${v.tong}</em>`)).join("");
  }
  // e2e tren CVAT
  const E = T.e2e || {}, NAME = { bdd: "Job BDD100K: box + polygon, 10 lỗi cài", id: "Lỗi ID của track", track: "Job video gán bằng Track" };
  $("#trustE2e").innerHTML = Object.entries(E).map(([k, v]) => `<li class="${v.dat === v.tong ? "ok" : "bad"}"><svg class="ic"><use href="#i-check"/></svg>
      <div><b>${NAME[k] || k}</b><span>${v.dat}/${v.tong} kịch bản đạt${v.hieu_qua != null ? ` · % Issue đúng (annotator sửa theo) ${pct0(v.hieu_qua)}` : ""} · chạy ${v.ngay}</span>
      <small>${Object.entries(v.chi_tiet).map(([n, okv]) => `${okv ? "✓" : "✗"} ${esc(n.replace(/^E\d+_/, "").replace(/_/g, " "))}`).join(" · ")}</small></div></li>`).join("") || `<li class="wl-empty">Chưa có kết quả test trên CVAT.</li>`;
  $("#trustDate").textContent = `Số đo cập nhật ${T.ngay}. Đánh giá lại: chạy review_eval.py --json cho từng bộ rồi tao_do_tin_cay.py.`;
}

start();
