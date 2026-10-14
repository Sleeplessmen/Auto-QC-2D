// Web QC nhan 2D — giao dien (JS thuan, khong can build)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = { cho: "Đang chờ", dang_chay: "Đang chạy", xong: "Xong", loi: "Lỗi" };
const fmtTime = t => t ? new Date(t * 1000).toLocaleString("vi-VN") : "";
const ROLE_VI = { labeler: "labeler", qc: "QC", admin: "admin" };
const PASS = 0.97;

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

// ------------------------------------------------------------ dang nhap
function showLogin() {
  $("#login").classList.remove("hidden"); $("#app").classList.add("hidden");
  fetch("/api/setup").then(r => r.json()).then(s => {
    const h = $("#loginHint");
    if (s.first_run) {
      h.innerHTML = `<b>Lần đầu dùng?</b> Đăng nhập bằng tài khoản <code>admin</code>. Mật khẩu nằm trong file <code>${esc(s.admin_file)}</code> trên máy chủ. Đăng nhập xong vào Cài đặt đổi mật khẩu rồi xoá file đó.`;
      h.classList.remove("hidden");
    } else h.classList.add("hidden");
  }).catch(() => {});
  $("#lgUser").focus();
}
$("#loginForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/login", { method: "POST", json: { username: f.get("username"), password: f.get("password") } });
    $("#loginErr").textContent = ""; start();
  } catch (err) { $("#loginErr").textContent = err.message; }
};
$("#logout").onclick = async () => { await api("/api/logout", { method: "POST" }); location.reload(); };

async function start() {
  try { ME = await api("/api/me"); } catch { return showLogin(); }
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#whoName").textContent = `${ME.username} · ${ROLE_VI[ME.role] || ME.role}`;
  $("#usersCard").classList.toggle("hidden", ME.role !== "admin");
  $("#gUpload").classList.toggle("hidden", ME.role === "labeler");
  await loadConfig();
  await loadGuideOptions();
  const m = location.hash.match(/run=(\d+)/);
  if (m) openRun(+m[1]);
}

// ------------------------------------------------------------ tab
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(t) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach(s => s.classList.toggle("hidden", s.id !== "tab-" + t));
  if (t === "history") loadHistory();
  if (t === "guide") loadGuides();
  if (t === "settings") loadSettings();
}

