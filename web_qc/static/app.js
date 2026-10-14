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
  const m = location.hash.match(/run=(\d+)/);
  if (m) openRun(+m[1]); else if (!CFG.connections.length) showTab("conn");
}

// ============================================================ dieu huong
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", e => { const a = e.target.closest("[data-goto]"); if (a) { e.preventDefault(); showTab(a.dataset.goto); } });
function showTab(t) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach(s => s.classList.toggle("hidden", s.id !== "tab-" + t));
  ({ dash: loadDash, history: loadHistory, guide: loadGuides, conn: loadConns, settings: loadSettings })[t]?.();
}

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
    (CFG.webhook_enabled ? `<div class="st-row"><i class="dot ok"></i><span>Webhook đang bật</span></div>` : "");
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
    chips.push(JOBINFO.dimension === "3d" ? `<span class="chip bad">Job 3D · web này chỉ review 2D</span>` : `<span class="chip ok">2D · ${JOBINFO.frames ?? "?"} frame</span>`);
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
    r.guideline_name ? "Guideline " + r.guideline_name : "không dùng guideline", r.source === "webhook" ? "tự chạy qua webhook" : ""].filter(Boolean).join(" · ");
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
    <div class="kpi ${s.unsure ? "warn" : ""}"><div class="v">${s.unsure ?? 0}</div><div class="k">Không chắc, cần xem</div></div>
    <div class="kpi"><div class="v">${s.boxes ?? 0}</div><div class="k">Box trong ${s.frames ?? 0} ảnh</div></div>
    <div class="kpi"><div class="v">${sec < 90 ? Math.round(sec) + "s" : (sec / 60).toFixed(1) + "m"}</div><div class="k">Thời gian chạy · ${s.frames ? (sec / s.frames).toFixed(1) : "?"}s/ảnh</div></div>`;
  $("#runStatus").className = "pill " + (pass ? "pass" : "fail");
  $("#runStatus").textContent = pass ? "Xong · Đạt" : "Xong · Chưa đạt";
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
  if (f && !f.note && f.name === CUR_NAME) html += rect(f.box, "ov-cur");
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
}
function renderDetail(f) {
  const fb = FEEDBACK[f.id], edited = !f.note && EDITS[f.id];
  const tags = f.note
    ? `<span class="tag note">Ghi chú người review</span><span class="tag k">${esc(f.username || "")}</span>`
    : `<span class="tag s${+f.sure}">${f.sure ? "Lỗi" : "Không chắc"}</span><span class="tag k">${esc(f.kind_vi)}</span><span class="tag k">${esc(f.label)}</span>${f.tang === 1 ? '<span class="tag k">Tầng 1 · luật</span>' : '<span class="tag k">Tầng 2 · model</span>'}${edited ? '<span class="edited-badge">lời nhắn đã sửa</span>' : ""}`;
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
  try { await navigator.clipboard.writeText(url); b.classList.add("copied"); b.lastChild.textContent = "Đã copy link"; }
  catch { window.open(url, "_blank"); }
  setTimeout(() => { b.classList.remove("copied"); b.lastChild.textContent = "Link cho labeler"; }, 2500);
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
  if (v === "frames") renderFrames();
  if (v === "issues") loadIssues();
}
function renderFrames() {
  if (!RUN_DATA) return;
  $("#frameGrid").innerHTML = RUN_DATA.frames.map(fr => {
    const nn = NOTES.filter(n => n.name === fr.name).length, unsure = fr.n - fr.sure;
    return `<button type="button" class="frame-card ${fr.n || nn ? "" : "clean"}" data-name="${esc(fr.name)}">
      <img src="${fr.preview}" alt="Frame ${fr.frame ?? ""}" loading="lazy">
      <div class="fc-meta">${fr.sure ? `<span class="tag s1">${fr.sure} lỗi</span>` : ""}${unsure ? `<span class="tag s0">${unsure} không chắc</span>` : ""}${nn ? `<span class="tag note">${nn} ghi chú</span>` : ""}${fr.n || nn ? "" : '<span class="tag k">Không lỗi</span>'}<span class="fc-name" title="${esc(fr.name)}">${fr.frame != null ? "F" + fr.frame + " · " : ""}${esc(fr.name)}</span></div>
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
  if (p.resolved) parts.push(`đóng ${p.resolved} (đã có trả lời)`);
  if (p.removed) parts.push(`xoá ${p.removed} (lỗi đã hết)`);
  return parts.join(", ") + ` · ${fmtTime(p.time)} · ` + (p.unchanged ? ok("Nhãn gốc không đổi ✔") : bad("Nhãn trên CVAT đã khác lúc review (có người đang sửa job?)"));
}
$("#pushBtn").onclick = async () => {
  const ids = [...SELECTED].filter(x => !isNote(x)).map(Number), noteIds = [...SELECTED].filter(isNote).map(x => +x.slice(1));
  const summary = $("#addSummary").checked;
  if (!ids.length && !noteIds.length && !summary) { $("#pushRes").innerHTML = bad("Chưa chọn mục nào."); return; }
  const nUnsure = RUN_DATA.findings.filter(f => SELECTED.has(String(f.id)) && !f.sure).length;
  const sure = await askConfirm(`Đẩy lên job ${RUN_DATA.job_id}: ${ids.length} lỗi${nUnsure ? ` (${nUnsure} không chắc)` : ""}, ${noteIds.length} ghi chú của bạn${summary ? ", kèm 1 Issue tổng kết có link trang lỗi cho labeler" : ""}. ` +
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
    k(d.sure, `Lỗi chắc chắn · ${d.unsure} không chắc`, d.sure ? "bad" : "") +
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
      <td>${esc(r.assignee || "—")}</td><td>${esc(r.username)}${r.source === "webhook" ? ' <span class="fp-badge">tự động</span>' : ""}</td><td>${fmtTime(r.created)}</td>
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
  $("#gtable tbody").innerHTML = GUIDES.map(g => `<tr data-id="${g.id}"><td class="strong">${esc(g.name)}</td><td>${esc(g.file_name)}</td>
    <td>${g.tasks.length ? g.tasks.join(", ") : '<span class="meta">chưa gán</span>'}</td>
    <td>${g.n_labels ? `<span class="pill pass">${g.n_labels} nhãn</span>` : '<span class="pill">Chưa có luật</span>'}${g.warnings?.length ? ' <span class="pill fail" title="' + esc(g.warnings.join(" · ")) + '">cần xem lại</span>' : ""}</td>
    <td class="r">${canQc() ? `<button class="link-danger" data-del="${g.id}">Xoá</button>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5" class="empty-row">Chưa có guideline nào. Tải file lên ở trên.</td></tr>`;
}
$("#gtable tbody").addEventListener("click", async e => {
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

async function openGuide(id) {
  const g = await api(`/api/guidelines/${id}`);
  CUR_G = g; RULE_ATTRS = {};
  $("#gDetail").classList.remove("hidden");
  $("#gName").textContent = g.name;
  $("#gFile").href = `/api/guidelines/${id}/file`;
  $("#gTasks").textContent = g.tasks.length ? `Đang gán cho task ${g.tasks.join(", ")}: review các task này sẽ tự dùng guideline này.` : "Chưa gán cho task nào: nhập số task ở dưới rồi bấm Gán.";
  $("#gTask").value = $("#gTask").value || $("#fTask").value || CFG.env_task_id || "";
  $("#gRules").value = g.rules;
  $("#ruleMsg").innerHTML = g.warnings?.length ? bad("Cần xem lại: " + g.warnings.join(" · ")) : "";
  $("#gMsg").textContent = "";
  renderRuleTable(g.rules_obj || {});
  renderSections(g.sections);
  const ro = !canQc();
  ["#gRules", "#gSave", "#gTemplate", "#gAssign", "#ruleAdd", "#ruleSave"].forEach(s => $(s).disabled = ro);
  setGTab("rules");
  $("#gDetail").scrollIntoView({ behavior: "smooth", block: "start" });
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
function renderRuleTable(obj) {
  const nhan = obj.nhan || {}, q = obj.quy_tac || {};
  $("#ruleTable tbody").innerHTML = Object.entries(nhan).map(([n, sp]) => ruleRow(n, sp || {})).join("")
    || `<tr class="rule-empty"><td colspan="9" class="empty-row">Chưa có nhãn nào. Nhập số task rồi bấm <b>Lấy nhãn từ task</b>, hoặc bấm <b>Thêm nhãn</b>.</td></tr>`;
  $("#qRider").checked = q.nguoi_lai_co_box_rieng ?? true;
  $("#qOutside").checked = !!q.nhan_ngoai_guideline;
  $("#qEdge").value = q.box_ra_ngoai_anh_px ?? 2;
  $("#qMuc").value = q.muc_chung || "";
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
  return { nhan, quy_tac: { nguoi_lai_co_box_rieng: $("#qRider").checked, nhan_ngoai_guideline: $("#qOutside").checked,
    box_ra_ngoai_anh_px: parseInt($("#qEdge").value) || 0, muc_chung: $("#qMuc").value.trim() || undefined } };
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
    $("#ruleMsg").textContent = `Đã lấy ${Object.keys(r.rules_obj.nhan || {}).length} nhãn từ task ${r.task_id}. Điền giá trị theo guideline rồi bấm Lưu luật. Gợi ý thuộc tính hiện mờ trong ô.`;
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
  $("#sHook").checked = s.webhook_enabled; $("#sHookPush").checked = s.webhook_auto_push;
  $("#sHookConn").innerHTML = `<option value="">Kết nối mặc định</option>` + CFG.connections.map(c => `<option value="${c.id}" ${s.webhook_connection_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  renderHook(s);
  loadUsers();
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
      webhook_connection_id: $("#sHookConn").value ? +$("#sHookConn").value : null } });
    s.webhook_url = location.origin + "/api/webhook/cvat";
    renderHook(s); $("#setMsg").innerHTML = ok("Đã lưu ✔"); await loadConfig();
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

start();
