// Web QC nhan 2D — giao dien (JS thuan, khong can build)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = { cho: "Đang chờ", dang_chay: "Đang chạy", xong: "Xong", loi: "Lỗi" };
const ROLE_VI = { labeler: "Labeler", qc: "QC", admin: "Admin" };
const PASS = 0.97;
const fmtTime = t => t ? new Date(t * 1000).toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";

let ME = null, CFG = null, RUN = null, RUN_DATA = null, POLL = null, CUR_G = null, CUR_F = null;
const SELECTED = new Set();

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
  $("#gUpload").closest(".panel").classList.toggle("hidden", ME.role === "labeler");
  await loadConfig();
  await loadGuideOptions();
  const m = location.hash.match(/run=(\d+)/);
  if (m) openRun(+m[1]);
}

// ============================================================ dieu huong
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", e => { const a = e.target.closest("[data-goto]"); if (a) { e.preventDefault(); showTab(a.dataset.goto); } });
function showTab(t) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach(s => s.classList.toggle("hidden", s.id !== "tab-" + t));
  if (t === "history") loadHistory();
  if (t === "guide") loadGuides();
  if (t === "settings") loadSettings();
}

// ============================================================ cau hinh
async function loadConfig() {
  CFG = await api("/api/config");
  const f = $("#runForm");
  if (!f.job_id.value) f.job_id.value = CFG.job_id ?? "";
  if (!f.task_id.value) f.task_id.value = CFG.task_id ?? "";
  const host = (CFG.cvat_url || "").replace(/^https?:\/\//, "") || "chưa cấu hình";
  const gpu = CFG.device.startsWith("GPU");
  $("#cvatInfo").innerHTML =
    `<div class="st-row" title="${esc(CFG.cvat_url)}"><i class="dot ${CFG.cvat_url ? "ok" : "no"}"></i><span>${esc(host)}</span></div>` +
    `<div class="st-row"><i class="dot ${CFG.has_token ? "ok" : "no"}"></i><span>${CFG.has_token ? "Đã có token" : "Chưa có token"}</span></div>` +
    `<div class="st-row" title="${esc(CFG.device)}"><i class="dot ${gpu ? "ok" : "no"}"></i><span>${gpu ? esc(CFG.device.replace(/^GPU \((.*)\)$/, "$1")) : "CPU (chậm)"}</span></div>`;
}

async function loadGuideOptions() {
  const gs = await api("/api/guidelines");
  const sel = $("#runGuide"), cur = sel.value;
  sel.innerHTML = `<option value="">Không dùng</option>` + gs.map(g => `<option value="${g.id}">${esc(g.name)}${g.has_rules ? "" : " · chưa có luật"}</option>`).join("");
  const tid = +$("#runForm").task_id.value;
  const auto = gs.find(g => g.tasks.includes(tid));
  sel.value = cur || (auto ? auto.id : "");
}
$("#runForm").task_id.addEventListener("change", loadGuideOptions);

// ============================================================ chay review
$("#runForm").onsubmit = async e => {
  e.preventDefault();
  const f = e.target, fd = new FormData();
  ["job_id", "task_id", "guideline_id", "mode", "max_frames"].forEach(k => fd.append(k, f[k].value));
  fd.append("rider", f.rider.checked ? "1" : "0");
  fd.append("auto_push", f.auto_push.checked ? "1" : "0");
  if (f.file.files[0]) fd.append("file", f.file.files[0]);
  $("#runErr").textContent = "";
  $("#optPop").open = false;
  try {
    const r = await api("/api/runs", { method: "POST", body: fd });
    openRun(r.id);
  } catch (err) { $("#runErr").textContent = err.message; }
};
document.addEventListener("click", e => { const p = $("#optPop"); if (p.open && !p.contains(e.target)) p.open = false; });

function openRun(id) {
  showTab("review");
  RUN = id; RUN_DATA = null; CUR_F = null; SELECTED.clear();
  location.hash = "run=" + id;
  $("#runEmpty").classList.add("hidden");
  $("#runPanel").classList.remove("hidden");
  $("#runResult").classList.add("hidden");
  $("#stats").innerHTML = "";
  $("#logBox").open = true;
  $("#runProgress").style.width = "0";
  $("#runProgress").className = "progress-bar";
  $("#pushRes").textContent = "";
  clearInterval(POLL);
  poll();
  POLL = setInterval(poll, 2000);
}

async function poll() {
  const id = RUN;
  let r;
  try { r = await api(`/api/runs/${id}`); } catch { return; }
  if (id !== RUN) return;
  $("#runTitle").textContent = `Lần review #${r.id} · ${r.job_id ? "Job " + r.job_id : "file tải lên"}${r.task_id ? " · Task " + r.task_id : ""}`;
  $("#skipped").textContent = `${r.username || ""} · ${fmtTime(r.created)}`;
  const m = [...(r.log || []).join("\n").matchAll(/\[(\d+)\/(\d+)\]/g)].pop();
  const pct = r.status === "xong" ? 100 : m ? 100 * m[1] / m[2] : r.status === "dang_chay" ? 4 : 0;
  const bar = $("#runProgress");
  bar.style.width = pct + "%";
  bar.className = "progress-bar" + (r.status === "xong" ? " done" : r.status === "loi" ? " fail" : "");
  const st = $("#runStatus");
  st.className = "pill " + r.status;
  st.textContent = STATUS[r.status] + (r.status === "cho" && r.position ? ` · thứ ${r.position} trong hàng đợi`
    : r.status === "dang_chay" && m ? ` · ảnh ${m[1]}/${m[2]}` : "");
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
function showResult(r) {
  RUN_DATA = r;
  $("#runResult").classList.remove("hidden");
  const s = r.stats || {}, pct = s.boxes ? s.ok / s.boxes : 0, pass = pct >= PASS, sec = s.giay || 0;
  $("#stats").innerHTML = `
    <div class="kpi main-k"><div class="v">${(pct * 100).toFixed(1)}%<span class="pill ${pass ? "pass" : "fail"}">${pass ? "Đạt" : "Chưa đạt"}</span></div><div class="k">Box không có lỗi chắc chắn · ngưỡng ${PASS * 100}%</div></div>
    <div class="kpi ${s.sure ? "bad" : ""}"><div class="v">${s.sure ?? 0}</div><div class="k">Lỗi chắc chắn</div></div>
    <div class="kpi ${s.unsure ? "warn" : ""}"><div class="v">${s.unsure ?? 0}</div><div class="k">Không chắc, cần xem</div></div>
    <div class="kpi"><div class="v">${s.boxes ?? 0}</div><div class="k">Box trong ${s.frames ?? 0} ảnh</div></div>
    <div class="kpi"><div class="v">${sec < 90 ? Math.round(sec) + "s" : (sec / 60).toFixed(1) + "m"}</div><div class="k">Thời gian chạy</div></div>`;
  $("#runStatus").className = "pill " + (pass ? "pass" : "fail");
  $("#runStatus").textContent = pass ? "Xong · Đạt" : "Xong · Chưa đạt";
  const extra = [r.guideline_name ? `Guideline: ${r.guideline_name}` : "Không dùng guideline",
    r.skipped_labels?.length ? `Tool không đánh giá được nhãn: ${r.skipped_labels.join(", ")}` : ""].filter(Boolean).join(" · ");
  $("#skipped").textContent = `${r.username || ""} · ${fmtTime(r.created)} · ${extra}`;
  const kinds = [...new Set(r.findings.map(f => f.kind_vi))];
  $("#fKind").innerHTML = `<option value="">Mọi loại lỗi</option>` + kinds.map(k => `<option>${esc(k)}</option>`).join("");
  $("#cAll").textContent = r.findings.length;
  $("#cSure").textContent = r.findings.filter(f => f.sure).length;
  $("#cUnsure").textContent = r.findings.filter(f => !f.sure).length;
  SELECTED.clear();
  r.findings.forEach(f => { if (f.sure) SELECTED.add(f.id); });   // mac dinh: chon loi chac; "khong chac" de nguoi QC duyet
  $("#csv").href = `/api/runs/${r.id}/report.csv`;
  $("#pushBtn").disabled = !r.job_id;
  $("#pushRes").innerHTML = r.pushed ? pushedText(r.pushed)
    : r.job_id ? "" : "Review từ file nên không đẩy Issue được. Chạy lại theo số job để đẩy.";
  renderList();
  const first = filtered()[0];
  if (first) select(first.id); else { $("#pvBox").innerHTML = `<div class="viewer-empty">Không có lỗi nào. Job đạt yêu cầu.</div>`; $("#detail").innerHTML = ""; $("#gRef").innerHTML = ""; }
}

function filtered() {
  const k = $("#fKind").value, s = $("#fSure").value, t = $("#fTang").value;
  return RUN_DATA.findings.filter(f => (!k || f.kind_vi === k) && (!s || String(+f.sure) === s) && (!t || String(f.tang) === t));
}
["#fKind", "#fTang"].forEach(s => $(s).onchange = renderList);
$$("#segSure button").forEach(b => b.onclick = () => {
  $$("#segSure button").forEach(x => x.classList.toggle("on", x === b));
  $("#fSure").value = b.dataset.v; renderList();
});

function renderList() {
  const rows = filtered();
  $("#flist").innerHTML = rows.map(f => `
    <li class="fi s${+f.sure}${f.id === CUR_F ? " cur" : ""}" data-id="${f.id}">
      <input type="checkbox" aria-label="Chọn lỗi ${f.id + 1}" ${SELECTED.has(f.id) ? "checked" : ""}>
      <div>
        <div class="fi-top"><span class="fi-kind">${esc(f.kind_vi)}</span><span class="fi-lab">${esc(f.label)}</span>${f.tang === 1 ? '<span class="fi-tier">luật</span>' : ""}<span class="fi-frame">${f.frame != null ? "F" + f.frame : "#" + (f.id + 1)}</span></div>
        <div class="fi-msg">${esc(f.msg)}</div>
      </div>
    </li>`).join("") || `<li class="fl-empty">Không có lỗi nào với bộ lọc này.</li>`;
  updatePush();
}

$("#flist").addEventListener("click", e => {
  const li = e.target.closest("li[data-id]");
  if (!li) return;
  const id = +li.dataset.id;
  if (e.target.type === "checkbox") { e.target.checked ? SELECTED.add(id) : SELECTED.delete(id); return updatePush(); }
  select(id);
});

function select(id) {
  CUR_F = id;
  $$("#flist .fi.cur").forEach(x => x.classList.remove("cur"));
  const li = $(`#flist li[data-id="${id}"]`);
  if (li) { li.classList.add("cur"); li.scrollIntoView({ block: "nearest" }); }
  showFinding(RUN_DATA.findings[id]);
}

// phim tat: len/xuong chuyen loi, Space chon/bo
document.addEventListener("keydown", e => {
  if (!RUN_DATA || $("#tab-review").classList.contains("hidden") || !$("#confirmBox").classList.contains("hidden")) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  const rows = filtered(); if (!rows.length) return;
  const i = Math.max(0, rows.findIndex(f => f.id === CUR_F));
  if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); select(rows[Math.min(rows.length - 1, i + 1)].id); }
  else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); select(rows[Math.max(0, i - 1)].id); }
  else if (e.key === " " && CUR_F != null) {
    e.preventDefault();
    SELECTED.has(CUR_F) ? SELECTED.delete(CUR_F) : SELECTED.add(CUR_F);
    const cb = $(`#flist li[data-id="${CUR_F}"] input`); if (cb) cb.checked = SELECTED.has(CUR_F);
    updatePush();
  }
});