// ------------------------------------------------------------ cau hinh
async function loadConfig() {
  CFG = await api("/api/config");
  const f = $("#runForm");
  if (!f.job_id.value) f.job_id.value = CFG.job_id ?? "";
  if (!f.task_id.value) f.task_id.value = CFG.task_id ?? "";
  const host = (CFG.cvat_url || "").replace(/^https?:\/\//, "") || "chưa cấu hình";
  $("#cvatInfo").innerHTML = `<span class="cfg-line"><span class="chip" title="${esc(CFG.cvat_url)}">CVAT: ${esc(host)}</span>` +
    `<span class="chip ${CFG.has_token ? "ok" : "no"}">${CFG.has_token ? "Có token" : "Chưa có token"}</span>` +
    `<span class="chip" title="${esc(CFG.device)}">${CFG.device.startsWith("GPU") ? "GPU" : "CPU (chậm)"}</span></span>`;
}

async function loadGuideOptions() {
  const gs = await api("/api/guidelines");
  const sel = $("#runGuide"), cur = sel.value;
  sel.innerHTML = `<option value="">— không dùng —</option>` + gs.map(g => `<option value="${g.id}">${esc(g.name)}${g.has_rules ? "" : " (chưa có luật)"}</option>`).join("");
  const tid = +$("#runForm").task_id.value;
  const auto = gs.find(g => g.tasks.includes(tid));
  sel.value = cur || (auto ? auto.id : "");
}
$("#runForm").task_id.addEventListener("change", loadGuideOptions);

// ------------------------------------------------------------ review
$("#runForm").onsubmit = async e => {
  e.preventDefault();
  const f = e.target, fd = new FormData();
  ["job_id", "task_id", "guideline_id", "mode", "max_frames"].forEach(k => fd.append(k, f[k].value));
  fd.append("rider", f.rider.checked ? "1" : "0");
  fd.append("auto_push", f.auto_push.checked ? "1" : "0");
  if (f.file.files[0]) fd.append("file", f.file.files[0]);
  $("#runErr").textContent = "";
  try {
    const r = await api("/api/runs", { method: "POST", body: fd });
    openRun(r.id);
  } catch (err) { $("#runErr").textContent = err.message; }
};

function openRun(id) {
  showTab("review");
  RUN = id; RUN_DATA = null; SELECTED.clear();
  location.hash = "run=" + id;
  $("#runEmpty").classList.add("hidden");
  $("#runPanel").classList.remove("hidden");
  $("#runResult").classList.add("hidden");
  $("#logBox").open = true;
  $("#runProgress").style.width = "0";
  $("#runProgress").className = "progress-bar";
  $("#pushRes").textContent = "";
  CUR_F = null;
  clearInterval(POLL);
  poll();
  POLL = setInterval(poll, 2000);
}

async function poll() {
  const id = RUN;
  let r;
  try { r = await api(`/api/runs/${id}`); } catch { return; }
  if (id !== RUN) return;
  $("#runTitle").textContent = `Lần review #${r.id} · ${r.job_id ? "job " + r.job_id : "file tải lên"}${r.task_id ? " · task " + r.task_id : ""}`;
  const st = $("#runStatus");
  const m = [...(r.log || []).join("\n").matchAll(/\[(\d+)\/(\d+)\]/g)].pop();
  const pct = r.status === "xong" ? 100 : m ? 100 * m[1] / m[2] : r.status === "dang_chay" ? 4 : 0;
  const bar = $("#runProgress");
  bar.style.width = pct + "%";
  bar.className = "progress-bar" + (r.status === "xong" ? " done" : r.status === "loi" ? " fail" : "");
  st.className = "badge " + r.status;
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

function showResult(r) {
  RUN_DATA = r;
  $("#runResult").classList.remove("hidden");
  const s = r.stats || {}, pct = s.boxes ? s.ok / s.boxes : 0, pass = pct >= PASS;
  const sec = s.giay || 0;
  $("#stats").innerHTML = [
    [(pct * 100).toFixed(1) + "%", `Box không có lỗi chắc · ${pass ? "Đạt" : "Chưa đạt"} (ngưỡng ${PASS * 100}%)`, pass ? "pass" : "fail"],
    [s.sure, "Lỗi chắc chắn", s.sure ? "bad" : ""], [s.unsure, "Không chắc, cần xem", s.unsure ? "warn" : ""],
    [s.boxes, `Box trong ${s.frames} ảnh`, ""], [sec < 90 ? Math.round(sec) + " giây" : (sec / 60).toFixed(1) + " phút", "Thời gian chạy", ""],
  ].map(([v, k, c]) => `<div class="stat ${c}"><b>${esc(v ?? "-")}</b><span>${esc(k)}</span></div>`).join("");
  $("#runStatus").textContent = pass ? "Xong · Đạt" : "Xong · Chưa đạt";
  $("#runStatus").className = "badge " + (pass ? "xong" : "loi");
  $("#skipped").textContent = (r.guideline_name ? `Guideline: ${r.guideline_name}. ` : "Không dùng guideline. ") +
    (r.skipped_labels?.length ? `Tool không đánh giá được các nhãn: ${r.skipped_labels.join(", ")}.` : "");
  const kinds = [...new Set(r.findings.map(f => f.kind_vi))];
  $("#fKind").innerHTML = `<option value="">Tất cả</option>` + kinds.map(k => `<option>${esc(k)}</option>`).join("");
  SELECTED.clear();
  r.findings.forEach(f => { if (f.sure) SELECTED.add(f.id); });   // mac dinh: chon loi chac, "khong chac" de nguoi QC duyet
  $("#csv").href = `/api/runs/${r.id}/report.csv`;
  $("#pushBtn").disabled = !r.job_id;
  $("#pushRes").innerHTML = r.pushed ? pushedText(r.pushed)
    : r.job_id ? "" : `<span class="muted">Lần này review từ file, không gắn job nên không đẩy Issue được. Chạy lại theo số job để đẩy.</span>`;
  renderTable();
}

function filtered() {
  const k = $("#fKind").value, s = $("#fSure").value, t = $("#fTang").value;
  return RUN_DATA.findings.filter(f => (!k || f.kind_vi === k) && (!s || String(+f.sure) === s) && (!t || String(f.tang) === t));
}
["#fKind", "#fTang"].forEach(s => $(s).onchange = renderTable);
$$("#segSure button").forEach(b => b.onclick = () => {
  $$("#segSure button").forEach(x => x.classList.toggle("on", x === b));
  $("#fSure").value = b.dataset.v; renderTable();
});

function renderTable() {
  const rows = filtered();
  $("#ftable tbody").innerHTML = rows.map(f => `
    <tr data-id="${f.id}" class="sev-${+f.sure}${f.id === CUR_F ? " cur" : ""}">
      <td><input type="checkbox" aria-label="Chọn ghi chú ${f.id + 1}" ${SELECTED.has(f.id) ? "checked" : ""}></td>
      <td class="num">${f.id + 1}</td>
      <td>${f.frame != null ? "Frame " + f.frame : ""}<div class="img-name" title="${esc(f.name)}">${esc(f.name)}</div></td>
      <td><span class="tag sev-${+f.sure}">${f.sure ? "Lỗi" : "Không chắc"}</span><span class="tag kind">${esc(f.kind_vi)}${f.tang === 1 ? " · luật" : ""}</span><span class="tag lab">${esc(f.label)}</span></td>
      <td>${esc(f.msg)}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="muted">Không có ghi chú nào với bộ lọc này.</td></tr>`;
  updatePushBtn();
}

$("#ftable tbody").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-id]");
  if (!tr) return;
  const id = +tr.dataset.id;
  if (e.target.type === "checkbox") {
    e.target.checked ? SELECTED.add(id) : SELECTED.delete(id);
    return updatePushBtn();
  }
  $$("#ftable tr.cur").forEach(x => x.classList.remove("cur"));
  tr.classList.add("cur"); CUR_F = id;
  showFinding(RUN_DATA.findings[id]);
});

