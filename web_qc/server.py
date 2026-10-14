"""
server.py — Web QC nhan 2D (ban day du): dang nhap, hang doi review, lich su, guideline, cai dat.
Nguyen tac nhu review_core: chi ghi Issue len CVAT, KHONG sua nhan.

  web_qc.bat                 -> http://localhost:8000 (chi may nay)
  web_qc.bat --lan           -> may khac cung mang vao http://<ip may nay>:8000
"""
import argparse
import os
import secrets
import shutil
import socket
import sys
import time

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
from worker import Worker, cvat_config

UPLOADS = os.path.join(store.DATA, "uploads")
GUIDE_DIR = os.path.join(store.DATA, "guidelines")
for d in (UPLOADS, GUIDE_DIR):
    os.makedirs(d, exist_ok=True)


def secret_key():
    p = os.path.join(store.DATA, "secret.key")
    if not os.path.exists(p):
        open(p, "w").write(secrets.token_hex(32))
    return open(p).read().strip()


app = FastAPI(title="Web QC nhãn 2D", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=secret_key(), max_age=14 * 24 * 3600, same_site="lax")
worker = Worker()
ROLES = {"labeler": 0, "qc": 1, "admin": 2}


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
    return int(v) if str(v or "").strip().isdigit() else None


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


# ------------------------------------------------------------------ cau hinh
@app.get("/api/config")
def config(u=Depends(user)):
    c = cvat_config()
    return dict(cvat_url=c["url"], task_id=c["task_id"], job_id=c["job_id"], has_token=bool(c["token"]),
                device=R.ToolRunner.device(), user=u, guideline_for_task=store.task_guideline(c["task_id"]))


@app.get("/api/cvat/test")
def cvat_test(u=Depends(need("qc"))):
    c = cvat_config()
    cv = R.Cvat(c["url"], c["token"])
    info = dict(ok=True, username=cv.user.get("username"))
    if c["job_id"]:
        j = cv.job(c["job_id"])
        info.update(job_id=c["job_id"], job_task=j["task_id"], job_state=j.get("state"), job_stage=j.get("stage"),
                    task_match=(c["task_id"] in (None, j["task_id"])))
    return info


# ------------------------------------------------------------------ review
@app.post("/api/runs")
def create_run(job_id: str = Form(""), task_id: str = Form(""), guideline_id: str = Form(""), mode: str = Form("chinh_xac"),
               rider: str = Form("1"), max_frames: str = Form(""), auto_push: str = Form("0"), push_unsure: str = Form("0"),
               file: UploadFile | None = File(None), u=Depends(user)):
    jid, tid = num(job_id), num(task_id)
    if not jid and not (file and file.filename):
        raise HTTPException(400, "Cần số job, hoặc tải lên file export.")
    if jid and not cvat_config()["token"]:
        raise HTTPException(400, "Máy chủ chưa có CVAT_TOKEN trong file .env.")
    gid = num(guideline_id) or store.task_guideline(tid)
    params = dict(mode="nhanh" if mode == "nhanh" else "chinh_xac", rider=rider == "1", max_frames=num(max_frames),
                  auto_push=auto_push == "1", push_unsure=push_unsure == "1")
    run_id = store.new_run(jid, tid, u["username"], params, gid)
    if file and file.filename:
        if not file.filename.lower().endswith(".zip"):
            raise HTTPException(400, "File export phải là .zip (CVAT for images 1.1 / COCO / YOLO).")
        path = os.path.join(UPLOADS, f"run{run_id}.zip")
        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        params["file"] = path
        store.update_run(run_id, params=params)
    worker.submit(run_id)
    return dict(id=run_id)