function showFinding(f) {
  $("#pvBox").innerHTML = f.preview
    ? `<img src="/api/runs/${RUN}/preview/${encodeURIComponent(f.preview)}" alt="Ảnh frame ${f.frame ?? ""} có vẽ lỗi" title="Bấm để phóng to">`
    : `<div class="viewer-empty">Không có ảnh xem trước cho lỗi này.</div>`;
  $("#detail").innerHTML = `
    <div class="detail-head"><span class="tag s${+f.sure}">${f.sure ? "Lỗi" : "Không chắc"}</span><span class="tag k">${esc(f.kind_vi)}</span><span class="tag k">${esc(f.label)}</span>${f.tang === 1 ? '<span class="tag k">Tầng 1 · luật</span>' : ""}</div>
    <div class="detail-msg">${esc(f.msg)}</div>
    <div class="detail-meta">${f.frame != null ? "frame " + f.frame + " · " : ""}${esc(f.name)} · box [${f.box.join(", ")}]${f.ref ? " · " + esc(f.ref) : ""}</div>`;
  const refs = RUN_DATA.guideline_refs?.[f.label] || [];
  $("#gRef").innerHTML = RUN_DATA.guideline_name
    ? `<h3>Guideline nói gì về "${esc(f.label)}"</h3>` + (refs.length
      ? refs.map(x => `<div class="gref"><b>${esc(x.title)}</b>${esc(x.snippet)}</div>`).join("")
      : `<p class="meta">Không tìm thấy đoạn nào nhắc tới nhãn này. Thêm tên gọi khác vào <code>dong_nghia</code> trong file luật.</p>`)
    : "";
}
$("#pvBox").addEventListener("click", e => { if (e.target.tagName === "IMG") { $("#modalImg").src = e.target.src; $("#modal").classList.remove("hidden"); } });
$("#modal").onclick = () => $("#modal").classList.add("hidden");