function showFinding(f) {
  $("#pvBox").className = "";
  $("#pvBox").innerHTML = (f.preview
    ? `<img src="/api/runs/${RUN}/preview/${encodeURIComponent(f.preview)}" alt="Ảnh frame ${f.frame ?? ""} có vẽ lỗi">
       <p class="pv-cap">Bấm ảnh để phóng to · đỏ = lỗi, vàng = không chắc, nét đứt = vật bị thiếu, khung xám = box người gán · số trên khung = thứ tự lỗi trong ảnh</p>`
    : `<div class="pv-empty">Không có ảnh xem trước cho ghi chú này.</div>`) +
    `<p class="pv-msg"><span class="tag sev-${+f.sure}">${f.sure ? "Lỗi" : "Không chắc"}</span> ${esc(f.msg)}</p><p class="pv-cap">Box [${f.box.join(", ")}]${f.ref ? " · " + esc(f.ref) : ""}</p>`;
  const refs = RUN_DATA.guideline_refs?.[f.label] || [];
  $("#gRef").innerHTML = RUN_DATA.guideline_name
    ? `<h3>Guideline nói gì về "${esc(f.label)}"</h3>` + (refs.length
      ? refs.map(x => `<div class="gref"><b>${esc(x.title)}</b>${esc(x.snippet)}</div>`).join("")
      : `<p class="muted">Không tìm thấy đoạn nào nhắc tới nhãn này. Thêm tên gọi khác vào <code>dong_nghia</code> trong file luật.</p>`)
    : "";
}
$("#pvBox").addEventListener("click", e => { if (e.target.tagName === "IMG") { $("#modalImg").src = e.target.src; $("#modal").classList.remove("hidden"); } });
$("#modal").onclick = () => $("#modal").classList.add("hidden");

$("#selSure").onclick = () => { SELECTED.clear(); RUN_DATA.findings.forEach(f => f.sure && SELECTED.add(f.id)); renderTable(); };
$("#selAll").onclick = () => { filtered().forEach(f => SELECTED.add(f.id)); renderTable(); };
$("#selNone").onclick = () => { filtered().forEach(f => SELECTED.delete(f.id)); renderTable(); };
function updatePushBtn() {
  $("#pushBtn").textContent = `⬆ Đẩy ${SELECTED.size} Issue lên CVAT`;
  if (RUN_DATA) $("#selInfo").textContent = `${filtered().length} ghi chú · đã chọn ${SELECTED.size}`;
}