@app.get("/api/runs")
def runs(job_id: str = "", u=Depends(user)):
    out = store.list_runs(job_id=num(job_id))
    for r in out:
        r["position"] = worker.position(r["id"])
        r.pop("out_dir", None)
        if r.get("params"):
            r["params"].pop("file", None)
    return out


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int, u=Depends(user)):
    r = store.get_run(run_id)
    if not r:
        raise HTTPException(404, "Không có lần review này.")
    r["position"] = worker.position(run_id)
    r["running_now"] = worker.current
    r["log"] = worker.log_tail(run_id)
    r["findings"], r["frames"], r["guideline_refs"] = [], [], {}
    if r["status"] == "xong":
        rv = worker.review_obj(run_id)
        if rv is not None:
            pv_of = {}
            for k, (n, base, nbox, pv, finds) in enumerate(rv.frames):
                fn = os.path.basename(pv)
                r["frames"].append(dict(frame=n, name=base, preview=f"/api/runs/{run_id}/preview/{fn}", n=len(finds)))
                pv_of[(n, base)] = fn
            for i, f in enumerate(rv.findings):
                r["findings"].append(dict(id=i, frame=f["frame"], name=f["name"], kind=f["kind"],
                                          kind_vi=R.KIND_VI.get(f["kind"], f["kind"]), sure=f["sure"], label=f["label"],
                                          box=[round(v) for v in f["box"]], msg=f["msg"], ref=f.get("ref"),
                                          tang=f.get("tang", 2), preview=pv_of.get((f["frame"], f["name"]))))
            g = store.get_guideline(r["guideline_id"])
            if g:
                rules, _ = G.parse_rules(g["rules"]) if g.get("rules") else ({}, [])
                for lb in sorted({f["label"] for f in rv.findings}):
                    r["guideline_refs"][lb] = G.find_related(g["text"], G.words_for(rules, lb))
                r["guideline_name"] = g["name"]
            r["skipped_labels"] = rv.skipped_labels
    params = r.get("params") or {}
    params.pop("file", None)
    r.pop("out_dir", None)
    return r


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


@app.get("/api/runs/{run_id}/report.csv")
def report(run_id: int, u=Depends(user)):
    p = os.path.join(_run_dir(run_id), "ket_qua_review.csv")
    return FileResponse(p, filename=f"review_run{run_id}.csv")


@app.post("/api/runs/{run_id}/push")
def push(run_id: int, body: dict, u=Depends(user)):
    ids = [int(i) for i in body.get("ids", [])]
    if not ids:
        raise HTTPException(400, "Chưa chọn ghi chú nào để đẩy.")
    return worker.push(run_id, ids, replace_old=bool(body.get("replace_old", True)))


# ------------------------------------------------------------------ guideline
@app.get("/api/guidelines")
def guidelines(u=Depends(user)):
    return store.list_guidelines()


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
    warn = "" if len(text.strip()) > 50 else "File gần như không có chữ (có thể là PDF dạng ảnh scan) — tra cứu sẽ không có kết quả."
    return dict(id=gid, n_chars=len(text), warning=warn)


@app.get("/api/guidelines/{gid}")
def guideline_detail(gid: int, u=Depends(user)):
    g = store.get_guideline(gid)
    if not g:
        raise HTTPException(404, "Không có guideline này.")
    secs = G.sections(g["text"])
    return dict(id=g["id"], name=g["name"], file_name=g["file_name"], rules=g["rules"] or "",
                sections=[dict(muc=s["muc"], title=s["title"], body=s["body"][:4000]) for s in secs],
                tasks=next((x["tasks"] for x in store.list_guidelines() if x["id"] == gid), []))


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
    txt = body.get("rules", "")
    _, warn = G.parse_rules(txt)            # sai cu phap -> ValueError -> 400
    store.update_guideline(gid, rules=txt)
    return dict(warnings=warn)


@app.post("/api/guidelines/{gid}/template")
def rules_template(gid: int, body: dict, u=Depends(need("qc"))):
    c = cvat_config()
    tid = num(body.get("task_id")) or c["task_id"]
    if not tid:
        raise HTTPException(400, "Cần số task để lấy danh sách nhãn.")
    cv = R.Cvat(c["url"], c["token"])
    labels = []
    try:
        labels = cv.get("/api/labels", task_id=tid, page_size=500).json()["results"]
    except RuntimeError:                        # tai khoan khong co quyen xem task -> lay nhan qua job cua task do
        pass
    jid = num(body.get("job_id")) or c["job_id"]
    if not labels and jid and cv.job(jid)["task_id"] == tid:
        labels = cv.get("/api/labels", job_id=jid, page_size=500).json()["results"]
    if not labels:
        raise HTTPException(400, f"Task {tid} không có nhãn nào (hoặc nhãn nằm ở project).")
    tool2job, _, _ = R.build_label_map([lb["name"] for lb in labels])
    guess = {j: c2 for c2, j in tool2job.items() if j and c2 != "GreenSM"}
    guess.update({j: "GreenSM" for c2, j in tool2job.items() if j and c2 == "GreenSM" and j not in guess})
    return dict(rules=G.template_from_labels(labels, guess))


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