$("#selSure").onclick = () => { SELECTED.clear(); RUN_DATA.findings.forEach(f => f.sure && SELECTED.add(f.id)); renderList(); };
$("#selAll").onclick = () => { filtered().forEach(f => SELECTED.add(f.id)); renderList(); };
$("#selNone").onclick = () => { filtered().forEach(f => SELECTED.delete(f.id)); renderList(); };
function updatePush() {
  $("#pushLabel").textContent = SELECTED.size ? `Đẩy ${SELECTED.size} Issue lên CVAT` : "Đẩy Issue lên CVAT";
  if (RUN_DATA) $("#selInfo").textContent = `Đã chọn ${SELECTED.size} / ${RUN_DATA.findings.length}`;
}

function pushedText(p) {
  return `Đã đẩy <b>${p.created}</b> Issue${p.removed ? `, xoá ${p.removed} Issue tự động cũ` : ""} lúc ${fmtTime(p.time)} · ` +
    (p.unchanged ? `<span class="ok-text">Nhãn gốc không đổi ✔</span>` : `<span class="err">Nhãn trên CVAT đã khác lúc review (có người đang sửa job?)</span>`);
}

$("#pushBtn").onclick = async () => {
  if (!SELECTED.size) { $("#pushRes").innerHTML = `<span class="err">Chưa chọn lỗi nào.</span>`; return; }
  const nUnsure = RUN_DATA.findings.filter(f => SELECTED.has(f.id) && !f.sure).length;
  const ok = await askConfirm(`Tạo ${SELECTED.size} Issue trên job ${RUN_DATA.job_id}${nUnsure ? `, trong đó ${nUnsure} lỗi "không chắc"` : ""}. Tool chỉ tạo Issue, không sửa nhãn.`, "Đẩy Issue", "Đẩy Issue lên CVAT?");
  if (!ok) return;
  const b = $("#pushBtn"); b.disabled = true; $("#pushRes").textContent = "Đang đẩy…";
  try {
    const p = await api(`/api/runs/${RUN}/push`, { method: "POST", json: { ids: [...SELECTED], replace_old: $("#replaceOld").checked } });
    $("#pushRes").innerHTML = pushedText(p);
  } catch (err) { $("#pushRes").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  b.disabled = false;
};

// ============================================================ lich su
async function loadHistory() {
  const rs = await api("/api/runs" + ($("#hJob").value ? `?job_id=${encodeURIComponent($("#hJob").value)}` : ""));
  $("#htable tbody").innerHTML = rs.map(r => {
    const s = r.stats || {}, pct = s.boxes ? s.ok / s.boxes : null;
    const st = r.status === "xong" && pct != null ? (pct >= PASS ? ["pass", "Đạt"] : ["fail", "Chưa đạt"]) : [r.status, STATUS[r.status] + (r.position ? " · thứ " + r.position : "")];
    return `<tr data-id="${r.id}"><td class="strong">#${r.id}</td><td>${r.job_id ?? "file"}</td><td>${r.task_id ?? "—"}</td><td>${esc(r.username)}</td>
      <td>${fmtTime(r.created)}</td><td><span class="pill ${st[0]}">${st[1]}</span></td>
      <td class="r">${pct != null ? (pct * 100).toFixed(1) + "%" : "—"}</td><td class="r">${s.boxes !== undefined ? `${s.sure} / ${s.unsure}` : "—"}</td>
      <td class="r">${r.pushed ? r.pushed.created + " Issue" : "—"}</td></tr>`;
  }).join("") || `<tr><td colspan="9" class="empty-row">Chưa có lần review nào.</td></tr>`;
}
$("#hJob").oninput = () => loadHistory();
$("#htable tbody").addEventListener("click", e => { const tr = e.target.closest("tr[data-id]"); if (tr) openRun(+tr.dataset.id); });

// ============================================================ guideline
async function loadGuides() {
  const gs = await api("/api/guidelines");
  const canEdit = ME.role !== "labeler";
  $("#gtable tbody").innerHTML = gs.map(g => `<tr data-id="${g.id}"><td class="strong">${esc(g.name)}</td><td>${esc(g.file_name)}</td>
    <td>${g.tasks.length ? g.tasks.join(", ") : "—"}</td><td>${g.has_rules ? '<span class="pill pass">Có</span>' : '<span class="pill">Chưa có</span>'}</td>
    <td class="r">${canEdit ? `<button class="link-danger" data-del="${g.id}">Xoá</button>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5" class="empty-row">Chưa có guideline nào. Tải file lên ở trên.</td></tr>`;
}
$("#gtable tbody").addEventListener("click", async e => {
  if (e.target.dataset.del) {
    e.stopPropagation();
    if (await askConfirm("Xoá guideline này? File gốc và file luật sẽ bị xoá.", "Xoá", "Xoá guideline?")) {
      await api(`/api/guidelines/${e.target.dataset.del}`, { method: "DELETE" }); loadGuides(); loadGuideOptions(); $("#gDetail").classList.add("hidden");
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
    await loadGuides(); await loadGuideOptions(); openGuide(r.id);
  } catch (err) { $("#gUpErr").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};

async function openGuide(id) {
  const g = await api(`/api/guidelines/${id}`);
  CUR_G = g;
  $("#gDetail").classList.remove("hidden");
  $("#gName").textContent = g.name;
  $("#gFile").href = `/api/guidelines/${id}/file`;
  $("#gRules").value = g.rules;
  $("#gTask").value = $("#gTask").value || CFG.task_id || "";
  $("#gTasks").textContent = g.tasks.length ? `Đang gán cho task ${g.tasks.join(", ")}. Review các task này sẽ tự chọn guideline này.` : "Chưa gán cho task nào.";
  $("#gMsg").textContent = "";
  const ro = ME.role === "labeler";
  ["#gRules", "#gSave", "#gTemplate", "#gAssign"].forEach(s => $(s).disabled = ro);
  renderSections(g.sections);
  $("#gDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderSections(secs, words = []) {
  const hl = s => { let h = esc(s); words.forEach(w => { if (w) h = h.replace(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), m => `<mark>${m}</mark>`); }); return h; };
  $("#gSections").innerHTML = secs.map(s => `<div class="sec"><b>${hl(s.title)}</b><div>${hl(s.body || s.snippet || "")}</div></div>`).join("")
    || `<p class="fl-empty">Không có kết quả.</p>`;
}
$("#gSearchBtn").onclick = async () => {
  const q = $("#gSearch").value.trim();
  if (!q) return renderSections(CUR_G.sections);
  const res = await api(`/api/guidelines/${CUR_G.id}/search?q=${encodeURIComponent(q)}`);
  renderSections(res, q.split(",").map(x => x.trim()));
};
$("#gSearch").onkeydown = e => { if (e.key === "Enter") $("#gSearchBtn").click(); };
$("#gSave").onclick = async () => {
  try {
    const r = await api(`/api/guidelines/${CUR_G.id}/rules`, { method: "PUT", json: { rules: $("#gRules").value } });
    $("#gMsg").innerHTML = r.warnings.length ? `<span class="err">Đã lưu, cần xem lại: ${esc(r.warnings.join(" · "))}</span>` : `<span class="ok-text">Đã lưu ✔</span>`;
    loadGuides(); loadGuideOptions();
  } catch (err) { $("#gMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
$("#gTemplate").onclick = async () => {
  if ($("#gRules").value.trim() && !(await askConfirm("Thay nội dung file luật hiện tại bằng mẫu mới?", "Thay", "Tạo mẫu mới?"))) return;
  try {
    const r = await api(`/api/guidelines/${CUR_G.id}/template`, { method: "POST", json: { task_id: $("#gTask").value } });
    $("#gRules").value = r.rules; $("#gMsg").textContent = "Đã tạo mẫu từ nhãn của task. Sửa giá trị theo guideline rồi bấm Lưu.";
  } catch (err) { $("#gMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
$("#gAssign").onclick = async () => {
  try {
    await api(`/api/guidelines/${CUR_G.id}/tasks`, { method: "POST", json: { task_id: $("#gTask").value } });
    openGuide(CUR_G.id); loadGuides(); loadGuideOptions();
  } catch (err) { $("#gMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};

// ============================================================ cai dat
async function loadSettings() {
  await loadConfig();
  $("#cfgBox").innerHTML = `<dt>CVAT_URL</dt><dd>${esc(CFG.cvat_url || "—")}</dd>
    <dt>CVAT_TOKEN</dt><dd>${CFG.has_token ? "đã có (ẩn)" : '<span class="err">chưa có</span>'}</dd>
    <dt>CVAT_TASK_ID</dt><dd>${CFG.task_id ?? "—"}</dd>
    <dt>CVAT_JOB_ID</dt><dd>${CFG.job_id ?? "—"}</dd>
    <dt>Máy chạy</dt><dd>${esc(CFG.device)}</dd>`;
  $("#testCvat").disabled = ME.role === "labeler";
  if (ME.role === "admin") loadUsers();
}
$("#testCvat").onclick = async () => {
  $("#testRes").textContent = "Đang kiểm tra…";
  try {
    const r = await api("/api/cvat/test");
    $("#testRes").innerHTML = `<span class="ok-text">Kết nối được ✔</span> tài khoản <b>${esc(r.username)}</b>` +
      (r.job_id ? ` · job ${r.job_id} thuộc task ${r.job_task}, trạng thái ${esc(r.job_state)} / ${esc(r.job_stage)}` +
        (r.task_match ? "" : ` · <span class="err">CVAT_TASK_ID trong .env không khớp</span>`) : "");
  } catch (err) { $("#testRes").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
$("#pwForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try { await api("/api/password", { method: "POST", json: { old: f.get("old"), new: f.get("new") } }); $("#pwMsg").innerHTML = `<span class="ok-text">Đã đổi ✔</span>`; e.target.reset(); }
  catch (err) { $("#pwMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
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
    $("#userMsg").innerHTML = `<span class="ok-text">Đã lưu ✔</span>`; e.target.reset(); loadUsers();
  } catch (err) { $("#userMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
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
  if (e.key === "Escape") { $("#modal").classList.add("hidden"); $("#optPop").open = false; if (!$("#confirmBox").classList.contains("hidden")) $("#cfNo").click(); }
});

start();