function pushedText(p) {
  return `Đã đẩy <b>${p.created}</b> Issue${p.removed ? `, xoá ${p.removed} Issue tự động cũ` : ""} lúc ${fmtTime(p.time)}. ` +
    (p.unchanged ? `<span class="ok-text">Nhãn gốc không thay đổi ✔</span>` : `<span class="err">Nhãn trên CVAT đã khác lúc review (có người đang sửa job?)</span>`);
}

$("#pushBtn").onclick = async () => {
  if (!SELECTED.size) { $("#pushRes").innerHTML = `<span class="err">Chưa chọn ghi chú nào.</span>`; return; }
  const nUnsure = RUN_DATA.findings.filter(f => SELECTED.has(f.id) && !f.sure).length;
  const ok = await askConfirm(`Tạo ${SELECTED.size} Issue trên job ${RUN_DATA.job_id}${nUnsure ? `, trong đó ${nUnsure} ghi chú "không chắc"` : ""}. Tool chỉ tạo Issue, không sửa nhãn.`, "Đẩy Issue", "Đẩy Issue lên CVAT?");
  if (!ok) return;
  const b = $("#pushBtn"); b.disabled = true; $("#pushRes").textContent = "Đang đẩy…";
  try {
    const p = await api(`/api/runs/${RUN}/push`, { method: "POST", json: { ids: [...SELECTED], replace_old: $("#replaceOld").checked } });
    $("#pushRes").innerHTML = pushedText(p);
  } catch (err) { $("#pushRes").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  b.disabled = false;
};

// ------------------------------------------------------------ lich su
async function loadHistory() {
  const rs = await api("/api/runs" + ($("#hJob").value ? `?job_id=${encodeURIComponent($("#hJob").value)}` : ""));
  $("#htable tbody").innerHTML = rs.map(r => {
    const s = r.stats || {};
    return `<tr data-id="${r.id}"><td>${r.id}</td><td>${r.job_id ?? "file"}</td><td>${r.task_id ?? ""}</td><td>${esc(r.username)}</td>
      <td>${fmtTime(r.created)}</td><td><span class="badge ${r.status}">${STATUS[r.status]}${r.position ? " · thứ " + r.position : ""}</span></td>
      <td>${s.boxes ? (s.ok / s.boxes * 100).toFixed(1) + "%" : ""}</td><td>${s.boxes !== undefined ? `${s.sure} / ${s.unsure}` : ""}</td>
      <td>${r.pushed ? r.pushed.created + " Issue" : ""}</td></tr>`;
  }).join("") || `<tr><td colspan="9" class="muted">Chưa có lần review nào.</td></tr>`;
}
$("#hJob").oninput = () => loadHistory();
$("#htable tbody").addEventListener("click", e => { const tr = e.target.closest("tr[data-id]"); if (tr) openRun(+tr.dataset.id); });

// ------------------------------------------------------------ guideline
async function loadGuides() {
  const gs = await api("/api/guidelines");
  const canEdit = ME.role !== "labeler";
  $("#gtable tbody").innerHTML = gs.map(g => `<tr data-id="${g.id}"><td><b>${esc(g.name)}</b></td><td>${esc(g.file_name)}</td>
    <td>${g.tasks.join(", ")}</td><td>${g.has_rules ? "Có" : '<span class="muted">Chưa có</span>'}</td>
    <td>${canEdit ? `<button class="link" data-del="${g.id}">Xoá</button>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5" class="muted">Chưa có guideline nào.</td></tr>`;
}
$("#gtable tbody").addEventListener("click", async e => {
  if (e.target.dataset.del) {
    e.stopPropagation();
    if (await askConfirm("Xoá guideline này? File gốc và file luật sẽ bị xoá.")) { await api(`/api/guidelines/${e.target.dataset.del}`, { method: "DELETE" }); loadGuides(); loadGuideOptions(); $("#gDetail").classList.add("hidden"); }
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
  } catch (err) { $("#gUpErr").textContent = err.message; }
};

async function openGuide(id) {
  const g = await api(`/api/guidelines/${id}`);
  CUR_G = g;
  $("#gDetail").classList.remove("hidden");
  $("#gName").textContent = g.name;
  $("#gFile").href = `/api/guidelines/${id}/file`;
  $("#gRules").value = g.rules;
  $("#gTask").value = $("#gTask").value || CFG.task_id || "";
  $("#gTasks").textContent = g.tasks.length ? `Đang gán cho task: ${g.tasks.join(", ")} (review các task này tự chọn guideline này).` : "Chưa gán cho task nào.";
  $("#gMsg").textContent = "";
  const ro = ME.role === "labeler";
  ["#gRules", "#gSave", "#gTemplate", "#gAssign"].forEach(s => $(s).disabled = ro);
  renderSections(g.sections);
  $("#gDetail").scrollIntoView({ behavior: "smooth" });
}
function renderSections(secs, words = []) {
  const hl = s => { let h = esc(s); words.forEach(w => { if (w) h = h.replace(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), m => `<mark>${m}</mark>`); }); return h; };
  $("#gSections").innerHTML = secs.map(s => `<div class="sec"><b>${hl(s.title)}</b><div>${hl(s.body || s.snippet || "")}</div></div>`).join("")
    || `<p class="muted">Không có kết quả.</p>`;
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
    $("#gMsg").innerHTML = r.warnings.length ? `<span class="err">Đã lưu, cần xem lại: ${esc(r.warnings.join(" · "))}</span>` : `<span style="color:var(--good)">Đã lưu ✔</span>`;
    loadGuides(); loadGuideOptions();
  } catch (err) { $("#gMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
$("#gTemplate").onclick = async () => {
  if ($("#gRules").value.trim() && !(await askConfirm("Thay nội dung file luật hiện tại bằng mẫu mới?"))) return;
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

// ------------------------------------------------------------ cai dat
async function loadSettings() {
  await loadConfig();
  $("#cfgBox").innerHTML = `<span class="muted">CVAT_URL</span><span>${esc(CFG.cvat_url || "-")}</span>
    <span class="muted">CVAT_TOKEN</span><span>${CFG.has_token ? "đã có (ẩn)" : '<span class="err">chưa có</span>'}</span>
    <span class="muted">CVAT_TASK_ID</span><span>${CFG.task_id ?? "-"}</span>
    <span class="muted">CVAT_JOB_ID</span><span>${CFG.job_id ?? "-"}</span>
    <span class="muted">Máy chạy</span><span>${esc(CFG.device)}</span>`;
  $("#testCvat").disabled = ME.role === "labeler";
  if (ME.role === "admin") loadUsers();
}
$("#testCvat").onclick = async () => {
  $("#testRes").textContent = "Đang kiểm tra…";
  try {
    const r = await api("/api/cvat/test");
    $("#testRes").innerHTML = `<span style="color:var(--good)">Kết nối được ✔</span> tài khoản <b>${esc(r.username)}</b>` +
      (r.job_id ? ` · job ${r.job_id} thuộc task ${r.job_task}, trạng thái ${esc(r.job_state)} / ${esc(r.job_stage)}` +
        (r.task_match ? "" : ` · <span class="err">CVAT_TASK_ID trong .env không khớp</span>`) : "");
  } catch (err) { $("#testRes").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
$("#pwForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try { await api("/api/password", { method: "POST", json: { old: f.get("old"), new: f.get("new") } }); $("#pwMsg").textContent = "Đã đổi ✔"; e.target.reset(); }
  catch (err) { $("#pwMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
async function loadUsers() {
  const us = await api("/api/users");
  $("#utable tbody").innerHTML = us.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.role)}</td>
    <td>${u.username !== ME.username ? `<button class="link" data-u="${esc(u.username)}">Xoá</button>` : ""}</td></tr>`).join("");
}
$("#utable tbody").addEventListener("click", async e => {
  const n = e.target.dataset.u;
  if (n && await askConfirm(`Xoá tài khoản ${n}?`)) { await api(`/api/users/${encodeURIComponent(n)}`, { method: "DELETE" }); loadUsers(); }
});
$("#userForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/users", { method: "POST", json: { username: f.get("username"), password: f.get("password"), role: f.get("role") } });
    $("#userMsg").textContent = "Đã lưu ✔"; e.target.reset(); loadUsers();
  } catch (err) { $("#userMsg").innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};

start();

// hop xac nhan tu ve (confirm() co the bi trinh duyet chan)
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
  if (e.key === "Escape") { $("#modal").classList.add("hidden"); if (!$("#confirmBox").classList.contains("hidden")) $("#cfNo").click(); }
});
