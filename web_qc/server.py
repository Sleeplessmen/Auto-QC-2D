"""
server.py — Web QC nhan 2D: dang nhap, ket noi CVAT (nhieu may, them tren web), chon job tu CVAT, hang doi review,
duyet loi + danh dau "tool nham", day Issue (chong trung), theo doi Issue, tong quan, guideline + trinh soan luat,
webhook CVAT tu chay khi job hoan thanh. Nguyen tac nhu review_core: chi ghi Issue len CVAT, KHONG sua nhan.

  web_qc.bat                 -> http://localhost:8000 (chi may nay)
  web_qc.bat --lan           -> may khac cung mang vao http://<ip may nay>:8000
"""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))          # cvat_2d: review_core, label_hq_2d, label_mapping

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import store
import guideline as G

store.init()
import review_core as R                             # nap torch + model: cham, de sau store.init
from worker import Worker, env_config, cvat_client, connection_for

UPLOADS = os.path.join(store.DATA, "uploads")
GUIDE_DIR = os.path.join(store.DATA, "guidelines")
for d in (UPLOADS, GUIDE_DIR):
    os.makedirs(d, exist_ok=True)

# .env cu tro thanh 1 ket noi tren web (lan dau, hoac khi doi token trong .env)
_e = env_config()
store.import_env_connection(_e["url"], _e["token"], _e["org"])

app = FastAPI(title="Web QC nhãn 2D", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=store.secret_key(), max_age=14 * 24 * 3600, same_site="lax")
worker = Worker()
ROLES = {"labeler": 0, "qc": 1, "admin": 2}
_task_names = {}                                     # (connection id, task id) -> ten task


@app.exception_handler(ValueError)
@app.exception_handler(RuntimeError)
async def _err(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def user(request: Request):
    u = request.session.get("user")
    if not u:
        raise HTTPException(401, "Chưa đăng nhập.")
    return u


def need(role):
    def dep(u=Depends(user)):
        if ROLES.get(u["role"], 0) < ROLES[role]:
            raise HTTPException(403, "Tài khoản của bạn không có quyền làm việc này.")
        return u
    return dep


def num(v):
    """'12' / 12 -> 12; 0 la so hop le (frame dau tien thuong la 0); rong / chu -> None."""
    s = "" if v is None else str(v).strip()
    return int(s) if s.lstrip("-").isdigit() else None


def pct_of(stats):
    return (stats["ok"] / stats["boxes"]) if stats and stats.get("boxes") else None


def report_token(run_id):
    """Ma bi mat cho link bao cao gui labeler (khong can dang nhap). Doi secret.key la moi link cu het hieu luc."""
    return hmac.new(store.secret_key().encode(), f"report:{run_id}".encode(), hashlib.sha256).hexdigest()[:24]


def report_url(request, run_id):
    return str(request.base_url).rstrip("/") + f"/bao-cao.html?run={run_id}&t={report_token(run_id)}"


def _findings_of(run):
    p = os.path.join(run.get("out_dir") or "", "ket_qua_review.json")
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8")).get("findings", [])


def compare_prev(run):
    """So voi lan review xong gan nhat truoc do cua cung job: bao nhieu loi da sua / con / moi (theo dau van tay)."""
    if not run.get("job_id"):
        return None
    prev = next((r for r in store.list_runs(job_id=run["job_id"]) if r["id"] < run["id"] and r["status"] == "xong"), None)
    if not prev:
        return None
    fp = R.Review.fingerprint
    a = {fp(f) for f in _findings_of(prev) if f.get("frame") is not None}
    b = {fp(f) for f in _findings_of(run) if f.get("frame") is not None}
    return dict(prev_id=prev["id"], prev_pct=pct_of(prev.get("stats")), fixed=len(a - b), still=len(a & b), new=len(b - a))


# ------------------------------------------------------------------ dang nhap
@app.post("/api/login")
def login(request: Request, body: dict):
    u = store.check_pw(body.get("username", "").strip(), body.get("password", ""))
    if not u:
        time.sleep(1)
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu.")
    request.session["user"] = dict(username=u["username"], role=u["role"])
    return request.session["user"]


@app.get("/api/setup")
def setup_info():
    """Cho trang dang nhap biet day la lan dau (file mat khau admin con) de hien huong dan. Khong lo mat khau."""
    first = os.path.exists(os.path.join(store.DATA, "MAT_KHAU_ADMIN.txt"))
    return dict(first_run=first, admin_file=r"cvat_2d\web_qc\data\MAT_KHAU_ADMIN.txt" if first else None)


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {}


@app.get("/api/me")
def me(u=Depends(user)):
    return u


@app.post("/api/password")
def change_pw(body: dict, u=Depends(user)):
    if not store.check_pw(u["username"], body.get("old", "")):
        raise HTTPException(400, "Mật khẩu cũ không đúng.")
    if len(body.get("new", "")) < 6:
        raise HTTPException(400, "Mật khẩu mới cần ít nhất 6 ký tự.")
    store.set_user(u["username"], pw=body["new"])
    return {}


# ------------------------------------------------------------------ cau hinh chung
@app.get("/api/config")
def config(u=Depends(user)):
    e, s = env_config(), store.get_settings()
    d = store.default_connection(with_token=False)
    return dict(connections=store.list_connections(), default_connection=d["id"] if d else None,
                env_task_id=e["task_id"], env_job_id=e["job_id"], device=R.ToolRunner.device(), user=u,
                pass_threshold=s["pass_threshold"], default_mode=s["default_mode"], webhook_enabled=s["webhook_enabled"])


@app.get("/api/settings")
def get_settings(request: Request, u=Depends(need("admin"))):
    s = store.get_settings()
    s["webhook_url"] = str(request.base_url).rstrip("/") + "/api/webhook/cvat"
    return s


@app.put("/api/settings")
def put_settings(body: dict, u=Depends(need("admin"))):
    t = body.get("pass_threshold")
    if t is not None and not (0.5 <= float(t) <= 1):
        raise HTTPException(400, "Ngưỡng đạt phải từ 50% đến 100%.")
    if body.get("webhook_enabled") and not (body.get("webhook_secret") or store.get_settings()["webhook_secret"]):
        body["webhook_secret"] = secrets.token_urlsafe(18)
    if body.get("default_mode") not in (None, "chinh_xac", "nhanh"):
        raise HTTPException(400, "Chế độ không hợp lệ.")
    store.set_settings(**{k: v for k, v in body.items() if k in store.DEFAULT_SETTINGS})
    return store.get_settings()


# ------------------------------------------------------------------ ket noi CVAT
def _clean_conn(body):
    name, url = (body.get("name") or "").strip(), (body.get("url") or "").strip()
    if not name or not url:
        raise HTTPException(400, "Cần tên kết nối và địa chỉ CVAT.")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Địa chỉ CVAT phải bắt đầu bằng http:// hoặc https://")
    return name, url


@app.get("/api/connections")
def connections(u=Depends(user)):
    return store.list_connections()


@app.post("/api/connections")
def add_connection(body: dict, u=Depends(need("qc"))):
    name, url = _clean_conn(body)
    if not (body.get("token") or "").strip():
        raise HTTPException(400, "Cần token của CVAT (Profile → Security → Personal Access Tokens).")
    cid = store.save_connection(None, name, url, body["token"].strip(), (body.get("org") or "").strip(), bool(body.get("is_default")), u["username"])
    return dict(id=cid)


@app.put("/api/connections/{cid}")
def edit_connection(cid: int, body: dict, u=Depends(need("qc"))):
    name, url = _clean_conn(body)
    store.save_connection(cid, name, url, (body.get("token") or "").strip() or None, (body.get("org") or "").strip(),
                          bool(body.get("is_default")), u["username"])
    for k in [k for k in _task_names if k[0] == cid]:
        _task_names.pop(k, None)
    return {}


@app.post("/api/connections/{cid}/default")
def default_conn(cid: int, u=Depends(need("qc"))):
    c = store.get_connection(cid)
    if not c:
        raise HTTPException(404, "Không có kết nối này.")
    store.save_connection(cid, c["name"], c["url"], None, c["org"], True, u["username"])
    return {}


@app.delete("/api/connections/{cid}")
def delete_conn(cid: int, u=Depends(need("qc"))):
    store.del_connection(cid)
    return {}


@app.post("/api/connections/test")
def test_connection(body: dict, u=Depends(need("qc"))):
    """Thu ket noi: hoac theo id (dung token da luu), hoac theo URL + token vua nhap (chua luu)."""
    if body.get("id"):
        cv, c = cvat_client(int(body["id"]))
    else:
        _, url = _clean_conn(dict(name="x", url=body.get("url")))
        if not (body.get("token") or "").strip():
            raise HTTPException(400, "Cần token để thử kết nối.")
        cv = R.Cvat(url, body["token"].strip(), (body.get("org") or "").strip() or None)
    info = dict(ok=True, username=cv.user.get("username"))
    try:
        info["version"] = cv.get("/api/server/about").json().get("version")
    except Exception:
        pass
    try:
        info["orgs"] = [o.get("slug") for o in cv.get("/api/organizations", page_size=50).json().get("results", [])]
    except Exception:
        info["orgs"] = []
    try:
        info["jobs"] = cv.get("/api/jobs", page_size=1).json().get("count")
    except Exception:
        pass
    return info


def _task_name(cid, cv, tid):
    key = (cid, tid)
    if key not in _task_names:
        try:
            _task_names[key] = cv.get(f"/api/tasks/{tid}").json().get("name")
        except Exception:
            _task_names[key] = None
    return _task_names[key]


@app.get("/api/connections/{cid}/jobs")
def list_jobs(cid: int, page: int = 1, search: str = "", stage: str = "", state: str = "", dimension: str = "", u=Depends(user)):
    """Danh sach job tren CVAT de chon (khoi phai go so job). Kem ket qua review gan nhat cua tung job."""
    cv, c = cvat_client(cid)
    params = dict(page=max(1, page), page_size=25, sort="-updated_date")
    for k, v in (("search", search), ("stage", stage), ("state", state), ("dimension", dimension)):
        if v.strip():
            params[k] = v.strip()
    try:
        data = cv.get("/api/jobs", **params).json()
    except RuntimeError:
        params.pop("search", None)
        params.pop("sort", None)
        data = cv.get("/api/jobs", **params).json()
    last = {}
    for r in store.list_runs(limit=1000):
        if r["job_id"] and r["job_id"] not in last and r.get("connection_id") in (None, cid):
            last[r["job_id"]] = r
    out = []
    for j in data.get("results", []):
        a = j.get("assignee") or {}
        lr = last.get(j["id"])
        out.append(dict(id=j["id"], task_id=j.get("task_id"), task_name=j.get("task_name") or _task_name(cid, cv, j.get("task_id")),
                        project_id=j.get("project_id"), assignee=a.get("username"), assignee_name=a.get("first_name"),
                        stage=j.get("stage"), state=j.get("state"), dimension=j.get("dimension"), type=j.get("type"),
                        frames=j.get("frame_count") or ((j.get("stop_frame") or 0) - (j.get("start_frame") or 0) + 1),
                        updated=j.get("updated_date"), issues=(j.get("issues") or {}).get("count"),
                        last_run=dict(id=lr["id"], status=lr["status"], pct=pct_of(lr.get("stats")), created=lr["created"]) if lr else None))
    return dict(count=data.get("count", len(out)), page=params["page"], page_size=params["page_size"], results=out)


@app.get("/api/connections/{cid}/jobs/{jid}")
def job_info(cid: int, jid: int, u=Depends(user)):
    cv, c = cvat_client(cid)
    j = cv.job(jid)
    a = j.get("assignee") or {}
    return dict(id=j["id"], task_id=j.get("task_id"), task_name=_task_name(cid, cv, j.get("task_id")), dimension=j.get("dimension"),
                stage=j.get("stage"), state=j.get("state"), assignee=a.get("username"),
                frames=j.get("frame_count"), guideline_id=store.task_guideline(j.get("task_id")))


# ------------------------------------------------------------------ review
@app.post("/api/runs")
def create_run(job_id: str = Form(""), task_id: str = Form(""), guideline_id: str = Form(""), mode: str = Form("chinh_xac"),
               connection_id: str = Form(""), rider: str = Form("1"), max_frames: str = Form(""), auto_push: str = Form("0"),
               push_unsure: str = Form("0"), file: UploadFile | None = File(None), u=Depends(user)):
    jid, tid, cid = num(job_id), num(task_id), num(connection_id)
    if not jid and not (file and file.filename):
        raise HTTPException(400, "Chọn một job, hoặc tải lên file export.")
    frames_hint = None
    if jid:
        cid = connection_for(cid)["id"]
        try:                                     # so frame de uoc luong thoi gian cho trong hang doi
            cv, _ = cvat_client(cid)
            frames_hint = cv.job(jid).get("frame_count")
        except Exception:
            pass
    gid = num(guideline_id)
    if gid is None and guideline_id != "0":
        gid = store.task_guideline(tid)
    params = dict(mode="nhanh" if mode == "nhanh" else "chinh_xac", rider=rider == "1", max_frames=num(max_frames),
                  auto_push=auto_push == "1", push_unsure=push_unsure == "1", frames_hint=frames_hint)
    run_id = store.new_run(jid, tid, u["username"], params, gid or None, cid if jid else None)
    if file and file.filename:
        if not file.filename.lower().endswith(".zip"):
            raise HTTPException(400, "File export phải là .zip (CVAT for images 1.1 / COCO / YOLO).")
        path = os.path.join(UPLOADS, f"run{run_id}.zip")
        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        params["file"] = path
        try:                                     # so anh trong file -> uoc luong thoi gian cho
            import zipfile
            with zipfile.ZipFile(path) as z:
                params["frames_hint"] = sum(1 for n in z.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")))
        except Exception:
            pass
        store.update_run(run_id, params=params)
    worker.submit(run_id)
    return dict(id=run_id)


@app.post("/api/runs/{run_id}/rerun")
def rerun(run_id: int, u=Depends(user)):
    r = store.get_run(run_id)
    if not r:
        raise HTTPException(404, "Không có lần review này.")
    p = dict(r["params"] or {})
    if p.get("file") and not os.path.exists(p["file"]):
        raise HTTPException(400, "File export của lần trước không còn, hãy tải lên lại.")
    nid = store.new_run(r["job_id"], r["task_id"], u["username"], p, r["guideline_id"], r.get("connection_id"))
    worker.submit(nid)
    return dict(id=nid)


def _run_public(r):
    r = dict(r)
    r["position"] = worker.position(r["id"])
    if r["status"] in ("cho", "dang_chay"):
        try:
            r["eta"] = worker.eta(r["id"])
        except Exception:
            r["eta"] = None
    r["pct"] = pct_of(r.get("stats"))
    r.pop("out_dir", None)
    if r.get("params"):
        r["params"] = {k: v for k, v in r["params"].items() if k != "file"}
    return r


@app.get("/api/runs")
def runs(job_id: str = "", u=Depends(user)):
    fb = store.feedback_counts()
    out = []
    for r in store.list_runs(job_id=num(job_id)):
        d = _run_public(r)
        d["fp"] = fb.get(r["id"], 0)
        out.append(d)
    return out


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int, request: Request, u=Depends(user)):
    r = store.get_run(run_id)
    if not r:
        raise HTTPException(404, "Không có lần review này.")
    d = _run_public(r)
    d["running_now"] = worker.current
    d["log"] = worker.log_tail(run_id)
    d["findings"], d["frames"], d["guideline_refs"] = [], [], {}
    c = store.get_connection(r.get("connection_id"), with_token=False) if r.get("connection_id") else None
    d["connection"] = dict(id=c["id"], name=c["name"], url=c["url"]) if c else None
    if c and r["job_id"] and r.get("task_id"):
        d["cvat_job_url"] = f"{c['url']}/tasks/{r['task_id']}/jobs/{r['job_id']}"
    g = store.get_guideline(r["guideline_id"])
    if g:
        d["guideline_name"] = g["name"]
    if r["status"] == "xong":
        rv = worker.review_obj(run_id)
        if rv is not None:
            pv_of = {}
            for n, base, nbox, pv, finds in rv.frames:
                fn = os.path.basename(pv)
                stem = os.path.splitext(fn)[0]
                has_an = os.path.exists(os.path.join(rv.out_dir, "analysis", stem + ".json"))
                d["frames"].append(dict(frame=n, name=base, preview=f"/api/runs/{run_id}/preview/{fn}",
                                        n=len(finds), sure=sum(1 for f in finds if f["sure"]),
                                        analysis=f"/api/runs/{run_id}/analysis/{stem}" if has_an else None,
                                        raw=f"/api/runs/{run_id}/raw/{stem}" if has_an else None))
                pv_of[(n, base)] = fn
            for i, f in enumerate(rv.findings):
                d["findings"].append(dict(id=i, frame=f["frame"], name=f["name"], kind=f["kind"],
                                          kind_vi=R.KIND_VI.get(f["kind"], f["kind"]), sure=f["sure"], label=f["label"],
                                          box=[round(v) for v in f["box"]], msg=f["msg"], ref=f.get("ref"),
                                          tang=f.get("tang", 2), preview=pv_of.get((f["frame"], f["name"]))))
            if g:
                rules, _ = G.parse_rules(g["rules"]) if g.get("rules") else ({}, [])
                for lb in sorted({f["label"] for f in rv.findings}):
                    d["guideline_refs"][lb] = G.find_related(g["text"], G.words_for(rules, lb))
            d["skipped_labels"] = rv.skipped_labels
    d["feedback"] = store.get_feedback(run_id)
    d["notes"] = store.get_notes(run_id)
    d["edits"] = store.get_edits(run_id)
    if r["status"] == "xong":
        d["compare"] = compare_prev(r)
        d["report_url"] = report_url(request, run_id)
    return d


# ------------------------------------------------------------------ ghi chu tay + sua loi nhan (nguoi review)
def _msg(body, limit=500):
    m = (body.get("msg") or "").strip()
    if len(m) > limit:
        raise HTTPException(400, f"Ghi chú dài quá {limit} ký tự.")
    return m


@app.post("/api/runs/{run_id}/notes")
def add_note(run_id: int, body: dict, u=Depends(user)):
    if not store.get_run(run_id):
        raise HTTPException(404, "Không có lần review này.")
    box = body.get("box") or []
    if len(box) != 4 or box[2] - box[0] < 2 or box[3] - box[1] < 2:
        raise HTTPException(400, "Kéo một khung trên ảnh để đánh dấu chỗ cần ghi chú.")
    msg = _msg(body)
    if not msg:
        raise HTTPException(400, "Nhập nội dung ghi chú.")
    nid = store.add_note(run_id, num(body.get("frame")), body.get("name") or "", box, msg, u["username"])
    return dict(id=nid, notes=store.get_notes(run_id))


@app.put("/api/runs/{run_id}/notes/{nid}")
def edit_note(run_id: int, nid: int, body: dict, u=Depends(user)):
    msg = _msg(body)
    if not msg:
        raise HTTPException(400, "Nhập nội dung ghi chú.")
    store.update_note(nid, msg)
    return store.get_notes(run_id)


@app.delete("/api/runs/{run_id}/notes/{nid}")
def delete_note(run_id: int, nid: int, u=Depends(user)):
    store.del_note(nid)
    return store.get_notes(run_id)


@app.put("/api/runs/{run_id}/findings/{fid}")
def edit_finding(run_id: int, fid: int, body: dict, u=Depends(user)):
    """Nguoi review sua loi nhan cua tool truoc khi day (trong = tro ve loi nhan goc)."""
    store.set_edit(run_id, fid, _msg(body), u["username"])
    return store.get_edits(run_id)


def _run_dir(run_id):
    r = store.get_run(run_id)
    if not r or not r.get("out_dir"):
        raise HTTPException(404, "Không có kết quả.")
    return r["out_dir"]


@app.get("/api/runs/{run_id}/preview/{fn}")
def preview(run_id: int, fn: str, u=Depends(user)):
    p = os.path.join(_run_dir(run_id), "preview", os.path.basename(fn))
    if not os.path.exists(p):
        raise HTTPException(404, "Không có ảnh.")
    return FileResponse(p)


@app.get("/api/runs/{run_id}/analysis/{stem}")
def analysis(run_id: int, stem: str, u=Depends(user)):
    """Du lieu che do Phan tich cua 1 anh: nhan labeler, vat tool thay, mat duong model, doi chieu."""
    p = os.path.join(_run_dir(run_id), "analysis", os.path.basename(stem) + ".json")
    if not os.path.exists(p):
        raise HTTPException(404, "Lần review này chạy bằng bản cũ, chưa có dữ liệu phân tích. Bấm Review lại.")
    return FileResponse(p, media_type="application/json")


@app.get("/api/runs/{run_id}/raw/{stem}")
def raw_image(run_id: int, stem: str, u=Depends(user)):
    p = os.path.join(_run_dir(run_id), "goc", os.path.basename(stem) + ".jpg")
    if not os.path.exists(p):
        raise HTTPException(404, "Không có ảnh gốc.")
    return FileResponse(p)


@app.get("/api/runs/{run_id}/report.csv")
def report(run_id: int, u=Depends(user)):
    p = os.path.join(_run_dir(run_id), "ket_qua_review.csv")
    return FileResponse(p, filename=f"review_run{run_id}.csv")


@app.post("/api/runs/{run_id}/feedback")
def feedback(run_id: int, body: dict, u=Depends(user)):
    fid = num(body.get("finding_id"))
    if fid is None:
        raise HTTPException(400, "Thiếu mã lỗi.")
    verdict = body.get("verdict") or ""
    if verdict not in ("", "tool_nham"):
        raise HTTPException(400, "Phản hồi không hợp lệ.")
    store.set_feedback(run_id, fid, verdict, (body.get("note") or "")[:300], u["username"])
    return store.get_feedback(run_id)


@app.post("/api/runs/{run_id}/push")
def push(run_id: int, body: dict, request: Request, u=Depends(user)):
    ids = [int(i) for i in body.get("ids", [])]
    note_ids = [int(i) for i in body.get("note_ids", [])]
    if not ids and not note_ids and not body.get("summary"):
        raise HTTPException(400, "Chưa chọn ghi chú nào để đẩy.")
    return worker.push(run_id, ids, replace_old=bool(body.get("replace_old", True)), note_ids=note_ids,
                       summary=bool(body.get("summary")), report_url=report_url(request, run_id))


# ------------------------------------------------------------------ trang bao cao cho labeler (khong can dang nhap, co ma)
def _check_token(run_id, t):
    if not t or not hmac.compare_digest(t, report_token(run_id)):
        raise HTTPException(403, "Link báo cáo không đúng hoặc đã hết hiệu lực.")


@app.get("/api/public/runs/{run_id}")
def public_run(run_id: int, t: str = ""):
    _check_token(run_id, t)
    r = store.get_run(run_id)
    if not r or r["status"] != "xong":
        raise HTTPException(404, "Lần review này chưa xong.")
    rv = worker.review_obj(run_id)
    fb = store.get_feedback(run_id)
    edits = store.get_edits(run_id)
    pushed = set((r.get("pushed") or {}).get("ids") or [])
    pv_name = {base: os.path.basename(pv) for n, base, _, pv, _ in rv.frames}       # tim anh theo ten file
    items = []
    for i, f in enumerate(rv.findings):
        if fb.get(i, {}).get("verdict") == "tool_nham":
            continue
        if pushed and i not in pushed:                   # da day roi thi chi hien nhung loi da day
            continue
        items.append(dict(frame=f["frame"], name=f["name"], kind_vi=R.KIND_VI.get(f["kind"], f["kind"]), sure=f["sure"],
                          label=f["label"], box=[round(v) for v in f["box"]], msg=edits.get(i, f["msg"]),
                          preview=pv_name.get(f["name"])))
    for n in store.get_notes(run_id):
        items.append(dict(frame=n["frame"], name=n["name"], kind_vi="Ghi chú người review", sure=True, label="", box=n["box"],
                          msg=n["msg"], preview=pv_name.get(n["name"])))
    c = store.get_connection(r.get("connection_id"), with_token=False) if r.get("connection_id") else None
    base = f"{c['url']}/tasks/{r['task_id']}/jobs/{r['job_id']}" if c and r.get("task_id") and r.get("job_id") else None
    g = store.get_guideline(r["guideline_id"])
    return dict(id=r["id"], job_id=r["job_id"], task_name=r.get("task_name") or (f"Task {r['task_id']}" if r.get("task_id") else ""),
                assignee=r.get("assignee"), created=r["created"], stats=r["stats"], pct=pct_of(r["stats"]),
                threshold=store.get_settings()["pass_threshold"], cvat_job_url=base, guideline_name=g["name"] if g else None,
                items=sorted(items, key=lambda x: (x["frame"] if x["frame"] is not None else 1e9, not x["sure"])), compare=compare_prev(r))


@app.get("/api/public/runs/{run_id}/preview/{fn}")
def public_preview(run_id: int, fn: str, t: str = ""):
    _check_token(run_id, t)
    p = os.path.join(_run_dir(run_id), "preview", os.path.basename(fn))
    if not os.path.exists(p):
        raise HTTPException(404, "Không có ảnh.")
    return FileResponse(p)


@app.get("/api/runs/{run_id}/issues")
def run_issues(run_id: int, u=Depends(user)):
    return worker.job_issues(run_id)


# ------------------------------------------------------------------ tong quan
@app.get("/api/dashboard")
def dashboard(days: int = 30, u=Depends(user)):
    s = store.get_settings()
    thr = s["pass_threshold"]
    since = time.time() - max(1, days) * 86400
    rs = [r for r in store.list_runs(limit=2000) if r["created"] >= since]
    done = [r for r in rs if r["status"] == "xong" and pct_of(r.get("stats")) is not None]
    fb = store.feedback_counts()
    kinds = defaultdict(int)
    by_ass = defaultdict(lambda: dict(runs=0, pct=0.0, sure=0, unsure=0, passed=0, jobs=set(), last=0))
    by_day = defaultdict(lambda: dict(runs=0, pct=0.0))
    tot_find = tot_fp = pushed = 0
    for r in done:
        st, p = r["stats"], pct_of(r["stats"])
        if not st.get("kinds") and r.get("out_dir"):        # lan review cu chua luu thong ke theo loai -> doc bu tu file ket qua
            try:
                res = json.load(open(os.path.join(r["out_dir"], "ket_qua_review.json"), encoding="utf-8"))
                st["kinds"] = {}
                for f in res.get("findings", []):
                    st["kinds"][f["kind"]] = st["kinds"].get(f["kind"], 0) + 1
            except Exception:
                pass
        for k, n in (st.get("kinds") or {}).items():
            kinds[R.KIND_VI.get(k, k)] += n
        name = r.get("assignee") or "(chưa rõ người gán)"
        a = by_ass[name]
        a["runs"] += 1; a["pct"] += p; a["sure"] += st.get("sure", 0); a["unsure"] += st.get("unsure", 0)
        a["passed"] += p >= thr; a["last"] = max(a["last"], r["created"])
        if r["job_id"]:
            a["jobs"].add(r["job_id"])
        day = time.strftime("%Y-%m-%d", time.localtime(r["created"]))
        by_day[day]["runs"] += 1; by_day[day]["pct"] += p
        tot_find += st.get("sure", 0) + st.get("unsure", 0)
        tot_fp += fb.get(r["id"], 0)
        pushed += (r.get("pushed") or {}).get("created", 0)
    n = len(done)
    return dict(
        days=days, threshold=thr, runs=len(rs), done=n, failed=sum(1 for r in rs if r["status"] == "loi"),
        passed=sum(1 for r in done if pct_of(r["stats"]) >= thr),
        avg_pct=(sum(pct_of(r["stats"]) for r in done) / n) if n else None,
        sure=sum(r["stats"].get("sure", 0) for r in done), unsure=sum(r["stats"].get("unsure", 0) for r in done),
        boxes=sum(r["stats"].get("boxes", 0) for r in done), issues_pushed=pushed,
        fp_rate=(tot_fp / tot_find) if tot_find else None, fp=tot_fp,
        kinds=sorted(([k, v] for k, v in kinds.items()), key=lambda x: -x[1]),
        assignees=sorted([dict(name=k, runs=v["runs"], jobs=len(v["jobs"]), avg_pct=v["pct"] / v["runs"], sure=v["sure"],
                               unsure=v["unsure"], pass_rate=v["passed"] / v["runs"], last=v["last"]) for k, v in by_ass.items()],
                         key=lambda x: x["avg_pct"]),
        trend=[dict(day=k, runs=v["runs"], avg_pct=v["pct"] / v["runs"]) for k, v in sorted(by_day.items())],
        recent=[_run_public(r) for r in rs[:8]],
    )


# ------------------------------------------------------------------ guideline
@app.get("/api/guidelines")
def guidelines(u=Depends(user)):
    out = []
    for g in store.list_guidelines():
        rules, warn = ({}, [])
        try:
            rules, warn = G.parse_rules(g.pop("rules"))
        except ValueError:
            warn = ["File luật sai cú pháp"]
        g["n_labels"] = len(rules.get("nhan") or {})
        g["warnings"] = warn
        out.append(g)
    return out


@app.post("/api/guidelines")
def upload_guideline(name: str = Form(""), file: UploadFile = File(...), u=Depends(need("qc"))):
    fn = os.path.basename(file.filename or "guideline")
    ext = os.path.splitext(fn)[1].lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Guideline phải là PDF, DOCX, TXT hoặc MD.")
    gid = store.add_guideline(name.strip() or os.path.splitext(fn)[0], fn, "", "", "", u["username"])
    path = os.path.join(GUIDE_DIR, f"g{gid}{ext}")
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        text = G.extract_text(path)
    except Exception as e:
        store.del_guideline(gid)
        raise HTTPException(400, f"Không đọc được file: {e}")
    store.update_guideline(gid, file_path=path, text=text)
    warn = "" if len(text.strip()) > 50 else "File gần như không có chữ (có thể là PDF dạng ảnh scan), tra cứu sẽ không có kết quả."
    return dict(id=gid, n_chars=len(text), warning=warn)


@app.get("/api/guidelines/{gid}")
def guideline_detail(gid: int, u=Depends(user)):
    g = store.get_guideline(gid)
    if not g:
        raise HTTPException(404, "Không có guideline này.")
    secs = G.sections(g["text"])
    try:
        rules, warn = G.parse_rules(g["rules"] or "")
    except ValueError as e:
        rules, warn = {}, [str(e)]
    return dict(id=g["id"], name=g["name"], file_name=g["file_name"], rules=g["rules"] or "", rules_obj=rules, warnings=warn,
                sections=[dict(muc=s["muc"], title=s["title"], body=s["body"][:4000]) for s in secs],
                tasks=next((x["tasks"] for x in store.list_guidelines() if x["id"] == gid), []), tool_classes=G.TOOL_CLASSES)


@app.get("/api/guidelines/{gid}/file")
def guideline_file(gid: int, u=Depends(user)):
    g = store.get_guideline(gid)
    if not g or not os.path.exists(g["file_path"] or ""):
        raise HTTPException(404, "Không có file.")
    return FileResponse(g["file_path"], filename=g["file_name"],
                        content_disposition_type="inline" if g["file_name"].lower().endswith(".pdf") else "attachment")


@app.get("/api/guidelines/{gid}/search")
def guideline_search(gid: int, q: str, u=Depends(user)):
    g = store.get_guideline(gid)
    if not g:
        raise HTTPException(404, "Không có guideline này.")
    return G.find_related(g["text"], [w for w in q.split(",") if w.strip()] or [q], limit=8)


@app.put("/api/guidelines/{gid}/rules")
def save_rules(gid: int, body: dict, u=Depends(need("qc"))):
    """Nhan YAML ('rules') hoac doi tuong tu trinh soan dang bang ('rules_obj')."""
    if body.get("rules_obj") is not None:
        txt = G.rules_to_yaml(body["rules_obj"])
    else:
        txt = body.get("rules", "")
    rules, warn = G.parse_rules(txt)            # sai cu phap -> ValueError -> 400
    store.update_guideline(gid, rules=txt)
    return dict(warnings=warn, rules=txt, rules_obj=rules)


@app.post("/api/guidelines/{gid}/template")
def rules_template(gid: int, body: dict, u=Depends(need("qc"))):
    tid, jid = num(body.get("task_id")), num(body.get("job_id"))
    cv, c = cvat_client(num(body.get("connection_id")))
    if not tid and jid:
        tid = cv.job(jid)["task_id"]
    if not tid:
        tid = env_config()["task_id"]
    if not tid:
        raise HTTPException(400, "Cần số task (hoặc số job) để lấy danh sách nhãn.")
    labels = []
    try:
        labels = cv.get("/api/labels", task_id=tid, page_size=500).json()["results"]
    except RuntimeError:                        # tai khoan khong co quyen xem task -> lay nhan qua job cua task do
        pass
    if not labels:
        try:
            j = next((x for x in cv.get("/api/jobs", task_id=tid, page_size=1).json().get("results", [])), None)
            jid = jid or (j or {}).get("id")
        except RuntimeError:
            pass
        if jid:
            labels = cv.get("/api/labels", job_id=jid, page_size=500).json()["results"]
    if not labels:
        raise HTTPException(400, f"Task {tid} không có nhãn nào (hoặc tài khoản không xem được).")
    tool2job, _, _ = R.build_label_map([lb["name"] for lb in labels])
    guess = {j: c2 for c2, j in tool2job.items() if j and c2 != "GreenSM"}
    guess.update({j: "GreenSM" for c2, j in tool2job.items() if j and c2 == "GreenSM" and j not in guess})
    txt = G.template_from_labels(labels, guess)
    rules, _ = G.parse_rules(txt)
    attrs = {lb["name"]: [a["name"] for a in lb.get("attributes", [])] for lb in labels}
    return dict(rules=txt, rules_obj=rules, attributes=attrs, task_id=tid)


@app.post("/api/guidelines/{gid}/tasks")
def assign_task(gid: int, body: dict, u=Depends(need("qc"))):
    tid = num(body.get("task_id"))
    if not tid:
        raise HTTPException(400, "Cần số task.")
    store.set_task_guideline(tid, gid if body.get("assign", True) else None)
    return {}


@app.delete("/api/guidelines/{gid}")
def delete_guideline(gid: int, u=Depends(need("qc"))):
    g = store.get_guideline(gid)
    if g and g.get("file_path") and os.path.exists(g["file_path"]):
        os.remove(g["file_path"])
    store.del_guideline(gid)
    return {}


# ------------------------------------------------------------------ nguoi dung (admin)
@app.get("/api/users")
def list_users(u=Depends(need("admin"))):
    return store.users()


@app.post("/api/users")
def save_user(body: dict, u=Depends(need("admin"))):
    name = body.get("username", "").strip()
    if not name or not name.replace("_", "").replace(".", "").isalnum():
        raise HTTPException(400, "Tên tài khoản chỉ gồm chữ, số, dấu _ hoặc .")
    if body.get("role") not in ROLES:
        raise HTTPException(400, "Vai trò phải là labeler, qc hoặc admin.")
    if body.get("password") and len(body["password"]) < 6:
        raise HTTPException(400, "Mật khẩu cần ít nhất 6 ký tự.")
    store.set_user(name, pw=body.get("password") or None, role=body["role"])
    return {}


@app.delete("/api/users/{name}")
def delete_user(name: str, u=Depends(need("admin"))):
    if name == u["username"]:
        raise HTTPException(400, "Không tự xoá tài khoản đang đăng nhập.")
    store.del_user(name)
    return {}


# ------------------------------------------------------------------ webhook CVAT
@app.post("/api/webhook/cvat")
async def cvat_webhook(request: Request, key: str = ""):
    """CVAT goi khi co su kien. Job chuyen sang 'completed' -> tu xep 1 lan review vao hang doi.
    Xac thuc: header X-Signature-256 (CVAT ky bang secret) hoac ?key=<secret> tren URL."""
    s = store.get_settings()
    if not s["webhook_enabled"]:
        raise HTTPException(403, "Webhook đang tắt (bật trong Cài đặt).")
    raw = await request.body()
    sig = request.headers.get("X-Signature-256", "")
    good = "sha256=" + hmac.new(s["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest()
    if not ((sig and hmac.compare_digest(sig, good)) or (key and hmac.compare_digest(key, s["webhook_secret"]))):
        raise HTTPException(401, "Sai chữ ký webhook.")
    data = json.loads(raw or b"{}")
    ev = data.get("event", "")
    if ev == "ping":
        return dict(ok=True, pong=True)
    job = data.get("job") or {}
    before = data.get("before_update") or {}
    if ev != "update:job" or job.get("state") != "completed" or before.get("state") == "completed":
        return dict(ok=True, skipped=ev or "khong_ro")
    if job.get("dimension") == "3d":
        return dict(ok=True, skipped="job_3d")
    tid = job.get("task_id")
    params = dict(mode=s["default_mode"], rider=True, max_frames=None, auto_push=bool(s["webhook_auto_push"]), push_unsure=False)
    rid = store.new_run(job["id"], tid, "webhook", params, store.task_guideline(tid), s["webhook_connection_id"] or None, source="webhook")
    worker.submit(rid)
    return dict(ok=True, run_id=rid)


# ------------------------------------------------------------------ giao dien
class NoCacheStatic(StaticFiles):
    """Trinh duyet luon hoi lai may chu (304 neu file khong doi) -> sua giao dien xong nguoi dung thay ngay, khong can Ctrl+F5."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=os.path.join(HERE, "static"), html=True), name="static")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="cho may khac cung mang vao")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    if args.lan:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            print(f"May khac cung mang vao: http://{s.getsockname()[0]}:{args.port}", flush=True)
        except OSError:
            pass
    print(f"Mo trinh duyet: http://localhost:{args.port}", flush=True)
    import uvicorn
    uvicorn.run(app, host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
